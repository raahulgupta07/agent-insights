"""Context compaction (GCC / OpenDerisk pattern, native).

Operates on the ASSEMBLED planner `instructions` string (the concatenation of
`### ...` context blocks that agent_v2 appends each rebuild). Three deterministic
moves, all gated on HYBRID_CONTEXT_COMPACT, all fail-soft:

  EDIT       drop lowest-priority `### ` sections until under a token budget
  AWARENESS  append a "### Context budget" line so the model self-manages
  COMPRESS   (sub-flag) summarize dropped text to a digest; MVP = truncate

Default-OFF -> `compact()` returns the input unchanged. Never raises.

The in-loop path (`compact`) is SYNCHRONOUS, LLM-free and cheap (runs ~2x per
planner iteration). The async `maybe_compress` is kept available for future
wiring of the opt-in LLM digest but is not called in the hot loop.
"""

from __future__ import annotations

import logging
import os
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# Fallback budget when the model exposes no context window, and a hard floor so
# we never compact a session down to something unusable.
_FALLBACK_BUDGET = 24000
_MIN_BUDGET = 4000
_DEFAULT_RATIO = 0.75

# Lowest-priority (dropped FIRST) -> higher-priority (dropped LAST). Each entry
# is a case-insensitive substring matched against a section's FIRST line. Any
# section whose first line matches NONE of these is CORE and never dropped
# (schemas/instructions/messages/semantic/metrics/skills/studio/etc.). The
# matched header strings (from the section renderers):
#   "## PROVEN APPROACHES (code-memory)"      -> code_bank
#   "### Remembered notes"                    -> agent_memory
#   "### Company definitions"                 -> docs
#   "### How tables join"                     -> join_graph
#   "## CORRELATION GRAPH (approved)"         -> brain_graph
#   "## PROVEN QUERIES (reasoning-cache)"     -> brain proven queries
_DROP_ORDER = [
    "proven approaches",       # code_bank (PROVEN APPROACHES)
    "remembered notes",        # agent_memory
    "company definitions",     # docs
    "how tables join",         # join_graph
    "correlation",             # brain_graph (CORRELATION GRAPH header)
    "proven sql",              # brain proven block (alt phrasing, if present)
    "proven queries",          # brain proven queries (reasoning-cache)
]

# Truncate length for the deterministic COMPRESS digest (no-LLM path).
_DIGEST_CHARS = 600

# Marker that begins the AWARENESS block (always appended LAST). Used to strip a
# prior awareness block so `compact()` is IDEMPOTENT — agent_v2 reuses the same
# `instructions` var across knowledge-harness loop steps, so a non-idempotent
# compact would stack awareness lines + inflate the measured token count.
_AWARENESS_MARKER = "### Context budget"


def _enabled() -> bool:
    try:
        from app.settings.hybrid_flags import flags
        return bool(flags.CONTEXT_COMPACT)
    except Exception:
        return False


def _llm_enabled() -> bool:
    try:
        from app.settings.hybrid_flags import flags
        return bool(flags.CONTEXT_COMPACT_LLM)
    except Exception:
        return False


def _count(text: str, model_id: Optional[str] = None) -> int:
    """Token count, fail-soft to a char/4 estimate."""
    try:
        from app.ai.utils.token_counter import count_tokens
        return count_tokens(text or "", model_id)
    except Exception:
        return max(0, (len(text or "") + 3) // 4)


def _budget_tokens(model) -> int:
    """Soft token budget = context window * ratio, floored. Falls back to a
    constant when the model exposes no window. Never raises."""
    try:
        window = getattr(model, "context_window_tokens", None)
    except Exception:
        window = None
    ratio = _DEFAULT_RATIO
    try:
        raw = os.environ.get("HYBRID_CONTEXT_COMPACT_RATIO")
        if raw is not None:
            ratio = float(raw)
    except Exception:
        ratio = _DEFAULT_RATIO
    if not ratio or ratio <= 0:
        ratio = _DEFAULT_RATIO
    try:
        if window and int(window) > 0:
            budget = int(int(window) * ratio)
        else:
            budget = _FALLBACK_BUDGET
    except Exception:
        budget = _FALLBACK_BUDGET
    return max(_MIN_BUDGET, budget)


def _drop_rank(first_line_lower: str) -> Optional[int]:
    """Return the drop-priority of a section's first line, or None if it is a
    core (never-droppable) section. Lower rank == dropped first."""
    if not first_line_lower:
        return None
    for rank, needle in enumerate(_DROP_ORDER):
        if needle in first_line_lower:
            return rank
    return None


def _split_sections(instructions: str) -> List[str]:
    """Split the assembled instructions into blocks on the `"\\n\\n"` delimiter
    that agent_v2 uses to join context sections. Index 0 (the base
    instructions / leading text) is preserved as-is and is NEVER droppable.
    Returns a list of raw block strings. Never raises."""
    if not instructions:
        return []
    try:
        return instructions.split("\n\n")
    except Exception:
        return [instructions]


def _first_line_lower(block: str) -> str:
    try:
        return (block.splitlines()[0] if block else "").strip().lower()
    except Exception:
        return ""


def edit_to_budget(
    instructions: str,
    *,
    used_tokens: int,
    budget: int,
    model=None,
) -> Tuple[str, List[str]]:
    """EDIT: if over budget, drop droppable sections in `_DROP_ORDER` (lowest
    priority first) one at a time, re-measuring, until under budget. Never
    drops the base block (index 0) or any unmatched/core section. Returns
    `(new_instructions, dropped_first_lines)`. Never raises."""
    try:
        if not instructions or used_tokens <= budget:
            return instructions, []

        model_id = getattr(model, "model_id", None) if model is not None else None
        blocks = _split_sections(instructions)
        if len(blocks) <= 1:
            return instructions, []

        # Build a list of (drop_rank, index) for droppable blocks (skip index 0).
        droppable: List[Tuple[int, int]] = []
        for idx in range(1, len(blocks)):
            rank = _drop_rank(_first_line_lower(blocks[idx]))
            if rank is not None:
                droppable.append((rank, idx))
        # Lowest rank first; stable on original order for equal ranks.
        droppable.sort(key=lambda t: (t[0], t[1]))

        if not droppable:
            return instructions, []

        removed_idx = set()
        dropped_headers: List[str] = []
        for _rank, idx in droppable:
            removed_idx.add(idx)
            dropped_headers.append(_first_line_lower(blocks[idx]) or "(section)")
            kept = [b for i, b in enumerate(blocks) if i not in removed_idx]
            candidate = "\n\n".join(kept)
            if _count(candidate, model_id) <= budget:
                return candidate, dropped_headers

        # Still over budget after dropping everything droppable -> return the
        # maximally-trimmed result (COMPRESS would run next if its sub-flag on).
        kept = [b for i, b in enumerate(blocks) if i not in removed_idx]
        return "\n\n".join(kept), dropped_headers
    except Exception as exc:  # never break the loop
        logger.debug("context compaction edit_to_budget failed: %s", exc)
        return instructions, []


def _strip_awareness(instructions: str) -> str:
    """Remove a previously-appended AWARENESS block so compact() is idempotent.
    The block is always appended LAST behind a `\\n\\n` separator, so cut from the
    last marker occurrence onward. Never raises."""
    try:
        if not instructions or _AWARENESS_MARKER not in instructions:
            return instructions
        marker = "\n\n" + _AWARENESS_MARKER
        cut = instructions.rfind(marker)
        if cut != -1:
            return instructions[:cut].rstrip()
        # marker at very start (no leading content) -> drop the whole block
        if instructions.lstrip().startswith(_AWARENESS_MARKER):
            return ""
        return instructions
    except Exception:
        return instructions


def awareness_line(used_tokens: int, budget: int) -> str:
    """AWARENESS: a small self-management hint appended to the instructions.
    Empty string when the budget is unknown/zero."""
    try:
        if not budget or budget <= 0:
            return ""
        pct = int((used_tokens / budget) * 100) if budget else 0
        return (
            "### Context budget\n"
            f"Using ~{used_tokens} of ~{budget} context tokens ({pct}%). "
            "Be concise; reuse recalled facts and prior results instead of "
            "re-deriving."
        )
    except Exception:
        return ""


def _truncate_digest(dropped_text: str) -> str:
    """Deterministic COMPRESS fallback: head-truncate the dropped text."""
    try:
        text = (dropped_text or "").strip()
        if len(text) <= _DIGEST_CHARS:
            return text
        return text[:_DIGEST_CHARS].rstrip() + " …"
    except Exception:
        return ""


async def maybe_compress(dropped_text: str, *, model=None, db=None) -> str:
    """COMPRESS (opt-in): summarize dropped/old text into a one-line digest.

    When `CONTEXT_COMPACT_LLM` is on and the text is large, attempt ONE LLM
    one-shot summary; on ANY failure or when the sub-flag is off, fall back to
    the deterministic head-truncate. Never raises.

    NOTE: kept available for future wiring; the in-loop `compact()` path does
    NOT call this (it must stay synchronous/cheap). The repo's one-shot LLM
    client pattern lives behind per-org provider config + an async client; to
    avoid a brittle, untested call from a pure helper, the LLM digest path is
    intentionally a TODO for MVP and we return the deterministic truncate. The
    sub-flag defaulting OFF makes this acceptable.
    """
    try:
        if not _llm_enabled():
            return _truncate_digest(dropped_text)
        # TODO(compress-llm): wire a single one-shot LLM summarization here,
        # mirroring app.ai.brain.* distill helpers (per-org client, never raise).
        # Until then, even with the sub-flag on we return the safe truncate.
        return _truncate_digest(dropped_text)
    except Exception:
        return _truncate_digest(dropped_text)


def compact(instructions: str, *, model=None) -> Tuple[str, dict]:
    """Single deterministic entry point used by agent_v2 (synchronous, no LLM,
    no awaiting). EDIT (drop low-priority sections to budget) + AWARENESS
    (append the budget hint). COMPRESS is NOT run here.

    Returns `(new_instructions, meta)`. On any error or when the flag is off,
    returns `(instructions, {})` — NEVER breaks the planner loop."""
    try:
        if not _enabled():
            return instructions, {}
        if not instructions:
            return instructions, {}

        # Idempotency: drop any awareness block from a prior compact() pass so
        # re-running on the same `instructions` (loop reuse) neither stacks the
        # hint nor inflates the token count.
        instructions = _strip_awareness(instructions)

        model_id = getattr(model, "model_id", None) if model is not None else None
        used = _count(instructions, model_id)
        budget = _budget_tokens(model)

        edited, dropped = edit_to_budget(
            instructions, used_tokens=used, budget=budget, model=model
        )
        used2 = _count(edited, model_id)

        line = awareness_line(used2, budget)
        if line:
            edited = (edited + "\n\n" + line) if edited else line

        return edited, {
            "used_before": used,
            "used_after": used2,
            "budget": budget,
            "dropped": dropped,
        }
    except Exception as exc:  # never break the loop
        logger.debug("context compaction compact failed: %s", exc)
        return instructions, {}
