"""Node: Response Composer + UI actions/CTA."""

from __future__ import annotations

from typing import Any

from agent.nodes.context import NodeContext
from agent.state import AgentState


def _result(results: list[dict], name: str) -> Any:
    for r in results:
        if r["name"] == name:
            return r["result"]
    return None


def _money(value: int | float | None, *, per_m2: bool = False) -> str | None:
    if value is None:
        return None
    if per_m2:
        return f"{value / 1_000_000:,.1f} triệu VND/m2".replace(",", ".")
    return f"{value / 1_000_000_000:,.2f} tỷ VND".replace(",", ".")


def _range_text(stats: dict, formatter) -> str | None:
    lo = formatter(stats.get("min"))
    hi = formatter(stats.get("max"))
    avg = formatter(stats.get("avg"))
    if not any([lo, hi, avg]):
        return None
    parts = []
    if lo and hi:
        parts.append(f"dao động {lo} - {hi}")
    if avg:
        parts.append(f"trung bình {avg}")
    return ", ".join(parts)


def _top_property_type(by_property_type: dict) -> str | None:
    if not by_property_type:
        return None
    key, count = max(by_property_type.items(), key=lambda item: item[1])
    labels = {
        "can_ho": "căn hộ",
        "lien_ke": "liền kề",
        "shophouse": "shophouse",
        "thuong_mai_dich_vu": "thương mại dịch vụ",
        "biet_thu_song_lap": "biệt thự song lập",
        "biet_thu_tu_lap": "biệt thự tứ lập",
        "biet_thu_don_lap": "biệt thự đơn lập",
        "nha_pho": "nhà phố",
        "unknown": "chưa rõ loại hình",
    }
    return f"{labels.get(key, key)} ({count} listing)"


def _compose_overview(overview: dict) -> tuple[str, list[dict]]:
    project = overview.get("project") or {}
    stats = overview.get("stats") or {}
    actions = [{"type": "overview", "project": project, "stats": stats}]

    name = project.get("name") or project.get("id") or "dự án này"
    place = ", ".join(p for p in [project.get("district"), project.get("province")] if p)
    count = stats.get("count", 0)
    coverage = stats.get("coverage") or {}
    by_price_type = stats.get("by_price_type") or {}

    price_kind = None
    price_stats = None
    if by_price_type.get("asking", {}).get("coverage", {}).get("price_vnd_count"):
        price_kind = "giá chào bán"
        price_stats = by_price_type["asking"].get("price_vnd") or {}
    elif by_price_type.get("estimate", {}).get("coverage", {}).get("price_vnd_count"):
        price_kind = "giá tham khảo do nguồn ước tính"
        price_stats = by_price_type["estimate"].get("price_vnd") or {}
    else:
        price_stats = stats.get("price_vnd") or {}

    lines = [f"Dạ, đây là thống kê mô tả từ các listing hiện có của {name}."]
    if place:
        lines.append(f"Khu vực: {place}.")
    lines.append(f"Hệ thống đang có {count} listing cho dự án này.")

    price_text = _range_text(price_stats or {}, _money)
    if price_text:
        prefix = price_kind or "giá ghi nhận"
        base = f"Về {prefix}, {price_text}"
        used = None
        if price_kind == "giá chào bán":
            used = by_price_type["asking"]["coverage"].get("price_vnd_count")
        elif price_kind == "giá tham khảo do nguồn ước tính":
            used = by_price_type["estimate"]["coverage"].get("price_vnd_count")
        elif coverage.get("price_vnd_count") is not None:
            used = coverage["price_vnd_count"]
        if used is not None:
            base += f" trên {used}/{count} listing có dữ liệu giá"
        lines.append(base + ".")

    ppm2_text = _range_text(stats.get("price_per_m2_vnd") or {}, lambda v: _money(v, per_m2=True))
    if ppm2_text:
        lines.append(f"Giá trên m2 {ppm2_text}.")

    area_text = _range_text(stats.get("area_m2") or {}, lambda v: f"{v:g} m2" if v is not None else None)
    if area_text:
        lines.append(f"Diện tích {area_text}.")

    beds = stats.get("bedrooms_range") or {}
    if beds.get("min") is not None and beds.get("max") is not None:
        lines.append(f"Khoảng phòng ngủ ghi nhận từ {beds['min']} đến {beds['max']} phòng.")

    top_type = _top_property_type(stats.get("by_property_type") or {})
    if top_type:
        lines.append(f"Loại hình phổ biến nhất là {top_type}.")

    lines.append("Các số liệu này không phải thẩm định giá hay khuyến nghị đầu tư.")
    return " ".join(lines), actions


async def compose(state: AgentState, ctx: NodeContext) -> dict:
    """
    INPUT  : ``needs_clarification``, ``tool_results``, ``active_skill``.
    OUTPUT : ``response_text`` + ``actions``.
    """
    cot = list(state.get("cot", []))
    actions: list[dict] = []
    results = state.get("tool_results", [])

    if state.get("needs_clarification"):
        skill = ctx.skills.by_name(state.get("active_skill") or "")
        prompt = (skill.clarify_prompt if skill else None) or "Dạ anh/chị muốn xem dự án nào ạ?"
        resolved = _result(results, "resolve_project") or {}
        suggestions = [
            {"id": p.get("id"), "label": p.get("name") or p.get("id")}
            for p in (resolved.get("candidates") or [])[:3]
            if p.get("id")
        ]
        actions.append({"type": "clarify", "prompt": prompt, "suggestions": suggestions})
        cot.append("compose: clarify missing or ambiguous project")
        return {"response_text": prompt, "actions": actions, "cot": cot}

    overview = _result(results, "project_overview")
    if isinstance(overview, dict):
        text, actions = _compose_overview(overview)
        cot.append("compose: built US4 overview response")
        return {"response_text": text, "actions": actions, "cot": cot}

    listings = _result(results, "search_listings") or _result(results, "search_listings_by_province") or []
    ctas = _result(results, "listing_cta_actions") or {}

    if isinstance(listings, list) and listings:
        actions.append({"type": "cards", "items": listings})
        if ctas.get("ctas"):
            actions.append({"type": "cta", "items": ctas["ctas"]})
        text = f"Dạ em tìm thấy {len(listings)} kết quả phù hợp ạ."
        if len(listings) > 3:
            text += ' Anh/chị bấm "Xem tất cả" để xem thêm nhé.'
    else:
        text = "Dạ hiện em chưa tìm thấy kết quả phù hợp. Anh/chị thử đổi tiêu chí giúp em ạ?"

    cot.append("compose: built response from tool results")
    return {"response_text": text, "actions": actions, "cot": cot}
