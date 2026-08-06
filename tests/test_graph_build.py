"""Test graph COMPILE được (hạ tầng). [DONE]

Chỉ kiểm tra wiring build/compile thành công với MCP rỗng — KHÔNG chạy flow US1
(không invoke qua tools/compose) để tránh lộ lời giải.
"""

from __future__ import annotations

from agent.graph import build_graph


def test_graph_compiles(skills, null_mcp):
    graph = build_graph(skills, null_mcp)
    assert graph is not None
    # Graph đã compile phải có invoke/astream (interface runnable của LangGraph).
    assert hasattr(graph, "ainvoke")
    assert hasattr(graph, "astream")


def test_graph_has_expected_nodes(skills, null_mcp):
    graph = build_graph(skills, null_mcp)
    node_names = set(graph.get_graph().nodes.keys())
    for expected in {"normalize", "intent", "entities", "conversation", "tools", "compose"}:
        assert expected in node_names, f"thiếu node {expected}"
