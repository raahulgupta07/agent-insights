from typing import Literal, Optional
from pydantic import BaseModel, Field


class RememberThisInput(BaseModel):
    """Input schema for the remember_this tool.

    The agent calls this mid-answer to explicitly save a hard-won query or
    approach to Shared Memory so it (and teammates who hold the same data) can
    reuse it later — the explicit counterpart to the automatic verified-golden
    gate.
    """

    summary: str = Field(
        ...,
        min_length=1,
        description=(
            "A short, self-contained description of the proven query or approach "
            "and when to use it (e.g. 'Monthly net revenue by channel — join sales "
            "to channel_dim, sum net_amount, group by month')."
        ),
    )
    sql_or_dax: Optional[str] = Field(
        None,
        description=(
            "The exact SQL or DAX that worked. When provided with scope='data', "
            "it is sanitized into a reusable, parameterized template keyed to the "
            "current data source(s)."
        ),
    )
    kind: Literal["query_template", "howto"] = Field(
        "query_template",
        description=(
            "'query_template' for a reusable query/DAX; 'howto' for a narrative "
            "approach or gotcha that isn't a single query."
        ),
    )
    scope: Literal["data", "private"] = Field(
        "data",
        description=(
            "'data' shares the memory with anyone who holds the same data "
            "(safe by construction — no leak). 'private' keeps it in your own "
            "personal scratchpad only."
        ),
    )


class RememberThisOutput(BaseModel):
    """Output schema for the remember_this tool."""

    status: str = Field(
        default="saved",
        description="'saved', 'noop' (feature off / nothing to save), or 'error'.",
    )
    written: int = Field(
        default=0,
        description="Number of memory rows written or reinforced.",
    )
    scope: str = Field(default="data", description="Scope the memory was saved under.")
