"""
Agent 2: Web Search Agent (MCP-powered).

Fallback agent — triggered only when the Retrieval Agent's confidence
is below the configured threshold.

Uses MCP (Model Context Protocol) to invoke web search tools:
- Primary:  Tavily MCP server  (@tavily/mcp-server)
- Fallback: Brave Search MCP   (@modelcontextprotocol/server-brave-search)
- Any other MCP server registered in the MCPClientManager

MCP flow:
1. Check which MCP search servers are available
2. Call the search tool via MCP protocol (stdio transport)
3. Parse structured results from MCP response
4. Synthesize results with LLM into a supplementary answer

This agent is fully pluggable — adding a new search provider is
just registering another MCP server in the manager. No code changes.
"""

from typing import Optional

import openai

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.mcp_client import MCPClientManager, MCPToolResult, get_mcp_manager
from app.models.workflow import AgentType, WebSearchAgentConfig
from app.services.agents.base import (
    AgentContext,
    AgentResult,
    AgentStatus,
    BaseAgent,
)

logger = get_logger(__name__)

# MCP server preference order for web search
SEARCH_SERVER_PRIORITY = ["brave_search", "tavily"]

# Tool name mapping — each MCP server may expose tools with different names
SEARCH_TOOL_NAMES = {
    "tavily": "search",           # Tavily exposes a "search" tool
    "brave_search": "brave_web_search",  # Brave exposes "brave_web_search"
}


class WebSearchAgent(BaseAgent):
    """
    MCP-powered web search fallback agent.

    Discovers available MCP search servers at runtime, invokes the
    best available one, and synthesizes results via LLM.
    """

    agent_type = AgentType.WEB_SEARCH

    def __init__(self, mcp_manager: Optional[MCPClientManager] = None):
        self._mcp = mcp_manager

    @property
    def mcp(self) -> MCPClientManager:
        """Lazy-load MCP manager (allows test injection)."""
        if self._mcp is None:
            self._mcp = get_mcp_manager()
        return self._mcp

    async def should_run(self, context: AgentContext) -> bool:
        """
        Run only if:
        1. Agent is enabled in the workflow config
        2. Retrieval confidence is below threshold
        3. At least one MCP search server is available
        """
        agent_configs = context.workflow_config.get("agents", [])
        for ac in agent_configs:
            if ac.get("type") == AgentType.WEB_SEARCH and ac.get("enabled", True):
                cfg = WebSearchAgentConfig(**ac.get("config", {}))

                # Check confidence threshold
                if cfg.trigger_on_low_confidence:
                    if context.retrieval_confidence >= cfg.confidence_threshold:
                        return False

                # Check if any MCP search server is available
                available = self._find_search_server()
                if available is None:
                    logger.warning("agent.web_search.no_mcp_server_available")
                    return False

                logger.info(
                    "agent.web_search.triggered",
                    retrieval_confidence=context.retrieval_confidence,
                    threshold=cfg.confidence_threshold,
                    mcp_server=available,
                )
                return True

        return False

    async def _execute(self, context: AgentContext) -> AgentResult:
        """
        Execute web search via MCP and synthesize results.
        """
        # Parse agent config
        agent_configs = context.workflow_config.get("agents", [])
        search_cfg = WebSearchAgentConfig()
        for ac in agent_configs:
            if ac.get("type") == AgentType.WEB_SEARCH:
                search_cfg = WebSearchAgentConfig(**ac.get("config", {}))
                break

        # Find best available MCP search server
        server_name = self._find_search_server()
        if server_name is None:
            return AgentResult(
                agent_type=self.agent_type,
                status=AgentStatus.FAILED,
                error="No MCP search server available. Configure TAVILY_API_KEY or BRAVE_SEARCH_API_KEY.",
            )

        # Build search query (augmented with SQL context)
        search_query = f"SQL database schema: {context.query}"

        # Call MCP search tool
        tool_name = SEARCH_TOOL_NAMES.get(server_name, "search")
        mcp_result = await self.mcp.call_tool(
            server_name=server_name,
            tool_name=tool_name,
            arguments={
                "query": search_query,
                "max_results": search_cfg.max_results,
            },
        )

        if not mcp_result.success or not mcp_result.has_content:
            logger.warning(
                "agent.web_search.mcp_empty",
                server=server_name,
                error=mcp_result.error,
            )
            return AgentResult(
                agent_type=self.agent_type,
                status=AgentStatus.SUCCESS,
                response=None,
                confidence=0.0,
                metadata={
                    "mcp_server": server_name,
                    "results_count": 0,
                    "error": mcp_result.error,
                },
            )

        # Parse search results from MCP response
        search_text = mcp_result.text
        sources = self._extract_sources(mcp_result)

        # Synthesize with LLM
        synthesized = await self._synthesize_results(
            query=context.query,
            search_results=search_text,
            retrieval_response=context.retrieval_response,
        )

        # Write to context for downstream agents
        context.web_search_response = synthesized
        context.web_search_sources = sources

        logger.info(
            "agent.web_search.completed",
            mcp_server=server_name,
            tool=tool_name,
            sources_count=len(sources),
        )

        return AgentResult(
            agent_type=self.agent_type,
            status=AgentStatus.SUCCESS,
            response=synthesized,
            confidence=0.7,
            metadata={
                "mcp_server": server_name,
                "mcp_tool": tool_name,
                "sources": sources,
                "results_count": len(sources) if sources else 1,
            },
        )

    # ──────────────────────────────────────────────
    # MCP Server Discovery
    # ──────────────────────────────────────────────

    def _find_search_server(self) -> Optional[str]:
        """
        Find the best available MCP search server.
        Checks in priority order: tavily → brave_search → any registered.
        """
        for name in SEARCH_SERVER_PRIORITY:
            if self.mcp.has_server(name):
                return name

        # Fall back to any registered server
        available = self.mcp.get_available_servers()
        return available[0] if available else None

    @staticmethod
    def _extract_sources(result: MCPToolResult) -> list[str]:
        """Extract source URLs from MCP tool result content blocks."""
        sources = []
        for block in result.content:
            if block.get("type") == "text":
                text = block.get("text", "")
                # Tavily and Brave typically include URLs in their text output
                for word in text.split():
                    if word.startswith("http://") or word.startswith("https://"):
                        clean = word.rstrip(".,;)")
                        if clean not in sources:
                            sources.append(clean)
            elif block.get("type") == "resource":
                uri = block.get("uri", "")
                if uri:
                    sources.append(uri)
        return sources

    # ──────────────────────────────────────────────
    # LLM Synthesis
    # ──────────────────────────────────────────────

    @staticmethod
    async def _synthesize_results(
        query: str,
        search_results: str,
        retrieval_response: Optional[str] = None,
    ) -> str:
        """
        Use LLM to synthesize MCP search results into a coherent
        supplementary response that enriches the retrieval answer.
        """
        settings = get_settings()
        client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

        prompt = (
            "You are a SQL database expert. The user asked about a database schema, "
            "and the primary retrieval system provided a partial answer. "
            "Use the web search results below to supplement the answer.\n\n"
            f"User question: {query}\n\n"
        )

        if retrieval_response:
            prompt += f"Retrieval agent's response:\n{retrieval_response}\n\n"

        prompt += (
            f"Web search results:\n{search_results[:3000]}\n\n"
            "Provide additional context, best practices, or corrections "
            "based on the search results. Be concise and relevant."
        )

        response = await client.chat.completions.create(
            model=settings.OPENAI_LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=512,
        )

        return response.choices[0].message.content or ""