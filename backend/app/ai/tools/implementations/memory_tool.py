"""Agent-memory tools — `remember` + `recall` (MemGPT-style page-in/out).

Two native auto-registered Tools over the vectorless agent_memory store
(``app.ai.brain.agent_memory``). The agent deliberately stows durable notes
(`remember`) and pages relevant ones back before answering (`recall`).

Both self-gate on ``flags.AGENT_MEMORY``: when OFF they return a benign empty
result (success=True, saved=False / no memories) so a fresh deploy behaves like
upstream — no DB hit, no leak. Personal scope is the agent's own live
scratchpad; project/org scope lands 'pending' and only surfaces once approved
(the store enforces this). Never raise into the loop.
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
from app.ai.tools.schemas.agent_memory import (
    RememberInput,
    RememberOutput,
    RecallInput,
    RecallOutput,
    RecalledMemory,
)
from app.settings.hybrid_flags import flags
from app.ai.brain import agent_memory

logger = logging.getLogger(__name__)


class RememberTool(Tool):
    """Save a durable note/learning to memory for future sessions."""

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="remember",
            description=(
                "Save a durable note/learning to memory for future sessions "
                "(e.g. a finding, a user preference, a data caveat). Shared "
                "scope needs approval before others see it."
            ),
            category="both",
            version="1.0.0",
            input_schema=RememberInput.model_json_schema(),
            output_schema=RememberOutput.model_json_schema(),
            max_retries=1,
            timeout_seconds=15,
            idempotent=False,
            tags=["memory", "knowledge"],
            examples=[
                {
                    "input": {"text": "Revenue excludes refunds.", "mem_key": "revenue_def"},
                    "description": "Save a data caveat for this project",
                },
            ],
        )

    @property
    def input_model(self) -> Type[BaseModel]:
        return RememberInput

    @property
    def output_model(self) -> Type[BaseModel]:
        return RememberOutput

    async def run_stream(
        self, tool_input: Dict[str, Any], runtime_ctx: Dict[str, Any]
    ) -> AsyncIterator[ToolEvent]:
        try:
            data = RememberInput(**tool_input)
        except Exception as e:
            yield ToolErrorEvent(
                type="tool.error",
                payload={"error": f"Invalid input: {e}", "code": "INVALID_INPUT"},
            )
            return

        yield ToolStartEvent(
            type="tool.start",
            payload={"mem_key": data.mem_key, "scope": data.scope},
        )

        # Gate: behave as a no-op save when the feature is off (no leak, no DB hit).
        if not flags.AGENT_MEMORY:
            output = RememberOutput(
                success=True,
                saved=False,
                status="disabled",
                message="Agent memory is not enabled.",
            )
            yield ToolEndEvent(
                type="tool.end",
                payload={
                    "output": output.model_dump(),
                    "observation": {"summary": "Agent memory disabled; nothing saved."},
                },
            )
            return

        db = runtime_ctx.get("db")
        organization = runtime_ctx.get("organization")
        if not db or not organization:
            yield ToolErrorEvent(
                type="tool.error",
                payload={
                    "error": "Missing required runtime context (db, organization)",
                    "code": "MISSING_CONTEXT",
                },
            )
            return

        # The current user/owner — needed so personal-scope memory has an owner.
        # If absent, write_memory downgrades personal -> project (held for approval).
        user = runtime_ctx.get("user") or runtime_ctx.get("current_user")
        scope = (data.scope or "project").strip().lower()
        if scope == "personal" and not user:
            scope = "project"

        try:
            new_id = await agent_memory.write_memory(
                db,
                organization=organization,
                user=user,
                scope=scope,
                text=data.text,
                mem_key=data.mem_key,
                data_source_id=data.data_source_id,
            )
            saved = bool(new_id)
            # personal -> live (approved); shared -> pending review.
            status = ("saved" if scope == "personal" else "pending") if saved else "failed"
            if not saved:
                msg = "Could not save the note."
            elif scope == "personal":
                msg = "Saved to your memory."
            else:
                msg = "Saved — pending approval before it's shared."
            output = RememberOutput(
                success=True,
                saved=saved,
                status=status,
                message=msg,
            )
            yield ToolEndEvent(
                type="tool.end",
                payload={
                    "output": output.model_dump(),
                    "observation": {"summary": msg},
                },
            )
        except Exception as e:
            logger.exception(f"remember failed: {e}")
            yield ToolErrorEvent(
                type="tool.error",
                payload={"error": f"Remember failed: {e}", "code": "REMEMBER_FAILED"},
            )


class RecallTool(Tool):
    """Recall relevant notes saved earlier about this project/data."""

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="recall",
            description=(
                "Recall relevant notes you saved earlier about this "
                "project/data before answering."
            ),
            category="both",
            version="1.0.0",
            input_schema=RecallInput.model_json_schema(),
            output_schema=RecallOutput.model_json_schema(),
            max_retries=1,
            timeout_seconds=15,
            idempotent=True,
            tags=["memory", "knowledge", "lookup"],
            examples=[
                {
                    "input": {"query": "how is revenue defined"},
                    "description": "Recall notes relevant to the question",
                },
            ],
        )

    @property
    def input_model(self) -> Type[BaseModel]:
        return RecallInput

    @property
    def output_model(self) -> Type[BaseModel]:
        return RecallOutput

    async def run_stream(
        self, tool_input: Dict[str, Any], runtime_ctx: Dict[str, Any]
    ) -> AsyncIterator[ToolEvent]:
        try:
            data = RecallInput(**tool_input)
        except Exception as e:
            yield ToolErrorEvent(
                type="tool.error",
                payload={"error": f"Invalid input: {e}", "code": "INVALID_INPUT"},
            )
            return

        yield ToolStartEvent(
            type="tool.start",
            payload={"query": data.query, "k": data.k},
        )

        # Gate: behave as "no memories" when the feature is off (no DB hit).
        if not flags.AGENT_MEMORY:
            output = RecallOutput(success=True, memories=[], count=0)
            yield ToolEndEvent(
                type="tool.end",
                payload={
                    "output": output.model_dump(),
                    "observation": {"summary": "Agent memory disabled; no notes recalled."},
                },
            )
            return

        db = runtime_ctx.get("db")
        organization = runtime_ctx.get("organization")
        if not db or not organization:
            yield ToolErrorEvent(
                type="tool.error",
                payload={
                    "error": "Missing required runtime context (db, organization)",
                    "code": "MISSING_CONTEXT",
                },
            )
            return

        user = runtime_ctx.get("user") or runtime_ctx.get("current_user")
        user_id = str(getattr(user, "id", None) or "") or None

        try:
            rows = await agent_memory.recall(
                db,
                organization=organization,
                query=data.query,
                user_id=user_id,
                data_source_id=data.data_source_id,
                k=data.k,
            )
            memories = [
                RecalledMemory(
                    mem_key=str((r.get("mem_key") if isinstance(r, dict) else "") or ""),
                    text=str((r.get("text") if isinstance(r, dict) else "") or ""),
                )
                for r in (rows or [])
                if isinstance(r, dict)
            ]
            output = RecallOutput(
                success=True,
                memories=memories,
                count=len(memories),
            )
            yield ToolEndEvent(
                type="tool.end",
                payload={
                    "output": output.model_dump(),
                    "observation": {"summary": f"Recalled {len(memories)} note(s)."},
                },
            )
        except Exception as e:
            logger.exception(f"recall failed: {e}")
            yield ToolErrorEvent(
                type="tool.error",
                payload={"error": f"Recall failed: {e}", "code": "RECALL_FAILED"},
            )
