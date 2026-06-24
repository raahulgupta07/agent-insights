from typing import Optional
from pydantic import BaseModel, Field


class ReadSkillFileInput(BaseModel):
    """Input schema for the ``read_skill_file`` tool.

    Reads a single bundled L3 resource (reference doc or script) from a loaded
    skill by the skill's exact name plus a relative file path, as listed in the
    SKILLS catalog surfaced in context.
    """

    skill: str = Field(
        ...,
        description="The exact skill name from the SKILLS catalog.",
    )
    path: str = Field(
        ...,
        description=(
            "Relative file path within the skill bundle, "
            'e.g. "references/API.md" or "scripts/queries.sql".'
        ),
    )


class ReadSkillFileOutput(BaseModel):
    success: bool
    skill: Optional[str] = None
    path: Optional[str] = None
    kind: Optional[str] = None
    content: Optional[str] = None
    message: Optional[str] = None
