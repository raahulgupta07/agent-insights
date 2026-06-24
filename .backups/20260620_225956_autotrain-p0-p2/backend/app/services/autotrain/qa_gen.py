"""Generate LLM question/SQL pairs and keep only the ones that execute cleanly.

Never raises: returns [] on any error.
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

_FORBIDDEN_RE = re.compile(r"(?i)\b(insert|update|delete|drop|alter|truncate|create|grant)\b")
_FENCE_RE = re.compile(r"```[a-zA-Z]*\s*|\s*```")


def _strip_fences(s: str) -> str:
    if not isinstance(s, str):
        return ""
    return _FENCE_RE.sub("", s).strip()


def _extract_json(raw: str):
    """Best-effort extraction of the first JSON array/object from raw text."""
    if not isinstance(raw, str):
        return None
    text = _strip_fences(raw)
    # locate first array or object
    starts = [i for i in (text.find("["), text.find("{")) if i != -1]
    if not starts:
        return None
    start = min(starts)
    open_ch = text[start]
    close_ch = "]" if open_ch == "[" else "}"
    depth = 0
    end = -1
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    candidate = text[start:end] if end != -1 else text[start:]
    # trailing-comma repair
    repaired = re.sub(r",(\s*[\]}])", r"\1", candidate)
    for attempt in (candidate, repaired):
        try:
            return json.loads(attempt)
        except Exception:
            continue
    return None


def _normalize_pairs(parsed) -> list[dict]:
    if parsed is None:
        return []
    if isinstance(parsed, dict):
        # could be {"pairs": [...]} or a single pair
        for key in ("pairs", "qa", "items", "data"):
            if isinstance(parsed.get(key), list):
                parsed = parsed[key]
                break
        else:
            parsed = [parsed]
    if not isinstance(parsed, list):
        return []
    out = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        q = item.get("question") or item.get("q")
        s = item.get("sql") or item.get("query")
        if isinstance(q, str) and isinstance(s, str) and q.strip() and s.strip():
            out.append({"question": q.strip(), "sql": s})
    return out


def _build_prompt(table: str, profile: dict, max_pairs: int) -> str:
    cols = (profile or {}).get("columns", []) or []
    dims = [c["name"] for c in cols if c.get("role") == "dimension"]
    measures = [c["name"] for c in cols if c.get("role") == "measure"]
    sample_lines = []
    for c in cols[:30]:
        line = f"- {c.get('name')} ({c.get('dtype')}, role={c.get('role')}, distinct={c.get('distinct')})"
        tv = c.get("top_values") or []
        if tv:
            vals = ", ".join(str(t.get("value")) for t in tv[:5])
            line += f" e.g. {vals}"
        sample_lines.append(line)
    return (
        f"You are a data analyst. The table is staging.{table}.\n"
        f"Row count: {(profile or {}).get('row_count')}\n"
        f"Dimensions: {', '.join(dims) or 'none'}\n"
        f"Measures: {', '.join(measures) or 'none'}\n"
        "Columns:\n" + "\n".join(sample_lines) + "\n\n"
        f"Generate up to {max_pairs} useful analytical question/SQL pairs. "
        f"Each SQL must be a single read-only SELECT over staging.{table} "
        "(no INSERT/UPDATE/DELETE/DROP/ALTER/TRUNCATE/CREATE/GRANT).\n"
        'Respond ONLY with a JSON array of objects: '
        '[{"question": "...", "sql": "SELECT ..."}].'
    )


def generate_verified_qa(table: str, *, profile: dict, llm_inference, run_sql, max_pairs: int = 8) -> list[dict]:
    try:
        prompt = _build_prompt(table, profile or {}, max_pairs)
    except Exception as e:
        logger.warning("generate_verified_qa: prompt build failed: %s", e)
        return []

    try:
        raw = llm_inference(prompt)
    except Exception as e:
        logger.warning("generate_verified_qa: llm_inference failed: %s", e)
        return []

    pairs = _normalize_pairs(_extract_json(raw))[:max_pairs]
    verified: list[dict] = []
    for pair in pairs:
        try:
            sql = _strip_fences(pair["sql"])
            if not sql or _FORBIDDEN_RE.search(sql):
                continue
            ok, err = run_sql(sql)
            if ok:
                verified.append({"question": pair["question"], "sql": sql, "verified": True})
            else:
                logger.debug("qa pair rejected (sql error): %s", err)
        except Exception as e:
            logger.debug("qa pair verification error: %s", e)
            continue
    return verified
