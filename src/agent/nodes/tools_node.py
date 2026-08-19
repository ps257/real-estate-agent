"""Node: Tool Calling Layer.  [DONE]

PRD bước 5. Gọi MCP tool nằm trong allow-list của skill (``skill.tools``).

Mỗi intent có một handler riêng, tra trong ``_HANDLERS``. Thêm intent mới =
thêm một hàm + một dòng trong bảng, không đụng ``call_tools``.

Node này KHÔNG dùng LLM: intent quyết định gọi tool nào, slots quyết định truyền
tham số gì. Cả hai đã do các node trước lo. Giữ thuần cơ học như vậy để luồng
tường minh, đo được, và allow-list mới có ý nghĩa ràng buộc thật.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from agent.nodes.context import NodeContext
from agent.state import AgentState

logger = logging.getLogger(__name__)

# Slot chuyển thẳng thành tham số lọc của search_listings*. Tên slot == tên
# tham số MCP (xem entities_llm.ExtractedEntities), nên không phải map lại.
_SEARCH_FILTERS = (
    "property_type",
    "bedrooms",
    "min_bedrooms",
    "max_bedrooms",
    "min_price_vnd",
    "max_price_vnd",
    "min_area_m2",
    "max_area_m2",
)

_MAP_FILTERS = (
    "property_type",
    "bedrooms",
    "min_bedrooms",
    "max_bedrooms",
    "min_price_vnd",
    "max_price_vnd",
)

_MAX_SUGGESTIONS = 3


class _ToolRun:
    """Gom việc gọi tool + ghi lại call/result, để handler đọc cho gọn.

    ``calls`` và ``results`` được giữ ĐỒNG CHỈ SỐ — runner.py ghép ``calls[i]``
    với ``results[i]`` khi phát SSE event.
    """

    def __init__(self, ctx: NodeContext, allow: list[str]) -> None:
        self._ctx = ctx
        self._allow = allow
        self.calls: list[dict] = []
        self.results: list[dict] = []
        self.cot: list[str] = []

    async def call(self, name: str, args: dict[str, Any]) -> Any:
        """Gọi tool, chặn nếu ngoài allow-list của skill."""
        if name not in self._allow:
            raise PermissionError(
                f"Tool {name!r} khong nam trong allow-list skill: {self._allow}"
            )
        result = await self._ctx.mcp.call_tool(name, args)
        self.calls.append({"name": name, "args": args})
        self.results.append({"name": name, "result": result})
        return result


def _search_filters(slots: dict) -> dict:
    """Lọc slot thành tham số cho search_listings / search_listings_by_province."""
    return {k: slots[k] for k in _SEARCH_FILTERS if slots.get(k) is not None}


def _suggestions_from(candidates: list[dict]) -> list[dict]:
    """Ứng viên dự án -> nút bấm. Cùng shape với conversation._candidate_suggestions."""
    out = []
    for cand in candidates[:_MAX_SUGGESTIONS]:
        name = cand.get("name")
        if not name:
            continue
        province = cand.get("province")
        out.append({
            "label": f"{name} — {province}" if province else name,
            "value": name,
            "project_id": cand.get("id"),
        })
    return out


# ============================================================ handlers
# Chữ ký chung: (run, slots, state) -> dict | None
# Trả dict = ghi đè thêm vào state (dùng để yêu cầu hỏi lại). None = bình thường.

async def _us1_search(run: _ToolRun, slots: dict, state: AgentState) -> dict | None:
    """US1 — tra cứu theo dự án hoặc tỉnh, kèm CTA."""
    term = slots.get("project_or_province", "")
    filters = _search_filters(slots)

    resolved = await run.call("resolve_project", {"text": term})
    matched = isinstance(resolved, dict) and resolved.get("matched")
    candidates = resolved.get("candidates") or [] if isinstance(resolved, dict) else []

    if matched:
        listings = await run.call(
            "search_listings",
            {"project_id": resolved["project"]["id"], "limit": 10, **filters},
        )
    elif candidates:
        # Tên mơ hồ ("Vinhomes" khớp 5 dự án). search-real-estate.md quy định:
        # hiện tối đa 3 ứng viên cho khách chọn, KHÔNG đoán bừa. Trước đây nhánh
        # này rơi xuống search_listings_by_province(province="Vinhomes") — sai
        # nghiệp vụ vì tên dự án không phải tên tỉnh, và luôn trả rỗng.
        run.cot.append(f"tools: '{term}' khớp {len(candidates)} dự án -> hỏi lại")
        return {
            "needs_clarification": True,
            "clarify": {
                "prompt": f'Dạ có nhiều dự án khớp với "{term}". '
                          "Anh/chị chọn giúp em dự án nào ạ?",
                "suggestions": _suggestions_from(candidates),
            },
        }
    else:
        # Không khớp dự án nào và không có gợi ý -> term có thể là tên tỉnh.
        listings = await run.call(
            "search_listings_by_province", {"province": term, "limit": 10, **filters}
        )

    # CTA cho listing đầu tiên (nếu có).
    first = listings[0] if isinstance(listings, list) and listings else None
    if isinstance(first, dict) and first.get("id"):
        await run.call("listing_cta_actions", {"listing_id": first["id"]})
    return None


async def _us2_1_visit(run: _ToolRun, slots: dict, state: AgentState) -> dict | None:
    """US2.1 — mở form đặt lịch tham quan."""
    await run.call(
        "start_visit_booking",
        {
            "project_id": slots["project_id"],
            "is_authenticated": bool(slots.get("is_authenticated", False)),
        },
    )
    return None


async def _us2_2_consult(run: _ToolRun, slots: dict, state: AgentState) -> dict | None:
    """US2.2 — mở form tư vấn mua nhà."""
    await run.call(
        "start_consultation",
        {
            "project_id": slots["project_id"],
            "is_authenticated": bool(slots.get("is_authenticated", False)),
        },
    )
    return None


async def _us3_detail(run: _ToolRun, slots: dict, state: AgentState) -> dict | None:
    """US3 — xem chi tiết căn hộ."""
    listing_ids = slots.get("listing_ids")
    
    if not listing_ids or not isinstance(listing_ids, list):
        run.cot.append("tools: thiếu listing_ids")
        return None

    args = {"listing_id": listing_ids[0]}
    await run.call("get_listing", args)
    return None


async def _us4_analytics(run: _ToolRun, slots: dict, state: AgentState) -> dict | None:
    """US4 — tổng quan dự án."""
    await run.call("project_overview", {"project_id": slots["project_id"]})
    return None


async def _us5_map(run: _ToolRun, slots: dict, state: AgentState) -> dict | None:
    """US5 — bản đồ căn hộ."""
    project_id = slots.get("project_id")
    term = slots.get("project_or_province")
    listing_ids = slots.get("listing_ids")

    if not project_id and not listing_ids and term:
        resolved = await run.call("resolve_project", {"text": term})
        if isinstance(resolved, dict) and resolved.get("matched"):
            project_id = (resolved.get("project") or {}).get("id")
        elif isinstance(resolved, dict) and resolved.get("candidates"):
            candidates = resolved.get("candidates") or []
            run.cot.append(f"tools: '{term}' khớp {len(candidates)} dự án -> hỏi lại bản đồ")
            return {
                "needs_clarification": True,
                "clarify": {
                    "prompt": f'Dạ có nhiều dự án khớp với "{term}". '
                              "Anh/chị chọn giúp em dự án muốn xem bản đồ ạ?",
                    "suggestions": _suggestions_from(candidates),
                },
            }

    if not project_id and not listing_ids:
        run.cot.append("tools: thiếu project_id/listing_ids/project_or_province cho bản đồ")
        return {
            "needs_clarification": True,
            "clarify": {
                "prompt": "Dạ anh/chị muốn xem bản đồ của dự án nào ạ?",
                "suggestions": [],
            },
        }

    args = {
        "project_id": project_id,
        "listing_ids": listing_ids,
        "limit": 200,
        "include_amenities": bool(
            slots.get("include_amenities", slots.get("wants_amenities", False))
        ),
    }
    args.update({k: slots[k] for k in _MAP_FILTERS if slots.get(k) is not None})
    await run.call(
        "map_listings", args
    )
    return None


async def _us6_compare(run: _ToolRun, slots: dict, state: AgentState) -> dict | None:
    """US6 — so sánh 2-4 căn."""
    listing_ids = slots.get("listing_ids") or []
    if len(listing_ids) < 2:
        run.cot.append(f"tools: chỉ có {len(listing_ids)} căn -> cần ít nhất 2")
        return {
            "needs_clarification": True,
            "clarify": {
                "prompt": "Dạ anh/chị muốn so sánh những căn nào ạ? "
                          "Em cần ít nhất 2 căn để so sánh.",
                "suggestions": [],
            },
        }
    # MCP giới hạn 2-4; cắt bớt còn hơn để tool trả lỗi.
    listing_ids = listing_ids[:4]
    await run.call("compare_listings", {"listing_ids": listing_ids})
    return None


_HANDLERS: dict[str, Callable[[_ToolRun, dict, AgentState], Awaitable[dict | None]]] = {
    "US1_SEARCH": _us1_search,
    "US2_1_VISIT": _us2_1_visit,
    "US2_2_CONSULT": _us2_2_consult,
    "US3_DETAIL": _us3_detail,
    "US4_ANALYTICS": _us4_analytics,
    "US5_MAP": _us5_map,
    "US6_COMPARE": _us6_compare,
}


async def call_tools(state: AgentState, ctx: NodeContext) -> dict:
    """
    INPUT  : ``intent``, ``active_skill``, ``slots``.
    OUTPUT : ``tool_calls`` [{name,args}] + ``tool_results`` [{name,result}].
             Có thể thêm ``needs_clarification``/``clarify`` khi tool phát hiện
             cần hỏi lại (vd tên dự án mơ hồ) — compose sẽ đọc và hỏi.

    Chỉ chạy khi conversation cho đủ slot (needs_clarification=False).
    """
    skill = ctx.skills.by_name(state.get("active_skill") or "")
    intent = state.get("intent") or ""
    slots = state.get("slots") or {}
    cot = list(state.get("cot", []))

    handler = _HANDLERS.get(intent)
    if handler is None:
        cot.append(f"tools: intent {intent!r} không có handler")
        logger.warning("tools: intent %r không có handler", intent)
        return {"tool_calls": [], "tool_results": [], "cot": cot}

    run = _ToolRun(ctx, skill.tools if skill else [])
    override = await handler(run, slots, state)

    cot.extend(run.cot)
    if run.calls:
        cot.append(f"tools: gọi {[c['name'] for c in run.calls]}")

    out: dict[str, Any] = {
        "tool_calls": run.calls,
        "tool_results": run.results,
        "cot": cot,
    }
    if override:
        out.update(override)
    return out
