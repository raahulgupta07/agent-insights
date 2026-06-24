"""
Skill files store (Phase S3.2 / S3.4)
======================================

Store + read for L3 skill resources — the bundled scripts, references and
assets that ship alongside a SKILL.md body. Mirrors `loader.py` exactly:

- Everything gated by flags.SKILLS — safe no-ops ([] / None) when off or no db.
- Lazy model import inside functions so this module imports without the full
  model registry and stays unit-testable.
- Every public coroutine swallows its own DB errors and degrades to a no-op so
  the agent loop never breaks on skill files.

`safe_rel_path` is pure (never raises, no DB) — the path guard for every L3
resource. Reject absolute paths, '..' traversal, > 2 segments deep, empty.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

KIND_SCRIPT = "script"
KIND_REFERENCE = "reference"
KIND_ASSET = "asset"
VALID_KINDS = {KIND_SCRIPT, KIND_REFERENCE, KIND_ASSET}


def safe_rel_path(path: str) -> Optional[str]:
    """Normalize + validate a relative skill-file path. Pure, never raises.

    Accepts a bare file ('file.md') or one-level-deep dir + file
    ('scripts/q.sql'). Backslashes are normalized to '/'. Returns the cleaned
    'dir/file' or bare 'file' string, or None if invalid.

    Rejected: None / empty, absolute paths, any '..' (parent) segment, '.'
    current-dir segments, > 2 path segments deep, empty segments.
    """
    try:
        if not path or not isinstance(path, str):
            return None

        # Normalize backslashes (Windows-style) to forward slashes.
        cleaned = path.replace("\\", "/").strip()
        if not cleaned:
            return None

        # Reject absolute paths (POSIX leading '/' or Windows drive like 'C:').
        if cleaned.startswith("/"):
            return None
        if len(cleaned) >= 2 and cleaned[1] == ":":
            return None

        segments = cleaned.split("/")

        # Drop nothing — every segment must be a real, simple name.
        for seg in segments:
            if seg == "" or seg == "." or seg == "..":
                return None

        # One-level-deep dir max: 'a/b' OK, 'a/b/c' rejected.
        if len(segments) > 2:
            return None

        return "/".join(segments)
    except Exception:
        return None


async def add_skill_file(
    db: Any,
    *,
    skill_id: Any,
    path: str,
    kind: str,
    content: Optional[str],
) -> Optional[str]:
    """Insert a skill-file row. Gated flags.SKILLS.

    Validates path via safe_rel_path (invalid path -> no-op None). kind must be
    in VALID_KINDS else defaults to 'reference'. Returns the new id (str) or
    None. Swallows DB errors -> None.
    """
    from app.settings.hybrid_flags import flags

    if not flags.SKILLS:
        return None
    if db is None:
        return None

    rel = safe_rel_path(path)
    if rel is None:
        return None

    safe_kind = kind if kind in VALID_KINDS else KIND_REFERENCE

    try:
        from app.models.skill_file import SkillFile

        row = SkillFile(
            skill_id=skill_id,
            path=rel,
            kind=safe_kind,
            content=content,
        )
        db.add(row)
        await db.flush()
        new_id = str(row.id)
        await db.commit()
        return new_id
    except Exception as e:  # never break the loop on skill-file writes
        logger.warning("add_skill_file failed: %s", e)
        try:
            await db.rollback()
        except Exception:
            pass
        return None


async def list_skill_files(db: Any, *, skill_id: Any) -> List[Dict[str, Any]]:
    """List a skill's non-deleted files (L3 catalog). Gated flags.SKILLS.

    Returns [{'path','kind'}] ordered by kind then path. [] when off / no db /
    no skill_id / on error.
    """
    from app.settings.hybrid_flags import flags

    if not flags.SKILLS:
        return []
    if db is None or skill_id is None:
        return []

    try:
        from sqlalchemy import select
        from app.models.skill_file import SkillFile

        stmt = (
            select(SkillFile)
            .where(
                SkillFile.skill_id == skill_id,
                SkillFile.deleted_at.is_(None),
            )
            .order_by(SkillFile.kind, SkillFile.path)
        )
        rows = (await db.execute(stmt)).scalars().all()
    except Exception as e:  # never break the loop on skill-file reads
        logger.warning("list_skill_files failed: %s", e)
        return []

    return [{"path": r.path, "kind": r.kind} for r in rows]


async def get_skill_file(
    db: Any, *, skill_id: Any, path: str
) -> Optional[Dict[str, Any]]:
    """Load one non-deleted skill file by path. Gated flags.SKILLS.

    path is validated via safe_rel_path (invalid -> None). Returns
    {'path','kind','content'} for the matching file, or None. Swallows errors.
    """
    from app.settings.hybrid_flags import flags

    if not flags.SKILLS:
        return None
    if db is None or skill_id is None:
        return None

    rel = safe_rel_path(path)
    if rel is None:
        return None

    try:
        from sqlalchemy import select
        from app.models.skill_file import SkillFile

        stmt = (
            select(SkillFile)
            .where(
                SkillFile.skill_id == skill_id,
                SkillFile.path == rel,
                SkillFile.deleted_at.is_(None),
            )
            .limit(1)
        )
        row = (await db.execute(stmt)).scalars().first()
    except Exception as e:  # never break the loop on skill-file reads
        logger.warning("get_skill_file failed: %s", e)
        return None

    if row is None:
        return None

    return {"path": row.path, "kind": row.kind, "content": row.content}
