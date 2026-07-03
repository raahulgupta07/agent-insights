"""retrieve — read the Shared Memory store and reuse "how it was done before".

Given the current agent (its data sources) + the viewer, resolve the viewer's
own scopes, then fetch ONLY the knowledge visible under those scopes (access
gate), rank it, and format it for injection into the planner context.

Access is enforced twice: the SQL filters to the viewer's own (scope_kind,
scope_key) pairs (a tuple-IN), and can_view() is the belt-and-suspenders row
check. A viewer can never receive knowledge for a model/schema/file they don't
hold, and private ('user') rows only reach their owner.

All fail-soft: on any error returns [] / None (no context injected, no crash).
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select, tuple_

from app.models.agent_knowledge import AgentKnowledge
from app.services.knowledge import access as A
from app.services.knowledge.capture import _resolve_scopes_for_source

logger = logging.getLogger("app.services.knowledge.retrieve")

MAX_ITEMS = 12


async def _viewer_scopes(db, data_source_ids: list[str]) -> list[dict]:
    scopes: list[dict] = []
    seen: set[tuple] = set()
    for ds_id in data_source_ids or []:
        for s in await _resolve_scopes_for_source(db, ds_id):
            sig = (s["scope_kind"], s["scope_key"])
            if sig not in seen:
                seen.add(sig)
                scopes.append(s)
    return scopes


async def recall_items(
    db,
    *,
    organization_id: str,
    current_user_id: str | None,
    data_source_ids: list[str],
) -> list[Any]:
    """Visible, active AgentKnowledge rows for this agent+viewer, ranked."""
    try:
        scopes = await _viewer_scopes(db, data_source_ids)
        pairs = A.visible_scope_pairs(current_user_id, scopes)
        if not pairs:
            return []
        rows = (
            await db.execute(
                select(AgentKnowledge).where(
                    AgentKnowledge.organization_id == str(organization_id),
                    AgentKnowledge.status == "active",
                    AgentKnowledge.deleted_at.is_(None),
                    tuple_(AgentKnowledge.scope_kind, AgentKnowledge.scope_key).in_(pairs),
                )
            )
        ).scalars().all()
        # belt-and-suspenders + rank: verified_count desc, updated_at desc
        rows = [r for r in rows if A.can_view(r, current_user_id, scopes)]
        rows.sort(key=lambda r: ((r.verified_count or 1), r.updated_at or 0), reverse=True)
        return rows[:MAX_ITEMS]
    except Exception as e:  # pragma: no cover
        logger.debug("shared-memory recall failed: %s", e)
        return []


def _line(row: Any) -> str:
    c = row.content_json if isinstance(row.content_json, dict) else {}
    title = (row.title or c.get("title") or row.kind or "").strip()
    if row.kind == "mistake":
        fix = c.get("fix_shape") or ""
        return f"- Avoid ({c.get('error_class', title)}): {fix}".strip()
    if row.kind in ("query_template", "dax_template"):
        tmpl = c.get("template") or row.text or ""
        return f"- Reuse pattern — {title}: {tmpl}".strip()
    if row.kind == "meaning":
        return f"- Note — {title}: {c.get('meaning') or row.text or ''}".strip()
    return f"- {title}: {row.text or ''}".strip()


async def recall_block(
    db,
    *,
    organization_id: str,
    current_user_id: str | None,
    data_source_ids: list[str],
) -> str | None:
    """A single text block for planner injection, or None if nothing to reuse."""
    rows = await recall_items(
        db, organization_id=organization_id, current_user_id=current_user_id,
        data_source_ids=data_source_ids,
    )
    if not rows:
        return None
    mistakes = [r for r in rows if r.kind == "mistake"]
    reuse = [r for r in rows if r.kind != "mistake"]
    lines: list[str] = [
        "Knowledge reused from how similar tasks were solved before on this "
        "data (sanitized, no data values). Prefer these patterns; heed the warnings.",
    ]
    for r in reuse:
        lines.append(_line(r))
    for r in mistakes:
        lines.append(_line(r))
    return "\n".join(lines)


def provenance(rows: list[Any]) -> list[dict]:
    """Compact provenance for the chat chip / UI: which scopes were reused."""
    out, seen = [], set()
    for r in rows or []:
        key = (r.scope_kind, r.scope_key)
        if key in seen:
            continue
        seen.add(key)
        out.append({"scope_kind": r.scope_kind, "scope_key": r.scope_key, "count": r.verified_count})
    return out
