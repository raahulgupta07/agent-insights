"""Ingest reader: CSV -> pandas DataFrame. Encoding + delimiter sniff + null norm.

Pure (no DB). Never raises — returns an empty DataFrame on failure.
"""
from __future__ import annotations

import csv as _csv
import logging

import pandas as pd

logger = logging.getLogger(__name__)

_NULL_TOKENS = {"", "na", "n/a", "null", "none", "-", "--", "?", ".", "—", "–", "nan"}


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


def read_csv(path: str, *, max_rows: int = 1_000_000) -> pd.DataFrame:
    """Read a CSV robustly. Normalizes common null tokens to NaN."""
    try:
        enc = _detect_encoding(path)
        sep = _detect_delimiter(path, enc)
        df = pd.read_csv(
            path,
            sep=sep,
            encoding=enc,
            encoding_errors="replace",
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
        # best-effort numeric coercion per column (>50% numeric -> coerce)
        for col in df.columns:
            coerced = pd.to_numeric(df[col], errors="coerce")
            if coerced.notna().mean() > 0.5:
                df[col] = coerced
        return df
    except Exception:
        logger.exception("read_csv failed for %s", path)
        return pd.DataFrame()
