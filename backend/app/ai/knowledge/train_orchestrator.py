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


# --- Claude-Code-style live log -------------------------------------------
# Each run keeps a rolling buffer of timestamped log lines (capped). Lines come
# from (a) explicit _log() calls at stage/LLM boundaries and (b) a logging
# handler that captures everything the trainer + LLM client already emit, so the
# panel shows "which model / how many tokens / what saved" without threading
# state through every call site.
_LOG_CAP = 1500         # max lines kept in-process (verbose streaming)
_LOG_PERSIST_CAP = 600  # max lines mirrored to the DB (bound JSON size)


def _log(studio_id, msg, level: str = "info") -> None:
    """Append one timestamped line to the run's log buffer (capped)."""
    sid = str(studio_id)
    cur = _RUNS.get(sid)
    if not isinstance(cur, dict):
        return
    buf = cur.get("log")
    if not isinstance(buf, list):
        buf = []
        cur["log"] = buf
    try:
        ts = datetime.now().strftime("%H:%M:%S.") + f"{datetime.now().microsecond // 100000}"
    except Exception:  # noqa: BLE001
        ts = ""
    buf.append({"t": ts, "lvl": level, "msg": str(msg)[:500]})
    if len(buf) > _LOG_CAP:
        del buf[: len(buf) - _LOG_CAP]


class _RunLogHandler(logging.Handler):
    """Routes log records emitted DURING a run into that run's log buffer.

    Attached to the trainer + LLM loggers for the run's lifetime, detached in
    finally. Maps Python levels to our cli levels (error/warn/info)."""

    def __init__(self, sid: str):
        super().__init__(level=logging.INFO)
        self._sid = sid

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D401
        try:
            if record.levelno >= logging.ERROR:
                lvl = "error"
            elif record.levelno >= logging.WARNING:
                lvl = "warn"
            else:
                lvl = "info"
            msg = record.getMessage()
            # strip the noisy module-prefix the trainer prepends
            if msg.startswith("train_orchestrator "):
                msg = msg[len("train_orchestrator "):]
            _log(self._sid, msg, lvl)
        except Exception:  # noqa: BLE001 - logging must never raise
            pass


# Logger names whose records we capture into the live log during a run.
# Pipeline v1: widened so per-table profiling, semantic proposals, golden writes,
# join mining, ingest + tool detail stream into the live train log (was only the
# coarse `▸ stage` markers).
_CAPTURE_LOGGERS = (
    "app.ai.knowledge", "app.ai.llm", "app.ai.brain", "app.ai.tools",
    "app.routes.column_profile", "app.services.ingest", "app.services.train",
    __name__,
)


def _attach_log_capture(sid: str):
    """Attach a capture handler to the trainer/LLM loggers; return (handler,
    [loggers]) so the caller can detach in finally."""
    handler = _RunLogHandler(sid)
    attached = []
    for name in _CAPTURE_LOGGERS:
        lg = logging.getLogger(name)
        lg.addHandler(handler)
        if lg.level == logging.NOTSET or lg.level > logging.INFO:
            # ensure INFO records reach the handler without changing global config
            lg.setLevel(logging.INFO)
        attached.append(lg)
    return handler, attached


def _detach_log_capture(handler, loggers) -> None:
    for lg in loggers or []:
        try:
            lg.removeHandler(handler)
        except Exception:  # noqa: BLE001
            pass


def reset_status(studio_id) -> None:
    """Drop any in-process status/log for a studio (used by the reset route)."""
    _RUNS.pop(str(studio_id), None)


async def _persist_db(db, studio, sid) -> None:
    """Mirror the in-process status onto Studio.config['_train_status'] so it is
    visible across uvicorn workers (the in-process _RUNS is per-process). Cheap,
    called at stage boundaries. Fail-soft."""
    try:
        from sqlalchemy.orm.attributes import flag_modified

        cfg = studio.config if isinstance(studio.config, dict) else {}
        cfg = dict(cfg)
        snap = dict(_RUNS.get(str(sid), {}))
        # mirror only the tail of the log to bound the persisted JSON size
        if isinstance(snap.get("log"), list) and len(snap["log"]) > _LOG_PERSIST_CAP:
            snap["log"] = snap["log"][-_LOG_PERSIST_CAP:]
        cfg["_train_status"] = snap
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


async def _route_inbox(sid, studio_id, organization_id, user_id) -> dict:
    """``route_inbox`` train stage (flag HYBRID_TRAIN_ROUTING).

    Classifies each file queued in ``Studio.config['inbox']`` with the train
    model (the studio's configured ``model_id``, else legacy ``train_model_id``,
    else the org default model — NO hardcoded slug) and
    a LARGE excerpt, then AUTO-PLACES confident files via the Smart Upload sinks
    and HOLDS uncertain / answer-changing ones in ``Studio.config['inbox_held']``
    for post-train Review. Runs in its OWN session so ``apply_routes``'s internal
    commit cannot expire the main train session's ORM objects (greenlet landmine).
    Fail-soft: never raises; returns a summary dict.
    """
    from app.settings.hybrid_flags import flags as _flags
    if not getattr(_flags, "TRAIN_ROUTING", False):
        return {"skipped": "flag off"}
    try:
        from app.dependencies import async_session_maker
        from app.models.organization import Organization
        from app.models.user import User
        from app.models.file import File as _File
        from app.models.llm_model import LLMModel
        from app.services.smart_upload import classifier as _clf
        from app.services.smart_upload import apply as _sapply
        from app.services.llm_service import LLMService
    except Exception as e:  # noqa: BLE001
        _log(sid, f"route_inbox import failed: {e}", "warn")
        return {"error": f"import: {e}"}

    placed = 0
    held_new: list = []
    per_file: list = []      # one entry per classified queued file (segregation receipt)
    by_dest: dict = {}       # dest -> count of placed files
    files_in = 0             # number of queued files seen
    try:
        async with async_session_maker() as rdb:
            studio = await _load_studio(rdb, studio_id)
            organization = (await rdb.execute(
                select(Organization).where(Organization.id == organization_id)
            )).scalar_one_or_none()
            user = (await rdb.execute(
                select(User).where(User.id == user_id)
            )).scalar_one_or_none()
            if studio is None or organization is None:
                return {"skipped": "no studio/org"}

            cfg = studio.config if isinstance(studio.config, dict) else {}
            queued = [q for q in (cfg.get("inbox") or []) if isinstance(q, dict)]
            if not queued:
                return {"skipped": "empty inbox"}
            files_in = len(queued)

            _log(sid, f"▸ route_inbox · sorting {len(queued)} inbox file(s)", "info")

            # Resolve the train model: prefer the studio's configured model,
            # else the legacy train_model_id, else the org default model.
            # NO hardcoded slug. None => heuristic-only.
            train_model = None
            want = cfg.get("model_id") or cfg.get("train_model_id")
            if not want:
                # Org-level training default (LLM settings → Agent Defaults),
                # inserted between the studio config and the generic org default.
                # Fail-soft: never break training if settings are unreadable.
                try:
                    from app.services.organization_settings_service import (
                        OrganizationSettingsService,
                    )
                    _os = await OrganizationSettingsService().get_settings(
                        rdb, organization, user)
                    _oc = _os.config if isinstance(_os.config, dict) else {}
                    want = _oc.get("default_studio_train_model_id") or _oc.get("default_train_model_id") or want
                except Exception:  # noqa: BLE001
                    pass
            try:
                train_model = (await rdb.execute(
                    select(LLMModel)
                    .filter(LLMModel.organization_id == organization.id)
                    .filter(LLMModel.model_id == want)
                    .filter(LLMModel.is_enabled == True)  # noqa: E712
                )).scalar_one_or_none()
            except Exception:  # noqa: BLE001
                train_model = None
            if train_model is None:
                try:
                    train_model = await LLMService().get_default_model(
                        rdb, organization, user)
                except Exception:  # noqa: BLE001
                    train_model = None
            _log(sid, f"  route model: "
                      f"{getattr(train_model, 'model_id', None) or 'heuristic-only'}",
                 "info")

            # Build {path, filename} per queued file (resolve path from File).
            files = []
            for q in queued:
                p = ""
                f = (await rdb.execute(
                    select(_File).where(
                        _File.id == str(q.get("file_id")),
                        _File.organization_id == organization.id,
                    )
                )).scalar_one_or_none()
                if f is not None:
                    p = _sapply._resolve_path(f.path or "") or ""
                files.append({"path": p, "filename": q.get("filename") or ""})

            records = await _clf.classify_batch(
                files, llm=train_model, organization=organization,
                excerpt_chars=4000,
            )

            # Build the plan as PLAIN dicts (no ORM) so the per-item apply below
            # can run in its OWN fresh session. semantic needs an existing target
            # data source to map onto — at train time there isn't one yet, so we
            # HOLD it for Review rather than letting it fail mid-batch.
            confident = []  # plain apply items
            _VALID_DESTS = {"database", "data", "semantic", "instructions",
                            "examples", "knowledge", "skip"}
            for q, rec in zip(queued, records):
                rec = dict(rec)
                # Honor a human re-route from the Inbox: if the user pinned a
                # lane before training, use it instead of the re-classification.
                if (q.get("dest_source") == "user"
                        and q.get("dest") in _VALID_DESTS):
                    rec["dest"] = q.get("dest")
                    rec["source"] = "user"
                    rec["needs_confirm"] = False
                dest = rec.get("dest")
                src = rec.get("source")
                base = {"file_id": q.get("file_id"), "filename": q.get("filename"),
                        "dest": dest, "confidence": rec.get("confidence"),
                        "reason": rec.get("reason"), "signals": rec.get("signals"),
                        "source": src}
                if rec.get("needs_confirm") or dest in (None, "", "skip"):
                    held_new.append(base)
                    per_file.append({"filename": q.get("filename"), "dest": dest,
                                     "confidence": rec.get("confidence"),
                                     "source": src, "placed": False})
                    _log(sid, f"  ⏸ {q.get('filename')} → {dest} "
                              f"{rec.get('confidence')}% HELD", "info")
                elif dest == "semantic":
                    base["reason"] = ("glossary needs a target data source — map it "
                                      "after the data is ingested")
                    held_new.append(base)
                    per_file.append({"filename": q.get("filename"), "dest": dest,
                                     "confidence": rec.get("confidence"),
                                     "source": src, "placed": False})
                    _log(sid, f"  ⏸ {q.get('filename')} → semantic HELD "
                              "(needs a data source to map onto)", "info")
                else:
                    confident.append(base)

        # --- apply each confident item in ITS OWN fresh session (PARALLEL) -----
        # apply_routes + create_data_source_from_file commit/rollback internally;
        # sharing one session means one item's failure poisons the rest, so each
        # item opens its OWN session. Those sessions are independent, so we run
        # them with bounded concurrency (Semaphore(4)) instead of serially.
        async def _apply_one(item: dict) -> dict:
            try:
                async with async_session_maker() as adb:
                    org = (await adb.execute(select(Organization).where(
                        Organization.id == organization_id))).scalar_one_or_none()
                    usr = (await adb.execute(select(User).where(
                        User.id == user_id))).scalar_one_or_none()
                    res = await _sapply.apply_routes(
                        adb, organization=org, current_user=usr,
                        studio_id=str(studio_id), data_source_id=None,
                        items=[item],
                    )
                r0 = (res.get("results") or [{}])[0]
                if r0.get("ok"):
                    return {"ok": True, "item": item, "error": None}
                return {"ok": False, "item": item,
                        "error": str(r0.get("detail") or "apply returned not-ok")}
            except Exception as ie:  # noqa: BLE001 - one bad item never sinks others
                return {"ok": False, "item": item, "error": str(ie)}

        if confident:
            # Data files flow through create_data_source_from_file, which is NOT
            # concurrency-safe: it commits internally (expires ORM -> MissingGreenlet
            # under parallel sessions) and auto-names the connection (parallel ->
            # duplicate-name IntegrityError on "spreadsheet-1"). So apply DATA items
            # strictly SEQUENTIALLY; the lighter instruction/example/skill items
            # stay parallel. Sequential also lets same-schema months merge cleanly.
            _DATA_DESTS = {"database", "data"}
            data_items = [it for it in confident if it.get("dest") in _DATA_DESTS]
            other_items = [it for it in confident if it.get("dest") not in _DATA_DESTS]

            results = []
            for it in data_items:
                results.append(await _apply_one(it))

            if other_items:
                _sem = asyncio.Semaphore(4)

                async def _guarded(it: dict) -> dict:
                    async with _sem:
                        return await _apply_one(it)

                results.extend(await asyncio.gather(
                    *[_guarded(it) for it in other_items],
                    return_exceptions=False,
                ))

            for r in results:
                item = r.get("item", {})
                dest = item.get("dest")
                if r.get("ok"):
                    placed += 1
                    by_dest[dest] = by_dest.get(dest, 0) + 1
                    per_file.append({"filename": item.get("filename"), "dest": dest,
                                     "confidence": item.get("confidence"),
                                     "source": item.get("source"), "placed": True})
                    _log(sid, f"  ✓ {item.get('filename')} → {dest} "
                              f"{item.get('confidence')}% placed", "info")
                else:
                    err = r.get("error") or "apply failed"
                    per_file.append({"filename": item.get("filename"), "dest": dest,
                                     "confidence": item.get("confidence"),
                                     "source": item.get("source"), "placed": False})
                    _log(sid, f"  ✗ {item.get('filename')} → {dest} "
                              f"FAILED: {err}", "warn")
                    held_new.append({**item,
                                     "reason": f"placement failed: {err}"})

        # NOTE: the inbox-clear + held write is done by the CALLER on the main
        # train session's studio object — NOT here. A separate session would race
        # the train loop's periodic _persist_db(studio.config) writes (which carry
        # the stale inbox) and get clobbered. We just return the held list.
        _log(sid, f"  route_inbox done · {placed} placed · {len(held_new)} held",
             "info")
        return {"placed": placed, "held": len(held_new), "held_list": held_new,
                "per_file": per_file, "by_dest": by_dest, "files_in": files_in}
    except Exception as e:  # noqa: BLE001
        _log(sid, f"route_inbox error: {e}", "warn")
        return {"error": str(e), "held_list": held_new,
                "per_file": per_file, "by_dest": by_dest, "files_in": files_in}


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
        "log": [],
    }
    _log_handler, _log_loggers = _attach_log_capture(sid)
    _log(sid, "Auto-train started", "info")

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

            # IDLE-IN-TXN GUARD: the PK reloads above (org/user/studio SELECTs)
            # leave an OPEN read transaction on this main `db`. The next stage
            # (`_route_inbox`) classifies every inbox file via the LLM and can run
            # for many MINUTES in its own session, during which `db` sits
            # idle-IN-transaction. Postgres `idle_in_transaction_session_timeout`
            # (300s, set in settings/database.py) then TERMINATES this connection,
            # so every later use (`db.refresh`, `_resolve_pinned_sources`, every
            # downstream stage) hits `connection is closed` / `Can't reconnect
            # until invalid transaction is rolled back` and the WHOLE train rolls
            # back — nothing past Stage 0 persists. Commit here to end the read
            # txn so the connection goes plain-idle (no idle-in-txn timer) and
            # survives the long external waits. (pool_pre_ping can't help: it only
            # validates on pool checkout, never a connection held for the run.)
            try:
                await db.commit()
            except Exception:
                try:
                    await db.rollback()
                except Exception:
                    pass

            # Mirror the initial "running" status to the DB NOW so a poll landing
            # on another uvicorn worker (in-proc _RUNS is per-worker) sees the run
            # from the start — the next _persist_db is only at pct 40 (profiling),
            # which would otherwise leave cross-worker polls reading "idle" for the
            # long route_inbox stage. Fail-soft (own commit inside _persist_db).
            await _persist_db(db, studio, sid)

            # --- Stage 0: route inbox files (Inbox -> Train) ------------------
            # Classify + place any files queued in the studio inbox BEFORE we
            # resolve sources, so newly-placed Database sources are profiled in
            # this same run. Own-session + fail-soft; no-op when the flag is off
            # or the inbox is empty.
            try:
                _set(sid, step="route_inbox", pct=8, note="sorting inbox")
                _ri = await _route_inbox(
                    sid, studio_id, organization_id, user_id)
                detail["route_inbox"] = {k: v for k, v in _ri.items()
                                         if k != "held_list"}
                # Persist inbox-clear + held on THIS (main) session's studio so it
                # rides the train loop's own config writes (no cross-session race).
                if "held_list" in _ri and not _ri.get("skipped"):
                    await db.refresh(studio)
                    cfg = dict(studio.config) if isinstance(studio.config, dict) else {}
                    prev = [h for h in (cfg.get("inbox_held") or [])
                            if isinstance(h, dict)]
                    merged = {str(h.get("file_id")): h for h in prev}
                    for h in (_ri.get("held_list") or []):
                        merged[str(h.get("file_id"))] = h
                    cfg["inbox_held"] = list(merged.values())
                    cfg["inbox"] = []
                    studio.config = cfg
                    await db.commit()
                    await db.refresh(studio)
            except Exception as _rie:  # noqa: BLE001
                detail["route_inbox"] = {"error": str(_rie)}
                _log(sid, f"route_inbox stage error: {_rie}", "warn")

            # Resolve pinned sources ONCE — reused across profiling + joins stages.
            # (Resolved AFTER route_inbox so freshly-placed sources are included.)
            sources = await _resolve_pinned_sources(db, studio, organization)
            _log(sid, f"studio '{getattr(studio, 'name', sid)}' · {len(sources)} pinned source(s)", "info")

            # --- Stage 0b: ingest self-heal (stitch split same-schema tables) --
            # Repair an agent whose same-schema data got split across multiple
            # physical staging tables (files uploaded in separate sessions) —
            # UNION-append the orphan rows back into the ONE bound table. Runs
            # BEFORE profiling/reconcile/index so every later stage sees the
            # merged rows. Generic + idempotent + fail-soft. No-op unless the
            # flag is on / self-limits to sources that actually have staging
            # tables. Never raises.
            try:
                from app.settings.hybrid_flags import flags as _sh_flags
                if _sh_flags.INGEST_SELFHEAL:
                    _set(sid, step="selfheal", pct=9, note="repairing split data")
                    _log(sid, "▸ self-heal split data", "info")
                    from app.services.ingest.selfheal import selfheal_data_source
                    _healed = 0
                    _added = 0
                    for ds in sources:
                        try:
                            r = await selfheal_data_source(
                                db, organization=organization, data_source=ds,
                                dry_run=False, drop_orphans=True,
                            )
                            if r and r.get("tables_stitched"):
                                _healed += int(r.get("tables_stitched") or 0)
                                _added += int(r.get("rows_added") or 0)
                                _log(sid, f"  {getattr(ds,'name','?')}: {r.get('note')}", "info")
                        except Exception as _she:  # noqa: BLE001 — per-source fail-soft
                            logger.warning("train_orchestrator selfheal failed for %s: %s",
                                           getattr(ds, "id", "?"), _she)
                    detail["selfheal"] = f"ok ({_healed} stitched, {_added} rows)"
                    _log(sid, f"self-heal: {_healed} table(s) stitched, {_added} rows added", "info")
            except Exception as _e:  # noqa: BLE001
                try:
                    await db.rollback()
                except Exception:  # noqa: BLE001
                    pass
                detail["selfheal"] = f"error: {_e}"
                _log(sid, f"selfheal failed: {_e}", "warn")
            # --- Resolve the studio's CHOSEN train model ONCE ------------------
            # studio.config['train_model_id'] -> org LLMModel row -> org default.
            # Passed into every generation stage below so the WHOLE train log +
            # output reflects the picked model (not the org small default). When
            # unset -> None -> each stage falls back to its own get_default_model.
            train_model = None
            try:
                from app.models.llm_model import LLMModel as _LLMModelTM
                from app.services.llm_service import LLMService as _LLMSvc0
                _cfg0 = studio.config if isinstance(studio.config, dict) else {}
                _want = _cfg0.get("model_id") or _cfg0.get("train_model_id")
                if not _want:
                    # Org-level TRAINING default (Settings → LLM → Agent Defaults),
                    # inserted between the studio config and the generic org
                    # (analysis) default. Fail-soft: never break the run.
                    try:
                        from app.services.organization_settings_service import (
                            OrganizationSettingsService,
                        )
                        _os0 = await OrganizationSettingsService().get_settings(
                            db, organization, user)
                        _oc0 = _os0.config if isinstance(_os0.config, dict) else {}
                        _want = _oc0.get("default_studio_train_model_id") or _oc0.get("default_train_model_id") or _want
                    except Exception:  # noqa: BLE001
                        pass
                if _want:
                    train_model = (await db.execute(
                        select(_LLMModelTM)
                        .filter(_LLMModelTM.organization_id == organization.id)
                        .filter(_LLMModelTM.model_id == _want)
                        .filter(_LLMModelTM.is_enabled == True)  # noqa: E712
                    )).scalar_one_or_none()
                if train_model is None:
                    train_model = await _LLMSvc0().get_default_model(db, organization)
                _tm_name = getattr(train_model, "model_id", None) or getattr(train_model, "name", None) or "org default"
                _log(sid, f"train model: {_tm_name}", "info")
            except Exception as _dme:  # noqa: BLE001 - fail-soft, model is informational
                train_model = None
                _log(sid, f"could not resolve train model: {_dme}", "warn")

            # --- Stage 1: profile all pinned sources (pct 10 -> 40) -----------
            # Profiling N tables × many columns against a live connector can take
            # minutes; without intra-stage feedback the UI looks frozen at 10%.
            # A per-table progress callback interpolates pct across the 10..40
            # slice and writes a human note ("RTM · 3/8 tables"), so the bar moves.
            _set(sid, step="profiling", pct=10, note="starting")
            _log(sid, "▸ profile columns", "info")
            try:
                from app.routes.column_profile import _profile_all_tables

                profiled = 0
                n_src = max(1, len(sources))
                for si, ds in enumerate(sources):
                    ds_name = getattr(ds, "name", None) or str(getattr(ds, "id", "?"))[:8]
                    base = 10 + int(30 * si / n_src)      # this source's slice start
                    span = 30 / n_src                      # pct width for this source

                    def _on_table(done, total, table, written, _base=base, _span=span, _name=ds_name):
                        pct = int(_base + _span * (done / max(1, total)))
                        _set(sid, pct=min(39, max(10, pct)),
                             note=f"{_name} · {done}/{total} tables")

                    try:
                        # Hard ceiling per source: a hung remote query (no
                        # statement_timeout) must not freeze the train forever.
                        written, _u, reports, _rows, _n = await asyncio.wait_for(
                            _profile_all_tables(db, ds, str(ds.id), progress=_on_table),
                            timeout=600,
                        )
                        if reports:
                            profiled += 1
                        logger.info("train_orchestrator profiled %s: %s cols, %s tables",
                                    ds_name, written, _n)
                    except asyncio.TimeoutError:
                        logger.warning("train_orchestrator profile TIMEOUT (600s) for %s", ds_name)
                        _set(sid, note=f"{ds_name} · timed out, skipped")
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
            _set(sid, pct=40, note="")
            await _persist_db(db, studio, sid)

            # --- Stage 1a-pre: smart source name (month token -> real range) ---
            # If a source's display name carries a SINGLE month token (e.g.
            # "(Apr'25)") but its merged table actually spans multiple periods
            # (_source_period), rewrite the display NAME to the true range
            # ("(Jan-Jun'25)"). Renames DataSource.name ONLY — never the table
            # id/slug. Entirely fail-soft: any error leaves the name unchanged.
            from app.settings.hybrid_flags import flags as _ssn_flags
            if _ssn_flags.SMART_SOURCE_NAME:
                _set(sid, step="smart_source_name", pct=40)
                try:
                    import re as _re
                    from sqlalchemy import select as _sel_n
                    from app.models.datasource_table import DataSourceTable as _DST_n

                    _MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                            "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
                    _SINGLE_RE = _re.compile(
                        r"\(\s*([A-Za-z]{3,9})\s*['`’]?\s*(\d{2,4})\s*\)")

                    def _fmt_range(pmin, pmax):
                        try:
                            y1, m1 = int(pmin[:4]), int(pmin[5:7])
                            y2, m2 = int(pmax[:4]), int(pmax[5:7])
                            if not (1 <= m1 <= 12 and 1 <= m2 <= 12):
                                return None
                            a, b = _MON[m1 - 1], _MON[m2 - 1]
                            if y1 == y2:
                                return f"{a}-{b}'{y2 % 100:02d}"
                            return f"{a}'{y1 % 100:02d}-{b}'{y2 % 100:02d}"
                        except Exception:  # noqa: BLE001
                            return None

                    renamed = 0
                    for ds in sources:
                        try:
                            cur = getattr(ds, "name", None) or ""
                            # need a single-month token; skip if already a range
                            if "-" in cur.split("(")[-1] or "–" in cur:
                                continue
                            if not _SINGLE_RE.search(cur):
                                continue
                            tbls = list((await db.execute(
                                _sel_n(_DST_n)
                                .where(_DST_n.datasource_id == str(ds.id))
                                .where(_DST_n.is_active.is_(True))
                            )).scalars().all())
                            client = None
                            periods = set()
                            for tbl in tbls:
                                cols = tbl.columns if isinstance(tbl.columns, list) else []
                                if not any(isinstance(c, dict) and c.get("name") == "_source_period" for c in cols):
                                    continue
                                if client is None:
                                    client = ds.get_client()
                                df = await client.aexecute_query(
                                    f'SELECT DISTINCT "_source_period" AS p FROM "{tbl.name}" ORDER BY 1')
                                try:
                                    vals = list(df["p"].tolist())
                                except Exception:  # noqa: BLE001
                                    vals = list(df.iloc[:, 0].tolist())
                                for v in vals[:200]:
                                    s = str(v) if v is not None else ""
                                    if _re.fullmatch(r"\d{4}-\d{2}", s):
                                        periods.add(s)
                            if len(periods) <= 1:
                                continue
                            rng = _fmt_range(min(periods), max(periods))
                            if not rng:
                                continue
                            base = _SINGLE_RE.sub("", cur)
                            base = _re.sub(r"\.(csv|xlsx?|tsv|parquet|json)\b", "", base, flags=_re.I)
                            base = _re.sub(r"\s{2,}", " ", base).strip().rstrip("-·").strip()
                            new_name = f"{base} ({rng})".strip()
                            if new_name and new_name != cur:
                                ds.name = new_name
                                renamed += 1
                                _log(sid, f"renamed source -> {new_name}", "info")
                        except Exception as _one:  # noqa: BLE001 - per-source fail-soft
                            logger.warning("smart_source_name: %s failed: %s",
                                           getattr(ds, "id", "?"), _one)
                    if renamed:
                        await db.commit()
                    detail["smart_source_name"] = f"ok ({renamed} renamed)"
                except Exception as e:  # noqa: BLE001
                    try:
                        await db.rollback()
                    except Exception:
                        pass
                    detail["smart_source_name"] = f"error: {e}"

            # --- Stage 1a: deep profile v2 (Wave1 P1) -------------------------
            # When flags.PROFILE_V2 is ON, run profile_table_v2 on every active
            # table of each source AFTER the column profiler has written its data.
            # Mirrors the Stage 4b (semantic_metrics) pattern: per-source fail-soft,
            # single commit at the end.  Zero DB reads / writes when flag is OFF.
            from app.settings.hybrid_flags import flags as _flags

            if _flags.PROFILE_V2:
                _set(sid, step="profile_v2", pct=41)
                _log(sid, "▸ deep profile", "info")
                try:
                    from sqlalchemy import select as _sel
                    from app.models.datasource_table import DataSourceTable as _DST
                    from app.ai.knowledge.profile_v2 import profile_table_v2 as _pv2

                    pv2_count = 0
                    for ds in sources:
                        try:
                            tbl_rows = list(
                                (
                                    await db.execute(
                                        _sel(_DST)
                                        .where(_DST.datasource_id == str(ds.id))
                                        .where(_DST.is_active.is_(True))
                                    )
                                ).scalars().all()
                            )
                            for tbl_row in tbl_rows:
                                try:
                                    _pv2(tbl_row)
                                    pv2_count += 1
                                except Exception as _te:  # noqa: BLE001
                                    logger.debug(
                                        "train_orchestrator profile_v2 table %s: %s",
                                        getattr(tbl_row, "name", "?"),
                                        _te,
                                    )
                        except Exception as _se:  # noqa: BLE001 - per-source fail-soft
                            logger.warning(
                                "train_orchestrator profile_v2 source %s: %s",
                                getattr(ds, "id", "?"),
                                _se,
                            )
                    await db.commit()
                    detail["profile_v2"] = f"ok ({pv2_count} tables)"
                except Exception as e:  # noqa: BLE001
                    try:
                        await db.rollback()
                    except Exception:
                        pass
                    detail["profile_v2"] = f"error: {e}"

            # --- Stage 1b: code enrich (Wave1 P6) --------------------------------
            # When flags.CODE_ENRICH is ON, fetch view/table DDL for each active
            # table and LLM-extract grain + derived-column formulas + population.
            # Stores in metadata_json['pipeline_logic'].  Mirrors Stage 1a pattern.
            # Zero DB reads/writes when flag is OFF.
            if _flags.CODE_ENRICH:
                _set(sid, step="code_enrich", pct=42)
                _log(sid, "▸ code enrich", "info")
                try:
                    from app.ai.knowledge.code_enrich import enrich_source
                    from app.services.llm_service import LLMService as _LLMSvc

                    _ce_model = train_model or await _LLMSvc().get_default_model(
                        db, organization, user, is_small=True
                    )
                    ce_enriched = 0
                    ce_skipped = 0
                    for ds in sources:
                        try:
                            r = await enrich_source(
                                db,
                                data_source=ds,
                                organization=organization,
                                model=_ce_model,
                            )
                            ce_enriched += int((r or {}).get("enriched", 0) or 0)
                            ce_skipped += int((r or {}).get("skipped", 0) or 0)
                        except Exception as _ce_err:  # noqa: BLE001 - per-source fail-soft
                            logger.warning(
                                "train_orchestrator code_enrich failed for %s: %s",
                                getattr(ds, "id", "?"),
                                _ce_err,
                            )
                    detail["code_enrich"] = f"ok ({ce_enriched} enriched, {ce_skipped} skipped)"
                except Exception as e:  # noqa: BLE001
                    try:
                        await db.rollback()
                    except Exception:
                        pass
                    detail["code_enrich"] = f"error: {e}"

            # --- Stage 1c: pack autobind (Phase 4) ----------------------------
            # Try every library pack against the freshly-profiled columns; write
            # pending/dormant StudioBoundPack rows. Then render the studio's ACTIVE
            # skills into a context block that biases the query/eval generators.
            _set(sid, step="packs", pct=42)
            _log(sid, "▸ bind domain packs", "info")
            skill_context = ""
            try:
                from app.ai.packs.pack_train import (
                    autobind_library_packs,
                    recheck_bindings,
                    build_skill_context,
                )

                detail["packs"] = await autobind_library_packs(db, sid, organization)
                # Phase 5: re-check existing rows vs the just-profiled schema
                # (dormant->pending if a missing column appeared; active->dormant
                # if a bound column vanished).
                detail["pack_recheck"] = await recheck_bindings(db, sid)
                skill_context = await build_skill_context(db, sid)
            except Exception as e:  # noqa: BLE001
                try:
                    await db.rollback()
                except Exception:
                    pass
                detail["packs"] = f"error: {e}"
            _set(sid, pct=44)

            # --- Stage 2: auto-queries (pct 60) -------------------------------
            _set(sid, step="queries", pct=45)
            _log(sid, "▸ write example queries", "info")
            try:
                from app.ai.knowledge.auto_queries import generate_queries_for_studio

                qres = await generate_queries_for_studio(
                    db,
                    organization=organization,
                    current_user=user,
                    studio_id=sid,
                    model=train_model,
                    skill_context=skill_context,
                )
                detail["queries"] = qres
            except Exception as e:  # noqa: BLE001
                try:
                    await db.rollback()
                except Exception:
                    pass
                detail["queries"] = f"error: {e}"
            _set(sid, pct=60)
            # Mid-run persist: queries/evals are long LLM stages; mirror progress
            # so cross-worker polls track past the pct-40 profiling checkpoint.
            await _persist_db(db, studio, sid)

            # --- Stage 3: auto-evals (pct 75) ---------------------------------
            _set(sid, step="evals", pct=65)
            _log(sid, "▸ write eval goldens", "info")
            try:
                from app.ai.knowledge.auto_evals import generate_evals_for_studio

                eres = await generate_evals_for_studio(
                    db,
                    organization=organization,
                    current_user=user,
                    studio_id=sid,
                    model=train_model,
                    skill_context=skill_context,
                )
                detail["evals"] = eres
            except Exception as e:  # noqa: BLE001
                try:
                    await db.rollback()
                except Exception:
                    pass
                detail["evals"] = f"error: {e}"

            # --- Stage 3b: materialise pack-carried goldens (Phase 4) ---------
            try:
                from app.ai.packs.pack_train import materialize_pack_goldens

                detail["pack_goldens"] = await materialize_pack_goldens(
                    db, organization, sid
                )
            except Exception as e:  # noqa: BLE001
                try:
                    await db.rollback()
                except Exception:
                    pass
                detail["pack_goldens"] = f"error: {e}"

            # --- Stage 3c: MINT goldens from each active pack's method (Phase C) -
            # Run the pack method's headline computation on real data → real
            # expected value → golden TestCase. Reuses the auto_evals machinery.
            try:
                from app.ai.packs.pack_goldens import mint_pack_goldens

                detail["pack_goldens_minted"] = await mint_pack_goldens(
                    db, organization, sid
                )
            except Exception as e:  # noqa: BLE001
                try:
                    await db.rollback()
                except Exception:
                    pass
                detail["pack_goldens_minted"] = f"error: {e}"
            _set(sid, pct=75)
            await _persist_db(db, studio, sid)

            # --- Stage 4: artifacts loop (pct 95) -----------------------------
            _set(sid, step="artifacts", pct=80)
            _log(sid, "▸ generate artifacts", "info")
            artifacts = {}
            try:
                from app.models.studio import StudioArtifact
                from app.services.studio_artifacts import generate_artifact

                for kind in _ARTIFACT_KINDS:
                    try:
                        content = await generate_artifact(
                            db, studio, kind, organization=organization,
                            model=train_model
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

            # --- Stage 4b: semantic layer + metrics catalog (pct 93) ----------
            # Opt-in surfaces. Only runs when a flag is on. Proposals are AI-
            # pending; auto-approved here (like every other Auto-train stage) so
            # the Semantic / Metrics tabs are populated AND live after the one-
            # button train instead of sitting empty.
            from app.settings.hybrid_flags import flags as _flags

            if _flags.SEMANTIC_LAYER or _flags.METRICS_CATALOG:
                _set(sid, step="semantic_metrics", pct=93)
                _log(sid, "▸ semantic + metrics", "info")
                try:
                    from sqlalchemy import update as _sql_update

                    from app.ai.brain.knowledge_proposer import (
                        propose_column_meanings,
                        propose_knowledge_from_schema,
                    )
                    from app.models.metric_definition import MetricDefinition
                    from app.models.semantic_table import SemanticColumn, SemanticTable
                    from app.services.llm_service import LLMService

                    focus = (
                        "both"
                        if (_flags.SEMANTIC_LAYER and _flags.METRICS_CATALOG)
                        else ("semantic" if _flags.SEMANTIC_LAYER else "metrics")
                    )
                    model = train_model or await LLMService().get_default_model(
                        db, organization, user, is_small=True
                    )
                    sem_ids: list[str] = []
                    met_ids: list[str] = []
                    col_ids: list[str] = []
                    # T3: meanings bound from a sibling "Definitions" glossary.
                    # Kept SEPARATE from col_ids — these stay PENDING (approval
                    # gate), unlike the auto-approved AI-proposed meanings.
                    def_ids: list[str] = []
                    for ds in sources:
                        try:
                            r = await propose_knowledge_from_schema(
                                db,
                                organization=organization,
                                data_source=ds,
                                model=model,
                                focus=focus,
                            )
                        except Exception as e:  # noqa: BLE001 - per-source fail-soft
                            logger.warning(
                                "train_orchestrator semantic/metrics failed for %s: %s",
                                getattr(ds, "id", "?"),
                                e,
                            )
                            continue
                        sem_ids.extend((r or {}).get("semantics", []) or [])
                        met_ids.extend((r or {}).get("metrics", []) or [])
                        # Per-column meanings: only meaningful when SEMANTIC_LAYER is
                        # on. Fills blank SemanticColumn.meaning rows (pending), then
                        # we auto-approve below like every other Auto-train surface.
                        if _flags.SEMANTIC_LAYER:
                            try:
                                rc = await propose_column_meanings(
                                    db,
                                    organization=organization,
                                    data_source=ds,
                                    model=model,
                                )
                                col_ids.extend((rc or {}).get("columns", []) or [])
                            except Exception as e:  # noqa: BLE001 - per-source fail-soft
                                logger.warning(
                                    "train_orchestrator column meanings failed for %s: %s",
                                    getattr(ds, "id", "?"),
                                    e,
                                )
                            # T3: bind a sibling "Definitions" glossary onto this
                            # source's columns (parse -> fuzzy -> pending). Stays
                            # PENDING (not added to col_ids -> not auto-approved).
                            try:
                                from app.ai.knowledge.doc_extractor import (
                                    apply_definitions_to_data_source,
                                )
                                rd = await apply_definitions_to_data_source(
                                    db,
                                    organization=organization,
                                    data_source=ds,
                                    model=model,
                                )
                                def_ids.extend((rd or {}).get("columns", []) or [])
                            except Exception as e:  # noqa: BLE001 - per-source fail-soft
                                logger.warning(
                                    "train_orchestrator definitions bind failed for %s: %s",
                                    getattr(ds, "id", "?"),
                                    e,
                                )

                    # Auto-approve the fresh proposals (Auto-train auto-approves;
                    # keeps the Review queue empty and the rows live in context).
                    if sem_ids:
                        await db.execute(
                            _sql_update(SemanticTable)
                            .where(SemanticTable.id.in_(sem_ids))
                            .values(status="approved")
                        )
                    if met_ids:
                        await db.execute(
                            _sql_update(MetricDefinition)
                            .where(MetricDefinition.id.in_(met_ids))
                            .values(status="approved")
                        )
                    if col_ids:
                        await db.execute(
                            _sql_update(SemanticColumn)
                            .where(SemanticColumn.id.in_(col_ids))
                            .values(status="approved")
                        )
                    if sem_ids or met_ids or col_ids:
                        await db.commit()
                    detail["semantic_metrics"] = (
                        f"ok ({len(sem_ids)} semantic, {len(met_ids)} metrics, "
                        f"{len(col_ids)} col meanings, "
                        f"{len(def_ids)} from definitions (pending))"
                    )
                except Exception as e:  # noqa: BLE001
                    try:
                        await db.rollback()
                    except Exception:
                        pass
                    detail["semantic_metrics"] = f"error: {e}"
                _set(sid, pct=94)

            # --- Stage 5: value-overlap join mining (pct 98) ------------------
            # Proven-SQL joins need query history; value-overlap works on day 1.
            _set(sid, step="joins", pct=94)
            _log(sid, "▸ mine joins", "info")
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

            # --- Verified Goldens (P4/P5 EVAL GATE — wire pipeline INTO train) -
            # For every business definition (metric/filter/rule) carrying an
            # expected ground-truth answer, regenerate its golden SQL and eval it
            # against the live source. Save ONLY matches as approved goldens;
            # mismatches are HELD (never shipped). Reuses the doc-driven pipeline
            # services (golden_gen + eval_gate) + the route's _save_golden upsert.
            # Runs BEFORE hybrid_index so approved goldens get indexed this run.
            # No-op unless BOTH flags on (VERIFIED_GOLDENS default OFF). Fail-soft.
            try:
                from app.settings.hybrid_flags import flags as _vg_flags
                if _vg_flags.VERIFIED_GOLDENS and _vg_flags.FULL_PIPELINE:
                    _set(sid, step="verified_goldens", pct=98)
                    _log(sid, "▸ verified goldens (eval gate)", "info")
                    from app.models.agent_definition import AgentDefinition
                    from app.services.train import golden_gen as _G, eval_gate as _E
                    from app.routes.pipeline import _save_golden as _save_vg

                    _defs = (await db.execute(
                        select(AgentDefinition).where(
                            AgentDefinition.organization_id == str(organization.id),
                            AgentDefinition.deleted_at.is_(None),
                        )
                    )).scalars().all()
                    # Group each def under its own data source; defs with no pinned
                    # source fall back to the first pinned studio source.
                    _ds_ids = [str(getattr(s, "id", "")) for s in sources
                               if getattr(s, "id", None)]
                    _by_ds: dict = {}
                    for _d in _defs:
                        _k = _d.data_source_id or (_ds_ids[0] if _ds_ids else None)
                        if _k:
                            _by_ds.setdefault(str(_k), []).append(_d)
                    _appr = _held = 0
                    for _dsid, _grp in _by_ds.items():
                        _cands = await _G.generate_for_definitions(
                            db, data_source_id=_dsid, definitions=_grp)
                        _res = await _E.evaluate(
                            db, data_source_id=_dsid, candidates=_cands)
                        _byid = {str(d.id): d for d in _grp}
                        for _c in _res.get("approved", []):
                            _dd = _byid.get(_c["definition_id"])
                            if _dd is not None:
                                _dd.status = "approved"
                            await _save_vg(
                                db, organization=organization, data_source_id=_dsid,
                                name=_c["name"], sql=_c["sql"], expected=_c["expected"])
                        _appr += len(_res.get("approved", []))
                        _held += len(_res.get("held", []))
                    await db.commit()
                    detail["verified_goldens"] = f"ok ({_appr} approved, {_held} held)"
                    _log(sid, f"verified goldens: {_appr} approved, {_held} held", "info")
            except Exception as _e:  # noqa: BLE001
                try:
                    await db.rollback()
                except Exception:
                    pass
                detail["verified_goldens"] = f"error: {_e}"
                _log(sid, f"verified_goldens failed: {_e}", "warn")

            # --- Attached docs -> Knowledge (any file, any type) ---------------
            # Turn every doc-type file attached to a source (PDF/Word/PPT/text/
            # reference-xlsx) into searchable KnowledgeDoc chunks so the agent can
            # CITE them. Idempotent (content-hash dedup) + fail-soft. Runs BEFORE
            # hybrid_index so the new approved docs get embedded THIS run. No-op
            # unless HYBRID_DOC_KNOWLEDGE is on.
            try:
                from app.settings.hybrid_flags import flags as _dk_flags
                if _dk_flags.DOC_KNOWLEDGE:
                    _set(sid, step="ingest_docs", pct=98)
                    _log(sid, "▸ ingest attached docs", "info")
                    from app.services.knowledge.file_ingest import backfill_data_source_docs
                    _ing = 0
                    for ds in sources:
                        try:
                            r = await backfill_data_source_docs(
                                db, organization=organization, data_source_id=str(ds.id))
                            _ing += int((r or {}).get("ingested", 0) or 0)
                        except Exception as _de:  # noqa: BLE001 — per-source fail-soft
                            logger.warning("train_orchestrator ingest_docs failed for %s: %s",
                                           getattr(ds, "id", "?"), _de)
                    detail["ingest_docs"] = f"ok ({_ing} docs indexed)"
                    _log(sid, f"ingest attached docs: {_ing} indexed", "info")
            except Exception as _e:  # noqa: BLE001
                try:
                    await db.rollback()
                except Exception:  # noqa: BLE001
                    pass
                detail["ingest_docs"] = f"error: {_e}"
                _log(sid, f"ingest_docs failed: {_e}", "warn")

            # --- Hybrid Search auto-index (P13: wire reindex INTO training) ---
            # Approved semantic/metric/query/doc rows -> knowledge_search_index
            # (tsv + pgvector). Without this the Hybrid Search tab stays blank
            # until someone clicks "Rebuild search index". Fail-soft.
            try:
                from app.settings.hybrid_flags import flags as _hs_flags
                if _hs_flags.SEMANTIC_SEARCH or _hs_flags.FULL_PIPELINE:
                    _set(sid, step="hybrid_index", pct=99)
                    _log(sid, "▸ hybrid_index", "info")
                    from app.ai.knowledge.indexer import reindex_org
                    _summary = await reindex_org(db, organization)
                    detail["hybrid_index"] = (
                        f"ok ({_summary.get('indexed', 0)} indexed, "
                        f"{_summary.get('embedded', 0)} embedded)"
                    )
            except Exception as _e:  # noqa: BLE001
                detail["hybrid_index"] = f"error: {_e}"
                _log(sid, f"hybrid_index failed: {_e}", "warn")

            # --- Brain/Knowledge Graph (P14: wire edge-mine INTO training) ----
            # Deterministic metric/query -> table edges; auto-publish so the
            # graph tab fills AND the agent's neighbors() can traverse. Fail-soft.
            try:
                from app.settings.hybrid_flags import flags as _kg_flags
                if (_kg_flags.SEMANTIC_SEARCH or getattr(_kg_flags, "BRAIN_GRAPH", False)
                        or _kg_flags.FULL_PIPELINE):
                    _set(sid, step="brain_graph", pct=99)
                    _log(sid, "▸ brain_graph", "info")
                    from app.ai.knowledge.knowledge_graph import build_knowledge_graph
                    from sqlalchemy import text as _sql_text
                    _org_id = str(getattr(organization, "id", ""))
                    _kg = await build_knowledge_graph(db, org_id=_org_id)
                    # auto-promote draft edges so neighbors()/agent context see them
                    await db.execute(_sql_text(
                        "UPDATE brain_graph_edges SET status='published' "
                        "WHERE organization_id=:o AND status='draft'"
                    ), {"o": _org_id})
                    await db.commit()
                    detail["brain_graph"] = f"ok ({_kg.get('edges_written', 0)} edges)"
            except Exception as _e:  # noqa: BLE001
                detail["brain_graph"] = f"error: {_e}"
                _log(sid, f"brain_graph failed: {_e}", "warn")

            # --- Per-agent Auto-EDA (BI-uplift Phase 6) -----------------------
            # Profile each agent's data (computed) + narrate insights + suggested
            # questions, saved to data_sources.eda_profile and shown ONLY on that
            # agent's Overview. Per-source fail-soft. No-op unless HYBRID_AUTO_EDA.
            try:
                from app.settings.hybrid_flags import flags as _eda_flags
                if getattr(_eda_flags, "AUTO_EDA", False):
                    _set(sid, step="auto_eda", pct=99)
                    _log(sid, "▸ auto_eda", "info")
                    from app.services.analytics.agent_eda import build_agent_eda
                    _eda_ok = 0
                    for ds in sources:
                        try:
                            r = await build_agent_eda(
                                db, organization=organization, data_source=ds,
                                model=train_model)
                            if r and not r.get("error"):
                                _eda_ok += 1
                            elif r and r.get("error"):
                                _log(sid, f"  auto_eda {getattr(ds,'name','?')}: {r['error']}", "warn")
                        except Exception as _ee:  # noqa: BLE001 — per-source fail-soft
                            logger.warning("train_orchestrator auto_eda failed for %s: %s",
                                           getattr(ds, "id", "?"), _ee)
                    detail["auto_eda"] = f"ok ({_eda_ok} agents)"
                    _log(sid, f"auto_eda: {_eda_ok} agents profiled", "info")
            except Exception as _e:  # noqa: BLE001
                try:
                    await db.rollback()
                except Exception:  # noqa: BLE001
                    pass
                detail["auto_eda"] = f"error: {_e}"
                _log(sid, f"auto_eda failed: {_e}", "warn")

            # --- Per-agent KPI layer (BI-uplift Phase 3) ----------------------
            # Propose governed KPIs (outcome ratios, leading/lagging, target/
            # action) grounded on the agent's EDA profile, saved to
            # data_sources.kpi_defs, shown on the agent Overview. Runs AFTER
            # auto_eda so it can reuse the fresh profile. Per-source fail-soft.
            try:
                from app.settings.hybrid_flags import flags as _kpi_flags
                if getattr(_kpi_flags, "KPI_LAYER", False):
                    _set(sid, step="agent_kpis", pct=99)
                    _log(sid, "▸ agent_kpis", "info")
                    from app.services.analytics.agent_kpis import build_agent_kpis
                    _kpi_ok = 0
                    for ds in sources:
                        try:
                            r = await build_agent_kpis(
                                db, organization=organization, data_source=ds,
                                model=train_model)
                            if r and not r.get("error"):
                                _kpi_ok += 1
                            elif r and r.get("error"):
                                _log(sid, f"  agent_kpis {getattr(ds,'name','?')}: {r['error']}", "warn")
                        except Exception as _ke:  # noqa: BLE001 — per-source fail-soft
                            logger.warning("train_orchestrator agent_kpis failed for %s: %s",
                                           getattr(ds, "id", "?"), _ke)
                    detail["agent_kpis"] = f"ok ({_kpi_ok} agents)"
                    _log(sid, f"agent_kpis: {_kpi_ok} agents", "info")
            except Exception as _e:  # noqa: BLE001
                try:
                    await db.rollback()
                except Exception:  # noqa: BLE001
                    pass
                detail["agent_kpis"] = f"error: {_e}"
                _log(sid, f"agent_kpis failed: {_e}", "warn")

            # --- Agent Overview autofill -------------------------------------
            # Pin a primary instruction + seed conversation starters for any
            # agent whose Overview is still empty, so a freshly-trained agent
            # isn't blank ("No primary instruction / No conversation starters").
            # Fills only what's missing; never overrides a user's choice.
            # Fail-soft. No-op unless HYBRID_AUTOFILL_AGENT_OVERVIEW is on.
            try:
                from app.settings.hybrid_flags import flags as _ao_flags
                if getattr(_ao_flags, "AUTOFILL_AGENT_OVERVIEW", True):
                    _set(sid, step="agent_overview", pct=99)
                    _log(sid, "▸ agent_overview", "info")
                    from app.services.knowledge.agent_overview import autofill_agent_overview
                    _filled = 0
                    for ds in sources:
                        try:
                            r = await autofill_agent_overview(
                                db, organization=organization, data_source=ds)
                            if r and not r.get("error"):
                                _filled += 1
                        except Exception as _ae:  # noqa: BLE001 — per-source fail-soft
                            logger.warning("train_orchestrator agent_overview failed for %s: %s",
                                           getattr(ds, "id", "?"), _ae)
                    detail["agent_overview"] = f"ok ({_filled} agents)"
                    _log(sid, f"agent_overview: {_filled} agents filled", "info")
            except Exception as _e:  # noqa: BLE001
                try:
                    await db.rollback()
                except Exception:  # noqa: BLE001
                    pass
                detail["agent_overview"] = f"error: {_e}"
                _log(sid, f"agent_overview failed: {_e}", "warn")

            # --- Done ---------------------------------------------------------
            _errs = [k for k, v in detail.items()
                     if (isinstance(v, str) and v.lower().startswith("error"))
                     or (isinstance(v, dict) and v.get("ok") is False)]
            if _errs:
                _log(sid, f"finished with {len(_errs)} failed stage(s): {', '.join(_errs)}", "warn")
            else:
                _log(sid, "all stages complete — agent ready", "info")
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
        _log(sid, f"fatal: {e}", "error")
        _set(sid, status="error", step="error", error=str(e))
    finally:
        _detach_log_capture(_log_handler, _log_loggers)


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
