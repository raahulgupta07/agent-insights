"""remember_this — agent-callable Shared Memory save.

Lets the agent explicitly vouch for a hard-won query/approach mid-answer and
persist it to Shared Memory, the explicit counterpart to the automatic
verified-golden gate. Reuse is leak-safe by construction: a 'data'-scoped
memory is keyed to the current data source's model/schema signature, so only
users who hold the same data ever retrieve it; 'private' stays in the caller's
own scratchpad.

Flag-gated by ``flags.SHARED_MEMORY``. Fail-soft everywhere: when the flag is
off, or anything goes wrong, the tool returns a friendly no-op ToolEnd rather
than raising into the agent loop.
"""
import logging
from typing import AsyncIterator, Dict, Any, Type, List, Optional

from pydantic import BaseModel

from app.ai.tools.base import Tool
from app.ai.tools.metadata import ToolMetadata
from app.ai.tools.schemas.remember_this import RememberThisInput, RememberThisOutput
from app.ai.tools.schemas.events import (
    ToolEvent,
    ToolStartEvent,
    ToolEndEvent,
)

logger = logging.getLogger("app.ai.tools.remember_this")


async def _report_data_source_ids(db, report) -> List[str]:
    """Data source ids attached to the report (fail-soft, no lazy-load).

    Re-queries the association table with the live session so we never trip an
    async lazy-load on a detached ``report.data_sources`` relationship.
    """
    report_id = getattr(report, "id", None)
    if db is None or not report_id:
        return []
    try:
        from sqlalchemy import select
        from app.models.report_data_source_association import (
            report_data_source_association as assoc,
        )

        rows = (
            await db.execute(
                select(assoc.c.data_source_id).where(
                    assoc.c.report_id == str(report_id)
                )
            )
        ).all()
        return [str(r[0]) for r in rows if r[0]]
    except Exception as e:  # pragma: no cover - defensive
        logger.debug("remember_this: resolve report data sources failed: %s", e)
        return []


def _end(status: str, message: str, *, written: int = 0, scope: str = "data") -> ToolEndEvent:
    return ToolEndEvent(
        type="tool.end",
        payload={
            "output": {"status": status, "written": written, "scope": scope},
            "observation": {
                "summary": message,
                "artifacts": [],
                "analysis_complete": True,
                "final_answer": message,
            },
        },
    )


class RememberThisTool(Tool):
    """Save a proven query/approach to Shared Memory so it can be reused later."""

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="remember_this",
            description=(
                "Save a proven query/approach so you and teammates with the same data "
                "can reuse it later. Call this after you've confirmed a query or method "
                "actually works and is worth reusing. Pass the exact `sql_or_dax` when "
                "you have one; use scope='data' to share with everyone who holds this "
                "data (leak-safe), or scope='private' for your own scratchpad."
            ),
            category="action",
            version="1.0.0",
            input_schema=RememberThisInput.model_json_schema(),
            output_schema=RememberThisOutput.model_json_schema(),
            max_retries=1,
            timeout_seconds=15,
            idempotent=True,
            required_permissions=[],
            tags=["memory", "shared-memory", "reuse", "learning"],
            examples=[
                {
                    "input": {
                        "summary": "Monthly net revenue by channel — sum net_amount, group by month + channel",
                        "sql_or_dax": "SELECT date_trunc('month', order_date) m, channel, SUM(net_amount) FROM sales GROUP BY 1,2",
                        "kind": "query_template",
                        "scope": "data",
                    },
                    "description": "save a verified revenue query for anyone with the same sales data",
                },
                {
                    "input": {
                        "summary": "This model stores amounts in cents — divide by 100 before displaying",
                        "kind": "howto",
                        "scope": "data",
                    },
                    "description": "save a gotcha/approach (no single query)",
                },
            ],
        )

    @property
    def input_model(self) -> Type[BaseModel]:
        return RememberThisInput

    @property
    def output_model(self) -> Type[BaseModel]:
        return RememberThisOutput

    async def run_stream(
        self, tool_input: Dict[str, Any], runtime_ctx: Dict[str, Any]
    ) -> AsyncIterator[ToolEvent]:
        data = RememberThisInput(**tool_input)
        scope = data.scope
        yield ToolStartEvent(
            type="tool.start",
            payload={"summary": data.summary, "kind": data.kind, "scope": scope},
        )

        # Flag gate — friendly no-op when Shared Memory is off.
        try:
            from app.settings.hybrid_flags import flags
            if not flags.SHARED_MEMORY:
                yield _end(
                    "noop",
                    "Shared Memory is turned off, so I couldn't save this for reuse.",
                    scope=scope,
                )
                return
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("remember_this: flag read failed: %s", e)
            yield _end("noop", "I couldn't save this right now.", scope=scope)
            return

        try:
            from app.services.knowledge import capture as C
            from app.services.knowledge.scope_resolver import (
                resolve_agent_scopes,
                private_scope,
            )

            db = runtime_ctx.get("db")
            organization = runtime_ctx.get("organization")
            user = runtime_ctx.get("user")
            report = runtime_ctx.get("report")

            organization_id = getattr(organization, "id", None) or runtime_ctx.get(
                "organization_id"
            )
            user_id = getattr(user, "id", None) or runtime_ctx.get("user_id")

            if db is None or not organization_id:
                yield _end("noop", "I couldn't save this right now.", scope=scope)
                return

            summary = (data.summary or "").strip()
            sql = (data.sql_or_dax or "").strip()
            title = summary[:120] or ("verified query" if sql else "approach")

            written = 0

            # PRIVATE: personal scratchpad, no data source needed.
            if scope == "private":
                if not user_id:
                    yield _end("noop", "I couldn't save this privately right now.", scope=scope)
                    return
                content: Dict[str, Any] = {"kind": data.kind, "summary": summary}
                if sql:
                    content["template"] = sql
                written = await C.capture(
                    db,
                    organization_id=str(organization_id),
                    scopes=[private_scope(str(user_id))],
                    kind=data.kind,
                    title=title,
                    content=content,
                    text=(sql or summary),
                    user_id=str(user_id),
                    verified=True,
                )
                await self._safe_commit(db)
                yield self._done(written, scope)
                return

            # DATA scope: key the memory to the report's data source(s).
            ds_ids = await _report_data_source_ids(db, report)
            if not ds_ids:
                # No attached data source to key against — degrade to private so
                # the agent's effort isn't lost.
                if user_id:
                    content = {"kind": data.kind, "summary": summary}
                    if sql:
                        content["template"] = sql
                    written = await C.capture(
                        db,
                        organization_id=str(organization_id),
                        scopes=[private_scope(str(user_id))],
                        kind=data.kind,
                        title=title,
                        content=content,
                        text=(sql or summary),
                        user_id=str(user_id),
                        verified=True,
                    )
                    await self._safe_commit(db)
                    if written:
                        yield _end(
                            "saved",
                            "No shared data source was attached, so I saved this to your personal memory instead.",
                            written=written,
                            scope="private",
                        )
                        return
                yield _end(
                    "noop",
                    "There's no attached data source to key this to, so I couldn't save it for reuse.",
                    scope=scope,
                )
                return

            for ds_id in ds_ids:
                if sql:
                    # A concrete query -> sanitized, parameterized template keyed
                    # to the source's model/schema scopes (verified => active now).
                    written += await C.capture_verified_query(
                        db,
                        organization_id=str(organization_id),
                        data_source_id=str(ds_id),
                        sql=sql,
                        name=title,
                        user_id=str(user_id) if user_id else None,
                    )
                else:
                    # A narrative approach/gotcha -> capture under the same shared
                    # scopes the source resolves to.
                    scopes = await self._resolve_scopes(db, ds_id, resolve_agent_scopes)
                    if not scopes:
                        continue
                    written += await C.capture(
                        db,
                        organization_id=str(organization_id),
                        scopes=scopes,
                        kind=data.kind,
                        title=title,
                        content={"kind": data.kind, "summary": summary},
                        text=summary,
                        user_id=str(user_id) if user_id else None,
                        data_source_id=str(ds_id),
                        verified=True,
                    )

            await self._safe_commit(db)

            if written:
                yield self._done(written, scope)
            else:
                yield _end(
                    "noop",
                    "I couldn't turn that into a reusable memory this time.",
                    scope=scope,
                )
        except Exception as e:  # pragma: no cover - never crash the loop
            logger.warning("remember_this failed: %s", e)
            yield _end("error", "I hit a snag saving that to memory, but carried on.", scope=scope)

    # --- helpers -------------------------------------------------------------

    def _done(self, written: int, scope: str) -> ToolEndEvent:
        where = "your teammates with the same data" if scope == "data" else "your personal memory"
        return _end(
            "saved",
            f"Saved this for reuse by {where}.",
            written=written,
            scope=scope,
        )

    async def _resolve_scopes(self, db, data_source_id, resolve_agent_scopes) -> List[dict]:
        """Resolve the shared scopes for a data source (mirrors capture's own
        internal resolver, kept local so we only import from knowledge/*)."""
        try:
            from sqlalchemy import select
            from app.models.data_source import DataSource
            from app.models.connection_table import ConnectionTable

            ds = (
                await db.execute(
                    select(DataSource).where(DataSource.id == str(data_source_id))
                )
            ).scalar_one_or_none()
            if ds is None:
                return []
            conn_ids = [str(c.id) for c in (getattr(ds, "connections", None) or [])]
            tables: List[Any] = []
            if conn_ids:
                tables = list(
                    (
                        await db.execute(
                            select(ConnectionTable).where(
                                ConnectionTable.connection_id.in_(conn_ids)
                            )
                        )
                    ).scalars().all()
                )
            return resolve_agent_scopes(ds, tables)
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("remember_this: scope resolve failed: %s", e)
            return []

    async def _safe_commit(self, db) -> None:
        try:
            await db.commit()
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("remember_this: commit failed: %s", e)
            try:
                await db.rollback()
            except Exception:
                pass
