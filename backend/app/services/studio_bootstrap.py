"""Studio Context Harness bootstrap (hybrid Studios ST7).

Auto-born studio context — no user typing. A Studio is created with only a
name + description; this module fills in the engineered context behind the
scenes, in two phases:

  ON CREATE (name + description only):
    * avatar   -> pick a single emoji                         -> LIVE (studio.avatar)
    * voice    -> short tone + reply-language line            -> LIVE (studio.persona)
    * summary0 -> "what this studio is for"                   -> LIVE (StudioArtifact 'summary')

  ON SOURCE PINNED (pinned-source schemas now available):
    * summary1     -> regenerate over real schemas            -> LIVE (replace 'summary')
    * suggestedQs  -> starter questions                       -> LIVE (replace 'suggested_questions')
    * instructions -> propose 3-6 rules from schema           -> PENDING (review gate)
    * examples     -> mine query bank + generate Q->answer    -> PENDING (review gate)

Reuse, not reinvention (CLAUDE.md HARD RULE: no second LLM client):
  * LLM  = the org's *small* default model resolved by
    ``LLMService().get_default_model(..., is_small=True)``, called via dash's
    one-shot wrapper ``LLM(model, usage_session_maker=async_session_maker)
    .inference(prompt)`` — the exact shape ``studio_artifacts.py`` /
    the distiller / knowledge proposer use. ``.inference()`` is synchronous, so
    it runs in a worker thread.
  * Schema = reuses ``app.ai.brain.knowledge_proposer._introspect_schema_text``
    and ``app.services.studio_artifacts._gather_pinned_schema`` (the existing
    pinned-source schema getter) — no new schema infra.

Guardrails honored:
  * rules + examples are ALWAYS born ``pending`` (never reach the model until a
    human approves via the existing review gate).
  * avatar / voice / summary / suggestedQs = auto (mechanical, safe) -> LIVE.
  * bootstrap_state (JSON on ``studios``) is the idempotency ledger:
    ``{'created': true}`` after on-create, ``{'sourced': true}`` after on-pin.
    NULL is treated as ``{}``.
  * Everything is best-effort: each LLM step is independently guarded so a
    single failure never aborts the rest, and the background entry points
    swallow all errors so they can never break create / pin.
  * 'suggested_questions' StudioArtifact kind is SHARED with the self-improve
    agent (ST8) — this module always REPLACES the existing row of that kind,
    never duplicates it.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.settings.logging_config import get_logger

logger = get_logger(__name__)

# StudioArtifact kinds this module writes.
_KIND_SUMMARY = "summary"
_KIND_SUGGESTED = "suggested_questions"

# Bound how many auto rules / examples we propose per run (cheap tier).
_MAX_INSTRUCTIONS = 6
_MAX_EXAMPLES = 6
# Bound how many proven query-bank rows we fold in.
_MAX_BANK_ROWS = 12


# --------------------------------------------------------------------------- #
# Shared low-level helpers
# --------------------------------------------------------------------------- #
def _state(studio) -> dict:
    """Return the studio's bootstrap_state as a dict (NULL -> {})."""
    st = getattr(studio, "bootstrap_state", None)
    return dict(st) if isinstance(st, dict) else {}


async def _resolve_organization(db: AsyncSession, studio) -> Optional[Any]:
    """Load the Studio's Organization (LLMService needs a real org object)."""
    org_id = getattr(studio, "organization_id", None)
    if not org_id:
        return None
    from app.models.organization import Organization

    res = await db.execute(select(Organization).where(Organization.id == org_id))
    return res.scalar_one_or_none()


async def _resolve_model(db: AsyncSession, studio, organization):
    """Resolve the org's small/cheap default model (reuse, no new infra)."""
    from app.services.llm_service import LLMService

    return await LLMService().get_default_model(
        db, organization, getattr(studio, "owner_user_id", None), is_small=True
    )


async def _infer(model, prompt: str) -> str:
    """Run dash's synchronous one-shot LLM wrapper off the event loop.

    Mirrors ``studio_artifacts._infer`` exactly. Returns the stripped text;
    callers guard for empties.
    """

    def _run() -> str:
        from app.ai.llm.llm import LLM
        from app.dependencies import async_session_maker

        return LLM(model, usage_session_maker=async_session_maker).inference(prompt)

    text = await asyncio.to_thread(_run)
    return (text or "").strip()


async def _upsert_artifact(db: AsyncSession, studio_id: str, kind: str, content: str) -> None:
    """REPLACE the single StudioArtifact of ``kind`` for this studio.

    The 'suggested_questions' kind is shared with the ST8 self-improve loop, so
    we always replace rather than append. We soft-update the newest existing row
    and soft-delete any older duplicates of the same kind to keep one live row.
    """
    from datetime import datetime

    from app.models.studio import StudioArtifact

    res = await db.execute(
        select(StudioArtifact)
        .where(
            StudioArtifact.studio_id == studio_id,
            StudioArtifact.kind == kind,
            StudioArtifact.deleted_at.is_(None),
        )
        .order_by(StudioArtifact.created_at.desc())
    )
    rows = list(res.scalars().all())
    if rows:
        rows[0].content = content
        for stale in rows[1:]:
            stale.deleted_at = datetime.utcnow()
    else:
        db.add(StudioArtifact(studio_id=studio_id, kind=kind, content=content))


def _parse_json_list(text: str) -> List[str]:
    """Best-effort parse of an LLM reply into a list of short strings.

    Accepts a raw JSON array, a fenced JSON array, or a newline / bullet list.
    Always returns a (possibly empty) list of cleaned strings.
    """
    if not text:
        return []
    raw = text.strip()
    # Strip code fences if present.
    if raw.startswith("```"):
        raw = raw.strip("`")
        nl = raw.find("\n")
        if nl != -1:
            raw = raw[nl + 1 :]
        raw = raw.strip()
    # Try JSON first.
    start = raw.find("[")
    end = raw.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            parsed = json.loads(raw[start : end + 1])
            if isinstance(parsed, list):
                out = [str(x).strip() for x in parsed if str(x).strip()]
                if out:
                    return out
        except Exception:
            pass
    # Fall back to line/bullet parsing.
    items: List[str] = []
    for line in raw.splitlines():
        s = line.strip().lstrip("-*0123456789.)( ").strip().strip('"').strip()
        if s:
            items.append(s)
    return items


# --------------------------------------------------------------------------- #
# ON CREATE — avatar / voice / summary0 (all LIVE)
# --------------------------------------------------------------------------- #
async def bootstrap_on_create(db: AsyncSession, studio) -> None:
    """Auto-born context from name + description (mechanical, safe -> LIVE).

    Idempotent: re-runs are cheap-skipped once ``bootstrap_state['created']`` is
    set. Each LLM step is independently guarded; partial success is committed.
    """
    state = _state(studio)
    if state.get("created"):
        return

    name = (getattr(studio, "name", None) or "").strip()
    description = (getattr(studio, "description", None) or "").strip()
    studio_id = str(getattr(studio, "id"))

    organization = await _resolve_organization(db, studio)
    model = await _resolve_model(db, studio, organization) if organization else None

    if model is not None:
        ctx = f"Name: {name}\nDescription: {description or '(none provided)'}"

        # 1) avatar -> a single emoji.
        try:
            emoji = await _infer(
                model,
                "Pick a SINGLE emoji that best represents this analytics "
                "workspace (a 'Studio'). Respond with ONLY the emoji character, "
                "nothing else.\n\n" + ctx,
            )
            emoji = emoji.split()[0] if emoji else ""
            if emoji:
                studio.avatar = emoji[:8]
        except Exception as e:  # noqa: BLE001
            logger.warning("studio_bootstrap.avatar failed for %s: %s", studio_id, e)

        # 2) voice -> short tone + reply-language line (reuse `persona` column).
        try:
            voice = await _infer(
                model,
                "Write a SHORT voice/tone guide (2-3 sentences) for an AI "
                "analyst assistant that runs this analytics workspace. Describe "
                "the tone it should use and end with one line stating the "
                "reply language (default: reply in the user's language). No "
                "preamble, no headings.\n\n" + ctx,
            )
            if voice:
                studio.persona = voice
        except Exception as e:  # noqa: BLE001
            logger.warning("studio_bootstrap.voice failed for %s: %s", studio_id, e)

        # 3) summary v0 -> "what this studio is for" (LIVE artifact).
        try:
            summary = await _infer(
                model,
                "Write a clear 2-4 sentence summary of what this analytics "
                "workspace is for and the kinds of questions it will help "
                "answer. Markdown, no headings, no preamble.\n\n" + ctx,
            )
            if summary:
                await _upsert_artifact(db, studio_id, _KIND_SUMMARY, summary)
        except Exception as e:  # noqa: BLE001
            logger.warning("studio_bootstrap.summary0 failed for %s: %s", studio_id, e)
    else:
        logger.info(
            "studio_bootstrap.on_create: no model configured for studio %s; "
            "marking created without generation.",
            studio_id,
        )

    state["created"] = True
    studio.bootstrap_state = state
    flag_modified(studio, "bootstrap_state")  # JSON in-place reassign needs explicit dirty flag
    await db.commit()


# --------------------------------------------------------------------------- #
# ON SOURCE PINNED — summary1 / suggestedQs (LIVE) + instructions / examples (PENDING)
# --------------------------------------------------------------------------- #
async def bootstrap_on_source_pin(
    db: AsyncSession, studio, *, force: bool = False
) -> None:
    """Auto-born context grounded on the real pinned-source schemas.

    Runs only when the studio has at least one introspectable pinned source.
    Idempotent via ``bootstrap_state['sourced']`` unless ``force=True``. Each
    sub-step is independently guarded; partial success is committed.
    """
    state = _state(studio)
    if state.get("sourced") and not force:
        return

    studio_id = str(getattr(studio, "id"))

    organization = await _resolve_organization(db, studio)
    if organization is None:
        return

    # Reuse the existing pinned-source schema getter.
    from app.services.studio_artifacts import _gather_pinned_schema

    schema_digest, source_names = await _gather_pinned_schema(db, studio, organization)
    if not schema_digest:
        # No introspectable schema yet — nothing to ground on. Do NOT mark
        # 'sourced' so a later pin (with a connected source) re-runs.
        return

    model = await _resolve_model(db, studio, organization)
    name = (getattr(studio, "name", None) or "").strip()
    description = (getattr(studio, "description", None) or "").strip()
    sources_line = ", ".join(source_names) if source_names else "the pinned data sources"
    grounding = (
        f"Studio: {name}\nDescription: {description or '(none provided)'}\n"
        f"Grounded on: {sources_line}\n\n"
        "Schema (table(col1, col2, ...) per pinned source):\n"
        f"{schema_digest}\n\n"
        "Ground everything ONLY in this schema — do NOT invent tables, columns "
        "or facts not present above."
    )

    if model is not None:
        # 1) summary v1 -> regenerate over real schemas (LIVE, replace).
        try:
            summary = await _infer(
                model,
                grounding
                + "\n\nTask: Write a clear summary (Markdown, ~120-180 words) of "
                "what this data is about: the key tables, what each represents, "
                "and the analyses it supports. Reference tables by name. Output "
                "ONLY the Markdown, no preamble, no code fences.",
            )
            if summary:
                await _upsert_artifact(db, studio_id, _KIND_SUMMARY, summary)
        except Exception as e:  # noqa: BLE001
            logger.warning("studio_bootstrap.summary1 failed for %s: %s", studio_id, e)

        # 2) suggested questions -> LIVE artifact (JSON list, replace).
        try:
            qs_text = await _infer(
                model,
                grounding
                + "\n\nTask: Propose 5-7 realistic starter questions a business "
                "user would ask of this data, answerable from these tables. "
                "Output ONLY a JSON array of question strings, nothing else.",
            )
            questions = _parse_json_list(qs_text)[:7]
            if questions:
                await _upsert_artifact(
                    db, studio_id, _KIND_SUGGESTED, json.dumps(questions)
                )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "studio_bootstrap.suggestedQs failed for %s: %s", studio_id, e
            )

    # 3) instructions -> PENDING candidate rules (review gate).
    try:
        await _propose_instructions(db, studio, model, grounding)
    except Exception as e:  # noqa: BLE001
        logger.warning("studio_bootstrap.instructions failed for %s: %s", studio_id, e)

    # 4) examples -> PENDING golden few-shots (query bank + generated).
    try:
        await _propose_examples(
            db, studio, organization, model, grounding, source_names
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("studio_bootstrap.examples failed for %s: %s", studio_id, e)

    state["sourced"] = True
    studio.bootstrap_state = state
    flag_modified(studio, "bootstrap_state")  # JSON in-place reassign needs explicit dirty flag
    await db.commit()


# --------------------------------------------------------------------------- #
# Proposers (importable for the API agent's /regenerate)
# --------------------------------------------------------------------------- #
async def _propose_instructions(db: AsyncSession, studio, model, grounding: str) -> int:
    """LLM-propose 3-6 candidate rules from the schema -> PENDING rows.

    Returns the number of instruction rows inserted. Each row is born
    source='auto', status='pending' (never reaches the model until approved).
    """
    if model is None:
        return 0

    from app.models.studio import StudioInstruction

    text = await _infer(
        model,
        grounding
        + "\n\nTask: Propose 3-6 concise guidance rules an AI analyst should "
        "follow when answering questions over THIS data (e.g. which table to "
        "use for a concept, important joins, caveats, default filters, units). "
        "Each rule must be grounded in the schema above. Output ONLY a JSON "
        "array of rule strings, nothing else.",
    )
    rules = _parse_json_list(text)[:_MAX_INSTRUCTIONS]
    studio_id = str(getattr(studio, "id"))
    inserted = 0
    for rule in rules:
        db.add(
            StudioInstruction(
                studio_id=studio_id,
                content=rule,
                source="auto",
                status="pending",
            )
        )
        inserted += 1
    return inserted


async def _mine_query_bank(
    db: AsyncSession, organization, source_names: List[str], studio
) -> List[Tuple[str, str]]:
    """Mine proven Q->SQL from the reasoning cache for the studio's pinned DS.

    Reads ``query_cache`` rows scoped to the org + the studio's pinned data
    sources. Returns a list of ``(question, sql)`` pairs (best-effort, guarded).
    """
    try:
        from app.models.query_cache import QueryCache
        from app.models.studio import StudioDataSource

        pin_res = await db.execute(
            select(StudioDataSource.agent_id).where(
                StudioDataSource.studio_id == str(getattr(studio, "id")),
                StudioDataSource.deleted_at.is_(None),
            )
        )
        ds_ids = [row[0] for row in pin_res.all()]
        if not ds_ids:
            return []

        q = (
            select(QueryCache)
            .where(
                QueryCache.organization_id == str(getattr(organization, "id")),
                QueryCache.data_source_id.in_(ds_ids),
                QueryCache.deleted_at.is_(None),
            )
            .order_by(QueryCache.hit_count.desc())
            .limit(_MAX_BANK_ROWS)
        )
        rows = list((await db.execute(q)).scalars().all())
        out: List[Tuple[str, str]] = []
        for r in rows:
            question = (getattr(r, "question_norm", None) or "").strip()
            sql = (getattr(r, "sql_text", None) or "").strip()
            # Skip rows with a recorded thumbs-down (not "proven").
            if question and sql and (getattr(r, "thumbs_down", 0) or 0) == 0:
                out.append((question, sql))
        return out
    except Exception as e:  # noqa: BLE001
        logger.warning("studio_bootstrap._mine_query_bank failed: %s", e)
        return []


async def _propose_examples(
    db: AsyncSession,
    studio,
    organization,
    model,
    grounding: str,
    source_names: List[str],
) -> int:
    """Propose golden few-shot examples -> PENDING rows.

    Two sources, both born source='auto', status='pending':
      * mined proven Q->SQL from the query bank (no LLM); and
      * LLM-generated Q->answer (with optional SQL) from the schema.
    Returns the number of example rows inserted.
    """
    from app.models.studio import StudioExample

    studio_id = str(getattr(studio, "id"))
    inserted = 0

    # (a) Mine proven Q->SQL from the query bank (free, no LLM).
    mined = await _mine_query_bank(db, organization, source_names, studio)
    for question, sql in mined[:_MAX_EXAMPLES]:
        db.add(
            StudioExample(
                studio_id=studio_id,
                question=question,
                answer="",  # proven SQL example; answer filled on approval/use
                sql=sql,
                source="auto",
                status="pending",
            )
        )
        inserted += 1

    # (b) Generate Q->answer pairs from the schema (LLM), if we have budget.
    remaining = _MAX_EXAMPLES - inserted
    if model is not None and remaining > 0:
        text = await _infer(
            model,
            grounding
            + "\n\nTask: Write "
            + str(min(remaining, 4))
            + " example question/answer pairs a new analyst would find useful "
            "for this data. Each answer must be grounded in the schema and "
            "reference the relevant table(s) by name. Output ONLY a JSON array "
            'of objects like {"question": "...", "answer": "...", "sql": "..."} '
            "where sql is optional (use null if not applicable).",
        )
        for obj in _parse_json_objects(text)[:remaining]:
            question = (obj.get("question") or "").strip()
            answer = (obj.get("answer") or "").strip()
            sql = (obj.get("sql") or None)
            if isinstance(sql, str):
                sql = sql.strip() or None
            if question and answer:
                db.add(
                    StudioExample(
                        studio_id=studio_id,
                        question=question,
                        answer=answer,
                        sql=sql,
                        source="auto",
                        status="pending",
                    )
                )
                inserted += 1

    return inserted


def _parse_json_objects(text: str) -> List[dict]:
    """Best-effort parse of an LLM reply into a list of dicts."""
    if not text:
        return []
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        nl = raw.find("\n")
        if nl != -1:
            raw = raw[nl + 1 :]
        raw = raw.strip()
    start = raw.find("[")
    end = raw.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []
    try:
        parsed = json.loads(raw[start : end + 1])
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return [x for x in parsed if isinstance(x, dict)]


# --------------------------------------------------------------------------- #
# Public re-run entry points (the API agent's /regenerate calls these)
# --------------------------------------------------------------------------- #
async def regenerate_instructions(db: AsyncSession, studio) -> int:
    """Re-run JUST the instruction proposer over the studio's pinned schema.

    Inserts fresh PENDING rows (never touches existing/approved ones). Returns
    the count inserted (0 when no model / no introspectable schema). Commits.
    """
    organization = await _resolve_organization(db, studio)
    if organization is None:
        return 0
    from app.services.studio_artifacts import _gather_pinned_schema

    schema_digest, source_names = await _gather_pinned_schema(db, studio, organization)
    if not schema_digest:
        return 0
    model = await _resolve_model(db, studio, organization)
    grounding = _grounding_text(studio, source_names, schema_digest)
    inserted = await _propose_instructions(db, studio, model, grounding)
    await db.commit()
    return inserted


async def regenerate_examples(db: AsyncSession, studio) -> int:
    """Re-run JUST the example proposer over the studio's pinned schema.

    Inserts fresh PENDING rows (never touches existing/approved ones). Returns
    the count inserted (0 when no introspectable schema). Commits.
    """
    organization = await _resolve_organization(db, studio)
    if organization is None:
        return 0
    from app.services.studio_artifacts import _gather_pinned_schema

    schema_digest, source_names = await _gather_pinned_schema(db, studio, organization)
    if not schema_digest:
        return 0
    model = await _resolve_model(db, studio, organization)
    grounding = _grounding_text(studio, source_names, schema_digest)
    inserted = await _propose_examples(
        db, studio, organization, model, grounding, source_names
    )
    await db.commit()
    return inserted


def _grounding_text(studio, source_names: List[str], schema_digest: str) -> str:
    """Compose the shared schema-grounding preamble (pure)."""
    name = (getattr(studio, "name", None) or "").strip()
    description = (getattr(studio, "description", None) or "").strip()
    sources_line = ", ".join(source_names) if source_names else "the pinned data sources"
    return (
        f"Studio: {name}\nDescription: {description or '(none provided)'}\n"
        f"Grounded on: {sources_line}\n\n"
        "Schema (table(col1, col2, ...) per pinned source):\n"
        f"{schema_digest}\n\n"
        "Ground everything ONLY in this schema — do NOT invent tables, columns "
        "or facts not present above."
    )


# --------------------------------------------------------------------------- #
# Background-task entry points (open their own session; never raise)
# --------------------------------------------------------------------------- #
async def _run_on_create(studio_id: str) -> None:
    """Background entry: load the studio in a fresh session, run on-create."""
    from app.dependencies import async_session_maker
    from app.models.studio import Studio

    try:
        async with async_session_maker() as session:
            res = await session.execute(
                select(Studio).where(
                    Studio.id == studio_id, Studio.deleted_at.is_(None)
                )
            )
            studio = res.scalar_one_or_none()
            if studio is not None:
                await bootstrap_on_create(session, studio)
    except Exception as e:  # noqa: BLE001 — never break the request
        logger.warning("studio_bootstrap on_create background failed (%s): %s", studio_id, e)


async def _run_on_source_pin(studio_id: str) -> None:
    """Background entry: load the studio in a fresh session, run on-source-pin."""
    from app.dependencies import async_session_maker
    from app.models.studio import Studio

    try:
        async with async_session_maker() as session:
            res = await session.execute(
                select(Studio).where(
                    Studio.id == studio_id, Studio.deleted_at.is_(None)
                )
            )
            studio = res.scalar_one_or_none()
            if studio is not None:
                await bootstrap_on_source_pin(session, studio)
    except Exception as e:  # noqa: BLE001 — never break the request
        logger.warning(
            "studio_bootstrap on_source_pin background failed (%s): %s", studio_id, e
        )


def schedule_bootstrap_on_create(background_tasks, studio) -> None:
    """Schedule on-create bootstrap as a FastAPI BackgroundTask (flag-gated).

    Safe to call from the create route after commit. No-op unless flags.STUDIOS.
    Captures only the studio id (the request session is gone by run time).
    """
    from app.settings.hybrid_flags import flags

    if not flags.STUDIOS:
        return
    try:
        background_tasks.add_task(_run_on_create, str(getattr(studio, "id")))
    except Exception as e:  # noqa: BLE001
        logger.warning("studio_bootstrap: failed to schedule on_create: %s", e)


def schedule_bootstrap_on_source_pin(background_tasks, studio_id: str) -> None:
    """Schedule on-source-pin bootstrap as a FastAPI BackgroundTask (flag-gated).

    Idempotent (the task itself short-circuits via bootstrap_state). No-op unless
    flags.STUDIOS.
    """
    from app.settings.hybrid_flags import flags

    if not flags.STUDIOS:
        return
    try:
        background_tasks.add_task(_run_on_source_pin, str(studio_id))
    except Exception as e:  # noqa: BLE001
        logger.warning("studio_bootstrap: failed to schedule on_source_pin: %s", e)
