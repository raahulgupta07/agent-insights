"""Route ingest/profile-time DATA-QUALITY GOTCHAS into GLOBAL Shared Memory.

dash-inspired ``data_quality_notes``: a trap detected once at ingest (a text
column that is really numeric, a single-value column, near-duplicate category
spellings) is written to the GLOBAL tier of Shared Memory so EVERY agent in the
org avoids it — "don't SUM this text column without casting", "these two labels
are the same group".

STRUCTURE ONLY travels: table name, column name, and the RULE (a ``fix_shape``).
Never a literal data value — ``capture_global`` sanitizes anyway, but we keep it
clean at the source. Flag-gated (``flags.GOTCHA_MEMORY``), fail-soft: any error
(or flag OFF) returns 0 and never touches the ingest request.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# issue-vocabulary (from data_validator + post_ingest.scan_dataframe_quality)
# -> (memory kind, one-line rule). Only concrete, SAFE-to-share traps are here;
# transient/statistical noise (outliers, null-spike %) is intentionally omitted.
_MISTAKE = "mistake"
_MEANING = "meaning"

# typing traps -> a SUM/AVG over the raw text silently breaks -> cast first.
_TYPING_ISSUES = {"mixed_type", "type_coercion"}
# column-semantics the agent should know before grouping/filtering.
_SEMANTIC_ISSUES = {"category_near_duplicate", "near_constant", "all_null"}


def _rule_for(issue: str, table: str, column: str) -> Dict[str, str] | None:
    """Translate one finding into (kind, error_class, fix_shape). ``None`` when
    the issue isn't one we want to teach org-wide."""
    col = column or "a column"
    if issue in _TYPING_ISSUES:
        return {
            "kind": _MISTAKE,
            "error_class": "numeric-looking values stored as text",
            "fix_shape": (
                f"column {col!r} in table {table!r} holds numeric values stored "
                f"as text — CAST it to a number before SUM/AVG/comparison, or the "
                f"aggregate breaks or sorts lexically"
            ),
        }
    if issue == "category_near_duplicate":
        return {
            "kind": _MEANING,
            "error_class": "near-duplicate category spellings",
            "fix_shape": (
                f"column {col!r} in table {table!r} has near-duplicate category "
                f"spellings that split one real group — normalise (trim/case) "
                f"before GROUP BY or the group scatters and under-counts"
            ),
        }
    if issue == "near_constant":
        return {
            "kind": _MEANING,
            "error_class": "single-value column",
            "fix_shape": (
                f"column {col!r} in table {table!r} has a single distinct value — "
                f"it carries no signal; don't GROUP BY / filter on it expecting variation"
            ),
        }
    if issue == "all_null":
        return {
            "kind": _MEANING,
            "error_class": "empty column",
            "fix_shape": (
                f"column {col!r} in table {table!r} is entirely null — it carries "
                f"no data; don't aggregate or filter on it"
            ),
        }
    return None


def gotchas_from_quality_summary(summary: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Translate ``run_data_quality_scan``-style summary
    (``[{table, findings:[{column, issue, ...}]}]``) into a compact gotcha list
    ``[{table, column, issue, kind, error_class, fix_shape}]``. Never raises."""
    out: List[Dict[str, str]] = []
    seen: set = set()
    try:
        for entry in summary or []:
            table = str((entry or {}).get("table") or "")
            for f in (entry or {}).get("findings") or []:
                issue = str((f or {}).get("issue") or "")
                column = str((f or {}).get("column") or "")
                rule = _rule_for(issue, table, column)
                if rule is None:
                    continue
                key = (table, column, issue)
                if key in seen:
                    continue
                seen.add(key)
                out.append({"table": table, "column": column, "issue": issue, **rule})
    except Exception as e:  # noqa: BLE001 — translation never blocks ingest
        logger.debug("gotchas_from_quality_summary failed: %s", e)
    return out


async def route_gotchas_to_global(
    db,
    *,
    organization_id: str,
    gotchas: List[Dict[str, str]],
) -> int:
    """Write each gotcha as a GLOBAL Shared-Memory fact (read by every agent).

    Flag-gated (``flags.GOTCHA_MEMORY``) + fail-soft. Returns the number of facts
    written. ``kind='mistake'`` for typing traps, ``kind='meaning'`` for column
    semantics. STRUCTURE only — table/column names + the rule, never a data value.
    """
    written = 0
    try:
        from app.settings.hybrid_flags import flags

        if not flags.GOTCHA_MEMORY or not gotchas:
            return 0

        from app.services.knowledge.capture import capture_global

        for g in gotchas:
            try:
                kind = str(g.get("kind") or _MISTAKE)
                table = str(g.get("table") or "")
                column = str(g.get("column") or "")
                fix_shape = str(g.get("fix_shape") or "").strip()
                if not fix_shape:
                    continue
                error_class = str(g.get("error_class") or g.get("issue") or "data gotcha")
                content: Dict[str, Any] = {
                    "kind": kind,
                    "error_class": error_class[:200],
                    "fix_shape": fix_shape[:500],
                    "table": table[:200],
                    "column": column[:200],
                }
                title = f"{error_class}: {column or table}"[:120]
                written += await capture_global(
                    db,
                    organization_id=organization_id,
                    kind=kind,
                    title=title,
                    content=content,
                    text=fix_shape,
                    verified=True,
                )
            except Exception as e:  # noqa: BLE001 — one bad gotcha never kills the rest
                logger.debug("route_gotchas_to_global skipped a gotcha: %s", e)
                continue
    except Exception as e:  # noqa: BLE001
        logger.warning("route_gotchas_to_global failed: %s", e)
    return written
