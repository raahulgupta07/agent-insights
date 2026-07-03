"""Institutional-knowledge RAG into data answers (P4).

Business questions ("what's our activation rate?", "how did the March launch
land?") should resolve to the *right* metric using the org's approved
institutional docs — metric definitions, incident notes, launch write-ups.
Those docs already exist (``KnowledgeDoc`` / ``KnowledgeDocChunk``, ingested via
``ai/knowledge/docs_index.py`` and human-approved in the Knowledge → Review tab)
but they only ever fed the *display* Docs section — never the data planner. This
module retrieves them, access-controlled, and formats a compact planner block so
a business term grounds on the approved definition instead of a guess.

Design (mirrors the rest of the hybrid knowledge layer):

* **Reuse, don't rebuild.** Retrieval delegates to
  ``ai/knowledge/docs_index.search_docs`` — the same VECTORLESS Postgres
  full-text search (``to_tsvector`` / ``plainto_tsquery`` / ``ts_rank``,
  GIN-indexed) that the Docs section uses. No embedding client exists in this
  image, so there is nothing else to reuse.
* **Access control.** ``KnowledgeDoc`` has NO per-user / per-doc ACL — its only
  visibility gates are ``organization_id`` and ``status`` (only ``'approved'``
  docs are live; ``pending``/``rejected`` are invisible). ``search_docs`` already
  enforces both (``WHERE d.organization_id = :org AND d.status = 'approved' AND
  d.deleted_at IS NULL``). So **org-scope + approved is the floor**, and we NEVER
  search an org other than the caller's ``organization_id``. The ``user`` is
  advisory here (accepted for signature stability + a future doc-ACL); we only
  use it to confirm the caller is org-consistent, never to widen scope.
* **Flag-gated, fail-soft.** ``flags.INSTITUTIONAL_KB`` OFF → ``[]`` with no DB
  hit (byte-identical to today). ANY error → ``[]``. NEVER raises.

Public surface:
    async retrieve_institutional(db, *, organization_id, user, question, limit=5) -> list[dict]
    institutional_block(items) -> str            (pure)
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

# Keep the injected block small so it grounds without bloating the planner
# prompt. Chunks can be ~1000 chars; a definition rarely needs more than this.
_MAX_ITEMS = 5
_SNIPPET_CHARS = 500


async def retrieve_institutional(
    db: Any,
    *,
    organization_id: str,
    user: Any = None,
    question: str,
    limit: int = 5,
) -> List[dict]:
    """Retrieve approved institutional docs relevant to ``question``. Fail-soft.

    Returns a ranked list of ``{"doc_id", "title", "text", "rank"}`` (≤ ``limit``)
    drawn from the org's ``status='approved'`` ``KnowledgeDoc`` chunks, most
    relevant first. Empty list when the flag is OFF, the question is blank, no org
    id, nothing matched, or on ANY error. NEVER raises.

    Access control: results are strictly org-scoped + approved-only (enforced by
    ``search_docs``). ``user`` is advisory — see the module docstring; passing a
    user from a different org does not widen scope (we always search
    ``organization_id``), it only lets us short-circuit an obvious mismatch.
    """
    # Flag gate FIRST — OFF is a true no-op, no DB hit.
    try:
        from app.settings.hybrid_flags import flags
        if not flags.INSTITUTIONAL_KB:
            return []
    except Exception:
        return []

    org_id = str(organization_id or "").strip()
    if not org_id:
        return []
    if not (question and question.strip()):
        return []

    # Access floor: never search an org the caller isn't in. `user` is advisory;
    # if it carries an organization_id and it disagrees with `organization_id`,
    # refuse rather than risk crossing a tenant boundary.
    try:
        user_org = getattr(user, "organization_id", None) if user is not None else None
        if user_org and str(user_org).strip() and str(user_org).strip() != org_id:
            logger.debug(
                "institutional: user org %s != requested org %s; refusing",
                user_org, org_id,
            )
            return []
    except Exception:
        # An unreadable user must not widen scope — org-scope still holds below.
        pass

    try:
        k = max(1, int(limit))
    except Exception:
        k = _MAX_ITEMS
    k = min(k, _MAX_ITEMS)

    try:
        from app.ai.knowledge.docs_index import search_docs

        # search_docs enforces org-scope + approved-only. data_source_id=None →
        # it omits the ds clause and searches ALL approved org docs (both
        # org-wide and per-source), which is the widest institutional net.
        rows = await search_docs(
            db,
            organization=SimpleNamespace(id=org_id),
            query=question,
            data_source_id=None,
            k=k,
        )
    except Exception as e:
        logger.debug("institutional: retrieve degraded to []: %s", e)
        return []

    out: List[dict] = []
    for r in (rows or []):
        if not isinstance(r, dict):
            continue
        text = str(r.get("text") or "").strip()
        if not text:
            continue
        out.append(
            {
                "doc_id": r.get("doc_id"),
                "title": str(r.get("title") or "").strip(),
                "text": text,
                "rank": float(r.get("rank") or 0.0),
            }
        )
    return out[:k]


def institutional_block(items: Optional[List[dict]]) -> str:
    """Compact planner-injection text for institutional docs. Pure, never raises.

    Returns ``""`` when there is nothing to inject, else a small markdown block
    the planner can read to resolve a business term to the approved definition::

        ### Institutional knowledge (definitions/context)
        Approved company definitions/notes — use them to resolve business terms to
        the right metric; do not invent a definition when one is listed here.
        - **Activation**: a user who completes onboarding within 7 days …
        - **March launch**: shipped 2026-03-02; excludes trial cohorts …
    """
    if not items:
        return ""

    lines: List[str] = []
    seen: set = set()
    for it in items:
        if not isinstance(it, dict):
            continue
        text = str(it.get("text") or "").strip()
        if not text:
            continue
        title = str(it.get("title") or "").strip()
        # Collapse whitespace + cap length so one long chunk can't dominate.
        snippet = " ".join(text.split())
        if len(snippet) > _SNIPPET_CHARS:
            snippet = snippet[:_SNIPPET_CHARS].rstrip() + "…"
        key = (title.lower(), snippet[:80].lower())
        if key in seen:
            continue
        seen.add(key)
        if title:
            lines.append(f"- **{title}**: {snippet}")
        else:
            lines.append(f"- {snippet}")
        if len(lines) >= _MAX_ITEMS:
            break

    if not lines:
        return ""

    header = (
        "### Institutional knowledge (definitions/context)\n"
        "Approved company definitions/notes — use them to resolve business terms "
        "to the right metric; do not invent a definition when one is listed here."
    )
    return header + "\n" + "\n".join(lines)
