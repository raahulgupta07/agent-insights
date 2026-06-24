"""DocsContextBuilder — surfaces relevant approved company-doc chunks (Phase 5 docs RAG).

Mirrors JoinGraphContextBuilder. When flags.DOC_KNOWLEDGE is ON, injects the
most-relevant chunks from approved company docs for the run's query + data
source. Retrieval is QUERY-DRIVEN (unlike join_graph) — no query, no DB hit.
When OFF -> empty section (render() == ""), with no DB hit.

Never raises — degrades to an empty section.
"""
from __future__ import annotations
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.context.sections.docs import (
    DocsSection,
    DocChunkItem,
)

# How many top doc chunks to retrieve/inject.
_TOP_K = 4


class DocsContextBuilder:
    def __init__(self, db: AsyncSession, organization, data_source_ids: Optional[List[str]] = None):
        self.db = db
        self.organization = organization
        self.data_source_ids = data_source_ids

    async def build(self, query: Optional[str] = None) -> DocsSection:
        # Flag gate: empty (no DB hit) when OFF.
        try:
            from app.settings.hybrid_flags import flags
            if not flags.DOC_KNOWLEDGE:
                return DocsSection(items=[])
        except Exception:
            return DocsSection(items=[])

        # Docs retrieval is query-driven — nothing to search without a query.
        if not (query and query.strip()):
            return DocsSection(items=[])

        org_id = str(getattr(self.organization, "id", None) or "")
        if not org_id:
            return DocsSection(items=[])

        ds_id = self.data_source_ids[0] if self.data_source_ids else None

        try:
            from app.ai.knowledge.docs_index import search_docs

            rows = await search_docs(
                self.db,
                organization=self.organization,
                query=query,
                data_source_id=ds_id,
                k=_TOP_K,
            )
        except Exception:
            return DocsSection(items=[])

        items = [
            DocChunkItem(
                title=str((r.get("title") if isinstance(r, dict) else None) or ""),
                text=str((r.get("text") if isinstance(r, dict) else None) or ""),
            )
            for r in (rows or [])
            if isinstance(r, dict)
        ]
        return DocsSection(items=items)
