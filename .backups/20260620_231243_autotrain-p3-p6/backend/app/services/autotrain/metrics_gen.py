"""Heuristic (+ optional LLM) metric proposal from a column profile.

Pure-Python, stdlib only. Every public function NEVER raises: on any error it
returns a safe default and logs via logging.getLogger(__name__).
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

_IDENT_RE = re.compile(r"^[A-Za-z0-9_]+$")


def _safe(name) -> bool:
    try:
        return bool(name) and bool(_IDENT_RE.match(str(name)))
    except Exception:
        return False


def _parse_llm_array(text):
    """Robustly pull the first JSON array out of an LLM response. -> list."""
    try:
        s = str(text or "")
        if "```" in s:
            # strip code fences (``` or ```json)
            s = re.sub(r"```[a-zA-Z0-9_]*", "", s).replace("```", "")
        start = s.find("[")
        end = s.rfind("]")
        if start == -1 or end == -1 or end <= start:
            return []
        chunk = s[start : end + 1]
        try:
            data = json.loads(chunk)
        except Exception:
            # trailing-comma repair
            repaired = re.sub(r",\s*([\]}])", r"\1", chunk)
            data = json.loads(repaired)
        return data if isinstance(data, list) else []
    except Exception:
        logger.exception("metrics_gen: failed to parse LLM array")
        return []


def propose_metrics(
    table: str,
    *,
    profile: dict,
    schema: str = "staging",
    llm_inference=None,
    max_metrics: int = 5,
) -> list[dict]:
    try:
        if not _safe(table) or not _safe(schema):
            return []
        cols = (profile or {}).get("columns") or []
        measures, dims = [], []
        for c in cols:
            try:
                name = c.get("name")
                if not _safe(name):
                    continue
                role = c.get("role")
                if role == "measure":
                    measures.append(name)
                elif role == "dimension":
                    dims.append(name)
            except Exception:
                continue

        ref = f'{schema}."{table}"'
        out: list[dict] = []

        def add(m):
            if any(x["name"] == m["name"] for x in out):
                return
            out.append(m)

        for col in measures:
            add({
                "name": f"total_{col}",
                "definition": f"Total (sum) of {col} across all rows in {table}.",
                "sql_calc": f'SELECT SUM("{col}") AS total_{col} FROM {ref}',
                "table_ref": table,
            })

        add({
            "name": "row_count",
            "definition": f"Number of rows in {table}.",
            "sql_calc": f"SELECT COUNT(*) AS row_count FROM {ref}",
            "table_ref": table,
        })

        if dims and measures:
            d, m = dims[0], measures[0]
            add({
                "name": f"{m}_by_{d}",
                "definition": f"Sum of {m} grouped by {d}, ranked descending.",
                "sql_calc": (
                    f'SELECT "{d}", SUM("{m}") AS total_{m} FROM {ref} '
                    f"GROUP BY 1 ORDER BY 2 DESC"
                ),
                "table_ref": table,
            })

        out = out[: max(0, int(max_metrics or 0))]

        if llm_inference is not None and len(out) < max_metrics:
            try:
                prompt = (
                    "Given table '%s' columns %s, propose up to 2 additional "
                    "read-only SQL analytics metrics as a JSON array of objects "
                    'with keys name,definition,sql_calc. Only SELECT statements.'
                    % (table, [c.get("name") for c in cols])
                )
                extra = _parse_llm_array(llm_inference(prompt))
                for item in extra[:2]:
                    try:
                        nm = item.get("name")
                        sql = str(item.get("sql_calc", "")).strip()
                        if not _safe(nm) or not sql.lstrip().upper().startswith("SELECT"):
                            continue
                        add({
                            "name": nm,
                            "definition": str(item.get("definition", "")),
                            "sql_calc": sql,
                            "table_ref": table,
                        })
                    except Exception:
                        continue
                out = out[: max(0, int(max_metrics or 0))]
            except Exception:
                logger.exception("metrics_gen: llm augmentation failed")

        return out
    except Exception:
        logger.exception("metrics_gen.propose_metrics failed for %s", table)
        return []
