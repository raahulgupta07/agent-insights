"""Teach Box routes — paste an analysis, the agent learns it.

POST /studios/{id}/teach          -> classify pasted text into spans + bind
                                     preview (NO writes; review-first).
POST /studios/{id}/teach/approve  -> persist the (optionally edited) spans to
                                     their surfaces, all born pending. Optional
                                     `train: true` kicks the studio auto-train.

Gated by flags.TEACH_BOX (404 when off). Editor/owner only. Mirrors the
auth/org-scope idiom of the other studio_* routes.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_user
from app.dependencies import get_async_db, get_current_organization
from app.models.user import User
from app.models.organization import Organization
from app.services.studio_access import resolve_studio_access
from app.settings.hybrid_flags import flags
from app.ai.packs import teach as teach_engine

router = APIRouter(tags=["studios"])


async def _require_editor(db: AsyncSession, studio_id: str, user: User) -> str:
    role = await resolve_studio_access(db, studio_id, user)
    if role is None:
        raise HTTPException(status_code=404, detail="Studio not found")
    if role not in {"owner", "editor"}:
        raise HTTPException(status_code=403, detail="Editor or owner role required")
    return role


def _guard():
    if not flags.TEACH_BOX:
        raise HTTPException(status_code=404, detail="Teach Box not enabled")


@router.post("/studios/{studio_id}/teach")
async def teach_classify(
    studio_id: str,
    body: Dict[str, Any],
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Classify pasted text into reviewable spans (skill / instruction / data
    rule / knowledge) with a per-skill bind preview. Writes nothing."""
    _guard()
    await _require_editor(db, studio_id, current_user)
    text = str((body or {}).get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="'text' is required")
    if len(text) > 20000:
        text = text[:20000]

    cols = await teach_engine.studio_columns(db, studio_id)
    col_names = [c.get("name") for c in cols if c.get("name")]
    spans = await teach_engine.classify(db, organization, text, column_names=col_names)
    if not spans:
        return {"ok": True, "spans": [], "note": "no teachable spans detected"}
    preview = await teach_engine.preview_spans(db, studio_id, spans)
    return {"ok": True, "spans": preview, "count": len(preview)}


@router.post("/studios/{studio_id}/teach/approve")
async def teach_approve(
    studio_id: str,
    body: Dict[str, Any],
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Persist the approved spans (born pending behind the review gate). Body:
    {spans: [...], train: bool?}. Returns a per-surface created summary."""
    _guard()
    await _require_editor(db, studio_id, current_user)
    spans = (body or {}).get("spans")
    if not isinstance(spans, list) or not spans:
        raise HTTPException(status_code=400, detail="'spans' (non-empty list) is required")

    summary = await teach_engine.apply_spans(db, organization, studio_id, spans)

    kicked = False
    if (body or {}).get("train"):
        try:
            from app.ai.knowledge import train_orchestrator
            train_orchestrator.start_training(
                str(studio_id), str(organization.id), str(current_user.id)
            )
            kicked = True
        except Exception:
            kicked = False

    return {"ok": True, "created": summary, "train_kicked": kicked}


@router.get("/studios/{studio_id}/teach/template")
async def teach_template(
    studio_id: str,
    fmt: str = "md",
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Download a blank teach template to fill in offline. `fmt=md` (default) or
    `fmt=xlsx`. Writes nothing."""
    _guard()
    await _require_editor(db, studio_id, current_user)

    from app.ai.packs.teach_template import build_template_md, build_template_xlsx

    if fmt == "md":
        return Response(
            content=build_template_md(),
            media_type="text/markdown",
            headers={
                "Content-Disposition": 'attachment; filename="city-agent-teach-template.md"'
            },
        )
    if fmt == "xlsx":
        return Response(
            content=build_template_xlsx(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": 'attachment; filename="city-agent-teach-template.xlsx"'
            },
        )
    raise HTTPException(status_code=400, detail="unsupported fmt (use 'md' or 'xlsx')")


@router.post("/studios/{studio_id}/teach/upload")
async def teach_upload(
    studio_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Upload a filled template (or any supported doc), parse it to text, then run
    the SAME classify+preview pipeline as `teach_classify`. Writes nothing."""
    _guard()
    await _require_editor(db, studio_id, current_user)

    from app.ai.packs.teach_template import parse_upload

    raw = await file.read()
    if len(raw) > 2 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="file too large (max 2MB)")
    try:
        text = parse_upload(file.filename, raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="unsupported file type")

    cols = await teach_engine.studio_columns(db, studio_id)
    col_names = [c.get("name") for c in cols if c.get("name")]
    spans = await teach_engine.classify(db, organization, text, column_names=col_names)
    if not spans:
        return {
            "ok": True,
            "spans": [],
            "count": 0,
            "source_chars": len(text),
            "note": "no teachable spans detected",
        }
    preview = await teach_engine.preview_spans(db, studio_id, spans)
    return {
        "ok": True,
        "spans": preview,
        "count": len(preview),
        "source_chars": len(text),
    }
