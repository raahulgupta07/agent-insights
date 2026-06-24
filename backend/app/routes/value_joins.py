"""Value-overlap JOIN mining route (Kepler P6 extension).

  POST /api/data_sources/{data_source_id}/mine-value-joins
       -> samples distinct values of candidate key columns across the data
          source's tables and proposes pending TableEdge rows when two columns
          share a high fraction of values. Unlike the SQL-history join miner,
          this works on a brand-new connector with ZERO query history.

Mined edges land ``status='pending'`` / ``source='value_overlap'`` — same
approval gate as the existing miner; only ``status='approved'`` edges reach the
agent. Self-gates on ``flags.JOIN_GRAPH`` (returns {disabled:True} when off).

Never 500s — fail-soft to {ok:False,error,mined:0}.

NOTE: deliberately NO ``from __future__ import annotations`` (body+permission
route landmine: stringized annotations make FastAPI mis-read params).
"""

from fastapi import APIRouter, Depends
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
from app.ai.knowledge.join_miner import mine_value_overlap_edges


router = APIRouter(tags=["joins"])


async def _load_ds(db, data_source_id, organization):
    res = await db.execute(
        select(DataSource).where(
            DataSource.id == data_source_id,
            DataSource.organization_id == organization.id,
        )
    )
    ds = res.scalar_one_or_none()
    if ds is None:
        raise AppError.not_found("data_source.not_found", "Data source not found")
    return ds


@router.post("/data_sources/{data_source_id}/mine-value-joins", response_model=dict)
@requires_resource_permission("data_source", "view_schema")
async def mine_value_joins(
    data_source_id: str,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(current_user),
    organization: Organization = Depends(get_current_organization),
):
    if not getattr(flags, "JOIN_GRAPH", False):
        return {"disabled": True, "data_source_id": data_source_id}

    try:
        ds = await _load_ds(db, data_source_id, organization)
        result = await mine_value_overlap_edges(
            db, organization=organization, data_source=ds
        )
        result["data_source_id"] = str(ds.id)
        return result
    except AppError:
        raise
    except Exception as e:  # noqa: BLE001 — never 500
        return {"ok": False, "data_source_id": data_source_id,
                "error": f"mine-value-joins failed: {e}", "mined": 0}
