"""CodeBankContextBuilder — Kepler Phase 2 (code-memory read).

Folds code-memory recall into a ContextHub builder. Gated transitively by
flags.CODE_BANK (recall_proven_code returns [] when off). Never raises —
degrades to an empty section. Mirrors BrainContextBuilder exactly.
"""
from __future__ import annotations
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.brain.code_cache_store import recall_proven_code
from app.ai.context.sections.code_examples import CodeExamplesSection, CodeExampleItem


class CodeBankContextBuilder:
    def __init__(self, db: AsyncSession, organization, data_source_ids: Optional[List[str]] = None):
        self.db = db
        self.organization = organization
        self.data_source_ids = data_source_ids

    async def build(self, query: Optional[str] = None) -> CodeExamplesSection:
        if not query or not str(query).strip():
            return CodeExamplesSection(items=[])
        ds_id = self.data_source_ids[0] if self.data_source_ids else None
        try:
            recalled = await recall_proven_code(
                self.db,
                organization_id=str(self.organization.id),
                data_source_id=ds_id,
                question=query,
            )
        except Exception:
            recalled = []
        return CodeExamplesSection(
            items=[CodeExampleItem(question=r.get("question", ""), code=r.get("code", "")) for r in (recalled or [])]
        )
