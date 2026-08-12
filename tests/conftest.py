"""Fixtures dùng chung cho test HẠ TẦNG. [DONE]

Lưu ý: test ở đây CHỈ kiểm tra khung (skill loader, event serialize, graph compile).
KHÔNG smoke-test flow US1 → không lộ lời giải cho student.

`NullMCP` chỉ để `build_graph` construct được; nó KHÔNG chứa dữ liệu/logic mẫu
(mọi tool trả None). Muốn chạy flow thật, student tự viết mock hoặc dùng MCP thật.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent.skills.loader import SkillRegistry

CATALOG_DIR = Path(__file__).resolve().parents[1] / "src" / "agent" / "skills" / "catalog"


class NullMCP:
    """MCP client rỗng — khớp interface MCPProtocol, không có dữ liệu mẫu."""

    async def list_tools(self) -> list[str]:
        return []

    async def call_tool(self, name: str, args: dict[str, Any]) -> Any:
        return None


class MockCompareMCP:
    """Mock MCP client để test luồng US1 và US6."""

    def __init__(self, compare_data: dict[str, Any] | None = None):
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.compare_data = compare_data or {
            "listings": [
                {
                    "id": "lc_2",
                    "title": "Căn 2PN Vinhomes Ocean Park",
                    "price_vnd": 3500000000,
                    "price_per_m2_vnd": 50000000,
                    "area_m2": 70.0,
                    "bedrooms": 2,
                    "price_type": "asking",
                },
                {
                    "id": "lc_1",
                    "title": "Căn 1PN Vinhomes Ocean Park",
                    "price_vnd": 2000000000,
                    "price_per_m2_vnd": 45000000,
                    "area_m2": 44.0,
                    "bedrooms": 1,
                    "price_type": "estimate",
                },
            ],
            "fields": ["price_vnd", "price_per_m2_vnd", "area_m2", "bedrooms"],
            "context": {"same_project": True, "same_province": True},
            "deltas": {
                "price_vnd": {"min": 2000000000, "max": 3500000000, "diff": 1500000000},
                "area_m2": {"min": 44.0, "max": 70.0, "diff": 26.0},
            },
            "highlights": {
                "lc_1": ["cheapest_price", "lowest_price_per_m2"],
                "lc_2": ["largest_area", "most_bedrooms"],
            },
        }

    async def list_tools(self) -> list[str]:
        return [
            "compare_listings",
            "compare_nearby_amenities",
            "calculate_commute_matrix",
            "search_listings",
            "resolve_project",
        ]

    async def call_tool(self, name: str, args: dict[str, Any]) -> Any:
        self.calls.append((name, args))
        if name == "compare_listings":
            return self.compare_data
        if name == "resolve_project":
            return {"matched": True, "project": {"id": "vinhomes-ocean-park"}}
        if name == "search_listings":
            return self.compare_data.get("listings", [])
        return None


@pytest.fixture
def skills() -> SkillRegistry:
    return SkillRegistry.load(CATALOG_DIR)


@pytest.fixture
def null_mcp() -> NullMCP:
    return NullMCP()


@pytest.fixture
def mock_mcp() -> MockCompareMCP:
    return MockCompareMCP()
