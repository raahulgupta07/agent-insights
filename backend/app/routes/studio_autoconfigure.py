"""Auto-configure-from-doc API (hybrid AUTOMAP).

A user uploads a definitions spreadsheet (.xlsx) and/or an explanation deck
(.pptx); an extraction step (``app.ai.knowledge.doc_extractor``) reads them and
PROPOSES (a) per-column descriptions matched to a target data source's live
schema, (b) always-on instructions (KPI formulas / business rules / compliance),
and (c) example Q->SQL. The user reviews the preview, then applies:

- Applied column descriptions are merged into the matched ``DataSourceTable``
  ``columns`` JSON (each col's ``description`` set) — writes the schema.
- Instructions + examples are created as ``status='pending'`` ``StudioInstruction``
  / ``StudioExample`` rows (the existing review gate), mirroring
  ``studio_instructions.py`` / ``studio_examples.py``.

Two endpoints:
  POST /api/studios/{studio_id}/auto-configure/preview   (no writes)
  POST /api/studios/{studio_id}/auto-configure/apply      (writes)

Gating: every endpoint is behind ``flags.AUTOMAP`` (env ``HYBRID_AUTOMAP``),
read defensively via ``getattr(flags, "AUTOMAP", False)`` (the attribute is
wired by the platform owner). When OFF, routes 404 exactly like the Studios
feature gate does. Authorization mirrors ``studio_instructions.py``: org scope
+ studio role (editor+ to apply, viewer+ to preview).

This router is mounted under /api by main.py (registered as
``studio_autoconfigure.router``). NOTE: no ``from __future__ import annotations``
here — body pydantic models on routes can be mis-read as query params under
stringized annotations (the data_source_from_file landmine); kept off on purpose.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.auth import current_user
from app.dependencies import get_async_db, get_current_organization
from app.errors import AppError, ErrorCode
from app.models.data_source import DataSource
from app.models.datasource_table import DataSourceTable
from app.models.organization import Organization
from app.models.studio import Studio, StudioExample, StudioInstruction
from app.models.user import User
from app.services.studio_access import resolve_studio_access
from app.settings.hybrid_flags import flags

router = APIRouter(tags=["studios"])

# Roles that may APPLY (write). Preview only needs viewer+.
_EDITOR_ROLES = {"owner", "editor"}


# --------------------------------------------------------------------------- #
# Flag + role helpers (mirror studio_instructions.py exactly)
# --------------------------------------------------------------------------- #
def _require_flag() -> None:
    """Short-circuit when AUTOMAP is OFF — 404 like the Studios gate.

    ``getattr`` so a not-yet-wired flag attribute reads OFF instead of crashing.
    """
    if not getattr(flags, "AUTOMAP", False):
        raise AppError.not_found("studio.not_found", "Studio not found")


async def _require_role(
    db: AsyncSession, studio_id: str, user: User, *, editor: bool = False
) -> str:
    """Resolve the caller's effective role or raise 404/403.

    404 (not 403) when the user has no access at all so a Studio's existence
    isn't leaked to non-members.
    """
    role = await resolve_studio_access(db, studio_id, user)
    if role is None:
        raise AppError.not_found("studio.not_found", "Studio not found")
    if editor and role not in _EDITOR_ROLES:
        raise AppError.forbidden(
            ErrorCode.ACCESS_DENIED, "Editor or owner role required"
        )
    return role


async def _load_studio(db: AsyncSession, studio_id: str) -> Studio:
    """Load a non-deleted Studio or raise 404."""
    res = await db.execute(
        select(Studio).where(
            Studio.id == studio_id,
            Studio.deleted_at.is_(None),
        )
    )
    studio = res.scalar_one_or_none()
    if studio is None:
        raise AppError.not_found("studio.not_found", "Studio not found")
    return studio


async def _require_data_source(
    db: AsyncSession, data_source_id: str, organization: Organization
) -> DataSource:
    """Load a data source scoped to the org or raise 404."""
    res = await db.execute(
        select(DataSource).where(
            DataSource.id == str(data_source_id),
            DataSource.organization_id == organization.id,
        )
    )
    ds = res.scalar_one_or_none()
    if ds is None:
        raise AppError.not_found(
            ErrorCode.DATA_SOURCE_NOT_FOUND, "Data source not found"
        )
    return ds


# --------------------------------------------------------------------------- #
# Request bodies
# --------------------------------------------------------------------------- #
class AutoConfigurePreviewRequest(BaseModel):
    file_ids: List[str]
    data_source_id: str


class ApplyColumnDescription(BaseModel):
    column: str
    description: str
    table_id: Optional[str] = None


class ApplyInstruction(BaseModel):
    content: str
    category: Optional[str] = None


class ApplyExample(BaseModel):
    question: str
    answer: Optional[str] = None
    sql: Optional[str] = None


class AutoConfigureApplyRequest(BaseModel):
    data_source_id: str
    column_descriptions: List[ApplyColumnDescription] = []
    instructions: List[ApplyInstruction] = []
    examples: List[ApplyExample] = []


# --------------------------------------------------------------------------- #
# PREVIEW (viewer+) — no writes
# --------------------------------------------------------------------------- #
@router.post("/studios/{studio_id}/auto-configure/preview")
async def auto_configure_preview(
    studio_id: str,
    body: AutoConfigurePreviewRequest,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
) -> Dict[str, Any]:
    """Parse the uploaded docs + return the proposal WITHOUT writing anything.

    Proposal carries column_descriptions (with per-column match status against
    the live schema), instructions, examples and compliance rules.
    """
    _require_flag()
    await _require_role(db, studio_id, current_user)
    await _load_studio(db, studio_id)
    await _require_data_source(db, body.data_source_id, organization)

    from app.ai.knowledge.doc_extractor import extract_proposal

    result = await extract_proposal(
        db,
        organization=organization,
        file_ids=body.file_ids,
        data_source_id=body.data_source_id,
    )
    if isinstance(result, dict) and result.get("error"):
        raise AppError.bad_request(
            ErrorCode.VALIDATION, result["error"]
        )
    return result


# --------------------------------------------------------------------------- #
# APPLY (editor+) — writes descriptions to schema + pending rules/examples
# --------------------------------------------------------------------------- #
@router.post("/studios/{studio_id}/auto-configure/apply")
async def auto_configure_apply(
    studio_id: str,
    body: AutoConfigureApplyRequest,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
) -> Dict[str, Any]:
    """Apply a reviewed proposal.

    - column_descriptions -> merge ``description`` into the matched
      ``DataSourceTable.columns`` JSON (writes the schema). Each item may carry
      a ``table_id`` (from preview); otherwise the column name is matched across
      the data source's active tables.
    - instructions -> create ``StudioInstruction`` rows ``status='pending'``
      ``source='auto'`` (review gate).
    - examples -> create ``StudioExample`` rows ``status='pending'``
      ``source='auto'`` (review gate).
    Returns counts of what was written.
    """
    _require_flag()
    await _require_role(db, studio_id, current_user, editor=True)
    await _load_studio(db, studio_id)
    await _require_data_source(db, body.data_source_id, organization)

    # ── 1. Merge column descriptions into DataSourceTable.columns JSON ──────
    # Load the active tables for this data source once.
    tbl_res = await db.execute(
        select(DataSourceTable).where(
            DataSourceTable.datasource_id == str(body.data_source_id),
            DataSourceTable.is_active == True,  # noqa: E712
        )
    )
    tables = list(tbl_res.scalars().all())
    by_id = {str(t.id): t for t in tables}

    def _norm(s: str) -> str:
        return "".join(ch for ch in (s or "").lower().strip() if ch.isalnum())

    descriptions_written = 0
    columns_unmatched: List[str] = []

    for cd in body.column_descriptions:
        col = (cd.column or "").strip()
        desc = (cd.description or "").strip()
        if not col or not desc:
            continue

        # Resolve which tables to search: the hinted one, else all active.
        candidates = []
        if cd.table_id and str(cd.table_id) in by_id:
            candidates = [by_id[str(cd.table_id)]]
        else:
            candidates = tables

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
                if ename == col or ename.lower().strip() == col.lower().strip() \
                        or _norm(ename) == col_norm:
                    entry["description"] = desc
                    changed = True
                    applied = True
                    break
            if changed:
                # JSON in-place mutation must be flagged dirty (the
                # bootstrap_state landmine — same fix applies to columns).
                flag_modified(t, "columns")
                break
        if not applied:
            columns_unmatched.append(col)
        else:
            descriptions_written += 1

    # ── 2. Create pending StudioInstruction rows (mirror create logic) ─────
    instructions_created = 0
    for instr in body.instructions:
        content = (instr.content or "").strip()
        if not content:
            continue
        db.add(StudioInstruction(
            studio_id=studio_id,
            content=content,
            source="auto",
            status="pending",
        ))
        instructions_created += 1

    # ── 3. Create pending StudioExample rows (mirror create logic) ─────────
    examples_created = 0
    for ex in body.examples:
        question = (ex.question or "").strip()
        answer = (ex.answer or "").strip()
        if not question:
            continue
        # StudioExample.answer is NOT NULL — keep parity with the create route's
        # "answer required" rule but be lenient for doc-derived examples.
        if not answer:
            answer = "(see SQL)" if (ex.sql or "").strip() else "(no answer provided)"
        db.add(StudioExample(
            studio_id=studio_id,
            question=question,
            answer=answer,
            sql=(ex.sql or "").strip() or None,
            source="auto",
            status="pending",
        ))
        examples_created += 1

    await db.commit()

    return {
        "ok": True,
        "studio_id": studio_id,
        "data_source_id": body.data_source_id,
        "descriptions_written": descriptions_written,
        "columns_unmatched": columns_unmatched,
        "instructions_created": instructions_created,
        "examples_created": examples_created,
    }
