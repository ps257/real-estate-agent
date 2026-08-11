"""Node: Entity Extraction."""

from __future__ import annotations

import re
import unicodedata

from agent.nodes.context import NodeContext
from agent.state import AgentState


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn")


def _clean_project_query(text: str) -> str:
    folded = _fold(text)
    folded = re.sub(r"[?!.:,;]+", " ", folded)
    folded = re.sub(
        r"\b("
        r"hay|giup|minh|toi|cho|em|anh|chi|nhe|nha|a|"
        r"du an|phan tich|tong quan|thong ke|thi truong|gia|"
        r"gia trung binh|gia tren m2|gia/m2|bao nhieu listing|so luong listing|"
        r"loai hinh|dien tich trung binh|cua|ve|cho toi|cho minh"
        r")\b",
        " ",
        folded,
    )
    return re.sub(r"\s+", " ", folded).strip()


async def extract_entities(state: AgentState, ctx: NodeContext) -> dict:
    """
    INPUT  : ``normalized_input`` (+ ``intent``).
    OUTPUT : ``entities``. For US4, extract project text only; project id resolution belongs to
    the tool node via MCP `resolve_project`.
    """
    raw_text = state.get("normalized_input") or ""
    folded = _fold(raw_text)
    intent = state.get("intent")
    entities: dict = {}

    if intent == "US4_ANALYTICS":
        project = _clean_project_query(raw_text)
        if project:
            entities["project"] = project
    else:
        if "vinhomes" in folded:
            entities["project"] = "Vinhomes"
        if "can ho" in folded or "apartment" in folded:
            entities["property_type"] = "can_ho"

    cot = list(state.get("cot", []))
    cot.append(f"entities: {entities or '{}'} (rule-based)")
    return {"entities": entities, "cot": cot}
