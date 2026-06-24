"""
Answer-cache store (Tier-1 final-answer reuse)
==============================================

Pure-Postgres Tier-1 answer-cache — no new infra. Caches a fully-rendered answer
(markdown + a small row-count summary) the agent produced, keyed by a
normalized-question hash + data-source scope, so an identical later question can
be served directly instead of re-running the whole plan/execute/reflect loop.

This sits in front of the reasoning-cache (query_cache_store), which only stores
SQL to re-run live. Here we store the rendered output itself, optionally with a
TTL (expires_at) so stale answers age out — NULL expires_at = never expires.

Design rules honored:
- Reuse is gated by flags.ANSWER_CACHE; off -> total no-op.
- No new approval gate: this caches the agent's own validated output (unlike
  query_cache, whose proven SQL goes through the bow approval gate).
- normalize_question + question_hash are REUSED from query_cache_store so the two
  caches key questions identically. Dependency-free otherwise.
- Side-effect-light: every public coroutine swallows its own errors and degrades
  to a no-op (returns None) so the agent loop never breaks on cache.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional, Tuple

# Reuse the exact same normalization + hashing the reasoning-cache uses so both
# caches key questions identically (no duplicate implementation).
from app.ai.brain.query_cache_store import normalize_question, question_hash

logger = logging.getLogger(__name__)


async def serve_answer_cache(
    db: Any,
    *,
    organization_id: str,
    data_source_id: Optional[str],
    question: str,
) -> Optional[Tuple[str, int]]:
    """Serve a cached answer for an exact-hash question match (Tier-1 read).

    No-op unless flags.ANSWER_CACHE. Returns ``(answer_md, row_count)`` on a
    fresh (non-expired) hit, else None. On hit, bumps hit_count + last_used_at
    and commits. Scope: this data source OR org-wide (NULL). Any error -> None.
    """
    from app.settings.hybrid_flags import flags

    if not flags.ANSWER_CACHE:
        return None
    if db is None or not organization_id or not question:
        return None

    norm = normalize_question(question)
    if not norm:
        return None
    qhash = question_hash(norm)

    try:
        from sqlalchemy import select
        from app.models.answer_cache import AnswerCache

        now = datetime.utcnow()
        stmt = (
            select(AnswerCache)
            .where(AnswerCache.organization_id == organization_id)
            .where(AnswerCache.question_hash == qhash)
            .where(AnswerCache.deleted_at.is_(None))
            .where(
                AnswerCache.expires_at.is_(None) | (AnswerCache.expires_at > now)
            )
        )
        if data_source_id is None:
            stmt = stmt.where(AnswerCache.data_source_id.is_(None))
        else:
            stmt = stmt.where(AnswerCache.data_source_id == data_source_id)

        row = (await db.execute(stmt)).scalars().first()
        if row is None:
            return None

        row.hit_count = (row.hit_count or 0) + 1
        row.last_used_at = now
        await db.commit()
        return (row.answer_md, int(row.row_count or 0))
    except Exception as e:  # never break the loop on cache read
        logger.warning("answer_cache serve failed: %s", e)
        try:
            await db.rollback()
        except Exception:
            pass
        return None


async def store_answer(
    db: Any,
    *,
    organization_id: str,
    data_source_id: Optional[str],
    question: str,
    answer_md: str,
    row_count: int = 0,
    sql_text: Optional[str] = None,
    ttl_seconds: Optional[int] = None,
) -> Optional[str]:
    """Store (or refresh) a rendered answer for a question (Tier-1 write).

    No-op unless flags.ANSWER_CACHE. Returns the row id on store, else None.
    Upserts on (org, data_source, hash): refreshes an existing row instead of
    duplicating. ``expires_at`` = utcnow()+ttl_seconds when ttl_seconds is given,
    else NULL (no expiry). Rolls back and returns None on any error.
    """
    from app.settings.hybrid_flags import flags

    if not flags.ANSWER_CACHE:
        return None
    if db is None or not organization_id or not question:
        return None
    if not answer_md:
        return None

    norm = normalize_question(question)
    if not norm:
        return None
    qhash = question_hash(norm)

    expires_at = None
    if ttl_seconds is not None:
        try:
            expires_at = datetime.utcnow() + timedelta(seconds=int(ttl_seconds))
        except Exception:
            expires_at = None

    try:
        from sqlalchemy import select
        from app.models.answer_cache import AnswerCache

        stmt = (
            select(AnswerCache)
            .where(AnswerCache.organization_id == organization_id)
            .where(AnswerCache.question_hash == qhash)
            .where(AnswerCache.deleted_at.is_(None))
        )
        if data_source_id is None:
            stmt = stmt.where(AnswerCache.data_source_id.is_(None))
        else:
            stmt = stmt.where(AnswerCache.data_source_id == data_source_id)

        existing = (await db.execute(stmt)).scalars().first()
        if existing is not None:
            existing.answer_md = answer_md
            existing.row_count = int(row_count or 0)
            existing.sql_text = sql_text
            existing.expires_at = expires_at
            existing.hit_count = (existing.hit_count or 0) + 1
            existing.last_used_at = datetime.utcnow()
            await db.commit()
            return str(existing.id)

        row = AnswerCache(
            organization_id=organization_id,
            data_source_id=data_source_id,
            question_norm=norm,
            question_hash=qhash,
            answer_md=answer_md,
            row_count=int(row_count or 0),
            sql_text=sql_text,
            hit_count=1,
            last_used_at=datetime.utcnow(),
            expires_at=expires_at,
        )
        db.add(row)
        await db.commit()
        return str(row.id)
    except Exception as e:  # never break the loop on cache write
        logger.warning("answer_cache store failed: %s", e)
        try:
            await db.rollback()
        except Exception:
            pass
        return None
