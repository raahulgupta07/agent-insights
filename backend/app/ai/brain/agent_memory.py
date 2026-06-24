"""Agent memory store — MemGPT-style deliberate page-in/out (vectorless).

`write_memory` stows an agent-authored memory; `recall` pages the most relevant
ones back. Personal scope is live (own scratchpad); project/org scope lands
'pending' and only surfaces once approved. Retrieval is Postgres full-text
(ts_rank) with a token-Jaccard fallback — NO embeddings (repo is vectorless).

Every function never raises into the caller — returns a safe default + logs.
"""
from __future__ import annotations

import logging
import uuid
from typing import List, Optional

from sqlalchemy import text as _sql

logger = logging.getLogger(__name__)

_VALID_SCOPES = ("personal", "project", "org")


async def write_memory(
    db,
    *,
    organization,
    user=None,
    scope: str = "personal",
    text: str,
    mem_key: Optional[str] = None,
    data_source_id: Optional[str] = None,
) -> Optional[str]:
    """Insert an agent memory. personal -> approved; project/org -> pending.

    Returns the new id, or None on failure / empty text.
    """
    try:
        body = (text or "").strip()
        if not body:
            return None
        sc = scope if scope in _VALID_SCOPES else "personal"
        org_id = str(getattr(organization, "id", None) or "")
        if not org_id:
            return None
        user_id = str(getattr(user, "id", None) or "") or None
        if sc == "personal" and not user_id:
            # personal memory needs an owner; without one, hold for approval
            sc = "project"
        status = "approved" if sc == "personal" else "pending"

        from app.models.agent_memory import AgentMemory

        row = AgentMemory(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            user_id=user_id if sc == "personal" else None,
            data_source_id=str(data_source_id) if data_source_id else None,
            scope=sc,
            mem_key=(mem_key or None),
            text=body[:8000],
            status=status,
            source="agent",
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row.id
    except Exception:
        logger.exception("agent_memory.write_memory failed")
        try:
            await db.rollback()
        except Exception:
            pass
        return None


def _bitemporal_enabled() -> bool:
    try:
        from app.settings.hybrid_flags import flags
        return bool(flags.BITEMPORAL)
    except Exception:
        return False


def _visibility_clause(has_ds: bool) -> str:
    # own approved personal OR approved shared (project/org). The ds restriction
    # is only added when a ds is given (avoids binding a bare NULL param, which
    # asyncpg can't type-infer).
    shared = "scope IN ('project','org') AND status = 'approved'"
    if has_ds:
        shared += " AND (data_source_id = :ds OR data_source_id IS NULL)"
    clause = (
        "organization_id = :org AND deleted_at IS NULL AND ("
        "(scope = 'personal' AND user_id = :uid AND status = 'approved') "
        "OR (" + shared + ")"
        ")"
    )
    # Bi-temporal (HYBRID_BITEMPORAL): only currently-valid memories surface; a
    # superseded memory carries invalid_at. OFF -> clause is byte-identical.
    if _bitemporal_enabled():
        clause = "(" + clause + ") AND invalid_at IS NULL"
    return clause


async def recall(
    db,
    *,
    organization,
    query: Optional[str],
    user_id: Optional[str] = None,
    data_source_id: Optional[str] = None,
    k: int = 5,
) -> List[dict]:
    """Return up to k relevant visible memories as [{mem_key, text}].

    FTS (ts_rank) first; if no FTS hits, fall back to token-Jaccard over recent
    visible rows. Never raises -> [].
    """
    try:
        org_id = str(getattr(organization, "id", None) or "")
        if not org_id:
            return []
        q = (query or "").strip()
        # bind uid as a non-null sentinel so the personal branch is typed; an
        # empty string never matches a real user id, so it's a safe no-match.
        params = {"org": org_id, "uid": str(user_id or ""), "k": int(k)}
        has_ds = bool(data_source_id)
        if has_ds:
            params["ds"] = str(data_source_id)
        vis = _visibility_clause(has_ds)

        dialect = db.bind.dialect.name if getattr(db, "bind", None) else ""
        rows = []
        if q and dialect == "postgresql":
            params["q"] = q
            sql = _sql(
                "SELECT mem_key, text FROM agent_memories WHERE " + vis +
                " AND to_tsvector('english', text) @@ plainto_tsquery('english', :q) "
                "ORDER BY ts_rank(to_tsvector('english', text), plainto_tsquery('english', :q)) DESC "
                "LIMIT :k"
            )
            rows = (await db.execute(sql, params)).fetchall()

        if not rows:
            # fallback: recent visible rows ranked by token-Jaccard (vectorless)
            recent = (
                await db.execute(
                    _sql(
                        "SELECT mem_key, text FROM agent_memories WHERE " + vis +
                        " ORDER BY created_at DESC LIMIT 200"
                    ),
                    params,
                )
            ).fetchall()
            if q and recent:
                try:
                    from app.ai.brain.query_cache_store import _tokens, _jaccard

                    qt = _tokens(q)
                    scored = sorted(
                        recent,
                        key=lambda r: _jaccard(qt, _tokens(r[1] or "")),
                        reverse=True,
                    )
                    rows = scored[: int(k)]
                except Exception:
                    rows = recent[: int(k)]
            else:
                rows = recent[: int(k)]

        return [{"mem_key": r[0] or "", "text": r[1] or ""} for r in rows]
    except Exception:
        logger.exception("agent_memory.recall failed")
        return []
