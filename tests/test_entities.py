"""Test node entities: sanitize (hàm thuần) + wiring node."""

from __future__ import annotations

import pytest

from agent.config import get_settings
from agent.entities_llm import (
    EntityExtractor,
    ExtractedEntities,
    build_entity_extractor,
    sanitize,
)
from agent.nodes.context import NodeContext
from agent.nodes.entities import extract_entities
from agent.state import new_state


# ------------------------------------------------------------- sanitize

def test_bo_field_null():
    out = sanitize(ExtractedEntities(project="Vinhomes Global Gate"))
    assert out == {"project": "Vinhomes Global Gate"}


def test_giu_gia_tri_hop_ly():
    out = sanitize(
        ExtractedEntities(
            province="Hà Nội",
            property_type="can_ho",
            bedrooms=2,
            max_price_vnd=5_000_000_000,
            min_area_m2=80.0,
        )
    )
    assert out == {
        "province": "Hà Nội",
        "property_type": "can_ho",
        "bedrooms": 2,
        "max_price_vnd": 5_000_000_000,
        "min_area_m2": 80.0,
    }


@pytest.mark.parametrize(
    "field, value",
    [
        ("max_price_vnd", 35_000_000_000_000),  # LLM nhân sai "3 tỷ 5"
        ("min_price_vnd", 5_000),               # quên nhân đơn vị
        ("bedrooms", 99),
        ("max_area_m2", 5.0),
    ],
)
def test_bo_gia_tri_vo_ly(field, value):
    """LLM làm số học không đáng tin -> loại thay vì truyền xuống MCP."""
    assert field not in sanitize(ExtractedEntities(**{field: value}))


def test_bo_ca_cap_khi_min_lon_hon_max():
    out = sanitize(
        ExtractedEntities(min_price_vnd=5_000_000_000, max_price_vnd=3_000_000_000)
    )
    assert "min_price_vnd" not in out and "max_price_vnd" not in out


def test_giu_cap_khoang_hop_le():
    out = sanitize(
        ExtractedEntities(min_price_vnd=3_000_000_000, max_price_vnd=5_000_000_000)
    )
    assert out["min_price_vnd"] == 3_000_000_000
    assert out["max_price_vnd"] == 5_000_000_000


def test_gia_min_bang_max_thi_noi_thanh_khoang():
    """min==max cho giá gần như chắc chắn trả rỗng -> nới +/-10%."""
    out = sanitize(
        ExtractedEntities(min_price_vnd=3_500_000_000, max_price_vnd=3_500_000_000)
    )
    assert out["min_price_vnd"] == 3_150_000_000
    assert out["max_price_vnd"] == 3_850_000_000


def test_dien_tich_min_bang_max_thi_noi():
    out = sanitize(ExtractedEntities(min_area_m2=80.0, max_area_m2=80.0))
    assert out["min_area_m2"] == pytest.approx(72.0)
    assert out["max_area_m2"] == pytest.approx(88.0)


def test_bedrooms_min_bang_max_thi_giu_nguyen():
    """Khác giá: 'đúng 2 phòng ngủ' là điều kiện thật, không nới."""
    out = sanitize(ExtractedEntities(min_bedrooms=2, max_bedrooms=2))
    assert out["min_bedrooms"] == 2
    assert out["max_bedrooms"] == 2


@pytest.mark.parametrize(
    "value",
    ["apartment", "townhouse", "villa", "land", "dat_nen", "CAN_HO_XYZ"],
)
def test_bo_property_type_ngoai_tu_vung(value):
    """MCP từ chối mã lạ ("Unknown property_type") -> cả truy vấn hỏng.

    Bỏ field còn hơn: mất điều kiện lọc thì kết quả rộng hơn, sai mã thì KHÔNG
    có kết quả nào. Đây là bug thật đã gặp: prompt dạy mã tiếng Anh trong khi
    dữ liệu dùng tiếng Việt không dấu -> mọi câu nhắc loại hình đều trả rỗng.
    """
    assert "property_type" not in sanitize(ExtractedEntities(property_type=value))


@pytest.mark.parametrize(
    "value",
    ["can_ho", "lien_ke", "nha_pho", "shophouse", "biet_thu_don_lap"],
)
def test_giu_property_type_hop_le(value):
    assert sanitize(ExtractedEntities(property_type=value))["property_type"] == value


def test_property_type_chuan_hoa_hoa_thuong():
    assert sanitize(ExtractedEntities(property_type="  CAN_HO "))["property_type"] == "can_ho"


def test_listing_ids():
    out = sanitize(ExtractedEntities(listing_ids=["vhm:a", "  ", "vhm:b"]))
    assert out["listing_ids"] == ["vhm:a", "vhm:b"]


def test_chuoi_rong_bi_bo():
    assert sanitize(ExtractedEntities(project="   ", province="")) == {}


# ----------------------------------------------------------------- node

class FakeEntitiesLLM:
    def __init__(self, result: dict | None = None) -> None:
        self.result = result
        self.calls: list[tuple[str, str | None]] = []

    async def extract(self, text, intent=None):
        self.calls.append((text, intent))
        return self.result


@pytest.fixture
def ctx(skills, null_mcp) -> NodeContext:
    return NodeContext(skills=skills, mcp=null_mcp)


async def test_khong_co_llm_van_bat_ten_vinhomes_ro_rang(ctx):
    out = await extract_entities(new_state("Tìm căn hộ Vinhomes", "t1"), ctx)
    assert out["entities"] == {"project": "Vinhomes"}
    assert "rule" in out["cot"][-1]


async def test_llm_loi_van_lay_project_phong_ngu_va_tien_ich(skills, null_mcp):
    ctx = NodeContext(skills=skills, mcp=null_mcp, entities_llm=FakeEntitiesLLM(None))
    state = new_state("Tìm quán ăn gần dự án Vinhomes Ocean Park 2 phòng ngủ", "t1")

    out = await extract_entities(state, ctx)

    assert out["entities"] == {
        "project": "Vinhomes Ocean Park",
        "bedrooms": 2,
        "wants_amenities": True,
        "include_amenities": True,
    }


async def test_llm_tra_ket_qua(skills, null_mcp):
    fake = FakeEntitiesLLM({"project": "Vinhomes Global Gate", "bedrooms": 2})
    ctx = NodeContext(skills=skills, mcp=null_mcp, entities_llm=fake)
    state = new_state("Tìm một lựa chọn phù hợp giúp tôi", "t1")
    state["intent"] = "US1_SEARCH"

    out = await extract_entities(state, ctx)

    assert out["entities"] == {"project": "Vinhomes Global Gate", "bedrooms": 2}
    # intent được truyền xuống để model biết tập trung field nào
    assert fake.calls[0][1] == "US1_SEARCH"


async def test_llm_loi_thi_rong(skills, null_mcp):
    """extract() trả None (lỗi/timeout) -> {} chứ không crash."""
    ctx = NodeContext(skills=skills, mcp=null_mcp, entities_llm=FakeEntitiesLLM(None))
    out = await extract_entities(new_state("abc", "t1"), ctx)
    assert out["entities"] == {}
    assert "lỗi" in out["cot"][-1]


# ------------------------------------------------------- EntityExtractor

def test_tu_tat_khi_thieu_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert EntityExtractor(get_settings()).enabled is False
    assert build_entity_extractor(get_settings()) is None


async def test_khong_goi_api_voi_input_rong(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-test")
    extractor = EntityExtractor(get_settings())
    assert await extractor.extract("   ") is None
    assert extractor._client is None
