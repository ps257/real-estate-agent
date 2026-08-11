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


from agent.config import init_llm

async def compose(state: AgentState, ctx: NodeContext) -> dict:
    """
    INPUT  : ``needs_clarification``, ``tool_results``, ``active_skill``.
    OUTPUT : ``response_text`` (str) + ``actions`` (list[dict]).
    """
    cot = list(state.get("cot", []))
    actions: list[dict] = []
    intent = state.get("intent", "")
    results = state.get("tool_results", [])
    
    # Nhánh clarify: thiếu slot -> hỏi lại kèm gợi ý.
    if state.get("needs_clarification"):
        skill = ctx.skills.by_name(state.get("active_skill") or "")
        # Get response from state if guardrail set it
        if state.get("response_text"):
            text = state["response_text"]
        else:
            text = (skill.clarify_prompt if skill else None) or "Dạ anh/chị muốn làm rõ thêm thông tin gì ạ?"
            actions.append({"type": "clarify", "prompt": text, "suggestions": []})
        cot.append("compose: hỏi làm rõ slot")
        return {"response_text": text, "actions": actions, "cot": cot}

    # Xử lý các UI Action tùy theo Intent
    if intent == "US1_SEARCH":
        listings = _result(results, "search_listings") or _result(results, "search_listings_by_province") or []
        ctas = _result(results, "listing_cta_actions") or {}
        if isinstance(listings, list) and listings:
            actions.append({"type": "cards", "items": listings[:3]})
            if len(listings) > 3:
                actions.append({"type": "cta", "items": [{"label": "Xem tất cả", "action": "view_all"}]})
            if isinstance(ctas, dict) and ctas.get("ctas"):
                actions.append({"type": "cta", "items": ctas["ctas"]})

    
    elif intent in ["US2_1_VISIT", "US2_2_CONSULT"]:
        form_spec = _result(results, "start_visit_booking") or _result(results, "start_consultation")
        if form_spec:
            actions.append({"type": "form", "spec": form_spec})
        
        submit_res = _result(results, "submit_booking")
        if submit_res:
            actions.append({"type": "booking_success", "data": submit_res})
    
    elif intent == "US4_ANALYTICS":
        overview = _result(results, "project_overview")
        if overview:
            actions.append({"type": "overview", "data": overview})
    
    elif intent == "US5_MAP":
        map_res = _result(results, "map_listings")
        if map_res:
            actions.append({"type": "map", "data": map_res})
            actions.append({"type": "cta", "items": [
                {"label": "Quay lại danh sách", "action": "US1_SEARCH"},
                {"label": "Đặt lịch đi xem thực tế", "action": "US2_1_VISIT"},
                {"label": "Gọi tư vấn viên", "action": "US2_2_CONSULT"}
            ]})
        comp_res = _result(results, "compare_listings")
        if comp_res:
            actions.append({"type": "compare", "data": comp_res})

    # Dùng LLM sinh text cho tự nhiên
    llm = init_llm(model=ctx.llm_model, temperature=0.3)
    prompt = f"""
    Bạn là trợ lý ảo bất động sản. Hãy viết một câu trả lời ngắn gọn, thân thiện dựa trên dữ liệu sau.
    Chú ý: Khi báo giá, luôn nêu rõ loại giá (price_type: asking - chào bán, estimate - ước tính).
    
    Intent: {intent}
    Tool Results: {results}
    """
    
    try:
        res = await llm.ainvoke(prompt)
        text = res.content if isinstance(res.content, str) else str(res.content)
    except Exception as e:
        cot.append(f"compose: LLM error {e}")
        text = "Dạ đây là thông tin em tìm được ạ."

    cot.append("compose: dựng text + actions từ kết quả tool")
    return {"response_text": text, "actions": actions, "cot": cot}
