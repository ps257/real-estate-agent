"""Guardrail tầng 2 — LLM classifier (OpenAI). [DONE]

Tầng 1 (regex, trong nodes/normalize.py) bắt các cách diễn đạt trực diện với chi
phí ~micro giây. Tầng này chỉ chạy khi tầng 1 **không** bắt được, để phủ các cách
nói vòng vo ("bỏ tiền vào đây có ổn không?") mà regex bỏ sót.

Ba nguyên tắc thiết kế:

1. **Fail-open.** Mọi lỗi (timeout, rate limit, refusal, parse hỏng) đều trả về
   "cho qua". Guardrail chết không được phép làm chết cả sản phẩm — tầng 1 vẫn
   còn đó làm lưới an toàn.
2. **Ngưỡng tin cậy.** Chỉ chặn khi model đủ chắc. False positive (chặn nhầm câu
   hợp lệ) tốn khách; false negative chỉ tốn một câu trả lời lệch phạm vi.
3. **Ngân sách latency cứng.** Timeout mặc định 2s, nằm trong mục tiêu
   TTFT < 800ms của PRD vì tầng này chỉ chạy cho phần request tầng 1 không bắt.

Dùng Responses API (`client.responses.parse`) — đường được OpenAI khuyến nghị cho
structured outputs. Không dùng `chat.completions.parse` (API cũ hơn).
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel

from agent.config import Settings, get_settings

logger = logging.getLogger(__name__)

# Khớp với GuardrailRule.code trong nodes/normalize.py, cộng nhãn "hợp lệ".
GuardrailCode = Literal[
    "valuation",
    "investment",
    "financial",
    "transaction",
    "unrelated",
    "in_scope",
]


class GuardrailVerdict(BaseModel):
    """Kết quả phân loại. ``code="in_scope"`` nghĩa là hợp lệ."""

    code: GuardrailCode
    # Không ràng buộc ge/le: structured outputs không hỗ trợ numeric constraint.
    # Tự clamp trong classify() an toàn hơn.
    confidence: float
    reason: str


_SYSTEM_PROMPT = """\
Bạn là bộ phân loại phạm vi cho một trợ lý bất động sản Việt Nam. Nhiệm vụ duy \
nhất: gán tin nhắn của khách vào đúng một nhãn. Không trả lời khách.

NHÃN NGOÀI PHẠM VI:

- valuation — nhờ định giá/thẩm định một BĐS cụ thể, hỏi "nhà tôi bán được bao \
nhiêu", "giá trị thực của căn này".
- investment — xin ý kiến đầu tư: "có nên mua không", "căn nào đáng mua hơn", \
lướt sóng, sinh lời, tỷ suất lợi nhuận, dự báo giá lên/xuống.
- financial — nhờ tính toán vay/trả góp/lãi suất/ân hạn gốc, mô phỏng khoản vay.
- transaction — muốn đặt cọc, thanh toán trực tuyến, chuyển khoản, ký hợp đồng \
điện tử ngay trong cuộc trò chuyện.
- unrelated — hỏi những câu lạc đề, chuyện phiếm không liên quan, nhờ làm toán, \
viết code, hỏi thời tiết, hoặc bất cứ chủ đề nào nằm ngoài lĩnh vực bất động sản.

NHÃN HỢP LỆ:

- in_scope — mọi thứ còn lại.

QUY TẮC PHÂN LOẠI (theo thứ tự ưu tiên):

1. Hỏi VỀ chính sách/quy định/quy trình/thủ tục/điều kiện đã được dự án công bố \
là in_scope, kể cả khi nhắc tới trả góp, lãi suất hay đặt cọc. Phân biệt "chính \
sách trả góp của dự án là gì?" (in_scope) với "tính giúp tôi trả góp 20 năm" \
(financial).
2. "Chủ đầu tư" là tên gọi doanh nghiệp phát triển dự án, KHÔNG phải hành vi đầu \
tư. "Chủ đầu tư dự án X là ai?" là in_scope.
3. Tra cứu BĐS, hỏi giá rao bán, so sánh thông số các căn, xem bản đồ, xem tiện \
ích, đặt lịch tham quan, xin tư vấn viên đều là in_scope.
4. Chào hỏi cơ bản ("chào em", "xin chào") hoặc cảm ơn ("cảm ơn em") là in_scope. \
Nhưng nếu yêu cầu làm việc khác (thời tiết, giải trí, kiến thức chung) thì là unrelated.
5. Phân vân về CHỦ ĐỀ (không rõ khách đang hỏi gì) thì chọn in_scope — chặn nhầm \
câu hợp lệ tệ hơn bỏ lọt. NHƯNG nếu ý định đã rõ mà chỉ diễn đạt vòng vo, hãy gán \
đúng nhãn: nói lóng không biến một câu ngoài phạm vi thành in_scope.

CÁCH NÓI GIÁN TIẾP — ĐỌC KỸ:

Khách Việt Nam hiếm khi hỏi thẳng. Hãy giải mã Ý ĐỊNH, đừng khớp từ khoá. Các \
kiểu nói vòng sau VẪN thuộc nhãn ngoài phạm vi:

- Hỏi có nên mua bằng cách nói bóng: "chỗ này ngon không", "vào được không", \
"xuống tay giờ hợp lý chứ", "múc được chưa" → investment.
- Hỏi giá trị tài sản bằng cách nói bóng: "sang tay được bao nhiêu", "bán vội \
thì mấy giá", "cầm về được mấy" → valuation.
- Hỏi gánh nặng trả nợ: "mỗi tháng gánh bao nhiêu", "trả dần thì sao" → financial.
- Rủ giao dịch ngay: "cọc luôn giờ", "chốt luôn nhé" → transaction.

Ngược lại, các câu sau tuy nghe giống nhưng LÀ in_scope: "căn này giá rao bao \
nhiêu" (tra cứu giá niêm yết), "dự án ngon không" khi hỏi về tiện ích/hạ tầng \
chứ không phải nên mua hay không.

Trả về code, confidence (0.0-1.0, mức chắc chắn của bạn), và reason ngắn gọn \
bằng tiếng Việt (tối đa 15 từ)."""


class LLMGuardrail:
    """Classifier tầng 2. Lazy-init client để import module không cần API key.

    Tự vô hiệu hoá khi thiếu ``OPENAI_API_KEY`` — nhờ vậy test và môi trường dev
    không key vẫn chạy được, chỉ còn tầng regex.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = None  # AsyncOpenAI, tạo ở lần dùng đầu

    @property
    def enabled(self) -> bool:
        return bool(
            self._settings.guardrail_llm_enabled and self._settings.openai_api_key
        )

    def _ensure(self):
        if self._client is None:
            # Import trong hàm: môi trường không cài extra [llm] vẫn import được module.
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(
                api_key=self._settings.openai_api_key,
                base_url=self._settings.openai_base_url or None,
            )
        return self._client

    async def classify(self, text: str) -> GuardrailVerdict | None:
        """Trả về verdict nếu nên CHẶN; None nếu cho qua.

        None bao gồm cả 3 trường hợp: hợp lệ, confidence dưới ngưỡng, và lỗi
        (fail-open). Caller không cần phân biệt.
        """
        verdict = await self.classify_raw(text)
        if verdict is None or verdict.code == "in_scope":
            return None

        confidence = min(max(verdict.confidence, 0.0), 1.0)
        if confidence < self._settings.guardrail_min_confidence:
            logger.info(
                "guardrail LLM: '%s' conf=%.2f dưới ngưỡng %.2f -> cho qua",
                verdict.code,
                confidence,
                self._settings.guardrail_min_confidence,
            )
            return None

        return verdict.model_copy(update={"confidence": confidence})

    async def classify_raw(self, text: str) -> GuardrailVerdict | None:
        """Verdict THÔ từ model — chưa lọc ``in_scope``, chưa áp ngưỡng.

        Dùng để chẩn đoán (xem scripts/smoke_guardrail.py): phân biệt "model bảo
        hợp lệ" với "model bắt đúng nhưng confidence thấp" — hai lỗi cần hai cách
        sửa khác nhau. Trả None chỉ khi lỗi/refusal (fail-open).
        """
        if not self.enabled or not text.strip():
            return None

        try:
            client = self._ensure()
            response = await client.with_options(
                timeout=self._settings.guardrail_llm_timeout,
                max_retries=0,  # Guardrail nằm trên đường đi của request — không retry.
            ).responses.parse(
                model=self._settings.guardrail_llm_model,
                input=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                text_format=GuardrailVerdict,
                max_output_tokens=256,  # Output là 3 field ngắn.
                # Model dòng gpt-5.x là reasoning model. Nếu latency chưa đạt,
                # chỗ này là nút vặn đầu tiên (tham số `reasoning`) — kiểm tra
                # giá trị hợp lệ trong docs trước khi bật, sai là 400.
            )
        except Exception as exc:  # noqa: BLE001 — fail-open là chủ ý, xem docstring.
            logger.warning("guardrail LLM lỗi, cho qua: %s: %s", type(exc).__name__, exc)
            return None

        # Model từ chối vì lý do an toàn -> output_parsed là None.
        verdict = getattr(response, "output_parsed", None)
        if verdict is None:
            logger.warning("guardrail LLM không trả verdict (refusal hoặc parse hỏng)")
        return verdict


def build_guardrail_llm(settings: Settings | None = None) -> LLMGuardrail | None:
    """Trả về classifier đã bật, hoặc None nếu tắt/thiếu key (graph sẽ bỏ qua tầng 2)."""
    guardrail = LLMGuardrail(settings)
    return guardrail if guardrail.enabled else None
