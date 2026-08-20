"""Node: Conversation Manager — slot-filling.  [DONE]

PRD bước 4. Người gác cổng của graph: quyết định đã đủ thông tin để gọi tool
chưa, hay phải hỏi lại khách. Mục tiêu PRD: số lượt hỏi làm rõ trung bình < 2.

Ba việc:
  1. Dịch ``entities`` (cái khách NÓI) sang ``slots`` (cái skill CẦN).
  2. Resolve tên dự án -> ``project_id`` qua MCP, cho 5 skill đòi id.
  3. Đối chiếu ``skill.required_slots``, thiếu thì soạn câu hỏi lại kèm gợi ý.

Vì sao resolve ở ĐÂY chứ không ở tools_node: khi tên dự án mơ hồ ("Vinhomes"
khớp 5 dự án), việc đúng là HỎI LẠI — mà hỏi lại là nhiệm vụ của node này. Để
tới tools_node thì tool đã chạy rồi mới phát hiện cần hỏi, quá muộn.
"""

from __future__ import annotations

import logging
from typing import Any

from agent.nodes.context import NodeContext
from agent.state import AgentState

logger = logging.getLogger(__name__)

# Entity chuyển thẳng sang slot làm điều kiện lọc — tên trùng tham số MCP.
_FILTER_KEYS = (
    "property_type",
    "bedrooms",
    "min_bedrooms",
    "max_bedrooms",
    "min_price_vnd",
    "max_price_vnd",
    "min_area_m2",
    "max_area_m2",
    "listing_ids",
    "wants_amenities",
    "include_amenities",
)

# Số gợi ý tối đa hiển thị khi hỏi lại (theo search-real-estate.md).
_MAX_SUGGESTIONS = 3


async def _resolve_project(ctx: NodeContext, allow: list[str], term: str) -> tuple[str | None, list[dict]]:
    """Gọi ``resolve_project``. Trả ``(project_id, candidates)``.

    ``project_id=None`` nghĩa là chưa khớp chắc chắn — xem ``candidates`` để
    biết nên hỏi lại kèm gợi ý hay báo không tìm thấy. Lỗi MCP không raise:
    coi như không khớp, khách sẽ được hỏi lại thay vì nhận lỗi 500.
    """
    if "resolve_project" not in allow:
        logger.warning(
            "conversation: 'resolve_project' không có trong allow-list của skill (%s)",
            allow,
        )
        return None, []
    try:
        resolved = await ctx.mcp.call_tool("resolve_project", {"text": term})
    except Exception as exc:  # noqa: BLE001 — hỏi lại vẫn tốt hơn làm sập lượt chat.
        # PHẢI log: không có dòng này thì lỗi hạ tầng (MCP chết, sai đường dẫn
        # spawn) trông y hệt "không tìm thấy dự án" — khách bị hỏi lại vô hạn mà
        # không ai biết vì sao.
        logger.warning(
            "conversation: resolve_project(%r) lỗi -> coi như chưa khớp: %s: %s",
            term, type(exc).__name__, exc,
        )
        return None, []

    # MCP tool lỗi -> parse_tool_result trả str thay vì dict.
    if not isinstance(resolved, dict):
        logger.warning(
            "conversation: resolve_project(%r) trả %s thay vì dict: %.200s",
            term, type(resolved).__name__, resolved,
        )
        return None, []
    if resolved.get("matched"):
        project = resolved.get("project") or {}
        return project.get("id"), []
    return None, list(resolved.get("candidates") or [])


def _candidate_suggestions(candidates: list[dict]) -> list[dict]:
    """Ứng viên dự án -> nút bấm. ``value`` là thứ frontend gửi lại làm tin nhắn."""
    out = []
    for cand in candidates[:_MAX_SUGGESTIONS]:
        name = cand.get("name")
        if not name:
            continue
        province = cand.get("province")
        out.append(
            {
                "label": f"{name} — {province}" if province else name,
                "value": name,
                "project_id": cand.get("id"),
            }
        )
    return out


async def manage_conversation(state: AgentState, ctx: NodeContext) -> dict:
    """
    INPUT  : ``active_skill``, ``entities`` (+ ``slots`` tích luỹ qua các lượt).
    OUTPUT : ``slots``, ``needs_clarification``, ``clarify`` ({prompt, suggestions}).

    ``needs_clarification=True`` -> graph rẽ sang compose để hỏi lại.
    """
    skill = ctx.skills.by_name(state.get("active_skill") or "")
    entities: dict[str, Any] = state.get("entities") or {}
    # dict() để không mutate state cũ; slots được checkpointer giữ qua các lượt.
    slots: dict[str, Any] = dict(state.get("slots") or {})
    cot = list(state.get("cot", []))

    allow = skill.tools if skill else []
    required = skill.required_slots if skill else []

    # 1) Điều kiện lọc: chuyển thẳng, tên đã trùng tham số MCP.
    for key in _FILTER_KEYS:
        if entities.get(key) is not None:
            slots[key] = entities[key]

    # 2) US1 dùng TÊN (dự án hoặc tỉnh), không cần id.
    name = entities.get("project") or entities.get("province")
    if name:
        slots["project_or_province"] = name

    # 3) 5 skill còn lại đòi project_id — phải resolve tên sang mã.
    clarify: dict[str, Any] | None = None
    if "project_id" in required:
        # Khách nêu tên dự án mới trong lượt này -> resolve lại, đừng dùng id cũ.
        term = entities.get("project")
        if term or "project_id" not in slots:
            term = term or slots.get("project_or_province")
            if term:
                project_id, candidates = await _resolve_project(ctx, allow, term)
                if project_id:
                    slots["project_id"] = project_id
                    cot.append(f"conversation: resolve '{term}' -> {project_id}")
                else:
                    slots.pop("project_id", None)
                    suggestions = _candidate_suggestions(candidates)
                    cot.append(
                        f"conversation: '{term}' chưa khớp chắc chắn "
                        f"({len(candidates)} ứng viên)"
                    )
                    if suggestions:
                        clarify = {
                            "prompt": f"Dạ có nhiều dự án khớp với \"{term}\". "
                                      "Anh/chị chọn giúp em dự án nào ạ?",
                            "suggestions": suggestions,
                        }

    missing = [s for s in required if s not in slots]
    needs = bool(missing)

    # Thiếu slot nhưng chưa có câu hỏi cụ thể -> để compose dùng skill.clarify_prompt.
    if needs and clarify is None:
        clarify = None

    cot.append(
        f"conversation: slots={ {k: v for k, v in slots.items()} }, "
        f"thiếu={missing or 'không'} -> {'hỏi lại' if needs else 'đủ slot'}"
    )
    return {
        "slots": slots,
        "needs_clarification": needs,
        # Trả tường minh để xoá clarify còn sót từ lượt trước (checkpointer giữ state).
        "clarify": clarify if needs else None,
        "cot": cot,
    }
