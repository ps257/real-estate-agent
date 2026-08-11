"""Regression tests for US4 rule-based routing and entity cleanup."""

from agent.nodes.entities import _clean_project_query
from agent.nodes.intent import _is_analytics_query


def test_natural_market_price_question_routes_to_us4():
    assert _is_analytics_query(
        "Mặt bằng giá và diện tích ở Amber Riverside hiện thế nào?"
    )


def test_search_request_does_not_route_to_us4():
    assert not _is_analytics_query("Tìm căn hộ tại Vinhomes Ocean Park")


def test_project_cleanup_removes_analytics_filler():
    assert (
        _clean_project_query("Cho tôi xem thống kê giá của dự án Amber Riverside")
        == "amber riverside"
    )
    assert (
        _clean_project_query("Mặt bằng giá và diện tích ở Amber Riverside hiện thế nào?")
        == "amber riverside"
    )
