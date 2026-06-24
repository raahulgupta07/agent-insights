"""Schemas for the ``delegate_subtask`` tool (subagent fan-out).

The tool hands ONE focused sub-question to a clean-context research worker that
runs its own read-only SQL and returns a distilled finding.
"""
from typing import Optional
from pydantic import BaseModel, Field


class DelegateSubtaskInput(BaseModel):
    """Input for ``delegate_subtask``."""

    question: str = Field(
        ...,
        description=(
            "A single, self-contained sub-question for the research worker to "
            "answer by running its own SQL (e.g. 'what were Q3 sales by region')."
        ),
        max_length=1000,
    )
    focus: Optional[str] = Field(
        None,
        description=(
            "Optional hint that narrows the worker's focus (e.g. a table name, a "
            "time window, or a metric to concentrate on)."
        ),
    )


class DelegateSubtaskOutput(BaseModel):
    success: bool
    answer: str = ""
    sql: str = ""
    ok: bool = False
    message: str = ""
    # Recursive-verify metadata (only set when HYBRID_RECURSIVE is on; None
    # otherwise so the plain subagent path is byte-identical).
    verified: Optional[bool] = None
    attempts: Optional[int] = None
