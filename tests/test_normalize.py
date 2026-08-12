"""Test node normalize: chuẩn hoá text + guardrail out-of-scope."""

from __future__ import annotations

import pytest

from agent.config import get_settings
from agent.guardrail_llm import GuardrailVerdict, LLMGuardrail, build_guardrail_llm
from agent.nodes.context import NodeContext
from agent.nodes.normalize import check_guardrail, normalize, normalize_text
from agent.state import new_state


# ------------------------------------------------------------- normalize_text

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("  Tìm   căn hộ   Vinhomes  ", "Tìm căn hộ Vinhomes"),
        ("Có căn 2PN nào không ???", "Có căn 2 phòng ngủ nào không?"),
        ("dep quaaaaa", "dep quaa"),
        ("ko biết đc giá", "không biết được giá"),
        ("tìm bđs ở tphcm", "tìm bất động sản ở hồ chí minh"),
        ("căn 80m2 giá 5 tr / m2", "căn 80 m2 giá 5 triệu / m2"),
    ],
)
def test_normalize_text(raw, expected):
    assert normalize_text(raw) == expected


def test_giu_nguyen_chu_so_lon():
    """Rút gọn ký tự lặp KHÔNG được phá giá tiền."""
    assert "5000000" in normalize_text("giá 5000000 đồng")


def test_giu_hoa_thuong_va_dau():
    """Tên dự án phải nguyên vẹn để node entities còn nhận diện."""
    assert normalize_text("Vinhomes Ocean Park") == "Vinhomes Ocean Park"


# ---------------------------------------------------------------- guardrail

@pytest.mark.parametrize(
    "text, code",
    [
        ("Anh muốn định giá căn hộ nhà anh", "valuation"),
        ("Căn nào đáng mua hơn em?", "investment"),
        ("Có nên mua căn này không?", "investment"),
        ("Tính giúp anh trả góp 20 năm", "financial"),
        ("Lãi suất vay ngân hàng bao nhiêu?", "financial"),
        ("Anh muốn đặt cọc luôn", "transaction"),
        ("Ký hợp đồng điện tử được không", "transaction"),
        ("dinh gia can ho giup anh", "valuation"),  # người dùng gõ không dấu
    ],
)
def test_guardrail_chan_out_of_scope(text, code):
    rule = check_guardrail(normalize_text(text))
    assert rule is not None and rule.code == code


@pytest.mark.parametrize(
    "text",
    [
        "Tôi muốn tìm căn hộ Vinhomes",
        "Chủ đầu tư dự án Vinhomes là ai?",          # "chủ đầu tư" != "đầu tư"
        "Chính sách trả góp của dự án là gì?",        # hỏi *về* chính sách -> US3
        "Quy trình đặt cọc của dự án ra sao?",        # ditto
        "Cho em xem giá các căn 2PN",                 # "giá" thường != "định giá"
        "Dự án đã bàn giao rồi phải không?",          # "rồi" -> "roi", không dính rule
    ],
)
def test_guardrail_khong_bat_nham(text):
    assert check_guardrail(normalize_text(text)) is None


# --------------------------------------------------------------------- node

@pytest.fixture
def ctx(skills, null_mcp) -> NodeContext:
    return NodeContext(skills=skills, mcp=null_mcp)


async def test_node_input_hop_le(ctx):
    state = new_state("Tôi muốn tìm  căn hộ Vinhomes", "t1")
    out = await normalize(state, ctx)

    assert out["normalized_input"] == "Tôi muốn tìm căn hộ Vinhomes"
    assert out["guardrail"] is None
    assert len(out["cot"]) == 2


async def test_node_input_bi_chan(ctx):
    state = new_state("Anh có nên đầu tư căn này không?", "t1")
    out = await normalize(state, ctx)

    assert out["guardrail"] is not None
    assert out["guardrail"]["code"] == "investment"
    assert out["guardrail"]["message"]
    assert out["guardrail"]["suggestions"]


async def test_node_xoa_guardrail_cu(ctx):
    """Lượt sạch phải reset guardrail của lượt trước (checkpointer giữ state)."""
    state = new_state("Tìm căn hộ Vinhomes", "t1")
    state["guardrail"] = {"code": "investment", "message": "cũ", "suggestions": []}

    out = await normalize(state, ctx)
    assert out["guardrail"] is None


# ------------------------------------------------------- tầng 2 (LLM classifier)

class FakeGuardrailLLM:
    """Đóng vai LLMGuardrail, không gọi API. Ghi lại số lần được gọi."""

    def __init__(self, verdict: GuardrailVerdict | None = None) -> None:
        self.verdict = verdict
        self.calls: list[str] = []

    async def classify(self, text: str) -> GuardrailVerdict | None:
        self.calls.append(text)
        return self.verdict


def _ctx_with(skills, null_mcp, fake) -> NodeContext:
    return NodeContext(skills=skills, mcp=null_mcp, guardrail_llm=fake)


async def test_tang2_bat_cau_vong_vo(skills, null_mcp):
    """Câu regex bỏ sót nhưng LLM bắt được -> chặn, dùng lại message của rule."""
    fake = FakeGuardrailLLM(
        GuardrailVerdict(code="investment", confidence=0.9, reason="xin ý kiến đầu tư")
    )
    text = "Theo em thì bỏ tiền vào đây có ổn không?"
    assert check_guardrail(normalize_text(text)) is None  # tầng 1 bỏ sót

    out = await normalize(new_state(text, "t1"), _ctx_with(skills, null_mcp, fake))

    assert out["guardrail"]["code"] == "investment"
    assert out["guardrail"]["message"]      # lấy từ _RULES, không phải LLM sinh ra
    assert out["guardrail"]["suggestions"]


async def test_tang2_khong_chay_khi_tang1_da_bat(skills, null_mcp):
    """Tiết kiệm latency: regex bắt được thì không gọi LLM."""
    fake = FakeGuardrailLLM(
        GuardrailVerdict(code="valuation", confidence=1.0, reason="x")
    )
    out = await normalize(
        new_state("Anh muốn định giá căn hộ", "t1"), _ctx_with(skills, null_mcp, fake)
    )

    assert out["guardrail"]["code"] == "valuation"
    assert fake.calls == []


async def test_tang2_cho_qua_khi_hop_le(skills, null_mcp):
    """classify() trả None (hợp lệ / dưới ngưỡng / lỗi) -> request đi tiếp."""
    fake = FakeGuardrailLLM(None)
    out = await normalize(
        new_state("Tìm căn hộ Vinhomes", "t1"), _ctx_with(skills, null_mcp, fake)
    )

    assert out["guardrail"] is None
    assert fake.calls == ["Tìm căn hộ Vinhomes"]


async def test_tang2_bo_qua_khi_khong_cau_hinh(ctx):
    """ctx.guardrail_llm=None (test/thiếu key) -> chỉ chạy regex, không lỗi."""
    out = await normalize(new_state("Bỏ tiền vào đây ổn không?", "t1"), ctx)
    assert out["guardrail"] is None


# ------------------------------------------------------------- LLMGuardrail

def test_tu_tat_khi_thieu_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert LLMGuardrail(get_settings()).enabled is False
    assert build_guardrail_llm(get_settings()) is None


def test_tu_tat_khi_enabled_false(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-test")
    monkeypatch.setenv("GUARDRAIL_LLM_ENABLED", "false")
    assert LLMGuardrail(get_settings()).enabled is False


def test_model_classifier_khong_ke_thua_agent_model(monkeypatch):
    """GUARDRAIL_LLM_MODEL độc lập: đổi AGENT_LLM_MODEL không kéo theo classifier."""
    monkeypatch.delenv("GUARDRAIL_LLM_MODEL", raising=False)
    monkeypatch.setenv("AGENT_LLM_MODEL", "gpt-5.6")
    settings = get_settings()
    assert settings.llm_model == "gpt-5.6"
    assert settings.guardrail_llm_model == "gpt-5.6-luna"


async def test_khong_goi_api_voi_input_rong(monkeypatch):
    """Guard rỗng: không tốn request nào."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-test")
    guardrail = LLMGuardrail(get_settings())
    assert await guardrail.classify("   ") is None
    assert guardrail._client is None  # chưa từng khởi tạo client
