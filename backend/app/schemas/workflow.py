"""
Workflow request/response schemas.

Workflows are the central configuration object. Admins create them,
users consume them via the chat interface.
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.models.workflow import (
    AgentConfig,
    AgentType,
    FeatureFlags,
    ModelSettings,
)


# ──────────────────────────────────────────────
# Requests
# ──────────────────────────────────────────────


class AgentConfigRequest(BaseModel):
    """Agent configuration submitted when creating/updating a workflow."""

    type: AgentType
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


class CreateWorkflowRequest(BaseModel):
    """Create a new workflow."""

    name: str = Field(..., min_length=1, max_length=200, examples=["ERP Schema Q&A"])
    description: str = ""
    ingestion_config_id: str = Field(..., description="ID of the ingestion config to use")

    agents: list[AgentConfigRequest] = Field(
        default_factory=lambda: [
            AgentConfigRequest(type=AgentType.RETRIEVAL, enabled=True),
            AgentConfigRequest(type=AgentType.WEB_SEARCH, enabled=True),
            AgentConfigRequest(type=AgentType.GUARDRAIL, enabled=True),
        ]
    )

    model_settings: ModelSettings = Field(default_factory=ModelSettings)
    feature_flags: FeatureFlags = Field(default_factory=FeatureFlags)


class UpdateWorkflowRequest(BaseModel):
    """Partial update of a workflow. Only provided fields are updated."""

    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    agents: Optional[list[AgentConfigRequest]] = None
    model_settings: Optional[ModelSettings] = None
    feature_flags: Optional[FeatureFlags] = None
    is_active: Optional[bool] = None


# ──────────────────────────────────────────────
# Responses
# ──────────────────────────────────────────────


class WorkflowResponse(BaseModel):
    """Full workflow detail returned to the client."""

    id: str
    name: str
    description: str
    ingestion_config_id: str
    agents: list[AgentConfig]
    model_settings: ModelSettings
    feature_flags: FeatureFlags
    is_active: bool
    created_by: str
    created_at: datetime
    updated_at: datetime

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class WorkflowListItem(BaseModel):
    """Lightweight workflow info for listing (no agent details)."""

    id: str
    name: str
    description: str
    ingestion_config_id: str
    is_active: bool
    agent_count: int
    cache_enabled: bool
    created_at: datetime


class WorkflowListResponse(BaseModel):
    """Paginated list of workflows."""

    items: list[WorkflowListItem]
    total: int
    page: int
    page_size: int