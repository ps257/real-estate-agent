"""MCP client — kết nối `real-estate-mcp`. [DONE]

Dùng `langchain-mcp-adapters` (MultiServerMCPClient). Config-driven qua .env:
  - MCP_TRANSPORT=stdio (dev local): agent tự spawn server.
  - MCP_TRANSPORT=http  (server đã host): agent kết nối tới MCP_SERVER_URL (+ auth headers).
Xem agent/config.py::MCPConfig.server_spec().

Trong test, thay bằng một object cùng interface `MCPProtocol` (xem tests/conftest.py)
nên KHÔNG cần chạy server thật để smoke-test.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Protocol, runtime_checkable

from agent.config import MCPConfig, get_settings


def parse_tool_result(raw: Any) -> Any:
    """Bóc content block của MCP thành dữ liệu Python.

    `langchain-mcp-adapters` KHÔNG trả JSON đã parse — nó trả list content block
    theo chuẩn MCP, với payload nằm trong chuỗi ``text``::

        [{"type": "text", "text": '{"matched": false, "candidates": [...]}'}]

    Không bóc lớp này thì mọi node phía sau nhận nhầm kiểu: ``isinstance(x, dict)``
    luôn False, và ``x.get("id")`` lấy trúng id của content block chứ không phải
    id nghiệp vụ.

    Tool lỗi thì ``text`` là câu thông báo thường, không phải JSON — khi đó trả
    nguyên chuỗi để caller tự xử lý (không raise, để một tool hỏng không làm
    sập cả lượt chat).
    """
    if not isinstance(raw, (dict, list, str)):
        if hasattr(raw, "model_dump"):
            raw = raw.model_dump()
        elif hasattr(raw, "content"):
            raw = raw.content

    if isinstance(raw, str):
        try:
            return parse_tool_result(json.loads(raw))
        except (json.JSONDecodeError, TypeError):
            return raw

    if isinstance(raw, dict):
        for key in ("structured_content", "structuredContent"):
            if raw.get(key) is not None:
                return parse_tool_result(raw[key])

        if raw.get("type") == "text" and isinstance(raw.get("text"), str):
            return parse_tool_result(raw["text"])

        payload_keys = {"project", "stats", "matched", "candidates", "listings"}
        if "content" in raw and not (payload_keys & set(raw)):
            return parse_tool_result(raw["content"])
        return raw

    if not isinstance(raw, list):
        return raw  # Đã là dict/str — adapters version khác có thể trả thẳng.

    texts = [
        block["text"]
        for block in raw
        if isinstance(block, dict) and block.get("type") == "text" and "text" in block
    ]
    if not texts:
        return raw  # image/resource block — trả nguyên, caller tự lo.

    payload = "".join(texts)
    try:
        return json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        return payload


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
        self._init_lock = asyncio.Lock()

    async def _ensure(self) -> None:
        if self._client is not None and self._tools:
            return
        async with self._init_lock:
            if self._client is not None and self._tools:
                return

            # Import trong hàm để môi trường test không bắt buộc cài adapters.
            from langchain_mcp_adapters.client import MultiServerMCPClient

            # Dựng vào biến local và chỉ publish sau khi get_tools hoàn tất. Nếu
            # publish client trước await, request đồng thời có thể thấy tools={}
            # rồi báo sai "tool không tồn tại".
            client = MultiServerMCPClient({"real_estate": self._config.server_spec()})
            tools = await client.get_tools()
            self._tools = {t.name: t for t in tools}
            self._client = client

    async def list_tools(self) -> list[str]:
        """Tên các tool server MCP cung cấp."""
        await self._ensure()
        return list(self._tools)

    async def call_tool(self, name: str, args: dict[str, Any]) -> Any:
        """Gọi một MCP tool và trả kết quả ĐÃ BÓC content block (dict / list / str)."""
        await self._ensure()
        if name not in self._tools:
            raise KeyError(f"MCP tool khong ton tai: {name!r}. Co: {list(self._tools)}")
        return parse_tool_result(await self._tools[name].ainvoke(args))
