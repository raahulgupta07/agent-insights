"""BrainContextBuilder — surfaces proven reasoning-cache queries (Phase 4 read).

Folds the reasoning-cache recall (previously an inline hook in agent_v2) into a
ContextHub builder. Gated transitively by flags.BRAIN_READ (recall_proven_queries
returns [] when off). Never raises — degrades to an empty section.
"""
from __future__ import annotations
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.brain.query_cache_store import recall_proven_queries
from app.ai.context.sections.brain import ProvenQueriesSection, ProvenQueryItem


class BrainContextBuilder:
    def __init__(self, db: AsyncSession, organization, data_source_ids: Optional[List[str]] = None):
        self.db = db
        self.organization = organization
        self.data_source_ids = data_source_ids

    async def build(self, query: Optional[str] = None) -> ProvenQueriesSection:
        if not query or not str(query).strip():
            return ProvenQueriesSection(items=[])
        ds_id = self.data_source_ids[0] if self.data_source_ids else None
        try:
            recalled = await recall_proven_queries(
                self.db,
                organization_id=str(self.organization.id),
                data_source_id=ds_id,
                question=query,
            )
        except Exception:
            recalled = []
        return ProvenQueriesSection(
            items=[ProvenQueryItem(question=r.get("question", ""), sql=r.get("sql", "")) for r in (recalled or [])]
        )
