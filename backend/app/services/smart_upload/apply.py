"""Smart Upload — APPLY confirmed route records by calling EXISTING sinks.

The classifier (``classifier.py``) decides WHERE each uploaded file should go;
this module ACTS on a list of human-confirmed route records by dispatching each
to the matching knowledge-subsystem sink the rest of the platform already uses.
We never edit a sink — we reuse them exactly:

  * ``database``     -> ``routes.data_source_from_file.create_data_source_from_file``
                        (file -> spreadsheet Connection + DataSource, schema synced).
  * ``semantic``     -> ``ai.knowledge.doc_extractor.extract_proposal`` (binds a
                        glossary file to a target data source's live columns) +
                        merge the matched column descriptions into the schema
                        (mirrors ``routes.studio_autoconfigure.apply``).
  * ``instructions`` -> ``ai.packs.teach.classify`` (file text -> spans) +
    / ``examples``      ``ai.packs.teach.apply_spans`` (spans -> StudioInstruction /
                        StudioExample / KnowledgeDoc, **all born pending**).
  * ``knowledge``    -> ``ai.knowledge.docs_index.ingest_doc`` (chunks + indexes a
                        doc, **born pending**).
  * ``skip``         -> no-op.

Design contract (mirrors the classifier): every per-item dispatch runs in its
OWN ``try/except`` so one failure never blocks the others, and answer-changing
writes (semantic/instructions/examples/knowledge) land as **pending** — we never
force-approve. Returns a JSON-friendly summary ``{applied, results:[...]}``.
"""

import logging
import os
from typing import Any, Dict, List, Optional

from app.services.smart_upload import contract
from app.services.smart_upload.contract import (
    DEST_DATABASE,
    DEST_EXAMPLES,
    DEST_INSTRUCTIONS,
    DEST_KNOWLEDGE,
    DEST_SEMANTIC,
    DEST_SKIP,
)

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# File text extraction — reuse the classifier's own readers (no new deps)
# --------------------------------------------------------------------------- #
async def _load_file(db, organization, file_id: str):
    """Load a File row scoped to the org, or None. Never raises."""
    try:
        from sqlalchemy import select
        from app.models.file import File as FileModel

        res = await db.execute(
            select(FileModel).where(
                FileModel.id == str(file_id),
                FileModel.organization_id == organization.id,
            )
        )
        return res.scalar_one_or_none()
    except Exception:  # noqa: BLE001
        logger.warning("smart_upload.apply: file load failed for %s", file_id,
                       exc_info=True)
        return None


def _resolve_path(stored_path: str) -> Optional[str]:
    """Reuse the canonical upload-path resolver (traversal-safe)."""
    try:
        from app.routes.data_source_from_file import _resolve_upload_path
        return _resolve_upload_path(stored_path or "")
    except Exception:  # noqa: BLE001
        return None


def _file_text(path: str, filename: str) -> str:
    """Extract prose text from a file, reusing the classifier's readers.

    Tabular files degrade to a small CSV head; unsupported -> "". Never raises.
    """
    from app.services.smart_upload import classifier

    ext = os.path.splitext(filename or path or "")[1].lower()
    try:
        if ext in classifier._TABULAR_EXTS:
            df, _ = classifier._read_tabular(path, ext)
            if df is not None:
                return df.head(200).to_csv(index=False)
            return ""
        text, _ = classifier._extract_text(path, ext, filename)
        return text or ""
    except Exception:  # noqa: BLE001
        return ""


# --------------------------------------------------------------------------- #
# Per-destination sink dispatch — each reuses an existing subsystem, fail-soft
# --------------------------------------------------------------------------- #
async def _apply_database(db, *, organization, current_user, file_id, filename,
                          studio_id=None):
    """database sink: file -> DataSource via the existing from-file route, then
    PIN the new data source to the studio so the agent can actually see it."""
    from app.routes.data_source_from_file import (
        create_data_source_from_file,
        DataSourceFromFileRequest,
    )

    payload = DataSourceFromFileRequest(
        file_id=str(file_id),
        data_source_name=(filename or None),
    )
    body = await create_data_source_from_file(
        payload=payload,
        current_user=current_user,
        db=db,
        organization=organization,
    )
    body = body if isinstance(body, dict) else {}
    ds_id = body.get("id")

    # Pin the data source to the studio (StudioDataSource has only studio_id +
    # agent_id [=data_source id]; NO organization_id column — landmine). Dedupe +
    # undelete so re-uploads don't stack duplicate pins. Best-effort.
    pinned = False
    if studio_id and ds_id:
        try:
            from sqlalchemy import select
            from app.models.studio import StudioDataSource
            existing = (await db.execute(
                select(StudioDataSource).where(
                    StudioDataSource.studio_id == str(studio_id),
                    StudioDataSource.agent_id == str(ds_id),
                )
            )).scalar_one_or_none()
            if existing is None:
                db.add(StudioDataSource(studio_id=str(studio_id),
                                        agent_id=str(ds_id)))
            elif getattr(existing, "deleted_at", None) is not None:
                existing.deleted_at = None
            await db.commit()
            pinned = True
        except Exception:  # noqa: BLE001 - pinning is best-effort
            logger.warning("smart_upload.apply: pin DS %s to studio %s failed",
                           ds_id, studio_id, exc_info=True)

    return {
        "data_source_id": ds_id,
        "name": body.get("name"),
        "tables": len(body.get("tables") or []),
        "reused": body.get("reused", False),
        "pinned": pinned,
    }


async def _apply_semantic(db, *, organization, file_id, data_source_id):
    """semantic sink: bind a glossary file to a data source's live columns.

    Reuses ``doc_extractor.extract_proposal`` (fuzzy-matches the glossary to the
    schema) then merges the matched column descriptions into the
    ``DataSourceTable.columns`` JSON — the same write ``studio_autoconfigure``
    performs when a reviewed proposal is applied.
    """
    if not data_source_id:
        raise ValueError("semantic routing needs a target data_source_id")

    from app.ai.knowledge.doc_extractor import extract_proposal
    from sqlalchemy import select
    from sqlalchemy.orm.attributes import flag_modified
    from app.models.datasource_table import DataSourceTable

    proposal = await extract_proposal(
        db, organization=organization,
        file_ids=[str(file_id)], data_source_id=str(data_source_id),
    )
    if isinstance(proposal, dict) and proposal.get("error"):
        raise ValueError(proposal["error"])

    col_defs = (proposal or {}).get("column_descriptions") or []

    tbl_res = await db.execute(
        select(DataSourceTable).where(
            DataSourceTable.datasource_id == str(data_source_id),
            DataSourceTable.is_active == True,  # noqa: E712
        )
    )
    tables = list(tbl_res.scalars().all())
    by_id = {str(t.id): t for t in tables}

    def _norm(s: str) -> str:
        return "".join(ch for ch in (s or "").lower().strip() if ch.isalnum())

    written, unmatched = 0, []
    for cd in col_defs:
        col = str((cd or {}).get("column", "")).strip()
        desc = str((cd or {}).get("description", "")).strip()
        if not col or not desc:
            continue
        tid = (cd or {}).get("table_id")
        candidates = [by_id[str(tid)]] if (tid and str(tid) in by_id) else tables
        applied = False
        col_norm = _norm(col)
        for t in candidates:
            cols = t.columns
            if not isinstance(cols, list) or not cols:
                continue
            changed = False
            for entry in cols:
                if not isinstance(entry, dict):
                    continue
                ename = entry.get("name") or ""
                if (ename == col or ename.lower().strip() == col.lower().strip()
                        or _norm(ename) == col_norm):
                    entry["description"] = desc
                    changed = True
                    applied = True
                    break
            if changed:
                flag_modified(t, "columns")
                break
        if applied:
            written += 1
        else:
            unmatched.append(col)

    await db.commit()
    return {
        "descriptions_written": written,
        "columns_unmatched": unmatched,
        "data_source_id": str(data_source_id),
    }


async def _apply_teach(db, *, organization, studio_id, path, filename):
    """instructions/examples sink: file text -> spans -> pending studio rows.

    ``teach.classify`` turns the prose into typed spans (INSTRUCTION / DATA_RULE
    / KNOWLEDGE / SKILL / example); ``teach.apply_spans`` persists them — every
    span born ``status='pending'`` (the existing review gate).
    """
    from app.ai.packs import teach

    text = _file_text(path, filename)
    if not text or not text.strip():
        raise ValueError("no extractable text in file")

    spans = await teach.classify(db, organization, text)
    if not spans:
        return {"spans": 0, "note": "classifier produced no spans"}

    created = await teach.apply_spans(
        db, organization, str(studio_id), spans, default_status="pending"
    )
    summary = dict(created) if isinstance(created, dict) else {}
    summary["spans"] = len(spans)
    return summary


async def _apply_examples(db, *, organization, studio_id, path, filename):
    """examples sink: Q&A / logic doc -> pending StudioExample rows.

    Primary path reuses the existing logic-doc parser (Q./Ans:/Logic: triples).
    If that yields nothing (a doc using different markers), fall back to a single
    cheap small-model call that extracts {question, answer, sql} pairs. Each pair
    becomes a StudioExample born status='pending' (the review gate), so the
    studio's Examples lane fills after upload. Fail-soft — never raises the batch.
    """
    from app.services.ingest import logic_parser
    from app.models.studio import StudioExample

    def _add(question, answer, sql):
        question = (question or "").strip()
        if not question:
            return 0
        answer = (answer or "").strip() or "(see logic)"
        db.add(StudioExample(
            studio_id=str(studio_id), question=question, answer=answer,
            sql=(sql or None), source="auto", status="pending",
        ))
        return 1

    created = 0
    # --- primary: structured Q./Ans:/Logic: parser -----------------------------
    try:
        for t in (logic_parser.parse_logic_doc(path) or []):
            answer = (t.get("answer_text") or "").strip() or (t.get("logic_text") or "").strip()
            created += _add(t.get("question"), answer, t.get("sql"))
    except Exception as e:  # noqa: BLE001 - fall through to LLM
        logger.warning("smart_upload.apply examples: parser failed: %s", e)

    # --- fallback: one small-model extraction if the parser found nothing -------
    if created == 0:
        try:
            text = _file_text(path, filename)
            if text and text.strip():
                from app.services.llm_service import LLMService
                from app.ai.llm.llm import LLM
                from app.dependencies import async_session_maker
                model = await LLMService().get_default_model(
                    db, organization, None, is_small=True)
                if model is not None:
                    prompt = (
                        "Extract EVERY question-and-answer / example the document "
                        "contains as JSON. Do NOT summarize or drop any. Return ONLY:\n"
                        '{"examples":[{"question":"...","answer":"...","sql":"..."}]}\n'
                        "sql is optional (\"\" if none). Preserve the original wording.\n"
                        "DOCUMENT:\n<<<\n" + text[:60000] + "\n>>>"
                    )
                    raw = LLM(model, usage_session_maker=async_session_maker).inference(
                        prompt, usage_scope="smart_upload_examples") or ""
                    import json as _json
                    import re as _re
                    m = _re.search(r"\{.*\}", raw, _re.DOTALL)
                    data = _json.loads(m.group(0)) if m else {}
                    for ex in (data.get("examples") or []):
                        if isinstance(ex, dict):
                            created += _add(ex.get("question"), ex.get("answer"), ex.get("sql"))
        except Exception as e:  # noqa: BLE001 - fail-soft
            logger.warning("smart_upload.apply examples: LLM fallback failed: %s", e)

    if created:
        await db.commit()
    return {"examples": created}


async def _apply_knowledge(db, *, organization, file_id, filename, path,
                           data_source_id):
    """knowledge sink: chunk + index the doc as a pending KnowledgeDoc."""
    from app.ai.knowledge.docs_index import ingest_doc

    text = _file_text(path, filename)
    if not text or not text.strip():
        raise ValueError("no extractable text in file")

    res = await ingest_doc(
        db, organization=organization,
        title=(filename or "Uploaded document"),
        body=text, source="upload",
        data_source_id=(str(data_source_id) if data_source_id else None),
    )
    res = res if isinstance(res, dict) else {}
    return {
        "doc_id": res.get("doc_id"),
        "chunks": res.get("chunks"),
        "deduped": res.get("deduped", False),
    }


# --------------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------------- #
async def apply_routes(
    db, *, organization, current_user, studio_id, data_source_id,
    items: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Apply a list of confirmed route records by dispatching to existing sinks.

    ``items`` = [{file_id, filename?, dest, ...}, ...]. Each item is dispatched
    by ``dest`` in its OWN try/except (one failure never blocks the others). A
    per-item result ``{file_id, dest, ok, detail, created}`` is collected.

    Returns ``{applied: <n ok>, results: [...], data_source_id: <effective id>}``.
    """
    from app.models.organization import Organization
    from app.models.user import User

    # GREENLET LANDMINE: the database sink (create_data_source_from_file) commits
    # AND rolls back internally across its fail-soft stages. A rollback expires
    # EVERY ORM object on this shared request session (expire_on_commit only
    # governs commit, not rollback), so on the next item, reading the expired
    # request-scoped `organization`/`current_user` triggers a sync lazy-load
    # outside the async greenlet -> MissingGreenlet -> _load_file swallows it and
    # returns None -> "file not found in this organization". Capture ids up-front
    # and re-hydrate a fresh, live org/user per item.
    org_id = str(organization.id)
    user_id = str(current_user.id)

    # BACKFILL: on a brand-NEW agent the caller has no data_source_id yet — the
    # database dest CREATES it mid-loop. Track it locally so the semantic/knowledge
    # sinks (which NEED a real target id) can bind to the just-created source instead
    # of the still-None outer param. `effective_ds_id` is updated the moment a
    # database item succeeds; it defaults to the passed-in id for existing agents.
    effective_ds_id = data_source_id

    # ORDER-INDEPENDENT: process all database dests FIRST so the agent id exists no
    # matter what order the caller sent items in (e.g. glossary before its CSV).
    # Stable-sort a working COPY (never mutate the caller's list) — database items
    # keep their relative order, everything else keeps its relative order after them.
    def _dest_of(it: Dict[str, Any]) -> str:
        d = str((it or {}).get("dest") or "").strip().lower()
        if d not in contract.ALL_DESTS_SET:
            d = contract.normalize_record({"dest": d})["dest"]
        return d

    ordered_items = sorted(
        (it for it in (items or []) if isinstance(it, dict)),
        key=lambda it: 0 if _dest_of(it) == DEST_DATABASE else 1,
    )

    results: List[Dict[str, Any]] = []

    for item in ordered_items:
        # Re-hydrate live ORM objects for THIS item — a prior item's ingest may
        # have expired them via an internal rollback. db.get() is awaited, so the
        # reload happens inside the greenlet (safe).
        organization = await db.get(Organization, org_id)
        current_user = await db.get(User, user_id)
        item = item if isinstance(item, dict) else {}
        file_id = item.get("file_id")
        dest = str(item.get("dest") or "").strip().lower()
        # Defensive: coerce unknown destinations to knowledge (contract default).
        if dest not in contract.ALL_DESTS_SET:
            dest = contract.normalize_record({"dest": dest})["dest"]

        result: Dict[str, Any] = {
            "file_id": file_id, "dest": dest, "ok": False,
            "detail": "", "created": {},
        }

        if dest == DEST_SKIP:
            result.update(ok=True, detail="skipped (no-op)")
            results.append(result)
            continue

        try:
            # Resolve the File row + on-disk path for the text-based sinks.
            file = None
            filename = item.get("filename") or ""
            path = ""
            if file_id is not None:
                file = await _load_file(db, organization, file_id)
                if file is None:
                    raise ValueError("file not found in this organization")
                filename = filename or (file.filename or "")
                if dest in (DEST_INSTRUCTIONS, DEST_EXAMPLES, DEST_KNOWLEDGE):
                    path = _resolve_path(file.path or "")
                    if not path:
                        raise ValueError("file content missing on disk")

            if dest == DEST_DATABASE:
                created = await _apply_database(
                    db, organization=organization, current_user=current_user,
                    file_id=file_id, filename=filename, studio_id=studio_id,
                )
                # A brand-new agent's id is born here — backfill it so the
                # semantic/knowledge sinks that follow can target this source.
                effective_ds_id = (created or {}).get("data_source_id") or effective_ds_id
            elif dest == DEST_SEMANTIC:
                created = await _apply_semantic(
                    db, organization=organization, file_id=file_id,
                    data_source_id=effective_ds_id,
                )
            elif dest == DEST_EXAMPLES:
                created = await _apply_examples(
                    db, organization=organization, studio_id=studio_id,
                    path=path, filename=filename,
                )
            elif dest == DEST_INSTRUCTIONS:
                created = await _apply_teach(
                    db, organization=organization, studio_id=studio_id,
                    path=path, filename=filename,
                )
            elif dest == DEST_KNOWLEDGE:
                created = await _apply_knowledge(
                    db, organization=organization, file_id=file_id,
                    filename=filename, path=path, data_source_id=effective_ds_id,
                )
            else:  # pragma: no cover - normalized above
                created = {}

            result.update(ok=True, detail="applied", created=created or {})
        except Exception as e:  # one bad item never sinks the batch
            logger.warning("smart_upload.apply: %s sink failed for file %s: %s",
                           dest, file_id, e, exc_info=True)
            # A failed write may have left the session dirty — roll back so the
            # next item starts clean.
            try:
                await db.rollback()
            except Exception:  # noqa: BLE001
                pass
            result.update(ok=False, detail=f"{type(e).__name__}: {e}")

        results.append(result)

    applied = sum(1 for r in results if r.get("ok"))
    return {"applied": applied, "results": results, "data_source_id": effective_ds_id}
