"""Per-org staging tenant provisioning + engines.

Each org's autotrain uploads land in a DEDICATED schema `staging_<orgid>`,
readable only by that org's own restricted login role `at_ro_<orgid>`.

Three engines (the security split — see docs/AUTOTRAIN_FIX_PLAN.md):
  _admin_engine / loader_write_engine  RAW superuser, no write-guard. CREATE SCHEMA/ROLE/GRANT
                                       + the loader's table writes (server-derived schema only,
                                       never agent-reachable).
  org_read_engine(org_id)              connects AS the restricted role at_ro_<org>, search_path
                                       = staging_<org> ONLY (no public). codex/profiler/qa run
                                       their (LLM-generated) SELECTs here -> physically cannot
                                       read public.* (role lacks USAGE).

Pure helpers. Never raise into callers except an explicit RuntimeError when the
provisioning secret is unset.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
from functools import lru_cache

from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)


def _slug(org_id: str) -> str:
    return re.sub(r'[^a-z0-9]', '', (org_id or '').lower())[:16] or 'default'


def org_schema(org_id: str) -> str:
    return 'staging_' + _slug(org_id)


def org_role(org_id: str) -> str:
    return 'at_ro_' + _slug(org_id)


def _secret() -> str:
    # H4: dedicated, high-entropy secret REQUIRED. No fallback to the DB password
    # (which is reused + likely in .env/logs) — a single leak would otherwise forge
    # every org's deterministic role password.
    s = os.environ.get('AUTOTRAIN_STAGING_ROLE_SECRET')
    if not s or len(s) < 16:
        raise RuntimeError(
            'autotrain: AUTOTRAIN_STAGING_ROLE_SECRET (>=16 chars, dedicated random) '
            'must be set to provision per-org staging roles'
        )
    return s


def org_role_password(org_id: str) -> str:
    return 'at_' + hmac.new(_secret().encode(), (org_id or '').encode(), hashlib.sha256).hexdigest()[:28]


def _managed_parts() -> dict:
    from sqlalchemy.engine import make_url

    from app.settings.database import _get_database_url

    u = make_url(_get_database_url())
    return {
        "host": os.environ.get("AUTOTRAIN_STAGING_DB_HOST") or u.host or "localhost",
        "port": int(os.environ.get("AUTOTRAIN_STAGING_DB_PORT") or u.port or 5432),
        "database": os.environ.get("AUTOTRAIN_STAGING_DB_NAME") or u.database or "dash",
    }


@lru_cache(maxsize=1)
def _admin_engine():
    """RAW managed engine (no write-guard) — dash superuser — for CREATE SCHEMA/ROLE/GRANT."""
    from app.settings.database import _get_database_url

    return create_engine(_get_database_url(), pool_pre_ping=True)


def loader_write_engine():
    """Raw server engine for the loader's table writes. NOT the agent-guarded engine,
    so quoted/reserved identifiers work; only the loader calls it, with a
    server-derived schema (staging_<org>), so the agent can never reach it."""
    return _admin_engine()


@lru_cache(maxsize=128)
def org_read_engine(org_id: str):
    """Read-only engine that connects AS the org's restricted role with
    search_path = staging_<org> (no public). Used for codex/profiler/qa SELECTs so
    LLM-generated SQL cannot read public.* (role has no USAGE there)."""
    prov = ensure_org_staging(org_id)  # idempotent; guarantees role exists
    schema, role, pw = prov["schema"], prov["role"], prov["password"]
    p = _managed_parts()
    url = f"postgresql://{role}:{pw}@{p['host']}:{p['port']}/{p['database']}"
    return create_engine(
        url,
        connect_args={"options": f"-csearch_path={schema}"},
        pool_pre_ping=True,
    )


def ensure_org_staging(org_id: str) -> dict:
    """Idempotently provision schema + hardened restricted login role + grants.

    Returns {'schema','role','password'}. Raises RuntimeError only if the
    provisioning secret is unset (let that propagate so callers stay safe-off).
    """
    schema, role, pw = org_schema(org_id), org_role(org_id), org_role_password(org_id)
    eng = _admin_engine()
    with eng.begin() as c:
        c.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        # H4 hardening: explicit NO* attributes (no inherited/group privileges, no
        # role/db creation, not superuser, can't bypass RLS). format(%I,%L) keeps the
        # role+password injection-safe inside the DO block.
        c.execute(text(
            "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname=:r) THEN "
            "EXECUTE format('CREATE ROLE %I LOGIN NOINHERIT NOCREATEDB NOCREATEROLE "
            "NOSUPERUSER NOBYPASSRLS PASSWORD %L', :r, :p); "
            "ELSE EXECUTE format('ALTER ROLE %I LOGIN NOINHERIT NOCREATEDB NOCREATEROLE "
            "NOSUPERUSER NOBYPASSRLS PASSWORD %L', :r, :p); END IF; END $$;"
        ).bindparams(r=role, p=pw))
        c.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"'))
        c.execute(text(f'GRANT SELECT ON ALL TABLES IN SCHEMA "{schema}" TO "{role}"'))
        c.execute(text(f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" GRANT SELECT ON TABLES TO "{role}"'))
        # defense-in-depth: strip any public access (USAGE + table privileges)
        c.execute(text(f'REVOKE ALL ON SCHEMA public FROM "{role}"'))
        c.execute(text(f'REVOKE ALL ON ALL TABLES IN SCHEMA public FROM "{role}"'))
    logger.info("tenant_schema: ensured %s + hardened role %s", schema, role)
    return {'schema': schema, 'role': role, 'password': pw}
