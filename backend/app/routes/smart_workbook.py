"""Smart Workbook Build (HYBRID_SMART_WORKBOOK) — additive sidecar.

The Outputs panel "Excel" tab gets a SMART builder. Flag-gated default OFF.
Flag OFF (or route absent) = today's raw workbook dump unchanged.

"Smart" = user types intent ("pivot revenue by region × month, drop raw ids"),
an LLM converts that to a TRANSFORM SPEC (pick columns / pivot / aggregate /
rename / filter / sort), and we apply it in pure-Python over the existing grids
(NO SQL re-run, NO eval/exec, strict whitelist ops only).

  GET  /api/reports/{id}/workbook/context
       Gate on SMART_WORKBOOK (off → {disabled:true}). Reuse the grid-collection
       logic from report_slides (same Query→Step→_coerce_grid walk). Return
       {ok, sheets:[{name,rows,cols,columns}], prefill} where prefill comes from
       the last chat turn.

  POST /api/reports/{id}/workbook/smart-build   body {prompt:str, sheets?:[str]}
       Gate. Collect grids → filter to requested sheets → build compact schema
       summary → ask org default LLM for a strict JSON transform spec → validate
       + apply via _apply_transform → return {ok, sheets:[transformed grids], spec}.
       Never 500 — fail-soft to {ok:False, error}. No grids → {ok:False, needs_data:True}.

NOTE: no `from __future__ import annotations` (body+permission route landmine —
stringized annotations make FastAPI mis-read the pydantic body as a query param).
"""
import json
import logging
import re
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_async_db, get_current_organization
from app.models.user import User
from app.models.organization import Organization
from app.models.report import Report
from app.models.completion import Completion
from app.core.auth import current_user
from app.settings.hybrid_flags import flags

logger = logging.getLogger(__name__)

router = APIRouter(tags=["smart-workbook"])

# --------------------------------------------------------------------- #
#  Whitelist for transform ops.                                          #
# --------------------------------------------------------------------- #
_ALLOWED_OPS = {"select", "rename", "filter", "aggregate", "pivot", "sort"}
_WORKBOOK_ROW_CAP = 5000


def _disabled():
    return {"disabled": True, "feature": "smart_workbook"}


# --------------------------------------------------------------------- #
#  Grid helpers — re-use report_slides._coerce_grid + query walk        #
# --------------------------------------------------------------------- #

def _coerce_grid_local(data) -> Optional[dict]:
    """Mirror of report_slides._coerce_grid — kept local to avoid circular import."""
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:  # noqa: BLE001
            return None
    rows = cols = None
    if isinstance(data, dict):
        cols = data.get("columns") or data.get("schema")
        rows = data.get("rows") or data.get("data")
        if isinstance(cols, list) and cols and isinstance(cols[0], dict):
            cols = [c.get("field") or c.get("name") or c.get("headerName") or c.get("generated_column_name") for c in cols]
    elif isinstance(data, list):
        rows = data
        if rows and isinstance(rows[0], dict):
            cols = list(rows[0].keys())
    if not rows:
        return None
    if not cols and isinstance(rows[0], dict):
        cols = list(rows[0].keys())
    cols = [str(c) for c in (cols or [])]
    out_rows = []
    for r in rows[:_WORKBOOK_ROW_CAP]:
        if isinstance(r, dict):
            out_rows.append([r.get(c) for c in cols])
        elif isinstance(r, (list, tuple)):
            out_rows.append(list(r))
        else:
            out_rows.append([r])
    return {"columns": cols, "rows": out_rows}


async def _collect_grids(db: AsyncSession, report: Report) -> List[dict]:
    """Return [{name, columns, rows}] for the report's latest-success steps."""
    from app.models.query import Query
    from app.models.step import Step
    try:
        from app.services.parquet_store import hydrate as _hydrate
    except Exception:  # noqa: BLE001
        _hydrate = lambda d: d  # noqa: E731

    sheets: List[dict] = []
    try:
        queries = (
            await db.execute(
                select(Query).where(Query.report_id == report.id).order_by(Query.created_at.asc())
            )
        ).scalars().all()
        for q in queries:
            if len(sheets) >= 50:
                break
            step = None
            if getattr(q, "default_step_id", None):
                step = await db.get(Step, q.default_step_id)
            if step is None or (step.status or "") != "success" or not step.data:
                step = (
                    await db.execute(
                        select(Step).where(Step.query_id == q.id, Step.status == "success")
                        .order_by(desc(Step.created_at)).limit(1)
                    )
                ).scalar_one_or_none()
            if step is None or not step.data:
                continue
            try:
                sd = _hydrate(step.data)
            except Exception:  # noqa: BLE001
                sd = step.data
            grid = _coerce_grid_local(sd)
            if not grid:
                continue
            name = (q.title or step.title or f"Sheet {len(sheets) + 1}")[:28]
            sheets.append({"name": name, "columns": grid["columns"], "rows": grid["rows"]})
    except Exception:  # noqa: BLE001
        logger.exception("smart-workbook: grid collection failed for report %s", report.id)
    return sheets


# --------------------------------------------------------------------- #
#  Last chat turn (prefill)                                              #
# --------------------------------------------------------------------- #

def _text_of(blob) -> str:
    if blob is None:
        return ""
    if isinstance(blob, str):
        return blob.strip()
    if isinstance(blob, dict):
        for k in ("content", "text", "message", "prompt"):
            v = blob.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return ""


async def _last_turn(db: AsyncSession, report_id: str) -> dict:
    out = {"question": "", "answer": ""}
    try:
        rows = (await db.execute(
            select(Completion)
            .where(Completion.report_id == report_id, Completion.deleted_at.is_(None))
            .order_by(desc(Completion.turn_index), desc(Completion.created_at))
            .limit(12)
        )).scalars().all()
        for c in rows:
            role = (c.role or "").lower()
            if role == "user" and not out["question"]:
                out["question"] = _text_of(c.prompt)
            elif role == "system" and not out["answer"]:
                out["answer"] = _text_of(c.completion)
            if out["question"] and out["answer"]:
                break
    except Exception:  # noqa: BLE001
        logger.exception("smart-workbook: last-turn read failed")
    return out


def _prefill(turn: dict) -> str:
    q = (turn.get("question") or "").strip()
    if q:
        return q if len(q) <= 240 else q[:240].rstrip() + "…"
    return ""


async def _load_report(db: AsyncSession, report_id: str, organization) -> Optional[Report]:
    try:
        r = (await db.execute(
            select(Report).where(
                Report.id == report_id,
                Report.organization_id == str(organization.id),
            )
        )).scalars().first()
        return r
    except Exception:  # noqa: BLE001
        logger.exception("smart-workbook: report load failed")
        return None


# --------------------------------------------------------------------- #
#  Transform spec application (pure-Python, pandas, strict whitelist)   #
# --------------------------------------------------------------------- #

def _apply_transform(grid: dict, spec: dict) -> dict:
    """Apply a transform spec to a {columns, rows} grid.

    Supported ops (validated against _ALLOWED_OPS):
      select      — keep named columns             {op:"select", columns:[str]}
      rename      — rename columns                 {op:"rename", mapping:{old:new}}
      filter      — simple col op value            {op:"filter", column:str, operator:str, value}
                    operators: "==", "!=", ">", "<", ">=", "<=", "contains", "not_contains"
      aggregate   — group_by + agg func            {op:"aggregate", group_by:[str], agg:{col:func}}
                    funcs: sum|mean|count|min|max
      pivot       — pandas pivot_table             {op:"pivot", index:[str], columns:str, values:str, aggfunc:str}
      sort        — sort rows                      {op:"sort", by:[str], ascending:bool}

    Returns a (possibly modified) {columns, rows} dict.
    Unknown ops are silently skipped. Never raises — any error returns the original grid.
    Output rows are capped at _WORKBOOK_ROW_CAP.
    """
    try:
        import pandas as pd  # pandas is in the project's stack

        cols = grid.get("columns", [])
        rows = grid.get("rows", [])

        # Build DataFrame
        df = pd.DataFrame(rows, columns=cols) if cols else pd.DataFrame(rows)

        ops = spec.get("ops") or []
        if not isinstance(ops, list):
            ops = []

        for op_item in ops:
            if not isinstance(op_item, dict):
                continue
            op = op_item.get("op", "")
            if op not in _ALLOWED_OPS:
                continue  # strict whitelist — ignore unknown ops

            try:
                if op == "select":
                    keep = [c for c in (op_item.get("columns") or []) if c in df.columns]
                    if keep:
                        df = df[keep]

                elif op == "rename":
                    mapping = op_item.get("mapping") or {}
                    # Only rename columns that actually exist
                    safe_map = {k: v for k, v in mapping.items() if k in df.columns and isinstance(v, str)}
                    if safe_map:
                        df = df.rename(columns=safe_map)

                elif op == "filter":
                    col = op_item.get("column")
                    operator = op_item.get("operator", "==")
                    value = op_item.get("value")
                    if col and col in df.columns and operator in ("==", "!=", ">", "<", ">=", "<=", "contains", "not_contains"):
                        if operator == "==":
                            df = df[df[col] == value]
                        elif operator == "!=":
                            df = df[df[col] != value]
                        elif operator == ">":
                            df = df[df[col] > value]
                        elif operator == "<":
                            df = df[df[col] < value]
                        elif operator == ">=":
                            df = df[df[col] >= value]
                        elif operator == "<=":
                            df = df[df[col] <= value]
                        elif operator == "contains":
                            df = df[df[col].astype(str).str.contains(str(value), na=False)]
                        elif operator == "not_contains":
                            df = df[~df[col].astype(str).str.contains(str(value), na=False)]

                elif op == "aggregate":
                    group_by = [c for c in (op_item.get("group_by") or []) if c in df.columns]
                    agg_dict = op_item.get("agg") or {}
                    _VALID_FUNCS = {"sum", "mean", "count", "min", "max"}
                    safe_agg = {c: f for c, f in agg_dict.items() if c in df.columns and f in _VALID_FUNCS}
                    if group_by and safe_agg:
                        df = df.groupby(group_by, as_index=False).agg(safe_agg)

                elif op == "pivot":
                    index = op_item.get("index") or []
                    if isinstance(index, str):
                        index = [index]
                    index = [c for c in index if c in df.columns]
                    pivot_cols = op_item.get("columns")
                    values = op_item.get("values")
                    aggfunc = op_item.get("aggfunc", "sum")
                    _VALID_FUNCS = {"sum", "mean", "count", "min", "max"}
                    if aggfunc not in _VALID_FUNCS:
                        aggfunc = "sum"
                    if index and pivot_cols and pivot_cols in df.columns and values and values in df.columns:
                        df = pd.pivot_table(
                            df, index=index, columns=pivot_cols, values=values,
                            aggfunc=aggfunc, fill_value=0
                        ).reset_index()
                        df.columns = [str(c) for c in df.columns]

                elif op == "sort":
                    by = [c for c in (op_item.get("by") or []) if c in df.columns]
                    ascending = op_item.get("ascending", True)
                    if by:
                        df = df.sort_values(by=by, ascending=ascending)

            except Exception:  # noqa: BLE001 — one bad op → skip, keep going
                logger.debug("smart-workbook: transform op %r failed, skipping", op, exc_info=True)
                continue

        # Cap rows + serialize back to {columns, rows}
        df = df.head(_WORKBOOK_ROW_CAP)
        out_cols = list(df.columns)
        out_rows = [[None if (isinstance(v, float) and v != v) else v for v in row]   # replace NaN with None
                    for row in df.values.tolist()]
        return {"columns": out_cols, "rows": out_rows}

    except ImportError:
        # pandas not available — return original grid unchanged
        logger.warning("smart-workbook: pandas not available, returning untransformed grid")
        return grid
    except Exception:  # noqa: BLE001
        logger.exception("smart-workbook: _apply_transform failed, returning original grid")
        return grid


# --------------------------------------------------------------------- #
#  LLM prompt + response parsing                                         #
# --------------------------------------------------------------------- #

_TRANSFORM_SYSTEM = """\
You are a data transform planner. Given a schema summary and a user intent, output a JSON transform spec.

STRICT OUTPUT FORMAT — output ONLY valid JSON, no markdown fences, no prose:
{
  "ops": [
    {"op": "select", "columns": ["col1", "col2"]},
    {"op": "rename", "mapping": {"old_name": "new_name"}},
    {"op": "filter", "column": "col", "operator": "==", "value": "x"},
    {"op": "aggregate", "group_by": ["col1"], "agg": {"col2": "sum"}},
    {"op": "pivot", "index": ["col1"], "columns": "col2", "values": "col3", "aggfunc": "sum"},
    {"op": "sort", "by": ["col1"], "ascending": true}
  ]
}

RULES:
- ops list may contain 0..N items. Empty list = return data unchanged.
- Allowed op values ONLY: select, rename, filter, aggregate, pivot, sort.
- filter operators: ==, !=, >, <, >=, <=, contains, not_contains
- aggregate funcs: sum, mean, count, min, max
- pivot aggfunc: sum, mean, count, min, max
- Only reference columns that exist in the schema. Ignore columns not present.
- Do NOT output anything other than the JSON object.
"""

_TRANSFORM_USER_TPL = """\
SCHEMA:
{schema}

USER INTENT:
{intent}

Output the JSON transform spec now.
"""


def _build_schema_summary(sheets: List[dict]) -> str:
    parts = []
    for s in sheets:
        name = s.get("name", "Sheet")
        cols = s.get("columns", [])
        sample = s.get("rows", [])[:3]
        lines = [f"Sheet: {name}", f"Columns: {', '.join(cols)}"]
        if sample:
            lines.append("Sample rows (first 3):")
            for r in sample:
                lines.append("  " + str(r))
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def _parse_spec(raw: str) -> Optional[dict]:
    """Parse LLM output defensively — strip markdown fences, parse JSON."""
    if not raw:
        return None
    # Strip markdown code fences
    text = re.sub(r"```[a-z]*\n?", "", raw).strip()
    # Find the first '{' and last '}'
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        spec = json.loads(text[start:end + 1])
        if not isinstance(spec, dict):
            return None
        # Validate ops list
        ops = spec.get("ops") or []
        if not isinstance(ops, list):
            return None
        valid_ops = [op for op in ops if isinstance(op, dict) and op.get("op") in _ALLOWED_OPS]
        spec["ops"] = valid_ops
        return spec
    except (json.JSONDecodeError, ValueError):
        return None


# --------------------------------------------------------------------- #
#  Routes                                                                #
# --------------------------------------------------------------------- #

@router.get("/reports/{report_id}/workbook/context")
async def smart_workbook_context(
    report_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Return the workbook's sheet names + a prefill prompt from the last chat turn.
    Gated by HYBRID_SMART_WORKBOOK. Off → {disabled:true}. Never 500."""
    if not flags.SMART_WORKBOOK:
        return _disabled()

    report = await _load_report(db, report_id, organization)
    if report is None:
        return {"ok": False, "error": "report not found"}

    sheets = await _collect_grids(db, report)
    turn = await _last_turn(db, report_id)
    prefill = _prefill(turn)

    sheet_info = [
        {"name": s["name"], "rows": len(s["rows"]), "cols": len(s["columns"]), "columns": s["columns"]}
        for s in sheets
    ]

    return {
        "ok": True,
        "sheets": sheet_info,
        "prefill": prefill,
    }


class SmartBuildRequest(BaseModel):
    prompt: Optional[str] = ""
    sheets: Optional[List[str]] = None   # sheet names to include; None = all


@router.post("/reports/{report_id}/workbook/smart-build")
async def smart_workbook_build(
    report_id: str,
    body: SmartBuildRequest = ...,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Transform the workbook grids with an LLM-generated spec.
    Gated by HYBRID_SMART_WORKBOOK. Off → {disabled:true}. Never 500."""
    if not flags.SMART_WORKBOOK:
        return _disabled()

    report = await _load_report(db, report_id, organization)
    if report is None:
        return {"ok": False, "error": "report not found"}

    all_sheets = await _collect_grids(db, report)
    if not all_sheets:
        return {
            "ok": False,
            "needs_data": True,
            "message": "Ask the agent a data question first so it builds the result tables, then smart-build the workbook from them.",
        }

    # Filter to requested sheets if provided
    if body.sheets:
        req = set(body.sheets)
        target_sheets = [s for s in all_sheets if s["name"] in req] or all_sheets
    else:
        target_sheets = all_sheets

    intent = (body.prompt or "").strip()
    if not intent:
        return {"ok": False, "error": "prompt is required"}

    # Build schema summary for LLM
    schema_summary = _build_schema_summary(target_sheets)
    user_msg = _TRANSFORM_USER_TPL.format(schema=schema_summary, intent=intent)

    # Call org default LLM
    spec = None
    spec_note = None
    try:
        from app.models.llm_model import LLMModel
        from app.models.llm_provider import LLMProvider
        from app.ai.llm.clients.openai_client import OpenAIClient

        model_row = (await db.execute(
            select(LLMModel)
            .where(
                LLMModel.organization_id == str(organization.id),
                LLMModel.is_default.is_(True),
            )
            .limit(1)
        )).scalar_one_or_none()

        if model_row is None:
            model_row = (await db.execute(
                select(LLMModel)
                .where(LLMModel.organization_id == str(organization.id))
                .limit(1)
            )).scalar_one_or_none()

        if model_row:
            provider = await db.get(LLMProvider, model_row.llm_provider_id)
            if provider:
                client = OpenAIClient(provider, model_row)
                messages = [
                    {"role": "system", "content": _TRANSFORM_SYSTEM},
                    {"role": "user", "content": user_msg},
                ]
                raw = ""
                async for chunk in client.inference_stream_v2(messages=messages, max_tokens=800, temperature=0):
                    if isinstance(chunk, dict):
                        raw += chunk.get("content", "")
                    elif isinstance(chunk, str):
                        raw += chunk
                spec = _parse_spec(raw)
                if spec is None:
                    spec_note = "LLM returned an unparseable spec — returning data untransformed."
    except Exception:  # noqa: BLE001
        logger.exception("smart-workbook: LLM call failed")
        spec_note = "LLM unavailable — returning data untransformed."

    # Apply transforms (or return originals if no spec)
    result_sheets = []
    for s in target_sheets:
        if spec:
            transformed = _apply_transform({"columns": s["columns"], "rows": s["rows"]}, spec)
        else:
            transformed = {"columns": s["columns"], "rows": s["rows"]}
        result_sheets.append({
            "name": s["name"],
            "columns": transformed["columns"],
            "rows": transformed["rows"],
        })

    return {
        "ok": True,
        "sheets": result_sheets,
        "spec": spec,
        **({"note": spec_note} if spec_note else {}),
    }
