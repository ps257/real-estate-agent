"""Test node conversation: map entities->slots, resolve project_id, hỏi lại."""

from __future__ import annotations

from typing import Any

import pytest

from agent.nodes.context import NodeContext
from agent.nodes.conversation import manage_conversation
from agent.state import new_state


class StubMCP:
    """MCP giả: trả kết quả resolve_project đặt sẵn, đếm số lần gọi."""

    def __init__(self, result: Any = None, raises: bool = False) -> None:
        self.result = result
        self.raises = raises
        self.calls: list[tuple[str, dict]] = []

    async def list_tools(self) -> list[str]:
        return ["resolve_project"]

    async def call_tool(self, name: str, args: dict) -> Any:
        self.calls.append((name, args))
        if self.raises:
            raise RuntimeError("MCP chết")
        return self.result


MATCHED = {"matched": True, "project": {"id": "vhm:global-gate", "name": "Vinhomes Global Gate"}}
AMBIGUOUS = {
    "matched": False,
    "candidates": [
        {"id": "vhm:a", "name": "Vinhomes Global Gate", "province": "Hà Nội"},
        {"id": "vhm:b", "name": "Vinhomes Global Gate Hạ Long", "province": "Quảng Ninh"},
        {"id": "vhm:c", "name": "Vinhomes Golden Avenue", "province": "Quảng Ninh"},
        {"id": "vhm:d", "name": "Vinhomes Thứ Tư", "province": None},
    ],
}


def _ctx(skills, mcp) -> NodeContext:
    return NodeContext(skills=skills, mcp=mcp)


def _state(skill_name: str, entities: dict, slots: dict | None = None):
    state = new_state("câu gì đó", "t1")
    state["active_skill"] = skill_name
    state["entities"] = entities
    if slots is not None:
        state["slots"] = slots
    return state


# ------------------------------------------------------ US1: dùng TÊN

async def test_us1_du_slot_voi_ten(skills):
    mcp = StubMCP()
    out = await manage_conversation(
        _state("search-real-estate", {"project": "Vinhomes Global Gate"}), _ctx(skills, mcp)
    )
    assert out["needs_clarification"] is False
    assert out["slots"]["project_or_province"] == "Vinhomes Global Gate"
    assert mcp.calls == []  # US1 không cần project_id -> không resolve


async def test_us1_thieu_slot_thi_hoi_lai(skills):
    out = await manage_conversation(
        _state("search-real-estate", {}), _ctx(skills, StubMCP())
    )
    assert out["needs_clarification"] is True
    assert out["clarify"] is None  # compose sẽ dùng skill.clarify_prompt


async def test_chuyen_dieu_kien_loc_sang_slot(skills):
    """bedrooms/giá/diện tích trước đây bị bỏ trước khi tới tools."""
    entities = {
        "province": "Hà Nội",
        "property_type": "apartment",
        "bedrooms": 2,
        "max_price_vnd": 5_000_000_000,
        "min_area_m2": 80.0,
    }
    out = await manage_conversation(
        _state("search-real-estate", entities), _ctx(skills, StubMCP())
    )
    slots = out["slots"]
    assert slots["bedrooms"] == 2
    assert slots["max_price_vnd"] == 5_000_000_000
    assert slots["min_area_m2"] == 80.0
    assert slots["property_type"] == "apartment"


# ------------------------------------------- US2-US5: cần project_id

async def test_resolve_ten_thanh_project_id(skills):
    mcp = StubMCP(MATCHED)
    out = await manage_conversation(
        _state("book-visit", {"project": "Vinhomes Global Gate"}), _ctx(skills, mcp)
    )
    assert out["slots"]["project_id"] == "vhm:global-gate"
    assert out["needs_clarification"] is False
    assert mcp.calls[0] == ("resolve_project", {"text": "Vinhomes Global Gate"})


async def test_ten_mo_ho_thi_hoi_lai_kem_3_goi_y(skills):
    """4 ứng viên -> hỏi lại, hiện tối đa 3 nút (search-real-estate.md)."""
    out = await manage_conversation(
        _state("book-visit", {"project": "Vinhomes"}), _ctx(skills, StubMCP(AMBIGUOUS))
    )
    assert out["needs_clarification"] is True
    assert "project_id" not in out["slots"]

    suggestions = out["clarify"]["suggestions"]
    assert len(suggestions) == 3
    assert suggestions[0]["label"] == "Vinhomes Global Gate — Hà Nội"
    assert suggestions[0]["value"] == "Vinhomes Global Gate"
    assert suggestions[0]["project_id"] == "vhm:a"


async def test_mcp_loi_thi_hoi_lai_khong_crash(skills):
    out = await manage_conversation(
        _state("book-visit", {"project": "Vinhomes"}), _ctx(skills, StubMCP(raises=True))
    )
    assert out["needs_clarification"] is True


async def test_mcp_tra_chuoi_loi_thi_hoi_lai(skills):
    """parse_tool_result trả str khi tool lỗi -> không được vỡ."""
    out = await manage_conversation(
        _state("book-visit", {"project": "X"}), _ctx(skills, StubMCP("No project found"))
    )
    assert out["needs_clarification"] is True


# ------------------------------------------------------ đa lượt

async def test_nho_slot_qua_luot(skills):
    """Lượt 2 nói trống vẫn đủ slot nhờ project_id lượt 1 còn trong state."""
    mcp = StubMCP()
    out = await manage_conversation(
        _state("book-visit", {}, slots={"project_id": "vhm:global-gate"}), _ctx(skills, mcp)
    )
    assert out["needs_clarification"] is False
    assert mcp.calls == []  # đã có id -> không resolve lại


async def test_ten_moi_thi_resolve_lai(skills):
    """Khách đổi dự án -> phải resolve lại, không dùng id cũ."""
    mcp = StubMCP(MATCHED)
    out = await manage_conversation(
        _state("book-visit", {"project": "Dự án khác"}, slots={"project_id": "vhm:cu"}),
        _ctx(skills, mcp),
    )
    assert mcp.calls[0][1] == {"text": "Dự án khác"}
    assert out["slots"]["project_id"] == "vhm:global-gate"


async def test_new_state_khong_ghi_de_slots():
    """new_state cố ý KHÔNG đặt slots — nếu đặt, checkpointer bị ghi đè {}."""
    assert "slots" not in new_state("x", "t1")


async def test_xoa_clarify_cu_khi_du_slot(skills):
    state = _state("book-visit", {"project": "Vinhomes Global Gate"})
    state["clarify"] = {"prompt": "cũ", "suggestions": [{"label": "cũ"}]}
    out = await manage_conversation(state, _ctx(skills, StubMCP(MATCHED)))
    assert out["clarify"] is None


# ------------------------------------------------------ US6: listing_ids

async def test_us6_dung_listing_ids(skills):
    mcp = StubMCP()
    out = await manage_conversation(
        _state("compare-listings", {"listing_ids": ["vhm:a", "vhm:b"]}), _ctx(skills, mcp)
    )
    assert out["needs_clarification"] is False
    assert out["slots"]["listing_ids"] == ["vhm:a", "vhm:b"]
    assert mcp.calls == []
