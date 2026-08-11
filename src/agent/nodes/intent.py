"""Node: Intent Detection."""

from __future__ import annotations

import unicodedata

from agent.nodes.context import NodeContext
from agent.state import AgentState

INTENTS = [
    "US1_SEARCH",
    "US2_1_VISIT",
    "US2_2_CONSULT",
    "US3_POLICY",
    "US4_ANALYTICS",
    "US5_MAP",
    "US6_COMPARE",
]


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn")


async def detect_intent(state: AgentState, ctx: NodeContext) -> dict:
    """
    INPUT  : ``normalized_input``.
    OUTPUT : ``intent`` (one of INTENTS) + ``active_skill``.

    Deterministic rule-based routing for implemented stories. This keeps the graph easy to test
    with MCP mocks; an LLM classifier can replace or augment it later.
    """
    text = _fold(state.get("normalized_input") or "")
    analytics_markers = [
        "phan tich",
        "tong quan",
        "thong ke",
        "thi truong",
        "gia trung binh",
        "gia/m2",
        "gia tren m2",
        "bao nhieu listing",
        "so luong listing",
        "loai hinh",
        "dien tich trung binh",
    ]

    intent = "US4_ANALYTICS" if any(marker in text for marker in analytics_markers) else "US1_SEARCH"
    skill = ctx.skills.get(intent)
    cot = list(state.get("cot", []))
    cot.append(f"intent: {intent} (rule-based)")
    return {
        "intent": intent,
        "active_skill": skill.name if skill else None,
        "cot": cot,
    }
