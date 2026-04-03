"""
Workflow definition document model.

A workflow ties together:
- An ingestion config (which SQL database + Qdrant collection to use)
- An ordered list of agent configurations (retrieval → web search → guardrail)
- LLM model settings
- Feature flags (caching, etc.)

Workflows are created by admins and consumed by users through the chat interface.
The workflow engine reads this config at runtime to execute the agent pipeline.
"""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Optional

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ──────────────────────────────────────────────
# Agent Type Definitions
# ──────────────────────────────────────────────


class AgentType(StrEnum):
    RETRIEVAL = "retrieval"
    WEB_SEARCH = "web_search"
    GUARDRAIL = "guardrail"


class RetrievalAgentConfig(BaseModel):
    """Config for Agent 1: Vector retrieval + SQL query generation."""

    top_k: int = Field(5, ge=1, le=20, description="Tables to consider per query")
    score_threshold: float = Field(
        0.70, ge=0.0, le=1.0, description="Min similarity score to accept"
    )
    prompt_template: str = (
        "You are a SQL expert assistant. Given the following database schema context, "
        "answer the user's question by generating and explaining the appropriate SQL query.\n\n"
        "Schema Context:\n{context}\n\n"
        "User Question: {query}\n\n"
        "Provide the SQL query and explain what it does."
    )
    max_retries: int = 2
    execute_sql: bool = True  # Whether to actually execute generated SQL


class WebSearchAgentConfig(BaseModel):
    """Config for Agent 2: Web search fallback."""

    trigger_on_low_confidence: bool = True
    confidence_threshold: float = Field(
        0.60, ge=0.0, le=1.0,
        description="Below this score, trigger web search"
    )
    max_results: int = Field(3, ge=1, le=10)
    search_prompt_template: str = (
        "The database schema did not contain enough information to answer this query. "
        "Use web search to find relevant information about: {query}"
    )


class GuardrailAgentConfig(BaseModel):
    """Config for Agent 3: Validation + safety."""

    check_hallucination: bool = True
    check_sql_injection: bool = True
    check_pii_exposure: bool = True
    blocked_topics: list[str] = Field(default_factory=lambda: ["PII exposure", "credential leaks"])
    max_output_tokens: int = 2048
    validation_prompt: str = (
        "Review the following response for:\n"
        "1. Factual accuracy against the provided schema context\n"
        "2. SQL injection patterns or dangerous queries (DROP, DELETE, UPDATE without WHERE)\n"
        "3. Potential PII or credential exposure\n\n"
        "Response to validate:\n{response}\n\n"
        "Schema context:\n{context}\n\n"
        "Return APPROVED if safe, or REJECTED with specific reasons."
    )


# ──────────────────────────────────────────────
# Agent Wrapper (polymorphic by type)
# ──────────────────────────────────────────────


class AgentConfig(BaseModel):
    """
    Single agent entry in the workflow pipeline.
    The `config` field holds type-specific settings.
    """

    type: AgentType
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)

    def get_typed_config(self) -> RetrievalAgentConfig | WebSearchAgentConfig | GuardrailAgentConfig:
        """Deserialize the generic config dict into the typed model."""
        match self.type:
            case AgentType.RETRIEVAL:
                return RetrievalAgentConfig(**self.config)
            case AgentType.WEB_SEARCH:
                return WebSearchAgentConfig(**self.config)
            case AgentType.GUARDRAIL:
                return GuardrailAgentConfig(**self.config)


# ──────────────────────────────────────────────
# Model Settings
# ──────────────────────────────────────────────


class ModelSettings(BaseModel):
    """LLM model configuration for the workflow."""

    model: str = "gpt-4o"
    temperature: float = Field(0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(1024, ge=1, le=16384)
    top_p: float = Field(1.0, ge=0.0, le=1.0)


# ──────────────────────────────────────────────
# Feature Flags
# ──────────────────────────────────────────────


class FeatureFlags(BaseModel):
    """Runtime toggles for the workflow."""

    enable_cache: bool = True
    cache_ttl_seconds: int = Field(3600, ge=60, le=86400)
    enable_streaming: bool = False
    enable_chat_history: bool = True
    max_history_messages: int = Field(20, ge=1, le=100)


# ──────────────────────────────────────────────
# Workflow Document
# ──────────────────────────────────────────────


class WorkflowDocument(BaseModel):
    """
    MongoDB document for a workflow definition.

    This is the central config object that drives the entire
    agent pipeline at query time.
    """

    id: Optional[str] = Field(None, alias="_id")
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""

    # Link to ingestion config (which DB + Qdrant collection)
    ingestion_config_id: str

    # Agent pipeline (ordered list — execution follows list order)
    agents: list[AgentConfig] = Field(
        default_factory=lambda: [
            AgentConfig(
                type=AgentType.RETRIEVAL,
                enabled=True,
                config=RetrievalAgentConfig().model_dump(),
            ),
            AgentConfig(
                type=AgentType.WEB_SEARCH,
                enabled=True,
                config=WebSearchAgentConfig().model_dump(),
            ),
            AgentConfig(
                type=AgentType.GUARDRAIL,
                enabled=True,
                config=GuardrailAgentConfig().model_dump(),
            ),
        ]
    )

    # LLM settings
    model_settings: ModelSettings = Field(default_factory=ModelSettings)

    # Feature flags
    feature_flags: FeatureFlags = Field(default_factory=FeatureFlags)

    # State
    is_active: bool = True

    # Audit
    created_by: str = ""
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)

    class Config:
        populate_by_name = True
        json_encoders = {datetime: lambda v: v.isoformat()}

    def get_enabled_agents(self) -> list[AgentConfig]:
        """Return only agents that are enabled, in pipeline order."""
        return [a for a in self.agents if a.enabled]

    def to_mongo(self) -> dict:
        data = self.model_dump(by_alias=False, exclude={"id"})
        data["updated_at"] = _utc_now()
        return data