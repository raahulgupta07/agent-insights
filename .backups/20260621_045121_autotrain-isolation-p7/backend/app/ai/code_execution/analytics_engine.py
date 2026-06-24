"""
Analytics engine — dual-schema, DB-level write guard (Phase 2)
==============================================================

Ports the dash dual-schema pattern into dash's model:

- Company data lives in EXTERNAL Connections (Snowflake/Postgres/...) and is
  read-only by virtue of dash's existing query path — nothing to enforce here.
- The agent-owned `analytics` schema (and `staging` for ingested snapshots)
  lives in dash's MANAGED Postgres. The Engineer agent builds reusable views
  and summary tables there via build_data_asset.

This module provides:
  * get_analytics_write_engine() — write engine with search_path=analytics,public.
    A DDL/DML guard (SQLAlchemy event listener) rejects any write whose target is
    NOT analytics.* / staging.*, so the Engineer can never touch dash's app tables
    or company data. Infrastructure guardrail, not a prompt instruction.
  * get_analytics_readonly_engine() — read-only engine (default_transaction_read_only)
    for safe reads of the managed analytics/staging schemas.

NOTE: this is defense-in-depth at the application layer. The strongest guarantee
is a dedicated Postgres role GRANTed only on analytics/staging — added in Phase 9.

Gated by flags.DUAL_SCHEMA. Engines are built lazily (never at import) so config
is loaded and the managed DB URL is resolvable first.
"""

from __future__ import annotations

import re
import threading
from typing import Optional, Tuple

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

from app.errors.app_error import AppError  # dash's typed app error

ANALYTICS_SCHEMA = "analytics"
STAGING_SCHEMA = "staging"
_WRITABLE_SCHEMAS = {ANALYTICS_SCHEMA, STAGING_SCHEMA}


def _is_writable_schema(schema: str) -> bool:
    """Writable targets: analytics, the shared staging, and per-org autotrain
    schemas `staging_<orgid>` (tenant-isolated ingest). CREATE/DROP SCHEMA + GRANT
    stay always-blocked by _ALWAYS_BLOCK_RE, so this only widens which schemas the
    Engineer/loader may write TABLES/rows into."""
    return (
        schema == ANALYTICS_SCHEMA
        or schema == STAGING_SCHEMA
        or schema.startswith("staging_")
    )

# Statements that mutate data or schema.
_WRITE_RE = re.compile(
    r"^\s*(INSERT\s+INTO|UPDATE|DELETE\s+FROM|TRUNCATE(?:\s+TABLE)?|"
    r"CREATE(?:\s+OR\s+REPLACE)?(?:\s+MATERIALIZED)?\s+(?:VIEW|TABLE)|"
    r"DROP\s+(?:MATERIALIZED\s+)?(?:VIEW|TABLE)|ALTER\s+(?:VIEW|TABLE)|"
    r"GRANT|REVOKE|CREATE\s+SCHEMA|DROP\s+SCHEMA)\b",
    re.IGNORECASE,
)

# Privilege/schema ops are never legitimate Engineer writes — always block.
_ALWAYS_BLOCK_RE = re.compile(r"^\s*(GRANT|REVOKE|CREATE\s+SCHEMA|DROP\s+SCHEMA)\b", re.IGNORECASE)

# Capture the WRITE TARGET only (the object being created/altered/dropped/written),
# NOT read sources in the body — an analytics view may freely SELECT from public.
_OBJ = r"(?:IF\s+(?:NOT\s+)?EXISTS\s+)?([a-zA-Z_][\w]*(?:\.[a-zA-Z_][\w]*)?)"
_TARGET_RES = [
    re.compile(
        r"^\s*(?:CREATE(?:\s+OR\s+REPLACE)?(?:\s+MATERIALIZED)?\s+(?:VIEW|TABLE)|"
        r"DROP\s+(?:MATERIALIZED\s+)?(?:VIEW|TABLE)|ALTER\s+(?:VIEW|TABLE))\s+" + _OBJ,
        re.IGNORECASE,
    ),
    re.compile(r"^\s*INSERT\s+INTO\s+" + _OBJ, re.IGNORECASE),
    re.compile(r"^\s*UPDATE\s+" + _OBJ, re.IGNORECASE),
    re.compile(r"^\s*DELETE\s+FROM\s+" + _OBJ, re.IGNORECASE),
    re.compile(r"^\s*TRUNCATE(?:\s+TABLE)?\s+" + _OBJ, re.IGNORECASE),
]


class AnalyticsWriteViolation(AppError):
    """Raised when a write targets a schema outside analytics/staging."""

    def __init__(self, message: str) -> None:
        super().__init__("analytics_write_violation", message, status_code=403)


def _is_write(sql: str) -> bool:
    return bool(_WRITE_RE.match(sql or ""))


def _violates_schema_boundary(sql: str) -> bool:
    """True if a write statement's TARGET is outside analytics/staging.

    Only the write target's schema is checked — reading from public/company data
    in the statement body is allowed (that is the core Engineer pattern:
    CREATE VIEW analytics.x AS SELECT ... FROM public.customers).

    Privilege/schema ops are always blocked. Unqualified write targets are
    rejected (the Engineer must always prefix analytics./staging.).
    """
    if not _is_write(sql):
        return False
    if _ALWAYS_BLOCK_RE.match(sql):
        return True
    for rx in _TARGET_RES:
        m = rx.match(sql)
        if m:
            target = m.group(1)
            if "." not in target:
                return True  # unqualified write target — reject
            schema = target.split(".", 1)[0].lower()
            return not _is_writable_schema(schema)
    # Write verb matched but no target parsed → reject conservatively.
    return True


def _install_write_guard(engine: Engine) -> None:
    @event.listens_for(engine, "before_cursor_execute")
    def _guard(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        if _violates_schema_boundary(statement):
            raise AnalyticsWriteViolation(
                "Write blocked: the analytics engine may only modify "
                f"{sorted(_WRITABLE_SCHEMAS)} schemas. Offending statement: "
                f"{(statement or '')[:200]}"
            )


_write_engine: Engine | None = None
_ro_engine: Engine | None = None
_lock = threading.Lock()


def _managed_db_url() -> str:
    """Resolve dash's managed (app) database URL, sync driver."""
    from app.settings.database import _get_database_url  # lazy: config must be loaded

    return _get_database_url()


def get_analytics_write_engine() -> Engine:
    """Lazily build the guarded write engine (search_path=analytics,public)."""
    global _write_engine
    if _write_engine is None:
        with _lock:
            if _write_engine is None:
                url = _managed_db_url()
                connect_args = {}
                if url.startswith("postgresql"):
                    connect_args = {"options": f"-csearch_path={ANALYTICS_SCHEMA},public"}
                eng = create_engine(url, connect_args=connect_args, pool_pre_ping=True)
                _install_write_guard(eng)
                _write_engine = eng
    return _write_engine


def get_analytics_readonly_engine() -> Engine:
    """Lazily build a read-only engine for the managed analytics/staging schemas."""
    global _ro_engine
    if _ro_engine is None:
        with _lock:
            if _ro_engine is None:
                url = _managed_db_url()
                connect_args = {}
                if url.startswith("postgresql"):
                    connect_args = {
                        "options": (
                            f"-csearch_path={ANALYTICS_SCHEMA},public "
                            "-cdefault_transaction_read_only=on"
                        )
                    }
                _ro_engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True)
    return _ro_engine


# --------------------------------------------------------------------------- #
# Materialized-view serve (Tier ③ of the serving funnel)
# --------------------------------------------------------------------------- #
# A precomputed analytics.* matview can answer a question directly with a cheap
# read (zero-LLM). We serve CONSERVATIVELY: only when an existing matview's name
# unambiguously appears as whole token(s) in the question. Anything fuzzy or
# ambiguous returns None so the funnel falls through to the agent loop.

# matview/asset identifiers are lowercase a-z0-9_ (see build_data_asset._NAME_RE),
# so a question token only matches a matview name when it carries >1 char of
# signal — single-char names are ignored to avoid accidental matches.
_TOKEN_RE = re.compile(r"[a-z0-9_]+")

# Hard cap on rows read out of a served matview, mirroring the reasoning-cache's
# MAX_SERVE_ROWS so a huge matview can't blow up the chat payload.
MATVIEW_MAX_ROWS = 100


def list_analytics_matviews() -> list[str]:
    """Return the names of materialized views in the ``analytics`` schema.

    Read-only, best-effort: any error (engine unbuildable, schema absent,
    non-Postgres) degrades to an empty list so callers can treat it as a MISS.
    Names are the bare matview name (no schema prefix), lowercased.
    """
    try:
        from sqlalchemy import text as _sql_text

        engine = get_analytics_readonly_engine()
        if not str(engine.url).startswith("postgresql"):
            return []  # pg_matviews is Postgres-only
        with engine.connect() as conn:
            rows = conn.execute(
                _sql_text(
                    "SELECT matviewname FROM pg_matviews WHERE schemaname = :s"
                ),
                {"s": ANALYTICS_SCHEMA},
            ).fetchall()
        return [str(r[0]).lower() for r in rows if r and r[0]]
    except Exception:
        return []


def _match_matview(question: str, matviews: list[str]) -> Optional[str]:
    """Pick the single matview whose name is referenced by the question.

    Conservative match: the matview's name must appear in the question as a
    contiguous run of whole word-tokens (e.g. a matview ``monthly_mrr`` matches
    a question containing the tokens "monthly" then "mrr", or the literal token
    "monthly_mrr"). Returns the matched name only when EXACTLY ONE matview
    matches — zero or multiple candidates is ambiguous and returns None.
    """
    if not question or not matviews:
        return None
    q_tokens = _TOKEN_RE.findall(question.lower())
    if not q_tokens:
        return None
    q_joined = " ".join(q_tokens)

    hits: list[str] = []
    for mv in matviews:
        name_tokens = mv.split("_")
        # Build a whitespace-joined token phrase for the matview name and test
        # it against the whitespace-joined question tokens with word edges.
        phrase = " ".join(t for t in name_tokens if t)
        if not phrase:
            continue
        # Match the underscore-name as a single token OR its parts as adjacent
        # words. Word boundaries prevent "mrr" matching inside "mrromance".
        pat = re.compile(r"(?<![a-z0-9_])" + re.escape(phrase) + r"(?![a-z0-9_])")
        pat_underscore = re.compile(r"(?<![a-z0-9_])" + re.escape(mv) + r"(?![a-z0-9_])")
        if pat.search(q_joined) or pat_underscore.search(q_joined):
            hits.append(mv)

    if len(hits) == 1:
        return hits[0]
    return None  # 0 -> miss, >1 -> ambiguous


def serve_matview(question: str) -> Optional[Tuple[str, list, list, int]]:
    """Serve a precomputed analytics.* matview that answers ``question``.

    Tier-③ serve (zero-LLM, conservative). Detects whether exactly one existing
    ``analytics.*`` materialized view is named by the question; if so, reads it
    (capped at ``MATVIEW_MAX_ROWS``) via the read-only analytics engine and
    returns ``(matview_name, columns, rows, total_row_count)``. Returns None on
    no/ambiguous match, when flags.DUAL_SCHEMA is off, or on any error (never
    raises).
    """
    from app.settings.hybrid_flags import flags

    if not flags.DUAL_SCHEMA:
        return None
    if not question or not question.strip():
        return None
    try:
        matviews = list_analytics_matviews()
        name = _match_matview(question, matviews)
        if name is None:
            return None

        from sqlalchemy import text as _sql_text

        engine = get_analytics_readonly_engine()
        # name comes from pg_matviews (DB metadata), not user input, and was
        # validated lowercase a-z0-9_ at creation — safe to interpolate. Cap +1
        # so we can detect (and report) truncation past MATVIEW_MAX_ROWS.
        sql = f'SELECT * FROM {ANALYTICS_SCHEMA}."{name}" LIMIT {MATVIEW_MAX_ROWS + 1}'
        with engine.connect() as conn:
            cur = conn.execute(_sql_text(sql))
            columns = [str(c) for c in cur.keys()]
            fetched = cur.fetchall()
        all_rows = [list(r) for r in fetched]
        total = len(all_rows)
        rows = all_rows[:MATVIEW_MAX_ROWS]
        return (name, columns, rows, total)
    except Exception:
        return None
