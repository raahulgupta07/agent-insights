"""Slack → institutional KnowledgeDoc ingest (Part E, flag ``HYBRID_NOTION_KB``).

Pull Slack channel threads, flatten each root-thread conversation into plain text,
and persist it as a ``KnowledgeDoc`` (+ chunks) via the SAME doc-creation path the
manual upload uses (``ai/knowledge/docs_index.ingest_doc``). Once approved in the
Knowledge → Review tab, the P4 ``services/knowledge/institutional.py`` layer
retrieves it so a decision captured in a Slack thread ("we redefined churn as …")
grounds later business-term questions instead of a guess.

Mirrors ``notion_ingest.py`` exactly (same flag, same reuse, same fail-soft +
dedupe-by-external-id discipline). The external key is a stable
``slack:{channel}:{thread_ts}`` URI written to ``KnowledgeDoc.url``, so a re-sync of
a grown thread replaces the prior version rather than duplicating it. The token is
never logged or hardcoded.

Public surface:
    messages_to_text(messages) -> str                                (pure)
    async sync_slack(db, *, organization_id, token, channel_ids=None) -> dict
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from types import SimpleNamespace
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

_SLACK_API = "https://slack.com/api"
_HTTP_TIMEOUT = 20
# Defensive caps.
_MAX_CHANNELS = 50
_MAX_THREADS_PER_CHANNEL = 50
_MAX_REPLIES = 200


# ---------------------------------------------------------------------------
# Pure message → text conversion (unit-tested, never raises, no network)
# ---------------------------------------------------------------------------

def _message_line(msg: Any) -> str:
    """Flatten ONE Slack message to a line. Pure, never raises.

    Skips join/leave/channel-topic system messages (``subtype`` present) and
    empty texts. Prefixes the author id when available so a thread reads as a
    conversation. Slack ``<@U123>`` / ``<#C123|name>`` mention markup is left
    intact (it is still searchable text).
    """
    if not isinstance(msg, dict):
        return ""
    if msg.get("subtype"):
        return ""
    text = msg.get("text")
    if not text or not str(text).strip():
        return ""
    text = str(text).strip()
    author = msg.get("user") or msg.get("username") or msg.get("bot_id")
    return f"{author}: {text}" if author else text


def messages_to_text(messages: Any) -> str:
    """Flatten a Slack thread (list of messages) to plain text. Pure, never raises."""
    if not isinstance(messages, list):
        return ""
    lines: List[str] = []
    for msg in messages:
        line = _message_line(msg)
        if line:
            lines.append(line)
    return "\n\n".join(lines)


def _thread_url(channel_id: str, thread_ts: str) -> str:
    """Stable synthetic external key for a thread (dedupe on ``KnowledgeDoc.url``)."""
    return f"slack:{channel_id}:{thread_ts}"


def _thread_title(channel_id: str, messages: Any) -> str:
    """Best-effort title = channel + first-message snippet. Pure, never raises."""
    snippet = ""
    if isinstance(messages, list):
        for msg in messages:
            if isinstance(msg, dict) and msg.get("text") and not msg.get("subtype"):
                snippet = " ".join(str(msg["text"]).split())[:80]
                break
    base = f"Slack thread ({channel_id})"
    return f"{base}: {snippet}" if snippet else base


# ---------------------------------------------------------------------------
# Network (blocking urllib, guarded, offloaded to a thread by the caller)
# ---------------------------------------------------------------------------

def _api_get(token: str, method: str, params: dict) -> Optional[dict]:
    """One Slack Web API GET. Returns JSON (with ``ok``) or ``None`` on error.

    Blocking (urllib) — the async entrypoint offloads it via ``asyncio.to_thread``.
    Token sent as a Bearer header, NEVER logged.
    """
    if not token:
        return None
    query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    url = f"{_SLACK_API}/{method}?{query}"
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if isinstance(data, dict) and not data.get("ok"):
            logger.warning("slack_ingest: %s -> not ok (%s)", method, data.get("error"))
        return data if isinstance(data, dict) else None
    except urllib.error.HTTPError as e:
        logger.warning("slack_ingest: %s -> HTTP %s", method, getattr(e, "code", "?"))
        return None
    except Exception as e:  # noqa: BLE001 — fail-soft, never surface token/details
        logger.warning("slack_ingest: %s failed: %s", method, type(e).__name__)
        return None


def _root_thread_ts(token: str, channel_id: str, limit: int) -> List[str]:
    """List root-message timestamps in a channel (each = a thread head)."""
    res = _api_get(token, "conversations.history", {"channel": channel_id, "limit": min(limit, 200)})
    if not isinstance(res, dict) or not res.get("ok"):
        return []
    ts_list: List[str] = []
    for msg in res.get("messages", []) or []:
        if not isinstance(msg, dict) or msg.get("subtype"):
            continue
        ts = msg.get("thread_ts") or msg.get("ts")
        if ts and ts not in ts_list:
            ts_list.append(str(ts))
        if len(ts_list) >= limit:
            break
    return ts_list


def _thread_messages(token: str, channel_id: str, thread_ts: str) -> List[dict]:
    """Fetch a thread's messages (root + replies), capped. Fail-soft → []."""
    res = _api_get(
        token, "conversations.replies",
        {"channel": channel_id, "ts": thread_ts, "limit": min(_MAX_REPLIES, 200)},
    )
    if not isinstance(res, dict) or not res.get("ok"):
        return []
    msgs = res.get("messages") or []
    return [m for m in msgs if isinstance(m, dict)][:_MAX_REPLIES]


# ---------------------------------------------------------------------------
# Persist (reuse docs_index.ingest_doc + external-id dedupe on the url column)
# ---------------------------------------------------------------------------

async def _persist_thread(db: Any, *, organization_id: str, title: str, body: str, url: str) -> Optional[str]:
    """Persist one thread via the shared ingest path, dedupe by ``url``. Never raises."""
    from datetime import datetime, timezone
    from sqlalchemy import select
    from app.ai.knowledge.docs_index import ingest_doc
    from app.models.knowledge_doc import KnowledgeDoc

    try:
        res = await ingest_doc(
            db,
            organization=SimpleNamespace(id=organization_id),
            title=title,
            body=body,
            source="slack",
            url=url,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("slack_ingest: persist failed: %s", type(e).__name__)
        return None

    doc_id = res.get("doc_id")
    try:
        stale = (
            await db.execute(
                select(KnowledgeDoc).where(
                    KnowledgeDoc.organization_id == str(organization_id),
                    KnowledgeDoc.source == "slack",
                    KnowledgeDoc.url == url,
                    KnowledgeDoc.id != doc_id,
                    KnowledgeDoc.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        if stale:
            now = datetime.now(timezone.utc)
            for old in stale:
                old.deleted_at = now
            await db.commit()
    except Exception:
        try:
            await db.rollback()
        except Exception:
            pass
    return doc_id


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

async def sync_slack(
    db: Any,
    *,
    organization_id: str,
    token: str,
    channel_ids: Optional[List[str]] = None,
) -> dict:
    """Sync Slack channel threads into the org's institutional KnowledgeDocs. Fail-soft.

    Flag-gated (``flags.NOTION_KB``). With no ``channel_ids`` the workspace's
    accessible channels are discovered via ``conversations.list``. Each root thread
    is flattened to text and persisted (``status='pending'``, dedupe by URL). Returns
    ``{"enabled", "ok", "threads", "ingested", "skipped", "errors"}``; NEVER raises.
    The token is passed only to the HTTP layer, never logged.
    """
    try:
        from app.settings.hybrid_flags import flags
        if not flags.NOTION_KB:
            return {"enabled": False, "ok": False, "threads": 0, "ingested": 0, "skipped": 0, "errors": 0}
    except Exception:
        return {"enabled": False, "ok": False, "threads": 0, "ingested": 0, "skipped": 0, "errors": 0}

    org_id = str(organization_id or "").strip()
    token = (token or "").strip()
    if not org_id or not token:
        return {"enabled": True, "ok": False, "reason": "no_token", "threads": 0, "ingested": 0, "skipped": 0, "errors": 0}

    import asyncio

    channels = [str(c).strip() for c in (channel_ids or []) if str(c).strip()]
    if not channels:
        try:
            res = await asyncio.to_thread(
                _api_get, token, "conversations.list", {"limit": _MAX_CHANNELS, "exclude_archived": "true"}
            )
            if isinstance(res, dict) and res.get("ok"):
                channels = [
                    str(c["id"]) for c in (res.get("channels") or [])
                    if isinstance(c, dict) and c.get("id")
                ]
        except Exception:
            channels = []
    channels = channels[:_MAX_CHANNELS]

    ingested = 0
    errors = 0
    skipped = 0
    threads_seen = 0
    for channel_id in channels:
        try:
            ts_list = await asyncio.to_thread(_root_thread_ts, token, channel_id, _MAX_THREADS_PER_CHANNEL)
        except Exception:
            errors += 1
            continue
        for thread_ts in ts_list:
            threads_seen += 1
            try:
                msgs = await asyncio.to_thread(_thread_messages, token, channel_id, thread_ts)
                body = messages_to_text(msgs)
                if not body.strip():
                    skipped += 1
                    continue
                doc_id = await _persist_thread(
                    db,
                    organization_id=org_id,
                    title=_thread_title(channel_id, msgs),
                    body=body,
                    url=_thread_url(channel_id, thread_ts),
                )
                if doc_id:
                    ingested += 1
                else:
                    errors += 1
            except Exception as e:  # noqa: BLE001 — one bad thread never kills the sync
                logger.warning("slack_ingest: thread %s failed: %s", str(thread_ts)[:12], type(e).__name__)
                errors += 1

    return {
        "enabled": True,
        "ok": True,
        "threads": threads_seen,
        "ingested": ingested,
        "skipped": skipped,
        "errors": errors,
    }
