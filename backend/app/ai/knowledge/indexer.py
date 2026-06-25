"""Indexer for the knowledge_search_index (Hybrid Search population).

Rebuilds the per-org unified search index from the APPROVED knowledge assets:
    kind='table'  -> semantic_tables (description + use_cases)
    kind='metric' -> metric_definitions (definition + sql_calc)
    kind='query'  -> query_library_items (description + sql_text)
    kind='doc'    -> knowledge_docs (body)

For each row it sets the base columns (via ORM), the PG ``tsv`` (to_tsvector) and,
when an embedder is available, the ``embedding`` vector(1536) (OpenRouter
text-embedding-3-small). All vector/FTS DDL is PG-only and fail-soft — on SQLite
or any error those columns are skipped and the vectorless path still works.

Gated by flags.SEMANTIC_SEARCH at the route layer; this module assumes the caller
already checked the flag.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from sqlalchemy import select, text as sa_text

log = logging.getLogger(__name__)

_APPROVED = ("approved", "published")


def _is_postgres(db) -> bool:
    try:
        return db.bind.dialect.name == "postgresql"
    except Exception:
        try:
            return db.get_bind().dialect.name == "postgresql"
        except Exception:
            return False


async def _gather_assets(db, org_id: str) -> List[Dict[str, Any]]:
    """Collect (kind, ref_id, title, body) for every approved knowledge asset."""
    assets: List[Dict[str, Any]] = []

    from app.models.semantic_table import SemanticTable
    from app.models.metric_definition import MetricDefinition
    from app.models.query_library import QueryLibraryItem
    from app.models.knowledge_doc import KnowledgeDoc

    # Semantic tables
    try:
        rows = (await db.execute(
            select(SemanticTable).where(
                SemanticTable.organization_id == org_id,
                SemanticTable.status.in_(_APPROVED),
            )
        )).scalars().all()
        for r in rows:
            use_cases = r.use_cases if isinstance(r.use_cases, list) else []
            body = " ".join([r.description or ""] + [str(u) for u in use_cases]).strip()
            assets.append({"kind": "table", "ref_id": str(r.id),
                           "title": r.table_name or "", "body": body})
    except Exception as exc:
        log.debug("indexer: semantic_tables skipped (%s)", exc)

    # Metrics
    try:
        rows = (await db.execute(
            select(MetricDefinition).where(
                MetricDefinition.organization_id == org_id,
                MetricDefinition.status.in_(_APPROVED),
            )
        )).scalars().all()
        for r in rows:
            body = " ".join([r.definition or "", r.table_ref or "", r.sql_calc or ""]).strip()
            assets.append({"kind": "metric", "ref_id": str(r.id),
                           "title": r.name or "", "body": body})
    except Exception as exc:
        log.debug("indexer: metrics skipped (%s)", exc)

    # Query library
    try:
        rows = (await db.execute(
            select(QueryLibraryItem).where(
                QueryLibraryItem.organization_id == org_id,
                QueryLibraryItem.status.in_(_APPROVED),
            )
        )).scalars().all()
        for r in rows:
            body = " ".join([r.description or "", r.sql_text or ""]).strip()
            assets.append({"kind": "query", "ref_id": str(r.id),
                           "title": r.name or "", "body": body})
    except Exception as exc:
        log.debug("indexer: query_library skipped (%s)", exc)

    # Knowledge docs
    try:
        rows = (await db.execute(
            select(KnowledgeDoc).where(
                KnowledgeDoc.organization_id == org_id,
                KnowledgeDoc.status.in_(_APPROVED),
            )
        )).scalars().all()
        for r in rows:
            assets.append({"kind": "doc", "ref_id": str(r.id),
                           "title": r.title or "", "body": (r.body or "")[:20000]})
    except Exception as exc:
        log.debug("indexer: knowledge_docs skipped (%s)", exc)

    return assets


async def index_count(db, org_id: str) -> int:
    """How many rows are currently indexed for this org."""
    try:
        from app.models.knowledge_search_index import KnowledgeSearchIndex
        from sqlalchemy import func
        n = (await db.execute(
            select(func.count(KnowledgeSearchIndex.id)).where(
                KnowledgeSearchIndex.org_id == org_id,
                KnowledgeSearchIndex.deleted_at.is_(None),
            )
        )).scalar()
        return int(n or 0)
    except Exception:
        return 0


async def reindex_org(db, organization) -> Dict[str, Any]:
    """Full rebuild of the org's search index. Returns a summary dict.

    Steps: gather approved assets -> wipe old rows -> insert base rows ->
    set tsv (PG) -> embed + set vectors (PG, best-effort).
    """
    from app.models.knowledge_search_index import KnowledgeSearchIndex
    from sqlalchemy import delete as sa_delete

    org_id = str(getattr(organization, "id", None) or "")
    if not org_id:
        return {"indexed": 0, "embedded": 0, "error": "no org"}

    assets = await _gather_assets(db, org_id)

    # Wipe + re-insert base rows (full rebuild keeps it simple + consistent).
    await db.execute(sa_delete(KnowledgeSearchIndex).where(KnowledgeSearchIndex.org_id == org_id))
    new_rows: List[KnowledgeSearchIndex] = []
    for a in assets:
        row = KnowledgeSearchIndex(
            org_id=org_id, kind=a["kind"], ref_id=a["ref_id"],
            title=a["title"] or "", body=a["body"] or "",
        )
        db.add(row)
        new_rows.append(row)
    await db.commit()
    for row in new_rows:
        await db.refresh(row)

    indexed = len(new_rows)
    embedded = 0
    pg = _is_postgres(db)

    # PG full-text vector (tsv) — one statement for the whole org.
    if pg and indexed:
        try:
            await db.execute(sa_text(
                "UPDATE knowledge_search_index "
                "SET tsv = to_tsvector('english', coalesce(title,'') || ' ' || coalesce(body,'')) "
                "WHERE org_id = :org"
            ), {"org": org_id})
            await db.commit()
        except Exception as exc:
            log.debug("indexer: tsv update skipped (%s)", exc)

    # Embeddings (best-effort; needs a provider key). PG only.
    if pg and indexed:
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
                        log.debug("indexer: embedding update skipped for %s (%s)", row.id, exc)
                await db.commit()
        except Exception as exc:
            log.warning("indexer: embedding phase failed (%s)", exc)

    log.info("indexer: org=%s indexed=%d embedded=%d", org_id, indexed, embedded)
    return {"indexed": indexed, "embedded": embedded}
