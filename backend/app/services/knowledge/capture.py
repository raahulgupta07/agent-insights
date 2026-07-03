"""capture — write + singularize learned facts into the Shared Memory store.

Public entry points (all fail-soft, all flag-gated by the caller):
  capture(...)                 — low-level: sanitize + upsert one fact per scope.
  capture_verified_query(...)  — a verified/golden query -> a shareable template.
  capture_mistake(...)         — a diagnosed error + its fix -> a 'mistake' fact.

Singularize: a fact is keyed by (org, scope_kind, scope_key, kind, source_hash);
re-learning the same fact bumps ``verified_count`` instead of inserting a
duplicate. Confidence gate: SHARED facts promote to status='active' (injectable)
at verified_count >= 2 OR when captured as ``verified=True``; otherwise they sit
'pending'. PRIVATE facts (scope_kind='user') are 'active' immediately (own
scratchpad) and never sanitized-to-death (kept raw for the owner).

Nothing here raises into a caller: every path is wrapped; on any error it logs
and returns 0.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Iterable

from sqlalchemy import select

from app.models.agent_knowledge import AgentKnowledge
from app.services.knowledge import sanitize as S
from app.services.knowledge.scope_resolver import resolve_agent_scopes, stable_hash

logger = logging.getLogger("app.services.knowledge.capture")

PROMOTE_AT = 2  # verified_count needed to promote a shared fact to 'active'


# --- pure helpers (unit-tested without a DB) --------------------------------

def content_hash(kind: str, content: Any) -> str:
    """Stable dedupe hash over the *sanitized* canonical content + kind."""
    canon = json.dumps(content, sort_keys=True, ensure_ascii=False, default=str)
    return stable_hash(str(kind or ""), canon)


def status_for(*, is_private: bool, verified: bool, count: int) -> str:
    """Confidence gate. Private = trusted immediately; shared needs a 2nd
    confirmation OR an explicit verified capture."""
    if is_private:
        return "active"
    if verified or count >= PROMOTE_AT:
        return "active"
    return "pending"


def prep_share(content: Any, *, is_private: bool) -> tuple[bool, Any]:
    """For a SHARED fact, run the leak firewall; for PRIVATE, keep raw.

    Returns (shareable, clean_content). shareable=False => skip the shared write.
    """
    if is_private:
        return True, content
    r = S.sanitize_content(content)
    return r.ok, r.content


# --- DB loader (fail-soft) ---------------------------------------------------

async def _load_connection_tables(db, data_source_id: str) -> list:
    """ConnectionTable rows backing a data source (via its connections)."""
    try:
        from app.models.data_source import DataSource
        from app.models.connection_table import ConnectionTable

        ds = (
            await db.execute(
                select(DataSource).where(DataSource.id == str(data_source_id))
            )
        ).scalar_one_or_none()
        if ds is None:
            return []
        conn_ids = [str(c.id) for c in (getattr(ds, "connections", None) or [])]
        if not conn_ids:
            return []
        rows = (
            await db.execute(
                select(ConnectionTable).where(ConnectionTable.connection_id.in_(conn_ids))
            )
        ).scalars().all()
        return list(rows)
    except Exception as e:  # pragma: no cover - defensive
        logger.debug("shared-memory: load tables failed for %s: %s", data_source_id, e)
        return []


async def _resolve_scopes_for_source(db, data_source_id: str) -> list[dict]:
    try:
        from app.models.data_source import DataSource
        ds = (
            await db.execute(select(DataSource).where(DataSource.id == str(data_source_id)))
        ).scalar_one_or_none()
        tables = await _load_connection_tables(db, data_source_id)
        return resolve_agent_scopes(ds, tables)
    except Exception as e:  # pragma: no cover
        logger.debug("shared-memory: resolve scopes failed: %s", e)
        return []


# --- core upsert -------------------------------------------------------------

async def _upsert_one(
    db,
    *,
    organization_id: str,
    scope_kind: str,
    scope_key: str,
    kind: str,
    title: str | None,
    content: Any,
    text: str | None,
    user_id: str | None,
    data_source_id: str | None,
    verified: bool,
) -> AgentKnowledge | None:
    src_hash = content_hash(kind, content)
    is_private = scope_kind == "user"

    existing = (
        await db.execute(
            select(AgentKnowledge).where(
                AgentKnowledge.organization_id == str(organization_id),
                AgentKnowledge.scope_kind == scope_kind,
                AgentKnowledge.scope_key == str(scope_key),
                AgentKnowledge.kind == kind,
                AgentKnowledge.source_hash == src_hash,
                AgentKnowledge.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.verified_count = (existing.verified_count or 1) + 1
        new_status = status_for(is_private=is_private, verified=verified,
                                 count=existing.verified_count)
        # only ever ratchet UP (pending -> active), never demote
        if new_status == "active":
            existing.status = "active"
        return existing

    row = AgentKnowledge(
        id=str(uuid.uuid4()),
        organization_id=str(organization_id),
        scope_kind=scope_kind,
        scope_key=str(scope_key),
        kind=kind,
        title=(title or "")[:300] or None,
        content_json=content,
        text=text,
        source_hash=src_hash,
        verified_count=1,
        created_by_user_id=str(user_id) if user_id else None,
        data_source_id=str(data_source_id) if data_source_id else None,
        status=status_for(is_private=is_private, verified=verified, count=1),
    )
    db.add(row)
    return row


async def capture(
    db,
    *,
    organization_id: str,
    scopes: Iterable[dict],
    kind: str,
    title: str | None,
    content: Any,
    text: str | None = None,
    user_id: str | None = None,
    data_source_id: str | None = None,
    verified: bool = False,
) -> int:
    """Sanitize (per tier) + upsert `content` under each scope. Returns rows
    written/updated. Fail-soft: never raises, never partially corrupts (caller
    commits)."""
    written = 0
    try:
        for scope in scopes or []:
            sk = str(scope.get("scope_kind") or "")
            key = str(scope.get("scope_key") or "")
            if not sk or not key:
                continue
            shareable, clean = prep_share(content, is_private=(sk == "user"))
            if not shareable or clean in (None, {}, []):
                continue
            row = await _upsert_one(
                db, organization_id=organization_id, scope_kind=sk, scope_key=key,
                kind=kind, title=title, content=clean, text=text,
                user_id=user_id, data_source_id=data_source_id, verified=verified,
            )
            if row is not None:
                written += 1
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("shared-memory capture failed: %s", e)
    return written


# --- convenience hooks -------------------------------------------------------

async def capture_verified_query(
    db,
    *,
    organization_id: str,
    data_source_id: str,
    sql: str,
    name: str | None = None,
    user_id: str | None = None,
) -> int:
    """A verified/golden query -> a shareable parameterized template, captured
    under the source's model/schema scopes (verified=True => active now)."""
    scopes = await _resolve_scopes_for_source(db, data_source_id)
    if not scopes:
        return 0
    tmpl = S.sanitize_template(sql or "")
    content = {"kind": "query_template", "template": tmpl.content}
    return await capture(
        db, organization_id=organization_id, scopes=scopes, kind="query_template",
        title=(name or "verified query")[:120], content=content,
        text=tmpl.content, user_id=user_id, data_source_id=data_source_id,
        verified=True,
    )


async def capture_global(
    db,
    *,
    organization_id: str,
    kind: str,
    title: str | None,
    content: Any,
    text: str | None = None,
    user_id: str | None = None,
    verified: bool = True,
) -> int:
    """Write a GLOBAL (tier-3) fact — read by EVERY agent in the org, regardless
    of data. For house rules / universal conventions / org-wide mistakes.
    Sanitized like any shared fact (org tier is not private)."""
    from app.services.knowledge.scope_resolver import org_scope
    return await capture(
        db, organization_id=organization_id, scopes=[org_scope(organization_id)],
        kind=kind, title=title, content=content, text=text,
        user_id=user_id, data_source_id=None, verified=verified,
    )


async def capture_mistake(
    db,
    *,
    organization_id: str,
    data_source_id: str,
    error_class: str,
    fix_shape: str,
    failed_template: str | None = None,
    fixed_template: str | None = None,
    user_id: str | None = None,
) -> int:
    """A diagnosed error + how it was fixed -> a 'mistake' fact ('never repeat').

    Only the STRUCTURE travels: error class, the shape of the fix, and
    parameterized templates. Captured as unverified (needs a 2nd sighting to
    promote) so a one-off fluke doesn't teach everyone.
    """
    scopes = await _resolve_scopes_for_source(db, data_source_id)
    if not scopes:
        return 0
    content = {
        "kind": "mistake",
        "error_class": (error_class or "")[:200],
        "fix_shape": (fix_shape or "")[:500],
    }
    if failed_template:
        content["failed_template"] = S.sanitize_template(failed_template).content
    if fixed_template:
        content["fixed_template"] = S.sanitize_template(fixed_template).content
    return await capture(
        db, organization_id=organization_id, scopes=scopes, kind="mistake",
        title=(error_class or "mistake")[:120], content=content,
        text=fix_shape, user_id=user_id, data_source_id=data_source_id,
        verified=False,
    )
