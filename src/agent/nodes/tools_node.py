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
    
    raw_res = await ctx.mcp.call_tool(name, args)
    
    import json
    text_content = None
    
    if isinstance(raw_res, str):
        text_content = raw_res
    elif isinstance(raw_res, list) and len(raw_res) > 0:
        first_item = raw_res[0]
        if isinstance(first_item, dict) and "text" in first_item:
            text_content = first_item["text"]
        elif hasattr(first_item, "text"):
            text_content = first_item.text
            
    if text_content is not None:
        try:
            return json.loads(text_content)
        except json.JSONDecodeError:
            return text_content
            
    return raw_res


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
            for key in ["property_type", "bedrooms", "min_price_vnd", "max_price_vnd"]:
                if slots.get(key) is not None:
                    args[key] = slots[key]
            listings = await _guarded_call(ctx, allow, "search_listings", args)
            calls.append({"name": "search_listings", "args": args})
            results.append({"name": "search_listings", "result": listings})
        elif isinstance(resolved, dict) and not resolved.get("matched") and resolved.get("candidates"):
            candidates = resolved["candidates"]
            c_names = [c["name"] for c in candidates]
            prompt = f"Anh/chị đang muốn tìm hiểu về dự án nào trong các dự án sau: {', '.join(c_names)}?"
            cot.append("tools: project ambiguous, need clarification")
            return {
                "tool_calls": calls, 
                "tool_results": results, 
                "cot": cot, 
                "needs_clarification": True, 
                "response_text": prompt
            }
        else:
            args = {"province": term, "limit": 10}
            for key in ["property_type", "bedrooms", "min_price_vnd", "max_price_vnd"]:
                if slots.get(key) is not None:
                    args[key] = slots[key]
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
    elif intent == "US5_MAP":
        term = slots.get("project_or_province", "")
        # 1) resolve xem term có phải dự án không
        resolved = await _guarded_call(ctx, allow, "resolve_project", {"text": term})
        calls.append({"name": "resolve_project", "args": {"text": term}})
        results.append({"name": "resolve_project", "result": resolved})

        if isinstance(resolved, dict) and resolved.get("matched"):
            project_id = resolved["project"]["id"]
            # 2) gọi map_listings với project_id và các bộ lọc
            args = {
                "project_id": project_id, 
                "limit": 200, 
                "include_amenities": slots.get("wants_amenities", False)
            }
            for key in ["property_type", "bedrooms", "min_price_vnd", "max_price_vnd"]:
                if slots.get(key) is not None:
                    args[key] = slots[key]
                    
            map_res = await _guarded_call(ctx, allow, "map_listings", args)
            calls.append({"name": "map_listings", "args": args})
            results.append({"name": "map_listings", "result": map_res})
        elif isinstance(resolved, dict) and not resolved.get("matched") and resolved.get("candidates"):
            candidates = resolved["candidates"]
            c_names = [c["name"] for c in candidates]
            prompt = f"Dạ anh/chị muốn xem bản đồ của dự án nào trong các dự án sau: {', '.join(c_names)}?"
            cot.append("tools: project ambiguous for map, need clarification")
            return {
                "tool_calls": calls, 
                "tool_results": results, 
                "cot": cot, 
                "needs_clarification": True, 
                "response_text": prompt
            }
        else:
            # Nếu không tìm thấy dự án, hỏi lại
            prompt = "Dạ anh/chị muốn xem bản đồ của dự án nào ạ?"
            cot.append("tools: project not found for map view, need clarification")
            return {
                "tool_calls": calls, 
                "tool_results": results, 
                "cot": cot, 
                "needs_clarification": True, 
                "response_text": prompt
            }
        
        cot.append(f"tools: gọi {[c['name'] for c in calls]}")
    else:
        # TODO(student): triển khai tool-calling cho US2.1/2.2/US3/US4/US6.
        #   Theo mẫu US1: chọn tool trong `allow`, build args từ `slots`, _guarded_call.
        cot.append(f"tools: intent {intent} chưa có nhánh (TODO student)")

    return {"tool_calls": calls, "tool_results": results, "cot": cot}
