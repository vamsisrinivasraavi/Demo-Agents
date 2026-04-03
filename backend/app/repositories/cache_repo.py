"""
Semantic cache repository using LangCache (GPTCache) backed by Redis.

Unlike simple hash-key caching, LangCache uses embedding similarity to
match queries — so "What tables reference Orders?" and "Which tables
have FK constraints pointing to the Orders table?" hit the same cache entry.

Architecture:
- LangCache stores embeddings + cached responses in Redis
- All LangCache operations are synchronous → wrapped with run_in_executor
- Each (workflow_id, agent pipeline) gets its own cache namespace
- TTL is controlled per-workflow via feature_flags.cache_ttl_seconds
- A dedicated ThreadPoolExecutor caps parallelism to avoid thread explosion

Usage:
    cache_repo = CacheRepository(redis_client, settings)
    result = await cache_repo.get(workflow_id, query, agent_id="retrieval")
    if result is None:
        response = await run_pipeline(...)
        await cache_repo.set(workflow_id, query, response, agent_id="retrieval")
"""

import asyncio
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

import redis.asyncio as aioredis

from app.core.config import Settings, get_settings
from app.core.logging import get_logger, log_duration

logger = get_logger(__name__)

# Bounded thread pool for sync LangCache operations
_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="langcache")


class CacheRepository:
    """
    Semantic cache backed by Redis via LangCache.

    LangCache flow:
    1. Query → embedding (via OpenAI)
    2. Similarity search against cached embeddings in Redis
    3. If similarity > threshold → return cached response (HIT)
    4. If no match → return None (MISS), caller stores after pipeline runs
    """

    def __init__(
        self,
        redis_client: aioredis.Redis,
        settings: Optional[Settings] = None,
    ):
        self._redis = redis_client
        self._settings = settings or get_settings()
        self._lang_cache = None
        self._initialized = False

    def _ensure_lang_cache(self):
        """
        Lazy-initialize the LangCache instance.
        Done lazily because LangCache import + setup is heavy
        and not needed if caching is disabled in the workflow.
        """
        if self._initialized:
            return

        try:
            from langcache import LangCache

            # LangCache is sync, create instance
            self._lang_cache = LangCache(
                server_url=self._settings.LANG_CACHE_SERVICE_URL,
                cache_id=self._settings.LANG_CACHE_ID,
                api_key=self._settings.LANG_CACHE_API_KEY,
            )

            self._initialized = True
            logger.info("langcache.initialized")
        except ImportError:
            logger.warning(
                "langcache.not_installed",
                detail="LangCache not available — falling back to hash-based cache",
            )
            self._lang_cache = None
            self._initialized = True
        except Exception as e:
            logger.error("langcache.init_failed", error=str(e))
            self._lang_cache = None
            self._initialized = True

    # ──────────────────────────────────────────────
    # Prompt Building
    # ──────────────────────────────────────────────

    def _build_prompt(
        self,
        workflow_id: str,
        agent_id: str,
        query: str,
    ) -> str:
        """
        Build a cache lookup prompt that includes namespace context.
        The workflow_id + agent_id scope ensures different workflows
        don't cross-contaminate cache entries.
        """
        return f"[wf:{workflow_id}][agent:{agent_id}] {query}"

    # ──────────────────────────────────────────────
    # Sync LangCache Operations (run in executor)
    # ──────────────────────────────────────────────

    def _sync_lang_cache_get(self, prompt: str) -> Optional[str]:
        """Synchronous LangCache lookup — runs in thread pool."""
        if self._lang_cache is None:
            return None
        try:
            result = self._lang_cache.search(prompt)
            return result
        except Exception as e:
            logger.warning("langcache.get_error", error=str(e))
            return None

    def _sync_lang_cache_set(
        self,
        prompt: str,
        response: str,
        ttl: int,
    ) -> bool:
        """Synchronous LangCache store — runs in thread pool."""
        if self._lang_cache is None:
            return False
        try:
            self._lang_cache.set(prompt=prompt, response=response, ttl_millis=ttl*1000)
            return True
        except Exception as e:
            logger.warning("langcache.set_error", error=str(e))
            return False

    def _sync_lang_cache_invalidate(self, prompt: str) -> bool:
        """Synchronous LangCache invalidation — runs in thread pool."""
        if self._lang_cache is None:
            return False
        try:
            self._lang_cache.invalidate(prompt)
            return True
        except Exception as e:
            logger.warning("langcache.invalidate_error", error=str(e))
            return False

    # ──────────────────────────────────────────────
    # Async Public API
    # ──────────────────────────────────────────────

    @log_duration("cache.get")
    async def get(
        self,
        workflow_id: str,
        query: str,
        agent_id: str = "default",
    ) -> Optional[dict[str, Any]]:
        """
        Attempt to retrieve a cached response via semantic similarity.

        Returns:
            dict with 'response', 'cached_at', 'cache_key' if HIT
            None if MISS
        """
        self._ensure_lang_cache()

        if self._lang_cache:
            # Semantic cache path
            prompt = self._build_prompt(workflow_id, agent_id, query)
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                _executor,
                self._sync_lang_cache_get,
                prompt,
            )
            if result is not None:
                logger.info(
                    "cache.hit",
                    type="semantic",
                    workflow_id=workflow_id,
                    agent_id=agent_id,
                )
                try:
                    return json.loads(result)
                except (json.JSONDecodeError, TypeError):
                    return {"response": result, "cached_at": None, "cache_key": prompt}
        else:
            # Fallback: hash-based exact-match cache via plain Redis
            cache_key = self._hash_key(workflow_id, agent_id, query)
            raw = await self._redis.get(cache_key)
            if raw is not None:
                logger.info(
                    "cache.hit",
                    type="hash",
                    workflow_id=workflow_id,
                    agent_id=agent_id,
                )
                try:
                    return json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    return {"response": raw, "cached_at": None, "cache_key": cache_key}

        logger.debug(
            "cache.miss",
            workflow_id=workflow_id,
            agent_id=agent_id,
        )
        return None

    @log_duration("cache.set")
    async def set(
        self,
        workflow_id: str,
        query: str,
        response: str,
        agent_id: str = "default",
        ttl: Optional[int] = None,
        metadata: Optional[dict] = None,
    ) -> bool:
        """
        Store a response in the semantic cache.

        Args:
            workflow_id: Scopes the cache to a workflow
            query: The user's original query
            response: The generated response to cache
            agent_id: Further scopes by agent type
            ttl: Time-to-live in seconds (defaults to config)
            metadata: Optional metadata to store alongside
        """
        self._ensure_lang_cache()
        effective_ttl = ttl or self._settings.REDIS_DEFAULT_TTL

        cache_entry = json.dumps({
            "response": response,
            "cached_at": time.time(),
            "cache_key": self._build_prompt(workflow_id, agent_id, query),
            "workflow_id": workflow_id,
            "agent_id": agent_id,
            "metadata": metadata or {},
        })

        if self._lang_cache:
            prompt = self._build_prompt(workflow_id, agent_id, query)
            loop = asyncio.get_running_loop()
            success = await loop.run_in_executor(
                _executor,
                self._sync_lang_cache_set,
                prompt,
                cache_entry,
                effective_ttl,
            )
            if success:
                logger.info(
                    "cache.stored",
                    type="semantic",
                    workflow_id=workflow_id,
                    ttl=effective_ttl,
                )
            return success
        else:
            # Fallback: hash-based
            cache_key = self._hash_key(workflow_id, agent_id, query)
            await self._redis.setex(cache_key, effective_ttl, cache_entry)
            logger.info(
                "cache.stored",
                type="hash",
                workflow_id=workflow_id,
                ttl=effective_ttl,
            )
            return True

    async def invalidate(
        self,
        workflow_id: str,
        query: str,
        agent_id: str = "default",
    ) -> bool:
        """Invalidate a specific cache entry."""
        self._ensure_lang_cache()

        if self._lang_cache:
            prompt = self._build_prompt(workflow_id, agent_id, query)
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                _executor,
                self._sync_lang_cache_invalidate,
                prompt,
            )
        else:
            cache_key = self._hash_key(workflow_id, agent_id, query)
            result = await self._redis.delete(cache_key)
            return result > 0

    async def invalidate_workflow(self, workflow_id: str) -> int:
        """
        Invalidate ALL cache entries for a workflow.
        Only works with hash-based fallback (pattern scan).
        For LangCache, workflow re-ingestion should reset the collection.
        """
        pattern = f"schema_assistant:cache:{workflow_id}:*"
        deleted = 0
        async for key in self._redis.scan_iter(match=pattern, count=100):
            await self._redis.delete(key)
            deleted += 1
        logger.info("cache.workflow_invalidated", workflow_id=workflow_id, deleted=deleted)
        return deleted

    # ──────────────────────────────────────────────
    # Hash-Based Fallback Helpers
    # ──────────────────────────────────────────────

    @staticmethod
    def _hash_key(workflow_id: str, agent_id: str, query: str) -> str:
        """
        Generate a deterministic Redis key from workflow + agent + query.
        Used as fallback when LangCache is unavailable.
        """
        raw = f"{workflow_id}:{agent_id}:{query.strip().lower()}"
        query_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]
        return f"schema_assistant:cache:{workflow_id}:{agent_id}:{query_hash}"