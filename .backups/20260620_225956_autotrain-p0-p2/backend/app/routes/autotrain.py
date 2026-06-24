"""Autotrain HTTP surface.

POST /api/autotrain/from-file : take an already-uploaded flat file, ingest it
into `staging`, and auto-propose PENDING knowledge. Flag-gated (HYBRID_AUTOTRAIN),
approval-only (everything lands pending), source-agnostic underneath.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_user
from app.dependencies import get_async_db, get_current_organization
from app.models.data_source import DataSource
from app.models.file import File
from app.models.llm_model import LLMModel
from app.models.organization import Organization
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/autotrain", tags=["autotrain"])


class FromFileRequest(BaseModel):
    file_id: str
    data_source_id: str
    load_key: str = "replace"  # replace | period | append
    period: str | None = None


@router.post("/from-file")
async def autotrain_from_file(
    body: FromFileRequest,
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(current_user),
):
    from app.settings.hybrid_flags import flags

    if not flags.AUTOTRAIN:
        raise HTTPException(status_code=403, detail="autotrain is disabled (HYBRID_AUTOTRAIN off)")

    f = (
        await db.execute(
            select(File).where(File.id == body.file_id, File.organization_id == organization.id)
        )
    ).scalars().first()
    if f is None:
        raise HTTPException(status_code=404, detail="file not found")

    ds = (
        await db.execute(
            select(DataSource).where(
                DataSource.id == body.data_source_id,
                DataSource.organization_id == organization.id,
            )
        )
    ).scalars().first()
    if ds is None:
        raise HTTPException(status_code=404, detail="data_source not found")

    ext = (f.filename or "").lower().rsplit(".", 1)[-1]
    if ext not in {"csv", "tsv", "txt"}:
        raise HTTPException(
            status_code=400,
            detail=f"autotrain MVP supports csv only (got .{ext}); xlsx/pdf are follow-on phases",
        )

    from app.services.ingest import csv_reader, gate, loader, stage

    batch = await stage.stage_file(
        db,
        organization_id=organization.id,
        filename=f.filename,
        path=f.path,
        file_id=f.id,
        data_source_id=ds.id,
    )
    if batch.status == "promoted" and batch.row_count:
        return {"reused": True, "batch_id": batch.id, "table": batch.target_table}

    df = csv_reader.read_csv(f.path)
    g = gate.score_dataframe(df)
    if g.get("verdict") == "quarantine":
        batch.status = "quarantined"
        batch.quarantine_reason = ", ".join(g.get("issues") or []) or "low quality"
        await db.commit()
        return {"quarantined": True, "batch_id": batch.id, "gate": g}

    rows = loader.load_dataframe_to_staging(
        df,
        batch.target_table,
        batch_id=batch.id,
        source_file=f.filename or "upload",
        content_hash=batch.file_hash or "",
        period=body.period,
        load_key=body.load_key,
    )
    batch.target_table = loader.safe_table_name(batch.target_table)
    batch.status = "promoted" if rows else "failed"
    batch.row_count = rows
    await db.commit()

    if not rows:
        return {"ok": False, "batch_id": batch.id, "error": "load produced 0 rows", "gate": g}

    # default org model so codex uses the real LLM (None -> heuristic fallback)
    model = (
        await db.execute(
            select(LLMModel).where(LLMModel.is_default == True)  # noqa: E712
        )
    ).scalars().first()

    from app.services.autotrain import orchestrator

    summary = await orchestrator.autotrain(
        db,
        organization=organization,
        data_source=ds,
        table=batch.target_table,
        schema="staging",
        model=model,
    )
    return {
        "ok": True,
        "batch_id": batch.id,
        "table": batch.target_table,
        "rows": rows,
        "gate": g,
        "autotrain": summary,
        "note": "knowledge proposed as PENDING -> approve in Knowledge > Review",
    }
