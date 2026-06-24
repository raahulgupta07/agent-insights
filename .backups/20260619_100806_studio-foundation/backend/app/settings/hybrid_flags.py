"""
Hybrid feature flags
====================

Flags that gate the CityAgent Analytics hybrid work (dash patterns +
Karpathy 2nd-Brain + self-service skills + federation). Each maps to an
env var and defaults OFF so a fresh deploy behaves exactly like upstream
bow until a flag is explicitly enabled.

Keep this module dependency-free and decoupled from Settings.load so the
hybrid layers can be toggled without touching core config flow.

Usage:
    from app.settings.hybrid_flags import flags
    if flags.DUAL_SCHEMA:
        ...
"""

from __future__ import annotations

import os


def _bool(name: str, default: bool = False) -> bool:
    """Read a boolean env var. Truthy: 1/true/yes/on (case-insensitive)."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class HybridFlags:
    """Lazily-read flag registry. Read at access so env changes (tests) apply."""

    # --- Slice 1: foundation -------------------------------------------------
    @property
    def DUAL_SCHEMA(self) -> bool:
        # Phase 2: DB-level read-only engine + analytics/staging schemas.
        return _bool("HYBRID_DUAL_SCHEMA")

    @property
    def ENGINEER_ASSETS(self) -> bool:
        # Phase 3: build_data_asset tool (reusable analytics.* views).
        return _bool("HYBRID_ENGINEER_ASSETS")

    @property
    def ANSWER_CACHE(self) -> bool:
        # Tier-0 Redis answer-cache.
        return _bool("HYBRID_ANSWER_CACHE")

    # --- Slice 2: brain + skills --------------------------------------------
    @property
    def BRAIN_READ(self) -> bool:
        # Phase 4: inject brain memories + cached queries into context.
        return _bool("HYBRID_BRAIN_READ")

    @property
    def DISTILLER(self) -> bool:
        # Phase 5: 👎 self-distill -> pending memory.
        return _bool("HYBRID_DISTILLER")

    @property
    def QUERY_CACHE(self) -> bool:
        # Phase 5: reasoning-cache (param-swap proven SQL).
        return _bool("HYBRID_QUERY_CACHE")

    @property
    def SKILLS(self) -> bool:
        # Phase 6: self-service skills subsystem.
        return _bool("HYBRID_SKILLS")

    # --- Slice 3: federation + correlation ----------------------------------
    @property
    def FEDERATION(self) -> bool:
        # Phase 7: DuckDB cross-source federation.
        return _bool("HYBRID_FEDERATION")

    @property
    def BRAIN_GRAPH(self) -> bool:
        # Phase 8: Apache AGE entity/correlation graph. Default OFF.
        return _bool("HYBRID_BRAIN_GRAPH")

    @property
    def INSIGHT_DAEMON(self) -> bool:
        # Phase 8: proactive insight daemon (leader-gated). Default OFF.
        return _bool("HYBRID_INSIGHT_DAEMON")

    # --- Slice 4: scale harden ----------------------------------------------
    @property
    def QUOTAS(self) -> bool:
        # Phase 9: per-org request/token quota enforcement (UsagePolicy). Default OFF.
        return _bool("HYBRID_QUOTAS")

    # --- Slice 5: knowledge layer -------------------------------------------
    @property
    def SEMANTIC_LAYER(self) -> bool:
        # dash semantic model: per-table/column meaning injected into context.
        return _bool("HYBRID_SEMANTIC_LAYER")

    @property
    def METRICS_CATALOG(self) -> bool:
        # dash metrics catalog: named metric -> SQL definition.
        return _bool("HYBRID_METRICS_CATALOG")

    def snapshot(self) -> dict[str, bool]:
        """All flags as a dict (for /health, debugging, tests)."""
        return {
            "DUAL_SCHEMA": self.DUAL_SCHEMA,
            "ENGINEER_ASSETS": self.ENGINEER_ASSETS,
            "ANSWER_CACHE": self.ANSWER_CACHE,
            "BRAIN_READ": self.BRAIN_READ,
            "DISTILLER": self.DISTILLER,
            "QUERY_CACHE": self.QUERY_CACHE,
            "SKILLS": self.SKILLS,
            "FEDERATION": self.FEDERATION,
            "BRAIN_GRAPH": self.BRAIN_GRAPH,
            "INSIGHT_DAEMON": self.INSIGHT_DAEMON,
            "QUOTAS": self.QUOTAS,
            "SEMANTIC_LAYER": self.SEMANTIC_LAYER,
            "METRICS_CATALOG": self.METRICS_CATALOG,
        }


flags = HybridFlags()
