"""Eval canary health + drift alert - SERVICE LAYER (read-only over the eval harness).

Turns the existing nightly result-set goldens (``services/eval_harness.py``,
``models/eval.py``) into continuous canaries: per-golden eval pass-rate health +
regression-vs-last-green alerts. The nightly scheduler already RUNS the goldens
and detects regressions; this module only SURFACES that history for a health page.

Two public coroutines, both org-scoped, both flag-gated and defensive:
  * ``table_health(db, *, organization_id)``  -> per-golden pass-rate + trend.
  * ``detect_drift(db, *, organization_id)``   -> regressions (was pass, now fail).

Flag ``EVAL_CANARY`` (env ``HYBRID_EVAL_CANARY``, default OFF). OFF -> [].

Design rules (CLAUDE.md HARD RULES 3/4/5):
- Additive + flag-gated; OFF returns a safe empty default with zero DB hits.
- NEVER raises into the caller; on any failure logs a warning and returns [].
- Reads the eval models directly; imports from ``eval_harness`` are read-only
  (we reuse ``_find_result_set_golden_cases`` to scope to result-set goldens).
- ASCII only.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


def _canary_enabled() -> bool:
    """Flag gate. Fail-soft -> False so a broken flag never surfaces data."""
    try:
        from app.settings.hybrid_flags import flags

        return bool(getattr(flags, "EVAL_CANARY", False))
    except Exception:
        return False


async def _org_golden_case_ids(db: Any, org_id: str) -> List[str]:
    """The org's active result-set golden TestCase ids (reuses the harness's
    own selector so we canary exactly what the scheduler runs). [] on failure."""
    try:
        from app.services.eval_harness import _find_result_set_golden_cases

        cases = await _find_result_set_golden_cases(db, org_id=str(org_id))
        return [str(c.id) for c in (cases or []) if getattr(c, "id", None)]
    except Exception as e:
        logger.warning("canary_health._org_golden_case_ids failed: %s", e)
        return []


def _trend(last: Optional[str], prev: Optional[str]) -> str:
    """Trend of the two most-recent statuses for a golden."""
    good = {"pass"}
    if prev is None:
        return "new"
    last_ok = last in good
    prev_ok = prev in good
    if last_ok and not prev_ok:
        return "up"
    if prev_ok and not last_ok:
        return "down"
    return "flat"


async def table_health(db: Any, *, organization_id: Any) -> List[dict]:
    """Per-golden canary health for an org.

    For every active result-set golden, aggregates its recent TestResults into a
    pass-rate, last-run status/time, and a two-point trend. Returns a list of
    dicts (newest-failing first) or [] when gated off / no goldens / on failure.
    NEVER raises.

    Each dict: ``{case_id, name, data_source_ids, runs, passes, pass_rate,
    last_status, last_run_at, trend}``.
    """
    try:
        if not _canary_enabled():
            return []

        org_id = str(organization_id or "")
        if not org_id:
            return []

        case_ids = await _org_golden_case_ids(db, org_id)
        if not case_ids:
            return []

        from sqlalchemy import select
        from app.models.eval import TestCase, TestResult, TestRun

        # Pull every result for the org's goldens, ordered oldest->newest so the
        # last row per case is its most-recent run.
        rows = (
            await db.execute(
                select(
                    TestResult.case_id,
                    TestResult.status,
                    TestRun.created_at,
                    TestCase.name,
                    TestCase.data_source_ids_json,
                )
                .join(TestRun, TestRun.id == TestResult.run_id)
                .join(TestCase, TestCase.id == TestResult.case_id)
                .where(TestResult.case_id.in_(case_ids))
                .order_by(TestRun.created_at.asc())
            )
        ).all()

        # Aggregate per case.
        agg: dict = {}
        for case_id, status, created_at, name, ds_ids in rows:
            cid = str(case_id)
            a = agg.get(cid)
            if a is None:
                a = {
                    "case_id": cid,
                    "name": name or "golden",
                    "data_source_ids": ds_ids if isinstance(ds_ids, list) else [],
                    "runs": 0,
                    "passes": 0,
                    "last_status": None,
                    "prev_status": None,
                    "last_run_at": None,
                }
                agg[cid] = a
            a["runs"] += 1
            if status == "pass":
                a["passes"] += 1
            # rows are ascending -> keep shifting last->prev.
            a["prev_status"] = a["last_status"]
            a["last_status"] = status
            a["last_run_at"] = created_at.isoformat() if created_at is not None else None

        out: List[dict] = []
        for a in agg.values():
            runs = a["runs"] or 0
            pass_rate = round(a["passes"] / runs, 4) if runs else 0.0
            out.append(
                {
                    "case_id": a["case_id"],
                    "name": a["name"],
                    "data_source_ids": a["data_source_ids"],
                    "runs": runs,
                    "passes": a["passes"],
                    "pass_rate": pass_rate,
                    "last_status": a["last_status"],
                    "last_run_at": a["last_run_at"],
                    "trend": _trend(a["last_status"], a["prev_status"]),
                }
            )

        # Goldens that have never run yet still deserve a row (health = unknown).
        seen = set(agg.keys())
        missing = [c for c in case_ids if c not in seen]
        if missing:
            try:
                res = await db.execute(
                    select(TestCase.id, TestCase.name, TestCase.data_source_ids_json).where(
                        TestCase.id.in_(missing)
                    )
                )
                for cid, name, ds_ids in res.all():
                    out.append(
                        {
                            "case_id": str(cid),
                            "name": name or "golden",
                            "data_source_ids": ds_ids if isinstance(ds_ids, list) else [],
                            "runs": 0,
                            "passes": 0,
                            "pass_rate": 0.0,
                            "last_status": None,
                            "last_run_at": None,
                            "trend": "new",
                        }
                    )
            except Exception:
                pass

        # Failing / lowest pass-rate first so the page leads with problems.
        _rank = {"down": 0, "flat": 1, "new": 2, "up": 3}
        out.sort(key=lambda r: (_rank.get(r["trend"], 4), r["pass_rate"]))
        return out
    except Exception as e:
        logger.warning("canary_health.table_health failed: %s", e)
        return []


async def _org_run_ids_desc(db: Any, case_ids: List[str]) -> List[Any]:
    """Distinct TestRuns that touched the org's goldens, newest first. Each
    element is ``(run_id, status)``. [] on failure."""
    try:
        from sqlalchemy import select
        from app.models.eval import TestResult, TestRun

        res = await db.execute(
            select(TestRun.id, TestRun.status, TestRun.created_at)
            .join(TestResult, TestResult.run_id == TestRun.id)
            .where(TestResult.case_id.in_(case_ids))
            .group_by(TestRun.id, TestRun.status, TestRun.created_at)
            .order_by(TestRun.created_at.desc())
        )
        return [(str(rid), status) for rid, status, _created in res.all()]
    except Exception:
        return []


async def _status_by_case(db: Any, run_id: str, case_ids: List[str]) -> dict:
    """case_id -> status for one run, restricted to the org's goldens."""
    try:
        from sqlalchemy import select
        from app.models.eval import TestResult

        res = await db.execute(
            select(TestResult.case_id, TestResult.status).where(
                TestResult.run_id == str(run_id),
                TestResult.case_id.in_(case_ids),
            )
        )
        return {str(cid): st for cid, st in res.all() if cid is not None}
    except Exception:
        return {}


async def detect_drift(db: Any, *, organization_id: Any) -> List[dict]:
    """Read-only regression-vs-last-green for an org's goldens.

    Compares the latest run touching the org's goldens against the most-recent
    prior ``success`` run and surfaces cases that were ``pass`` and are now
    ``fail``/``error``. Mirrors ``eval_harness.detect_regressions`` but performs
    NO writes. Returns alert dicts or [] when gated off / no history / on
    failure. NEVER raises.

    Each dict: ``{case_id, case_name, prev_status, now_status, run_id,
    prev_run_id}``.
    """
    try:
        if not _canary_enabled():
            return []

        org_id = str(organization_id or "")
        if not org_id:
            return []

        case_ids = await _org_golden_case_ids(db, org_id)
        if not case_ids:
            return []

        runs = await _org_run_ids_desc(db, case_ids)
        if not runs:
            return []

        latest_id, _latest_status = runs[0]
        # Last green = most-recent successful run strictly before the latest.
        prev_id = None
        for rid, status in runs[1:]:
            if status == "success":
                prev_id = rid
                break
        if prev_id is None:
            return []

        now_status = await _status_by_case(db, latest_id, case_ids)
        prev_status = await _status_by_case(db, prev_id, case_ids)
        if not now_status or not prev_status:
            return []

        # Resolve names for the cases that regressed.
        regressed = [
            (cid, prev_status.get(cid), st)
            for cid, st in now_status.items()
            if prev_status.get(cid) == "pass" and st in ("fail", "error")
        ]
        if not regressed:
            return []

        name_by_case: dict = {}
        try:
            from sqlalchemy import select
            from app.models.eval import TestCase

            res = await db.execute(
                select(TestCase.id, TestCase.name).where(
                    TestCase.id.in_([cid for cid, _p, _n in regressed])
                )
            )
            name_by_case = {str(cid): cname for cid, cname in res.all()}
        except Exception:
            pass

        return [
            {
                "case_id": cid,
                "case_name": name_by_case.get(cid),
                "prev_status": prev,
                "now_status": now,
                "run_id": latest_id,
                "prev_run_id": prev_id,
            }
            for cid, prev, now in regressed
        ]
    except Exception as e:
        logger.warning("canary_health.detect_drift failed: %s", e)
        return []
