"""Autotrain HTTP surface.

POST /api/autotrain/from-file : take an already-uploaded flat file (csv or xlsx),
ingest it into `staging`, and auto-propose PENDING knowledge. Flag-gated
(HYBRID_AUTOTRAIN), approval-only (everything lands pending), source-agnostic
underneath. Excel files yield one or more tables (multi-sheet); each is ingested
+ autotrained. Re-drops are schema-contract checked (drift -> quarantine).
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_user
from app.dependencies import get_async_db, get_current_organization
from app.models.data_source import DataSource
from app.models.file import File
from app.models.ingest_batch import IngestBatch
from app.models.llm_model import LLMModel
from app.models.organization import Organization
from app.models.schema_contract import SchemaContract
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/autotrain", tags=["autotrain"])


class FromFileRequest(BaseModel):
    file_id: str
    data_source_id: str
    load_key: str = "replace"  # replace | period | append
    period: str | None = None


async def _check_contract(db, *, org_id, ds_id, logical, columns, load_key) -> dict:
    """Infer + diff the column contract for a logical dataset. Returns
    {"verdict","quarantine":bool,"changes":[...]} and upserts the contract.
    Drift -> quarantine (unless explicit replace)."""
    try:
        from app.services.ingest import contract as contract_mod

        new_c = {"columns": columns}
        active = (
            await db.execute(
                select(SchemaContract).where(
                    SchemaContract.organization_id == org_id,
                    SchemaContract.data_source_id == ds_id,
                    SchemaContract.logical_dataset == logical,
                    SchemaContract.active == True,  # noqa: E712
                    SchemaContract.deleted_at.is_(None),
                )
            )
        ).scalars().first()
        old_c = {"columns": active.columns} if active else None
        diff = contract_mod.diff_contracts(old_c, new_c)
        verdict = diff.get("verdict", "new")
        quarantine = verdict == "drift" and load_key != "replace"
        if not quarantine:
            if active is None:
                db.add(
                    SchemaContract(
                        id=str(uuid.uuid4()),
                        organization_id=org_id,
                        data_source_id=ds_id,
                        logical_dataset=logical,
                        version=1,
                        columns=new_c.get("columns", columns),
                        active=True,
                    )
                )
            elif verdict == "drift":
                active.columns = new_c.get("columns", columns)
                active.version = (active.version or 1) + 1
            await db.flush()
        return {"verdict": verdict, "quarantine": quarantine, "changes": diff.get("retyped", []) + diff.get("removed", [])}
    except Exception:
        logger.exception("contract check failed for %s", logical)
        return {"verdict": "error", "quarantine": False, "changes": []}


async def _ingest_one(
    db, *, organization, current_user, data_source, batch, table_name, df, content_hash, source_file, load_key, period, model
) -> dict:
    """Contract-check -> load to staging -> autotrain -> register one table. Returns a result dict."""
    from app.services.autotrain import orchestrator
    from app.services.ingest import gate, loader, tenant_schema

    # PER-ORG staging isolation: provision the org's dedicated schema + restricted
    # role ONCE before loading, then load/autotrain/register against that schema.
    # If the provisioning secret is unset, ensure_org_staging raises -> fall back
    # to the shared "staging" schema for load+autotrain and skip register (current
    # safe-off behavior).
    org_schema = tenant_schema.org_schema(organization.id)
    provisioned = False
    try:
        await asyncio.to_thread(tenant_schema.ensure_org_staging, organization.id)
        provisioned = True
    except Exception:
        logger.warning(
            "autotrain: per-org staging not provisioned (secret unset?) -> "
            "falling back to shared 'staging' schema, skipping register"
        )
        org_schema = "staging"

    g = gate.score_dataframe(df)
    cols = [{"name": str(c), "dtype": str(df[c].dtype)} for c in df.columns]
    contract = await _check_contract(
        db, org_id=organization.id, ds_id=data_source.id,
        logical=table_name, columns=cols, load_key=load_key,
    )
    if g.get("verdict") == "quarantine" or contract.get("quarantine"):
        return {"table": table_name, "quarantined": True, "gate": g, "contract": contract}

    rows = await asyncio.to_thread(
        loader.load_dataframe_to_staging,
        df, table_name, batch_id=batch.id, source_file=source_file,
        content_hash=content_hash, period=period, load_key=load_key,
        schema=org_schema,
    )
    if not rows:
        return {"table": table_name, "ok": False, "error": "0 rows loaded", "gate": g}

    safe = loader.safe_table_name(table_name)
    summary = await orchestrator.autotrain(
        db, organization=organization, data_source=data_source,
        table=safe, schema=org_schema, model=model,
    )
    # register so the agent can SELECT it. Skipped when per-org staging wasn't
    # provisioned (no secret) — no restricted role exists to scope the Connection.
    registered = None
    if provisioned:
        try:
            from app.services.ingest import register

            registered = await register.register_table(
                db, organization=organization, current_user=current_user,
                data_source=data_source, table=safe, columns=cols, no_rows=rows,
            )
        except Exception:
            logger.exception("register step failed for %s", safe)
    return {
        "table": safe, "ok": True, "rows": rows, "gate": g,
        "contract": contract, "autotrain": summary, "registered": bool(registered),
    }


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
    if ext not in {"csv", "tsv", "txt", "xlsx", "xls"}:
        raise HTTPException(
            status_code=400,
            detail=f"autotrain supports csv/xlsx (got .{ext}); pdf is a follow-on phase",
        )

    from app.services.ingest import stage

    batch = await stage.stage_file(
        db, organization_id=organization.id, filename=f.filename,
        path=f.path, file_id=f.id, data_source_id=ds.id,
    )
    if batch.status == "promoted" and batch.row_count:
        return {"reused": True, "batch_id": batch.id, "table": batch.target_table}

    model = (
        await db.execute(select(LLMModel).where(LLMModel.is_default == True))  # noqa: E712
    ).scalars().first()

    # build the table list (csv = 1, xlsx = N)
    tables: list[tuple[str, object]] = []
    if ext in {"csv", "tsv", "txt"}:
        from app.services.ingest import csv_reader

        df = csv_reader.read_csv(f.path)
        if df is not None and not df.empty:
            tables.append((batch.target_table, df))
    else:
        from app.services.ingest import excel_reader

        for t in excel_reader.read_excel(f.path, content_hash=batch.file_hash or ""):
            tname = f"{batch.target_table}_{t.get('table_name') or t.get('sheet') or 'sheet'}"
            tdf = t.get("df")
            if tdf is not None and not tdf.empty:
                tables.append((tname, tdf))

    if not tables:
        batch.status = "failed"
        await db.commit()
        return {"ok": False, "batch_id": batch.id, "error": "no readable tables in file"}

    results = []
    total_rows = 0
    for tname, df in tables:
        r = await _ingest_one(
            db, organization=organization, current_user=user, data_source=ds, batch=batch,
            table_name=tname, df=df, content_hash=batch.file_hash or "",
            source_file=f.filename or "upload", load_key=body.load_key,
            period=body.period, model=model,
        )
        results.append(r)
        total_rows += int(r.get("rows", 0) or 0)

    promoted = any(r.get("ok") for r in results)
    batch.status = "promoted" if promoted else "quarantined"
    batch.row_count = total_rows
    # drift baseline for the first table (best-effort). Also compare against the
    # most-recent PRIOR promoted baseline for the same logical dataset, if any.
    drift_verdict = None
    try:
        from app.services.ingest import drift

        first = next((t for _, t in [(n, d) for n, d in tables]), None)
        if first is not None:
            cols = [{"name": str(c), "dtype": str(first[c].dtype)} for c in first.columns]
            new_baseline = drift.make_baseline(batch.target_table, columns=cols)

            # find the prior promoted batch (same org + logical dataset) with a baseline
            try:
                prior = (
                    await db.execute(
                        select(IngestBatch)
                        .where(
                            IngestBatch.organization_id == organization.id,
                            IngestBatch.logical_dataset == batch.logical_dataset,
                            IngestBatch.status == "promoted",
                            IngestBatch.id != batch.id,
                        )
                        .order_by(IngestBatch.created_at.desc())
                    )
                ).scalars().all()
                prior_baseline = None
                for pb in prior:
                    cand = (pb.manifest or {}).get("baseline")
                    if cand:
                        prior_baseline = cand
                        break
                if prior_baseline:
                    drift_verdict = drift.compare_baseline(prior_baseline, new_baseline)
            except Exception:
                logger.exception("drift compare_baseline failed")

            man = dict(batch.manifest or {})
            man["baseline"] = new_baseline
            from sqlalchemy.orm.attributes import flag_modified

            batch.manifest = man
            flag_modified(batch, "manifest")
    except Exception:
        logger.exception("drift baseline failed")
    await db.commit()

    # M1: a 'promoted' batch can still have produced NO knowledge or hit errors —
    # surface that as 'degraded' instead of a silent ok=true.
    knowledge_errors = [
        e
        for r in results
        for e in (r.get("autotrain", {}).get("errors") or [])
    ]
    produced = any(
        (
            r.get("autotrain", {}).get("semantics")
            or r.get("autotrain", {}).get("metrics")
            or r.get("autotrain", {}).get("qa")
        )
        for r in results
    )
    degraded = bool(knowledge_errors) or not produced

    resp = {
        "ok": promoted,
        "batch_id": batch.id,
        "tables": len(tables),
        "rows": total_rows,
        "results": results,
        "degraded": degraded,
        "knowledge_errors": knowledge_errors,
        "note": (
            "Ingested, but some/all knowledge proposals failed — check logs"
            if degraded
            else "knowledge proposed as PENDING -> approve in Knowledge > Review"
        ),
    }
    if drift_verdict is not None:
        resp["drift"] = drift_verdict
    return resp
