"""Generic file -> searchable Knowledge (any file, any type).

An attached document (PDF, Word, PowerPoint, plain text, Markdown, HTML, JSON,
or a spreadsheet used as reference rather than a queryable table) carries text
the agent should be able to CITE — definitions, Q&A logic, an explanation deck,
a policy PDF. Today those files sit as raw `data_source_file_association` rows
that never reach the Knowledge layer, so the agent can't quote them.

This module closes that gap generically:

    file (any supported ext) -> _extract_text() -> docs_index.ingest_doc()
        -> KnowledgeDoc(+chunks) -> (approved) -> hybrid index

Design:
* **Any type.** Extension dispatch with graceful skip on an unknown/unsupported
  type — never a hard failure. Reuses the battle-tested ingest_brain extractors
  (pdf/docx/pptx, which themselves never raise) + light readers for text-ish
  files. A spreadsheet is digested as reference text (sheet -> rows) so a
  definitions/glossary workbook is searchable even though it's also a table.
* **Flag-gated + fail-soft.** Gated by `HYBRID_DOC_KNOWLEDGE`; every failure is
  swallowed so it can NEVER block an upload or a training run.
* **Idempotent.** `ingest_doc` UPSERTs on (org, data_source, content_hash), so
  re-running (upload hook AND train stage) does not duplicate.
* **First-party = approved.** A file the user explicitly attached is source
  material, not a distilled guess, so it lands `approved` (immediately usable)
  rather than `pending` — unlike learned memories which stay gated.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Extensions that carry prose we can extract. CSV/TSV are intentionally EXCLUDED
# by default — those are queryable tables, not documents — unless the caller
# forces them. Spreadsheets ARE included: a reference/definitions workbook is
# common and its text is valuable even when the same file is also a table.
DOC_EXTS = {
    ".pdf", ".docx", ".doc", ".pptx", ".ppt",
    ".txt", ".md", ".markdown", ".rst",
    ".html", ".htm", ".json", ".yaml", ".yml",
    ".xlsx", ".xlsm", ".xls",
}

_TABULAR_EXTS = {".csv", ".tsv"}
_MAX_CHARS = 200_000  # cap a single doc's body so one huge file can't blow up chunks


def is_doc_file(filename: str) -> bool:
    """True when the file looks like a document we can turn into knowledge."""
    ext = os.path.splitext(filename or "")[1].lower()
    return ext in DOC_EXTS


def _resolve_upload_path(stored_path: str) -> Optional[str]:
    """Resolve a File.path to an absolute on-disk path (mirrors the from-file route)."""
    if not stored_path:
        return None
    if os.path.isabs(stored_path) and os.path.exists(stored_path):
        return stored_path
    base = os.path.basename(stored_path)
    for root in ("uploads/files", os.path.join(os.getcwd(), "uploads", "files")):
        cand = os.path.join(root, base)
        if os.path.exists(cand):
            return cand
    if os.path.exists(stored_path):
        return stored_path
    return None


def _strip_html(raw: str) -> str:
    try:
        from bs4 import BeautifulSoup  # F09 dep, present in the image
        return BeautifulSoup(raw, "html.parser").get_text("\n")
    except Exception:  # noqa: BLE001 — fall back to a crude tag strip
        import re
        return re.sub(r"<[^>]+>", " ", raw)


def _prose_from_extractor(fn, path: str, filename: str) -> str:
    """Run an ingest_brain extractor -> join its ProseBlock bodies (+ table text)."""
    tables, prose = fn(path, filename=filename)
    parts = [p.body for p in (prose or []) if getattr(p, "body", "").strip()]
    # A doc's tables (a Word/PPT table, a PDF grid) also carry citable text.
    for t in (tables or []):
        rows = getattr(t, "rows", None) or []
        for r in rows[:50]:
            try:
                parts.append(" | ".join(str(c) for c in (r.values() if isinstance(r, dict) else r)))
            except Exception:  # noqa: BLE001
                continue
    return "\n\n".join(parts)


def _xlsx_digest(path: str, filename: str) -> str:
    """Reference-workbook digest: 'Sheet <name>' then 'a: b' pairs / rows."""
    try:
        import pandas as pd
        sheets = pd.read_excel(path, sheet_name=None)
    except Exception:  # noqa: BLE001
        return ""
    out: list[str] = []
    for name, df in (sheets or {}).items():
        out.append(f"# Sheet: {name}")
        try:
            if df.shape[1] == 2:  # classic term/definition glossary
                for _, row in df.head(500).iterrows():
                    a, b = str(row.iloc[0]).strip(), str(row.iloc[1]).strip()
                    if a and a.lower() != "nan":
                        out.append(f"{a}: {b}")
            else:
                out.append(", ".join(str(c) for c in df.columns))
                for _, row in df.head(200).iterrows():
                    out.append(" | ".join(str(v) for v in row.tolist()))
        except Exception:  # noqa: BLE001
            continue
    return "\n".join(out)


def _extract_text(path: str, filename: str) -> str:
    """Any-type -> plain text. Returns '' when nothing extractable. Never raises."""
    ext = os.path.splitext(filename or path or "")[1].lower()
    try:
        if ext == ".pdf":
            from app.services.ingest_brain.pdf_extract import extract_pdf
            return _prose_from_extractor(extract_pdf, path, filename)
        if ext in (".docx", ".doc"):
            from app.services.ingest_brain.pdf_extract import extract_docx
            return _prose_from_extractor(extract_docx, path, filename)
        if ext in (".pptx", ".ppt"):
            from app.services.ingest_brain.pdf_extract import extract_pptx
            return _prose_from_extractor(extract_pptx, path, filename)
        if ext in (".xlsx", ".xlsm", ".xls"):
            return _xlsx_digest(path, filename)
        if ext in (".html", ".htm"):
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                return _strip_html(fh.read())
        if ext in (".txt", ".md", ".markdown", ".rst", ".json", ".yaml", ".yml"):
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                return fh.read()
    except Exception:  # noqa: BLE001 — any extractor failure -> skip, never block
        logger.warning("file_ingest: extract failed for %s", filename, exc_info=True)
    return ""


async def ingest_file_to_knowledge(
    db: Any,
    *,
    organization: Any,
    file: Any,
    data_source_id: Optional[str] = None,
    approve: bool = True,
) -> Optional[dict]:
    """Extract one file's text and persist it as a KnowledgeDoc. Fail-soft.

    Returns ingest_doc's dict on success, None when skipped/failed. Off unless
    `HYBRID_DOC_KNOWLEDGE` is on.
    """
    try:
        from app.settings.hybrid_flags import flags
        if not flags.DOC_KNOWLEDGE:
            return None
    except Exception:  # noqa: BLE001
        return None

    fname = getattr(file, "filename", "") or ""
    if not is_doc_file(fname):
        return None
    abs_path = _resolve_upload_path(getattr(file, "path", "") or "")
    if not abs_path:
        return None

    body = (_extract_text(abs_path, fname) or "").strip()
    if not body:
        return None
    if len(body) > _MAX_CHARS:
        body = body[:_MAX_CHARS]

    try:
        from app.ai.knowledge.docs_index import ingest_doc
        res = await ingest_doc(
            db, organization=organization,
            title=fname, body=body, source="upload",
            data_source_id=data_source_id,
        )
        if approve and res and res.get("doc_id"):
            # First-party upload -> approved so it reaches the agent immediately.
            from sqlalchemy import update
            from app.models.knowledge_doc import KnowledgeDoc
            await db.execute(
                update(KnowledgeDoc)
                .where(KnowledgeDoc.id == res["doc_id"])
                .values(status="approved")
            )
            await db.commit()
        logger.info("file_ingest: indexed %s -> doc %s (%s chunks)",
                    fname, (res or {}).get("doc_id"), (res or {}).get("chunks"))
        return res
    except Exception:  # noqa: BLE001
        logger.warning("file_ingest: ingest_doc failed for %s", fname, exc_info=True)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return None


async def backfill_data_source_docs(db: Any, *, organization: Any, data_source_id: str) -> dict:
    """Index every doc-type file attached to a data source that isn't in knowledge
    yet. Idempotent (ingest_doc dedups on content_hash). Fail-soft; used both by
    the training stage and as an on-demand repair. Returns {ingested, skipped}.
    """
    result = {"ingested": 0, "skipped": 0}
    try:
        from app.settings.hybrid_flags import flags
        if not flags.DOC_KNOWLEDGE:
            return result
    except Exception:  # noqa: BLE001
        return result

    try:
        from sqlalchemy import select
        from app.models.file import File
        from app.models.data_source_file_association import data_source_file_association

        rows = (await db.execute(
            select(File)
            .join(data_source_file_association,
                  data_source_file_association.c.file_id == File.id)
            .where(data_source_file_association.c.data_source_id == data_source_id)
        )).scalars().all()
    except Exception:  # noqa: BLE001
        logger.warning("file_ingest: backfill list failed for %s", data_source_id, exc_info=True)
        return result

    for f in rows:
        if not is_doc_file(getattr(f, "filename", "") or ""):
            result["skipped"] += 1
            continue
        res = await ingest_file_to_knowledge(
            db, organization=organization, file=f, data_source_id=data_source_id, approve=True,
        )
        if res:
            result["ingested"] += 1
        else:
            result["skipped"] += 1
    return result
