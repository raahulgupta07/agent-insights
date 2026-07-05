from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.dependencies import get_async_db, get_current_organization
from app.models.user import User
from app.models.organization import Organization
from app.core.auth import current_user
from app.core.permissions_decorator import requires_permission
from app.services.llm_service import LLMService
from app.services.organization_settings_service import OrganizationSettingsService
from sqlalchemy.orm.attributes import flag_modified
from app.schemas.llm_schema import (
    LLMProviderSchema,
    LLMProviderCreate,
    LLMProviderUpdate,
    LLMProviderTestConnection,
    LLMModelSchema,
    LLMModelCreate,
    LLMModelUpdate,
    LLMModelSchemaWithProvider
)
from app.settings.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["llm"])
llm_service = LLMService()
org_settings_service = OrganizationSettingsService()

# Org-level Agent Defaults are stored in organization_settings.config under
# these three keys (JSON column, merged in place like the hybrid_overrides).
_DEFAULTS_KEYS = {
    "analysis": "default_analysis_model_id",
    "train": "default_train_model_id",
    "router": "default_router_model_id",
}


def _read_defaults(config: dict) -> dict:
    config = config if isinstance(config, dict) else {}
    return {k: config.get(ckey) for k, ckey in _DEFAULTS_KEYS.items()}

@router.get("/llm/available_providers", response_model=list[dict])
@requires_permission('manage_llm')
async def get_available_providers(
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization)
):
    return await llm_service.get_available_providers(db, organization, current_user)

@router.get("/llm/available_models", response_model=list[dict])
@requires_permission('manage_llm')
async def get_available_models(
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization)
):
    return await llm_service.get_available_models(db, organization, current_user)

@router.post("/llm/test_connection", response_model=dict)
@requires_permission('manage_llm')
async def test_connection(
    provider: LLMProviderTestConnection,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization)
):
    try:
        return await llm_service.test_connection(db, organization, current_user, provider)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("LLM test_connection route error: %s", e, exc_info=True)
        return {"success": False, "message": str(e)}

@router.get("/llm/providers", response_model=List[LLMProviderSchema])
@requires_permission('manage_llm')
async def get_providers(
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization)
):
    """Get all LLM providers for the organization"""
    return await llm_service.get_providers(db, organization, current_user)

@router.post("/llm/providers", response_model=LLMProviderSchema)
@requires_permission('manage_llm')
async def create_provider(
    provider: LLMProviderCreate,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization)
):
    """Create a new custom LLM provider"""
    return await llm_service.create_provider(db, organization, current_user, provider)


@router.put("/llm/providers/{provider_id}", response_model=LLMProviderSchema)
@requires_permission('manage_llm')
async def update_provider(
    provider_id: str,
    provider: LLMProviderUpdate,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization)
):
    """Update provider settings"""
    return await llm_service.update_provider(db, organization, current_user, provider_id, provider)

@router.delete("/llm/providers/{provider_id}")
@requires_permission('manage_llm')
async def delete_provider(
    provider_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization)
):
    """Delete a custom provider (preset providers cannot be deleted)"""
    return await llm_service.delete_provider(db, organization, current_user, provider_id)

@router.get("/llm/key_status", response_model=dict)
async def key_status(
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization)
):
    """Whether the org's LLM providers have a usable API key — drives the
    'Add your API key' banner on the LLM settings page."""
    return await llm_service.get_key_status(db, organization, current_user)

@router.post("/llm/models/{model_id}/test", response_model=dict)
@requires_permission('manage_llm')
async def test_model(
    model_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization)
):
    """Health-check a single model (1-token ping). Returns success + latency."""
    try:
        return await llm_service.test_model(db, organization, current_user, model_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("LLM test_model route error: %s", e, exc_info=True)
        return {"success": False, "message": str(e), "id": model_id}

@router.get("/llm/models", response_model=List[LLMModelSchemaWithProvider])
async def get_models(
    is_enabled: bool = None,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization)
):
    """Get all LLM models, optionally filtered by status"""
    return await llm_service.get_models(db, organization, current_user, is_enabled)

@router.post("/llm/models", response_model=LLMModelSchema)
@requires_permission('manage_llm')
async def create_model(
    model: LLMModelCreate,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization)
):
    """Create a new custom model"""
    return await llm_service.create_model(db, organization, current_user, model)

@router.patch("/llm/models/{model_id}")
@requires_permission('manage_llm')
async def update_model(
    model_id: str,
    model: LLMModelUpdate,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization)
):
    """Update model settings"""
    return await llm_service.update_model(db, organization, current_user, model_id, model)

@router.delete("/llm/models/{model_id}")
@requires_permission('manage_llm')
async def delete_model(
    model_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization)
):
    """Delete a custom model (preset models cannot be deleted)"""
    return await llm_service.delete_model(db, organization, current_user, model_id)

@router.post("/llm/providers/{provider_id}/toggle")
@requires_permission('manage_llm')
async def toggle_provider(
    provider_id: str,
    enabled: bool,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization)
):
    """Enable/disable a provider"""
    return await llm_service.toggle_provider(db, organization, current_user, provider_id, enabled)

@router.post("/llm/models/{model_id}/toggle")
@requires_permission('manage_llm')
async def toggle_model(
    model_id: str,
    enabled: bool,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization)
):
    """Enable/disable a model"""
    return await llm_service.toggle_model(db, organization, current_user, model_id, enabled)

@router.post("/llm/models/{model_id}/set_default")
@requires_permission('manage_llm')
async def set_default_model(
    model_id: str,
    small: bool = False,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization)
):
    """Set a model as the default model for the organization. Use small=true for small default."""
    return await llm_service.set_default_model(db, current_user, organization, model_id, small=small)


# ---------------------------------------------------------------------------
# Org-level Agent Defaults (analysis / training / router models)
# Persisted in organization_settings.config keys default_analysis_model_id /
# default_train_model_id / default_router_model_id. Consumed by the LLM
# settings screen; the training default is wired into train_orchestrator.
# ---------------------------------------------------------------------------

@router.get("/llm/defaults", response_model=dict)
async def get_llm_defaults(
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Read the org's default analysis/train/router models (null when unset)."""
    try:
        settings = await org_settings_service.get_settings(db, organization, current_user)
        config = settings.config if isinstance(settings.config, dict) else {}
    except Exception as e:  # noqa: BLE001
        logger.error("get_llm_defaults error: %s", e, exc_info=True)
        config = {}
    return _read_defaults(config)


@router.put("/llm/defaults", response_model=dict)
@requires_permission('manage_llm')
async def update_llm_defaults(
    payload: dict,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Persist the org's default analysis/train/router models.

    Body {analysis?, train?, router?} — only supplied keys are updated; other
    config keys are preserved (merge). A null/blank value clears that default.
    Fail-soft: returns the saved {analysis, train, router}.
    """
    try:
        settings = await org_settings_service.get_settings(db, organization, current_user)
        if settings.config is None:
            settings.config = {}
        config = settings.config

        for k, ckey in _DEFAULTS_KEYS.items():
            if k not in payload:
                continue
            val = payload.get(k)
            if val is None or val == "":
                config.pop(ckey, None)
            else:
                config[ckey] = str(val)

        flag_modified(settings, "config")
        await db.commit()
        return _read_defaults(config)
    except Exception as e:  # noqa: BLE001
        logger.error("update_llm_defaults error: %s", e, exc_info=True)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
        raise HTTPException(status_code=500, detail="Could not save agent defaults")
