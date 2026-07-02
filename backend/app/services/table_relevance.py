"""Deterministic table-relevance classifier for connector sync.

A freshly-synced data source (especially Power BI) surfaces every table in every
semantic model the user can see — including tables that are pure noise to a
business user: Power BI *usage-metrics* telemetry (who viewed which report),
staging copies, measure holders, and empty/internal tables. Left active, they
bloat the schema prompt, get promoted into the agent's "Key Tables", and seed
telemetry-flavoured conversation starters ("Report Usage Analytics") that nobody
asked for.

``classify_table`` applies cheap, deterministic rules (NO LLM) to tag each table
with a role, an audience, and a ``useful`` verdict. The sync path stores the
verdict on ``DataSourceTable.metadata_json['classification']`` and sets
``is_active = useful`` — so downstream (schema, Key Tables, starters) carries only
business-useful tables. A manual re-check in the Tables tab always wins.

Gated by ``flags.AUTO_TABLE_RELEVANCE`` (default OFF) at the call site; this module
itself is pure and side-effect free.

Verdict shape::

    {
      "role": "fact" | "dimension" | "measure" | "staging" | "telemetry" | "meta" | "table",
      "audience": "business" | "admin" | "system",
      "useful": bool,
      "reason": str,     # human-readable why
      "score": float,    # 0..1 confidence this table is business-useful
      "version": 1,
    }
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

VERSION = 1

# Power BI internal index column present on every table over the REST/DAX path.
_INTERNAL_COL_PREFIXES = ("RowNumber-", "RowNumber")

# Dataset names Microsoft auto-creates for report-adoption telemetry.
_USAGE_METRICS_MARKERS = ("usage metrics",)

# Column names that betray a Power BI usage-metrics model.
_USAGE_METRICS_COLS = ("isusagemetricsreport", "isusagemetricsreportws")

# Leaf table names / prefixes that are staging (raw, pre-modelled) copies.
_STAGING_PREFIXES = ("stg_", "staging", "_raw", "raw_", "tmp", "temp_")

# Leaf names that are measure / meta holders (no analysable rows of their own).
_META_EXACT = {"#measure", "model measures", "refresh stats"}

# Power BI auto date/time hierarchy tables — never business content.
_PBI_AUTO_DATE = ("datetabletemplate", "localdatetable")


def _leaf(name: str) -> str:
    """Return the table leaf, dropping a ``<dataset>/`` prefix if present."""
    return name.split("/", 1)[1] if "/" in name else name


def _dataset(name: str) -> str:
    """Return the ``<dataset>`` prefix, or "" when the name is unqualified."""
    return name.split("/", 1)[0] if "/" in name else ""


def _col_names(columns: Optional[List[Any]]) -> List[str]:
    """Normalise a columns payload (list of dicts or objects) to lower-case names."""
    out: List[str] = []
    for c in columns or []:
        if isinstance(c, dict):
            n = c.get("name")
        else:
            n = getattr(c, "name", None)
        if n:
            out.append(str(n))
    return out


def _real_col_names(columns: Optional[List[Any]]) -> List[str]:
    """Column names excluding Power BI internal index columns."""
    return [
        n for n in _col_names(columns)
        if not any(n.startswith(p) for p in _INTERNAL_COL_PREFIXES)
    ]


def classify_table(name: str, columns: Optional[List[Any]] = None) -> Dict[str, Any]:
    """Classify one table by name + columns. Pure; never raises.

    Rules run top-down, first match wins. Noise rules first (they are the point),
    then positive fact/dimension signals, then a permissive default (keep).
    """
    leaf = _leaf(name)
    leaf_l = leaf.strip().lower()
    dataset_l = _dataset(name).strip().lower()
    all_cols = _col_names(columns)
    real_cols = _real_col_names(columns)
    real_l = [c.lower() for c in real_cols]

    def verdict(role, audience, useful, reason, score):
        return {
            "role": role, "audience": audience, "useful": useful,
            "reason": reason, "score": round(float(score), 2), "version": VERSION,
        }

    # ---- NOISE rules (deactivate) --------------------------------------------

    # 1. Power BI usage-metrics telemetry — dataset name or tell-tale column.
    if any(m in dataset_l for m in _USAGE_METRICS_MARKERS) or any(
        c in real_l for c in _USAGE_METRICS_COLS
    ):
        return verdict(
            "telemetry", "admin", False,
            "Power BI usage-metrics telemetry (report-adoption stats), not business data",
            0.05,
        )

    # 2. Power BI auto date/time hierarchy tables.
    if leaf_l.startswith(_PBI_AUTO_DATE):
        return verdict(
            "system", "system", False,
            "Power BI auto date/time hierarchy table", 0.0,
        )

    # 3. Measure / meta holders (no analysable rows).
    if leaf_l in _META_EXACT or leaf_l.startswith("#") or (
        leaf_l.endswith("measures") and len(real_cols) <= 2
    ):
        return verdict(
            "meta", "system", False,
            "Measure/meta holder — no queryable rows of its own", 0.05,
        )

    # 4. Staging / raw copies (redundant with a modelled dimension/fact).
    if leaf_l.startswith(_STAGING_PREFIXES):
        return verdict(
            "staging", "admin", False,
            "Staging/raw copy — superseded by the modelled table", 0.1,
        )

    # 5. Empty tables: no real columns at all (only internal index col, or none).
    if not real_cols:
        return verdict(
            "meta", "system", False,
            "No data columns (internal/index-only table)", 0.0,
        )

    # ---- POSITIVE rules (keep) -----------------------------------------------

    # 6. Explicit dimension.
    if leaf_l.startswith("dim_") or leaf_l.startswith("dim ") or leaf_l == "dim":
        return verdict(
            "dimension", "business", True,
            "Dimension table — grouping/filter axis", 0.7,
        )

    # 7. Explicit fact / pre-aggregated fact.
    if leaf_l.startswith(("fct_", "fact_", "fct ", "fact ")):
        agg = any(k in real_l for k in ("year", "month", "count", "total"))
        return verdict(
            "fact", "business", True,
            "Pre-aggregated fact table" if agg else "Fact table — measurable grain",
            0.6 if agg else 0.85,
        )

    # 8. Heuristic fact: has a metric-ish column AND a dimension/date column.
    metric_hint = any(
        any(k in c for k in ("amount", "qty", "quantity", "count", "total",
                             "price", "net", "value", "views", "time", "duration",
                             "ratio", "rank", "score"))
        for c in real_l
    )
    dimlike_hint = any(
        any(k in c for k in ("date", "id", "name", "code", "status", "type",
                             "sector", "dept", "category", "group"))
        for c in real_l
    )
    if metric_hint and dimlike_hint and len(real_cols) >= 4:
        return verdict(
            "fact", "business", True,
            "Fact-like table — carries measures + dimensions", 0.8,
        )

    # 9. Small lookup → dimension.
    if len(real_cols) <= 4:
        return verdict(
            "dimension", "business", True,
            "Small lookup/dimension table", 0.55,
        )

    # 10. Default: keep, unclassified business table (permissive — never hide by
    #     accident; only the explicit noise rules above deactivate).
    return verdict(
        "table", "business", True,
        "General business table", 0.5,
    )


def classify_tables(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Batch helper. ``rows`` = [{"name":.., "columns":[..]}]; returns each row's
    dict augmented with a ``classification`` key. Pure; never raises."""
    out = []
    for r in rows:
        try:
            c = classify_table(r.get("name", ""), r.get("columns"))
        except Exception:  # noqa: BLE001 — classifier must never break sync
            c = {
                "role": "table", "audience": "business", "useful": True,
                "reason": "classifier error — kept by default", "score": 0.5,
                "version": VERSION,
            }
        out.append({**r, "classification": c})
    return out
