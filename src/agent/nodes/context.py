"""NodeContext — phụ thuộc dùng chung mà node cần. [DONE]

graph.py bind context này vào mỗi node (qua functools.partial) nên chữ ký node là
``async def node(state, ctx) -> dict``. Test bơm ctx với MCP mock.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent.mcp.client import MCPProtocol
from agent.skills.loader import SkillRegistry


@dataclass
class NodeContext:
    skills: SkillRegistry
    mcp: MCPProtocol
    llm_model: str = "claude-haiku-4-5-20251001"
