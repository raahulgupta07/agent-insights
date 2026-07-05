"""Chart-selection guardrail (BI-uplift Phase 1, flag HYBRID_CHART_GUARDRAIL).

Encodes the deck's intent->chart matrix and corrects a clearly-wrong choice
BEFORE the view is built. Deliberately conservative: it only downgrades combos
that are unambiguously wrong (a pie of 20 categories, a bar of a time series
the user asked to 'trend'), never second-guesses a reasonable pick. Returns a
possibly-corrected data_model plus human-readable lint notes.

Pure + fail-soft: any error returns the input data_model unchanged with no
notes, so it can never break create_data.

Matrix:
  compare categories        -> bar_chart
  change over time          -> line_chart
  part-to-whole (<=5 cats)  -> pie_chart      (>5 -> bar_chart)
  correlation / relationship-> scatter_plot
  ranking (top/highest)     -> bar_chart
  precise values            -> table
"""
from __future__ import annotations

from typing import Any

_TIME_WORDS = ("over time", "trend", "trending", "monthly", "per month", "by month",
               "daily", "per day", "by day", "weekly", "yearly", "per year", "growth",
               "time series", "timeline")
_CORR_WORDS = ("correlation", "correlate", "relationship", "versus", " vs ", "vs.",
               "against", "impact of", "driver", "scatter")
_RANK_WORDS = ("top ", "rank", "ranking", "highest", "largest", "biggest", "lowest",
               "smallest", "leaderboard", "best ", "worst ")
_TIME_COL_HINTS = ("date", "month", "year", "day", "time", "period", "quarter", "week")

_MAX_SERIES = 4          # cap: more than this on one axis is noise
_MAX_PIE_SLICES = 5      # part-to-whole rule from the deck


def _looks_datetime(col_name: str, sample_vals: list) -> bool:
    n = str(col_name).lower()
    if any(h in n for h in _TIME_COL_HINTS):
        return True
    # cheap value probe: mostly parseable as dates?
    try:
        import pandas as pd
        vals = [v for v in sample_vals if v not in (None, "")][:15]
        if not vals:
            return False
        parsed = pd.to_datetime(pd.Series(vals).astype(str), errors="coerce")
        return parsed.notna().mean() >= 0.7
    except Exception:
        return False


def _is_numeric_col(sample_vals: list) -> bool:
    vals = [v for v in sample_vals if v not in (None, "")][:15]
    if not vals:
        return False
    ok = 0
    for v in vals:
        try:
            float(v)
            ok += 1
        except Exception:
            pass
    return ok / len(vals) >= 0.8


def guardrail_data_model(prompt: str, formatted: dict, data_model: dict) -> tuple[dict, list[str]]:
    """Return (corrected_data_model, notes). Never raises."""
    try:
        dm = dict(data_model or {})
        vtype = (dm.get("type") or "table").lower()
        if vtype in ("table", "metric_card", "count", "map", "heatmap"):
            return dm, []  # not chart-matrix territory

        prompt_l = (prompt or "").lower()
        cols = formatted.get("columns", []) or []
        rows = formatted.get("rows", []) or []
        total_rows = int((formatted.get("info", {}) or {}).get("total_rows", len(rows)) or len(rows))

        # per-column sample values
        def col_vals(field):
            out = []
            for r in rows[:20]:
                if isinstance(r, dict):
                    out.append(r.get(field))
                elif isinstance(r, (list, tuple)):
                    pass
            return out

        fields = [c.get("field") for c in cols if c.get("field")]
        time_cols = [f for f in fields if _looks_datetime(f, col_vals(f))]
        numeric_cols = [f for f in fields if _is_numeric_col(col_vals(f))]
        cat_cols = [f for f in fields if f not in numeric_cols and f not in time_cols]

        # cardinality of the primary category dim (approx from sample + total rows)
        dim = cat_cols[0] if cat_cols else None
        dim_card = None
        if dim:
            seen = set()
            for r in rows[:200]:
                if isinstance(r, dict):
                    seen.add(r.get(dim))
            # if sample is saturated, assume >= total distinct is at least len(seen)
            dim_card = len(seen) if len(rows) < 200 else max(len(seen), total_rows)

        notes: list[str] = []
        new_type = vtype

        want_time = bool(time_cols) and any(w in prompt_l for w in _TIME_WORDS)
        want_corr = any(w in prompt_l for w in _CORR_WORDS)
        want_rank = any(w in prompt_l for w in _RANK_WORDS)

        # 1. pie/doughnut with too many slices -> bar
        if vtype in ("pie_chart",) and (dim_card is not None and dim_card > _MAX_PIE_SLICES):
            new_type = "bar_chart"
            notes.append(f"pie had {dim_card} categories (>{_MAX_PIE_SLICES}) → switched to bar for readability")

        # 2. correlation intent with two numeric columns -> scatter
        elif want_corr and len(numeric_cols) >= 2 and vtype in ("bar_chart", "line_chart"):
            new_type = "scatter_plot"
            notes.append("relationship/correlation intent with two measures → scatter plot")

        # 3. trend-over-time intent shown as bar/area -> line
        elif want_time and vtype in ("bar_chart", "area_chart"):
            new_type = "line_chart"
            notes.append("time-series intent → line chart (bar hides the trend)")

        # 4. ranking intent as pie/line -> bar
        elif want_rank and vtype in ("pie_chart", "line_chart") and dim:
            new_type = "bar_chart"
            notes.append("ranking intent → bar chart (ordered comparison)")

        if new_type != vtype:
            dm["type"] = new_type

        # 5. series cap (note only — never silently drop data)
        series = dm.get("series")
        if isinstance(series, list) and len(series) > _MAX_SERIES:
            notes.append(f"{len(series)} series on one axis exceeds the {_MAX_SERIES}-series focus limit — "
                         "consider splitting into small multiples")

        return dm, notes
    except Exception:
        return dict(data_model or {}), []
