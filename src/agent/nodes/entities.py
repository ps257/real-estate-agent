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

    phrases = (
        "bao nhieu listing",
        "so luong listing",
        "dien tich trung binh",
        "mat bang gia",
        "gia trung binh",
        "gia tren m2",
        "gia hien nay",
        "tinh hinh gia",
        "phan tich",
        "tong quan",
        "thong ke",
        "thi truong",
        "muc gia",
        "don gia",
        "loai hinh",
        "dien tich",
        "gia/m2",
        "du an",
        "cho toi",
        "cho minh",
        "the nao",
    )
    for phrase in phrases:
        folded = re.sub(rf"\b{re.escape(phrase)}\b", " ", folded)

    filler_words = (
        "hay",
        "giup",
        "minh",
        "toi",
        "cho",
        "em",
        "anh",
        "chi",
        "nhe",
        "nha",
        "a",
        "gia",
        "cua",
        "ve",
        "xem",
        "hien",
        "o",
        "va",
    )
    folded = re.sub(rf"\b({'|'.join(filler_words)})\b", " ", folded)
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
