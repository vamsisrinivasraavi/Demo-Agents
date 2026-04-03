"""
MCP (Model Context Protocol) client manager.

Manages connections to external MCP tool servers. Each server exposes
tools (web search, file access, API integrations) via a standard protocol.

Architecture:
- MCPServerConfig defines how to connect to each server (command, args, env)
- MCPClientManager maintains a registry of server configs
- On tool invocation, it spawns the MCP server process (stdio transport),
  creates a session, calls the tool, and returns results
- Sessions are created per-invocation for reliability (MCP servers are
  lightweight Node.js processes that start in <1s)

Supported MCP servers:
- @tavily/mcp-server          → web search (AI-optimized results)
- @modelcontextprotocol/server-brave-search → Brave web + local search
- Any custom MCP server following the protocol

Usage:
    manager = MCPClientManager(settings)
    manager.register_server("tavily", MCPServerConfig(
        command="npx", args=["-y", "@tavily/mcp-server"],
        env={"TAVILY_API_KEY": "..."}
    ))
    result = await manager.call_tool("tavily", "search", {"query": "SQL best practices"})
"""

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Optional

from app.core.config import Settings, get_settings
from app.core.logging import get_logger, log_duration

logger = get_logger(__name__)


# ──────────────────────────────────────────────
# MCP Server Configuration
# ──────────────────────────────────────────────


@dataclass
class MCPServerConfig:
    """
    Configuration for an MCP server.

    For stdio transport (most common):
        command: "npx"
        args: ["-y", "@tavily/mcp-server"]
        env: {"TAVILY_API_KEY": "tvly-xxx"}

    For SSE transport (remote servers):
        command: None
        sse_url: "http://mcp-server:8080/sse"
    """

    command: Optional[str] = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    sse_url: Optional[str] = None  # For SSE transport (remote MCP servers)
    timeout: int = 30  # seconds


# Pre-built configs for common MCP servers
TAVILY_SERVER = lambda api_key: MCPServerConfig(
    command="npx",
    args=["-y", "@tavily/mcp-server"],
    env={"TAVILY_API_KEY": api_key},
)

BRAVE_SEARCH_SERVER = lambda api_key: MCPServerConfig(
    command="npx",
    args=["-y", "@modelcontextprotocol/server-brave-search"],
    env={"BRAVE_API_KEY": api_key},
)


# ──────────────────────────────────────────────
# MCP Tool Result
# ──────────────────────────────────────────────


@dataclass
class MCPToolResult:
    """Result from an MCP tool invocation."""

    success: bool
    content: list[dict[str, Any]] = field(default_factory=list)
    text: str = ""  # Flattened text content for convenience
    raw: Any = None
    error: Optional[str] = None

    @property
    def has_content(self) -> bool:
        return bool(self.text.strip())


# ──────────────────────────────────────────────
# MCP Client Manager
# ──────────────────────────────────────────────


class MCPClientManager:
    """
    Manages connections to multiple MCP servers.

    Registry pattern: servers are registered by name, then tools
    are invoked by server name + tool name. This allows the orchestrator
    to route tool calls dynamically based on workflow config.
    """

    def __init__(self, settings: Optional[Settings] = None):
        self._settings = settings or get_settings()
        self._servers: dict[str, MCPServerConfig] = {}
        self._tool_cache: dict[str, list[dict]] = {}  # server_name → available tools

    # ──────────────────────────────────────────────
    # Server Registry
    # ──────────────────────────────────────────────

    def register_server(self, name: str, config: MCPServerConfig) -> None:
        """Register an MCP server configuration."""
        self._servers[name] = config
        logger.info("mcp.server_registered", name=name, command=config.command)

    def register_defaults(self) -> None:
        """
        Register default MCP servers based on available API keys.
        Called during app startup.
        """
        if self._settings.TAVILY_API_KEY:
            self.register_server(
                "tavily",
                TAVILY_SERVER(self._settings.TAVILY_API_KEY),
            )

        if self._settings.BRAVE_SEARCH_API_KEY:
            self.register_server(
                "brave_search",
                BRAVE_SEARCH_SERVER(self._settings.BRAVE_SEARCH_API_KEY),
            )

    def get_available_servers(self) -> list[str]:
        """Return names of registered servers."""
        return list(self._servers.keys())

    def has_server(self, name: str) -> bool:
        return name in self._servers

    # ──────────────────────────────────────────────
    # Tool Discovery
    # ──────────────────────────────────────────────

    @log_duration("mcp.list_tools")
    async def list_tools(self, server_name: str) -> list[dict[str, Any]]:
        """
        Connect to an MCP server and list its available tools.
        Results are cached per server name.
        """
        if server_name in self._tool_cache:
            return self._tool_cache[server_name]

        config = self._servers.get(server_name)
        if config is None:
            logger.warning("mcp.server_not_found", name=server_name)
            return []

        try:
            tools = await self._execute_with_session(
                config,
                action="list_tools",
            )
            self._tool_cache[server_name] = tools
            logger.info(
                "mcp.tools_discovered",
                server=server_name,
                tools=[t.get("name") for t in tools],
            )
            return tools
        except Exception as e:
            logger.error("mcp.list_tools_failed", server=server_name, error=str(e))
            return []

    # ──────────────────────────────────────────────
    # Tool Invocation
    # ──────────────────────────────────────────────

    @log_duration("mcp.call_tool")
    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> MCPToolResult:
        """
        Invoke a tool on an MCP server.

        Flow:
        1. Spawn MCP server process (stdio) or connect (SSE)
        2. Initialize session
        3. Call the tool with arguments
        4. Parse and return results
        5. Close session + process
        """
        config = self._servers.get(server_name)
        if config is None:
            return MCPToolResult(
                success=False,
                error=f"MCP server '{server_name}' not registered",
            )

        try:
            result = await self._execute_with_session(
                config,
                action="call_tool",
                tool_name=tool_name,
                arguments=arguments,
            )
            return result
        except asyncio.TimeoutError:
            logger.error("mcp.timeout", server=server_name, tool=tool_name)
            return MCPToolResult(
                success=False,
                error=f"MCP tool call timed out after {config.timeout}s",
            )
        except Exception as e:
            logger.error(
                "mcp.call_failed",
                server=server_name,
                tool=tool_name,
                error=str(e),
            )
            return MCPToolResult(success=False, error=str(e))

    # ──────────────────────────────────────────────
    # Session Management (stdio transport)
    # ──────────────────────────────────────────────

    async def _execute_with_session(
        self,
        config: MCPServerConfig,
        action: str,
        tool_name: str = "",
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        """
        Spawn an MCP server, create a session, perform an action, and clean up.

        Uses the mcp Python SDK for protocol handling.
        Falls back to raw subprocess JSON-RPC if the SDK is not available.
        """
        try:
            return await self._execute_with_mcp_sdk(
                config, action, tool_name, arguments
            )
        except ImportError:
            logger.info("mcp.sdk_not_available, using raw subprocess fallback")
            return await self._execute_with_subprocess(
                config, action, tool_name, arguments
            )

    async def _execute_with_mcp_sdk(
        self,
        config: MCPServerConfig,
        action: str,
        tool_name: str = "",
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        """
        Execute using the official mcp Python SDK.

        pip install mcp
        """
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command=config.command,
            args=config.args,
            env={**config.env} if config.env else None,
        )

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                if action == "list_tools":
                    response = await session.list_tools()
                    return [
                        {
                            "name": tool.name,
                            "description": tool.description or "",
                            "input_schema": tool.inputSchema if hasattr(tool, "inputSchema") else {},
                        }
                        for tool in response.tools
                    ]

                elif action == "call_tool":
                    response = await session.call_tool(tool_name, arguments or {})

                    # Parse content blocks into our result format
                    content_list = []
                    text_parts = []

                    for block in response.content:
                        if hasattr(block, "text"):
                            content_list.append({"type": "text", "text": block.text})
                            text_parts.append(block.text)
                        elif hasattr(block, "data"):
                            content_list.append({"type": "resource", "data": block.data})
                        else:
                            content_list.append({"type": "unknown", "raw": str(block)})

                    return MCPToolResult(
                        success=not response.isError if hasattr(response, "isError") else True,
                        content=content_list,
                        text="\n".join(text_parts),
                        raw=response,
                    )

    async def _execute_with_subprocess(
        self,
        config: MCPServerConfig,
        action: str,
        tool_name: str = "",
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        """
        Fallback: raw subprocess with JSON-RPC messages over stdio.
        Used if the mcp SDK is not installed.
        """
        import os

        if not config.command:
            raise ValueError("Subprocess transport requires a command")

        env = {**os.environ, **config.env} if config.env else None

        process = await asyncio.create_subprocess_exec(
            config.command,
            *config.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        try:
            # Send JSON-RPC initialize
            init_msg = json.dumps({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "schema-assistant", "version": "1.0.0"},
                },
            }) + "\n"

            process.stdin.write(init_msg.encode())
            await process.stdin.drain()

            # Read initialize response
            init_response = await asyncio.wait_for(
                process.stdout.readline(), timeout=config.timeout
            )

            if action == "list_tools":
                list_msg = json.dumps({
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/list",
                    "params": {},
                }) + "\n"

                process.stdin.write(list_msg.encode())
                await process.stdin.drain()

                response_line = await asyncio.wait_for(
                    process.stdout.readline(), timeout=config.timeout
                )
                response = json.loads(response_line.decode())
                return response.get("result", {}).get("tools", [])

            elif action == "call_tool":
                call_msg = json.dumps({
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": arguments or {}},
                }) + "\n"

                process.stdin.write(call_msg.encode())
                await process.stdin.drain()

                response_line = await asyncio.wait_for(
                    process.stdout.readline(), timeout=config.timeout
                )
                response = json.loads(response_line.decode())
                result = response.get("result", {})
                content = result.get("content", [])

                text_parts = [
                    c.get("text", "") for c in content if c.get("type") == "text"
                ]

                return MCPToolResult(
                    success=not result.get("isError", False),
                    content=content,
                    text="\n".join(text_parts),
                    raw=result,
                )

        finally:
            process.stdin.close()
            try:
                process.kill()
                await process.wait()
            except ProcessLookupError:
                pass


# ──────────────────────────────────────────────
# Singleton Instance
# ──────────────────────────────────────────────

_mcp_manager: Optional[MCPClientManager] = None


def get_mcp_manager() -> MCPClientManager:
    """Get or create the singleton MCP client manager."""
    global _mcp_manager
    if _mcp_manager is None:
        _mcp_manager = MCPClientManager()
        _mcp_manager.register_defaults()
    return _mcp_manager


def init_mcp_manager(settings: Settings) -> MCPClientManager:
    """Initialize with explicit settings (called during app startup)."""
    global _mcp_manager
    _mcp_manager = MCPClientManager(settings)
    _mcp_manager.register_defaults()
    logger.info(
        "mcp.manager_initialized",
        servers=_mcp_manager.get_available_servers(),
    )
    return _mcp_manager