"""
BI snapshot engine — local DuckDB copy of Power BI / Fabric tables (Fast Lane)
==============================================================================

Power BI / Fabric are slow to query interactively: every question fans out live
DAX/SQL over HTTP to Microsoft's engine (seconds per call, plus 429 throttling).
This module makes them fast by keeping a LOCAL, columnar copy of each connector
table in a per-data-source DuckDB file. Once a table is snapshotted, a query
hits local Parquet/DuckDB storage (milliseconds) instead of the live service.

Lifecycle (wiring lives elsewhere — this is the engine only):
  * refreshed on connector SYNC or on demand (``snapshot_data_source`` /
    ``snapshot_table``) — pulls each active table with a bounded pull and writes
    it to the local store, recording row count + an ``updated_at`` marker;
  * queried IN PLACE (``query_snapshot``) — read-only DuckDB SQL over the local
    copy, so the agent's create_data path can run against ms-fast local data;
  * freshness bookkeeping (``snapshot_meta`` / ``is_stale``) tells the router
    whether a table's snapshot is new enough to serve or must be refreshed.

"Live mode" (a later wiring concern) bypasses this module entirely and queries
the source directly for always-fresh, never-cached reads.

Design rules (mirror ``ai/code_execution/duckdb_engine.py``):
  * REUSES that module's bounded-connection config — ``_memory_limit`` /
    ``_temp_dir`` / ``_threads`` / ``_duckdb_available`` — instead of a second
    connection layer. The one difference is persistence: federation opens a
    ``:memory:`` connection, whereas a snapshot store must be a persistent
    ``.duckdb`` file per data source, so this module opens that file itself
    (applying the exact same bounds).
  * Store dir reuses ``FEDERATION_SNAPSHOT_DIR`` (or ``BI_SNAPSHOT_DIR``) env,
    else a sane ``/tmp/ca_bi_snapshot`` default — created on demand.
  * Fail-soft: every function swallows operational errors and returns a status
    dict / empty result / None-ish value. NOTHING here raises into a caller.
  * Import-safe: ``duckdb`` / ``pandas`` are imported lazily inside functions so
    the module imports with the dependency absent. No ``datetime.now()`` — the
    caller passes ``updated_at``; if absent we fall back to ``time.time()``.
  * Flag gate: the implicit sync-time entrypoint (``snapshot_data_source``)
    respects ``flags.FAST_LANE and flags.BI_SNAPSHOT`` (skip when off). The raw
    per-table / query helpers stay directly callable — the flag gate for the
    query router will live at the wiring site later.

Store layout (per data source):
  <snapshot_dir>/ds_<safe_ds_id>.duckdb
    ├── <table_key>                  one DuckDB table per snapshotted BI table
    └── _bi_snapshot_meta            sidecar: table_key, table_name, rows, updated_at
"""

from __future__ import annotations

import logging
import os
import re
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)

# Reuse the federation engine's bounded-connection config (single source of
# truth for memory/temp/threads + the duckdb-available probe). Import-safe: this
# module imports fine even if these move; a failure degrades to conservative
# local defaults.
try:  # pragma: no cover - trivial import shim
    from app.ai.code_execution.duckdb_engine import (
        _duckdb_available,
        _memory_limit,
        _temp_dir,
        _threads,
    )
except Exception:  # pragma: no cover - defensive fallback
    def _duckdb_available() -> bool:
        import importlib.util

        return importlib.util.find_spec("duckdb") is not None

    def _memory_limit() -> str:
        return (os.environ.get("DUCKDB_MEMORY_LIMIT") or "512MB").strip()

    def _temp_dir() -> Optional[str]:
        raw = (os.environ.get("DUCKDB_TEMP_DIR") or "").strip()
        return raw or None

    def _threads() -> Optional[int]:
        raw = (os.environ.get("DUCKDB_THREADS") or "").strip()
        try:
            n = int(raw)
            return n if n > 0 else None
        except Exception:
            return None


# Default bound on a single table pull — a snapshot is a bounded local cache, not
# a full mirror of an unbounded warehouse. Override per call.
_DEFAULT_MAX_ROWS = 200_000

# Sidecar meta table name inside each per-source DuckDB file.
_META_TABLE = "_bi_snapshot_meta"


# --- configuration ---------------------------------------------------------


def snapshot_dir() -> str:
    """Resolve (and create) the local dir that holds the DuckDB snapshot files.

    Precedence: ``BI_SNAPSHOT_DIR`` env, else ``FEDERATION_SNAPSHOT_DIR``/bi
    (reusing the federation snapshot root when present), else a temp default
    ``<DUCKDB_TEMP_DIR or /tmp>/ca_bi_snapshot``. Created on demand; falls back
    to the default on any error so a bad env can't wedge the engine.
    """
    try:
        raw = (os.environ.get("BI_SNAPSHOT_DIR") or "").strip()
        if not raw:
            fed = (os.environ.get("FEDERATION_SNAPSHOT_DIR") or "").strip()
            if fed:
                raw = os.path.join(fed, "bi")
        if not raw:
            base = _temp_dir() or os.path.join(os.path.sep, "tmp")
            raw = os.path.join(base, "ca_bi_snapshot")
        os.makedirs(raw, exist_ok=True)
        return raw
    except Exception:
        fallback = os.path.join(os.path.sep, "tmp", "ca_bi_snapshot")
        try:
            os.makedirs(fallback, exist_ok=True)
        except Exception:
            pass
        return fallback


def _safe_slug(value: Any, *, maxlen: int = 120) -> str:
    """Collapse an arbitrary string to a filesystem/SQL-safe ``[A-Za-z0-9_]`` slug."""
    s = re.sub(r"[^A-Za-z0-9_]+", "_", str(value or "").strip()).strip("_")
    if not s:
        s = "x"
    # DuckDB identifiers must not start with a digit for the bare form we use.
    if s[0].isdigit():
        s = "t_" + s
    return s[:maxlen]


def snapshot_key(data_source_id: Any, table_name: Any) -> str:
    """A stable, safe DuckDB table key for ``(data_source_id, table_name)``.

    The BI table name may carry a ``Workspace/Model/Table`` qualifier and spaces
    — this normalises to a bare, identifier-safe key. The data_source_id is not
    part of the key because tables already live in that source's own DB file, but
    it is accepted so callers can compute keys without the client.
    """
    bare = str(table_name or "")
    # Prefer the trailing segment of a qualified BI name (the DAX table).
    if "/" in bare:
        bare = bare.split("/")[-1]
    return _safe_slug(bare)


def _db_path(data_source_id: Any) -> str:
    """Absolute path to the per-data-source DuckDB snapshot file."""
    return os.path.join(snapshot_dir(), "ds_%s.duckdb" % _safe_slug(data_source_id))


# --- bounded persistent connection -----------------------------------------


@contextmanager
def _connect(data_source_id: Any, *, read_only: bool = False) -> Iterator[Any]:
    """Yield a bounded DuckDB connection to the source's snapshot file.

    Applies the same ``memory_limit`` / ``temp_directory`` / ``threads`` bounds
    as the federation engine so a heavy local scan can't OOM the box. Ensures the
    meta sidecar table exists (write connections only). Always closed in finally.
    Lazy-imports duckdb; raises RuntimeError if the dep is missing (public
    helpers pre-check ``_duckdb_available`` and degrade instead).
    """
    import duckdb  # lazy: keeps module import-safe without the dep

    path = _db_path(data_source_id)
    con = duckdb.connect(database=path, read_only=read_only)
    try:
        try:
            con.execute("SET memory_limit = ?", [_memory_limit()])
            tmp = _temp_dir()
            if tmp:
                con.execute("SET temp_directory = ?", [tmp])
            threads = _threads()
            if threads is not None:
                con.execute("SET threads = ?", [threads])
        except Exception:
            logger.debug("bi_snapshot: bound config failed", exc_info=True)
        if not read_only:
            con.execute(
                "CREATE TABLE IF NOT EXISTS %s "
                "(table_key VARCHAR PRIMARY KEY, table_name VARCHAR, "
                "rows BIGINT, updated_at DOUBLE)" % _META_TABLE
            )
        yield con
    finally:
        try:
            con.close()
        except Exception:  # pragma: no cover
            logger.debug("bi_snapshot: connection close failed", exc_info=True)


# --- pulling a table from the BI client ------------------------------------


async def _call_execute(
    client: Any,
    query: str,
    table_name: Optional[str],
    *,
    dataset_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
) -> Optional[Any]:
    """Execute ``query`` on a BI client, returning a DataFrame or None (fail-soft).

    Handles both sync (``execute_query``, PowerBI/Fabric) and async
    (``aexecute_query``) client APIs; offloads a sync call to a thread so the
    event loop isn't blocked.

    When ``dataset_id`` / ``workspace_id`` are given they are forwarded as kwargs
    so the client can query that EXACT Power BI dataset without any offline
    table-index resolution (the multi-dataset connector's index can be empty →
    resolution returns ``(None, None)`` → brute-force generic-name probing that
    fails). If the client's signature doesn't accept those kwargs, we degrade
    gracefully: retry with just ``table_name``, then positionally.
    """
    import asyncio
    import inspect

    # Progressively-degrading kwarg sets: richest (explicit ids) first, so a
    # client that DOES accept them queries the exact dataset; a client that
    # doesn't falls back to table_name, then to a bare positional call.
    kwarg_sets: List[Dict[str, Any]] = []
    ids_kwargs: Dict[str, Any] = {}
    if dataset_id is not None:
        ids_kwargs["dataset_id"] = dataset_id
    if workspace_id is not None:
        ids_kwargs["workspace_id"] = workspace_id
    if ids_kwargs:
        kwarg_sets.append({"table_name": table_name, **ids_kwargs})
    kwarg_sets.append({"table_name": table_name})
    kwarg_sets.append({})

    for meth_name in ("execute_query", "aexecute_query"):
        meth = getattr(client, meth_name, None)
        if meth is None:
            continue
        for kwargs in kwarg_sets:
            try:
                if inspect.iscoroutinefunction(meth):
                    return await meth(query, **kwargs)
                return await asyncio.to_thread(lambda k=kwargs: meth(query, **k))
            except TypeError:
                # Signature rejects these kwargs — try the next, leaner set.
                continue
            except Exception:
                logger.debug("bi_snapshot: %s failed", meth_name, exc_info=True)
                break
    return None


def _spec_fields(spec: Any) -> Dict[str, Any]:
    """Normalise a table ``spec`` (plain string OR dict) → the fields we pull with.

    Legacy string: only a qualified/bare ``name`` is known → DAX uses the bare
    trailing segment, no explicit ids (client resolves as before).
    Dict spec: carries the qualified ``name`` (snapshot key source), the bare
    ``dax_name`` for the DAX/SQL body, and explicit ``dataset_id`` /
    ``workspace_id`` so the client skips all resolution.
    """
    if isinstance(spec, dict):
        name = str(spec.get("name") or "")
        dax_name = spec.get("dax_name") or spec.get("tableName")
        if not dax_name:
            dax_name = name.split("/")[-1] if "/" in name else name
        return {
            "name": name,
            "dax_name": str(dax_name),
            "dataset_id": spec.get("dataset_id"),
            "workspace_id": spec.get("workspace_id"),
            "queryable": spec.get("queryable", True),
        }
    name = str(spec or "")
    bare = name.split("/")[-1] if "/" in name else name
    return {
        "name": name,
        "dax_name": bare,
        "dataset_id": None,
        "workspace_id": None,
        "queryable": True,
    }


async def _pull_table(client: Any, spec: Any, max_rows: int) -> Optional[Any]:
    """Bounded full-table pull from a BI client → pandas DataFrame (or None).

    ``spec`` may be a plain table-name string (legacy: bare-name DAX, client
    resolves the dataset itself) OR a dict carrying explicit ``dataset_id`` /
    ``workspace_id`` + a bare ``dax_name`` — in which case those ids are passed
    through so the client queries that EXACT dataset with NO offline-index lookup.

    Tries a DAX bounded EVALUATE first (Power BI), then a SQL LIMIT (Fabric /
    SQL-style clients). Whichever returns a non-empty DataFrame wins. Fail-soft.
    """
    f = _spec_fields(spec)
    bare = f["dax_name"]
    name = f["name"]
    dataset_id = f["dataset_id"]
    workspace_id = f["workspace_id"]
    cap = int(max_rows) if max_rows and int(max_rows) > 0 else _DEFAULT_MAX_ROWS

    # 1) DAX (Power BI): TOPN bounds the pull server-side. Explicit ids (when
    #    present) skip the client's table-index resolution entirely.
    dax = "EVALUATE TOPN(%d, '%s')" % (cap, bare.replace("'", "''"))
    df = await _call_execute(
        client, dax, name, dataset_id=dataset_id, workspace_id=workspace_id
    )
    if df is not None:
        try:
            if len(df) > 0 or getattr(df, "columns", None) is not None:
                return df
        except Exception:
            return df

    # 2) SQL (Fabric / warehouse-style): LIMIT bounds the pull.
    sql = 'SELECT * FROM "%s" LIMIT %d' % (bare.replace('"', '""'), cap)
    df = await _call_execute(
        client, sql, name, dataset_id=dataset_id, workspace_id=workspace_id
    )
    return df


def _df_rowcount(df: Any) -> int:
    try:
        return int(len(df))
    except Exception:
        return 0


# --- snapshot writers -------------------------------------------------------


async def snapshot_table(
    client: Any,
    data_source_id: Any,
    table: Any,
    *,
    max_rows: int = _DEFAULT_MAX_ROWS,
    updated_at: Optional[float] = None,
) -> Dict[str, Any]:
    """Pull one BI table and write it to the local DuckDB snapshot store.

    Args:
        client: a constructed BI client exposing ``execute_query`` /
            ``aexecute_query`` returning a pandas DataFrame.
        data_source_id: owns the per-source DuckDB file.
        table: EITHER a plain table-name string (bare or
            ``Workspace/Model/Table`` qualified) OR a spec dict with the
            qualified ``name`` + bare ``dax_name`` + explicit ``dataset_id`` /
            ``workspace_id`` (see ``_spec_fields``). The DuckDB table key is
            always derived from the qualified ``name`` so SnapshotClient reads
            line up.
        max_rows: bound on the pull (a snapshot is a bounded cache).
        updated_at: freshness marker to record; defaults to ``time.time()``.

    Returns:
        ``{ok, rows, table, error}`` — never raises. ``ok=False`` with an
        ``error`` string on any failure (dep missing, empty pull, write error).
    """
    # The snapshot KEY stays derived from the qualified name (string or dict.name)
    # so the DuckDB table key is STABLE across the legacy + explicit-id callers.
    qualified_name = table.get("name") if isinstance(table, dict) else table
    key = snapshot_key(data_source_id, qualified_name)
    if not _duckdb_available():
        return {"ok": False, "rows": 0, "table": key, "error": "duckdb not installed"}
    if not qualified_name or not str(qualified_name).strip():
        return {"ok": False, "rows": 0, "table": key, "error": "empty table_name"}

    ts = float(updated_at) if updated_at is not None else time.time()

    try:
        df = await _pull_table(client, table, max_rows)
    except Exception as exc:  # pragma: no cover - _pull_table is already fail-soft
        return {"ok": False, "rows": 0, "table": key, "error": "pull failed: %s" % exc}

    if df is None:
        return {"ok": False, "rows": 0, "table": key, "error": "no data returned"}

    rows = _df_rowcount(df)
    try:
        with _connect(data_source_id) as con:
            # Register the DataFrame and materialise it as a persistent table.
            con.register("_bi_snap_src", df)
            con.execute('CREATE OR REPLACE TABLE "%s" AS SELECT * FROM _bi_snap_src' % key)
            con.unregister("_bi_snap_src")
            # Upsert freshness meta (delete+insert = portable across DuckDB vers).
            con.execute("DELETE FROM %s WHERE table_key = ?" % _META_TABLE, [key])
            con.execute(
                "INSERT INTO %s (table_key, table_name, rows, updated_at) "
                "VALUES (?, ?, ?, ?)" % _META_TABLE,
                [key, str(qualified_name), rows, ts],
            )
    except Exception as exc:
        logger.warning("bi_snapshot.snapshot_table write failed for %s", key, exc_info=True)
        return {"ok": False, "rows": rows, "table": key, "error": "write failed: %s" % exc}

    logger.info("bi_snapshot: wrote %s (%d rows) for ds=%s", key, rows, data_source_id)
    return {"ok": True, "rows": rows, "table": key, "error": None}


def _active_table_names(data_source: Any) -> List[str]:
    """Best-effort list of active table names from a DataSource ORM object.

    Reads ``data_source.tables`` (``DataSourceTable`` rows with ``.name`` /
    ``.is_active``). Fail-soft → empty list (caller then no-ops or uses an
    explicit ``tables`` list).
    """
    names: List[str] = []
    try:
        for t in (getattr(data_source, "tables", None) or []):
            try:
                if getattr(t, "is_active", True) and getattr(t, "name", None):
                    names.append(str(t.name))
            except Exception:
                continue
    except Exception:
        return []
    return names


def snapshot_enabled() -> bool:
    """True when the Fast Lane + BI snapshot flags are both ON (fail-soft)."""
    try:
        from app.settings.hybrid_flags import flags

        return bool(flags.FAST_LANE and flags.BI_SNAPSHOT)
    except Exception:
        return False


async def snapshot_data_source(
    client: Any,
    data_source: Any,
    *,
    tables: Optional[List[Any]] = None,
    max_rows: int = _DEFAULT_MAX_ROWS,
    updated_at: Optional[float] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Snapshot every active table of a data source (or the given ``tables``).

    This is the implicit sync-time entrypoint, so it respects the flag gate
    (``flags.FAST_LANE and flags.BI_SNAPSHOT``) unless ``force=True`` (used by
    an explicit "refresh now" action / tests). Per-table fail-soft: one bad
    table doesn't abort the rest.

    ``tables`` may be a list of plain name strings (legacy) OR a list of spec
    dicts (see ``_spec_fields``: qualified ``name`` + ``dax_name`` + explicit
    ``dataset_id`` / ``workspace_id`` + ``queryable``). A spec with
    ``queryable == False`` is SKIPPED (not pulled) so empty / non-queryable
    datasets (Usage Metrics, empty models) never throw.

    Returns:
        ``{ok, snapshotted, failed, skipped, rows, tables: {name: result},
        error}``.
    """
    if not force and not snapshot_enabled():
        return {
            "ok": False, "snapshotted": 0, "failed": 0, "skipped": 0, "rows": 0,
            "tables": {}, "error": "disabled",
        }
    if not _duckdb_available():
        return {
            "ok": False, "snapshotted": 0, "failed": 0, "skipped": 0, "rows": 0,
            "tables": {}, "error": "duckdb not installed",
        }

    data_source_id = getattr(data_source, "id", data_source)
    specs = list(tables) if tables else _active_table_names(data_source)
    if not specs:
        return {
            "ok": True, "snapshotted": 0, "failed": 0, "skipped": 0, "rows": 0,
            "tables": {}, "error": "no active tables",
        }

    ts = float(updated_at) if updated_at is not None else time.time()
    results: Dict[str, Any] = {}
    snapshotted = 0
    failed = 0
    skipped = 0
    total_rows = 0
    for spec in specs:
        # Result key = the qualified name (string spec, or dict.name).
        name = spec.get("name") if isinstance(spec, dict) else spec
        name = str(name or "")
        # Skip non-queryable specs (empty / non-queryable datasets) up-front.
        if isinstance(spec, dict) and not spec.get("queryable", True):
            results[name] = {
                "ok": False, "rows": 0,
                "table": snapshot_key(data_source_id, name),
                "error": "skipped (not queryable)", "skipped": True,
            }
            skipped += 1
            continue
        res = await snapshot_table(
            client, data_source_id, spec, max_rows=max_rows, updated_at=ts
        )
        results[name] = res
        if res.get("ok"):
            snapshotted += 1
            total_rows += int(res.get("rows") or 0)
        else:
            failed += 1

    return {
        "ok": failed == 0,
        "snapshotted": snapshotted,
        "failed": failed,
        "skipped": skipped,
        "rows": total_rows,
        "tables": results,
        "error": None if failed == 0 else "%d table(s) failed" % failed,
    }


# --- read-only local query --------------------------------------------------


# Statements that must never run against the read-only snapshot store.
_WRITE_TOKENS = re.compile(
    r"\b(insert|update|delete|drop|create|alter|attach|detach|copy|replace|"
    r"truncate|merge|export|import|pragma|call|install|load|set)\b",
    re.IGNORECASE,
)


def _is_read_only_sql(sql: str) -> bool:
    """Conservative guard: only allow a single SELECT/WITH read query."""
    s = (sql or "").strip().rstrip(";").strip()
    if not s:
        return False
    # No statement chaining.
    if ";" in s:
        return False
    first = s.split(None, 1)[0].lower()
    if first not in ("select", "with", "table", "from"):
        return False
    if _WRITE_TOKENS.search(s):
        return False
    return True


def query_snapshot(data_source_id: Any, sql: str) -> Any:
    """Run a read-only SQL query against the source's local DuckDB snapshot.

    DuckDB dialect. Guards read-only (SELECT/WITH only; any write keyword is
    rejected). Returns a pandas DataFrame on success, or an EMPTY DataFrame on
    any error / when the store is missing / when the SQL is rejected. Never
    raises.
    """
    import pandas as pd  # lazy

    empty = pd.DataFrame()
    if not _duckdb_available():
        return empty
    if not _is_read_only_sql(sql):
        logger.debug("bi_snapshot.query_snapshot rejected non-read-only sql")
        return empty
    if not os.path.isfile(_db_path(data_source_id)):
        return empty
    try:
        with _connect(data_source_id, read_only=True) as con:
            return con.execute(sql).df()
    except Exception:
        logger.warning("bi_snapshot.query_snapshot failed", exc_info=True)
        return empty


# --- freshness bookkeeping --------------------------------------------------


def snapshot_meta(data_source_id: Any) -> Dict[str, Any]:
    """Per-table freshness for a source: row counts + last-updated markers.

    Returns ``{tables: {table_name: {table_key, rows, updated_at, age_seconds}},
    count}``. Empty (``count=0``) when no store / no meta / any error.
    """
    out: Dict[str, Any] = {"tables": {}, "count": 0}
    if not _duckdb_available() or not os.path.isfile(_db_path(data_source_id)):
        return out
    now = time.time()
    try:
        with _connect(data_source_id, read_only=True) as con:
            rows = con.execute(
                "SELECT table_key, table_name, rows, updated_at FROM %s" % _META_TABLE
            ).fetchall()
        for table_key, table_name, nrows, updated_at in rows:
            ua = float(updated_at) if updated_at is not None else None
            out["tables"][str(table_name)] = {
                "table_key": table_key,
                "rows": int(nrows) if nrows is not None else 0,
                "updated_at": ua,
                "age_seconds": (now - ua) if ua is not None else None,
            }
        out["count"] = len(out["tables"])
    except Exception:
        logger.debug("bi_snapshot.snapshot_meta failed", exc_info=True)
    return out


def is_stale(data_source_id: Any, table: str, ttl_seconds: Optional[int]) -> bool:
    """True if ``table``'s snapshot is missing or older than ``ttl_seconds``.

    A missing snapshot is always stale (must be refreshed). A non-positive /
    absent ``ttl_seconds`` means "never expire" → not stale when present. Any
    error is treated as stale (safe: forces a refresh) EXCEPT the missing-store
    fast path which is unambiguous.
    """
    try:
        meta = snapshot_meta(data_source_id)
        # Match by exact table_name first, then by normalized snapshot_key.
        entry = meta["tables"].get(str(table))
        if entry is None:
            key = snapshot_key(data_source_id, table)
            for e in meta["tables"].values():
                if e.get("table_key") == key:
                    entry = e
                    break
        if entry is None:
            return True  # not snapshotted → stale
        if not ttl_seconds or int(ttl_seconds) <= 0:
            return False  # never expire
        age = entry.get("age_seconds")
        if age is None:
            return True
        return float(age) >= float(ttl_seconds)
    except Exception:
        return True
