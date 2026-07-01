"""Ingest reader: CSV -> pandas DataFrame. Encoding + delimiter sniff + null norm.

Pure (no DB). Never raises — returns an empty DataFrame on failure.
"""
from __future__ import annotations

import csv as _csv
import logging
import re

import pandas as pd

logger = logging.getLogger(__name__)

_NULL_TOKENS = {"", "na", "n/a", "null", "none", "-", "--", "?", ".", "—", "–", "nan"}

# id-like column names whose values must stay text (never numeric-coerce)
_ID_NAME_RE = re.compile(
    r"(?i)(^|_)(id|code|zip|postal|phone|mobile|tel|sku|account|acct|iban|ssn|barcode|upc|ean)(_|$)"
)
_MAX_SAFE_INT = 2 ** 53


def _should_skip_numeric(col_name, series: pd.Series) -> bool:
    """True when a column must stay text (skip numeric coercion) because it is an
    identifier-like column. Guards against corrupting IDs/codes via float casting.
    Skip when ANY of:
      - the column name is id-like (regex, or endswith '_id', or == 'id'), OR
      - >5% of non-null values have a LEADING ZERO ('0' + digits, len>1), OR
      - any value's integer magnitude exceeds 2**53 (would lose float precision).
    """
    try:
        name = str(col_name).strip()
        low = name.lower()
        if _ID_NAME_RE.search(name) or low.endswith("_id") or low == "id":
            return True

        non_null = [v for v in series.tolist() if v is not None and not (isinstance(v, float) and pd.isna(v))]
        if not non_null:
            return False

        leading_zero = 0
        for v in non_null:
            s = str(v).strip()
            if len(s) > 1 and s[0] == "0" and s.isdigit():
                leading_zero += 1
        if leading_zero / len(non_null) > 0.05:
            return True

        for v in non_null:
            s = str(v).strip()
            digits = s[1:] if s[:1] in "+-" else s
            if digits.isdigit() and abs(int(s)) > _MAX_SAFE_INT:
                return True

        return False
    except Exception:  # noqa: BLE001
        # fail-safe: on any error keep the column as-is (do not coerce)
        return True


def _detect_encoding(path: str) -> str:
    try:
        import chardet  # vendored in the image

        with open(path, "rb") as f:
            raw = f.read(65536)
        enc = (chardet.detect(raw) or {}).get("encoding")
        return enc or "utf-8"
    except Exception:
        return "utf-8"


def _detect_delimiter(path: str, encoding: str) -> str:
    try:
        with open(path, "r", encoding=encoding, errors="replace") as f:
            sample = f.read(8192)
        return _csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except Exception:
        return ","


def _is_label(v) -> bool:
    """True if a cell is a non-null, non-numeric-looking string label."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return False
    s = str(v).strip()
    if not s:
        return False
    try:
        float(s.replace(",", ""))
        return False
    except (ValueError, TypeError):
        return True


def _detect_header_row(path: str, enc: str, sep: str, *, scan: int = 25) -> int:
    """First row where >=60% of non-null cells are string labels AND the row
    spans most columns — skips banner/title rows above the real header. Returns 0
    when nothing better is found. Fail-soft.

    Parses raw rows with the stdlib ``csv`` reader (NOT pandas) so a narrow banner
    row above the real header can't collapse the inferred column count to 1.
    """
    try:
        rows: list[list[str]] = []
        with open(path, "r", encoding=enc, errors="replace", newline="") as f:
            for i, fields in enumerate(_csv.reader(f, delimiter=sep)):
                rows.append(fields)
                if i + 1 >= scan:
                    break
        if not rows:
            return 0
        width = max(len(r) for r in rows)
        if width <= 1:
            return 0
        min_cover = max(2, int(0.6 * width))
        for i, row in enumerate(rows):
            non_null = [c for c in row if c is not None and str(c).strip() != ""]
            if len(non_null) < min_cover:
                continue  # banner / sparse row above the header
            labels = sum(1 for c in non_null if _is_label(c))
            if labels / max(len(non_null), 1) >= 0.6:
                return i
    except Exception:  # noqa: BLE001
        pass
    return 0


def read_csv(path: str, *, max_rows: int = 1_000_000) -> pd.DataFrame:
    """Read a CSV robustly. Normalizes common null tokens to NaN."""
    try:
        enc = _detect_encoding(path)
        sep = _detect_delimiter(path, enc)
        header_row = _detect_header_row(path, enc, sep)
        df = pd.read_csv(
            path,
            sep=sep,
            encoding=enc,
            encoding_errors="replace",
            header=header_row,
            nrows=max_rows,
            on_bad_lines="skip",
            dtype=object,
        )
        # normalize nulls
        df = df.applymap(
            lambda v: None
            if (isinstance(v, str) and v.strip().lower() in _NULL_TOKENS)
            else v
        )
        # best-effort numeric coercion per column (>50% numeric -> coerce),
        # but skip id-like / leading-zero / >2**53 columns to keep them text.
        for col in df.columns:
            if _should_skip_numeric(col, df[col]):
                continue
            coerced = pd.to_numeric(df[col], errors="coerce")
            if coerced.notna().mean() > 0.5:
                df[col] = coerced
        return df
    except Exception:
        logger.exception("read_csv failed for %s", path)
        return pd.DataFrame()
