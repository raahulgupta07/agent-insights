"""E3 — Column profiling (Master Plan stage 3), pure-pandas, fail-soft.

Per-column facts computed straight off an in-memory frame (no live client, no
LLM, no ORM) so the validation net (E4) and the semantic layer have real
ground-truth about each column BEFORE the first question.

``profile_frame(df)`` returns one entry per column::

    {col: {dtype, null_pct, distinct, min, max, top_values, sample}}

where ``dtype`` is one of ``number | date | category | text`` (the coarse
data-shape vocabulary the plan's validation + agent surface speak — distinct
from ``column_intel``'s semantic *role* dimension/measure/id/date, which is a
SQL-side concern). Detection idioms mirror ``ai/knowledge/column_intel`` so the
two agree on what "numeric" / "date-ish" means.

Every column is profiled independently and fail-soft: any per-column error is
swallowed and that column falls back to a text profile. ``profile_frame`` never
raises.

Persistence: there is NO ``ColumnProfile`` table in this repo (the plan's
``colprofile1`` migration was never merged here — profiling instead lives in
``column_intel`` writing into ``DataSourceTable.columns[].metadata``). So
``persist_profile`` is a graceful no-op-if-absent helper that merges the profile
into that same metadata dict when handed active table rows, and simply returns 0
when there is nowhere to write. If a dedicated table is wanted later, the DDL is
documented in the module that owns migrations — this service does not author one.
"""
from __future__ import annotations

import logging
import math
import re
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ── vocab shared in spirit with ai/knowledge/column_intel ───────────────────
# name patterns hinting a date even when stored as text
_DATE_NAME_RE = re.compile(
    r"\b(date|month|year|day|quarter|week|period|_at)\b|month$|year$", re.IGNORECASE
)

# how many distinct values below which a text column is treated as a category
_CATEGORY_CARDINALITY_CAP = 200
# how many top values to store
_TOP_VALUES_LIMIT = 20
# how many distinct non-null values to try to date-parse before deciding a text
# column is really a date (cheap sample, not the whole column)
_DATE_SNIFF_SAMPLE = 50
# fraction of the sniffed sample that must parse as dates to call it a date
_DATE_SNIFF_THRESHOLD = 0.8


def _jsonable(v: Any) -> Any:
    """Coerce a value into something JSON-serialisable (mirrors column_intel)."""
    if v is None:
        return None
    try:
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
    except Exception:
        pass
    if isinstance(v, (str, int, float, bool)):
        return v
    # numpy / pandas scalars -> python
    try:
        if hasattr(v, "item"):
            return _jsonable(v.item())
    except Exception:
        pass
    return str(v)


def _looks_like_date_name(name: str) -> bool:
    return bool(_DATE_NAME_RE.search(name or ""))


def _sniff_dates(series: "pd.Series") -> bool:
    """True when a healthy majority of a text series' distinct sample parses as
    dates. Cheap: only looks at up to ``_DATE_SNIFF_SAMPLE`` distinct values."""
    try:
        sample = series.dropna().astype(str).unique()[:_DATE_SNIFF_SAMPLE]
        if len(sample) == 0:
            return False
        parsed = pd.to_datetime(pd.Series(sample), errors="coerce", format="mixed")
        ok = int(parsed.notna().sum())
        return ok >= max(1, int(len(sample) * _DATE_SNIFF_THRESHOLD))
    except Exception:
        return False


def _classify_dtype(series: "pd.Series", name: str) -> str:
    """number | date | category | text — data-shape, not semantic role."""
    try:
        if pd.api.types.is_bool_dtype(series):
            return "category"
        if pd.api.types.is_numeric_dtype(series):
            return "number"
        if pd.api.types.is_datetime64_any_dtype(series):
            return "date"
    except Exception:
        pass

    # object / string column — decide date vs category vs text
    try:
        non_null = series.dropna()
        if len(non_null) == 0:
            return "text"
        if _looks_like_date_name(name) and _sniff_dates(non_null):
            return "date"
        distinct = int(non_null.astype(str).nunique())
        if 0 < distinct <= _CATEGORY_CARDINALITY_CAP:
            return "category"
        # last chance: an un-hinted-name column that still parses as dates
        if _sniff_dates(non_null):
            return "date"
        return "text"
    except Exception:
        return "text"


def _min_max(series: "pd.Series", dtype: str):
    """(min, max) for number/date columns; (None, None) otherwise. JSON-safe."""
    if dtype not in ("number", "date"):
        return None, None
    try:
        s = series.dropna()
        if len(s) == 0:
            return None, None
        if dtype == "date":
            s = pd.to_datetime(s, errors="coerce", format="mixed").dropna()
            if len(s) == 0:
                return None, None
            return str(s.min()), str(s.max())
        return _jsonable(s.min()), _jsonable(s.max())
    except Exception:
        return None, None


def _top_values(series: "pd.Series") -> List[Any]:
    """Most-frequent non-null values (JSON-safe), capped. Empty on any failure."""
    try:
        vc = series.dropna().value_counts().head(_TOP_VALUES_LIMIT)
        return [_jsonable(v) for v in vc.index.tolist()]
    except Exception:
        return []


def _sample(series: "pd.Series", n: int = 5) -> List[Any]:
    """A few real non-null example values (JSON-safe)."""
    try:
        vals = series.dropna().unique()[:n]
        return [_jsonable(v) for v in vals]
    except Exception:
        return []


def profile_column(series: "pd.Series", name: str) -> Dict[str, Any]:
    """Profile a single column. Fail-soft — falls back to a text profile."""
    try:
        n = int(len(series))
        nulls = int(series.isna().sum())
        null_pct = round((nulls / n) * 100, 2) if n else 0.0
        try:
            distinct = int(series.dropna().nunique())
        except Exception:
            distinct = None

        dtype = _classify_dtype(series, name)
        mn, mx = _min_max(series, dtype)

        # a values list is only meaningful for category-shaped columns; number
        # and text columns still get a small sample for context.
        top_values = _top_values(series) if dtype in ("category",) else []

        return {
            "dtype": dtype,
            "null_pct": null_pct,
            "distinct": distinct,
            "min": mn,
            "max": mx,
            "top_values": top_values,
            "sample": _sample(series),
        }
    except Exception as e:  # noqa: BLE001 — never let one column kill the frame
        logger.debug("profile_column(%r) fell back to text: %s", name, e)
        return {
            "dtype": "text",
            "null_pct": 0.0,
            "distinct": None,
            "min": None,
            "max": None,
            "top_values": [],
            "sample": [],
        }


def profile_frame(df: "pd.DataFrame") -> Dict[str, Dict[str, Any]]:
    """Profile every column of a frame → ``{col: {dtype, null_pct, distinct,
    min, max, top_values, sample}}``. Never raises; a bad frame → ``{}``."""
    out: Dict[str, Dict[str, Any]] = {}
    try:
        if df is None or getattr(df, "empty", True):
            return out
        for col in df.columns:
            try:
                out[str(col)] = profile_column(df[col], str(col))
            except Exception as e:  # noqa: BLE001
                logger.debug("profile_frame skipped column %r: %s", col, e)
                continue
    except Exception as e:  # noqa: BLE001
        logger.warning("profile_frame failed on frame: %s", e)
        return out
    return out


# ── persistence (no-op-graceful; NO dedicated table exists in this repo) ─────
# The plan's ``ColumnProfile`` model + ``colprofile1`` migration are NOT present
# here; the established store is ``DataSourceTable.columns[].metadata`` (written
# by column_intel). This helper merges an E3 profile into that same metadata for
# a set of active table rows, WITHOUT clobbering ``description`` or any
# manually-set key — mirroring column_intel._store_profile's discipline. Caller
# commits. Returns the number of columns written (0 when there is nowhere to
# write, so it is safe to call unconditionally).
_PROFILE_KEYS = ("dtype", "null_pct", "distinct", "min", "max", "top_values")


def _norm(s: str) -> str:
    return "".join(ch for ch in (str(s) or "").lower().strip() if ch.isalnum())


def persist_profile(table_rows, profile: Dict[str, Dict[str, Any]]) -> int:
    """Merge ``profile`` into each ``DataSourceTable``-like row's
    ``columns[].metadata`` (match by normalised column name). Fail-soft; does
    NOT commit and does NOT touch ``description``. Returns columns written.

    ``table_rows`` is any iterable of objects exposing a mutable ``columns``
    list-of-dicts (the DataSourceTable ORM shape). Pass an empty iterable and
    this simply returns 0 — the profiler stays useful even with no place to
    persist.
    """
    if not table_rows or not profile:
        return 0
    try:
        from sqlalchemy.orm.attributes import flag_modified  # local: keep pure imports optional
    except Exception:
        flag_modified = None  # type: ignore

    by_norm = {_norm(k): v for k, v in profile.items()}
    written = 0
    for t in table_rows:
        try:
            cols = getattr(t, "columns", None)
            if not isinstance(cols, list) or not cols:
                continue
            changed = False
            for entry in cols:
                if not isinstance(entry, dict):
                    continue
                prof = by_norm.get(_norm(entry.get("name") or ""))
                if not prof:
                    continue
                meta = entry.get("metadata")
                if not isinstance(meta, dict):
                    meta = {}
                for k in _PROFILE_KEYS:
                    if k in prof:
                        meta[k] = prof[k]
                entry["metadata"] = meta
                written += 1
                changed = True
            if changed and flag_modified is not None:
                flag_modified(t, "columns")
        except Exception as e:  # noqa: BLE001
            logger.debug("persist_profile skipped a table row: %s", e)
            continue
    return written
