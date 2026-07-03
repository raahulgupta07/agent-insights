"""Phase-4 eval harness (result-set goldens) - SERVICE LAYER.

This module is the headless, dependency-light harness behind the Phase-4
"result-set golden" eval feature. A result-set golden is a ``TestCase`` with
``auto_generated=True``, ``source_completion_id`` set, and an
``expectations_json`` carrying exactly one ``result_set`` rule (the
``ResultSetRule`` JSON shape):

    {"type": "result_set", "golden_data": [{col: val, ...}], "golden_columns": [...],
     "tolerance": 0.0, "order_insensitive": true, "key_columns": null}

The produced rows are captured into the eval snapshot under
``snapshot["create_data"]["rows"]`` by the matcher agent.

Callers (all written by OTHER agents) ``from app.services.eval_harness import <fn>``:
  (a) the nightly scheduler            -> ``run_scheduled_evals``
  (b) the knowledge-approve hook       -> ``enqueue_context_change_run``
  (c) the thumbs-up save-as-golden hook       -> ``save_completion_as_golden``
  (d) a FE route                       -> any of the above

Flags (``app/settings/hybrid_flags.py``), both default OFF:
  * ``EVAL_HARNESS``           (env ``HYBRID_EVAL_HARNESS``) - matcher + UI + write hooks.
  * ``EVAL_SCHEDULE_ENABLED``  (env ``EVAL_SCHEDULE_ENABLED``) - nightly daemon.

Design rules honored (CLAUDE.md HARD RULES 3/4/5):
- Everything additive + flag-gated; default OFF -> no DB writes, safe defaults.
- Every public coroutine is defensive: it NEVER raises into the caller. On any
  failure it logs a warning and returns a safe default (None / []).
- ASCII only. Reuses existing services (TestRunService headless executor,
  TestEvaluationService snapshot builder) rather than duplicating logic.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


# Default per-org test suite that collects thumbs-up-blessed result-set goldens.
DEFAULT_GOLDEN_SUITE_NAME = "Blessed goldens"

# Cap on how many golden rows we persist into a rule (keeps expectations_json
# bounded - a result set with thousands of rows is not a useful golden).
_DEFAULT_ROW_CAP = 200


async def make_result_set_rule_from_snapshot(
    snapshot: dict,
    *,
    tolerance: float = 0.0,
    cap: int = _DEFAULT_ROW_CAP,
) -> Optional[dict]:
    """Build a ``ResultSetRule`` JSON dict from an eval snapshot's create_data.

    Reads ``snapshot["create_data"]["rows"]`` / ``["columns"]`` (the matcher
    agent captures the produced rows here). Returns ``None`` when there are no
    rows. Pure / never raises.
    """
    try:
        cd = snapshot.get("create_data") or {}
        if not isinstance(cd, dict):
            return None
        rows = cd.get("rows") or []
        cols = cd.get("columns") or []
        if not isinstance(rows, list) or not rows:
            return None
        if not isinstance(cols, list):
            cols = []
        try:
            row_cap = int(cap)
        except Exception:
            row_cap = _DEFAULT_ROW_CAP
        if row_cap <= 0:
            row_cap = _DEFAULT_ROW_CAP
        try:
            tol = float(tolerance)
        except Exception:
            tol = 0.0
        return {
            "type": "result_set",
            "golden_data": rows[:row_cap],
            "golden_columns": cols,
            "tolerance": tol,
            "order_insensitive": True,
            "key_columns": None,
        }
    except Exception as e:
        logger.warning("make_result_set_rule_from_snapshot failed: %s", e)
        return None


async def _resolve_report_data_source_ids(db: Any, report_id: Any) -> List[str]:
    """Collect every DataSource id linked to a report (report.data_sources).

    Mirrors ``knowledge_proposer._resolve_data_source_id`` but returns the full
    list (a golden may legitimately span >1 source). Guarded -> [] on failure.
    """
    try:
        if not report_id:
            return []
        from app.models.report import Report

        report = await db.get(Report, str(report_id))
        if report is None:
            return []
        out: List[str] = []
        for ds in getattr(report, "data_sources", None) or []:
            ds_id = getattr(ds, "id", None)
            if ds_id:
                out.append(str(ds_id))
        return out
    except Exception:
        return []


async def _resolve_question_text(db: Any, completion: Any) -> str:
    """Resolve the question text for a (system) completion.

    dash splits a turn into a user row (``prompt``) + a system row
    (``completion``). Prefer the distiller's ``gather_feedback_context`` (which
    resolves the paired sibling); fall back to the parent user row's
    ``prompt['content']``. Never raises -> '' on failure.
    """
    # 1. Reuse the existing paired-sibling resolver.
    try:
        from app.ai.brain.distiller import gather_feedback_context

        ctx = await gather_feedback_context(db, completion)
        q = (ctx or {}).get("question") or ""
        if isinstance(q, str) and q.strip():
            return q.strip()
    except Exception:
        pass

    # 2. Fallback: this row's own prompt, then its parent user row's prompt.
    try:
        from app.models.completion import Completion

        for cand in (completion, None):
            obj = cand
            if obj is None:
                parent_id = getattr(completion, "parent_id", None)
                if not parent_id:
                    break
                obj = await db.get(Completion, str(parent_id))
                if obj is None:
                    break
            pj = getattr(obj, "prompt", None)
            if isinstance(pj, dict):
                content = pj.get("content")
                if isinstance(content, str) and content.strip():
                    return content.strip()
    except Exception:
        pass
    return ""


async def _find_or_create_suite(db: Any, *, org_id: str, name: str) -> Optional[Any]:
    """Find (or create) the org-scoped TestSuite named ``name``. None on error."""
    try:
        from sqlalchemy import select
        from app.models.eval import TestSuite

        res = await db.execute(
            select(TestSuite).where(
                TestSuite.organization_id == str(org_id),
                TestSuite.name == name,
            )
        )
        suite = res.scalars().first()
        if suite is not None:
            return suite
        suite = TestSuite(organization_id=str(org_id), name=name)
        db.add(suite)
        await db.flush()
        return suite
    except Exception as e:
        logger.warning("_find_or_create_suite failed: %s", e)
        return None


async def save_completion_as_golden(
    db: Any,
    *,
    organization: Any,
    user: Any,
    completion: Any,
    suite_name: str = DEFAULT_GOLDEN_SUITE_NAME,
) -> Optional[str]:
    """Bless a thumbs-up'd completion's produced rows as a result-set golden TestCase.

    Returns the (existing or new) TestCase id, or ``None`` when gated off / no
    report / no rows / on any failure. NEVER raises.
    """
    try:
        from app.settings.hybrid_flags import flags

        if not flags.EVAL_HARNESS:
            return None

        org_id = str(getattr(organization, "id", None) or "")
        if not org_id:
            return None

        report_id = getattr(completion, "report_id", None)
        if not report_id:
            return None

        # 1. Build the snapshot for the completion's report; extract blessed rows.
        from app.services.test_evaluation_service import TestEvaluationService

        snapshot = await TestEvaluationService().build_final_snapshot(db, str(report_id))
        rule = await make_result_set_rule_from_snapshot(snapshot or {})
        if rule is None:
            return None

        # 2. Resolve the question text (sibling user row).
        question = await _resolve_question_text(db, completion)
        name = (question[:120] if question else "") or "blessed golden"

        # 3. Dedup by source_completion_id (idempotent re-bless).
        from sqlalchemy import select
        from app.models.eval import TestCase, TestSuite

        existing = (
            await db.execute(
                select(TestCase.id)
                .join(TestSuite, TestSuite.id == TestCase.suite_id)
                .where(TestSuite.organization_id == org_id)
                .where(TestCase.source_completion_id == str(getattr(completion, "id", "")))
                .where(TestCase.deleted_at.is_(None))
                .limit(1)
            )
        ).first()
        if existing is not None:
            return str(existing[0])

        # 4. Find-or-create the org-scoped goldens suite.
        suite = await _find_or_create_suite(db, org_id=org_id, name=suite_name)
        if suite is None:
            return None

        # 5. Resolve data sources + mode, build the case.
        ds_ids = await _resolve_report_data_source_ids(db, report_id)
        mode = getattr(completion, "mode", None) or "default"

        case = TestCase(
            suite_id=str(suite.id),
            name=name,
            prompt_json={"content": question, "mode": mode},
            expectations_json={
                "spec_version": 1,
                "rules": [rule],
                "order_mode": "flexible",
            },
            data_source_ids_json=ds_ids,
            status="active",
            auto_generated=True,
            source_completion_id=str(getattr(completion, "id", "")) or None,
        )
        db.add(case)
        await db.commit()
        await db.refresh(case)

        # Safety/reliability judges (flag-gated, fail-soft, log-only). Runs on the
        # blessed answer so a thumbs-up'd golden also gets a SECURITY/GOVERNANCE/
        # BOUNDARIES/ROUTING pass. NEVER blocks the golden save.
        try:
            from app.services.evals.safety_evals import maybe_run_safety

            answer_text = ""
            comp_json = getattr(completion, "completion", None)
            if isinstance(comp_json, dict):
                answer_text = str(comp_json.get("content") or "")
            await maybe_run_safety(
                db,
                organization=organization,
                completion_or_answer_text=answer_text,
                question=question,
                allowed_data_source_ids=ds_ids,
                context="golden-save",
            )
        except Exception:
            pass

        return str(case.id)
    except Exception as e:
        logger.warning("save_completion_as_golden failed: %s", e)
        try:
            await db.rollback()
        except Exception:
            pass
        return None


async def _find_result_set_golden_cases(
    db: Any,
    *,
    org_id: str,
    data_source_id: Optional[str] = None,
) -> List[Any]:
    """Return active TestCases (org-scoped) that carry a result_set rule.

    Optionally narrowed to cases whose ``data_source_ids_json`` mentions
    ``data_source_id`` (coarse JSON-substring filter, portable across
    SQLite/Postgres). Guarded -> [] on failure.
    """
    try:
        from sqlalchemy import cast, select, String as SAString
        from app.models.eval import TestCase, TestSuite

        stmt = (
            select(TestCase)
            .join(TestSuite, TestSuite.id == TestCase.suite_id)
            .where(TestSuite.organization_id == str(org_id))
            .where(TestCase.status == "active")
            .where(TestCase.auto_generated == True)  # noqa: E712
            .where(TestCase.deleted_at.is_(None))
        )
        if data_source_id:
            stmt = stmt.where(
                cast(TestCase.data_source_ids_json, SAString).ilike(f"%{data_source_id}%")
            )
        rows = (await db.execute(stmt)).scalars().all()

        out: List[Any] = []
        for case in rows:
            spec = case.expectations_json or {}
            rules = spec.get("rules") if isinstance(spec, dict) else None
            if not isinstance(rules, list):
                continue
            if any(isinstance(r, dict) and r.get("type") == "result_set" for r in rules):
                out.append(case)
        return out
    except Exception as e:
        logger.warning("_find_result_set_golden_cases failed: %s", e)
        return []


async def enqueue_context_change_run(
    db: Any,
    *,
    organization: Any,
    user: Any,
    data_source_id: str,
) -> Optional[str]:
    """On a knowledge/context change, re-run the affected result-set goldens.

    Finds active result_set goldens for this org touching ``data_source_id`` and
    kicks off a headless TestRun (trigger_reason='context_change') that EXECUTES
    the analyst in the background. Returns the run id, or ``None`` when gated off
    / no matching cases / on any failure. NEVER raises.
    """
    try:
        from app.settings.hybrid_flags import flags

        if not flags.EVAL_HARNESS:
            return None

        org_id = str(getattr(organization, "id", None) or "")
        if not org_id or not data_source_id:
            return None

        cases = await _find_result_set_golden_cases(
            db, org_id=org_id, data_source_id=str(data_source_id)
        )
        if not cases:
            return None

        from app.services.test_run_service import TestRunService

        run, _results = await TestRunService().create_and_execute_background(
            db,
            organization,
            user,
            case_ids=[str(c.id) for c in cases],
            trigger_reason="context_change",
        )
        return str(run.id) if run is not None else None
    except Exception as e:
        logger.warning("enqueue_context_change_run failed: %s", e)
        return None


async def _resolve_org_member_user(session: Any, org_id: str) -> Optional[Any]:
    """Resolve any member User of an org (the scheduler has no request user).

    The headless executor needs a ``current_user`` (it stamps
    ``requested_by_user_id`` and the stub report's ``user_id``). Pick the first
    membership's user. Guarded -> None.
    """
    try:
        from sqlalchemy import select
        from app.models.membership import Membership
        from app.models.user import User

        res = await session.execute(
            select(Membership.user_id).where(Membership.organization_id == str(org_id)).limit(1)
        )
        row = res.first()
        if not row or not row[0]:
            return None
        return await session.get(User, str(row[0]))
    except Exception:
        return None


async def _await_and_finalize_run(
    svc: Any,
    session: Any,
    organization: Any,
    user: Any,
    run: Any,
    *,
    timeout_s: float = 900.0,
    poll_s: float = 3.0,
) -> None:
    """Path-1 gap closer for the harness: ``create_and_execute_background`` runs
    the analyst but never finalizes TestResults (only ``stream_run`` did). Poll the
    run's system COMPLETIONS until terminal, then call ``finalize_run_results`` so
    ``detect_regressions`` reads real pass/fail instead of in_progress. NEVER raises.
    """
    try:
        import asyncio as _asyncio
        import time as _time
        from sqlalchemy import select as _select
        from app.models.eval import TestResult as _TR
        from app.models.completion import Completion as _C

        if run is None:
            return
        deadline = _time.monotonic() + float(timeout_s)
        while True:
            try:
                rows = list((await session.execute(
                    _select(_TR).where(_TR.run_id == str(run.id))
                    .execution_options(populate_existing=True)
                )).scalars().all())
                all_done = bool(rows)
                for r in rows:
                    head_id = getattr(r, "head_completion_id", None)
                    if not head_id:
                        all_done = False
                        break
                    head = (await session.execute(
                        _select(_C).where(_C.id == str(head_id))
                        .execution_options(populate_existing=True)
                    )).scalar_one_or_none()
                    if head is None:
                        all_done = False
                        break
                    sys_c = (await session.execute(
                        _select(_C).where(
                            _C.report_id == str(head.report_id),
                            _C.parent_id == str(head.id),
                            _C.role == "system",
                        ).order_by(_C.created_at.desc()).limit(1)
                        .execution_options(populate_existing=True)
                    )).scalar_one_or_none()
                    if sys_c is None or getattr(sys_c, "status", "") not in ("success", "error", "stopped"):
                        all_done = False
                        break
                if all_done:
                    break
            except Exception:
                break
            if _time.monotonic() >= deadline:
                break
            await _asyncio.sleep(poll_s)

        # Score whatever completed (idempotent; skips already-terminal rows).
        try:
            await svc.finalize_run_results(session, organization, user, str(run.id))
        except Exception:
            pass
    except Exception:
        pass


async def run_scheduled_evals() -> Optional[str]:
    """Nightly scheduler entry: re-run every org's result-set goldens.

    Has NO request session / org - opens its own session. For each org that owns
    at least one active auto_generated result_set golden, kicks off a headless
    TestRun (trigger_reason='schedule') and then runs regression detection on it.
    Returns a short summary string, or ``None`` when gated off / on any failure.
    NEVER raises (logs instead).
    """
    try:
        from app.settings.hybrid_flags import flags

        if not flags.EVAL_SCHEDULE_ENABLED:
            return None

        from app.settings.database import create_async_session_factory

        async_session = create_async_session_factory()

        runs_started = 0
        orgs_processed = 0

        async with async_session() as session:
            # Discover orgs that own at least one result_set golden.
            from sqlalchemy import select
            from app.models.eval import TestCase, TestSuite

            org_rows = (
                await session.execute(
                    select(TestSuite.organization_id)
                    .join(TestCase, TestCase.suite_id == TestSuite.id)
                    .where(TestCase.status == "active")
                    .where(TestCase.auto_generated == True)  # noqa: E712
                    .where(TestCase.deleted_at.is_(None))
                    .distinct()
                )
            ).all()
            org_ids = [str(r[0]) for r in org_rows if r and r[0]]

            from app.models.organization import Organization as _Org
            from app.services.test_run_service import TestRunService

            svc = TestRunService()

            for org_id in org_ids:
                try:
                    organization = await session.get(_Org, org_id)
                    if organization is None:
                        continue
                    cases = await _find_result_set_golden_cases(session, org_id=org_id)
                    if not cases:
                        continue
                    user = await _resolve_org_member_user(session, org_id)
                    # The stub-report path needs a real user id; skip if none.
                    if user is None:
                        logger.warning(
                            "run_scheduled_evals: org %s has goldens but no member user; skipping",
                            org_id,
                        )
                        continue
                    orgs_processed += 1
                    run, _results = await svc.create_and_execute_background(
                        session,
                        organization,
                        user,
                        case_ids=[str(c.id) for c in cases],
                        trigger_reason="schedule",
                    )
                    runs_started += 1
                    # Path 1 doesn't finalize -> wait for completions + score the
                    # run so regression detection reads real pass/fail (not in_progress).
                    await _await_and_finalize_run(svc, session, organization, user, run)
                    # Regression detection (compares against last green run).
                    try:
                        await detect_regressions(session, run=run)
                    except Exception:
                        pass
                except Exception as inner:
                    logger.warning(
                        "run_scheduled_evals: org %s failed: %s", org_id, inner
                    )
                    try:
                        await session.rollback()
                    except Exception:
                        pass
                    continue

        return (
            f"scheduled_evals: started {runs_started} run(s) across "
            f"{orgs_processed} org(s)"
        )
    except Exception as e:
        logger.warning("run_scheduled_evals failed: %s", e)
        return None


async def detect_regressions(db: Any, *, run: Any) -> list:
    """Compare a just-created/finished run against the last green run for the
    same suite_ids and surface regressions (was pass, now fail/error).

    Writes the regression list into ``run.summary_json['regressions']`` (merged,
    not clobbered) and commits. Returns the list of
    ``{case_id, case_name, prev_status, now_status}`` dicts. NEVER raises; there
    is no notifications table in this codebase (dash), so the FE reads the banner
    straight from ``run.summary_json['regressions']``.
    """
    try:
        if run is None:
            return []
        from sqlalchemy import select
        from app.models.eval import TestRun, TestResult, TestCase

        suite_ids = getattr(run, "suite_ids", "") or ""

        # Find the previous successful run with the SAME suite_ids string. The
        # suite_ids column is a sorted comma-string, so equality is a clean key.
        prev = (
            await db.execute(
                select(TestRun)
                .where(TestRun.id != str(run.id))
                .where(TestRun.suite_ids == suite_ids)
                .where(TestRun.status == "success")
                .order_by(TestRun.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        regressions: list = []

        if prev is not None:
            # Map case_id -> status for both runs.
            async def _status_by_case(run_id: str) -> dict:
                res = await db.execute(
                    select(TestResult.case_id, TestResult.status).where(
                        TestResult.run_id == str(run_id)
                    )
                )
                out: dict = {}
                for cid, st in res.all():
                    if cid is not None:
                        out[str(cid)] = st
                return out

            prev_status = await _status_by_case(str(prev.id))
            now_status = await _status_by_case(str(run.id))

            regressed_ids = []
            for cid, now_st in now_status.items():
                was = prev_status.get(cid)
                if was == "pass" and now_st in ("fail", "error"):
                    regressed_ids.append((cid, was, now_st))

            # Resolve case names for the banner.
            name_by_case: dict = {}
            if regressed_ids:
                try:
                    res = await db.execute(
                        select(TestCase.id, TestCase.name).where(
                            TestCase.id.in_([cid for cid, _w, _n in regressed_ids])
                        )
                    )
                    for cid, cname in res.all():
                        name_by_case[str(cid)] = cname
                except Exception:
                    pass

            for cid, was, now_st in regressed_ids:
                regressions.append(
                    {
                        "case_id": cid,
                        "case_name": name_by_case.get(cid),
                        "prev_status": was,
                        "now_status": now_st,
                    }
                )

        # Merge into summary_json without clobbering existing keys.
        try:
            existing = run.summary_json
            if not isinstance(existing, dict):
                existing = {}
            merged = dict(existing)
            merged["regressions"] = regressions
            run.summary_json = merged
            # JSON dict in-place reassign may not flag dirty if identity is
            # unchanged - assigning a NEW dict above is enough, but flag to be safe.
            try:
                from sqlalchemy.orm.attributes import flag_modified

                flag_modified(run, "summary_json")
            except Exception:
                pass
            db.add(run)
            await db.commit()
        except Exception as commit_err:
            logger.warning("detect_regressions commit failed: %s", commit_err)
            try:
                await db.rollback()
            except Exception:
                pass

        return regressions
    except Exception as e:
        logger.warning("detect_regressions failed: %s", e)
        return []
