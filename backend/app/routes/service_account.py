"""Service Accounts — machine/service principals for headless API access.

Admin-only (``manage_members`` — the same gate ``routes/organization.py`` uses
for member management) and org-scoped. Endpoints are declared WITHOUT the
``/api`` prefix; ``main.py`` adds ``/api`` at include time, so ``/service-accounts``
becomes ``/api/service-accounts``.

Feature-gated by ``HYBRID_SERVICE_ACCOUNTS`` (default OFF): when off, every
endpoint 404s so the surface is dark on a fresh deploy.
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_async_db, get_current_organization
from app.core.auth import current_user
from app.core.permissions_decorator import requires_permission
from app.models.user import User
from app.models.organization import Organization
from app.schemas.service_account_schema import (
    ServiceAccountCreate, ServiceAccountUpdate, ServiceAccountResponse,
    ServiceAccountDetail, ServiceAccountKeyCreate, ServiceAccountKeyCreated,
)
from app.services.service_account_service import ServiceAccountService
from app.settings.hybrid_flags import flags

router = APIRouter(tags=["service_accounts"])
service = ServiceAccountService()


def _require_flag() -> None:
    if not flags.SERVICE_ACCOUNTS:
        raise HTTPException(status_code=404, detail="Service accounts are not enabled")


@router.get("/service-accounts", response_model=List[ServiceAccountResponse])
@requires_permission('manage_members')
async def list_service_accounts(
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user),
):
    _require_flag()
    return await service.list_service_accounts(db, organization)


@router.post("/service-accounts", response_model=ServiceAccountResponse)
@requires_permission('manage_members')
async def create_service_account(
    data: ServiceAccountCreate,
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user),
):
    _require_flag()
    return await service.create_service_account(db, data, current_user, organization)


@router.get("/service-accounts/{sa_id}", response_model=ServiceAccountDetail)
@requires_permission('manage_members')
async def get_service_account(
    sa_id: str,
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user),
):
    _require_flag()
    return await service.get_service_account(db, organization, sa_id)


@router.patch("/service-accounts/{sa_id}", response_model=ServiceAccountResponse)
@requires_permission('manage_members')
async def update_service_account(
    sa_id: str,
    data: ServiceAccountUpdate,
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user),
):
    _require_flag()
    return await service.update_service_account(db, organization, sa_id, data)


@router.delete("/service-accounts/{sa_id}")
@requires_permission('manage_members')
async def delete_service_account(
    sa_id: str,
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user),
):
    _require_flag()
    await service.delete_service_account(db, organization, sa_id)
    return {"message": "Service account deleted"}


@router.post("/service-accounts/{sa_id}/keys", response_model=ServiceAccountKeyCreated)
@requires_permission('manage_members')
async def create_service_account_key(
    sa_id: str,
    data: ServiceAccountKeyCreate,
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user),
):
    _require_flag()
    # The plaintext token is returned ONLY here, exactly once.
    return await service.issue_key(db, organization, sa_id, data)


@router.delete("/service-accounts/{sa_id}/keys/{key_id}")
@requires_permission('manage_members')
async def revoke_service_account_key(
    sa_id: str,
    key_id: str,
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user),
):
    _require_flag()
    await service.revoke_key(db, organization, sa_id, key_id)
    return {"message": "API key revoked"}
