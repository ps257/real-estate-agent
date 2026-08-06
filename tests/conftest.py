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


@pytest.fixture
def skills() -> SkillRegistry:
    return SkillRegistry.load(CATALOG_DIR)


@pytest.fixture
def null_mcp() -> NullMCP:
    return NullMCP()
