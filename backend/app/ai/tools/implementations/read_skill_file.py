"""Read Skill File Tool — read a bundled L3 resource from a loaded skill.

Progressive disclosure L3: a skill's SKILL.md (L2) may reference bundled files
(reference docs under ``references/`` or runnable scripts under ``scripts/``).
Those files are NOT injected into context up front. When the SKILL.md points the
agent at such a file, the agent calls this tool to pull the file's content by
skill name + relative path. Scoping (personal/org/global visibility) and the
SKILLS flag gate are enforced by ``get_skill_body`` in the loader (skill NAME →
id resolution), exactly as in ``load_skill``.

Script files are returned with their content too, labelled ``kind='script'`` so
the planner knows the content is code it may adapt and run — this tool itself
does NOT execute anything (sandbox-execution is a separate follow-up).
"""

from typing import AsyncIterator, Dict, Any, Type
import logging

from pydantic import BaseModel

from app.ai.tools.base import Tool
from app.ai.tools.metadata import ToolMetadata
from app.ai.tools.schemas.events import (
    ToolEvent,
    ToolStartEvent,
    ToolEndEvent,
    ToolErrorEvent,
)
from app.ai.tools.schemas.read_skill_file import (
    ReadSkillFileInput,
    ReadSkillFileOutput,
)

logger = logging.getLogger(__name__)


class ReadSkillFileTool(Tool):
    """Read a bundled file (reference doc or script) from a loaded skill."""

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="read_skill_file",
            description=(
                "Read a bundled file (reference doc or script) from a loaded skill's "
                "L3 resources by skill name + relative path."
            ),
            category="research",
            version="1.0.0",
            input_schema=ReadSkillFileInput.model_json_schema(),
            output_schema=ReadSkillFileOutput.model_json_schema(),
            max_retries=0,
            timeout_seconds=20,
            idempotent=True,
            is_active=True,
            required_permissions=[],
            tags=["skill", "file", "read"],
            observation_policy="on_trigger",
            allowed_modes=["chat", "deep"],
            examples=[
                {
                    "input": {"skill": "<skill-name>", "path": "references/API.md"},
                    "description": "Read a reference doc bundled with a skill",
                },
            ],
        )

    @property
    def input_model(self) -> Type[BaseModel]:
        return ReadSkillFileInput

    @property
    def output_model(self) -> Type[BaseModel]:
        return ReadSkillFileOutput

    async def run_stream(
        self, tool_input: Dict[str, Any], runtime_ctx: Dict[str, Any]
    ) -> AsyncIterator[ToolEvent]:
        try:
            data = ReadSkillFileInput(**tool_input)
        except Exception as e:
            yield ToolErrorEvent(
                type="tool.error",
                payload={"error": f"Invalid input: {e}", "code": "INVALID_INPUT"},
            )
            return

        yield ToolStartEvent(
            type="tool.start", payload={"skill": data.skill, "path": data.path}
        )

        context_hub = runtime_ctx.get("context_hub")
        db = context_hub.db if context_hub else runtime_ctx.get("db")
        organization = (
            context_hub.organization if context_hub else runtime_ctx.get("organization")
        )
        user = runtime_ctx.get("user")

        if not all([db, organization]):
            yield ToolErrorEvent(
                type="tool.error",
                payload={
                    "error": "Missing required runtime context (db, organization)",
                    "code": "MISSING_CONTEXT",
                },
            )
            return

        try:
            from app.ai.skills.loader import get_skill_body
            from app.ai.skills.files import (
                get_skill_file,
                KIND_SCRIPT,
            )

            user_id = str(user.id) if user else None
            body = await get_skill_body(
                db,
                organization_id=str(organization.id),
                user_id=user_id,
                name=data.skill,
            )

            if not body:
                output = ReadSkillFileOutput(
                    success=False,
                    skill=data.skill,
                    path=data.path,
                    message="Skill not found or not available.",
                )
                yield ToolEndEvent(
                    type="tool.end",
                    payload={
                        "output": output.model_dump(),
                        "observation": {
                            "summary": f"Skill not found or not available: {data.skill}",
                            "error": {"type": "not_found", "message": output.message},
                        },
                    },
                )
                return

            file = await get_skill_file(db, skill_id=body["id"], path=data.path)

            if not file:
                output = ReadSkillFileOutput(
                    success=False,
                    skill=body["name"],
                    path=data.path,
                    message="File not found in skill bundle.",
                )
                yield ToolEndEvent(
                    type="tool.end",
                    payload={
                        "output": output.model_dump(),
                        "observation": {
                            "summary": (
                                f"File '{data.path}' not found in skill "
                                f"'{body['name']}'."
                            ),
                            "error": {"type": "not_found", "message": output.message},
                        },
                    },
                )
                return

            kind = file.get("kind")
            path = file.get("path", data.path)
            content = file.get("content")

            if kind == KIND_SCRIPT:
                summary = (
                    f"Read script '{path}' from skill '{body['name']}'. This is a "
                    "script the agent may adapt and run (execution is a separate step "
                    "— this content is for inspection/adaptation)."
                )
            else:
                summary = f"Read {kind} '{path}' from skill '{body['name']}'."

            output = ReadSkillFileOutput(
                success=True,
                skill=body["name"],
                path=path,
                kind=kind,
                content=content,
                message=None,
            )
            yield ToolEndEvent(
                type="tool.end",
                payload={
                    "output": output.model_dump(),
                    "observation": {
                        "summary": summary,
                        "skill": body["name"],
                        "path": path,
                        "kind": kind,
                        "content": content,
                    },
                },
            )
        except Exception as e:
            logger.exception(f"read_skill_file failed: {e}")
            yield ToolErrorEvent(
                type="tool.error",
                payload={"error": f"Read failed: {e}", "code": "READ_FAILED"},
            )
            return
