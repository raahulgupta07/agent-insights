"""Usage-trust table ranking (flag ``HYBRID_USAGE_TRUST``, default OFF).

Today's table-selection ranking (``SchemaContextBuilder.build``) orders tables by
a *semantic/structural* composite score — usage counts, centrality, richness. That
treats a table that was queried once in a throwaway exploration the same as a table
that backs a dozen saved dashboards and verified goldens.

This module adds a **trust** dimension answering "is this table actually relied
upon?" (OpenAI data-agent principle: *dashboard-backed > one-off exploratory*). It
is computed from REAL curated/verified usage and blended into the existing
relevance so the agent picks the right table first-try.

Two public functions:

- ``table_trust_scores(db, *, organization_id, data_source_id=None) -> dict``
  Async. Per-table trust in ``[0, 1]``, **keyed by lowercased table name** (the
  same key ``SchemaContextBuilder`` uses to look up ``TableStats`` and to name its
  ``PromptTable`` rows). Returns ``{}`` when the flag is OFF or no trust signal
  exists — callers treat ``{}`` as "no change". Never raises.

- ``rank_tables(tables, scores, *, weight=0.5) -> list``
  Pure. Blend an existing per-table relevance (read off each table's ``.score``)
  with the trust score and return the tables re-ordered best-first. Empty
  ``scores`` -> the input order is returned unchanged (identity), so an OFF flag
  is byte-identical to today's ordering.

Every signal is fail-soft: a missing table, model, or column contributes 0 rather
than aborting the ranking. The module has NO side effects.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.settings.hybrid_flags import flags


# Relative weights of the four trust signals before normalisation. Curated
# library queries and verified goldens are the strongest "relied upon" evidence;
# raw verified usage and dashboard backing follow.
_W_LIBRARY = 1.0
_W_STATS = 1.0
_W_DASHBOARD = 1.5
_W_MEMORY = 0.75


async def table_trust_scores(
    db: AsyncSession,
    *,
    organization_id: str,
    data_source_id: Optional[str] = None,
) -> Dict[str, float]:
    """Return ``{table_name_lower: trust in [0,1]}`` for an org's tables.

    ``data_source_id`` (optional) scopes the computation to one data source — the
    ``SchemaContextBuilder`` iterates per data source, so it passes it. When the
    flag is OFF, or nothing trustworthy exists, returns ``{}`` (caller: no-op).
    Never raises.
    """
    if not flags.USAGE_TRUST:
        return {}

    try:
        org_id = str(organization_id)
        ds_id = str(data_source_id) if data_source_id else None

        # Authoritative table-name set for these data source(s) — gives us the
        # exact keys the consumer ranks by, and the vocabulary for SQL matching.
        names = await _table_names(db, org_id, ds_id)
        if not names:
            return {}

        raw: Dict[str, float] = {n: 0.0 for n in names}

        _accumulate(raw, await _library_trust(db, org_id, ds_id, names), _W_LIBRARY)
        _accumulate(raw, await _stats_trust(db, org_id, ds_id, names), _W_STATS)
        _accumulate(raw, await _dashboard_trust(db, org_id, ds_id, names), _W_DASHBOARD)
        _accumulate(raw, await _memory_trust(db, org_id, ds_id, names), _W_MEMORY)

        return _normalize_log(raw)
    except Exception:
        # Trust is an enhancement — never let it break schema context.
        return {}


def rank_tables(tables: List[Any], scores: Dict[str, float], *, weight: float = 0.5) -> List[Any]:
    """Re-order ``tables`` blending their existing relevance with ``scores``.

    ``tables`` are objects/dicts/tuples exposing a table *name* and a *relevance*
    (a ``PromptTable`` with ``.name`` + ``.score`` in the live path). ``scores`` is
    the ``table_trust_scores`` output (name-lower -> trust in ``[0,1]``).

    ``weight`` is trust's share of the blended key: ``0`` ignores trust (input
    order preserved), ``1`` ranks purely by trust. Relevance is min-max normalised
    across the given list so the two live on the same ``[0,1]`` scale.

    Pure; stable; returns a NEW list. Empty ``scores`` -> ``list(tables)``
    unchanged, so an OFF flag keeps today's ordering exactly.
    """
    if not scores or not tables:
        return list(tables)

    w = min(1.0, max(0.0, float(weight)))

    rels = [_relevance_of(t) for t in tables]
    lo, hi = min(rels), max(rels)
    span = hi - lo

    def _blended(idx: int, t: Any) -> float:
        rel_norm = (rels[idx] - lo) / span if span > 1e-12 else 0.0
        trust = float(scores.get(_name_of(t).lower(), 0.0) or 0.0)
        return (1.0 - w) * rel_norm + w * trust

    # Decorate with original index for a stable sort (ties keep input order).
    order = sorted(
        range(len(tables)),
        key=lambda i: (_blended(i, tables[i]), -i),
        reverse=True,
    )
    return [tables[i] for i in order]


# --------------------------------------------------------------------------- #
# Signal helpers — each returns {table_name_lower: raw_contribution}, fail-soft #
# --------------------------------------------------------------------------- #

async def _table_names(db: AsyncSession, org_id: str, ds_id: Optional[str]) -> List[str]:
    """Active table names for the org's data source(s)."""
    try:
        from app.models.datasource_table import DataSourceTable
        from app.models.data_source import DataSource

        q = (
            select(DataSourceTable.name)
            .join(DataSource, DataSourceTable.datasource_id == DataSource.id)
            .where(DataSource.organization_id == org_id)
        )
        if ds_id:
            q = q.where(DataSourceTable.datasource_id == ds_id)
        res = await db.execute(q)
        return [n for (n,) in res.all() if n]
    except Exception:
        return []


async def _library_trust(
    db: AsyncSession, org_id: str, ds_id: Optional[str], names: List[str]
) -> Dict[str, float]:
    """Saved/verified/golden Query-Library items referencing a table (name in SQL).

    A curated, reusable, verified query is the clearest "relied upon" signal.
    Contribution per matching item = run_count + 3*verified_count + 8*is_golden.
    """
    out: Dict[str, float] = {}
    try:
        from app.models.query_library import QueryLibraryItem

        q = select(QueryLibraryItem).where(QueryLibraryItem.organization_id == org_id)
        if ds_id:
            q = q.where(QueryLibraryItem.data_source_id == ds_id)
        res = await db.execute(q)
        items = res.scalars().all()
        if not items:
            return out

        lowered = [(n, n.lower()) for n in names]
        for it in items:
            sql = (getattr(it, "sql_text", "") or "").lower()
            if not sql:
                continue
            weight = (
                float(getattr(it, "run_count", 0) or 0)
                + 3.0 * float(getattr(it, "verified_count", 0) or 0)
                + (8.0 if getattr(it, "is_golden", False) else 0.0)
            )
            if weight <= 0:
                weight = 1.0  # a saved query still counts as curated backing
            for orig, low in lowered:
                if _name_in_sql(low, sql):
                    out[orig] = out.get(orig, 0.0) + weight
    except Exception:
        return out
    return out


async def _stats_trust(
    db: AsyncSession, org_id: str, ds_id: Optional[str], names: List[str]
) -> Dict[str, float]:
    """Verified/trusted real usage from the ``TableStats`` rollup.

    Emphasises the *trust-flavoured* columns (trusted usage + positive feedback)
    rather than raw usage, which the base relevance already rewards.
    Contribution = trusted_usage_count + 2*pos_feedback_count + weighted_pos_feedback.
    """
    out: Dict[str, float] = {}
    try:
        from app.models.table_stats import TableStats

        q = select(TableStats).where(
            TableStats.org_id == org_id,
            TableStats.report_id == None,  # noqa: E711 — org-wide rollup row
        )
        if ds_id:
            q = q.where(TableStats.data_source_id == ds_id)
        res = await db.execute(q)
        name_lut = {n.lower(): n for n in names}
        for s in res.scalars().all():
            key = _fqn_leaf((s.table_fqn or "").lower())
            orig = name_lut.get(key)
            if not orig:
                continue
            contrib = (
                float(getattr(s, "trusted_usage_count", 0) or 0)
                + 2.0 * float(getattr(s, "pos_feedback_count", 0) or 0)
                + float(getattr(s, "weighted_pos_feedback", 0.0) or 0.0)
            )
            if contrib > 0:
                out[orig] = out.get(orig, 0.0) + contrib
    except Exception:
        return out
    return out


async def _dashboard_trust(
    db: AsyncSession, org_id: str, ds_id: Optional[str], names: List[str]
) -> Dict[str, float]:
    """Dashboard/artifact backing: distinct reports that (a) used the table in a
    successful step AND (b) produced a saved Artifact. This is the direct
    "dashboard-backed > exploratory" signal. Contribution = distinct backed reports.
    """
    out: Dict[str, float] = {}
    try:
        from app.models.table_usage_event import TableUsageEvent
        from app.models.artifact import Artifact

        # report_ids in this org that have at least one artifact = "dashboard-backed"
        art_q = select(Artifact.report_id).where(Artifact.organization_id == org_id)
        art_res = await db.execute(art_q)
        backed_reports = {str(r) for (r,) in art_res.all() if r}
        if not backed_reports:
            return out

        q = select(
            TableUsageEvent.table_fqn,
            func.count(func.distinct(TableUsageEvent.report_id)),
        ).where(
            TableUsageEvent.org_id == org_id,
            TableUsageEvent.success == True,  # noqa: E712
            TableUsageEvent.report_id.in_(backed_reports),
        )
        if ds_id:
            q = q.where(TableUsageEvent.data_source_id == ds_id)
        q = q.group_by(TableUsageEvent.table_fqn)
        res = await db.execute(q)

        name_lut = {n.lower(): n for n in names}
        for fqn, cnt in res.all():
            orig = name_lut.get(_fqn_leaf((fqn or "").lower()))
            if orig and cnt:
                out[orig] = out.get(orig, 0.0) + float(cnt)
    except Exception:
        return out
    return out


async def _memory_trust(
    db: AsyncSession, org_id: str, ds_id: Optional[str], names: List[str]
) -> Dict[str, float]:
    """Shared-Memory (``agent_knowledge``) verified learnings that name the table.

    An active, repeatedly-verified learning that references a table is a soft trust
    boost. Scoped to active rows (optionally pinned to the data source).
    Contribution = verified_count per mentioning row.
    """
    out: Dict[str, float] = {}
    try:
        from app.models.agent_knowledge import AgentKnowledge

        q = select(AgentKnowledge).where(
            AgentKnowledge.organization_id == org_id,
            AgentKnowledge.status == "active",
        )
        res = await db.execute(q)
        rows = res.scalars().all()
        if not rows:
            return out

        lowered = [(n, n.lower()) for n in names]
        for r in rows:
            # If pinned to a data source, honour the scope; unpinned = org-wide.
            pin = getattr(r, "data_source_id", None)
            if ds_id and pin and str(pin) != ds_id:
                continue
            blob = " ".join(
                str(x or "")
                for x in (getattr(r, "title", ""), getattr(r, "text", ""), getattr(r, "content_json", ""))
            ).lower()
            if not blob:
                continue
            vc = float(getattr(r, "verified_count", 1) or 1)
            for orig, low in lowered:
                if low and low in blob:
                    out[orig] = out.get(orig, 0.0) + vc
    except Exception:
        return out
    return out


# --------------------------------------------------------------------------- #
# Small pure utilities                                                          #
# --------------------------------------------------------------------------- #

def _accumulate(target: Dict[str, float], part: Dict[str, float], weight: float) -> None:
    """Add ``weight * part[k]`` into ``target[k]`` (target pre-seeded with names)."""
    if not part:
        return
    for k, v in part.items():
        if k in target:
            target[k] += weight * float(v or 0.0)


def _normalize_log(raw: Dict[str, float]) -> Dict[str, float]:
    """Log-scale then divide by the max so the busiest table maps to ~1.0.

    Log scaling stops one hyper-used table from flattening every other trust
    score to ~0. Returns ``{}`` when there is no positive signal at all (so the
    caller leaves ordering untouched).
    """
    logged = {k: math.log1p(v) for k, v in raw.items() if v and v > 0}
    if not logged:
        return {}
    top = max(logged.values())
    if top <= 0:
        return {}
    return {k: round(v / top, 6) for k, v in logged.items()}


def _fqn_leaf(fqn: str) -> str:
    """Best-effort bare table name from a possibly-qualified fqn.

    ``TableStats.table_fqn`` may be stored bare (``account``) or prefixed
    (``<data_source_id>.account``). We can't know a table's own dots vs a prefix
    separator, so take the last dot-segment — matches the common
    ``<prefix>.<table>`` shape and is a no-op for bare names.
    """
    if not fqn:
        return fqn
    return fqn.rsplit(".", 1)[-1]


def _name_in_sql(name_low: str, sql_low: str) -> bool:
    """Word-boundary-ish membership of a table name inside a lowercased SQL string.

    Avoids ``order`` matching inside ``orders`` by requiring the surrounding chars
    (if any) to be non-identifier characters.
    """
    if not name_low:
        return False
    start = 0
    n = len(name_low)
    while True:
        i = sql_low.find(name_low, start)
        if i < 0:
            return False
        before = sql_low[i - 1] if i > 0 else " "
        after = sql_low[i + n] if i + n < len(sql_low) else " "
        if not _is_ident(before) and not _is_ident(after):
            return True
        start = i + 1


def _is_ident(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def _name_of(t: Any) -> str:
    """Table name from an object (.name), dict ('name'), or (name, relevance) tuple."""
    if hasattr(t, "name"):
        return str(getattr(t, "name", "") or "")
    if isinstance(t, dict):
        return str(t.get("name", "") or "")
    if isinstance(t, (tuple, list)) and t:
        return str(t[0] or "")
    return ""


def _relevance_of(t: Any) -> float:
    """Existing relevance from an object (.score), dict ('score'), or tuple[1]."""
    try:
        if hasattr(t, "score"):
            return float(getattr(t, "score", 0.0) or 0.0)
        if isinstance(t, dict):
            return float(t.get("score", 0.0) or 0.0)
        if isinstance(t, (tuple, list)) and len(t) > 1:
            return float(t[1] or 0.0)
    except Exception:
        return 0.0
    return 0.0
