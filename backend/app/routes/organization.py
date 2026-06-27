from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from uuid import UUID
from app.dependencies import get_async_db
from app.models.membership import Membership
from app.services.organization_service import OrganizationService
from app.schemas.organization_schema import OrganizationCreate, OrganizationSchema, OrganizationAndRoleSchema, OrganizationUpdate
from app.schemas.organization_schema import MembershipCreate, MembershipSchema, MembershipUpdate
from app.schemas.organization_schema import MembershipImportReport
from app.schemas.organization_schema import DirectUserCreate
from app.models.user import User
from app.models.organization import Organization
from app.core.auth import current_user
from typing import List
from app.dependencies import get_current_organization
from app.core.permissions_decorator import requires_permission
from app.schemas.user_schema import UserSchema
from app.ee.audit.service import audit_service

router = APIRouter(tags=["organizations"])
organization_service = OrganizationService()


def _derive_auth_sources(user) -> list[str]:
    """Derive how a member authenticates from the User ORM object.

    Returns a list such as ["ldap"], ["sso:google"], ["ldap", "sso:google"],
    ["scim"] or ["local"]. "local" is only added when the user has no
    ldap/sso/scim signal (LDAP/SSO auto-provisioned users also carry a random
    hashed_password, so it can't be used as a positive "local" signal on its
    own). Empty derivation defaults to ["local"]. None user → [].
    """
    if user is None:
        return []
    sources: list[str] = []
    if getattr(user, "ldap_dn", None):
        sources.append("ldap")
    seen_providers: set[str] = set()
    for acct in (getattr(user, "oauth_accounts", None) or []):
        name = getattr(acct, "oauth_name", None)
        if name and name not in seen_providers:
            seen_providers.add(name)
            sources.append(f"sso:{name}")
    if getattr(user, "scim_external_id", None):
        sources.append("scim")
    if not sources:
        # No federated identity → a real local-password account.
        sources.append("local")
    return sources

@router.post("/organizations", response_model=OrganizationSchema)
async def create_organization(organization: OrganizationCreate, db: AsyncSession = Depends(get_async_db), current_user: User = Depends(current_user)):
    return await organization_service.create_organization(db, organization, current_user)

@router.post("/organizations/{organization_id}/members", response_model=MembershipSchema)
@requires_permission('manage_members')
async def add_member(
    organization_id: str,
    membership: MembershipCreate,
    request: Request,
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db)
):
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=403,
            detail="Only a super admin can create users. LDAP/SSO users are provisioned automatically.",
        )
    membership.organization_id = organization_id
    result = await organization_service.add_member(db, membership, current_user.id)
    await audit_service.log(
        db=db,
        organization_id=organization_id,
        action="member.invited",
        user_id=current_user.id,
        resource_type="membership",
        resource_id=result.id,
        details={"email": membership.email, "role": membership.role},
        request=request,
    )
    return result

@router.post("/organizations/{organization_id}/members/create-user", response_model=MembershipSchema)
@requires_permission('manage_members')
async def create_user_directly(
    organization_id: str,
    payload: DirectUserCreate,
    request: Request,
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Admin creates a user with email + password directly (no email invite).

    The account is active/verified immediately, so the new user can sign in
    right away with the password the admin set.
    """
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=403,
            detail="Only a super admin can create users. LDAP/SSO users are provisioned automatically.",
        )
    result = await organization_service.create_user_with_password(
        db=db,
        organization_id=organization_id,
        email=payload.email,
        password=payload.password,
        name=payload.name,
        role=payload.role or "member",
        current_user=current_user,
    )
    try:
        await audit_service.log(
            db=db,
            organization_id=organization_id,
            action="member.created",
            user_id=current_user.id,
            resource_type="membership",
            resource_id=result.id,
            details={"email": payload.email, "role": payload.role},
            request=request,
        )
    except Exception:
        pass
    return result

@router.get("/organizations/{organization_id}/members", response_model=List[MembershipSchema])
@requires_permission('view_members')
async def get_members(organization_id: str, db: AsyncSession = Depends(get_async_db), organization: Organization = Depends(get_current_organization), current_user: User = Depends(current_user)):
    members = await organization_service.get_members(db, organization, current_user)

    # Per-member auth source(s). The service resolves roles but loads only the
    # User row; we need its oauth_accounts (+ ldap_dn/scim) to label each member.
    # Re-fetch memberships with the User and its oauth_accounts eager-loaded,
    # then map back onto the already-built schemas by membership id.
    result = await db.execute(
        select(Membership)
        .options(selectinload(Membership.user).selectinload(User.oauth_accounts))
        .where(Membership.organization_id == organization.id)
    )
    user_by_membership_id = {m.id: m.user for m in result.scalars().all()}
    for member in members:
        member.auth_sources = _derive_auth_sources(user_by_membership_id.get(member.id))
    return members

@router.delete("/organizations/{organization_id}/members/{membership_id}", status_code=204)
@requires_permission('manage_members')
async def remove_member(
    organization_id: str,
    membership_id: str,
    request: Request,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization)
):
    await audit_service.log(
        db=db,
        organization_id=organization_id,
        action="member.removed",
        user_id=current_user.id,
        resource_type="membership",
        resource_id=membership_id,
        request=request,
    )
    return await organization_service.remove_member(db, organization_id, membership_id, current_user, organization)

@router.put("/organizations/{organization_id}/members/{membership_id}", response_model=MembershipSchema)
@requires_permission('manage_members')
async def update_member(
    organization_id: str,
    membership_id: str,
    membership: MembershipUpdate,
    request: Request,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    result = await organization_service.update_member(db, membership_id, organization_id, membership, current_user, organization)
    try:
        await audit_service.log(
            db=db,
            organization_id=organization_id,
            action="member.role_changed",
            user_id=current_user.id,
            resource_type="membership",
            resource_id=membership_id,
            details={"new_role": membership.role, "target_user_id": str(result.user_id) if hasattr(result, "user_id") else None},
            request=request,
        )
    except Exception:
        pass
    return result


@router.post("/organizations/{organization_id}/members/{membership_id}/resend", response_model=MembershipSchema)
@requires_permission('manage_members')
async def resend_invite(
    organization_id: str,
    membership_id: str,
    request: Request,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    result = await organization_service.resend_invite(db, membership_id, organization_id)
    try:
        await audit_service.log(
            db=db,
            organization_id=organization_id,
            action="member.invite_resent",
            user_id=current_user.id,
            resource_type="membership",
            resource_id=membership_id,
            details={"email_status": result.invite_email_status},
            request=request,
        )
    except Exception:
        pass
    return result


@router.get("/organizations/{organization_id}/members/{membership_id}/invite-link")
@requires_permission('manage_members')
async def get_invite_link(
    organization_id: str,
    membership_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    return await organization_service.get_invite_link(db, membership_id, organization_id)


@router.post("/organizations/{organization_id}/members/import", response_model=MembershipImportReport)
@requires_permission('manage_members')
async def import_members(
    organization_id: str,
    request: Request,
    file: UploadFile = File(...),
    dry_run: bool = True,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file")
    report = await organization_service.import_members(
        db=db,
        organization=organization,
        file_bytes=file_bytes,
        filename=file.filename or "",
        dry_run=dry_run,
        current_user=current_user,
    )
    if not dry_run:
        try:
            await audit_service.log(
                db=db,
                organization_id=organization_id,
                action="member.imported",
                user_id=current_user.id,
                resource_type="membership",
                details={
                    "filename": file.filename,
                    "summary": report.summary.dict(),
                },
                request=request,
            )
        except Exception:
            pass
    return report

@router.get("/organizations", response_model=List[OrganizationAndRoleSchema])
async def get_organizations(db: AsyncSession = Depends(get_async_db), current_user: User = Depends(current_user)):
    return await organization_service.get_user_organizations(db, current_user)

@requires_permission('manage_members')
@router.get("/organization/members", response_model=List[UserSchema])
async def get_organization_members(db: AsyncSession = Depends(get_async_db), current_user: User = Depends(current_user), organization: Organization = Depends(get_current_organization)):
    return await organization_service.get_organization_members(db, current_user, organization)


@router.put("/organization", response_model=OrganizationSchema)
@requires_permission('manage_settings')
async def update_organization(
    payload: OrganizationUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(current_user),
    organization: Organization = Depends(get_current_organization)
):
    return await organization_service.update_organization(db, organization, payload, current_user)