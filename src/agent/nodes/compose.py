"""Node: Response Composer + UI actions/CTA.  [TODO stub — US1 tối thiểu]

PRD bước 6. Sinh text trả lời + `actions` cho UI (cards/form/map/cta/clarify)
+ đẩy các bước reasoning vào `cot` (để stream response.reasoning.delta).

Xem docs/ARCHITECTURE.md §7 để biết mapping action -> UI.
"""

from __future__ import annotations

import json
from typing import Any

from agent.nodes.context import NodeContext
from agent.state import AgentState


def _result(results: list[dict], name: str) -> Any:
    for r in results:
        if r.get("name") == name:
            res = r.get("result")
            # Tự động parse JSON nếu MCP trả về TextContent dạng list[dict(type='text', text='...')]
            if isinstance(res, list) and res and isinstance(res[0], dict) and res[0].get("type") == "text":
                text_val = res[0].get("text", "")
                if text_val.strip().startswith("{") or text_val.strip().startswith("["):
                    try:
                        return json.loads(text_val)
                    except Exception:
                        pass
                return text_val
            elif isinstance(res, str) and (res.strip().startswith("{") or res.strip().startswith("[")):
                try:
                    return json.loads(res)
                except Exception:
                    pass
            return res
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

    # Nhánh clarify: thiếu slot -> hỏi lại kèm gợi ý.
    if state.get("needs_clarification"):
        skill = ctx.skills.by_name(state.get("active_skill") or "")
        prompt = (skill.clarify_prompt if skill else None) or "Dạ anh/chị muốn tìm ở dự án nào ạ?"
        actions.append({"type": "clarify", "prompt": prompt, "suggestions": []})
        cot.append("compose: hỏi làm rõ slot")
        return {"response_text": prompt, "actions": actions, "cot": cot}

    # Nhánh có kết quả (US1).
    results = state.get("tool_results", [])
    intent = state.get("intent")

    # Nhánh US6: So sánh Bất Động Sản (US6_COMPARE)
    if intent == "US6_COMPARE":
        compare_data = _result(results, "compare_listings")
        if isinstance(compare_data, dict) and compare_data.get("listings"):
            listings = compare_data["listings"]
            # Đảm bảo sắp xếp các căn theo thứ tự giá tăng dần
            sorted_listings = sorted(listings, key=lambda x: (x.get("price_vnd") or 0))

            compare_payload = {
                "listings": sorted_listings,
                "fields": compare_data.get("fields", [
                    "price_vnd",
                    "price_per_m2_vnd",
                    "area_m2",
                    "bedrooms",
                    "bathrooms",
                    "floor_num",
                    "property_type",
                    "direction_balcony",
                    "view",
                    "legal_status",
                    "furnishing",
                ]),
                "context": compare_data.get("context", {"same_project": True, "same_province": True}),
                "deltas": compare_data.get("deltas", {}),
                "highlights": compare_data.get("highlights", {}),
            }

            # Bổ sung thông tin tiện ích & thời gian di chuyển (OSM/OSRM)
            amenities_data = _result(results, "compare_nearby_amenities")
            if isinstance(amenities_data, dict) and "listings_amenities" in amenities_data:
                compare_payload["amenities"] = amenities_data["listings_amenities"]
            elif isinstance(amenities_data, list):
                compare_payload["amenities"] = amenities_data

            actions.append({"type": "compare", "data": compare_payload})

            # Nút CTA điều hướng nhanh
            cta_items = [
                {"type": "button", "label": "Đặt lịch xem căn", "action": "visit_schedule"},
                {"type": "button", "label": "Nhận tư vấn chi tiết", "action": "consult_expert"},
            ]
            actions.append({"type": "cta", "items": cta_items})

            has_estimate = any(l.get("price_type") == "estimate" for l in sorted_listings)
            has_asking = any(l.get("price_type") == "asking" for l in sorted_listings)

            price_note = ""
            if has_estimate and has_asking:
                price_note = " (Lưu ý: danh sách gồm cả giá chào bán thực tế và giá ước tính tham khảo)."
            elif has_estimate:
                price_note = " (Lưu ý: giá hiển thị là giá ước tính tham khảo do nguồn phân tích tính toán)."

            text = (
                f"Dạ em gửi anh/chị bảng so sánh chi tiết giữa {len(sorted_listings)} căn hộ "
                f"theo thứ tự giá tăng dần bên dưới ạ{price_note}. "
                f"Anh/chị xem chi tiết các thông số kỹ thuật để có lựa chọn phù hợp nhất nhé!"
            )
        else:
            text = "Dạ hiện em chưa tìm thấy dữ liệu để so sánh các căn này. Anh/chị kiểm tra lại mã căn giúp em nhé."

        cot.append("compose: dựng bảng so sánh compare + CTA")
        return {"response_text": text, "actions": actions, "cot": cot}

    # Nhánh US1: Tìm kiếm BĐS
    listings = _result(results, "search_listings") or _result(results, "search_listings_by_province") or []
    ctas = _result(results, "listing_cta_actions") or {}

    if isinstance(listings, list) and listings:
        actions.append({"type": "cards", "items": listings})
        if isinstance(ctas, dict) and ctas.get("ctas"):
            actions.append({"type": "cta", "items": ctas["ctas"]})
        elif isinstance(ctas, list) and ctas:
            actions.append({"type": "cta", "items": ctas})
        text = f"Dạ em tìm thấy {len(listings)} kết quả phù hợp ạ."
        if len(listings) > 3:
            text += ' Anh/chị bấm "Xem tất cả" để xem thêm nhé.'
    else:
        text = "Dạ hiện em chưa tìm thấy kết quả phù hợp. Anh/chị thử đổi tiêu chí giúp em ạ?"

    cot.append("compose: dựng text + actions từ kết quả tool")
    return {"response_text": text, "actions": actions, "cot": cot}
