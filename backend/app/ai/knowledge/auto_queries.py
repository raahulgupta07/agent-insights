"""Auto-generate VERIFIED example SQL for a Studio's pinned sources.

For each Data Source pinned to a Studio, this asks the org's small default model
(via dash's one-shot ``LLM(...).inference`` wrapper, OpenRouter-only) for a small
set of example analytical ``SELECT`` queries grounded ONLY in that source's
schema. Each proposed query is then *verified*: it is checked read-only and RUN
against the live source through dash's standard query path
(``DataSource.get_client().aexecute_query`` -> pandas DataFrame). ONLY queries
that execute without error are saved to the Query Library as reusable, approved
saved queries (status='approved', source='auto').

Reuse, not reinvention (CLAUDE.md HARD RULES):
  * LLM = org small default model resolved by
    ``LLMService().get_default_model(..., is_small=True)``, called via dash's
    one-shot wrapper ``LLM(model, usage_session_maker=async_session_maker)
    .inference(prompt)`` (SYNC -> run in a worker thread).
  * Schema digest = ``knowledge_proposer._introspect_schema_text`` (same renderer
    the artifacts / knowledge-proposer use).
  * Read-only guard = ``routes.knowledge._is_read_only_sql``.
  * Pinned sources = ``StudioDataSource`` -> ``DataSource`` (mirrors
    ``services.studio_artifacts._gather_pinned_schema``).
  * Saved query model = ``QueryLibraryItem`` (dedupe by the unique
    (organization, data_source, name)).

Design rules honored: flag-gated (``flags.AUTO_QUERIES``, default OFF -> no-op);
cheap tier (ONE small-model inference per source, bounded N); NEVER raises into
the caller (all failures are caught and surfaced in the returned dict).
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.brain.knowledge_proposer import _introspect_schema_text
from app.models.data_source import DataSource
from app.models.query_library import QueryLibraryItem
from app.models.studio import StudioDataSource
from app.settings.hybrid_flags import flags
from app.settings.logging_config import get_logger

logger = get_logger(__name__)

# Bound the number of pinned sources processed in one call (cheap tier).
_MAX_SOURCES = 8


def _clean(s: Any) -> str:
    return str(s).strip() if s is not None else ""


def _strip_fences(text: str) -> str:
    """Strip ```json ... ``` / ``` ... ``` fences a model may wrap output in."""
    t = (text or "").strip()
    if t.startswith("```"):
        # drop the first fence line and any trailing fence
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    return t.strip()


def _parse_query_list(text: str) -> List[dict]:
    """Parse the LLM output into a list of {name, description, sql} dicts.

    Tolerant: strips fences, falls back to extracting the first JSON array.
    Returns [] on any junk (never raises).
    """
    raw = _strip_fences(text)
    candidates: List[Any] = []
    try:
        parsed = json.loads(raw)
        candidates = parsed if isinstance(parsed, list) else parsed.get("queries", []) \
            if isinstance(parsed, dict) else []
    except Exception:
        # Fall back to the first [...] block in the text.
        m = re.search(r"\[.*\]", raw, flags=re.DOTALL)
        if m:
            try:
                parsed = json.loads(m.group(0))
                candidates = parsed if isinstance(parsed, list) else []
            except Exception:
                candidates = []

    out: List[dict] = []
    for c in candidates:
        if not isinstance(c, dict):
            continue
        name = _clean(c.get("name"))
        sql = _clean(c.get("sql") or c.get("sql_text"))
        description = _clean(c.get("description"))
        if name and sql:
            out.append({"name": name, "description": description, "sql": sql})
    return out


def _build_prompt(source_name: str, schema_text: str, max_n: int,
                  skill_context: str = "") -> str:
    """One-shot prompt asking for up to N example analytical SELECT queries.

    ``skill_context`` (Phase 4) is the studio's active-skill block; when present
    it biases the proposals toward the queries those skills compute."""
    skill_block = ""
    if skill_context:
        skill_block = (
            "\n\n" + skill_context.strip() +
            "\nWhere the schema supports it, include at least one query per skill "
            "above that computes its headline numbers.\n"
        )
    return (
        "You are a data analyst assistant. Below is the schema of a data source "
        f"named '{source_name}' as a list of `table(col1, col2, ...)` lines. "
        f"Propose up to {max_n} useful EXAMPLE analytical SQL queries that answer "
        "common business questions about this data, grounded ONLY in this schema. "
        "Do NOT invent tables or columns that are not present.\n\n"
        f"Schema:\n{schema_text}\n"
        f"{skill_block}\n"
        "Return ONLY a single JSON array (no prose, no markdown) of objects with "
        "this exact shape:\n"
        '[{"name": "<short distinct query name>", "description": "<one-sentence '
        'description of what the query answers>", "sql": "<a SINGLE read-only '
        'SELECT statement over this schema>"}]\n\n'
        "Rules:\n"
        "- Use table names EXACTLY as written in the schema above, verbatim "
        "(they may be long uuid-prefixed identifiers — do NOT shorten, rename, "
        "or alias them away in the FROM clause).\n"
        "- ALWAYS wrap every table and column identifier in double quotes "
        '(e.g. SELECT "Call Outcome", COUNT(*) FROM "the_exact_table_name" '
        'GROUP BY "Call Outcome") — many names contain spaces, colons or mixed '
        "case and will error unquoted.\n"
        "- Each `sql` MUST be a single read-only SELECT (or WITH ... SELECT) "
        "statement; no semicolons chaining, no writes/DDL.\n"
        "- Each `name` must be short, distinct, human-readable.\n"
        "- Prefer aggregate/analytical queries (counts, sums, group-bys, top-N).\n"
        "- Prefer fewer, high-confidence queries over guessing.\n"
        "- Output the JSON array ONLY."
    )


def _default_infer(model: Any):
    """Build the default SYNC one-shot inference callable (OpenRouter-only)."""
    def infer(prompt: str) -> str:
        from app.ai.llm.llm import LLM
        from app.dependencies import async_session_maker

        return LLM(model, usage_session_maker=async_session_maker).inference(
            prompt, usage_scope="auto_queries"
        )

    return infer


async def _upsert_query(
    db: AsyncSession,
    *,
    org_id: str,
    ds_id: str,
    name: str,
    description: str,
    sql_text: str,
) -> bool:
    """UPSERT a QueryLibraryItem by (org, ds, name). Returns True if a row was
    created or updated. status='approved', source='auto'. Never raises."""
    try:
        res = await db.execute(
            select(QueryLibraryItem).where(
                QueryLibraryItem.organization_id == org_id,
                QueryLibraryItem.data_source_id == ds_id,
                QueryLibraryItem.name == name,
            )
        )
        existing = res.scalar_one_or_none()
        if existing is not None:
            existing.sql_text = sql_text
            if description:
                existing.description = description
            existing.source = "auto"
            existing.status = "approved"
        else:
            db.add(
                QueryLibraryItem(
                    organization_id=org_id,
                    data_source_id=ds_id,
                    name=name,
                    description=description or "",
                    sql_text=sql_text,
                    source="auto",
                    status="approved",
                    run_count=0,
                )
            )
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("auto_queries upsert failed (%s): %s", name, e)
        return False


async def generate_queries_for_studio(
    db: AsyncSession,
    *,
    organization: Any,
    current_user: Any,
    studio_id: str,
    model: Any = None,
    max_per_source: int = 6,
    skill_context: str = "",
) -> dict:
    """Generate + verify example SQL for each of a Studio's pinned sources and
    save the working ones to the Query Library.

    Self-gates on ``flags.AUTO_QUERIES`` (default OFF -> ``{disabled:True}``).
    NEVER raises: any failure returns ``{"ok": False, "error": ..., "saved": N}``.
    """
    saved = 0
    skipped = 0
    by_source: dict = {}

    if not getattr(flags, "AUTO_QUERIES", False):
        return {"disabled": True, "saved": 0}

    try:
        org_id = str(getattr(organization, "id", None) or "")
        if not org_id:
            return {"ok": False, "error": "no organization", "saved": 0}

        try:
            max_n = int(max_per_source)
        except Exception:
            max_n = 6
        max_n = max(1, min(max_n, 12))

        # Resolve the studio's pinned DataSources (mirror studio_artifacts).
        res = await db.execute(
            select(StudioDataSource)
            .where(
                StudioDataSource.studio_id == studio_id,
                StudioDataSource.deleted_at.is_(None),
            )
            .order_by(StudioDataSource.created_at.asc())
        )
        pins = list(res.scalars().all())
        agent_ids = [p.agent_id for p in pins][:_MAX_SOURCES]
        if not agent_ids:
            return {"ok": True, "saved": 0, "by_source": {}, "skipped": 0}

        ds_res = await db.execute(
            select(DataSource).where(
                DataSource.id.in_(agent_ids),
                DataSource.organization_id == org_id,
            )
        )
        sources = list(ds_res.scalars().all())
        if not sources:
            return {"ok": True, "saved": 0, "by_source": {}, "skipped": 0}

        # Resolve the org small default model once if not provided.
        if model is None:
            try:
                from app.services.llm_service import LLMService

                model = await LLMService().get_default_model(
                    db, organization, current_user, is_small=True
                )
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "error": f"no model: {e}", "saved": 0}

        if model is None:
            return {"ok": False, "error": "no default model", "saved": 0}

        infer = _default_infer(model)

        for ds in sources:
            ds_id = str(getattr(ds, "id", "") or "")
            ds_name = getattr(ds, "name", None) or ds_id
            src_saved = 0
            src_skipped = 0

            # 1. Schema digest (guarded; skip sources with no introspectable schema).
            try:
                schema_text, table_names = _introspect_schema_text(ds)
            except Exception:
                schema_text, table_names = "", set()
            if not schema_text or not table_names:
                by_source[ds_name] = {"saved": 0, "skipped": 0, "note": "no schema"}
                continue

            # 2. ONE small-model inference (SYNC -> worker thread).
            try:
                prompt = _build_prompt(ds_name, schema_text, max_n, skill_context)
                raw = await asyncio.to_thread(infer, prompt)
            except Exception as e:  # noqa: BLE001
                logger.warning("auto_queries inference failed for %s: %s", ds_name, e)
                by_source[ds_name] = {"saved": 0, "skipped": 0, "note": "llm error"}
                continue

            proposals = _parse_query_list(raw or "")[:max_n]

            # 3. Verify each proposal read-only + RUN it; save only the working ones.
            try:
                client = ds.get_client()
            except Exception as e:  # noqa: BLE001
                logger.warning("auto_queries client failed for %s: %s", ds_name, e)
                by_source[ds_name] = {"saved": 0, "skipped": 0, "note": "no client"}
                continue

            # Import the guard lazily (avoids importing the routes module at import time).
            from app.routes.knowledge import _is_read_only_sql

            for p in proposals:
                name = p["name"]
                sql = p["sql"]
                description = p.get("description", "")

                if not _is_read_only_sql(sql):
                    src_skipped += 1
                    continue
                try:
                    # Run read-only against the source; success (no error) = verified.
                    await client.aexecute_query(sql)
                except Exception:  # noqa: BLE001 - bad query, skip it
                    src_skipped += 1
                    continue

                ok = await _upsert_query(
                    db,
                    org_id=org_id,
                    ds_id=ds_id,
                    name=name,
                    description=description,
                    sql_text=sql,
                )
                if ok:
                    src_saved += 1
                else:
                    src_skipped += 1

            saved += src_saved
            skipped += src_skipped
            by_source[ds_name] = {"saved": src_saved, "skipped": src_skipped}

        # Persist all the saved rows once.
        if saved:
            await db.commit()

        return {"ok": True, "saved": saved, "by_source": by_source, "skipped": skipped}

    except Exception as e:  # noqa: BLE001 - never raise into the caller
        logger.warning("generate_queries_for_studio failed: %s", e)
        try:
            await db.rollback()
        except Exception:
            pass
        return {"ok": False, "error": str(e), "saved": saved}
