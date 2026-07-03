"""Daily offline context pipeline — build once, embed once, read fast.

For every active ``DataSourceTable`` in an org this:
  1. builds the P3 Unified Table Card (``knowledge.table_card.build_table_card``),
     renders it to one tight text block, and PERSISTS it into
     ``DataSourceTable.metadata_json['context_doc'] = {"text", "built_at"}``
     (the durable source of truth — a retrieval read-side prefers this over
     rebuilding the card per request);
  2. embeds each doc once (``ai.knowledge.embeddings.embed_texts``) and upserts
     it into ``knowledge_search_index`` under ``kind='table_card'`` so semantic
     search can rank the merged doc directly.

Design rules (CLAUDE.md HARD RULES 3/4/5):
  * Additive, in a NEW module. Shared files (table_card, embeddings, indexer,
    scheduler, models) are imported read-only, never modified.
  * Gated on ``flags.OFFLINE_CONTEXT`` (env ``HYBRID_OFFLINE_CONTEXT``), default
    OFF → byte-identical no-op.
  * NEVER raises into the caller. Every stage / every table is guarded; a
    failure logs a warning and degrades (skips that table / that org).
  * ``build_table_card`` is itself gated on ``flags.TABLE_CARD`` and returns
    ``{}`` when OFF → this pipeline produces 0 docs unless TABLE_CARD is also ON.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# The knowledge_search_index kind this pipeline owns. Kept distinct from the
# indexer's 'table'/'metric'/'query'/'doc' kinds so an offline build only ever
# rewrites its OWN rows (delete-by-kind + insert), never the FTS assets.
_KSI_KIND = "table_card"


def _is_postgres(db) -> bool:
    """Mirror indexer._is_postgres — vector/tsv DDL is PG-only."""
    try:
        return db.bind.dialect.name == "postgresql"
    except Exception:
        try:
            return db.get_bind().dialect.name == "postgresql"
        except Exception:
            return False


async def _load_org_data_sources(db, org_id: str) -> List[Any]:
    """DataSources for an org, with connections eager-loaded (auth/last_synced)."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from app.models.data_source import DataSource

    stmt = (
        select(DataSource)
        .options(selectinload(DataSource.connections))
        .where(DataSource.organization_id == str(org_id))
    )
    return list((await db.execute(stmt)).scalars().all())


async def _load_active_tables(db, ds_id: str) -> List[Any]:
    """Active DataSourceTables for a source, with the ConnectionTable eager-loaded
    (build_table_card reads columns off the table OR its connection_table)."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from app.models.datasource_table import DataSourceTable
    from app.models.connection_table import ConnectionTable

    stmt = (
        select(DataSourceTable)
        .options(
            selectinload(DataSourceTable.connection_table)
            .selectinload(ConnectionTable.connection)
        )
        .where(
            DataSourceTable.datasource_id == str(ds_id),
            DataSourceTable.is_active == True,  # noqa: E712
        )
    )
    return list((await db.execute(stmt)).scalars().all())


def _persist_context_doc(table: Any, text: str, built_at: str) -> None:
    """Write the rendered card into metadata_json['context_doc'] + flag dirty."""
    meta = table.metadata_json
    meta = dict(meta) if isinstance(meta, dict) else {}
    meta["context_doc"] = {"text": text, "built_at": built_at}
    table.metadata_json = meta
    try:
        from sqlalchemy.orm.attributes import flag_modified

        flag_modified(table, "metadata_json")
    except Exception:
        pass


async def _reindex_context_docs(
    db, organization, docs: List[Tuple[str, str, str]]
) -> int:
    """Rebuild the org's ``kind='table_card'`` rows in knowledge_search_index and
    embed them once. ``docs`` = list of (ref_id, title, body). Returns the number
    of rows that got a real embedding. Fail-soft: any failure returns what it had.

    NOTE (read-side / interaction): the indexer's ``reindex_org`` does a FULL
    org-wide wipe of knowledge_search_index before re-inserting its own kinds, so
    a subsequent FTS reindex would drop these ``table_card`` rows. That is why the
    DURABLE store is ``metadata_json['context_doc']`` — the search-index rows are a
    best-effort semantic accelerator, and a retrieval path should prefer the
    persisted doc first.
    """
    embedded = 0
    try:
        from sqlalchemy import delete as sa_delete, select as sa_select, text as sa_text
        from app.models.knowledge_search_index import KnowledgeSearchIndex

        org_id = str(getattr(organization, "id", None) or "")
        if not org_id:
            return 0

        # Idempotent rebuild of OUR kind only.
        await db.execute(
            sa_delete(KnowledgeSearchIndex).where(
                KnowledgeSearchIndex.org_id == org_id,
                KnowledgeSearchIndex.kind == _KSI_KIND,
            )
        )
        new_rows: List[Any] = []
        for ref_id, title, body in docs:
            row = KnowledgeSearchIndex(
                org_id=org_id, kind=_KSI_KIND, ref_id=str(ref_id),
                title=title or "", body=body or "",
            )
            db.add(row)
            new_rows.append(row)
        await db.commit()
        for row in new_rows:
            await db.refresh(row)

        if not new_rows or not _is_postgres(db):
            return 0

        # PG full-text vector (tsv) for the new rows.
        try:
            await db.execute(sa_text(
                "UPDATE knowledge_search_index "
                "SET tsv = to_tsvector('english', coalesce(title,'') || ' ' || coalesce(body,'')) "
                "WHERE org_id = :org AND kind = :kind"
            ), {"org": org_id, "kind": _KSI_KIND})
            await db.commit()
        except Exception as exc:
            logger.debug("offline_context: tsv update skipped (%s)", exc)

        # Embeddings (best-effort; needs a provider key). Mirrors indexer.reindex_org.
        try:
            from app.settings.hybrid_flags import flags
            from app.ai.knowledge.embeddings import embed_texts, to_pgvector_literal

            if flags.SEMANTIC_SEARCH:
                texts = [f"{r.title or ''}\n{r.body or ''}".strip() for r in new_rows]
                vectors = await embed_texts(db, organization, texts)
                for row, vec in zip(new_rows, vectors):
                    lit = to_pgvector_literal(vec) if vec else None
                    if not lit:
                        continue
                    try:
                        await db.execute(sa_text(
                            "UPDATE knowledge_search_index SET embedding = (:v)::vector WHERE id = :id"
                        ), {"v": lit, "id": str(row.id)})
                        embedded += 1
                    except Exception as exc:
                        logger.debug("offline_context: embedding skipped for %s (%s)", row.id, exc)
                await db.commit()
        except Exception as exc:
            logger.warning("offline_context: embedding phase failed (%s)", exc)
    except Exception as exc:
        logger.warning("offline_context: reindex phase failed (%s)", exc)
        try:
            await db.rollback()
        except Exception:
            pass
    return embedded


async def build_offline_context(db, *, organization_id) -> Dict[str, Any]:
    """Build + persist + embed the merged context doc for every active table in an org.

    Returns counts ``{"data_sources", "tables", "docs", "embedded"}``. Fail-soft
    per table (one bad table never aborts the org). No-op ``{...: 0}`` when the
    flag is off or nothing qualifies. NEVER raises.
    """
    from app.settings.hybrid_flags import flags

    result = {"data_sources": 0, "tables": 0, "docs": 0, "embedded": 0}
    if not flags.OFFLINE_CONTEXT:
        return result

    try:
        from app.services.knowledge.table_card import build_table_card, render_card

        org_id = str(organization_id or "")
        if not org_id:
            return result

        # Load the Organization once (embed_texts + reindex need it).
        from app.models.organization import Organization

        organization = await db.get(Organization, org_id)
        if organization is None:
            return result

        built_at = datetime.now(timezone.utc).isoformat()
        docs: List[Tuple[str, str, str]] = []  # (table_id, table_name, text)

        data_sources = await _load_org_data_sources(db, org_id)
        result["data_sources"] = len(data_sources)

        for ds in data_sources:
            try:
                tables = await _load_active_tables(db, str(ds.id))
            except Exception as exc:
                logger.warning("offline_context: load tables failed for ds %s (%s)", getattr(ds, "id", "?"), exc)
                continue
            result["tables"] += len(tables)

            for table in tables:
                try:
                    card = await build_table_card(
                        db, organization_id=org_id, data_source=ds, table=table
                    )
                    if not card:
                        continue
                    text = render_card(card)
                    if not text or not text.strip():
                        continue
                    _persist_context_doc(table, text, built_at)
                    docs.append((str(table.id), str(getattr(table, "name", "") or ""), text))
                except Exception as exc:  # never let one table abort the org
                    logger.warning(
                        "offline_context: table %s failed (%s)", getattr(table, "id", "?"), exc
                    )
                    continue

        # Commit the persisted context_doc payloads.
        try:
            await db.commit()
        except Exception as exc:
            logger.warning("offline_context: persist commit failed (%s)", exc)
            try:
                await db.rollback()
            except Exception:
                pass

        result["docs"] = len(docs)
        if docs:
            result["embedded"] = await _reindex_context_docs(db, organization, docs)

        logger.info(
            "offline_context: org=%s data_sources=%d tables=%d docs=%d embedded=%d",
            org_id, result["data_sources"], result["tables"], result["docs"], result["embedded"],
        )
        return result
    except Exception as exc:
        logger.warning("build_offline_context failed for org %s: %s", organization_id, exc)
        try:
            await db.rollback()
        except Exception:
            pass
        return result


async def _discover_org_ids(session) -> List[str]:
    """Every org that owns at least one active DataSourceTable. Guarded -> []."""
    try:
        from sqlalchemy import select
        from app.models.data_source import DataSource
        from app.models.datasource_table import DataSourceTable

        rows = (await session.execute(
            select(DataSource.organization_id)
            .join(DataSourceTable, DataSourceTable.datasource_id == DataSource.id)
            .where(DataSourceTable.is_active == True)  # noqa: E712
            .distinct()
        )).all()
        return [str(r[0]) for r in rows if r and r[0]]
    except Exception as exc:
        logger.warning("offline_context: org discovery failed (%s)", exc)
        return []


async def run_scheduled_offline_context() -> Optional[str]:
    """Nightly scheduler entry: rebuild the offline context doc for every org.

    Self-contained (opens its own async session, re-checks the flag). Mirrors
    ``services.eval_harness.run_scheduled_evals``. Returns a short summary string,
    or ``None`` when gated off / on any failure. NEVER raises.
    """
    try:
        from app.settings.hybrid_flags import flags

        if not flags.OFFLINE_CONTEXT:
            return None

        from app.settings.database import create_async_session_factory

        async_session = create_async_session_factory()

        orgs_processed = 0
        docs_total = 0

        async with async_session() as session:
            org_ids = await _discover_org_ids(session)
            for org_id in org_ids:
                try:
                    counts = await build_offline_context(session, organization_id=org_id)
                    orgs_processed += 1
                    docs_total += int(counts.get("docs") or 0)
                except Exception as inner:
                    logger.warning("offline_context: org %s failed: %s", org_id, inner)
                    try:
                        await session.rollback()
                    except Exception:
                        pass
                    continue

        return (
            f"offline_context: built {docs_total} doc(s) across {orgs_processed} org(s)"
        )
    except Exception as e:
        logger.warning("run_scheduled_offline_context failed: %s", e)
        return None
