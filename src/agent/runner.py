"""Runner — chạy graph non-stream & stream (SSE Realtime-style). [DONE]

- run_once(): chạy tới END, trả full dict (dùng cho POST /chat).
- run_stream(): async-generator phát các Event mô phỏng OpenAI Realtime
  (dùng cho POST /chat/stream).

Tiến độ node được phát trực tiếp trong lúc graph chạy. Text cuối vẫn được chia
thành các delta sau bước compose; vì vậy UI có phản hồi tức thời ngay cả khi LLM
hoặc MCP đang xử lý lâu.
"""

from __future__ import annotations

import uuid
import time
from typing import Any, AsyncIterator

from agent.events import (
    ActionEvent,
    Event,
    MCPToolCallArguments,
    MCPToolCallCompleted,
    OutputTextDelta,
    ProgressEvent,
    ReasoningDelta,
    ResponseCreated,
    ResponseDone,
)
from agent.state import new_state


def _final_payload(
    state: dict, thread_id: str, *, include_reasoning: bool = False
) -> dict[str, Any]:
    """Payload tổng hợp — dùng cho non-stream và cho response.done."""
    payload = {
        "thread_id": thread_id,
        "intent": state.get("intent"),
        "text": state.get("response_text", ""),
        "tool_calls": state.get("tool_calls", []),
        "actions": state.get("actions", []),
    }
    if include_reasoning:
        payload["reasoning"] = state.get("cot", [])
    return payload


async def run_once(
    graph, message: str, thread_id: str, *, intent_override: str | None = None, include_reasoning: bool = False
) -> dict[str, Any]:
    """Chạy graph, trả full JSON (non-stream)."""
    config = {"configurable": {"thread_id": thread_id}}
    result = await graph.ainvoke(new_state(message, thread_id, intent_override=intent_override), config=config)
    return _final_payload(result, thread_id, include_reasoning=include_reasoning)


async def run_stream(
    graph, message: str, thread_id: str, *, intent_override: str | None = None, include_reasoning: bool = False
) -> AsyncIterator[Event]:
    """Chạy graph, yield chuỗi Event mô phỏng OpenAI Realtime server events."""
    response_id = f"resp_{uuid.uuid4().hex[:12]}"
    started = time.perf_counter()
    def elapsed() -> int:
        return round((time.perf_counter() - started) * 1000)
    yield ResponseCreated(response_id=response_id, thread_id=thread_id)
    yield ProgressEvent(
        stage="request", status="active", message="Đang tiếp nhận yêu cầu…", elapsed_ms=elapsed()
    )

    config = {"configurable": {"thread_id": thread_id}}
    state: dict[str, Any] = {}
    progress_messages = {
        "normalize": "Đã kiểm tra phạm vi yêu cầu",
        "intent": "Đã xác định nhu cầu của bạn",
        "entities": "Đã đọc dự án và các tiêu chí cần phân tích",
        "conversation": "Đã chuẩn bị dữ liệu truy vấn",
        "tools": "Đã nhận số liệu mới nhất từ hệ thống",
        "compose": "Đã hoàn thiện câu trả lời",
    }
    active_messages = {
        "intent": "Đang xác định nhu cầu của bạn…",
        "entities": "Đang đọc dự án và các tiêu chí…",
        "conversation": "Đang chuẩn bị dữ liệu truy vấn…",
        "tools": "Đang lấy số liệu mới nhất từ hệ thống…",
        "compose": "Đang tổng hợp câu trả lời…",
    }

    # Stream update ngay khi từng node hoàn tất, thay vì ainvoke xong toàn graph rồi
    # mới replay event. UI nhờ đó thấy tiến độ thật trong lúc LLM/MCP đang chạy.
    async for update in graph.astream(
        new_state(message, thread_id, intent_override=intent_override),
        config=config,
        stream_mode="updates",
    ):
        if not isinstance(update, dict):
            continue
        for node_name, node_update in update.items():
            if isinstance(node_update, dict):
                state.update(node_update)
            progress_message = progress_messages.get(node_name)
            if progress_message:
                yield ProgressEvent(
                    stage=node_name,
                    message=progress_message,
                    elapsed_ms=elapsed(),
                )
                if node_name == "normalize":
                    next_node = "compose" if state.get("guardrail") else "intent"
                elif node_name == "intent":
                    next_node = "entities"
                elif node_name == "entities":
                    next_node = "conversation"
                elif node_name == "conversation":
                    next_node = "compose" if state.get("needs_clarification") else "tools"
                elif node_name == "tools":
                    next_node = "compose"
                else:
                    next_node = None
                if next_node and active_messages.get(next_node):
                    yield ProgressEvent(
                        stage=next_node,
                        status="active",
                        message=active_messages[next_node],
                        elapsed_ms=elapsed(),
                    )

    # 1) Chain-of-thought.
    if include_reasoning:
        for step in state.get("cot", []):
            yield ReasoningDelta(delta=step)

    # 2) MCP tool calls (arguments trước, completed sau — ghép theo thứ tự).
    calls = state.get("tool_calls", [])
    results = state.get("tool_results", [])
    for i, call in enumerate(calls):
        yield MCPToolCallArguments(name=call["name"], arguments=call.get("args", {}))
        res = results[i]["result"] if i < len(results) else None
        yield MCPToolCallCompleted(name=call["name"], result=res)

    # 3) Text trả lời — chunk theo từ để mô phỏng streaming token.
    for chunk in _chunk_text(state.get("response_text", "")):
        yield OutputTextDelta(delta=chunk)

    # 4) UI actions.
    for action in state.get("actions", []):
        yield ActionEvent(action=action)

    # 5) Done.
    yield ResponseDone(
        response=_final_payload(state, thread_id, include_reasoning=include_reasoning)
    )


def _chunk_text(text: str, size: int = 6) -> list[str]:
    """Cắt text thành mẩu ~size từ để mô phỏng output_text.delta."""
    if not text:
        return []
    words = text.split(" ")
    return [" ".join(words[i : i + size]) + (" " if i + size < len(words) else "")
            for i in range(0, len(words), size)]
