"""Autotrain for LIVE connector tables (P7).

Unlike the upload path (orchestrator.py), connector tables are NOT in the
`staging` schema — they live in the remote DB and are read via the data
source's CLIENT. They are already queryable by the agent (no register step).
P7 only PROPOSES pending knowledge (semantic + metrics + verified Q&A) for
them, mirroring what uploaded files get.

`autotrain_connector` NEVER raises -> returns a summary dict. Everything is
written as status='pending' through the same approval-safe brain helpers used
by the upload path. Gated on flags.AUTOTRAIN (caller checks too).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_IDENT = re.compile(r"^[A-Za-z0-9_ ./\-]+$")  # TEMP(bench): allow PBI names (slash/space) — revert after
_STAGING_QUALIFIER = re.compile(r"(?i)\bstaging\.")

# numeric-ish dtype hints (covers sqlite + warehouse dtypes)
_NUMERIC_HINTS = (
    "int", "float", "double", "decimal", "numeric", "real", "money", "number",
)
_ID_NAME_HINTS = ("id", "_id", "key", "pk", "code", "guid", "uuid")


def _safe_ident(name) -> bool:
    try:
        return bool(name) and bool(_IDENT.match(str(name)))
    except Exception:
        return False


def _guess_role(name: str, dtype: str) -> str:
    """numeric dtype -> 'measure'; id-like name -> 'id'; else 'dimension'."""
    n = (name or "").lower()
    d = (dtype or "").lower()
    if n == "id" or any(n.endswith(h) for h in _ID_NAME_HINTS):
        return "id"
    if any(h in d for h in _NUMERIC_HINTS):
        return "measure"
    return "dimension"


def _build_llm_inference(model) -> Optional[Callable[[str], str]]:
    if model is None:
        return None
    try:
        from app.ai.llm.llm import LLM
        from app.dependencies import async_session_maker

        return LLM(model, usage_session_maker=async_session_maker).inference
    except Exception:
        logger.exception("autotrain_connector: could not build llm_inference")
        return None


def _pick_connection(data_source):
    """First connection that is NOT the 'City Agent Staging' one. Returns None."""
    try:
        conns = list(getattr(data_source, "connections", None) or [])
    except Exception:
        return None
    for c in conns:
        if (getattr(c, "name", "") or "") == "City Agent Staging":
            continue
        return c
    return None


def _parse_json_obj(txt: str) -> dict:
    """Robust: strip ``` fences, take first {..}, repair trailing commas."""
    if not txt:
        return {}
    s = str(txt).strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z0-9_]*\n?", "", s).rstrip("`").strip()
    a, b = s.find("{"), s.rfind("}")
    if a >= 0 and b > a:
        s = s[a : b + 1]
    s = re.sub(r",\s*([}\]])", r"\1", s)  # trailing commas
    try:
        out = json.loads(s)
        return out if isinstance(out, dict) else {}
    except Exception:
        return {}


def _run_one(client, sql: str) -> tuple:
    """Execute a read-only SELECT via the client. Returns (ok, err)."""
    try:
        # SqliteClient.execute_query(sql) -> pandas.DataFrame (sync).
        client.execute_query(sql)
        return True, ""
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:300]


def _build_metrics(table: str, profile: dict) -> list:
    """Inline heuristic metrics using `FROM "<table>"` (no schema qualifier)."""
    ref = f'"{table}"'
    cols = (profile or {}).get("columns") or []
    measures = [c.get("name") for c in cols if c.get("role") == "measure" and _safe_ident(c.get("name"))]
    out: list = [
        {
            "name": "row_count",
            "definition": f"Number of rows in {table}.",
            "sql_calc": f"SELECT COUNT(*) AS row_count FROM {ref}",
            "table_ref": table,
        }
    ]
    for col in measures[:3]:
        out.append({
            "name": f"total_{col}",
            "definition": f"Total (sum) of {col} across all rows in {table}.",
            "sql_calc": f'SELECT SUM("{col}") AS total_{col} FROM {ref}',
            "table_ref": table,
        })
    return out


async def _persist_qa(db, *, org_id: str, ds_id: str, pairs: list) -> int:
    """Best-effort: write verified Q&A as PENDING query-library rows.

    Mirrors orchestrator._persist_qa. De-dups by name within this call so the
    unique (org, ds, name) constraint doesn't abort the batch.
    """
    n = 0
    try:
        from app.models.query_library import QueryLibraryItem  # type: ignore
    except Exception:
        logger.info("connector persist_qa: QueryLibraryItem not importable, skipping")
        return 0
    seen: set = set()
    for p in pairs or []:
        if not isinstance(p, dict) or not p.get("sql"):
            continue
        name = str(p.get("question", "verified query"))[:160]
        if name in seen:
            continue
        seen.add(name)
        try:
            item = QueryLibraryItem(
                organization_id=org_id,
                data_source_id=ds_id,
                name=name,
                sql_text=str(p["sql"])[:4000],
                status="pending",
            )
            db.add(item)
            n += 1
        except Exception:
            logger.exception("connector persist_qa row failed")
    if n:
        try:
            await db.commit()
        except Exception:
            logger.exception("connector persist_qa commit failed")
            return 0
    return n


_STAGING_CONN_NAME = "City Agent Staging"


def _columns_for_dst_row(row) -> list:
    """Resolve [{name, dtype}] for a DataSourceTable row.

    Prefer the linked ConnectionTable schema (new architecture); fall back to
    the legacy `columns` JSON on the DataSourceTable itself. Mirrors
    `app/routes/autotrain_connector.py::_columns_for_table`.
    """
    cols = []
    try:
        ct = getattr(row, "connection_table", None)
        if ct is not None and ct.columns:
            cols = ct.columns
        elif row.columns:
            cols = row.columns
    except Exception:
        cols = getattr(row, "columns", None) or []
    out = []
    for c in cols or []:
        try:
            if isinstance(c, dict) and c.get("name"):
                out.append({"name": c["name"], "dtype": c.get("dtype") or "unknown"})
        except Exception:
            continue
    return out


def _dst_row_is_staging(row) -> bool:
    """True if this table's ConnectionTable belongs to the 'City Agent Staging'
    connection (skip those — upload-staging lane, not a live DB). Mirrors the
    route's `_connection_is_staging`."""
    try:
        ct = getattr(row, "connection_table", None)
        if ct is None:
            return False
        conn = getattr(ct, "connection", None)
        return bool(conn) and (getattr(conn, "name", "") or "") == _STAGING_CONN_NAME
    except Exception:
        return False


async def autotrain_data_source(
    db,
    *,
    organization,
    data_source,
    model=None,
    max_tables: int = 25,
    only_new: bool = True,
) -> dict:
    """Batch auto-train ALL live connector tables on a data source -> PENDING
    knowledge. Never raises.

    Resolves the data source's active (non-deleted) DataSourceTable rows, skips
    any whose ConnectionTable belongs to the 'City Agent Staging' connection,
    and (when only_new) skips tables that already have a SemanticTable row (i.e.
    were already auto-trained). Caps at max_tables, then calls
    `autotrain_connector` per table.

    Returns {"trained": int, "skipped": int, "tables": [names], "errors": [...]}.
    """
    out = {"trained": 0, "skipped": 0, "tables": [], "errors": []}

    try:
        from app.settings.hybrid_flags import flags
    except Exception:
        out["errors"].append("flags import failed")
        return out
    if not flags.AUTOTRAIN:
        out["errors"].append("AUTOTRAIN flag OFF")
        return out

    org_id = getattr(organization, "id", None)
    ds_id = getattr(data_source, "id", None)
    if not org_id or not ds_id:
        out["errors"].append("missing org/ds")
        return out

    # --- default model (best-effort) ----------------------------------------
    if model is None:
        try:
            from sqlalchemy import select as _select
            from app.models.llm_model import LLMModel

            model = (
                await db.execute(
                    _select(LLMModel).where(LLMModel.is_default == True)  # noqa: E712
                )
            ).scalars().first()
        except Exception:
            logger.info("autotrain_data_source: default model lookup failed", exc_info=True)
            model = None

    # --- resolve active DataSourceTable rows --------------------------------
    # selectinload connection_table -> connection so we can read the connection
    # name (staging skip) without an async lazy-load (MissingGreenlet).
    try:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.models.connection_table import ConnectionTable
        from app.models.datasource_table import DataSourceTable

        rows = (
            await db.execute(
                select(DataSourceTable)
                .where(
                    DataSourceTable.datasource_id == ds_id,
                    DataSourceTable.is_active == True,  # noqa: E712
                    DataSourceTable.deleted_at.is_(None),
                )
                .options(
                    selectinload(DataSourceTable.connection_table).selectinload(
                        ConnectionTable.connection
                    )
                )
            )
        ).scalars().all()
    except Exception:
        logger.exception("autotrain_data_source: failed to load tables")
        out["errors"].append("load tables failed")
        return out

    # --- only_new dedup: skip tables already auto-trained -------------------
    async def _already_trained(table_name: str) -> bool:
        try:
            from sqlalchemy import select
            from app.models.semantic_table import SemanticTable

            hit = (
                await db.execute(
                    select(SemanticTable.id)
                    .where(
                        SemanticTable.organization_id == org_id,
                        SemanticTable.data_source_id == ds_id,
                        SemanticTable.table_name == table_name,
                    )
                    .limit(1)
                )
            ).first()
            return hit is not None
        except Exception:
            logger.debug("autotrain_data_source: dedup check failed", exc_info=True)
            return False

    cap = max(1, int(max_tables or 1))
    for r in rows:
        if len(out["tables"]) >= cap:
            break
        name = getattr(r, "name", None)
        if not name or not _safe_ident(name):
            continue
        if _dst_row_is_staging(r):
            continue
        if only_new and await _already_trained(name):
            out["skipped"] += 1
            continue
        cols = _columns_for_dst_row(r)
        try:
            await autotrain_connector(
                db,
                organization=organization,
                data_source=data_source,
                table=name,
                columns=cols,
                model=model,
            )
            out["trained"] += 1
            out["tables"].append(name)
        except Exception as e:  # autotrain_connector never raises, but belt+suspenders
            logger.exception("autotrain_data_source: table %s failed", name)
            out["errors"].append(f"{name}: {str(e)[:200]}")

    return out


async def autotrain_connector(
    db,
    *,
    organization,
    data_source,
    table: str,
    columns: list,
    model=None,
    llm_inference: Optional[Callable[[str], str]] = None,
) -> dict:
    """Auto-train ONE live connector table -> PENDING knowledge. Never raises.

    columns: [{name, dtype}] from DataSourceTable / ConnectionTable.
    Returns {table, semantics:[], metrics:[], qa:int, errors:[]}.
    """
    summary = {"table": table, "semantics": [], "metrics": [], "qa": 0, "errors": []}

    try:
        from app.settings.hybrid_flags import flags
    except Exception:
        summary["errors"].append("flags import failed")
        return summary
    if not flags.AUTOTRAIN:
        summary["errors"].append("AUTOTRAIN flag OFF")
        return summary

    org_id = getattr(organization, "id", None)
    ds_id = getattr(data_source, "id", None)
    if not org_id or not ds_id or not _safe_ident(table):
        summary["errors"].append("missing/invalid org/ds/table")
        return summary

    # --- client + run_sql + sample ------------------------------------------
    conn = _pick_connection(data_source)
    if conn is None:
        summary["errors"].append("no usable connection")
        return summary
    try:
        client = conn.get_client()
    except Exception:
        logger.exception("autotrain_connector: get_client failed")
        summary["errors"].append("get_client failed")
        return summary

    def run_sql(sql: str):
        # Verified-Q&A SQL is generated against a `staging.<table>` prompt
        # (shared qa_gen prompt); connector tables live under no schema, so
        # strip a leading `staging.` qualifier before executing on the client.
        try:
            cleaned = _STAGING_QUALIFIER.sub("", str(sql or ""))
        except Exception:
            cleaned = sql
        return _run_one(client, cleaned)

    def fetch_sample() -> list:
        try:
            df = client.execute_query(f'SELECT * FROM "{table}" LIMIT 8')
        except Exception:
            return []
        try:
            rows = df.head(8).to_dict(orient="records")
            return [
                {k: (str(v)[:60] if v is not None else None) for k, v in r.items()}
                for r in rows
            ]
        except Exception:
            return []

    # --- profile -------------------------------------------------------------
    prof_cols = []
    for c in columns or []:
        try:
            name = c.get("name") if isinstance(c, dict) else None
            if not _safe_ident(name):
                continue
            dtype = (c.get("dtype") if isinstance(c, dict) else None) or "unknown"
            prof_cols.append({
                "name": name,
                "dtype": dtype,
                "role": _guess_role(name, dtype),
                "distinct": None,
                "null_pct": None,
                "top_values": [],
            })
        except Exception:
            continue
    profile = {"row_count": None, "columns": prof_cols}

    if llm_inference is None and model is not None:
        llm_inference = _build_llm_inference(model)

    sample = fetch_sample()

    # --- CODEX: description (build the prompt ourselves) --------------------
    try:
        from app.services.autotrain import writeback

        desc = ""
        if llm_inference is not None and prof_cols:
            col_lines = "\n".join(
                f"- {c['name']} ({c['dtype']})" for c in prof_cols[:40]
            )
            prompt = (
                "You are a data analyst. Given a database table's schema and "
                "sample rows, describe it for an analytics agent. Reply ONLY "
                "with JSON:\n"
                '{"description": str (1-2 sentences, what the table is),\n'
                ' "grain": str (what one row represents),\n'
                ' "use_cases": [str, ...] (<=4 analytical questions it answers)}\n\n'
                f"TABLE: {table}\nCOLUMNS:\n{col_lines}\n\n"
                f"SAMPLE ROWS (up to 8):\n{json.dumps(sample, default=str)[:2000]}\n"
            )
            try:
                out = _parse_json_obj(llm_inference(prompt))
            except Exception:
                logger.exception("autotrain_connector: codex llm failed")
                out = {}
            desc = (out.get("description") or "").strip()
            grain = (out.get("grain") or "").strip()
            if grain:
                desc = f"{desc} Grain: {grain}".strip()
        if not desc and prof_cols:
            # heuristic fallback (no LLM / parse miss) — still useful, pending.
            desc = f"Table {table} with columns: " + ", ".join(
                c["name"] for c in prof_cols[:20]
            )
        if desc:
            sid = await writeback.write_semantic(
                db, org_id=org_id, ds_id=ds_id, table_name=table, description=desc
            )
            if sid:
                summary["semantics"].append(sid)
    except Exception:
        logger.exception("autotrain_connector: codex step failed")
        summary["errors"].append("codex")

    # --- METRICS: inline heuristic w/ FROM "<table>" -----------------------
    try:
        from app.services.autotrain import writeback

        for m in _build_metrics(table, profile):
            if not m.get("name") or not m.get("sql_calc"):
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
        logger.exception("autotrain_connector: metrics step failed")
        summary["errors"].append("metrics")

    # --- QA: generate -> execute on the connector -> keep verified ---------
    if flags.AUTOTRAIN_QA and llm_inference is not None:
        try:
            from app.services.autotrain import qa_gen

            pairs = qa_gen.generate_verified_qa(
                table,
                profile=profile,
                llm_inference=llm_inference,
                run_sql=run_sql,
                max_pairs=6,
                schema="",  # connector table is in the remote DB, no staging schema
            )
            # persist the cleaned SQL (the form that actually ran on the client)
            for p in pairs:
                try:
                    p["sql"] = _STAGING_QUALIFIER.sub("", str(p.get("sql", "")))
                except Exception:
                    pass
            n = await _persist_qa(db, org_id=org_id, ds_id=ds_id, pairs=pairs)
            summary["qa"] = n
        except Exception:
            logger.exception("autotrain_connector: qa step failed")
            summary["errors"].append("qa")

    return summary
