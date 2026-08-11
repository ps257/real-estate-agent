"""MCP client for connecting to `real-estate-mcp`."""

from __future__ import annotations

import json
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
    # Adapter versions may return a ToolMessage/Pydantic model rather than
    # the raw Python value.
    if not isinstance(value, (dict, list, str)):
        if hasattr(value, "model_dump"):
            value = value.model_dump()
        elif hasattr(value, "content"):
            value = value.content

    if isinstance(value, str):
        try:
            return _unwrap_tool_result(json.loads(value))
        except (json.JSONDecodeError, TypeError):
            return value

    if isinstance(value, dict):
        for key in ("structured_content", "structuredContent"):
            if value.get(key) is not None:
                return _unwrap_tool_result(value[key])

        # MCP text content blocks contain the serialized JSON tool result.
        if value.get("type") == "text" and isinstance(value.get("text"), str):
            return _unwrap_tool_result(value["text"])

        # ToolMessage.model_dump() keeps the actual payload under content.
        payload_keys = {"project", "stats", "matched", "candidates"}
        if "content" in value and not (payload_keys & set(value)):
            return _unwrap_tool_result(value["content"])
        return value

    if isinstance(value, list) and len(value) == 1:
        return _unwrap_tool_result(value[0])

    return value
