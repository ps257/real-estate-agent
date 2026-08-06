"""Node: Entity Extraction.  [TODO stub]

PRD bước 3. Trích thực thể: project, province, property_type, price, bedrooms, ...
Mục tiêu PRD: độ chính xác entity > 92%.
"""

from __future__ import annotations

from agent.nodes.context import NodeContext
from agent.state import AgentState


async def extract_entities(state: AgentState, ctx: NodeContext) -> dict:
    """
    INPUT  : ``normalized_input`` (+ ``intent`` để biết cần entity gì).
    OUTPUT : ``entities`` (dict). Gợi ý key: project, province, property_type,
             min_price_vnd, max_price_vnd, bedrooms, listing_ids...

    Scaffold: trả entities rỗng — conversation node sẽ coi là thiếu slot.
    Riêng để smoke-test US1 chạy tới tool, ta bơm sẵn 1 entity mẫu nếu phát hiện
    từ khoá "vinhomes" (đơn giản, không phải NER thật).
    # TODO(student): NER thật bằng LLM và/hoặc gọi ctx.mcp.call_tool("resolve_project", ...).
    """
    text = (state.get("normalized_input") or "").lower()
    entities: dict = {}
    if "vinhomes" in text:
        entities["project"] = "Vinhomes"
    if "căn hộ" in text or "can ho" in text or "apartment" in text:
        entities["property_type"] = "apartment"

    cot = list(state.get("cot", []))
    cot.append(f"entities: {entities or '{}'} (scaffold keyword match)")
    return {"entities": entities, "cot": cot}
