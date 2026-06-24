from typing import Optional
from pydantic import BaseModel, Field


class LoadSkillInput(BaseModel):
    """Input schema for the ``load_skill`` tool.

    Loads the full instructions (SKILL.md) of a saved skill by its exact name,
    as listed in the SKILLS catalog surfaced in context.
    """

    name: str = Field(
        ...,
        description="The exact skill name from the SKILLS catalog to load.",
    )


class LoadSkillOutput(BaseModel):
    success: bool
    name: Optional[str] = None
    description: Optional[str] = None
    skill_md: Optional[str] = None
    message: Optional[str] = None
