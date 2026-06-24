"""
build_data_asset — Engineer capability (Phase 3)
================================================

Creates a reusable data asset (view / materialized view / table) in the
agent-owned `analytics` schema of dash's managed Postgres, then records it as an
AI-sourced Instruction so the Analyst discovers and prefers it.

Writes are confined to analytics/staging by the database-level guard in
analytics_engine (reading public/company data in the SELECT is allowed).

Gated by flags.ENGINEER_ASSETS.
"""

import asyncio
import logging
import os
import re
from typing import Any, AsyncIterator, Dict, Optional, Type

from pydantic import BaseModel
from sqlalchemy import text

from app.ai.tools.base import Tool
from app.ai.tools.metadata import ToolMetadata
from app.ai.tools.schemas.build_data_asset import BuildDataAssetInput, BuildDataAssetOutput
from app.ai.tools.schemas.events import (
    ToolEndEvent,
    ToolEvent,
    ToolProgressEvent,
    ToolStartEvent,
)
from app.settings.hybrid_flags import flags

logger = logging.getLogger(__name__)

_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
_SELECT_RE = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)

# Postgres identifier limit. The physical object name (prefix + asset name) must
# stay <= this, so the name part is truncated when the prefix would overflow it.
_MAX_IDENT_LEN = 63


def _per_user_assets_enabled() -> bool:
    """Opt-in env gate. OFF (default) = legacy bare ``analytics.<name>`` behavior."""
    return os.getenv("SKILL_PER_USER_ASSETS", "0").strip().lower() in {"1", "true", "yes", "on"}


def _short_id(raw: Any) -> str:
    """Turn an org/user id into a short, valid lowercase identifier fragment.

    Dashes stripped, non-[a-z0-9_] dropped, lowercased, truncated to 12 chars.
    """
    s = re.sub(r"[^a-z0-9_]", "", str(raw or "").replace("-", "").lower())
    return s[:12]


def _physical_name(name: str, runtime_ctx: Dict[str, Any]) -> str:
    """Resolve the physical asset name (already validated ``name``).

    With ``SKILL_PER_USER_ASSETS`` OFF → legacy bare ``name`` (caller prefixes
    ``analytics.``). ON → ``u_<short_user_id>_<name>`` (or ``o_<short_org_id>_<name>``
    when there is no user, e.g. a system/eval run). The user-supplied ``name`` is
    truncated if needed so the full identifier stays <= 63 chars. Never returns a
    bare name when the gate is ON.
    """
    if not _per_user_assets_enabled():
        return name

    user = runtime_ctx.get("user")
    organization = runtime_ctx.get("organization")
    if user is not None and getattr(user, "id", None) is not None:
        prefix = f"u_{_short_id(user.id)}_"
    elif organization is not None and getattr(organization, "id", None) is not None:
        prefix = f"o_{_short_id(organization.id)}_"
    else:
        # No user and no org — still never emit a bare name; use a stable marker.
        prefix = "o_unknown_"

    budget = _MAX_IDENT_LEN - len(prefix)
    if budget < 1:
        budget = 1
    return f"{prefix}{name[:budget]}"


def _build_ddl(physical_name: str, kind: str, select_sql: str) -> str:
    target = f"analytics.{physical_name}"
    if kind == "view":
        return f"CREATE OR REPLACE VIEW {target} AS\n{select_sql}"
    if kind == "materialized_view":
        return f"CREATE MATERIALIZED VIEW IF NOT EXISTS {target} AS\n{select_sql}"
    if kind == "table":
        return f"CREATE TABLE IF NOT EXISTS {target} AS\n{select_sql}"
    raise ValueError(f"unsupported kind: {kind}")


def _validate(data: BuildDataAssetInput) -> Optional[str]:
    if not _NAME_RE.match(data.name):
        return f"invalid name '{data.name}' — use lowercase identifier (a-z, 0-9, _)."
    body = data.select_sql.strip().rstrip(";").strip()
    if not _SELECT_RE.match(body):
        return "select_sql must be a single SELECT or WITH ... SELECT statement."
    if ";" in body:
        return "select_sql must be a single statement (no ';')."
    return None


def _execute_ddl(ddl: str) -> None:
    """Run the DDL on the guarded analytics write engine (sync, off-loop)."""
    from app.ai.code_execution.analytics_engine import get_analytics_write_engine

    engine = get_analytics_write_engine()
    with engine.begin() as conn:  # guard fires in before_cursor_execute
        conn.execute(text(ddl))


async def _record_instruction(runtime_ctx: Dict[str, Any], obj: str, description: str) -> None:
    """Record the asset as an AI-sourced Instruction (Analyst discovers it)."""
    db = runtime_ctx.get("db")
    organization = runtime_ctx.get("organization")
    if db is None or organization is None:
        logger.warning("build_data_asset: no db/organization in runtime_ctx; skipping Instruction record")
        return
    from app.models.instruction import Instruction

    text_body = (
        f"Data asset `{obj}` (agent-built). Prefer it over raw tables when relevant.\n\n{description}"
    )
    inst = Instruction(
        text=text_body,
        source_type="ai",
        status="published",
        load_mode="intelligent",
        category="data_asset",
        ai_source="engineer_asset",
        organization_id=str(organization.id),
        structured_data={"object": obj, "kind": "data_asset"},
    )
    db.add(inst)
    await db.commit()


class BuildDataAssetTool(Tool):
    """Engineer: build reusable views/tables in the analytics schema."""

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="build_data_asset",
            description=(
                "Create a reusable data asset (view, materialized view, or table) in the "
                "analytics schema. Use when a query pattern is worth precomputing or sharing "
                "(e.g. monthly_mrr, customer_health, churn_risk). Reads company data, writes "
                "only to analytics. Records the asset so it can be discovered and reused."
            ),
            category="action",
            version="1.0.0",
            input_schema=BuildDataAssetInput.model_json_schema(),
            output_schema=BuildDataAssetOutput.model_json_schema(),
            idempotent=False,
            timeout_seconds=60,
            tags=["engineer", "analytics", "view", "materialize"],
            allowed_modes=["chat", "deep"],
        )

    @property
    def input_model(self) -> Type[BaseModel]:
        return BuildDataAssetInput

    @property
    def output_model(self) -> Type[BaseModel]:
        return BuildDataAssetOutput

    async def run_stream(
        self, tool_input: Dict[str, Any], runtime_ctx: Dict[str, Any]
    ) -> AsyncIterator[ToolEvent]:
        data = BuildDataAssetInput(**tool_input)

        yield ToolStartEvent(type="tool.start", payload={"title": f"Building analytics.{data.name}"})

        if not flags.ENGINEER_ASSETS:
            yield ToolEndEvent(
                type="tool.end",
                payload={
                    "output": {"success": False, "error_message": "Engineer assets are disabled (HYBRID_ENGINEER_ASSETS off)."},
                    "observation": {"summary": "build_data_asset disabled by flag", "success": False},
                },
            )
            return

        err = _validate(data)
        if err:
            yield ToolEndEvent(
                type="tool.end",
                payload={
                    "output": {"success": False, "error_message": err},
                    "observation": {"summary": f"build_data_asset invalid input: {err}", "success": False},
                },
            )
            return

        # Resolve the physical object name AFTER validation (the _NAME_RE check
        # runs on the user-supplied name; the per-user/org prefix is added by us).
        # `obj` is the one physical identifier used for DDL, the Instruction
        # record, and all output events — keep them consistent so lookups resolve.
        physical_name = _physical_name(data.name, runtime_ctx)
        obj = f"analytics.{physical_name}"

        body = data.select_sql.strip().rstrip(";").strip()
        ddl = _build_ddl(physical_name, data.kind, body)

        yield ToolProgressEvent(type="tool.progress", payload={"stage": "creating", "object": obj})
        try:
            await asyncio.to_thread(_execute_ddl, ddl)
        except Exception as e:  # includes AnalyticsWriteViolation
            logger.error("build_data_asset DDL failed: %s", e, exc_info=True)
            yield ToolEndEvent(
                type="tool.end",
                payload={
                    "output": {"success": False, "object": obj, "kind": data.kind, "error_message": str(e)},
                    "observation": {"summary": f"build_data_asset failed: {e}", "success": False},
                },
            )
            return

        yield ToolProgressEvent(type="tool.progress", payload={"stage": "recording"})
        try:
            await _record_instruction(runtime_ctx, obj, data.description)
        except Exception as e:
            logger.warning("build_data_asset: created %s but failed to record instruction: %s", obj, e)

        yield ToolEndEvent(
            type="tool.end",
            payload={
                "output": {"success": True, "object": obj, "kind": data.kind},
                "observation": {
                    "summary": f"Built {data.kind} {obj} and recorded it for reuse.",
                    "success": True,
                },
            },
        )
