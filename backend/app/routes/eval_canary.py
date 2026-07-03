"""Eval canary health + drift alert - HTTP surface (read-only).

Exposes the per-golden eval health + regression-vs-last-green computed by
``services/evals/canary_health.py`` so a standalone FE page can render canary
badges + drift alerts.

Router has NO prefix; main.py mounts it with ``prefix="/api"`` like every other
router -> live paths are ``/api/eval/canary/health`` and ``/api/eval/canary/drift``.

Both endpoints are org-scoped (header ``X-Organization-Id`` via
``get_current_organization``), flag-gated on ``HYBRID_EVAL_CANARY`` (OFF ->
``{enabled: false}``), and fail-soft (never 500 on the read).
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_async_db, get_current_organization
from app.core.auth import current_user
from app.models.user import User
from app.models.organization import Organization

router = APIRouter(tags=["eval_canary"])


def _enabled() -> bool:
    try:
        from app.settings.hybrid_flags import flags

        return bool(getattr(flags, "EVAL_CANARY", False))
    except Exception:
        return False


@router.get("/eval/canary/health")
async def eval_canary_health(
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Per-golden canary pass-rate + last-run status + trend. Empty unless
    HYBRID_EVAL_CANARY."""
    if not _enabled():
        return {"enabled": False, "tables": []}
    from app.services.evals.canary_health import table_health

    tables = await table_health(db, organization_id=str(organization.id))
    return {"enabled": True, "tables": tables}


@router.get("/eval/canary/drift")
async def eval_canary_drift(
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Regressions vs last-green (was pass, now fail/error). Empty unless
    HYBRID_EVAL_CANARY."""
    if not _enabled():
        return {"enabled": False, "drift": []}
    from app.services.evals.canary_health import detect_drift

    drift = await detect_drift(db, organization_id=str(organization.id))
    return {"enabled": True, "drift": drift}
