"""Pipeline v1 (P8): HTTP surface for the doc-driven verified-golden pipeline.

Two endpoints (flag-gated, fail-soft):

  POST /api/studios/{studio_id}/pipeline/build-goldens
      body {file_id, data_source_id}
      parse logic doc -> registry -> generate -> EVAL GATE -> save approved as
      verified goldens + publish definitions as instructions. Returns the
      approved/held breakdown.

  POST /api/studios/{studio_id}/pipeline/recorrect
      body {instruction, data_source_id}
      correction loop: update one definition -> regenerate -> re-eval -> if it
      matches, update its saved golden.
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_user
from app.dependencies import get_async_db, get_current_organization
from app.models.organization import Organization
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(tags=["pipeline"])


class BuildGoldensRequest(BaseModel):
    file_id: str
    data_source_id: str


class RecorrectRequest(BaseModel):
    instruction: str
    data_source_id: str


def _gate():
    from app.settings.hybrid_flags import flags
    if not flags.VERIFIED_GOLDENS:
        raise HTTPException(status_code=404, detail="verified-goldens pipeline disabled")


def _resolve_path(stored: str) -> Optional[str]:
    if not stored:
        return None
    base = os.path.basename(stored)
    for cand in (os.path.join(os.getcwd(), "uploads", "files", base),
                 os.path.join(os.getcwd(), stored), stored):
        if cand and os.path.exists(cand):
            return cand
    return None


async def _save_golden(db, *, organization, data_source_id, name, sql, expected):
    """Upsert a verified golden into the query library (approved + is_golden)."""
    from app.models.query_library import QueryLibraryItem

    existing = (
        await db.execute(
            select(QueryLibraryItem).where(
                QueryLibraryItem.organization_id == str(organization.id),
                QueryLibraryItem.data_source_id == str(data_source_id),
                QueryLibraryItem.name == name,
            )
        )
    ).scalar_one_or_none()
    desc = f"Verified against ground truth (expected {expected})."
    if existing is None:
        db.add(QueryLibraryItem(
            id=str(uuid.uuid4()), organization_id=str(organization.id),
            data_source_id=str(data_source_id), name=name, description=desc,
            sql_text=sql, source="verified_pipeline", status="approved",
            is_golden=True, verified_count=1,
        ))
    else:
        existing.sql_text = sql
        existing.description = desc
        existing.status = "approved"
        existing.is_golden = True
        existing.verified_count = (existing.verified_count or 0) + 1


@router.post("/studios/{studio_id}/pipeline/build-goldens")
async def build_goldens(
    studio_id: str,
    payload: BuildGoldensRequest,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    _gate()
    from app.models.file import File as FileModel
    from app.services.ingest import logic_parser as L
    from app.services.train import (
        registry as R, golden_gen as G, eval_gate as E,
        definition_instructions as DI,
    )
    from app.models.agent_definition import AgentDefinition

    file = (
        await db.execute(
            select(FileModel).where(
                FileModel.id == payload.file_id,
                FileModel.organization_id == organization.id,
            )
        )
    ).scalar_one_or_none()
    if file is None:
        raise HTTPException(status_code=404, detail="file not found")
    path = _resolve_path(file.path or "")
    if not path:
        raise HTTPException(status_code=400, detail="file content missing")

    # 1) parse -> 2) registry
    triples = L.parse_logic_doc(path)
    reg = await R.upsert_from_triples(
        db, organization=organization, triples=triples,
        data_source_id=payload.data_source_id, studio_id=studio_id,
        source_doc=file.filename,
    )
    # 3) generate for all defs with a predicate
    defs = (
        await db.execute(
            select(AgentDefinition).where(
                AgentDefinition.organization_id == str(organization.id),
                AgentDefinition.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    cands = await G.generate_for_definitions(
        db, data_source_id=payload.data_source_id, definitions=defs,
    )
    # 4) EVAL GATE
    res = await E.evaluate(db, data_source_id=payload.data_source_id, candidates=cands)

    # 5) approve + save matches; publish definitions as instructions
    by_id = {str(d.id): d for d in defs}
    for c in res["approved"]:
        d = by_id.get(c["definition_id"])
        if d is not None:
            d.status = "approved"
        await _save_golden(
            db, organization=organization, data_source_id=payload.data_source_id,
            name=c["name"], sql=c["sql"], expected=c["expected"],
        )
    await db.commit()
    pub = await DI.sync_definitions_to_instructions(
        db, organization=organization, data_source_id=payload.data_source_id,
    )

    return {
        "triples": len(triples),
        "definitions": reg,
        "approved": [{"name": c["name"], "actual": c["actual"], "expected": c["expected"]}
                     for c in res["approved"]],
        "held": [{"name": c["name"], "verdict": c["verdict"],
                  "actual": c.get("actual"), "expected": c.get("expected")}
                 for c in res["held"]],
        "instructions_published": pub.get("published", 0),
    }


@router.post("/studios/{studio_id}/pipeline/recorrect")
async def recorrect(
    studio_id: str,
    payload: RecorrectRequest,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    from app.settings.hybrid_flags import flags
    if not flags.QUERY_CORRECTION:
        raise HTTPException(status_code=404, detail="query correction disabled")
    from app.services.train import corrector as C

    res = await C.apply_correction(
        db, organization=organization, data_source_id=payload.data_source_id,
        instruction=payload.instruction,
    )
    # if it now matches, persist the corrected golden
    if res.get("verdict") == "match" and res.get("sql"):
        await _save_golden(
            db, organization=organization, data_source_id=payload.data_source_id,
            name=res["definition"], sql=res["sql"], expected=res["expected"],
        )
        await db.commit()
    return res
