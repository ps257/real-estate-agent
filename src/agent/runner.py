"""Runner — chạy graph non-stream & stream (SSE Realtime-style). [DONE]

- run_once(): chạy tới END, trả full dict (dùng cho POST /chat).
- run_stream(): async-generator phát các Event mô phỏng OpenAI Realtime
  (dùng cho POST /chat/stream).

Ghi chú: scaffold phát event *sau khi* graph chạy xong (replay từ state) để đơn
giản và deterministic cho student. Muốn TTFT thật (<800ms như PRD), student có thể
chuyển sang graph.astream_events / stream token LLM trực tiếp trong compose.
"""

from __future__ import annotations

import uuid
from typing import Any, AsyncIterator

from agent.events import (
    ActionEvent,
    Event,
    MCPToolCallArguments,
    MCPToolCallCompleted,
    OutputTextDelta,
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
    yield ResponseCreated(response_id=response_id, thread_id=thread_id)

    config = {"configurable": {"thread_id": thread_id}}
    state = await graph.ainvoke(new_state(message, thread_id, intent_override=intent_override), config=config)

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
