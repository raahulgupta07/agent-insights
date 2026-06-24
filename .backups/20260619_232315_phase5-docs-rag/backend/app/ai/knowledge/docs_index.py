"""DOCS INDEX (Phase-5 DOCS RAG) — ingest + retrieve company documents.

VECTORLESS by design. No embedding client exists anywhere in this image (see the
CLAUDE landmines: the skills top-K, semantic/metrics top-K, and reasoning-cache
all rank with token-Jaccard, never embeddings). So retrieval here is **Postgres
full-text search** — ``to_tsvector('english', text)`` matched against
``plainto_tsquery('english', :q)`` and ranked by ``ts_rank``. A GIN functional
index ``ix_knowledge_doc_chunks_fts`` on ``to_tsvector('english', text)`` already
exists via migration, so the search is index-backed. A pgvector upgrade is a
later flag-gated follow-up, not required for the Phase-5 gate (a term-definition
question resolving from an approved doc).

Design invariants (mirrors the rest of the hybrid knowledge layer):

* **Approval gate.** An ingested doc lands ``status='pending'``. ONLY
  ``status='approved'`` docs (and their chunks) surface in :func:`search_docs`,
  so a freshly ingested doc is automatically invisible until a human approves it
  (mirrors the JOIN_MINER / SemanticTable / BrainGraphEdge convention).
* **Dedupe.** A re-ingest of the same ``(organization, data_source, content)``
  is UPSERTed in place rather than duplicated; identical body is a soft skip.
* **Fail-soft retrieval.** :func:`search_docs` degrades silently to ``[]`` on ANY
  error (e.g. SQLite dev has no ``to_tsvector`` — the whole body is guarded).
  Ingest is NOT fully swallowed: on error it rolls back and re-raises so the
  caller route can surface the failure to the uploader.

Public surface:
    _chunk_text(body, target, overlap)  -> list[str]          (pure)
    _content_hash(title, body)          -> str                (pure)
    ingest_doc(db, *, organization, title, body, ...) -> dict
    search_docs(db, *, organization, query, ...)      -> list[dict]
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

# Defensive cap on chunks per doc — a runaway body should not explode the table.
_MAX_CHUNKS = 200
# Minimum useful chunk length (drop tiny fragments left over by splitting).
_MIN_CHUNK_CHARS = 1

# Paragraph / sentence boundary splitters for the chunker.
_PARA_RE = re.compile(r"\n\s*\n")
_SENT_RE = re.compile(r"(?<=[.!?])\s+")


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def _content_hash(title: str, body: str) -> str:
    """Stable sha256 hexdigest of ``f"{title}\\n{body}"``. Pure, never raises."""
    payload = f"{title or ''}\n{body or ''}".encode("utf-8", errors="replace")
    return hashlib.sha256(payload).hexdigest()


def _chunk_text(body: str, target: int = 1000, overlap: int = 100) -> List[str]:
    """Split ``body`` into ~``target``-char chunks. Pure, never raises.

    Strategy (largest boundary first, so we keep coherent units):

    1. Split into paragraphs on blank lines. A paragraph that already fits in
       ``target`` becomes (part of) a chunk.
    2. A paragraph longer than ``target`` is further split on sentence
       boundaries; sentences are packed greedily up to ``target``.
    3. A single sentence longer than ``target`` is hard-sliced by character.

    Consecutive small pieces are packed together up to ``target`` so we don't
    emit a swarm of tiny chunks. A small ``overlap`` of trailing characters from
    the previous chunk is prepended to the next (helps a term straddling a
    boundary stay searchable in at least one chunk). Empty / whitespace-only
    chunks are dropped and the result is capped at ``_MAX_CHUNKS``.
    """
    if not body or not isinstance(body, str):
        return []
    try:
        target = max(1, int(target))
    except Exception:
        target = 1000
    try:
        overlap = max(0, int(overlap))
    except Exception:
        overlap = 100
    # Overlap must be strictly smaller than target or packing can't make progress.
    if overlap >= target:
        overlap = target // 4

    # --- 1. break the body into atomic "units" no larger than `target` -------
    units: List[str] = []
    for para in _PARA_RE.split(body):
        para = para.strip()
        if not para:
            continue
        if len(para) <= target:
            units.append(para)
            continue
        # Paragraph too big -> split into sentences.
        for sent in _SENT_RE.split(para):
            sent = sent.strip()
            if not sent:
                continue
            if len(sent) <= target:
                units.append(sent)
                continue
            # Sentence still too big -> hard char-slice.
            for i in range(0, len(sent), target):
                piece = sent[i:i + target].strip()
                if piece:
                    units.append(piece)

    # --- 2. greedily pack units into ~target chunks, with small overlap ------
    chunks: List[str] = []
    cur = ""
    for unit in units:
        if not cur:
            cur = unit
        elif len(cur) + 1 + len(unit) <= target:
            cur = f"{cur} {unit}"
        else:
            chunks.append(cur)
            tail = cur[-overlap:] if overlap and len(cur) > overlap else (cur if overlap else "")
            # Start the next chunk with the overlap tail (if any) + this unit.
            cur = f"{tail} {unit}".strip() if tail else unit
        if len(chunks) >= _MAX_CHUNKS:
            break
    if cur and len(chunks) < _MAX_CHUNKS:
        chunks.append(cur)

    # --- 3. final clean: drop empties, cap ----------------------------------
    out = [c.strip() for c in chunks if c and c.strip() and len(c.strip()) >= _MIN_CHUNK_CHARS]
    return out[:_MAX_CHUNKS]


# ---------------------------------------------------------------------------
# Ingest (ORM, async session)
# ---------------------------------------------------------------------------

async def ingest_doc(
    db: Any,
    *,
    organization: Any,
    title: str,
    body: str,
    source: str = "upload",
    data_source_id: Optional[str] = None,
    url: Optional[str] = None,
) -> dict:
    """Ingest (or re-ingest) one document for an org, chunk it, and persist.

    UPSERT keyed on ``(organization_id, data_source_id, content_hash)``:

    * **Existing (non-deleted) match** — update its ``title/body/source/url``,
      reset ``status`` back to ``'pending'`` (re-approval required), drop and
      re-insert its chunks. If the body is byte-identical we soft-skip the
      re-chunk (the row already reflects this content) and report ``deduped``.
    * **No match** — INSERT a new ``KnowledgeDoc(status='pending')`` tagged
      ``structured_data={"origin": "docs_index"}``.

    Chunks are produced by :func:`_chunk_text` and one ``KnowledgeDocChunk`` is
    written per chunk. Commits once. On any exception we ``rollback`` and
    re-raise (the caller route owns user-facing error handling).

    Returns ``{"doc_id": <id>, "chunks": <n>, "deduped": <bool>}``.
    """
    from sqlalchemy import select, delete
    from app.models.knowledge_doc import KnowledgeDoc, KnowledgeDocChunk

    org_id = str(getattr(organization, "id", None) or "")
    if not org_id:
        raise ValueError("ingest_doc: organization has no id")

    title = title or ""
    body = body or ""
    content_hash = _content_hash(title, body)

    try:
        # --- locate an existing (non-deleted) doc for this dedupe key --------
        existing_q = select(KnowledgeDoc).where(
            KnowledgeDoc.organization_id == org_id,
            KnowledgeDoc.data_source_id == data_source_id,
            KnowledgeDoc.content_hash == content_hash,
            KnowledgeDoc.deleted_at.is_(None),
        )
        existing = (await db.execute(existing_q)).scalar_one_or_none()

        deduped = existing is not None

        if existing is not None:
            # Body identical (same content_hash) -> soft skip re-chunk; just
            # refresh display fields + reset approval. Chunks already reflect it.
            body_identical = (existing.body or "") == body
            existing.title = title
            existing.source = source
            existing.url = url
            existing.body = body
            existing.status = "pending"

            if body_identical:
                # Count existing live chunks for an accurate return value.
                cnt_rows = (
                    await db.execute(
                        select(KnowledgeDocChunk.id).where(
                            KnowledgeDocChunk.doc_id == existing.id,
                            KnowledgeDocChunk.deleted_at.is_(None),
                        )
                    )
                ).all()
                await db.commit()
                return {"doc_id": existing.id, "chunks": len(cnt_rows), "deduped": True}

            doc = existing
            # Hard-delete child rows (a re-chunk fully replaces them).
            await db.execute(
                delete(KnowledgeDocChunk).where(KnowledgeDocChunk.doc_id == doc.id)
            )
        else:
            doc = KnowledgeDoc(
                organization_id=org_id,
                data_source_id=data_source_id,
                title=title,
                source=source,
                body=body,
                url=url,
                content_hash=content_hash,
                status="pending",
                structured_data={"origin": "docs_index"},
            )
            db.add(doc)
            # Flush so doc.id is populated for the FK on the chunk rows.
            await db.flush()

        # --- re-chunk + insert ----------------------------------------------
        chunks = _chunk_text(body)
        for idx, text_chunk in enumerate(chunks):
            db.add(
                KnowledgeDocChunk(
                    organization_id=org_id,
                    doc_id=doc.id,
                    chunk_index=idx,
                    text=text_chunk,
                )
            )

        await db.commit()
        return {"doc_id": doc.id, "chunks": len(chunks), "deduped": deduped}
    except Exception as e:
        logger.warning("docs_index: ingest_doc failed: %s", e)
        try:
            await db.rollback()
        except Exception:
            pass
        raise


# ---------------------------------------------------------------------------
# Retrieve (raw PG full-text search, fail-soft)
# ---------------------------------------------------------------------------

async def search_docs(
    db: Any,
    *,
    organization: Any,
    query: str,
    data_source_id: Optional[str] = None,
    k: int = 4,
) -> List[dict]:
    """Full-text-search approved doc chunks for an org. Fail-soft -> [] on error.

    Ranks ``knowledge_doc_chunks`` whose PARENT ``knowledge_docs`` row is
    ``status='approved'`` and not soft-deleted, scoped to the org and (when
    given) the data source OR org-wide (``data_source_id IS NULL``) docs. Uses
    ``plainto_tsquery`` + ``ts_rank`` against the GIN-indexed
    ``to_tsvector('english', c.text)``.

    The whole body is guarded: any error (notably SQLite dev, which has no
    ``to_tsvector``) degrades silently to ``[]``. When ``data_source_id`` is
    ``None`` the ds filter clause is omitted entirely (we never bind a NULL into
    an ``= :ds`` comparison).

    Returns ``[{"doc_id", "title", "text", "rank": float}, ...]`` (≤ ``k``).
    """
    if not query or not query.strip():
        return []

    org_id = str(getattr(organization, "id", None) or "")
    if not org_id:
        return []

    try:
        from sqlalchemy import text

        try:
            k_int = max(1, int(k))
        except Exception:
            k_int = 4

        # Build the ds-scope clause without binding NULL into `= :ds`.
        if data_source_id is not None:
            ds_clause = "AND (d.data_source_id = :ds OR d.data_source_id IS NULL)"
        else:
            ds_clause = ""

        sql = text(
            f"""
            SELECT
                d.id    AS doc_id,
                d.title AS title,
                c.text  AS text,
                ts_rank(
                    to_tsvector('english', c.text),
                    plainto_tsquery('english', :q)
                ) AS rank
            FROM knowledge_doc_chunks c
            JOIN knowledge_docs d ON d.id = c.doc_id
            WHERE d.organization_id = :org
              AND d.status = 'approved'
              AND d.deleted_at IS NULL
              {ds_clause}
              AND c.deleted_at IS NULL
              AND to_tsvector('english', c.text) @@ plainto_tsquery('english', :q)
            ORDER BY ts_rank(
                to_tsvector('english', c.text),
                plainto_tsquery('english', :q)
            ) DESC
            LIMIT :k
            """
        )

        params: dict = {"org": org_id, "q": query, "k": k_int}
        if data_source_id is not None:
            params["ds"] = data_source_id

        res = await db.execute(sql, params)
        rows = res.mappings().all()

        out: List[dict] = []
        for row in rows:
            out.append(
                {
                    "doc_id": row["doc_id"],
                    "title": row["title"] or "",
                    "text": row["text"] or "",
                    "rank": float(row["rank"] or 0.0),
                }
            )
        return out
    except Exception as e:
        # SQLite dev has no FTS; ANY failure degrades silently per the spec.
        logger.debug("docs_index: search_docs degraded to []: %s", e)
        return []
