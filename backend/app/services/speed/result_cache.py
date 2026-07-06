"""
Warehouse result cache
======================

An in-process, short-TTL cache for the RESULT PAYLOAD of a SQL query executed
against a live warehouse source (postgres / snowflake / bigquery / mssql / …).

Motivation
----------
On the warehouse lane every `execute_query(sql)` is a network round-trip to a
remote engine. Within a chat/report session the SAME question (or a follow-up
that regenerates the identical SQL) commonly re-runs the byte-identical query.
Caching the returned rows per (data_source, normalized SQL) for a short TTL lets
a repeated identical query return instantly with zero DB round-trip.

Scope / correctness
-------------------
* WAREHOUSE LANE ONLY. The caller classifies the source
  (`speed.source_lane.classify_connection_type`) and only consults this cache for
  LANE_WAREHOUSE sources. Local uploads are already fast; BI has its own snapshot
  lane. Nothing here is consulted for those.
* READ-ONLY SELECT RESULTS ONLY. The caller stores only successful SELECT-style
  results — never a write/DDL statement and never an error. A miss simply runs the
  query live, exactly as today.
* PER-PROCESS. With uvicorn workers=N each worker keeps its own cache; that is
  fine — this is a performance cache, not correctness state. A miss (cold worker,
  eviction, or TTL expiry) simply re-runs the query. Stale entries self-heal within
  <= TTL; `invalidate(ds_id)` exists for the eager schema-refresh case.
* The KEY includes the data_source id, so one source's results can never be served
  for another source. SQL is normalized (whitespace-collapsed + lowercased) so a
  cosmetically-different-but-identical query still hits.
* Everything here is best-effort. Callers MUST wrap usage in try/except and fall
  through to a live query on any error (fail-soft). Nothing here raises on a normal
  miss.

TTL
---
Default ~300s, overridable via env `HYBRID_RESULT_CACHE_TTL` (fail-soft parse: a
bad value falls back to the default). Expiry uses `time.monotonic()` so it is
immune to wall-clock adjustments.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
_DEFAULT_TTL = 300.0        # seconds
_MAX_ENTRIES = 256          # hard cap → simple oldest-eviction beyond this


def _ttl_seconds() -> float:
    """TTL from env `HYBRID_RESULT_CACHE_TTL`, fail-soft to `_DEFAULT_TTL`."""
    raw = os.getenv("HYBRID_RESULT_CACHE_TTL")
    if not raw:
        return _DEFAULT_TTL
    try:
        val = float(raw)
        return val if val > 0 else _DEFAULT_TTL
    except Exception:
        return _DEFAULT_TTL


# ---------------------------------------------------------------------------
# Store: key = sha256(ds_id + normalized_sql) -> (payload, monotonic_expiry)
# Insertion-ordered dict → the first key is the oldest, giving cheap FIFO
# eviction without extra bookkeeping. A parallel key->ds_id map lets
# invalidate(ds_id) drop just one source's entries.
# ---------------------------------------------------------------------------
_CACHE: Dict[str, Tuple[Any, float]] = {}
_KEY_DS: Dict[str, str] = {}


def _normalize_sql(sql: Any) -> str:
    """Deterministic normalization: strip + collapse all whitespace + lowercase.

    `"  SELECT   *\n FROM  t "` and `"select * from t"` collapse to the same
    string, so a cosmetically-different-but-identical query hits the same key.
    """
    return " ".join(str(sql or "").split()).strip().lower()


def _mk_key(ds_id: Any, sql: Any) -> str:
    """sha256 of (data_source_id + normalized SQL)."""
    ds = str(ds_id if ds_id is not None else "unknown")
    payload = ds + "\n" + _normalize_sql(sql)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def get_cached_result(ds_id: Any, sql: str) -> Optional[Any]:
    """Return the cached result payload for (ds_id, sql), or None if absent or
    expired. Expired entries are dropped on access. Never raises."""
    try:
        key = _mk_key(ds_id, sql)
        entry = _CACHE.get(key)
        if entry is None:
            return None
        payload, expiry = entry
        if time.monotonic() >= expiry:
            _CACHE.pop(key, None)
            _KEY_DS.pop(key, None)
            return None
        return payload
    except Exception:
        return None


def put_cached_result(
    ds_id: Any,
    sql: str,
    payload: Any,
    ttl: Optional[float] = None,
) -> None:
    """Cache `payload` for (ds_id, sql) with the given TTL (default env/300s).
    Enforces `_MAX_ENTRIES` via oldest-first eviction. Never raises. A None
    payload is not cached (caller decides what counts as a real result)."""
    try:
        if payload is None:
            return
        ttl_val = ttl if (ttl is not None and ttl > 0) else _ttl_seconds()
        key = _mk_key(ds_id, sql)
        # Refresh position on re-put so it counts as newest.
        _CACHE.pop(key, None)
        _CACHE[key] = (payload, time.monotonic() + ttl_val)
        _KEY_DS[key] = str(ds_id if ds_id is not None else "unknown")
        # Oldest-first eviction to bound growth.
        while len(_CACHE) > _MAX_ENTRIES:
            try:
                oldest = next(iter(_CACHE))
                _CACHE.pop(oldest, None)
                _KEY_DS.pop(oldest, None)
            except StopIteration:
                break
    except Exception:
        # Never let a cache write break the caller.
        return


def invalidate(ds_id: Any = None) -> int:
    """Drop cached results. `ds_id=None` clears ALL sources; otherwise drops only
    that source's entries. Call on re-sync / schema change so a fresh query picks
    up new data. Returns the number of entries dropped. Never raises."""
    try:
        if ds_id is None:
            n = len(_CACHE)
            _CACHE.clear()
            _KEY_DS.clear()
            return n
        target = str(ds_id)
        stale = [k for k, ds in _KEY_DS.items() if ds == target]
        for k in stale:
            _CACHE.pop(k, None)
            _KEY_DS.pop(k, None)
        return len(stale)
    except Exception:
        return 0


def clear() -> None:
    """Drop the entire cache (test / shutdown / admin reset). Never raises."""
    try:
        _CACHE.clear()
        _KEY_DS.clear()
    except Exception:
        return


if __name__ == "__main__":
    # Self-test — pure, deterministic, no deps.
    ok = True

    def check(label: str, cond: bool):
        global ok
        status = "PASS" if cond else "FAIL"
        if not cond:
            ok = False
        print(f"{status}: {label}")

    clear()

    DS = "ds-123"
    OTHER_DS = "ds-999"
    SQL = "SELECT * FROM sales WHERE region = 'EU'"

    # 1. Miss on a cold cache.
    check("cold get -> miss", get_cached_result(DS, SQL) is None)

    # 2. put -> get hit, exact payload returned.
    payload = [{"region": "EU", "total": 42}]
    put_cached_result(DS, SQL, payload)
    got = get_cached_result(DS, SQL)
    check("put -> get hit returns payload", got == payload)

    # 3. Normalization: whitespace-different + case-different SAME sql -> same key -> hit.
    sql_variant = "  select *   FROM   sales\n WHERE region = 'EU'  "
    check("whitespace/case-different same SQL -> hit", get_cached_result(DS, sql_variant) == payload)

    # 4. Different SQL -> miss.
    check("different SQL -> miss", get_cached_result(DS, "SELECT * FROM inventory") is None)

    # 5. Same SQL, DIFFERENT data source -> miss (ds_id is in the key).
    check("same SQL other data source -> miss", get_cached_result(OTHER_DS, SQL) is None)

    # 6. invalidate(ds_id) drops only that source.
    put_cached_result(OTHER_DS, SQL, [{"x": 1}])
    dropped = invalidate(DS)
    check("invalidate(ds) drops DS entry", get_cached_result(DS, SQL) is None)
    check("invalidate(ds) kept OTHER_DS", get_cached_result(OTHER_DS, SQL) == [{"x": 1}])
    check("invalidate(ds) returned count>=1", dropped >= 1)

    # 7. invalidate() (None) clears everything.
    invalidate()
    check("invalidate(None) clears all", get_cached_result(OTHER_DS, SQL) is None)

    # 8. TTL expiry.
    put_cached_result(DS, SQL, payload, ttl=0.05)
    check("fresh TTL entry hits", get_cached_result(DS, SQL) == payload)
    time.sleep(0.08)
    check("expired TTL entry -> miss", get_cached_result(DS, SQL) is None)

    # 9. B5 — same query twice hits cache, executor runs ONCE (no 2nd DB call).
    clear()
    calls = {"n": 0}

    def fake_execute(ds_id, sql):
        cached = get_cached_result(ds_id, sql)
        if cached is not None:
            return cached, "cache"
        calls["n"] += 1
        result = [{"row": calls["n"]}]           # simulate a live DB read
        put_cached_result(ds_id, sql, result)
        return result, "live"

    r1, src1 = fake_execute(DS, SQL)
    r2, src2 = fake_execute(DS, SQL)
    check("B5 first call is live", src1 == "live")
    check("B5 second identical call is a cache HIT", src2 == "cache")
    check("B5 executor ran exactly once (no 2nd DB round-trip)", calls["n"] == 1)
    check("B5 both calls returned identical rows", r1 == r2)

    print("\nALL PASS" if ok else "\nSOME FAILED")
