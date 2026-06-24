"""Studio artifacts generation (hybrid Studios ST4).

Generate NotebookLM-style artifacts — an auto-summary, an FAQ, or a briefing —
by introspecting the schemas of a Studio's *pinned* Data Agents (DataSource
rows pinned via ``studio_data_sources``) and running ONE cheap LLM call over a
compact schema digest. User-saved notes are handled in the route (no LLM).

Reuse, not reinvention (CLAUDE.md HARD RULE: no second LLM client):
  * LLM  = the org's *small* default model resolved by
    ``LLMService().get_default_model(..., is_small=True)``, called via dash's
    one-shot wrapper ``LLM(model, usage_session_maker=async_session_maker)
    .inference(prompt)`` — the exact shape the distiller / knowledge proposer
    use. The call is synchronous, so we run it in a worker thread.
  * Schema = reuses ``app.ai.brain.knowledge_proposer._introspect_schema_text``
    (``data_source.get_client().get_schemas()`` -> ``table(col1, col2, ...)``).

Design rules honored:
  * Cheap tier: ONE small-model inference per generate, bounded prompt size.
  * Flag gate (``flags.STUDIOS``) + access checks live in the route, not here.
  * Guarded: schema introspection degrades to a no-op per source; an empty
    schema across all pinned sources raises a clear ValueError the route turns
    into a 400 so the user gets a useful message rather than a blank artifact.
"""

from __future__ import annotations

import asyncio
from typing import Any, List, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.brain.knowledge_proposer import _introspect_schema_text
from app.models.data_source import DataSource
from app.models.studio import StudioDataSource
from app.settings.logging_config import get_logger

logger = get_logger(__name__)

# Artifact kinds the generator produces. The route imports this set to validate
# the requested ``kind``. ``summary``/``faq``/``briefing``/``kpi_pack``/``notes``
# are LLM-generated; ``data_dictionary`` is built deterministically (no LLM).
GENERATED_KINDS = {
    "summary",
    "faq",
    "briefing",
    "notes",
    "kpi_pack",
    "data_dictionary",
}

# Bound the number of pinned sources folded into one prompt (cheap tier).
_MAX_SOURCES = 8


async def _gather_pinned_schema(
    db: AsyncSession, studio, organization
) -> Tuple[str, List[str]]:
    """Build a compact schema digest over the Studio's pinned Data Agents.

    Returns ``(digest_text, source_names)``. Sources whose schema can't be
    introspected are skipped (guarded). Org-scoped: only DataSources owned by
    the studio's organization are read.
    """
    org_id = getattr(organization, "id", None) or getattr(studio, "organization_id", None)

    res = await db.execute(
        select(StudioDataSource)
        .where(
            StudioDataSource.studio_id == studio.id,
            StudioDataSource.deleted_at.is_(None),
        )
        .order_by(StudioDataSource.created_at.asc())
    )
    pins = list(res.scalars().all())
    if not pins:
        return "", []

    agent_ids = [p.agent_id for p in pins][:_MAX_SOURCES]
    ds_res = await db.execute(
        select(DataSource).where(
            DataSource.id.in_(agent_ids),
            DataSource.organization_id == org_id,
        )
    )
    sources = list(ds_res.scalars().all())

    blocks: List[str] = []
    names: List[str] = []
    for ds in sources:
        ds_name = getattr(ds, "name", None) or str(getattr(ds, "id", ""))
        # Reuse the knowledge-proposer schema renderer: table(col, col, ...).
        schema_text, table_names = _introspect_schema_text(ds)
        if not schema_text or not table_names:
            continue
        names.append(ds_name)
        blocks.append(f"## Source: {ds_name}\n{schema_text}")

    return "\n\n".join(blocks), names


async def _gather_pinned_sources(
    db: AsyncSession, studio, organization
) -> List[DataSource]:
    """Resolve the Studio's pinned DataSource rows (org-scoped, bounded).

    Mirrors ``_gather_pinned_schema``'s pin->DataSource resolution but returns
    the ORM rows so the deterministic data-dictionary can read stored column
    intelligence. Guarded; returns ``[]`` on any failure.
    """
    try:
        org_id = getattr(organization, "id", None) or getattr(
            studio, "organization_id", None
        )
        res = await db.execute(
            select(StudioDataSource)
            .where(
                StudioDataSource.studio_id == studio.id,
                StudioDataSource.deleted_at.is_(None),
            )
            .order_by(StudioDataSource.created_at.asc())
        )
        pins = list(res.scalars().all())
        if not pins:
            return []
        agent_ids = [p.agent_id for p in pins][:_MAX_SOURCES]
        ds_res = await db.execute(
            select(DataSource).where(
                DataSource.id.in_(agent_ids),
                DataSource.organization_id == org_id,
            )
        )
        return list(ds_res.scalars().all())
    except Exception as e:  # pragma: no cover - fail-soft
        logger.warning("studio_artifacts._gather_pinned_sources failed: %s", e)
        return []


def _fmt_pct(val: Any) -> str:
    """Render a null-fraction/percentage value as ``NN%`` (best-effort)."""
    try:
        if val is None:
            return ""
        num = float(val)
        # Stored as a fraction (0..1) in some profilers, a percent in others.
        if num <= 1.0:
            num *= 100.0
        return f"{num:.0f}%"
    except Exception:
        return ""


def _fmt_values(values: Any, limit: int = 5) -> str:
    """Render a short, table-cell-safe list of sample values."""
    if not isinstance(values, (list, tuple)):
        return ""
    out: List[str] = []
    for v in values[:limit]:
        s = str(v).replace("|", "/").replace("\n", " ").strip()
        if len(s) > 24:
            s = s[:23] + "…"
        if s:
            out.append(s)
    return ", ".join(out)


async def _build_data_dictionary(db: AsyncSession, studio, organization) -> str:
    """DETERMINISTIC (no LLM) Markdown data dictionary over pinned sources.

    Reads the already-stored column intelligence on each active
    ``DataSourceTable``: ``columns`` is a list of dicts; per column it reads
    ``entry["name"]`` and ``entry["metadata"]`` -> ``role``/``distinct``/
    ``null_pct``/``values`` (the same keys ``column_profile.get_column_intel``
    writes). Columns lacking metadata still emit a row with blank cells.
    Always returns a string; never raises.
    """
    from app.models.datasource_table import DataSourceTable

    header = (
        "# Data dictionary\n\n"
        "| Column | Table | Role | Distinct | Null % | Sample values |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
    )

    try:
        sources = await _gather_pinned_sources(db, studio, organization)
        if not sources:
            return header + "| _(no pinned sources)_ |  |  |  |  |  |\n"

        rows: List[str] = []
        for ds in sources:
            ds_name = getattr(ds, "name", None) or str(getattr(ds, "id", ""))
            try:
                t_res = await db.execute(
                    select(DataSourceTable).where(
                        DataSourceTable.datasource_id == str(ds.id),
                        DataSourceTable.is_active == True,  # noqa: E712
                    )
                )
                tables = list(t_res.scalars().all())
            except Exception as e:  # pragma: no cover - fail-soft per source
                logger.warning(
                    "studio_artifacts data_dictionary: table load failed for %s: %s",
                    ds_name,
                    e,
                )
                tables = []

            for t in tables:
                t_name = getattr(t, "name", None) or ""
                # Qualify the table with its source so multi-source dicts are clear.
                t_label = f"{ds_name}.{t_name}" if t_name else ds_name
                cols = t.columns if isinstance(t.columns, list) else []
                for entry in cols:
                    if not isinstance(entry, dict):
                        continue
                    name = entry.get("name") or ""
                    meta = entry.get("metadata")
                    meta = meta if isinstance(meta, dict) else {}
                    role = meta.get("role") or ""
                    distinct = meta.get("distinct")
                    distinct_s = "" if distinct is None else str(distinct)
                    null_s = _fmt_pct(meta.get("null_pct"))
                    values_s = _fmt_values(meta.get("values"))
                    name_s = str(name).replace("|", "/")
                    rows.append(
                        f"| {name_s} | {t_label} | {role} | {distinct_s} "
                        f"| {null_s} | {values_s} |"
                    )

        if not rows:
            return header + "| _(no columns found)_ |  |  |  |  |  |\n"
        return header + "\n".join(rows) + "\n"
    except Exception as e:  # pragma: no cover - never raise
        logger.warning("studio_artifacts._build_data_dictionary failed: %s", e)
        return header + "| _(data dictionary unavailable)_ |  |  |  |  |  |\n"


def _build_prompt(kind: str, source_names: List[str], schema_digest: str) -> str:
    """Compose the one-shot generation prompt for the given artifact kind.

    Pure/deterministic. The prompt is grounded ONLY in the pinned sources'
    schemas; the model is told not to invent tables/columns.
    """
    sources_line = ", ".join(source_names) if source_names else "the pinned data sources"

    if kind == "faq":
        task = (
            "Write a concise FAQ a new analyst would have about this data. "
            "Produce 6-10 question/answer pairs. Each question should be a "
            "realistic business or data question answerable from these tables; "
            "each answer should be 1-2 sentences and reference the relevant "
            "table(s) by name. Format as Markdown with **Q:** / **A:** lines."
        )
    elif kind == "briefing":
        task = (
            "Write a short executive briefing (Markdown, ~200-300 words) that "
            "explains what this data covers, the main entities/tables and how "
            "they relate, and the kinds of questions it can answer. Use a few "
            "headings and a short bulleted 'Suggested questions' list at the end."
        )
    elif kind == "kpi_pack":
        task = (
            "Produce a Markdown 'KPI Pack': 4-8 key metrics that matter for this "
            "data. For EACH metric use a `### <Metric name>` heading, then a "
            "one-line plain-English definition, then a fenced ```sql code block "
            "with a concrete SQL snippet that computes it. Reference only real "
            "tables/columns from the schema; keep each SQL snippet short and "
            "self-contained. No intro paragraph — start with the first metric."
        )
    elif kind == "notes":
        task = (
            "Write short 'Analyst notes & caveats' (Markdown, bulleted, ~120-200 "
            "words) inferred ONLY from the schema: likely data-quality gotchas, "
            "columns that look sparse or optional, weak or ambiguous join keys "
            "between tables, and any date/time columns that warrant a date-range "
            "check before filtering. Be specific and reference tables/columns by "
            "name. If something cannot be inferred from the schema, do not invent it."
        )
    else:  # summary (default)
        task = (
            "Write a clear summary (Markdown, ~120-180 words) of what this data "
            "is about: the key tables, what each represents, and the analyses it "
            "supports. Reference tables by name. End with one sentence on the "
            "most valuable insight this data could surface."
        )

    return (
        "You are documenting an analytics workspace (a 'Studio') that is "
        f"grounded on these data sources: {sources_line}.\n\n"
        "Below is the schema of each pinned source as a list of "
        "`table(col1, col2, ...)` lines. Ground everything you write ONLY in "
        "this schema — do NOT invent tables, columns, or facts that are not "
        "present.\n\n"
        f"Schema:\n{schema_digest}\n\n"
        f"Task: {task}\n\n"
        "Output ONLY the Markdown artifact, no preamble, no code fences."
    )


async def generate_artifact(db: AsyncSession, studio, kind: str, *, organization=None) -> str:
    """Generate an artifact body for ``kind`` over the Studio's pinned sources.

    ``kind`` must be in :data:`GENERATED_KINDS`. ``data_dictionary`` is built
    deterministically from stored column intelligence (no LLM, never raises);
    the others (``summary``/``faq``/``briefing``/``kpi_pack``/``notes``) run one
    cheap small-model call over a compact schema digest.

    Returns the generated Markdown content. For the LLM kinds, raises
    ``ValueError`` when the kind is unsupported, no model is configured, or none
    of the pinned sources expose an introspectable schema (the route maps these
    to 400s).
    """
    kind = (kind or "").strip().lower()
    if kind not in GENERATED_KINDS:
        raise ValueError(f"Unsupported generated artifact kind: {kind!r}")

    # Deterministic, no-LLM kind: build directly from stored column intelligence.
    if kind == "data_dictionary":
        return await _build_data_dictionary(db, studio, organization)

    schema_digest, source_names = await _gather_pinned_schema(db, studio, organization)
    if not schema_digest:
        raise ValueError(
            "No introspectable schema on the studio's pinned sources. "
            "Pin at least one connected Data Agent before generating an artifact."
        )

    # Resolve the org's small/cheap default model (reuse, no new infra).
    from app.services.llm_service import LLMService

    model = await LLMService().get_default_model(
        db, organization, getattr(studio, "owner_user_id", None), is_small=True
    )
    if model is None:
        raise ValueError("No LLM model is configured for this organization.")

    prompt = _build_prompt(kind, source_names, schema_digest)

    # dash's LLM wrapper .inference() is synchronous — run it off the event loop.
    def _infer() -> str:
        from app.ai.llm.llm import LLM
        from app.dependencies import async_session_maker

        return LLM(model, usage_session_maker=async_session_maker).inference(prompt)

    try:
        text = await asyncio.to_thread(_infer)
    except Exception as e:
        logger.warning("studio_artifacts.generate_artifact LLM call failed: %s", e)
        raise ValueError("Artifact generation failed while calling the model.") from e

    content = (text or "").strip()
    if not content:
        raise ValueError("The model returned an empty artifact.")
    return content
