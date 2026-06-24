from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_async_db, get_current_organization
from app.models.user import User
from app.models.organization import Organization
from app.core.auth import current_user
from app.core.permissions_decorator import requires_permission
from app.services.organization_settings_service import OrganizationSettingsService
from app.schemas.organization_settings_schema import (
    OrgSmtpSchema,
    OrgSmtpUpdate,
    OrgLdapSchema,
    OrgLdapUpdate,
    OrgSsoSchema,
    OrgSsoGoogleUpdate,
    OrgSsoOidcUpdate,
    OrgSsoAuthModeUpdate,
    OrganizationSettingsSchema,
    OrganizationSettingsUpdate,
    SignupPolicySchema,
    OrgSignupEnabledSchema,
)

router = APIRouter(tags=["organization_settings"])
settings_service = OrganizationSettingsService()

@router.get("/organization/settings", response_model=OrganizationSettingsSchema)
async def get_organization_settings(
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization)
):
    """Get all settings for the organization"""
    return await settings_service.get_settings(db, organization, current_user)

@router.put("/organization/settings", response_model=OrganizationSettingsSchema)
@requires_permission('manage_settings')
async def update_organization_settings(
    settings: OrganizationSettingsUpdate,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization)
):
    """Update organization settings"""
    return await settings_service.update_settings(db, organization, current_user, settings)

@router.post("/organization/settings/agents/{agent_name}")
@requires_permission('manage_settings')
async def update_agent_setting(
    agent_name: str,
    enabled: bool,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization)
):
    """Enable/disable a specific agent"""
    return await settings_service.update_agent_setting(db, organization, current_user, agent_name, enabled) 


@router.post("/organization/general/icon", response_model=OrganizationSettingsSchema)
@requires_permission('manage_settings')
async def upload_general_icon(
    icon: UploadFile = File(...),
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization)
):
    return await settings_service.set_general_icon(db, organization, current_user, icon)


@router.delete("/organization/general/icon", response_model=OrganizationSettingsSchema)
@requires_permission('manage_settings')
async def delete_general_icon(
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization)
):
    return await settings_service.remove_general_icon(db, organization, current_user)


@router.get("/organization/locale")
async def get_organization_locale(
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Effective locale for this org + enabled list + system default."""
    return await settings_service.get_locale(db, organization, current_user)


@router.put("/organization/locale")
@requires_permission('manage_settings')
async def update_organization_locale(
    payload: dict,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Set the org's locale override. Pass {"locale": "en|es|he"} or {"locale": null} to clear."""
    locale = payload.get("locale")
    return await settings_service.update_locale(db, organization, current_user, locale)


@router.get("/organization/signup-policy", response_model=SignupPolicySchema)
@requires_permission('full_admin_access')
async def get_signup_policy(
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    return await settings_service.get_signup_policy(db, organization, current_user)


@router.put("/organization/signup-policy", response_model=SignupPolicySchema)
@requires_permission('full_admin_access')
async def update_signup_policy(
    policy: SignupPolicySchema,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    return await settings_service.update_signup_policy(db, organization, current_user, policy)


@router.get("/organization/signup-enabled", response_model=OrgSignupEnabledSchema)
@requires_permission('manage_settings')
async def get_org_signup_enabled(
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Get the public signup enabled toggle for the organization."""
    return await settings_service.get_signup_enabled(db, organization, current_user)


@router.put("/organization/signup-enabled", response_model=OrgSignupEnabledSchema)
@requires_permission('manage_settings')
async def update_org_signup_enabled(
    data: OrgSignupEnabledSchema,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Update the public signup enabled toggle for the organization."""
    return await settings_service.update_signup_enabled(db, organization, current_user, data)


@router.get("/organization/smtp", response_model=OrgSmtpSchema)
@requires_permission('manage_settings')
async def get_org_smtp(
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    return await settings_service.get_smtp(db, organization, current_user)


@router.put("/organization/smtp", response_model=OrgSmtpSchema)
@requires_permission('manage_settings')
async def update_org_smtp(
    data: OrgSmtpUpdate,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    return await settings_service.update_smtp(db, organization, current_user, data)


@router.post("/organization/smtp/test", response_model=dict)
@requires_permission('manage_settings')
async def test_org_smtp(
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    return await settings_service.test_smtp(db, organization, current_user)


# ---------------------------------------------------------------------------
# LDAP endpoints (org-scoped)
# ---------------------------------------------------------------------------

@router.get("/organization/ldap", response_model=OrgLdapSchema)
@requires_permission('manage_settings')
async def get_org_ldap(
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Get the org's LDAP configuration (bind_password is never returned)."""
    return await settings_service.get_ldap(db, organization, current_user)


@router.put("/organization/ldap", response_model=OrgLdapSchema)
@requires_permission('manage_settings')
async def update_org_ldap(
    data: OrgLdapUpdate,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Update the org's LDAP configuration."""
    return await settings_service.update_ldap(db, organization, current_user, data)


@router.post("/organization/ldap/test", response_model=dict)
@requires_permission('manage_settings')
async def test_org_ldap(
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Test the org's saved LDAP connection."""
    return await settings_service.test_ldap(db, organization, current_user)


# ---------------------------------------------------------------------------
# SSO endpoints (instance-level)
# ---------------------------------------------------------------------------

@router.get("/organization/sso", response_model=OrgSsoSchema)
@requires_permission('manage_settings')
async def get_org_sso(
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Get the SSO configuration (client secrets are never returned)."""
    return await settings_service.get_sso(db, organization, current_user)


@router.put("/organization/sso/google", response_model=OrgSsoSchema)
@requires_permission('manage_settings')
async def update_org_sso_google(
    data: OrgSsoGoogleUpdate,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Update Google OAuth settings."""
    return await settings_service.update_sso_google(db, organization, current_user, data)


@router.put("/organization/sso/oidc", response_model=OrgSsoSchema)
@requires_permission('manage_settings')
async def update_org_sso_oidc(
    data: OrgSsoOidcUpdate,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Update the full list of OIDC providers (Microsoft = provider named 'microsoft')."""
    return await settings_service.update_sso_oidc(db, organization, current_user, data)


@router.put("/organization/sso/auth-mode", response_model=OrgSsoSchema)
@requires_permission('manage_settings')
async def update_org_sso_auth_mode(
    data: OrgSsoAuthModeUpdate,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Set the auth mode: local_only | sso_only | hybrid."""
    return await settings_service.update_sso_auth_mode(db, organization, current_user, data)


# ---------------------------------------------------------------------------
# Hybrid feature-flag overrides (per-org override layer over env defaults)
# ---------------------------------------------------------------------------
import os
from sqlalchemy.orm.attributes import flag_modified
from app.settings.hybrid_flags import flags, UPGRADE_FLAGS, set_override


def _env_default(env_name: str) -> bool:
    """The pure-env value of a flag (ignores any process override)."""
    raw = os.environ.get(env_name)
    if raw is None:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _effective(env_name: str) -> bool:
    """Effective value via the flags singleton property (override > env)."""
    # Map env name -> HybridFlags property name (strip the HYBRID_ prefix).
    prop = env_name[len("HYBRID_"):] if env_name.startswith("HYBRID_") else env_name
    return bool(getattr(flags, prop, False))


@router.get("/organization/hybrid-flags")
@requires_permission('manage_settings')
async def get_hybrid_flags(
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """List the agent-upgrade hybrid flags with env default, per-org override and effective value."""
    settings = await settings_service.get_settings(db, organization, current_user)
    config = settings.config if isinstance(settings.config, dict) else {}
    overrides = config.get("hybrid_overrides") or {}
    if not isinstance(overrides, dict):
        overrides = {}

    rows = []
    for env_name, meta in UPGRADE_FLAGS.items():
        key = env_name[len("HYBRID_"):] if env_name.startswith("HYBRID_") else env_name
        override = overrides.get(env_name)
        rows.append({
            "key": key,
            "env_name": env_name,
            "label": meta["label"],
            "role": meta["role"],
            "default_env": _env_default(env_name),
            "override": (bool(override) if override is not None else None),
            "effective": _effective(env_name),
        })
    return rows


@router.put("/organization/hybrid-flags/{env_name}")
@requires_permission('manage_settings')
async def update_hybrid_flag(
    env_name: str,
    payload: dict,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Set or clear a per-org hybrid-flag override.

    Body {"enabled": true|false|null}. null clears the override (env default
    applies). Persists to config['hybrid_overrides'] and applies the override
    live to this process immediately.
    """
    if env_name not in UPGRADE_FLAGS:
        raise HTTPException(status_code=400, detail=f"Unknown hybrid flag: {env_name}")

    enabled = payload.get("enabled")
    if enabled is not None and not isinstance(enabled, bool):
        raise HTTPException(status_code=400, detail="'enabled' must be a boolean or null")

    settings = await settings_service.get_settings(db, organization, current_user)
    if settings.config is None:
        settings.config = {}
    config = settings.config
    overrides = config.get("hybrid_overrides")
    if not isinstance(overrides, dict):
        overrides = {}
        config["hybrid_overrides"] = overrides

    if enabled is None:
        overrides.pop(env_name, None)
    else:
        overrides[env_name] = bool(enabled)

    flag_modified(settings, "config")
    await db.commit()

    # Apply live to this process right away.
    set_override(env_name, enabled)

    meta = UPGRADE_FLAGS[env_name]
    key = env_name[len("HYBRID_"):] if env_name.startswith("HYBRID_") else env_name
    return {
        "key": key,
        "env_name": env_name,
        "label": meta["label"],
        "role": meta["role"],
        "default_env": _env_default(env_name),
        "override": (bool(enabled) if enabled is not None else None),
        "effective": _effective(env_name),
    }