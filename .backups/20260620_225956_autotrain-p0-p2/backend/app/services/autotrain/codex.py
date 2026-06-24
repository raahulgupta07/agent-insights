"""Autotrain codex: read a staging table's schema + sample, ask the LLM for
{description, use_cases, grain, metrics}. Pure compute + an injected llm.

Reads via the analytics write engine (read-capable, pgbouncer-safe; the
write-guard only blocks WRITES). Never raises -> returns a safe empty dict.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_IDENT = re.compile(r"^[A-Za-z0-9_]+$")


def _safe(ident: str) -> bool:
    return bool(ident) and bool(_IDENT.match(ident))


def _read_schema_and_sample(table: str, schema: str, engine) -> tuple[list, list]:
    """Return (columns=[{name,dtype}], sample_rows=[dict])."""
    from sqlalchemy import text

    cols, sample = [], []
    with engine.connect() as c:
        rows = c.execute(
            text(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema=:s AND table_name=:t ORDER BY ordinal_position"
            ),
            {"s": schema, "t": table},
        ).fetchall()
        cols = [{"name": r[0], "dtype": r[1]} for r in rows]
        if cols:
            res = c.execute(text(f'SELECT * FROM {schema}."{table}" LIMIT 8'))
            keys = list(res.keys())
            for r in res.fetchall():
                sample.append({k: (str(v)[:60] if v is not None else None) for k, v in zip(keys, r)})
    return cols, sample


def _parse_json(txt: str) -> dict:
    if not txt:
        return {}
    s = txt.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s).rstrip("`").strip()
    a, b = s.find("{"), s.rfind("}")
    if a >= 0 and b > a:
        s = s[a : b + 1]
    s = re.sub(r",\s*([}\]])", r"\1", s)  # trailing commas
    try:
        return json.loads(s)
    except Exception:
        return {}


def codex_enrich(
    table: str,
    *,
    schema: str = "staging",
    engine=None,
    llm_inference: Optional[Callable[[str], str]] = None,
) -> dict:
    """Return {table, description, use_cases:[...], grain, columns:[{name,desc}],
    metrics:[{name,definition,sql_calc,table_ref}]}. Safe empty dict on failure.
    """
    if not _safe(table) or not _safe(schema):
        return {}
    try:
        if engine is None:
            from app.ai.code_execution.analytics_engine import get_analytics_write_engine

            engine = get_analytics_write_engine()
        cols, sample = _read_schema_and_sample(table, schema, engine)
        if not cols:
            return {}
        if llm_inference is None:
            # no LLM -> minimal heuristic description (still useful, approval-safe)
            return {
                "table": table,
                "description": f"Table {table} with columns: "
                + ", ".join(c["name"] for c in cols[:20]),
                "use_cases": [],
                "grain": "",
                "columns": [{"name": c["name"], "desc": ""} for c in cols],
                "metrics": [],
            }

        col_lines = "\n".join(f"- {c['name']} ({c['dtype']})" for c in cols)
        prompt = (
            "You are a data analyst. Given a database table's schema and sample rows, "
            "describe it for an analytics agent. Reply ONLY with JSON:\n"
            '{"description": str (1-2 sentences, what the table is),\n'
            ' "grain": str (what one row represents),\n'
            ' "use_cases": [str, ...] (<=4 analytical questions it answers),\n'
            ' "columns": [{"name": str, "desc": str}],\n'
            ' "metrics": [{"name": str, "definition": str, "sql_calc": str (a read-only SELECT over '
            f'{schema}.\\"{table}\\"), "table_ref": "{table}"}}]  (<=3 obvious metrics)}}\n\n'
            f"TABLE: {schema}.{table}\nCOLUMNS:\n{col_lines}\n\n"
            f"SAMPLE ROWS (up to 8):\n{json.dumps(sample, default=str)[:2000]}\n"
        )
        out = _parse_json(llm_inference(prompt))
        if not isinstance(out, dict):
            return {}
        out["table"] = table
        out.setdefault("description", f"Table {table}")
        out.setdefault("use_cases", [])
        out.setdefault("grain", "")
        out.setdefault("columns", [])
        out.setdefault("metrics", [])
        return out
    except Exception:
        logger.exception("codex_enrich failed for %s.%s", schema, table)
        return {}
