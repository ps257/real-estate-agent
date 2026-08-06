"""Test event SSE serialize + OpenAI-compat mapping (hạ tầng, không đụng US1). [DONE]"""

from __future__ import annotations

import json

from agent.events import (
    MCPToolCallArguments,
    OutputTextDelta,
    ReasoningDelta,
    ResponseCreated,
    ResponseDone,
)
from agent.openai_compat import extract_last_user_message, to_chat_completion


def test_event_sse_framing():
    ev = ResponseCreated(response_id="r1", thread_id="t1")
    frame = ev.sse()
    assert frame.startswith("event: response.created\n")
    assert "data: " in frame
    assert frame.endswith("\n\n")
    # data phải là JSON hợp lệ.
    data_line = [l for l in frame.splitlines() if l.startswith("data: ")][0]
    payload = json.loads(data_line[len("data: "):])
    assert payload["type"] == "response.created"
    assert payload["thread_id"] == "t1"


def test_reasoning_and_text_events():
    assert ReasoningDelta(delta="suy nghĩ").type == "response.reasoning.delta"
    assert OutputTextDelta(delta="chào").type == "response.output_text.delta"
    tc = MCPToolCallArguments(name="search_listings", arguments={"limit": 10})
    assert tc.type == "response.mcp_tool_call.arguments"
    assert tc.arguments["limit"] == 10


def test_response_done_carries_payload():
    ev = ResponseDone(response={"text": "xong", "intent": "US1_SEARCH"})
    payload = json.loads(ev.model_dump_json())
    assert payload["response"]["intent"] == "US1_SEARCH"


def test_extract_last_user_message_str_and_parts():
    assert extract_last_user_message(
        [{"role": "user", "content": "xin chào"}]
    ) == "xin chào"
    # content dạng parts kiểu OpenAI vision.
    assert extract_last_user_message(
        [{"role": "user", "content": [{"type": "text", "text": "tìm nhà"}]}]
    ) == "tìm nhà"


def test_to_chat_completion_shape():
    payload = {
        "text": "Dạ em tìm thấy 2 kết quả ạ.",
        "intent": "US1_SEARCH",
        "reasoning": ["b1", "b2"],
        "tool_calls": [{"name": "search_listings", "args": {}}],
        "actions": [{"type": "cards", "items": []}],
    }
    out = to_chat_completion(payload, model="real-estate-agent")
    assert out["object"] == "chat.completion"
    msg = out["choices"][0]["message"]
    assert msg["role"] == "assistant"
    assert msg["content"] == "Dạ em tìm thấy 2 kết quả ạ."
    # Dữ liệu miền nằm ở field mở rộng 'agent'.
    assert msg["agent"]["intent"] == "US1_SEARCH"
    assert out["choices"][0]["finish_reason"] == "stop"
