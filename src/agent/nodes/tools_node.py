"""Node: Tool Calling Layer."""

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
    """Only call MCP tools declared in the selected skill allow-list."""
    if name not in skill_tools:
        raise PermissionError(f"Tool {name!r} khong nam trong allow-list skill: {skill_tools}")
    return await ctx.mcp.call_tool(name, args)


async def call_tools(state: AgentState, ctx: NodeContext) -> dict:
    """
    INPUT  : ``intent``, ``active_skill``, ``slots``.
    OUTPUT : ``tool_calls`` [{name,args}] + ``tool_results`` [{name,result}].
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
        resolved = await _guarded_call(ctx, allow, "resolve_project", {"text": term})
        calls.append({"name": "resolve_project", "args": {"text": term}})
        results.append({"name": "resolve_project", "result": resolved})

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

        first = (listings or [None])[0] if isinstance(listings, list) else None
        if first and first.get("id"):
            ctas = await _guarded_call(ctx, allow, "listing_cta_actions", {"listing_id": first["id"]})
            calls.append({"name": "listing_cta_actions", "args": {"listing_id": first["id"]}})
            results.append({"name": "listing_cta_actions", "result": ctas})

        cot.append(f"tools: called {[c['name'] for c in calls]}")

    elif intent == "US4_ANALYTICS":
        project_id = slots.get("project_id")

        if not project_id:
            project_query = slots.get("project_query", "")
            resolved = await _guarded_call(ctx, allow, "resolve_project", {"text": project_query})
            calls.append({"name": "resolve_project", "args": {"text": project_query}})
            results.append({"name": "resolve_project", "result": resolved})

            if isinstance(resolved, dict) and resolved.get("matched"):
                project_id = resolved["project"]["id"]
            else:
                cot.append("tools: resolve_project returned candidates or no match")
                return {
                    "tool_calls": calls,
                    "tool_results": results,
                    "needs_clarification": True,
                    "cot": cot,
                }

        overview = await _guarded_call(ctx, allow, "project_overview", {"project_id": project_id})
        calls.append({"name": "project_overview", "args": {"project_id": project_id}})
        results.append({"name": "project_overview", "result": overview})
        cot.append(f"tools: called {[c['name'] for c in calls]}")

    else:
        cot.append(f"tools: intent {intent} has no tool branch yet")

    return {"tool_calls": calls, "tool_results": results, "cot": cot}
