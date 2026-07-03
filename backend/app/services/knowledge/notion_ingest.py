"""Notion → institutional KnowledgeDoc ingest (Part E, flag ``HYBRID_NOTION_KB``).

Pull Notion pages, flatten their block tree into plain text, and persist each
page as a ``KnowledgeDoc`` (+ ``KnowledgeDocChunk`` rows) through the EXACT same
doc-creation path the manual doc upload uses — ``ai/knowledge/docs_index.ingest_doc``
(chunk → FTS-indexed rows). Once a human approves the doc in the Knowledge → Review
tab the P4 ``services/knowledge/institutional.py`` layer retrieves it (org-scoped +
approved-only Postgres full-text search) and grounds the planner with it. So a
Notion page about "activation" resolves the business term instead of a guess.

Design (mirrors the rest of the hybrid knowledge layer):

* **Reuse, don't rebuild.** Persistence delegates to ``ingest_doc`` — the same
  VECTORLESS ingest the upload/paste path uses. Docs land ``status='pending'``
  (the approval-gate convention) so a freshly synced page is invisible to the
  agent until approved; nothing new-user-facing goes live automatically.
* **Dedupe by external id.** Each page's stable Notion URL is written to the
  ``KnowledgeDoc.url`` column and used as the external key: a re-sync of an
  *edited* page ingests the new content and soft-deletes the prior version for
  that URL, so one Notion page maps to at most one live doc.
* **Flag-gated, fail-soft.** ``flags.NOTION_KB`` OFF → no-op ``{"enabled": False}``.
  A missing token → clean early return (no network). ANY per-page error is
  swallowed and counted; the sync NEVER raises. Tokens are never logged.

Public surface:
    blocks_to_text(blocks) -> str                              (pure)
    async sync_notion(db, *, organization_id, token, page_ids=None) -> dict
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from types import SimpleNamespace
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

_NOTION_API = "https://api.notion.com/v1"
_NOTION_VERSION = "2022-06-28"
_HTTP_TIMEOUT = 20
# Defensive caps so a giant workspace can't run unbounded.
_MAX_PAGES = 100
_MAX_BLOCKS_PER_PAGE = 500


# ---------------------------------------------------------------------------
# Pure block → text conversion (unit-tested, never raises, no network)
# ---------------------------------------------------------------------------

def _rich_text(rich: Any) -> str:
    """Join a Notion ``rich_text`` array to plain text. Pure, never raises."""
    if not isinstance(rich, list):
        return ""
    out: List[str] = []
    for span in rich:
        if not isinstance(span, dict):
            continue
        # Every rich_text span carries a flattened ``plain_text``; fall back to
        # the nested ``text.content`` if an odd payload omits it.
        txt = span.get("plain_text")
        if not txt:
            t = span.get("text")
            if isinstance(t, dict):
                txt = t.get("content")
        if txt:
            out.append(str(txt))
    return "".join(out)


def _block_to_text(block: Any) -> str:
    """Flatten ONE Notion block to a line of text. Pure, never raises.

    Handles the common text-bearing block types (paragraph, headings, list
    items, to-dos, quotes, callouts, toggles, code). Unknown / layout-only
    blocks (divider, image, ...) yield ``""`` and are dropped by the caller.
    """
    if not isinstance(block, dict):
        return ""
    btype = block.get("type")
    if not btype:
        return ""
    payload = block.get(btype)
    if not isinstance(payload, dict):
        return ""

    text = _rich_text(payload.get("rich_text"))
    if not text:
        return ""

    if btype in ("heading_1", "heading_2", "heading_3"):
        return text
    if btype in ("bulleted_list_item", "numbered_list_item", "toggle"):
        return f"- {text}"
    if btype == "to_do":
        mark = "x" if payload.get("checked") else " "
        return f"- [{mark}] {text}"
    if btype == "quote":
        return f"> {text}"
    if btype == "callout":
        return text
    if btype == "code":
        return text
    # paragraph + anything else text-bearing
    return text


def blocks_to_text(blocks: Any) -> str:
    """Flatten a list of Notion blocks to a plain-text body. Pure, never raises."""
    if not isinstance(blocks, list):
        return ""
    lines: List[str] = []
    for block in blocks:
        line = _block_to_text(block)
        if line:
            lines.append(line)
    return "\n\n".join(lines)


def _page_title(page: Any) -> str:
    """Best-effort page title from a Notion page object. Pure, never raises."""
    if not isinstance(page, dict):
        return ""
    props = page.get("properties")
    if isinstance(props, dict):
        for prop in props.values():
            if isinstance(prop, dict) and prop.get("type") == "title":
                title = _rich_text(prop.get("title"))
                if title:
                    return title
    return ""


def _page_url(page_id: str) -> str:
    """Stable Notion URL used as the external dedupe key."""
    return f"https://www.notion.so/{str(page_id or '').replace('-', '')}"


# ---------------------------------------------------------------------------
# Network (blocking urllib, guarded, offloaded to a thread by the caller)
# ---------------------------------------------------------------------------

def _api_request(token: str, path: str, *, method: str = "GET", body: Optional[dict] = None) -> Optional[dict]:
    """One Notion API call. Returns parsed JSON or ``None`` on ANY error.

    Blocking (urllib) — the async entrypoint runs it via ``asyncio.to_thread``.
    The token is sent in the Authorization header and NEVER logged.
    """
    if not token:
        return None
    url = path if path.startswith("http") else f"{_NOTION_API}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Notion-Version", _NOTION_VERSION)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        logger.warning("notion_ingest: API %s %s -> HTTP %s", method, path, getattr(e, "code", "?"))
        return None
    except Exception as e:  # noqa: BLE001 — fail-soft, never surface token/details
        logger.warning("notion_ingest: API %s %s failed: %s", method, path, type(e).__name__)
        return None


def _discover_page_ids(token: str, limit: int) -> List[str]:
    """List page ids via Notion ``/search`` when the caller gave none."""
    body = {"filter": {"value": "page", "property": "object"}, "page_size": min(limit, 100)}
    res = _api_request(token, "/search", method="POST", body=body)
    if not isinstance(res, dict):
        return []
    ids: List[str] = []
    for row in res.get("results", []) or []:
        if isinstance(row, dict) and row.get("object") == "page" and row.get("id"):
            ids.append(str(row["id"]))
        if len(ids) >= limit:
            break
    return ids


def _fetch_blocks(token: str, page_id: str) -> List[dict]:
    """Fetch a page's block children (paginated, capped). Fail-soft → []."""
    blocks: List[dict] = []
    cursor: Optional[str] = None
    while len(blocks) < _MAX_BLOCKS_PER_PAGE:
        path = f"/blocks/{page_id}/children?page_size=100"
        if cursor:
            path += f"&start_cursor={cursor}"
        res = _api_request(token, path)
        if not isinstance(res, dict):
            break
        results = res.get("results") or []
        if not isinstance(results, list):
            break
        blocks.extend(b for b in results if isinstance(b, dict))
        if not res.get("has_more"):
            break
        cursor = res.get("next_cursor")
        if not cursor:
            break
    return blocks[:_MAX_BLOCKS_PER_PAGE]


# ---------------------------------------------------------------------------
# Persist (reuse docs_index.ingest_doc + external-id dedupe on the url column)
# ---------------------------------------------------------------------------

async def _approve_doc(db: Any, doc_id: str) -> None:
    """Flip one just-ingested ``KnowledgeDoc`` to ``status='approved'``. Fail-soft.

    Reuses the EXACT mechanism of the Knowledge → Review approve endpoint
    (``routes/knowledge.py``: ``row.status = "approved"; await db.commit()`` — no
    bitemporal supersede for the ``doc`` kind). Only used when the caller opted into
    auto-approve; NEVER raises (a failed flip just leaves the doc ``pending``).
    """
    from sqlalchemy import select
    from app.models.knowledge_doc import KnowledgeDoc

    try:
        row = (
            await db.execute(select(KnowledgeDoc).where(KnowledgeDoc.id == doc_id))
        ).scalar_one_or_none()
        if row is not None and row.status != "approved":
            row.status = "approved"
            await db.commit()
    except Exception:  # noqa: BLE001 — approve is best-effort; pending is a safe fallback
        try:
            await db.rollback()
        except Exception:
            pass


async def _persist_page(
    db: Any, *, organization_id: str, title: str, body: str, url: str, auto_approve: bool = False
) -> Optional[str]:
    """Persist one page via the shared ingest path, dedupe by ``url``.

    Reuses ``docs_index.ingest_doc`` (chunk + FTS rows, lands ``status='pending'``)
    then soft-deletes any OTHER live ``KnowledgeDoc`` sharing this Notion URL so an
    edited page (new content_hash) doesn't leave a stale twin. When ``auto_approve``
    is set, the freshly ingested doc is flipped to ``status='approved'`` (reusing the
    Review approve mechanism) so it grounds answers immediately. Returns the doc id,
    or ``None`` on failure. Never raises.
    """
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
            source="notion",
            url=url,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("notion_ingest: persist failed: %s", type(e).__name__)
        return None

    doc_id = res.get("doc_id")
    # External-id dedupe: retire older docs for the same Notion URL.
    try:
        stale = (
            await db.execute(
                select(KnowledgeDoc).where(
                    KnowledgeDoc.organization_id == str(organization_id),
                    KnowledgeDoc.source == "notion",
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

    # Optional: skip Review — flip the just-ingested doc live immediately.
    if auto_approve and doc_id:
        await _approve_doc(db, doc_id)
    return doc_id


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

async def sync_notion(
    db: Any,
    *,
    organization_id: str,
    token: str,
    page_ids: Optional[List[str]] = None,
    auto_approve: bool = False,
) -> dict:
    """Sync Notion pages into the org's institutional KnowledgeDocs. Fail-soft.

    Flag-gated (``flags.NOTION_KB``). With no ``page_ids`` the integration's
    accessible pages are discovered via ``/search``. Each page's block tree is
    flattened to text and persisted (``status='pending'``, dedupe by URL). With
    ``auto_approve=True`` each ingested doc is flipped ``approved`` right away
    (reusing the Review approve mechanism) so it grounds answers without a manual
    Review step; default ``False`` keeps the pending-until-approved behavior.
    Returns a summary ``{"enabled", "ok", "pages", "ingested", "skipped", "errors"}``;
    NEVER raises. The token is passed through only to the HTTP layer, never logged.
    """
    # Flag gate FIRST — OFF is a true no-op.
    try:
        from app.settings.hybrid_flags import flags
        if not flags.NOTION_KB:
            return {"enabled": False, "ok": False, "pages": 0, "ingested": 0, "skipped": 0, "errors": 0}
    except Exception:
        return {"enabled": False, "ok": False, "pages": 0, "ingested": 0, "skipped": 0, "errors": 0}

    org_id = str(organization_id or "").strip()
    token = (token or "").strip()
    if not org_id or not token:
        # Missing creds → clean early return, no network.
        return {"enabled": True, "ok": False, "reason": "no_token", "pages": 0, "ingested": 0, "skipped": 0, "errors": 0}

    import asyncio

    ids = [str(p).strip() for p in (page_ids or []) if str(p).strip()]
    if not ids:
        try:
            ids = await asyncio.to_thread(_discover_page_ids, token, _MAX_PAGES)
        except Exception:
            ids = []
    ids = ids[:_MAX_PAGES]

    ingested = 0
    errors = 0
    skipped = 0
    for page_id in ids:
        try:
            page = await asyncio.to_thread(_api_request, token, f"/pages/{page_id}")
            blocks = await asyncio.to_thread(_fetch_blocks, token, page_id)
            body = blocks_to_text(blocks)
            if not body.strip():
                skipped += 1
                continue
            title = _page_title(page) or f"Notion page {page_id[:8]}"
            doc_id = await _persist_page(
                db, organization_id=org_id, title=title, body=body, url=_page_url(page_id),
                auto_approve=auto_approve,
            )
            if doc_id:
                ingested += 1
            else:
                errors += 1
        except Exception as e:  # noqa: BLE001 — one bad page never kills the sync
            logger.warning("notion_ingest: page %s failed: %s", str(page_id)[:8], type(e).__name__)
            errors += 1

    return {
        "enabled": True,
        "ok": True,
        "pages": len(ids),
        "ingested": ingested,
        "skipped": skipped,
        "errors": errors,
    }
