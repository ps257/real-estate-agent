"""Node: Response Composer + UI actions/CTA.  [TODO stub — US1 tối thiểu]

PRD bước 6. Sinh text trả lời + `actions` cho UI (cards/form/map/cta/clarify)
+ đẩy các bước reasoning vào `cot` (để stream response.reasoning.delta).

Xem docs/ARCHITECTURE.md §7 để biết mapping action -> UI.
"""

from __future__ import annotations

from typing import Any

from agent.nodes.context import NodeContext
from agent.state import AgentState


def _result(results: list[dict], name: str) -> Any:
    for r in results:
        if r["name"] == name:
            return r["result"]
    return None


async def compose(state: AgentState, ctx: NodeContext) -> dict:
    """
    INPUT  : ``needs_clarification``, ``tool_results``, ``active_skill``.
    OUTPUT : ``response_text`` (str) + ``actions`` (list[dict]).

    Scaffold: đủ để US1 trả text + cards + cta, và nhánh clarify hỏi lại.
    # TODO(student): compose bằng LLM cho tự nhiên; quy tắc price_type; >3 listing thêm
    #   nút "Xem tất cả"; compose riêng cho US2..US6 (form/map/overview/compare).
    """
    cot = list(state.get("cot", []))
    actions: list[dict] = []

    # Nhánh guardrail: input out-of-scope -> từ chối lịch sự + gợi ý lối đi khác.
    # Node normalize đã soạn sẵn message; đến đây chỉ đóng gói thành action.
    guardrail = state.get("guardrail")
    if guardrail:
        message = guardrail["message"]
        actions.append({
            "type": "clarify",
            "prompt": message,
            "suggestions": guardrail.get("suggestions", []),
        })
        cot.append(f"compose: từ chối theo guardrail '{guardrail['code']}'")
        return {"response_text": message, "actions": actions, "cot": cot}

    # Nhánh clarify: thiếu slot -> hỏi lại kèm gợi ý.
    if state.get("needs_clarification"):
        skill = ctx.skills.by_name(state.get("active_skill") or "")
        prompt = (skill.clarify_prompt if skill else None) or "Dạ anh/chị muốn tìm ở dự án nào ạ?"
        actions.append({"type": "clarify", "prompt": prompt, "suggestions": []})
        cot.append("compose: hỏi làm rõ slot")
        return {"response_text": prompt, "actions": actions, "cot": cot}

    # Nhánh có kết quả (US1).
    results = state.get("tool_results", [])
    listings = _result(results, "search_listings") or _result(results, "search_listings_by_province") or []
    ctas = _result(results, "listing_cta_actions")

    # MCP tool lỗi -> parse_tool_result trả str (thông báo lỗi) thay vì dict/list.
    # Kiểm tra kiểu trước khi dùng, nếu không một tool hỏng sẽ làm sập cả lượt chat.
    if not isinstance(ctas, dict):
        ctas = {}

    if isinstance(listings, list) and listings:
        actions.append({"type": "cards", "items": listings})
        if ctas.get("ctas"):
            actions.append({"type": "cta", "items": ctas["ctas"]})
        text = f"Dạ em tìm thấy {len(listings)} kết quả phù hợp ạ."
        if len(listings) > 3:
            text += ' Anh/chị bấm "Xem tất cả" để xem thêm nhé.'
    else:
        text = "Dạ hiện em chưa tìm thấy kết quả phù hợp. Anh/chị thử đổi tiêu chí giúp em ạ?"

    cot.append("compose: dựng text + actions từ kết quả tool")
    return {"response_text": text, "actions": actions, "cot": cot}
