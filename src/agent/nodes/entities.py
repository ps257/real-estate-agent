"""Node: Entity Extraction.  [DONE]

PRD bước 3. Trích thực thể: project, province, property_type, giá, phòng ngủ,
diện tích, listing_ids. Mục tiêu PRD: độ chính xác entity > 92%.

Logic trích nằm ở agent/entities_llm.py (dễ test riêng, không phụ thuộc graph).
Node này chỉ nối dây và ghi CoT.
"""

from __future__ import annotations

from agent.nodes.context import NodeContext
from agent.state import AgentState


async def extract_entities(state: AgentState, ctx: NodeContext) -> dict:
    """
    INPUT  : ``normalized_input`` + ``intent`` (gợi ý model tập trung field nào).
    OUTPUT : ``entities`` (dict, chỉ chứa khoá có giá trị) + ``cot``.

    Không có extractor (thiếu API key / tắt) hoặc LLM lỗi -> trả ``{}``. Node
    ``conversation`` sẽ thấy thiếu slot và hỏi lại — an toàn hơn là đoán bừa.
    """
    text = state.get("normalized_input") or state.get("user_input", "")
    cot = list(state.get("cot", []))

    entities: dict = {}
    if ctx.entities_llm is not None:
        extracted = await ctx.entities_llm.extract(text, intent=state.get("intent"))
        if extracted is not None:
            entities = extracted
            source = "llm"
        else:
            source = "llm lỗi -> rỗng"
    else:
        source = "LLM tắt -> rỗng"

    cot.append(f"entities: {entities or '{}'} [{source}]")
    return {"entities": entities, "cot": cot}
