"""
Warm-session client cache
=========================

An in-process, short-TTL cache for CONSTRUCTED data-source clients.

Motivation
----------
`DataSourceService.construct_clients` rebuilds the connector client(s) and
re-resolves per-user credentials on EVERY agent turn. For most sources that is
pure, repeated work whose result is identical within a single chat/report
session. Caching the constructed clients per (data_source, user) and reusing
them within a short TTL is a large latency win across all source types.

Scope / correctness
--------------------
* This cache sits ENTIRELY BEHIND the security access guard in
  `construct_clients` (`user_can_access_data_source` → 403). It is only ever
  consulted AFTER that guard has run and passed on the current call, so it can
  never serve a client to an unauthorized user.
* The cache key includes the requesting user id, so per-user credential
  resolution / Row-Level-Security identity is preserved (each user gets their
  own constructed clients; nothing crosses users).
* It is PER-PROCESS. With uvicorn workers=4 each worker keeps its own cache;
  that is fine — this is a performance cache, not correctness state. A miss (in
  a cold worker, after eviction, or after TTL expiry) simply rebuilds exactly as
  today. Stale entries self-heal within <= TTL; `invalidate()` exists for the
  eager re-sync / schema-refresh case.
* Everything here is best-effort. Callers MUST wrap usage in try/except and fall
  through to the normal build on any error (fail-soft). Nothing in this module
  raises for a normal miss.

TTL
---
Default ~300s, overridable via env `HYBRID_WARM_SESSION_TTL` (fail-soft parse:
a bad value falls back to the default). Expiry uses `time.monotonic()` so it is
immune to wall-clock adjustments.
"""

from __future__ import annotations

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
    """TTL from env `HYBRID_WARM_SESSION_TTL`, fail-soft to `_DEFAULT_TTL`."""
    raw = os.getenv("HYBRID_WARM_SESSION_TTL")
    if not raw:
        return _DEFAULT_TTL
    try:
        val = float(raw)
        return val if val > 0 else _DEFAULT_TTL
    except Exception:
        return _DEFAULT_TTL


# ---------------------------------------------------------------------------
# Store: key = (ds_id, user_id) -> (clients_dict, monotonic_expiry)
# Insertion-ordered dict → the first key is the oldest, giving cheap FIFO
# eviction without extra bookkeeping.
# ---------------------------------------------------------------------------
_CACHE: Dict[Tuple[str, str], Tuple[Dict[str, Any], float]] = {}


def _mk_key(ds_id: Any, user_id: Any) -> Tuple[str, str]:
    return (str(ds_id), str(user_id if user_id is not None else "system"))


def get_cached_clients(ds_id: Any, user_id: Any) -> Optional[Dict[str, Any]]:
    """Return the cached clients dict for (ds_id, user_id), or None if absent
    or expired. Expired entries are dropped on access. Never raises."""
    try:
        key = _mk_key(ds_id, user_id)
        entry = _CACHE.get(key)
        if entry is None:
            return None
        clients, expiry = entry
        if time.monotonic() >= expiry:
            _CACHE.pop(key, None)
            return None
        return clients
    except Exception:
        return None


def put_cached_clients(
    ds_id: Any,
    user_id: Any,
    clients: Dict[str, Any],
    ttl: Optional[float] = None,
) -> None:
    """Cache `clients` for (ds_id, user_id) with the given TTL (default env/300s).
    Enforces `_MAX_ENTRIES` via oldest-first eviction. Never raises."""
    try:
        if not clients:
            return
        ttl_val = ttl if (ttl is not None and ttl > 0) else _ttl_seconds()
        key = _mk_key(ds_id, user_id)
        # Refresh position on re-put so it counts as newest.
        _CACHE.pop(key, None)
        _CACHE[key] = (clients, time.monotonic() + ttl_val)
        # Oldest-first eviction to bound growth.
        while len(_CACHE) > _MAX_ENTRIES:
            try:
                oldest = next(iter(_CACHE))
                _CACHE.pop(oldest, None)
            except StopIteration:
                break
    except Exception:
        # Never let a cache write break the caller.
        return


def invalidate(ds_id: Any) -> int:
    """Drop ALL users' cached entries for a data source. Call on re-sync /
    schema change so a fresh build picks up new metadata. Returns the number of
    entries dropped. Never raises."""
    try:
        target = str(ds_id)
        stale = [k for k in _CACHE if k[0] == target]
        for k in stale:
            _CACHE.pop(k, None)
        return len(stale)
    except Exception:
        return 0


def clear() -> None:
    """Drop the entire cache (test / shutdown / admin reset). Never raises."""
    try:
        _CACHE.clear()
    except Exception:
        return
