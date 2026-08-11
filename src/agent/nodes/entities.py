"""Node: Entity Extraction.  [TODO stub]

PRD bước 3. Trích thực thể: project, province, property_type, price, bedrooms, ...
Mục tiêu PRD: độ chính xác entity > 92%.
"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field
from agent.config import init_llm

from agent.nodes.context import NodeContext
from agent.state import AgentState

class EntitiesResult(BaseModel):
    project_or_province: str | None = Field(default=None, description="Tên dự án bất động sản hoặc tỉnh thành (vd: Vinhomes, Ocean Park, Hà Nội). Dùng chung cho tìm kiếm, xem bản đồ, phân tích.")
    project_id: str | None = Field(default=None, description="ID của dự án nếu người dùng nhập chính xác mã ID.")
    province: str | None = Field(default=None, description="Tỉnh / Thành phố.")
    property_type: str | None = Field(default=None, description="Loại hình BĐS. MUST be one of: can_ho, lien_ke, nha_pho, shophouse, thuong_mai_dich_vu, biet_thu_don_lap, biet_thu_song_lap, biet_thu_tu_lap.")
    bedrooms: int | None = Field(default=None, description="Số phòng ngủ.")
    min_price_vnd: float | None = Field(default=None, description="Giá tối thiểu (đơn vị VND).")
    max_price_vnd: float | None = Field(default=None, description="Giá tối đa (đơn vị VND).")
    listing_ids: list[str] | None = Field(default=None, description="Danh sách mã ID của các tin đăng BĐS, thường dùng khi so sánh.")
    wants_amenities: bool | None = Field(default=None, description="True nếu người dùng ngụ ý muốn xem hoặc hỏi về tiện ích xung quanh (vd: trường học, siêu thị, bệnh viện, tiện ích, xung quanh có gì...).")

async def extract_entities(state: AgentState, ctx: NodeContext) -> dict:
    """
    INPUT  : ``normalized_input`` (+ ``intent`` để biết cần entity gì).
    OUTPUT : ``entities`` (dict).
    """
    cot = list(state.get("cot", []))
    
    # Bỏ qua nếu guardrail chặn
    if state.get("needs_clarification"):
        return {"cot": cot}

    text = state.get("normalized_input", "")
    intent = state.get("intent", "")

    llm = init_llm(model=ctx.llm_model, temperature=0.0)
    structured_llm = llm.with_structured_output(EntitiesResult)

    prompt = f"""
    You are an entity extraction agent for a real estate chatbot.
    Extract the relevant entities from the user input.
    Current Intent: {intent}
    
    User Input: "{text}"
    """

    try:
        result = await structured_llm.ainvoke(prompt)
        entities = {k: v for k, v in result.model_dump().items() if v is not None}
        
        # Normalize property_type
        if "property_type" in entities and isinstance(entities["property_type"], str):
            pt = entities["property_type"].lower()
            if any(x in pt for x in ["căn hộ", "chung cư", "apartment", "can ho"]):
                entities["property_type"] = "can_ho"
            elif any(x in pt for x in ["liền kề", "townhouse", "lien ke"]):
                entities["property_type"] = "lien_ke"
            elif any(x in pt for x in ["nhà phố", "nha pho", "nhà"]):
                entities["property_type"] = "nha_pho"
            elif "shophouse" in pt:
                entities["property_type"] = "shophouse"
            elif any(x in pt for x in ["thương mại", "dịch vụ", "thuong mai", "dich vu"]):
                entities["property_type"] = "thuong_mai_dich_vu"
            elif any(x in pt for x in ["đơn lập", "don lap"]):
                entities["property_type"] = "biet_thu_don_lap"
            elif any(x in pt for x in ["song lập", "song lap"]):
                entities["property_type"] = "biet_thu_song_lap"
            elif any(x in pt for x in ["tứ lập", "tu lap"]):
                entities["property_type"] = "biet_thu_tu_lap"
            elif any(x in pt for x in ["biệt thự", "villa", "biet thu"]):
                entities["property_type"] = "biet_thu_don_lap"
                
    except Exception as e:
        cot.append(f"entities: LLM error {e}, fallback to empty")
        entities = {}

    cot.append(f"entities: extracted {entities}")
    return {"entities": entities, "cot": cot}
