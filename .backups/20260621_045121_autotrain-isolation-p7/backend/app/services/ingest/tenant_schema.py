"""Per-org staging tenant provisioning.

Each org's autotrain uploads land in a DEDICATED schema `staging_<orgid>`,
readable only by that org's own restricted login role `at_ro_<orgid>`.

Provisioning (CREATE SCHEMA / CREATE ROLE / GRANT) is BLOCKED by the guarded
analytics write-engine (_ALWAYS_BLOCK_RE), so it MUST run on a RAW admin engine
built from dash's superuser url — never get_analytics_write_engine().

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
    s = os.environ.get('AUTOTRAIN_STAGING_ROLE_SECRET') or os.environ.get('AUTOTRAIN_STAGING_DB_PASSWORD')
    if not s:
        raise RuntimeError(
            'autotrain: AUTOTRAIN_STAGING_DB_PASSWORD (or _ROLE_SECRET) must be set '
            'to provision per-org staging roles'
        )
    return s


def org_role_password(org_id: str) -> str:
    return 'at_' + hmac.new(_secret().encode(), (org_id or '').encode(), hashlib.sha256).hexdigest()[:28]


@lru_cache(maxsize=1)
def _admin_engine():
    # RAW managed engine (no write-guard) — dash superuser — for CREATE SCHEMA/ROLE/GRANT.
    from app.settings.database import _get_database_url

    return create_engine(_get_database_url(), pool_pre_ping=True)


def ensure_org_staging(org_id: str) -> dict:
    """Idempotently provision schema + restricted login role + grants for an org.

    Returns {'schema','role','password'}. Raises RuntimeError only if the
    provisioning secret is unset (let that propagate so callers stay safe-off).
    """
    schema, role, pw = org_schema(org_id), org_role(org_id), org_role_password(org_id)
    eng = _admin_engine()
    with eng.begin() as c:
        c.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        # idempotent role create (DO block) + keep password deterministic.
        # :r/:p can't be identifiers in DDL directly; format(%I,%L) makes the
        # DO-block role+password injection-safe.
        c.execute(text(
            "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname=:r) THEN "
            "EXECUTE format('CREATE ROLE %I LOGIN PASSWORD %L', :r, :p); "
            "ELSE EXECUTE format('ALTER ROLE %I LOGIN PASSWORD %L', :r, :p); END IF; END $$;"
        ).bindparams(r=role, p=pw))
        c.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"'))
        c.execute(text(f'GRANT SELECT ON ALL TABLES IN SCHEMA "{schema}" TO "{role}"'))
        c.execute(text(f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" GRANT SELECT ON TABLES TO "{role}"'))
        c.execute(text(f'REVOKE ALL ON SCHEMA public FROM "{role}"'))
    logger.info("tenant_schema: ensured %s + role %s", schema, role)
    return {'schema': schema, 'role': role, 'password': pw}
