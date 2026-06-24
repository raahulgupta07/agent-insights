"""
Freshness policy — federation data-staleness selector (Phase 7)
===============================================================

A tiny, pure, dependency-free helper that decides HOW FRESH a federated data
asset should be served:

  * LIVE         — query the source system directly every time. Pick this for
                   small, latency-tolerant assets that must reflect the most
                   recent writes (e.g. an order-status lookup).
  * CACHED       — reuse a recent result for a bounded TTL. Pick this for
                   repeat / tolerant reads where a few minutes of staleness is
                   acceptable and we want to avoid re-hitting the source.
  * MATERIALIZED — pre-compute / snapshot the asset (e.g. to a parquet snapshot
                   the federation engine scans). Pick this for heavy or
                   cross-source-correlated work that is too expensive to run
                   live on every request.

``resolve_policy`` reads simple hints from an asset-metadata dict and returns a
``FreshnessPolicy``. It is intentionally rule-based and side-effect free so it
can be unit-tested in isolation and reused by the federation engine and the
agent code-exec path without pulling in DuckDB, pandas, or the DB layer.

The actual cache/snapshot mechanics live elsewhere (the engine + a future MinIO
snapshot path); this module only expresses the *decision*.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

# --- Modes -----------------------------------------------------------------
# Plain string constants (stable, JSON-friendly, no enum import needed at call
# sites). Kept in a frozenset for cheap membership validation.
LIVE = "live"
CACHED = "cached"
MATERIALIZED = "materialized"

MODES = frozenset({LIVE, CACHED, MATERIALIZED})

# Default TTL applied to a CACHED policy when the caller gives no explicit hint.
DEFAULT_CACHE_TTL_SECONDS = 300


@dataclass(frozen=True)
class FreshnessPolicy:
    """An immutable freshness decision.

    Attributes:
        mode: one of LIVE / CACHED / MATERIALIZED.
        ttl_seconds: cache lifetime for CACHED mode; None for LIVE/MATERIALIZED.
    """

    mode: str
    ttl_seconds: Optional[int] = None

    def __post_init__(self) -> None:
        # Defensive: never construct an unknown mode. Falls back to LIVE which
        # is always correct (just potentially slower), the safe default.
        if self.mode not in MODES:
            object.__setattr__(self, "mode", LIVE)
            object.__setattr__(self, "ttl_seconds", None)
        # A TTL only makes sense for CACHED.
        if self.mode != CACHED and self.ttl_seconds is not None:
            object.__setattr__(self, "ttl_seconds", None)

    @property
    def is_live(self) -> bool:
        return self.mode == LIVE

    @property
    def is_cached(self) -> bool:
        return self.mode == CACHED

    @property
    def is_materialized(self) -> bool:
        return self.mode == MATERIALIZED


def _coerce_ttl(value: Any, default: int = DEFAULT_CACHE_TTL_SECONDS) -> int:
    """Best-effort positive-int TTL with a safe default."""
    try:
        ttl = int(value)
    except (TypeError, ValueError):
        return default
    return ttl if ttl > 0 else default


def resolve_policy(asset_meta: Optional[Dict[str, Any]]) -> FreshnessPolicy:
    """Choose a freshness policy from simple metadata hints.

    Recognised (all optional) keys in ``asset_meta``:
        mode            explicit override: 'live' | 'cached' | 'materialized'.
        needs_fresh     bool — the answer must reflect the latest writes.
        small           bool — the asset is cheap to query live.
        repeat          bool — the asset is read repeatedly (cache-friendly).
        tolerant        bool — some staleness is acceptable.
        heavy           bool — expensive to compute.
        correlated      bool — joins/correlates across multiple sources.
        ttl_seconds     int  — explicit cache TTL (only used for CACHED).

    Decision order (first match wins):
        1. explicit ``mode`` override (validated).
        2. heavy OR correlated                      -> MATERIALIZED.
        3. small AND needs_fresh                    -> LIVE.
        4. needs_fresh (and not heavy/correlated)   -> LIVE.
        5. repeat AND tolerant                       -> CACHED(ttl).
        6. tolerant or repeat (one of them)          -> CACHED(ttl).
        7. default                                   -> LIVE.

    LIVE is the safe default: it is always correct, only potentially slower.
    """
    meta: Dict[str, Any] = asset_meta or {}

    # 1. Explicit override always wins (validated by FreshnessPolicy).
    explicit = meta.get("mode")
    if isinstance(explicit, str) and explicit.strip().lower() in MODES:
        mode = explicit.strip().lower()
        if mode == CACHED:
            return FreshnessPolicy(CACHED, _coerce_ttl(meta.get("ttl_seconds")))
        return FreshnessPolicy(mode)

    needs_fresh = bool(meta.get("needs_fresh"))
    small = bool(meta.get("small"))
    repeat = bool(meta.get("repeat"))
    tolerant = bool(meta.get("tolerant"))
    heavy = bool(meta.get("heavy"))
    correlated = bool(meta.get("correlated"))

    # 2. Expensive / cross-source work — snapshot it.
    if heavy or correlated:
        return FreshnessPolicy(MATERIALIZED)

    # 3-4. Freshness requirement — go to the source.
    if needs_fresh:
        return FreshnessPolicy(LIVE)
    if small and not (repeat and tolerant):
        # Small + no caching signal: cheap enough to serve live.
        return FreshnessPolicy(LIVE)

    # 5-6. Cache-friendly signals.
    if (repeat and tolerant) or tolerant or repeat:
        return FreshnessPolicy(CACHED, _coerce_ttl(meta.get("ttl_seconds")))

    # 7. Safe default.
    return FreshnessPolicy(LIVE)
