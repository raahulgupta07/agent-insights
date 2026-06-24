"""resolve_metric Tool — look up an approved business metric definition.

Knowledge Layer Phase 4. Given a metric name (case-insensitive, scoped to the
organization, optionally to a data source), returns the approved
MetricDefinition's definition, table_ref, sql_calc and owner so the agent reuses
the canonical metric rather than re-deriving it.

Self-gates on flags.METRICS_CATALOG: when the catalog is off the tool simply
returns ``found=False`` (it never raises), so a fresh deploy behaves like
upstream. Native ToolRegistry pattern (auto-registered via implementations/).
"""
from typing import AsyncIterator, Dict, Any, Type
import logging

from pydantic import BaseModel
from sqlalchemy import select, func

from app.ai.tools.base import Tool
from app.ai.tools.metadata import ToolMetadata
from app.ai.tools.schemas.events import (
    ToolEvent,
    ToolStartEvent,
    ToolEndEvent,
    ToolErrorEvent,
)
from app.ai.tools.schemas.resolve_metric import (
    ResolveMetricInput,
    ResolveMetricOutput,
    ResolveMetricMatch,
)
from app.settings.hybrid_flags import flags
from app.models.metric_definition import MetricDefinition
from app.ai.brain import bitemporal

logger = logging.getLogger(__name__)


class ResolveMetricTool(Tool):
    """Resolve an approved named business metric to its definition + SQL."""

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="resolve_metric",
            description=(
                "Look up an APPROVED business metric by name (case-insensitive). "
                "Use this before computing a named metric so you reuse the "
                "organization's canonical definition and SQL instead of "
                "inventing one. Returns definition, table_ref, sql_calc and "
                "owner. Optionally scope by data_source_id."
            ),
            category="both",
            version="1.0.0",
            input_schema=ResolveMetricInput.model_json_schema(),
            output_schema=ResolveMetricOutput.model_json_schema(),
            max_retries=1,
            timeout_seconds=15,
            idempotent=True,
            tags=["metrics", "knowledge", "lookup"],
            examples=[
                {
                    "input": {"metric_name": "Active Customers"},
                    "description": "Resolve a metric by name across the org",
                },
                {
                    "input": {"metric_name": "MRR", "data_source_id": "<ds-uuid>"},
                    "description": "Resolve a metric scoped to one data source",
                },
            ],
        )

    @property
    def input_model(self) -> Type[BaseModel]:
        return ResolveMetricInput

    @property
    def output_model(self) -> Type[BaseModel]:
        return ResolveMetricOutput

    async def run_stream(
        self, tool_input: Dict[str, Any], runtime_ctx: Dict[str, Any]
    ) -> AsyncIterator[ToolEvent]:
        try:
            data = ResolveMetricInput(**tool_input)
        except Exception as e:
            yield ToolErrorEvent(
                type="tool.error",
                payload={"error": f"Invalid input: {e}", "code": "INVALID_INPUT"},
            )
            return

        yield ToolStartEvent(
            type="tool.start",
            payload={"metric_name": data.metric_name, "data_source_id": data.data_source_id},
        )

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

        # When the catalog is off, behave as "no approved metric" — no leak.
        if not flags.METRICS_CATALOG:
            output = ResolveMetricOutput(
                success=True,
                found=False,
                message="Metrics catalog is not enabled.",
            )
            yield ToolEndEvent(
                type="tool.end",
                payload={
                    "output": output.model_dump(),
                    "observation": {"summary": "Metrics catalog disabled; no metric resolved."},
                },
            )
            return

        try:
            name = (data.metric_name or "").strip()
            stmt = (
                select(MetricDefinition)
                .where(MetricDefinition.organization_id == str(organization.id))
                .where(MetricDefinition.status == "approved")
                .where(func.lower(MetricDefinition.name) == name.lower())
            )
            if data.data_source_id:
                stmt = stmt.where(MetricDefinition.data_source_id == str(data.data_source_id))

            # Bi-temporal (HYBRID_BITEMPORAL): time-travel if as_of is given,
            # else only the currently-valid version reaches the agent. Both are
            # no-ops when the flag is OFF (conditions empty / None).
            as_of = None
            if getattr(data, "as_of", None):
                try:
                    from datetime import datetime
                    raw = str(data.as_of).strip()
                    # tolerate a trailing Z (UTC) which fromisoformat rejects pre-3.11
                    if raw.endswith("Z"):
                        raw = raw[:-1] + "+00:00"
                    as_of = datetime.fromisoformat(raw)
                except Exception:
                    as_of = None  # parse fail -> ignore, fall back to current
            if as_of is not None:
                for cond in bitemporal.asof_conditions(MetricDefinition, as_of):
                    stmt = stmt.where(cond)
            else:
                cond = bitemporal.current_condition(MetricDefinition)
                if cond is not None:
                    stmt = stmt.where(cond)

            stmt = stmt.order_by(MetricDefinition.name.asc())
            row = (await db.execute(stmt)).scalars().first()

            if row is None:
                # Surface approved metric names as candidates for a near-miss.
                cand_stmt = (
                    select(MetricDefinition.name)
                    .where(MetricDefinition.organization_id == str(organization.id))
                    .where(MetricDefinition.status == "approved")
                )
                if data.data_source_id:
                    cand_stmt = cand_stmt.where(
                        MetricDefinition.data_source_id == str(data.data_source_id)
                    )
                cand_stmt = cand_stmt.order_by(MetricDefinition.name.asc()).limit(25)
                candidates = [c for c in (await db.execute(cand_stmt)).scalars().all() if c]
                output = ResolveMetricOutput(
                    success=True,
                    found=False,
                    candidates=candidates,
                    message=f"No approved metric named '{name}'.",
                )
                yield ToolEndEvent(
                    type="tool.end",
                    payload={
                        "output": output.model_dump(),
                        "observation": {
                            "summary": f"No approved metric '{name}' (candidates: {len(candidates)})",
                        },
                    },
                )
                return

            match = ResolveMetricMatch(
                name=row.name,
                definition=row.definition or "",
                table_ref=row.table_ref or "",
                sql_calc=row.sql_calc or "",
                owner=row.owner,
                data_source_id=str(row.data_source_id),
            )
            output = ResolveMetricOutput(
                success=True,
                found=True,
                metric=match,
                message=f"Resolved metric '{row.name}'.",
            )
            yield ToolEndEvent(
                type="tool.end",
                payload={
                    "output": output.model_dump(),
                    "observation": {
                        "summary": f"Resolved metric '{row.name}' -> {row.table_ref or 'n/a'}",
                        "artifacts": [
                            {
                                "type": "metric_definition",
                                "name": row.name,
                                "definition": match.definition,
                                "table_ref": match.table_ref,
                                "sql_calc": match.sql_calc,
                                "owner": match.owner,
                            }
                        ],
                    },
                },
            )
        except Exception as e:
            logger.exception(f"resolve_metric failed: {e}")
            yield ToolErrorEvent(
                type="tool.error",
                payload={"error": f"Resolve failed: {e}", "code": "RESOLVE_FAILED"},
            )
