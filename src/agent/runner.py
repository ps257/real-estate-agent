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
<<<<<<< Updated upstream
import time
from typing import Any, AsyncIterator
=======
from collections.abc import AsyncIterator
from typing import Any
>>>>>>> Stashed changes

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
from agent.telemetry import get_telemetry


def _final_payload(
    state: dict,
    thread_id: str,
    *,
    include_reasoning: bool = False,
    message_id: str | None = None,
    trace_id: str | None = None,
    feedback_token: str | None = None,
) -> dict[str, Any]:
    """Payload tổng hợp — dùng cho non-stream và cho response.done."""
    payload = {
        "thread_id": thread_id,
        "intent": state.get("intent"),
        "text": state.get("response_text", ""),
        "tool_calls": state.get("tool_calls", []),
        "actions": state.get("actions", []),
        "message_id": message_id,
        "trace_id": trace_id,
        "feedback_token": feedback_token,
    }
    if include_reasoning:
        payload["reasoning"] = state.get("cot", [])
    return payload


async def run_once(
    graph,
    message: str,
    thread_id: str,
    *,
    intent_override: str | None = None,
    include_reasoning: bool = False,
    request_message_id: str | None = None,
    user_id: str | None = None,
    transport: str = "native",
) -> dict[str, Any]:
    """Chạy graph, trả full JSON (non-stream)."""
    telemetry = get_telemetry()
    async with telemetry.chat_trace(
        message=message,
        thread_id=thread_id,
        user_id=user_id,
        message_id=request_message_id,
        transport=transport,
        intent_override=intent_override,
    ) as turn:
        config = {"configurable": {"thread_id": thread_id}}
        result = await graph.ainvoke(
            new_state(message, thread_id, intent_override=intent_override), config=config
        )
        payload = _final_payload(
            result,
            thread_id,
            include_reasoning=include_reasoning,
            message_id=turn.message_id,
            trace_id=turn.trace_id,
            feedback_token=turn.feedback_token,
        )
        turn.finish(payload)
        return payload


async def run_stream(
    graph,
    message: str,
    thread_id: str,
    *,
    intent_override: str | None = None,
    include_reasoning: bool = False,
    request_message_id: str | None = None,
    user_id: str | None = None,
    transport: str = "native",
) -> AsyncIterator[Event]:
    """Chạy graph, yield chuỗi Event mô phỏng OpenAI Realtime server events."""
<<<<<<< Updated upstream
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
=======
    telemetry = get_telemetry()
    async with telemetry.chat_trace(
        message=message,
        thread_id=thread_id,
        user_id=user_id,
        message_id=request_message_id,
        transport=transport,
        intent_override=intent_override,
    ) as turn:
        response_id = f"resp_{uuid.uuid4().hex[:12]}"
        yield ResponseCreated(
            response_id=response_id,
            thread_id=thread_id,
            message_id=turn.message_id,
            trace_id=turn.trace_id,
            feedback_token=turn.feedback_token,
        )

        config = {"configurable": {"thread_id": thread_id}}
        state = await graph.ainvoke(
            new_state(message, thread_id, intent_override=intent_override), config=config
        )
>>>>>>> Stashed changes

        # 1) Chain-of-thought is only returned under the explicit debug switch.  It is
        # intentionally never passed to telemetry.
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
            turn.mark_ttft()
            yield OutputTextDelta(delta=chunk)

        # 4) UI actions.
        for action in state.get("actions", []):
            yield ActionEvent(action=action)

        # 5) Done.  Keep the root open while the event is handed to the transport.
        # Success is recorded only after the consumer resumes the generator; a
        # disconnect while sending the final event is therefore still cancellation.
        payload = _final_payload(
            state,
            thread_id,
            include_reasoning=include_reasoning,
            message_id=turn.message_id,
            trace_id=turn.trace_id,
            feedback_token=turn.feedback_token,
        )
        yield ResponseDone(
            response=payload,
            message_id=turn.message_id,
            trace_id=turn.trace_id,
            feedback_token=turn.feedback_token,
        )
        turn.finish(payload)


def _chunk_text(text: str, size: int = 6) -> list[str]:
    """Cắt text thành mẩu ~size từ để mô phỏng output_text.delta."""
    if not text:
        return []
    words = text.split(" ")
    return [" ".join(words[i : i + size]) + (" " if i + size < len(words) else "")
            for i in range(0, len(words), size)]
