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
from agent.telemetry import current_w3c_carrier, get_telemetry, redact


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

        telemetry = get_telemetry()
        with telemetry.observation(
            name=f"mcp.{name}",
            as_type="tool",
            input=redact(args),
            metadata={"transport": self._config.transport, "tool_name": name},
        ) as observation:
            argument_valid = _arguments_match_schema(self._tools[name], args)
            observation.score("argument_validity", argument_valid)

            # The LangChain BaseTool wrapper does not expose MCP request `_meta`.
            # Use the same adapter session factory one level lower so W3C context is
            # carried in CallToolRequest.params._meta.  A fresh initialized session per
            # invocation matches MultiServerMCPClient's existing lifecycle.
            from langchain_mcp_adapters.sessions import create_session

            result: Any = None
            captured_exception: Exception | None = None
            try:
                async with create_session(self._config.server_spec()) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        name,
                        args,
                        meta=current_w3c_carrier() or None,
                    )
            except Exception as exc:  # noqa: BLE001 - mirrors adapter transport handling
                captured_exception = exc

            # Re-raise outside the adapter context.  Some MCP transports suppress an
            # exception while disconnecting; MultiServerMCPClient uses the same guard.
            if captured_exception is not None:
                observation.score("tool_success", False)
                observation.update(
                    output={"status": "transport_error"},
                    level="ERROR",
                    status_message=type(captured_exception).__name__,
                )
                raise captured_exception

            is_error = bool(getattr(result, "isError", False))
            parsed = parse_tool_result(result)
            observation.score("tool_success", not is_error)
            observation.update(
                output=_tool_result_summary(parsed, is_error=is_error),
                level="WARNING" if is_error else None,
                status_message="mcp_error" if is_error else None,
            )
            return parsed


def _arguments_match_schema(tool: Any, args: Any) -> bool:
    """Best-effort JSON Schema check used only for telemetry scoring.

    The MCP server remains the source of truth and still receives invalid arguments,
    preserving the previous adapter/server validation and error semantics.
    """

    if not isinstance(args, dict):
        return False
    schema = getattr(tool, "args_schema", None)
    try:
        if isinstance(schema, type) and hasattr(schema, "model_validate"):
            schema.model_validate(args)
            return True
        if isinstance(schema, type) and hasattr(schema, "parse_obj"):
            schema.parse_obj(args)
            return True
        if schema is None and hasattr(tool, "get_input_schema"):
            model = tool.get_input_schema()
            if hasattr(model, "model_validate"):
                model.model_validate(args)
                return True
        if not isinstance(schema, dict):
            return True

        from jsonschema.validators import validator_for

        validator = validator_for(schema)
        validator.check_schema(schema)
        validator(schema).validate(args)
        return True
    except Exception:  # noqa: BLE001 - third-party schemas are best-effort scoring only
        return False


def _tool_result_summary(result: Any, *, is_error: bool) -> dict[str, Any]:
    """Summarize tool output without copying domain data into telemetry."""

    summary: dict[str, Any] = {
        "status": "error" if is_error else "ok",
        "result_type": type(result).__name__,
    }
    if isinstance(result, dict):
        summary["keys"] = sorted(str(key) for key in result)[:50]
    elif isinstance(result, list):
        summary["item_count"] = len(result)
    elif isinstance(result, str):
        summary["text_length"] = len(result)
    return summary
