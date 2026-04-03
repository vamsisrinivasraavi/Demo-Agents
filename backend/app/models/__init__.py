"""
Document models for MongoDB collections.

Each model maps to a MongoDB collection:
- UserDocument          → users
- IngestionConfigDocument → ingestion_configs
- WorkflowDocument      → workflows
- ChatSessionDocument   → chat_sessions
"""

from app.models.user import UserDocument
from app.models.ingestion_config import (
    IngestionConfigDocument,
    IngestionStatus,
    SchemaStats,
    SQLConnectionConfig,
)
from app.models.workflow import (
    AgentConfig,
    AgentType,
    FeatureFlags,
    GuardrailAgentConfig,
    ModelSettings,
    RetrievalAgentConfig,
    WebSearchAgentConfig,
    WorkflowDocument,
)
from app.models.chat_session import (
    AgentTraceEntry,
    ChatMessage,
    ChatSessionDocument,
    MessageMetadata,
    MessageRole,
)

__all__ = [
    "UserDocument",
    "IngestionConfigDocument",
    "IngestionStatus",
    "SchemaStats",
    "SQLConnectionConfig",
    "WorkflowDocument",
    "AgentConfig",
    "AgentType",
    "FeatureFlags",
    "GuardrailAgentConfig",
    "ModelSettings",
    "RetrievalAgentConfig",
    "WebSearchAgentConfig",
    "ChatMessage",
    "ChatSessionDocument",
    "AgentTraceEntry",
    "MessageMetadata",
    "MessageRole",
]