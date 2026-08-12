"""OpenAI-compatible I/O — cho phép client OpenAI SDK (mọi ngôn ngữ) dùng agent. [DONE]

Mục tiêu: `POST /v1/chat/completions` nhận & trả đúng shape của OpenAI Chat
Completions, để `openai` SDK (Python/JS/Go/...) gọi được mà không cần code riêng.

- Non-stream  → object `chat.completion`  (choices[0].message.content = câu trả lời).
- Stream      → chuỗi `chat.completion.chunk` (choices[0].delta.content), kết bằng `[DONE]`.

Dữ liệu miền (chain-of-thought, MCP tool call, UI actions) được mang kèm mà KHÔNG phá
tính tương thích:
- `reasoning` → cũng đẩy vào `delta.reasoning_content` (quy ước phổ biến của nhiều
  OpenAI-compatible server; OpenAI SDK giữ field lạ, client đọc được nếu muốn).
- MCP tool call + actions → nhét trong field mở rộng `agent` của message/chunk
  (OpenAI SDK bỏ qua field không biết, nhưng vẫn parse được JSON → client nâng cao đọc).

Xem docs/OPENAI_COMPAT.md.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, AsyncIterator

from agent.events import (
    ActionEvent,
    MCPToolCallArguments,
    MCPToolCallCompleted,
    OutputTextDelta,
    ReasoningDelta,
    ResponseDone,
)
from agent.runner import run_stream


def _now() -> int:
    return int(time.time())


def _completion_id() -> str:
    return f"chatcmpl-{uuid.uuid4().hex[:24]}"


def extract_last_user_message(messages: list[dict[str, Any]]) -> str:
    """Lấy nội dung message user cuối cùng từ mảng messages kiểu OpenAI."""
    for m in reversed(messages or []):
        if m.get("role") == "user":
            content = m.get("content", "")
            # content có thể là str hoặc list parts (OpenAI vision-style).
            if isinstance(content, list):
                return " ".join(
                    p.get("text", "") for p in content if isinstance(p, dict)
                ).strip()
            return str(content)
    return ""


def to_chat_completion(payload: dict[str, Any], model: str) -> dict[str, Any]:
    """Map payload non-stream của agent → object `chat.completion` (OpenAI)."""
    agent_data = {
        "intent": payload.get("intent"),
        "tool_calls": payload.get("tool_calls", []),
        "actions": payload.get("actions", []),
    }
    if "reasoning" in payload:
        agent_data["reasoning"] = payload["reasoning"]

    return {
        "id": _completion_id(),
        "object": "chat.completion",
        "created": _now(),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": payload.get("text", ""),
                    # Field mở rộng: client thường (OpenAI SDK) bỏ qua, client nâng cao đọc được.
                    "agent": agent_data,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _chunk(completion_id: str, model: str, delta: dict[str, Any],
           finish_reason: str | None = None) -> dict[str, Any]:
    return {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": _now(),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }


async def stream_chat_completion_chunks(
    graph,
    message: str,
    thread_id: str,
    model: str,
    *,
    include_reasoning: bool = False,
) -> AsyncIterator[dict[str, Any]]:
    """Chạy graph, yield dict `chat.completion.chunk` (chưa serialize SSE).

    Ánh xạ event nội bộ → delta OpenAI:
      - ReasoningDelta          → delta.reasoning_content  (+ agent.reasoning)
      - MCPToolCall*            → agent.mcp_tool_call       (không có content)
      - OutputTextDelta         → delta.content
      - ActionEvent             → agent.action
      - ResponseDone            → chunk cuối, finish_reason="stop"
    """
    cid = _completion_id()

    # Chunk mở màn: role assistant (chuẩn OpenAI: chunk đầu set role).
    yield _chunk(cid, model, {"role": "assistant", "content": ""})

    async for ev in run_stream(
        graph, message, thread_id, include_reasoning=include_reasoning
    ):
        if isinstance(ev, ReasoningDelta):
            yield _chunk(cid, model, {
                "reasoning_content": ev.delta,
                "agent": {"type": "reasoning", "delta": ev.delta},
            })
        elif isinstance(ev, MCPToolCallArguments):
            yield _chunk(cid, model, {
                "agent": {"type": "mcp_tool_call.arguments",
                          "name": ev.name, "arguments": ev.arguments},
            })
        elif isinstance(ev, MCPToolCallCompleted):
            yield _chunk(cid, model, {
                "agent": {"type": "mcp_tool_call.completed",
                          "name": ev.name, "result": ev.result},
            })
        elif isinstance(ev, OutputTextDelta):
            yield _chunk(cid, model, {"content": ev.delta})
        elif isinstance(ev, ActionEvent):
            yield _chunk(cid, model, {"agent": {"type": "action", "action": ev.action}})
        elif isinstance(ev, ResponseDone):
            yield _chunk(cid, model, {}, finish_reason="stop")
