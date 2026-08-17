"""AgentState — state trôi qua mọi node của LangGraph. [DONE]

Xem docs/ARCHITECTURE.md §3 để biết ý nghĩa từng field.
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    # Lịch sử hội thoại (reducer add_messages gộp message qua các lượt).
    messages: Annotated[list, add_messages]

    # Khoá phiên — checkpointer + Redis (theo PRD) key theo giá trị này.
    thread_id: str

    # Input lượt hiện tại.
    user_input: str
    normalized_input: str  # sau normalize/guardrail
    intent_override: str | None # intent ép buộc từ UI


    # Guardrail: None = hợp lệ. dict {code, message, suggestions} = out-of-scope
    # (PRD mục "Out of scope") -> graph rẽ thẳng normalize → compose.
    guardrail: dict[str, Any] | None

    # Hiểu ý định & thực thể.
    intent: str | None          # vd "US1_SEARCH"
    entities: dict[str, Any]     # thực thể trích được
    slots: dict[str, Any]        # slot đã điền cho skill hiện tại
    active_skill: str | None     # name của skill được chọn
    needs_clarification: bool    # có phải hỏi lại không
    # Nội dung câu hỏi lại do conversation soạn: {prompt, suggestions}.
    # None = compose tự dùng skill.clarify_prompt.
    clarify: dict[str, Any] | None

    # Tool calling (MCP).
    tool_calls: list[dict[str, Any]]     # [{name, args}]
    tool_results: list[dict[str, Any]]   # [{name, result}]

    # Đầu ra.
    actions: list[dict[str, Any]]   # lệnh UI: cards/form/map/cta/clarify...
    cot: list[str]                  # reasoning steps -> stream response.reasoning.delta
    response_text: str              # text trả lời cuối


def new_state(user_input: str, thread_id: str, intent_override: str | None = None) -> AgentState:
    """Khởi tạo state cho một lượt chat. [DONE]"""
    return AgentState(
        messages=[{"role": "user", "content": user_input}],
        thread_id=thread_id,
        user_input=user_input,
        normalized_input=user_input,
        intent_override=intent_override,
        guardrail=None,
        intent=None,
        entities={},
        # CỐ Ý không đặt slots ở đây. slots không có reducer, nên truyền {} vào
        # sẽ GHI ĐÈ slot mà checkpointer đang giữ từ lượt trước — hội thoại đa
        # lượt ("đặt lịch đi" sau khi đã nói tên dự án) sẽ không bao giờ chạy.
        # Vắng mặt trong dict input = LangGraph giữ nguyên giá trị đã checkpoint.
        active_skill=None,
        needs_clarification=False,
        clarify=None,
        tool_calls=[],
        tool_results=[],
        actions=[],
        cot=[],
        response_text="",
    )
