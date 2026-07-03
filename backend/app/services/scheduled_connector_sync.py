"""Scheduled connector auto-sync.

Per-agent config is stored in
``organization_settings.config['connector_auto_sync'][ds_id]``::

    {"enabled": bool, "interval_hours": int, "last_sync_at": iso-str | None}

``sweep_due_syncs`` is registered as an interval job (see ``core.scheduler``) and
re-runs ``per_user_connector.sync_clone_bg`` for every enabled clone whose interval
has elapsed. Re-training is diff-gated inside ``sync_clone_bg``, so a sweep that
finds no schema change costs zero LLM calls. Self-contained + fully fail-soft —
never raises, so a bad entry can't wedge the scheduler.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

_KEY = "connector_auto_sync"
_MIN_INTERVAL_H = 1
_MAX_INTERVAL_H = 24 * 7


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def get_config(db, org_id: str, ds_id: str) -> dict:
    """Read the per-agent auto-sync config (defaults when unset)."""
    from sqlalchemy import select
    from app.models.organization_settings import OrganizationSettings
    row = (await db.execute(
        select(OrganizationSettings).where(OrganizationSettings.organization_id == str(org_id))
    )).scalars().first()
    bucket = ((row.config or {}) if row else {}).get(_KEY) or {}
    return bucket.get(str(ds_id)) or {"enabled": False, "interval_hours": 24, "last_sync_at": None}


async def set_config(db, org_id: str, ds_id: str, enabled: bool, interval_hours: int) -> dict:
    """Upsert the per-agent auto-sync config. Clamps interval to [1h, 7d]."""
    from sqlalchemy import select
    from sqlalchemy.orm.attributes import flag_modified
    from app.models.organization_settings import OrganizationSettings
    interval_hours = max(_MIN_INTERVAL_H, min(_MAX_INTERVAL_H, int(interval_hours or 24)))
    row = (await db.execute(
        select(OrganizationSettings).where(OrganizationSettings.organization_id == str(org_id))
    )).scalars().first()
    if row is None:
        row = OrganizationSettings(organization_id=str(org_id), config={})
        db.add(row)
    cfg = dict(row.config or {})
    bucket = dict(cfg.get(_KEY) or {})
    entry = dict(bucket.get(str(ds_id)) or {})
    entry.update({"enabled": bool(enabled), "interval_hours": interval_hours})
    entry.setdefault("last_sync_at", None)
    bucket[str(ds_id)] = entry
    cfg[_KEY] = bucket
    row.config = cfg
    flag_modified(row, "config")
    await db.commit()
    return entry


def _due(entry: dict, now: datetime) -> bool:
    if not entry or not entry.get("enabled"):
        return False
    interval = max(_MIN_INTERVAL_H, int(entry.get("interval_hours") or 24))
    last = entry.get("last_sync_at")
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(str(last))
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return True
    return (now - last_dt) >= timedelta(hours=interval)


async def sweep_due_syncs() -> None:
    """Interval job: launch a diff-gated sync for every due, enabled clone."""
    import asyncio
    try:
        from app.settings.hybrid_flags import flags, load_overrides_from_db
    except Exception:  # noqa: BLE001
        return
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from sqlalchemy.orm.attributes import flag_modified
    from app.dependencies import async_session_maker
    from app.models.organization_settings import OrganizationSettings
    from app.models.data_source import DataSource
    from app.services import per_user_connector

    try:
        async with async_session_maker() as db:
            try:
                await load_overrides_from_db(db)
            except Exception:  # noqa: BLE001
                pass
            if not flags.CONNECTOR_AUTO_SYNC:
                return
            now = _now()
            rows = (await db.execute(select(OrganizationSettings))).scalars().all()
            launched = 0
            for row in rows:
                bucket = (row.config or {}).get(_KEY) or {}
                if not bucket:
                    continue
                org_id = str(row.organization_id)
                for ds_id, entry in list(bucket.items()):
                    if not _due(entry, now):
                        continue
                    ds = (await db.execute(
                        select(DataSource)
                        .options(selectinload(DataSource.connections))
                        .where(DataSource.id == str(ds_id))
                    )).scalars().first()
                    if ds is None or not ds.connections:
                        continue
                    owner = getattr(ds.connections[0], "owner_user_id", None)
                    if not owner:
                        continue
                    # Stamp last_sync_at NOW (optimistic) BEFORE launching so a
                    # long-running sync is never double-launched by the next sweep.
                    entry["last_sync_at"] = now.isoformat()
                    flag_modified(row, "config")
                    await db.commit()
                    asyncio.create_task(
                        per_user_connector.sync_clone_bg(
                            str(ds_id), org_id, str(owner), True, "scheduled"
                        )
                    )
                    launched += 1
            if launched:
                logger.info("connector auto-sync: launched %d scheduled sync(s)", launched)
    except Exception as e:  # noqa: BLE001
        logger.warning("connector auto-sync sweep failed: %s", e)
