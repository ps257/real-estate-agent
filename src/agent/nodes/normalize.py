"""Node: Input Normalization & Guardrail.  [TODO stub]

PRD bước 1. Chuẩn hoá input & chặn nội dung ngoài phạm vi (mục "Out of scope").
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from agent.config import init_llm
from langchain_core.prompts import PromptTemplate

from agent.nodes.context import NodeContext
from agent.state import AgentState

class GuardrailResult(BaseModel):
    is_out_of_scope: bool = Field(description="True if the request is about financial modeling, pricing valuation, investment advice, or online transactions.")
    reason: str = Field(description="Reason for the decision.")
    normalized_text: str = Field(description="The normalized user input.")

async def normalize(state: AgentState, ctx: NodeContext) -> dict:
    """
    INPUT  (đọc state): ``user_input``.
    OUTPUT (trả dict, merge vào state):
        - ``normalized_input``: str đã chuẩn hoá (trim, lower dấu câu thừa, ...).
        - (tuỳ chọn) đặt ``needs_clarification=True`` + ``actions`` nếu vi phạm guardrail
    """
    cot = list(state.get("cot", []))
    user_input = state.get("user_input", "").strip()

    llm = init_llm(model=ctx.llm_model, temperature=0.0)
    structured_llm = llm.with_structured_output(GuardrailResult)

    prompt = f"""
    You are a real estate assistant guardrail. Your job is to check if the user request is out of scope and to normalize it.
    
    Out of scope topics:
    - Financial modeling / installments (mô phỏng tài chính / trả góp)
    - Real estate valuation (định giá BĐS)
    - Investment advice / comparing which is better to buy (tư vấn đầu tư / căn nào đáng mua hơn)
    - Online transactions / booking payments (giao dịch online / thanh toán / ký HĐ)
    
    User input: "{user_input}"
    """
    
    try:
        result = await structured_llm.ainvoke(prompt)
    except Exception as e:
        cot.append(f"normalize: LLM error {e}, fallback to pass-through")
        return {"normalized_input": user_input, "cot": cot}

    cot.append(f"normalize: Guardrail checked. Out of scope: {result.is_out_of_scope} - {result.reason}")

    if result.is_out_of_scope:
        return {
            "normalized_input": result.normalized_text,
            "needs_clarification": True,
            "response_text": "Xin lỗi, yêu cầu của anh/chị nằm ngoài phạm vi hỗ trợ của em (định giá, tài chính, tư vấn đầu tư). Anh/chị cần em kết nối với chuyên viên tư vấn không ạ?",
            "actions": [],
            "cot": cot
        }

    return {"normalized_input": result.normalized_text, "cot": cot}
