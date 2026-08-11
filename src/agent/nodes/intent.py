"""Node: Intent Detection.  [TODO stub — hiện hard-code US1 để smoke-test]

PRD bước 2. Phân loại ý định người dùng và chọn skill tương ứng.
Mục tiêu PRD: độ chính xác intent > 95%.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from agent.config import init_llm

from agent.nodes.context import NodeContext
from agent.state import AgentState

# Các intent key hợp lệ (khớp `intent:` trong skills/catalog/*.md).
INTENTS = [
    "US1_SEARCH",
    "US2_1_VISIT",
    "US2_2_CONSULT",
    "US3_POLICY",
    "US4_ANALYTICS",
    "US5_MAP",
    "US6_COMPARE",
]

class IntentResult(BaseModel):
    intent: str = Field(description="The detected intent key from the provided list, or 'UNKNOWN' if no match.")

async def detect_intent(state: AgentState, ctx: NodeContext) -> dict:
    """
    INPUT  : ``normalized_input``.
    OUTPUT : ``intent`` (một trong INTENTS) + ``active_skill`` (name của skill khớp).
    """
    cot = list(state.get("cot", []))
    
    # Bỏ qua nếu guardrail ở node trước đã chặn
    if state.get("needs_clarification"):
        return {"cot": cot}

    text = state.get("normalized_input", "")

    # Chuẩn bị danh sách intent và mô tả từ skills
    skills_info = []
    for s in ctx.skills.all():
        skills_info.append(f"- {s.intent}: {s.description}")
    skills_text = "\n".join(skills_info)

    llm = init_llm(model=ctx.llm_model, temperature=0.0)
    structured_llm = llm.with_structured_output(IntentResult)

    prompt = f"""
    You are an intent classification agent for a real estate chatbot.
    Based on the user's input, choose the most appropriate intent from the list below.
    If none match well, return 'US1_SEARCH' as fallback.
    
    Available Intents:
    {skills_text}
    
    User Input: "{text}"
    """

    try:
        result = await structured_llm.ainvoke(prompt)
        intent = result.intent if result.intent in INTENTS else "US1_SEARCH"
    except Exception as e:
        cot.append(f"intent: LLM error {e}, fallback to US1_SEARCH")
        intent = "US1_SEARCH"

    skill = ctx.skills.get(intent)
    cot.append(f"intent: detected {intent}")
    return {
        "intent": intent,
        "active_skill": skill.name if skill else None,
        "cot": cot,
    }
