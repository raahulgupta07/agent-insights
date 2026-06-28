"""Studio self-improvement daemon (hybrid Studios ST8).

Leader-gated periodic task that runs ``studio_learning.improve_studio`` over
every studio so each studio keeps learning from its own traffic without anyone
clicking "improve". Mirrors the proactive-insight daemon
(``app.services.brain_service.run_insight_daemon_tick``) exactly:

  1. Enable gate FIRST — ``STUDIO_LEARN_DAEMON_ENABLED`` (default 0). OFF -> 0,
     without acquiring any lock. This is independent of ``flags.STUDIOS`` (which
     ``improve_studio`` itself also checks) so the daemon stays dark on a fresh
     deploy.
  2. Per-pod leader lock (``try_acquire_scheduler_leader``) + cross-pod claim
     (``claim_scheduled_run``) — exactly one worker/replica runs a given fire.
  3. Open a session, iterate studios (bounded), call ``improve_studio`` per
     studio. Returns the total number of items proposed/published.

Import-safe: importing this module starts NOTHING. The daemon only runs when it
is both scheduled (see ``register_studio_learn_daemon``) AND its env flag is on.
Every step is guarded; the tick NEVER raises into the scheduler.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# Stable scheduler claim/dedup id (mirrors CURATOR_JOB_ID / INSIGHT_*_JOB_ID).
STUDIO_LEARN_JOB_ID = "hybrid_studio_learn"

# How many studios to process per tick (bounded so one tick can't run away).
_DEFAULT_MAX_STUDIOS_PER_TICK = 50

# Per-studio cadence → minimum spacing (for 6h) / period semantics.
_CADENCES = {"6h", "daily", "weekly", "monthly", "off"}


def daemon_enabled() -> bool:
    """True when the org master switch ``STUDIO_LEARN_DAEMON_ENABLED`` is on.

    Reads the override layer (DB toggle / env) via ``flags`` so the Feature-Flags
    UI toggle works without a compose env var. Default OFF — a fresh deploy never
    runs the learning daemon until explicitly enabled (CLAUDE.md HARD RULE 4).
    Falls back to a raw-env read if the flags module is somehow unavailable.
    """
    try:
        from app.settings.hybrid_flags import flags
        return bool(flags.STUDIO_LEARN_DAEMON)
    except Exception:
        raw = os.environ.get("STUDIO_LEARN_DAEMON_ENABLED")
        return bool(raw) and raw.strip().lower() in {"1", "true", "yes", "on"}


# --------------------------------------------------------------------------
# Per-studio cadence helpers (read studio.config['self_learn']).
# --------------------------------------------------------------------------
def get_self_learn_cfg(studio: Any) -> dict:
    """Return the studio's self-learn config dict (defaults when unset)."""
    cfg = {}
    try:
        cfg = dict((getattr(studio, "config", None) or {}).get("self_learn", {}) or {})
    except Exception:
        cfg = {}
    cadence = cfg.get("cadence", "daily")
    if cadence not in _CADENCES:
        cadence = "daily"
    enabled = bool(cfg.get("enabled", False)) and cadence != "off"
    try:
        hour = int(cfg.get("hour_utc", 0))
    except (TypeError, ValueError):
        hour = 0
    hour = min(23, max(0, hour))
    return {
        "enabled": enabled,
        "cadence": cadence,
        "hour_utc": hour,
        "last_run_at": cfg.get("last_run_at"),
    }


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def is_due(cfg: dict, now: Optional[datetime] = None) -> bool:
    """True when a studio's self-learn cadence is due to run at ``now`` (UTC)."""
    if not cfg.get("enabled"):
        return False
    now = now or datetime.now(timezone.utc)
    last = _parse_iso(cfg.get("last_run_at"))
    cadence = cfg.get("cadence", "daily")
    hour = int(cfg.get("hour_utc", 0))

    if cadence == "6h":
        return last is None or (now - last) >= timedelta(hours=6)

    # daily / weekly / monthly all gate on the chosen UTC hour.
    if now.hour < hour:
        return False
    if last is None:
        return True
    if cadence == "daily":
        return last.date() < now.date()
    if cadence == "weekly":
        return (now - last) >= timedelta(days=7)
    if cadence == "monthly":
        return (now.year, now.month) != (last.year, last.month)
    return False


def next_run_estimate(cfg: dict, now: Optional[datetime] = None) -> Optional[str]:
    """Rough next-run ISO string for UI display (best-effort, not exact)."""
    if not cfg.get("enabled"):
        return None
    now = now or datetime.now(timezone.utc)
    if is_due(cfg, now):
        return now.replace(microsecond=0).isoformat()
    last = _parse_iso(cfg.get("last_run_at"))
    cadence = cfg.get("cadence", "daily")
    hour = int(cfg.get("hour_utc", 0))
    base = last or now
    if cadence == "6h":
        nxt = base + timedelta(hours=6)
    elif cadence == "daily":
        nxt = (now + timedelta(days=1)).replace(hour=hour, minute=0, second=0, microsecond=0)
    elif cadence == "weekly":
        nxt = (base + timedelta(days=7)).replace(hour=hour, minute=0, second=0, microsecond=0)
    elif cadence == "monthly":
        nxt = (base + timedelta(days=30)).replace(hour=hour, minute=0, second=0, microsecond=0)
    else:
        return None
    return nxt.replace(microsecond=0).isoformat()


def _max_studios_per_tick() -> int:
    try:
        return max(1, int(os.environ.get("STUDIO_LEARN_MAX_STUDIOS", _DEFAULT_MAX_STUDIOS_PER_TICK)))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_STUDIOS_PER_TICK


async def run_studio_learn_tick(session_maker: Optional[Callable[[], Any]] = None) -> int:
    """Leader-gated periodic entry point. Returns total items proposed/published.

    Steps (all guarded; returns 0 on any failure):
      1. Daemon enable gate (off -> 0, no lock acquired).
      2. Win the per-pod scheduler leader lock, else 0.
      3. Win the cross-pod scheduled-run claim, else 0.
      4. Open a session and run ``improve_studio`` per non-deleted studio.

    ``session_maker`` is injectable for tests; defaults to the app session
    factory. NEVER raises.
    """
    # 1. Daemon enable gate — independent of flags.STUDIOS, default OFF.
    if not daemon_enabled():
        return 0

    # 2 + 3. Leader + cross-pod claim. Both must succeed for THIS process.
    try:
        import asyncio

        from app.core.scheduler import claim_scheduled_run, try_acquire_scheduler_leader

        if not try_acquire_scheduler_leader():
            return 0
        if not await asyncio.to_thread(claim_scheduled_run, STUDIO_LEARN_JOB_ID):
            return 0
    except Exception as e:
        logger.warning("studio_learn tick leader/claim failed: %s", e)
        return 0

    total = 0
    try:
        maker = session_maker
        if maker is None:
            from app.dependencies import async_session_maker

            maker = async_session_maker

        from sqlalchemy import select

        from app.models.studio import Studio
        from app.services.studio_learning import improve_studio
        from app.settings.hybrid_flags import flags

        # Second gate: if the Studios feature itself is off, there is nothing to
        # learn from (improve_studio would no-op anyway — short-circuit cleanly).
        if not flags.STUDIOS:
            return 0

        from sqlalchemy.orm.attributes import flag_modified

        now = datetime.now(timezone.utc)
        async with maker() as db:
            res = await db.execute(
                select(Studio)
                .where(Studio.deleted_at.is_(None))
                .order_by(Studio.created_at.asc())
            )
            all_studios = list(res.scalars().all())
            # Only studios whose OWN cadence is due this tick (per-agent control).
            due = [s for s in all_studios if is_due(get_self_learn_cfg(s), now)]
            studios = due[: _max_studios_per_tick()]
            ran = 0
            for studio in studios:
                try:
                    counts = await improve_studio(db, studio)
                    total += int(
                        (counts or {}).get("examples", 0)
                        + (counts or {}).get("rules", 0)
                        + (counts or {}).get("suggested", 0)
                    )
                    # Stamp last_run_at on the studio config so cadence advances
                    # even when a tick proposes nothing (don't re-run all day).
                    new_cfg = dict(getattr(studio, "config", None) or {})
                    sl = dict(new_cfg.get("self_learn", {}) or {})
                    sl["last_run_at"] = now.replace(microsecond=0).isoformat()
                    new_cfg["self_learn"] = sl
                    studio.config = new_cfg
                    flag_modified(studio, "config")
                    ran += 1
                except Exception:
                    # One bad studio must not abort the sweep.
                    continue
            if ran:
                try:
                    await db.commit()
                except Exception as e:
                    logger.warning("studio_learn commit failed: %s", e)
            logger.info(
                "studio_learn tick: %d due, %d ran, %d item(s)", len(due), ran, total
            )
    except Exception as e:
        logger.warning("studio_learn run_studio_learn_tick failed: %s", e)
        return total

    if total:
        logger.info("studio_learn tick: proposed/published %d item(s)", total)
    return total


def register_studio_learn_daemon(scheduler: Any, is_scheduler_leader: bool) -> bool:
    """Register the studio-learning tick on ``scheduler`` (call from main.py).

    Provided so main.py can wire this in ONE line without this module having to
    edit main.py. Schedules nothing unless this process is the scheduler leader
    AND ``STUDIO_LEARN_DAEMON_ENABLED`` is on — so a default deploy is unchanged.
    The tick ALSO self-leader-gates, so an accidental double-schedule is harmless.

    Returns True if the job was scheduled, else False. Never raises.
    """
    if not is_scheduler_leader or not daemon_enabled():
        return False
    try:
        interval_hours = _registration_interval_hours()
        scheduler.add_job(
            run_studio_learn_tick,
            trigger="interval",
            hours=interval_hours,
            id=STUDIO_LEARN_JOB_ID,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=600,
        )
        logger.info("Scheduled job: %s every %d hour(s)", STUDIO_LEARN_JOB_ID, interval_hours)
        return True
    except Exception as e:
        logger.error("Failed to schedule studio_learn daemon job: %s", e)
        return False


def _registration_interval_hours() -> int:
    # Tick HOURLY so per-studio cadences (6h/daily/weekly/monthly) resolve at
    # 1-hour granularity. Each studio's own cadence + last_run_at decides whether
    # it actually runs on a given tick — the tick itself is just the clock.
    try:
        return max(1, int(os.environ.get("STUDIO_LEARN_INTERVAL_HOURS", 1)))
    except (TypeError, ValueError):
        return 1
