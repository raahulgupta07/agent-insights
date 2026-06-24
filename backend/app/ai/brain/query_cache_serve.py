"""
Reasoning-cache serve (Tier-② param-swap fast-path)
===================================================

The fast-path that sits BEFORE the agent loop. Given a question, find an
EXACTLY-matching proven (status='active') query in the reasoning-cache,
re-run its SQL LIVE for fresh numbers, and return a renderable result —
zero-LLM.

Design rules honored:
- Nothing is hardcoded. We re-run the SQL the agent itself proved earlier
  (recalled via ``query_cache_store``) so the numbers are always current.
- Serving is gated by BOTH flags.QUERY_CACHE (the cache is enabled) and
  flags.BRAIN_READ (recall is enabled). Off -> no-op.
- We only serve on an EXACT normalized-question match. Fuzzy matches exist
  for planner context-injection (``render_proven_queries``) but are never
  served blind, since the SQL may not actually answer a merely-similar Q.
- Re-use ``query_cache_store`` helpers (normalize_question / is_read_only /
  recall_proven_queries); never duplicate that logic here.

Like its sibling store module, this is side-effect-light: the public
coroutine swallows its own errors and degrades to ``None`` so the agent loop
never breaks on a cache miss or a bad re-run. ``render_answer_markdown`` is a
pure, dependency-free string builder.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Tuple

from app.settings.hybrid_flags import flags
from app.ai.brain.query_cache_store import (
    normalize_question,
    is_read_only,
    recall_proven_queries,
    _tokens,
    _jaccard,
)

logger = logging.getLogger(__name__)

# Cap rows rendered into the served answer so a huge SELECT can't blow up the
# chat payload. The full row_count is still reported on the ServeResult.
MAX_SERVE_ROWS = 100

# Param-swap (Mode-2) fast-path: how many fuzzy candidates to consider, and the
# STRICT token-Jaccard floor a candidate must clear before we even attempt a
# literal swap. Higher than the store's FUZZY_FLOOR (0.6) because a blind serve
# is far less forgiving than planner context-injection — a wrong served answer
# is worse than a miss.
PARAM_SWAP_FLOOR = 0.8
PARAM_SWAP_LIMIT = 3

# A "literal" differing token we are willing to swap: a number (int/decimal) or
# a simple bare word/value. Quoting in the SQL is handled at substitution time.
_NUMBER_RE = re.compile(r"^\d+(?:\.\d+)?$")


def _q_tokens(norm: str) -> List[str]:
    """Ordered, whitespace-split tokens of a normalized question (no stopword
    drop — order/structure matters here, unlike the Jaccard set in the store)."""
    return [t for t in norm.split(" ") if t]


def _diff_positions(old_toks: List[str], new_toks: List[str]) -> Optional[List[Tuple[str, str]]]:
    """Return aligned (old, new) pairs at positions where the two token lists
    differ, or None if they cannot be aligned 1:1 (different length / structure).

    Strictly positional: the questions must have the SAME number of tokens and
    differ only by value substitutions at matching positions. Any length
    mismatch (an added/removed/reordered word) -> None.
    """
    if len(old_toks) != len(new_toks):
        return None
    diffs: List[Tuple[str, str]] = []
    for o, n in zip(old_toks, new_toks):
        if o != n:
            diffs.append((o, n))
    return diffs


def _is_literal_token(tok: str) -> bool:
    """A differing token we are willing to treat as a swappable literal. We only
    accept a plain number or a single bare alphanumeric value (no spaces, no
    punctuation that would imply structure)."""
    if not tok:
        return False
    if _NUMBER_RE.match(tok):
        return True
    # Bare value: letters/digits/underscore/hyphen only (e.g. a region name).
    return re.match(r"^[\w-]+$", tok) is not None


def _swap_one(sql: str, old: str, new: str) -> Optional[str]:
    """Replace exactly one literal occurrence of ``old`` in ``sql`` with ``new``.

    The old literal must appear VERBATIM exactly once in the SQL. Quoting is
    respected: if it sits inside a single-quoted SQL string ('X'), the new value
    is substituted inside those quotes; a numeric literal is replaced as-is.
    Returns the rewritten SQL, or None on ambiguity (zero or >1 occurrence).
    """
    if old is None or new is None:
        return None

    # Find occurrences of the old literal as a standalone token in the SQL
    # (word boundaries so e.g. "30" in "300" or "north" in "northwest" is not
    # matched). Matching is case-INSENSITIVE because the question is normalized
    # to lowercase while the SQL literal keeps its original case
    # ('North' in SQL vs 'north' token). This covers bare numeric literals and
    # quoted-string contents ('North' -> the inner North matches with
    # boundaries).
    pat = re.compile(r"(?<![\w-])" + re.escape(old) + r"(?![\w-])", re.IGNORECASE)
    matches = pat.findall(sql)
    if len(matches) != 1:
        # 0 -> not present verbatim; >1 -> ambiguous. Both bail.
        return None

    # Transfer the casing of the literal AS IT APPEARS IN THE SQL onto the new
    # value. The question is normalized to lowercase, so the new token is
    # lowercase; the SQL literal keeps its source case (e.g. 'North'). Matching
    # that case preserves SQL string semantics under case-sensitive collations.
    sql_literal = matches[0]
    replacement = _match_case(sql_literal, new)

    # Substitute a literal string (escape backslashes so the replacement is
    # treated verbatim, not as a regex backreference).
    return pat.sub(replacement.replace("\\", "\\\\"), sql, count=1)


def _match_case(template: str, value: str) -> str:
    """Apply the casing style of ``template`` (as found in the SQL) to ``value``
    (the lowercase new token). Handles all-upper, titlecase, and the common
    lowercase/default case; otherwise leaves ``value`` as-is."""
    if not template or not value:
        return value
    if template.isupper():
        return value.upper()
    if template.istitle():
        return value.title()
    if template.islower():
        return value.lower()
    return value


def swap_literals(
    stored_question: str,
    stored_sql: str,
    new_question: str,
) -> Optional[str]:
    """Produce ``stored_sql`` with literal value(s) swapped to match
    ``new_question``, IFF the new question differs from the stored one ONLY by
    swapping concrete literal value(s) (a number or a bare/quoted value).

    Returns the rewritten SQL on a clean, unambiguous swap; otherwise None. This
    helper is pure (no DB, no I/O) and never raises — any ambiguity / structural
    difference / non-read-only result degrades to None.

    Bails to None when:
      * either question normalizes to empty,
      * the questions differ by anything other than value substitutions
        (different words, added/removed tokens, reordering) -> structural diff,
      * there are zero differing tokens (that's an exact match, not a swap),
      * any differing OLD or NEW token is not a simple literal,
      * an old literal is not found VERBATIM exactly once in the SQL
        (absent -> can't map; >1 -> ambiguous),
      * the resulting SQL is no longer read-only.
    """
    try:
        old_norm = normalize_question(stored_question or "")
        new_norm = normalize_question(new_question or "")
        if not old_norm or not new_norm or not stored_sql:
            return None

        old_toks = _q_tokens(old_norm)
        new_toks = _q_tokens(new_norm)

        diffs = _diff_positions(old_toks, new_toks)
        if diffs is None:
            return None              # length / structural mismatch
        if not diffs:
            return None              # identical -> exact path's job, not ours

        # Every differing pair must be a simple literal on BOTH sides.
        for old_v, new_v in diffs:
            if not _is_literal_token(old_v) or not _is_literal_token(new_v):
                return None

        # Apply each swap to the SQL. Each old literal must occur verbatim
        # exactly once (clean 1:1 mapping); otherwise bail.
        swapped = stored_sql
        for old_v, new_v in diffs:
            result = _swap_one(swapped, old_v, new_v)
            if result is None:
                return None
            swapped = result

        # The rewrite must still be a single read-only SELECT/WITH.
        if not is_read_only(swapped):
            return None

        return swapped
    except Exception:  # pure helper must never raise into the fast-path
        return None


@dataclass
class ServeResult:
    """A renderable, freshly-re-run proven-query result."""

    question: str          # normalized matched question
    sql: str               # proven SQL that was re-run
    columns: List[str]
    rows: List[list]       # capped to MAX_SERVE_ROWS
    row_count: int         # total rows returned (pre-cap)
    truncated: bool        # True if row_count > MAX_SERVE_ROWS


async def try_serve_proven_query(
    db: Any,
    *,
    organization_id: str,
    data_source_id: Optional[str],
    question: str,
    run_sql: Callable[[str], Any],   # sync callable(sql) -> pandas.DataFrame
    data_source_ids: Optional[List[str]] = None,
) -> Optional[ServeResult]:
    """Try to answer ``question`` from the reasoning-cache, zero-LLM.

    Returns a ServeResult only when an EXACT proven match exists and its SQL
    re-runs cleanly. ANY gate-off / guard-fail / non-match / error returns
    ``None`` (never raises) so the caller can fall through to the agent loop.

    ``run_sql`` is a SYNCHRONOUS callable taking the SQL string and returning
    a pandas DataFrame (or any duck-typed object exposing ``.columns`` and
    ``.values``). It is invoked directly (not awaited).

    ``data_source_ids`` (multi-source set, optional): the FULL pinned source set.
    Forwarded to ``recall_proven_queries`` so a multi-source Studio matches only
    queries proven for the SAME source set (folded into the hash only when >1).
    None / single-source -> behavior unchanged.
    """
    try:
        # 1. Gate: both the cache and brain-recall must be enabled.
        if not (flags.QUERY_CACHE and flags.BRAIN_READ):
            return None

        # 2. Guard: need a db, an org scope, and a non-blank question.
        if db is None or not organization_id or not (question and question.strip()):
            return None

        # 3. Normalize; bail if it collapses to nothing.
        norm = normalize_question(question)
        if not norm:
            return None

        # 4. Recall the best proven queries for this question (fuzzy, best-first).
        #    A small limit covers both the exact-match and the param-swap path.
        items = await recall_proven_queries(
            db,
            organization_id=organization_id,
            data_source_id=data_source_id,
            question=question,
            limit=PARAM_SWAP_LIMIT,
            data_source_ids=data_source_ids,
        )
        if not items:
            return None

        # 5. EXACT-MATCH path (unchanged): serve only when a stored normalized
        #    question is identical. recall returns exact-hash matches first, so
        #    the exact match (if any) is items[0].
        top = items[0]
        if top.get("question") == norm:
            sql = top.get("sql") or ""
            if not is_read_only(sql):
                return None
            return _serve_sql(run_sql, sql=sql, served_question=norm)

        # 6. PARAM-SWAP path (Mode-2, strictly additive — only on exact-miss):
        #    take the best fuzzy candidate whose question clears the STRICT
        #    PARAM_SWAP_FLOOR AND whose proven SQL can be literal-swapped to
        #    match the new question. Conservative: first clean hit wins.
        qtokens = _tokens(norm)
        for it in items:
            cand_q = it.get("question") or ""
            cand_sql = it.get("sql") or ""
            if not cand_q or not cand_sql:
                continue
            # Strict similarity gate (Jaccard on stopword-stripped tokens).
            if _jaccard(qtokens, _tokens(cand_q)) < PARAM_SWAP_FLOOR:
                continue
            swapped = swap_literals(cand_q, cand_sql, norm)
            if not swapped:
                continue
            # Re-confirm read-only on the swapped SQL before any live run.
            if not is_read_only(swapped):
                continue
            return _serve_sql(run_sql, sql=swapped, served_question=norm)

        return None
    except Exception as e:  # never propagate from the fast-path
        logger.warning("query_cache serve failed: %s", e)
        return None


def _serve_sql(
    run_sql: Callable[[str], Any],
    *,
    sql: str,
    served_question: str,
) -> Optional[ServeResult]:
    """Run ``sql`` LIVE and build a ServeResult, degrading to None on any
    bad re-run / unexpected return type. Shared by the exact and param-swap
    paths so they apply identical row-capping + DataFrame duck-typing."""
    # Execute LIVE for fresh numbers (sync call).
    try:
        df = run_sql(sql)
    except Exception as e:  # bad re-run -> fall through to the agent loop
        logger.warning("query_cache serve re-run failed: %s", e)
        return None

    # Convert the DataFrame defensively. Duck-type on .columns/.values so we
    # degrade rather than raise on an unexpected return type.
    columns_attr = getattr(df, "columns", None)
    values_attr = getattr(df, "values", None)
    if columns_attr is None or values_attr is None:
        return None

    columns = [str(c) for c in columns_attr]
    all_rows = values_attr.tolist()  # values left as-is; renderer str()s them
    row_count = len(all_rows)
    rows = all_rows[:MAX_SERVE_ROWS]
    truncated = row_count > MAX_SERVE_ROWS

    return ServeResult(
        question=served_question,
        sql=sql,
        columns=columns,
        rows=rows,
        row_count=row_count,
        truncated=truncated,
    )


def render_answer_markdown(result: ServeResult) -> str:
    """Render a ServeResult as a chat-ready markdown answer.

    Pure string building (no deps). Produces:
    - a one-line italicized cache note (served from the reasoning-cache by
      re-running proven SQL live),
    - a GitHub-flavored markdown table (or a graceful no-rows message),
    - a trailing "showing first N of M" line if truncated,
    - a fenced ```sql block of the proven SQL under a "Query" caption.
    """
    note = (
        "_Served from the reasoning-cache — proven SQL was re-run live, "
        "so these numbers are fresh._"
    )

    lines: List[str] = [note, ""]

    if not result.columns or not result.rows:
        lines.append("Query returned no rows.")
    else:
        # Header + separator.
        lines.append("| " + " | ".join(result.columns) + " |")
        lines.append("| " + " | ".join("---" for _ in result.columns) + " |")
        # Data rows: str() each cell, escape pipes, collapse newlines.
        for row in result.rows:
            cells = []
            for cell in row:
                text = str(cell).replace("|", "\\|")
                text = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
                cells.append(text)
            lines.append("| " + " | ".join(cells) + " |")

        if result.truncated:
            lines.append("")
            lines.append(
                f"_Showing first {MAX_SERVE_ROWS} of {result.row_count} rows._"
            )

    # Always append the proven SQL for transparency.
    lines.append("")
    lines.append("Query")
    lines.append("```sql")
    lines.append((result.sql or "").strip())
    lines.append("```")

    return "\n".join(lines)
