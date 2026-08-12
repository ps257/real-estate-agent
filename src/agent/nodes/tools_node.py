"""Node: Tool Calling Layer.  [DONE cho US1 — mở rộng cho US khác]

PRD bước 5. Gọi MCP tool nằm trong allow-list của skill (skill.tools).

Scaffold triển khai đầy đủ nhánh US1_SEARCH để pipeline chạy end-to-end với MCP
(hoặc MCP mock trong test). Các US khác: theo mẫu này.
"""

from __future__ import annotations

from typing import Any

from agent.nodes.context import NodeContext
from agent.state import AgentState


async def _guarded_call(
    ctx: NodeContext,
    skill_tools: list[str],
    name: str,
    args: dict[str, Any],
) -> Any:
    """Chỉ cho gọi tool nằm trong allow-list của skill (an toàn + dễ chấm)."""
    if name not in skill_tools:
        raise PermissionError(f"Tool {name!r} khong nam trong allow-list skill: {skill_tools}")
    return await ctx.mcp.call_tool(name, args)


async def call_tools(state: AgentState, ctx: NodeContext) -> dict:
    """
    INPUT  : ``intent``, ``active_skill``, ``slots``.
    OUTPUT : ``tool_calls`` [{name,args}] + ``tool_results`` [{name,result}].

    Chỉ chạy khi conversation cho đủ slot (needs_clarification=False).
    """
    skill = ctx.skills.by_name(state.get("active_skill") or "")
    allow = skill.tools if skill else []
    slots = state.get("slots", {})
    intent = state.get("intent")

    calls: list[dict] = []
    results: list[dict] = []
    cot = list(state.get("cot", []))

    if intent == "US1_SEARCH":
        term = slots.get("project_or_province", "")
        # 1) resolve xem term có phải dự án đã biết không.
        resolved = await _guarded_call(ctx, allow, "resolve_project", {"text": term})
        calls.append({"name": "resolve_project", "args": {"text": term}})
        results.append({"name": "resolve_project", "result": resolved})

        # 2) tuỳ resolve → tìm theo project_id hoặc theo province.
        if isinstance(resolved, dict) and resolved.get("matched"):
            project_id = resolved["project"]["id"]
            args = {"project_id": project_id, "limit": 10}
            if slots.get("property_type"):
                args["property_type"] = slots["property_type"]
            listings = await _guarded_call(ctx, allow, "search_listings", args)
            calls.append({"name": "search_listings", "args": args})
            results.append({"name": "search_listings", "result": listings})
        else:
            args = {"province": term, "limit": 10}
            if slots.get("property_type"):
                args["property_type"] = slots["property_type"]
            listings = await _guarded_call(ctx, allow, "search_listings_by_province", args)
            calls.append({"name": "search_listings_by_province", "args": args})
            results.append({"name": "search_listings_by_province", "result": listings})

        # 3) CTA cho listing đầu tiên (nếu có).
        first = (listings or [None])[0] if isinstance(listings, list) else None
        if first and first.get("id"):
            ctas = await _guarded_call(ctx, allow, "listing_cta_actions", {"listing_id": first["id"]})
            calls.append({"name": "listing_cta_actions", "args": {"listing_id": first["id"]}})
            results.append({"name": "listing_cta_actions", "result": ctas})

        cot.append(f"tools: gọi {[c['name'] for c in calls]}")
    elif intent == "US6_COMPARE":
        listing_ids = slots.get("listing_ids", [])
        if listing_ids:
            compare_data = await _guarded_call(
                ctx, allow, "compare_listings", {"listing_ids": listing_ids}
            )
            calls.append({"name": "compare_listings", "args": {"listing_ids": listing_ids}})
            results.append({"name": "compare_listings", "result": compare_data})

            # Tùy chọn: gọi compare_nearby_amenities nếu có trong allow-list
            if "compare_nearby_amenities" in allow:
                try:
                    amenities_data = await _guarded_call(
                        ctx, allow, "compare_nearby_amenities", {"listing_ids": listing_ids}
                    )
                    if amenities_data:
                        calls.append({"name": "compare_nearby_amenities", "args": {"listing_ids": listing_ids}})
                        results.append({"name": "compare_nearby_amenities", "result": amenities_data})
                except Exception:
                    pass

        cot.append(f"tools: gọi {[c['name'] for c in calls]}")
    else:
        # TODO(student): triển khai tool-calling cho US2.1/2.2/US3/US4/US5.
        #   Theo mẫu US1/US6: chọn tool trong `allow`, build args từ `slots`, _guarded_call.
        cot.append(f"tools: intent {intent} chưa có nhánh (TODO student)")

    return {"tool_calls": calls, "tool_results": results, "cot": cot}
