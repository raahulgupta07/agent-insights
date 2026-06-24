"""Studio KPI Metric Registry API (Feature 3 — number-safety).

Lets a Studio register named KPI metrics with VERIFIED SQL (e.g. ``v_lead``,
``recruitment_rate``) so the agent REUSES the exact registered SQL instead of
re-deriving the filter logic on every question (prevents drift).

The target data source is a spreadsheet (DuckDB, in-memory per query) so a
persistent ``CREATE VIEW`` is NOT viable. Instead a metric is stored as a
high-priority *verified golden example* — a ``StudioExample`` row — which the
existing ``StudioContextBuilder`` already injects into the Studio chat context
(``status='active'`` rows render as ``Q:/A:/SQL:`` few-shots in the
``<studio_context>`` block). So a registered metric becomes a verified example
the agent SEES: "for metric X, use this exact SQL".

REUSES existing infra (NO new table, NO migration):
  - storage    : ``studio_examples`` (ST7/ST8) rows, tagged ``[METRIC] <name>``.
  - surfacing  : ``StudioContextBuilder`` -> ``StudioSection.render()`` already
                 injects every ``status='active'`` StudioExample (verified at
                 backend/app/ai/context/builders/studio_context_builder.py:142
                 and backend/app/ai/context/sections/studio.py:68).

This router is self-contained (its own ``APIRouter()``), mirrors the auth /
org-scope / role / flag conventions of ``app.routes.studio_examples``, and is
gated behind ``flags.METRICS_CATALOG`` (reuses the existing flag). Additive: it
only reads/writes ``studio_examples`` rows; ``studios`` / ``data_sources`` are
never mutated.
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_user
from app.dependencies import get_async_db, get_current_organization
from app.errors import AppError, ErrorCode
from app.models.organization import Organization
from app.models.studio import Studio, StudioExample
from app.models.user import User
from app.schemas.base import OptionalUTCDatetime
from app.services.studio_access import resolve_studio_access
from app.settings.hybrid_flags import flags

router = APIRouter(tags=["studios"])

# Roles that may register / delete metrics.
_EDITOR_ROLES = {"owner", "editor"}

# Marker prefix that distinguishes a metric row from a plain golden example in
# the shared ``studio_examples`` table. Kept in the rendered ``question`` so the
# agent reads it as "[METRIC] <name>: <definition>".
_METRIC_PREFIX = "[METRIC]"


# --------------------------------------------------------------------------- #
# Schemas (self-contained — metric is a thin view over StudioExample)
# --------------------------------------------------------------------------- #
class MetricCreate(BaseModel):
    name: str
    definition: Optional[str] = None
    sql: str
    data_source_id: Optional[str] = None  # echo-only (a Studio's pinned set defines scope)


class MetricResponse(BaseModel):
    id: str
    studio_id: str
    name: str
    definition: str
    sql: Optional[str] = None
    data_source_id: Optional[str] = None
    status: str
    source: str
    created_at: OptionalUTCDatetime = None
    updated_at: OptionalUTCDatetime = None


# --------------------------------------------------------------------------- #
# Helpers (mirror studio_examples.py)
# --------------------------------------------------------------------------- #
def _require_flag() -> None:
    """Short-circuit when the Metrics Catalog feature is OFF (404, no leak)."""
    if not flags.METRICS_CATALOG:
        raise AppError.not_found("studio.not_found", "Studio not found")


async def _require_role(
    db: AsyncSession, studio_id: str, user: User, *, editor: bool = False
) -> str:
    role = await resolve_studio_access(db, studio_id, user)
    if role is None:
        raise AppError.not_found("studio.not_found", "Studio not found")
    if editor and role not in _EDITOR_ROLES:
        raise AppError.forbidden(
            ErrorCode.ACCESS_DENIED, "Editor or owner role required"
        )
    return role


async def _load_studio(db: AsyncSession, studio_id: str) -> Studio:
    res = await db.execute(
        select(Studio).where(
            Studio.id == studio_id,
            Studio.deleted_at.is_(None),
        )
    )
    studio = res.scalar_one_or_none()
    if studio is None:
        raise AppError.not_found("studio.not_found", "Studio not found")
    return studio


async def _load_metric(
    db: AsyncSession, studio_id: str, metric_id: str
) -> StudioExample:
    """Load a non-deleted METRIC example belonging to this studio or raise 404."""
    res = await db.execute(
        select(StudioExample).where(
            StudioExample.id == metric_id,
            StudioExample.studio_id == studio_id,
            StudioExample.deleted_at.is_(None),
        )
    )
    row = res.scalar_one_or_none()
    if row is None or not (row.question or "").startswith(_METRIC_PREFIX):
        raise AppError.not_found("studio.metric_not_found", "Metric not found")
    return row


def _parse_metric_name(question: str) -> str:
    """Recover the metric ``name`` from the stored ``[METRIC] <name>: <def>``."""
    q = (question or "")[len(_METRIC_PREFIX):].lstrip()
    name = q.split(":", 1)[0].strip()
    return name


def _to_read(row: StudioExample) -> MetricResponse:
    return MetricResponse(
        id=str(row.id),
        studio_id=str(row.studio_id),
        name=_parse_metric_name(row.question),
        definition=row.answer or "",
        sql=row.sql,
        data_source_id=None,  # echo-only on create; StudioExample has no per-DS column
        status=row.status,
        source=row.source,
        created_at=getattr(row, "created_at", None),
        updated_at=getattr(row, "updated_at", None),
    )


# --------------------------------------------------------------------------- #
# LIST (viewer+)
# --------------------------------------------------------------------------- #
@router.get(
    "/studios/{studio_id}/metrics",
    response_model=List[MetricResponse],
)
async def list_studio_metrics(
    studio_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """List a Studio's registered KPI metrics (viewer+), newest first."""
    _require_flag()
    await _require_role(db, studio_id, current_user)

    stmt = (
        select(StudioExample)
        .where(
            StudioExample.studio_id == studio_id,
            StudioExample.deleted_at.is_(None),
            StudioExample.question.like(f"{_METRIC_PREFIX}%"),
        )
        .order_by(StudioExample.created_at.desc())
    )
    res = await db.execute(stmt)
    return [_to_read(r) for r in res.scalars().all()]


# --------------------------------------------------------------------------- #
# CREATE (editor+) — metric goes straight to 'active' (verified by the editor)
# --------------------------------------------------------------------------- #
@router.post(
    "/studios/{studio_id}/metrics",
    response_model=MetricResponse,
)
async def create_studio_metric(
    studio_id: str,
    body: MetricCreate,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Register a named KPI metric with VERIFIED SQL (editor+).

    Stored as an ``active`` ``StudioExample`` so the agent immediately sees it as
    a verified example (``Q: [METRIC] <name>: <definition>`` / ``A: ...`` /
    ``SQL: <verified sql>``) and reuses the exact SQL instead of re-deriving the
    filter logic. The metric name must be unique within the Studio.
    """
    _require_flag()
    await _require_role(db, studio_id, current_user, editor=True)
    await _load_studio(db, studio_id)

    name = (body.name or "").strip()
    definition = (body.definition or "").strip()
    sql = (body.sql or "").strip()
    if not name:
        raise AppError.bad_request(ErrorCode.VALIDATION, "name is required")
    if not sql:
        raise AppError.bad_request(ErrorCode.VALIDATION, "sql is required")

    # Enforce a unique metric name within the Studio (case-insensitive).
    existing = (
        await db.execute(
            select(StudioExample).where(
                StudioExample.studio_id == studio_id,
                StudioExample.deleted_at.is_(None),
                StudioExample.question.like(f"{_METRIC_PREFIX}%"),
            )
        )
    ).scalars().all()
    for r in existing:
        if _parse_metric_name(r.question).lower() == name.lower():
            raise AppError.bad_request(
                ErrorCode.VALIDATION, f"A metric named '{name}' already exists"
            )

    # question carries the marker + name + definition so the agent reads it as a
    # named, verified metric. answer holds the human definition.
    question = f"{_METRIC_PREFIX} {name}"
    if definition:
        question += f": {definition}"
    answer = definition or f"Verified SQL for the '{name}' metric."

    row = StudioExample(
        studio_id=studio_id,
        question=question,
        answer=answer,
        sql=sql,
        source="manual",
        status="active",   # editor-verified -> reaches the agent immediately
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    out = _to_read(row)
    out.data_source_id = body.data_source_id
    return out


# --------------------------------------------------------------------------- #
# DELETE (editor+) — soft-delete the metric
# --------------------------------------------------------------------------- #
@router.delete("/studios/{studio_id}/metrics/{metric_id}")
async def delete_studio_metric(
    studio_id: str,
    metric_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Delete a registered metric (editor+). Soft-deletes the row."""
    _require_flag()
    await _require_role(db, studio_id, current_user, editor=True)
    row = await _load_metric(db, studio_id, metric_id)

    row.deleted_at = datetime.utcnow()
    await db.commit()
    return {"ok": True, "studio_id": studio_id, "metric_id": metric_id}
