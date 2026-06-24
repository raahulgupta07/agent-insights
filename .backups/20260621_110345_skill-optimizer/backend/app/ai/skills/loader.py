"""
Skills loader (Phase 6 read)
============================

Progressive-disclosure loader for the self-service Skills subsystem. Surfaces an
L1 catalog (name + description) of skills visible to a user, and loads the full
SKILL.md body (L2) on demand.

Visibility rule (one place, reused by both reads):
    scope='global'
    OR (scope='org'      AND organization_id matches)
    OR (scope='personal' AND owner_user_id == user_id)
... filtered by status and excluding soft-deleted rows.

Design rules honored:
- Everything is gated by flags.SKILLS. Safe no-ops ([] / None) when the flag is
  off or there's no db — a fresh deploy behaves exactly like upstream dash.
- Side-effect-light: every public coroutine swallows its own DB errors and
  degrades to a no-op so the agent loop never breaks on skills.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _visibility_clause(organization_id: Optional[str], user_id: Optional[str]):
    """Build the shared visibility OR-clause. Imports kept local (flag-gated)."""
    from sqlalchemy import or_, and_
    from app.models.skill import Skill

    return or_(
        Skill.scope == "global",
        and_(Skill.scope == "org", Skill.organization_id == organization_id),
        and_(Skill.scope == "personal", Skill.owner_user_id == user_id),
    )


async def list_visible_skills(
    db: Any,
    *,
    organization_id: Optional[str],
    user_id: Optional[str],
    status: str = "active",
    limit: int = 200,
    for_model: bool = False,
) -> List[Dict[str, Any]]:
    """List skills visible to this user (L1 catalog).

    No-op [] unless flags.SKILLS. Returns skills visible per the shared
    visibility rule, filtered by status and excluding soft-deleted rows. Each
    dict: {'id','name','description','scope'}. Capped at limit, ordered by
    hit_count desc then name.

    ``for_model`` (S4.1 invocation parity): when True this is the planner-facing
    catalog, so skills flagged ``disable_model_invocation`` are dropped (the model
    must not auto-select them — only an explicit human invoke may run them). The
    default (False) returns the full user-visible set for FE listing / slash
    autocomplete. ``user_invocable`` does NOT affect the model catalog (a
    model-only skill stays visible to the planner).
    """
    from app.settings.hybrid_flags import flags

    if not flags.SKILLS:
        return []
    if db is None:
        return []

    try:
        from sqlalchemy import select, or_
        from app.models.skill import Skill

        conds = [
            Skill.status == status,
            Skill.invalid_at.is_(None),  # hide bi-temporal superseded versions (no-op for current data)
            Skill.deleted_at.is_(None),
            _visibility_clause(organization_id, user_id),
        ]
        if for_model:
            # Drop model-disabled skills from the planner catalog. Treat NULL
            # (pre-migration rows) as not-disabled so old skills stay visible.
            conds.append(
                or_(
                    Skill.disable_model_invocation == False,  # noqa: E712
                    Skill.disable_model_invocation.is_(None),
                )
            )

        stmt = (
            select(Skill)
            .where(*conds)
            .order_by(Skill.hit_count.desc(), Skill.name)
            .limit(limit)
        )
        rows = (await db.execute(stmt)).scalars().all()
    except Exception as e:  # never break the loop on skills read
        logger.warning("skills list failed: %s", e)
        return []

    return [
        {
            "id": str(r.id),
            "name": r.name,
            "description": r.description,
            "scope": r.scope,
        }
        for r in rows
    ]


async def get_skill_body(
    db: Any,
    *,
    organization_id: Optional[str],
    user_id: Optional[str],
    name: str,
) -> Optional[Dict[str, Any]]:
    """Load the full SKILL.md body (L2) for a visible active skill by name.

    No-op None unless flags.SKILLS. Returns
    {'id','name','description','skill_md','category', plus the frontmatter
    fields: 'allowed_tools','disallowed_tools','disable_model_invocation',
    'user_invocable','metadata','license'} for the first VISIBLE active skill
    matching name (same visibility rule). None if not found / not visible.

    Defensive about pre-migration / old rows: missing columns degrade to safe
    defaults ([] / {} / False / True / None) and never raise.
    """
    from app.settings.hybrid_flags import flags

    if not flags.SKILLS:
        return None
    if db is None or not name:
        return None

    try:
        from sqlalchemy import select, or_
        from app.models.skill import Skill

        # get_skill_body is the model's load path (load_skill / read_skill_file).
        # Defense-in-depth for S4.1: a model-disabled skill must not be loadable
        # by name even if the model somehow knows it (it's already dropped from
        # the catalog). NULL (pre-migration) treated as not-disabled.
        stmt = (
            select(Skill)
            .where(
                Skill.name == name,
                Skill.status == "active",
                Skill.deleted_at.is_(None),
                or_(
                    Skill.disable_model_invocation == False,  # noqa: E712
                    Skill.disable_model_invocation.is_(None),
                ),
                _visibility_clause(organization_id, user_id),
            )
            .order_by(Skill.hit_count.desc(), Skill.name)
            .limit(1)
        )
        row = (await db.execute(stmt)).scalars().first()
    except Exception as e:  # never break the loop on skills read
        logger.warning("skills get failed: %s", e)
        return None

    if row is None:
        return None

    def _json_list(val: Any) -> List[Any]:
        """Decode a JSON list column to a list; [] on null/parse-fail/non-list."""
        if not val:
            return []
        if isinstance(val, (list, tuple)):
            return list(val)
        try:
            import json
            parsed = json.loads(val)
            return list(parsed) if isinstance(parsed, (list, tuple)) else []
        except Exception:
            return []

    def _json_dict(val: Any) -> Dict[str, Any]:
        """Decode a JSON object column to a dict; {} on null/parse-fail/non-dict."""
        if not val:
            return {}
        if isinstance(val, dict):
            return dict(val)
        try:
            import json
            parsed = json.loads(val)
            return dict(parsed) if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    # S3.4: best-effort bundled-file listing so the L2 body can advertise the
    # skill's available files (scripts/references/assets) to the planner. Lazy
    # import; default [] on any error — never raise.
    files: List[Dict[str, Any]] = []
    try:
        from app.ai.skills.files import list_skill_files

        files = await list_skill_files(db, skill_id=row.id) or []
    except Exception as e:
        logger.warning("skills file listing failed: %s", e)
        files = []

    return {
        "id": str(row.id),
        "name": row.name,
        "description": row.description,
        "skill_md": row.skill_md,
        "category": row.category,
        # New frontmatter fields — defensive against pre-migration / old rows.
        "allowed_tools": _json_list(getattr(row, "allowed_tools", None)),
        "disallowed_tools": _json_list(getattr(row, "disallowed_tools", None)),
        "disable_model_invocation": bool(
            getattr(row, "disable_model_invocation", False) or False
        ),
        "user_invocable": (
            True
            if getattr(row, "user_invocable", True) is None
            else bool(getattr(row, "user_invocable", True))
        ),
        "metadata": _json_dict(getattr(row, "skill_metadata", None)),
        "license": getattr(row, "license", None),
        "files": files,
    }


async def list_studio_pinned_skill_ids(db: Any, *, studio_id: Optional[str]) -> List[str]:
    """Return the set of skill ids pinned to a Studio (hybrid Studios ST5).

    No-op [] unless flags.STUDIOS (so a flag-OFF deploy never reads the join) and
    [] when there's no db / no studio_id. Used by ``SkillContextBuilder`` to
    RESTRICT the offered skill catalog to a Studio's curated set. Excludes
    soft-deleted pins. Never raises — degrades to [] so the agent loop never
    breaks (caller treats [] as "studio pins none" -> full visible catalog).
    """
    from app.settings.hybrid_flags import flags

    if not flags.STUDIOS:
        return []
    if db is None or not studio_id:
        return []

    try:
        from sqlalchemy import select
        from app.models.studio import StudioSkill

        rows = (
            await db.execute(
                select(StudioSkill.skill_id).where(
                    StudioSkill.studio_id == studio_id,
                    StudioSkill.deleted_at.is_(None),
                )
            )
        ).all()
    except Exception as e:  # never break the loop on the studio-skill read
        logger.warning("studio pinned skills read failed: %s", e)
        return []

    return [str(r[0]) for r in rows if r and r[0] is not None]


async def record_skill_use(skill_id: str) -> None:
    """Bump hit_count + last_used_at for a skill, in an ISOLATED async session.

    Called by the load_skill tool after a successful load. Uses its own session
    (not the agent's shared/greenlet-bound one) so the write can never raise the
    'greenlet_spawn' async-context error on the hot read path. Best effort.
    """
    if not skill_id:
        return
    try:
        from datetime import datetime
        from sqlalchemy import update
        from app.models.skill import Skill
        from app.dependencies import async_session_maker
        async with async_session_maker() as s:
            await s.execute(
                update(Skill)
                .where(Skill.id == skill_id)
                .values(hit_count=Skill.hit_count + 1,
                        last_used_at=datetime.utcnow())  # naive: column is TIMESTAMP WITHOUT TIME ZONE
            )
            await s.commit()
    except Exception as e:
        logger.warning("record_skill_use failed: %s", e)


def render_skill_catalog(items: List[Dict[str, Any]]) -> str:
    """Render the visible skills as an L1 planner catalog block. Empty -> ''."""
    if not items:
        return ""
    lines = [
        "## SKILLS (proven, vetted procedures)",
        "BEFORE answering, scan this list. If ANY skill's description matches the "
        "user's task or intent — even loosely — you MUST call load_skill(\"<name>\") "
        "FIRST and follow that skill's steps verbatim instead of improvising. "
        "Always prefer a matching skill over ad-hoc reasoning. If two skills match, "
        "pick the most specific one. If none match, proceed normally — do not force "
        "a skill.",
    ]
    for it in items:
        name = (it.get("name") or "").strip()
        desc = (it.get("description") or "").strip()
        lines.append(f"- {name}: {desc}")
    return "\n".join(lines)


def render_injected_skill(name: str, body: str) -> str:
    """Render an auto-loaded (top-match) skill's full SKILL.md inline for the planner.

    Used by S5.2 auto-inject: when a skill's match score clears the floor the
    builder inlines its body so the planner needn't spend a load_skill round-trip.
    Empty/blank body -> "".
    """
    # Defensive: pure string work, but tolerate None inputs without raising.
    if body is None or not str(body).strip():
        return ""
    safe_name = (name or "").strip() or "skill"
    header = (
        f"## ACTIVE SKILL (auto-loaded: {safe_name})\n"
        "This skill closely matches the task; its full instructions are below. "
        "Follow them. You do NOT need to call load_skill for this skill — it is "
        "already loaded. Other skills in the catalog still require load_skill."
    )
    return f"{header}\n\n{str(body).strip()}"
