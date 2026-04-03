"""
User router — browse workflows, chat with agents, manage sessions.

All endpoints require user role (user or admin).
The chat endpoint is the main interaction point — it triggers
the full agent pipeline through ChatService.
"""

from fastapi import APIRouter, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.dependencies import (
    get_cache_repo,
    get_current_user,
    get_mcp_manager,
    get_mongo_db,
    get_vector_repo,
)
from app.core.security import TokenPayload
from app.core.mcp_client import MCPClientManager
from app.repositories.cache_repo import CacheRepository
from app.repositories.chat_repo import ChatRepository
from app.repositories.config_repo import IngestionConfigRepository
from app.repositories.vector_repo import VectorRepository
from app.repositories.workflow_repo import WorkflowRepository
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ChatSessionDetailResponse,
    ChatSessionListResponse,
)
from app.schemas.workflow import WorkflowListResponse
from app.services.agents.orchestrator import AgentOrchestrator
from app.services.chat_service import ChatService
from app.services.workflow_service import WorkflowService

router = APIRouter()


# ──────────────────────────────────────────────
# Dependencies
# ──────────────────────────────────────────────


async def _get_workflow_service(
    db: AsyncIOMotorDatabase = Depends(get_mongo_db),
) -> WorkflowService:
    return WorkflowService(
        workflow_repo=WorkflowRepository(db),
        config_repo=IngestionConfigRepository(db),
    )


async def _get_chat_service(
    db: AsyncIOMotorDatabase = Depends(get_mongo_db),
    vector_repo: VectorRepository = Depends(get_vector_repo),
    cache_repo: CacheRepository = Depends(get_cache_repo),
    mcp_manager: MCPClientManager = Depends(get_mcp_manager),
) -> ChatService:
    """
    Build the full ChatService with all its dependencies:
    ChatService → (ChatRepo, WorkflowRepo, ConfigRepo, CacheRepo, Orchestrator)
    Orchestrator → VectorRepository → (LlamaIndex, Qdrant)
    """
    return ChatService(
        chat_repo=ChatRepository(db),
        workflow_repo=WorkflowRepository(db),
        config_repo=IngestionConfigRepository(db),
        cache_repo=cache_repo,
        orchestrator=AgentOrchestrator(vector_repo, mcp_manager=mcp_manager),
    )


# ══════════════════════════════════════════════
# WORKFLOW BROWSING
# ══════════════════════════════════════════════


@router.get(
    "/workflows",
    response_model=WorkflowListResponse,
    summary="List available workflows",
)
async def list_workflows(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: TokenPayload = Depends(get_current_user),
    workflow_service: WorkflowService = Depends(_get_workflow_service),
):
    """
    List all active workflows available for the user to chat with.
    Only ACTIVE workflows with COMPLETED ingestion configs are shown.
    """
    return await workflow_service.list_active_workflows(
        page=page, page_size=page_size
    )


# ══════════════════════════════════════════════
# CHAT
# ══════════════════════════════════════════════


@router.post(
    "/workflows/{workflow_id}/chat",
    response_model=ChatResponse,
    summary="Send a message to the agent pipeline",
)
async def chat(
    workflow_id: str,
    request: ChatRequest,
    current_user: TokenPayload = Depends(get_current_user),
    chat_service: ChatService = Depends(_get_chat_service),
):
    """
    Send a natural language question to the agent pipeline.

    The full flow:
    1. Check semantic cache (LangCache)
    2. On miss → Retrieval Agent (LlamaIndex → SQL → execute)
    3. If low confidence → Web Search Agent (conditional)
    4. Guardrail Agent (SQL safety + PII + hallucination check)
    5. Cache result + store in conversation history

    Include session_id for multi-turn conversations.
    Omit session_id to start a new session.

    Response includes:
    - Generated SQL query
    - Tables referenced
    - Confidence score
    - Agent execution trace
    - Cache hit indicator
    """
    return await chat_service.process_message(
        workflow_id=workflow_id,
        request=request,
        user_id=current_user.sub,
    )


# ══════════════════════════════════════════════
# CHAT SESSIONS
# ══════════════════════════════════════════════


@router.get(
    "/sessions",
    response_model=ChatSessionListResponse,
    summary="List chat sessions",
)
async def list_sessions(
    workflow_id: str | None = Query(None, description="Filter by workflow"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: TokenPayload = Depends(get_current_user),
    chat_service: ChatService = Depends(_get_chat_service),
):
    """
    List the user's chat sessions, sorted by most recent.
    Optionally filter by workflow_id.
    """
    return await chat_service.list_sessions(
        user_id=current_user.sub,
        workflow_id=workflow_id,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/sessions/{session_id}",
    response_model=ChatSessionDetailResponse,
    summary="Load full chat session",
)
async def get_session(
    session_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    chat_service: ChatService = Depends(_get_chat_service),
):
    """
    Load a complete chat session with all messages and metadata.
    Includes SQL queries, agent traces, and confidence scores
    for each assistant response.
    """
    return await chat_service.get_session(
        session_id=session_id,
        user_id=current_user.sub,
    )