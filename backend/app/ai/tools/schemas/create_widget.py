from typing import Dict, Any, Optional, List, Union
from pydantic import (
    BaseModel,
    Field,
    AliasChoices,
    ConfigDict,
    field_validator,
    model_validator,
)

from .create_data_model import DataModel


class TablesBySource(BaseModel):
    """Per-source table filters to focus schema loading.

    - data_source_id: scope to a specific data source (UUID). If omitted/null, applies across all sources.
    - tables: list of table names. Names are always treated as literal (escaped).
      Matching is case-insensitive and names match with or without a schema/dataset prefix (. or / separator).
      Examples: "film", "public.inventory", "Regional Sales Sample (2)/Opportunities".
    """

    # Accept `tables` by field name even when an alias is defined.
    model_config = ConfigDict(populate_by_name=True)

    data_source_id: Optional[str] = Field(
        default=None,
        description="UUID of the data source to scope these tables. If null, applies to all sources.",
    )
    tables: List[str] = Field(
        ...,
        # LLMs frequently emit `table_names`/`table`; accept them as aliases for `tables`.
        validation_alias=AliasChoices("tables", "table_names", "table"),
        description="Table names (literal, case-insensitive). Schema or dataset prefix (. or /) is optional.",
    )

    @model_validator(mode="before")
    @classmethod
    def _coerce_shape(cls, v):
        # A bare string entry ("projects") → {"tables": ["projects"]}.
        if isinstance(v, str):
            return {"tables": [v]}
        # A dict whose `tables`/alias is a single string → wrap in a list.
        if isinstance(v, dict):
            for key in ("tables", "table_names", "table"):
                if isinstance(v.get(key), str):
                    v = {**v, key: [v[key]]}
                    break
        return v


def _coerce_tables_by_source(v):
    """Normalize the many shapes an LLM emits for `tables_by_source` into
    List[TablesBySource]-compatible input.

    Accepts:
      - None                                    → None
      - "projects"                              → [{"tables": ["projects"]}]
      - ["projects", "owners"]                  → [{"tables": ["projects", "owners"]}]
      - {"tables": [...]} / single dict         → [ {...} ]
      - [{"table_names": [...], ...}, ...]       → handled via field alias
    """
    if v is None:
        return v
    if isinstance(v, str):
        return [{"tables": [v]}]
    if isinstance(v, dict):
        return [v]
    if isinstance(v, list):
        # Whole list is bare strings → collapse to one cross-source entry.
        if v and all(isinstance(x, str) for x in v):
            return [{"tables": list(v)}]
        out = []
        for item in v:
            out.append({"tables": [item]} if isinstance(item, str) else item)
        return out
    return v


class CreateWidgetInput(BaseModel):
    """Input for end-to-end widget creation.

    The tool will generate a data_model, then code, then execute it to populate the widget.
    """

    widget_title: str = Field(..., description="Title for the widget to create")
    user_prompt: str = Field(..., description="Original user instruction")
    interpreted_prompt: str = Field(..., description="LLM-interpreted, clarified version of the user prompt")

    tables_by_source: Optional[List[TablesBySource]] = Field(
        default=None,
        description=(
            "Compact per-source table targeting. MUST be a list of objects: "
            '[{"data_source_id": null, "tables": ["Open Project Tracking/projects"]}]. '
            "Use the field name `tables` (a list of strings). data_source_id may be null for cross-source."
        ),
    )

    @field_validator("tables_by_source", mode="before")
    @classmethod
    def _normalize_tables_by_source(cls, v):
        return _coerce_tables_by_source(v)

    schema_limit: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Max tables to include per data source when rendering the schema excerpt.",
    )


class CreateWidgetOutput(BaseModel):
    """Output of end-to-end widget creation."""

    success: bool = Field(..., description="Whether the overall operation succeeded")
    data_model: Optional[DataModel] = Field(default=None, description="Final normalized data model")
    code: Optional[str] = Field(default=None, description="Final code used to compute widget data")
    widget_data: Optional[Dict[str, Any]] = Field(default=None, description="Rendered data structure for the widget")
    data_preview: Optional[Dict[str, Any]] = Field(default=None, description="Privacy-safe preview for UI/LLM")
    stats: Optional[Dict[str, Any]] = Field(default=None, description="Execution stats/metadata")
    execution_log: Optional[str] = Field(default=None, description="Execution log or trace output if available")


