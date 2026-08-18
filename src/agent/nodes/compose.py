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

    return "", [{"type": "detail", "listing": listing}]


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
    return "Dạ đây là bản đồ các căn của dự án ạ.", [{"type": "map", "map": points}]


def _c_us6_compare(results: list[dict], state: AgentState) -> tuple[str, list[dict]]:
    comparison = _result(results, "compare_listings")
    if not isinstance(comparison, dict) or not comparison.get("listings"):
        return "Dạ em chưa so sánh được các căn anh/chị chọn ạ.", []
    amenities = _result(results, "compare_nearby_amenities")
    if amenities:
        comparison = dict(comparison)
        if isinstance(amenities, dict):
            comparison["amenities"] = amenities.get("listings_amenities", amenities)
        else:
            comparison["amenities"] = amenities
    n = len(comparison["listings"])
    # KHÔNG khuyến nghị "căn nào đáng mua hơn" — Out of scope trong PRD.
    return (
        f"Dạ em đặt {n} căn cạnh nhau để anh/chị tiện đối chiếu ạ.",
        [{"type": "compare", "comparison": comparison}],
    )


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

    # Gọi ComposeLLM để sinh văn bản tự nhiên, nếu có
    # US4 đã được dựng hoàn toàn từ số liệu MCP thật. Không gọi LLM thêm lần nữa:
    # tránh paraphrase làm mất số liệu và giảm một network round-trip lớn.
    if ctx.compose_llm and intent != "US4_ANALYTICS":
        text = await ctx.compose_llm.compose_text(state, intent, actions, fallback_text)
        cot.append(f"compose: dùng LLM sinh text cho {intent}")
    else:
        text = fallback_text

    return {"response_text": text, "actions": actions, "cot": cot}
