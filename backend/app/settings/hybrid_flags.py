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

import logging
import os
from contextvars import ContextVar

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Override stores (per-org hybrid-flag override layer)
# ---------------------------------------------------------------------------
# ISSUE #2 FIX — tenant isolation. `load_overrides_from_db` used to merge every
# org's overrides into a single process-global dict (last-scanned org wins), so
# in a multi-org deploy one org's flag state silently bled into every other. The
# store is now split:
#
#   _OVERRIDES_BY_ORG  — per-org maps {org_id: {ENV_NAME: bool}}. Populated from
#                        each organization_settings row. These are the truth for
#                        a given tenant and NEVER cross orgs.
#   _OVERRIDES         — the "merged global" store (historical name kept). Two
#                        roles: (a) runtime pins from set_override that aren't
#                        scoped to an org, and (b) the fallback used when NO org
#                        context is bound (single-org deploys, daemons, offline
#                        scripts). It is the union of every org's overrides; a
#                        cross-org value conflict is logged LOUDLY at load time
#                        (see load_overrides_from_db) rather than silently merged.
#
# Resolution consults the org bound via set_current_org() FIRST, then falls back
# to the merged global. Empty stores + unbound context => byte-identical to the
# pure-env flags (dormant until a caller binds an org / the DB has overrides).
_OVERRIDES_BY_ORG: dict[str, dict[str, bool]] = {}
_OVERRIDES: dict[str, bool] = {}

# The organization whose per-org overrides win for the current request / task.
# Bound by set_current_org() (e.g. from request middleware); None => use the
# merged-global fallback. A ContextVar so it's isolated per asyncio task/thread.
_current_org: ContextVar[str | None] = ContextVar("hybrid_current_org", default=None)


def set_current_org(org_id: "str | None"):
    """Bind the org whose per-org flag overrides win for the current context.

    Call from request middleware / per-org task setup so `flags.X` resolves that
    tenant's overrides instead of the merged-global fallback. Returns a token;
    pass it to reset_current_org() to restore the previous binding. Unbound
    (never called / reset) => merged-global fallback (unchanged single-org
    behaviour).
    """
    return _current_org.set(str(org_id) if org_id is not None else None)


def reset_current_org(token) -> None:
    """Restore the org binding replaced by a set_current_org() token. Fail-soft."""
    try:
        _current_org.reset(token)
    except Exception:
        pass


def get_current_org() -> "str | None":
    """The org currently bound for flag resolution (or None)."""
    return _current_org.get()


def _bool(name: str, default: bool = False) -> bool:
    """Read a boolean flag.

    Resolution order:
      1. the CURRENT-ORG override (`_OVERRIDES_BY_ORG[current_org][name]`) if an
         org is bound (set_current_org) and the key is set for it, else
      2. the merged-global / runtime-pin store (`_OVERRIDES[name]`), else
      3. the env var (truthy: 1/true/yes/on, case-insensitive), else
      4. the supplied default.
    """
    org = _current_org.get()
    if org is not None:
        org_map = _OVERRIDES_BY_ORG.get(org)
        if org_map is not None and name in org_map:
            return org_map[name]
    if name in _OVERRIDES:
        return _OVERRIDES[name]
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    """Read an integer config knob from env (flags are bool-only; numeric knobs
    read env directly). Falls back to ``default`` on missing/invalid."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except (ValueError, AttributeError):
        return default


def set_override(env_name: str, value: "bool | None", org_id: "str | None" = None) -> None:
    """Set or clear a flag override, effective immediately this process.

    value=True/False pins the flag; value=None clears it so the env default takes
    over again. The pin is written to the merged-global store AND, when scoped to
    an org, to that org's per-org map so a live admin toggle resolves correctly
    for the tenant that flipped it. The org is taken from `org_id` if given, else
    from the current-org contextvar (set_current_org) — so the existing
    single-arg call in the admin route becomes org-aware automatically once a
    request binds its org, with no signature break for other callers.
    """
    org = str(org_id) if org_id is not None else _current_org.get()
    if value is None:
        _OVERRIDES.pop(env_name, None)
        if org is not None:
            m = _OVERRIDES_BY_ORG.get(org)
            if m is not None:
                m.pop(env_name, None)
    else:
        b = bool(value)
        _OVERRIDES[env_name] = b
        if org is not None:
            _OVERRIDES_BY_ORG.setdefault(org, {})[env_name] = b


def overrides_snapshot() -> dict[str, bool]:
    """Merged-global override store (copy, for debugging / health)."""
    return dict(_OVERRIDES)


def overrides_by_org_snapshot() -> dict[str, dict[str, bool]]:
    """Per-org override maps (deep copy, for debugging / health)."""
    return {org: dict(m) for org, m in _OVERRIDES_BY_ORG.items()}


# ---------------------------------------------------------------------------
# Flag registry — drives the Settings → Features UI (per-org override layer).
# Every togglable flag MUST be here or the override is silently ignored AND the
# PUT /organization/hybrid-flags route rejects it. Each entry:
#   label    — human name
#   role     — who the toggle is for: 'agent' (capability) | 'user' (UX) |
#              'review' (writes proposed knowledge through the approval gate)
#   category — UI section grouping
#   status   — 'stable'      : works now, flip to enable
#              'experimental': works but changes behaviour / token-heavy
#              'needs_dep'   : flag alone is not enough (needs infra/bake)
#              'unstable'    : known-bad, keep off
#              'daemon'      : background job, read at boot → needs restart
#   note     — short caveat shown in the UI (optional)
# ---------------------------------------------------------------------------
UPGRADE_FLAGS: dict[str, dict[str, str]] = {
    # --- Core -------------------------------------------------------------
    "HYBRID_STUDIOS": {"label": "Agent Studios", "role": "user", "category": "Core", "status": "stable"},
    "HYBRID_DASH_VERSIONS": {"label": "Dashboard Versions", "role": "user", "category": "Core", "status": "stable"},
    "HYBRID_SCOPE_GATE": {"label": "Scope Guardrail", "role": "user", "category": "Core", "status": "stable"},
    "HYBRID_FOLLOWUPS": {"label": "Suggested Follow-ups", "role": "user", "category": "Core", "status": "stable"},
    "HYBRID_DUAL_SCHEMA": {"label": "Dual Schema (read-only engine)", "role": "agent", "category": "Core", "status": "stable"},
    "HYBRID_ENGINEER_ASSETS": {"label": "Engineer Assets (view builder)", "role": "agent", "category": "Core", "status": "stable"},

    # --- Knowledge --------------------------------------------------------
    "HYBRID_SEMANTIC_LAYER": {"label": "Semantic Layer", "role": "agent", "category": "Knowledge", "status": "stable"},
    "HYBRID_METRICS_CATALOG": {"label": "Metrics Catalog", "role": "review", "category": "Knowledge", "status": "stable"},
    "HYBRID_VERIFIED_METRICS": {"label": "Executable Verified Metrics", "role": "review", "category": "Knowledge", "status": "stable"},
    "HYBRID_GOLDEN_QUERIES": {"label": "Golden Query Promotion", "role": "review", "category": "Knowledge", "status": "stable"},
    "HYBRID_DOC_KNOWLEDGE": {"label": "Company Docs (RAG)", "role": "review", "category": "Knowledge", "status": "stable"},
    "HYBRID_GOVERNANCE": {"label": "Governance (PII/freshness)", "role": "agent", "category": "Knowledge", "status": "stable"},
    "HYBRID_AUTOMAP": {"label": "Auto-configure from Doc", "role": "review", "category": "Knowledge", "status": "stable"},

    # --- Intelligence -----------------------------------------------------
    "HYBRID_PROFILE_V2": {"label": "Deep Profiler (dim catalog)", "role": "agent", "category": "Intelligence", "status": "stable"},
    "HYBRID_PROACTIVE_INSIGHTS": {"label": "Proactive Insights + Anomaly", "role": "user", "category": "Intelligence", "status": "stable"},
    "HYBRID_COLUMN_INTEL": {"label": "Column Intel (pre-train profiler)", "role": "agent", "category": "Intelligence", "status": "stable"},
    "HYBRID_COMPLIANCE_GATE": {"label": "Compliance & Quality Scan", "role": "user", "category": "Intelligence", "status": "stable"},
    "HYBRID_SENSE_MAKING": {"label": "Sense-Making / Decision Layer", "role": "user", "category": "Intelligence", "status": "experimental", "note": "Adds a Decision card (so-what/now-what) above answers. Default OFF."},
    "HYBRID_AUTO_MODEL": {"label": "Auto Model Selection", "role": "user", "category": "Intelligence", "status": "experimental", "note": "Pick 'Auto' in the model picker and a complexity classifier routes each question to the cheapest capable model (Fast/Balanced/Reason). Heuristic first; a cheap LLM tie-break only on ambiguous questions. Fail-soft to the org default. Default OFF."},
    "HYBRID_CODE_ENRICH": {"label": "Code Enrich (pipeline logic)", "role": "agent", "category": "Intelligence", "status": "experimental", "note": "Extra LLM cost on train."},
    "HYBRID_FORECAST": {"label": "Forecasting Tool", "role": "user", "category": "Intelligence", "status": "stable", "note": "Holt-Winters/ETS (statsmodels) + LLM narrative. No heavy dep."},
    "HYBRID_DLT_INGEST": {"label": "Robust Ingest (dlt)", "role": "agent", "category": "Core", "status": "experimental", "superseded_by": ["HYBRID_ROBUST_INGEST", "HYBRID_ONE_TABLE_MERGE"], "note": "Legacy dlt → DuckDB idempotent merge. Superseded by Robust Ingest + One-Table Merge (both ON). OFF = pandas path."},
    "HYBRID_FULL_PIPELINE": {"label": "Full Pipeline (15 stages)", "role": "agent", "category": "Core", "status": "experimental", "note": "Quality-gate + golden/answer eval + hybrid-index + brain-graph in one train. See NEWPIPE.md."},
    "HYBRID_POWERBI_USER": {"label": "Power BI Connector (User Sign-in)", "role": "user", "category": "Connectors", "status": "experimental", "note": "Adds a Power BI semantic-model connector that signs in with email+password (ROPC) — no app registration. Needs MFA off + Build permission on the datasets. Default OFF."},
    "HYBRID_CONNECTOR_AS_AGENT": {"label": "Connector → Data Agent (auto)", "role": "admin", "category": "Connectors", "status": "experimental", "note": "When an admin connects a data source, auto-create an org-shared agent (Studio) bound to it, so every member can chat it immediately. For user_required connectors (e.g. Power BI user sign-in) each member signs in with their own account. Default OFF."},
    "HYBRID_CONNECTOR_ROBUSTNESS": {"label": "Connector query robustness", "role": "agent", "category": "Connectors", "status": "experimental", "note": "Hardens the create_data → connector query path so agents answer reliably against live connectors (Power BI, Fabric): (P1) auto-fill target tables from the report's data sources when the model omits them — no wasted 'no tables matched' retry; (P2) honor rate-limit Retry-After with backoff on the DAX/query path instead of hard-failing; (P4) thread dataset/workspace IDs into generated code. Off = byte-identical to today. Default OFF."},
    "HYBRID_SCOPED_INSTRUCTIONS": {"label": "Scoped instructions (per-agent isolation)", "role": "agent", "category": "Connectors", "status": "experimental", "note": "Stops one agent's instructions bleeding into another agent in the SAME org. When ON, an instruction with NO data-source link applies ONLY to its own source(s) instead of being treated as org-global — so old CRM/crypto 'definitions' can't leak into a Power BI agent's context. Also scopes the agent's search_reports/search_data tools to the report's own data sources. An instruction can still be org-wide by setting an explicit global_status. Off = legacy (unscoped = global). Default OFF."},
    "HYBRID_PROMPT_SCOPE": {"label": "Scoped prompt visibility (per-agent membership)", "role": "agent", "category": "Governance", "status": "stable", "note": "Saved-prompt READ visibility mirrors the /agents list: an 'agent'-scoped prompt is visible only to explicit members of ALL its mentioned agents (public agents count), 'private' → owner only, 'global' → everyone; the owner always sees their own. Closes the leak where every org member saw every prompt regardless of scope. Write/manage authority unchanged. Default ON."},
    "HYBRID_CONNECTOR_JOURNEY_V2": {"label": "Connector journey v2 (confirm → consent → sync)", "role": "agent", "category": "Connectors", "status": "experimental", "note": "Revamped Power BI per-user connect flow: (1) capture the real Microsoft account email/tenant from the id_token on sign-in; (2) do NOT auto-sync — show 'Connected as <ms email>' + a consent gate + explicit 'Sync my data' button; (3) discover datasets via REPORTS + APPS (not just the datasets list) so shared-report users get their queryable data; (4) honest status — queryable vs view-only (no Build), never a hallucinated overview on 0 tables. Off = current auto-sync flow (byte-identical). Default OFF."},
    "HYBRID_PER_USER_CONNECTOR": {"label": "Per-User Connector (self-register)", "role": "admin", "category": "Connectors", "status": "experimental", "note": "Admin configures a connector template once (tenant/client, no creds). Each member registers with their own email+password → gets a PRIVATE copy with their own synced tables (not shared org-wide). Each builds their own analysis. Microsoft/source access control enforced per user. Default OFF."},
    "HYBRID_ADAPTIVE_CONNECT": {"label": "Adaptive connector sign-in (email+password, auto device-code on MFA)", "role": "admin", "category": "Connectors", "status": "experimental", "note": "One sign-in flow for per-user connectors: a member enters email+password and the backend tries ROPC (password grant) first. No MFA → connects immediately; MFA / conditional access / legacy-auth blocked → auto-falls-back to device-code sign-in. Both paths build the same private per-user clone. Default OFF."},
    "HYBRID_MS_UNIFIED_SIGNIN": {"label": "One Microsoft sign-in → Power BI + Fabric agents", "role": "admin", "category": "Connectors", "status": "experimental", "superseded_by": ["HYBRID_PER_USER_CONNECTOR"], "note": "Legacy — the joint 'Microsoft (Fabric + Power BI)' tile was removed. Power BI and Fabric are now always two separate connector cards: connect Fabric → Fabric agent, connect Power BI → Power BI agent. Flag no longer has any effect."},
    "HYBRID_SEMANTIC_SEARCH": {"label": "Hybrid Search (FTS + embeddings)", "role": "agent", "category": "Intelligence", "status": "experimental", "note": "Uses your OpenRouter key for embeddings (text-embedding-3-small). After enabling, click Rebuild search index."},

    # --- Agents & Access --------------------------------------------------
    "HYBRID_AGENT_TEMPLATES": {"label": "Agent Templates", "role": "user", "category": "Agents & Access", "status": "stable"},
    "HYBRID_FOLDER_SYNC": {"label": "Folder Sync (desktop auto-ingest)", "role": "user", "category": "Agents & Access", "status": "stable"},
    "HYBRID_AGENT_ACL": {"label": "Per-Agent Access Control", "role": "user", "category": "Agents & Access", "status": "stable"},
    "HYBRID_USER_GROUPS": {"label": "User-Owned Groups", "role": "user", "category": "Agents & Access", "status": "stable", "note": "Let any member create personal contact groups and use them as reusable share targets (My Groups)."},
    "HYBRID_AGENT_CONNECTORS": {"label": "Per-Agent Private Connectors", "role": "user", "category": "Agents & Access", "status": "stable", "note": "Let a connector be private to a user (owner_user_id) or bound to a single agent/studio (studio_id), instead of org-wide. NULL/NULL = org-wide (unchanged)."},
    "HYBRID_GROUP_ACCESS": {"label": "Group-Based Agent Access", "role": "user", "category": "Agents & Access", "status": "stable", "note": "Share an agent/studio to a GROUP (incl. AD/LDAP-synced groups) — every group member gets access and the agent auto-appears in their studios list + chat dropdown. Reuses ResourceGrant (resource_type='studio', principal_type='group'). Default OFF."},
    "HYBRID_FILE_BROWSER": {"label": "File Browser (SharePoint/OneDrive/Drive)", "role": "user", "category": "Agents & Access", "status": "stable", "note": "Browse a SharePoint/OneDrive/Google Drive connector's folders/files with YOUR own Microsoft/Google sign-in (each user sees only what their identity can read), and ingest picked files as queryable Data Agents."},
    "HYBRID_AGENT_CHANNELS": {"label": "Agent Channels", "role": "user", "category": "Agents & Access", "status": "beta", "note": "Per-agent channels (Slack/Teams/WhatsApp/AI Mailbox/MCP/Telegram) scoped to that agent's pinned data. Config in Studio → Access & Channels. Inbound routing for Slack/Teams/WhatsApp is phase 2 (Telegram routing live)."},
    "HYBRID_AGENT_REPORTS": {"label": "Scheduled Reports (per-agent)", "role": "user", "category": "Agents & Access", "status": "beta", "note": "Per-agent 'Reports' tab: schedule a prompt/dashboard to run on a cadence and email the result to subscribers, sent from the agent's own SMTP identity. UI only; gates the Studio → Reports tab."},
    "HYBRID_RICH_REPORT_EMAIL": {"label": "Rich Report Emails", "role": "agent", "category": "Agents & Access", "status": "beta", "note": "Render scheduled/automated report emails from structured results (clean table + sanitized insights + dashboard image/PDF) instead of dumping the raw agent chat. OFF = legacy raw-content email."},
    "HYBRID_ONECLICK_ARTIFACTS": {"label": "One-click Dashboard / Slides / Excel", "role": "user", "category": "Agents & Access", "status": "beta", "note": "On a report's right panel, turns the empty Dashboard/Slides/Excel states into one-click builders: 'Generate dashboard' (real page artifact), 'Generate slide deck' (python-pptx deck + previews + .pptx) from the report's existing charts, and an auto-filled Excel workbook. Reuses the chat create_artifact pipeline."},
    "HYBRID_OUTPUT_CUSTOMIZE": {"label": "Output Customize Dialogs (NotebookLM-style)", "role": "user", "category": "Agents & Access", "status": "beta", "note": "Tap a report output tile (Dashboard/Report/Slides/Excel) -> a customize modal (Format/Length/Depth/Focus/Model/Language) -> Generate passes those options into the build. OFF = tiles keep instant-generate. Default ON."},
    "HYBRID_AUTO_ARTIFACT": {"label": "Auto-build Dashboard from chat", "role": "user", "category": "Agents & Access", "status": "legacy", "superseded_by": ["HYBRID_ONECLICK_ARTIFACTS"], "note": "LEGACY — default OFF. Auto-built a dashboard in the background after any data turn with no artifact. Retired because it generated dashboards nobody asked for (token + time cost on trivial questions). Dashboards are now user-initiated only: ask in chat, or use the 'Build a dashboard' modal (HYBRID_ONECLICK_ARTIFACTS)."},
    "HYBRID_FAST_LANE": {"label": "Fast Lane (adaptive speed)", "role": "agent", "category": "Performance", "status": "experimental", "note": "Master switch for the adaptive speed layer: classify each source into a speed lane (local uploads / SQL warehouse / BI semantic) and enable the fast paths (warm session, planner collapse, BI snapshot). Default OFF = today's per-turn live behavior, byte-identical."},
    "HYBRID_WARM_SESSION": {"label": "Warm Session Cache", "role": "agent", "category": "Performance", "status": "experimental", "note": "Cache the constructed data-source client + schema per report/session so they are not rebuilt and creds re-resolved and schema re-loaded on every turn. Fail-soft (cache miss builds fresh). Needs FAST_LANE. Default OFF."},
    "HYBRID_PLANNER_COLLAPSE": {"label": "Planner Turn Collapse", "role": "agent", "category": "Performance", "status": "experimental", "note": "When the bound sources' schema is already known, skip the redundant read_resources/describe_tables turns and go straight to codegen, cutting 2-3 LLM hops. Fail-soft to the full loop. Needs FAST_LANE. Default OFF."},
    "HYBRID_BI_SNAPSHOT": {"label": "BI Snapshot (Power BI/Fabric local cache)", "role": "agent", "category": "Performance", "status": "experimental", "note": "Snapshot Power BI / Fabric tables into a local store (DuckDB) on sync and query the local copy (ms) instead of live DAX over HTTP (slow + throttled). Per-agent 'Live mode' bypasses to the source. Needs FAST_LANE. Default OFF."},
    "HYBRID_FAST_CODEGEN": {"label": "Fast Codegen Model", "role": "agent", "category": "Performance", "status": "experimental", "note": "Route the pure code-generation step (create_data) to the org's fast/small model (a Gemini flash variant) so code steps run 3-5x cheaper/faster in tokens, while planning/reflection stay on the higher-quality model. Fail-soft to the normal model. Needs FAST_LANE. Default OFF."},
    "HYBRID_WAREHOUSE_CACHE": {"label": "Warehouse Result Cache", "role": "agent", "category": "Performance", "status": "experimental", "note": "Cache the ROWS returned by a SQL query against a live warehouse source (postgres/snowflake/bigquery/…) per (data_source, normalized SQL) for a short TTL, so a repeated identical query returns instantly with zero DB round-trip. Warehouse lane only (local uploads are already fast; BI has its own snapshot lane). Read-only SELECT results only; fail-soft (miss runs live). Needs FAST_LANE. Default OFF."},
    "HYBRID_SUBPROCESS_SANDBOX": {"label": "Subprocess sandbox (isolated code exec)", "role": "agent", "category": "Performance", "status": "experimental", "note": "Runs uploaded-file analysis code in a fresh isolated process so memory is freed after every run; prevents the shared worker heap from filling. Default OFF."},
    "HYBRID_SUBPROCESS_SANDBOX_LIVE": {"label": "Subprocess sandbox — live DB clients", "role": "agent", "category": "Performance", "status": "experimental", "note": "Extends the subprocess sandbox to runs that query a live SQL database (rebuilds a plain-SQL client in the child; OAuth/BI connectors stay in-process). Requires the Subprocess sandbox flag. Default OFF."},
    "HYBRID_SANDBOX_PUSHDOWN": {"label": "SQL pushdown (memory discipline)", "role": "agent", "category": "Performance", "status": "experimental", "note": "Nudges generated code to push filters/aggregation/LIMIT to SQL and pull only needed rows, instead of loading whole tables into pandas — cuts per-run memory so more runs fit per box. Prompt-only, default OFF."},
    "HYBRID_SMART_VIZ": {"label": "Smart Viz Picker", "role": "user", "category": "Intelligence", "status": "experimental", "note": "Deterministic chart-type correction on top of the LLM's pick, using the data profile already computed (rows, columns, dtype, cardinality): high-cardinality category -> bar not pie, time + numeric -> line, two numerics -> scatter, too many categories -> top-N. Never widens the allowed viz set; fail-soft to the LLM answer. Default OFF."},
    "HYBRID_AUTO_FORMAT": {"label": "Result Auto-Format", "role": "user", "category": "Intelligence", "status": "experimental", "note": "Attach a per-column display format to result tables (thousands separators, currency, %, decimals, dates) derived from column dtype + name. Rendered as a valueFormatter; underlying values unchanged. Fail-soft. Default OFF = raw numeric/ISO."},
    "HYBRID_BRAND_PALETTE": {"label": "Brand Chart Palette", "role": "user", "category": "Intelligence", "status": "experimental", "note": "Default chart theme uses the CityAgent brand palette (accent #C2541E-led) instead of generic blue. Per-report theme overrides still win. Frontend-only. Default OFF."},
    "HYBRID_PARAM_TEMPLATES": {"label": "Parameterized Report Templates", "role": "user", "category": "Agents & Access", "status": "experimental", "note": "Saved prompts with {{name}} parameters gain a fill-in UI + a substitution/run engine that creates a report from the filled template, plus a reusable-template gallery. Builds on the existing Prompt.parameters model. API always mounted; flag shows the UI. Default OFF."},
    "HYBRID_STARTER_REFRESH": {"label": "Regenerate Starters", "role": "user", "category": "Agents & Access", "status": "experimental", "note": "A Refresh button on the agent Overview re-runs the schema-grounded conversation-starter generator on demand. OFF = starters only made at onboarding/train. Default OFF."},
    "HYBRID_BI_MODEL_INTROSPECT": {"label": "BI Model Introspection (measures + relationships)", "role": "agent", "category": "Intelligence", "status": "experimental", "note": "At connector sync, pull the BI semantic model's own measures + relationships (Power BI INFO.VIEW.*) and inject them into the DAX system prompt on every query, so the agent uses tested existing measures + the real join graph instead of inventing DAX. Fail-soft per dataset. The biggest DAX-error reducer for Power BI / Fabric. Default OFF."},
    "HYBRID_RESULT_NARRATIVE": {"label": "Per-Result Interpretation", "role": "user", "category": "Intelligence", "status": "experimental", "note": "A short inline narrative attached to each individual result (reuses compute_insights + build_sense_making), rendered beside that result's table — finer than the existing turn-level DecisionCard. Fail-soft. Default OFF."},
    "HYBRID_CROSS_SOURCE_UNIFY": {"label": "Cross-Source Unify", "role": "agent", "category": "Intelligence", "status": "experimental", "note": "At ingest, detect same-shape sibling tables (e.g. 6 monthly files with identical columns) and register a unified UNION ALL view (+ a _period column) so the agent queries across them in one shot. Records a union group + emits an instruction. Fail-soft, no migration. Default ON."},
    "HYBRID_DATA_QUALITY": {"label": "Data Quality Scan", "role": "user", "category": "Intelligence", "status": "experimental", "note": "At ingest, scan columns for quality issues (high null %, type-coercion risk, outliers, near-constant) and emit a data_quality guardrail instruction the agent reads. Pure pandas, fail-soft, no migration. Default OFF."},
    "HYBRID_VALUE_NORMALIZE": {"label": "Value Normalization (canonical)", "role": "agent", "category": "Intelligence", "status": "experimental", "note": "Resolve a canonical value for near-duplicate labels (e.g. 'daily_used__l' vs 'daily_used__l_') and record a value→canonical map so GROUP BY doesn't scatter one category across spellings. Detection only, no data rewrite. Default OFF."},
    "HYBRID_AGENT_PLAN": {"label": "Agent Task Plan", "role": "user", "category": "Agents & Access", "status": "experimental", "note": "At run start the agent writes a 3-5 item high-level task plan (a Claude-style checklist) as a transient 'plan' block. The report Progress panel then shows a numbered task list that ticks over as work proceeds, instead of only low-level tool steps. One extra small-model call per run, fail-soft. Default OFF."},
    "HYBRID_COWORK_PANEL": {"label": "Cowork Outputs Panel", "role": "user", "category": "Agents & Access", "status": "experimental", "note": "Report right-panel redesign: Create/Activity toggle, numbered Progress (the task plan + live sub-steps with auto-scroll), a Working-folders tree of file + database sources and their tables, and a Context section (Skills loaded/used + Sub-agents). Frontend-only, reuses existing activity data. Off keeps the legacy panel. Default OFF."},
    "HYBRID_SMART_UPLOAD": {"label": "Smart Upload Router", "role": "user", "category": "Agents & Access", "status": "experimental", "note": "One drop zone for ANY file. A heuristic + small-LLM ensemble classifies each upload (data / glossary / rules / Q&A / reference) and routes it to the right home — Database, Semantic, Instructions, Examples, or Knowledge — auto-applying confident low-risk files and asking you to confirm only the uncertain or answer-changing ones. Reuses existing sinks. Fail-soft. Default OFF."},
    "HYBRID_SMART_WORKBOOK": {"label": "Smart Excel Build", "role": "user", "category": "Agents & Access", "status": "experimental", "note": "Outputs 'Excel' tab becomes a smart builder: user types an intent ('pivot revenue by region × month'), an LLM converts it to a transform spec (select/rename/filter/aggregate/pivot/sort), and the result is applied in pure-Python over the existing grids — no SQL re-run. Flag OFF = today's raw workbook dump unchanged. Default OFF."},
    "HYBRID_SMART_SLIDES": {"label": "Smart Slide Deck Build", "role": "user", "category": "Agents & Access", "status": "experimental", "note": "Outputs 'Generate slide deck' becomes a smart builder: auto-prefills the prompt from the chat turn, auto-uses the agent's own bound data sources (no picker), routes the model via Auto, and asks ONE clarifying chip ONLY when there's no usable signal. Reuses create_artifact + ambiguity-gate + sense-making. Default OFF."},
    "HYBRID_SMART_DASHBOARD": {"label": "Smart Dashboard Build", "role": "user", "category": "Agents & Access", "status": "experimental", "note": "Outputs 'Generate dashboard' becomes a smart builder: auto-prefills the prompt from the chat turn, auto-uses the agent's own bound data sources (no picker), routes the model via Auto, and asks ONE clarifying chip ONLY when there's no usable signal. Reuses create_artifact + ambiguity-gate + sense-making. Default OFF."},
    "HYBRID_FOLLOWUP_FASTPATH": {"label": "Follow-up Fast Path", "role": "agent", "category": "Agents & Access", "status": "experimental", "note": "Speeds up follow-up questions in a report. When the report already researched its tables in an earlier turn (a prior read_resources / describe_tables ran), the planner is told the schema, instructions, and metadata resources are ALREADY in its context — so it skips the redundant 'let me read the instructions first' research step and goes straight to the answer. Pure prompt nudge over context that is always rebuilt, so correctness is unchanged; only a wasted plan/execute/reflect cycle is removed. Fail-soft. Default OFF."},
    "HYBRID_QUOTAS": {"label": "Per-Org Quotas", "role": "agent", "category": "Agents & Access", "status": "stable"},
    "HYBRID_DOMAIN_PACKS": {"label": "Domain Packs (Skills)", "role": "agent", "category": "Agents & Access", "status": "stable"},
    "HYBRID_PROMPTS_LIBRARY": {"label": "Prompts Library", "role": "user", "category": "Agents & Access", "status": "experimental", "note": "Reusable saved-prompt library (create / edit / delete prompts) surfaced as a 'Prompts' nav entry under Build. API is always mounted; this flag only shows/hides the nav link. Default OFF."},
    "HYBRID_USER_AVATAR": {"label": "User Avatar Upload", "role": "user", "category": "Agents & Access", "status": "experimental", "note": "Lets a user upload a profile image that displays in the nav / chat. The avatar serve route + column exist unconditionally; this flag only shows/hides the 'Edit profile' upload affordance in the nav. Default OFF."},
    "HYBRID_NOTIFICATIONS_INBOX": {"label": "Notifications Inbox", "role": "user", "category": "Agents & Access", "status": "experimental", "note": "In-app notification inbox: a bell in the nav with an unread badge + a dropdown listing recent notifications (mark-read / mark-all-read / dismiss). The API is always mounted; this flag only shows/hides the nav bell. Unrelated to outbound email. Default OFF."},
    "HYBRID_SERVICE_ACCOUNTS": {"label": "Service Accounts", "role": "user", "category": "Agents & Access", "status": "experimental", "note": "Machine/service accounts an org admin creates for headless / programmatic access. Each account holds one or more API keys (bow_ prefix, SHA-256 hashed, plaintext shown once at creation). Admin-only (manage_members). This flag gates the admin API + the Settings → Service Accounts page. Default OFF."},
    "HYBRID_CONNECTION_GRANTS": {"label": "Connection Grants (RBAC)", "role": "agent", "category": "Agents & Access", "status": "experimental", "note": "#489: an admin can grant or revoke a specific member/group access to a single connection or data source (per-principal, not all-or-nothing). Off = connection grants unsupported (pre-#489 behavior). Default OFF."},
    "HYBRID_AUTO_PUBLISH": {"label": "Auto-publish Agents", "role": "user", "category": "Agents & Access", "status": "experimental", "note": "New data agents / instructions are published immediately on create instead of staying in draft. Off = keep the draft-until-promoted flow. Default OFF."},
    "HYBRID_FILE_REFERENCES": {"label": "File References in Prompts", "role": "user", "category": "Agents & Access", "status": "experimental", "note": "#497: reference an uploaded file inside a prompt so its content is injected into the agent context. Off = no file references are read; context is unchanged. Default OFF."},
    "HYBRID_MCP_GATEWAY": {"label": "External MCP Gateway", "role": "agent", "category": "Agents & Access", "status": "experimental", "note": "#487: expose an agent's own tools out through the external MCP endpoint so other MCP clients can call them. Off = the gateway is inert. Default OFF."},
    "HYBRID_USD_QUOTA": {"label": "USD Spend Cap", "role": "agent", "category": "Agents & Access", "status": "experimental", "note": "#488: a per-org / per-user monthly spend limit in US dollars, enforced against recorded LLM cost. Off = no dollar limit is checked. Default OFF."},
    "HYBRID_STANDALONE_CONNECTORS": {"label": "Standalone Connectors", "role": "user", "category": "Agents & Access", "status": "experimental", "note": "#467: use a connector on its own (tools-only) without turning it into a full data agent. Off = connectors are always agent-wrapped, as today. Default OFF."},
    "HYBRID_TREE_LAZYLOAD": {"label": "Lazy Tree Load", "role": "user", "category": "Agents & Access", "status": "experimental", "note": "#494/430: the /agents knowledge tree loads counts and search lazily instead of eager full loads, so large agents open faster. Off = existing eager load. Default ON."},
    "HYBRID_SIDEBAR_ACTIVITY_SORT": {"label": "Sort Sidebar by Activity", "role": "user", "category": "Workspace", "status": "experimental", "note": "#479: order the reports sidebar by most-recent activity instead of creation date. Off = sort by created date, as today. Default ON."},
    "HYBRID_GLOBAL_EVALS_NODE": {"label": "Global Evals Node", "role": "review", "category": "Workspace", "status": "experimental", "note": "#478: show a global Evals node in the knowledge explorer tree. Off = node hidden. Default ON."},
    "HYBRID_LOCALIZED_FOLLOWUPS": {"label": "Localized Follow-ups", "role": "user", "category": "Workspace", "status": "experimental", "note": "#521: translate follow-up suggestions and render them direction-aware (RTL-safe). Off = follow-ups render as today. Default ON."},
    "HYBRID_WEEK_START": {"label": "Configurable Week Start", "role": "user", "category": "Workspace", "status": "experimental", "note": "430: choose the first day of the week for prompt scheduling and date grouping. Off = existing default week start. Default ON."},
    "HYBRID_PDF_HYDRATION": {"label": "PDF Export Hydration", "role": "user", "category": "Workspace", "status": "experimental", "note": "#527: hydrate report numbers and chart data into PDF exports so they aren't blank. Off = existing PDF path. Default ON."},
    "HYBRID_PACK_ROUTER": {"label": "Pack Router", "role": "agent", "category": "Agents & Access", "status": "stable"},
    "HYBRID_PACK_AUTOBIND": {"label": "Pack Auto-bind", "role": "review", "category": "Agents & Access", "status": "experimental", "note": "Adds pending rows to review on every train."},
    "HYBRID_TEACH_BOX": {"label": "Teach Box (paste→skill)", "role": "review", "category": "Agents & Access", "status": "stable"},

    # --- Ingest / Autotrain ----------------------------------------------
    "HYBRID_AUTOTRAIN": {"label": "Autotrain (file→pending knowledge)", "role": "review", "category": "Ingest", "status": "stable"},
    "HYBRID_AUTOTRAIN_QA": {"label": "Autotrain — Verified Q&A", "role": "review", "category": "Ingest", "status": "stable"},
    "HYBRID_AUTOTRAIN_PROFILE": {"label": "Autotrain — Profile", "role": "agent", "category": "Ingest", "status": "stable"},
    "HYBRID_AUTOTRAIN_ON_INDEX": {"label": "Autotrain on Connector Index", "role": "agent", "category": "Ingest", "status": "risky", "superseded_by": ["HYBRID_TRAIN_ROUTING"], "note": "Legacy — env-only, auto-trains every new table (costly/slow). Superseded by Inbox Routing + manual Train + per-studio SelfLearn."},
    "HYBRID_AUTO_QUERIES": {"label": "Auto Example Queries", "role": "review", "category": "Ingest", "status": "stable"},
    "HYBRID_AUTO_EVALS": {"label": "Auto Eval Cases", "role": "review", "category": "Ingest", "status": "stable"},
    "HYBRID_MERGE_SAME_SCHEMA": {"label": "Merge Same-Schema Uploads", "role": "user", "category": "Ingest", "status": "stable"},
    "HYBRID_SMART_HEADER": {"label": "Smart Header + Glossary", "role": "user", "category": "Ingest", "status": "stable"},
    "HYBRID_TOTAL_ROW": {"label": "Pre-Aggregated Total-Row Detection", "role": "user", "category": "Ingest", "status": "experimental", "note": "At file ingest, flag likely total/subtotal rows (e.g. site='ALL Total') so the agent excludes them and stops double-counting SUM()."},
    "HYBRID_ONE_TABLE_MERGE": {"label": "One-Table Merge (kill UNION ALL)", "role": "user", "category": "Ingest", "status": "experimental", "note": "Pipeline v1 (P1): same-schema monthly uploads stack into ONE table + _source_period column instead of N stem-keyed tables that forced UNION ALL. Fail-soft. Default OFF."},
    "HYBRID_SMART_SOURCE_NAME": {"label": "Smart Source Name (month->range)", "role": "user", "category": "Ingest", "status": "stable", "note": "When merged monthly uploads span multiple periods but the source name still says a single month (e.g. 'Apr'25'), rename the display name to the real range ('Jan-Jun'25'). Renames DataSource.name only; fail-soft. Default ON."},
    "HYBRID_LOGIC_PARSER": {"label": "Logic / Q&A Doc Parser", "role": "user", "category": "Ingest", "status": "experimental", "note": "Pipeline v1 (P2): parse a logic/Q&A doc into (question, answer, logic) triples + expected answers; route logic docs to Instructions. Feeds the Definition Registry. Default OFF."},
    "HYBRID_DEF_REGISTRY": {"label": "Definition Registry", "role": "review", "category": "Knowledge", "status": "experimental", "note": "Pipeline v1 (P3): single source of truth for business metrics (Lead/New User/Status rule) + expected answers; goldens/instructions reference a def so one fix propagates. Needs migration defreg1. Default OFF."},
    "HYBRID_VERIFIED_GOLDENS": {"label": "Verified Goldens (eval gate)", "role": "review", "category": "Knowledge", "status": "experimental", "note": "Pipeline v1 (P4+P5): logic-aware golden generation + eval gate — approve a query only when it matches the doc's expected number; mismatch/unknown -> held with a diff. Default OFF."},
    "HYBRID_QUERY_CORRECTION": {"label": "Query Correction from Instruction", "role": "user", "category": "Knowledge", "status": "experimental", "note": "Pipeline v1 (P6): a user instruction updates a definition -> regenerates every dependent golden -> re-evals. One correction fixes all SQL. Default OFF."},
    "HYBRID_AUTO_MAP_GLOSSARY": {"label": "Auto-Map Glossary File", "role": "user", "category": "Ingest", "status": "experimental", "note": "Import v2 (P2): a standalone glossary/definitions file (uploaded on its own) is parsed term->definition and auto-mapped onto existing data sources' columns (pending SemanticColumn meanings + KnowledgeDoc). Extends Smart Header beyond in-file sheets. Fail-soft, review-gated. Default OFF."},
    "HYBRID_ROBUST_INGEST": {"label": "Robust Spreadsheet Ingest", "role": "user", "category": "Ingest", "status": "experimental", "note": "Import v2 (P3): route spreadsheet uploads through the robust readers (encoding/delimiter sniff, real-header detection, banner skip, id-safe numeric, bad-row skip) + per-file ingest feedback, instead of the naive pandas read. Fail-soft fallback. Default OFF."},
    "HYBRID_PERSIST_WAREHOUSE": {"label": "Persist Uploads to Warehouse", "role": "admin", "category": "Ingest", "status": "experimental", "note": "Import v2 (P4, architectural): persist spreadsheet uploads into the per-org Postgres staging schema so data survives restarts, gets deep stats, and the unified cross-source VIEW can physically materialize -- instead of in-memory DuckDB. Default ON."},
    "HYBRID_INGEST_RECONCILE": {"label": "Ingest Reconcile (fail-loud merge)", "role": "admin", "category": "Ingest", "status": "stable", "note": "Ingest-completeness guard: the multi-file spreadsheet merge records each file's outcome (loaded|failed + rows + error) instead of silently swallowing a bad file with 'except: continue', flips a source DEGRADED on a row-count/file mismatch, feeds coverage-context to the agent (stop fabricating missing periods), and surfaces 'N of M failed' in the upload UI. Off = byte-identical to today. Default ON."},
    "HYBRID_INGEST_SELFHEAL": {"label": "Self-heal split data", "role": "user", "category": "Ingest", "status": "stable", "note": "Detect an agent's orphaned same-schema tables (files uploaded across separate sessions that never merged into its one bound table) and auto-stitch them back in. Runs on train + a 'Repair data' action. Backup + transaction-safe + idempotent; generic for any dataset partition. Default ON."},
    "HYBRID_AUTOEDA_AUTOAPPROVE": {"label": "Auto-approve first-party docs", "role": "user", "category": "Knowledge", "status": "stable", "note": "Insight/Auto-EDA docs generated from the user's own uploaded data land approved (agent-visible) instead of pending/invisible. Learned/AI-proposed memories still go through review. Default ON."},
    "HYBRID_SOURCE_SYNC_GATE": {"label": "Refuse when source has no synced data", "role": "user", "category": "reliability", "status": "stable", "note": "If the chat's bound data source(s) have NO synced/active tables, refuse to answer with a clear 'sync it first' message instead of silently answering from some other source's data. Only refuses when EVERY bound source is empty; if any has tables, proceeds normally. Off = legacy (may answer from whatever is reachable). Default ON."},
    "HYBRID_COLUMN_PROFILE": {"label": "Column Profiling (types + value stats)", "role": "user", "category": "Ingest", "status": "experimental", "note": "Master plan E3: on upload, profile each column (dtype num/date/category/text, null %, distinct count, min/max, top values) and persist. Fills the empty semantic_columns.type + gives validation/engineering/understanding real facts. Fail-soft. Default OFF."},
    "HYBRID_DATA_VALIDATION": {"label": "Data Validation Gate (garbage-in net)", "role": "review", "category": "Ingest", "status": "experimental", "note": "Master plan E4: using column profiles, loud checks — filter-value existence (typo 'Retentnion' vs 'Retention' -> flag not silent-0), row-count floor, null-spike/all-null, category near-duplicate, dup-file hash. Surfaces a <data_quality> block. Golden verifies LOGIC; this verifies DATA. Fail-soft. Default OFF."},
    "HYBRID_RATIO_METRICS": {"label": "Ratio Metrics (num ÷ den goldens)", "role": "review", "category": "Knowledge", "status": "experimental", "note": "Master plan A2+A3: parse Numerator/Denominator logic into a kind='ratio' definition (num_predicate + den_predicate + group_by), generate two COUNT queries, eval verifies BOTH counts vs ground truth -> approve rate golden. Unblocks recruitment/retention/drop-off rates (Q8/Q9/Q11). Needs migration ratiodef1. Default OFF."},
    "HYBRID_DATA_TYPING": {"label": "Data Typing (real numbers + dates)", "role": "user", "category": "Ingest", "status": "experimental", "note": "Master plan E5: before the query engine, cast number-shaped columns ('1,234' -> 1234) and date-shaped columns (strings -> real dates) using the E3 dtype, so SUM/AVG/min-max + date range/sort work correctly. Category/text/provenance untouched (protects verified-golden filters). Conservative (>=90% must parse or keep raw), fail-soft. Default OFF."},
    "HYBRID_TRAIN_ROUTING": {"label": "Inbox → Train auto-routing", "role": "user", "category": "Ingest", "status": "experimental", "note": "Upload files into a per-agent Inbox with no per-file decision. When you Train, a first stage classifies each queued file (train model, default GLM-5.2, + larger excerpt), auto-places confident files to Database/Semantic/Instructions/Examples/Knowledge, and HOLDS uncertain ones for post-train Review. Reuses the Smart Upload classifier + sinks. Default OFF."},
    "HYBRID_AUTOPILOT_V2": {"label": "Auto-pilot v2 (queue-first)", "role": "user", "category": "Ingest", "status": "experimental", "note": "Reordered studio Auto-pilot: ADD (compact connector/upload/folder) → QUEUE (prominent, instant heuristic type-guess chips + inline re-route) → TRAIN (one button, streams a segregation receipt with reconcile 'N in → M placed' + coverage 'periods materialized' lines) → RESULT lanes. Held items show why (reason/confidence/signals) with one-click resolve. Faster: heuristic-first classify skips the LLM on obvious files, parallel apply, skip-unchanged. Reuses route_inbox/classifier/train. Off keeps the legacy 3-step UI. Fail-soft. Default OFF."},
    "HYBRID_INGEST_BRAIN": {"label": "Universal Ingest Brain (F09)", "role": "user", "category": "Ingest", "status": "experimental", "note": "Deep file understanding (messy Excel/PDF/Word/image) → one org brain. Phased; Default ON."},
    "HYBRID_AUTOTRAIN_ON_UPLOAD": {"label": "Auto-train after Upload", "role": "user", "category": "Ingest", "status": "experimental", "note": "After Smart Upload sorts and stores dropped files, the studio auto-trains in one pass — no Train button. Bounded to the studio + just-uploaded files (NOT the warehouse-wide risky Autotrain on Connector Index). Off = upload only stores; train stays manual. Default ON."},
    "HYBRID_ROBOT_DOCK": {"label": "Robot CLI Dock", "role": "user", "category": "Workspace", "status": "experimental", "note": "A floating robot bottom-right of the studio opens a live CLI terminal streaming upload → classify → train stages one at a time, with model, counts, tokens, spend and readiness. Off = no dock. Default ON."},

    # --- Learning / Brain -------------------------------------------------
    "HYBRID_BRAIN_READ": {"label": "Brain Read (inject memories)", "role": "agent", "category": "Learning", "status": "stable"},
    "HYBRID_DISTILLER": {"label": "Self-Distiller (👎→pending)", "role": "review", "category": "Learning", "status": "stable"},
    "HYBRID_MEMORY_LOOP": {"label": "Memory Loop (👍→pending)", "role": "review", "category": "Learning", "status": "stable"},
    "HYBRID_QUERY_CACHE": {"label": "Reasoning Cache (proven SQL)", "role": "agent", "category": "Learning", "status": "stable"},
    "HYBRID_QUERY_LEARNING": {"label": "Live Query Learning", "role": "review", "category": "Learning", "status": "stable"},
    "HYBRID_RESULT_CACHE": {"label": "Result Cache", "role": "agent", "category": "Learning", "status": "stable", "note": "Uses Redis."},
    "HYBRID_PARQUET_RESULTS": {"label": "Parquet Result Storage", "role": "agent", "category": "Advanced", "status": "stable", "note": "ON by default. Large step results stored as compressed Parquet on disk instead of inline JSON; smaller DB, faster dashboards. Threshold: HYBRID_PARQUET_MIN_ROWS (default 2000)."},
    "HYBRID_ANSWER_CACHE": {"label": "Answer Cache (Tier-0)", "role": "agent", "category": "Learning", "status": "stable", "note": "Uses Redis."},
    "HYBRID_AUTO_TABLE_RELEVANCE": {"label": "Auto Table Relevance", "role": "agent", "category": "Advanced", "status": "beta", "note": "At connector sync, auto-classify tables (fact/dim/measure/staging/telemetry) and deactivate noise (Power BI usage-metrics, Stg_ staging, empty/measure holders) so the agent carries only business-useful tables. Manual override in Tables tab wins. Default OFF."},
    "HYBRID_CONNECTOR_AUTO_SYNC": {"label": "Connector Auto-Sync (scheduled)", "role": "agent", "category": "Advanced", "status": "beta", "note": "Scheduler sweeps connector clones with per-agent auto-sync enabled and re-runs the sync pipeline on the configured interval. Re-training is diff-gated (no LLM cost when the schema is unchanged). Default OFF."},
    "HYBRID_LEARN_FROM_DATA": {"label": "Learn From Data (sample rows)", "role": "agent", "category": "Advanced", "status": "beta", "note": "At connector learn time, sample a few real rows per table and feed example column values into the onboarding LLM so the generated description/starters/instruction are grounded in actual data, not just table names. Kills domain hallucination on FK-less sources (Power BI). PII columns never sampled. Default OFF."},
    "HYBRID_HOT_START": {"label": "Hot Start (pre-warm + headline)", "role": "agent", "category": "Advanced", "status": "beta", "note": "On agent open, pre-warm the user's Power BI model and pre-compute its headline measures into the per-user query cache, so the first question is instant (cache hit) instead of a cold 40-84s query, and the Overview can show real numbers before the user types. Per-user, PBI-only, background, throttled, fail-soft. Default OFF. See services.connector_warm."},
    "HYBRID_MOA": {"label": "Mixture-of-Agents (model)", "role": "admin", "category": "Experimental", "superseded_by": ["HYBRID_AUTO_MODEL"], "status": "experimental", "note": "ON = a \"Mixture-of-Agents\" entry appears in the model picker; selecting it runs a panel of diverse OpenRouter models + a GLM aggregator live for that report (slow, high-cost). OFF = not offered. Superseded for everyday use by Auto Model. OpenRouter-only, fail-soft."},
    "HYBRID_CODE_BANK": {"label": "Code Bank (proven snippets)", "role": "agent", "category": "Learning", "status": "stable"},
    "HYBRID_AGENT_MEMORY": {"label": "Agent Memory", "role": "review", "category": "Learning", "status": "stable"},
    "HYBRID_SHARED_MEMORY": {"label": "Shared Memory (cross-user reuse, no leak)", "role": "agent", "category": "Learning", "status": "experimental", "note": "Singularized, reusable agent knowledge. When an agent solves something (verified query, a fixed error, a how-to), it's SANITIZED (no data values) and stored ONCE per fact, keyed by SCOPE — a Power BI semantic model, a DB schema, a file, or (private) the user. Another agent/user who shares that SAME scope reuses it ('how it was done before') so the agent gets smarter over time; users who don't share the scope never see it. Personal-agent memory stays private. Off = byte-identical (nothing captured or injected). Default OFF."},
    "HYBRID_USAGE_TRUST": {"label": "Usage-Trust Table Ranking", "role": "agent", "category": "Learning", "status": "experimental", "note": "Rank tables for retrieval by REAL usage trust — a table backed by many saved/verified queries or popular dashboards outranks a one-off exploratory table (OpenAI data-agent 'dashboard-backed > exploratory'). Lifts table-selection accuracy so the agent picks the right table first-try. Off = today's semantic-only relevance. Default OFF."},
    "HYBRID_TABLE_CARD": {"label": "Unified Table Card (+memory overlay)", "role": "agent", "category": "Learning", "status": "experimental", "note": "Merge every context layer for a table — schema/usage metadata, human + AI annotations, code-enrich grain/formulas, freshness, owner, PII flags — into ONE card, then OVERLAY approved Shared-Memory corrections onto it so the agent always sees a corrected baseline (OpenAI data-agent core pattern). Off = piecemeal per-builder context. Default OFF."},
    "HYBRID_INSTITUTIONAL_KB": {"label": "Institutional Knowledge into answers", "role": "agent", "category": "Learning", "status": "experimental", "note": "Retrieve access-controlled institutional docs (metric definitions, incident notes, launch context from knowledge_doc / connected docs) and ground the planner with them so business-term questions resolve to the right metric. Scoped to org + approved docs only (KnowledgeDoc has no per-viewer ACL today — org-granularity access). Off = docs exist but never feed data answers. Default OFF."},
    "HYBRID_EVAL_CANARY": {"label": "Eval Canary Health + Drift Alert", "role": "review", "category": "Learning", "status": "experimental", "note": "Turn the nightly result-set goldens into continuous canaries: compute a per-table eval pass-rate health badge and alert on regression-vs-last-green so drift is caught before a user hits it. Off = nightly evals run but health isn't surfaced. Default OFF."},
    "HYBRID_WORKFLOWS_V2": {"label": "Workflows (save & replay an analysis)", "role": "agent", "category": "Learning", "status": "experimental", "note": "Save a finished analysis as a reusable, parameterized workflow and replay it from the composer ('Use a workflow') — the same steps run consistently for every user. Encodes context + best-practice once (OpenAI data-agent workflows: weekly reports, table validations). Off = no save/replay. Default OFF."},
    "HYBRID_OFFLINE_CONTEXT": {"label": "Daily offline context pipeline", "role": "admin", "category": "Learning", "status": "experimental", "note": "A nightly job merges every context layer (table usage, annotations, code-enrich, freshness, memory) into ONE normalized per-table document and embeds it once, so retrieval is faster and consistent instead of rebuilt per request. Off = request-time assembly (today). Default OFF."},
    "HYBRID_CODE_ENRICH_PLUS": {"label": "Codex enrichment — deeper", "role": "agent", "category": "Learning", "status": "experimental", "note": "Extends code-enrich with primary keys, downstream usage patterns (which reports/dashboards consume a table), and 'use this alternate table instead' hints when a table is stale/low-trust. Off = grain/formulas/population only. Default ON."},
    "HYBRID_GOLDEN_SQL": {"label": "Golden-SQL evals", "role": "review", "category": "Learning", "status": "experimental", "note": "Store the expected SQL alongside the expected rows for a golden, and grade on both the SQL (intent) and the result set (LLM-judged for acceptable variation) — matches OpenAI's eval pipeline. Off = result-set-only grading (today). Default OFF."},
    "HYBRID_NOTION_KB": {"label": "Notion / Slack knowledge sources", "role": "admin", "category": "Learning", "status": "experimental", "note": "Ingest Notion pages and Slack threads into the institutional knowledge base so metric definitions and incident/launch context from those tools can ground answers (feeds the Institutional Knowledge layer). Off = no Notion/Slack ingest. Default OFF."},
    "HYBRID_LEAN_TOOLS": {"label": "Lean tool catalog", "role": "admin", "category": "Core", "status": "experimental", "note": "Trim the planner's tool set — hide overlapping/duplicate tools (per docs/TOOL_AUDIT.md: retire remember_this, collapse the schema-lookup trio, dedup live-vs-MCP) so the model picks the right tool more reliably (OpenAI 'less is more'). Off = full catalog. Default OFF."},
    "HYBRID_DOC_ACL": {"label": "Per-document access control", "role": "admin", "category": "Core", "status": "experimental", "note": "Restrict institutional knowledge docs to an explicit viewer allow-list (beyond org + approved), so a sensitive doc grounds answers only for authorized users. Off = org-granularity (every approved doc visible org-wide). Default OFF."},
    "HYBRID_DOC_KNOWLEDGE": {"label": "Attached files → searchable Knowledge", "role": "agent", "category": "Core", "status": "stable", "note": "Turn any attached document (PDF, Word, PowerPoint, text, Markdown, HTML, JSON, or a reference spreadsheet) into searchable Knowledge the agent can cite — extract its text, chunk it, and index it. Runs on upload and again on train (idempotent). First-party uploads land approved. Off = attached docs stay non-searchable. Default ON."},
    "HYBRID_AUTOFILL_AGENT_OVERVIEW": {"label": "Auto-fill agent Overview on train", "role": "agent", "category": "Core", "status": "stable", "note": "When an agent finishes training, pre-fill its Overview panel if empty — pin a primary instruction (an existing high-level one, else a clean synthesized one) and seed a few conversation starters — so a fresh agent isn't blank ('No primary instruction / No conversation starters'). Only fills what's MISSING; never overrides your own choices. Off = Overview stays blank until set by hand. Default ON."},
    "HYBRID_SAFETY_EVALS": {"label": "Safety & Reliability Evals", "role": "review", "category": "Learning", "status": "experimental", "note": "Beyond accuracy, run LLM-as-judge binary checks on answers/changes: SECURITY (no secret/credential/PII leak), GOVERNANCE (refuses destructive SQL/DDL), BOUNDARIES (agent stayed inside its own data scope — verifies the Shared-Memory isolation), ROUTING (right tool picked). Fail → held with reason. Runs on train + on demand. Dash-style AgentAsJudge. Default OFF."},

    # --- BI Uplift (analyst-grade dashboards; the 'bi learning' framework set) --
    "HYBRID_CHART_GUARDRAIL": {"label": "Chart-selection guardrail", "role": "agent", "category": "Core", "status": "experimental", "note": "Enforce the right chart for the message: compare→bar, over-time→line, part-to-whole (≤5 cats)→pie/donut, correlation→scatter, ranking→horizontal bar, spread→histogram. Post-render lint caps series, requires axis titles, one accent colour, and colour+text labels (never colour-only). Kills kitchen-sink dual-axis charts. Off = the model picks freely. Default OFF."},
    "HYBRID_INSIGHT_ENGINE": {"label": "Insight engine (Data→Insight→Decision)", "role": "agent", "category": "Core", "status": "experimental", "note": "After an answer, sweep the result for the dominant signal (trend / outlier / seasonality / relationship — computed, not guessed), then have the model wrap it as a Context→Conflict→Resolution decision and, on any drop, enumerate candidate drivers and check each against the data (facts before conclusions). Every output ends in a recommended action, not just a number. Off = raw answer only. Default OFF."},
    "HYBRID_KPI_LAYER": {"label": "KPI intelligence (leading/lagging + thresholds)", "role": "agent", "category": "Advanced", "status": "experimental", "note": "Treat KPIs as governed objects per agent: prefer outcome ratios over activity counts, model leading→lagging dependency chains so an upstream breach alerts BEFORE revenue moves, and attach target/owner/action-on-breach. Off = KPIs are just free-form metrics. Default OFF."},
    "HYBRID_DASHBOARD_COMPOSER": {"label": "Dashboard composer (hero + F-pattern)", "role": "agent", "category": "Advanced", "status": "experimental", "note": "When building a page artifact, promote one hero metric (biggest deviation) top-left, mute supporting KPIs, cascade charts along the reading path, hold to one accent colour, and run a 5-second QA gate before publish — instead of dumping the top-N visuals. Off = today's top-N selection. Default OFF."},
    "HYBRID_DATA_PREP_GATE": {"label": "Data-prep gate (Fill / Investigate / Remove)", "role": "agent", "category": "Core", "status": "experimental", "note": "At ingest, classify missing data and act: FILL non-critical dimensions (impute), REMOVE rows missing a critical measure (revenue/qty/id), and FLAG missing-value spikes for investigation — then show a data-quality banner so a dashboard can't silently mislead. Off = today's ingest. Default OFF."},
    "HYBRID_AUTO_EDA": {"label": "Per-agent Auto-EDA on the agent screen", "role": "agent", "category": "Core", "status": "experimental", "note": "On train, profile each agent's data (row/column counts, category shares, time range + peak, top-N ranking, distribution + outliers — all computed) and have the model narrate a few insights plus suggested first questions. Saved PER AGENT and shown only on that agent's Overview (not the workspace). Refreshable on demand. Off = agents don't auto-profile. Default OFF."},
    "HYBRID_ADV_METHODS": {"label": "Advanced methods (LLM-driven ML + mining)", "role": "agent", "category": "Advanced", "status": "experimental", "note": "Live analytics tools: market-basket (apriori → cross-sell bundles with lift), statistical rigour (correlation + significance, auto 'correlation ≠ causation' caveat), and LLM-driven prediction (churn risk / forecast / segmentation) where SQL computes the aggregates and the model reasons over them — labelled 'AI estimate', never a trained model. Off = descriptive only. Default OFF."},
    "HYBRID_READONLY_ENFORCE": {"label": "Structural Read-Only Enforcement", "role": "agent", "category": "Core", "status": "experimental", "note": "Enforce read-only at the CONNECTION/engine level (not just a prompt or SQL-string check) so a prompt-injection can't DROP/DELETE/ALTER source data. Writes allowed only on the agent's own staging schema. Off = today's string-based guard. Default OFF."},
    "HYBRID_ASSET_MATERIALIZE": {"label": "Materialize Hot Metrics (reusable assets)", "role": "agent", "category": "Advanced", "status": "experimental", "note": "When a Shared-Memory query template is reused enough (verified_count >= threshold), offer to MATERIALIZE it as a persistent computed asset (a view/table) so the hot metric is computed once and served instantly instead of re-running a heavy query every time. Builds on Engineer Assets. Default OFF."},
    "HYBRID_GOTCHA_MEMORY": {"label": "Data Gotchas → Global Memory", "role": "review", "category": "Learning", "status": "experimental", "note": "Route data-quality gotchas found at ingest/profile (wrong type, total/subtotal rows, near-duplicate categories) into the GLOBAL tier of Shared Memory so EVERY agent avoids the same trap (don't SUM total rows, cast this column first). Reuses column profiles + the global memory tier. Needs Shared Memory ON. Default OFF."},
    "HYBRID_SKILL_AUTOGROW": {"label": "Skill Auto-grow", "role": "review", "category": "Learning", "status": "risky", "note": "RISK — leave OFF. Depends on the Skills sandbox path (livelock risk). Env-only knob."},
    "HYBRID_EVAL_HARNESS": {"label": "Eval Harness (result goldens)", "role": "user", "category": "Learning", "status": "stable"},
    "HYBRID_BITEMPORAL": {"label": "Bi-temporal Facts", "role": "user", "category": "Learning", "status": "experimental", "note": "Changes how facts read (time-filtered)."},

    # --- Advanced ---------------------------------------------------------
    "HYBRID_SUBAGENTS": {"label": "Subagent Fan-out", "role": "agent", "category": "Advanced", "status": "risky", "note": "RISK — leave OFF for stability (STABLE config = SUBAGENTS=0). N× token cost, budget & concurrency capped. Env-only knob."},
    "HYBRID_RECURSIVE": {"label": "Recursive Verify", "role": "agent", "category": "Advanced", "status": "risky", "note": "RISK — leave OFF. No-op unless Subagents is also on (which is itself held OFF). Env-only knob."},
    "HYBRID_WORKFLOWS": {"label": "Workflow Runner", "role": "user", "category": "Advanced", "status": "stable"},
    "HYBRID_SKILLS": {"label": "Skills (sandbox exec)", "role": "agent", "category": "Advanced", "status": "risky", "note": "RISK — leave OFF. Can livelock the agent loop; STABLE config = SKILLS=0. Use Domain Packs instead. Env-only knob."},
    "HYBRID_SKILL_OPTIMIZE": {"label": "Skill Optimizer", "role": "user", "category": "Advanced", "status": "risky", "note": "RISK — leave OFF. Skills-path dependent (livelock risk). Env-only knob."},
    "HYBRID_CONTEXT_COMPACT": {"label": "Context Compaction", "role": "agent", "category": "Advanced", "status": "experimental"},
    "HYBRID_CONTEXT_COMPACT_LLM": {"label": "Context Compaction — LLM", "role": "agent", "category": "Advanced", "status": "experimental", "note": "Allows one LLM summarize per run (extra cost)."},
    "HYBRID_AMBIGUITY_GATE": {"label": "Ambiguity Gate (clarify first)", "role": "user", "category": "Advanced", "status": "experimental"},
    "HYBRID_JOIN_GRAPH": {"label": "Join Graph context", "role": "agent", "category": "Advanced", "status": "stable"},
    "HYBRID_BRAIN_GRAPH": {"label": "Brain Graph (entity/correlation)", "role": "agent", "category": "Advanced", "status": "experimental", "note": "Empty until edges are mined."},
    "HYBRID_FEDERATION": {"label": "DuckDB Federation", "role": "agent", "category": "Advanced", "status": "needs_dep", "note": "Needs S3/MinIO (FEDERATION_S3_*) — no-op without it."},

    # --- Daemons (background; read at boot → toggle needs restart) ---------
    "HYBRID_INSIGHT_DAEMON": {"label": "Insight Daemon", "role": "agent", "category": "Daemons", "status": "daemon", "note": "Applies after a container restart."},
    "HYBRID_SKILL_OPTIMIZE_DAEMON": {"label": "Skill Optimizer Daemon", "role": "agent", "category": "Daemons", "status": "risky", "note": "RISK — leave OFF. Skills-path dependent (livelock risk). Env-only daemon, applies after a container restart."},
    "EVAL_SCHEDULE_ENABLED": {"label": "Eval Schedule Daemon", "role": "agent", "category": "Daemons", "status": "daemon", "note": "Applies after a container restart."},
    "JOIN_MINE_ENABLED": {"label": "Join Mining Daemon", "role": "agent", "category": "Daemons", "status": "daemon", "note": "Applies after a container restart."},
    "STUDIO_LEARN_DAEMON_ENABLED": {"label": "Studio Learn Daemon", "role": "agent", "category": "Daemons", "status": "daemon", "superseded_by": ["per-studio SelfLearn"], "note": "Legacy — env-only always-running daemon (applies after restart). Superseded by per-studio SelfLearn (on-demand)."},
}

# Flags hidden from the Feature-Flags UI (and rejected by the PUT route). These
# are KNOWN-UNSTABLE features that livelock the agent loop — we don't want anyone
# enabling them from the UI. The flag code still exists and defaults OFF; this
# only removes the toggle. To re-expose after a redesign, drop the name here.
#   - HYBRID_SKILLS    : sandbox skill exec — livelocks; use Domain Packs instead.
#   - HYBRID_SUBAGENTS : subagent fan-out — instability source (livelocks).
#   - HYBRID_RECURSIVE : no-op unless Subagents is on, so hide it with them.
#   - HYBRID_SKILL_AUTOGROW / SKILL_OPTIMIZE / SKILL_OPTIMIZE_DAEMON : the whole
#       skill self-improvement family dead-ends on HYBRID_SKILLS (authoring is
#       hard-gated on it, optimization needs skill rows that can't exist) — retired
#       with the skill subsystem. Use Domain Packs instead.
# NOTE: HYBRID_CONTEXT_COMPACT_LLM is NO LONGER hidden — the LLM-summarize path is
# now implemented (maybe_compress + async wiring in agent_v2), so the toggle works.
HIDDEN_FLAGS: set[str] = {
    "HYBRID_SKILLS",
    "HYBRID_SUBAGENTS",
    "HYBRID_RECURSIVE",
    "HYBRID_SKILL_AUTOGROW",
    "HYBRID_SKILL_OPTIMIZE",
    "HYBRID_SKILL_OPTIMIZE_DAEMON",
}

# Stable, browser-facing order of the UI sections.
FLAG_CATEGORIES: list[str] = [
    "Core", "Knowledge", "Intelligence", "Agents & Access",
    "Ingest", "Learning", "Advanced", "Daemons",
]


async def load_overrides_from_db(db) -> int:
    """Scan organization_settings rows and apply their hybrid overrides.

    Reads each row's `config['hybrid_overrides']` (a dict of {ENV_NAME: bool})
    into the PER-ORG map `_OVERRIDES_BY_ORG[organization_id]` (tenant isolation,
    ISSUE #2). Each recognised key is ALSO folded into the merged-global
    `_OVERRIDES` fallback (used when no org context is bound); if two orgs set
    the SAME key to DIFFERENT values a loud WARNING is logged naming both the
    losing and winning value rather than silently letting the last org win.
    Only keys present in UPGRADE_FLAGS are honoured (ignores stale/unknown keys).
    Returns the number of override keys loaded. Never raises into the boot path.
    """
    loaded = 0
    # Track which org last wrote each merged-global key so a cross-org conflict
    # can be reported with the specific orgs involved.
    _global_source: dict[str, str] = {}
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
            org_id = str(getattr(row, "organization_id", "") or "")
            org_map = _OVERRIDES_BY_ORG.setdefault(org_id, {}) if org_id else None
            for env_name, value in overrides.items():
                if env_name in UPGRADE_FLAGS and value is not None:
                    b = bool(value)
                    if org_map is not None:
                        org_map[env_name] = b
                    # Merged-global fallback + loud cross-org conflict guard.
                    if env_name in _OVERRIDES and _OVERRIDES[env_name] != b:
                        logger.warning(
                            "hybrid flag override CONFLICT across orgs for %s: "
                            "org %s=%s overrides org %s=%s in the merged-global "
                            "fallback; per-org resolution (set_current_org) is "
                            "unaffected. Bind org context per request to avoid bleed.",
                            env_name, org_id or "?", b,
                            _global_source.get(env_name, "?"), _OVERRIDES[env_name],
                        )
                    _OVERRIDES[env_name] = b
                    _global_source[env_name] = org_id or "?"
                    loaded += 1
    except Exception:
        # Never break boot over a malformed override row.
        return loaded
    return loaded


class HybridFlags:
    """Lazily-read flag registry. Read at access so env changes (tests) apply."""

    # --- Per-agent access control + channels ---------------------------------
    @property
    def AGENT_ACL(self) -> bool:
        # Enforce StudioMember / share_scope at chat time (per-agent access)
        # and honour per-agent model override (Studio.config.model_id).
        return _bool("HYBRID_AGENT_ACL", True)

    @property
    def USER_GROUPS(self) -> bool:
        # User-owned contact groups: a normal (non-admin) member can create
        # their OWN groups (owner_user_id set), add org members, and use them
        # as reusable share targets. Org/admin/LDAP groups (owner_user_id NULL)
        # are unaffected. Gates the /api/me/groups* + /api/me/contacts router.
        # Default OFF.
        return _bool("HYBRID_USER_GROUPS", True)

    @property
    def AGENT_CONNECTORS(self) -> bool:
        # Per-agent PRIVATE connectors: a connector can be scoped private to a
        # user (owner_user_id set) or bound to a single agent/studio (studio_id
        # set), instead of org-wide. Org-wide connectors (owner_user_id NULL +
        # studio_id NULL) are unaffected. Default OFF.
        return _bool("HYBRID_AGENT_CONNECTORS", True)

    @property
    def GROUP_ACCESS(self) -> bool:
        # Group-based agent/studio access: share a studio to a GROUP via
        # ResourceGrant(resource_type='studio', principal_type='group'). Every
        # member of the granted group (incl. AD/LDAP-synced groups) resolves to
        # viewer/editor and the studio auto-appears in their list + chat
        # dropdown. Off => no group resolution (owner/member/org only). Default OFF.
        return _bool("HYBRID_GROUP_ACCESS", True)

    @property
    def AGENT_CHANNELS(self) -> bool:
        # Per-agent external channels (Telegram bot bound to one Studio,
        # with member-only audience + verification). Default OFF.
        return _bool("HYBRID_AGENT_CHANNELS", True)

    @property
    def PROMPT_SCOPE(self) -> bool:
        # Scope saved-prompt READ visibility to agent membership (mirrors the
        # /agents list). ON: an 'agent'-scoped prompt is visible only to explicit
        # members of ALL its mentioned agents (public agents count); 'private' →
        # owner only; 'global' → everyone; the owner always sees their own. OFF =
        # legacy (every org member sees every prompt — the pre-existing leak).
        # Write/manage authority is unchanged. Default ON (closes the leak).
        return _bool("HYBRID_PROMPT_SCOPE", True)

    @property
    def AGENT_REPORTS(self) -> bool:
        # Per-agent "Reports" tab: schedule a prompt/dashboard to run on a
        # cadence and email the result to subscribers from the agent's own SMTP
        # identity. UI-gating only (Studio → Reports tab + scheduled-report
        # CRUD routes). Default OFF.
        return _bool("HYBRID_AGENT_REPORTS", True)

    @property
    def RICH_REPORT_EMAIL(self) -> bool:
        # Render scheduled/automated report emails from STRUCTURED results
        # (clean table + sanitized insights + dashboard image/PDF) via the
        # universal delivery layer, instead of dumping the raw agent chat
        # content. OFF = legacy raw-content email (byte-identical old path).
        # Default OFF.
        return _bool("HYBRID_RICH_REPORT_EMAIL", True)

    @property
    def FILE_BROWSER(self) -> bool:
        # Per-user file browser for the existing SharePoint/OneDrive/Google
        # Drive connectors: navigate folders/files using THIS user's resolved
        # per-user credentials (so the source's own ACLs isolate each user),
        # then ingest picked files as queryable Data Agents. Gates the
        # /api/connections/{id}/files router only; no agent-loop effect.
        # Default OFF.
        return _bool("HYBRID_FILE_BROWSER", True)

    @property
    def ONECLICK_ARTIFACTS(self) -> bool:
        # One-click builders on a report's right panel (Dashboard / Slides /
        # Excel): build a REAL page or slides artifact from the report's existing
        # visualizations (reusing the chat create_artifact pipeline) and
        # auto-fill the Excel workbook — instead of dead "No X yet" empty states.
        # Gates POST /api/reports/{id}/{dashboard,slides}/generate + the FE
        # buttons only; no agent-loop effect. Default OFF.
        return _bool("HYBRID_ONECLICK_ARTIFACTS", True)

    @property
    def OUTPUT_CUSTOMIZE(self) -> bool:
        # NotebookLM-style customize dialog on the report output tiles
        # (Dashboard/Report/Slides/Excel): tap a tile -> a modal with
        # Format/Length/Depth/Focus/Model/Language -> Generate passes those
        # options into the generate endpoint. Flag OFF = tiles keep today's
        # instant-generate/chat-prompt handlers. Default ON.
        return _bool("HYBRID_OUTPUT_CUSTOMIZE", True)

    @property
    def AUTO_ARTIFACT(self) -> bool:
        # Auto-build a dashboard (page artifact) in the BACKGROUND after a
        # successful chat turn that produced a dataset (create_data → ≥1
        # visualization/step) but made NO artifact — so the Outputs panel isn't
        # empty. Reuses the one-click create_artifact pipeline
        # (report_slides._generate_artifact, mode='page'). Idempotent (skips when
        # the report already has any artifact) + fail-soft (never affects the
        # chat response). No agent-loop effect. LEGACY — default OFF: dashboards
        # are user-initiated only (chat ask or the "Build a dashboard" modal),
        # never auto-generated. Superseded by HYBRID_ONECLICK_ARTIFACTS.
        return _bool("HYBRID_AUTO_ARTIFACT", False)

    @property
    def FAST_LANE(self) -> bool:
        # Master switch for the adaptive speed layer. When ON, sources are
        # classified into speed lanes (local / warehouse / bi) and the fast
        # paths below (warm session, planner collapse, BI snapshot) may engage.
        # Default OFF = byte-identical to today's per-turn live behavior.
        return _bool("HYBRID_FAST_LANE", False)

    @property
    def WARM_SESSION(self) -> bool:
        # Cache the constructed data-source client + schema per report/session so
        # they are not rebuilt (and creds re-resolved / schema re-loaded) on every
        # turn. Fail-soft (cache miss → build fresh, exactly as today). Gated by
        # FAST_LANE too. Default OFF.
        return _bool("HYBRID_WARM_SESSION", False)

    @property
    def PLANNER_COLLAPSE(self) -> bool:
        # When the bound sources' schema is already known/cached, let the planner
        # skip the redundant read_resources/describe_tables turns and go straight
        # to codegen — cutting 2-3 LLM hops. Fail-soft: any doubt → run the full
        # loop. Gated by FAST_LANE. Default OFF.
        return _bool("HYBRID_PLANNER_COLLAPSE", False)

    @property
    def BI_SNAPSHOT(self) -> bool:
        # Snapshot Power BI / Fabric tables into a local store on sync and query
        # the local copy (ms) instead of live DAX over HTTP (slow + throttled). A
        # per-agent "Live mode" bypasses to the source. Gated by FAST_LANE.
        # Default OFF.
        return _bool("HYBRID_BI_SNAPSHOT", False)

    @property
    def FAST_CODEGEN(self) -> bool:
        # Route the PURE code-generation step (create_data's Coder) to the org's
        # fast/small model (a Gemini flash variant) instead of the reasoning model,
        # so code steps run 3-5x cheaper/faster in tokens. Planning/reflection stay
        # on the normal model. Gated by FAST_LANE too. Fail-soft (any doubt → normal
        # model). Default OFF = byte-identical to today.
        return _bool("HYBRID_FAST_CODEGEN", False)

    @property
    def WAREHOUSE_CACHE(self) -> bool:
        # Read-through cache of the ROWS returned by a warehouse SQL query, keyed
        # by (data_source, normalized SQL) with a short TTL. A repeated identical
        # query returns instantly with zero DB round-trip. Warehouse lane only
        # (local uploads already fast; BI uses the snapshot lane). Read-only
        # SELECT results only; fail-soft (miss runs live). Gated by FAST_LANE.
        # Default OFF = byte-identical to today.
        return _bool("HYBRID_WAREHOUSE_CACHE", False)

    @property
    def SUBPROCESS_SANDBOX(self) -> bool:
        # Runs ad-hoc uploaded-file analysis code in a fresh isolated one-shot
        # child process instead of in-process, so its memory is freed after
        # every run instead of accumulating in the shared worker heap.
        # Fail-soft (any doubt → in-process, today's behavior). Default OFF.
        return _bool("HYBRID_SUBPROCESS_SANDBOX", False)

    @property
    def SUBPROCESS_SANDBOX_LIVE(self) -> bool:
        # Phase 4: also offload LIVE-DB-client runs (not just uploaded files) to
        # the isolated subprocess sandbox — the child rebuilds a plain-SQL client
        # from a serialized spec (allowlisted connector types only; OAuth/BI stay
        # in-process). Requires SUBPROCESS_SANDBOX too. Fail-soft (rebuild failure
        # → in-process). Default OFF.
        return _bool("HYBRID_SUBPROCESS_SANDBOX_LIVE", False)

    @property
    def SANDBOX_PUSHDOWN(self) -> bool:
        # Phase 5: nudge the code generator to push filtering/aggregation/LIMIT
        # down to SQL and pull only the rows needed, instead of SELECT * then
        # filtering whole tables in pandas — cuts per-run memory so more runs fit
        # per box. Prompt-only, respects the "return granular rows" exception.
        # Default OFF (byte-identical prompt when off).
        return _bool("HYBRID_SANDBOX_PUSHDOWN", False)

    # --- Phase 4 (Julius-quality polish) — all default OFF ---
    @property
    def SMART_VIZ(self) -> bool:
        # Deterministic viz-type override on top of the LLM's pick. Uses the data
        # profile already computed (row_count, column_count, per-column dtype +
        # cardinality) to correct obvious mismatches: high-cardinality category ->
        # bar not pie, time + numeric -> line, two numerics -> scatter, too many
        # categories -> top-N bar/table. Never widens the allowed set; fail-soft to
        # the LLM answer. Default OFF = today's LLM-only choice.
        return _bool("HYBRID_SMART_VIZ", False)

    @property
    def AUTO_FORMAT(self) -> bool:
        # Attach a per-column display format (thousands separators, currency, %,
        # decimals, dates) to result tables, derived from the column dtype + name
        # heuristics that are already available at serialization time. Frontend
        # renders it as a valueFormatter; raw values are unchanged. Fail-soft.
        # Default OFF = raw numeric/ISO rendering.
        return _bool("HYBRID_AUTO_FORMAT", False)

    @property
    def BRAND_PALETTE(self) -> bool:
        # Make the default chart theme use the CityAgent brand palette (accent
        # #C2541E-led) instead of the generic blue-led default. Per-report theme
        # overrides still win. Frontend-only, fail-soft. Default OFF.
        return _bool("HYBRID_BRAND_PALETTE", False)

    @property
    def PARAM_TEMPLATES(self) -> bool:
        # Parameterized report templates: a saved Prompt with {{name}} parameters
        # (already in the Prompt model/schema) gains a param UI + a substitution/run
        # engine that fills the variables and creates a report from the result. A
        # template gallery surfaces reusable prompts. API always mounted; flag shows
        # the UI + enables the run engine. Default OFF.
        return _bool("HYBRID_PARAM_TEMPLATES", False)

    @property
    def STARTER_REFRESH(self) -> bool:
        # Allow on-demand regeneration of an agent's data-driven conversation
        # starters (re-runs the schema-grounded generator) via a Refresh button on
        # the agent Overview. OFF = starters only generated at onboarding/train.
        # Default OFF.
        return _bool("HYBRID_STARTER_REFRESH", False)

    @property
    def BI_MODEL_INTROSPECT(self) -> bool:
        # At connector sync, pull the BI semantic model's own measures +
        # relationships (Power BI: EVALUATE INFO.VIEW.MEASURES()/RELATIONSHIPS())
        # and persist them, then re-install on every client build so the DAX
        # system prompt carries the real tested measures + join graph. The agent
        # uses existing measures instead of inventing DAX -> the biggest DAX-error
        # reducer. Fail-soft per dataset (a dataset that rejects INFO.VIEW is
        # skipped). Default OFF = today's name+type-only grounding.
        return _bool("HYBRID_BI_MODEL_INTROSPECT", False)

    @property
    def RESULT_NARRATIVE(self) -> bool:
        # Per-result inline interpretation: a short deterministic-then-LLM narrative
        # attached to each create_data result (reuses compute_insights +
        # build_sense_making), rendered beside that result's table — finer-grained
        # than the existing turn-level DecisionCard. Fail-soft. Default OFF.
        return _bool("HYBRID_RESULT_NARRATIVE", False)

    @property
    def CROSS_SOURCE_UNIFY(self) -> bool:
        # At ingest, detect same-shape sibling tables (e.g. 6 monthly files with
        # identical columns) and register a unified logical view (UNION ALL +
        # a _period column) so the agent can query across them in one shot,
        # instead of UNIONing by hand. Records a union group + emits an
        # instruction. Fail-soft, no migration. Default OFF.
        return _bool("HYBRID_CROSS_SOURCE_UNIFY", True)

    @property
    def DATA_QUALITY(self) -> bool:
        # At ingest, scan columns for quality issues (high null %, type-coercion
        # risk, outliers, constant/near-constant) and emit a data_quality
        # guardrail instruction the agent reads. Pure pandas, fail-soft,
        # no migration. Default OFF.
        return _bool("HYBRID_DATA_QUALITY", False)

    @property
    def VALUE_NORMALIZE(self) -> bool:
        # Extend deep-profile variant detection to resolve a CANONICAL value for
        # near-duplicate labels (e.g. 'daily_used__l' vs 'daily_used__l_') and
        # record a value→canonical map so GROUP BY doesn't scatter one real
        # category across spellings. Detection only (no data rewrite). Default OFF.
        return _bool("HYBRID_VALUE_NORMALIZE", False)

    @property
    def AGENT_PLAN(self) -> bool:
        # At the start of a run the planner emits a 3-5 item high-level task PLAN
        # (a Claude-style TODO list) as a transient completion block
        # (source_type='plan'). Lets the right panel show a numbered checklist
        # whose items tick over as execution proceeds, instead of only low-level
        # tool steps. One extra small-model call per run, fail-soft. Default OFF.
        return _bool("HYBRID_AGENT_PLAN", False)

    @property
    def COWORK_PANEL(self) -> bool:
        # Report right-panel redesign (Cowork look): a Create/Activity toggle,
        # numbered Progress (the AGENT_PLAN list with live sub-steps + auto-scroll),
        # a Working-folders tree (file + database sources with their tables), and a
        # Context section (Skills loaded/used + Sub-agents). FE-only; reuses existing
        # activity fields. Off => the legacy stacked panel. Default OFF.
        return _bool("HYBRID_COWORK_PANEL", False)

    @property
    def SMART_UPLOAD(self) -> bool:
        # Smart Upload Router: one drop zone for ANY file (data / glossary / rules
        # / Q&A / reference doc). A heuristic + small-LLM ensemble classifies each
        # file and routes it to the right home — Database (data source), Semantic
        # (column meanings), Instructions, Examples, or Knowledge (RAG) — at the
        # highest confidence it can, asking the user to confirm ONLY when uncertain
        # or answer-changing. Reuses existing sinks (data_source_from_file,
        # doc_extractor, teach engine, docs_index). Fail-soft. Default OFF.
        return _bool("HYBRID_SMART_UPLOAD", False)

    @property
    def AUTOPILOT_V2(self) -> bool:
        # Auto-pilot v2 panel: reordered studio home (ADD -> QUEUE -> TRAIN ->
        # RESULT). Compact add row (connector/upload/folder), a prominent queue
        # with instant heuristic type-guess chips + inline re-route, a one-button
        # train that streams a structured SEGREGATION RECEIPT (per-file dest +
        # counts) with a RECONCILE line (files-in vs placed, never silent) and a
        # COVERAGE line (distinct _source_period vs uploads), held-lock detail
        # (reason/confidence/signals + one-click resolve), and faster training
        # (heuristic-first classify skips the LLM on obvious files, parallel
        # apply, skip-unchanged). FE reuses the existing autopilot methods; BE
        # reuses route_inbox/classifier/train. Off keeps the legacy 3-step UI.
        # Fail-soft. Default OFF.
        return _bool("HYBRID_AUTOPILOT_V2", False)

    @property
    def TRAIN_ROUTING(self) -> bool:
        # Inbox -> Train auto-routing: uploads can just STASH into a per-studio
        # inbox (no per-file decision). When the studio is trained, a new first
        # stage (route_inbox) classifies each queued file with the train model
        # (default GLM-5.2) + a larger excerpt, AUTO-PLACES confident files via
        # the Smart Upload sinks and HOLDS the uncertain/answer-changing ones for
        # post-train Review. Reuses the Smart Upload classifier + apply. OFF.
        return _bool("HYBRID_TRAIN_ROUTING", False)

    @property
    def SMART_SLIDES(self) -> bool:
        # Smart Slide Deck Build (Outputs → "Generate slide deck"). Auto-prefills
        # the prompt from the chat turn, auto-resolves the agent's OWN bound data
        # sources (no picker). Flag OFF → the existing one-click builder is
        # unchanged. Default OFF.
        return _bool("HYBRID_SMART_SLIDES", False)

    @property
    def SMART_DASHBOARD(self) -> bool:
        # Smart Dashboard Build (Outputs → "Generate dashboard"). Auto-prefills the
        # prompt from the chat turn, auto-resolves the agent's OWN bound data
        # sources (no picker), routes the model via Auto, and asks ONE clarifying
        # chip ONLY when there is no usable signal (cold open + empty prompt).
        # Reuses report_slides._generate_artifact (build), the ambiguity gate
        # (clarify), and sense-making (Decision card). Flag OFF → the existing
        # one-click builder is unchanged. Default OFF.
        return _bool("HYBRID_SMART_DASHBOARD", False)

    # --- Slice 1: foundation -------------------------------------------------
    @property
    def DUAL_SCHEMA(self) -> bool:
        # Phase 2: DB-level read-only engine + analytics/staging schemas.
        return _bool("HYBRID_DUAL_SCHEMA", True)

    @property
    def ENGINEER_ASSETS(self) -> bool:
        # Phase 3: build_data_asset tool (reusable analytics.* views).
        return _bool("HYBRID_ENGINEER_ASSETS", True)

    # --- Autotrain: dash-style "upload a file -> train -> answer" ------------
    @property
    def AUTOTRAIN(self) -> bool:
        # Ingest a flat file (or connector table) into `staging`, profile it,
        # and auto-propose PENDING knowledge (semantic/metrics/verified-Q&A).
        # Source-agnostic, approval-only, vectorless. Default OFF.
        return _bool("HYBRID_AUTOTRAIN", True)

    @property
    def AUTOTRAIN_QA(self) -> bool:
        # Sub-flag: generate+execute+keep verified Q&A during autotrain.
        return _bool("HYBRID_AUTOTRAIN_QA", True)

    @property
    def AUTOTRAIN_PROFILE(self) -> bool:
        # Sub-flag: write profile_v2 JSONB onto datasource_tables.metadata_json.
        return _bool("HYBRID_AUTOTRAIN_PROFILE", True)

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
        return _bool("HYBRID_WORKFLOWS", True)

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
        return _bool("HYBRID_CONTEXT_COMPACT", True)

    @property
    def CONTEXT_COMPACT_LLM(self) -> bool:
        # Sub-flag: allow ONE LLM summarization of dropped/old text per agent run
        # (COMPRESS). Off -> deterministic head-truncate only (no LLM cost).
        return _bool("HYBRID_CONTEXT_COMPACT_LLM", True)

    # --- Bi-temporal facts (Zep/Graphiti: valid_at/invalid_at/superseded_by) --
    @property
    def BITEMPORAL(self) -> bool:
        # Evolving facts (metrics, semantic, memory) get a timeline instead of
        # being overwritten: reads return only currently-valid rows; supersede on
        # re-approve; optional as-of time-travel. Default OFF (reads unfiltered).
        return _bool("HYBRID_BITEMPORAL", True)

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
        return _bool("HYBRID_AGENT_MEMORY", True)

    @property
    def SHARED_MEMORY(self) -> bool:
        # Singularized cross-user learning store (agent_knowledge). Capture a
        # SANITIZED, deduped fact per solved task (verified query / fixed error /
        # how-to), scoped by a resolver (PBI model / DB schema / file / private
        # user), and inject it back for agents sharing that scope so the agent
        # reuses "how it was done before". Access = intersection with the
        # viewer's own scopes; private tier never crosses users. Off = nothing
        # captured or injected (byte-identical). Default OFF.
        return _bool("HYBRID_SHARED_MEMORY", False)

    @property
    def USAGE_TRUST(self) -> bool:
        # P2 — rank table retrieval by REAL usage trust (query-frequency +
        # dashboard-backed > one-off exploratory), OpenAI-data-agent style.
        # Off = today's semantic-only relevance. Default OFF.
        return _bool("HYBRID_USAGE_TRUST", False)

    @property
    def TABLE_CARD(self) -> bool:
        # P3 — merge metadata + annotation + code-enrich + freshness + owner/PII
        # into ONE embedded table card, and OVERLAY shared-memory corrections
        # onto it (corrected baseline). Off = piecemeal context. Default OFF.
        return _bool("HYBRID_TABLE_CARD", False)

    @property
    def INSTITUTIONAL_KB(self) -> bool:
        # P4 — retrieve access-controlled institutional docs (metric defs,
        # incidents, launches) INTO planner grounding. Off = docs not fed to
        # data answers. Default OFF.
        return _bool("HYBRID_INSTITUTIONAL_KB", False)

    @property
    def EVAL_CANARY(self) -> bool:
        # P5 — per-table eval pass-rate health badge + drift alert on
        # regression-vs-last-green (canary-in-prod). Off = nightly evals only,
        # no surfaced health. Default OFF.
        return _bool("HYBRID_EVAL_CANARY", False)

    @property
    def WORKFLOWS_V2(self) -> bool:
        # Part A — save a finished analysis as a reusable, parameterized
        # workflow; replay from the composer ("Use a workflow"). OpenAI
        # data-agent workflows. Default OFF.
        return _bool("HYBRID_WORKFLOWS_V2", False)

    @property
    def OFFLINE_CONTEXT(self) -> bool:
        # Part B — nightly job merges all context layers into ONE normalized
        # per-table doc + embeds once (vs request-time assembly). Default OFF.
        return _bool("HYBRID_OFFLINE_CONTEXT", False)

    @property
    def CODE_ENRICH_PLUS(self) -> bool:
        # Part C — deepen Codex enrichment: primary keys, downstream usage,
        # alternate-table hints. Default OFF.
        return _bool("HYBRID_CODE_ENRICH_PLUS", True)

    @property
    def GOLDEN_SQL(self) -> bool:
        # Part D — store expected SQL alongside expected rows in evals; grade
        # on SQL + result-set + LLM. Default OFF.
        return _bool("HYBRID_GOLDEN_SQL", False)

    @property
    def NOTION_KB(self) -> bool:
        # Part E — Notion / Slack as institutional-knowledge sources feeding
        # the P4 institutional layer. Default OFF.
        return _bool("HYBRID_NOTION_KB", False)

    @property
    def LEAN_TOOLS(self) -> bool:
        # F1 — trim the planner's tool catalog (retire overlapping/duplicate
        # tools per docs/TOOL_AUDIT.md) to reduce model confusion. Default OFF
        # = full catalog unchanged.
        return _bool("HYBRID_LEAN_TOOLS", False)

    @property
    def DOC_ACL(self) -> bool:
        # F3 — per-document access control on institutional knowledge (viewer
        # allow-list beyond org+approved). Default OFF = org-granularity (today).
        return _bool("HYBRID_DOC_ACL", False)

    @property
    def DOC_KNOWLEDGE(self) -> bool:
        # Any attached document (any type) -> extracted + chunked + indexed as
        # searchable Knowledge the agent can cite. Default ON.
        return _bool("HYBRID_DOC_KNOWLEDGE", True)

    @property
    def AUTOFILL_AGENT_OVERVIEW(self) -> bool:
        # On train, pin a primary instruction + seed conversation starters when
        # the agent's Overview is empty (fills only what's missing). Default ON.
        return _bool("HYBRID_AUTOFILL_AGENT_OVERVIEW", True)

    # --- BI Uplift ---------------------------------------------------------
    @property
    def CHART_GUARDRAIL(self) -> bool:
        # Enforce intent→chart matrix + post-render lint (one accent, labelled,
        # capped series). Default OFF.
        return _bool("HYBRID_CHART_GUARDRAIL", False)

    @property
    def INSIGHT_ENGINE(self) -> bool:
        # Computed signal sweep → Context/Conflict/Resolution decision + driver
        # enumeration on a drop. Default OFF.
        return _bool("HYBRID_INSIGHT_ENGINE", False)

    @property
    def KPI_LAYER(self) -> bool:
        # Per-agent governed KPIs: outcome ratios, leading/lagging chains,
        # target/owner/action-on-breach. Default OFF.
        return _bool("HYBRID_KPI_LAYER", False)

    @property
    def DASHBOARD_COMPOSER(self) -> bool:
        # Hero-metric + F-pattern layout + 5-second QA gate for page artifacts.
        # Default OFF.
        return _bool("HYBRID_DASHBOARD_COMPOSER", False)

    @property
    def DATA_PREP_GATE(self) -> bool:
        # Fill/Investigate/Remove missing-data tree + data-quality banner.
        # Default OFF.
        return _bool("HYBRID_DATA_PREP_GATE", False)

    @property
    def AUTO_EDA(self) -> bool:
        # Per-agent computed EDA profile + LLM narration, saved on the agent's
        # Overview only. Default OFF.
        return _bool("HYBRID_AUTO_EDA", False)

    @property
    def ADV_METHODS(self) -> bool:
        # Market-basket + stat-rigour (computed) + LLM-driven churn/forecast/
        # segmentation (labelled AI estimate). Default OFF.
        return _bool("HYBRID_ADV_METHODS", False)

    @property
    def SAFETY_EVALS(self) -> bool:
        # LLM-as-judge binary safety/reliability evals (security/governance/
        # boundaries/routing) beyond accuracy. Default OFF.
        return _bool("HYBRID_SAFETY_EVALS", False)

    @property
    def READONLY_ENFORCE(self) -> bool:
        # Connection/engine-level read-only enforcement (not prompt/string) on
        # the AGENT query path: Postgres opens with default_transaction_read_only
        # and every generated statement passes the structural write/DDL guard in
        # code_execution. ISSUE #6 — default flipped OFF->ON as pure security
        # hardening so a prompt-injection can't DROP/DELETE/ALTER source data out
        # of the box. This deliberately DEVIATES from the upstream-parity rule
        # (justified: it only blocks writes on external read paths, which the
        # agent never legitimately writes to — ingest/Engineer use their own
        # managed staging/analytics engines). Set HYBRID_READONLY_ENFORCE=0 to
        # restore the legacy string-only-when-explicitly-enabled behaviour.
        return _bool("HYBRID_READONLY_ENFORCE", True)

    @property
    def ASSET_MATERIALIZE(self) -> bool:
        # Materialize hot Shared-Memory query templates into persistent assets.
        # Default OFF.
        return _bool("HYBRID_ASSET_MATERIALIZE", False)

    @property
    def GOTCHA_MEMORY(self) -> bool:
        # Route ingest/profile data-quality gotchas into GLOBAL Shared Memory.
        # Default OFF.
        return _bool("HYBRID_GOTCHA_MEMORY", False)

    @property
    def ANSWER_CACHE(self) -> bool:
        # Tier-0 Redis answer-cache.
        return _bool("HYBRID_ANSWER_CACHE", True)

    @property
    def AMBIGUITY_GATE(self) -> bool:
        # R3 "ask before assuming" gate: pre-planning ambiguity classifier that
        # makes the agent clarify (via the clarify tool) instead of assuming a
        # year/metric/entity. Vectorless, OpenRouter-only, fail-open. Default OFF.
        return _bool("HYBRID_AMBIGUITY_GATE", False)

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
        return _bool("HYBRID_BRAIN_READ", True)

    @property
    def DISTILLER(self) -> bool:
        # Phase 5: 👎 self-distill -> pending memory.
        return _bool("HYBRID_DISTILLER", True)

    @property
    def QUERY_CACHE(self) -> bool:
        # Phase 5: reasoning-cache (param-swap proven SQL).
        return _bool("HYBRID_QUERY_CACHE", True)

    @property
    def SKILLS(self) -> bool:
        # Phase 6: self-service skills subsystem.
        return _bool("HYBRID_SKILLS")

    @property
    def STUDIOS(self) -> bool:
        # Studios: NotebookLM-style shareable agent containers. Default OFF.
        return _bool("HYBRID_STUDIOS", True)

    # --- Slice 3: federation + correlation ----------------------------------
    @property
    def FEDERATION(self) -> bool:
        # Phase 7: DuckDB cross-source federation.
        return _bool("HYBRID_FEDERATION", True)

    @property
    def BRAIN_GRAPH(self) -> bool:
        # Phase 8: Apache AGE entity/correlation graph. Default OFF.
        return _bool("HYBRID_BRAIN_GRAPH", True)

    @property
    def INSIGHT_DAEMON(self) -> bool:
        # Phase 8: proactive insight daemon (leader-gated). Default OFF.
        return _bool("HYBRID_INSIGHT_DAEMON", True)

    @property
    def JOIN_GRAPH(self) -> bool:
        # Phase 6: join-graph context (relationship/join edges injected into
        # the planner, mined offline). Default OFF.
        return _bool("HYBRID_JOIN_GRAPH", True)

    @property
    def JOIN_MINE_ENABLED(self) -> bool:
        # Phase 6: nightly join-mining daemon (leader-gated). NOTE: no HYBRID_
        # prefix — matches EVAL_SCHEDULE_ENABLED naming convention. Default OFF.
        return _bool("JOIN_MINE_ENABLED", True)

    @property
    def STUDIO_LEARN_DAEMON(self) -> bool:
        # Org master switch for the per-studio self-learn daemon. Reads the
        # override layer (DB toggle / env), so the Feature-Flags UI toggle works
        # without a compose env var. Per-studio cadence is stored on the studio.
        return _bool("STUDIO_LEARN_DAEMON_ENABLED", True)

    # --- Slice 4: scale harden ----------------------------------------------
    @property
    def QUOTAS(self) -> bool:
        # Phase 9: per-org request/token quota enforcement (UsagePolicy). Default OFF.
        return _bool("HYBRID_QUOTAS", True)

    # --- Slice 5: knowledge layer -------------------------------------------
    @property
    def SEMANTIC_LAYER(self) -> bool:
        # dash semantic model: per-table/column meaning injected into context.
        return _bool("HYBRID_SEMANTIC_LAYER", True)

    @property
    def METRICS_CATALOG(self) -> bool:
        # dash metrics catalog: named metric -> SQL definition.
        return _bool("HYBRID_METRICS_CATALOG", True)

    @property
    def GOVERNANCE(self) -> bool:
        # Kepler Phase 1: owner / freshness / PII metadata on semantic tables,
        # injected as a per-table governance footer + planner PII rule. Default OFF.
        return _bool("HYBRID_GOVERNANCE", True)

    @property
    def AUTOMAP(self) -> bool:
        # Feature 1: auto-configure-from-doc. Extract column descriptions +
        # instructions + examples from an uploaded definitions xlsx / deck pptx
        # and apply them (descriptions live, instructions/examples pending). Default OFF.
        return _bool("HYBRID_AUTOMAP", True)

    @property
    def COMPLIANCE_GATE(self) -> bool:
        # Feature 4: on-demand, advisory, read-only compliance & data-integrity
        # scan endpoint (dedup + required-field quality). Default OFF.
        return _bool("HYBRID_COMPLIANCE_GATE", True)

    @property
    def COLUMN_INTEL(self) -> bool:
        # Batch B: pre-train per-column profiler (role + allowed values +
        # distinct + null_pct) merged into DataSourceTable.columns[].metadata,
        # surfaced into the schema XML so the agent knows each column up front.
        # Default OFF.
        return _bool("HYBRID_COLUMN_INTEL", True)

    @property
    def AUTO_QUERIES(self) -> bool:
        # Auto-train pipeline: LLM generates example SQL per pinned source,
        # runs read-only, saves verified queries to the library. Default OFF.
        return _bool("HYBRID_AUTO_QUERIES", True)

    @property
    def AUTO_EVALS(self) -> bool:
        # Auto-train pipeline: LLM generates golden eval cases from real data
        # aggregates (grounded expectations). Creation only. Default OFF.
        return _bool("HYBRID_AUTO_EVALS", True)

    @property
    def FOLLOWUPS(self) -> bool:
        # Suggested follow-up questions after each chat answer (ChatGPT/Claude
        # style). Generated per-agent: grounded in the Studio's voice + active
        # instructions + real column values, so each agent suggests its own
        # follow-ups. Default OFF.
        return _bool("HYBRID_FOLLOWUPS", True)

    @property
    def CODE_BANK(self) -> bool:
        # Kepler Phase 2: capture proven generate_df python on success + inject the
        # closest snippet(s) as PROVEN APPROACHES context (never executed). Default OFF.
        return _bool("HYBRID_CODE_BANK", True)

    @property
    def MEMORY_LOOP(self) -> bool:
        # Kepler Phase 3: on 👍, draft pending knowledge (proven SQL -> QueryLibraryItem,
        # bless captured code) with chat provenance. Approval-gated. Default OFF.
        return _bool("HYBRID_MEMORY_LOOP", True)

    @property
    def EVAL_HARNESS(self) -> bool:
        # Phase 4 (eval result-set goldens): result_set matcher + save-as-golden /
        # context-change re-run hooks + FE harness UI. Default OFF.
        return _bool("HYBRID_EVAL_HARNESS", True)

    @property
    def EVAL_SCHEDULE_ENABLED(self) -> bool:
        # Phase 4: nightly scheduled re-run of result-set goldens (leader-gated
        # daemon). NOTE: no HYBRID_ prefix — matches PLAN_KEPLER.md naming. Default OFF.
        return _bool("EVAL_SCHEDULE_ENABLED", True)

    # --- Domain Packs (lightweight "skills" engine — not native Skills) ------
    @property
    def DOMAIN_PACKS(self) -> bool:
        # Master flag for the Domain Packs subsystem: declarative method files
        # (app/ai/packs/library) bound per-agent to real columns and injected
        # into the planner as a method+binding block. Rides the default
        # create_data/create_artifact loop — NO sandbox exec (unlike native
        # HYBRID_SKILLS, which livelocks). When OFF nothing reads the
        # studio_bound_packs table and the agent loop is byte-identical. Default OFF.
        return _bool("HYBRID_DOMAIN_PACKS", True)

    @property
    def PROMPTS_LIBRARY(self) -> bool:
        # Prompts Library: a reusable saved-prompt subsystem (CRUD over the
        # `prompts` table). The API router is always mounted; this flag only
        # gates the "Prompts" nav entry on the frontend. When OFF the page/route
        # still exist but are unlinked from the nav. Default OFF.
        return _bool("HYBRID_PROMPTS_LIBRARY", False)

    @property
    def USER_AVATAR(self) -> bool:
        # User avatar upload: gates only the FE "Edit profile" upload affordance.
        # The avatar serve route + users.image_url column exist unconditionally so
        # an already-uploaded avatar keeps rendering if the flag is later OFF.
        return _bool("HYBRID_USER_AVATAR", False)

    @property
    def NOTIFICATIONS_INBOX(self) -> bool:
        # In-app notification inbox: gates only the FE nav bell. The API router +
        # notifications table exist unconditionally; when OFF the bell is hidden.
        # Default OFF.
        return _bool("HYBRID_NOTIFICATIONS_INBOX", False)

    @property
    def SERVICE_ACCOUNTS(self) -> bool:
        # Service Accounts: machine/service principals an org admin creates,
        # each holding one or more API keys (bow_ prefix, SHA-256 hashed) for
        # headless/programmatic access. Gates the admin routes + settings page.
        # When OFF the routes 404 and the settings nav entry is hidden. Default OFF.
        return _bool("HYBRID_SERVICE_ACCOUNTS", False)

    @property
    def CONNECTION_GRANTS(self) -> bool:
        # #489: per-principal grant/revoke of access to a connection / data source
        # (the RBAC resource cascade for connections). When OFF the resolver behaves
        # exactly as the pre-#489 fork (connection grants unsupported). Default OFF.
        return _bool("HYBRID_CONNECTION_GRANTS", False)

    @property
    def AUTO_PUBLISH(self) -> bool:
        # Auto-publish: newly created data agents / instructions are published on
        # create per an org rule instead of staying draft. When OFF creation keeps
        # the current draft-until-promoted behavior. Default OFF.
        return _bool("HYBRID_AUTO_PUBLISH", False)

    @property
    def FILE_REFERENCES(self) -> bool:
        # #497: reference uploaded files inside prompts / agent context. When OFF no
        # file-reference model is read and the agent context is byte-identical.
        # Default OFF.
        return _bool("HYBRID_FILE_REFERENCES", False)

    @property
    def MCP_GATEWAY(self) -> bool:
        # #487: external MCP gateway that re-exposes an agent's own tools out through
        # the external MCP endpoint. When OFF the gateway routes are inert. Default OFF.
        return _bool("HYBRID_MCP_GATEWAY", False)

    @property
    def USD_QUOTA(self) -> bool:
        # #488: per-org / per-user monthly spend cap in USD, enforced against
        # llm_usage_records cost. When OFF no USD limit is checked. Default OFF.
        return _bool("HYBRID_USD_QUOTA", False)

    @property
    def STANDALONE_CONNECTORS(self) -> bool:
        # #467: use a connector standalone (tools-only) without wrapping it as a data
        # agent. When OFF connectors behave as today (agent-wrapped). Default OFF.
        return _bool("HYBRID_STANDALONE_CONNECTORS", False)

    @property
    def TREE_LAZYLOAD(self) -> bool:
        # #494/430: /agents knowledge tree loads instruction/knowledge counts and
        # global search lazily via dedicated endpoints instead of eager full loads.
        # When OFF the tree uses the existing eager path. Default OFF.
        return _bool("HYBRID_TREE_LAZYLOAD", True)

    @property
    def SIDEBAR_ACTIVITY_SORT(self) -> bool:
        # #479: order the reports sidebar by last activity (message / turn-finalize)
        # instead of created_at. When OFF ordering is unchanged (created_at). Default OFF.
        return _bool("HYBRID_SIDEBAR_ACTIVITY_SORT", True)

    @property
    def GLOBAL_EVALS_NODE(self) -> bool:
        # #478: show a global Evals node in the knowledge explorer tree.
        # When OFF the node is hidden. FE-only. Default OFF.
        return _bool("HYBRID_GLOBAL_EVALS_NODE", True)

    @property
    def LOCALIZED_FOLLOWUPS(self) -> bool:
        # #521: localize follow-up suggestions and render direction-aware (dir="auto",
        # RTL). When OFF follow-ups render as today. FE-only. Default OFF.
        return _bool("HYBRID_LOCALIZED_FOLLOWUPS", True)

    @property
    def WEEK_START(self) -> bool:
        # 430: configurable week-start day for prompt scheduling / date grouping.
        # When OFF the existing default week start is used. Default OFF.
        return _bool("HYBRID_WEEK_START", True)

    @property
    def PDF_HYDRATION(self) -> bool:
        # #527: hydrate report data into the PDF render path so exported PDFs include
        # numbers and chart data. When OFF the existing PDF path is used. Default OFF.
        return _bool("HYBRID_PDF_HYDRATION", True)

    @property
    def PACK_AUTOBIND(self) -> bool:
        # Sub-flag: during studio train, auto-try binding every library pack to
        # the agent's profiled columns and write PENDING studio_bound_packs rows
        # (review-gated before active). Off -> packs only bind on explicit
        # request. No-op unless DOMAIN_PACKS is also on. Default OFF.
        return _bool("HYBRID_PACK_AUTOBIND", True)

    @property
    def PACK_ROUTER(self) -> bool:
        # Sub-flag: at query time, candidate-gate ACTIVE bound packs, score vs
        # the question, and inject the top-1 method+binding into the planner.
        # Off -> packs are bound/visible but never auto-injected. No-op unless
        # DOMAIN_PACKS is also on. Default OFF.
        return _bool("HYBRID_PACK_ROUTER", True)

    @property
    def TEACH_BOX(self) -> bool:
        # Teach Box: paste an existing analysis / SOP, one LLM call classifies it
        # into SKILL | INSTRUCTION | KNOWLEDGE | DATA-RULE spans, each routed to
        # its surface (SKILL -> user-authored domain pack bound to the studio;
        # INSTRUCTION/DATA-RULE -> StudioInstruction; KNOWLEDGE -> KnowledgeDoc).
        # Everything is born pending behind the existing review gate. Gates only
        # the /studios/{id}/teach endpoints; no agent-loop effect. Default OFF.
        return _bool("HYBRID_TEACH_BOX", True)

    @property
    def MERGE_SAME_SCHEMA(self) -> bool:
        # Ingest Task 5: same-schema spreadsheet uploads collapse into ONE
        # data source + table instead of N sources. (a) Content-hash dedup —
        # a byte-identical re-upload returns the existing source. (b) Same-schema
        # append — when the new file's normalized column-set matches an existing
        # spreadsheet source in the same org, the new file's path is added to
        # that source's connection (config['merged_paths']) and the rows are
        # UNION-loaded into the one table with a `_source_label` provenance
        # column, rather than creating a new source+table. Fail-soft: any error
        # falls back to today's one-source-per-file behavior. Default OFF.
        return _bool("HYBRID_MERGE_SAME_SCHEMA", True)

    @property
    def SMART_HEADER(self) -> bool:
        # Ingest Task 6: smarter xlsx ingest. (a) Header detection — if reading a
        # sheet with the default header yields a high fraction of `Unnamed: N`
        # columns, scan the first rows for the real header row and re-read. (b)
        # Glossary routing — a field-definition / data-dictionary sheet (2-3
        # cols of name->description, or filename/sheet name contains
        # defin/glossary/dictionary) is routed into the Knowledge layer
        # (KnowledgeDoc, pending) so its terms can map onto OTHER sources'
        # columns, instead of landing as a junk `Unnamed` queryable table.
        # Conservative — only reroutes when confident. Default OFF.
        return _bool("HYBRID_SMART_HEADER", True)

    @property
    def TOTAL_ROW(self) -> bool:
        # Ingest Task T2: detect PRE-AGGREGATED total/subtotal rows at ingest so
        # the agent stops double-counting. Real case: a CSV has per-site rows PLUS
        # rows where site='ALL Total' (already summed across sites) — a naive
        # SUM(value) over the whole table double-counts (the subtotal + its parts).
        # During profiling we scan the DataFrame for likely total rows (a
        # low-cardinality dimension equals 'total'/'all total'/'grand total'/...
        # while other key dimensions are blank), record markers into the
        # DataSourceTable.metadata_json['total_row_markers'] (+ an estimated
        # total_row_count), and auto-emit a guardrail Instruction the agent reads
        # ("Exclude pre-aggregated total rows: WHERE site NOT ILIKE '%total%'").
        # Conservative (only flags when row-share is plausible, < 60%) and
        # fail-soft (never breaks ingest). Default OFF.
        return _bool("HYBRID_TOTAL_ROW", False)

    @property
    def ONE_TABLE_MERGE(self) -> bool:
        # Pipeline v1 (P1): same-schema spreadsheet uploads stack into ONE
        # canonical table + a _source_period column, instead of N tables keyed by
        # filename stem (which forced UNION ALL across monthly files). Fail-soft.
        return _bool("HYBRID_ONE_TABLE_MERGE", True)

    @property
    def SMART_SOURCE_NAME(self) -> bool:
        # After profiling, if a data source's display name carries a single-month
        # token (e.g. "(Apr'25)") but its _source_period column spans multiple
        # months, rewrite the display name to the real range ("(Jan-Jun'25)").
        # Renames DataSource.name ONLY (never the table id/slug). Fail-soft.
        return _bool("HYBRID_SMART_SOURCE_NAME", True)

    @property
    def COLUMN_PROFILE(self) -> bool:
        # Master plan E3: profile each column on upload (dtype, null %, distinct,
        # min/max, top values) -> fills semantic_columns.type + feeds validation.
        return _bool("HYBRID_COLUMN_PROFILE", False)

    @property
    def DATA_VALIDATION(self) -> bool:
        # Master plan E4: garbage-in net — filter-value existence, row-count floor,
        # null-spike, category near-dup, dup-file. Surfaces <data_quality>.
        return _bool("HYBRID_DATA_VALIDATION", False)

    @property
    def DATA_TYPING(self) -> bool:
        # Master plan E5: cast number/date-shaped columns to real types before the
        # query engine, so SUM/AVG/date-range work instead of string ops. Uses E3
        # dtype; category/text untouched (protects the verified-golden filters).
        return _bool("HYBRID_DATA_TYPING", False)

    @property
    def RATIO_METRICS(self) -> bool:
        # Master plan A2+A3: kind='ratio' definitions (num + den predicates) ->
        # two COUNT queries -> eval verifies both counts. Unblocks rate metrics.
        return _bool("HYBRID_RATIO_METRICS", False)

    @property
    def LOGIC_PARSER(self) -> bool:
        # Pipeline v1 (P2): parse a logic/Q&A doc into (question, answer, logic)
        # triples + expected answers; route logic docs into Instructions instead
        # of held Examples. Feeds the Definition Registry. Fail-soft.
        return _bool("HYBRID_LOGIC_PARSER", False)

    @property
    def DEF_REGISTRY(self) -> bool:
        # Pipeline v1 (P3): Definition Registry — single source of truth for
        # business metrics (Lead/New User/Status rule) + expected answers. Every
        # golden/instruction references a def. Needs migration defreg1.
        return _bool("HYBRID_DEF_REGISTRY", False)

    @property
    def VERIFIED_GOLDENS(self) -> bool:
        # Pipeline v1 (P4+P5): logic-aware golden generation + EVAL GATE — a
        # generated query is approved only when it matches the doc's expected
        # number; mismatch/unknown -> held with a diff. Fail-soft.
        return _bool("HYBRID_VERIFIED_GOLDENS", False)

    @property
    def QUERY_CORRECTION(self) -> bool:
        # Pipeline v1 (P6): user instruction -> update a definition -> regenerate
        # every dependent golden -> re-eval. One correction fixes all SQL.
        return _bool("HYBRID_QUERY_CORRECTION", False)

    @property
    def AUTO_MAP_GLOSSARY(self) -> bool:
        # Import v2 (P2): a SEPARATE glossary/definitions FILE (not a sheet inside a
        # data file) uploaded on its own is detected, parsed term->definition, and
        # auto-mapped onto the columns of the org's existing data sources (fuzzy
        # name match) -> writes pending SemanticColumn meanings + a KnowledgeDoc.
        # Extends SMART_HEADER (which only routes glossary SHEETS within a data
        # file). Fail-soft, review-gated. Default OFF.
        return _bool("HYBRID_AUTO_MAP_GLOSSARY", False)

    @property
    def ROBUST_INGEST(self) -> bool:
        # Import v2 (P3): route spreadsheet uploads through the robust ingest
        # readers (services/ingest/csv_reader + excel_reader: encoding+delimiter
        # sniff, real-header detection, banner skip, id-safe numeric coercion,
        # bad-row skip) instead of SpreadsheetClient's naive pandas read. Per-file
        # ingest feedback (skipped rows, detected encoding/header) surfaced on the
        # response. Fail-soft -> falls back to the naive reader on any error.
        # Default OFF.
        return _bool("HYBRID_ROBUST_INGEST", False)

    @property
    def INGEST_RECONCILE(self) -> bool:
        # Ingest-completeness guard: make the multi-file spreadsheet merge
        # fail-LOUD like the chat-upload path. The merge loop in
        # SpreadsheetClient._load_frames records each file's outcome
        # (loaded|failed + rows + error) instead of silently swallowing a bad
        # file with `except: continue`. Later phases use this record to flip a
        # source DEGRADED, feed coverage-context to the agent, and surface the
        # gap in the upload UI. Flag OFF -> byte-identical to today (no capture,
        # silent-skip preserved). Default ON (production ingest-completeness).
        return _bool("HYBRID_INGEST_RECONCILE", True)

    @property
    def INGEST_SELFHEAL(self) -> bool:
        # Self-heal repair: detect orphaned same-schema physical tables that
        # belong to an agent's data source but never got merged into its ONE
        # bound table (e.g. files uploaded across separate sessions), and
        # auto-stitch them back in. Runs fail-soft as a train stage AND on
        # demand via a "Repair data" action. Backup + transaction-safe +
        # idempotent. Generic: keys off column-signature, works for ANY dataset
        # partition (not just months). Off = no repair. Default ON.
        return _bool("HYBRID_INGEST_SELFHEAL", True)

    @property
    def AUTOEDA_AUTOAPPROVE(self) -> bool:
        # First-party knowledge auto-approve: insight/Auto-EDA docs and other
        # docs generated FROM the user's own uploaded data land status='approved'
        # (agent-visible) instead of 'pending' (silent + invisible). Learned/
        # AI-proposed memories still go through the review gate. Off = docs stay
        # pending until manual approval. Default ON.
        return _bool("HYBRID_AUTOEDA_AUTOAPPROVE", True)

    @property
    def SOURCE_SYNC_GATE(self) -> bool:
        # Refuse-when-empty gate: if the bound data source(s) for a chat have NO
        # synced/active tables, refuse to answer instead of silently falling back
        # to some other source's data. The agent surfaces a clear "sync it first"
        # message. Only refuses when EVERY bound source is empty; if any source
        # has tables, proceeds normally. Off = legacy behaviour (may answer from
        # whatever data is reachable). Default ON (reliability / no-wrong-source).
        return _bool("HYBRID_SOURCE_SYNC_GATE", True)

    @property
    def PERSIST_WAREHOUSE(self) -> bool:
        # Import v2 (P4, architectural/risky): persist spreadsheet uploads into the
        # per-org Postgres staging schema (tenant_schema.loader_write_engine) so
        # data survives restarts, gets deep stats, and the cross-source unified
        # VIEW can physically materialize -- instead of the in-memory DuckDB that
        # is lost on restart. Default OFF (proven on a copy before recommending).
        return _bool("HYBRID_PERSIST_WAREHOUSE", True)

    @property
    def INGEST_BRAIN(self) -> bool:
        # ROADMAP F09: Universal Ingest Brain. A 6-stage pipeline behind the
        # existing from-file ingest — DETECT → EXTRACT (messy Excel regions /
        # merged cells / multi-row headers; PDF/Word/image GPU-free) → PROFILE
        # (per-column ColumnProfile) → UNDERSTAND → UNIFY (cross-source joins)
        # → STORE+LEARN into one org-level brain (review-gated). Built in
        # phases; every stage fail-soft and preview-before-commit. With this
        # OFF the ingest path is byte-identical to today. Default OFF.
        return _bool("HYBRID_INGEST_BRAIN", True)

    @property
    def AUTOTRAIN_ON_UPLOAD(self) -> bool:
        # After a user drops files via Smart Upload and they are placed into their
        # lanes, automatically kick the studio's one-pass training (the same
        # train_orchestrator.start_training the Auto-train button runs). Bounded to
        # the studio + just-uploaded files — NOT the risky warehouse-wide
        # HYBRID_AUTOTRAIN_ON_INDEX. When OFF, upload only stores; training stays a
        # manual step. Default ON.
        return _bool("HYBRID_AUTOTRAIN_ON_UPLOAD", True)

    @property
    def ROBOT_DOCK(self) -> bool:
        # Floating robot mascot pinned bottom-right of the studio page; click to
        # expand a live CLI terminal streaming upload → classify → train stages
        # (one at a time) with model, counts, tokens, spend and readiness. When OFF
        # the dock is not rendered and the page is unchanged. Default ON.
        return _bool("HYBRID_ROBOT_DOCK", True)

    @property
    def RESULT_CACHE(self) -> bool:
        # Task 7: deterministic result cache. Keyed by (normalized question text +
        # the report's per-source row-count watermark signature). On a HIT with an
        # unchanged watermark, serve the stored create_data result and SKIP codegen
        # + execution entirely. A re-train / new upload bumps the watermark -> the
        # key changes -> natural miss -> rebuild once. Never serves a stale entry
        # when the watermark differs. Default OFF.
        return _bool("HYBRID_RESULT_CACHE", True)

    @property
    def PARQUET_RESULTS(self) -> bool:
        # Store large step result sets as compressed Parquet files on disk instead
        # of inline JSON in Postgres. Shrinks the DB + speeds dashboard loads; rows
        # are hydrated transparently on read. Small results stay inline. Default ON.
        return _bool("HYBRID_PARQUET_RESULTS", True)

    @property
    def PARQUET_MIN_ROWS(self) -> int:
        # Row-count threshold: results with >= this many rows go to Parquet; smaller
        # results stay inline JSON (Parquet's footer overhead isn't worth it). Env knob.
        return _int("HYBRID_PARQUET_MIN_ROWS", 2000)

    @property
    def CONNECTOR_AUTO_SYNC(self) -> bool:
        # Master gate for scheduled connector auto-sync. When ON, a scheduler job
        # sweeps connector clones that have per-agent auto-sync enabled (stored in
        # organization_settings.config['connector_auto_sync'][ds_id]) and re-runs
        # sync_clone_bg on the configured interval. Re-training is diff-gated inside
        # sync_clone_bg, so a no-change sweep costs no LLM calls. Default OFF.
        return _bool("HYBRID_CONNECTOR_AUTO_SYNC", False)

    @property
    def AUTO_TABLE_RELEVANCE(self) -> bool:
        # At connector sync, classify each discovered table (fact / dimension /
        # measure / staging / telemetry / meta) and mark noise tables inactive so
        # the agent's schema, Key Tables, and starters carry only business-useful
        # tables. Deterministic rules (Power BI usage-metrics, Stg_ staging, empty
        # / RowNumber-only, measure holders → noise). Verdict stored on the table's
        # metadata_json.classification; is_active set from it. Manual override in
        # the Tables tab always wins. Default OFF (opt-in per org). See
        # app.services.table_relevance.classify_table.
        return _bool("HYBRID_AUTO_TABLE_RELEVANCE", False)

    @property
    def LEARN_FROM_DATA(self) -> bool:
        # At connector learn time, pull a tiny sample of REAL rows from each active
        # table and record a few example values per column into the schema the
        # onboarding LLM reads. Grounds the generated description / starters /
        # instruction in actual data (not just table names + the connector's
        # display name) — kills domain hallucination on sources that lack FKs /
        # column descriptions (e.g. Power BI). PII columns are never sampled.
        # Default OFF. See app.services.connector_sampler.
        return _bool("HYBRID_LEARN_FROM_DATA", False)

    @property
    def HOT_START(self) -> bool:
        # On agent open, pre-warm the user's Power BI model (fire cheap queries so
        # Microsoft's engine loads the model into memory) and pre-compute the model's
        # headline measures into the per-user DAX cache, so the first real question is
        # a cache hit (<1s) instead of a cold 40-84s query — and the Overview can show
        # real headline numbers before the user types anything. Per-user, PBI-only,
        # background, throttled, fail-soft. Default OFF. See services.connector_warm.
        return _bool("HYBRID_HOT_START", False)

    @property
    def MOA(self) -> bool:
        # Mixture-of-Agents "peer-consult" sidecar: a measurement-only endpoint
        # (POST /api/llm/moa/test) that fires a panel of cheap diverse OpenRouter
        # models in parallel, assembles a peer block, and optionally A/Bs a GLM
        # aggregator with/without it. NOT wired into AgentV2 / planner / reports.
        # OpenRouter-only, fail-soft. When OFF the router is not even mounted.
        return _bool("HYBRID_MOA", False)

    @property
    def QUERY_LEARNING(self) -> bool:
        # Task 8: live query-learning. When a create_data step SUCCEEDS, persist its
        # working SQL/approach to the query library tagged with the question (review-
        # gated, born pending), marked a win, so future similar questions can reuse
        # it. A fail-then-retry-success records the corrected approach as positive
        # (and optionally the dead path as a down-weighted negative studio note).
        # Reuse is injected into the planner context the same way auto-queries are.
        # Default OFF.
        return _bool("HYBRID_QUERY_LEARNING", True)

    @property
    def DOC_KNOWLEDGE(self) -> bool:
        # Kepler Phase 5: company-docs RAG. Approved docs are chunked + PG
        # full-text-searched (VECTORLESS — no embedder in image) and the top
        # matches injected as a "### Company definitions" block to resolve
        # business-term ambiguity. Approval-gated. Default OFF.
        return _bool("HYBRID_DOC_KNOWLEDGE", True)

    @property
    def PROFILE_V2(self) -> bool:
        # Wave1 P1: deep profiler — per-column role (DIMENSION/STATE/MEASURE/
        # IDENTIFIER/TEMPORAL) + top-3 values/freq + variant warnings, stored in
        # DataSourceTable.metadata_json['profile_v2'] + injected as a compact
        # 80-char/col prompt catalog. Default OFF.
        return _bool("HYBRID_PROFILE_V2", True)

    @property
    def PROACTIVE_INSIGHTS(self) -> bool:
        # Wave1 P2: z-score/IQR anomaly + trend scan on result df → insights[]
        # attached post-create_data, rendered as chips. Default OFF.
        return _bool("HYBRID_PROACTIVE_INSIGHTS", True)

    @property
    def SENSE_MAKING(self) -> bool:
        # F10: post-answer decision layer — deterministic signals + 1 cheap LLM → sense_making card. OFF.
        return _bool("HYBRID_SENSE_MAKING", True)

    @property
    def AUTO_MODEL(self) -> bool:
        # Auto model selection: a complexity classifier routes each question to the
        # cheapest capable model (FAST/BALANCED/REASON). Sentinel model_id "auto". OFF.
        return _bool("HYBRID_AUTO_MODEL", True)

    @property
    def FORECAST(self) -> bool:
        # Wave1 P3: Prophet forecast tool (df[date,value] → forecast df). OFF.
        return _bool("HYBRID_FORECAST", True)

    @property
    def DLT_INGEST(self) -> bool:
        # NEWPIPE P2/P3: robust dlt ingest → DuckDB FILE + idempotent merge
        # (by _source_period + content-hash). Default OFF → pandas path unchanged.
        return _bool("HYBRID_DLT_INGEST", False)

    @property
    def FULL_PIPELINE(self) -> bool:
        # NEWPIPE master flag: run all 15 stages (quality-gate, golden/answer eval,
        # hybrid-index, brain-graph) in one train. Default OFF.
        return _bool("HYBRID_FULL_PIPELINE", True)

    @property
    def POWERBI_USER(self) -> bool:
        # Power BI semantic-model connector via USER sign-in (ROPC email+password)
        # instead of a service principal. Gates visibility of the `powerbi_user`
        # connector type in the add-connection grid. Default OFF.
        return _bool("HYBRID_POWERBI_USER", False)

    @property
    def CONNECTOR_AS_AGENT(self) -> bool:
        # On connector-create, auto-spawn an org-shared Studio (agent) bound to
        # the connection, so every member can chat it with no manual setup.
        # Default OFF.
        return _bool("HYBRID_CONNECTOR_AS_AGENT", False)

    @property
    def CONNECTOR_ROBUSTNESS(self) -> bool:
        # Harden the create_data → live-connector query path (auto-fill tables,
        # rate-limit backoff, dataset-id threading). Default OFF.
        return _bool("HYBRID_CONNECTOR_ROBUSTNESS", False)

    @property
    def SCOPED_INSTRUCTIONS(self) -> bool:
        # Per-agent instruction + search isolation: unscoped instruction != global,
        # and search tools filter to the report's own data sources. Default OFF.
        return _bool("HYBRID_SCOPED_INSTRUCTIONS", False)

    @property
    def CONNECTOR_JOURNEY_V2(self) -> bool:
        # Revamped connect flow: capture MS email, consent gate + explicit sync,
        # report/app-based dataset discovery, honest queryable-vs-view-only. Default OFF.
        return _bool("HYBRID_CONNECTOR_JOURNEY_V2", False)

    @property
    def PER_USER_CONNECTOR(self) -> bool:
        # Admin marks a connector as a per-user TEMPLATE (tenant/client config,
        # no user creds). Each member registers with their own credentials →
        # cloned into a private owner-scoped DataSource with their OWN synced
        # catalog (isolated: is_public=False + owner_user_id + MS access control).
        # Default OFF.
        return _bool("HYBRID_PER_USER_CONNECTOR", False)

    @property
    def ADAPTIVE_CONNECT(self) -> bool:
        # Adaptive per-user connector sign-in: a member enters email+password →
        # backend tries ROPC (password grant); if the account has no MFA it
        # connects immediately, else it auto-falls-back to device-code sign-in.
        # Both paths funnel to the SAME refresh_token→clone builder. Default OFF.
        return _bool("HYBRID_ADAPTIVE_CONNECT", False)

    @property
    def MS_UNIFIED_SIGNIN(self) -> bool:
        # One Microsoft sign-in → TWO Data Agents. The FOCI refresh token minted on
        # a Power BI sign-in also redeems a Fabric token (same token family), so a
        # single sign-in builds BOTH a Power BI clone and a Fabric sibling clone
        # (shared credentials). Additive: a NEW "Microsoft (Fabric + Power BI)" tile;
        # the existing single-source tiles are untouched. Default OFF.
        return _bool("HYBRID_MS_UNIFIED_SIGNIN", False)

    @property
    def GOLDEN_QUERIES(self) -> bool:
        # Wave1 P4: promote thumbs-up / repeat-success learned queries to golden;
        # golden ranks first in coder injection. Default OFF.
        return _bool("HYBRID_GOLDEN_QUERIES", True)

    @property
    def VERIFIED_METRICS(self) -> bool:
        # Wave1 P7: executable locked MetricDefinition (run via metric tool,
        # overrides agent formula) + drift check. Default OFF.
        return _bool("HYBRID_VERIFIED_METRICS", True)

    @property
    def SEMANTIC_SEARCH(self) -> bool:
        # Wave1 P8: hybrid pgvector + BM25 RRF search + knowledge graph. OFF.
        return _bool("HYBRID_SEMANTIC_SEARCH", True)

    @property
    def CODE_ENRICH(self) -> bool:
        # Wave1 P6: L3 Codex code-enrich — extract grain + derived-column formulas
        # + population from table/view DDL source SQL, store in
        # DataSourceTable.metadata_json['pipeline_logic'], inject a compact
        # PIPELINE LOGIC prompt block. Meaning lives in code, not schemas. Default OFF.
        return _bool("HYBRID_CODE_ENRICH", True)

    @property
    def AGENT_TEMPLATES(self) -> bool:
        # Share an agent's data-agnostic best practices (rules, metric formulas,
        # example patterns, skills, persona) as a portable, versioned template that
        # others bind to their own columns. Export/Gallery/bind. Default OFF.
        return _bool("HYBRID_AGENT_TEMPLATES", True)

    @property
    def FOLDER_SYNC(self) -> bool:
        # Desktop Folder Sync agent: a local tray app watches a folder and pushes
        # changed Excel/CSV files (API-key authed) to /api/sync/file, which delta-
        # upserts them into a per-agent DataSource. Like Claude Code for data.
        # Default OFF.
        return _bool("HYBRID_FOLDER_SYNC", True)

    @property
    def SMART_WORKBOOK(self) -> bool:
        # Smart Excel builder: user types a transform intent, an LLM converts it to
        # a strict whitelist-validated spec (select/rename/filter/aggregate/pivot/sort)
        # applied in pure-Python (pandas) over the existing query-result grids — no
        # SQL re-run. Flag OFF = today's raw workbook dump unchanged. Default OFF.
        return _bool("HYBRID_SMART_WORKBOOK", False)

    @property
    def FOLLOWUP_FASTPATH(self) -> bool:
        # Follow-up fast-path: when a report already researched its tables in an
        # earlier turn (a prior read_resources / describe_tables ran), inject a
        # planner hint that the schema / instructions / metadata resources are
        # ALREADY in context so the model skips the redundant "read the
        # instructions first" research step on follow-ups. Pure prompt nudge —
        # the data it points at is always rebuilt into context, so correctness is
        # unchanged; only removes a wasted plan/execute/reflect cycle. Fail-soft,
        # OFF = byte-identical. Default OFF.
        return _bool("HYBRID_FOLLOWUP_FASTPATH", False)

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
            "STUDIO_LEARN_DAEMON": self.STUDIO_LEARN_DAEMON,
            "QUOTAS": self.QUOTAS,
            "SEMANTIC_LAYER": self.SEMANTIC_LAYER,
            "METRICS_CATALOG": self.METRICS_CATALOG,
            "GOVERNANCE": self.GOVERNANCE,
            "CODE_BANK": self.CODE_BANK,
            "MEMORY_LOOP": self.MEMORY_LOOP,
            "SHARED_MEMORY": self.SHARED_MEMORY,
            "USAGE_TRUST": self.USAGE_TRUST,
            "TABLE_CARD": self.TABLE_CARD,
            "INSTITUTIONAL_KB": self.INSTITUTIONAL_KB,
            "EVAL_CANARY": self.EVAL_CANARY,
            "WORKFLOWS_V2": self.WORKFLOWS_V2,
            "OFFLINE_CONTEXT": self.OFFLINE_CONTEXT,
            "CODE_ENRICH_PLUS": self.CODE_ENRICH_PLUS,
            "GOLDEN_SQL": self.GOLDEN_SQL,
            "NOTION_KB": self.NOTION_KB,
            "LEAN_TOOLS": self.LEAN_TOOLS,
            "DOC_ACL": self.DOC_ACL,
            "DOC_KNOWLEDGE": self.DOC_KNOWLEDGE,
            "AUTOFILL_AGENT_OVERVIEW": self.AUTOFILL_AGENT_OVERVIEW,
            "CHART_GUARDRAIL": self.CHART_GUARDRAIL,
            "INSIGHT_ENGINE": self.INSIGHT_ENGINE,
            "KPI_LAYER": self.KPI_LAYER,
            "DASHBOARD_COMPOSER": self.DASHBOARD_COMPOSER,
            "DATA_PREP_GATE": self.DATA_PREP_GATE,
            "AUTO_EDA": self.AUTO_EDA,
            "ADV_METHODS": self.ADV_METHODS,
            "SAFETY_EVALS": self.SAFETY_EVALS,
            "READONLY_ENFORCE": self.READONLY_ENFORCE,
            "ASSET_MATERIALIZE": self.ASSET_MATERIALIZE,
            "GOTCHA_MEMORY": self.GOTCHA_MEMORY,
            "EVAL_HARNESS": self.EVAL_HARNESS,
            "EVAL_SCHEDULE_ENABLED": self.EVAL_SCHEDULE_ENABLED,
            "DOC_KNOWLEDGE": self.DOC_KNOWLEDGE,
            "RESULT_CACHE": self.RESULT_CACHE,
            "PARQUET_RESULTS": self.PARQUET_RESULTS,
            "AUTO_TABLE_RELEVANCE": self.AUTO_TABLE_RELEVANCE,
            "CONNECTOR_AUTO_SYNC": self.CONNECTOR_AUTO_SYNC,
            "LEARN_FROM_DATA": self.LEARN_FROM_DATA,
            "HOT_START": self.HOT_START,
            "MOA": self.MOA,
            "QUERY_LEARNING": self.QUERY_LEARNING,
            "MERGE_SAME_SCHEMA": self.MERGE_SAME_SCHEMA,
            "SMART_HEADER": self.SMART_HEADER,
            "TOTAL_ROW": self.TOTAL_ROW,
            "AUTO_MAP_GLOSSARY": self.AUTO_MAP_GLOSSARY,
            "ROBUST_INGEST": self.ROBUST_INGEST,
            "INGEST_RECONCILE": self.INGEST_RECONCILE,
            "INGEST_SELFHEAL": self.INGEST_SELFHEAL,
            "AUTOEDA_AUTOAPPROVE": self.AUTOEDA_AUTOAPPROVE,
            "SOURCE_SYNC_GATE": self.SOURCE_SYNC_GATE,
            "PERSIST_WAREHOUSE": self.PERSIST_WAREHOUSE,
            "ONE_TABLE_MERGE": self.ONE_TABLE_MERGE,
            "SMART_SOURCE_NAME": self.SMART_SOURCE_NAME,
            "COLUMN_PROFILE": self.COLUMN_PROFILE,
            "DATA_VALIDATION": self.DATA_VALIDATION,
            "DATA_TYPING": self.DATA_TYPING,
            "RATIO_METRICS": self.RATIO_METRICS,
            "LOGIC_PARSER": self.LOGIC_PARSER,
            "DEF_REGISTRY": self.DEF_REGISTRY,
            "VERIFIED_GOLDENS": self.VERIFIED_GOLDENS,
            "QUERY_CORRECTION": self.QUERY_CORRECTION,
            "INGEST_BRAIN": self.INGEST_BRAIN,
            "AUTOTRAIN_ON_UPLOAD": self.AUTOTRAIN_ON_UPLOAD,
            "ROBOT_DOCK": self.ROBOT_DOCK,
            "CONTEXT_COMPACT": self.CONTEXT_COMPACT,
            "SKILL_OPTIMIZE": self.SKILL_OPTIMIZE,
            "SUBAGENTS": self.SUBAGENTS,
            "RECURSIVE": self.RECURSIVE,
            "FOLLOWUPS": self.FOLLOWUPS,
            "SCOPE_GATE": self.SCOPE_GATE,
            "DASH_VERSIONS": self.DASH_VERSIONS,
            "DOMAIN_PACKS": self.DOMAIN_PACKS,
            "PROMPTS_LIBRARY": self.PROMPTS_LIBRARY,
            "USER_AVATAR": self.USER_AVATAR,
            "NOTIFICATIONS_INBOX": self.NOTIFICATIONS_INBOX,
            "SERVICE_ACCOUNTS": self.SERVICE_ACCOUNTS,
            "CONNECTION_GRANTS": self.CONNECTION_GRANTS,
            "AUTO_PUBLISH": self.AUTO_PUBLISH,
            "FILE_REFERENCES": self.FILE_REFERENCES,
            "MCP_GATEWAY": self.MCP_GATEWAY,
            "USD_QUOTA": self.USD_QUOTA,
            "STANDALONE_CONNECTORS": self.STANDALONE_CONNECTORS,
            "TREE_LAZYLOAD": self.TREE_LAZYLOAD,
            "SIDEBAR_ACTIVITY_SORT": self.SIDEBAR_ACTIVITY_SORT,
            "GLOBAL_EVALS_NODE": self.GLOBAL_EVALS_NODE,
            "LOCALIZED_FOLLOWUPS": self.LOCALIZED_FOLLOWUPS,
            "WEEK_START": self.WEEK_START,
            "PDF_HYDRATION": self.PDF_HYDRATION,
            "PACK_AUTOBIND": self.PACK_AUTOBIND,
            "PACK_ROUTER": self.PACK_ROUTER,
            "TEACH_BOX": self.TEACH_BOX,
            "PROFILE_V2": self.PROFILE_V2,
            "PROACTIVE_INSIGHTS": self.PROACTIVE_INSIGHTS,
            "SENSE_MAKING": self.SENSE_MAKING,
            "AUTO_MODEL": self.AUTO_MODEL,
            "FORECAST": self.FORECAST,
            "DLT_INGEST": self.DLT_INGEST,
            "FULL_PIPELINE": self.FULL_PIPELINE,
            "POWERBI_USER": self.POWERBI_USER,
            "CONNECTOR_AS_AGENT": self.CONNECTOR_AS_AGENT,
            "CONNECTOR_ROBUSTNESS": self.CONNECTOR_ROBUSTNESS,
            "SCOPED_INSTRUCTIONS": self.SCOPED_INSTRUCTIONS,
            "PROMPT_SCOPE": self.PROMPT_SCOPE,
            "CONNECTOR_JOURNEY_V2": self.CONNECTOR_JOURNEY_V2,
            "PER_USER_CONNECTOR": self.PER_USER_CONNECTOR,
            "ADAPTIVE_CONNECT": self.ADAPTIVE_CONNECT,
            "MS_UNIFIED_SIGNIN": self.MS_UNIFIED_SIGNIN,
            "GOLDEN_QUERIES": self.GOLDEN_QUERIES,
            "VERIFIED_METRICS": self.VERIFIED_METRICS,
            "SEMANTIC_SEARCH": self.SEMANTIC_SEARCH,
            "CODE_ENRICH": self.CODE_ENRICH,
            "AGENT_TEMPLATES": self.AGENT_TEMPLATES,
            "FOLDER_SYNC": self.FOLDER_SYNC,
            "USER_GROUPS": self.USER_GROUPS,
            "AGENT_CONNECTORS": self.AGENT_CONNECTORS,
            "GROUP_ACCESS": self.GROUP_ACCESS,
            "FILE_BROWSER": self.FILE_BROWSER,
            "AGENT_REPORTS": self.AGENT_REPORTS,
            "RICH_REPORT_EMAIL": self.RICH_REPORT_EMAIL,
            "ONECLICK_ARTIFACTS": self.ONECLICK_ARTIFACTS,
            "OUTPUT_CUSTOMIZE": self.OUTPUT_CUSTOMIZE,
            "AUTO_ARTIFACT": self.AUTO_ARTIFACT,
            "FAST_LANE": self.FAST_LANE,
            "WARM_SESSION": self.WARM_SESSION,
            "PLANNER_COLLAPSE": self.PLANNER_COLLAPSE,
            "BI_SNAPSHOT": self.BI_SNAPSHOT,
            "FAST_CODEGEN": self.FAST_CODEGEN,
            "WAREHOUSE_CACHE": self.WAREHOUSE_CACHE,
            "SUBPROCESS_SANDBOX": self.SUBPROCESS_SANDBOX,
            "SUBPROCESS_SANDBOX_LIVE": self.SUBPROCESS_SANDBOX_LIVE,
            "SANDBOX_PUSHDOWN": self.SANDBOX_PUSHDOWN,
            "SMART_VIZ": self.SMART_VIZ,
            "AUTO_FORMAT": self.AUTO_FORMAT,
            "BRAND_PALETTE": self.BRAND_PALETTE,
            "PARAM_TEMPLATES": self.PARAM_TEMPLATES,
            "STARTER_REFRESH": self.STARTER_REFRESH,
            "BI_MODEL_INTROSPECT": self.BI_MODEL_INTROSPECT,
            "RESULT_NARRATIVE": self.RESULT_NARRATIVE,
            "CROSS_SOURCE_UNIFY": self.CROSS_SOURCE_UNIFY,
            "DATA_QUALITY": self.DATA_QUALITY,
            "VALUE_NORMALIZE": self.VALUE_NORMALIZE,
            "AGENT_PLAN": self.AGENT_PLAN,
            "COWORK_PANEL": self.COWORK_PANEL,
            "SMART_UPLOAD": self.SMART_UPLOAD,
            "TRAIN_ROUTING": self.TRAIN_ROUTING,
            "AUTOPILOT_V2": self.AUTOPILOT_V2,
            "SMART_WORKBOOK": self.SMART_WORKBOOK,
            "SMART_SLIDES": self.SMART_SLIDES,
            "SMART_DASHBOARD": self.SMART_DASHBOARD,
            "FOLLOWUP_FASTPATH": self.FOLLOWUP_FASTPATH,
        }


flags = HybridFlags()
