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


# ---------------------------------------------------------------------------
# Per-process override store (per-org hybrid-flag override layer)
# ---------------------------------------------------------------------------
# When a key is present here it WINS over the env default. Populated at boot
# from organization_settings.config['hybrid_overrides'] (see
# load_overrides_from_db) and kept live by the admin route via set_override.
# Empty by default -> behaviour is byte-identical to the pure-env flags.
_OVERRIDES: dict[str, bool] = {}


def _bool(name: str, default: bool = False) -> bool:
    """Read a boolean flag.

    Resolution order:
      1. process override (`_OVERRIDES[name]`) if present, else
      2. the env var (truthy: 1/true/yes/on, case-insensitive), else
      3. the supplied default.
    """
    if name in _OVERRIDES:
        return _OVERRIDES[name]
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def set_override(env_name: str, value: "bool | None") -> None:
    """Set or clear a per-process flag override.

    value=True/False pins the flag; value=None clears the override so the
    env default takes over again. Takes effect immediately this process.
    """
    if value is None:
        _OVERRIDES.pop(env_name, None)
    else:
        _OVERRIDES[env_name] = bool(value)


def overrides_snapshot() -> dict[str, bool]:
    """Current process override store (copy, for debugging / health)."""
    return dict(_OVERRIDES)


# ---------------------------------------------------------------------------
# Upgrade flag metadata (the 8 agent-upgrade env-names + UI rendering hints)
# role: who the toggle is for — 'agent' (capability), 'user' (UX), 'review'
# (writes learned/proposed knowledge through the approval gate).
# ---------------------------------------------------------------------------
UPGRADE_FLAGS: dict[str, dict[str, str]] = {
    "HYBRID_AGENT_MEMORY": {"label": "Agent Memory", "role": "review"},
    "HYBRID_SUBAGENTS": {"label": "Subagent Fan-out", "role": "agent"},
    "HYBRID_SKILL_AUTOGROW": {"label": "Skill Auto-grow", "role": "review"},
    "HYBRID_BITEMPORAL": {"label": "Bi-temporal Facts", "role": "user"},
    "HYBRID_WORKFLOWS": {"label": "Workflow Runner", "role": "user"},
    "HYBRID_CONTEXT_COMPACT": {"label": "Context Compaction", "role": "agent"},
    "HYBRID_SKILL_OPTIMIZE": {"label": "Skill Optimizer", "role": "user"},
    "HYBRID_SKILL_OPTIMIZE_DAEMON": {"label": "Skill Optimizer Daemon", "role": "agent"},
    "HYBRID_RECURSIVE": {"label": "Recursive Verify", "role": "agent"},
    "HYBRID_FOLLOWUPS": {"label": "Suggested Follow-ups", "role": "user"},
    "HYBRID_SCOPE_GATE": {"label": "Scope Guardrail", "role": "user"},
    "HYBRID_DASH_VERSIONS": {"label": "Dashboard Versions", "role": "user"},
}


async def load_overrides_from_db(db) -> int:
    """Scan organization_settings rows and apply their hybrid overrides.

    Reads each row's `config['hybrid_overrides']` (a dict of
    {ENV_NAME: bool}) and merges every recognised key into `_OVERRIDES`.
    Only keys present in UPGRADE_FLAGS are honoured (ignores stale/unknown
    keys). Returns the number of override keys loaded. Never raises into the
    boot path — on any error it returns whatever was loaded so far.

    NOTE: single-project deploys have one org; if multiple org rows set the
    same key the last-scanned row wins (process-wide store, not per-org).
    """
    loaded = 0
    try:
        from sqlalchemy import select  # local import: keep module dep-free
        from app.models.organization_settings import OrganizationSettings

        result = await db.execute(select(OrganizationSettings))
        rows = result.scalars().all()
        for row in rows:
            config = getattr(row, "config", None) or {}
            overrides = config.get("hybrid_overrides") if isinstance(config, dict) else None
            if not isinstance(overrides, dict):
                continue
            for env_name, value in overrides.items():
                if env_name in UPGRADE_FLAGS and value is not None:
                    _OVERRIDES[env_name] = bool(value)
                    loaded += 1
    except Exception:
        # Never break boot over a malformed override row.
        return loaded
    return loaded


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

    # --- Workflow runner (deterministic conductor + verifier gate) ----------
    @property
    def WORKFLOWS(self) -> bool:
        # Deterministic batch pipeline: fan a work-list through fixed stages, a
        # per-item judge gate (pass/retry/skip), full log. Reuses subagent
        # workers. For reliable bulk ops (train warehouse, eval backfill). Default OFF.
        return _bool("HYBRID_WORKFLOWS")

    # --- Skill Optimizer (SkillOpt: skill doc as trainable artifact) ---------
    @property
    def SKILL_OPTIMIZE(self) -> bool:
        # Closed-loop skill optimization: rollout a skill on held-out eval
        # goldens -> Judge score -> LLM textual edits -> accept only if the
        # held-out score strictly improves -> new version, status pending.
        # Approval-gated, OpenRouter-only, no GPU. Default OFF.
        return _bool("HYBRID_SKILL_OPTIMIZE")

    @property
    def SKILL_OPTIMIZE_DAEMON(self) -> bool:
        # Sub-flag: nightly leader-gated auto-optimize of stale/low-scoring
        # skills. Default OFF.
        return _bool("HYBRID_SKILL_OPTIMIZE_DAEMON")

    # --- Context compaction (GCC/OpenDerisk: edit + compress + awareness) ----
    @property
    def CONTEXT_COMPACT(self) -> bool:
        # Between/within turns: drop superseded/low-priority sections to a token
        # budget (EDIT), append a "context: X of Y" awareness line (AWARENESS),
        # and optionally LLM-summarize the dropped text (COMPRESS, sub-flag).
        # Longer/cheaper sessions, fewer "context full" failures. Default OFF.
        return _bool("HYBRID_CONTEXT_COMPACT")

    @property
    def CONTEXT_COMPACT_LLM(self) -> bool:
        # Sub-flag: allow ONE LLM summarization of dropped/old text per agent run
        # (COMPRESS). Off -> deterministic head-truncate only (no LLM cost).
        return _bool("HYBRID_CONTEXT_COMPACT_LLM")

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
    def RECURSIVE(self) -> bool:
        # Recursive verify: each subagent finding is graded by a cheap critic;
        # HARD-error findings are re-delegated with the reviewer note (bounded
        # loop, default 2 retries via HYBRID_RECURSIVE_MAX_RETRIES). Rides on
        # the subagent path — no-op unless SUBAGENTS is also on. Default OFF.
        return _bool("HYBRID_RECURSIVE")

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

    @property
    def AMBIGUITY_GATE(self) -> bool:
        # R3 "ask before assuming" gate: pre-planning ambiguity classifier that
        # makes the agent clarify (via the clarify tool) instead of assuming a
        # year/metric/entity. Vectorless, OpenRouter-only, fail-open. Default OFF.
        return _bool("HYBRID_AMBIGUITY_GATE")

    @property
    def SCOPE_GATE(self) -> bool:
        # Per-agent SCOPE GUARDRAIL: a zero-LLM directive injected pre-loop that
        # binds the agent to its OWN connected data sources. Off-topic / general-
        # knowledge / current-events questions (e.g. "who is president of usa")
        # are REFUSED — the agent must not answer them even if the model knows,
        # and instead redirects to a data question. Grounded per-Studio by the
        # report's pinned data-source names, so each agent's scope is its own.
        # Fail-open (never blocks a real data question). Default ON — every agent
        # should be guarded.
        return _bool("HYBRID_SCOPE_GATE", True)

    @property
    def DASH_VERSIONS(self) -> bool:
        # Dashboard layout VERSIONING: deliberate semantic changes (add/remove
        # chart from chat, manual remove, autopilot) snapshot a NEW immutable
        # layout version + keep all prior ones (restore-able). In-place
        # drag/resize stays a single-version mutate. Mainly gates FE behavior;
        # the snapshot/restore endpoints still work when off. Default ON.
        return _bool("HYBRID_DASH_VERSIONS", True)

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
    def AUTOMAP(self) -> bool:
        # Feature 1: auto-configure-from-doc. Extract column descriptions +
        # instructions + examples from an uploaded definitions xlsx / deck pptx
        # and apply them (descriptions live, instructions/examples pending). Default OFF.
        return _bool("HYBRID_AUTOMAP")

    @property
    def COMPLIANCE_GATE(self) -> bool:
        # Feature 4: on-demand, advisory, read-only compliance & data-integrity
        # scan endpoint (dedup + required-field quality). Default OFF.
        return _bool("HYBRID_COMPLIANCE_GATE")

    @property
    def COLUMN_INTEL(self) -> bool:
        # Batch B: pre-train per-column profiler (role + allowed values +
        # distinct + null_pct) merged into DataSourceTable.columns[].metadata,
        # surfaced into the schema XML so the agent knows each column up front.
        # Default OFF.
        return _bool("HYBRID_COLUMN_INTEL")

    @property
    def AUTO_QUERIES(self) -> bool:
        # Auto-train pipeline: LLM generates example SQL per pinned source,
        # runs read-only, saves verified queries to the library. Default OFF.
        return _bool("HYBRID_AUTO_QUERIES")

    @property
    def AUTO_EVALS(self) -> bool:
        # Auto-train pipeline: LLM generates golden eval cases from real data
        # aggregates (grounded expectations). Creation only. Default OFF.
        return _bool("HYBRID_AUTO_EVALS")

    @property
    def FOLLOWUPS(self) -> bool:
        # Suggested follow-up questions after each chat answer (ChatGPT/Claude
        # style). Generated per-agent: grounded in the Studio's voice + active
        # instructions + real column values, so each agent suggests its own
        # follow-ups. Default OFF.
        return _bool("HYBRID_FOLLOWUPS")

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
            "CONTEXT_COMPACT": self.CONTEXT_COMPACT,
            "SKILL_OPTIMIZE": self.SKILL_OPTIMIZE,
            "SUBAGENTS": self.SUBAGENTS,
            "RECURSIVE": self.RECURSIVE,
            "FOLLOWUPS": self.FOLLOWUPS,
            "SCOPE_GATE": self.SCOPE_GATE,
            "DASH_VERSIONS": self.DASH_VERSIONS,
        }


flags = HybridFlags()
