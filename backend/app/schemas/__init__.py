"""
Pydantic schemas for API request/response validation.

Convention:
- *Request  = incoming data from client
- *Response = outgoing data to client
- Models (in app/models/) = MongoDB document shapes
"""

from app.schemas.auth import (
    AuthResponse,
    LoginRequest,
    RefreshTokenRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.schemas.ingestion import (
    CreateIngestionRequest,
    IngestionConfigResponse,
    IngestionListResponse,
    TestConnectionRequest,
    TestConnectionResponse,
)
from app.schemas.workflow import (
    CreateWorkflowRequest,
    UpdateWorkflowRequest,
    WorkflowListResponse,
    WorkflowResponse,
)
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ChatSessionDetailResponse,
    ChatSessionListResponse,
    NewSessionRequest,
)

__all__ = [
    "AuthResponse", "LoginRequest", "RefreshTokenRequest",
    "RegisterRequest", "TokenResponse", "UserResponse",
    "CreateIngestionRequest", "IngestionConfigResponse",
    "IngestionListResponse", "TestConnectionRequest", "TestConnectionResponse",
    "CreateWorkflowRequest", "UpdateWorkflowRequest",
    "WorkflowListResponse", "WorkflowResponse",
    "ChatRequest", "ChatResponse", "ChatSessionDetailResponse",
    "ChatSessionListResponse", "NewSessionRequest",
]