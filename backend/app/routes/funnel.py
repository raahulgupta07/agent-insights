"""Read-only serving-funnel stats endpoint (hybrid-brain cache-hit metric).

Reports how many successful completions were answered by each serving tier
(reasoning_cache / answer_cache / materialized / agent_loop) plus latency
percentiles. Used to observe cache-hit rate of the serving funnel.

The pure helper ``compute_funnel_stats`` carries no heavy imports so it can be
unit-tested standalone. All FastAPI / SQLAlchemy / model imports live at module
top only as needed by the endpoint; the helper itself uses none of them.
"""

# --- Pure, dependency-free helper (unit-testable, no DB / FastAPI) ----------

_TIERS = ("reasoning_cache", "answer_cache", "materialized", "agent_loop")


def _percentile(sorted_vals, pct):
    """Linear-interpolation percentile over a sorted list. pct in [0,100].

    Returns None for an empty list. Deterministic.
    """
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    rank = (pct / 100.0) * (len(sorted_vals) - 1)
    low = int(rank)
    high = min(low + 1, len(sorted_vals) - 1)
    frac = rank - low
    return sorted_vals[low] + (sorted_vals[high] - sorted_vals[low]) * frac


def _norm_tier(served_by):
    """Map a served_by value to a known tier; NULL/empty/unknown -> agent_loop."""
    if not served_by:
        return "agent_loop"
    s = str(served_by).strip()
    if s in _TIERS:
        return s
    return "agent_loop"


def _coerce_ms(value):
    """Return an int millisecond value, or None if not a usable number."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def compute_funnel_stats(rows):
    """rows: [{'served_by': str|None, 'elapsed_ms': int|None, 'status': str}].

    Returns funnel cache-hit + latency stats over success rows only.
    """
    by_tier = {t: 0 for t in _TIERS}
    all_ms = []
    cache_ms = []
    cold_ms = []
    total = 0

    for row in rows or []:
        try:
            status = row.get("status")
        except AttributeError:
            continue
        if status != "success":
            continue
        total += 1

        tier = _norm_tier(row.get("served_by"))
        by_tier[tier] += 1

        ms = _coerce_ms(row.get("elapsed_ms"))
        if ms is not None:
            all_ms.append(ms)
            if tier == "agent_loop":
                cold_ms.append(ms)
            else:
                cache_ms.append(ms)

    cache_hit = sum(by_tier[t] for t in _TIERS if t != "agent_loop")
    cache_hit_rate = round(cache_hit / total, 4) if total else 0.0

    all_ms.sort()
    cache_ms.sort()
    cold_ms.sort()

    def _p(vals, pct):
        v = _percentile(vals, pct)
        return int(round(v)) if v is not None else None

    return {
        "total": total,
        "by_tier": by_tier,
        "cache_hit": cache_hit,
        "cache_hit_rate": cache_hit_rate,
        "p50_ms": _p(all_ms, 50),
        "p95_ms": _p(all_ms, 95),
        "p50_cache_ms": _p(cache_ms, 50),
        "p50_cold_ms": _p(cold_ms, 50),
    }


def _empty_stats():
    return {
        "total": 0,
        "by_tier": {t: 0 for t in _TIERS},
        "cache_hit": 0,
        "cache_hit_rate": 0.0,
        "p50_ms": None,
        "p95_ms": None,
        "p50_cache_ms": None,
        "p50_cold_ms": None,
    }


# --- Endpoint -----------------------------------------------------------------
# Heavy imports (FastAPI / SQLAlchemy / models / auth) are deferred into
# _register_routes() so that importing this module for the pure helper above
# does NOT require the full app dependency tree (e.g. fastapi_users). The
# router is built at import time via _register_routes(); if those deps are
# unavailable (bare unit-test env) the module still imports with router=None.

router = None


def _register_routes():
    global router
    from datetime import datetime, timedelta
    from fastapi import APIRouter, Depends
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.dependencies import get_async_db, get_current_organization
    from app.models.user import User
    from app.models.organization import Organization
    from app.models.completion import Completion
    from app.models.report import Report
    from app.core.auth import current_user
    from app.core.permissions_decorator import requires_permission
    from app.settings.logging_config import get_logger

    logger = get_logger(__name__)
    router = APIRouter(tags=["funnel"])

    @router.get("/funnel/stats")
    @requires_permission('manage_settings')
    async def funnel_stats(
        days: int = 7,
        db: AsyncSession = Depends(get_async_db),
        organization: Organization = Depends(get_current_organization),
        current_user: User = Depends(current_user),
    ):
        """Serving-funnel cache-hit + latency stats over the last `days`.

        Completion has no organization_id; it is scoped to the org by joining
        Report (Report.organization_id), matching how completion.py resolves org.
        """
        cutoff = datetime.utcnow() - timedelta(days=days)
        try:
            stmt = (
                select(
                    Completion.served_by,
                    Completion.elapsed_ms,
                    Completion.status,
                )
                .join(Report, Completion.report_id == Report.id)
                .where(
                    Report.organization_id == organization.id,
                    Completion.status == "success",
                    Completion.created_at >= cutoff,
                )
            )
            result = await db.execute(stmt)
            rows = [
                {"served_by": served_by, "elapsed_ms": elapsed_ms, "status": status}
                for served_by, elapsed_ms, status in result.all()
            ]
            stats = compute_funnel_stats(rows)
        except Exception as e:  # defensive: never 500 on a stats read
            logger.error("funnel_stats: failed to compute funnel stats: %s", e)
            stats = _empty_stats()

        return {**stats, "days": days, "cutoff": cutoff.isoformat()}


# Build the router at import time. In the full app this succeeds; in a bare
# unit-test env that lacks the app dependency tree it fails softly and leaves
# router = None (the pure helper above remains importable either way).
try:
    _register_routes()
except Exception:  # pragma: no cover - import-environment dependent
    router = None
