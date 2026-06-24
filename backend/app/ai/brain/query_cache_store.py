"""
Reasoning-cache store (Phase 4 read / Phase 5 write)
====================================================

Pure-Postgres reasoning-cache — no new infra. Captures proven read-only SELECTs
the agent ran successfully, keyed by a normalized-question hash + data-source
scope, and surfaces them back to the planner as PROVEN QUERIES context.

Design rules honored:
- Nothing is hardcoded. We store the SQL the agent itself wrote; a downstream
  serve path re-runs it LIVE for fresh numbers. This module only stores/recalls.
- Capture is gated by flags.QUERY_CACHE; injection by flags.BRAIN_READ.
- Captured rows land status='pending'. Only status='active' rows are surfaced —
  promotion happens through the dash approval gate (no new gate here).
- Dependency-free normalization (hashlib + re). Safe no-ops if flag off or no db.

This module is intentionally side-effect-light: every public coroutine swallows
its own errors and degrades to a no-op so the agent loop never breaks on cache.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Statements we are willing to cache + later re-run. Read-only only.
_READ_ONLY_RE = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)
_WRITE_TOKENS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|MERGE|REPLACE|COPY|CALL)\b",
    re.IGNORECASE,
)
_PUNCT_TAIL = re.compile(r"[\s\?\.\!,;:]+$")
_WS = re.compile(r"\s+")
_STOP = {"the", "a", "an", "of", "for", "to", "in", "on", "is", "are", "me", "show", "please", "and", "by"}

# How many proven queries to surface, and the fuzzy-match floor (token Jaccard).
MAX_PROVEN = 3
FUZZY_FLOOR = 0.6


def normalize_question(text: str) -> str:
    """Lowercase, collapse whitespace, strip trailing punctuation. Deterministic."""
    if not text:
        return ""
    t = _WS.sub(" ", text.strip().lower())
    return _PUNCT_TAIL.sub("", t)


def question_hash(norm: str) -> str:
    """SHA-256 of the normalized question — the exact-match lookup key."""
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def _sources_fp(ids: Optional[List[str]]) -> Optional[str]:
    """Stable fingerprint of a PINNED multi-source set, or None.

    Mirrors ``answer_cache._sources_fp``: a deterministic ``,``-joined sorted id
    string ONLY when the set has MORE THAN ONE source. Single-source or None ->
    None, so the cache key is byte-identical to before for the common case.
    """
    if ids and len(ids) > 1:
        return ",".join(sorted(map(str, ids)))
    return None


def _scoped_qhash(norm: str, sources_fp: Optional[str]) -> str:
    """Exact-match lookup key, optionally folded with a multi-source fingerprint.

    When ``sources_fp`` is set (a Studio pinned to >1 data source), it is folded
    into the hash so two multi-source Studios with different pinned sets don't
    mis-share a proven query. ``sources_fp`` None (single-source / unpinned) ->
    plain ``question_hash(norm)``, byte-identical to upstream. The DB row filter
    still keys on the single ``data_source_id`` column (caller passes the primary
    id); uniqueness for multi-source sets comes from this hash.
    """
    if sources_fp:
        return question_hash(f"{sources_fp}\n{norm}")
    return question_hash(norm)


def is_read_only(sql: str) -> bool:
    """True only for a single SELECT / WITH...SELECT with no write tokens."""
    if not sql:
        return False
    body = sql.strip().rstrip(";").strip()
    if not _READ_ONLY_RE.match(body):
        return False
    if ";" in body:  # single statement only
        return False
    # WITH ... SELECT is fine; reject if any write keyword appears as a statement verb.
    # (Names like "created_at" won't match — \bCREATE\b requires a word boundary on both ends.)
    return _WRITE_TOKENS.search(body) is None


def _tokens(norm: str) -> set[str]:
    return {w for w in norm.split(" ") if w and w not in _STOP}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


async def capture_query(
    db: Any,
    *,
    organization_id: str,
    data_source_id: Optional[str],
    question: str,
    sql: str,
    source: str = "chat",
    data_source_ids: Optional[List[str]] = None,
) -> Optional[str]:
    """Capture a proven read-only query (Phase 5 write).

    No-op unless flags.QUERY_CACHE. Returns the row id on capture, else None.
    Upserts on (org, data_source, hash): bumps an existing row instead of dupe.
    New rows land status='pending' (await approval before they're ever served).

    ``data_source_ids`` (multi-source set, optional): the FULL pinned source set,
    folded into the lookup hash only when >1 source (see ``_sources_fp``) so
    multi-source Studios don't share proven queries across different pinned sets.
    Single-source / None -> hash unchanged. ``question_norm`` always stores the
    plain norm; the single ``data_source_id`` column stores the primary id.
    """
    from app.settings.hybrid_flags import flags

    if not flags.QUERY_CACHE:
        return None
    if db is None or not organization_id:
        return None
    if not is_read_only(sql):
        return None

    norm = normalize_question(question)
    if not norm:
        return None
    qhash = _scoped_qhash(norm, _sources_fp(data_source_ids))

    try:
        from sqlalchemy import select
        from app.models.query_cache import QueryCache

        stmt = (
            select(QueryCache)
            .where(QueryCache.organization_id == organization_id)
            .where(QueryCache.question_hash == qhash)
            .where(QueryCache.deleted_at.is_(None))
        )
        if data_source_id is None:
            stmt = stmt.where(QueryCache.data_source_id.is_(None))
        else:
            stmt = stmt.where(QueryCache.data_source_id == data_source_id)

        existing = (await db.execute(stmt)).scalars().first()
        if existing is not None:
            existing.hit_count = (existing.hit_count or 0) + 1
            existing.last_used_at = datetime.utcnow()
            # Keep the latest proven SQL for the same question.
            existing.sql_text = sql.strip().rstrip(";").strip()
            await db.commit()
            return str(existing.id)

        row = QueryCache(
            organization_id=organization_id,
            data_source_id=data_source_id,
            question_norm=norm,
            question_hash=qhash,
            sql_text=sql.strip().rstrip(";").strip(),
            status="pending",
            source=source,
            hit_count=1,
            last_used_at=datetime.utcnow(),
        )
        db.add(row)
        await db.commit()
        return str(row.id)
    except Exception as e:  # never break the loop on cache write
        logger.warning("query_cache capture failed: %s", e)
        try:
            await db.rollback()
        except Exception:
            pass
        return None


async def recall_proven_queries(
    db: Any,
    *,
    organization_id: str,
    data_source_id: Optional[str],
    question: str,
    limit: int = MAX_PROVEN,
    data_source_ids: Optional[List[str]] = None,
) -> List[Dict[str, str]]:
    """Recall active proven queries for a similar question (Phase 4 read).

    No-op unless flags.BRAIN_READ. Returns [{question, sql}] best-first:
    exact-hash matches first, then token-Jaccard >= FUZZY_FLOOR. Only
    status='active' rows (approval-gated) are ever surfaced.

    ``data_source_ids`` (multi-source set, optional): the FULL pinned source set,
    folded into the EXACT-match hash only when >1 source (see ``_sources_fp``) so
    a multi-source Studio exact-matches only queries proven for the SAME set.
    Single-source / None -> hash unchanged. (The fuzzy token-Jaccard fallback is
    set-agnostic, as before.)
    """
    from app.settings.hybrid_flags import flags

    if not flags.BRAIN_READ:
        return []
    if db is None or not organization_id:
        return []

    norm = normalize_question(question)
    if not norm:
        return []
    qhash = _scoped_qhash(norm, _sources_fp(data_source_ids))
    qtokens = _tokens(norm)

    try:
        from sqlalchemy import select
        from app.models.query_cache import QueryCache

        stmt = (
            select(QueryCache)
            .where(QueryCache.organization_id == organization_id)
            .where(QueryCache.status == "active")
            .where(QueryCache.deleted_at.is_(None))
        )
        # Scope: this data source OR org-wide (NULL).
        if data_source_id is not None:
            stmt = stmt.where(
                (QueryCache.data_source_id == data_source_id)
                | (QueryCache.data_source_id.is_(None))
            )
        rows = (await db.execute(stmt)).scalars().all()
    except Exception as e:
        logger.warning("query_cache recall failed: %s", e)
        return []

    scored: List[tuple[float, Any]] = []
    for r in rows:
        if r.question_hash == qhash:
            score = 1.0
        else:
            score = _jaccard(qtokens, _tokens(r.question_norm or ""))
            if score < FUZZY_FLOOR:
                continue
        scored.append((score, r))

    scored.sort(key=lambda t: (t[0], t[1].hit_count or 0), reverse=True)
    return [{"question": r.question_norm, "sql": r.sql_text} for _, r in scored[:limit]]


def render_proven_queries(items: List[Dict[str, str]]) -> str:
    """Render recalled queries as a planner context block. Empty -> ''."""
    if not items:
        return ""
    lines = [
        "## PROVEN QUERIES (reasoning-cache)",
        "Previously-validated SQL for similar questions. Re-run (do not assume the "
        "numbers are current) or adapt before writing new SQL from scratch:",
    ]
    for i, it in enumerate(items, 1):
        sql = (it.get("sql") or "").strip()
        q = (it.get("question") or "").strip()
        lines.append(f"\n{i}. Q: {q}\n```sql\n{sql}\n```")
    return "\n".join(lines)
