"""Pydantic schemas for the Phase-3 Query Library (saved named SQL queries).

NB: the unscoped name ``query_schema`` is already used by dash core for the
Query/QueryRun model schemas, so the Phase-3 library schemas live here to avoid
clobbering dash core (HARD RULE: touch dash core minimally).
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict

from app.schemas.base import OptionalUTCDatetime


class QueryItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    data_source_id: str
    name: str
    description: str
    sql_text: str
    tags: List[str] = []
    source: str
    run_count: int
    owner: Optional[str] = None
    status: str
    created_at: OptionalUTCDatetime = None
    updated_at: OptionalUTCDatetime = None


class QueryLibraryResponse(BaseModel):
    data_source_id: str
    queries: List[QueryItemRead] = []
    stats: Dict[str, int] = {}


class QueryCreate(BaseModel):
    data_source_id: str
    name: str
    description: Optional[str] = None
    sql_text: Optional[str] = None
    tags: Optional[List[str]] = None


class QueryPatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    sql_text: Optional[str] = None
    tags: Optional[List[str]] = None
    source: Optional[str] = None
    status: Optional[str] = None


class QueryRunResult(BaseModel):
    ok: bool
    columns: Optional[List[str]] = None
    rows: Optional[List[List[Any]]] = None
    row_count: Optional[int] = None
    error: Optional[str] = None
