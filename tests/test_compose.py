"""Focused tests for US4 response composition."""

from agent.nodes.compose import _compose_overview, _not_found_prompt


def test_single_listing_avoids_fake_range_and_warns_about_sample_size():
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

    text, actions = _compose_overview(overview)

    assert "dao động" not in text
    assert "chỉ có 1 listing" in text
    assert "chưa đủ để phản ánh mặt bằng chung" in text
    assert "106.0 triệu VND/m²" in text
    assert "74.2 m²" in text
    assert actions[0]["type"] == "overview"


def test_not_found_prompt_explains_what_failed():
    text = _not_found_prompt("khong co that 123")
    assert '"khong co that 123"' in text
    assert "Không tìm thấy dự án" in text
