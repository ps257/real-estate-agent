"""Entity extraction — trích thực thể từ câu nói bằng LLM. [DONE]

PRD bước 3, mục tiêu > 92%. Khác intent (phân loại 1 nhãn), đây là **trích xuất**:
moi ra dữ liệu có cấu trúc, số khoá không cố định.

Schema bám sát tham số MCP nhận (xem docs/MCP_TOOLS.md § search_listings) để
``tools_node`` truyền thẳng, khỏi phải chuyển đổi tên hay đơn vị.

Không có tầng rule như intent: khác với nhãn CTA (khớp cả câu là xong), mọi câu
đều cần LLM để hiểu tên dự án / loại hình / khoảng giá — rule không tiết kiệm
được lời gọi nào. Lỗi/timeout -> trả rỗng, node ``conversation`` sẽ hỏi lại.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel

from agent.config import Settings, get_settings
from agent.telemetry import get_async_openai_class, get_telemetry

logger = logging.getLogger(__name__)

# Khoảng hợp lý để loại giá trị model tính sai (LLM làm số học không đáng tin).
_PRICE_VND_RANGE = (100_000_000, 1_000_000_000_000)  # 100 triệu .. 1000 tỷ
_BEDROOMS_RANGE = (1, 20)
_AREA_M2_RANGE = (10.0, 10_000.0)

# Từ vựng property_type CỦA DỮ LIỆU THẬT (MCP từ chối mọi giá trị ngoài đây).
# Không phải mã tiếng Anh — MCP dùng tiếng Việt không dấu.
VALID_PROPERTY_TYPES = frozenset({
    "can_ho",
    "lien_ke",
    "nha_pho",
    "shophouse",
    "thuong_mai_dich_vu",
    "biet_thu_don_lap",
    "biet_thu_song_lap",
    "biet_thu_tu_lap",
})


class ExtractedEntities(BaseModel):
    """Thực thể trích được. Mọi field optional — câu nói hiếm khi có đủ.

    Tên field = tên tham số MCP, cố ý. Đổi tên ở đây là phải sửa cả tools_node.
    """

    project: str | None = None
    province: str | None = None
    property_type: str | None = None
    bedrooms: int | None = None
    min_bedrooms: int | None = None
    max_bedrooms: int | None = None
    min_price_vnd: int | None = None
    max_price_vnd: int | None = None
    min_area_m2: float | None = None
    max_area_m2: float | None = None
    listing_ids: list[str] | None = None
    wants_amenities: bool | None = None


_SYSTEM_PROMPT = """\
Bạn là bộ trích xuất thực thể cho một trợ lý bất động sản Việt Nam. Đọc tin nhắn \
của khách và moi ra dữ liệu có cấu trúc. Không trả lời khách.

CHỈ TRÍCH CÁI KHÁCH THỰC SỰ NÓI. Field nào không có trong câu thì để null — \
tuyệt đối không suy đoán, không điền giá trị mặc định.

Mỗi field bạn điền là một ĐIỀU KIỆN LỌC sẽ chạy trên cơ sở dữ liệu. Thêm một \
điều kiện khách không nêu sẽ cắt mất đúng những căn khách muốn, và khách không \
hiểu vì sao không có kết quả. Khách hỏi diện tích thì CHỈ điền diện tích, không \
tự thêm khoảng giá. Khách hỏi giá thì CHỈ điền giá, không tự thêm số phòng ngủ. \
Bỏ sót một field an toàn hơn nhiều so với thêm một field.

TỪNG FIELD:

- project: tên dự án, giữ nguyên như khách viết ("Vinhomes Global Gate"). Nếu \
khách chỉ nói tên rút gọn ("Vinhomes") thì vẫn trích đúng phần khách nói, đừng \
tự bổ sung.
- province: tỉnh/thành, dùng tên hành chính chuẩn — "Hồ Chí Minh" (không phải \
"Sài Gòn"/"TPHCM"), "Hà Nội", "Đà Nẵng".
- property_type: PHẢI là một trong đúng 8 mã sau (tiếng Việt không dấu, lấy từ \
dữ liệu thật của MCP — mã ngoài danh sách này sẽ bị từ chối):
    can_ho              — căn hộ, chung cư
    lien_ke             — liền kề, nhà liền kề
    nha_pho             — nhà phố
    shophouse           — shophouse, nhà mặt tiền kinh doanh
    thuong_mai_dich_vu  — thương mại dịch vụ
    biet_thu_don_lap    — biệt thự đơn lập
    biet_thu_song_lap   — biệt thự song lập
    biet_thu_tu_lap     — biệt thự tứ lập
  Khách nói "biệt thự" chung chung, KHÔNG rõ đơn/song/tứ lập -> để null, đừng \
đoán một trong ba (đoán sai sẽ lọc mất hai loại còn lại).
  Khách nói "nhà" hoặc "căn" chung chung -> cũng để null.
- bedrooms: số phòng ngủ khi khách nói CHÍNH XÁC ("căn 2 phòng ngủ" -> 2).
- min_bedrooms / max_bedrooms: khi khách nói khoảng ("từ 2 phòng trở lên" -> \
min_bedrooms=2; "tối đa 3 phòng" -> max_bedrooms=3).
- min_price_vnd / max_price_vnd: giá quy về ĐỒNG (VNĐ), số nguyên.
  Quy đổi: "5 tỷ" = 5000000000 · "800 triệu" = 800000000 · "3 tỷ 5" = 3500000000
  Có từ chỉ hướng thì chỉ điền một vế:
    "dưới 5 tỷ"     -> max_price_vnd=5000000000
    "trên 3 tỷ"     -> min_price_vnd=3000000000
    "từ 3 đến 5 tỷ" -> min_price_vnd=3000000000, max_price_vnd=5000000000
  KHÔNG có từ chỉ hướng ("căn hộ 3 tỷ 5", "biệt thự khoảng 800 triệu") thì đó là
  TẦM GIÁ, không phải điều kiện bằng. Nới +/-10% quanh con số:
    "3 tỷ 5"           -> min=3150000000, max=3850000000
    "khoảng 800 triệu" -> min=720000000,  max=880000000
  TUYỆT ĐỐI KHÔNG đặt min_price_vnd bằng max_price_vnd — khách sẽ không nhận
  được kết quả nào.
- min_area_m2 / max_area_m2: diện tích theo m2. "trên 80m2" -> min_area_m2=80.
- listing_ids: mã căn khách nhắc tới (để xem chi tiết, bản đồ, hoặc so sánh). Chỉ trích khi câu có mã thật, không tự đặt mã, VÀ PHẢI GIỮ NGUYÊN toàn bộ mã (bao gồm cả tiền tố như oh:, vhm: nếu có).
- wants_amenities: true khi khách muốn xem tiện ích/xung quanh dự án như trường học, \
siêu thị, bệnh viện, công viên, thời gian di chuyển. Nếu không nhắc tới tiện ích thì null.

LƯU Ý:
- "chung cư"/"căn hộ" là property_type, KHÔNG phải project. "Vinhomes" là \
project, KHÔNG phải province.
- KHÔNG suy ra project/province từ mã căn. "vhm:abc123" có tiền tố gợi ý dự án \
nhưng khách KHÔNG nói tên dự án — để project=null. Chỉ điền project khi tên dự \
án xuất hiện thành chữ trong câu."""


class EntityExtractor:
    """Lazy-init client để import module không cần API key."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = None  # AsyncOpenAI

    @property
    def enabled(self) -> bool:
        return bool(
            self._settings.entities_llm_enabled and self._settings.openai_api_key
        )

    def _ensure(self):
        if self._client is None:
            AsyncOpenAI = get_async_openai_class()

            self._client = AsyncOpenAI(
                api_key=self._settings.openai_api_key,
                base_url=self._settings.openai_base_url or None,
            )
        return self._client

    async def extract(self, text: str, intent: str | None = None) -> dict | None:
        """Trả dict entity (chỉ khoá có giá trị), hoặc None khi không dùng được.

        ``intent`` chỉ để gợi ý model tập trung vào field liên quan; schema vẫn
        là một, model tự để null những field không liên quan.
        """
        if not self.enabled or not text.strip():
            return None

        user_content = text if not intent else f"[intent: {intent}]\n{text}"

        try:
            client = self._ensure()
            response = await client.with_options(
                timeout=self._settings.entities_llm_timeout,
                max_retries=0,
            ).responses.parse(
                model=self._settings.entities_llm_model,
                input=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                text_format=ExtractedEntities,
                max_output_tokens=512,  # nhiều field hơn intent
                **get_telemetry().openai_trace_kwargs("llm.entities"),
            )
        except Exception as exc:  # noqa: BLE001 — trả rỗng là chủ ý, xem docstring.
            logger.warning(
                "entities LLM lỗi, trả rỗng: %s", type(exc).__name__
            )
            return None

        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            logger.warning("entities LLM không trả kết quả (refusal hoặc parse hỏng)")
            return None

        return sanitize(parsed)


def sanitize(parsed: ExtractedEntities) -> dict:
    """Bỏ field null và giá trị vô lý. Hàm thuần — dễ test riêng.

    LLM làm số học không đáng tin ("3 tỷ 5" có lúc ra 35_000_000_000). Giá trị
    ngoài khoảng hợp lý bị loại thay vì truyền xuống MCP rồi trả rỗng khó hiểu.
    """
    out: dict = {}

    for key in ("project", "province"):
        value = getattr(parsed, key)
        if isinstance(value, str) and value.strip():
            out[key] = value.strip()

    # property_type ngoài từ vựng của dữ liệu -> MCP trả lỗi "Unknown
    # property_type" và cả truy vấn hỏng. Bỏ field còn hơn: mất một điều kiện
    # lọc thì kết quả rộng hơn, còn sai mã thì KHÔNG có kết quả nào.
    ptype = parsed.property_type
    if isinstance(ptype, str) and ptype.strip():
        ptype = ptype.strip().lower()
        if ptype in VALID_PROPERTY_TYPES:
            out["property_type"] = ptype
        else:
            logger.warning(
                "entities: bỏ property_type=%r (ngoài từ vựng dữ liệu %s)",
                ptype, sorted(VALID_PROPERTY_TYPES),
            )

    for key, (low, high) in (
        ("bedrooms", _BEDROOMS_RANGE),
        ("min_bedrooms", _BEDROOMS_RANGE),
        ("max_bedrooms", _BEDROOMS_RANGE),
        ("min_price_vnd", _PRICE_VND_RANGE),
        ("max_price_vnd", _PRICE_VND_RANGE),
        ("min_area_m2", _AREA_M2_RANGE),
        ("max_area_m2", _AREA_M2_RANGE),
    ):
        value = getattr(parsed, key)
        if value is None:
            continue
        if low <= value <= high:
            out[key] = value
        else:
            logger.info("entities: bỏ %s=%r (ngoài khoảng %s-%s)", key, value, low, high)

    # Khoảng ngược (min > max) -> model hiểu sai, bỏ cả cặp còn hơn lọc sai dữ liệu.
    for lo_key, hi_key in (
        ("min_price_vnd", "max_price_vnd"),
        ("min_bedrooms", "max_bedrooms"),
        ("min_area_m2", "max_area_m2"),
    ):
        if lo_key in out and hi_key in out and out[lo_key] > out[hi_key]:
            logger.info("entities: bỏ cặp %s/%s vì min > max", lo_key, hi_key)
            out.pop(lo_key)
            out.pop(hi_key)

    # min == max cho GIÁ và DIỆN TÍCH gần như chắc chắn trả rỗng: dữ liệu thật
    # hiếm khi khớp đúng một con số. Khách nói "3 tỷ 5" là nói tầm giá -> nới
    # +/-10%. (bedrooms thì min==max hợp lệ: "đúng 2 phòng ngủ" là điều kiện thật.)
    for lo_key, hi_key in (
        ("min_price_vnd", "max_price_vnd"),
        ("min_area_m2", "max_area_m2"),
    ):
        if lo_key in out and hi_key in out and out[lo_key] == out[hi_key]:
            midpoint = out[lo_key]
            out[lo_key] = type(midpoint)(midpoint * 0.9)
            out[hi_key] = type(midpoint)(midpoint * 1.1)
            logger.info(
                "entities: %s == %s (%r) -> nới thành khoảng +/-10%%",
                lo_key, hi_key, midpoint,
            )

    ids = parsed.listing_ids
    if ids:
        cleaned = [i.strip() for i in ids if isinstance(i, str) and i.strip()]
        if cleaned:
            out["listing_ids"] = cleaned

    if parsed.wants_amenities is not None:
        out["wants_amenities"] = parsed.wants_amenities

    return out


def build_entity_extractor(settings: Settings | None = None) -> EntityExtractor | None:
    """Trả extractor đã bật, hoặc None nếu tắt/thiếu key (node sẽ trả rỗng)."""
    extractor = EntityExtractor(settings)
    return extractor if extractor.enabled else None
