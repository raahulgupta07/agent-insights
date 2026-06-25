"""HybridSearchContextBuilder — injects top knowledge hits for the question.

Query-driven. When flags.SEMANTIC_SEARCH is ON, runs the unified hybrid search
(PG full-text + pgvector + token-Jaccard, fused with RRF) over the org's
knowledge_search_index and surfaces the top hits as grounding. When OFF (or no
query / no hits) -> empty section (render() == "").

Never raises — degrades to an empty section.
"""
from __future__ import annotations
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.context.sections.hybrid_search import HybridSearchSection, HybridHitItem

_TOP_K = 6


class HybridSearchContextBuilder:
    def __init__(self, db: AsyncSession, organization, data_source_ids: Optional[List[str]] = None):
        self.db = db
        self.organization = organization
        self.data_source_ids = data_source_ids

    async def build(self, query: Optional[str] = None) -> HybridSearchSection:
        try:
            from app.settings.hybrid_flags import flags
            if not flags.SEMANTIC_SEARCH:
                return HybridSearchSection(items=[])
        except Exception:
            return HybridSearchSection(items=[])

        org_id = str(getattr(self.organization, "id", None) or "")
        if not org_id or not query:
            return HybridSearchSection(items=[])

        try:
            from app.ai.knowledge.hybrid_search import hybrid_search
            hits = await hybrid_search(
                self.db, org_id=org_id, query=query, k=_TOP_K,
                organization=self.organization,
            )
        except Exception:
            return HybridSearchSection(items=[])

        items = [
            HybridHitItem(
                kind=str(h.get("kind", "") or ""),
                title=str(h.get("title", "") or ""),
                body=str(h.get("body", "") or ""),
            )
            for h in (hits or [])
        ]
        return HybridSearchSection(items=items)
