"""Robust Excel -> clean table(s) reader (dash 5-layer, condensed).

Pure-Python: pandas + openpyxl + stdlib only. NO DB writes. Every function
is fail-safe: on error it logs and returns a safe default instead of raising.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Callable, Optional

import pandas as pd

logger = logging.getLogger(__name__)

_NULL_TOKENS = {"", "na", "n/a", "null", "none", "-", "?", "nan"}

# id-like column names whose values must stay text (never numeric-coerce)
_ID_NAME_RE = re.compile(
    r"(?i)(^|_)(id|code|zip|postal|phone|mobile|tel|sku|account|acct|iban|ssn|barcode|upc|ean)(_|$)"
)
_MAX_SAFE_INT = 2 ** 53


def _should_skip_numeric(col_name, series: pd.Series) -> bool:
    """True when a column must stay text (skip numeric coercion) because it is an
    identifier-like column. Guards against corrupting IDs/codes via float casting.
    Skip when ANY of: id-like name; >5% leading-zero values; or any |int| > 2**53.
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
        return True


def _safe_table(name: str) -> str:
    """Slug a sheet name -> [a-z0-9_], lowercased, <=48 chars."""
    try:
        s = re.sub(r"[^a-z0-9_]+", "_", str(name).strip().lower())
        s = re.sub(r"_+", "_", s).strip("_")
        if not s:
            # degenerate slug (empty / symbol-only): append a short stable hash of
            # the original name so two different empty-slug names don't collide.
            h = hashlib.md5(str(name).encode("utf-8")).hexdigest()[:6]
            return "table_" + h
        return s[:48]
    except Exception:  # noqa: BLE001
        logger.exception("excel_reader._safe_table failed")
        return "table"


def _isna(c) -> bool:
    return c is None or (isinstance(c, float) and pd.isna(c))


def _is_label_cell(v) -> bool:
    """True if cell is a non-null, non-numeric-looking string label."""
    try:
        if _isna(v):
            return False
        s = str(v).strip()
        if not s or s.lower() in _NULL_TOKENS:
            return False
        try:
            float(s.replace(",", ""))
            return False
        except (ValueError, TypeError):
            return True
    except Exception:  # noqa: BLE001
        return False


def _find_header_row(raw: pd.DataFrame) -> int:
    """First row where >=60% of non-null cells are string labels."""
    try:
        ncols = raw.shape[1] if raw.ndim == 2 else 1
        min_cover = max(2, int(0.6 * ncols))  # header must span most columns (skip sparse banners)
        for i in range(min(len(raw), 50)):
            row = list(raw.iloc[i])
            non_null = [c for c in row if not _isna(c)]
            if len(non_null) < min_cover:
                continue  # banner / title / sparse row above the real header
            labels = sum(1 for c in non_null if _is_label_cell(c))
            if labels / max(len(non_null), 1) >= 0.6:
                return i
    except Exception:  # noqa: BLE001
        logger.exception("excel_reader._find_header_row failed")
    return 0


def _clean_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize null tokens, drop empty rows/cols, coerce numeric columns."""
    try:
        def _norm(v):
            if isinstance(v, str) and v.strip().lower() in _NULL_TOKENS:
                return pd.NA
            return v
        df = df.applymap(_norm)
        df = df.dropna(axis=0, how="all").dropna(axis=1, how="all")
        for col in df.columns:
            ser = df[col]
            non_null = ser.dropna()
            if len(non_null) == 0:
                continue
            # skip id-like / leading-zero / >2**53 columns to keep them text
            if _should_skip_numeric(col, ser):
                continue
            coerced = pd.to_numeric(non_null.astype(str).str.replace(",", "", regex=False),
                                    errors="coerce")
            if coerced.notna().mean() > 0.5:
                df[col] = pd.to_numeric(
                    ser.astype(str).str.replace(",", "", regex=False), errors="coerce")
        return df.reset_index(drop=True)
    except Exception:  # noqa: BLE001
        logger.exception("excel_reader._clean_frame failed")
        return df


def _read_sheet(path: str, sheet: str, header_row: int, skip_top: int = 0) -> pd.DataFrame:
    try:  # re-read with detected header/skip; returns cleaned frame
        df = pd.read_excel(path, sheet_name=sheet, header=header_row + skip_top, engine="openpyxl")
        return _clean_frame(df)
    except Exception:  # noqa: BLE001
        logger.exception("excel_reader._read_sheet failed: %s", sheet)
        return pd.DataFrame()


def _is_suspect(df: pd.DataFrame) -> bool:
    try:  # L2 validation: flag unlikely-clean tables
        if df.empty:
            return True
        rows, cols = df.shape
        if cols > 30 or cols > rows:
            return True
        if df.isna().mean().mean() > 0.6:
            return True
        names = [str(c).strip().lower() for c in df.columns]
        if len(names) != len(set(names)):
            return True
        return False
    except Exception:  # noqa: BLE001
        logger.exception("excel_reader._is_suspect failed")
        return False


def _parse_json(text: str) -> Optional[dict]:
    try:  # robustly parse a JSON object from llm output
        t = re.sub(r"```[a-zA-Z]*", "", str(text)).replace("```", "").strip()
        m = re.search(r"\{.*\}", t, re.DOTALL)
        if not m:
            return None
        blob = re.sub(r",\s*([}\]])", r"\1", m.group(0))  # trailing-comma repair
        obj = json.loads(blob)
        return obj if isinstance(obj, dict) else None
    except Exception:  # noqa: BLE001
        logger.exception("excel_reader._parse_json failed")
        return None


def _rescue(path: str, sheet: str, suspect: pd.DataFrame, llm_inference: Callable) -> Optional[dict]:
    try:  # L3: ask LLM for header_row/skip_top from first 25 raw rows
        raw = pd.read_excel(path, sheet_name=sheet, header=None, nrows=25, engine="openpyxl")
        prompt = (
            "Given these raw spreadsheet rows, return ONLY JSON "
            '{"header_row": int, "skip_top": int} for the real table header.\n\n'
            + raw.to_csv(index=False, header=False)
        )
        plan = _parse_json(llm_inference(prompt))
        if not plan:
            return None
        hr = int(plan.get("header_row", 0))
        st = int(plan.get("skip_top", 0))
        fixed = _read_sheet(path, sheet, hr, st)
        if len(fixed) >= 5 * max(len(suspect), 1):
            return {"header_row": hr, "skip_top": st, "df": fixed}
    except Exception:  # noqa: BLE001
        logger.exception("excel_reader._rescue failed: %s", sheet)
    return None


def read_excel(path: str, *, content_hash: str = "", llm_inference: Optional[Callable] = None,
               cache_lookup: Optional[Callable] = None,
               cache_save: Optional[Callable] = None) -> list:
    """Read an Excel workbook into one or more clean tables. Never raises."""
    out: list = []
    try:
        cached_plan = None
        if cache_lookup and content_hash:
            try:
                cached_plan = cache_lookup(content_hash)
            except Exception:  # noqa: BLE001
                logger.exception("excel_reader cache_lookup failed")
        xls = pd.ExcelFile(path, engine="openpyxl")
        resolved: dict = {}
        for sheet in xls.sheet_names:
            try:
                if cached_plan and sheet in cached_plan:  # 0-LLM cached apply
                    p = cached_plan[sheet]
                    df = _read_sheet(path, sheet, int(p.get("header_row", 0)),
                                     int(p.get("skip_top", 0)))
                    if not df.empty:
                        out.append({"sheet": sheet, "table_name": _safe_table(sheet), "df": df})
                    continue
                raw = pd.read_excel(path, sheet_name=sheet, header=None, engine="openpyxl")
                if raw.dropna(how="all").empty:
                    continue  # skip empty sheets
                # banner rows above header are skipped via the detected header_row
                df = _read_sheet(path, sheet, _find_header_row(raw), 0)
                if df.empty:
                    continue
                if _is_suspect(df) and llm_inference is not None:  # L3 rescue
                    rescued = _rescue(path, sheet, df, llm_inference)
                    if rescued:
                        df = rescued["df"]
                        resolved[sheet] = {"header_row": rescued["header_row"],
                                           "skip_top": rescued["skip_top"]}
                # Multi-table v1: blank separator rows are dropped by _clean_frame,
                # effectively returning the merged/first block. Not over-engineered.
                if not df.empty:
                    out.append({"sheet": sheet, "table_name": _safe_table(sheet), "df": df})
            except Exception:  # noqa: BLE001
                logger.exception("excel_reader sheet failed: %s", sheet)
                continue
        if resolved and cache_save and content_hash:
            try:
                cache_save(content_hash, resolved)
            except Exception:  # noqa: BLE001
                logger.exception("excel_reader cache_save failed")
    except Exception:  # noqa: BLE001
        logger.exception("excel_reader.read_excel total failure: %s", path)
        return []
    return out
