"""Deterministic analytics primitives — the shared 'compute' half of
compute-then-narrate. Pure pandas/numpy: no LLM, no DB, no network.

The BI-uplift phases all funnel through here so every surfaced number is real:
  * Phase 6 (Auto-EDA)      -> profile_dataframe()
  * Phase 5 (Data-prep gate)-> missing_data_plan()
  * Phase 2 (Insight engine)-> sweep_signals()
  * Phase 7 (Stat rigour)   -> correlation_pairs()

Everything is fail-soft: on any error a helper returns a partial/empty result
rather than raising, so a profiling pass can never break a train run.
"""
from __future__ import annotations

from typing import Any, Optional
import math

try:
    import pandas as pd
    import numpy as np
except Exception:  # pragma: no cover - pandas always present in-image
    pd = None
    np = None


# --- role detection ---------------------------------------------------------

# Tokens whose presence as a WHOLE WORD implies a critical measure — a missing
# value in one of these means the ROW is untrustworthy (Fill/Investigate/Remove
# -> Remove). Matched token-wise (not loose substring) so "Affiliate Value Name"
# or "Registration Date" don't get mis-flagged. 'value' is intentionally excluded
# (too generic); id-like columns are matched separately by suffix.
_CRITICAL_HINTS = (
    "revenue", "amount", "sales", "price", "cost", "profit", "qty", "quantity",
    "units", "transaction",
)
# Above this null-rate a critical column is treated as a broken/empty column
# (Investigate) rather than a reason to drop every row.
_ROW_DROP_MAX_NULL_PCT = 50.0
# Column names that must never be sampled as example values (PII).
_PII_HINTS = ("email", "phone", "ssn", "passport", "password", "credit", "card", "iban")


def _is_datetime(s) -> bool:
    try:
        if pd.api.types.is_datetime64_any_dtype(s):
            return True
        # try a cheap parse on a small sample
        sample = s.dropna().astype(str).head(20)
        if sample.empty:
            return False
        parsed = pd.to_datetime(sample, errors="coerce", utc=False)
        return parsed.notna().mean() >= 0.8
    except Exception:
        return False


def _is_numeric(s) -> bool:
    try:
        return pd.api.types.is_numeric_dtype(s)
    except Exception:
        return False


def _safe_num(x) -> Optional[float]:
    try:
        f = float(x)
        if math.isnan(f) or math.isinf(f):
            return None
        return round(f, 4)
    except Exception:
        return None


def classify_columns(df) -> dict[str, str]:
    """Map each column -> one of: 'datetime' | 'numeric' | 'categorical'."""
    roles: dict[str, str] = {}
    for c in df.columns:
        s = df[c]
        if _is_datetime(s):
            roles[c] = "datetime"
        elif _is_numeric(s):
            roles[c] = "numeric"
        else:
            roles[c] = "categorical"
    return roles


def is_critical_column(name: str) -> bool:
    """Critical = a measure token appears as a whole word, or the column is an
    id (ends in 'id' / '_id' / 'id ...'). Token-wise to avoid false positives
    like 'Affiliate Value Name'."""
    n = str(name).lower()
    tokens = [t for t in re_split_words(n) if t]
    if any(h in tokens for h in _CRITICAL_HINTS):
        return True
    # id columns: 'id', '<x>_id', 'order id', 'transaction id'
    if tokens and (tokens[-1] == "id" or n.endswith("_id") or n == "id"):
        return True
    return False


def re_split_words(name: str) -> list[str]:
    import re as _re
    return _re.split(r"[^a-z0-9]+", str(name).lower())


def is_pii_column(name: str) -> bool:
    n = str(name).lower()
    return any(h in n for h in _PII_HINTS)


# --- missing-data plan (Phase 5) -------------------------------------------

def missing_data_plan(df) -> dict[str, Any]:
    """Fill / Investigate / Remove decision per column, per the deck's tree.

    * Remove   -> critical measure/id column with any nulls (rows can't be trusted)
    * Investigate -> a null 'spike' (>20% missing) that may signal a system error
    * Fill     -> non-critical dimension with a modest amount of missing values
    Returns a summary dict; never mutates df.
    """
    out = {"total_rows": 0, "columns": [], "rows_droppable": 0, "actions": {}}
    if pd is None or df is None or len(df) == 0:
        return out
    try:
        n = len(df)
        out["total_rows"] = int(n)
        drop_mask = None
        for c in df.columns:
            miss = int(df[c].isna().sum())
            pct = round(100.0 * miss / n, 2) if n else 0.0
            if miss == 0:
                continue
            critical = is_critical_column(c)
            if critical and pct < _ROW_DROP_MAX_NULL_PCT:
                # a real, mostly-present critical measure: nulls here poison the ROW
                action = "remove"
                m = df[c].isna()
                drop_mask = m if drop_mask is None else (drop_mask | m)
            elif pct >= _ROW_DROP_MAX_NULL_PCT:
                # broken/empty column (even if 'critical'-named) — don't nuke rows
                action = "investigate"
            elif pct >= 20.0:
                action = "investigate"
            else:
                action = "fill"
            out["columns"].append(
                {"name": str(c), "missing": miss, "missing_pct": pct, "action": action,
                 "critical": bool(critical)}
            )
            out["actions"][str(c)] = action
        if drop_mask is not None:
            out["rows_droppable"] = int(drop_mask.sum())
        out["rows_clean"] = int(n - out["rows_droppable"])
        return out
    except Exception:
        return out


# --- profile (Phase 6) ------------------------------------------------------

def _category_shares(s, top: int = 5) -> list[dict]:
    try:
        vc = s.astype(str).value_counts(dropna=True)
        total = int(vc.sum()) or 1
        rows = []
        for name, cnt in vc.head(top).items():
            rows.append({"label": str(name)[:60], "count": int(cnt),
                         "pct": round(100.0 * int(cnt) / total, 1)})
        return rows
    except Exception:
        return []


def _numeric_distribution(s, bins: int = 8) -> dict:
    try:
        vals = pd.to_numeric(s, errors="coerce").dropna()
        if vals.empty:
            return {}
        q1, med, q3 = (float(vals.quantile(0.25)), float(vals.median()),
                       float(vals.quantile(0.75)))
        iqr = q3 - q1
        lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        outliers = int(((vals < lo) | (vals > hi)).sum())
        counts, edges = np.histogram(vals, bins=min(bins, max(3, vals.nunique())))
        buckets = [
            {"lo": _safe_num(edges[i]), "hi": _safe_num(edges[i + 1]), "count": int(counts[i])}
            for i in range(len(counts))
        ]
        return {
            "min": _safe_num(vals.min()), "max": _safe_num(vals.max()),
            "mean": _safe_num(vals.mean()), "median": _safe_num(med),
            "q1": _safe_num(q1), "q3": _safe_num(q3),
            "outlier_count": outliers, "outlier_low": _safe_num(lo), "outlier_high": _safe_num(hi),
            "buckets": buckets,
        }
    except Exception:
        return {}


def _time_series(df, dt_col, measure_col) -> dict:
    """Monthly aggregate of measure over a datetime column, with peak month."""
    try:
        d = df[[dt_col, measure_col]].copy()
        d[dt_col] = pd.to_datetime(d[dt_col], errors="coerce")
        d[measure_col] = pd.to_numeric(d[measure_col], errors="coerce")
        d = d.dropna()
        if d.empty:
            return {}
        g = d.groupby(d[dt_col].dt.to_period("M"))[measure_col].sum().sort_index()
        if g.empty:
            return {}
        points = [{"period": str(p), "value": _safe_num(v)} for p, v in g.items()]
        peak_period = str(g.idxmax())
        first, last = float(g.iloc[0]) or 0.0, float(g.iloc[-1])
        growth_pct = round(100.0 * (last - first) / first, 1) if first else None
        return {"points": points, "peak_period": peak_period,
                "peak_value": _safe_num(g.max()), "growth_pct": growth_pct,
                "measure": str(measure_col), "date_col": str(dt_col)}
    except Exception:
        return {}


def _ranking(df, dim_col, measure_col, top: int = 5) -> dict:
    try:
        d = df[[dim_col, measure_col]].copy()
        d[measure_col] = pd.to_numeric(d[measure_col], errors="coerce")
        d = d.dropna()
        if d.empty:
            return {}
        g = d.groupby(d[dim_col].astype(str))[measure_col].sum().sort_values(ascending=False).head(top)
        return {"dim": str(dim_col), "measure": str(measure_col),
                "rows": [{"label": str(k)[:60], "value": _safe_num(v)} for k, v in g.items()]}
    except Exception:
        return {}


def correlation_pairs(df, threshold: float = 0.5, top: int = 5) -> list[dict]:
    """Top absolute Pearson correlations between numeric columns (Phase 7/2)."""
    out: list[dict] = []
    if pd is None or df is None:
        return out
    try:
        num = df.select_dtypes(include="number")
        if num.shape[1] < 2:
            return out
        corr = num.corr(numeric_only=True)
        seen = set()
        pairs = []
        for a in corr.columns:
            for b in corr.columns:
                if a == b or (b, a) in seen:
                    continue
                seen.add((a, b))
                r = corr.loc[a, b]
                if r is None or (isinstance(r, float) and math.isnan(r)):
                    continue
                pairs.append((abs(float(r)), a, b, float(r)))
        pairs.sort(reverse=True)
        for absr, a, b, r in pairs[:top]:
            if absr >= threshold:
                out.append({"a": str(a), "b": str(b), "r": round(r, 3),
                            "direction": "positive" if r > 0 else "negative"})
        return out
    except Exception:
        return out


def profile_dataframe(df, table_name: str = "") -> dict[str, Any]:
    """The Auto-EDA computed profile — the 'first look' from the deck.

    Returns a JSON-safe dict: shape, per-column roles/nulls/uniques, category
    shares, a best-guess time series (peak), a best-guess ranking, a numeric
    distribution, and correlation pairs. Chart-ready for the Overview renderer.
    """
    prof: dict[str, Any] = {"table": str(table_name), "n_rows": 0, "n_cols": 0, "columns": []}
    if pd is None or df is None or len(df) == 0:
        return prof
    try:
        n = len(df)
        roles = classify_columns(df)
        prof["n_rows"], prof["n_cols"] = int(n), int(df.shape[1])
        for c in df.columns:
            s = df[c]
            prof["columns"].append({
                "name": str(c), "role": roles[c],
                "null_pct": round(100.0 * int(s.isna().sum()) / n, 1) if n else 0.0,
                "n_unique": int(s.nunique(dropna=True)),
            })

        dt_cols = [c for c, r in roles.items() if r == "datetime"]
        num_cols = [c for c, r in roles.items() if r == "numeric"]
        cat_cols = [c for c, r in roles.items() if r == "categorical"]

        # pick the "primary measure" = numeric col with the highest total spread
        measure = None
        if num_cols:
            measure = max(num_cols, key=lambda c: _safe_num(pd.to_numeric(df[c], errors="coerce").sum()) or 0)

        # category shares: first low-cardinality categorical (≤ 12 distinct)
        cat_pick = next((c for c in cat_cols if 2 <= df[c].nunique(dropna=True) <= 12), None)
        if cat_pick is not None:
            prof["category_shares"] = {"dim": str(cat_pick), "rows": _category_shares(df[cat_pick])}

        # time series: first datetime × primary measure
        if dt_cols and measure:
            ts = _time_series(df, dt_cols[0], measure)
            if ts:
                prof["time_series"] = ts

        # ranking: a higher-cardinality categorical × primary measure
        rank_dim = next((c for c in cat_cols if df[c].nunique(dropna=True) > 3), cat_pick)
        if rank_dim is not None and measure:
            rk = _ranking(df, rank_dim, measure)
            if rk:
                prof["ranking"] = rk

        # distribution of the primary measure
        if measure:
            dist = _numeric_distribution(df[measure])
            if dist:
                prof["distribution"] = {"column": str(measure), **dist}

        corr = correlation_pairs(df)
        if corr:
            prof["correlations"] = corr

        return prof
    except Exception:
        return prof


def sweep_signals(df, table_name: str = "") -> list[dict]:
    """Phase 2 signal sweep — rank the dominant deviations for the narrator.

    Emits computed signals (trend / seasonality-peak / outliers / relationship)
    each with a magnitude so the caller can pick the strongest 'story hook'.
    """
    signals: list[dict] = []
    if pd is None or df is None or len(df) == 0:
        return signals
    try:
        prof = profile_dataframe(df, table_name)
        ts = prof.get("time_series")
        if ts and ts.get("growth_pct") is not None:
            signals.append({"kind": "trend", "magnitude": abs(ts["growth_pct"]),
                            "detail": f"{ts['measure']} moved {ts['growth_pct']}% overall",
                            "data": ts})
            if ts.get("peak_period"):
                signals.append({"kind": "seasonality", "magnitude": 50.0,
                                "detail": f"peak in {ts['peak_period']}", "data": ts})
        dist = prof.get("distribution")
        if dist and dist.get("outlier_count"):
            signals.append({"kind": "outlier", "magnitude": float(dist["outlier_count"]),
                            "detail": f"{dist['outlier_count']} outliers in {dist['column']}",
                            "data": dist})
        for cp in prof.get("correlations", []):
            signals.append({"kind": "relationship", "magnitude": abs(cp["r"]) * 100,
                            "detail": f"{cp['a']} vs {cp['b']} r={cp['r']}", "data": cp})
        signals.sort(key=lambda s: s.get("magnitude", 0), reverse=True)
        return signals
    except Exception:
        return signals
