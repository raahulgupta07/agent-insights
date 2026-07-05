"""Auto-fill an agent's Overview panel at train time.

The report Agent panel's Overview reads two DEDICATED columns on the
data_source (agent): ``primary_instruction_id`` (the pinned instruction) and
``conversation_starters`` (saved starter chips, ``list[str]`` where each item is
``"title\\nprompt"``). Neither is populated by the training pipeline, so a
freshly-trained agent shows "No primary instruction / No conversation starters"
even though its Instructions tab has content and the report shows GENERIC
fallback chips. This fills what is MISSING (never overrides a user's own choice)
so the Overview is populated out of the box. Fail-soft — training never breaks
because of it.
"""
from __future__ import annotations

from app.settings.logging_config import get_logger

logger = get_logger(__name__)

# Generic-but-useful starters mirroring the frontend fallback chips, so the
# Overview is populated even when nothing better can be inferred. Each entry is
# "title\nprompt" per the panel's saved-starter format.
DEFAULT_STARTERS = [
    "Summarize this dataset\nRow count, date range, and key dimensions",
    "Trend over time\nShow the main metrics and how they trend over time",
    "What stands out\nWhat looks unusual or noteworthy in this data?",
    "Top category\nBreak down the primary measure by its top category",
]

# Categories that make a good PRIMARY directive, best first. A data_quality
# guardrail is a poor "primary", so it is deliberately excluded — we synthesize
# a clean primary instead when only guardrails exist.
_PRIMARY_PREF = ["general", "overview", "definition", "semantic", "business"]


async def _pick_primary_instruction(db, data_source):
    """Best existing NON-guardrail instruction linked to this agent, or None."""
    from sqlalchemy import select, text as sql_text
    from app.models.instruction import Instruction
    ids = (await db.execute(sql_text(
        "SELECT instruction_id FROM instruction_data_source_association "
        "WHERE data_source_id = :d"
    ), {"d": str(data_source.id)})).scalars().all()
    if not ids:
        return None
    insts = (await db.execute(
        select(Instruction).where(Instruction.id.in_(list(ids)))
    )).scalars().all()
    cands = [
        i for i in insts
        if (getattr(i, "status", None) or "") != "archived"
        and (getattr(i, "category", None) or "general") in _PRIMARY_PREF
    ]
    if not cands:
        return None
    cands.sort(key=lambda i: _PRIMARY_PREF.index(
        (getattr(i, "category", None) or "general")))
    return cands[0]


async def _synthesize_primary(db, organization, data_source):
    """Create + link a clean 1-paragraph primary instruction from the name."""
    from app.models.instruction import Instruction
    name = (getattr(data_source, "name", None) or "this dataset").strip()
    text_body = (
        f"You are the analyst for {name}. Answer using this agent's tables and "
        "knowledge. Report the full available period unless a specific date or "
        "segment is asked for, treat already-consolidated tables as final "
        "(never double-count across periods), and ground every number in the "
        "data rather than estimating."
    )
    inst = Instruction(
        text=text_body,
        title="Agent overview",
        source_type="ai",
        status="published",
        load_mode="always",
        category="general",
        ai_source="agent_overview_autofill",
        organization_id=str(organization.id),
    )
    db.add(inst)
    await db.flush()
    try:
        inst.data_sources = [data_source]
    except Exception as e:  # noqa: BLE001 — link is best-effort
        logger.debug("agent_overview: link synth instruction failed: %s", e)
    return inst


async def autofill_agent_overview(db, *, organization, data_source) -> dict:
    """Populate primary_instruction_id + conversation_starters if unset.

    Returns a dict describing what changed (empty if nothing needed doing,
    ``{"error": ...}`` on failure). Never raises.
    """
    changed: dict = {}
    try:
        cs = getattr(data_source, "conversation_starters", None)
        if not cs:  # None or empty list
            data_source.conversation_starters = list(DEFAULT_STARTERS)
            changed["starters"] = len(DEFAULT_STARTERS)

        if not getattr(data_source, "primary_instruction_id", None):
            best = await _pick_primary_instruction(db, data_source)
            if best is None:
                best = await _synthesize_primary(db, organization, data_source)
            if best is not None:
                data_source.primary_instruction_id = str(best.id)
                changed["primary"] = str(best.id)

        if changed:
            db.add(data_source)
            await db.commit()
            await db.refresh(data_source)
    except Exception as e:  # noqa: BLE001 — fail-soft
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
        logger.warning("autofill_agent_overview failed for %s: %s",
                       getattr(data_source, "id", "?"), e)
        return {"error": str(e)}
    return changed
