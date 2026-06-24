"""Skill folder importer — load a Claude-style skill folder into the DB.

A skill folder looks like::

    my-skill/
      SKILL.md            # frontmatter (name, description, allowed-tools) + body
      scripts/*.py|*.sql  # bundled runnable scripts  -> SkillFile(kind='script')
      references/*        # reference docs            -> SkillFile(kind='reference')
      assets/*            # other resources           -> SkillFile(kind='asset')

This reuses the existing pure helpers (parse/extract frontmatter, add_skill_file)
so the imported rows match what the loader/tools already read. Idempotent on the
(organization, name) pair: re-importing replaces the skill's body + files.

NOT gated here beyond flags.SKILLS (enforced by add_skill_file). Caller decides
scope ('personal'|'org'|'global') and status ('draft'|'active').
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

_SCRIPT_EXTS = {".py", ".sql"}
_REFERENCE_DIRS = {"references", "reference", "docs"}
_SCRIPT_DIRS = {"scripts", "script"}


def _kind_for(rel_path: str) -> str:
    head = rel_path.split("/", 1)[0].lower()
    ext = os.path.splitext(rel_path)[1].lower()
    if head in _SCRIPT_DIRS or ext in _SCRIPT_EXTS:
        return "script"
    if head in _REFERENCE_DIRS:
        return "reference"
    return "asset"


async def import_skill_folder(
    db: Any,
    *,
    organization_id: str,
    owner_user_id: Optional[str],
    root_dir: str,
    scope: str = "org",
    status: str = "active",
    category: Optional[str] = None,
) -> Dict[str, Any]:
    """Import one skill folder. Returns {skill_id, name, files:[...], replaced:bool}.

    Raises FileNotFoundError if SKILL.md is missing. DB errors on the Skill row
    propagate; per-file errors are swallowed by add_skill_file.
    """
    from sqlalchemy import select
    from app.models.skill import Skill
    from app.ai.skills.frontmatter import extract_skill_fields
    from app.ai.skills.files import add_skill_file

    skill_md_path = os.path.join(root_dir, "SKILL.md")
    if not os.path.isfile(skill_md_path):
        raise FileNotFoundError(f"No SKILL.md in {root_dir}")

    with open(skill_md_path, "r", encoding="utf-8") as fh:
        skill_md = fh.read()

    fields = extract_skill_fields(skill_md)
    name = fields["name"] or os.path.basename(os.path.normpath(root_dir))
    allowed = fields.get("allowed_tools") or []
    disallowed = fields.get("disallowed_tools") or []

    # Upsert by (organization_id, name): replace body if it already exists.
    res = await db.execute(
        select(Skill).where(
            Skill.organization_id == str(organization_id),
            Skill.name == name,
            Skill.deleted_at.is_(None),
        )
    )
    skill = res.scalar_one_or_none()
    replaced = skill is not None

    if skill is None:
        skill = Skill(
            name=name,
            description=fields["description"] or name,
            scope=scope,
            owner_user_id=str(owner_user_id) if owner_user_id else None,
            organization_id=str(organization_id),
            skill_md=skill_md,
            status=status,
            category=category,
            allowed_tools=json.dumps(allowed) if allowed else None,
            disallowed_tools=json.dumps(disallowed) if disallowed else None,
            disable_model_invocation=bool(fields.get("disable_model_invocation")),
            user_invocable=bool(fields.get("user_invocable", True)),
        )
        db.add(skill)
        await db.flush()
    else:
        skill.description = fields["description"] or skill.description
        skill.skill_md = skill_md
        skill.scope = scope
        skill.status = status
        skill.category = category or skill.category
        skill.allowed_tools = json.dumps(allowed) if allowed else None
        skill.disallowed_tools = json.dumps(disallowed) if disallowed else None
        skill.disable_model_invocation = bool(fields.get("disable_model_invocation"))
        skill.user_invocable = bool(fields.get("user_invocable", True))
        await db.flush()

    skill_id = str(skill.id)
    await db.commit()

    # Walk bundled files (everything except the root SKILL.md).
    imported_files = []
    for dirpath, _dirs, filenames in os.walk(root_dir):
        for fn in filenames:
            abs_path = os.path.join(dirpath, fn)
            rel = os.path.relpath(abs_path, root_dir).replace(os.sep, "/")
            if rel == "SKILL.md":
                continue
            try:
                with open(abs_path, "r", encoding="utf-8") as fh:
                    content = fh.read()
            except Exception:
                continue  # skip binary/unreadable
            kind = _kind_for(rel)
            fid = await add_skill_file(
                db, skill_id=skill_id, path=rel, kind=kind, content=content
            )
            if fid:
                imported_files.append({"path": rel, "kind": kind, "id": fid})

    return {
        "skill_id": skill_id,
        "name": name,
        "files": imported_files,
        "replaced": replaced,
    }
