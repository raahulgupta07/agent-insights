from __future__ import annotations
from typing import ClassVar, List
from pydantic import BaseModel
from app.ai.context.sections.base import ContextSection


class ProvenQueryItem(BaseModel):
    question: str
    sql: str


class ProvenQueriesSection(ContextSection):
    tag_name: ClassVar[str] = "proven_queries"
    items: List[ProvenQueryItem] = []

    def render(self) -> str:
        if not self.items:
            return ""
        # Reuse the canonical reasoning-cache block formatter so the planner
        # sees byte-identical text to the prior inline hook.
        from app.ai.brain.query_cache_store import render_proven_queries
        return render_proven_queries(
            [{"question": it.question, "sql": it.sql} for it in self.items]
        )
