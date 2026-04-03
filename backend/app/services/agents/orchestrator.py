"""
Agent orchestrator — pipeline controller.

Executes agents in workflow-defined order:
    Retrieval → (conditional) Web Search → Guardrail

Responsibilities:
1. Build AgentContext from workflow config + chat history
2. Instantiate agents based on workflow config
3. Execute each enabled agent in sequence
4. Collect AgentResult traces for observability
5. Handle agent failures gracefully (skip to next)
6. Return the final validated response

The orchestrator does NOT know about caching — that's handled by ChatService.
This keeps the orchestrator focused on agent execution only.
"""

from typing import Optional

from app.core.logging import get_logger
from app.models.chat_session import AgentTraceEntry
from app.models.workflow import AgentType
from app.repositories.vector_repo import VectorRepository
from app.services.agents.base import (
    AgentContext,
    AgentResult,
    AgentStatus,
    BaseAgent,
)
from app.services.agents.guardrail_agent import GuardrailAgent
from app.services.agents.retrieval_agent import RetrievalAgent
from app.services.agents.web_search_agent import WebSearchAgent

logger = get_logger(__name__)


class OrchestratorResult:
    """Final result from the orchestrator containing response + traces."""

    def __init__(
        self,
        response: str,
        confidence: float,
        sql_query: Optional[str],
        source_tables: list[str],
        retrieval_used_columns: list[str],
        retrieval_output_columns: list[str],
        retrieval_sql_result_preview: Optional[str],
        web_search_sources: Optional[list[str]],
        web_search_response: Optional[str],
        agent_traces: list[AgentTraceEntry],
        is_validated: bool,
        validation_issues: list[str],
    ):
        self.response = response
        self.confidence = confidence
        self.sql_query = sql_query
        self.source_tables = source_tables
        self.retrieval_used_columns = retrieval_used_columns
        self.retrieval_output_columns = retrieval_output_columns
        self.retrieval_sql_result_preview = retrieval_sql_result_preview
        self.web_search_sources = web_search_sources
        self.web_search_response = web_search_response
        self.agent_traces = agent_traces
        self.is_validated = is_validated
        self.validation_issues = validation_issues


class AgentOrchestrator:
    """
    Pipeline controller for the multi-agent system.

    Takes a workflow config and executes its agent pipeline.
    Agents are composable — the pipeline order and enabled/disabled
    state is driven entirely by the workflow config in MongoDB.
    """

    def __init__(self, vector_repo: VectorRepository, mcp_manager=None):
        self._vector_repo = vector_repo
        self._mcp_manager = mcp_manager
        self._agent_registry: dict[str, BaseAgent] = {}
        self._build_agent_registry()

    def _build_agent_registry(self):
        """
        Register available agent implementations.
        New agent types are added here — the orchestrator discovers
        them from the registry based on workflow config.
        """
        self._agent_registry = {
            AgentType.RETRIEVAL: RetrievalAgent(self._vector_repo),
            AgentType.WEB_SEARCH: WebSearchAgent(mcp_manager=self._mcp_manager),
            AgentType.GUARDRAIL: GuardrailAgent(),
        }

    async def execute(
        self,
        query: str,
        workflow_config: dict,
        ingestion_config: dict,
        chat_history: list[dict[str, str]] | None = None,
    ) -> OrchestratorResult:
        """
        Execute the full agent pipeline for a user query.

        Args:
            query: User's natural language question
            workflow_config: Full workflow document from MongoDB
            ingestion_config: Full ingestion config document
            chat_history: Previous messages for context

        Returns:
            OrchestratorResult with response, traces, and metadata
        """
        # Build shared context
        context = AgentContext(
            query=query,
            workflow_id=str(workflow_config.get("_id", "")),
            workflow_config=workflow_config,
            ingestion_config=ingestion_config,
            chat_history=chat_history or [],
        )

        # Get enabled agents in pipeline order
        agent_configs = workflow_config.get("agents", [])
        pipeline = [
            ac for ac in agent_configs
            if ac.get("enabled", True) and ac.get("type") in self._agent_registry
        ]

        if not pipeline:
            logger.error("orchestrator.no_agents", workflow_id=context.workflow_id)
            return OrchestratorResult(
                response="No agents configured for this workflow.",
                confidence=0.0,
                sql_query=None,
                source_tables=[],
                agent_traces=[],
                is_validated=False,
                validation_issues=["No agents in pipeline"],
            )

        # Execute agents in sequence
        traces: list[AgentTraceEntry] = []

        for agent_config in pipeline:
            agent_type = agent_config["type"]
            agent = self._agent_registry.get(agent_type)

            if agent is None:
                logger.warning("orchestrator.unknown_agent", type=agent_type)
                continue

            logger.info(
                "orchestrator.executing_agent",
                agent=agent_type,
                workflow_id=context.workflow_id,
            )

            result = await agent.run(context)

            # Record trace
            trace = AgentTraceEntry(
                agent_type=agent_type,
                status=result.status,
                duration_ms=result.duration_ms,
                input_summary=query[:200],
                output_summary=(result.response or "")[:300],
                metadata=result.metadata,
            )
            traces.append(trace)

            logger.info(
                "orchestrator.agent_completed",
                agent=agent_type,
                status=result.status,
                duration_ms=round(result.duration_ms, 2),
                confidence=result.confidence,
            )

            # If an agent fails critically, we can still continue
            # The guardrail agent will catch issues downstream
            if result.status == AgentStatus.FAILED:
                logger.warning(
                    "orchestrator.agent_failed",
                    agent=agent_type,
                    error=result.error,
                )

        # Build final response from context
        final_response = self._build_final_response(context)

        print("Final response:", final_response)

        return OrchestratorResult(
            response=final_response,
            confidence=context.retrieval_confidence,
            sql_query=context.retrieval_sql_query,
            source_tables=context.retrieval_tables,
            retrieval_used_columns=context.retrieval_used_columns,
            retrieval_output_columns=context.retrieval_output_columns,
            retrieval_sql_result_preview=context.retrieval_sql_result_preview,
            web_search_sources=context.web_search_sources,
            web_search_response=context.web_search_response,
            agent_traces=traces,
            is_validated=context.is_validated,
            validation_issues=context.validation_issues,
        )

    @staticmethod
    def _build_final_response(context: AgentContext) -> str:
        """
        Determine the final response based on what agents produced.

        Priority:
        1. Guardrail's final_response (validated/sanitized)
        2. Web search enriched response
        3. Raw retrieval response
        4. Fallback error message
        """
        print("Building final response from context...")
        print(context)
        if context.final_response:
            return context.final_response
        
        print("No guardrail final response, checking web search and retrieval results...")
        print(f"Retrieval confidence: {context.retrieval_confidence}")

        if context.retrieval_confidence < 0.5:
            if context.web_search_response:
                return (
                    f"I found some information related to your question, but I'm not very confident about it. I have found this information from the web that might help you:\n\n"
                    f"Here's what I found:\n\n{context.web_search_response}\n\n"
                    "Please note that the information may not be directly relevant to your question, so I recommend reviewing it carefully."
                )
        if context.web_search_response and context.retrieval_response:
            # Merge retrieval + web search
            return (
                f"{context.retrieval_response}\n\n"
                f"**Additional context from web search:**\n"
                f"{context.web_search_response}"
            )

        if context.retrieval_response:
            return context.retrieval_response

        return (
            "I wasn't able to find a clear answer for your question. "
            "Could you try rephrasing it, or ask about specific tables or columns?"
        )