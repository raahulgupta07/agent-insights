"""Compliance & data-integrity scan (Feature 4) — ON-DEMAND, advisory, read-only.

Self-contained router exposing a single endpoint that runs DETERMINISTIC
(code, not LLM) checks against a data source:

  POST /api/data_sources/{data_source_id}/compliance/scan
      body (optional): {"phone_column": "...", "required_fields": [...],
                        "table_name": "..."}

  -> dedup  (rows sharing a contact phone = possible duplicates)
  -> quality (required fields missing -> per-field counts + quality score)
  -> summary (compliance overview for the UI)

It does NOT touch the ingest pipeline. It reuses the SAME data-source client
path the agent / knowledge route use to run ad-hoc SQL
(`DataSource.get_client().aexecute_query(...)`), so the aggregations run against
the live DuckDB engine, not pandas-on-disk. Every query is a single read-only
SELECT/COUNT/GROUP BY.

Gated behind `getattr(flags, 'COMPLIANCE_GATE', False)` (a NEW flag — see the
delivery notes: the existing GOVERNANCE flag gates per-table prompt metadata
injection, a different mechanism, so this uses its own gate).

NOTE: deliberately NO `from __future__ import annotations` — combined with the
`@requires_resource_permission` wrapper, stringized body annotations make
FastAPI mis-read the pydantic body as a query param (known repo landmine).
"""

from typing import Optional, List

from fastapi import APIRouter, Depends, Body
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_async_db, get_current_organization
from app.models.user import User
from app.models.organization import Organization
from app.models.data_source import DataSource
from app.core.auth import current_user
from app.core.permissions_decorator import requires_resource_permission
from app.errors.app_error import AppError
from app.settings.hybrid_flags import flags
from app.ai.compliance.scanner import scan_data_source


router = APIRouter(tags=["compliance"])


class ComplianceScanRequest(BaseModel):
    phone_column: Optional[str] = None
    required_fields: Optional[List[str]] = None
    table_name: Optional[str] = None


@router.post("/data_sources/{data_source_id}/compliance/scan", response_model=dict)
@requires_resource_permission("data_source", "view")
async def run_compliance_scan(
    data_source_id: str,
    payload: ComplianceScanRequest = Body(default=ComplianceScanRequest()),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(current_user),
    organization: Organization = Depends(get_current_organization),
):
    """Run an on-demand, read-only compliance & data-integrity scan.

    Flag-gated (`COMPLIANCE_GATE`); returns 200 `{disabled: True}` when off so
    the UI can hide the feature without treating it as an error.
    """
    if not getattr(flags, "COMPLIANCE_GATE", False):
        return {"disabled": True, "data_source_id": data_source_id}

    # Load the data source (org-scoped). connections is lazy="selectin" -> the
    # M:N connections needed by get_client() are eager-loaded with this query.
    res = await db.execute(
        select(DataSource).where(
            DataSource.id == data_source_id,
            DataSource.organization_id == organization.id,
        )
    )
    data_source = res.scalar_one_or_none()
    if data_source is None:
        raise AppError.not_found("data_source.not_found", "Data source not found")

    # scan_data_source never raises: per-check failures are isolated, and client
    # / schema failures come back as {ok: False, error: ...}.
    report = await scan_data_source(
        data_source,
        phone_column=payload.phone_column,
        required_fields=payload.required_fields,
        table_name=payload.table_name,
    )
    return report
