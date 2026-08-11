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

ANALYTICS_MARKERS = (
    "phan tich",
    "tong quan",
    "thong ke",
    "thi truong",
    "mat bang gia",
    "gia trung binh",
    "gia hien nay",
    "tinh hinh gia",
    "muc gia",
    "don gia",
    "gia/m2",
    "gia tren m2",
    "bao nhieu listing",
    "so luong listing",
    "loai hinh",
    "dien tich trung binh",
    "dien tich o",
)


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn")


def _is_analytics_query(text: str) -> bool:
    folded = _fold(text)
    return any(marker in folded for marker in ANALYTICS_MARKERS)


async def detect_intent(state: AgentState, ctx: NodeContext) -> dict:
    """
    INPUT  : ``normalized_input``.
    OUTPUT : ``intent`` (one of INTENTS) + ``active_skill``.

    Deterministic rule-based routing for implemented stories. This keeps the graph easy to test
    with MCP mocks; an LLM classifier can replace or augment it later.
    """
    text = state.get("normalized_input") or ""
    intent = "US4_ANALYTICS" if _is_analytics_query(text) else "US1_SEARCH"
    skill = ctx.skills.get(intent)
    cot = list(state.get("cot", []))
    cot.append(f"intent: {intent} (rule-based)")
    return {
        "intent": intent,
        "active_skill": skill.name if skill else None,
        "cot": cot,
    }
