"""SkillContextBuilder — surfaces the visible SKILLS catalog (L1 progressive disclosure).

Folds the self-service Skills catalog (name + one-line description) into a
ContextHub builder. Gated transitively by flags.SKILLS (list_visible_skills
returns [] when off). Never raises — degrades to an empty section.

L1 surfaces the skills visible to THIS user (personal + org-shared + global,
per the loader's shared visibility rule). When a run ``query`` is present, the
visible set is ranked by similarity to the query and only the top-K most
relevant skills are injected; otherwise the full capped catalog is emitted.

Ranking approach
----------------
The project's established lightweight similarity idiom is the reasoning-cache's
token-Jaccard over normalized text (``app.ai.brain.query_cache_store`` —
``normalize_question`` / ``_tokens`` / ``_jaccard``). We reuse it here rather
than introduce a new embedding provider: OpenRouter is the only sanctioned
LLM/embeddings provider and the codebase ships no embeddings client or persisted
skill-embedding column yet. Each skill is scored by the Jaccard overlap between
the query tokens and the skill's ``name + description`` tokens, ties broken by
the loader's existing order (hit_count desc, then name). A future migration
(owned elsewhere) could add a persisted pgvector embedding column on ``skills``
and swap the scorer for a DB-side ``<=>`` top-K — the selection boundary here is
already isolated for that.

Graceful fallback (never breaks the loop): no query, no visible skills, or any
scoring error -> the previous naive behavior (full capped visible catalog).
"""
from __future__ import annotations
import logging
import os
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.skills.loader import list_visible_skills, get_skill_body
from app.ai.context.sections.skills import SkillsSection, SkillItem

logger = logging.getLogger(__name__)


def _top_k() -> int:
    """Top-K cap for query-relevant skill injection (env-overridable)."""
    try:
        k = int(os.getenv("HYBRID_SKILLS_TOP_K", "8"))
        return k if k > 0 else 8
    except (TypeError, ValueError):
        return 8


def _autoinject_enabled() -> bool:
    """S5.2: auto-inject the top-1 skill's full body when it strongly matches the
    query (skip the load_skill round-trip). Env-gated, default OFF — keeps the
    flag-OFF / no-config path byte-identical to upstream. Truthy = 1/true/yes/on.
    """
    val = (os.getenv("HYBRID_SKILLS_AUTOINJECT", "") or "").strip().lower()
    return val in ("1", "true", "yes", "on")


def _autoinject_floor() -> float:
    """Minimum top-1 Jaccard match score required to auto-inject (env-overridable).

    Default 0.5 — only a strong, unambiguous match inlines its body (token cost).
    """
    try:
        f = float(os.getenv("HYBRID_SKILLS_AUTOINJECT_FLOOR", "0.5"))
        return f if 0.0 < f <= 1.0 else 0.5
    except (TypeError, ValueError):
        return 0.5


def _rank_skills(query: str, skills: List[Dict[str, Any]], k: int) -> List[Dict[str, Any]]:
    """Rank visible skills by similarity to ``query`` and return the top-K.

    Uses the reasoning-cache's token-Jaccard idiom over each skill's
    ``name + description`` vs. the normalized query. Skills with zero overlap
    are still eligible (they fill remaining top-K slots in the loader's order)
    so we never *hide* a skill purely for lacking query keywords — we only
    PREFER the relevant ones. Pure, dependency-light, never raises.
    """
    # Local import keeps this flag-gated path off the hot import graph and
    # reuses the single source of truth for normalization/tokenization.
    from app.ai.brain.query_cache_store import normalize_question, _tokens, _jaccard

    q_tokens = _tokens(normalize_question(query))
    if not q_tokens:
        return skills[:k]

    scored: List[tuple] = []
    for idx, s in enumerate(skills):
        text = f"{s.get('name', '')} {s.get('description', '')}"
        score = _jaccard(q_tokens, _tokens(normalize_question(text)))
        # idx preserves the loader's order (hit_count desc, name) as the tiebreak.
        scored.append((score, -idx, s))
    # Highest score first; on ties, smaller original index first (-idx larger).
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [s for _, _, s in scored[:k]]


class SkillContextBuilder:
    def __init__(self, db: AsyncSession, organization, user=None, data_source_ids: Optional[List[str]] = None):
        self.db = db
        self.organization = organization
        self.user = user
        self.data_source_ids = data_source_ids

    async def build(self, query: Optional[str] = None) -> SkillsSection:
        # Personal/org scoping requires a user; without one we have no scope.
        user_id = str(self.user.id) if self.user else None
        if not user_id:
            return SkillsSection(items=[])

        # Pull the user-visible catalog (flag-gated inside the loader; [] when
        # flags.SKILLS is off, so OFF -> empty section, unchanged behavior).
        try:
            visible = await list_visible_skills(
                self.db,
                organization_id=str(self.organization.id),
                user_id=user_id,
                for_model=True,  # planner catalog: drop disable_model_invocation skills
            )
        except Exception:
            visible = []
        visible = visible or []

        # Top-K, query-relevant ranking when a query is available; otherwise the
        # naive full capped catalog. Any ranking failure -> naive fallback.
        selected = visible
        if query and (query or "").strip() and visible:
            try:
                selected = _rank_skills(query, visible, _top_k())
            except Exception as e:  # never break the loop on skills ranking
                logger.warning("skills top-K ranking failed, using full catalog: %s", e)
                selected = visible

        # S5.2 auto-inject: when the top-1 ranked skill clears the match floor and
        # auto-inject is enabled, inline its full SKILL.md body so the planner can
        # follow it without spending a load_skill round-trip. Env-gated (default
        # OFF) and best-effort — any failure leaves the catalog-only behavior
        # unchanged. The catalog itself is still emitted (other skills need
        # load_skill); only the single strong match is inlined.
        injected_name = None
        injected_body = None
        if (
            _autoinject_enabled()
            and query and (query or "").strip()
            and selected
        ):
            try:
                from app.ai.brain.query_cache_store import (
                    normalize_question,
                    _tokens,
                    _jaccard,
                )

                q_tokens = _tokens(normalize_question(query))
                top = selected[0]
                top_name = top.get("name", "")
                text = f"{top_name} {top.get('description', '')}"
                score = (
                    _jaccard(q_tokens, _tokens(normalize_question(text)))
                    if q_tokens
                    else 0.0
                )
                if top_name and score >= _autoinject_floor():
                    body = await get_skill_body(
                        self.db,
                        organization_id=str(self.organization.id),
                        user_id=user_id,
                        name=top_name,
                    )
                    # get_skill_body already drops model-disabled skills (S4.1),
                    # so a disabled top match simply won't inline.
                    if body and body.get("skill_md"):
                        injected_name = body.get("name") or top_name
                        injected_body = body.get("skill_md")
            except Exception as e:  # never break the loop on auto-inject
                logger.warning("skills auto-inject failed: %s", e)
                injected_name = None
                injected_body = None

        return SkillsSection(
            items=[
                SkillItem(name=s.get("name", ""), description=s.get("description", ""))
                for s in selected
            ],
            injected_name=injected_name,
            injected_body=injected_body,
        )
