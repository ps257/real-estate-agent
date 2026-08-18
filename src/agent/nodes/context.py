"""NodeContext — phụ thuộc dùng chung mà node cần. [DONE]

graph.py bind context này vào mỗi node (qua functools.partial) nên chữ ký node là
``async def node(state, ctx) -> dict``. Test bơm ctx với MCP mock.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent.entities_llm import EntityExtractor
from agent.guardrail_llm import LLMGuardrail
from agent.intent_llm import IntentClassifier
from agent.compose_llm import ComposeLLM
from agent.mcp.client import MCPProtocol
from agent.skills.loader import SkillRegistry


@dataclass
class NodeContext:
    skills: SkillRegistry
    mcp: MCPProtocol
    llm_model: str = "gpt-5.6"
    # Guardrail tầng 2. None = chỉ chạy tầng regex (test, hoặc thiếu API key).
    guardrail_llm: LLMGuardrail | None = None
    # Intent tầng 2. None = chỉ chạy rule nhanh rồi fallback UNKNOWN an toàn.
    intent_llm: IntentClassifier | None = None
    # Entity extraction. None = trả entities rỗng, conversation sẽ hỏi lại.
    entities_llm: EntityExtractor | None = None
    # Sinh văn bản trả lời tự nhiên. None = fallback về câu template cố định.
    compose_llm: ComposeLLM | None = None
