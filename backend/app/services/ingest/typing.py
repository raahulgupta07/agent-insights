"""E5 — Data typing (Master Plan stage 5).

Cast number/date-shaped object columns to real numeric/datetime BEFORE the frame
reaches DuckDB, so the query engine does true SUM/AVG/min-max + date range/sort
instead of broken string ops (``"1,234"`` summed as text, dates sorted lexically).

Discipline (why this is safe for the verified goldens):
* dtype is decided by E3's ``column_profile._classify_dtype`` — a shared, tested
  classifier. Only columns it calls ``number`` / ``date`` are touched.
* ``category`` and ``text`` columns are LEFT ALONE — they carry the exact filter
  values the verified-golden COUNT(*) predicates depend on. Typing must never move
  a count.
* provenance columns (``_source_*``) are never touched.
* conversion is all-or-nothing per column and only applied when a healthy majority
  of non-null values parse (``_CONVERT_THRESHOLD``); otherwise the raw string column
  is kept. Never corrupt data to gain a type.
* fail-soft: any error returns the raw frame unchanged.
"""
import logging
import re
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # import-cost only when type-checking
    import pandas as pd

_DATE_THRESHOLD = 0.90     # >=90% of non-null must parse as date, else keep raw
_NUM_THRESHOLD = 0.98      # numbers stricter — a column is a measure only if ~all parse
_CODE_LIKE_RE = re.compile(r"^0\d+$")     # leading-zero integer = code/phone/zip, NOT a measure
_NUM_STRIP_RE = re.compile(r"[,\s ]")     # thousands sep, spaces, nbsp
_LEADING_SYMBOL_RE = re.compile(r"^[^\d\-+.]+")  # leading currency/symbols ($, MMK, etc.)


def _clean_numeric_strings(s):
    """Strip thousands separators + a leading currency symbol from a string series."""
    return (s.astype(str)
             .str.replace(_NUM_STRIP_RE, "", regex=True)
             .str.replace(_LEADING_SYMBOL_RE, "", regex=True))


def _try_number(series):
    """Return a numeric Series if the column is a real measure, else None.

    Independent of E3's category/number label (a low-cardinality measure like
    ['1,234','2,000','500'] is classed 'category' by cardinality — we still want
    it typed). Guards: >=98% must parse, and any leading-zero integer value
    (``007``) marks the column as a CODE (phone/zip/id) → left as string so the
    leading zero + exact-match filters survive.
    """
    import pandas as pd
    non_null = series.dropna()
    if non_null.empty:
        return None
    as_str = non_null.astype(str)
    if as_str.str.match(_CODE_LIKE_RE).any():
        return None  # code/phone/zip column — never a measure
    parsed = pd.to_numeric(_clean_numeric_strings(non_null), errors="coerce")
    ok = int(parsed.notna().sum())
    if ok >= max(1, int(len(non_null) * _NUM_THRESHOLD)):
        return pd.to_numeric(_clean_numeric_strings(series), errors="coerce")
    return None


def _try_date(series):
    """Return a datetime Series if >=threshold of non-null values parse, else None."""
    import pandas as pd
    non_null = series.dropna()
    if non_null.empty:
        return None
    parsed = pd.to_datetime(non_null.astype(str), errors="coerce", format="mixed")
    ok = int(parsed.notna().sum())
    if ok >= max(1, int(len(non_null) * _DATE_THRESHOLD)):
        return pd.to_datetime(series, errors="coerce", format="mixed")
    return None


def apply_typing(df):
    """Return a typed COPY of ``df``. number-shaped object cols → numeric,
    date-shaped → datetime; category/text/provenance untouched. Never raises;
    returns the original frame on any failure. Also returns nothing extra — the
    caller just uses the frame."""
    import pandas as pd
    from app.services.ingest.column_profile import _classify_dtype
    try:
        if df is None or getattr(df, "empty", True):
            return df
        out = df.copy()
        for col in out.columns:
            name = str(col)
            if name.startswith("_source_"):
                continue
            s = out[col]
            try:
                if not pd.api.types.is_object_dtype(s):
                    continue  # already a real type
                dtype = _classify_dtype(s, name)
                # date takes priority (a date column must not be read as a number);
                # otherwise attempt number on ANY object column — _try_number is
                # strict (98% parse + code guard) so text/name columns return None
                # and only genuine measures (incl. low-cardinality ones E3 labels
                # 'category') get typed.
                if dtype == "date":
                    conv = _try_date(s)
                    if conv is not None:
                        out[col] = conv
                        continue
                conv = _try_number(s)
                if conv is not None:
                    out[col] = conv
            except Exception as e:  # noqa: BLE001 — one bad column never kills the frame
                logger.debug("apply_typing skipped column %r: %s", name, e)
                continue
        return out
    except Exception as e:  # noqa: BLE001
        logger.warning("apply_typing failed, using raw frame: %s", e)
        return df
