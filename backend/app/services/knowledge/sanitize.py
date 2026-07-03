"""sanitize — the leak firewall.

Before a learned fact crosses from a user's private context into the SHARED
store (keyed by model/schema/file), everything that could be a *data value*
must be stripped. Only SCHEMA-SHAPED knowledge is allowed to travel: table and
column names, a query's STRUCTURE, business-meaning prose, and parametric
templates with placeholders. A DAX/SQL *template* is safe; a *result row*,
a filter constant, an entity name, an id, a date — is not.

Design stance: CONSERVATIVE. When in doubt, drop or redact. A false drop costs
a little reuse; a false keep leaks data. Callers treat a ``SanitizeResult`` with
``ok=False`` as "do not share" (it may still be kept in the PRIVATE tier).

Pure, dependency-free, never raises.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# --- literal patterns that must never appear in shared text -----------------
# Quoted string literals ('Discontinued', "2024-01-01"), numbers with >=4 digits
# or decimals/thousands (ids, amounts, exact counts), ISO-ish dates, emails,
# GUID-like ids, and long digit runs.
_SQL_STRING_LIT = re.compile(r"'[^']*'|\"[^\"]*\"")
_DATE = re.compile(r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b|\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_GUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_BIG_NUM = re.compile(r"(?<![\w])[+-]?\d{1,3}(?:[,\.]\d{3})+(?:\.\d+)?(?![\w])|(?<![\w.])\d{4,}(?:\.\d+)?(?![\w])|(?<![\w])\d+\.\d+(?![\w])")

_PLACEHOLDER = "{value}"

# keys in a content dict that are STRUCTURE (safe) vs DATA (must be scrubbed)
_SAFE_KEYS = {
    "table", "tables", "column", "columns", "join", "joins", "relation",
    "measure", "measures", "kind", "title", "meaning", "note", "template",
    "dax_template", "query_template", "placeholders", "error_class", "fix_shape",
    "steps", "how", "scope_kind",
}
_DATA_KEYS = {
    "rows", "row", "result", "results", "values", "value", "data", "sample",
    "sample_values", "filter", "filters", "where", "constant", "constants",
    "answer", "number", "count", "total", "records",
}


@dataclass
class SanitizeResult:
    ok: bool
    content: Any
    redactions: int = 0
    reasons: list[str] = field(default_factory=list)


def redact_text(s: str) -> tuple[str, int]:
    """Replace every literal (strings/dates/emails/guids/big-numbers) with a
    placeholder. Returns (clean_text, redaction_count)."""
    n = 0

    def _sub(_m):
        nonlocal n
        n += 1
        return _PLACEHOLDER

    out = _SQL_STRING_LIT.sub(_sub, s)
    out = _EMAIL.sub(_sub, out)
    out = _GUID.sub(_sub, out)
    out = _DATE.sub(_sub, out)
    out = _BIG_NUM.sub(_sub, out)
    return out, n


def looks_like_data_value(s: str) -> bool:
    """True if a bare string smells like a concrete data value (not a name)."""
    s = (s or "").strip()
    if not s:
        return False
    if _EMAIL.search(s) or _GUID.search(s) or _DATE.search(s):
        return True
    # a pure number, or contains a big/decimal number
    if re.fullmatch(r"[+-]?\d+(?:[,\.]\d+)*", s):
        return True
    if _BIG_NUM.search(s):
        return True
    return False


def sanitize_template(sql_or_dax: str) -> SanitizeResult:
    """Sanitize a query into a shareable TEMPLATE: literals -> {value}.

    A template with any surviving literal is impossible by construction (all are
    replaced), so this always yields ok=True — but records how many values were
    parameterized so callers can see it did real work.
    """
    clean, n = redact_text(str(sql_or_dax or ""))
    return SanitizeResult(ok=True, content=clean, redactions=n,
                          reasons=([f"parameterized {n} literal(s)"] if n else []))


def sanitize_content(content: Any, *, _depth: int = 0) -> SanitizeResult:
    """Recursively sanitize a learning payload for the SHARED tier.

    Rules:
      - any key in _DATA_KEYS is DROPPED wholesale (rows/results/filters/values).
      - string leaves are literal-redacted; a leaf that IS a data value drops the
        whole entry (returns ok=False upward if it can't be safely kept).
      - dicts/lists recurse; safe structure is preserved.
    """
    reasons: list[str] = []
    total_redactions = 0

    if _depth > 8:
        return SanitizeResult(ok=False, content=None, reasons=["too deep"])

    if isinstance(content, str):
        if looks_like_data_value(content):
            return SanitizeResult(ok=False, content=None, redactions=1,
                                  reasons=["string is a data value"])
        clean, n = redact_text(content)
        return SanitizeResult(ok=True, content=clean, redactions=n)

    if isinstance(content, (int, float, bool)):
        # bare scalars are data values, not structure -> drop
        return SanitizeResult(ok=False, content=None, redactions=1,
                              reasons=["bare scalar dropped"])

    if isinstance(content, dict):
        out: dict = {}
        for k, v in content.items():
            key = str(k).lower()
            if key in _DATA_KEYS:
                total_redactions += 1
                reasons.append(f"dropped data key '{k}'")
                continue
            # template-ish keys: parameterize instead of drop
            if key in {"template", "dax_template", "query_template"} and isinstance(v, str):
                r = sanitize_template(v)
                out[k] = r.content
                total_redactions += r.redactions
                continue
            r = sanitize_content(v, _depth=_depth + 1)
            total_redactions += r.redactions
            reasons.extend(r.reasons)
            if r.ok and r.content not in (None, "", [], {}):
                out[k] = r.content
        return SanitizeResult(ok=bool(out), content=out, redactions=total_redactions, reasons=reasons)

    if isinstance(content, (list, tuple)):
        out_list = []
        for item in content:
            r = sanitize_content(item, _depth=_depth + 1)
            total_redactions += r.redactions
            reasons.extend(r.reasons)
            if r.ok and r.content not in (None, "", [], {}):
                out_list.append(r.content)
        return SanitizeResult(ok=bool(out_list), content=out_list, redactions=total_redactions, reasons=reasons)

    # unknown type -> drop, be safe
    return SanitizeResult(ok=False, content=None, reasons=[f"dropped {type(content).__name__}"])
