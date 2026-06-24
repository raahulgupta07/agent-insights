"""
Skill authoring service (Phase 6 write)
=======================================

"Save as skill" — turn a solved analytics question into a reusable SKILL.md
draft. Mirrors the discipline of ``app.ai.brain.distiller``:

- Pure prompt builder (``build_skill_prompt``) + pure parser (``parse_skill_draft``).
- A lazy default ``infer()`` that builds
  ``LLM(model, usage_session_maker=async_session_maker).inference(prompt)`` —
  injected for tests via ``llm_inference`` so the heavy imports never fire.
- Side-effect-light: ``distill_skill_from_completion`` swallows every error and
  degrades to ``None``; it NEVER raises and rolls back on failure.

Non-live by construction (CLAUDE.md HARD RULES 4 & 5):
- Gated by ``flags.SKILLS`` (env ``HYBRID_SKILLS``), default OFF — a fresh deploy
  authors nothing.
- Everything authored lands as a PERSONAL skill at ``status='draft'``. The author
  later activates it; org promotion is approval-gated elsewhere. We NEVER write
  ``status='active'`` from authoring.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

# Reject drafts whose body / name came back empty or too short to be real.
MIN_NAME_LEN = 2
MIN_BODY_LEN = 20

# The deterministic output contract delimiter between the header and body.
_BODY_DELIM = "---"

_WS = re.compile(r"\s+")
_NAME_RE = re.compile(r"^\s*NAME:\s*(.*)$", re.IGNORECASE)
_DESC_RE = re.compile(r"^\s*DESCRIPTION:\s*(.*)$", re.IGNORECASE)
# Slugify helper: keep word chars + hyphens, collapse the rest to single hyphens.
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def _slugish(name: str) -> str:
    """Lowercase, hyphenate a free-text name into a short slug-ish handle."""
    s = _SLUG_STRIP.sub("-", (name or "").strip().lower()).strip("-")
    return s[:60]


def build_skill_prompt(question: str, answer: str, sql: Optional[str]) -> str:
    """Compose the one-shot SKILL.md authoring prompt. Pure, deterministic.

    Asks the model to emit a standard Claude-Code-style SKILL.md draft for a
    REUSABLE analytics capability derived from this one solved question. The
    output is a SKILL.md with YAML frontmatter:

        ---
        name: <short slug>
        description: <one line — the "use when..." trigger>
        ---
        <procedural markdown body: numbered steps; include the proven SQL in a
         ```sql block when one is provided>

    Instructs the model to generalize: no row-specific values (no concrete
    numbers, names, dates, or single-row results).
    """
    if sql:
        sql_block = (
            "Proven SQL that solved this question (include it, generalized, inside "
            "a ```sql fenced block in the body):\n"
            f"{sql}\n\n"
        )
    else:
        sql_block = (
            "No proven SQL is available; author the procedure from the question "
            "and answer alone.\n\n"
        )

    return (
        "You are authoring a reusable analytics SKILL from one solved question. "
        "A SKILL is a generalizable, repeatable procedure a future analyst can "
        "follow to answer the same KIND of question on fresh data.\n\n"
        f"Question that was solved:\n{question}\n\n"
        f"Answer that was given:\n{answer}\n\n"
        f"{sql_block}"
        "Write the SKILL so it is GENERALIZABLE: describe the reusable method, "
        "NOT this question's specific data values (no concrete numbers, names, "
        "dates, or single-row results — parameterize them instead).\n\n"
        "Output EXACTLY a standard SKILL.md with YAML frontmatter, nothing else. "
        "It MUST begin with a YAML frontmatter block delimited by '---' lines:\n"
        f"{_BODY_DELIM}\n"
        "name: <a short slug, 2-6 words, lowercase-with-hyphens>\n"
        "description: <one line describing WHEN to use this skill, e.g. "
        "\"use when ...\">\n"
        f"{_BODY_DELIM}\n"
        "<the procedural body in markdown: a numbered list of steps; if proven "
        "SQL was provided, include it generalized in a ```sql fenced block>\n\n"
        "Do not add any preamble, commentary, or text outside this SKILL.md."
    )


def parse_skill_draft(text: str) -> Optional[Dict[str, Any]]:
    """Parse the authoring output into a skill dict. Pure.

    Accepts BOTH formats:
      1. Standard Claude-Code-style SKILL.md with YAML frontmatter (preferred) —
         parsed via ``app.ai.skills.frontmatter.extract_skill_fields``.
      2. The legacy ``NAME:`` / ``DESCRIPTION:`` / ``---`` contract (back-compat).

    Returns a dict with at least ``{'name', 'description', 'skill_md'}`` where
    ``skill_md`` is the procedural body (frontmatter/header stripped), plus the
    extra frontmatter fields (``allowed_tools``, ``disallowed_tools``,
    ``disable_model_invocation``, ``user_invocable``, ``metadata``, ``license``)
    and ``skill_md_full`` (the full SKILL.md, frontmatter included). Returns
    ``None`` when the text is unparseable or the name/body is too short.
    """
    try:
        if not text or not str(text).strip():
            return None

        raw = str(text).replace("\r\n", "\n").replace("\r", "\n")

        # 1. Preferred: standard SKILL.md with YAML frontmatter.
        try:
            from app.ai.skills.frontmatter import extract_skill_fields

            fields = extract_skill_fields(raw) or {}
            fm_name = (fields.get("name") or "").strip()
            fm_desc = (fields.get("description") or "").strip()
            fm_body = (fields.get("body") or "").strip()
            if fm_name and fm_desc:
                slug = _slugish(_WS.sub(" ", fm_name).strip())
                final_name = slug or _WS.sub(" ", fm_name).strip()
                description = _WS.sub(" ", fm_desc).strip()
                if (
                    final_name
                    and len(final_name) >= MIN_NAME_LEN
                    and description
                    and fm_body
                    and len(fm_body) >= MIN_BODY_LEN
                ):
                    metadata = fields.get("metadata")
                    return {
                        "name": final_name,
                        "description": description,
                        "skill_md": fm_body,
                        "skill_md_full": raw.strip(),
                        "allowed_tools": list(fields.get("allowed_tools") or []),
                        "disallowed_tools": list(fields.get("disallowed_tools") or []),
                        "disable_model_invocation": bool(
                            fields.get("disable_model_invocation")
                        ),
                        "user_invocable": bool(fields.get("user_invocable", True)),
                        "metadata": metadata if isinstance(metadata, dict) else {},
                        "license": fields.get("license"),
                    }
        except Exception:
            # frontmatter not parseable / module unavailable -> fall through to legacy.
            pass

        # 2. Legacy NAME:/DESCRIPTION:/--- contract (back-compat).
        lines = raw.split("\n")

        name: Optional[str] = None
        description: Optional[str] = None
        delim_idx: Optional[int] = None

        for idx, line in enumerate(lines):
            if name is None:
                m = _NAME_RE.match(line)
                if m:
                    name = m.group(1).strip()
                    continue
            if description is None:
                m = _DESC_RE.match(line)
                if m:
                    description = m.group(1).strip()
                    continue
            # The body delimiter must come AFTER we've seen name + description.
            if name is not None and description is not None and line.strip() == _BODY_DELIM:
                delim_idx = idx
                break

        if name is None or description is None or delim_idx is None:
            return None

        body = "\n".join(lines[delim_idx + 1:]).strip()

        name = _WS.sub(" ", name).strip()
        # Prefer a slug-ish handle; fall back to the cleaned free text.
        slug = _slugish(name)
        final_name = slug or name
        description = _WS.sub(" ", description).strip()

        if not final_name or len(final_name) < MIN_NAME_LEN:
            return None
        if not description:
            return None
        if not body or len(body) < MIN_BODY_LEN:
            return None

        return {
            "name": final_name,
            "description": description,
            "skill_md": body,
            "skill_md_full": body,
            "allowed_tools": [],
            "disallowed_tools": [],
            "disable_model_invocation": False,
            "user_invocable": True,
            "metadata": {},
            "license": None,
        }
    except Exception:
        # Side-effect-light: never raise on a malformed draft.
        return None


def _content(obj: Any) -> str:
    """Defensively pull a 'content' string from a JSON column (dict|str|other)."""
    try:
        if isinstance(obj, dict):
            return str(obj.get("content") or "")
        if isinstance(obj, str):
            return obj
    except Exception:
        pass
    return ""


async def _best_effort_sql(
    db: Any,
    *,
    organization: Any,
    question: str,
) -> Optional[str]:
    """Best-effort proven-SQL lookup for the question. Degrades to None.

    Uses ``recall_proven_queries`` (approval-gated; only surfaces active rows).
    Any failure -> None; the caller authors from question+answer alone.
    """
    try:
        from app.ai.brain.query_cache_store import recall_proven_queries

        org_id = getattr(organization, "id", None)
        if not org_id:
            return None
        rows = await recall_proven_queries(
            db,
            organization_id=str(org_id),
            data_source_id=None,
            question=question,
            limit=1,
        )
        if rows:
            sql = (rows[0] or {}).get("sql")
            return sql or None
    except Exception:
        pass
    return None


async def distill_skill_from_completion(
    db: Any,
    *,
    completion: Any,
    user: Any,
    organization: Any,
    model: Any,
    llm_inference: Optional[Callable[[str], str]] = None,
    gather_sql_fn: Optional[Callable[..., Any]] = None,
    origin: str = "manual",
) -> Optional[str]:
    """Author a DRAFT personal Skill from a solved completion.

    Flow: flag gate -> pull question/answer (defensive) -> need both ->
    best-effort SQL (injected ``gather_sql_fn`` or a lazy recall; None ok) ->
    build prompt -> infer (lazy LLM default) -> parse -> insert a PERSONAL,
    DRAFT, ``category='authored'`` Skill -> commit -> return its id.

    Returns the new skill id, or None when nothing was authored (flag off /
    missing question or answer / unparseable draft / error). NEVER raises;
    rolls back on error.
    """
    try:
        # 1. Flag gate. Default OFF — fresh deploy authors nothing.
        from app.settings.hybrid_flags import flags

        if not flags.SKILLS:
            return None

        # 2. Question + answer. dash splits a turn into a user row (prompt) + a
        # system row (completion); resolve both sides from the paired sibling so
        # we don't bail just because we were handed half the turn. Need both.
        from app.ai.brain.qa_pair import resolve_qa_pair
        question, answer = await resolve_qa_pair(db, completion)
        if not question or not answer:
            return None

        # 3. Best-effort proven SQL. None is fine — we author from Q+A alone.
        sql: Optional[str] = None
        try:
            if gather_sql_fn is not None:
                maybe = gather_sql_fn(db, completion=completion, question=question)
                if hasattr(maybe, "__await__"):
                    maybe = await maybe
                sql = maybe or None
            else:
                sql = await _best_effort_sql(db, organization=organization, question=question)
        except Exception:
            sql = None

        # 4. Build the authoring prompt.
        prompt = build_skill_prompt(question, answer, sql)

        # 5. Infer. Default: lazy one-shot LLM call (mirrors the distiller).
        infer = llm_inference
        if infer is None:
            def infer(p: str) -> str:  # noqa: E306 - tiny lazy default
                from app.ai.llm.llm import LLM
                from app.dependencies import async_session_maker

                return LLM(model, usage_session_maker=async_session_maker).inference(p)

        text = (infer(prompt) or "").strip()

        # 6. Parse the deterministic contract.
        draft = parse_skill_draft(text)
        if draft is None:
            return None

        # 7. WRITE — PERSONAL + DRAFT only. Never status='active' from authoring.
        from app.models.skill import Skill

        # Persist parsed frontmatter fields into the new columns. Lists/dicts are
        # JSON-encoded (or None when empty); scalars stored directly. Defensive:
        # any missing key falls back to a safe default.
        def _json_or_none(val: Any) -> Optional[str]:
            try:
                if val:
                    return json.dumps(val)
            except Exception:
                pass
            return None

        skill = Skill(
            name=draft["name"],
            description=draft["description"],
            # Store the FULL SKILL.md (frontmatter included) when available.
            skill_md=draft.get("skill_md_full") or draft["skill_md"],
            scope="personal",
            owner_user_id=getattr(user, "id", None),
            organization_id=getattr(organization, "id", None),
            status="draft",
            category="authored",
            origin=origin,
            hit_count=0,
            allowed_tools=_json_or_none(draft.get("allowed_tools")),
            disallowed_tools=_json_or_none(draft.get("disallowed_tools")),
            disable_model_invocation=bool(draft.get("disable_model_invocation")),
            user_invocable=bool(draft.get("user_invocable", True)),
            skill_metadata=_json_or_none(draft.get("metadata")),
            license=draft.get("license"),
        )
        db.add(skill)
        # Flush so skill.id is populated before we bundle any files against it.
        try:
            await db.flush()
        except Exception:
            pass

        # S3.2-emit: if proven SQL backed this completion, auto-bundle it as a
        # script file on the new skill so the L2 body can advertise it. Best
        # effort: NEVER change the skill-insert success/return; never raise.
        if sql and str(sql).strip():
            try:
                from app.ai.skills.files import add_skill_file, KIND_SCRIPT

                await add_skill_file(
                    db,
                    skill_id=skill.id,
                    path="scripts/queries.sql",
                    kind=KIND_SCRIPT,
                    content=str(sql),
                )
            except Exception as fe:
                logger.warning("skill authoring file emit failed: %s", fe)

        await db.commit()
        return str(skill.id)
    except Exception as e:  # never break the caller; roll back the failed write
        logger.warning("skill authoring distill_skill_from_completion failed: %s", e)
        try:
            await db.rollback()
        except Exception:
            pass
        return None
