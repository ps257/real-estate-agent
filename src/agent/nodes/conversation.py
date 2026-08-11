"""Node: Conversation Manager — slot-filling.  [TODO stub]

PRD bước 4. So `required_slots` của skill với slot đã có; thiếu → cần hỏi lại.
Mục tiêu PRD: số lượt hỏi làm rõ trung bình < 2.
"""

from __future__ import annotations

from agent.nodes.context import NodeContext
from agent.state import AgentState

async def manage_conversation(state: AgentState, ctx: NodeContext) -> dict:
    """
    INPUT  : ``active_skill``, ``entities`` (+ ``slots`` tích luỹ qua các lượt).
    OUTPUT : ``slots`` (đã map từ entities) + ``needs_clarification`` (bool).
    """
    cot = list(state.get("cot", []))
    
    # Bỏ qua nếu guardrail chặn
    if state.get("needs_clarification"):
        return {"cot": cot}
        
    skill = ctx.skills.by_name(state.get("active_skill") or "")
    entities = state.get("entities", {})
    slots = dict(state.get("slots", {}))

    # Hỗ trợ US1: nếu có project/province
    if entities.get("project_or_province"):
        slots["project_or_province"] = entities.get("project_or_province")
    if entities.get("province"):
        slots["province"] = entities.get("province")

    # Lưu các entity còn lại vào slots
    for k, v in entities.items():
        if v:
            slots[k] = v

    required = skill.required_slots if skill else []
    missing = [s for s in required if s not in slots]
    needs = bool(missing)

    cot.append(
        f"conversation: slots={slots}, thiếu={missing or 'không'} -> "
        f"{'hỏi lại' if needs else 'đủ slot'}"
    )
    return {"slots": slots, "needs_clarification": needs, "cot": cot}

