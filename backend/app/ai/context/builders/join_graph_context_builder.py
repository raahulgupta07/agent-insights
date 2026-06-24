"""JoinGraphContextBuilder — surfaces top approved table-join edges (Phase 6).

Mirrors BrainGraphContextBuilder. When flags.JOIN_GRAPH is ON, injects the
most-used APPROVED join edges (table.col = table.col) for the run's data source
(approved-only is the approval invariant). When OFF -> empty section
(render() == ""), with no DB hit.

Never raises — degrades to an empty section.
"""
from __future__ import annotations
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.context.sections.join_graph import (
    JoinGraphSection,
    JoinEdgeItem,
)

# How many top join edges to inject.
_TOP_K = 20


class JoinGraphContextBuilder:
    def __init__(self, db: AsyncSession, organization, data_source_ids: Optional[List[str]] = None):
        self.db = db
        self.organization = organization
        self.data_source_ids = data_source_ids

    async def build(self, query: Optional[str] = None) -> JoinGraphSection:
        # Flag gate: empty (no DB hit) when OFF.
        try:
            from app.settings.hybrid_flags import flags
            if not flags.JOIN_GRAPH:
                return JoinGraphSection(items=[])
        except Exception:
            return JoinGraphSection(items=[])

        org_id = str(getattr(self.organization, "id", None) or "")
        if not org_id:
            return JoinGraphSection(items=[])

        ds_id = self.data_source_ids[0] if self.data_source_ids else None

        try:
            from sqlalchemy import select
            from app.models.table_edge import TableEdge

            stmt = select(TableEdge).where(
                TableEdge.organization_id == org_id,
                TableEdge.status == "approved",
                TableEdge.deleted_at.is_(None),
            )
            # Scope to the run's data source OR org-wide (null ds) edges.
            if ds_id is not None:
                stmt = stmt.where(
                    (TableEdge.data_source_id == ds_id)
                    | (TableEdge.data_source_id.is_(None))
                )
            stmt = stmt.order_by(
                TableEdge.join_count.desc(),
                TableEdge.confidence.desc(),
            ).limit(_TOP_K)

            res = await self.db.execute(stmt)
            rows = list(res.scalars().all())
        except Exception:
            return JoinGraphSection(items=[])

        items = [
            JoinEdgeItem(
                left_table=str(getattr(r, "left_table", "") or ""),
                left_col=str(getattr(r, "left_col", "") or ""),
                right_table=str(getattr(r, "right_table", "") or ""),
                right_col=str(getattr(r, "right_col", "") or ""),
                join_count=int(getattr(r, "join_count", 0) or 0),
                confidence=float(getattr(r, "confidence", 0.0) or 0.0),
            )
            for r in rows
            if getattr(r, "left_table", None) and getattr(r, "right_table", None)
        ]
        return JoinGraphSection(items=items)
