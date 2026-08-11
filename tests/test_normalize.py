"""Test node normalize: chuẩn hoá text + guardrail out-of-scope."""

from __future__ import annotations

import pytest

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
