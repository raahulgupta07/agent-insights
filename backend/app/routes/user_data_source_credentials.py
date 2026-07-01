from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_async_db
from app.core.auth import current_user
from app.dependencies import get_current_organization
from app.models.user import User
from app.models.organization import Organization
from app.models.data_source import DataSource
from app.core.permissions_decorator import requires_permission, requires_resource_permission
from app.ee.audit.service import audit_service

from sqlalchemy import select

from app.schemas.user_data_source_credentials_schema import (
    UserDataSourceCredentialsCreate,
    UserDataSourceCredentialsUpdate,
    UserDataSourceCredentialsSchema,
)
from app.services.user_data_source_credentials_service import UserDataSourceCredentialsService


router = APIRouter(tags=["data_sources"])
svc = UserDataSourceCredentialsService()


async def _load_datasource(db: AsyncSession, organization: Organization, data_source_id: str) -> DataSource:
    from app.models.data_source import DataSource
    res = await db.execute(select(DataSource).where(DataSource.id == data_source_id, DataSource.organization_id == organization.id))
    ds = res.scalar_one_or_none()
    if not ds:
        raise HTTPException(status_code=404, detail="Data source not found")
    return ds


@router.get("/data_sources/{data_source_id}/my-credentials", response_model=UserDataSourceCredentialsSchema | None)
@requires_resource_permission('data_source', 'view')
async def get_my_credentials(
    data_source_id: str,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(current_user),
    organization: Organization = Depends(get_current_organization),
):
    ds = await _load_datasource(db, organization, data_source_id)
    return await svc.get_my_credentials(db=db, data_source=ds, user=current_user)


@router.post("/data_sources/{data_source_id}/my-credentials", response_model=UserDataSourceCredentialsSchema)
@requires_resource_permission('data_source', 'view')
async def upsert_my_credentials(
    data_source_id: str,
    payload: UserDataSourceCredentialsCreate,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(current_user),
    organization: Organization = Depends(get_current_organization),
):
    ds = await _load_datasource(db, organization, data_source_id)
    result = await svc.upsert_my_credentials(db=db, data_source=ds, user=current_user, payload=payload)
    try:
        await audit_service.log(
            db=db,
            organization_id=organization.id,
            action="credentials.created",
            user_id=current_user.id,
            resource_type="data_source",
            resource_id=data_source_id,
            request=request,
        )
    except Exception:
        pass
    return result


@router.patch("/data_sources/{data_source_id}/my-credentials", response_model=UserDataSourceCredentialsSchema)
@requires_resource_permission('data_source', 'view')
async def patch_my_credentials(
    data_source_id: str,
    payload: UserDataSourceCredentialsUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(current_user),
    organization: Organization = Depends(get_current_organization),
):
    ds = await _load_datasource(db, organization, data_source_id)
    return await svc.patch_my_credentials(db=db, data_source=ds, user=current_user, payload=payload)


@router.delete("/data_sources/{data_source_id}/my-credentials", status_code=204)
@requires_resource_permission('data_source', 'view')
async def delete_my_credentials(
    data_source_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(current_user),
    organization: Organization = Depends(get_current_organization),
):
    ds = await _load_datasource(db, organization, data_source_id)
    await svc.delete_my_credentials(db=db, data_source=ds, user=current_user)
    try:
        await audit_service.log(
            db=db,
            organization_id=organization.id,
            action="credentials.deleted",
            user_id=current_user.id,
            resource_type="data_source",
            resource_id=data_source_id,
            request=request,
        )
    except Exception:
        pass
    return None


@router.post("/data_sources/{data_source_id}/my-credentials/test", response_model=dict)
@requires_resource_permission('data_source', 'view')
async def test_my_credentials(
    data_source_id: str,
    payload: UserDataSourceCredentialsCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(current_user),
    organization: Organization = Depends(get_current_organization),
):
    ds = await _load_datasource(db, organization, data_source_id)
    return await svc.test_my_credentials(db=db, data_source=ds, user=current_user, payload=payload)


# --- P2: cross-tenant discovery for Power BI user sign-in --------------------
# Helps a user find the (often guest) tenant id where their Fabric workspaces live.
# Pre-connect: needs no data source, just the user's email + password. Flag-gated.
class PowerBIDiscoverTenantsRequest(BaseModel):
    username: str
    password: str
    home_tenant: str | None = None  # optional; defaults to the multi-tenant "organizations" authority


@router.post("/data_sources/powerbi/discover-tenants", response_model=dict)
async def powerbi_discover_tenants(
    payload: PowerBIDiscoverTenantsRequest,
    current_user: User = Depends(current_user),
    organization: Organization = Depends(get_current_organization),
):
    from app.settings.hybrid_flags import flags as _hf
    if not getattr(_hf, "POWERBI_USER", False):
        raise HTTPException(status_code=404, detail="Power BI user sign-in is not enabled")
    from app.services.powerbi_tenant_discovery import discover_tenants
    try:
        tenants = discover_tenants(payload.username, payload.password, payload.home_tenant or "organizations")
        return {"ok": True, "tenants": tenants}
    except Exception as e:  # noqa: BLE001 — surface the AADSTS hint, never 500
        return {"ok": False, "error": str(e), "tenants": []}


# --- #8: scan ALL reachable tenants → one merged per-user overlay -------------
# "Show me everything I can access anywhere." Loops get_schemas() per discovered
# tenant and merges the tenant-tagged tables into this user's overlay.
class PowerBIScanAllTenantsRequest(BaseModel):
    username: str
    password: str
    client_id: str | None = None


@router.post("/data_sources/{data_source_id}/my-credentials/scan-all-tenants", response_model=dict)
@requires_resource_permission('data_source', 'view')
async def powerbi_scan_all_tenants(
    data_source_id: str,
    payload: PowerBIScanAllTenantsRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(current_user),
    organization: Organization = Depends(get_current_organization),
):
    ds = await _load_datasource(db, organization, data_source_id)
    try:
        summary = await svc.scan_all_tenants_overlay(
            db=db, data_source=ds, user=current_user,
            username=payload.username, password=payload.password, client_id=payload.client_id,
        )
        return {"ok": True, **summary}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 — surface the scan error, never 500
        return {"ok": False, "error": str(e), "tenants": [], "table_count": 0}


# --- P3: device-code sign-in (MFA-safe) --------------------------------------
# ROPC dies on MFA-on accounts; device-code lets the user approve in a browser
# (2FA happens there) and returns a refresh token we persist (encrypted).
class PowerBIDeviceCodeStartRequest(BaseModel):
    tenant_id: str
    client_id: str | None = None


class PowerBIDeviceCodePollRequest(BaseModel):
    tenant_id: str
    device_code: str
    auth_mode: str
    username: str | None = None
    client_id: str | None = None


def _require_powerbi_user_flag():
    from app.settings.hybrid_flags import flags as _hf
    if not getattr(_hf, "POWERBI_USER", False):
        raise HTTPException(status_code=404, detail="Power BI user sign-in is not enabled")


@router.post("/data_sources/{data_source_id}/my-credentials/device-code/start", response_model=dict)
@requires_resource_permission('data_source', 'view')
async def powerbi_device_code_start(
    data_source_id: str,
    payload: PowerBIDeviceCodeStartRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(current_user),
    organization: Organization = Depends(get_current_organization),
):
    _require_powerbi_user_flag()
    await _load_datasource(db, organization, data_source_id)
    from app.services.powerbi_device_code import start_device_code
    try:
        return start_device_code(payload.tenant_id, payload.client_id)
    except Exception as e:  # noqa: BLE001 — never 500
        return {"ok": False, "error": str(e)}


@router.post("/data_sources/{data_source_id}/my-credentials/device-code/poll", response_model=dict)
@requires_resource_permission('data_source', 'view')
async def powerbi_device_code_poll(
    data_source_id: str,
    payload: PowerBIDeviceCodePollRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(current_user),
    organization: Organization = Depends(get_current_organization),
):
    _require_powerbi_user_flag()
    ds = await _load_datasource(db, organization, data_source_id)
    from app.services.powerbi_device_code import poll_device_code
    try:
        result = poll_device_code(payload.tenant_id, payload.device_code, payload.client_id)
        status = result.get("status")
        if status == "pending":
            return {"ok": True, "status": "pending"}
        if status != "success":
            return {"ok": False, "status": "error", "error": result.get("error") or "sign-in failed"}
        refresh_token = result.get("refresh_token")
        if not refresh_token:
            return {"ok": False, "status": "error",
                    "error": "No refresh token returned — enable offline_access / retry"}
        # Persist the credential (Fernet-encrypted) so future scans/DAX reuse it.
        create = UserDataSourceCredentialsCreate(
            auth_mode=payload.auth_mode,
            credentials={
                "tenant_id": payload.tenant_id,
                "refresh_token": refresh_token,
                "username": payload.username or None,
            },
            is_primary=True,
        )
        await svc.upsert_my_credentials(db=db, data_source=ds, user=current_user, payload=create)
        return {"ok": True, "status": "success"}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 — never 500, never leak a token
        return {"ok": False, "status": "error", "error": str(e)}


