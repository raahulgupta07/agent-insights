"""Pipeline v1 (P3): Definition Registry service.

Turns parsed logic-doc triples (P2) into ``AgentDefinition`` rows — the single
source of truth referenced by golden generation (P4), the eval gate (P5), and
the correction loop (P6). Pure-ish + fail-soft; commits its own writes.
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# question keyword -> canonical metric name (best-effort)
_NAME_HINTS = [
    (r"\blead", "Lead"),
    (r"\bnew user", "New User"),
    (r"\bunsuccessful", "Unsuccessful Calls"),
    (r"\bsuccessful", "Successful Calls"),
    (r"\bchannel", "Channel Breakdown"),
    (r"\bbrand switch", "Brand Switch"),
]


def name_from_triple(t: Dict) -> str:
    q = (t.get("question") or "").lower()
    for pat, nm in _NAME_HINTS:
        if re.search(pat, q):
            return nm
    return f"Q{t.get('n', '?')}"


def build_predicate(filters: List[Dict]) -> "tuple[str, list]":
    """[{column,op,value}] -> ('"col"=\'val\' AND ...', [columns]).

    Skips 'groupby' hints (those are dimensions, not equality filters). Escapes
    single quotes in values. Returns ('', []) when there's no equality filter.
    """
    parts: List[str] = []
    cols: List[str] = []
    for f in filters or []:
        if f.get("op") != "=":
            continue
        col = str(f.get("column", "")).strip()
        val = str(f.get("value", "")).strip()
        if not col or not val:
            continue
        # a value like "Successful / Unsuccessful" is an OR set -> expand
        alts = [v.strip() for v in re.split(r"\s*/\s*", val) if v.strip()]
        col_sql = '"' + col.replace('"', '') + '"'
        if len(alts) > 1:
            inlist = ", ".join("'" + a.replace("'", "''") + "'" for a in alts)
            parts.append(f"{col_sql} IN ({inlist})")
        else:
            parts.append(f"{col_sql}='" + val.replace("'", "''") + "'")
        cols.append(col)
    return " AND ".join(parts), cols


async def upsert_from_triples(
    db, *, organization, triples: List[Dict],
    data_source_id: Optional[str] = None, studio_id: Optional[str] = None,
    source_doc: Optional[str] = None,
) -> dict:
    """Create/update AgentDefinition rows from logic triples. Never raises.

    Returns ``{"created": n, "updated": m, "names": [...]}``. Definitions are
    born ``status='pending'`` (review gate). An existing (org, name) def is
    updated in place (predicate/expected/logic refreshed) unless it's approved
    AND already has a predicate (don't clobber a human-approved rule silently —
    leave it for the correction loop).
    """
    from sqlalchemy import select
    from app.models.agent_definition import AgentDefinition

    out = {"created": 0, "updated": 0, "names": []}
    try:
        org_id = str(organization.id)
        for t in triples or []:
            filters = t.get("filters") or []
            predicate, cols = build_predicate(filters)
            if not predicate:
                continue  # nothing to implement -> skip (e.g. prose-only answer)
            name = name_from_triple(t)
            expected = []
            if t.get("expected") is not None:
                expected = [{"scope": "total", "value": t["expected"]}]

            existing = (
                await db.execute(
                    select(AgentDefinition).where(
                        AgentDefinition.organization_id == org_id,
                        AgentDefinition.name == name,
                        AgentDefinition.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()

            if existing is None:
                db.add(AgentDefinition(
                    organization_id=org_id, data_source_id=data_source_id,
                    studio_id=studio_id, name=name, kind="metric",
                    sql_predicate=predicate, filters=filters, columns_used=cols,
                    expected=expected, logic_text=t.get("logic_text", ""),
                    description=t.get("question", ""), source_doc=source_doc,
                    status="pending",
                ))
                out["created"] += 1
                out["names"].append(name)
            else:
                if existing.status == "approved" and (existing.sql_predicate or "").strip():
                    continue  # leave approved rules to the correction loop
                existing.sql_predicate = predicate
                existing.filters = filters
                existing.columns_used = cols
                if expected:
                    existing.expected = expected
                existing.logic_text = t.get("logic_text", "")
                existing.source_doc = source_doc
                out["updated"] += 1
                out["names"].append(name)
        await db.commit()
        logger.info("registry: +%d defs, ~%d updated from %s",
                    out["created"], out["updated"], source_doc)
    except Exception:  # noqa: BLE001
        logger.warning("registry.upsert_from_triples failed", exc_info=True)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
    return out
