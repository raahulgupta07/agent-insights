# Upstream Feature Backlog — bagofwords → our fork

Ranked list of features from upstream `bagofwords1/bagofwords` releases to consider porting.
Method + rules = [UPSTREAM_SYNC.md](UPSTREAM_SYNC.md). Our version = VERSION_HYBRID 1.63.0;
upstream latest = **v0.0.428** (2026-06-30). No shared git ancestry → **port file-level, flag-gated**.

Status: `WANT` port · `HAVE` we built equivalent · `TRIAGE` decide · `SKIP` not needed
Effort: files are mostly **pure ADDS** (low conflict) unless noted.

Snapshot date: 2026-07-01. Re-run `scripts/upstream_triage.sh <from> <to>` to refresh.

---

## Top picks (high value, low conflict = pure new files)

### 1. Prompts — save & reuse prompts  (v0.0.426, +training-mode in v0.0.428)  — WANT
Save/parametrize/reuse prompts; surfaces as PromptCard in the box.
- BE: `ai/tools/implementations/{create,edit,search}_prompt.py` + schemas · `models/prompt_run.py` ·
  `models/prompt_data_source_association.py`
- FE: `components/prompt/{PromptCard,PromptEditModal,PromptParametersModal,ModeSelector,ModelSelector}.vue`
- Port: pure adds + one nav hook. Flag `HYBRID_PROMPTS`.

### 2. Service accounts — API keys for headless use  (v0.0.428)  — WANT
Non-human accounts to call the API (automation, embed). Pairs with our gateway work.
- BE: `models/service_account.py` · `routes/service_account.py` · `services/service_account_service.py`
  · `schemas/service_account_schema.py` · mig `add_service_accounts`
- FE: `components/ServiceAccountsManager.vue`
- Port: pure adds. Flag `HYBRID_SERVICE_ACCOUNTS`. Re-author mig idempotent.

### 3. Cost console — LLM spend by user/agent/group  (v0.0.423)  — WANT
Spend tracking + monthly quota. Good for multi-tenant billing visibility.
- BE: `ai/llm/usage_attribution.py` · mig `usdquota01_add_monthly_spend_limit_usd`
- FE: `pages/monitoring/cost.vue`
- Port: mostly add + hook LLM call sites for attribution. Flag `HYBRID_COST_CONSOLE`.

### 4. Notifications system  (v0.0.426)  — TRIAGE (we have a bell; compare)
In-app notify + inbox.
- BE: `models/notification.py` · `routes/notification.py` · `services/{inbox,notify}_service.py` ·
  `ai/tools/implementations/notify.py`
- FE: `components/NotificationModal.vue`
- Check vs our existing notif drawer before porting; may only want the agent `notify` tool.

---

## Knowledge / self-learning cluster  (v0.0.415)  — TRIAGE (overlaps our pipeline)
Upstream's take on continual learning + review — overlaps our verified-golden pipeline + KPI-Kinds.
- BE: `models/review_item.py` · `models/agent_automation_run.py` · `routes/{review,agent_reliability}.py`
  · `services/{review_service,review_producers,agent_reliability_service,suggestion_merge,text_hunks}.py`
- FE: `components/{KnowledgeExplorer,ReviewFeed,AgentEvalsPanel,AgentAutomationSettings,NewAgentWizardModal}.vue`
- Decision: mine for ideas (review queue, agent reliability score) but our train pipeline is more
  doc-verified. Don't wholesale-port — cherry-pick `review_service` + `KnowledgeExplorer` if useful.

## MCP tool gateway  (v0.0.428)  — TRIAGE
Agents call MCP tools via a connection gateway; file materialization.
- BE: `ai/tools/mcp/{execute_mcp,list_agent_tools}.py` · `services/{connection_tool_gateway,mcp_dcr_service}.py`
- We already have `enable_mcp_tools`; check gap before porting.

## Connectors  — SKIP unless needed
- Gmail: `data_sources/clients/graph_mail_client.py` (v0.0.428)
- Infor OLAP / XMLA: `analysis_services_client.py`, `xmla_base.py` (v0.0.417/423)
- Port only when a customer needs that source.

## Infra  — WANT (separate track)
- **uv migration** (v0.0.416) — dependency mgmt to `uv` + High/Critical vuln fixes. Evaluate against
  our baked image; security value. Do as its own PR, not bundled with a feature.

## HAVE already (skip / compare only)
- Follow-up suggestions (`FollowUpSuggestions.vue`, v0.0.423) — we built HYBRID_FOLLOWUPS.
- Skills / read_skill tool (v0.0.415) — we have skill-exec.
- Scheduled reports / run-on-demand (v0.0.427) — we have HYBRID_AGENT_REPORTS.

---

## How to port one (checklist)
1. `git diff <prevTag> <tag> -- <path>` — read the feature.
2. `git checkout <tag> -- <newfile>` for pure adds → rename bow→dash, keep bow_ token prefixes.
3. Conflicting edits (agent_v2, hybrid_flags, prompt box) → re-implement by hand behind `HYBRID_*`.
4. Migration → re-author idempotent alembic rev in OUR chain (don't import upstream's).
5. Test flag ON (prove) + OFF (inert). Bake docker-commit + bump VERSION_HYBRID + CHANGELOG_HYBRID.
