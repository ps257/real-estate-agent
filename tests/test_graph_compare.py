"""Kiểm thử tính năng So sánh Bất Động Sản (US6_COMPARE) trong LangGraph."""

from __future__ import annotations

import pytest

from agent.graph import build_graph
from agent.runner import run_once


@pytest.mark.asyncio
async def test_compare_happy_path(skills, mock_mcp):
    """Test Happy Path: Truyền đủ 2 căn -> gọi compare_listings và trả về action compare + CTA."""
    graph = build_graph(mcp=mock_mcp, skills=skills)
    user_msg = "So sánh 2 căn lc_1 và căn lc_2 giúp mình với"

    result = await run_once(graph, user_msg, thread_id="test_happy")

    assert result["intent"] == "US6_COMPARE"

    # Kiểm tra tool_calls
    tool_names = [call["name"] for call in result["tool_calls"]]
    assert "compare_listings" in tool_names

    # Kiểm tra actions sinh ra
    action_types = [a["type"] for a in result["actions"]]
    assert "compare" in action_types
    assert "cta" in action_types

    compare_action = next(a for a in result["actions"] if a["type"] == "compare")
    data = compare_action["comparison"]

    # Danh sách căn phải được sort theo giá tăng dần: lc_1 (2 tỷ) trước lc_2 (3.5 tỷ)
    listings = data["listings"]
    assert len(listings) == 2
    assert listings[0]["id"] == "lc_1"
    assert listings[1]["id"] == "lc_2"
    assert listings[0]["price_vnd"] < listings[1]["price_vnd"]

    # Kiểm tra deltas và highlights
    assert "deltas" in data
    assert "highlights" in data
    assert "context" in data
    assert data["context"]["same_project"] is True


@pytest.mark.asyncio
async def test_compare_clarification_no_ids(skills, mock_mcp):
    """Test Clarification Path: Người dùng yêu cầu so sánh nhưng không chọn căn nào -> hỏi lại."""
    graph = build_graph(mcp=mock_mcp, skills=skills)
    user_msg = "Tôi muốn so sánh các căn hộ"

    result = await run_once(graph, user_msg, thread_id="test_clarify_no_ids")

    assert result["intent"] == "US6_COMPARE"
    assert len(result["tool_calls"]) == 0

    action_types = [a["type"] for a in result["actions"]]
    assert "clarify" in action_types

    clarify_action = next(a for a in result["actions"] if a["type"] == "clarify")
    assert "chọn từ 2 đến 4 căn" in clarify_action["prompt"]


@pytest.mark.asyncio
async def test_compare_clarification_single_id(skills, mock_mcp):
    """Test Clarification Path: Chỉ chọn 1 căn -> không đủ điều kiện so sánh, yêu cầu chọn thêm."""
    graph = build_graph(mcp=mock_mcp, skills=skills)
    user_msg = "So sánh căn lc_1"

    result = await run_once(graph, user_msg, thread_id="test_clarify_1_id")

    assert result["intent"] == "US6_COMPARE"
    assert len(result["tool_calls"]) == 0
    assert result["actions"][0]["type"] == "clarify"


@pytest.mark.asyncio
async def test_compare_context_extraction_from_prior_search(skills, mock_mcp):
    """Test Context Extraction: Người dùng nói 'so sánh 2 căn vừa tìm' khi có dữ liệu từ trước."""
    # Giả lập state có sẵn kết quả tìm kiếm trước đó
    state = {
        "messages": [],
        "normalized_input": "so sánh 2 căn vừa tìm",
        "tool_results": [
            {
                "name": "search_listings",
                "data": [
                    {"id": "lc_1", "price_vnd": 2000000000},
                    {"id": "lc_2", "price_vnd": 3500000000},
                ],
            }
        ],
    }

    from agent.nodes.context import NodeContext
    from agent.nodes.entities import extract_entities

    ctx = NodeContext(skills=skills, mcp=mock_mcp, llm_model="test")
    extracted = await extract_entities(state, ctx)

    assert extracted["entities"].get("listing_ids") == ["lc_1", "lc_2"]


@pytest.mark.asyncio
async def test_compare_price_honesty_note(skills, mock_mcp):
    """Test Guardrail & Honesty: Ghi chú rõ ràng về loại giá (asking vs estimate), không tư vấn chủ quan."""
    graph = build_graph(mcp=mock_mcp, skills=skills)
    user_msg = "So sánh căn lc_1 và lc_2"

    result = await run_once(graph, user_msg, thread_id="test_honesty")

    text = result["text"]
    # Không được chứa nhận định chủ quan "đáng mua hơn" / "nên mua"
    assert "đáng mua hơn" not in text
    assert "nên mua" not in text

    # Có chú thích về giá chào bán / giá ước tính
    assert "giá chào bán" in text or "giá ước tính" in text
