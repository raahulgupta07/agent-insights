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
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# Stable scheduler claim/dedup id (mirrors CURATOR_JOB_ID / INSIGHT_*_JOB_ID).
STUDIO_LEARN_JOB_ID = "hybrid_studio_learn"

# How many studios to process per tick (bounded so one tick can't run away).
_DEFAULT_MAX_STUDIOS_PER_TICK = 50


def daemon_enabled() -> bool:
    """True only when ``STUDIO_LEARN_DAEMON_ENABLED`` is a truthy env value.

    Default OFF — a fresh deploy never runs the learning daemon until this is
    explicitly enabled (CLAUDE.md HARD RULE 4).
    """
    raw = os.environ.get("STUDIO_LEARN_DAEMON_ENABLED")
    if raw is None:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "on"}


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

        async with maker() as db:
            res = await db.execute(
                select(Studio)
                .where(Studio.deleted_at.is_(None))
                .order_by(Studio.created_at.asc())
            )
            studios = list(res.scalars().all())[: _max_studios_per_tick()]
            for studio in studios:
                try:
                    counts = await improve_studio(db, studio)
                    total += int(
                        (counts or {}).get("examples", 0)
                        + (counts or {}).get("rules", 0)
                        + (counts or {}).get("suggested", 0)
                    )
                except Exception:
                    # One bad studio must not abort the sweep.
                    continue
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
    try:
        return max(1, int(os.environ.get("STUDIO_LEARN_INTERVAL_HOURS", 6)))
    except (TypeError, ValueError):
        return 6
