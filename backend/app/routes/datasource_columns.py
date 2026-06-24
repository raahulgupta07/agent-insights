"""
Column-description editor — set/update per-column human descriptions on a
data source's tables.

The agent already READS these descriptions from
``DataSourceTable.columns[].description`` (see
``app/ai/context/sections/tables_schema_section.py`` + ``prompt_formatters.py``).
Until now there was no WRITE API for them (only direct SQL). This self-contained
router adds GET + PUT endpoints, scoped to the requesting organization.

Mounted in ``backend/main.py`` with ``prefix="/api"`` (paths below already start
with ``/data_sources``).

Auth/permission/db-session style mirrors ``app/routes/data_source.py``: the
table-schema edit routes there (``update_schema`` / ``update_tables_status`` /
``bulk_update_tables`` — which also mutate ``DataSourceTable``) all use
``@requires_resource_permission('data_source', 'view_schema')``. There is NO
``update_data_source`` permission string in ``permissions_registry.py``;
``view_schema`` is the verified-correct grant for editing table/column metadata.
"""

from typing import Dict, Optional, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.dependencies import get_async_db, get_current_organization
from app.core.auth import current_user
from app.core.permissions_decorator import requires_resource_permission
from app.models.user import User
from app.models.organization import Organization
from app.models.data_source import DataSource
from app.models.datasource_table import DataSourceTable

router = APIRouter(tags=["data_sources"])


class UpdateColumnDescriptionsRequest(BaseModel):
    # {"<column name>": "<description>", ...}
    descriptions: Dict[str, str]


async def _load_table(
    db: AsyncSession,
    data_source_id: str,
    table_id: str,
    organization: Organization,
) -> DataSourceTable:
    """Load a DataSourceTable, verifying it belongs to the data source AND the org.

    Org ownership is enforced by joining to DataSource on organization_id (same
    pattern as data_source_service: ``DataSource.organization_id == organization.id``).
    """
    result = await db.execute(
        select(DataSourceTable)
        .join(DataSource, DataSourceTable.datasource_id == DataSource.id)
        .filter(
            DataSourceTable.id == table_id,
            DataSourceTable.datasource_id == data_source_id,
            DataSource.organization_id == organization.id,
        )
    )
    table = result.scalar_one_or_none()
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")
    return table


def _columns_view(columns: Optional[list]) -> list:
    """Project the stored columns JSON to {name, dtype, description} for the editor."""
    out = []
    for col in (columns or []):
        if not isinstance(col, dict):
            continue
        out.append(
            {
                "name": col.get("name"),
                "dtype": col.get("dtype"),
                "description": col.get("description"),
            }
        )
    return out


@router.get("/data_sources/{data_source_id}/tables/{table_id}/columns", response_model=dict)
@requires_resource_permission('data_source', 'view_schema')
async def get_table_columns(
    data_source_id: str,
    table_id: str,
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user),
):
    """Return the current columns (name, dtype, description) for the editor to load."""
    table = await _load_table(db, data_source_id, table_id, organization)
    return {"columns": _columns_view(table.columns)}


@router.put("/data_sources/{data_source_id}/tables/{table_id}/columns", response_model=dict)
@requires_resource_permission('data_source', 'view_schema')
async def update_table_column_descriptions(
    data_source_id: str,
    table_id: str,
    payload: UpdateColumnDescriptionsRequest,
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(current_user),
):
    """Set/update per-column human descriptions on a data source's table.

    Iterates the table's ``columns`` JSON list; for each col whose ``name`` is in
    the payload, sets ``col['description']``. Other columns are left untouched.
    A NEW list is assigned and ``flag_modified`` called so SQLAlchemy persists the
    JSON mutation (same idiom used across this repo, e.g. studio_bootstrap.py /
    organization_settings_service.py).
    """
    table = await _load_table(db, data_source_id, table_id, organization)

    descriptions = payload.descriptions or {}
    existing = table.columns or []

    new_columns: list = []
    updated = 0
    for col in existing:
        if isinstance(col, dict):
            col = dict(col)  # shallow copy so we assign a fresh list/dicts
            name = col.get("name")
            if name in descriptions:
                col["description"] = descriptions[name]
                updated += 1
        new_columns.append(col)

    table.columns = new_columns
    flag_modified(table, "columns")
    await db.commit()
    await db.refresh(table)

    return {"updated": updated, "columns": _columns_view(table.columns)}
