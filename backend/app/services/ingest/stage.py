"""Ingest stage 1: hash the file, create an IngestBatch audit row, dedup.

No DB writes to the data itself here — this only records that a file was staged.
Never raises into the caller's request path beyond explicit ValueErrors.
"""
from __future__ import annotations

import hashlib
import logging
import os
import uuid
from typing import Optional

from sqlalchemy import select

from app.models.ingest_batch import IngestBatch

logger = logging.getLogger(__name__)


def content_hash(path: str) -> str:
    """sha256 of file bytes, chunked (never loads whole file into memory)."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        logger.exception("content_hash failed for %s", path)
        return ""


def derive_logical_dataset(filename: str) -> str:
    """Strip period tokens (Apr 25 / 2026-04 / _v2) so monthly re-drops of the
    same template collapse to ONE logical dataset (-> one _period-stamped table).
    Best-effort; safe slug only.
    """
    import re

    base = os.path.splitext(os.path.basename(filename or "dataset"))[0].lower()
    base = re.sub(r"[^a-z0-9]+", "_", base)
    # drop trailing month/year tokens
    base = re.sub(
        r"_(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|q[1-4]|"
        r"\d{4}|\d{1,2}|v\d+)+$",
        "",
        base,
    )
    base = base.strip("_") or "dataset"
    return base[:48]


async def stage_file(
    db,
    *,
    organization_id: str,
    filename: str,
    path: str,
    file_id: Optional[str] = None,
    data_source_id: Optional[str] = None,
) -> IngestBatch:
    """Create (or return an existing dedup) IngestBatch for this file.

    Dedup: if a PROMOTED batch with the same (org, file_hash) exists, reuse it.
    """
    fh = content_hash(path)
    logical = derive_logical_dataset(filename)

    if fh:
        existing = (
            await db.execute(
                select(IngestBatch).where(
                    IngestBatch.organization_id == organization_id,
                    IngestBatch.file_hash == fh,
                    IngestBatch.status == "promoted",
                    IngestBatch.deleted_at.is_(None),
                )
            )
        ).scalars().first()
        if existing is not None:
            logger.info("stage_file: dedup hit batch=%s hash=%s", existing.id, fh[:12])
            return existing

    batch = IngestBatch(
        id=str(uuid.uuid4()),
        organization_id=organization_id,
        data_source_id=data_source_id,
        file_id=file_id,
        file_hash=fh,
        filename=filename,
        logical_dataset=logical,
        target_table=logical,
        status="staged",
        manifest={"path": path, "size": _safe_size(path)},
        row_count=0,
    )
    db.add(batch)
    await db.commit()
    await db.refresh(batch)
    return batch


def _safe_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except Exception:
        return 0
