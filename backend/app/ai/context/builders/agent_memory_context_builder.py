"""AgentMemoryContextBuilder — surfaces relevant remembered notes (agent memory).

Mirrors DocsContextBuilder. When flags.AGENT_MEMORY is ON, recalls the most
relevant visible memories (own personal + approved shared) for the run's query
+ user + data source and injects them as a "### Remembered notes" block.
Retrieval is QUERY-DRIVEN (vectorless FTS / Jaccard) — no query, no DB hit.
When OFF -> empty section (render() == ""), with no DB hit.

Never raises — degrades to an empty section.
"""
from __future__ import annotations
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.context.sections.agent_memory import (
    AgentMemorySection,
    MemoryItem,
)

# How many top memories to recall/inject.
_TOP_K = 5


class AgentMemoryContextBuilder:
    def __init__(
        self,
        db: AsyncSession,
        organization,
        user=None,
        data_source_ids: Optional[List[str]] = None,
    ):
        self.db = db
        self.organization = organization
        self.user = user
        self.data_source_ids = data_source_ids

    async def build(self, query: Optional[str] = None) -> AgentMemorySection:
        # Flag gate: empty (no DB hit) when OFF.
        try:
            from app.settings.hybrid_flags import flags
            if not flags.AGENT_MEMORY:
                return AgentMemorySection(items=[])
        except Exception:
            return AgentMemorySection(items=[])

        # Recall is query-driven — nothing to search without a query.
        if not (query and query.strip()):
            return AgentMemorySection(items=[])

        org_id = str(getattr(self.organization, "id", None) or "")
        if not org_id:
            return AgentMemorySection(items=[])

        user_id = str(getattr(self.user, "id", None) or "") or None
        ds_id = self.data_source_ids[0] if self.data_source_ids else None

        try:
            from app.ai.brain import agent_memory

            rows = await agent_memory.recall(
                self.db,
                organization=self.organization,
                query=query,
                user_id=user_id,
                data_source_id=ds_id,
                k=_TOP_K,
            )
        except Exception:
            return AgentMemorySection(items=[])

        items = [
            MemoryItem(
                mem_key=str((r.get("mem_key") if isinstance(r, dict) else None) or ""),
                text=str((r.get("text") if isinstance(r, dict) else None) or ""),
            )
            for r in (rows or [])
            if isinstance(r, dict)
        ]
        return AgentMemorySection(items=items)
