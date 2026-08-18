"""Test node intent: rule CTA (tầng 1), LLM (tầng 2), fallback."""

from __future__ import annotations

import pytest

from agent.config import get_settings
from agent.intent_llm import (
    FALLBACK_INTENT,
    IntentClassifier,
    IntentVerdict,
    build_intent_classifier,
    match_cta_intent,
)
from agent.nodes.context import NodeContext
from agent.nodes.intent import detect_intent, known_intents
from agent.state import new_state


# ------------------------------------------------------- tầng 1: rule CTA

@pytest.mark.parametrize(
    "text, intent",
    [
        ("Đặt lịch tham quan", "US2_1_VISIT"),
        ("đặt lịch tham quan", "US2_1_VISIT"),
        ("Tư vấn mua nhà", "US2_2_CONSULT"),
        ("Xem bản đồ", "US5_MAP"),
        ("Xem tất cả", "US1_SEARCH"),
        ("  Xem bản đồ.  ", "US5_MAP"),  # thừa khoảng trắng/dấu câu vẫn khớp
    ],
)
def test_cta_khop(text, intent):
    assert match_cta_intent(text) == intent


@pytest.mark.parametrize(
    "text",
    [
        "Cho em xem bản đồ dự án nào có tiện ích tốt nhất",  # nhãn lẫn trong câu dài
        "Tôi muốn tìm căn hộ Vinhomes",
        "",
    ],
)
def test_cta_khong_khop_cau_thuong(text):
    """Chỉ khớp khi CẢ CÂU là nhãn CTA — tránh cướp câu hỏi thật."""
    assert match_cta_intent(text) is None


# --------------------------------------------------------------- node

class FakeIntentLLM:
    """Đóng vai IntentClassifier, không gọi API."""

    def __init__(self, verdict: IntentVerdict | None = None) -> None:
        self.verdict = verdict
        self.calls: list[tuple[str, list[str]]] = []

    async def classify(self, text, skills, history=None):
        self.calls.append((text, list(history or [])))
        return self.verdict


@pytest.fixture
def ctx(skills, null_mcp) -> NodeContext:
    return NodeContext(skills=skills, mcp=null_mcp)


def _ctx_with(skills, null_mcp, fake) -> NodeContext:
    return NodeContext(skills=skills, mcp=null_mcp, intent_llm=fake)


async def test_khong_co_llm_thi_fallback(ctx):
    """Không có LLM và không khớp rule -> UNKNOWN, không gắn skill tìm nhà."""
    out = await detect_intent(new_state("Yêu cầu bất động sản chưa rõ", "t1"), ctx)
    assert out["intent"] == FALLBACK_INTENT
    assert out["active_skill"] is None


async def test_tim_can_ho_dung_fast_path_khong_goi_llm(skills, null_mcp):
    fake = FakeIntentLLM(None)
    out = await detect_intent(
        new_state("Tôi muốn tìm căn hộ Vinhomes 2 phòng ngủ", "t1"),
        _ctx_with(skills, null_mcp, fake),
    )

    assert out["intent"] == "US1_SEARCH"
    assert out["active_skill"] == "search-real-estate"
    assert fake.calls == []


async def test_tien_ich_gan_du_an_routes_to_map_without_llm(skills, null_mcp):
    fake = FakeIntentLLM(None)
    out = await detect_intent(
        new_state("Tìm quán ăn gần dự án Vinhomes Ocean Park", "t1"),
        _ctx_with(skills, null_mcp, fake),
    )

    assert out["intent"] == "US5_MAP"
    assert out["active_skill"] == "map-view"
    assert fake.calls == []


async def test_cta_khong_goi_llm(skills, null_mcp):
    """Tiết kiệm latency: nhãn CTA khớp rule thì không gọi LLM."""
    fake = FakeIntentLLM(IntentVerdict(intent="US1_SEARCH", confidence=1.0, reason="x"))
    out = await detect_intent(new_state("Đặt lịch tham quan", "t1"), _ctx_with(skills, null_mcp, fake))

    assert out["intent"] == "US2_1_VISIT"
    assert out["active_skill"] == "book-visit"
    assert fake.calls == []


async def test_llm_quyet_dinh(skills, null_mcp):
    fake = FakeIntentLLM(
        IntentVerdict(intent="US6_COMPARE", confidence=0.93, reason="so sánh 2 căn")
    )
    out = await detect_intent(
        new_state("Đặt hai lựa chọn cạnh nhau giúp em", "t1"), _ctx_with(skills, null_mcp, fake)
    )

    assert out["intent"] == "US6_COMPARE"
    assert out["active_skill"] == "compare-listings"
    assert "llm 0.93" in out["cot"][-1]


async def test_llm_tra_none_thi_fallback(skills, null_mcp):
    """classify() trả None -> UNKNOWN và không gọi nhầm skill tìm nhà."""
    fake = FakeIntentLLM(None)
    out = await detect_intent(new_state("abcxyz", "t1"), _ctx_with(skills, null_mcp, fake))

    assert out["intent"] == FALLBACK_INTENT
    assert out["active_skill"] is None
    assert "fallback" in out["cot"][-1]


async def test_truyen_lich_su_cho_llm(skills, null_mcp):
    """Câu nói trống cần ngữ cảnh -> phải gửi lượt user trước đó, KHÔNG gửi trùng lượt hiện tại."""
    fake = FakeIntentLLM(IntentVerdict(intent="US2_1_VISIT", confidence=0.9, reason="x"))
    state = new_state("Đặt lịch xem đi", "t1")
    state["messages"] = [
        {"role": "user", "content": "Tìm căn hộ Vinhomes Global Gate"},
        {"role": "user", "content": "Đặt lịch xem đi"},
    ]

    await detect_intent(state, _ctx_with(skills, null_mcp, fake))

    text, history = fake.calls[0]
    assert text == "Đặt lịch xem đi"
    assert history == ["Tìm căn hộ Vinhomes Global Gate"]


async def test_nhan_lay_tu_catalog(ctx):
    """Danh sách intent đọc từ skills/catalog/*.md, không hard-code."""
    intents = set(known_intents(ctx))
    assert intents == {
        "US1_SEARCH", "US2_1_VISIT", "US2_2_CONSULT",
        "US3_DETAIL", "US4_ANALYTICS", "US5_MAP", "US6_COMPARE",
    }


# --------------------------------------------------------- IntentClassifier

def test_tu_tat_khi_thieu_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert IntentClassifier(get_settings()).enabled is False
    assert build_intent_classifier(get_settings()) is None


def test_model_mac_dinh_theo_agent_llm_model(monkeypatch):
    """Khác guardrail: intent KẾ THỪA AGENT_LLM_MODEL."""
    monkeypatch.delenv("INTENT_LLM_MODEL", raising=False)
    monkeypatch.setenv("AGENT_LLM_MODEL", "gpt-4o")
    assert get_settings().intent_llm_model == "gpt-4o"


async def test_khong_goi_api_voi_input_rong(monkeypatch, skills):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-test")
    classifier = IntentClassifier(get_settings())
    assert await classifier.classify("   ", skills) is None
    assert classifier._client is None  # chưa từng khởi tạo client


async def test_nhan_la_bi_tu_choi(monkeypatch, skills):
    """Model bịa nhãn không có trong catalog -> trả None để caller fallback."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-test")
    classifier = IntentClassifier(get_settings())

    class _Resp:
        output_parsed = IntentVerdict(intent="US99_BIA", confidence=1.0, reason="x")

    class _Responses:
        async def parse(self, **kw):
            return _Resp()

    class _Client:
        responses = _Responses()

        def with_options(self, **kw):
            return self

    classifier._client = _Client()
    assert await classifier.classify("gì đó", skills) is None
