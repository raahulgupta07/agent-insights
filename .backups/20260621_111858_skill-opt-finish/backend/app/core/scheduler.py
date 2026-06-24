import os
import fcntl
import socket
import time
import logging
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from app.settings.database import create_database_engine

logger = logging.getLogger(__name__)

# Use synchronous engine directly
_engine = create_database_engine()
jobstore = SQLAlchemyJobStore(
    engine=_engine,
    tablename='apscheduler_jobs'
)

scheduler = AsyncIOScheduler(
    jobstores={
        'default': jobstore
    }
)


_CRON_DOW_NUM_TO_NAME = {
    '0': 'sun', '1': 'mon', '2': 'tue', '3': 'wed',
    '4': 'thu', '5': 'fri', '6': 'sat', '7': 'sun',
}


def cron_dow_to_apscheduler(dow: str) -> str:
    """Translate a standard-cron day-of-week field into APScheduler's naming.

    Standard cron numbers weekdays 0=Sun..6=Sat (7=Sun too). APScheduler's
    numeric ``day_of_week`` instead uses 0=Mon..6=Sun, so feeding a standard
    cron number straight in shifts every weekday by one (e.g. Sunday '0' would
    fire Monday). We map numbers to APScheduler's unambiguous weekday NAMES
    (sun..sat) so the schedule means the same day in both conventions.

    Handles '*', comma lists ('0,6'), ranges ('1-5'); leaves names and step
    expressions ('*/2') untouched. The stored cron string is unchanged — this
    only adjusts the value handed to APScheduler at registration time.
    """
    if not dow or dow == '*' or '/' in dow:
        return dow

    def _map(token: str) -> str:
        t = token.strip().lower()
        return _CRON_DOW_NUM_TO_NAME.get(t, t)

    def _part(token: str) -> str:
        if '-' in token:
            a, _, b = token.partition('-')
            return f"{_map(a)}-{_map(b)}"
        return _map(token)

    return ','.join(_part(t) for t in dow.split(','))


def register_eval_jobs(scheduler) -> bool:
    """Phase 4: register the nightly eval-harness job (flag + leader gated).

    Mirrors the other daemon registration helpers (e.g.
    ``register_studio_learn_daemon``): the caller (main.py lifespan) only
    invokes this when it holds the scheduler leader lock, so we just add the
    flag gate here. ``run_scheduled_evals`` is self-contained (opens its own
    session, re-checks ``flags.EVAL_SCHEDULE_ENABLED``).

    Returns True if the job was registered. Never raises — a failure here must
    not break scheduler startup. Import is local to avoid an import cycle.
    """
    try:
        from app.settings.hybrid_flags import flags
        if not flags.EVAL_SCHEDULE_ENABLED:
            logger.info("Phase 4 nightly evals: EVAL_SCHEDULE_ENABLED off — not registered")
            return False
        from app.services.eval_harness import run_scheduled_evals
        scheduler.add_job(
            run_scheduled_evals,
            trigger="cron",
            id="phase4_nightly_evals",
            hour=3,
            minute=0,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        logger.info("Scheduled job: phase4_nightly_evals @ 03:00 daily")
        return True
    except Exception as e:  # never let registration crash scheduler startup
        logger.error(f"Failed to schedule phase4_nightly_evals job: {e}")
        return False


def register_join_mine_jobs(scheduler) -> bool:
    """Phase 6: register the nightly join-mining job (flag + leader gated).

    Mirrors ``register_eval_jobs``: the caller (main.py lifespan) only invokes
    this when it holds the scheduler leader lock, so we just add the flag gate
    here. ``run_join_mining`` is self-contained (opens its own session,
    re-checks ``flags.JOIN_MINE_ENABLED``) and never raises.

    Returns True if the job was registered. Never raises — a failure here must
    not break scheduler startup. Import is local to avoid an import cycle.
    """
    try:
        from app.settings.hybrid_flags import flags
        if not flags.JOIN_MINE_ENABLED:
            logger.info("Phase 6 join mining: JOIN_MINE_ENABLED off — not registered")
            return False
        from app.ai.knowledge.join_miner import run_join_mining
        scheduler.add_job(
            run_join_mining,
            trigger="cron",
            id="phase6_join_mining",
            hour=3,
            minute=30,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        logger.info("Scheduled job: phase6_join_mining @ 03:30 daily")
        return True
    except Exception as e:  # never let registration crash scheduler startup
        logger.error(f"Failed to schedule phase6_join_mining job: {e}")
        return False


def register_skill_optimize_jobs(scheduler) -> bool:
    """Phase 7: register the nightly skill-optimize job (flag + leader gated).

    Mirrors ``register_join_mine_jobs``: the caller (main.py lifespan) only
    invokes this when it holds the scheduler leader lock, so we just add the
    flag gate here. ``run_scheduled_skill_optimize`` is self-contained (opens
    its own session, re-checks ``flags.SKILL_OPTIMIZE`` AND
    ``flags.SKILL_OPTIMIZE_DAEMON``) and never raises.

    Returns True if the job was registered. Never raises — a failure here must
    not break scheduler startup. Import is local to avoid an import cycle.
    """
    try:
        from app.settings.hybrid_flags import flags
        if not flags.SKILL_OPTIMIZE_DAEMON:
            logger.info("Phase 7 skill optimize: SKILL_OPTIMIZE_DAEMON off — not registered")
            return False
        from app.ai.skills.optimizer import run_scheduled_skill_optimize
        scheduler.add_job(
            run_scheduled_skill_optimize,
            trigger="cron",
            id="phase7_skill_optimize",
            hour=4,
            minute=0,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        logger.info("Scheduled job: phase7_skill_optimize @ 04:00 daily")
        return True
    except Exception as e:  # never let registration crash scheduler startup
        logger.error(f"Failed to schedule phase7_skill_optimize job: {e}")
        return False


_LEADER_LOCK_FD = None


def try_acquire_scheduler_leader() -> bool:
    """Return True if this process wins the scheduler leader lock.

    Multi-worker uvicorn deployments otherwise run every scheduled job N
    times (once per worker), which is what turns warmup jobs into resource
    storms at customer sites. The lock is held for the lifetime of the
    process — a crashed leader releases the flock and the next worker to
    start wins on its next startup.

    Override via DASH_SCHEDULER_LEADER=1 to force-enable (useful when running
    a dedicated scheduler sidecar) or DASH_SCHEDULER_DISABLED=1 to opt out.
    """
    if os.environ.get("DASH_SCHEDULER_DISABLED") == "1":
        return False
    if os.environ.get("DASH_SCHEDULER_LEADER") == "1":
        return True

    global _LEADER_LOCK_FD
    lock_path = os.environ.get("DASH_SCHEDULER_LOCK_PATH", "/tmp/dash-scheduler.lock")
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _LEADER_LOCK_FD = fd  # keep fd alive for process lifetime
        return True
    except (OSError, BlockingIOError):
        return False


# Dedup window for scheduled-run claims, in seconds. A single scheduled fire
# may be executed by every uvicorn worker (and every replica) because all of
# them run an AsyncIOScheduler against the SAME shared job store — APScheduler
# 3.x does not coordinate execution across schedulers. We make execution
# idempotent by having each fire atomically *claim* its run row; only the
# winner proceeds, the rest skip. The claim key buckets the wall-clock fire
# time to this window so the near-simultaneous fires across workers (which are
# milliseconds apart) collapse to one key, while genuinely distinct fires never
# do. Every Dash schedule is cron-based (≥60s between fires) and the global
# maintenance jobs run hourly/daily, so a 30s window has a comfortable >=2x
# margin over the minimum real interval while dwarfing cross-worker jitter.
SCHEDULED_RUN_CLAIM_WINDOW_SECONDS = 30


def claim_scheduled_run(job_id: str, window_seconds: int = SCHEDULED_RUN_CLAIM_WINDOW_SECONDS) -> bool:
    """Atomically claim a scheduled fire so exactly one worker executes it.

    Returns True if THIS process won the claim (and must run the job body),
    False if another worker already claimed this fire (and we must skip).

    Coordination lives in the shared application database, so this is correct
    across uvicorn workers AND across replicas/containers/pods — unlike the
    per-host file lock above. The unique constraint on
    (job_id, run_bucket) is the arbiter: the first INSERT wins, concurrent
    INSERTs for the same bucket raise IntegrityError and lose.

    Fail-open: if the claim table is missing or the DB errors, we return True
    so the job still runs (better an occasional duplicate than a silently
    dropped scheduled run). This keeps the change safe to deploy ahead of the
    migration and resilient to transient DB hiccups.

    Synchronous on purpose (one tiny INSERT); async callers should off-load it
    with ``await asyncio.to_thread(claim_scheduled_run, job_id)`` so the event
    loop is never blocked.
    """
    bucket = int(time.time() // window_seconds * window_seconds)
    claimant = f"{socket.gethostname()}:{os.getpid()}"
    try:
        with _engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO scheduled_job_runs (job_id, run_bucket, claimed_by, claimed_at) "
                    "VALUES (:jid, :bucket, :by, :at)"
                ),
                {"jid": job_id, "bucket": bucket, "by": claimant, "at": datetime.utcnow()},
            )
    except IntegrityError:
        logger.info("Scheduled run %s @bucket %s already claimed — skipping in %s", job_id, bucket, claimant)
        return False
    except Exception as e:  # table missing / transient DB error -> fail open
        logger.warning("claim_scheduled_run(%s) failed open (%s): %s", job_id, type(e).__name__, e)
        return True

    # Won the claim. Opportunistically prune this job's old claim rows so the
    # table stays bounded (one row per fire would otherwise grow forever).
    try:
        cutoff = bucket - 7 * 24 * 3600
        with _engine.begin() as conn:
            conn.execute(
                text("DELETE FROM scheduled_job_runs WHERE job_id = :jid AND run_bucket < :cutoff"),
                {"jid": job_id, "cutoff": cutoff},
            )
    except Exception:
        pass
    return True
