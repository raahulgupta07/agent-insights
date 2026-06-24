"""
Per-org quota guard (Phase 9, work unit C)
==========================================

A pure, flag-gated check that answers: is this organization over its monthly
usage quota? Reuses the EXISTING usage models (no new tables):

- ``UsagePolicy`` (app/models/usage_policy.py) — per-org limits
  (``monthly_token_limit`` / ``monthly_query_limit`` / ``monthly_data_bytes_limit``).
- ``UsageCounter`` — windowed per-(org,user,metric) usage rows; we SUM the
  org's rows for the current calendar-month window.

Metric naming is reused verbatim from ``app.services.usage_policy_service``:
``llm_tokens`` / ``data_queries`` / ``data_bytes``.

Design rules honored (mirrors app/ai/skills/loader.py):
- Gated by ``flags.QUOTAS``. When the flag is OFF the guard ALWAYS allows —
  a fresh deploy behaves exactly like upstream dash.
- Side-effect-light + FAIL-OPEN: any DB/import error degrades to ``allowed=True``
  so a quota bug can never block real traffic.
- Heavy imports (models, sqlalchemy, settings helpers) are kept LOCAL to the
  functions so importing this module stays light (and py3.9-friendly).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# Metric string values — reused verbatim from app.services.usage_policy_service
# (METRIC_LLM_TOKENS / METRIC_DATA_QUERIES / METRIC_DATA_BYTES). Duplicated here
# as plain literals so the pure logic stays import-light.
METRIC_TOKENS = "llm_tokens"
METRIC_QUERIES = "data_queries"
METRIC_DATA_BYTES = "data_bytes"

# Maps each metric to the matching column name on UsagePolicy.
_METRIC_TO_LIMIT_FIELD = {
    METRIC_TOKENS: "monthly_token_limit",
    METRIC_QUERIES: "monthly_query_limit",
    METRIC_DATA_BYTES: "monthly_data_bytes_limit",
}

# All metrics we know how to evaluate, checked in this order when metric=None.
ALL_METRICS = (METRIC_TOKENS, METRIC_QUERIES, METRIC_DATA_BYTES)


@dataclass
class QuotaStatus:
    allowed: bool
    metric: Optional[str] = None
    limit: Optional[int] = None
    used: Optional[int] = None
    reason: Optional[str] = None


def _evaluate(
    policy_dict: Optional[Dict[str, Any]],
    used_by_metric: Dict[str, int],
    metric: Optional[str] = None,
) -> QuotaStatus:
    """Pure comparison core. No DB, no imports — exhaustively unit-tested.

    ``policy_dict`` carries the limit columns (may be ``None`` for unlimited).
    ``used_by_metric`` maps metric-string -> used amount.
    ``metric`` selects a single metric, or ``None`` to check all of them.
    """
    if policy_dict is None:
        return QuotaStatus(allowed=True, reason="no_policy")

    metrics = (metric,) if metric is not None else ALL_METRICS

    for m in metrics:
        limit_field = _METRIC_TO_LIMIT_FIELD.get(m)
        if limit_field is None:
            # Unknown metric — nothing to enforce.
            continue
        limit = policy_dict.get(limit_field)
        # NULL or 0 (falsy) limit means unlimited for that metric.
        if not limit:
            continue
        used = int(used_by_metric.get(m, 0) or 0)
        if used >= int(limit):
            return QuotaStatus(
                allowed=False,
                metric=m,
                limit=int(limit),
                used=used,
                reason="{field} exceeded ({used}/{limit})".format(
                    field=limit_field, used=used, limit=int(limit)
                ),
            )

    # Nothing breached. Report the single-metric figures when one was requested.
    if metric is not None:
        limit_field = _METRIC_TO_LIMIT_FIELD.get(metric)
        limit = policy_dict.get(limit_field) if limit_field else None
        return QuotaStatus(
            allowed=True,
            metric=metric,
            limit=int(limit) if limit else None,
            used=int(used_by_metric.get(metric, 0) or 0),
            reason="within_quota",
        )
    return QuotaStatus(allowed=True, reason="within_quota")


async def check_org_quota(
    db: Any,
    *,
    organization_id: str,
    metric: Optional[str] = None,
) -> QuotaStatus:
    """Return whether ``organization_id`` is within its monthly quota.

    FAIL-OPEN: on flag-off, missing policy, or any error -> ``allowed=True``.
    """
    # Flag-gated: imported locally so this module stays cheap to import.
    try:
        from app.settings.hybrid_flags import flags
    except Exception:  # pragma: no cover - defensive import guard
        return QuotaStatus(allowed=True, reason="quotas_disabled")

    if not flags.QUOTAS:
        return QuotaStatus(allowed=True, reason="quotas_disabled")

    try:
        from sqlalchemy import func, select

        from app.models.usage_policy import UsageCounter, UsagePolicy
        from app.services.usage_policy_service import current_month_window

        # One enabled policy row per org (model enforces uq on org+name; we take
        # the strictest/first enabled one).
        policy_result = await db.execute(
            select(UsagePolicy).where(
                UsagePolicy.organization_id == organization_id,
                UsagePolicy.enabled == True,  # noqa: E712 - SQLAlchemy needs ==
            )
        )
        policy = policy_result.scalars().first()
        if policy is None:
            return QuotaStatus(allowed=True, reason="no_policy")

        policy_dict = {
            "monthly_token_limit": policy.monthly_token_limit,
            "monthly_query_limit": policy.monthly_query_limit,
            "monthly_data_bytes_limit": policy.monthly_data_bytes_limit,
        }

        window_start, _window_end = current_month_window()

        # Sum org-wide usage per metric for the current window (across all users
        # and scopes — this is an ORG quota).
        metrics_to_load = (metric,) if metric is not None else ALL_METRICS
        used_by_metric: Dict[str, int] = {}
        used_result = await db.execute(
            select(
                UsageCounter.metric,
                func.coalesce(func.sum(UsageCounter.used), 0),
            )
            .where(
                UsageCounter.organization_id == organization_id,
                UsageCounter.window_start == window_start,
                UsageCounter.metric.in_(list(metrics_to_load)),
            )
            .group_by(UsageCounter.metric)
        )
        for row in used_result.all():
            used_by_metric[row[0]] = int(row[1] or 0)

        return _evaluate(policy_dict, used_by_metric, metric)
    except Exception as exc:  # FAIL-OPEN: never block real traffic on a quota bug.
        logger.warning("quota check failed, failing open: %s", exc)
        return QuotaStatus(allowed=True, reason="quota_check_error:{0}".format(exc))


def quota_exceeded_error(status: QuotaStatus) -> "Any":
    """Build an AppError(429) for callers that prefer to raise on a breach."""
    from app.errors.app_error import AppError

    return AppError(
        error_code="quota_exceeded",
        message=status.reason or "quota_exceeded",
        status_code=429,
    )
