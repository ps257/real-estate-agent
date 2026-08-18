"""Test tools_node: 7 nhánh intent + allow-list + nhánh hỏi lại."""

from __future__ import annotations

from typing import Any

import pytest

from agent.nodes.compose import compose
from agent.nodes.context import NodeContext
from agent.nodes.tools_node import call_tools
from agent.state import new_state


class StubMCP:
    """Trả kết quả đặt sẵn theo tên tool; ghi lại mọi lời gọi."""

    def __init__(self, responses: dict[str, Any] | None = None,
                 raises: set[str] | None = None) -> None:
        self.responses = responses or {}
        self.raises = raises or set()
        self.calls: list[tuple[str, dict]] = []

    async def list_tools(self) -> list[str]:
        return list(self.responses)

    async def call_tool(self, name: str, args: dict) -> Any:
        self.calls.append((name, args))
        if name in self.raises:
            raise RuntimeError(f"{name} disabled")
        return self.responses.get(name)


LISTING = {"id": "vhm:l1", "title": "Căn 2PN", "price_vnd": 4_000_000_000}
CTAS = {"listing_id": "vhm:l1", "ctas": [{"action": "view_all", "label": "Xem tất cả"}]}
PROJECT = {"id": "vhm:gg", "name": "Vinhomes Global Gate"}


def _ctx(skills, mcp) -> NodeContext:
    return NodeContext(skills=skills, mcp=mcp)


def _state(intent: str, skill: str, slots: dict):
    s = new_state("câu gì đó", "t1")
    s["intent"] = intent
    s["active_skill"] = skill
    s["slots"] = slots
    return s


async def _run(skills, mcp, intent, skill, slots):
    """Chạy tools rồi compose, trả (out_tools, out_compose)."""
    ctx = _ctx(skills, mcp)
    state = _state(intent, skill, slots)
    out = await call_tools(state, ctx)
    merged = {**state, **out}
    return out, await compose(merged, ctx)


# ------------------------------------------------------------- US1

async def test_us1_matched_tra_cards_va_cta(skills):
    mcp = StubMCP({
        "resolve_project": {"matched": True, "project": PROJECT},
        "search_listings": [LISTING],
        "listing_cta_actions": CTAS,
    })
    out, composed = await _run(skills, mcp, "US1_SEARCH", "search-real-estate",
                               {"project_or_province": "Vinhomes Global Gate"})

    assert [c["name"] for c in out["tool_calls"]] == [
        "resolve_project", "search_listings", "listing_cta_actions"]
    assert [a["type"] for a in composed["actions"]] == ["cards", "cta"]


async def test_us1_truyen_dieu_kien_loc_xuong_mcp(skills):
    """bedrooms/giá/diện tích trong slots phải tới được search_listings."""
    mcp = StubMCP({
        "resolve_project": {"matched": True, "project": PROJECT},
        "search_listings": [LISTING],
    })
    await _run(skills, mcp, "US1_SEARCH", "search-real-estate", {
        "project_or_province": "X", "bedrooms": 2,
        "max_price_vnd": 5_000_000_000, "min_area_m2": 80.0,
        "property_type": "apartment",
    })
    args = dict(mcp.calls[1][1])
    assert args["bedrooms"] == 2
    assert args["max_price_vnd"] == 5_000_000_000
    assert args["min_area_m2"] == 80.0
    assert args["property_type"] == "apartment"


async def test_us1_ten_mo_ho_thi_hoi_lai_khong_tim_theo_tinh(skills):
    """Bug cũ: matched=false rơi xuống search_listings_by_province(province='Vinhomes')."""
    mcp = StubMCP({"resolve_project": {
        "matched": False,
        "candidates": [
            {"id": "a", "name": "Vinhomes Global Gate", "province": "Hà Nội"},
            {"id": "b", "name": "Vinhomes Ocean Park", "province": "Hưng Yên"},
            {"id": "c", "name": "Vinhomes Grand Park", "province": "Hồ Chí Minh"},
            {"id": "d", "name": "Vinhomes Thứ Tư"},
        ],
    }})
    out, composed = await _run(skills, mcp, "US1_SEARCH", "search-real-estate",
                               {"project_or_province": "Vinhomes"})

    assert out["needs_clarification"] is True
    assert "search_listings_by_province" not in [c[0] for c in mcp.calls]
    assert len(composed["actions"][0]["suggestions"]) == 3


async def test_us1_khong_khop_va_khong_goi_y_thi_tim_theo_tinh(skills):
    mcp = StubMCP({
        "resolve_project": {"matched": False, "candidates": []},
        "search_listings_by_province": [LISTING],
    })
    await _run(skills, mcp, "US1_SEARCH", "search-real-estate",
               {"project_or_province": "Hà Nội"})
    assert mcp.calls[1][0] == "search_listings_by_province"
    assert mcp.calls[1][1]["province"] == "Hà Nội"


# --------------------------------------------------- US2.1 / US2.2

@pytest.mark.parametrize(
    "intent, skill, tool",
    [
        ("US2_1_VISIT", "book-visit", "start_visit_booking"),
        ("US2_2_CONSULT", "consultation", "start_consultation"),
    ],
)
async def test_form_us2(skills, intent, skill, tool):
    form = {"action": "visit_booking", "project": PROJECT,
            "fields": [{"name": "phone", "type": "tel", "required": True}]}
    mcp = StubMCP({tool: form})
    out, composed = await _run(skills, mcp, intent, skill, {"project_id": "vhm:gg"})

    assert mcp.calls[0] == (tool, {"project_id": "vhm:gg", "is_authenticated": False})
    assert composed["actions"] == [{"type": "form", "form": form}]
    assert "Vinhomes Global Gate" in composed["response_text"]


# ------------------------------------------------------------- US3 detail

async def test_us3_detail_goi_get_listing_va_tra_action(skills):
    mcp = StubMCP({"get_listing": LISTING})
    out, composed = await _run(
        skills, mcp, "US3_DETAIL", "listing_detail", {"listing_ids": ["vhm:l1"]}
    )

    assert out["tool_calls"] == [
        {"name": "get_listing", "args": {"listing_id": "vhm:l1"}}
    ]
    assert composed["actions"] == [{"type": "detail", "listing": LISTING}]


async def test_us3_detail_thieu_listing_id_khong_goi_mcp(skills):
    mcp = StubMCP()
    out, composed = await _run(skills, mcp, "US3_DETAIL", "listing_detail", {})

    assert out["tool_calls"] == []
    assert "chưa lấy được chi tiết" in composed["response_text"]


async def test_us3_detail_tool_khong_co_du_lieu_thi_fallback(skills):
    mcp = StubMCP({"get_listing": None})
    _, composed = await _run(
        skills, mcp, "US3_DETAIL", "listing_detail", {"listing_ids": ["vhm:missing"]}
    )

    assert "chưa lấy được chi tiết" in composed["response_text"]
    assert composed["actions"] == []


# ------------------------------------------------------ US4 / US5

async def test_us4_overview(skills):
    mcp = StubMCP({"project_overview": {"count": 120, "avg_price_vnd": 4e9}})
    _, composed = await _run(skills, mcp, "US4_ANALYTICS", "project-analytics",
                             {"project_id": "vhm:gg"})
    assert composed["actions"][0]["type"] == "overview"


async def test_us5_map(skills):
    mcp = StubMCP({"map_listings": {"points": [{"lat": 21.0, "lng": 105.8}]}})
    _, composed = await _run(skills, mcp, "US5_MAP", "map-view", {"project_id": "vhm:gg"})
    assert mcp.calls[0][1]["include_amenities"] is False
    assert composed["actions"][0]["type"] == "map"


async def test_us5_amenities_khong_co_du_lieu_thi_bao_ro(skills):
    mcp = StubMCP({"map_listings": {"points": [{"lat": 21.0, "lng": 105.8}]}})
    _, composed = await _run(
        skills,
        mcp,
        "US5_MAP",
        "map-view",
        {"project_id": "vhm:gg", "include_amenities": True},
    )

    assert mcp.calls[0][1]["include_amenities"] is True
    assert "chưa lấy được danh sách tiện ích lân cận" in composed["response_text"]


# ------------------------------------------------------------- US6

async def test_us6_compare(skills):
    mcp = StubMCP({"compare_listings": {
        "listings": [LISTING, LISTING], "fields": ["price", "area"]}})
    _, composed = await _run(skills, mcp, "US6_COMPARE", "compare-listings",
                             {"listing_ids": ["a", "b"]})
    assert mcp.calls[0][1]["listing_ids"] == ["a", "b"]
    assert composed["actions"][0]["type"] == "compare"


async def test_us6_cat_bot_qua_4_can(skills):
    """MCP giới hạn 2-4; cắt bớt còn hơn để tool trả lỗi."""
    mcp = StubMCP({"compare_listings": {"listings": [LISTING] * 4, "fields": []}})
    await _run(skills, mcp, "US6_COMPARE", "compare-listings",
               {"listing_ids": ["a", "b", "c", "d", "e", "f"]})
    assert mcp.calls[0][1]["listing_ids"] == ["a", "b", "c", "d"]


async def test_us6_duoi_2_can_thi_hoi_lai(skills):
    mcp = StubMCP()
    out, composed = await _run(skills, mcp, "US6_COMPARE", "compare-listings",
                               {"listing_ids": ["a"]})
    assert out["needs_clarification"] is True
    assert mcp.calls == []
    assert "ít nhất 2 căn" in composed["response_text"]


# ------------------------------------------------------ allow-list

async def test_chan_tool_ngoai_allow_list(skills):
    """compare-listings chỉ được phép gọi compare_listings."""
    from agent.nodes.tools_node import _ToolRun

    run = _ToolRun(_ctx(skills, StubMCP()), skills.by_name("compare-listings").tools)
    with pytest.raises(PermissionError):
        await run.call("submit_booking", {})


async def test_intent_khong_co_handler(skills):
    out = await call_tools(_state("US99_LA", "search-real-estate", {}),
                           _ctx(skills, StubMCP()))
    assert out["tool_calls"] == []
