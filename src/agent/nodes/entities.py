"""Node: Entity Extraction.  [DONE]

PRD bước 3. Trích thực thể: project, province, property_type, giá, phòng ngủ,
diện tích, listing_ids. Mục tiêu PRD: độ chính xác entity > 92%.

Logic trích nằm ở agent/entities_llm.py (dễ test riêng, không phụ thuộc graph).
Node này chỉ nối dây và ghi CoT.
"""

from __future__ import annotations

import re

from agent.nodes.context import NodeContext
from agent.state import AgentState


_PROJECT_QUERY_FILLER = re.compile(
    r"\b(?:cho tôi xem|thống kê giá|thống kê diện tích|phân tích tổng quan|"
    r"mặt bằng giá và diện tích|mặt bằng giá|giá và diện tích|và diện tích|"
    r"của dự án|dự án|ở|tại|hiện|thế nào)\b",
    re.IGNORECASE,
)

_LISTING_ID_RE = re.compile(r"\b[a-z]{1,10}(?::|_)[a-z0-9_-]+\b", re.IGNORECASE)
_PROJECT_STOP_RE = re.compile(
    r"\s+(?:(?:\d+)\s*(?:phòng|pn)\b|giá\b|diện tích\b|gần\b|xung quanh\b|"
    r"lân cận\b|hiện\b|thế nào\b|có căn\b|với ngân sách\b)",
    re.IGNORECASE,
)


def _clean_project_query(text: str) -> str:
    """Bỏ từ đệm analytics để lấy tên dự án làm query dự phòng."""
    cleaned = _PROJECT_QUERY_FILLER.sub(" ", text)
    cleaned = re.sub(r"[^\wÀ-ỹ-]+", " ", cleaned, flags=re.UNICODE)
    return re.sub(r"\s+", " ", cleaned).strip().casefold()


def _listing_ids_from_state(text: str, state: AgentState) -> list[str]:
    """Lấy mã căn deterministic từ câu hiện tại hoặc kết quả tìm kiếm trước."""
    ids = list(dict.fromkeys(match.strip() for match in _LISTING_ID_RE.findall(text)))
    if len(ids) >= 2 or not re.search(r"(?:vừa tìm|ở trên|hai căn đó|2 căn đó)", text, re.I):
        return ids

    for item in reversed(state.get("tool_results", [])):
        if not isinstance(item, dict) or item.get("name") != "search_listings":
            continue
        payload = item.get("result", item.get("data"))
        if isinstance(payload, list):
            for listing in payload:
                if isinstance(listing, dict) and listing.get("id"):
                    ids.append(str(listing["id"]).strip())
        break
    return list(dict.fromkeys(ids))


def _project_from_text(text: str) -> str | None:
    """Fallback bảo thủ cho tên dự án rõ ràng khi Entity LLM không dùng được."""
    clean_text = re.sub(r"\([^)]*\)", " ", text)
    clean_text = _LISTING_ID_RE.sub(" ", clean_text)

    match = re.search(r"\bvinhomes\b", clean_text, re.IGNORECASE)
    if match:
        tail = clean_text[match.start():]
    else:
        labelled = re.search(r"\bdự\s+án\s+", clean_text, re.IGNORECASE)
        if not labelled:
            return None
        tail = clean_text[labelled.end():]

    tail = _PROJECT_STOP_RE.split(tail, maxsplit=1)[0]
    tail = re.sub(r"[?!,.;:]+$", "", tail).strip()
    words = tail.split()
    if not words:
        return None
    return " ".join(words[:6])


def _rule_entities(text: str, state: AgentState) -> dict:
    entities: dict = {}
    listing_ids = _listing_ids_from_state(text, state)
    if listing_ids:
        entities["listing_ids"] = listing_ids

    project = _project_from_text(text)
    if project:
        entities["project"] = project

    bedrooms = re.search(r"\b(\d+)\s*(?:phòng ngủ|pn)\b", text, re.IGNORECASE)
    if bedrooms:
        entities["bedrooms"] = int(bedrooms.group(1))

    lowered = text.casefold()
    if any(word in lowered for word in ("quán ăn", "nhà hàng", "trường học", "bệnh viện", "siêu thị")):
        entities["wants_amenities"] = True
        entities["include_amenities"] = True
    return entities


def _rules_are_sufficient(text: str, intent: str | None, entities: dict) -> bool:
    """True khi rule đã đủ dữ kiện và gọi LLM chỉ làm tăng latency."""
    if intent in ("US4_ANALYTICS", "US5_MAP"):
        return bool(entities.get("project"))
    if intent == "US6_COMPARE":
        return len(entities.get("listing_ids") or []) >= 2
    if intent == "US1_SEARCH" and entities.get("project"):
        # Giá/diện tích cần LLM parse đơn vị; câu chỉ có dự án/phòng ngủ thì rule đủ.
        return not re.search(
            r"(?:\bgiá\b|ngân sách|triệu|tỷ|\bm2\b|m²|diện tích)",
            text,
            re.IGNORECASE,
        )
    return False


async def extract_entities(state: AgentState, ctx: NodeContext) -> dict:
    """
    INPUT  : ``normalized_input`` + ``intent`` (gợi ý model tập trung field nào).
    OUTPUT : ``entities`` (dict, chỉ chứa khoá có giá trị) + ``cot``.

    Không có extractor (thiếu API key / tắt) hoặc LLM lỗi -> trả ``{}``. Node
    ``conversation`` sẽ thấy thiếu slot và hỏi lại — an toàn hơn là đoán bừa.
    """
    text = state.get("normalized_input") or state.get("user_input", "")
    cot = list(state.get("cot", []))

    entities = _rule_entities(text, state)
    has_rule_entities = bool(entities)
    rules_sufficient = _rules_are_sufficient(text, state.get("intent"), entities)
    if ctx.entities_llm is not None and not rules_sufficient:
        extracted = await ctx.entities_llm.extract(text, intent=state.get("intent"))
        if extracted is not None:
            entities.update(extracted)
            source = "rule+llm" if has_rule_entities else "llm"
        else:
            source = "rule; llm lỗi" if has_rule_entities else "llm lỗi -> rỗng"
    elif rules_sufficient:
        source = "rule (đủ dữ kiện)"
    else:
        source = "rule" if has_rule_entities else "LLM tắt -> rỗng"

    cot.append(f"entities: {entities or '{}'} [{source}]")
    return {"entities": entities, "cot": cot}
