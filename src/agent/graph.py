"""Build LangGraph — wiring node + conditional edges + checkpointer. [DONE]

Sơ đồ: START → normalize → intent → entities → conversation
             → (đủ slot?) → tools → compose → END
             → (thiếu slot) ─────────────→ compose → END

Xem docs/ARCHITECTURE.md §2.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import partial
from typing import Any

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
from agent.intent_llm import FALLBACK_INTENT
from agent.skills.loader import SkillRegistry
from agent.state import AgentState
from agent.telemetry import get_telemetry

NodeFunction = Callable[[AgentState, NodeContext], Awaitable[dict[str, Any]]]


async def _observed_node(
    state: AgentState,
    *,
    ctx: NodeContext,
    node: NodeFunction,
    observation_name: str,
    observation_type: str,
    stage: str,
) -> dict[str, Any]:
    """Run a node in a child observation with an explicit, COT-free schema."""

    text = state.get("normalized_input") or state.get("user_input", "")
    with get_telemetry().observation(
        name=observation_name,
        as_type=observation_type,
        input={"message": text},
        metadata={"stage": stage},
    ) as observation:
        result = await node(state, ctx)
        if stage == "guardrail":
            guardrail = result.get("guardrail")
            output = {
                "allowed": guardrail is None,
                "reason_code": guardrail.get("code") if isinstance(guardrail, dict) else None,
            }
        elif stage == "routing":
            output = {
                "intent": result.get("intent"),
                "active_skill": result.get("active_skill"),
            }
        elif stage == "entities":
            entities = result.get("entities") or {}
            output = {
                "entity_fields": sorted(str(key) for key in entities),
                "entity_count": len(entities),
            }
        else:
            slots = result.get("slots") or {}
            output = {
                "slot_fields": sorted(str(key) for key in slots),
                "needs_clarification": bool(result.get("needs_clarification")),
            }
        observation.update(output=output)
        return result


def _route_after_normalize(state: AgentState) -> str:
    """Conditional edge: guardrail chặn → compose (từ chối); hợp lệ → intent."""
    return "compose" if state.get("guardrail") else "intent"


def _route_after_intent(state: AgentState) -> str:
    """Intent không xác định → hỏi lại, tuyệt đối không gọi entities/MCP."""
    return "compose" if state.get("intent") == FALLBACK_INTENT else "entities"


def _route_after_conversation(state: AgentState) -> str:
    """Conditional edge: thiếu slot → hỏi lại (compose); đủ → gọi tool."""
    return "compose" if state.get("needs_clarification") else "tools"


def build_graph(
    skills: SkillRegistry,
    mcp: MCPProtocol,
    *,
    llm_model: str = "gpt-5.6",
    guardrail_llm=None,
    intent_llm=None,
    entities_llm=None,
    compose_llm=None,
    checkpointer=None,
):
    """Trả về graph đã compile. Bind NodeContext vào từng node qua partial.

    checkpointer=None  → MemorySaver (đổi sang RedisSaver để theo PRD).
    guardrail_llm=None → chỉ chạy guardrail tầng regex.
    intent_llm=None    → chỉ chạy rule nhanh; câu còn lại dừng ở UNKNOWN.
    entities_llm=None  → entities luôn rỗng, conversation sẽ hỏi lại.
    """
    ctx = NodeContext(
        skills=skills,
        mcp=mcp,
        llm_model=llm_model,
        guardrail_llm=guardrail_llm,
        intent_llm=intent_llm,
        entities_llm=entities_llm,
        compose_llm=compose_llm,
    )

    g = StateGraph(AgentState)
    g.add_node(
        "normalize",
        partial(
            _observed_node,
            ctx=ctx,
            node=normalize,
            observation_name="agent.guardrail",
            observation_type="guardrail",
            stage="guardrail",
        ),
    )
    g.add_node(
        "intent",
        partial(
            _observed_node,
            ctx=ctx,
            node=detect_intent,
            observation_name="agent.routing",
            observation_type="span",
            stage="routing",
        ),
    )
    g.add_node(
        "entities",
        partial(
            _observed_node,
            ctx=ctx,
            node=extract_entities,
            observation_name="agent.data.extract",
            observation_type="span",
            stage="entities",
        ),
    )
    g.add_node(
        "conversation",
        partial(
            _observed_node,
            ctx=ctx,
            node=manage_conversation,
            observation_name="agent.data.conversation",
            observation_type="span",
            stage="conversation",
        ),
    )
    g.add_node("tools", partial(call_tools, ctx=ctx))
    g.add_node("compose", partial(compose, ctx=ctx))

    g.add_edge(START, "normalize")
    g.add_conditional_edges(
        "normalize",
        _route_after_normalize,
        {"intent": "intent", "compose": "compose"},
    )
    g.add_conditional_edges(
        "intent",
        _route_after_intent,
        {"entities": "entities", "compose": "compose"},
    )
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
    from agent.compose_llm import build_compose_llm
    from agent.config import get_settings
    from agent.entities_llm import build_entity_extractor
    from agent.guardrail_llm import build_guardrail_llm
    from agent.intent_llm import build_intent_classifier

    settings = get_settings()
    skills = SkillRegistry.load(settings.skills_dir)
    mcp = MCPClient(settings.mcp)
    return build_graph(
        skills,
        mcp,
        llm_model=settings.llm_model,
        guardrail_llm=build_guardrail_llm(settings),
        intent_llm=build_intent_classifier(settings),
        entities_llm=build_entity_extractor(settings),
        compose_llm=build_compose_llm(settings),
    )
