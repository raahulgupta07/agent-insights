"""Smart Upload API — classify uploaded files, then apply confirmed routes.

Exposes the Smart Upload brain (``app.services.smart_upload.classifier`` +
``contract``) over HTTP and APPLIES confirmed routes by calling the existing
knowledge-subsystem sinks (``app.services.smart_upload.apply``).

Flow (the client uploads via ``POST /api/files`` FIRST, then references the
returned file ids here):
  1. POST /api/studios/{studio_id}/smart-upload/classify  -> proposed routes.
  2. (UI lets the user confirm/override the per-file destinations.)
  3. POST /api/studios/{studio_id}/smart-upload/apply      -> writes via sinks.

Gating mirrors ``studio_autoconfigure.py``: every route is behind
``flags.SMART_UPLOAD`` (env ``HYBRID_SMART_UPLOAD``) and 404s when OFF, exactly
like the Studios gate. Authorization = org scope + studio role: viewer+ may
classify (read-only), editor/owner may apply (writes). Answer-changing writes
land as pending via the sinks — this layer never force-approves.

Mounted under /api by main.py. NOTE: no ``from __future__ import annotations``
(body pydantic models on routes can be mis-read as query params under stringized
annotations — the data_source_from_file landmine).
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_user
from app.dependencies import get_async_db, get_current_organization
from app.models.data_source import DataSource
from app.models.datasource_table import DataSourceTable
from app.models.file import File as FileModel
from app.models.organization import Organization
from app.models.studio import Studio, StudioDataSource
from app.models.user import User
from app.services.smart_upload import apply as smart_apply
from app.services.smart_upload import classifier
from app.services.studio_access import resolve_studio_access
from app.settings.hybrid_flags import flags

logger = logging.getLogger(__name__)

router = APIRouter(tags=["studios"])

_EDITOR_ROLES = {"owner", "editor"}


# --------------------------------------------------------------------------- #
# Gate + role helpers (mirror studio_autoconfigure.py)
# --------------------------------------------------------------------------- #
def _require_flag() -> None:
    """404 when SMART_UPLOAD is OFF — never leak the route's existence."""
    if not getattr(flags, "SMART_UPLOAD", False):
        raise HTTPException(status_code=404, detail="Not found")


def _require_inbox_flag() -> None:
    """404 unless Inbox->Train routing is enabled (TRAIN_ROUTING) OR the base
    Smart Upload flag is on — either gate exposes the inbox surface."""
    if not (getattr(flags, "TRAIN_ROUTING", False)
            or getattr(flags, "SMART_UPLOAD", False)):
        raise HTTPException(status_code=404, detail="Not found")


def _require_autopilot_v2() -> None:
    """404 when AUTOPILOT_V2 is OFF — never leak the route's existence."""
    if not getattr(flags, "AUTOPILOT_V2", False):
        raise HTTPException(status_code=404, detail="autopilot v2 disabled")


async def _load_studio(db: AsyncSession, studio_id: str,
                       organization: Organization) -> Studio:
    res = await db.execute(
        select(Studio).where(
            Studio.id == str(studio_id),
            Studio.organization_id == organization.id,
        )
    )
    studio = res.scalar_one_or_none()
    if studio is None:
        raise HTTPException(status_code=404, detail="Studio not found")
    return studio


def _inbox_of(studio: Studio) -> List[Dict[str, Any]]:
    cfg = studio.config if isinstance(studio.config, dict) else {}
    box = cfg.get("inbox")
    return box if isinstance(box, list) else []


def _held_of(studio: Studio) -> List[Dict[str, Any]]:
    cfg = studio.config if isinstance(studio.config, dict) else {}
    held = cfg.get("inbox_held")
    return held if isinstance(held, list) else []


async def _save_inbox(db: AsyncSession, studio: Studio,
                      *, queued: Optional[List[Dict[str, Any]]] = None,
                      held: Optional[List[Dict[str, Any]]] = None) -> None:
    """Persist the inbox/held lists back onto Studio.config (reassign whole dict
    so SQLAlchemy marks the JSON column dirty)."""
    cfg = dict(studio.config) if isinstance(studio.config, dict) else {}
    if queued is not None:
        cfg["inbox"] = queued
    if held is not None:
        cfg["inbox_held"] = held
    studio.config = cfg
    await db.commit()


async def _require_role(
    db: AsyncSession, studio_id: str, user: User, *, editor: bool = False
) -> str:
    """Resolve the caller's effective studio role or raise 404/403.

    404 (not 403) when the user has no access at all so a Studio's existence
    isn't leaked to non-members; 403 when a viewer attempts an editor action.
    """
    role = await resolve_studio_access(db, studio_id, user)
    if role is None:
        raise HTTPException(status_code=404, detail="Studio not found")
    if editor and role not in _EDITOR_ROLES:
        raise HTTPException(status_code=403, detail="Editor or owner role required")
    return role


# --------------------------------------------------------------------------- #
# Request bodies
# --------------------------------------------------------------------------- #
class ClassifyRequest(BaseModel):
    file_ids: List[str]
    data_source_id: Optional[str] = None


class ApplyItem(BaseModel):
    file_id: Optional[str] = None
    dest: str
    filename: Optional[str] = None

    class Config:
        extra = "allow"  # carry through reason/confidence/signals harmlessly


class ApplyRequest(BaseModel):
    items: List[ApplyItem]
    data_source_id: Optional[str] = None
    train: bool = False


class InboxAddRequest(BaseModel):
    file_ids: List[str]


class QueueItem(BaseModel):
    """One classified file to hold in the inbox (NOT applied/trained yet)."""
    file_id: str
    filename: Optional[str] = None
    dest: Optional[str] = None
    confidence: Optional[float] = None
    size: Optional[int] = None
    content_type: Optional[str] = None
    ext: Optional[str] = None

    class Config:
        extra = "allow"  # carry through reason/signals/source/needs_confirm harmlessly


class QueueRequest(BaseModel):
    items: List[QueueItem]


class InboxRerouteRequest(BaseModel):
    dest: str


# --------------------------------------------------------------------------- #
# CLASSIFY (viewer+) — no writes
# --------------------------------------------------------------------------- #
@router.post("/studios/{studio_id}/smart-upload/classify")
async def smart_upload_classify(
    studio_id: str,
    body: ClassifyRequest,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
) -> Dict[str, Any]:
    """Classify already-uploaded files into routes. WRITES NOTHING.

    Loads each File (org-scoped), resolves its on-disk path, runs the heuristic
    classifier (+ a fail-soft small-LLM tie-break for the uncertain ones) and
    returns one route record per file plus an auto/needs-confirm summary.
    """
    _require_flag()
    await _require_role(db, studio_id, current_user)

    # Resolve each file to {path, filename}, preserving order + ids.
    files: List[Dict[str, str]] = []
    file_ids: List[str] = []
    for fid in (body.file_ids or []):
        res = await db.execute(
            select(FileModel).where(
                FileModel.id == str(fid),
                FileModel.organization_id == organization.id,
            )
        )
        f = res.scalar_one_or_none()
        if f is None:
            # Keep a placeholder so the record count matches the request.
            files.append({"path": "", "filename": ""})
            file_ids.append(str(fid))
            continue
        path = smart_apply._resolve_path(f.path or "") or ""
        files.append({"path": path, "filename": f.filename or ""})
        file_ids.append(str(f.id))

    # Resolve a small LLM for the tie-break — fail-soft (heuristic-only on None).
    llm = None
    try:
        from app.services.llm_service import LLMService
        llm = await LLMService().get_default_model(
            db, organization, current_user, is_small=True
        )
    except Exception:  # noqa: BLE001
        logger.warning("smart_upload.classify: small-model resolve failed",
                       exc_info=True)
        llm = None

    records = await classifier.classify_batch(files, llm=llm,
                                              organization=organization)

    items: List[Dict[str, Any]] = []
    auto = 0
    needs_confirm = 0
    for fid, rec in zip(file_ids, records):
        rec = dict(rec)
        rec["file_id"] = fid
        items.append(rec)
        if rec.get("needs_confirm"):
            needs_confirm += 1
        else:
            auto += 1

    return {
        "items": items,
        "summary": {"auto": auto, "needs_confirm": needs_confirm,
                    "total": len(items)},
    }


# --------------------------------------------------------------------------- #
# APPLY (editor+) — writes via existing sinks (answer-changing => pending)
# --------------------------------------------------------------------------- #
@router.post("/studios/{studio_id}/smart-upload/apply")
async def smart_upload_apply(
    studio_id: str,
    body: ApplyRequest,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
) -> Dict[str, Any]:
    """Apply confirmed route records by dispatching each to its existing sink.

    Each item is applied in its own try/except (one failure never blocks the
    rest). If ``train`` is true, a background studio train run is kicked
    afterwards (fail-soft). Returns ``{applied, results:[...]}``.
    """
    _require_flag()
    await _require_role(db, studio_id, current_user, editor=True)

    # Capture IDs as strings up-front: apply_routes commits internally, which
    # expires these ORM objects -> a later attribute access triggers a SYNC
    # lazy-reload (MissingGreenlet). See create_data_source_from_file landmine.
    org_id = str(organization.id)
    user_id = str(current_user.id)

    items = [it.dict() for it in (body.items or [])]
    summary = await smart_apply.apply_routes(
        db,
        organization=organization,
        current_user=current_user,
        studio_id=studio_id,
        data_source_id=body.data_source_id,
        items=items,
    )

    if body.train or flags.AUTOTRAIN_ON_UPLOAD:
        try:
            from app.ai.knowledge import train_orchestrator
            train_orchestrator.start_training(
                str(studio_id), org_id, user_id
            )
            summary["train_started"] = True
        except Exception:  # noqa: BLE001
            logger.warning("smart_upload.apply: start_training failed",
                           exc_info=True)
            summary["train_started"] = False

    return summary


# --------------------------------------------------------------------------- #
# INBOX (Inbox -> Train) — stash files now, route them at train time
# --------------------------------------------------------------------------- #
@router.get("/studios/{studio_id}/smart-upload/inbox")
async def smart_upload_inbox_list(
    studio_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
) -> Dict[str, Any]:
    """List the studio's queued inbox files + any held-for-review records."""
    _require_inbox_flag()
    await _require_role(db, studio_id, current_user)
    studio = await _load_studio(db, studio_id, organization)
    return {"queued": _inbox_of(studio), "held": _held_of(studio)}


@router.post("/studios/{studio_id}/smart-upload/inbox")
async def smart_upload_inbox_add(
    studio_id: str,
    body: InboxAddRequest,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
) -> Dict[str, Any]:
    """Stash already-uploaded files into the studio inbox (no routing yet).

    Each file is recorded {file_id, filename, size, status:'queued'}; routing
    happens later in the train ``route_inbox`` stage. Dedupes by file_id.
    """
    _require_inbox_flag()
    await _require_role(db, studio_id, current_user, editor=True)
    studio = await _load_studio(db, studio_id, organization)

    queued = list(_inbox_of(studio))
    seen = {str(it.get("file_id")) for it in queued}
    added = 0
    for fid in (body.file_ids or []):
        fid = str(fid)
        if fid in seen:
            continue
        res = await db.execute(
            select(FileModel).where(
                FileModel.id == fid,
                FileModel.organization_id == organization.id,
            )
        )
        f = res.scalar_one_or_none()
        if f is None:
            continue
        size = 0
        try:
            import os
            p = smart_apply._resolve_path(f.path or "") or ""
            if p and os.path.exists(p):
                size = os.path.getsize(p)
        except Exception:  # noqa: BLE001
            size = 0
        queued.append({
            "file_id": fid,
            "filename": f.filename or "",
            "size": int(size),
            "status": "queued",
        })
        seen.add(fid)
        added += 1

    await _save_inbox(db, studio, queued=queued)
    return {"queued": queued, "added": added}


@router.post("/studios/{studio_id}/smart-upload/queue")
async def smart_upload_queue(
    studio_id: str,
    body: QueueRequest,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
) -> Dict[str, Any]:
    """QUEUE already-classified files into the studio inbox WITHOUT applying or
    training them. Each item carries its classifier metadata (guessed lane,
    confidence, size, type) and gets a SERVER-set ``queued_at`` ISO timestamp.

    Files rest in ``Studio.config['inbox']`` until the user clicks Train (the
    ``route_inbox`` train stage consumes this list). Dedupes by ``file_id``
    (a re-queue refreshes the existing record). Fail-soft per file.
    """
    _require_inbox_flag()
    await _require_role(db, studio_id, current_user, editor=True)
    studio = await _load_studio(db, studio_id, organization)

    import os

    queued = list(_inbox_of(studio))
    by_id = {str(it.get("file_id")): it for it in queued if isinstance(it, dict)}
    now_iso = datetime.now(timezone.utc).isoformat()
    added = 0
    for it in (body.items or []):
        fid = str(it.file_id)
        if not fid:
            continue
        # Org-scope the file; skip anything not visible to this org.
        f = (await db.execute(
            select(FileModel).where(
                FileModel.id == fid,
                FileModel.organization_id == organization.id,
            )
        )).scalar_one_or_none()
        if f is None:
            continue

        filename = it.filename or (f.filename or "")
        # size: prefer client-reported, else disk.
        size = int(it.size) if it.size is not None else 0
        if not size:
            try:
                p = smart_apply._resolve_path(f.path or "") or ""
                if p and os.path.exists(p):
                    size = os.path.getsize(p)
            except Exception:  # noqa: BLE001
                size = 0
        ext = it.ext or (os.path.splitext(filename)[1].lower() if filename else "")
        extra = it.dict(exclude={"file_id", "filename", "dest", "confidence",
                                 "size", "content_type", "ext"})

        record = {
            "file_id": fid,
            "filename": filename,
            "dest": it.dest,
            "confidence": it.confidence,
            "size": int(size),
            "content_type": it.content_type or "",
            "ext": ext,
            "status": "queued",
            "queued_at": now_iso,
        }
        # carry through reason/signals/source/needs_confirm (from classify).
        for k, v in (extra or {}).items():
            record.setdefault(k, v)

        if fid in by_id:
            # Re-queue: keep the original queued_at, refresh the rest.
            existing = by_id[fid]
            record["queued_at"] = existing.get("queued_at") or now_iso
            existing.clear()
            existing.update(record)
        else:
            queued.append(record)
            by_id[fid] = record
            added += 1

    await _save_inbox(db, studio, queued=queued)
    return {"queued": queued, "added": added, "queued_count": len(queued)}


@router.delete("/studios/{studio_id}/smart-upload/inbox/{file_id}")
async def smart_upload_inbox_remove(
    studio_id: str,
    file_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
) -> Dict[str, Any]:
    """Remove one file from the queued inbox and the held-review list."""
    _require_inbox_flag()
    await _require_role(db, studio_id, current_user, editor=True)
    studio = await _load_studio(db, studio_id, organization)

    fid = str(file_id)
    queued = [it for it in _inbox_of(studio) if str(it.get("file_id")) != fid]
    held = [it for it in _held_of(studio) if str(it.get("file_id")) != fid]
    await _save_inbox(db, studio, queued=queued, held=held)
    return {"queued": queued, "held": held}


@router.post("/studios/{studio_id}/smart-upload/inbox/clear")
async def smart_upload_inbox_clear(
    studio_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
) -> Dict[str, Any]:
    """Empty the queued inbox (held-review records are left intact)."""
    _require_inbox_flag()
    await _require_role(db, studio_id, current_user, editor=True)
    studio = await _load_studio(db, studio_id, organization)
    await _save_inbox(db, studio, queued=[])
    return {"queued": [], "held": _held_of(studio)}


@router.post("/studios/{studio_id}/smart-upload/inbox/{file_id}")
async def smart_upload_inbox_reroute(
    studio_id: str,
    file_id: str,
    body: InboxRerouteRequest,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
) -> Dict[str, Any]:
    """Change a QUEUED file's guessed lane (``dest``) before training — the file
    stays in the inbox, nothing is placed/trained. Marks ``dest_source='user'``
    so the train ``route_inbox`` stage honors the human choice over a re-classify.
    """
    _require_inbox_flag()
    await _require_role(db, studio_id, current_user, editor=True)
    studio = await _load_studio(db, studio_id, organization)

    fid = str(file_id)
    dest = (body.dest or "").strip()
    queued = list(_inbox_of(studio))
    for it in queued:
        if isinstance(it, dict) and str(it.get("file_id")) == fid:
            it["dest"] = dest
            it["dest_source"] = "user"
            break
    await _save_inbox(db, studio, queued=queued)
    return {"queued": queued, "held": _held_of(studio)}


# --------------------------------------------------------------------------- #
# AUTOPILOT V2 — instant heuristic sniff (no LLM) + warehouse coverage
# --------------------------------------------------------------------------- #
@router.post("/studios/{studio_id}/smart-upload/sniff")
async def smart_upload_sniff(
    studio_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
) -> Dict[str, Any]:
    """Instantly preview where each QUEUED inbox file would route — HEURISTIC
    ONLY (``classifier.sniff_file``, no LLM, no network), so a UI can show the
    proposed destination for the whole inbox without waiting on a train run.

    Fail-soft per file: a bad/missing file degrades to ``skip``/0 and never
    sinks the rest.
    """
    _require_autopilot_v2()
    await _require_role(db, studio_id, current_user)
    studio = await _load_studio(db, studio_id, organization)

    items: List[Dict[str, Any]] = []
    for q in _inbox_of(studio):
        if not isinstance(q, dict):
            continue
        fid = str(q.get("file_id") or "")
        fname = q.get("filename") or ""
        try:
            res = await db.execute(
                select(FileModel).where(
                    FileModel.id == fid,
                    FileModel.organization_id == organization.id,
                )
            )
            f = res.scalar_one_or_none()
            path = ""
            if f is not None:
                path = smart_apply._resolve_path(f.path or "") or ""
                fname = f.filename or fname
            rec = classifier.sniff_file(path, fname)
            items.append({
                "file_id": fid,
                "filename": fname,
                "dest": rec.get("dest"),
                "confidence": rec.get("confidence"),
                "source": rec.get("source"),
                "signals": rec.get("signals"),
            })
        except Exception as e:  # noqa: BLE001 - one bad file never sinks the rest
            logger.warning("smart_upload.sniff: file %s failed: %s", fid, e)
            items.append({
                "file_id": fid,
                "filename": fname,
                "dest": "skip",
                "confidence": 0,
                "source": "heuristic",
                "signals": {},
            })

    return {"items": items}


@router.get("/studios/{studio_id}/coverage")
async def studio_coverage(
    studio_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
) -> Dict[str, Any]:
    """Report the distinct ``_source_period`` values present in each pinned
    source's tables — i.e. which periods the warehouse actually covers.

    For every DataSource pinned to the studio, every active ``datasource_tables``
    row whose ``columns`` JSON carries a ``_source_period`` column is queried for
    its DISTINCT periods (capped). Tables without that column are skipped (their
    period coverage is unknown). Fail-soft per source AND per table — never
    raises.
    """
    _require_autopilot_v2()
    await _require_role(db, studio_id, current_user)
    studio = await _load_studio(db, studio_id, organization)

    # Resolve pinned DataSources (org-scoped) for this studio.
    sources: List[DataSource] = []
    try:
        pin_res = await db.execute(
            select(StudioDataSource).where(
                StudioDataSource.studio_id == str(studio.id),
                StudioDataSource.deleted_at.is_(None),
            )
        )
        pins = list(pin_res.scalars().all())
        agent_ids = [p.agent_id for p in pins]
        if agent_ids:
            ds_res = await db.execute(
                select(DataSource).where(
                    DataSource.id.in_(agent_ids),
                    DataSource.organization_id == organization.id,
                )
            )
            sources = list(ds_res.scalars().all())
    except Exception as e:  # noqa: BLE001 - fail-soft
        logger.warning("studio_coverage: pinned-source resolution failed: %s", e)
        sources = []

    out_sources: List[Dict[str, Any]] = []
    for ds in sources:
        src_entry: Dict[str, Any] = {
            "data_source_id": str(getattr(ds, "id", "")),
            "name": getattr(ds, "name", None),
            "tables": [],
        }
        try:
            tbl_res = await db.execute(
                select(DataSourceTable).where(
                    DataSourceTable.datasource_id == str(ds.id),
                    DataSourceTable.is_active.is_(True),
                )
            )
            tables = list(tbl_res.scalars().all())

            client = None
            for tbl in tables:
                try:
                    cols = tbl.columns if isinstance(tbl.columns, list) else []
                    has_period = any(
                        isinstance(c, dict) and c.get("name") == "_source_period"
                        for c in cols
                    )
                    if not has_period:
                        continue  # periods unknown for this table — skip
                    if client is None:
                        client = ds.get_client()
                    tname = tbl.name
                    sql = (
                        f'SELECT DISTINCT "_source_period" AS p '
                        f'FROM "{tname}" ORDER BY 1'
                    )
                    df = await client.aexecute_query(sql)
                    periods: List[Any] = []
                    try:
                        for v in list(df["p"].tolist())[:50]:
                            if v is not None:
                                periods.append(str(v))
                    except Exception:  # noqa: BLE001
                        # fall back to first column if 'p' alias missing
                        try:
                            for v in list(df.iloc[:, 0].tolist())[:50]:
                                if v is not None:
                                    periods.append(str(v))
                        except Exception:  # noqa: BLE001
                            periods = []
                    src_entry["tables"].append({
                        "table": tname,
                        "periods": periods,
                        "n_periods": len(periods),
                    })
                except Exception as te:  # noqa: BLE001 - per-table fail-soft
                    logger.warning(
                        "studio_coverage: table %s failed: %s",
                        getattr(tbl, "name", "?"), te)
                    continue
        except Exception as se:  # noqa: BLE001 - per-source fail-soft
            logger.warning(
                "studio_coverage: source %s failed: %s",
                getattr(ds, "id", "?"), se)
        out_sources.append(src_entry)

    return {"sources": out_sources}
