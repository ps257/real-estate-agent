"""SSE events — mô phỏng OpenAI Realtime server events. [DONE]

Mỗi event có `type` bám ý tưởng Realtime (`response.*`, `*.delta`, `*.done`)
nhưng rút gọn cho use case chat + MCP + chain-of-thought.

Serialize thành khung SSE:  ``event: <type>\\ndata: <json>\\n\\n``

Xem docs/ARCHITECTURE.md §6 để biết bảng event & thứ tự phát điển hình.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field


class Event(BaseModel):
    """Base cho mọi server event."""

    type: str

    def sse(self) -> str:
        """Trả về một khung SSE hoàn chỉnh."""
        payload = self.model_dump(exclude_none=True)
        return f"event: {self.type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


class ResponseCreated(Event):
    type: str = "response.created"
    response_id: str
    thread_id: str


class ReasoningDelta(Event):
    """Một bước chain-of-thought."""

    type: str = "response.reasoning.delta"
    delta: str


class ProgressEvent(Event):
    """Tiến độ xử lý theo node để UI không phải chờ trong im lặng."""

    type: str = "response.progress"
    stage: str
    status: str = "completed"
    message: str
    elapsed_ms: int


class MCPToolCallArguments(Event):
    """Phát ngay trước khi gọi một MCP tool."""

    type: str = "response.mcp_tool_call.arguments"
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class MCPToolCallCompleted(Event):
    """Phát sau khi MCP tool trả kết quả."""

    type: str = "response.mcp_tool_call.completed"
    name: str
    result: Any = None


class OutputTextDelta(Event):
    """Một mẩu token của câu trả lời."""

    type: str = "response.output_text.delta"
    delta: str


class ActionEvent(Event):
    """Một lệnh UI (cards/form/map/cta/clarify...)."""

    type: str = "response.action"
    action: dict[str, Any]


class ResponseDone(Event):
    """Kết thúc — kèm tổng hợp phản hồi (giống payload non-stream)."""

    type: str = "response.done"
    response: dict[str, Any]
