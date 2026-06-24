"""StudioContextBuilder — injects a Studio's engineered context (hybrid Studios ST7).

When the active report belongs to a Studio (``Report.studio_id`` set) and
``flags.STUDIOS`` is ON, this builder assembles ONE extra context section:

  - voice        : ``Studio.persona`` (the tone / reply-language line)
  - instructions : ACTIVE ``StudioInstruction`` rows (status='active',
                   deleted_at IS NULL) — approved-only; pending never reaches
                   the model
  - examples     : ACTIVE ``StudioExample`` rows (status='active') rendered as
                   Q -> answer(/sql) few-shot pairs — approved-only

It deliberately does NOT inject skills or grounded schemas — those are already
produced by SkillContextBuilder and SchemaContextBuilder respectively. This
builder's section ADDS voice + instructions + examples only.

Mirrors SkillContextBuilder: an async ``build()`` that no-ops (returns an empty
StudioSection) when the flag is OFF or the report has no studio_id, and that
never raises — any error degrades to an empty section so a Studio mishap can
never break the chat. Flag-OFF / non-studio path is byte-identical to upstream.
"""
from __future__ import annotations
import logging
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.settings.hybrid_flags import flags
from app.ai.context.sections.studio import (
    StudioSection,
    StudioInstructionItem,
    StudioExampleItem,
)

logger = logging.getLogger(__name__)

# Defensive caps so a runaway Studio can't bloat the planner prompt.
_MAX_INSTRUCTIONS = 25
_MAX_EXAMPLES = 10
# Upper bound on rows pulled before query-relevance ranking selects _MAX_EXAMPLES.
_EXAMPLE_POOL = 100


def _rank_examples(query: str, rows, k: int):
    """Pick the K most query-relevant examples (token-Jaccard over question +
    answer) instead of the oldest K. Cf. arXiv:2605.22502 — inject the relevant
    few-shots, not all. Any failure -> first K (original order)."""
    try:
        from app.ai.brain.query_cache_store import normalize_question, _tokens, _jaccard
        q_tokens = _tokens(normalize_question(query))
        if not q_tokens:
            return rows[:k]
        scored = []
        for r in rows:
            text = " ".join([
                (getattr(r, "question", None) or ""),
                (getattr(r, "answer", None) or ""),
            ])
            scored.append((_jaccard(q_tokens, _tokens(normalize_question(text))), r))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:k]]
    except Exception:
        return rows[:k]


class StudioContextBuilder:
    def __init__(
        self,
        db: AsyncSession,
        organization,
        user=None,
        data_source_ids: Optional[List[str]] = None,
        report=None,
    ):
        self.db = db
        self.organization = organization
        self.user = user
        self.data_source_ids = data_source_ids
        # hybrid Studios ST7: the active report carries a nullable studio_id.
        # When set (and flag ON) we inject the Studio's engineered context.
        self.report = report

    async def build(self, query: Optional[str] = None) -> StudioSection:
        # Flag OFF -> empty section, no DB hit (byte-identical to upstream).
        if not flags.STUDIOS:
            return StudioSection()

        studio_id = getattr(self.report, "studio_id", None) if self.report else None
        # No studio -> nothing to inject.
        if not studio_id:
            return StudioSection()

        studio_id = str(studio_id)

        voice: Optional[str] = None
        instructions: List[StudioInstructionItem] = []
        examples: List[StudioExampleItem] = []

        # --- voice (Studio.persona) -----------------------------------------
        try:
            from app.models.studio import Studio

            studio = (
                await self.db.execute(
                    select(Studio).where(
                        Studio.id == studio_id,
                        Studio.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if studio is not None:
                persona = getattr(studio, "persona", None)
                if persona and persona.strip():
                    voice = persona.strip()
        except Exception as e:  # never break the loop on studio read
            logger.warning("studio voice load failed: %s", e)

        # --- ACTIVE instructions (approved-only) ----------------------------
        try:
            from app.models.studio import StudioInstruction

            rows = (
                await self.db.execute(
                    select(StudioInstruction)
                    .where(
                        StudioInstruction.studio_id == studio_id,
                        StudioInstruction.status == "active",
                        StudioInstruction.deleted_at.is_(None),
                    )
                    .order_by(StudioInstruction.created_at.asc())
                    .limit(_MAX_INSTRUCTIONS)
                )
            ).scalars().all()
            for r in rows:
                content = (getattr(r, "content", None) or "").strip()
                if content:
                    instructions.append(StudioInstructionItem(content=content))
        except Exception as e:  # never break the loop on instructions read
            logger.warning("studio instructions load failed: %s", e)

        # --- ACTIVE golden examples (approved-only) -------------------------
        try:
            from app.models.studio import StudioExample

            rows = (
                await self.db.execute(
                    select(StudioExample)
                    .where(
                        StudioExample.studio_id == studio_id,
                        StudioExample.status == "active",
                        StudioExample.deleted_at.is_(None),
                    )
                    .order_by(StudioExample.created_at.asc())
                    .limit(_EXAMPLE_POOL)
                )
            ).scalars().all()
            rows = list(rows)
            # When a query is present and there are more than the cap, keep the
            # most relevant _MAX_EXAMPLES few-shots; otherwise the first cap.
            if query and query.strip() and len(rows) > _MAX_EXAMPLES:
                rows = _rank_examples(query, rows, _MAX_EXAMPLES)
            else:
                rows = rows[:_MAX_EXAMPLES]
            for r in rows:
                q = (getattr(r, "question", None) or "").strip()
                a = (getattr(r, "answer", None) or "").strip()
                if not (q and a):
                    continue
                sql = (getattr(r, "sql", None) or "").strip() or None
                examples.append(StudioExampleItem(question=q, answer=a, sql=sql))
        except Exception as e:  # never break the loop on examples read
            logger.warning("studio examples load failed: %s", e)

        return StudioSection(
            voice=voice,
            instructions=instructions,
            examples=examples,
        )
