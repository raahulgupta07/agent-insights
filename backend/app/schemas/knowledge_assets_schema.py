"""Pydantic schemas for Phase-6 Engineer Assets surfacing.

Read-only view over engineer-built data assets, which are stored as
``Instruction`` rows (category=='data_asset', ai_source=='engineer_asset') by
``app/ai/tools/implementations/build_data_asset.py``. No new model/migration —
these schemas simply project those rows for the Knowledge UI's Assets tab.

Mirrors ``query_library_schema.py`` style (ConfigDict(from_attributes=True),
OptionalUTCDatetime for timestamps).
"""
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict

from app.schemas.base import OptionalUTCDatetime


class AssetItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    object_name: str
    kind: str
    description: str
    status: str
    source: str
    created_at: OptionalUTCDatetime = None
    updated_at: OptionalUTCDatetime = None


class AssetsResponse(BaseModel):
    data_source_id: Optional[str] = None
    assets: List[AssetItemRead] = []
    stats: Dict[str, int] = {}
