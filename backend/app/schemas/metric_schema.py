"""Pydantic schemas for the Phase-1 Metrics Catalog (named business metrics)."""
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict

from app.schemas.base import OptionalUTCDatetime


class MetricRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    data_source_id: str
    name: str
    definition: str
    table_ref: str
    sql_calc: str
    owner: Optional[str] = None
    status: str
    created_at: OptionalUTCDatetime = None
    updated_at: OptionalUTCDatetime = None


class MetricsResponse(BaseModel):
    metrics: List[MetricRead] = []


class MetricCreate(BaseModel):
    data_source_id: str
    name: str
    definition: Optional[str] = None
    table_ref: Optional[str] = None
    sql_calc: Optional[str] = None


class MetricPatch(BaseModel):
    name: Optional[str] = None
    definition: Optional[str] = None
    table_ref: Optional[str] = None
    sql_calc: Optional[str] = None
    status: Optional[str] = None


class MetricTestResult(BaseModel):
    ok: bool
    value: Optional[Any] = None
    columns: Optional[List[str]] = None
    rows: Optional[List[List[Any]]] = None
    row_count: Optional[int] = None
    error: Optional[str] = None
