"""Per-studio self-learning config API (cockpit-controlled cadence).

Each agent owner/editor decides whether THEIR studio self-improves and how
often (every 6h / daily / weekly / monthly), under the org master switch
``STUDIO_LEARN_DAEMON_ENABLED``. Config is stored on ``studio.config['self_learn']``
(no migration); the studio-learn daemon reads it per studio and only runs a
studio when its own cadence is due.

Auth mirrors studio_reports.py: any role with access may GET; owner/editor may PUT.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.dependencies import get_async_db, get_current_organization
from app.core.auth import current_user
from app.models.user import User
from app.models.organization import Organization
from app.models.studio import Studio
from app.services.studio_access import resolve_studio_access
from app.schemas.self_learn_schema import SelfLearnConfig, SelfLearnResponse
from app.services.studio_learn_daemon import get_self_learn_cfg, next_run_estimate
from app.settings.hybrid_flags import flags

router = APIRouter(tags=["studio_self_learn"])


async def _load_studio(db: AsyncSession, studio_id: str, org: Organization) -> Studio:
    res = await db.execute(
        select(Studio).where(
            Studio.id == studio_id,
            Studio.organization_id == org.id,
            Studio.deleted_at.is_(None),
        )
    )
    studio = res.scalar_one_or_none()
    if studio is None:
        raise HTTPException(status_code=404, detail="Studio not found")
    return studio


def _build_response(studio: Studio, role: str | None) -> SelfLearnResponse:
    cfg = get_self_learn_cfg(studio)
    return SelfLearnResponse(
        enabled=cfg["enabled"],
        cadence=cfg["cadence"],
        hour_utc=cfg["hour_utc"],
        last_run_at=cfg["last_run_at"],
        next_run_at=next_run_estimate(cfg),
        master_enabled=bool(flags.STUDIO_LEARN_DAEMON),
        role=role,
    )


@router.get("/studios/{studio_id}/self-learn", response_model=SelfLearnResponse)
async def get_self_learn(
    studio_id: str,
    db: AsyncSession = Depends(get_async_db),
    org: Organization = Depends(get_current_organization),
    user: User = Depends(current_user),
):
    """Read this studio's self-learn config (any role with access)."""
    role = await resolve_studio_access(db, studio_id, user)
    if role is None:
        raise HTTPException(status_code=403, detail="No access to this studio")
    studio = await _load_studio(db, studio_id, org)
    return _build_response(studio, role)


@router.put("/studios/{studio_id}/self-learn", response_model=SelfLearnResponse)
async def update_self_learn(
    studio_id: str,
    body: SelfLearnConfig,
    db: AsyncSession = Depends(get_async_db),
    org: Organization = Depends(get_current_organization),
    user: User = Depends(current_user),
):
    """Set this studio's self-learn cadence (owner/editor only)."""
    role = await resolve_studio_access(db, studio_id, user)
    if role not in ("owner", "editor"):
        raise HTTPException(status_code=403, detail="Owner or editor required")

    studio = await _load_studio(db, studio_id, org)
    cfg = body.normalized()

    new_config = dict(getattr(studio, "config", None) or {})
    existing = dict(new_config.get("self_learn", {}) or {})
    # Preserve daemon-managed last_run_at across user edits.
    new_sl = {
        "enabled": cfg.enabled,
        "cadence": cfg.cadence,
        "hour_utc": cfg.hour_utc,
        "last_run_at": existing.get("last_run_at"),
    }
    new_config["self_learn"] = new_sl
    studio.config = new_config
    flag_modified(studio, "config")
    await db.commit()
    await db.refresh(studio)
    return _build_response(studio, role)
