"""Node: Intent Detection.  [TODO stub — hiện hard-code US1 để smoke-test]

PRD bước 2. Phân loại ý định người dùng và chọn skill tương ứng.
Mục tiêu PRD: độ chính xác intent > 95%.
"""

from __future__ import annotations

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


async def detect_intent(state: AgentState, ctx: NodeContext) -> dict:
    """
    INPUT  : ``normalized_input``.
    OUTPUT : ``intent`` (một trong INTENTS) + ``active_skill`` (name của skill khớp).
    """
    text = (state.get("normalized_input") or "").lower()
    
    # Kiểm tra intent so sánh (US6_COMPARE)
    compare_keywords = [
        "so sánh",
        "so sanh",
        "khác nhau",
        "khac nhau",
        "đối chiếu",
        "doi chieu",
        "compare",
        "vs",
    ]
    if any(kw in text for kw in compare_keywords):
        intent = "US6_COMPARE"
    else:
        intent = "US1_SEARCH"

    skill = ctx.skills.get(intent)
    cot = list(state.get("cot", []))
    cot.append(f"intent: {intent}")
    return {
        "intent": intent,
        "active_skill": skill.name if skill else None,
        "cot": cot,
    }
