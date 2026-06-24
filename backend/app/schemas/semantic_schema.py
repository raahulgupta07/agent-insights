"""Pydantic schemas for the Phase-1 Semantic Layer (per-table / per-column meaning)."""
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, computed_field

from app.schemas.base import OptionalUTCDatetime


class SemanticColumnRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    semantic_table_id: str
    name: str
    type: str
    meaning: str
    status: str
    pii: bool = False
    sensitivity: str = "none"
    created_at: OptionalUTCDatetime = None
    updated_at: OptionalUTCDatetime = None


class SemanticTableRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    data_source_id: str
    table_name: str
    description: str
    use_cases: List[str] = []
    quality_notes: List[str] = []
    status: str
    owner: Optional[str] = None
    pii: bool = False
    freshness_sla_hours: Optional[int] = None
    last_refreshed_at: OptionalUTCDatetime = None
    columns: List[SemanticColumnRead] = []
    created_at: OptionalUTCDatetime = None
    updated_at: OptionalUTCDatetime = None

    @computed_field
    @property
    def described(self) -> bool:
        """True when the table has a non-empty description."""
        return bool(self.description and self.description.strip())


class SemanticLayerStats(BaseModel):
    tables: int
    columns: int
    # Ratio (0..1) of tables that have a non-empty description.
    described_pct: float


class SemanticLayerResponse(BaseModel):
    data_source_id: str
    tables: List[SemanticTableRead] = []
    stats: SemanticLayerStats


class SemanticTablePatch(BaseModel):
    description: Optional[str] = None
    use_cases: Optional[List[str]] = None
    quality_notes: Optional[List[str]] = None
    status: Optional[str] = None
    owner: Optional[str] = None
    pii: Optional[bool] = None
    freshness_sla_hours: Optional[int] = None


class SemanticColumnPatch(BaseModel):
    meaning: Optional[str] = None
    status: Optional[str] = None
    pii: Optional[bool] = None
    sensitivity: Optional[str] = None
