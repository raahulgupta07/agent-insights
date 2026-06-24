"""BrainGraphContextBuilder — surfaces top approved correlation edges (Phase 8).

Mirrors BrainContextBuilder. When flags.BRAIN_GRAPH is ON, injects the highest-
weight PUBLISHED correlation edges for the run's data source (published-only is
the approval invariant). When OFF -> empty section (render() == "").

HARD RULE: the graph is the ``brain_graph_edges`` pgvector table + recursive-CTE
traversal (``app.ai.brain.brain_graph.neighbors``), NOT Apache AGE.

Never raises — degrades to an empty section.
"""
from __future__ import annotations
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.context.sections.brain_graph import (
    CorrelationGraphSection,
    CorrelationEdgeItem,
)

# How many top edges to inject.
_TOP_K = 12


class BrainGraphContextBuilder:
    def __init__(self, db: AsyncSession, organization, data_source_ids: Optional[List[str]] = None):
        self.db = db
        self.organization = organization
        self.data_source_ids = data_source_ids

    async def build(self, query: Optional[str] = None) -> CorrelationGraphSection:
        # Flag gate: empty (no DB hit) when OFF.
        try:
            from app.settings.hybrid_flags import flags
            if not flags.BRAIN_GRAPH:
                return CorrelationGraphSection(items=[])
        except Exception:
            return CorrelationGraphSection(items=[])

        org_id = str(getattr(self.organization, "id", None) or "")
        if not org_id:
            return CorrelationGraphSection(items=[])

        ds_id = self.data_source_ids[0] if self.data_source_ids else None

        try:
            from sqlalchemy import select
            from app.models.brain_graph_edge import BrainGraphEdge

            stmt = select(BrainGraphEdge).where(
                BrainGraphEdge.organization_id == org_id,
                BrainGraphEdge.status == "published",
                BrainGraphEdge.deleted_at.is_(None),
            )
            # Scope to the run's data source OR org-wide (null ds) edges.
            if ds_id is not None:
                stmt = stmt.where(
                    (BrainGraphEdge.data_source_id == ds_id)
                    | (BrainGraphEdge.data_source_id.is_(None))
                )
            stmt = stmt.order_by(BrainGraphEdge.weight.desc()).limit(_TOP_K)

            res = await self.db.execute(stmt)
            rows = list(res.scalars().all())
        except Exception:
            return CorrelationGraphSection(items=[])

        items = [
            CorrelationEdgeItem(
                src=str(getattr(r, "src_entity", "") or ""),
                dst=str(getattr(r, "dst_entity", "") or ""),
                relation=str(getattr(r, "relation", "") or "related_to"),
                weight=float(getattr(r, "weight", 0.0) or 0.0),
            )
            for r in rows
            if getattr(r, "src_entity", None) and getattr(r, "dst_entity", None)
        ]
        return CorrelationGraphSection(items=items)
