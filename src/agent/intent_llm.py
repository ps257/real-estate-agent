"""Intent classifier — phân loại ý định người dùng bằng LLM. [DONE]

Dùng chung triết lý hai tầng với guardrail (agent/guardrail_llm.py):

  tầng 1  rule       nhãn CTA khớp chính xác  (~µs, không tốn tiền)
  tầng 2  LLM        phần còn lại

Khác guardrail ở CHÍNH SÁCH LỖI. Guardrail fail-open (cho qua) vì tầng regex
vẫn là lưới an toàn. Intent thì buộc phải chọn MỘT nhãn, không có "không biết" —
nên lỗi/timeout/nhãn lạ đều fallback về ``US1_SEARCH``: intent an toàn nhất vì
nó chỉ tra cứu, không tạo booking hay ghi dữ liệu.

Danh sách nhãn KHÔNG hard-code — dựng động từ SkillRegistry. Thêm một file
``skills/catalog/*.md`` là có thêm một intent, không phải sửa file này.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from pydantic import BaseModel

from agent.config import Settings, get_settings

if TYPE_CHECKING:  # tránh import vòng khi chỉ cần type hint
    from agent.skills.loader import SkillRegistry

logger = logging.getLogger(__name__)

# Intent dùng khi không phân loại được (lỗi, timeout, nhãn lạ, chitchat).
# Chọn US1_SEARCH vì nó read-only: đoán sai chỉ tốn một lượt hỏi lại, không
# tạo booking nhầm cho khách.
FALLBACK_INTENT = "US1_SEARCH"

# --- Tầng 1: nhãn CTA -> intent -------------------------------------------
# 4 nút CTA do listing_cta_actions trả về (xác nhận từ MCP thật). Khi user bấm
# nút, frontend gửi lại đúng label -> khớp rule, khỏi tốn một LLM call.
# search-real-estate.md quy định: Đặt lịch → US2.1, Tư vấn → US2.2, Bản đồ → US5.
_CTA_INTENTS: dict[str, str] = {
    "xem tất cả": "US1_SEARCH",
    "đặt lịch tham quan": "US2_1_VISIT",
    "tư vấn mua nhà": "US2_2_CONSULT",
    "xem bản đồ": "US5_MAP",
}


class IntentVerdict(BaseModel):
    """Kết quả phân loại intent."""

    # str chứ không phải Literal: tập nhãn dựng động từ catalog nên không biết
    # trước lúc định nghĩa class. Caller phải validate lại (xem classify()).
    intent: str
    confidence: float
    reason: str


def match_cta_intent(text: str) -> str | None:
    """Tầng 1 — khớp nhãn CTA. Trả intent, hoặc None nếu không phải CTA.

    Chỉ khớp khi cả câu LÀ nhãn CTA (cho phép thừa dấu câu/khoảng trắng), không
    khớp khi nhãn chỉ nằm lẫn trong câu dài — "cho em xem bản đồ dự án nào có
    tiện ích tốt" là câu hỏi thật, không phải cú bấm nút.
    """
    normalized = re.sub(r"[\s.!?,]+", " ", text).strip().lower()
    return _CTA_INTENTS.get(normalized)


def _build_label_block(skills: SkillRegistry) -> str:
    """Dựng phần mô tả nhãn trong prompt từ catalog — không hard-code."""
    return "\n".join(
        f"- {s.intent} — {s.description}" for s in skills.all() if s.intent
    )


_SYSTEM_TEMPLATE = """\
Bạn là bộ phân loại ý định cho một trợ lý bất động sản Việt Nam. Nhiệm vụ duy \
nhất: gán tin nhắn MỚI NHẤT của khách vào đúng một nhãn. Không trả lời khách.

CÁC NHÃN:

{labels}

QUY TẮC:

1. Phân loại theo tin nhắn MỚI NHẤT. Lịch sử chỉ để hiểu ngữ cảnh khi tin nhắn \
mới nói trống ("đặt lịch xem đi", "so sánh 2 căn đó giúp em") — lúc đó hãy suy \
ra khách đang nói về dự án/căn nào đã nhắc trước đó.
2. Khách ĐỔI Ý ĐỊNH giữa chừng là bình thường. Đừng bám theo intent của lượt \
trước nếu tin nhắn mới rõ ràng hướng khác.
3. Phân biệt kỹ các cặp dễ nhầm:
   - Hỏi THÔNG TIN dự án (chính sách, pháp lý, tiện ích, quy định) → US3_POLICY.
   - Hỏi SỐ LIỆU tổng hợp (bao nhiêu căn, giá trung bình, phân bố loại hình) \
→ US4_ANALYTICS.
   - Hỏi DANH SÁCH căn cụ thể để xem → US1_SEARCH.
   - Đặt lịch ĐI XEM tận nơi → US2_1_VISIT. Xin người TƯ VẤN → US2_2_CONSULT.
   - So sánh từ 2 căn trở lên → US6_COMPARE. Xem vị trí trên bản đồ → US5_MAP.
4. Chào hỏi, cảm ơn, chuyện phiếm, hoặc không rõ ý → {fallback}.

Trả về intent (đúng một mã trong danh sách trên), confidence (0.0-1.0), và \
reason ngắn gọn bằng tiếng Việt (tối đa 15 từ)."""


class IntentClassifier:
    """Lazy-init client để import module không cần API key.

    Tự vô hiệu hoá khi thiếu ``OPENAI_API_KEY`` — test và dev không key vẫn chạy,
    chỉ còn tầng rule + fallback.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = None  # AsyncOpenAI, tạo ở lần dùng đầu

    @property
    def enabled(self) -> bool:
        return bool(
            self._settings.intent_llm_enabled and self._settings.openai_api_key
        )

    def _ensure(self):
        if self._client is None:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(
                api_key=self._settings.openai_api_key,
                base_url=self._settings.openai_base_url or None,
            )
        return self._client

    async def classify(
        self,
        text: str,
        skills: SkillRegistry,
        history: list[str] | None = None,
    ) -> IntentVerdict | None:
        """Phân loại intent. Trả None khi không dùng được (caller tự fallback).

        ``history``: các tin nhắn user trước đó, cũ → mới. Cần cho các câu nói
        trống kiểu "đặt lịch xem đi".
        """
        if not self.enabled or not text.strip():
            return None

        valid = {s.intent for s in skills.all() if s.intent}
        if not valid:
            logger.warning("intent: catalog rỗng, không có nhãn nào để phân loại")
            return None

        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": _SYSTEM_TEMPLATE.format(
                    labels=_build_label_block(skills), fallback=FALLBACK_INTENT
                ),
            }
        ]
        for past in (history or []):
            messages.append({"role": "user", "content": past})
        messages.append({"role": "user", "content": text})

        try:
            client = self._ensure()
            response = await client.with_options(
                timeout=self._settings.intent_llm_timeout,
                max_retries=0,  # Nằm trên đường đi của request — không retry.
            ).responses.parse(
                model=self._settings.intent_llm_model,
                input=messages,
                text_format=IntentVerdict,
                max_output_tokens=256,
            )
        except Exception as exc:  # noqa: BLE001 — fallback là chủ ý, xem docstring.
            logger.warning(
                "intent LLM lỗi, fallback %s: %s: %s",
                FALLBACK_INTENT,
                type(exc).__name__,
                exc,
            )
            return None

        verdict = getattr(response, "output_parsed", None)
        if verdict is None:
            logger.warning("intent LLM không trả verdict (refusal hoặc parse hỏng)")
            return None

        # Model có thể bịa nhãn không có trong catalog -> không tin, để caller fallback.
        if verdict.intent not in valid:
            logger.warning(
                "intent LLM trả nhãn lạ %r (hợp lệ: %s)", verdict.intent, sorted(valid)
            )
            return None

        return verdict.model_copy(
            update={"confidence": min(max(verdict.confidence, 0.0), 1.0)}
        )


def build_intent_classifier(settings: Settings | None = None) -> IntentClassifier | None:
    """Trả classifier đã bật, hoặc None nếu tắt/thiếu key (node sẽ dùng fallback)."""
    classifier = IntentClassifier(settings)
    return classifier if classifier.enabled else None
