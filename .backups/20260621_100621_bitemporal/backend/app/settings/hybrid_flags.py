"""
Hybrid feature flags
====================

Flags that gate the CityAgent Analytics hybrid work (dash patterns +
Karpathy 2nd-Brain + self-service skills + federation). Each maps to an
env var and defaults OFF so a fresh deploy behaves exactly like upstream
dash until a flag is explicitly enabled.

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

    # --- Autotrain: dash-style "upload a file -> train -> answer" ------------
    @property
    def AUTOTRAIN(self) -> bool:
        # Ingest a flat file (or connector table) into `staging`, profile it,
        # and auto-propose PENDING knowledge (semantic/metrics/verified-Q&A).
        # Source-agnostic, approval-only, vectorless. Default OFF.
        return _bool("HYBRID_AUTOTRAIN")

    @property
    def AUTOTRAIN_QA(self) -> bool:
        # Sub-flag: generate+execute+keep verified Q&A during autotrain.
        return _bool("HYBRID_AUTOTRAIN_QA")

    @property
    def AUTOTRAIN_PROFILE(self) -> bool:
        # Sub-flag: write profile_v2 JSONB onto datasource_tables.metadata_json.
        return _bool("HYBRID_AUTOTRAIN_PROFILE")

    @property
    def AUTOTRAIN_ON_INDEX(self) -> bool:
        # OPT-IN: after a connector finishes indexing, auto-train its NEW tables
        # into pending knowledge. Default OFF — can be costly on big warehouses.
        return _bool("HYBRID_AUTOTRAIN_ON_INDEX")

    # --- Bi-temporal facts (Zep/Graphiti: valid_at/invalid_at/superseded_by) --
    @property
    def BITEMPORAL(self) -> bool:
        # Evolving facts (metrics, semantic, memory) get a timeline instead of
        # being overwritten: reads return only currently-valid rows; supersede on
        # re-approve; optional as-of time-travel. Default OFF (reads unfiltered).
        return _bool("HYBRID_BITEMPORAL")

    # --- Skill auto-grow (Voyager: 👍 -> draft skill) ------------------------
    @property
    def SKILL_AUTOGROW(self) -> bool:
        # On a 👍'd answer, auto-author a DRAFT personal skill (reuses
        # distill_skill_from_completion). Owner activates it to go live.
        # Self-learning for PROCEDURES (memory tool = facts). Default OFF.
        return _bool("HYBRID_SKILL_AUTOGROW")

    # --- Subagents (orchestrator-worker fan-out) ----------------------------
    @property
    def SUBAGENTS(self) -> bool:
        # `delegate_subtask` tool + orchestrator fan-out: spawn clean-context
        # research workers (LLM->SQL->client->distill) for multi-source/hard Qs.
        # Default OFF — N× tokens; budget + concurrency capped. Single-analyst
        # path is untouched when off.
        return _bool("HYBRID_SUBAGENTS")

    @property
    def AGENT_MEMORY(self) -> bool:
        # `remember`/`recall` tools + a memory context section. Agent stows +
        # pages cross-session state. Personal scope = live; shared = pending.
        # Vectorless (PG-FTS + Jaccard). Default OFF.
        return _bool("HYBRID_AGENT_MEMORY")

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

    @property
    def STUDIOS(self) -> bool:
        # Studios: NotebookLM-style shareable agent containers. Default OFF.
        return _bool("HYBRID_STUDIOS")

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

    @property
    def JOIN_GRAPH(self) -> bool:
        # Phase 6: join-graph context (relationship/join edges injected into
        # the planner, mined offline). Default OFF.
        return _bool("HYBRID_JOIN_GRAPH")

    @property
    def JOIN_MINE_ENABLED(self) -> bool:
        # Phase 6: nightly join-mining daemon (leader-gated). NOTE: no HYBRID_
        # prefix — matches EVAL_SCHEDULE_ENABLED naming convention. Default OFF.
        return _bool("JOIN_MINE_ENABLED")

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

    @property
    def GOVERNANCE(self) -> bool:
        # Kepler Phase 1: owner / freshness / PII metadata on semantic tables,
        # injected as a per-table governance footer + planner PII rule. Default OFF.
        return _bool("HYBRID_GOVERNANCE")

    @property
    def CODE_BANK(self) -> bool:
        # Kepler Phase 2: capture proven generate_df python on success + inject the
        # closest snippet(s) as PROVEN APPROACHES context (never executed). Default OFF.
        return _bool("HYBRID_CODE_BANK")

    @property
    def MEMORY_LOOP(self) -> bool:
        # Kepler Phase 3: on 👍, draft pending knowledge (proven SQL -> QueryLibraryItem,
        # bless captured code) with chat provenance. Approval-gated. Default OFF.
        return _bool("HYBRID_MEMORY_LOOP")

    @property
    def EVAL_HARNESS(self) -> bool:
        # Phase 4 (eval result-set goldens): result_set matcher + save-as-golden /
        # context-change re-run hooks + FE harness UI. Default OFF.
        return _bool("HYBRID_EVAL_HARNESS")

    @property
    def EVAL_SCHEDULE_ENABLED(self) -> bool:
        # Phase 4: nightly scheduled re-run of result-set goldens (leader-gated
        # daemon). NOTE: no HYBRID_ prefix — matches PLAN_KEPLER.md naming. Default OFF.
        return _bool("EVAL_SCHEDULE_ENABLED")

    @property
    def DOC_KNOWLEDGE(self) -> bool:
        # Kepler Phase 5: company-docs RAG. Approved docs are chunked + PG
        # full-text-searched (VECTORLESS — no embedder in image) and the top
        # matches injected as a "### Company definitions" block to resolve
        # business-term ambiguity. Approval-gated. Default OFF.
        return _bool("HYBRID_DOC_KNOWLEDGE")

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
            "STUDIOS": self.STUDIOS,
            "FEDERATION": self.FEDERATION,
            "BRAIN_GRAPH": self.BRAIN_GRAPH,
            "INSIGHT_DAEMON": self.INSIGHT_DAEMON,
            "JOIN_GRAPH": self.JOIN_GRAPH,
            "JOIN_MINE_ENABLED": self.JOIN_MINE_ENABLED,
            "QUOTAS": self.QUOTAS,
            "SEMANTIC_LAYER": self.SEMANTIC_LAYER,
            "METRICS_CATALOG": self.METRICS_CATALOG,
            "GOVERNANCE": self.GOVERNANCE,
            "CODE_BANK": self.CODE_BANK,
            "MEMORY_LOOP": self.MEMORY_LOOP,
            "EVAL_HARNESS": self.EVAL_HARNESS,
            "EVAL_SCHEDULE_ENABLED": self.EVAL_SCHEDULE_ENABLED,
            "DOC_KNOWLEDGE": self.DOC_KNOWLEDGE,
        }


flags = HybridFlags()
