from __future__ import annotations
from typing import ClassVar, List, Optional
from pydantic import BaseModel
from app.ai.context.sections.base import ContextSection


class SkillItem(BaseModel):
    name: str
    description: str


class SkillsSection(ContextSection):
    tag_name: ClassVar[str] = "skills"
    items: List[SkillItem] = []
    injected_name: Optional[str] = None   # S5.2: auto-injected top-1 skill name
    injected_body: Optional[str] = None   # S5.2: full SKILL.md body to inline

    def render(self) -> str:
        # Nothing to render unless we have a catalog or an auto-injected skill body.
        if not self.items and not self.injected_body:
            return ""
        from app.ai.skills.loader import (
            render_skill_catalog,
            render_injected_skill,
        )
        parts: List[str] = []
        if self.items:
            parts.append(
                render_skill_catalog(
                    [{"name": it.name, "description": it.description} for it in self.items]
                )
            )
        if self.injected_body:
            parts.append(
                render_injected_skill(self.injected_name or "", self.injected_body)
            )
        return "\n\n".join(p for p in parts if p)
