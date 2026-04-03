"""
Chat request/response schemas.

The chat flow:
1. User sends a message via ChatRequest
2. Backend runs the agent pipeline
3. Returns ChatResponse with the answer + rich metadata
4. Frontend can display agent trace, SQL generated, confidence, etc.
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.models.chat_session import MessageRole


# ──────────────────────────────────────────────
# Requests
# ──────────────────────────────────────────────


class ChatRequest(BaseModel):
    """User sends a message to a workflow's agent pipeline."""

    message: str = Field(
        ..., min_length=1, max_length=4096,
        examples=["What tables reference the Orders table?"]
    )
    session_id: Optional[str] = Field(
        None,
        description="Existing session ID for multi-turn. Omit to start a new session."
    )


class NewSessionRequest(BaseModel):
    """Explicitly create a new chat session."""

    workflow_id: str
    title: Optional[str] = None


# ──────────────────────────────────────────────
# Responses
# ──────────────────────────────────────────────


class AgentTraceResponse(BaseModel):
    """Trace of a single agent's execution — exposed to the frontend."""

    agent_type: str
    status: str  # success | skipped | failed
    duration_ms: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatMessageResponse(BaseModel):
    """Single message in the chat history."""

    role: MessageRole
    content: str
    timestamp: datetime

    # Only present on assistant messages
    confidence_score: Optional[float] = None
    cached: bool = False
    latency_ms: Optional[float] = None
    sql_query: Optional[str] = None
    sql_result_preview: Optional[str] = None
    tables_referenced: list[str] = Field(default_factory=list)
    agent_trace: list[AgentTraceResponse] = Field(default_factory=list)

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class ChatResponse(BaseModel):
    """Response returned after processing a user's chat message."""

    session_id: str
    message: ChatMessageResponse

    # Session-level info
    workflow_id: str
    message_count: int


class ChatSessionListItem(BaseModel):
    """Lightweight session info for the sidebar list."""

    id: str
    workflow_id: str
    title: str
    message_count: int
    last_message_preview: str = ""
    created_at: datetime
    updated_at: datetime


class ChatSessionListResponse(BaseModel):
    """Paginated list of user's chat sessions."""

    items: list[ChatSessionListItem]
    total: int
    page: int
    page_size: int


class ChatSessionDetailResponse(BaseModel):
    """Full chat session with all messages (for loading a conversation)."""

    id: str
    workflow_id: str
    title: str
    messages: list[ChatMessageResponse]
    message_count: int
    is_active: bool
    created_at: datetime
    updated_at: datetime