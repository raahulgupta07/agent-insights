from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Any, Dict
from app.schemas.prompt_schema import PromptCreate, PromptUpdate, PromptResponse
from app.services.prompt_service import PromptService
from app.services.prompt_run import render_prompt_template
from app.core.auth import current_user
from app.core.permissions_decorator import requires_permission
from app.models.prompt import Prompt
from app.models.user import User
from app.models.organization import Organization
from app.dependencies import get_async_db, get_current_organization

router = APIRouter()
prompt_service = PromptService()

@router.post("/prompts", response_model=PromptResponse)
@requires_permission('create_reports')
async def create_prompt(
    prompt: PromptCreate,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization)
):
    return await prompt_service.create_prompt(db, prompt, current_user, organization)

@router.get("/prompts", response_model=List[PromptResponse])
async def read_prompts(
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization)
):
    return await prompt_service.get_prompts(db, skip=skip, limit=limit, current_user=current_user, organization=organization)

@router.get("/prompts/{prompt_id}", response_model=PromptResponse)
async def read_prompt(
    prompt_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization)
):
    # #555: READ visibility scoped to agent membership (get_prompt_visible).
    prompt = await prompt_service.get_prompt_visible(db, prompt_id, current_user, organization)
    if prompt is None:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return prompt

@router.put("/prompts/{prompt_id}", response_model=PromptResponse)
@requires_permission('update_reports', model=Prompt, owner_only=True)
async def update_prompt(
    prompt_id: str,
    prompt: PromptUpdate,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization)
):
    updated_prompt = await prompt_service.update_prompt(db, prompt_id, prompt, current_user, organization)
    if updated_prompt is None:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return updated_prompt

@router.delete("/prompts/{prompt_id}", response_model=PromptResponse)
@requires_permission('delete_reports', model=Prompt, owner_only=True)
async def delete_prompt(
    prompt_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization)
):
    deleted_prompt = await prompt_service.delete_prompt(db, prompt_id, current_user, organization)
    if deleted_prompt is None:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return deleted_prompt


# ── PARAM_TEMPLATES (feature, flag `flags.PARAM_TEMPLATES`) ───────────────────
# Turn a saved Prompt with {{name}} placeholders into a runnable report. Entirely
# additive + flag-gated: when the flag is OFF the endpoint 404s, so the API surface
# is byte-identical for existing clients.

class PromptInstantiateBody(BaseModel):
    values: Dict[str, Any] = {}
    data_sources: Optional[List[str]] = None
    title: Optional[str] = None


class PromptInstantiateResponse(BaseModel):
    report_id: str
    rendered_prompt: str


def _data_sources_from_mentions(mentions) -> List[str]:
    """Best-effort: pull data-source ids out of a saved prompt's `mentions`.

    `mentions` is a free-form JSON list (typically `[{name, items:[...]}]`). We only
    collect ids from items that look like a data-source reference; anything else is
    ignored. Fail-soft: never raises."""
    ids: List[str] = []
    try:
        for group in (mentions or []):
            if not isinstance(group, dict):
                continue
            name = str(group.get("name", "")).upper()
            items = group.get("items") or []
            is_ds_group = "DATA SOURCE" in name or "DATA SOURCES" in name
            for it in items:
                if not isinstance(it, dict):
                    continue
                if is_ds_group or it.get("type") == "data_source":
                    _id = it.get("id")
                    if _id:
                        ids.append(str(_id))
    except Exception:
        return []
    # de-dupe, preserve order
    seen = set()
    out = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


@router.post("/prompts/{prompt_id}/instantiate", response_model=PromptInstantiateResponse)
@requires_permission('create_reports')
async def instantiate_prompt(
    prompt_id: str,
    body: PromptInstantiateBody,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    from app.settings.hybrid_flags import flags
    if not flags.PARAM_TEMPLATES:
        # OFF -> endpoint invisible / byte-identical API surface for existing clients.
        raise HTTPException(status_code=404, detail="Not found")

    prompt = await prompt_service.get_prompt(db, prompt_id, current_user, organization)
    if prompt is None:
        raise HTTPException(status_code=404, detail="Prompt not found")

    try:
        rendered = render_prompt_template(
            prompt.text or "",
            prompt.parameters or [],
            body.values or {},
        )
    except ValueError as e:
        # Missing required parameter(s) -> 400 with a clear message.
        raise HTTPException(status_code=400, detail=str(e))

    # data_sources: explicit body wins, else derive from the prompt's mentions.
    data_sources = body.data_sources
    if data_sources is None:
        data_sources = _data_sources_from_mentions(prompt.mentions)

    # Create the report via the app's existing report-create path (READ-ONLY use of
    # its signature — we import and call, never modify it).
    from app.services.report_service import ReportService
    from app.schemas.report_schema import ReportCreate
    report_service = ReportService()
    report_create = ReportCreate(
        title=body.title or prompt.title or "untitled report",
        data_sources=data_sources or [],
    )
    report = await report_service.create_report(db, report_create, current_user, organization)

    # Return the id + rendered text; the frontend navigates to the report and sends
    # the rendered prompt as the first completion (mirrors the normal create flow).
    return PromptInstantiateResponse(report_id=str(report.id), rendered_prompt=rendered)