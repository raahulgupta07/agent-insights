"""
Reasoning-cache CURATOR (Phase 5 promote)
=========================================

Auto-promotes proven reasoning-cache rows from status='pending' to 'active' once
they have demonstrably earned trust, reusing the SAME approval philosophy as the
rest of the hybrid layer — NO new gate / UI. This is the dash query-curator
pattern ported native onto dash's QueryCache table.

Promotion rule (deterministic, no LLM):

    status == 'pending'  AND  hit_count >= MIN_HITS  AND  thumbs_down == 0
        ->  status = 'active'

Only status='active' rows are ever surfaced to the planner (see
query_cache_store.recall_proven_queries), so promotion is exactly the moment a
captured query goes live. A single 👎 (thumbs_down > 0) holds a row back, and a
configurable hit-count floor keeps one-off captures out.

Design rules honored:
- No-op (returns zeros) unless flags.QUERY_CACHE — default deploy is unchanged.
- Error-swallowing: never raises; the scheduler tick must never crash the loop.
- Dependency-light: async SQLAlchemy select/update, same style as the store.
- Threshold overridable via env QUERY_CURATOR_MIN_HITS (default 3).
- dry_run lists candidates without mutating — for inspection / tests.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Default hit-count floor. A captured query must have been seen this many times
# (and never thumbed-down) before it auto-promotes. Overridable per deploy.
_DEFAULT_MIN_HITS = 3


def _env_min_hits(default: int) -> int:
    try:
        return max(1, int(os.environ.get("QUERY_CURATOR_MIN_HITS", default)))
    except (TypeError, ValueError):
        return default


async def promote_proven_queries(
    db: Any,
    *,
    organization_id: Optional[str] = None,
    min_hits: int = _DEFAULT_MIN_HITS,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Promote pending reasoning-cache rows that have proven themselves.

    Selects rows where status='pending', hit_count >= effective floor, and
    thumbs_down == 0 (optionally scoped to a single organization), then flips
    them to status='active' — unless ``dry_run``, in which case nothing is
    mutated and the would-be candidates are merely listed.

    No-op returning {'promoted': 0, 'candidates': []} when flags.QUERY_CACHE is
    off or there is no db. Never raises: on any error it logs and degrades to a
    zero result so a scheduler tick can't crash the app.

    The effective hit floor is max(min_hits arg, default) overridden by env
    QUERY_CURATOR_MIN_HITS when set.
    """
    from app.settings.hybrid_flags import flags

    if not flags.QUERY_CACHE:
        return {"promoted": 0, "candidates": []}
    if db is None:
        return {"promoted": 0, "candidates": []}

    floor = _env_min_hits(min_hits)

    try:
        from sqlalchemy import select
        from app.models.query_cache import QueryCache

        stmt = (
            select(QueryCache)
            .where(QueryCache.status == "pending")
            .where(QueryCache.hit_count >= floor)
            .where(QueryCache.thumbs_down == 0)
            .where(QueryCache.deleted_at.is_(None))
        )
        if organization_id is not None:
            stmt = stmt.where(QueryCache.organization_id == organization_id)

        rows = (await db.execute(stmt)).scalars().all()
        candidates = [str(r.id) for r in rows]

        if dry_run or not rows:
            logger.info(
                "query_cache curator: %d candidate(s) (floor=%d, org=%s, dry_run=%s)",
                len(candidates), floor, organization_id, dry_run,
            )
            return {"promoted": 0 if dry_run else 0, "candidates": candidates}

        now = datetime.utcnow()
        for r in rows:
            r.status = "active"
            # source provenance: a curator-promoted row, not a hand-approved one.
            r.source = "curator"
            r.last_used_at = r.last_used_at or now
        await db.commit()

        logger.info(
            "query_cache curator: promoted %d row(s) pending->active (floor=%d, org=%s)",
            len(rows), floor, organization_id,
        )
        return {"promoted": len(rows), "candidates": candidates}
    except Exception as e:  # never break the scheduler tick on curation
        logger.warning("query_cache curator failed: %s", e)
        try:
            await db.rollback()
        except Exception:
            pass
        return {"promoted": 0, "candidates": []}


# Stable job id for the scheduler claim/dedup (mirrors SWEEP_JOB_ID).
CURATOR_JOB_ID = "query_cache_curator"


async def run_curator_sweep() -> None:
    """Scheduled entrypoint: leader-/claim-gated org-agnostic promotion sweep.

    Mirrors sweep_due_reindexes: claim the fire so exactly one worker/replica
    runs it, no-op without the flag, open a session, and promote org-agnostically
    (one pass over all pending rows). Safe on a short interval; the work is
    bounded by the number of pending rows meeting the rule.
    """
    from app.settings.hybrid_flags import flags

    if not flags.QUERY_CACHE:
        return

    import asyncio
    from app.core.scheduler import claim_scheduled_run

    # One worker/replica per fire.
    if not await asyncio.to_thread(claim_scheduled_run, CURATOR_JOB_ID):
        return

    try:
        from app.dependencies import async_session_maker
        async with async_session_maker() as db:
            await promote_proven_queries(db)
    except Exception as e:  # entrypoint must never raise into the scheduler
        logger.warning("query_cache curator sweep failed: %s", e)
