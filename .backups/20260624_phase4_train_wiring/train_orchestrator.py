"""Async studio Auto-train orchestrator.

Today the Studio "Auto-train" flow runs profiling + auto-queries + auto-evals +
artifact generation SEQUENTIALLY from the front-end, blocking the request for
~30-90s. This module moves that work into a fire-and-forget background task and
exposes an in-process status dict the FE can poll.

Design (mirrors the hybrid brain-worker discipline used elsewhere in the repo):
  * In-process status store ``_RUNS`` keyed by ``studio_id`` (like
    ``routes/workflows.py`` ``_LAST_RUNS``). No persistence table — runs are
    ephemeral; an empty/idle status is fine.
  * The background coroutine opens its OWN fresh async session
    (``async_session_maker``) — the request session is already closed by the
    time it runs. Org + User are reloaded by PK inside that session (they may be
    detached / belong to the request session).
  * Every stage is wrapped in try/except: a stage failure is recorded in
    ``detail`` and the next stage still runs. The task NEVER raises.
  * The created ``asyncio.Task`` is kept in a module-level list ``_TASKS`` so the
    event loop doesn't garbage-collect it mid-flight (the classic
    ``asyncio.create_task`` weak-reference landmine).

Status shape (``get_status``):
  ``{"status": "running"|"done"|"error"|"idle",
     "step": <str>, "pct": <int>, "detail": {<stage>: <ok|error msg>},
     "error": <str only when status=='error'>}``

Reuses existing services — does NOT re-implement any of them:
  profiling  -> ``routes.column_profile._profile_all_tables`` (canonical loop)
  queries    -> ``ai.knowledge.auto_queries.generate_queries_for_studio``
  evals      -> ``ai.knowledge.auto_evals.generate_evals_for_studio``
  artifacts  -> ``services.studio_artifacts.generate_artifact`` (persisted as
                ``StudioArtifact`` rows, mirroring the generate route).
"""

import asyncio
import logging
from datetime import datetime

from sqlalchemy import select

logger = logging.getLogger(__name__)

# In-process status store, keyed by studio_id. Survives only the process
# lifetime; per-uvicorn-worker (like the other hybrid in-process stores).
_RUNS: dict = {}

# Strong references to scheduled tasks so the loop doesn't GC them mid-flight.
_TASKS: list = []

# Artifact kinds generated during a train run (every GENERATED_KINDS member).
_ARTIFACT_KINDS = ("summary", "faq", "briefing", "notes", "kpi_pack", "data_dictionary")


def get_status(studio_id) -> dict:
    """Return the current/last status for a studio's train run, or idle."""
    return _RUNS.get(str(studio_id), {"status": "idle"})


def _set(studio_id, **kw) -> None:
    """Merge keys into the studio's status entry (in place)."""
    cur = _RUNS.get(str(studio_id))
    if not isinstance(cur, dict):
        cur = {}
        _RUNS[str(studio_id)] = cur
    cur.update(kw)


async def _persist_db(db, studio, sid) -> None:
    """Mirror the in-process status onto Studio.config['_train_status'] so it is
    visible across uvicorn workers (the in-process _RUNS is per-process). Cheap,
    called at stage boundaries. Fail-soft."""
    try:
        from sqlalchemy.orm.attributes import flag_modified

        cfg = studio.config if isinstance(studio.config, dict) else {}
        cfg = dict(cfg)
        cfg["_train_status"] = _RUNS.get(str(sid), {})
        studio.config = cfg
        flag_modified(studio, "config")
        await db.commit()
    except Exception:  # noqa: BLE001
        try:
            await db.rollback()
        except Exception:
            pass


async def _load_studio(db, studio_id):
    from app.models.studio import Studio

    res = await db.execute(
        select(Studio).where(
            Studio.id == studio_id,
            Studio.deleted_at.is_(None),
        )
    )
    return res.scalar_one_or_none()


async def _resolve_pinned_sources(db, studio, organization):
    """Resolve a studio's pinned DataSources (org-scoped). Mirrors
    ``services.studio_artifacts._gather_pinned_sources``; returns [] on failure."""
    try:
        from app.models.data_source import DataSource
        from app.models.studio import StudioDataSource

        org_id = getattr(organization, "id", None) or getattr(
            studio, "organization_id", None
        )
        res = await db.execute(
            select(StudioDataSource)
            .where(
                StudioDataSource.studio_id == studio.id,
                StudioDataSource.deleted_at.is_(None),
            )
            .order_by(StudioDataSource.created_at.asc())
        )
        pins = list(res.scalars().all())
        if not pins:
            return []
        agent_ids = [p.agent_id for p in pins]
        ds_res = await db.execute(
            select(DataSource).where(
                DataSource.id.in_(agent_ids),
                DataSource.organization_id == org_id,
            )
        )
        return list(ds_res.scalars().all())
    except Exception as e:  # noqa: BLE001 - fail-soft
        logger.warning("train_orchestrator pinned-source resolution failed: %s", e)
        return []


async def run_training(studio_id, organization_id, user_id) -> None:
    """Run the full studio auto-train pipeline in the background. NEVER raises.

    Opens its own fresh session, reloads org/user/studio by PK, then runs the
    stages (profile -> queries -> evals -> artifacts), updating ``_RUNS`` after
    each. A stage error is recorded in ``detail`` and the run continues.
    """
    sid = str(studio_id)
    _RUNS[sid] = {
        "status": "running",
        "step": "starting",
        "pct": 5,
        "started_at": datetime.utcnow().isoformat(),
        "detail": {},
    }

    try:
        from app.dependencies import async_session_maker
        from app.models.organization import Organization
        from app.models.user import User
    except Exception as e:  # noqa: BLE001 - cannot even import deps
        _RUNS[sid] = {"status": "error", "error": f"import failed: {e}"}
        return

    try:
        async with async_session_maker() as db:
            # Reload org / user / studio by PK in THIS session.
            organization = (
                await db.execute(
                    select(Organization).where(Organization.id == organization_id)
                )
            ).scalar_one_or_none()
            user = (
                await db.execute(select(User).where(User.id == user_id))
            ).scalar_one_or_none()
            studio = await _load_studio(db, studio_id)

            if studio is None or organization is None:
                _RUNS[sid] = {
                    "status": "error",
                    "error": "studio or organization not found",
                }
                return

            detail = _RUNS[sid]["detail"]
            # Resolve pinned sources ONCE — reused across profiling + joins stages.
            sources = await _resolve_pinned_sources(db, studio, organization)

            # --- Stage 1: profile all pinned sources (pct 40) -----------------
            _set(sid, step="profiling", pct=10)
            try:
                from app.routes.column_profile import _profile_all_tables

                profiled = 0
                for ds in sources:
                    try:
                        written, _u, reports, _rows, _n = await _profile_all_tables(
                            db, ds, str(ds.id)
                        )
                        if reports:
                            profiled += 1
                    except Exception as e:  # noqa: BLE001 - per-source fail-soft
                        logger.warning(
                            "train_orchestrator profile failed for %s: %s",
                            getattr(ds, "id", "?"),
                            e,
                        )
                await db.commit()
                detail["profiling"] = f"ok ({profiled}/{len(sources)} sources)"
            except Exception as e:  # noqa: BLE001
                try:
                    await db.rollback()
                except Exception:
                    pass
                detail["profiling"] = f"error: {e}"
            _set(sid, pct=40)
            await _persist_db(db, studio, sid)

            # --- Stage 2: auto-queries (pct 60) -------------------------------
            _set(sid, step="queries", pct=45)
            try:
                from app.ai.knowledge.auto_queries import generate_queries_for_studio

                qres = await generate_queries_for_studio(
                    db,
                    organization=organization,
                    current_user=user,
                    studio_id=sid,
                )
                detail["queries"] = qres
            except Exception as e:  # noqa: BLE001
                try:
                    await db.rollback()
                except Exception:
                    pass
                detail["queries"] = f"error: {e}"
            _set(sid, pct=60)

            # --- Stage 3: auto-evals (pct 75) ---------------------------------
            _set(sid, step="evals", pct=65)
            try:
                from app.ai.knowledge.auto_evals import generate_evals_for_studio

                eres = await generate_evals_for_studio(
                    db,
                    organization=organization,
                    current_user=user,
                    studio_id=sid,
                )
                detail["evals"] = eres
            except Exception as e:  # noqa: BLE001
                try:
                    await db.rollback()
                except Exception:
                    pass
                detail["evals"] = f"error: {e}"
            _set(sid, pct=75)
            await _persist_db(db, studio, sid)

            # --- Stage 4: artifacts loop (pct 95) -----------------------------
            _set(sid, step="artifacts", pct=80)
            artifacts = {}
            try:
                from app.models.studio import StudioArtifact
                from app.services.studio_artifacts import generate_artifact

                for kind in _ARTIFACT_KINDS:
                    try:
                        content = await generate_artifact(
                            db, studio, kind, organization=organization
                        )
                        row = StudioArtifact(
                            studio_id=sid, kind=kind, content=content
                        )
                        db.add(row)
                        await db.commit()
                        artifacts[kind] = "ok"
                    except Exception as e:  # noqa: BLE001 - per-kind fail-soft
                        try:
                            await db.rollback()
                        except Exception:
                            pass
                        artifacts[kind] = f"error: {e}"
                detail["artifacts"] = artifacts
            except Exception as e:  # noqa: BLE001
                detail["artifacts"] = f"error: {e}"
            _set(sid, pct=92)

            # --- Stage 5: value-overlap join mining (pct 98) ------------------
            # Proven-SQL joins need query history; value-overlap works on day 1.
            _set(sid, step="joins", pct=94)
            try:
                from app.ai.knowledge.join_miner import mine_value_overlap_edges

                mined = 0
                for ds in sources:
                    try:
                        r = await mine_value_overlap_edges(
                            db, organization=organization, data_source=ds
                        )
                        mined += int((r or {}).get("mined", 0) or 0)
                    except Exception as e:  # noqa: BLE001 - per-source fail-soft
                        logger.warning("train_orchestrator value-joins failed for %s: %s", getattr(ds, "id", "?"), e)
                detail["joins"] = f"ok ({mined} value-overlap edges)"
            except Exception as e:  # noqa: BLE001
                try:
                    await db.rollback()
                except Exception:
                    pass
                detail["joins"] = f"error: {e}"
            _set(sid, pct=98)

            # --- Done ---------------------------------------------------------
            _set(
                sid,
                status="done",
                step="done",
                pct=100,
                finished_at=datetime.utcnow().isoformat(),
            )
            await _persist_db(db, studio, sid)
    except Exception as e:  # noqa: BLE001 - fatal, never raise out of the task
        logger.warning("train_orchestrator fatal for studio %s: %s", sid, e)
        _RUNS[sid] = {"status": "error", "error": str(e)}


def start_training(studio_id, organization_id, user_id) -> dict:
    """Schedule a background train run for a studio (idempotent per studio).

    If a run is already in progress for this studio, returns the current status
    instead of starting a second one. Otherwise seeds the initial ``_RUNS``
    entry, schedules ``run_training`` via ``asyncio.create_task`` and keeps a
    STRONG reference to the task (``_TASKS``) so it isn't GC'd.
    """
    sid = str(studio_id)
    cur = _RUNS.get(sid)
    if isinstance(cur, dict) and cur.get("status") == "running":
        return cur

    _RUNS[sid] = {
        "status": "running",
        "step": "starting",
        "pct": 5,
        "started_at": datetime.utcnow().isoformat(),
        "detail": {},
    }

    task = asyncio.create_task(run_training(studio_id, organization_id, user_id))
    _TASKS.append(task)
    # Drop the strong ref once the task is done so the list doesn't grow forever.
    task.add_done_callback(lambda t: _TASKS.remove(t) if t in _TASKS else None)

    return {"started": True, "status": "running", "studio_id": sid}
