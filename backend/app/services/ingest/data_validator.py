"""E4 — Data validation gate (Master Plan stage 4), the "garbage-in" net.

Cheap, LOUD checks over an ingested frame + its E3 profile so a bad/typo filter
or a dropped month becomes a surfaced warning instead of a silent zero. Never
raises; every function returns structured warnings::

    {"severity": info|warn|error, "kind": ..., "column": ...|None, "detail": str,
     "suggestion": str|None}

Then ``build_data_quality_block(warnings)`` compacts them into a
``<data_quality>...</data_quality>`` string the agent can read (mirrors the
existing ``<data_coverage>`` reconcile surface).

Design mirror: pure functions, pandas-only, fail-soft, aligned dtype vocab with
``column_profile`` (E3). No ORM, no client, no LLM.
"""
from __future__ import annotations

import difflib
import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

# a null_pct above this on a column that isn't ~all-null is a spike worth noting
_NULL_SPIKE_PCT = 40.0
# category values this close (case/space-insensitive ratio) are near-duplicates.
# Tuned HIGH on purpose: a genuine typo differs by ~1-2 chars (ratio ~0.9+),
# whereas real distinct categories that merely share a stem
# ('Successful'/'Unsuccessful', 'Vanilla 400g'/'Vanilla 850g', 'Activation - GT'
# /'Activation - MT') must NOT be flagged — a noisy near-dup check trains the
# agent to distrust real values.
_NEAR_DUP_RATIO = 0.92
# a real typo also has a SMALL absolute edit distance; reject pairs whose folded
# strings differ by more than this many chars even if the ratio is high (guards
# long strings where a big shared prefix inflates the ratio).
_NEAR_DUP_MAX_EDITS = 2
# only hunt near-dups / value-existence among reasonably low-cardinality columns
_MAX_CATEGORY_DISTINCT = 500
# closeness for a "did you mean" suggestion on a missing filter value
_SUGGEST_RATIO = 0.6


def _warn(severity: str, kind: str, detail: str, column: Optional[str] = None,
          suggestion: Optional[str] = None) -> Dict[str, Any]:
    return {
        "severity": severity,
        "kind": kind,
        "column": column,
        "detail": detail,
        "suggestion": suggestion,
    }


def _norm_val(v: Any) -> str:
    """Case/whitespace-fold a value for near-match comparison."""
    return " ".join(str(v).strip().lower().split())


def _column_values(df: "pd.DataFrame", column: str) -> Optional[List[Any]]:
    """Distinct non-null raw values of a column, or None if the column is absent
    or too high-cardinality to be a filterable category."""
    try:
        if column not in df.columns:
            return None
        vals = df[column].dropna().unique().tolist()
        if len(vals) > _MAX_CATEGORY_DISTINCT:
            return None
        return vals
    except Exception:
        return None


def validate_filter_values(
    df: "pd.DataFrame",
    predicates: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Every filter value must actually appear in its column.

    ``predicates`` = ``[{"column": str, "value": <scalar or list>}, ...]`` (extra
    keys like ``op`` are ignored). For each value not present, emit a ``warn`` —
    and if a case/whitespace-insensitive near-match exists, suggest the real
    value (catches ``'Retentnion call'`` vs ``'Retention Call'`` → silent 0).

    Missing column → one ``error`` per predicate. High-cardinality columns are
    skipped for the existence check (can't warn on free-text). Never raises.
    """
    out: List[Dict[str, Any]] = []
    if df is None or not predicates:
        return out
    try:
        for pred in predicates:
            try:
                column = pred.get("column")
                if not column:
                    continue
                raw = pred.get("value")
                if raw is None:
                    continue
                values = raw if isinstance(raw, (list, tuple, set)) else [raw]

                if column not in df.columns:
                    out.append(_warn(
                        "error", "missing_column",
                        f"filter references column {column!r} which is not in the data",
                        column=column,
                    ))
                    continue

                col_vals = _column_values(df, column)
                if col_vals is None:
                    # high-cardinality / free-text — can't assert existence loudly
                    continue

                present_norm = {_norm_val(v): v for v in col_vals}
                for val in values:
                    if val is None:
                        continue
                    key = _norm_val(val)
                    if key in present_norm:
                        continue  # present (possibly modulo case/space)
                    # not present — hunt a near-match to suggest
                    match = difflib.get_close_matches(
                        key, list(present_norm.keys()), n=1, cutoff=_SUGGEST_RATIO
                    )
                    suggestion = present_norm[match[0]] if match else None
                    detail = (
                        f"filter value {val!r} does not appear in column {column!r} "
                        f"(would silently match 0 rows)"
                    )
                    if suggestion is not None:
                        detail += f" — did you mean {suggestion!r}?"
                    out.append(_warn(
                        "warn", "filter_value_absent", detail,
                        column=column, suggestion=(str(suggestion) if suggestion is not None else None),
                    ))
            except Exception as e:  # noqa: BLE001 — one bad predicate never kills the rest
                logger.debug("validate_filter_values skipped a predicate: %s", e)
                continue
    except Exception as e:  # noqa: BLE001
        logger.warning("validate_filter_values failed: %s", e)
    return out


def row_count_sanity(
    profile: Dict[str, Dict[str, Any]],
    expected_floor: Optional[int] = None,
    *,
    row_count: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Warn when the frame has too few rows.

    Row count is taken from ``row_count`` if given, else inferred from the E3
    profile (max distinct across columns is a floor on the real row count; but we
    prefer an explicit count). ``expected_floor`` is the minimum plausible row
    count for this source — below it is a ``warn`` (likely a dropped month / bad
    ingest). Zero rows is always an ``error``. Never raises.
    """
    out: List[Dict[str, Any]] = []
    try:
        n = row_count
        if n is None:
            # infer a lower bound: the largest per-column distinct count
            distincts = [
                p.get("distinct") for p in (profile or {}).values()
                if isinstance(p, dict) and isinstance(p.get("distinct"), int)
            ]
            n = max(distincts) if distincts else 0

        if n <= 0:
            out.append(_warn("error", "row_count_zero",
                             "the ingested data has 0 rows"))
            return out
        if expected_floor is not None and n < expected_floor:
            out.append(_warn(
                "warn", "row_count_low",
                f"row count {n} is below the expected floor of {expected_floor} "
                f"(a file/period may have failed to load)",
            ))
    except Exception as e:  # noqa: BLE001
        logger.warning("row_count_sanity failed: %s", e)
    return out


import re as _re

# separators that segment a category label into tokens (space + common code
# delimiters, incl. the en-dash Myanmar channel names use).
_TOKEN_SPLIT_RE = _re.compile(r"[\s–—\-/:,]+")
# a "code token" that legitimately distinguishes real variants (GT/MT, 3+, 400,
# QR, single/two-letter suffixes) — short and alphanumeric (letters and/or
# digits, optional trailing +).
_CODE_TOKEN_MAX_LEN = 3


def _strip_digits(s: str) -> str:
    return "".join(ch for ch in s if not ch.isdigit())


def _tokens(s: str) -> List[str]:
    return [t for t in _TOKEN_SPLIT_RE.split(s) if t]


def _is_code_token(t: str) -> bool:
    """Short alphanumeric code like 'gt', 'mt', 'qr', '3', '400', '1+'."""
    core = t.rstrip("+")
    return 0 < len(t) <= _CODE_TOKEN_MAX_LEN and core.isalnum()


def _differs_only_in_a_code_token(a: str, b: str) -> bool:
    """True when a and b split into the same number of tokens and differ in
    exactly ONE token, and that differing token is a short alphanumeric code on
    BOTH sides ('activation – gt' vs 'activation – mt', '...400g' vs '...850g',
    'pediasure 3+' vs 'pediasure 1+'). This marks a real distinct variant, NOT a
    typo. A misspelling ('retention'/'retentnion') differs in a long token → not
    matched here → still flagged as a near-duplicate."""
    ta, tb = _tokens(a), _tokens(b)
    if len(ta) != len(tb) or not ta:
        return False
    diff_idx = [k for k in range(len(ta)) if ta[k] != tb[k]]
    if len(diff_idx) != 1:
        return False
    k = diff_idx[0]
    return _is_code_token(ta[k]) and _is_code_token(tb[k])


def _edit_distance_le(a: str, b: str, limit: int) -> bool:
    """True when Levenshtein(a, b) <= limit. Cheap early-exit band; only ever
    called on short category strings, so the full DP is fine."""
    la, lb = len(a), len(b)
    if abs(la - lb) > limit:
        return False
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        row_min = cur[0]
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            row_min = min(row_min, cur[j])
        if row_min > limit:
            return False
        prev = cur
    return prev[lb] <= limit


def _near_duplicate_categories(values: Sequence[Any]) -> List[Tuple[Any, Any]]:
    """Pairs of category values that are TYPO-close (e.g. 'Retention Call' vs
    'Retentnion call'): high similarity AND a tiny absolute edit distance. The
    edit-distance guard is what rejects real distinct siblings that merely share
    a stem ('Successful'/'Unsuccessful', size/channel variants). O(n^2) —
    bounded by the cardinality cap."""
    pairs: List[Tuple[Any, Any]] = []
    norm = [(v, _norm_val(v)) for v in values]
    seen: set = set()
    for i in range(len(norm)):
        vi, ni = norm[i]
        for j in range(i + 1, len(norm)):
            vj, nj = norm[j]
            if ni == nj:
                continue  # exact case/space dupes are handled by folding, not a typo
            ratio = difflib.SequenceMatcher(None, ni, nj).ratio()
            if ratio < _NEAR_DUP_RATIO:
                continue
            if not _edit_distance_le(ni, nj, _NEAR_DUP_MAX_EDITS):
                continue
            # reject REAL distinct variants that differ only in a short code:
            #  * size/tier numbers ('...400g'/'...850g') — identical once digits
            #    are stripped;
            #  * a single short alphanumeric code token ('Activation – GT'/'– MT',
            #    'PA QR Code – GT'/'– MT') — a real channel split, not a typo.
            # A misspelling ('Retentnion'/'Retention') differs mid-word in a long
            # token → passes both guards → still flagged.
            if _strip_digits(ni) == _strip_digits(nj):
                continue
            if _differs_only_in_a_code_token(ni, nj):
                continue
            key = tuple(sorted((str(vi), str(vj))))
            if key not in seen:
                seen.add(key)
                pairs.append((vi, vj))
    return pairs


def null_and_dup_checks(
    df: "pd.DataFrame",
    profile: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Null-spike, all-null, and category near-duplicate checks.

    * all-null column → ``warn`` (the column carries no signal).
    * null_pct > threshold (but not all-null) → ``info`` null-spike.
    * category columns with near-duplicate values → ``warn`` (typo splits a group
      → under-counts). Uses the E3 ``top_values`` when present, else derives
      distinct values from the frame. Never raises.
    """
    out: List[Dict[str, Any]] = []
    try:
        for col, p in (profile or {}).items():
            if not isinstance(p, dict):
                continue
            null_pct = p.get("null_pct")
            if isinstance(null_pct, (int, float)):
                if null_pct >= 100.0:
                    out.append(_warn("warn", "all_null",
                                     f"column {col!r} is entirely null", column=col))
                elif null_pct >= _NULL_SPIKE_PCT:
                    out.append(_warn("info", "null_spike",
                                     f"column {col!r} is {null_pct}% null", column=col))

            if p.get("dtype") != "category":
                continue
            # source of candidate values: profile top_values, else the frame
            values = p.get("top_values") or []
            if not values and df is not None and col in getattr(df, "columns", []):
                values = _column_values(df, col) or []
            if len(values) < 2:
                continue
            for a, b in _near_duplicate_categories(values):
                out.append(_warn(
                    "warn", "category_near_duplicate",
                    f"column {col!r} has near-duplicate values {a!r} and {b!r} "
                    f"(likely a typo splitting one group)",
                    column=col, suggestion=str(b),
                ))
    except Exception as e:  # noqa: BLE001
        logger.warning("null_and_dup_checks failed: %s", e)
    return out


# severity → sort rank (errors first) and label
_SEV_RANK = {"error": 0, "warn": 1, "info": 2}


def build_data_quality_block(warnings: Sequence[Dict[str, Any]]) -> str:
    """Compact ``<data_quality>...</data_quality>`` string for the agent.

    Empty / no-warnings → an explicit clean marker so a downstream renderer can
    tell "checked, all good" apart from "never checked". Never raises.
    """
    try:
        if not warnings:
            return "<data_quality>ok: no data-quality issues detected</data_quality>"
        ordered = sorted(
            warnings,
            key=lambda w: (_SEV_RANK.get(w.get("severity", "info"), 3),
                           str(w.get("kind", ""))),
        )
        lines = ["<data_quality>"]
        for w in ordered:
            sev = str(w.get("severity", "info")).upper()
            col = w.get("column")
            col_s = f" [{col}]" if col else ""
            detail = str(w.get("detail", "")).strip()
            lines.append(f"- {sev}{col_s}: {detail}")
        lines.append("</data_quality>")
        return "\n".join(lines)
    except Exception as e:  # noqa: BLE001
        logger.warning("build_data_quality_block failed: %s", e)
        return "<data_quality>ok</data_quality>"
