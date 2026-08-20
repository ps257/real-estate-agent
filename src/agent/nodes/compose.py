"""Node: Response Composer + UI actions/CTA.  [DONE]

PRD bước 6. Sinh text trả lời + ``actions`` cho UI, và đẩy bước reasoning vào
``cot`` (để stream ``response.reasoning.delta``).

Mapping action -> UI xem docs/ARCHITECTURE.md §7. Mỗi intent một hàm dựng, tra
trong ``_COMPOSERS``.

Ba nhánh chặn trước, theo thứ tự ưu tiên:
  1. guardrail  — input ngoài phạm vi (normalize soạn sẵn lời từ chối)
  2. clarify    — thiếu slot (conversation/tools soạn câu hỏi + gợi ý)
  3. theo intent
"""

from __future__ import annotations

from typing import Any, Callable

from agent.nodes.context import NodeContext
from agent.state import AgentState


def _result(results: list[dict], name: str) -> Any:
    for r in results:
        if r["name"] == name:
            return r["result"]
    return None


def _project_name(results: list[dict], fallback: str = "dự án") -> str:
    """Tên dự án lấy từ bất kỳ tool nào có trả về, để câu trả lời tự nhiên hơn."""
    for name in ("project_overview", "start_visit_booking", "start_consultation", "resolve_project"):
        payload = _result(results, name)
        if isinstance(payload, dict):
            project = payload.get("project")
            if isinstance(project, dict) and project.get("name"):
                return project["name"]
    return fallback


# ============================================================ composers
# Chữ ký chung: (results, state) -> (text, actions)

def _c_us1_search(results: list[dict], state: AgentState) -> tuple[str, list[dict]]:
    listings = (
        _result(results, "search_listings")
        or _result(results, "search_listings_by_province")
        or []
    )
    if not isinstance(listings, list) or not listings:
        return "Dạ hiện em chưa tìm thấy kết quả phù hợp. Anh/chị thử đổi tiêu chí giúp em ạ?", []

    # Bổ sung thông tin dự án/tỉnh từ resolve_project hoặc slots nếu listing thiếu
    res_proj = _result(results, "resolve_project")
    proj_info = res_proj.get("project") if isinstance(res_proj, dict) else None
    fallback_proj_name = proj_info.get("name") if isinstance(proj_info, dict) else (state.get("slots") or {}).get("project")
    fallback_province = proj_info.get("province") if isinstance(proj_info, dict) else (state.get("slots") or {}).get("province")

    for item in listings:
        if isinstance(item, dict):
            if not item.get("project_name") and fallback_proj_name:
                item["project_name"] = fallback_proj_name
            if not item.get("province") and fallback_province:
                item["province"] = fallback_province
            if not item.get("address"):
                parts = [item.get("district"), item.get("province") or fallback_province]
                addr = ", ".join([p for p in parts if p])
                if addr:
                    item["address"] = addr
                elif fallback_proj_name:
                    item["address"] = fallback_proj_name

    actions: list[dict] = [{"type": "cards", "items": listings}]

    # MCP tool lỗi -> parse_tool_result trả str thay vì dict.
    ctas = _result(results, "listing_cta_actions")
    if isinstance(ctas, dict) and ctas.get("ctas"):
        actions.append({"type": "cta", "items": ctas["ctas"]})

    text = f"Dạ em tìm thấy {len(listings)} kết quả phù hợp, đây là {min(len(listings), 10)} căn có giá tốt nhất ạ."
    return text, actions


def _c_form(tool: str, verb: str):
    """Dựng composer cho US2.1/US2.2 — chỉ khác tên tool và động từ."""

    def compose_form(results: list[dict], state: AgentState) -> tuple[str, list[dict]]:
        form = _result(results, tool)
        if not isinstance(form, dict) or not form.get("fields"):
            return f"Dạ em chưa mở được form {verb}. Anh/chị thử lại giúp em ạ?", []
        name = _project_name(results)
        return (
            f"Dạ em mời anh/chị điền thông tin để {verb} tại {name} ạ.",
            [{"type": "form", "form": form}],
        )

    return compose_form


def _c_us3_detail(results: list[dict], state: AgentState) -> tuple[str, list[dict]]:
    listing = _result(results, "get_listing")

    if not isinstance(listing, dict):
        return "Dạ em chưa lấy được chi tiết của căn hộ này ạ.", []

    res_proj = _result(results, "resolve_project")
    proj_info = res_proj.get("project") if isinstance(res_proj, dict) else None
    fallback_proj_name = proj_info.get("name") if isinstance(proj_info, dict) else (state.get("slots") or {}).get("project")
    fallback_province = proj_info.get("province") if isinstance(proj_info, dict) else (state.get("slots") or {}).get("province")

    if not listing.get("project_name") and fallback_proj_name:
        listing["project_name"] = fallback_proj_name
    if not listing.get("province") and fallback_province:
        listing["province"] = fallback_province
    if not listing.get("address"):
        parts = [listing.get("district"), listing.get("province") or fallback_province]
        addr = ", ".join([p for p in parts if p])
        if addr:
            listing["address"] = addr
        elif fallback_proj_name:
            listing["address"] = fallback_proj_name

    title = listing.get("title") or "Bất động sản"
    text = f"Dạ em gửi anh/chị thông tin chi tiết về {title} ạ."
    return text, [{"type": "detail", "listing": listing}]


def _c_us4_analytics(results: list[dict], state: AgentState) -> tuple[str, list[dict]]:
    overview = _result(results, "project_overview")
    if not isinstance(overview, dict):
        return "Dạ em chưa lấy được số liệu tổng quan của dự án ạ.", []
    stats = overview.get("stats") or overview
    project = overview.get("project") or {}
    name = project.get("name") or _project_name(results)
    question = (state.get("normalized_input") or state.get("user_input") or "").casefold()

    def money(value: Any) -> str:
        if not isinstance(value, (int, float)):
            return "chưa có dữ liệu"
        billions = value / 1_000_000_000
        return f"{billions:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " tỷ đồng"

    def area(value: Any) -> str:
        if not isinstance(value, (int, float)):
            return "chưa có dữ liệu"
        return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " m²"

    def integer(value: Any) -> str:
        return f"{int(value or 0):,}".replace(",", ".")

    price = stats.get("price_vnd") or {}
    area_stats = stats.get("area_m2") or {}
    count = stats.get("count")
    property_types = stats.get("by_property_type") or {}
    price_types = stats.get("by_price_type") or {}

    if "cơ cấu" in question or "loại hình" in question:
        labels = {
            "can_ho": "căn hộ", "lien_ke": "liền kề", "shophouse": "shophouse",
            "thuong_mai_dich_vu": "thương mại dịch vụ", "biet_thu_song_lap": "biệt thự song lập",
            "unknown": "loại hình khác",
        }
        ranked = sorted(property_types.items(), key=lambda item: item[1], reverse=True)
        detail = ", ".join(f"{labels.get(key, key)} {value} căn" for key, value in ranked[:5])
        text = f"{name} hiện có cơ cấu nguồn hàng gồm {detail}. Căn hộ đang là nhóm chiếm tỷ trọng lớn nhất."
    elif "nguồn giá" in question or ("giá chào bán" in question and "giá ước tính" in question):
        asking = price_types.get("asking") or {}
        estimate = price_types.get("estimate") or {}
        text = (
            f"Tại {name}, dữ liệu gồm {asking.get('count', 0)} căn có giá chào bán, "
            f"trung bình {money((asking.get('price_vnd') or {}).get('avg'))}; và "
            f"{estimate.get('count', 0)} căn dùng giá ước tính, trung bình "
            f"{money((estimate.get('price_vnd') or {}).get('avg'))}. Hai nhóm giá được tách riêng trên biểu đồ bên dưới."
        )
    elif "thấp nhất" in question or "cao nhất" in question or "khoảng giá" in question:
        text = f"Khoảng giá ghi nhận tại {name} hiện từ {money(price.get('min'))} đến {money(price.get('max'))}."
    elif "diện tích" in question and "giá" in question:
        text = (
            f"Tại {name}, giá trung bình là {money(price.get('avg'))}, trong khoảng "
            f"{money(price.get('min'))}–{money(price.get('max'))}. Diện tích trung bình là "
            f"{area(area_stats.get('avg'))}, dao động từ {area(area_stats.get('min'))} đến {area(area_stats.get('max'))}."
        )
    elif "bao nhiêu căn" in question or "số lượng" in question:
        text = f"{name} hiện ghi nhận {integer(count)} căn, với mức giá trung bình {money(price.get('avg'))}."
    else:
        top_type = max(property_types, key=property_types.get) if property_types else None
        top_count = property_types.get(top_type, 0) if top_type else 0
        text = (
            f"{name} hiện ghi nhận {integer(count)} căn. Giá trung bình {money(price.get('avg'))}, "
            f"diện tích trung bình {area(area_stats.get('avg'))}; nguồn hàng chủ yếu là căn hộ "
            f"({integer(top_count)} căn)."
        )

    return text, [{"type": "overview", "overview": overview}]


def _c_us5_map(results: list[dict], state: AgentState) -> tuple[str, list[dict]]:
    points = _result(results, "map_listings")
    if not isinstance(points, dict):
        return "Dạ em chưa lấy được dữ liệu bản đồ của dự án ạ.", []
    slots = state.get("slots") or {}
    wants_amenities = bool(
        slots.get("include_amenities", slots.get("wants_amenities", False))
    )
    if points.get("amenities"):
        text = "Dạ đây là bản đồ các căn và tiện ích lân cận dự án ạ."
    elif wants_amenities:
        text = (
            "Dạ đây là bản đồ các căn của dự án. Hiện em chưa lấy được danh sách "
            "tiện ích lân cận, anh/chị thử lại sau giúp em ạ."
        )
    else:
        text = "Dạ đây là bản đồ các căn của dự án ạ."
    return text, [{"type": "map", "map": points}]


def _clean_project_name(name: str | None) -> str | None:
    if not name:
        return None
    import re
    cleaned = re.sub(r"^(vhm|oh|bds|batdongsan)\s*:\s*", "", name, flags=re.IGNORECASE).strip()
    return cleaned or None


def _detect_common_project_and_province(listings: list[dict]) -> tuple[str | None, str | None]:
    """Detect if all listings belong to the same project and/or province."""
    if not listings:
        return None, None

    # 1. Province
    provinces = {
        l.get("province")
        for l in listings
        if isinstance(l, dict) and l.get("province")
    }
    common_province = list(provinces)[0] if len(provinces) == 1 else None

    # 2. Project Name
    project_names = {
        _clean_project_name(l.get("project_name"))
        for l in listings
        if isinstance(l, dict) and l.get("project_name")
    }
    project_names.discard(None)

    titles = [
        l.get("title", "")
        for l in listings
        if isinstance(l, dict) and l.get("title")
    ]
    common_project = None

    if len(project_names) == 1:
        common_project = list(project_names)[0]

    if not common_project:
        project_ids = {
            l.get("project_id")
            for l in listings
            if isinstance(l, dict) and l.get("project_id")
        }
        if len(project_ids) == 1 and titles:
            last_segments = [t.split(" - ")[-1].strip() for t in titles if " - " in t]
            if last_segments and len(set(last_segments)) == 1:
                common_project = last_segments[0]
            else:
                pid = list(project_ids)[0]
                clean_pid = pid.split(":")[-1] if ":" in pid else pid
                common_project = clean_pid.replace("-", " ").title()

    if not common_project and titles:
        last_segments = [t.split(" - ")[-1].strip() for t in titles if " - " in t]
        if last_segments and len(last_segments) == len(titles) and len(set(last_segments)) == 1:
            common_project = last_segments[0]

    if common_project:
        common_project = _clean_project_name(common_project)

    return common_project, common_province


def _format_short_title(listing: dict, common_project: str | None = None) -> str:
    title = listing.get("title") or listing.get("id") or "Căn hộ"
    if common_project and f" - {common_project}" in title:
        title = title.replace(f" - {common_project}", "")
    elif " - Vinhomes Ocean Park" in title:
        title = title.replace(" - Vinhomes Ocean Park", "")
    elif " - Vinhomes Grand Park" in title:
        title = title.replace(" - Vinhomes Grand Park", "")
    elif " - Vinhomes Smart City" in title:
        title = title.replace(" - Vinhomes Smart City", "")
    elif " - Imperia Smart City" in title:
        title = title.replace(" - Imperia Smart City", "")
    return title.strip()


def _format_listing_titles_for_intro(listings: list[dict], common_project: str | None = None) -> str:
    if not listings:
        return ""
    items = []
    for l in listings:
        if isinstance(l, dict):
            t = _format_short_title(l, common_project).replace(", khu ", " khu ")
            items.append((t, l))

    raw_titles = [t for t, _ in items]
    formatted = []
    for t, l in items:
        if raw_titles.count(t) > 1 and l.get("price_vnd"):
            p_val = l["price_vnd"] / 1e9
            p_str = f"{p_val:.2f}".rstrip("0").rstrip(".") + " tỷ"
            formatted.append(f"{t} ({p_str})")
        else:
            formatted.append(t)

    if len(formatted) <= 1:
        return formatted[0] if formatted else ""
    if len(formatted) == 2:
        return f"{formatted[0]} và {formatted[1]}"
    return f"{', '.join(formatted[:-1])} và {formatted[-1]}"


def _format_location_phrase(common_project: str | None, common_province: str | None) -> str:
    if common_project and common_province:
        return f"tại dự án {common_project} ({common_province})"
    if common_project:
        return f"tại dự án {common_project}"
    if common_province:
        return f"tại khu vực {common_province}"
    return "anh/chị lựa chọn"


def _is_missing(val) -> bool:
    if val is None:
        return True
    s = str(val).strip().lower()
    return s in ("", "none", "null", "k", "khong", "k_co", "0", "-", "unknown", "chua_ro")


def _generate_comparison_summary(listings: list[dict], category: str, common_project: str | None = None) -> str:
    if not listings or len(listings) < 2:
        return ""

    def st_item(l: dict) -> str:
        t = _format_short_title(l, common_project)
        return t if t.lower().startswith("căn ") else f"căn {t}"

    if category == "financial_legal":
        valid_prices = [l for l in listings if isinstance(l, dict) and l.get("price_vnd") and l["price_vnd"] > 0]
        if len(valid_prices) >= 2:
            min_p = min(valid_prices, key=lambda x: x["price_vnd"])
            max_p = max(valid_prices, key=lambda x: x["price_vnd"])
            diff = max_p["price_vnd"] - min_p["price_vnd"]
            if diff >= 1e9:
                diff_val = diff / 1e9
                diff_str = f"{diff_val:.2f}".rstrip("0").rstrip(".") + " tỷ đồng"
                return f"Về tài chính và pháp lý, các căn có mức giá chênh lệch đáng kể khoảng {diff_str}, trong khi đơn giá, tình trạng pháp lý và hiện trạng sử dụng có sự khác biệt giữa các căn."

        return "Về tài chính và pháp lý, mức giá và đơn giá giữa các căn khá tương đồng, trong khi tình trạng pháp lý và hiện trạng sử dụng có sự khác biệt giữa các căn."

    if category == "space_interior":
        return "Về không gian và nội thất, các căn chủ yếu khác biệt ở loại phòng, số phòng vệ sinh, vị trí tầng, tầm nhìn view và mức độ hoàn thiện nội thất."

    return ""


_PROJECT_HIGHLIGHTS: dict[str, tuple[str, str]] = {
    "ocean-park": (
        "Gia Lâm, Hà Nội",
        "không gian sống sinh thái đại đô thị biển hồ, hồ nước ngọt 24.5ha và hệ sinh thái tiện ích all-in-one đẳng cấp",
    ),
    "ocean park": (
        "Gia Lâm, Hà Nội",
        "không gian sống sinh thái đại đô thị biển hồ, hồ nước ngọt 24.5ha và hệ sinh thái tiện ích all-in-one đẳng cấp",
    ),
    "smart-city": (
        "Nam Từ Liêm, Hà Nội",
        "quy mô đại đô thị thông minh, công viên trung tâm 10.2ha cùng chuỗi tiện ích đa dạng",
    ),
    "smart city": (
        "Nam Từ Liêm, Hà Nội",
        "quy mô đại đô thị thông minh, công viên trung tâm 10.2ha cùng chuỗi tiện ích đa dạng",
    ),
    "imperia": (
        "Nam Từ Liêm, Hà Nội",
        "vị trí trung tâm đại đô thị thông minh phía Tây, công viên cảnh quan và chuỗi tiện ích cao cấp",
    ),
    "sola park": (
        "Nam Từ Liêm, Hà Nội",
        "vị trí đắc địa tại đại đô thị thông minh phía Tây cùng không gian sống xanh năng động",
    ),
    "grand-park": (
        "TP. Thủ Đức, TP. Hồ Chí Minh",
        "đại công viên 36ha hàng đầu Đông Nam Á và không gian sống xanh hiện đại",
    ),
    "grand park": (
        "TP. Thủ Đức, TP. Hồ Chí Minh",
        "đại công viên 36ha hàng đầu Đông Nam Á và không gian sống xanh hiện đại",
    ),
    "amber-riverside": (
        "Hai Bà Trưng, Hà Nội",
        "vị trí kết nối thuận tiện ven sông Hồng cùng hệ tiện ích nội khu đầy đủ",
    ),
    "amber riverside": (
        "Hai Bà Trưng, Hà Nội",
        "vị trí kết nối thuận tiện ven sông Hồng cùng hệ tiện ích nội khu đầy đủ",
    ),
}


def _get_project_highlight(project_name: str, province: str | None = None) -> tuple[str, str]:
    name_low = project_name.lower()
    for k, (loc, hl) in _PROJECT_HIGHLIGHTS.items():
        if k in name_low:
            return loc, hl
    loc = province or "khu vực trung tâm"
    return loc, "vị trí kết nối thuận lợi cùng hệ thống hạ tầng và tiện ích dịch vụ đồng bộ"


def _c_us6_compare(
    tool_results: list[dict], state: AgentState
) -> tuple[str, list[dict]]:
    """US6: So sánh BĐS."""
    comparison = _result(tool_results, "compare_listings")
    if not isinstance(comparison, dict) or not comparison.get("listings"):
        return "Dạ em chưa lấy được dữ liệu so sánh các căn hộ.", []
    
    comparison = dict(comparison)
    comparison["listings"] = sorted(
        comparison["listings"],
        key=lambda listing: (
            listing.get("price_vnd") is None,
            listing.get("price_vnd") or 0,
        ) if isinstance(listing, dict) else (True, 0),
    )
    n = len(comparison["listings"])

    common_project, common_province = _detect_common_project_and_province(comparison["listings"])
    loc_phrase = _format_location_phrase(common_project, common_province)

    # Lấy tên căn rút gọn để hiển thị tự nhiên
    titles_str = _format_listing_titles_for_intro(comparison["listings"], common_project)

    listing_ids = [
        l.get("id")
        for l in comparison["listings"]
        if isinstance(l, dict) and l.get("id")
    ]
    ids_str = ", ".join(listing_ids)

    def st_item(l: dict) -> str:
        t = _format_short_title(l, common_project)
        return t if t.lower().startswith("căn ") else f"căn {t}"

    user_msg = (state.get("user_input") or state.get("normalized_input") or "").lower()
    is_financial = any(w in user_msg for w in ["tài chính", "pháp lý", "phap ly", "tai chinh"])
    is_space = any(w in user_msg for w in ["không gian", "nội thất", "khong gian", "noi that", "phòng ngủ", "toilet"])

    if is_financial:
        summary = _generate_comparison_summary(comparison["listings"], "financial_legal", common_project)
        actions = [
            {
                "type": "compare",
                "category": "financial_legal",
                "title": "Thông số Tài chính & Pháp lý",
                "comparison": comparison,
            },
            {
                "type": "cta",
                "items": [
                    {
                        "label": "So sánh không gian & nội thất",
                        "value": f"So sánh chi tiết về không gian và nội thất giữa các căn: {ids_str}",
                        "display_text": f"So sánh chi tiết về không gian và nội thất giữa các căn: {titles_str}",
                        "intent": "US6_COMPARE",
                    },
                    {"label": "Xem trên bản đồ", "intent": "US5_MAP"},
                    {"label": "Đặt lịch tham quan", "intent": "US2_1_VISIT"},
                    {"label": "Tư vấn mua nhà 1:1", "intent": "US2_2_CONSULT"},
                ],
            },
        ]
        return summary, actions

    if is_space:
        summary = _generate_comparison_summary(comparison["listings"], "space_interior", common_project)
        actions = [
            {
                "type": "compare",
                "category": "space_interior",
                "title": "Thông số Không gian & Nội thất",
                "comparison": comparison,
            },
            {
                "type": "cta",
                "items": [
                    {
                        "label": "So sánh tài chính & pháp lý",
                        "value": f"So sánh chi tiết về tài chính và pháp lý giữa các căn: {ids_str}",
                        "display_text": f"So sánh chi tiết về tài chính và pháp lý giữa các căn: {titles_str}",
                        "intent": "US6_COMPARE",
                    },
                    {"label": "Xem trên bản đồ", "intent": "US5_MAP"},
                    {"label": "Đặt lịch tham quan", "intent": "US2_1_VISIT"},
                    {"label": "Tư vấn mua nhà 1:1", "intent": "US2_2_CONSULT"},
                ],
            },
        ]
        return summary, actions

    # Mặc định: Khái quát ngắn các căn hộ thuộc dự án gì, nằm ở đâu, dự án đó có gì nổi bật
    projects_info: list[tuple[str, str, str]] = []
    seen_projects: set[str] = set()

    for l in comparison["listings"]:
        p_name = l.get("project_name") or l.get("project_title")
        if not p_name and l.get("project_id"):
            p_name = _clean_project_name(l["project_id"])
        if not p_name and common_project:
            p_name = common_project
        if not p_name:
            p_name = "Dự án"

        if p_name not in seen_projects:
            seen_projects.add(p_name)
            loc, hl = _get_project_highlight(p_name, common_province)
            projects_info.append((p_name, loc, hl))

    if len(projects_info) == 1:
        p_name, loc, hl = projects_info[0]
        text = f"Các căn hộ anh/chị đang quan tâm đều thuộc dự án {p_name} tại {loc}, nổi bật với {hl}."
    else:
        p_descs = [f"{p} tại {loc} (nổi bật với {hl})" for p, loc, hl in projects_info]
        text = f"Danh sách đối chiếu gồm các căn hộ thuộc các dự án: {'; '.join(p_descs)}."

    actions = [
        {"type": "cards", "items": comparison["listings"], "is_comparison": True},
        {
            "type": "cta",
            "items": [
                {
                    "label": "So sánh tài chính & pháp lý",
                    "value": f"So sánh chi tiết về tài chính và pháp lý giữa các căn: {ids_str}",
                    "display_text": f"So sánh chi tiết về tài chính và pháp lý giữa các căn: {titles_str}",
                    "intent": "US6_COMPARE",
                },
                {
                    "label": "So sánh không gian & nội thất",
                    "value": f"So sánh chi tiết về không gian và nội thất giữa các căn: {ids_str}",
                    "display_text": f"So sánh chi tiết về không gian và nội thất giữa các căn: {titles_str}",
                    "intent": "US6_COMPARE",
                },
                {"label": "Xem trên bản đồ", "intent": "US5_MAP"},
                {"label": "Đặt lịch tham quan", "intent": "US2_1_VISIT"},
            ],
        },
    ]

    return text, actions


_COMPOSERS: dict[str, Callable[[list[dict], AgentState], tuple[str, list[dict]]]] = {
    "US1_SEARCH": _c_us1_search,
    "US2_1_VISIT": _c_form("start_visit_booking", "đặt lịch tham quan"),
    "US2_2_CONSULT": _c_form("start_consultation", "được tư vấn mua nhà"),
    "US3_DETAIL": _c_us3_detail,
    "US4_ANALYTICS": _c_us4_analytics,
    "US5_MAP": _c_us5_map,
    "US6_COMPARE": _c_us6_compare,
}


async def compose(state: AgentState, ctx: NodeContext) -> dict:
    """
    INPUT  : ``guardrail``, ``needs_clarification``, ``clarify``, ``intent``,
             ``tool_results``, ``active_skill``.
    OUTPUT : ``response_text`` (str) + ``actions`` (list[dict]).
    """
    cot = list(state.get("cot", []))
    actions: list[dict] = []
    fallback_text = ""
    intent = state.get("intent") or ""

    # 1) Guardrail: input out-of-scope -> từ chối lịch sự + gợi ý lối đi khác.
    guardrail = state.get("guardrail")
    if guardrail:
        fallback_text = guardrail["message"]
        actions.append({
            "type": "clarify",
            "prompt": fallback_text,
            "suggestions": guardrail.get("suggestions", []),
        })
        cot.append(f"compose: từ chối theo guardrail '{guardrail['code']}'")
        intent = "guardrail"

    # Intent classifier không dùng được/không đủ chắc: hỏi lại bằng template cố
    # định và dừng trước MCP. Không để LLM tự biến UNKNOWN thành tìm kiếm nhà.
    elif intent == "UNKNOWN":
        fallback_text = (
            "Dạ em chưa xác định được nhu cầu bất động sản của anh/chị. "
            "Anh/chị muốn tìm căn hộ, xem thông tin dự án, phân tích giá "
            "hay đặt lịch tham quan ạ?"
        )
        actions.append({
            "type": "clarify",
            "prompt": fallback_text,
            "suggestions": [
                {"label": "Tìm căn hộ", "intent": "US1_SEARCH"},
                {"label": "Xem tổng quan dự án", "intent": "US4_ANALYTICS"},
                {"label": "Đặt lịch tham quan", "intent": "US2_1_VISIT"},
            ],
        })
        cot.append("compose: hỏi lại vì intent UNKNOWN")

    # 2) Thiếu slot -> hỏi lại. conversation/tools soạn sẵn câu hỏi + gợi ý khi
    #    biết cụ thể thiếu gì; không có thì lùi về clarify_prompt của skill.
    elif state.get("needs_clarification"):
        skill = ctx.skills.by_name(state.get("active_skill") or "")
        clarify = state.get("clarify") or {}
        fallback_text = (
            clarify.get("prompt")
            or (skill.clarify_prompt if skill else None)
            or "Dạ anh/chị muốn tìm ở dự án nào ạ?"
        )
        actions.append({
            "type": "clarify",
            "prompt": fallback_text,
            "suggestions": clarify.get("suggestions", []),
        })
        cot.append("compose: hỏi làm rõ slot")
        intent = "clarify"

    # 3) Dựng câu trả lời theo intent.
    else:
        composer = _COMPOSERS.get(intent)
        if composer is None:
            if intent in ("CHAT", "NONE"):
                cot.append(f"compose: intent {intent!r} không có composer, nhường LLM tự trả lời")
                fallback_text = ""
            else:
                cot.append(f"compose: intent {intent!r} không có composer")
                fallback_text = "Dạ em chưa hỗ trợ yêu cầu này ạ."
        else:
            fallback_text, actions = composer(state.get("tool_results", []), state)
            cot.append(f"compose: dựng {[a['type'] for a in actions] or 'text'} cho {intent}")

    # Guardrail/UNKNOWN dùng thông điệp an toàn cố định; US4/US6 dùng số liệu MCP
    # nguyên bản. Không cho Compose LLM viết lại các nhóm này.
    deterministic = intent in (
        "guardrail", "UNKNOWN", "clarify", "US4_ANALYTICS", "US5_MAP", "US6_COMPARE"
    )
    if ctx.compose_llm and not deterministic:
        text = await ctx.compose_llm.compose_text(state, intent, actions, fallback_text)
        cot.append(f"compose: dùng LLM sinh text cho {intent}")
    else:
        text = fallback_text

    return {"response_text": text, "actions": actions, "cot": cot}
