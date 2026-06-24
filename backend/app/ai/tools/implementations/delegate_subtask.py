"""delegate_subtask Tool — fan ONE focused sub-question out to a research worker.

Subagent fan-out (orchestrator-worker). The agent delegates a self-contained
piece of a larger analysis to a clean-context worker that runs its OWN read-only
SQL against the report's data-source clients and returns a distilled finding
(genuine subagent: clean context, own data access, distilled return — NOT a full
nested AgentV2).

Self-gates on ``flags.SUBAGENTS``: when subagents are off the tool returns a
benign empty result and does NO work (so a fresh deploy behaves like upstream).
Native ToolRegistry pattern (auto-registered via implementations/). Mirrors
``resolve_metric.py`` structure.
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
from app.ai.tools.schemas.delegate_subtask import (
    DelegateSubtaskInput,
    DelegateSubtaskOutput,
)
from app.ai.runner.orchestrator import (
    run_subtask,
    run_subtask_verified,
    _build_schema_hint,
)
from app.settings.hybrid_flags import flags
import os

logger = logging.getLogger(__name__)


class DelegateSubtaskTool(Tool):
    """Delegate a focused sub-question to a clean-context research worker."""

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="delegate_subtask",
            description=(
                "Delegate a FOCUSED sub-question to a clean-context research "
                "worker that runs its own SQL and returns a distilled finding. "
                "Use for one self-contained piece of a larger analysis (e.g. "
                "'what were Q3 sales by region')."
            ),
            category="both",
            version="1.0.0",
            input_schema=DelegateSubtaskInput.model_json_schema(),
            output_schema=DelegateSubtaskOutput.model_json_schema(),
            max_retries=1,
            timeout_seconds=120,
            idempotent=False,
            tags=["subagent", "research"],
            examples=[
                {
                    "input": {"question": "What were Q3 sales by region?"},
                    "description": "Delegate one focused analytical sub-question",
                },
                {
                    "input": {
                        "question": "Which 3 artists have the most albums?",
                        "focus": "Artist, Album",
                    },
                    "description": "Delegate with a focus hint on the relevant tables",
                },
            ],
        )

    @property
    def input_model(self) -> Type[BaseModel]:
        return DelegateSubtaskInput

    @property
    def output_model(self) -> Type[BaseModel]:
        return DelegateSubtaskOutput

    async def run_stream(
        self, tool_input: Dict[str, Any], runtime_ctx: Dict[str, Any]
    ) -> AsyncIterator[ToolEvent]:
        try:
            data = DelegateSubtaskInput(**tool_input)
        except Exception as e:
            yield ToolErrorEvent(
                type="tool.error",
                payload={"error": f"Invalid input: {e}", "code": "INVALID_INPUT"},
            )
            return

        # Self-gate: subagents off -> benign no-op (no work, no leak).
        if not flags.SUBAGENTS:
            output = DelegateSubtaskOutput(
                success=True,
                answer="",
                sql="",
                ok=False,
                message="subagents disabled",
            )
            yield ToolEndEvent(
                type="tool.end",
                payload={
                    "output": output.model_dump(),
                    "observation": {"summary": "subagents disabled; no work done."},
                },
            )
            return

        yield ToolStartEvent(
            type="tool.start",
            payload={"question": data.question, "focus": data.focus},
        )

        # Re-entrancy guard: a worker must never delegate again (belt-and-
        # suspenders — workers aren't AgentV2 and never reach this tool anyway).
        depth = 0
        try:
            depth = int(runtime_ctx.get("subagent_depth", 0) or 0)
        except Exception:
            depth = 0
        if depth >= 1:
            output = DelegateSubtaskOutput(
                success=True,
                answer="",
                sql="",
                ok=False,
                message="no nested delegation",
            )
            yield ToolEndEvent(
                type="tool.end",
                payload={
                    "output": output.model_dump(),
                    "observation": {"summary": "Refused: no nested delegation."},
                },
            )
            return

        try:
            model = runtime_ctx.get("model")
            ds_clients = runtime_ctx.get("ds_clients") or {}
            report = runtime_ctx.get("report")

            if model is None:
                yield ToolErrorEvent(
                    type="tool.error",
                    payload={
                        "error": "Missing required runtime context (model)",
                        "code": "MISSING_CONTEXT",
                    },
                )
                return

            # Build a short schema hint from the report's data sources.
            schema_hint = ""
            try:
                data_sources = getattr(report, "data_sources", None) if report else None
                if data_sources:
                    schema_hint = _build_schema_hint(data_sources)
                if not schema_hint and ds_clients:
                    schema_hint = _build_schema_hint(ds_clients)
            except Exception as e:
                logger.debug("delegate_subtask schema hint failed: %s", e)
                schema_hint = ""

            sub_question = data.question
            if data.focus:
                sub_question = f"{data.question}\n(Focus: {data.focus})"

            # Recursive verify rides on the subagent path: each finding is graded
            # by a cheap critic and HARD-error findings re-delegate (bounded).
            # Flag off -> plain single-pass run_subtask (byte-identical to before).
            if flags.RECURSIVE:
                try:
                    max_retries = int(os.environ.get("HYBRID_RECURSIVE_MAX_RETRIES", "2") or 2)
                except Exception:
                    max_retries = 2
                result = await run_subtask_verified(
                    sub_question=sub_question,
                    model=model,
                    ds_clients=ds_clients,
                    schema_hint=schema_hint,
                    max_retries=max_retries,
                )
            else:
                result = await run_subtask(
                    sub_question=sub_question,
                    model=model,
                    ds_clients=ds_clients,
                    schema_hint=schema_hint,
                )

            answer = result.get("answer", "") or ""
            ok = bool(result.get("ok", False))

            verified = result.get("verified")
            attempts = result.get("attempts")
            if flags.RECURSIVE and verified is not None:
                retries = max(0, int(attempts or 1) - 1)
                if verified and retries > 0:
                    message = f"verified (self-fixed after {retries} retr{'y' if retries == 1 else 'ies'})"
                elif verified:
                    message = "verified"
                else:
                    reason = result.get("critic_reason") or result.get("error") or "partial finding"
                    message = f"unverified after {attempts} attempt(s): {reason}"
                summary_prefix = (
                    "[verified] " if verified else "[unverified] "
                )
            else:
                message = "worker finding" if ok else (result.get("error") or "partial finding")
                summary_prefix = ""

            output = DelegateSubtaskOutput(
                success=True,
                answer=answer,
                sql=result.get("sql", "") or "",
                ok=ok,
                message=message,
                verified=verified if flags.RECURSIVE else None,
                attempts=attempts if flags.RECURSIVE else None,
            )
            yield ToolEndEvent(
                type="tool.end",
                payload={
                    "output": output.model_dump(),
                    "observation": {"summary": f"{summary_prefix}{answer[:300]}"},
                },
            )
        except Exception as e:
            logger.exception(f"delegate_subtask failed: {e}")
            yield ToolErrorEvent(
                type="tool.error",
                payload={"error": f"Delegate failed: {e}", "code": "DELEGATE_FAILED"},
            )
