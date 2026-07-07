"""Coder grounding contract (Phase 3, part A).

Builds a COMPACT, prompt-ready "grounding" block for the code generator: the
approved semantic column meanings + metric formulas + known join edges, SCOPED
to the tables the coder actually targets. The idea is to hand the coder the
DEFINED joins/metrics/meanings so it uses them verbatim instead of guessing.

Gated on ``flags.CODER_GROUNDING`` (``HYBRID_CODER_GROUNDING``, default OFF).
Returns "" when the flag is off, when nothing is in scope, or on ANY error —
this must NEVER break codegen.

Approved-only invariant: this module reuses the three existing approved-only
context builders (SemanticContextBuilder / MetricsContextBuilder /
JoinGraphContextBuilder), which already filter to ``status == "approved"``. We
only narrow their output down to the target tables + render compactly.
"""
from __future__ import annotations

from typing import Any, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.settings.hybrid_flags import flags

# Hard cap on the rendered block so the coder prompt budget is respected
# (target <= ~1500 tokens; ~6000 chars is a safe upper bound). We truncate
# gracefully with a note rather than emit an unbounded block.
_MAX_CHARS = 6000
# Per-subsection line caps (keep it a handful, most-relevant first).
_MAX_COLS = 24
_MAX_METRICS = 16
_MAX_JOINS = 16


def _norm(name: Any) -> str:
    """Normalize a table (or table.col) reference to its bare, lowercased leaf.

    Table names in ``tables_by_source`` may carry a schema/dataset prefix using
    ``.`` or ``/`` (e.g. "public.inventory", "Regional Sales/Opportunities").
    Semantic ``table_name`` / metric ``table_ref`` / join edge tables may or may
    not carry the same prefix, so we compare on the last path segment.
    """
    if not name:
        return ""
    s = str(name).strip().strip('"').strip("'")
    s = s.replace("/", ".")
    if "." in s:
        s = s.split(".")[-1]
    return s.strip().lower()


def _collect_targets(tables_by_source: Optional[List[Any]]) -> tuple[set[str], List[str]]:
    """Return (normalized-target-table-set, distinct data_source_ids).

    Accepts the normalized list[dict] shape used in build_codegen_context
    (each item ``{"data_source_id": str|None, "tables": [names]}``) as well as
    pydantic-like objects with the same attributes.
    """
    targets: set[str] = set()
    ds_ids: List[str] = []
    for item in tables_by_source or []:
        if isinstance(item, dict):
            ds_id = item.get("data_source_id")
            tables = item.get("tables") or []
        else:
            ds_id = getattr(item, "data_source_id", None)
            tables = getattr(item, "tables", None) or []
        if ds_id and str(ds_id) not in ds_ids:
            ds_ids.append(str(ds_id))
        for t in tables:
            n = _norm(t)
            if n:
                targets.add(n)
    return targets, ds_ids


async def build_grounding_context(
    db: AsyncSession,
    *,
    organization: Any,
    tables_by_source: Optional[List[Any]] = None,
    question: str = "",
) -> str:
    """Build the compact coder grounding block (or "").

    All failure modes -> "" (never raises). Empty when the flag is off, when
    there are no target tables, or when nothing approved is in scope.
    """
    # 1. Flag short-circuit — byte-identical (empty) when OFF.
    try:
        if not flags.CODER_GROUNDING:
            return ""
    except Exception:
        return ""

    if db is None or organization is None:
        return ""

    try:
        # 2. Target tables + their data sources.
        targets, ds_ids = _collect_targets(tables_by_source)
        if not targets and not ds_ids:
            return ""
        ds_scope = ds_ids or None
        q = question or ""

        # 3. Reuse the approved-only builders, scoped by data source + ranked by
        #    the question. They self-gate on their own feature flags
        #    (SEMANTIC_LAYER / METRICS_CATALOG / JOIN_GRAPH); when a layer is off
        #    its subsection is simply empty (fail-soft, no injection).
        from app.ai.context.builders.semantic_context_builder import SemanticContextBuilder
        from app.ai.context.builders.metrics_context_builder import MetricsContextBuilder
        from app.ai.context.builders.join_graph_context_builder import JoinGraphContextBuilder

        # ---- Column meanings (approved semantic columns for target tables) ----
        col_lines: List[str] = []
        try:
            sem = await SemanticContextBuilder(db, organization, ds_scope).build(q)
            for t in getattr(sem, "items", []) or []:
                if targets and _norm(getattr(t, "table_name", "")) not in targets:
                    continue
                tname = getattr(t, "table_name", "") or ""
                for c in getattr(t, "columns", []) or []:
                    meaning = (getattr(c, "meaning", "") or "").strip()
                    cname = getattr(c, "name", "") or ""
                    if not meaning or not cname:
                        continue
                    col_lines.append(f"- {tname}.{cname}: {meaning}")
                    if len(col_lines) >= _MAX_COLS:
                        break
                if len(col_lines) >= _MAX_COLS:
                    break
        except Exception:
            col_lines = []

        # ---- Metric formulas (approved metrics whose table_ref is a target) ----
        metric_lines: List[str] = []
        try:
            met = await MetricsContextBuilder(db, organization, ds_scope).build(q)
            for m in getattr(met, "items", []) or []:
                ref = getattr(m, "table_ref", "") or ""
                if targets and ref and _norm(ref) not in targets:
                    continue
                name = (getattr(m, "name", "") or "").strip()
                if not name:
                    continue
                # Prefer the exact SQL formula; fall back to the definition.
                calc = " ".join((getattr(m, "sql_calc", "") or "").split())
                definition = (getattr(m, "definition", "") or "").strip()
                body = calc or definition
                if not body:
                    continue
                if len(body) > 220:
                    body = body[:220] + "…"
                metric_lines.append(f"- {name}: {body}")
                if len(metric_lines) >= _MAX_METRICS:
                    break
        except Exception:
            metric_lines = []

        # ---- Known joins (approved edges between two target tables) ----
        join_lines: List[str] = []
        try:
            jg = await JoinGraphContextBuilder(db, organization, ds_scope).build(q)
            for e in getattr(jg, "items", []) or []:
                lt = getattr(e, "left_table", "") or ""
                rt = getattr(e, "right_table", "") or ""
                lc = getattr(e, "left_col", "") or ""
                rc = getattr(e, "right_col", "") or ""
                if not (lt and rt and lc and rc):
                    continue
                # Only edges whose BOTH endpoints are in the target set.
                if targets and (_norm(lt) not in targets or _norm(rt) not in targets):
                    continue
                join_lines.append(f"- {lt}.{lc} = {rt}.{rc}")
                if len(join_lines) >= _MAX_JOINS:
                    break
        except Exception:
            join_lines = []

        if not (col_lines or metric_lines or join_lines):
            return ""

        # 4. Render the compact block. Omit any empty subsection.
        parts: List[str] = [
            "## Grounding (use these — do not guess joins or metric formulas)",
        ]
        if col_lines:
            parts.append("### Column meanings")
            parts.extend(col_lines)
        if metric_lines:
            parts.append("### Metric formulas (use verbatim)")
            parts.extend(metric_lines)
        if join_lines:
            parts.append("### Known joins")
            parts.extend(join_lines)

        block = "\n".join(parts).strip()
        if len(block) > _MAX_CHARS:
            block = block[:_MAX_CHARS].rstrip() + "\n… (truncated)"
        return block
    except Exception:
        return ""
