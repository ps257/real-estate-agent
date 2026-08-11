"""Node: Conversation Manager - slot filling."""

from __future__ import annotations

from agent.nodes.context import NodeContext
from agent.state import AgentState


async def manage_conversation(state: AgentState, ctx: NodeContext) -> dict:
    """
    INPUT  : ``active_skill``, ``entities`` (+ accumulated ``slots``).
    OUTPUT : ``slots`` + ``needs_clarification``.

    US4 uses a two-step slot: the user gives a project query, then tools_node resolves it to the
    required project_id through MCP. Do not clarify early when a project query is present.
    """
    skill = ctx.skills.by_name(state.get("active_skill") or "")
    entities = state.get("entities", {})
    intent = state.get("intent")
    slots = dict(state.get("slots", {}))

    if intent == "US4_ANALYTICS":
        if entities.get("project"):
            slots["project_query"] = entities["project"]
        if entities.get("project_id"):
            slots["project_id"] = entities["project_id"]
        missing = [] if slots.get("project_query") or slots.get("project_id") else ["project_query"]
    else:
        if entities.get("project") or entities.get("province"):
            slots["project_or_province"] = entities.get("project") or entities.get("province")
        if entities.get("property_type"):
            slots["property_type"] = entities["property_type"]

        required = skill.required_slots if skill else []
        missing = [s for s in required if s not in slots]

    needs = bool(missing)

    cot = list(state.get("cot", []))
    cot.append(
        f"conversation: slots={slots}, missing={missing or 'none'} -> "
        f"{'clarify' if needs else 'ready'}"
    )
    return {"slots": slots, "needs_clarification": needs, "cot": cot}
