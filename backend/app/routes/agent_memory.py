"""Agent-memory review routes (#1 MEMORY TOOL — review surface).

Human review surface for agent-authored memories (`agent_memories`). The
`remember`/`recall` tools write rows; SHARED-scope writes land `status='pending'`
and need approval before recall surfaces them (the gate). This router lets an
operator LIST the pending/approved memories for their org and approve or reject.

Conventions copied verbatim from ``app.routes.skill``: deps
(``get_async_db``/``get_current_organization``), ``current_user`` auth, async
SQLAlchemy (``select`` + ``await db.execute``), ``AppError``/``ErrorCode`` errors,
no ``/api`` prefix (main.py adds it).

Gating (CLAUDE.md HARD RULE 4): every endpoint is gated by ``flags.AGENT_MEMORY``
(env ``HYBRID_AGENT_MEMORY``, default OFF). When the flag is off, ``GET`` returns
``[]`` (mirrors ``skill.list_skills``) and every write raises 403 (mirrors
``workflows.run_workflow``), so a fresh deploy behaves exactly like upstream Dash.
"""

from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_user
from app.dependencies import get_async_db, get_current_organization
from app.errors import AppError, ErrorCode
from app.models.organization import Organization
from app.models.user import User

router = APIRouter(tags=["agent-memory"])


def _ensure_enabled() -> None:
    """Raise 403 unless flags.AGENT_MEMORY is on (mirrors workflows write-gate)."""
    from app.settings.hybrid_flags import flags

    if not flags.AGENT_MEMORY:
        raise AppError(
            ErrorCode.FEATURE_LOCKED,
            "Agent memory is not enabled.",
            status_code=403,
        )


def _serialize(m: Any) -> dict:
    return {
        "id": str(m.id),
        "text": m.text,
        "mem_key": m.mem_key,
        "scope": m.scope,
        "status": m.status,
        "source": m.source,
        "user_id": str(m.user_id) if m.user_id else None,
        "data_source_id": str(m.data_source_id) if m.data_source_id else None,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


async def _load_owned_memory(
    db: AsyncSession, memory_id: str, organization: Organization
):
    """Load a non-deleted, currently-valid memory scoped to this org by id, or None."""
    from app.models.agent_memory import AgentMemory

    stmt = (
        select(AgentMemory)
        .where(
            AgentMemory.id == memory_id,
            AgentMemory.organization_id == str(organization.id),
            AgentMemory.deleted_at.is_(None),
        )
        .limit(1)
    )
    return (await db.execute(stmt)).scalars().first()


@router.get("/agent/memories")
async def list_memories(
    status: Optional[str] = None,
    scope: Optional[str] = None,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
) -> List[dict]:
    """List currently-valid memories for this org. [] when flag off.

    Optional ``status`` (pending|approved) and ``scope`` filters. Personal-scope
    rows are only ever returned to their own author (user_id == current user).
    Ordered newest-first.
    """
    from app.settings.hybrid_flags import flags

    if not flags.AGENT_MEMORY:
        return []

    from app.models.agent_memory import AgentMemory

    stmt = select(AgentMemory).where(
        AgentMemory.organization_id == str(organization.id),
        AgentMemory.deleted_at.is_(None),
        AgentMemory.invalid_at.is_(None),
    )

    if status:
        stmt = stmt.where(AgentMemory.status == status)
    if scope:
        stmt = stmt.where(AgentMemory.scope == scope)

    # Personal rows are private to their author: only return the caller's own.
    stmt = stmt.where(
        (AgentMemory.scope != "personal")
        | (AgentMemory.user_id == str(current_user.id))
    )

    stmt = stmt.order_by(AgentMemory.created_at.desc())

    rows = (await db.execute(stmt)).scalars().all()
    return [_serialize(m) for m in rows]


@router.post("/agent/memories/{memory_id}/approve")
async def approve_memory(
    memory_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
) -> dict:
    """Approve a memory (status -> 'approved'). 403 when flag off; 404 if missing."""
    _ensure_enabled()

    memory = await _load_owned_memory(db, memory_id, organization)
    if memory is None:
        raise AppError.not_found(ErrorCode.ENTITY_NOT_FOUND, "Memory not found.")

    memory.status = "approved"
    await db.commit()
    await db.refresh(memory)
    return _serialize(memory)


@router.post("/agent/memories/{memory_id}/reject")
async def reject_memory(
    memory_id: str,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
) -> dict:
    """Reject a memory by RETIRING it bi-temporally.

    There is no 'rejected' status; the model retires a row via ``invalid_at``
    (``invalid_at IS NULL`` = currently valid). Setting it drops the row out of
    recall AND out of the pending list (which filters ``invalid_at IS NULL``).
    Cols are TIMESTAMP WITHOUT TIME ZONE -> use NAIVE UTC. 403 when flag off.
    """
    _ensure_enabled()

    memory = await _load_owned_memory(db, memory_id, organization)
    if memory is None:
        raise AppError.not_found(ErrorCode.ENTITY_NOT_FOUND, "Memory not found.")

    memory.invalid_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()
    await db.refresh(memory)
    return _serialize(memory)
