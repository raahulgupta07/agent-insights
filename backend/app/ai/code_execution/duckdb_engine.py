"""
DuckDB federation engine — cross-source query (Phase 7)
=======================================================

A bounded, read-mostly DuckDB connection that can federate a single SQL query
across heterogeneous sources in one shot:

  * an ATTACHed read-only Postgres database (the `postgres` extension),
  * in-memory pandas DataFrames registered as scannable views,
  * parquet files / object-store snapshots scanned via ``read_parquet(...)``.

The intended future hook is the agent code-exec path
(``app/ai/code_execution/code_execution.py``): a tool can hand a federated SQL
string + the assets it references to ``run_federated_sql`` and get back a
pandas DataFrame — fitting naturally beside the existing DataFrame-returning
query helpers. The wiring is done by the parent agent; this module only
provides the engine.

Design rules (mirroring ``analytics_engine.py``):
  * Gated by ``flags.FEDERATION`` (env ``HYBRID_FEDERATION``, default OFF). When
    off, the public entry point no-ops (returns None) so the default deploy is
    byte-identical.
  * Bounded by construction: every connection sets a ``memory_limit`` and a
    spill ``temp_directory`` so a heavy join cannot OOM the box; ``threads`` is
    capped when configured.
  * Lazy ``import duckdb`` INSIDE functions — the module imports fine without
    the dependency installed (tests can run/skip cleanly), and a missing dep
    degrades to None rather than crashing the agent loop.
  * Side-effect-light: the public helper swallows operational errors and
    returns None instead of raising into the agent loop. Connections are always
    closed in ``finally``.

Knobs (env):
  * ``DUCKDB_MEMORY_LIMIT``  default '512MB'  — hard cap on DuckDB memory.
  * ``DUCKDB_TEMP_DIR``      optional         — spill/temp directory for joins.
  * ``DUCKDB_THREADS``       optional int     — worker-thread cap.

Snapshot (MinIO/S3) knobs (env, all optional — absent => local fallback):
  * ``FEDERATION_S3_ENDPOINT``    MinIO/S3 endpoint host[:port] (no scheme).
  * ``FEDERATION_S3_BUCKET``      bucket name snapshots are written under.
  * ``FEDERATION_S3_ACCESS_KEY``  / ``FEDERATION_S3_SECRET_KEY`` credentials.
  * ``FEDERATION_S3_REGION``      default 'us-east-1'.
  * ``FEDERATION_S3_USE_SSL``     '1'/'0' (default '1' = https).
  * ``FEDERATION_S3_PREFIX``      key prefix under the bucket (default 'snapshots').
  * ``FEDERATION_SNAPSHOT_DIR``   local fallback dir (default '<temp>/federation_snapshots').
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

from app.settings.hybrid_flags import flags
from app.ai.code_execution import freshness

logger = logging.getLogger(__name__)

# Default memory ceiling. Deliberately conservative — federation is read-mostly
# and a single bounded query should never be allowed to exhaust the host.
_DEFAULT_MEMORY_LIMIT = "512MB"


# --- config helpers (env-driven, mirror analytics_engine style) ------------


def _memory_limit() -> str:
    """DuckDB ``memory_limit`` (env ``DUCKDB_MEMORY_LIMIT``, default 512MB)."""
    raw = os.environ.get("DUCKDB_MEMORY_LIMIT")
    if raw and raw.strip():
        return raw.strip()
    return _DEFAULT_MEMORY_LIMIT


def _temp_dir() -> Optional[str]:
    """DuckDB spill ``temp_directory`` (env ``DUCKDB_TEMP_DIR``, optional)."""
    raw = os.environ.get("DUCKDB_TEMP_DIR")
    if raw and raw.strip():
        return raw.strip()
    return None


def _threads() -> Optional[int]:
    """DuckDB worker-thread cap (env ``DUCKDB_THREADS``, optional positive int)."""
    raw = os.environ.get("DUCKDB_THREADS")
    if raw is None or not raw.strip():
        return None
    try:
        n = int(raw.strip())
    except ValueError:
        return None
    return n if n > 0 else None


def _duckdb_available() -> bool:
    """True if the duckdb module can be imported (dep installed)."""
    import importlib.util

    return importlib.util.find_spec("duckdb") is not None


# --- bounded connection ----------------------------------------------------


@contextmanager
def duckdb_connection() -> Iterator[Any]:
    """Yield a bounded, in-memory DuckDB connection; always closed in finally.

    Applies ``memory_limit`` (always), ``temp_directory`` (when configured), and
    ``threads`` (when configured) so a heavy federated join cannot OOM the box.

    Lazy-imports duckdb. Raises a controlled RuntimeError if duckdb is missing —
    callers that must degrade silently should use the public ``run_federated_sql``
    helper (which pre-checks and returns None) instead of opening a connection
    directly.
    """
    try:
        import duckdb  # lazy: keeps the module importable without the dep
    except ImportError as exc:  # pragma: no cover - exercised only when dep absent
        raise RuntimeError("duckdb is not installed; federation unavailable") from exc

    con = duckdb.connect(database=":memory:")
    try:
        # Hard memory ceiling first — applied before any heavy statement runs.
        con.execute("SET memory_limit = ?", [_memory_limit()])
        tmp = _temp_dir()
        if tmp:
            con.execute("SET temp_directory = ?", [tmp])
        threads = _threads()
        if threads is not None:
            con.execute("SET threads = ?", [threads])
        yield con
    finally:
        try:
            con.close()
        except Exception:  # pragma: no cover - close should not raise
            logger.debug("duckdb connection close failed", exc_info=True)


# --- attachment / registration helpers -------------------------------------


def attach_postgres(con: Any, alias: str, dsn: str) -> bool:
    """ATTACH a Postgres database READ-ONLY under ``alias``. Returns success.

    Installs + loads the ``postgres`` extension and attaches the DSN. Defensive:
    any failure (extension unavailable, bad DSN, network) is swallowed and
    reported via the bool so the caller can degrade.
    """
    if not alias or not dsn:
        return False
    try:
        con.execute("INSTALL postgres")
        con.execute("LOAD postgres")
        # DSN/alias are interpolated (DuckDB ATTACH does not accept bind params
        # for the path/alias); alias is identifier-validated to limit injection.
        safe_alias = _safe_identifier(alias)
        safe_dsn = str(dsn).replace("'", "''")
        con.execute(
            "ATTACH '{dsn}' AS {alias} (TYPE postgres, READ_ONLY)".format(
                dsn=safe_dsn, alias=safe_alias
            )
        )
        return True
    except Exception:
        logger.warning("attach_postgres failed for alias=%s", alias, exc_info=True)
        return False


def register_dataframe(con: Any, name: str, df: Any) -> None:
    """Register a pandas DataFrame as a scannable DuckDB view named ``name``."""
    con.register(_safe_identifier(name), df)


def read_parquet(con: Any, name: str, path: str) -> None:
    """Create a view ``name`` over ``read_parquet('<path>')``.

    Supports local paths and (when the duckdb httpfs/s3 extension is configured
    by the caller) ``s3://`` / object-store paths. Kept intentionally simple —
    just the view-creating SQL; extension setup is the caller's concern.
    """
    safe_name = _safe_identifier(name)
    safe_path = str(path).replace("'", "''")
    con.execute(
        "CREATE OR REPLACE VIEW {name} AS SELECT * FROM read_parquet('{path}')".format(
            name=safe_name, path=safe_path
        )
    )


def _safe_identifier(name: str) -> str:
    """Validate a SQL identifier (view alias / attach alias).

    DuckDB view/attach aliases cannot be bound as parameters, so we restrict to
    a conservative ``[A-Za-z_][A-Za-z0-9_]*`` charset to prevent injection.
    """
    import re

    if not isinstance(name, str) or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
        raise ValueError("unsafe identifier: %r" % (name,))
    return name


# --- public entry point -----------------------------------------------------


def run_federated_sql(
    sql: str,
    *,
    attachments: Optional[Dict[str, str]] = None,
    dataframes: Optional[Dict[str, Any]] = None,
    parquet: Optional[Dict[str, str]] = None,
) -> Optional[Any]:
    """Execute ONE federated SQL query and return a pandas DataFrame, or None.

    Args:
        sql: the single federated SQL statement to run.
        attachments: ``{alias: postgres_dsn}`` — each ATTACHed READ-ONLY.
        dataframes: ``{view_name: pandas.DataFrame}`` — registered as views.
        parquet: ``{view_name: path}`` — each wrapped in a ``read_parquet`` view.

    Returns:
        A pandas DataFrame on success; ``None`` if the FEDERATION flag is off,
        duckdb is not installed, or any operational error occurs. Never raises
        into the agent loop. The bounded connection is always closed.
    """
    # Flag gate — off => byte-identical no-op.
    if not flags.FEDERATION:
        return None
    # Missing dependency => degrade silently.
    if not _duckdb_available():
        logger.debug("run_federated_sql: duckdb not installed; returning None")
        return None
    if not sql or not str(sql).strip():
        return None

    try:
        with duckdb_connection() as con:
            # If any parquet source is an object-store URI, wire httpfs/S3 first
            # using the configured credentials so read_parquet('s3://...') works.
            if any(
                str(p).lower().startswith(("s3://", "gcs://", "r2://"))
                for p in (parquet or {}).values()
            ):
                cfg = _s3_config()
                if cfg is not None:
                    _configure_s3(con, cfg)
            for alias, dsn in (attachments or {}).items():
                if not attach_postgres(con, alias, dsn):
                    # An attachment the query depends on failed — degrade.
                    logger.warning(
                        "run_federated_sql: attach failed for %s; aborting", alias
                    )
                    return None
            for name, df in (dataframes or {}).items():
                register_dataframe(con, name, df)
            for name, path in (parquet or {}).items():
                read_parquet(con, name, path)

            return con.execute(sql).df()
    except Exception:
        logger.warning("run_federated_sql failed", exc_info=True)
        return None


# --- MinIO / S3 snapshot helper --------------------------------------------


def _s3_config() -> Optional[Dict[str, str]]:
    """Return MinIO/S3 config from env, or None if not configured.

    A snapshot target is "configured" only when both an endpoint and a bucket
    are present. Missing => callers fall back to a local snapshot dir.
    """
    endpoint = (os.environ.get("FEDERATION_S3_ENDPOINT") or "").strip()
    bucket = (os.environ.get("FEDERATION_S3_BUCKET") or "").strip()
    if not endpoint or not bucket:
        return None
    return {
        "endpoint": endpoint,
        "bucket": bucket,
        "access_key": (os.environ.get("FEDERATION_S3_ACCESS_KEY") or "").strip(),
        "secret_key": (os.environ.get("FEDERATION_S3_SECRET_KEY") or "").strip(),
        "region": (os.environ.get("FEDERATION_S3_REGION") or "us-east-1").strip(),
        "use_ssl": (os.environ.get("FEDERATION_S3_USE_SSL", "1").strip().lower()
                    not in {"0", "false", "no", "off"}),
        "prefix": (os.environ.get("FEDERATION_S3_PREFIX") or "snapshots").strip().strip("/"),
    }


def _local_snapshot_dir() -> str:
    """Local fallback snapshot directory (created on demand)."""
    raw = (os.environ.get("FEDERATION_SNAPSHOT_DIR") or "").strip()
    if not raw:
        base = _temp_dir() or os.path.join(os.path.sep, "tmp")
        raw = os.path.join(base, "federation_snapshots")
    os.makedirs(raw, exist_ok=True)
    return raw


def _configure_s3(con: Any, cfg: Dict[str, Any]) -> None:
    """Install/load httpfs and set DuckDB S3 settings for ``cfg``.

    Endpoint is given without scheme (DuckDB wants ``host[:port]``); SSL is a
    separate flag. Path-style addressing (``url_style=path``) is required for
    MinIO. Credentials are SET via bind params where DuckDB allows it.
    """
    con.execute("INSTALL httpfs")
    con.execute("LOAD httpfs")
    con.execute("SET s3_endpoint = ?", [cfg["endpoint"]])
    con.execute("SET s3_region = ?", [cfg["region"]])
    con.execute("SET s3_use_ssl = ?", [bool(cfg["use_ssl"])])
    con.execute("SET s3_url_style = 'path'")
    if cfg.get("access_key"):
        con.execute("SET s3_access_key_id = ?", [cfg["access_key"]])
    if cfg.get("secret_key"):
        con.execute("SET s3_secret_access_key = ?", [cfg["secret_key"]])


def _is_fresh(path: str, ttl_seconds: Optional[int]) -> bool:
    """True if a LOCAL snapshot at ``path`` is younger than ``ttl_seconds``.

    Only local-FS freshness is checked (object-store stat is intentionally not
    performed here — see snapshot_to_parquet docstring). Returns False on any
    error so a stale-or-unknown snapshot is simply rewritten.
    """
    if not ttl_seconds or ttl_seconds <= 0:
        return False
    try:
        if not os.path.isfile(path):
            return False
        age = time.time() - os.path.getmtime(path)
        return age < float(ttl_seconds)
    except Exception:
        return False


def snapshot_to_parquet(
    sql: str,
    object_key: str,
    *,
    attachments: Optional[Dict[str, str]] = None,
    dataframes: Optional[Dict[str, Any]] = None,
    parquet: Optional[Dict[str, str]] = None,
    asset_meta: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Snapshot a (bounded, read-only) federated query result to Parquet.

    Runs ``sql`` against the given sources on a bounded DuckDB connection and
    writes the result to a Parquet object. Target selection:

      * if ``FEDERATION_S3_ENDPOINT`` + ``FEDERATION_S3_BUCKET`` are configured,
        writes to ``s3://<bucket>/<prefix>/<object_key>`` via the duckdb httpfs
        extension (works with MinIO and S3);
      * otherwise falls back to a LOCAL file under ``FEDERATION_SNAPSHOT_DIR``
        (or ``<temp>/federation_snapshots``) — never hard-fails when no
        object store is configured.

    Freshness: honors a CACHED policy derived from ``asset_meta`` via
    :func:`freshness.resolve_policy`. When the policy is CACHED with a TTL and a
    LOCAL snapshot already exists and is younger than the TTL, the existing path
    is returned without re-running the query. (Object-store TTL reuse is not
    asserted here — the caller owns object lifecycle/retention.)

    Args:
        sql: the single read-only SQL to materialize.
        object_key: relative key/filename for the snapshot (``.parquet``
            appended if absent). Identifier/path is sanitized.
        attachments / dataframes / parquet: same as :func:`run_federated_sql`.
        asset_meta: freshness hints (see :func:`freshness.resolve_policy`).

    Returns:
        The written location (``s3://...`` URI or local path) on success;
        ``None`` if the FEDERATION flag is off, duckdb is unavailable, the SQL
        is empty, or a write error occurs. Never raises into the agent loop.
    """
    # Flag gate — off => byte-identical no-op (no snapshot written).
    if not flags.FEDERATION:
        return None
    if not _duckdb_available():
        logger.debug("snapshot_to_parquet: duckdb not installed; returning None")
        return None
    if not sql or not str(sql).strip():
        return None
    if not object_key or not str(object_key).strip():
        return None

    key = str(object_key).strip().lstrip("/")
    if not key.lower().endswith(".parquet"):
        key = key + ".parquet"
    # Conservative path sanitation — no traversal, no absolute escape.
    if ".." in key or key.startswith(("/", "\\")):
        logger.warning("snapshot_to_parquet: unsafe object_key=%r", object_key)
        return None

    policy = freshness.resolve_policy(asset_meta)
    cfg = _s3_config()

    # CACHED reuse only meaningful for the local target (we can stat the file).
    if cfg is None and policy.is_cached:
        local_path = os.path.join(_local_snapshot_dir(), key)
        if _is_fresh(local_path, policy.ttl_seconds):
            logger.debug("snapshot_to_parquet: reusing fresh local snapshot %s", local_path)
            return local_path

    try:
        with duckdb_connection() as con:
            for alias, dsn in (attachments or {}).items():
                if not attach_postgres(con, alias, dsn):
                    logger.warning(
                        "snapshot_to_parquet: attach failed for %s; aborting", alias
                    )
                    return None
            for name, df in (dataframes or {}).items():
                register_dataframe(con, name, df)
            for name, path in (parquet or {}).items():
                read_parquet(con, name, path)

            # COPY (<query>) TO '<dest>' (FORMAT PARQUET). The query/dest cannot
            # be bound as params; query text comes from the caller (trusted
            # federation SQL) and dest is single-quote-escaped.
            if cfg is not None:
                _configure_s3(con, cfg)
                dest = "s3://{bucket}/{prefix}/{key}".format(
                    bucket=cfg["bucket"],
                    prefix=cfg["prefix"],
                    key=key,
                ) if cfg["prefix"] else "s3://{bucket}/{key}".format(
                    bucket=cfg["bucket"], key=key
                )
            else:
                dest = os.path.join(_local_snapshot_dir(), key)
                os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)

            safe_dest = str(dest).replace("'", "''")
            safe_sql = str(sql).strip().rstrip(";")
            con.execute(
                "COPY ({sql}) TO '{dest}' (FORMAT PARQUET)".format(
                    sql=safe_sql, dest=safe_dest
                )
            )
            logger.info("snapshot_to_parquet: wrote snapshot to %s", dest)
            return dest
    except Exception:
        logger.warning("snapshot_to_parquet failed", exc_info=True)
        return None
