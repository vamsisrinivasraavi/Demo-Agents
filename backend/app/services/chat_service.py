"""
Chat service — the main entry point for user queries.

Orchestrates the complete chat lifecycle:
1. Load or create chat session
2. Load workflow config + ingestion config
3. Check semantic cache (LangCache via Redis)
4. On cache miss → run agent orchestrator pipeline
5. Store result in cache (if enabled)
6. Append user + assistant messages to session
7. Return structured response with metadata

This is the only service that touches ChatRepository, CacheRepository,
and AgentOrchestrator. It's the glue between the user-facing API
and the agent system.
"""

import time
from typing import Optional

from app.core.encryption import decrypt_value
from app.core.exceptions import NotFoundError, WorkflowExecutionError
from app.core.logging import get_logger, log_duration
from app.models.chat_session import (
    AgentTraceEntry,
    ChatMessage,
    MessageMetadata,
    MessageRole,
)
from app.models.ingestion_config import IngestionStatus
from app.repositories.cache_repo import CacheRepository
from app.repositories.chat_repo import ChatRepository
from app.repositories.config_repo import IngestionConfigRepository
from app.repositories.workflow_repo import WorkflowRepository
from app.schemas.chat import (
    AgentTraceResponse,
    ChatMessageResponse,
    ChatRequest,
    ChatResponse,
    ChatSessionDetailResponse,
    ChatSessionListItem,
    ChatSessionListResponse,
)
from app.services.agents.orchestrator import AgentOrchestrator

logger = get_logger(__name__)


class ChatService:
    def __init__(
        self,
        chat_repo: ChatRepository,
        workflow_repo: WorkflowRepository,
        config_repo: IngestionConfigRepository,
        cache_repo: CacheRepository,
        orchestrator: AgentOrchestrator,
    ):
        self._chat_repo = chat_repo
        self._workflow_repo = workflow_repo
        self._config_repo = config_repo
        self._cache_repo = cache_repo
        self._orchestrator = orchestrator

    # ──────────────────────────────────────────────
    # Core Chat Flow
    # ──────────────────────────────────────────────

    @log_duration("chat.process_message")
    async def process_message(
        self,
        workflow_id: str,
        request: ChatRequest,
        user_id: str,
    ) -> ChatResponse:
        """
        Process a user message through the full pipeline.

        This is the main entry point called by the user chat API.
        """
        start_time = time.perf_counter()

        # ── Step 1: Load workflow config ──
        workflow = await self._workflow_repo.find_by_id(workflow_id)
        if workflow is None or not workflow.get("is_active"):
            raise NotFoundError(detail=f"Workflow '{workflow_id}' not found or inactive")

        # ── Step 2: Load ingestion config ──
        ingestion_config_id = workflow.get("ingestion_config_id")
        ingestion_config = await self._config_repo.find_by_id(ingestion_config_id)
        if ingestion_config is None:
            raise NotFoundError(detail="Ingestion config not found for this workflow")
        if ingestion_config.get("status") != IngestionStatus.COMPLETED:
            raise WorkflowExecutionError(
                detail="Schema ingestion not completed for this workflow"
            )

        # ── Step 3: Get or create session ──
        session_id = request.session_id
        if session_id:
            session = await self._chat_repo.get_session_with_messages(session_id)
            if session is None:
                raise NotFoundError(detail=f"Chat session '{session_id}' not found")
        else:
            session_id = await self._chat_repo.create_session({
                "user_id": user_id,
                "workflow_id": workflow_id,
                "title": request.message[:50] + "..." if len(request.message) > 50 else request.message,
            })
            session = await self._chat_repo.get_session_with_messages(session_id)

        # ── Step 4: Build chat history for context ──
        feature_flags = workflow.get("feature_flags", {})
        max_history = feature_flags.get("max_history_messages", 20)

        existing_messages = session.get("messages", [])
        chat_history = self._format_chat_history(existing_messages, max_history)

        # ── Step 5: Check cache ──
        cached_response = None
        cache_enabled = feature_flags.get("enable_cache", False)

        if cache_enabled:
            cached = await self._cache_repo.get(
                workflow_id=workflow_id,
                query=request.message,
                agent_id="orchestrator",
            )
            if cached:
                cached_response = cached.get("response")
                logger.info("chat.cache_hit", workflow_id=workflow_id)

        # ── Step 6: Run orchestrator (on cache miss) ──
        if cached_response:
            response_text = cached_response
            sql_query = None
            tables_referenced = []
            agent_traces = []
            confidence = 1.0
            was_cached = True
        else:
            try:
                result = await self._orchestrator.execute(
                    query=request.message,
                    workflow_config=workflow,
                    ingestion_config=ingestion_config,
                    chat_history=chat_history,
                )
                response_text = result.response
                sql_query = result.sql_query
                tables_referenced = result.source_tables
                used_columns = result.retrieval_used_columns
                output_columns = result.retrieval_output_columns
                sql_result_preview = result.retrieval_sql_result_preview
                agent_traces = result.agent_traces
                confidence = result.confidence
                was_cached = False

                # Store in cache
                if cache_enabled and response_text:
                    cache_ttl = feature_flags.get("cache_ttl_seconds", 3600)
                    await self._cache_repo.set(
                        workflow_id=workflow_id,
                        query=request.message,
                        response=response_text,
                        agent_id="orchestrator",
                        ttl=cache_ttl,
                        metadata={
                            "sql_query": sql_query,
                            "tables": tables_referenced,
                            "used_columns": used_columns,
                            "output_columns": output_columns,
                            "sql_result_preview": sql_result_preview,
                        },
                    )

            except Exception as e:
                logger.error(
                    "chat.orchestrator_failed",
                    error=str(e),
                    workflow_id=workflow_id,
                )
                raise WorkflowExecutionError(
                    detail=f"Agent pipeline failed: {str(e)}"
                )

        # ── Step 7: Store messages in session ──
        total_latency = (time.perf_counter() - start_time) * 1000

        user_msg = ChatMessage(role=MessageRole.USER, content=request.message)

        assistant_metadata = MessageMetadata(
            agent_trace=[
                AgentTraceEntry(
                    agent_type=t.agent_type,
                    status=t.status,
                    duration_ms=t.duration_ms,
                    output_summary=t.output_summary,
                    metadata=t.metadata,
                )
                for t in agent_traces
            ],
            confidence_score=confidence,
            cached=was_cached,
            total_latency_ms=total_latency,
            model_used=workflow.get("model_settings", {}).get("model", ""),
            sql_query=sql_query,
            tables_referenced=tables_referenced,
        )

        assistant_msg = ChatMessage(
            role=MessageRole.ASSISTANT,
            content=response_text,
            metadata=assistant_metadata,
        )

        await self._chat_repo.append_messages(
            session_id,
            [user_msg.model_dump(), assistant_msg.model_dump()],
        )

        # ── Step 8: Build response ──
        updated_session = await self._chat_repo.get_session_with_messages(session_id)
        message_count = updated_session.get("message_count", 0) if updated_session else 0

        return ChatResponse(
            session_id=session_id,
            message=ChatMessageResponse(
                role=MessageRole.ASSISTANT,
                content=response_text,
                timestamp=assistant_msg.timestamp,
                confidence_score=confidence,
                cached=was_cached,
                latency_ms=total_latency,
                sql_query=sql_query,
                tables_referenced=tables_referenced,
                agent_trace=[
                    AgentTraceResponse(
                        agent_type=t.agent_type,
                        status=t.status,
                        duration_ms=t.duration_ms,
                        metadata=t.metadata,
                    )
                    for t in agent_traces
                ],
            ),
            workflow_id=workflow_id,
            message_count=message_count,
        )

    # ──────────────────────────────────────────────
    # Session Management
    # ──────────────────────────────────────────────

    async def list_sessions(
        self,
        user_id: str,
        workflow_id: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> ChatSessionListResponse:
        """List chat sessions for a user."""
        skip = (page - 1) * page_size
        docs = await self._chat_repo.find_user_sessions(
            user_id, workflow_id=workflow_id, skip=skip, limit=page_size
        )
        total = await self._chat_repo.count_user_sessions(user_id, workflow_id)

        items = []
        for doc in docs:
            items.append(ChatSessionListItem(
                id=doc["_id"],
                workflow_id=doc.get("workflow_id", ""),
                title=doc.get("title", "New Chat"),
                message_count=doc.get("message_count", 0),
                created_at=doc["created_at"],
                updated_at=doc["updated_at"],
            ))

        return ChatSessionListResponse(
            items=items, total=total, page=page, page_size=page_size
        )

    async def get_session(self, session_id: str, user_id: str) -> ChatSessionDetailResponse:
        """Load full session with all messages."""
        session = await self._chat_repo.get_session_with_messages(session_id)
        if session is None or session.get("user_id") != user_id:
            raise NotFoundError(detail="Chat session not found")

        messages = []
        for msg in session.get("messages", []):
            meta = msg.get("metadata") or {}
            messages.append(ChatMessageResponse(
                role=MessageRole(msg["role"]),
                content=msg["content"],
                timestamp=msg["timestamp"],
                confidence_score=meta.get("confidence_score"),
                cached=meta.get("cached", False),
                latency_ms=meta.get("total_latency_ms"),
                sql_query=meta.get("sql_query"),
                tables_referenced=meta.get("tables_referenced", []),
                agent_trace=[
                    AgentTraceResponse(
                        agent_type=t["agent_type"],
                        status=t["status"],
                        duration_ms=t.get("duration_ms", 0),
                        metadata=t.get("metadata", {}),
                    )
                    for t in meta.get("agent_trace", [])
                ],
            ))

        return ChatSessionDetailResponse(
            id=session["_id"],
            workflow_id=session["workflow_id"],
            title=session.get("title", ""),
            messages=messages,
            message_count=session.get("message_count", 0),
            is_active=session.get("is_active", True),
            created_at=session["created_at"],
            updated_at=session["updated_at"],
        )

    # ──────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────

    @staticmethod
    def _format_chat_history(
        messages: list[dict], max_messages: int
    ) -> list[dict[str, str]]:
        """Format stored messages into LLM-compatible chat history."""
        conv = [
            m for m in messages
            if m.get("role") in (MessageRole.USER, MessageRole.ASSISTANT)
        ]
        recent = conv[-max_messages:] if len(conv) > max_messages else conv
        return [{"role": m["role"], "content": m["content"]} for m in recent]