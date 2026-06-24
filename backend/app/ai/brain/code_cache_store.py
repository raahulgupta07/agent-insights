"""
Code-memory store (Kepler Phase 2)
==================================

The python analogue of ``query_cache_store``: captures the proven
``generate_df`` python the agent wrote for a successful answer and recalls the
closest snippet(s) for a similar question, surfaced to the Coder as PROVEN
APPROACHES context. "Code matters more than schemas" — for a python-pandas agent
the most valuable memory is its own working code, not SQL.

Design rules (mirror query_cache_store):
- Reuses the SAME normalization + token-Jaccard fuzzy match (imported, not
  duplicated) so behavior is identical to the SQL cache.
- Capture + injection both gated by flags.CODE_BANK; safe no-op when off / no db.
- The code is injected as REFERENCE TEXT and is never executed, so captured rows
  land status='active' immediately (already proven). A future review surface may
  archive rows. Every public coroutine swallows its own errors.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

# Reuse the canonical normalization + fuzzy match from the SQL reasoning-cache.
from app.ai.brain.query_cache_store import (
    normalize_question,
    question_hash,
    _tokens,
    _jaccard,
    _sources_fp,
    _scoped_qhash,
)

logger = logging.getLogger(__name__)

# Code blocks are large — keep the surfaced set small and bound each block.
MAX_PROVEN_CODE = 2
FUZZY_FLOOR = 0.5          # slightly looser than SQL: code reuse is more tolerant
CODE_MAX_CHARS = 1400      # per-snippet cap so context stays bounded


def _looks_like_generate_df(code: str) -> bool:
    """Only cache the agent's data-producing function contract."""
    if not code or not code.strip():
        return False
    return "def generate_df" in code


async def capture_code(
    db: Any,
    *,
    organization_id: str,
    data_source_id: Optional[str],
    question: str,
    code: str,
    source: str = "chat",
    data_source_ids: Optional[List[str]] = None,
) -> Optional[str]:
    """Capture proven generate_df python (no-op unless flags.CODE_BANK).

    Upserts on (org, data_source, hash): refreshes an existing row's code +
    bumps hit_count instead of duplicating. Returns the row id, else None.

    ``data_source_ids`` (multi-source set, optional): the FULL pinned source set,
    folded into the lookup hash only when >1 source (see ``_sources_fp``) so
    multi-source Studios don't share proven code across different pinned sets.
    Single-source / None -> hash unchanged.
    """
    from app.settings.hybrid_flags import flags

    if not flags.CODE_BANK:
        return None
    if db is None or not organization_id:
        return None
    if not _looks_like_generate_df(code):
        return None

    norm = normalize_question(question)
    if not norm:
        return None
    qhash = _scoped_qhash(norm, _sources_fp(data_source_ids))
    code_text = code.strip()

    try:
        from sqlalchemy import select
        from app.models.code_cache import CodeCache

        stmt = (
            select(CodeCache)
            .where(CodeCache.organization_id == organization_id)
            .where(CodeCache.question_hash == qhash)
            .where(CodeCache.deleted_at.is_(None))
        )
        if data_source_id is None:
            stmt = stmt.where(CodeCache.data_source_id.is_(None))
        else:
            stmt = stmt.where(CodeCache.data_source_id == data_source_id)

        existing = (await db.execute(stmt)).scalars().first()
        if existing is not None:
            existing.hit_count = (existing.hit_count or 0) + 1
            existing.last_used_at = datetime.utcnow()
            existing.code = code_text  # keep the latest proven code
            await db.commit()
            return str(existing.id)

        row = CodeCache(
            organization_id=organization_id,
            data_source_id=data_source_id,
            question_norm=norm,
            question_hash=qhash,
            code=code_text,
            status="active",
            source=source,
            hit_count=1,
            last_used_at=datetime.utcnow(),
        )
        db.add(row)
        await db.commit()
        return str(row.id)
    except Exception as e:
        logger.warning("code_cache capture failed: %s", e)
        try:
            await db.rollback()
        except Exception:
            pass
        return None


async def recall_proven_code(
    db: Any,
    *,
    organization_id: str,
    data_source_id: Optional[str],
    question: str,
    limit: int = MAX_PROVEN_CODE,
    data_source_ids: Optional[List[str]] = None,
) -> List[Dict[str, str]]:
    """Recall active proven code for a similar question (no-op unless CODE_BANK).

    Returns [{question, code}] best-first: exact-hash first, then token-Jaccard
    >= FUZZY_FLOOR. Scoped to this data source OR org-wide (NULL).

    ``data_source_ids`` (multi-source set, optional): the FULL pinned source set,
    folded into the EXACT-match hash only when >1 source (see ``_sources_fp``) so
    a multi-source Studio exact-matches only code proven for the SAME set.
    Single-source / None -> hash unchanged. (Fuzzy fallback is set-agnostic.)
    """
    from app.settings.hybrid_flags import flags

    if not flags.CODE_BANK:
        return []
    if db is None or not organization_id:
        return []

    norm = normalize_question(question)
    if not norm:
        return []
    qhash = _scoped_qhash(norm, _sources_fp(data_source_ids))
    qtokens = _tokens(norm)

    try:
        from sqlalchemy import select
        from app.models.code_cache import CodeCache

        stmt = (
            select(CodeCache)
            .where(CodeCache.organization_id == organization_id)
            .where(CodeCache.status == "active")
            .where(CodeCache.deleted_at.is_(None))
        )
        if data_source_id is not None:
            stmt = stmt.where(
                (CodeCache.data_source_id == data_source_id)
                | (CodeCache.data_source_id.is_(None))
            )
        rows = (await db.execute(stmt)).scalars().all()
    except Exception as e:
        logger.warning("code_cache recall failed: %s", e)
        return []

    scored: List[tuple[float, Any]] = []
    for r in rows:
        if r.question_hash == qhash:
            score = 1.0
        else:
            score = _jaccard(qtokens, _tokens(r.question_norm or ""))
            if score < FUZZY_FLOOR:
                continue
        scored.append((score, r))

    scored.sort(key=lambda t: (t[0], t[1].hit_count or 0), reverse=True)
    out: List[Dict[str, str]] = []
    for _, r in scored[:limit]:
        code = (r.code or "").strip()
        if len(code) > CODE_MAX_CHARS:
            code = code[:CODE_MAX_CHARS] + "\n# … (truncated)"
        out.append({"question": r.question_norm, "code": code})
    return out


def render_proven_code(items: List[Dict[str, str]]) -> str:
    """Render recalled code as a Coder context block. Empty -> ''."""
    if not items:
        return ""
    lines = [
        "## PROVEN APPROACHES (code-memory)",
        "Working generate_df() code from similar past answers. Reuse the join / "
        "filter / dedup logic; adapt to the current question — do not assume the "
        "data is current:",
    ]
    for i, it in enumerate(items, 1):
        code = (it.get("code") or "").strip()
        q = (it.get("question") or "").strip()
        lines.append(f"\n{i}. Q: {q}\n```python\n{code}\n```")
    return "\n".join(lines)
