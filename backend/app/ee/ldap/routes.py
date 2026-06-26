# LDAP Admin Routes
# Licensed under the Business Source License 1.1
# See ENTERPRISE_LICENSE for details

from typing import Optional
from fastapi import APIRouter, Depends, Response, Body
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_async_db, get_current_organization
from app.core.auth import current_user
from app.core.permissions_decorator import requires_permission
from app.ee.license import require_enterprise
from app.ee.ldap.connection import LDAPConnectionManager
from app.ee.ldap.sync_service import LDAPGroupSyncService
from app.ee.ldap.schemas import (
    SyncResult,
    SyncStatus,
    LDAPSyncPreview,
    LDAPTestResult,
)
from app.settings.config import settings
from app.models.user import User
from app.models.organization import Organization
from app.schemas.organization_settings_schema import (
    OrgLdapDirectorySchema,
    OrgLdapDirectoryUpdate,
)
from app.services.organization_settings_service import OrganizationSettingsService

ldap_admin_router = APIRouter(prefix="/enterprise/ldap", tags=["enterprise", "ldap"])

# In-memory sync status per org (simple; could be DB-backed later)
_sync_status: dict[str, SyncResult] = {}


async def _get_ldap_config(db: AsyncSession, organization: Organization):
    """Prefer the DB org config over the file config.

    Priority: DB config (if enabled) > dash_config.ldap (if enabled) > 400 error.
    """
    from fastapi import HTTPException
    from app.services.organization_settings_service import get_org_ldap_config

    # 1. Try DB config first
    db_config = await get_org_ldap_config(db, str(organization.id))
    if db_config and db_config.enabled:
        return db_config

    # 2. Fall back to file config
    file_config = settings.dash_config.ldap
    if file_config.enabled:
        return file_config

    raise HTTPException(status_code=400, detail="LDAP is not configured")


@ldap_admin_router.post("/sync", response_model=SyncResult)
@require_enterprise(feature="ldap")
@requires_permission("manage_identity_providers")
async def trigger_sync(
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Trigger an immediate LDAP group sync for this organization."""
    config = await _get_ldap_config(db, organization)
    sync_service = LDAPGroupSyncService(config)
    result = await sync_service.sync_groups(db, str(organization.id))
    _sync_status[str(organization.id)] = result
    return result


@ldap_admin_router.get("/sync/status", response_model=SyncStatus)
@require_enterprise(feature="ldap")
@requires_permission("manage_identity_providers")
async def get_sync_status(
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Get the last sync result for this organization."""
    from app.services.organization_settings_service import get_org_ldap_config

    org_id = str(organization.id)
    # Check DB config first, then file config
    db_cfg = await get_org_ldap_config(db, org_id)
    ldap_configured = (
        (db_cfg.enabled if db_cfg else False) or settings.dash_config.ldap.enabled
    )
    return SyncStatus(
        last_sync=_sync_status.get(org_id),
        is_syncing=False,
        ldap_configured=ldap_configured,
    )


@ldap_admin_router.get("/sync/preview", response_model=LDAPSyncPreview)
@require_enterprise(feature="ldap")
@requires_permission("manage_identity_providers")
async def preview_sync(
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Dry-run: show what a sync would change without writing."""
    config = await _get_ldap_config(db, organization)
    sync_service = LDAPGroupSyncService(config)
    return await sync_service.preview_sync(db, str(organization.id))


@ldap_admin_router.get("/test-connection", response_model=LDAPTestResult)
@require_enterprise(feature="ldap")
@requires_permission("manage_identity_providers")
async def test_connection(
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Test LDAP server connectivity."""
    config = await _get_ldap_config(db, organization)
    manager = LDAPConnectionManager(config)
    conn_result = manager.test_connection()

    test_result = LDAPTestResult(
        connected=conn_result["connected"],
        server=conn_result["server"],
        vendor=conn_result.get("vendor"),
        error=conn_result.get("error"),
    )

    # If connected, try to count users and groups
    if test_result.connected:
        try:
            users = manager.search_users()
            test_result.user_count = len(users)
        except Exception:
            pass
        try:
            groups = manager.search_groups()
            test_result.group_count = len(groups)
        except Exception:
            pass

    return test_result


# ---------------------------------------------------------------------------
# Multi-directory LDAP routes
# ---------------------------------------------------------------------------

_svc = OrganizationSettingsService()


@ldap_admin_router.get("/directories", response_model=list)
@require_enterprise(feature="ldap")
@requires_permission("manage_identity_providers")
async def list_ldap_directories(
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """List all LDAP directories for this organization."""
    return await _svc.list_ldap_directories(db, organization)


@ldap_admin_router.post("/directories", response_model=OrgLdapDirectorySchema)
@require_enterprise(feature="ldap")
@requires_permission("manage_identity_providers")
async def create_ldap_directory(
    data: OrgLdapDirectoryUpdate,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Create a new LDAP directory."""
    return await _svc.upsert_ldap_directory(db, organization, current_user, data, dir_id=None)


@ldap_admin_router.put("/directories/{dir_id}", response_model=OrgLdapDirectorySchema)
@require_enterprise(feature="ldap")
@requires_permission("manage_identity_providers")
async def update_ldap_directory(
    dir_id: str,
    data: OrgLdapDirectoryUpdate,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Update an existing LDAP directory by id."""
    return await _svc.upsert_ldap_directory(db, organization, current_user, data, dir_id=dir_id)


@ldap_admin_router.delete("/directories/{dir_id}")
@require_enterprise(feature="ldap")
@requires_permission("manage_identity_providers")
async def delete_ldap_directory(
    dir_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Delete an LDAP directory by id."""
    deleted = await _svc.delete_ldap_directory(db, organization, current_user, dir_id)
    if not deleted:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Directory '{dir_id}' not found")
    return {"deleted": True, "id": dir_id}


@ldap_admin_router.post("/directories/{dir_id}/test")
@require_enterprise(feature="ldap")
@requires_permission("manage_identity_providers")
async def test_ldap_directory(
    dir_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Test connectivity to a specific LDAP directory by id."""
    return await _svc.test_ldap_directory(db, organization, current_user, dir_id)
