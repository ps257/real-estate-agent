"""Build LangGraph — wiring node + conditional edges + checkpointer. [DONE]

Sơ đồ: START → normalize → intent → entities → conversation
             → (đủ slot?) → tools → compose → END
             → (thiếu slot) ─────────────→ compose → END

Xem docs/ARCHITECTURE.md §2.
"""

from __future__ import annotations

from functools import partial

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from agent.mcp.client import MCPClient, MCPProtocol
from agent.nodes.compose import compose
from agent.nodes.context import NodeContext
from agent.nodes.conversation import manage_conversation
from agent.nodes.entities import extract_entities
from agent.nodes.intent import detect_intent
from agent.nodes.normalize import normalize
from agent.nodes.tools_node import call_tools
from agent.skills.loader import SkillRegistry
from agent.state import AgentState


def _route_after_normalize(state: AgentState) -> str:
    """Conditional edge: guardrail chặn → compose (từ chối); hợp lệ → intent."""
    return "compose" if state.get("guardrail") else "intent"


def _route_after_conversation(state: AgentState) -> str:
    """Conditional edge: thiếu slot → hỏi lại (compose); đủ → gọi tool."""
    return "compose" if state.get("needs_clarification") else "tools"


def build_graph(
    skills: SkillRegistry,
    mcp: MCPProtocol,
    *,
    llm_model: str = "gpt-5.6",
    guardrail_llm=None,
    checkpointer=None,
):
    """Trả về graph đã compile. Bind NodeContext vào từng node qua partial.

    checkpointer=None → MemorySaver (đổi sang RedisSaver để theo PRD).
    guardrail_llm=None → chỉ chạy guardrail tầng regex.
    """
    ctx = NodeContext(
        skills=skills, mcp=mcp, llm_model=llm_model, guardrail_llm=guardrail_llm
    )

    g = StateGraph(AgentState)
    g.add_node("normalize", partial(normalize, ctx=ctx))
    g.add_node("intent", partial(detect_intent, ctx=ctx))
    g.add_node("entities", partial(extract_entities, ctx=ctx))
    g.add_node("conversation", partial(manage_conversation, ctx=ctx))
    g.add_node("tools", partial(call_tools, ctx=ctx))
    g.add_node("compose", partial(compose, ctx=ctx))

    g.add_edge(START, "normalize")
    g.add_conditional_edges(
        "normalize",
        _route_after_normalize,
        {"intent": "intent", "compose": "compose"},
    )
    g.add_edge("intent", "entities")
    g.add_edge("entities", "conversation")
    g.add_conditional_edges(
        "conversation",
        _route_after_conversation,
        {"tools": "tools", "compose": "compose"},
    )
    g.add_edge("tools", "compose")
    g.add_edge("compose", END)

    return g.compile(checkpointer=checkpointer or MemorySaver())


def build_default_graph():
    """Graph dùng MCP thật + skill catalog từ config. [DONE]"""
    from agent.config import get_settings
    from agent.guardrail_llm import build_guardrail_llm

    settings = get_settings()
    skills = SkillRegistry.load(settings.skills_dir)
    mcp = MCPClient(settings.mcp)
    return build_graph(
        skills,
        mcp,
        llm_model=settings.llm_model,
        guardrail_llm=build_guardrail_llm(settings),
    )
