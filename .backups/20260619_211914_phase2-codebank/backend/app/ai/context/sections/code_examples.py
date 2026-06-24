"""CodeExamplesSection — Kepler Phase 2 (code-memory read).

Surfaces the closest proven generate_df snippets for the current question so the
Coder reuses working logic. Mirrors ProvenQueriesSection exactly.
"""
from __future__ import annotations
from typing import ClassVar, List
from pydantic import BaseModel
from app.ai.context.sections.base import ContextSection


class CodeExampleItem(BaseModel):
    question: str
    code: str


class CodeExamplesSection(ContextSection):
    tag_name: ClassVar[str] = "proven_code"
    items: List[CodeExampleItem] = []

    def render(self) -> str:
        if not self.items:
            return ""
        from app.ai.brain.code_cache_store import render_proven_code
        return render_proven_code(
            [{"question": it.question, "code": it.code} for it in self.items]
        )
