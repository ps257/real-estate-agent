"""Focused tests for deterministic response composition."""

from agent.nodes.compose import _c_us4_analytics, compose
from agent.nodes.context import NodeContext


def test_us4_overview_uses_real_mcp_payload():
    overview = {
        "project": {
            "id": "amber-riverside",
            "name": "Amber Riverside",
            "district": "Hai Bà Trưng",
            "province": "Hà Nội",
        },
        "stats": {
            "count": 1,
            "price_per_m2_vnd": {"min": 106_000_000, "max": 106_000_000, "avg": 106_000_000},
            "area_m2": {"min": 74.2, "max": 74.2, "avg": 74.2},
            "bedrooms_range": {"min": 2, "max": 2},
            "by_property_type": {"can_ho": 1},
            "by_price_type": {
                "estimate": {
                    "price_vnd": {
                        "min": 7_880_000_000,
                        "max": 7_880_000_000,
                        "avg": 7_880_000_000,
                    },
                    "coverage": {"price_vnd_count": 1},
                }
            },
        },
    }

    text, actions = _c_us4_analytics(
        [{"name": "project_overview", "result": overview}],
        {"user_input": "Phân tích tổng quan dự án Amber Riverside"},
    )

    assert "Amber Riverside" in text
    assert "1 căn" in text
    assert actions[0]["type"] == "overview"
    assert actions[0]["overview"] == overview


class _FailIfCalledComposeLLM:
    async def compose_text(self, *args, **kwargs):
        raise AssertionError("Compose LLM must not rewrite deterministic safety text")


async def test_guardrail_response_is_not_rewritten(skills, null_mcp):
    ctx = NodeContext(
        skills=skills,
        mcp=null_mcp,
        compose_llm=_FailIfCalledComposeLLM(),
    )
    state = {
        "intent": None,
        "guardrail": {
            "code": "out_of_domain",
            "message": "Em chỉ hỗ trợ bất động sản.",
            "suggestions": [],
        },
        "cot": [],
    }

    out = await compose(state, ctx)

    assert out["response_text"] == "Em chỉ hỗ trợ bất động sản."
    assert out["actions"][0]["type"] == "clarify"


async def test_unknown_response_is_not_rewritten(skills, null_mcp):
    ctx = NodeContext(
        skills=skills,
        mcp=null_mcp,
        compose_llm=_FailIfCalledComposeLLM(),
    )

    out = await compose({"intent": "UNKNOWN", "cot": []}, ctx)

    assert "chưa xác định được nhu cầu bất động sản" in out["response_text"]
    assert out["actions"][0]["type"] == "clarify"
