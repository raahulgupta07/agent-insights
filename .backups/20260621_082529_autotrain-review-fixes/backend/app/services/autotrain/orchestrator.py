"""Autotrain orchestrator — SOURCE-AGNOSTIC.

autotrain(db, organization, data_source, table) runs a registry of steps that
each: are flag-checked, never raise, and write PENDING knowledge through the
existing brain bus. Works for BOTH an uploaded staging table and a live
connector table (caller just passes a (data_source, table) pair).

Steps:
  codex   (always, when AUTOTRAIN) -> pending SemanticTable + MetricDefinition
  profile (AUTOTRAIN_PROFILE)      -> profile_v2 onto datasource_tables.metadata_json
  qa      (AUTOTRAIN_QA)           -> generate->execute->keep verified -> query library
"""
from __future__ import annotations

import asyncio
import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)


def _build_llm_inference(model) -> Optional[Callable[[str], str]]:
    if model is None:
        return None
    try:
        from app.ai.llm.llm import LLM
        from app.dependencies import async_session_maker

        return LLM(model, usage_session_maker=async_session_maker).inference
    except Exception:
        logger.exception("autotrain: could not build llm_inference")
        return None


def _make_run_sql(engine):
    """run_sql(sql)->(ok, err): execute a read-only SELECT on the write engine
    (write-guard blocks writes; SELECT passes; pgbouncer-safe)."""
    from sqlalchemy import text

    def run_sql(sql: str):
        try:
            with engine.connect() as c:
                c.execute(text(sql))
            return True, ""
        except Exception as e:  # noqa: BLE001
            return False, str(e)[:300]

    return run_sql


async def autotrain(
    db,
    *,
    organization,
    data_source,
    table: str,
    schema: str = "staging",
    model=None,
    llm_inference: Optional[Callable[[str], str]] = None,
    steps: Optional[list] = None,
) -> dict:
    """Returns a summary dict. Never raises."""
    from app.settings.hybrid_flags import flags

    summary = {
        "table": table,
        "schema": schema,
        "semantics": [],
        "metrics": [],
        "qa": 0,
        "profiled": False,
        "steps_run": [],
        "errors": [],
    }
    if not flags.AUTOTRAIN:
        summary["errors"].append("AUTOTRAIN flag OFF")
        return summary

    org_id = getattr(organization, "id", None)
    ds_id = getattr(data_source, "id", None)
    if not org_id or not ds_id or not table:
        summary["errors"].append("missing org/ds/table")
        return summary

    if llm_inference is None:
        llm_inference = _build_llm_inference(model)

    try:
        from app.ai.code_execution.analytics_engine import get_analytics_write_engine

        engine = get_analytics_write_engine()
    except Exception:
        logger.exception("autotrain: no analytics engine")
        summary["errors"].append("no analytics engine")
        return summary

    # Route codex/profiler/qa SELECTs through the per-org RESTRICTED read engine
    # (search_path=staging_<org> only, no public) so LLM-generated SQL can't read
    # public.*. Fall back to the shared write engine for the "staging" schema.
    read_engine = engine  # default (shared 'staging' fallback)
    if schema.startswith("staging_"):
        try:
            from app.services.ingest import tenant_schema

            read_engine = tenant_schema.org_read_engine(org_id)
        except Exception:
            logger.exception(
                "autotrain: org_read_engine unavailable, falling back to write engine"
            )

    want = set(steps) if steps else {"codex", "profile", "qa"}

    # profile once, reuse across steps (cheap; heuristic metrics need it)
    prof = {}
    try:
        from app.services.autotrain import profiler

        prof = await asyncio.to_thread(
            profiler.profile_table, table, engine=read_engine, schema=schema
        ) or {}
    except Exception:
        logger.exception("autotrain: profile compute failed")

    # --- codex: description + use-cases + metrics -> pending -----------------
    if "codex" in want:
        try:
            from app.services.autotrain import codex
            from app.services.autotrain import writeback

            enriched = await asyncio.to_thread(
                codex.codex_enrich,
                table,
                schema=schema,
                engine=read_engine,
                llm_inference=llm_inference,
            )
            if enriched:
                desc = (enriched.get("description") or "").strip()
                if enriched.get("grain"):
                    desc = f"{desc} Grain: {enriched['grain']}".strip()
                if desc:
                    sid = await writeback.write_semantic(
                        db, org_id=org_id, ds_id=ds_id, table_name=table, description=desc
                    )
                    if sid:
                        summary["semantics"].append(sid)
                for m in (enriched.get("metrics") or [])[:5]:
                    if not isinstance(m, dict) or not m.get("name") or not m.get("sql_calc"):
                        continue
                    mid = await writeback.write_metric(
                        db,
                        org_id=org_id,
                        ds_id=ds_id,
                        name=str(m["name"])[:120],
                        definition=str(m.get("definition", ""))[:1000],
                        sql_calc=str(m["sql_calc"])[:2000],
                        table_ref=str(m.get("table_ref", table))[:120],
                    )
                    if mid:
                        summary["metrics"].append(mid)
            # heuristic, profile-driven metrics (works without an LLM)
            try:
                from app.services.autotrain import metrics_gen

                for m in metrics_gen.propose_metrics(
                    table, profile=prof, schema=schema, llm_inference=llm_inference
                ):
                    if not isinstance(m, dict) or not m.get("name") or not m.get("sql_calc"):
                        continue
                    mid = await writeback.write_metric(
                        db,
                        org_id=org_id,
                        ds_id=ds_id,
                        name=str(m["name"])[:120],
                        definition=str(m.get("definition", ""))[:1000],
                        sql_calc=str(m["sql_calc"])[:2000],
                        table_ref=str(m.get("table_ref", table))[:120],
                    )
                    if mid and mid not in summary["metrics"]:
                        summary["metrics"].append(mid)
            except Exception:
                logger.exception("autotrain metrics_gen failed")
            summary["steps_run"].append("codex")
        except Exception:
            logger.exception("autotrain codex step failed")
            summary["errors"].append("codex")

    # --- profile: profile_v2 -> datasource_tables.metadata_json --------------
    if "profile" in want and flags.AUTOTRAIN_PROFILE:
        try:
            if prof:
                await _persist_profile(db, ds_id=ds_id, table=table, profile=prof)
                summary["profiled"] = True
            summary["steps_run"].append("profile")
        except Exception:
            logger.exception("autotrain profile step failed")
            summary["errors"].append("profile")

    # --- qa: generate -> execute -> keep verified -> query library -----------
    if "qa" in want and flags.AUTOTRAIN_QA and llm_inference is not None:
        try:
            from app.services.autotrain import qa_gen

            run_sql = _make_run_sql(read_engine)
            pairs = await asyncio.to_thread(
                qa_gen.generate_verified_qa,
                table,
                profile=prof,
                llm_inference=llm_inference,
                run_sql=run_sql,
                schema=schema,
            )
            n = await _persist_qa(db, org_id=org_id, ds_id=ds_id, pairs=pairs)
            summary["qa"] = n
            summary["steps_run"].append("qa")
        except Exception:
            logger.exception("autotrain qa step failed")
            summary["errors"].append("qa")

    return summary


async def _persist_profile(db, *, ds_id: str, table: str, profile: dict) -> None:
    """Best-effort: stash profile_v2 onto the matching DataSourceTable row."""
    try:
        from sqlalchemy import select
        from sqlalchemy.orm.attributes import flag_modified

        from app.models.datasource_table import DataSourceTable

        row = (
            await db.execute(
                select(DataSourceTable).where(
                    DataSourceTable.datasource_id == ds_id,
                    DataSourceTable.name == table,
                    DataSourceTable.deleted_at.is_(None),
                )
            )
        ).scalars().first()
        if row is None:
            return
        meta = dict(row.metadata_json or {})
        meta["profile_v2"] = profile
        row.metadata_json = meta
        flag_modified(row, "metadata_json")
        await db.commit()
    except Exception:
        logger.exception("persist_profile failed")


async def _persist_qa(db, *, org_id: str, ds_id: str, pairs: list) -> int:
    """Best-effort: write verified Q&A as PENDING query-library rows.

    Mirrors connector._persist_qa. De-dups by name within this call AND wraps
    each insert in a SAVEPOINT so a UniqueViolation on the (org, ds, name)
    constraint rolls back only that row — not the whole shared async session.
    """
    n = 0
    try:
        from app.models.query_library import QueryLibraryItem  # type: ignore
    except Exception:
        logger.info("persist_qa: QueryLibraryItem not importable, skipping")
        return 0
    from sqlalchemy.exc import IntegrityError

    seen: set = set()
    for p in pairs or []:
        if not isinstance(p, dict) or not p.get("sql"):
            continue
        name = str(p.get("question", "verified query"))[:160]
        if name in seen:
            continue
        seen.add(name)
        try:
            async with db.begin_nested():
                db.add(
                    QueryLibraryItem(
                        organization_id=org_id,
                        data_source_id=ds_id,
                        name=name,
                        sql_text=str(p["sql"])[:4000],
                        status="pending",
                    )
                )
            n += 1
        except IntegrityError:
            # already exists / dup — savepoint rolled back, session still good
            continue
        except Exception:
            logger.exception("persist_qa row failed")
    if n:
        try:
            await db.commit()
        except Exception:
            logger.exception("persist_qa commit failed")
            return 0
    return n
