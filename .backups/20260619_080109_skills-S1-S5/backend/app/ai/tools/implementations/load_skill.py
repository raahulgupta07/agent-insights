"""Load Skill Tool — load a saved skill's full instructions (SKILL.md) by name.

Progressive disclosure L2: the SKILLS catalog (L1) surfaces only name +
one-line description in context. When a catalog entry matches the task, the
agent calls this tool to pull the full SKILL.md body so it can follow the
proven procedure. Scoping (personal/org/global visibility) and the SKILLS
flag gate are enforced by ``get_skill_body`` in the loader.
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
from app.ai.tools.schemas.load_skill import (
    LoadSkillInput,
    LoadSkillOutput,
)

logger = logging.getLogger(__name__)


class LoadSkillTool(Tool):
    """Load a saved skill's full SKILL.md instructions by name."""

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="load_skill",
            description=(
                "Load a saved skill's full instructions (SKILL.md) by name to follow "
                "a proven procedure. Use when a SKILLS catalog entry matches the task."
            ),
            category="both",
            version="1.0.0",
            input_schema=LoadSkillInput.model_json_schema(),
            output_schema=LoadSkillOutput.model_json_schema(),
            max_retries=0,
            timeout_seconds=20,
            idempotent=True,
            is_active=True,
            required_permissions=[],
            tags=["skill", "load"],
            observation_policy="on_trigger",
            allowed_modes=["chat", "deep"],
            examples=[
                {
                    "input": {"name": "<skill-name>"},
                    "description": "Load a skill's full instructions by name",
                },
            ],
        )

    @property
    def input_model(self) -> Type[BaseModel]:
        return LoadSkillInput

    @property
    def output_model(self) -> Type[BaseModel]:
        return LoadSkillOutput

    async def run_stream(
        self, tool_input: Dict[str, Any], runtime_ctx: Dict[str, Any]
    ) -> AsyncIterator[ToolEvent]:
        try:
            data = LoadSkillInput(**tool_input)
        except Exception as e:
            yield ToolErrorEvent(
                type="tool.error",
                payload={"error": f"Invalid input: {e}", "code": "INVALID_INPUT"},
            )
            return

        yield ToolStartEvent(type="tool.start", payload={"name": data.name})

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

            user_id = str(user.id) if user else None
            body = await get_skill_body(
                db,
                organization_id=str(organization.id),
                user_id=user_id,
                name=data.name,
            )

            if not body:
                output = LoadSkillOutput(
                    success=False,
                    name=data.name,
                    message="Skill not found or not available.",
                )
                yield ToolEndEvent(
                    type="tool.end",
                    payload={
                        "output": output.model_dump(),
                        "observation": {
                            "summary": f"Skill not found or not available: {data.name}",
                            "error": {"type": "not_found", "message": output.message},
                        },
                    },
                )
                return

            # Record usage in an isolated session (never on the agent's shared
            # session — that raises greenlet_spawn). Best effort, non-blocking
            # to the result.
            try:
                from app.ai.skills.loader import record_skill_use
                await record_skill_use(body.get("id"))
            except Exception:
                pass

            # Record the active skill into the runtime context so the agent
            # loop can narrow the tool catalog on subsequent turns (Phase S2.2,
            # owned elsewhere). Best effort — never break the tool.
            try:
                runtime_ctx["active_skill"] = {
                    "name": body["name"],
                    "allowed_tools": body.get("allowed_tools") or [],
                    "disallowed_tools": body.get("disallowed_tools") or [],
                }
            except Exception:
                pass

            output = LoadSkillOutput(
                success=True,
                name=body["name"],
                description=body.get("description"),
                skill_md=body.get("skill_md"),
                message=None,
            )
            yield ToolEndEvent(
                type="tool.end",
                payload={
                    "output": output.model_dump(),
                    "observation": {
                        "summary": f"Loaded skill '{body['name']}' — follow these instructions.",
                        "skill": body["name"],
                        "instructions": body.get("skill_md"),
                    },
                },
            )
        except Exception as e:
            logger.exception(f"load_skill failed: {e}")
            yield ToolErrorEvent(
                type="tool.error",
                payload={"error": f"Load failed: {e}", "code": "LOAD_FAILED"},
            )
            return
