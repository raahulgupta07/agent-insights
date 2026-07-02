from typing import Dict, Any, Optional, List, Literal
from pydantic import BaseModel, Field, field_validator

# Reuse per-source targeting schema for consistent behavior
from .create_widget import TablesBySource, _coerce_tables_by_source
from .create_data_model import DataModel


VisualizationType = Literal[
    "table",
    "bar_chart",
    "line_chart",
    "pie_chart",
    "area_chart",
    "count",
    "metric_card",
    "heatmap",
    "map",
    "candlestick",
    "treemap",
    "radar_chart",
    "scatter_plot",
]


class CreateDataInput(BaseModel):
    """Input for code-first data creation (no explicit data model).

    Generates and executes code to produce tabular data based on the prompt and targeted schemas.
    """

    title: str = Field(..., description="Title for the data artifact to create. Should be in the same language of the user/prompt")
    user_prompt: str = Field(..., description="Original user instruction")
    interpreted_prompt: str = Field(..., description="LLM-interpreted, clarified version of the user prompt. "
    "Be prescriptive: name specific tables, target columns, and additional columns for filtering. "
    "Prefer a single wide master table with multiple metrics and dimensions over many narrow queries. "
    "Specify whether to return granular rows or pre-aggregate. "
    "Reuse additional columns from previous queries when the data is related, to enable cross-filtering.")

    tables_by_source: Optional[List[TablesBySource]] = Field(
        default=None,
        description=(
            "Compact per-source table targeting. MUST be a list of objects: "
            '[{"data_source_id": null, "tables": ["Open Project Tracking/projects"]}]. '
            "Use the field name `tables` (a list of strings). data_source_id may be null for cross-source. "
            "For file analysis only, keep this empty."
        ),
    )

    @field_validator("tables_by_source", mode="before")
    @classmethod
    def _normalize_tables_by_source(cls, v):
        return _coerce_tables_by_source(v)

    visualization_type: Optional[VisualizationType] = Field(
        default=None,
        description="Type of visualization to create. If not provided, a table will be created.",
    )


class CreateDataOutput(BaseModel):
    """Output of code-first data creation."""

    success: bool = Field(..., description="Whether the overall operation succeeded")
    code: Optional[str] = Field(default=None, description="Final code used to compute data")
    data: Optional[Dict[str, Any]] = Field(default=None, description="Rendered tabular data structure for consumers")
    data_preview: Optional[Dict[str, Any]] = Field(default=None, description="Privacy-safe preview for UI/LLM")
    stats: Optional[Dict[str, Any]] = Field(default=None, description="Execution stats/metadata")
    execution_log: Optional[str] = Field(default=None, description="Execution log or trace output if available")
    errors: Optional[List[Any]] = Field(default=None, description="Internal retry errors, if any")
    # Minimal data model (no columns) for visualization: type + optional series/grouping
    data_model: Optional[DataModel] = Field(default=None, description="Minimal data model: type + optional series/group_by/sort/limit; columns omitted")
    # Optional view options (styling/palette) to merge into Visualization.view.options
    view_options: Optional[Dict[str, Any]] = Field(default=None, description="Optional view.options overrides, e.g., colors palette")


