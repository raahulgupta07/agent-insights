"""Schemas for the build_data_asset tool (Phase 3, Engineer capability)."""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class BuildDataAssetInput(BaseModel):
    """Build a reusable data asset in the agent-owned `analytics` schema.

    The tool always creates the object as `analytics.<name>` — you provide the
    name (no schema prefix) and the SELECT body. You may read from company data
    (public.* and connected sources) in the SELECT; writes are confined to the
    analytics schema by a database-level guard.
    """

    name: str = Field(
        ...,
        description="Object name WITHOUT schema prefix (e.g. 'monthly_mrr'). Created as analytics.<name>.",
    )
    kind: Literal["view", "materialized_view", "table"] = Field(
        "view",
        description="view (default, stays in sync), materialized_view (cached), or table (snapshot).",
    )
    select_sql: str = Field(
        ...,
        description="The SELECT (or WITH ... SELECT) body. A single read statement. Do not include CREATE — the tool wraps it.",
    )
    description: str = Field(
        ...,
        description="What this asset is: what it joins, key columns + types, use cases, an example query. Recorded so the Analyst discovers and prefers it.",
    )


class BuildDataAssetOutput(BaseModel):
    success: bool
    object: Optional[str] = None  # e.g. "analytics.monthly_mrr"
    kind: Optional[str] = None
    error_message: Optional[str] = None
