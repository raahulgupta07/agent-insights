"""Run Skill File Tool — execute a bundled L3 *script* from a loaded skill.

Native skill execution (Phase S3.2). Where ``read_skill_file`` only returns a
script's source for inspection, this tool actually runs it. The script is pulled
by skill name + relative path (same per-user/org visibility as ``load_skill`` via
``get_skill_body``), then executed through the existing ``StreamingCodeExecutor``
sandbox — the very engine that runs widget code. That means:

  * AST security gate: forbidden imports (os/sys/subprocess/socket/...) and SQL
    write statements are rejected BEFORE execution (UnsafePythonError/UnsafeSQLError).
  * Per-user data: the script's ``generate_df(ds_clients, excel_files, ...)`` receives
    the caller's already-credentialed, quota-wrapped data-source clients. Data is read
    via ``ds_clients[key].execute_query(sql)`` — never the filesystem.

The script contract: define ``generate_df(ds_clients, excel_files, *args, **kwargs)``
returning a pandas DataFrame. Gated by ``flags.SKILLS``.
"""

from typing import AsyncIterator, Dict, Any, Type, Optional
import asyncio
import logging
import os
from datetime import datetime

from pydantic import BaseModel

from app.ai.tools.base import Tool
from app.ai.tools.metadata import ToolMetadata
from app.ai.tools.schemas.events import (
    ToolEvent,
    ToolStartEvent,
    ToolProgressEvent,
    ToolEndEvent,
    ToolErrorEvent,
)
from app.ai.tools.schemas.run_skill_file import (
    RunSkillFileInput,
    RunSkillFileOutput,
)

logger = logging.getLogger(__name__)

_PREVIEW_ROWS = 20
_DEFAULT_TIMEOUT_S = 60


def _timeout_s() -> int:
    raw = os.environ.get("SKILL_EXEC_TIMEOUT_S")
    if not raw:
        return _DEFAULT_TIMEOUT_S
    try:
        n = int(raw)
        return n if n > 0 else _DEFAULT_TIMEOUT_S
    except (TypeError, ValueError):
        return _DEFAULT_TIMEOUT_S


async def _new_skill_run(*, skill_id, user_id, org_id, path) -> Optional[str]:
    """Insert a SkillRun row (status='running') in an isolated session.

    Best-effort: never breaks the tool if tracking fails. Mirrors the isolated-
    session pattern used by record_skill_use (avoids the agent's shared session).
    """
    try:
        from app.settings.database import create_async_session_factory
        from app.models.skill_run import SkillRun

        maker = create_async_session_factory()
        async with maker() as db:
            run = SkillRun(
                skill_id=str(skill_id),
                owner_user_id=str(user_id) if user_id else None,
                organization_id=str(org_id) if org_id else None,
                path=path,
                status="running",
                started_at=datetime.utcnow(),
            )
            db.add(run)
            await db.commit()
            return str(run.id)
    except Exception as e:  # tracking must never break execution
        logger.warning(f"run_skill_file: could not create SkillRun: {e}")
        return None


async def _finish_skill_run(run_id, *, status, rows=None, stdout=None, error=None) -> None:
    if not run_id:
        return
    try:
        from app.settings.database import create_async_session_factory
        from app.models.skill_run import SkillRun
        from sqlalchemy import select

        maker = create_async_session_factory()
        async with maker() as db:
            res = await db.execute(select(SkillRun).where(SkillRun.id == str(run_id)))
            run = res.scalar_one_or_none()
            if run is None:
                return
            run.status = status
            run.rows = rows
            run.stdout = (stdout or None)
            run.error = (error or None)
            run.finished_at = datetime.utcnow()
            await db.commit()
    except Exception as e:
        logger.warning(f"run_skill_file: could not finalize SkillRun {run_id}: {e}")


class RunSkillFileTool(Tool):
    """Execute a bundled script from a loaded skill in the sandboxed code engine."""

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="run_skill_file",
            description=(
                "Execute a bundled script (kind='script', e.g. scripts/cohort.py) from a "
                "loaded skill. The script must define generate_df(ds_clients, excel_files, "
                "...) and return a DataFrame. Runs in the AST-gated sandbox; reads data via "
                "the provided ds_clients, never the filesystem. Use after load_skill when the "
                "SKILL.md tells you to run one of its scripts. This produces a real "
                "chart/step you can later compose with create_artifact. ALWAYS pass a "
                "distinct `title` per run (e.g. 'Artist Revenue Pareto') so repeated runs "
                "are distinguishable; for joins/aggregations pass `sql`."
            ),
            category="action",
            version="1.0.0",
            input_schema=RunSkillFileInput.model_json_schema(),
            output_schema=RunSkillFileOutput.model_json_schema(),
            max_retries=0,
            timeout_seconds=120,
            idempotent=False,
            is_active=True,
            required_permissions=[],
            tags=["skill", "file", "script", "execute"],
            observation_policy="on_trigger",
            allowed_modes=["chat", "deep"],
            examples=[
                {
                    "input": {"skill": "<skill-name>", "path": "scripts/cohort.py"},
                    "description": "Run a skill's bundled analysis script and get the result DataFrame",
                },
            ],
        )

    @property
    def input_model(self) -> Type[BaseModel]:
        return RunSkillFileInput

    @property
    def output_model(self) -> Type[BaseModel]:
        return RunSkillFileOutput

    async def run_stream(
        self, tool_input: Dict[str, Any], runtime_ctx: Dict[str, Any]
    ) -> AsyncIterator[ToolEvent]:
        try:
            data = RunSkillFileInput(**tool_input)
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
        settings = runtime_ctx.get("settings")
        ds_clients = runtime_ctx.get("ds_clients") or {}

        if not all([db, organization]):
            yield ToolErrorEvent(
                type="tool.error",
                payload={
                    "error": "Missing required runtime context (db, organization)",
                    "code": "MISSING_CONTEXT",
                },
            )
            return

        run_id = None
        try:
            from app.ai.skills.loader import get_skill_body
            from app.ai.skills.files import get_skill_file, KIND_SCRIPT
            from app.ai.code_execution.code_execution import (
                StreamingCodeExecutor,
                UnsafePythonError,
                UnsafeSQLError,
            )

            user_id = str(user.id) if user else None

            # Per-user/org visibility — identical gate to load_skill/read_skill_file.
            body = await get_skill_body(
                db,
                organization_id=str(organization.id),
                user_id=user_id,
                name=data.skill,
            )
            if not body:
                yield _fail(data.skill, data.path, "Skill not found or not available.")
                return

            file = await get_skill_file(db, skill_id=body["id"], path=data.path)
            if not file:
                yield _fail(body["name"], data.path, "File not found in skill bundle.")
                return

            if file.get("kind") != KIND_SCRIPT:
                yield _fail(
                    body["name"],
                    data.path,
                    f"'{data.path}' is kind='{file.get('kind')}', not a runnable script. "
                    "Use read_skill_file to read non-script resources.",
                )
                return

            code = file.get("content") or ""
            if not code.strip():
                yield _fail(body["name"], data.path, "Script is empty.")
                return

            from app.ai.skills.run_guard import user_run_slot, SkillRunBusyError

            # Per-user concurrency cap (fast reject if user is at their limit).
            try:
                slot = user_run_slot(user_id)
                await slot.__aenter__()
            except SkillRunBusyError as e:
                yield _fail(body["name"], data.path, str(e))
                return

            # Track this run (isolated session; best-effort).
            run_id = await _new_skill_run(
                skill_id=body["id"], user_id=user_id,
                org_id=str(organization.id), path=file.get("path", data.path),
            )

            # Optionally run a SQL query whose rows are passed to the skill as
            # input_df. Fail-soft: a bad query logs + continues WITHOUT input_df
            # (the skill still runs, just without the pre-computed frame).
            input_df = None
            if data.sql and data.sql.strip():
                input_df = await _run_input_query(
                    ds_clients, data.data_source, data.sql,
                )

            # Execute in the existing sandbox. The AST gate + SQL guard run inside
            # execute_code_async before exec(); clients are the caller's own.
            # enforce_limits=True activates the optional RLIMIT_AS mem cap when
            # SKILL_EXEC_MEM_CAP_MB is set. Hard wall-clock timeout via wait_for.
            executor = StreamingCodeExecutor(organization_settings=settings)
            try:
                df, stdout, queries = await asyncio.wait_for(
                    executor.execute_code_async(
                        code=code,
                        ds_clients=ds_clients,
                        excel_files=[],
                        enforce_limits=True,
                        input_df=input_df,
                    ),
                    timeout=_timeout_s(),
                )
            except asyncio.TimeoutError:
                await _finish_skill_run(
                    run_id, status="error",
                    error=f"Timed out after {_timeout_s()}s",
                )
                yield _fail(
                    body["name"], data.path,
                    f"Script exceeded the {_timeout_s()}s execution limit and was stopped.",
                )
                return
            finally:
                await slot.__aexit__(None, None, None)

            rows = int(getattr(df, "shape", [0])[0]) if df is not None else 0
            columns = list(map(str, getattr(df, "columns", []))) if df is not None else []
            preview = _safe_preview(df)

            summary = (
                f"Ran script '{file.get('path', data.path)}' from skill '{body['name']}' "
                f"under user {user_id or 'unknown'}: {rows} rows x {len(columns)} cols"
                + (f" via {len(queries)} query(ies)." if queries else ".")
            )

            await _finish_skill_run(
                run_id, status="success", rows=rows,
                stdout=(stdout or "").strip() or None,
            )

            # Build a composable step/visualization exactly like create_data so the
            # agent can assemble skill results into a dashboard via create_artifact.
            # Fully fail-soft: any error here leaves the original (raw-rows) output
            # path completely untouched (back-compat).
            viz_formatted = None
            viz_data_model = None
            viz_view = None
            viz_code = None
            # Prefer the agent-supplied descriptive title so repeated runs of the
            # same skill (e.g. pareto for artist / genre / country) produce
            # distinguishable steps — otherwise every step is titled the bare
            # skill name, the planner can't tell them apart in available_steps,
            # and it re-runs instead of assembling them into a dashboard.
            query_title = (
                (data.title.strip() if getattr(data, "title", None) and data.title.strip() else None)
                or (body.get("name") or f"{data.skill} — {file.get('path', data.path)}")
            )
            try:
                if df is not None and rows > 0:
                    viz_formatted, viz_data_model, viz_view = _build_skill_viz(
                        df, executor, query_title
                    )
                    if viz_formatted and viz_data_model and viz_view:
                        # Readable code block: the SQL passed (if any) + the skill script.
                        sql_block = (data.sql.strip() if (data.sql and data.sql.strip()) else None)
                        parts = []
                        if sql_block:
                            parts.append(f"-- SQL\n{sql_block}")
                        parts.append(f"# Skill script: {file.get('path', data.path)}\n{code}")
                        viz_code = "\n\n".join(parts)
                        # Emit early so agent_v2 creates the Query/Step/Visualization
                        # (one per run_skill_file call — state is reset per tool call).
                        yield ToolProgressEvent(
                            type="tool.progress",
                            payload={
                                "stage": "data_model_type_determined",
                                "data_model_type": viz_data_model["type"],
                                "query_title": query_title,
                            },
                        )
                    else:
                        viz_formatted = viz_data_model = viz_view = None
            except Exception as e:  # never break the tool on viz inference
                logger.warning(f"run_skill_file: skipping composable viz: {e}")
                viz_formatted = viz_data_model = viz_view = viz_code = None

            output = RunSkillFileOutput(
                success=True,
                skill=body["name"],
                path=file.get("path", data.path),
                rows=rows,
                columns=columns,
                preview=preview,
                stdout=(stdout or "").strip() or None,
                message=None,
            )
            output_payload = output.model_dump()
            # Additive composable fields (read by agent_v2's create_data-style
            # final-write handler). Omitted entirely when no usable viz was built.
            if viz_formatted and viz_data_model and viz_view:
                output_payload["success"] = True
                output_payload["code"] = viz_code
                output_payload["data"] = viz_formatted
                output_payload["data_model"] = viz_data_model
                output_payload["view"] = viz_view
                output_payload["view_options"] = viz_view
            yield ToolEndEvent(
                type="tool.end",
                payload={
                    "output": output_payload,
                    "observation": {
                        "summary": summary,
                        "skill": body["name"],
                        "path": file.get("path", data.path),
                        "rows": rows,
                        "columns": columns,
                        "preview": preview,
                        "stdout": (stdout or "").strip(),
                        "queries": queries,
                    },
                },
            )
        except (UnsafePythonError, UnsafeSQLError) as e:
            # Security gate fired — report as a clean, non-fatal tool result.
            await _finish_skill_run(run_id, status="blocked", error=str(e))
            yield ToolEndEvent(
                type="tool.end",
                payload={
                    "output": RunSkillFileOutput(
                        success=False,
                        skill=data.skill,
                        path=data.path,
                        message=f"Blocked by sandbox security gate: {e}",
                    ).model_dump(),
                    "observation": {
                        "summary": f"Script blocked by sandbox security gate: {e}",
                        "error": {"type": "security_blocked", "message": str(e)},
                    },
                },
            )
        except Exception as e:
            logger.exception(f"run_skill_file failed: {e}")
            await _finish_skill_run(run_id, status="error", error=str(e))
            yield ToolErrorEvent(
                type="tool.error",
                payload={"error": f"Run failed: {e}", "code": "RUN_FAILED"},
            )
            return


async def _run_input_query(ds_clients: dict, data_source, sql: str):
    """Run `sql` on a ds client and return the rows as a pandas DataFrame.

    Resolves the client: `data_source` (if given) matches a ds_clients key, else
    the first available client. Clients' `execute_query(sql)` returns a DataFrame.
    Fail-soft: any error (no client, query failure, build failure) logs a warning
    and returns None so the skill still runs without input_df.
    """
    try:
        if not ds_clients:
            logger.warning("run_skill_file: sql provided but no ds_clients available")
            return None

        # Client keys are "<DataSourceName>:<connection>" (e.g.
        # "Music Store:postgresql-1"). Resolve in order: exact key, then prefix
        # match on the data-source-name part before ':', then case-insensitive,
        # then (only if no data_source given) the first client. With multiple
        # active sources, NEVER silently fall through to an arbitrary client when
        # a data_source was named — that runs the SQL on the wrong DB.
        client = None
        if data_source:
            if data_source in ds_clients:
                client = ds_clients[data_source]
            else:
                ds_l = data_source.strip().lower()
                for key, c in ds_clients.items():
                    name = str(key).split(":", 1)[0].strip().lower()
                    if name == ds_l or str(key).strip().lower() == ds_l:
                        client = c
                        break
                if client is None:
                    logger.warning(
                        f"run_skill_file: data_source '{data_source}' not found "
                        f"among {list(ds_clients.keys())}; cannot run input query."
                    )
                    return None
        else:
            client = next(iter(ds_clients.values()), None)

        if client is None or "execute_query" not in dir(client):
            logger.warning("run_skill_file: resolved client cannot execute_query")
            return None

        # execute_query is synchronous — run off the event loop.
        result = await asyncio.to_thread(client.execute_query, sql)

        import pandas as pd

        if isinstance(result, pd.DataFrame):
            return result
        # Some clients may return rows (list of dicts/tuples) — coerce to a frame.
        return pd.DataFrame(result)
    except Exception as e:
        logger.warning(f"run_skill_file: input_df query failed, continuing without it: {e}")
        return None


def _fail(skill: str, path: str, message: str) -> ToolEndEvent:
    return ToolEndEvent(
        type="tool.end",
        payload={
            "output": RunSkillFileOutput(
                success=False, skill=skill, path=path, message=message
            ).model_dump(),
            "observation": {
                "summary": message,
                "error": {"type": "not_found", "message": message},
            },
        },
    )


def _build_skill_viz(df, executor, query_title: str):
    """Build a composable (data_model, view, formatted) triple from a skill df.

    Mirrors the create_data persistence contract WITHOUT an LLM:
      * formatted = StreamingCodeExecutor.format_df_for_widget(df) (widget_data shape)
      * data_model = a minimal {type, series} — bar_chart when the skill's
        item/value convention is present, else table.
      * view = build_view_from_data_model(...) (ViewSchema v2 dict).

    Never raises: any failure falls back to a plain table view (or None if even
    formatting is impossible) so the tool stays back-compatible.
    """
    try:
        formatted = executor.format_df_for_widget(df)
    except Exception as e:  # cannot format -> no composable viz
        logger.warning(f"run_skill_file: format_df_for_widget failed: {e}")
        return None, None, None

    cols = [
        str(c.get("field") or c.get("headerName"))
        for c in (formatted.get("columns") or [])
        if isinstance(c, dict) and (c.get("field") or c.get("headerName"))
    ]

    # Infer a minimal data_model. The skill convention is item/value -> bar.
    data_model = {"type": "table", "series": []}
    try:
        if "item" in cols and "value" in cols:
            data_model = {
                "type": "bar_chart",
                "series": [{"name": "value", "key": "item", "value": "value"}],
            }
    except Exception:
        data_model = {"type": "table", "series": []}

    # Build the ViewSchema v2 view; fall back to a bare table on any error.
    view_payload = None
    try:
        from app.ai.tools.implementations.create_data import build_view_from_data_model

        view_schema = build_view_from_data_model(
            data_model, title=query_title, palette_theme="default", available_columns=cols
        )
        view_payload = view_schema.model_dump(exclude_none=True) if view_schema else None
    except Exception as e:
        logger.warning(f"run_skill_file: build_view_from_data_model failed: {e}")
        view_payload = None

    if not view_payload:
        # Robust fallback — a valid v2 table view of whatever type we settled on.
        data_model = {"type": "table", "series": []}
        view_payload = {"version": "v2", "view": {"type": "table"}}

    return formatted, data_model, view_payload


def _safe_preview(df) -> list:
    """First N rows as JSON-safe records; never raises."""
    if df is None:
        return []
    try:
        import json
        head = df.head(_PREVIEW_ROWS)
        # Round-trip through pandas JSON to coerce numpy/Timestamp to native types.
        return json.loads(head.to_json(orient="records", date_format="iso"))
    except Exception:
        try:
            return df.head(_PREVIEW_ROWS).astype(str).to_dict(orient="records")
        except Exception:
            return []
