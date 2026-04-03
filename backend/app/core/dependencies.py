"""
FastAPI dependency injection providers.

All external client connections are managed here as singletons initialized
during app lifespan, then injected into routes via Depends().

Architecture:
- MongoDB (Motor) → async document store
- Redis (aioredis) → async cache layer
- Qdrant → async vector store (managed by LlamaIndex via VectorRepository)
- Auth → JWT token extraction + role enforcement
- Repository factories → VectorRepository, CacheRepository

LlamaIndex integration (ingestion + retrieval) lives entirely in
VectorRepository — no LlamaIndex code in this module.
"""

from typing import Optional

import redis.asyncio as aioredis
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from qdrant_client import AsyncQdrantClient

from app.core.config import Settings, get_settings
from app.core.exceptions import (
    AuthenticationError,
    InsufficientPermissionsError,
    InvalidTokenError,
)
from app.core.logging import get_logger
from app.core.security import TokenPayload, UserRole, decode_access_token

logger = get_logger(__name__)

# ──────────────────────────────────────────────
# Client Singletons (initialized in lifespan)
# ──────────────────────────────────────────────

_mongo_client: Optional[AsyncIOMotorClient] = None
_mongo_db: Optional[AsyncIOMotorDatabase] = None
_redis_client: Optional[aioredis.Redis] = None
_qdrant_client: Optional[AsyncQdrantClient] = None

# Repository singletons (depend on clients above)
_vector_repo = None
_cache_repo = None


# ──────────────────────────────────────────────
# Lifecycle Management
# ──────────────────────────────────────────────


async def init_clients(settings: Settings) -> None:
    """
    Initialize all external clients. Called once during app startup.
    Separated from Depends() so we control lifecycle explicitly.
    """
    global _mongo_client, _mongo_db, _redis_client, _qdrant_client
    global _vector_repo, _cache_repo

    # MongoDB
    try:
        _mongo_client = AsyncIOMotorClient(
            settings.MONGO_URI,
            maxPoolSize=settings.MONGO_MAX_POOL_SIZE,
            minPoolSize=settings.MONGO_MIN_POOL_SIZE,
            serverSelectionTimeoutMS=5000,  # 🔥 important for fast failure
        )

        # 🔥 Force connection (health check)
        await _mongo_client.admin.command("ping")

        _mongo_db = _mongo_client[settings.MONGO_DB_NAME]

        logger.info("mongodb.connected", database=settings.MONGO_DB_NAME)

    except Exception as e:
        logger.error(
            "mongodb.connection_failed",
            error=str(e),
            uri=settings.MONGO_URI,
        )
        _mongo_client = None
        _mongo_db = None

    # Redis
    try:
        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            max_connections=settings.REDIS_MAX_CONNECTIONS,
            decode_responses=True,
        )

        # 🔥 Health check
        await _redis_client.ping()

        logger.info("redis.connected", url=settings.REDIS_URL)

    except Exception as e:
        logger.error("redis.connection_failed", error=str(e))
        _redis_client = None

    # Qdrant
    if settings.QDRANT_URI:
        try:
            client = AsyncQdrantClient(
                url=settings.QDRANT_URI,
                api_key=settings.QDRANT_API_KEY,
                prefer_grpc=False,
                check_compatibility=False,
            )

            # 🔥 Ping (health check)
            await client.get_collections()

            _qdrant_client = client

            logger.info("qdrant.connected", host=settings.QDRANT_URI[0:15]+"....",)  # strip protocol and port for cleaner logs

        except Exception as e:
            logger.error("qdrant.connection_failed", error=str(e))
            _qdrant_client = None
    else:   
        _qdrant_client = AsyncQdrantClient(
            host=settings.QDRANT_HOST,
            port=settings.QDRANT_PORT,
            api_key=settings.QDRANT_API_KEY,
            grpc_port=settings.QDRANT_GRPC_PORT,
            prefer_grpc=settings.QDRANT_PREFER_GRPC,
        )
        logger.info("qdrant.connected", host=settings.QDRANT_HOST)

    # Initialize repositories that need singleton clients
    from app.repositories.vector_repo import VectorRepository
    from app.repositories.cache_repo import CacheRepository

    _vector_repo = VectorRepository(_qdrant_client, settings)
    _cache_repo = CacheRepository(_redis_client, settings)

    # MCP tool servers (web search, etc.)
    from app.core.mcp_client import init_mcp_manager
    init_mcp_manager(settings)

    # Create MongoDB indexes
    await _ensure_indexes(_mongo_db)


async def shutdown_clients() -> None:
    """Gracefully close all connections during app shutdown."""
    global _mongo_client, _redis_client, _qdrant_client
    global _vector_repo, _cache_repo

    # Close LlamaIndex's sync Qdrant client if it was created
    if _vector_repo:
        _vector_repo.close_sync_client()

    if _qdrant_client:
        await _qdrant_client.close()
        logger.info("qdrant.disconnected")

    if _redis_client:
        await _redis_client.aclose()
        logger.info("redis.disconnected")

    if _mongo_client:
        _mongo_client.close()
        logger.info("mongodb.disconnected")

    _vector_repo = None
    _cache_repo = None


async def _ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    """Create MongoDB indexes for performance-critical queries."""
    await db.users.create_index("email", unique=True)
    await db.chat_sessions.create_index([("user_id", 1), ("updated_at", -1)])
    await db.ingestion_configs.create_index("created_by")
    await db.workflows.create_index([("is_active", 1), ("created_by", 1)])
    logger.info("mongodb.indexes_ensured")


# ──────────────────────────────────────────────
# Dependency Providers — Raw Clients
# ──────────────────────────────────────────────


async def get_mongo_db() -> AsyncIOMotorDatabase:
    """Inject the MongoDB database instance."""
    if _mongo_db is None:
        raise RuntimeError("MongoDB not initialized. Check app lifespan.")
    return _mongo_db


async def get_redis() -> aioredis.Redis:
    """Inject the Redis client."""
    if _redis_client is None:
        raise RuntimeError("Redis not initialized. Check app lifespan.")
    return _redis_client


async def get_qdrant() -> AsyncQdrantClient:
    """Inject the Qdrant async client."""
    if _qdrant_client is None:
        raise RuntimeError("Qdrant not initialized. Check app lifespan.")
    return _qdrant_client

async def get_mcp_manager():
    """
    Inject the MCP client manager for tool invocations (web search, etc.).
    """
    from app.core.mcp_client import get_mcp_manager as _get_mgr
    return _get_mgr()


# ──────────────────────────────────────────────
# Dependency Providers — Repositories
# ──────────────────────────────────────────────


async def get_vector_repo():
    """
    Inject the VectorRepository singleton.

    This is the single entry point for all LlamaIndex operations:
    - ingest_sql_schema()   → ingestion pipeline
    - build_query_engine()  → retrieval engine construction
    - execute_query()       → NL → SQL → execute → NL response
    """
    if _vector_repo is None:
        raise RuntimeError("VectorRepository not initialized. Check app lifespan.")
    return _vector_repo


async def get_cache_repo():
    """
    Inject the CacheRepository singleton (semantic cache via LangCache).
    """
    if _cache_repo is None:
        raise RuntimeError("CacheRepository not initialized. Check app lifespan.")
    return _cache_repo


# ──────────────────────────────────────────────
# Auth Dependencies
# ──────────────────────────────────────────────

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> TokenPayload:
    """
    Extract and validate JWT from Authorization header.
    Returns the decoded token payload with user_id and role.
    """
    if credentials is None:
        raise AuthenticationError(detail="Authorization header missing")

    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise InvalidTokenError()

    return payload


def require_role(required_role: UserRole):
    """
    Factory that returns a dependency enforcing a specific role.

    Usage:
        @router.post("/admin/ingest", dependencies=[Depends(require_role(UserRole.ADMIN))])
    """

    async def role_checker(
        current_user: TokenPayload = Depends(get_current_user),
    ) -> TokenPayload:
        if current_user.role != required_role:
            raise InsufficientPermissionsError(
                detail=f"Role '{required_role}' required, you have '{current_user.role}'"
            )
        return current_user

    return role_checker