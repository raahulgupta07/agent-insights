"""User-owned groups router (HYBRID_USER_GROUPS).

Lets a normal (non-admin) member manage their OWN contact groups and use them
as reusable share targets. Every endpoint is gated by ``flags.USER_GROUPS``
(404 / feature-locked when off, mirroring routes/studio.py) and every mutation
is owner-enforced inside the service (``owner_user_id == current_user.id`` →
403 otherwise). Org/admin/LDAP groups are never touched here.

Mounted in main.py with ``prefix="/api"`` next to the rbac/studio routers, so
paths are declared bare (``/me/groups`` → ``/api/me/groups``).
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional

from app.core.auth import current_user
from app.dependencies import get_async_db, get_current_organization
from app.errors import AppError, ErrorCode
from app.models.organization import Organization
from app.models.user import User
from app.services.me_groups_service import me_groups_service
from app.schemas.me_groups_schema import (
    MyGroupSchema, MyGroupCreate, MyGroupUpdate, MyGroupMemberAdd, ContactSchema,
)

router = APIRouter(tags=["me-groups"])


def _ensure_enabled() -> None:
    """Raise 404 (feature not enabled) unless flags.USER_GROUPS is on."""
    from app.settings.hybrid_flags import flags

    if not flags.USER_GROUPS:
        raise AppError(
            ErrorCode.FEATURE_LOCKED,
            "User-owned groups are not enabled.",
            status_code=404,
        )


# --------------------------------------------------------------------------- #
# Groups
# --------------------------------------------------------------------------- #
@router.get("/me/groups", response_model=List[MyGroupSchema])
async def list_my_groups(
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
) -> List[MyGroupSchema]:
    _ensure_enabled()
    return await me_groups_service.list_my_groups(
        db, str(organization.id), str(current_user.id)
    )


@router.post("/me/groups", response_model=MyGroupSchema, status_code=201)
async def create_my_group(
    data: MyGroupCreate,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
) -> MyGroupSchema:
    _ensure_enabled()
    return await me_groups_service.create_my_group(
        db, str(organization.id), str(current_user.id), data
    )


@router.patch("/me/groups/{group_id}", response_model=MyGroupSchema)
async def update_my_group(
    group_id: str,
    data: MyGroupUpdate,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
) -> MyGroupSchema:
    _ensure_enabled()
    return await me_groups_service.update_my_group(
        db, str(organization.id), str(current_user.id), group_id, data
    )


@router.delete("/me/groups/{group_id}", status_code=204)
async def delete_my_group(
    group_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
) -> None:
    _ensure_enabled()
    await me_groups_service.delete_my_group(
        db, str(organization.id), str(current_user.id), group_id
    )


# --------------------------------------------------------------------------- #
# Members
# --------------------------------------------------------------------------- #
@router.post("/me/groups/{group_id}/members", response_model=MyGroupSchema)
async def add_my_group_members(
    group_id: str,
    data: MyGroupMemberAdd,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
) -> MyGroupSchema:
    _ensure_enabled()
    return await me_groups_service.add_members(
        db, str(organization.id), str(current_user.id), group_id, data.resolved_ids()
    )


@router.delete("/me/groups/{group_id}/members/{user_id}", status_code=204)
async def remove_my_group_member(
    group_id: str,
    user_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
) -> None:
    _ensure_enabled()
    await me_groups_service.remove_member(
        db, str(organization.id), str(current_user.id), group_id, user_id
    )


# --------------------------------------------------------------------------- #
# Contacts (org members for the picker)
# --------------------------------------------------------------------------- #
@router.get("/me/contacts", response_model=List[ContactSchema])
async def list_contacts(
    q: Optional[str] = Query(None),
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
) -> List[ContactSchema]:
    _ensure_enabled()
    return await me_groups_service.list_contacts(db, str(organization.id), q=q)
