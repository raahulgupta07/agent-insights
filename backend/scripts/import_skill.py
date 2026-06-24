#!/usr/bin/env python
"""CLI: import a skill folder (or a directory of skill folders) into the DB.

Usage:
    python scripts/import_skill.py <path> [--scope org|personal|global]
                                          [--status active|draft]
                                          [--org <org_id>] [--user <user_id>]

If <path> contains a SKILL.md it's imported as one skill. Otherwise every
immediate subdirectory that has a SKILL.md is imported. Org/user default to the
first organization and its first admin user.
"""

import argparse
import asyncio
import os
import sys


async def _resolve_defaults(db, org_id, user_id):
    from sqlalchemy import select
    from app.models.organization import Organization
    from app.models.user import User

    if not org_id:
        res = await db.execute(select(Organization).limit(1))
        org = res.scalar_one_or_none()
        org_id = str(org.id) if org else None
    if not user_id:
        res = await db.execute(select(User).limit(1))
        u = res.scalar_one_or_none()
        user_id = str(u.id) if u else None
    return org_id, user_id


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--scope", default="org")
    ap.add_argument("--status", default="active")
    ap.add_argument("--org", default=None)
    ap.add_argument("--user", default=None)
    args = ap.parse_args()

    # Load the full ORM graph so all mappers configure (CLI runs outside the
    # app boot path). main = /app/backend/main.py, the uvicorn target; importing
    # it registers every model without starting the server.
    try:
        import main  # noqa: F401
        from sqlalchemy.orm import configure_mappers
        configure_mappers()
    except Exception:
        pass

    from app.settings.database import create_async_session_factory
    from app.ai.skills.importer import import_skill_folder

    maker = create_async_session_factory()

    folders = []
    if os.path.isfile(os.path.join(args.path, "SKILL.md")):
        folders = [args.path]
    else:
        for entry in sorted(os.listdir(args.path)):
            sub = os.path.join(args.path, entry)
            if os.path.isdir(sub) and os.path.isfile(os.path.join(sub, "SKILL.md")):
                folders.append(sub)

    if not folders:
        print(f"No skill folders (with SKILL.md) found under {args.path}")
        sys.exit(1)

    async with maker() as db:
        org_id, user_id = await _resolve_defaults(db, args.org, args.user)
        if not org_id:
            print("No organization found; cannot import.")
            sys.exit(1)
        for folder in folders:
            res = await import_skill_folder(
                db,
                organization_id=org_id,
                owner_user_id=user_id,
                root_dir=folder,
                scope=args.scope,
                status=args.status,
            )
            verb = "replaced" if res["replaced"] else "created"
            print(f"{verb}: {res['name']}  ({len(res['files'])} files)  id={res['skill_id']}")


if __name__ == "__main__":
    asyncio.run(main())
