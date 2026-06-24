"""Schemas for the agent-memory tools (`remember` / `recall`).

MemGPT-style deliberate page-in/out over the vectorless agent_memory store.
`remember` stows a durable note; `recall` pages relevant ones back. Personal
scope is the agent's own scratchpad (live); shared scope (project/org) lands
pending and only surfaces once approved.
"""
from typing import List, Optional
from pydantic import BaseModel, Field


class RememberInput(BaseModel):
    """Input for ``remember`` — save a durable note to memory."""

    text: str = Field(
        ...,
        description="The note/learning to remember (a finding, a user preference, a data caveat).",
        max_length=8000,
    )
    mem_key: Optional[str] = Field(
        None,
        description="Optional short key/label for the note (e.g. 'revenue_definition').",
        max_length=200,
    )
    scope: Optional[str] = Field(
        "project",
        description=(
            "Visibility scope: 'personal' (your own scratchpad, live), "
            "'project' or 'org' (shared — needs approval before others see it). "
            "Defaults to 'project'."
        ),
    )
    data_source_id: Optional[str] = Field(
        None,
        description="Optional data source id to scope the note to one connection.",
    )


class RememberOutput(BaseModel):
    success: bool
    saved: bool = False
    status: str = ""
    message: str = ""


class RecallInput(BaseModel):
    """Input for ``recall`` — page relevant saved notes back into context."""

    query: str = Field(
        ...,
        description="What you want to recall about (free text — the topic/question).",
        max_length=2000,
    )
    data_source_id: Optional[str] = Field(
        None,
        description="Optional data source id to bias recall toward one connection.",
    )
    k: int = Field(
        5,
        description="Max number of notes to return.",
        ge=1,
        le=20,
    )


class RecalledMemory(BaseModel):
    mem_key: str = ""
    text: str = ""


class RecallOutput(BaseModel):
    success: bool
    memories: List[RecalledMemory] = Field(default_factory=list)
    count: int = 0
