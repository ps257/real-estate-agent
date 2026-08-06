"""Node: Input Normalization & Guardrail.  [TODO stub]

PRD bước 1. Chuẩn hoá input & chặn nội dung ngoài phạm vi (mục "Out of scope").
"""

from __future__ import annotations

from agent.nodes.context import NodeContext
from agent.state import AgentState


async def normalize(state: AgentState, ctx: NodeContext) -> dict:
    """
    INPUT  (đọc state): ``user_input``.
    OUTPUT (trả dict, merge vào state):
        - ``normalized_input``: str đã chuẩn hoá (trim, lower dấu câu thừa, ...).
        - (tuỳ chọn) đặt ``needs_clarification=True`` + ``actions`` nếu vi phạm guardrail
          (vd hỏi về đầu tư/định giá — xem Out of scope trong PRD) để dừng sớm.

    Scaffold: pass-through (chỉ copy user_input -> normalized_input) để graph chạy.
    # TODO(student): thêm chuẩn hoá tiếng Việt + guardrail out-of-scope.
    """
    cot = list(state.get("cot", []))
    cot.append("normalize: pass-through (chưa có guardrail)")
    return {"normalized_input": state.get("user_input", ""), "cot": cot}
