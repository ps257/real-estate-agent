"""MCP client — kết nối `real-estate-mcp`. [DONE]

Dùng `langchain-mcp-adapters` (MultiServerMCPClient). Config-driven qua .env:
  - MCP_TRANSPORT=stdio (dev local): agent tự spawn server.
  - MCP_TRANSPORT=http  (server đã host): agent kết nối tới MCP_SERVER_URL (+ auth headers).
Xem agent/config.py::MCPConfig.server_spec().

Trong test, thay bằng một object cùng interface `MCPProtocol` (xem tests/conftest.py)
nên KHÔNG cần chạy server thật để smoke-test.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from agent.config import MCPConfig, get_settings


@runtime_checkable
class MCPProtocol(Protocol):
    """Interface tối thiểu mà graph cần từ một MCP client (dễ mock)."""

    async def list_tools(self) -> list[str]: ...
    async def call_tool(self, name: str, args: dict[str, Any]) -> Any: ...


class MCPClient:
    """MCP client thật, kết nối `real-estate-mcp` qua stdio.

    Lazy-init: chỉ tạo kết nối khi lần đầu dùng để test import không cần server.
    """

    def __init__(self, config: MCPConfig | None = None) -> None:
        self._config = config or get_settings().mcp
        self._client: Any = None            # MultiServerMCPClient
        self._tools: dict[str, Any] = {}    # name -> BaseTool (từ adapters)

    async def _ensure(self) -> None:
        if self._client is not None:
            return
        # Import trong hàm để môi trường test không bắt buộc cài adapters.
        from langchain_mcp_adapters.client import MultiServerMCPClient

        # server_spec() tự chọn stdio (spawn) hoặc http (server đã host) theo config.
        self._client = MultiServerMCPClient({"real_estate": self._config.server_spec()})
        tools = await self._client.get_tools()
        self._tools = {t.name: t for t in tools}

    async def list_tools(self) -> list[str]:
        """Tên các tool server MCP cung cấp."""
        await self._ensure()
        return list(self._tools)

    async def call_tool(self, name: str, args: dict[str, Any]) -> Any:
        """Gọi một MCP tool và trả kết quả (dict / list / str tuỳ tool)."""
        await self._ensure()
        if name not in self._tools:
            raise KeyError(f"MCP tool khong ton tai: {name!r}. Co: {list(self._tools)}")
        return await self._tools[name].ainvoke(args)
