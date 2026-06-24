"""POST /api/data_sources/from-file — turn an uploaded Excel/CSV into a Data Agent.

Takes an existing File (uploaded via POST /api/files), creates a `spreadsheet`
Connection + DataSource backed by an in-memory DuckDB engine, runs schema
discovery so each sheet/CSV becomes a queryable table, and returns the created
DataSource (same shape as POST /api/data_sources) plus its discovered tables[].

Schema discovery is fail-soft: if the file can't be read the data source is
still returned (with empty tables[]) rather than crashing the request — except
when the file itself is missing/unreadable up front, which is a 400.
"""

import json
import logging
import os
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import current_user
from app.core.permissions_decorator import requires_permission
from app.dependencies import get_async_db, get_current_organization
from app.models.connection import Connection
from app.models.data_source import DataSource
from app.models.domain_connection import domain_connection
from app.models.file import File as FileModel
from app.models.organization import Organization
from app.models.user import User
from app.services.data_source_service import DataSourceService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["data_sources"])
data_source_service = DataSourceService()


class DataSourceFromFileRequest(BaseModel):
    file_id: str
    data_source_name: Optional[str] = None
    sheet_names: Optional[List[str]] = None
    description: Optional[str] = None


def _resolve_upload_path(stored_path: str) -> Optional[str]:
    """Resolve the on-disk absolute path for an uploaded file, traversal-safe.

    Uploaded files live flat under <cwd>/uploads/files/<basename> (see
    routes/file.py). Returns the path if it exists, else None.
    """
    if not stored_path:
        return None
    base = os.path.basename(stored_path)
    candidate = os.path.join(os.getcwd(), "uploads", "files", base)
    if os.path.exists(candidate):
        return candidate
    rel = os.path.join(os.getcwd(), stored_path)
    if os.path.exists(rel):
        return rel
    if os.path.isabs(stored_path) and os.path.exists(stored_path):
        return stored_path
    return None


@router.post("/data_sources/from-file")
@requires_permission('create_data_source')
async def create_data_source_from_file(
    payload: DataSourceFromFileRequest,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    # ── 1. Fetch the File, org-scoped (404 if not owned by the org) ──────
    file_result = await db.execute(
        select(FileModel).filter(
            FileModel.id == payload.file_id,
            FileModel.organization_id == organization.id,
        )
    )
    file = file_result.scalar_one_or_none()
    if not file:
        raise HTTPException(status_code=404, detail="File not found")

    abs_path = _resolve_upload_path(file.path or "")
    if not abs_path:
        raise HTTPException(status_code=400, detail="File content is missing or unreadable")

    # Basic extension sanity (the client also validates on read).
    ext = os.path.splitext(abs_path)[1].lower()
    if ext not in {".xlsx", ".xlsm", ".xls", ".csv", ".tsv", ".txt"}:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Upload an Excel (.xlsx/.xls) or CSV file.",
        )

    # ── 2. Create the Connection (type='spreadsheet') ───────────────────
    config = {
        "file_id": str(file.id),
        "sheet_names": payload.sheet_names,
        # Resolved server-side path so the client reads without a DB lookup.
        "path": file.path,
    }

    # Auto-generate connection name as spreadsheet-N (mirrors create_data_source).
    count_result = await db.execute(
        select(func.count(Connection.id)).filter(
            Connection.organization_id == organization.id,
            Connection.type == "spreadsheet",
        )
    )
    existing_count = count_result.scalar() or 0
    connection = Connection(
        name=f"spreadsheet-{existing_count + 1}",
        type="spreadsheet",
        config=json.dumps(config),
        organization_id=str(organization.id),
        is_active=True,
        auth_policy="system_only",
    )
    db.add(connection)
    await db.flush()

    # ── 3. Create the DataSource + link via domain_connection ───────────
    ds_name = (payload.data_source_name or "").strip() or (file.filename or "Spreadsheet")
    data_source = DataSource(
        name=ds_name,
        organization_id=organization.id,
        is_public=False,
        is_active=True,
        use_llm_sync=False,
        owner_user_id=current_user.id,
        description=payload.description,
    )
    data_source.connections.append(connection)
    db.add(data_source)

    try:
        await db.commit()
        await db.refresh(data_source)
    except Exception as e:
        await db.rollback()
        # Duplicate name per org is the common case (uq_data_sources_org_name).
        raise HTTPException(
            status_code=409,
            detail=(
                f"A data source named '{ds_name}' already exists in this organization. "
                "Please choose a different name."
            ),
        )

    # Creator becomes a member with manage rights (mirrors create_data_source).
    await data_source_service._create_memberships(
        db, data_source, [current_user.id], permissions=["manage"]
    )

    # ── 4. Schema discovery (fail-soft) ─────────────────────────────────
    # Reuse the SAME canonical path the demo/normal flow uses:
    #   ConnectionService.refresh_schema -> ConnectionTable
    #   DataSourceService.sync_domain_tables_from_connection -> DataSourceTable
    try:
        from app.services.connection_service import ConnectionService

        # Reload data source with its connection eagerly loaded for the sync.
        ds_q = await db.execute(
            select(DataSource)
            .options(selectinload(DataSource.connections))
            .filter(DataSource.id == data_source.id)
        )
        data_source = ds_q.scalar_one()
        conn = data_source.connections[0]

        await ConnectionService().refresh_schema(
            db=db, connection=conn, current_user=current_user
        )
        await data_source_service.sync_domain_tables_from_connection(
            db=db,
            data_source=data_source,
            connection=conn,
            max_auto_select=9999,  # activate all sheets — small files
        )
        await db.commit()
    except Exception as e:
        logger.warning(
            "from-file: schema discovery failed for data_source %s (file %s): %s",
            data_source.id, payload.file_id, e,
        )
        try:
            await db.rollback()
        except Exception:
            pass

    # ── 5. Build the response: DataSourceSchema (+ tables[]) ─────────────
    ds_schema = await data_source_service.get_data_source(
        db, str(data_source.id), organization, current_user
    )

    try:
        tables = await data_source_service.get_data_source_schema(
            db,
            str(data_source.id),
            include_inactive=True,
            organization=organization,
            current_user=current_user,
        )
    except Exception as e:
        logger.warning("from-file: could not load tables for response: %s", e)
        tables = []

    # Return the exact DataSourceSchema shape plus the discovered tables[].
    body = json.loads(ds_schema.json()) if hasattr(ds_schema, "json") else dict(ds_schema)
    body["tables"] = [
        json.loads(t.json()) if hasattr(t, "json") else dict(t) for t in (tables or [])
    ]
    return body
