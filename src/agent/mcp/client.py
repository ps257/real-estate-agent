"""MCP client for connecting to `real-estate-mcp`."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from agent.config import MCPConfig, get_settings


@runtime_checkable
class MCPProtocol(Protocol):
    """Minimal MCP client interface used by the graph and tests."""

    async def list_tools(self) -> list[str]: ...
    async def call_tool(self, name: str, args: dict[str, Any]) -> Any: ...


class MCPClient:
    """Real MCP client backed by langchain-mcp-adapters."""

    def __init__(self, config: MCPConfig | None = None) -> None:
        self._config = config or get_settings().mcp
        self._client: Any = None
        self._tools: dict[str, Any] = {}

    async def _ensure(self) -> None:
        if self._client is not None:
            return
        from langchain_mcp_adapters.client import MultiServerMCPClient

        self._client = MultiServerMCPClient({"real_estate": self._config.server_spec()})
        tools = await self._client.get_tools()
        self._tools = {t.name: t for t in tools}

    async def list_tools(self) -> list[str]:
        await self._ensure()
        return list(self._tools)

    async def call_tool(self, name: str, args: dict[str, Any]) -> Any:
        await self._ensure()
        if name not in self._tools:
            raise KeyError(f"MCP tool khong ton tai: {name!r}. Co: {list(self._tools)}")
        return _unwrap_tool_result(await self._tools[name].ainvoke(args))


def _unwrap_tool_result(value: Any) -> Any:
    """Normalize common LangChain MCP wrappers into the actual tool payload.

    FastMCP tools return JSON values, but the adapter can wrap a single structured result in
    a one-item list or a structured-content dict. Keep real multi-row listing lists intact.
    """
    if isinstance(value, dict):
        if "structured_content" in value:
            return value["structured_content"]
        if "structuredContent" in value:
            return value["structuredContent"]
        return value

    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict):
        item = value[0]
        if "structured_content" in item:
            return item["structured_content"]
        if "structuredContent" in item:
            return item["structuredContent"]
        if {"matched", "project", "candidates"} & set(item):
            return item
        if {"project", "stats"} <= set(item):
            return item

    return value
