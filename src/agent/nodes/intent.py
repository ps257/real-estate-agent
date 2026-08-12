"""Node: Intent Detection.  [DONE]

PRD bước 2. Phân loại ý định người dùng và chọn skill tương ứng.
Mục tiêu PRD: độ chính xác intent > 95%.

Hai tầng (xem agent/intent_llm.py):
  tầng 1  rule  — nhãn CTA khớp chính xác, ~µs, không tốn tiền
  tầng 2  LLM   — phần còn lại

Không hard-code danh sách intent: nhãn dựng động từ SkillRegistry, nên thêm một
file ``skills/catalog/*.md`` là có thêm một intent mà không phải sửa file này.
"""

from __future__ import annotations

from agent.intent_llm import FALLBACK_INTENT, match_cta_intent
from agent.nodes.context import NodeContext
from agent.state import AgentState

# Số lượt user gần nhất đưa vào prompt để hiểu câu nói trống ("đặt lịch xem đi").
# Đủ để bắt ngữ cảnh mà không thổi phồng token của mỗi request.
_HISTORY_TURNS = 4


def _recent_user_messages(state: AgentState, limit: int = _HISTORY_TURNS) -> list[str]:
    """Các tin nhắn user TRƯỚC lượt hiện tại, cũ -> mới.

    ``messages`` tích luỹ qua checkpointer nhờ reducer add_messages. Lượt hiện
    tại đã nằm cuối list (new_state thêm vào) nên phải bỏ ra, tránh gửi trùng.
    """
    texts: list[str] = []
    for message in state.get("messages", []):
        role = message.get("role") if isinstance(message, dict) else getattr(message, "type", None)
        content = message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
        if role in ("user", "human") and isinstance(content, str) and content.strip():
            texts.append(content)
    return texts[:-1][-limit:] if texts else []


async def detect_intent(state: AgentState, ctx: NodeContext) -> dict:
    """
    INPUT  : ``normalized_input`` (+ ``messages`` để hiểu ngữ cảnh đa lượt).
    OUTPUT : ``intent`` + ``active_skill`` (name của skill khớp) + ``cot``.

    Luôn trả về một intent — không có trạng thái "không biết". Lỗi/timeout/nhãn
    lạ đều rơi về ``FALLBACK_INTENT``.
    """
    text = state.get("normalized_input") or state.get("user_input", "")
    cot = list(state.get("cot", []))

    # Tầng 1: user bấm nút CTA -> nhãn khớp chính xác, khỏi tốn LLM call.
    intent = match_cta_intent(text)
    source = "cta"

    # Tầng 2: LLM.
    if intent is None and ctx.intent_llm is not None:
        verdict = await ctx.intent_llm.classify(
            text, ctx.skills, history=_recent_user_messages(state)
        )
        if verdict is not None:
            intent = verdict.intent
            source = f"llm {verdict.confidence:.2f} — {verdict.reason}"

    if intent is None:
        intent = FALLBACK_INTENT
        source = "fallback" if ctx.intent_llm is not None else "fallback (LLM tắt)"

    skill = ctx.skills.get(intent)
    if skill is None:
        # Intent hợp lệ nhưng catalog thiếu skill tương ứng -> các node sau sẽ
        # không biết gọi tool nào. Ghi rõ vào CoT thay vì fail âm thầm.
        cot.append(f"intent: {intent} [{source}] — CẢNH BÁO: không có skill cho intent này")
        return {"intent": intent, "active_skill": None, "cot": cot}

    cot.append(f"intent: {intent} [{source}]")
    return {"intent": intent, "active_skill": skill.name, "cot": cot}


# Giữ lại cho code/test cũ tham chiếu; nguồn sự thật là skills/catalog/*.md.
def known_intents(ctx: NodeContext) -> list[str]:
    """Danh sách intent hợp lệ, đọc từ catalog."""
    return [s.intent for s in ctx.skills.all() if s.intent]


__all__ = ["detect_intent", "known_intents", "FALLBACK_INTENT"]
