"""materialize — turn HOT Shared-Memory query templates into reusable assets.

dash's Engineer materializes repeated metrics (e.g. dash.monthly_mrr) so a hot
metric is computed once and served instantly. Here we detect templates that have
been reused enough (verified_count >= threshold) and surface them as asset
CANDIDATES.

Deliberately conservative v1: we DETECT + SURFACE, we do not auto-run DDL. Two
reasons: (1) Power BI templates are DAX (`EVALUATE …`) — not materializable as a
relational view; (2) executing generated DDL unattended is risky. A relational
(schema/file) SQL template is marked `materializable=True` so the existing
Engineer-assets path (`build_data_asset`) can build it on explicit request.

Flag-gated by HYBRID_ASSET_MATERIALIZE. Fail-soft.
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from app.models.agent_knowledge import AgentKnowledge

logger = logging.getLogger("app.services.knowledge.materialize")

HOT_THRESHOLD = 3


def _template_text(row) -> str:
    c = row.content_json if isinstance(row.content_json, dict) else {}
    return str(c.get("template") or row.text or "")


def _is_dax(sql_or_dax: str) -> bool:
    s = (sql_or_dax or "").lstrip().upper()
    return s.startswith("EVALUATE") or s.startswith("DEFINE")


def _materializable(row) -> bool:
    # Only relational (schema/file) SQL templates can become a view/table.
    if row.scope_kind not in ("schema", "file"):
        return False
    t = _template_text(row)
    return bool(t) and not _is_dax(t)


async def hot_asset_candidates(db, *, organization_id: str, threshold: int = HOT_THRESHOLD) -> list[dict]:
    """Reused query templates that are candidates for materialization.

    Includes DAX/model templates too (marked materializable=False) so the UI can
    show 'hot metrics' and explain which can be turned into a physical asset.
    """
    try:
        rows = (
            await db.execute(
                select(AgentKnowledge).where(
                    AgentKnowledge.organization_id == str(organization_id),
                    AgentKnowledge.kind.in_(("query_template", "dax_template")),
                    AgentKnowledge.status == "active",
                    AgentKnowledge.deleted_at.is_(None),
                    AgentKnowledge.verified_count >= int(threshold),
                )
            )
        ).scalars().all()
        rows.sort(key=lambda r: (r.verified_count or 1), reverse=True)
        out = []
        for r in rows:
            out.append({
                "id": r.id,
                "title": r.title,
                "scope_kind": r.scope_kind,
                "scope_key": r.scope_key,
                "verified_count": r.verified_count,
                "template": _template_text(r),
                "materializable": _materializable(r),
                "reason": ("relational SQL — can build a view/table"
                           if _materializable(r)
                           else "DAX / model metric — served from cache, not materialized"),
            })
        return out
    except Exception as e:  # pragma: no cover
        logger.debug("hot_asset_candidates failed: %s", e)
        return []
