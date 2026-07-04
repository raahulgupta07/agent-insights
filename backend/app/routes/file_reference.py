"""Routes for #497 report file references (pin an uploaded file into a prompt).

Org- AND user-scoped via the fork's auth dependencies. Every handler is gated on
``flags.FILE_REFERENCES`` -> 404 when OFF (route mounted unconditionally, but the
feature is invisible until the flag is on). 404-no-leak: a report / file / ref
from another org is indistinguishable from "not found".
"""
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List

from app.dependencies import get_async_db, get_current_organization
from app.core.auth import current_user
from app.models.user import User
from app.models.organization import Organization
from app.models.report import Report
from app.models.file import File
from app.models.file_reference import FileReference

router = APIRouter(tags=["file_references"])


def _flag_on() -> bool:
    try:
        from app.settings.hybrid_flags import flags
        return bool(flags.FILE_REFERENCES)
    except Exception:
        return False


def _require_flag():
    if not _flag_on():
        # Feature off -> behave as if the route does not exist.
        raise HTTPException(status_code=404, detail="Not found")


def _ref_dict(r: FileReference) -> dict:
    return {
        "id": r.id,
        "report_id": r.report_id,
        "file_id": r.file_id,
        "created_by_user_id": r.created_by_user_id,
    }


async def _get_owned_report(db: AsyncSession, report_id: str, org_id: str) -> Report:
    report = await db.get(Report, report_id)
    if not report or str(report.organization_id) != org_id or getattr(report, "deleted_at", None) is not None:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@router.get("/reports/{report_id}/file_references", response_model=List[dict])
async def list_file_references(
    report_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    _require_flag()
    org_id = str(organization.id)
    await _get_owned_report(db, report_id, org_id)
    rows = (await db.execute(
        select(FileReference).where(
            FileReference.report_id == report_id,
            FileReference.organization_id == org_id,
            FileReference.deleted_at.is_(None),
        )
    )).scalars().all()
    return [_ref_dict(r) for r in rows]


@router.post("/reports/{report_id}/file_references", response_model=dict)
async def create_file_reference(
    report_id: str,
    file_id: str = Body(..., embed=True),
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    _require_flag()
    org_id = str(organization.id)
    await _get_owned_report(db, report_id, org_id)

    f = await db.get(File, file_id)
    if not f or str(f.organization_id) != org_id or getattr(f, "deleted_at", None) is not None:
        # 404-no-leak: cross-org / missing file is just "not found".
        raise HTTPException(status_code=404, detail="File not found")

    # Idempotent: reuse an existing (non-deleted) reference for the same pair.
    existing = (await db.execute(
        select(FileReference).where(
            FileReference.report_id == report_id,
            FileReference.file_id == file_id,
            FileReference.organization_id == org_id,
            FileReference.deleted_at.is_(None),
        )
    )).scalars().first()
    if existing:
        return _ref_dict(existing)

    ref = FileReference(
        report_id=report_id,
        file_id=file_id,
        organization_id=org_id,
        created_by_user_id=str(current_user.id),
    )
    db.add(ref)
    await db.commit()
    await db.refresh(ref)
    return _ref_dict(ref)


@router.delete("/file_references/{reference_id}")
async def delete_file_reference(
    reference_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    _require_flag()
    ref = await db.get(FileReference, reference_id)
    if not ref or str(ref.organization_id) != str(organization.id) or ref.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Reference not found")
    await db.delete(ref)
    await db.commit()
    return {"success": True}
