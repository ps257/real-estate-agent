"""Skill loader — parse skill Markdown (frontmatter + body). [DONE]

Định dạng file & API xem docs/SKILLS.md.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

# Tách YAML frontmatter (giữa cặp `---`) khỏi body markdown.
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


class Skill(BaseModel):
    """Một skill = một cách xử lý cho một intent / user story."""

    name: str
    intent: str
    description: str
    tools: list[str] = Field(default_factory=list)      # allow-list MCP tool
    required_slots: list[str] = Field(default_factory=list)
    clarify_prompt: str | None = None
    body: str = ""                                        # prompt-fragment cho LLM

    @classmethod
    def from_markdown(cls, text: str, *, source: str = "<string>") -> "Skill":
        m = _FRONTMATTER_RE.match(text.lstrip("﻿"))
        if not m:
            raise ValueError(f"Skill thieu YAML frontmatter: {source}")
        meta = yaml.safe_load(m.group(1)) or {}
        body = m.group(2).strip()
        try:
            return cls(**meta, body=body)
        except Exception as exc:  # noqa: BLE001 — bọc lại kèm nguồn cho dễ debug
            raise ValueError(f"Skill khong hop le ({source}): {exc}") from exc

    @classmethod
    def from_file(cls, path: Path) -> "Skill":
        return cls.from_markdown(path.read_text(encoding="utf-8"), source=str(path))


class SkillRegistry:
    """Đăng ký skill, tra theo intent hoặc name."""

    def __init__(self, skills: list[Skill]) -> None:
        self._skills = skills
        self._by_intent: dict[str, Skill] = {s.intent: s for s in skills}
        self._by_name: dict[str, Skill] = {s.name: s for s in skills}

    @classmethod
    def load(cls, catalog_dir: str | Path) -> "SkillRegistry":
        """Load tất cả `*.md` trong thư mục catalog."""
        catalog = Path(catalog_dir)
        if not catalog.is_dir():
            raise FileNotFoundError(f"Khong thay skills dir: {catalog}")
        skills = [Skill.from_file(p) for p in sorted(catalog.glob("*.md"))]
        return cls(skills)

    def get(self, intent: str) -> Skill | None:
        """Skill phục vụ intent (dùng ở nodes/intent.py → chọn skill)."""
        return self._by_intent.get(intent)

    def by_name(self, name: str) -> Skill | None:
        return self._by_name.get(name)

    def all(self) -> list[Skill]:
        return list(self._skills)
