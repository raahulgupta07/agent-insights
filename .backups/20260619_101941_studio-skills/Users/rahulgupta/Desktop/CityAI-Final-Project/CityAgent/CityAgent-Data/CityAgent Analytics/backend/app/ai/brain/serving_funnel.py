"""
Serving funnel (cheap-tier fast-path BEFORE the agent loop)
===========================================================

A single ordered entry point that tries the cheap, zero-LLM serving tiers in
priority order and only falls through to the (expensive) agent loop when none
of them can answer the question:

    ① answer-cache      — PG-resident final-answer cache, served verbatim (LIVE)
    ② reasoning-cache   — param-swap serve of a proven SQL re-run live (LIVE)
    ③ materialized      — analytics.* materialized-view direct read (LIVE)

Design rules honored (mirrors the sibling brain modules):
- Zero-LLM. Every tier is a cheap lookup / live SQL re-run, never a model call.
- Never raises. Each tier call is wrapped in its own try/except so a single
  broken tier degrades to "skip this tier" rather than breaking the request.
  The function as a whole always returns a FunnelOutcome.
- Flag-gated. Tier ① is gated on flags.ANSWER_CACHE; Tier ③ on
  flags.FEDERATION or flags.DUAL_SCHEMA. Tier ② self-gates inside
  ``try_serve_proven_query`` (flags.QUERY_CACHE + flags.BRAIN_READ) so it
  needs no extra flag check here. When a tier's flag is OFF the branch is
  skipped cleanly and the funnel falls through to the next tier / agent loop.

Nothing heavy is imported here (no agent_v2): this module is meant to be cheap
to import and cheap to call on every request.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Optional, Tuple

from app.settings.hybrid_flags import flags
from app.ai.brain.query_cache_serve import (
    try_serve_proven_query,
    render_answer_markdown,
)

logger = logging.getLogger(__name__)

# Tier identifiers. These string values are ALSO what gets persisted in
# ``Completion.served_by`` so downstream analytics can attribute a served
# answer to the tier that produced it. Keep them stable.
TIER_ANSWER_CACHE = "answer_cache"
TIER_REASONING_CACHE = "reasoning_cache"
TIER_MATERIALIZED = "materialized"
TIER_AGENT_LOOP = "agent_loop"


@dataclass
class FunnelOutcome:
    """Result of running the serving funnel.

    ``served`` is True when a cheap tier produced an answer; ``tier`` is then
    the TIER_* constant that produced it. When no cheap tier serves, the
    outcome is the sentinel ``TIER_AGENT_LOOP`` with no answer, telling the
    caller to fall through to the normal (expensive) agent loop.
    """

    served: bool                 # True if a cheap tier produced an answer
    tier: str                    # one of the TIER_* constants
    answer_md: Optional[str]     # rendered markdown answer when served, else None
    row_count: int               # rows in the served result, else 0


# --------------------------------------------------------------------------- #
# Tier ① — PG-resident final-answer cache
# --------------------------------------------------------------------------- #
async def _try_answer_cache(
    db: Any,
    *,
    organization_id: str,
    data_source_id: Optional[str],
    question: str,
) -> Optional[Tuple[str, int]]:
    """Tier-0 Redis answer-cache lookup.

    Tier-① serve: an exact prior answer for this org + (data source | org-wide)
    is returned verbatim (zero-LLM, no SQL re-run). Backed by the PG-resident
    ``answer_cache`` table (no Redis dependency). Self-gates inside
    ``serve_answer_cache`` on flags.ANSWER_CACHE; returns ``(answer_md,
    row_count)`` on a hit, or ``None`` on a miss / disabled / error.
    """
    from app.ai.brain.answer_cache import serve_answer_cache

    return await serve_answer_cache(
        db,
        organization_id=organization_id,
        data_source_id=data_source_id,
        question=question,
    )


# --------------------------------------------------------------------------- #
# Tier ③ — analytics.* materialized-view direct read
# --------------------------------------------------------------------------- #
def _render_matview_markdown(name: str, columns: list, rows: list, row_count: int) -> str:
    """Render a served matview as a chat-ready markdown answer (pure, no deps).

    Mirrors the reasoning-cache renderer's table shape: a one-line note, a
    GitHub-flavored markdown table, and a truncation line when capped.
    """
    from app.ai.code_execution.analytics_engine import MATVIEW_MAX_ROWS

    note = (
        f"_Served from the precomputed materialized view `analytics.{name}` "
        "(no SQL planning needed)._"
    )
    lines = [note, ""]
    if not columns or not rows:
        lines.append("The materialized view returned no rows.")
    else:
        lines.append("| " + " | ".join(str(c) for c in columns) + " |")
        lines.append("| " + " | ".join("---" for _ in columns) + " |")
        for row in rows:
            cells = []
            for cell in row:
                text = str(cell).replace("|", "\\|")
                text = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
                cells.append(text)
            lines.append("| " + " | ".join(cells) + " |")
        if row_count > MATVIEW_MAX_ROWS:
            lines.append("")
            lines.append(f"_Showing first {MATVIEW_MAX_ROWS} of {row_count} rows._")
    return "\n".join(lines)


async def _try_materialized(
    db: Any,
    *,
    organization_id: str,
    data_source_id: Optional[str],
    question: str,
    run_sql: Callable[[str], Any],
) -> Optional[Tuple[str, int]]:
    """Materialized-view (analytics.*) serve.

    Conservatively matches the question against an existing pre-built
    ``analytics.*`` materialized view (Engineer data asset) and, on a single
    unambiguous match, reads it directly via the read-only analytics engine and
    renders it. Self-gates on flags.DUAL_SCHEMA inside ``serve_matview`` and
    returns ``(answer_md, row_count)`` on a hit, or ``None`` on a miss /
    ambiguous match / disabled / error.

    The matview read is synchronous; it is run off the event loop so the funnel
    stays non-blocking.
    """
    import asyncio

    from app.ai.code_execution.analytics_engine import serve_matview

    served = await asyncio.to_thread(serve_matview, question)
    if served is None:
        return None
    name, columns, rows, row_count = served
    answer_md = _render_matview_markdown(name, columns, rows, row_count)
    return (answer_md, row_count)


async def run_serving_funnel(
    db: Any,
    *,
    organization_id: str,
    data_source_id: Optional[str],
    question: str,
    run_sql: Callable[[str], Any],
) -> FunnelOutcome:
    """Try every cheap serving tier in priority order, then give up.

    Returns the first tier that produces an answer as a served FunnelOutcome.
    If no cheap tier serves, returns the sentinel ``TIER_AGENT_LOOP`` outcome
    (``served=False``) so the caller falls through to the agent loop.

    This is zero-LLM and NEVER raises: each tier call is independently wrapped
    in try/except, so a broken tier degrades to "skip" rather than propagating.

    ``run_sql`` is a SYNCHRONOUS callable taking a SQL string and returning a
    pandas DataFrame (passed straight through to the tiers that re-run SQL).
    """
    # --- Tier ① answer-cache ------------------------------------------------ #
    if flags.ANSWER_CACHE:
        try:
            hit = await _try_answer_cache(
                db,
                organization_id=organization_id,
                data_source_id=data_source_id,
                question=question,
            )
            if hit is not None:
                answer_md, row_count = hit
                logger.debug(
                    "serving_funnel served via %s (rows=%s)",
                    TIER_ANSWER_CACHE,
                    row_count,
                )
                return FunnelOutcome(
                    served=True,
                    tier=TIER_ANSWER_CACHE,
                    answer_md=answer_md,
                    row_count=row_count,
                )
        except Exception as e:  # broken tier -> skip, never raise
            logger.warning("serving_funnel tier %s failed: %s", TIER_ANSWER_CACHE, e)

    # --- Tier ② reasoning-cache (param-swap proven SQL, re-run live) -------- #
    # try_serve_proven_query self-gates on QUERY_CACHE + BRAIN_READ and swallows
    # its own errors; we still wrap defensively so the funnel never raises.
    try:
        result = await try_serve_proven_query(
            db,
            organization_id=organization_id,
            data_source_id=data_source_id,
            question=question,
            run_sql=run_sql,
        )
        if result is not None:
            answer_md = render_answer_markdown(result)
            logger.debug(
                "serving_funnel served via %s (rows=%s)",
                TIER_REASONING_CACHE,
                result.row_count,
            )
            return FunnelOutcome(
                served=True,
                tier=TIER_REASONING_CACHE,
                answer_md=answer_md,
                row_count=result.row_count,
            )
    except Exception as e:  # broken tier -> skip, never raise
        logger.warning("serving_funnel tier %s failed: %s", TIER_REASONING_CACHE, e)

    # --- Tier ③ materialized (analytics.* matviews) ------------------------- #
    if flags.FEDERATION or getattr(flags, "DUAL_SCHEMA", False):
        try:
            hit = await _try_materialized(
                db,
                organization_id=organization_id,
                data_source_id=data_source_id,
                question=question,
                run_sql=run_sql,
            )
            if hit is not None:
                answer_md, row_count = hit
                logger.debug(
                    "serving_funnel served via %s (rows=%s)",
                    TIER_MATERIALIZED,
                    row_count,
                )
                return FunnelOutcome(
                    served=True,
                    tier=TIER_MATERIALIZED,
                    answer_md=answer_md,
                    row_count=row_count,
                )
        except Exception as e:  # broken tier -> skip, never raise
            logger.warning("serving_funnel tier %s failed: %s", TIER_MATERIALIZED, e)

    # --- Default: no cheap tier served -> fall through to the agent loop ---- #
    return FunnelOutcome(
        served=False,
        tier=TIER_AGENT_LOOP,
        answer_md=None,
        row_count=0,
    )
