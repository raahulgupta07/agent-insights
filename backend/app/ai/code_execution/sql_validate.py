"""Static SQL validation for the code-execution retry loop (flags.SQL_VALIDATE).

Fail-soft, dry-plan-style validation that mirrors WrenAI's validate-and-regenerate
loop: when a generated-code run fails, we statically inspect the SQL it ran and feed
a STRUCTURED diagnosis back to the coder so the next regeneration produces good SQL
instead of the same "An error occurred". Advisory-on-retry only — this module NEVER
blocks execution and NEVER raises.

Complements the runtime string guard `_enforce_readonly_query` in code_execution.py:
that is a regex string check on the live query; this is a structural parse-tree check
that also surfaces a coach-able hint. Both are additive and independent.

sqlglot is optional. If it is not importable the whole module degrades to a pure
no-op (`validate_sql` always returns (True, None)) so nothing changes when the flag
is on but the dependency is absent.
"""

from __future__ import annotations

from typing import Optional, Tuple

try:  # optional dependency — degrade to no-op if unavailable
    import sqlglot
    from sqlglot import expressions as _exp
except Exception:  # pragma: no cover - exercised only when sqlglot missing
    sqlglot = None
    _exp = None


# Structural write/DDL expression types → the operation word we tell the model to drop.
# Keyed by sqlglot expression class name so we don't depend on a specific sqlglot version
# exposing every class at import time.
_WRITE_OP_BY_CLASSNAME = {
    "Insert": "INSERT",
    "Update": "UPDATE",
    "Delete": "DELETE",
    "Drop": "DROP",
    "Alter": "ALTER",
    "AlterTable": "ALTER",
    "Create": "CREATE",
    "TruncateTable": "TRUNCATE",
    "Truncate": "TRUNCATE",
    "Merge": "MERGE",
}


def _short(reason: str, limit: int = 160) -> str:
    reason = " ".join(str(reason).split())
    return reason if len(reason) <= limit else reason[: limit - 1] + "…"


def validate_sql(sql: str) -> Tuple[bool, Optional[str]]:
    """Statically validate a single SQL string.

    Returns (ok, hint):
      - ok=False + hint → a hard problem (unparseable, or a write/DDL statement).
      - ok=True  + hint → an advisory nudge (e.g. SELECT * without LIMIT); never blocks.
      - ok=True  + None → looks fine, or validation could not run (fail-soft allow).

    Fail-soft: any parser error, uncertainty, or missing sqlglot → (True, None).
    NEVER raises.
    """
    if sqlglot is None:
        return (True, None)
    if not isinstance(sql, str) or not sql.strip():
        return (True, None)

    try:
        try:
            parsed = sqlglot.parse_one(sql, read="duckdb")
        except Exception:
            # Retry dialect-agnostic before giving a parse-fail verdict.
            parsed = sqlglot.parse_one(sql)
    except Exception as e:  # (a) unparseable
        return (
            False,
            f"SQL did not parse: {_short(str(e) or type(e).__name__)}. "
            "Rewrite as a single valid SELECT.",
        )

    if parsed is None:
        return (True, None)

    try:
        # (b) read-only structural check: reject a write/DDL top-level statement.
        op = _WRITE_OP_BY_CLASSNAME.get(type(parsed).__name__)
        if op:
            return (
                False,
                f"Only read-only SELECT queries are allowed; remove the {op}.",
            )

        # (c) shape nudge (advisory, still ok=True): a bare SELECT * with no LIMIT
        # and no aggregation/GROUP BY tends to over-fetch. Mild — never blocks.
        if isinstance(parsed, _exp.Select):
            selects_star = any(isinstance(e, _exp.Star) for e in parsed.expressions)
            has_limit = parsed.args.get("limit") is not None
            has_group = parsed.args.get("group") is not None
            has_agg = bool(list(parsed.find_all(_exp.AggFunc)))
            if selects_star and not has_limit and not has_group and not has_agg:
                return (
                    True,
                    "Hint: avoid SELECT * without LIMIT — select only needed columns "
                    "or add LIMIT/GROUP BY.",
                )
    except Exception:
        return (True, None)

    return (True, None)


def build_sql_error_feedback(sql: str, error: Optional[str]) -> Optional[str]:
    """Compose a short structured hint to append to the coder's corrective feedback.

    Names the offending SQL (truncated) + the validation reason + a one-line fix.
    Returns None when there is nothing useful to say (or on any failure).
    NEVER raises.
    """
    try:
        if not isinstance(sql, str) or not sql.strip():
            return None
        ok, hint = validate_sql(sql)
        if hint is None:
            return None
        snippet = " ".join(sql.strip().split())
        if len(snippet) > 200:
            snippet = snippet[:199] + "…"
        prefix = "SQL check failed" if not ok else "SQL check"
        return (
            f"{prefix} for the query you ran: \"{snippet}\". "
            f"{hint} Regenerate the code to produce a single valid read-only SELECT."
        )
    except Exception:
        return None
