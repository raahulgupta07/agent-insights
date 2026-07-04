"""FileReferenceContextBuilder — inject user-pinned uploaded files (#497).

Mirrors BrainGraphContextBuilder / FilesContextBuilder. When flags.FILE_REFERENCES
is ON, loads the report's ``FileReference`` rows (org-scoped), resolves each to an
uploaded ``File``, and surfaces its LLM-facing text. When OFF -> empty section (no
DB hit, render() == ""), so the agent context is byte-identical to flag-off.

Never raises — degrades to an empty section.
"""
from __future__ import annotations
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.context.sections.file_references import (
    FileReferencesSection,
    ReferencedFileItem,
)


class FileReferenceContextBuilder:
    def __init__(self, db: AsyncSession, organization, report):
        self.db = db
        self.organization = organization
        self.report = report

    async def build(self, query: Optional[str] = None) -> FileReferencesSection:
        # Flag gate: empty (no DB hit) when OFF.
        try:
            from app.settings.hybrid_flags import flags
            if not flags.FILE_REFERENCES:
                return FileReferencesSection(items=[])
        except Exception:
            return FileReferencesSection(items=[])

        org_id = str(getattr(self.organization, "id", None) or "")
        report_id = str(getattr(self.report, "id", None) or "")
        if not org_id or not report_id:
            return FileReferencesSection(items=[])

        try:
            from app.services.file_reference_service import resolve_reference_files
            resolved = await resolve_reference_files(self.db, report_id, org_id)
        except Exception:
            return FileReferencesSection(items=[])

        items = [
            ReferencedFileItem(filename=fn, content_type=ct, text=txt)
            for (fn, ct, txt) in resolved
        ]
        return FileReferencesSection(items=items)
