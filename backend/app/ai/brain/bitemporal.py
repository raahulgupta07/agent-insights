"""Bi-temporal facts (Zep/Graphiti pattern, native).

Evolving facts carry a timeline instead of being overwritten:
  valid_at      when it became true   (NULL = "since the beginning")
  invalid_at    when it stopped       (NULL = still current)
  superseded_by id of the row that replaced it

Default-OFF: when HYBRID_BITEMPORAL is off, `current_condition` returns None and
callers skip the filter -> behaves exactly like before (all rows current).

Pure helpers, never raise into the caller.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)


def _enabled() -> bool:
    try:
        from app.settings.hybrid_flags import flags
        return bool(flags.BITEMPORAL)
    except Exception:
        return False


def current_condition(model):
    """SQLAlchemy condition selecting only currently-valid rows, or None when the
    flag is off (caller then adds no filter -> backward compatible)."""
    if not _enabled():
        return None
    try:
        return model.invalid_at.is_(None)
    except Exception:
        return None


def asof_conditions(model, as_of) -> list:
    """Conditions for a point-in-time (time-travel) read: valid at `as_of`.
    Empty list when flag off or no as_of."""
    if not _enabled() or as_of is None:
        return []
    try:
        return [
            ((model.valid_at.is_(None)) | (model.valid_at <= as_of)),
            ((model.invalid_at.is_(None)) | (model.invalid_at > as_of)),
        ]
    except Exception:
        return []


async def supersede_prior(db, model, *, key_filters: List, keep_id: str) -> int:
    """Invalidate prior currently-valid rows matching key_filters (same logical
    fact) except `keep_id`: set invalid_at=now, superseded_by=keep_id.

    No-op (returns 0) when the flag is off. Never raises.
    """
    if not _enabled():
        return 0
    try:
        from sqlalchemy import update

        # The bi-temporal columns are TIMESTAMP WITHOUT TIME ZONE (matching the
        # BaseSchema created_at/updated_at convention `datetime.utcnow`). Use a
        # NAIVE UTC timestamp so asyncpg can bind it — an aware datetime is
        # rejected against a naive column ("can't subtract offset-naive and
        # offset-aware datetimes"), which would silently no-op the supersede.
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        stmt = (
            update(model)
            .where(
                *key_filters,
                model.id != keep_id,
                model.invalid_at.is_(None),
            )
            .values(invalid_at=now, superseded_by=keep_id)
        )
        res = await db.execute(stmt)
        await db.commit()
        return int(res.rowcount or 0)
    except Exception:
        logger.exception("bitemporal.supersede_prior failed")
        try:
            await db.rollback()
        except Exception:
            pass
        return 0
