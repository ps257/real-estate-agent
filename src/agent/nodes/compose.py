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
    for name in ("start_visit_booking", "start_consultation", "resolve_project"):
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

    text = f"Dạ em tìm thấy {len(listings)} kết quả phù hợp ạ."
    if len(listings) > 3:
        text += ' Anh/chị bấm "Xem tất cả" để xem thêm nhé.'
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


def _c_us3_policy(results: list[dict], state: AgentState) -> tuple[str, list[dict]]:
    answer = _result(results, "answer_project_policy")

    # RAG chưa bật (hoặc lỗi) -> TỪ CHỐI, không bịa. PRD: hallucination < 1%.
    if not isinstance(answer, dict) or answer.get("available") is False:
        return (
            "Dạ phần hỏi đáp chính sách theo tài liệu dự án hiện chưa sẵn sàng ạ. "
            "Em xin phép nối anh/chị với tư vấn viên để được trả lời chính xác ạ.",
            [{"type": "clarify", "prompt": "Anh/chị muốn em nối tư vấn viên chứ ạ?",
              "suggestions": [{"label": "Nối tư vấn viên", "intent": "US2_2_CONSULT"}]}],
        )

    # Retrieval dưới ngưỡng -> cũng từ chối (quy tắc trong project-policy-rag.md).
    if not answer.get("confident"):
        return (
            "Dạ thông tin này em chưa tìm thấy trong tài liệu của dự án ạ. "
            "Em xin phép nối anh/chị với tư vấn viên để tránh trả lời sai ạ.",
            [{"type": "clarify", "prompt": "Anh/chị muốn em nối tư vấn viên chứ ạ?",
              "suggestions": [{"label": "Nối tư vấn viên", "intent": "US2_2_CONSULT"}]}],
        )

    return answer.get("answer", ""), [
        {"type": "sources", "items": answer.get("sources", [])}
    ]


def _c_us4_analytics(results: list[dict], state: AgentState) -> tuple[str, list[dict]]:
    overview = _result(results, "project_overview")
    if not isinstance(overview, dict):
        return "Dạ em chưa lấy được số liệu tổng quan của dự án ạ.", []
    return (
        f"Dạ đây là tổng quan {_project_name(results)} ạ.",
        [{"type": "overview", "overview": overview}],
    )


def _c_us5_map(results: list[dict], state: AgentState) -> tuple[str, list[dict]]:
    points = _result(results, "map_listings")
    if not isinstance(points, dict):
        return "Dạ em chưa lấy được dữ liệu bản đồ của dự án ạ.", []
    return "Dạ đây là bản đồ các căn của dự án ạ.", [{"type": "map", "map": points}]


def _c_us6_compare(results: list[dict], state: AgentState) -> tuple[str, list[dict]]:
    comparison = _result(results, "compare_listings")
    if not isinstance(comparison, dict) or not comparison.get("listings"):
        return "Dạ em chưa so sánh được các căn anh/chị chọn ạ.", []
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
    "US3_POLICY": _c_us3_policy,
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

    # 1) Guardrail: input out-of-scope -> từ chối lịch sự + gợi ý lối đi khác.
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

    # 2) Thiếu slot -> hỏi lại. conversation/tools soạn sẵn câu hỏi + gợi ý khi
    #    biết cụ thể thiếu gì; không có thì lùi về clarify_prompt của skill.
    if state.get("needs_clarification"):
        skill = ctx.skills.by_name(state.get("active_skill") or "")
        clarify = state.get("clarify") or {}
        prompt = (
            clarify.get("prompt")
            or (skill.clarify_prompt if skill else None)
            or "Dạ anh/chị muốn tìm ở dự án nào ạ?"
        )
        actions.append({
            "type": "clarify",
            "prompt": prompt,
            "suggestions": clarify.get("suggestions", []),
        })
        cot.append("compose: hỏi làm rõ slot")
        return {"response_text": prompt, "actions": actions, "cot": cot}

    # 3) Dựng câu trả lời theo intent.
    intent = state.get("intent") or ""
    composer = _COMPOSERS.get(intent)
    if composer is None:
        cot.append(f"compose: intent {intent!r} không có composer")
        return {
            "response_text": "Dạ em chưa hỗ trợ yêu cầu này ạ.",
            "actions": [],
            "cot": cot,
        }

    text, actions = composer(state.get("tool_results", []), state)
    cot.append(f"compose: dựng {[a['type'] for a in actions] or 'text'} cho {intent}")
    return {"response_text": text, "actions": actions, "cot": cot}
