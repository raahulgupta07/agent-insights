"""Resolve #497 file references into injectable text.

Loads the ``FileReference`` rows for a report (org-scoped) and their referenced
uploaded ``File`` rows, then renders each file's LLM-facing text (the fork's
existing ``File.description``). Never raises — a missing / deleted file is
skipped so the agent loop is never broken. All reads assume the caller already
flag-gated on ``flags.FILE_REFERENCES``.
"""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# Cap injected text per file so a huge referenced file can't blow the prompt.
_MAX_TEXT_CHARS = 20_000


def render_file_text(file) -> str:
    """Best-effort LLM-facing text for an uploaded File. Never raises."""
    try:
        text = file.description
    except Exception:
        try:
            text = file.prompt_schema()
        except Exception:
            text = None
    text = (text or "").strip()
    if len(text) > _MAX_TEXT_CHARS:
        text = text[:_MAX_TEXT_CHARS] + "\n… (truncated)"
    return text


async def resolve_reference_files(db, report_id: str, organization_id: str) -> List[Tuple[str, Optional[str], str]]:
    """Return [(filename, content_type, text)] for a report's file references.

    Org-scoped on both the reference row and the resolved file. Deleted /
    missing / cross-org files are silently skipped. Best-effort — returns [] on
    any error.
    """
    try:
        from sqlalchemy import select
        from app.models.file_reference import FileReference
        from app.models.file import File

        org_id = str(organization_id or "")
        if not org_id or not report_id:
            return []

        rows = (await db.execute(
            select(FileReference).where(
                FileReference.report_id == str(report_id),
                FileReference.organization_id == org_id,
                FileReference.deleted_at.is_(None),
            )
        )).scalars().all()

        out: List[Tuple[str, Optional[str], str]] = []
        for ref in rows:
            f = await db.get(File, ref.file_id)
            # 404-no-leak invariant also holds at read time: never inject a file
            # that isn't in this org (or was deleted).
            if f is None or str(getattr(f, "organization_id", "")) != org_id:
                continue
            if getattr(f, "deleted_at", None) is not None:
                continue
            text = render_file_text(f)
            if not text:
                continue
            out.append((
                getattr(f, "filename", None) or getattr(f, "name", "file"),
                getattr(f, "content_type", None),
                text,
            ))
        return out
    except Exception as e:  # never break the agent loop
        logger.debug(f"[file_reference_service] resolve failed: {e}")
        return []
