"""Test skill loader — parse frontmatter + body, tra theo intent. [DONE]"""

from __future__ import annotations

from agent.skills.loader import Skill, SkillRegistry


def test_load_all_catalog_skills(skills: SkillRegistry):
    all_skills = skills.all()
    assert len(all_skills) >= 7, "phải load đủ 7 skill (US1..US6)"
    intents = {s.intent for s in all_skills}
    assert "US1_SEARCH" in intents


def test_get_by_intent(skills: SkillRegistry):
    s = skills.get("US1_SEARCH")
    assert s is not None
    assert s.name == "search-real-estate"
    # allow-list tool phải có mặt để tools_node giới hạn.
    assert "search_listings" in s.tools
    assert "project_or_province" in s.required_slots


def test_by_name(skills: SkillRegistry):
    assert skills.by_name("search-real-estate") is not None
    assert skills.by_name("khong-ton-tai") is None


def test_parse_from_markdown():
    md = (
        "---\n"
        "name: demo\n"
        "intent: DEMO\n"
        "description: mô tả\n"
        "tools: [a, b]\n"
        "required_slots: [x]\n"
        "---\n"
        "Nội dung body hướng dẫn.\n"
    )
    s = Skill.from_markdown(md)
    assert s.name == "demo"
    assert s.tools == ["a", "b"]
    assert s.body.strip() == "Nội dung body hướng dẫn."


def test_missing_frontmatter_raises():
    import pytest

    with pytest.raises(ValueError):
        Skill.from_markdown("không có frontmatter")
