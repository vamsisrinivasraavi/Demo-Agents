"""
Base agent interface and shared types.

Every agent in the pipeline:
1. Receives an AgentContext (query, conversation history, previous agent results)
2. Returns an AgentResult (response, confidence, metadata, trace info)
3. Can decide to SKIP itself based on context (e.g., web search skips if retrieval confidence is high)

Agents are stateless — all state lives in the context passed between them.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Optional
import time


class AgentStatus(StrEnum):
    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass
class AgentContext:
    """
    Shared context passed through the agent pipeline.
    Each agent reads from and writes to this context.
    """

    # Original user query
    query: str

    # Workflow configuration
    workflow_id: str
    workflow_config: dict[str, Any]

    # Ingestion config (for SQL connection + Qdrant collection)
    ingestion_config: dict[str, Any]

    # Conversation history (last N messages as LLM-format dicts)
    chat_history: list[dict[str, str]] = field(default_factory=list)

    # Accumulated results from previous agents in the pipeline
    retrieval_response: Optional[str] = None
    retrieval_confidence: float = 0.0
    retrieval_sql_query: Optional[str] = None
    retrieval_tables: list[str] = field(default_factory=list)
    retrieval_used_columns: list[str] = field(default_factory=list)
    retrieval_output_columns: list[str] = field(default_factory=list)
    retrieval_sql_result_preview : Optional[str] = None

    web_search_response: Optional[str] = None
    web_search_sources: list[str] = field(default_factory=list)

    # Final validated response (set by guardrail agent)
    final_response: Optional[str] = None
    is_validated: bool = False
    validation_issues: list[str] = field(default_factory=list)


@dataclass
class AgentResult:
    """Result returned by a single agent execution."""

    agent_type: str
    status: AgentStatus
    response: Optional[str] = None
    confidence: float = 0.0
    duration_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


class BaseAgent(ABC):
    """
    Abstract base for all agents.

    Subclasses implement:
    - should_run(context): whether this agent should execute
    - _execute(context): the actual agent logic
    """

    agent_type: str = "base"

    @abstractmethod
    async def should_run(self, context: AgentContext) -> bool:
        """
        Decide if this agent should execute based on current context.
        Called by the orchestrator before _execute().
        """
        ...

    @abstractmethod
    async def _execute(self, context: AgentContext) -> AgentResult:
        """
        Core agent logic. Must return an AgentResult.
        Should also mutate the context to pass data to downstream agents.
        """
        ...

    async def run(self, context: AgentContext) -> AgentResult:
        """
        Entry point called by the orchestrator.
        Handles should_run check, timing, and error wrapping.
        """
        if not await self.should_run(context):
            return AgentResult(
                agent_type=self.agent_type,
                status=AgentStatus.SKIPPED,
                metadata={"reason": "Precondition not met"},
            )

        start = time.perf_counter()
        try:
            result = await self._execute(context)
            result.duration_ms = (time.perf_counter() - start) * 1000
            return result
        except Exception as e:
            duration = (time.perf_counter() - start) * 1000
            return AgentResult(
                agent_type=self.agent_type,
                status=AgentStatus.FAILED,
                error=str(e),
                duration_ms=duration,
            )