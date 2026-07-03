# Shared Memory + Dash-Inspired Hardening — v1.85 → v1.87

> One-file reference for everything built 2026-07-03. Self-learning agent memory that
> compounds across users **without leaking data**, plus 5 hardening mechanisms adopted
> from agno-agi/dash. All flag-gated, default OFF, ON for org `7d372305`. Backend +
> minimal FE. Commits `da05ebad` (1.85) · `36ecdcf8` (1.86) · `4992cade` (1.87), all
> pushed to `origin/feature/table-relevance-overview`. **NOT yet baked into the image
> (hot-cp + fe-sync = EPHEMERAL) and NO PR to dev yet.**

---

## 1. The core idea

Agents learn once and reuse ("how it was done before") — but a learning is shared only
with users who have the **same data**, and only the *method* travels, never the values.

**Two planes, one store (`agent_knowledge`):**
- **SHARED** — keyed by a SCOPE that is identical only for same-access users → safe to share.
- **PRIVATE** — keyed by `user_id` → never crosses users.

**Three tiers (`scope_kind`):**
| tier | scope_kind | scope_key | who reads it |
|---|---|---|---|
| Global | `org` | organization_id | **every agent** in the org |
| By-data | `model` / `schema` / `file` | PBI datasetId / DB schema-sig / file-sig | users who hold that data |
| Personal | `user` | user_id | only that user |

**Isolation falls out of the key:** retrieval filters `WHERE (scope_kind,scope_key) IN (viewer's own scopes ∪ ('org',org) ∪ ('user',me))`. A user physically cannot receive a scope they don't hold. No separate ACL.

**Leak firewall:** before a fact enters a SHARED tier it is sanitized — result rows, WHERE constants, ids, dates, emails, GUIDs, big/decimal numbers stripped; only table/column names + query STRUCTURE (`{value}` templates) + business-meaning prose survive. Private tier kept raw for its owner.

**Singularize:** unique `(org, scope_kind, scope_key, kind, source_hash)`. Re-learning bumps `verified_count`; promotes pending→active at ≥2 OR an explicit `verified=True`.

---

## 2. Data model

Table `agent_knowledge` (mig `agentknow1`, down_revision `colprofile1`; no FK — enrichment convention):
```
id, organization_id, scope_kind, scope_key, kind, title, content_json, text,
source_hash, verified_count, created_by_user_id, data_source_id, status,
created_at, updated_at, deleted_at
UNIQUE (organization_id, scope_kind, scope_key, kind, source_hash)
```
`kind ∈ {meaning, join, query_template, dax_template, mistake, howto}`
`status ∈ {pending, active, rejected}` — only `active` is injected.

**LANDMINE:** SEPARATE from the pre-existing `agent_memories` table + `HYBRID_AGENT_MEMORY` flag (that's the MemGPT remember/recall scratchpad). This feature is `HYBRID_SHARED_MEMORY` + table `agent_knowledge`. Do not conflate.

---

## 3. Backend files (`backend/app/services/knowledge/`)

| file | role |
|---|---|
| `scope_resolver.py` | agent → scope keys. `model_scope_keys` (PBI `metadata_json.powerbi.datasetId`), `schema_signature`, `file_signature`, `private_scope(user)`, `org_scope(org)`, `resolve_agent_scopes`. `stable_hash` shared util. |
| `sanitize.py` | leak firewall. `sanitize_content` (drops data-keys, redacts literals, drops bare scalars/data-value strings), `sanitize_template` (literals→`{value}`), `redact_text`, `looks_like_data_value`. |
| `access.py` | `visible_scope_pairs(user, scopes, org)` (+org +private), `can_view(row,...)` (org=all, user=owner-only, else intersection). |
| `capture.py` | write+singularize. `capture`, `capture_verified_query` (query→template), `capture_mistake` (error→fix), `capture_global` (org tier). `status_for` gate, `content_hash`, `prep_share`. |
| `retrieve.py` | `recall_items` (access-gated query, ranked verified_count desc), `recall_block` (planner injection text), `provenance` (chip data). Always includes global tier. |
| `materialize.py` | `hot_asset_candidates` (query_template verified_count≥3; materializable only relational SQL not DAX). |

**Hooks (flag-gated, fail-soft):**
- Capture verified: `routes/pipeline._save_golden` → `capture_verified_query`.
- Capture mistake: `ai/tools/implementations/create_data.py:~1480` error-recover path → `capture_mistake`.
- Retrieve/inject: `ai/context/builders/instruction_context_builder.build._inject_shared_memory` → appends ONE synthetic `<instruction>` with `recall_block`.
- Provenance: `services/completion_service.py` fills `shared_memory` on the completion (stream + non-stream); schema `schemas/completion_v2_schema.py`.

---

## 4. Endpoints (`routes/data_source.py`, mounted `/api`)

| method + path | purpose | flag |
|---|---|---|
| `GET /data_sources/{id}/memory` | per-agent facts (scope-filtered) | SHARED_MEMORY |
| `GET /memory/shared` | org-wide, grouped by scope, `tier` tagged (global/data/personal, ordered) | SHARED_MEMORY |
| `DELETE /memory/{id}` | soft-delete (creator or org-admin) | — |
| `PATCH /memory/{id}` | demote/reactivate `{status}` | — |
| `GET /memory/hot-assets` | materialize candidates | ASSET_MATERIALIZE |

`_can_curate` = row creator OR `resolve_permissions` FULL_ADMIN / manage_connections.

---

## 5. Frontend

| surface | file |
|---|---|
| Per-agent **Memory** tab (Configure group) | `pages/agents/[id]/memory.vue` (+ registered in `layouts/data.vue`: tab list, `TAB_ICONS`, `TAB_GROUPS`) |
| Org-wide **Shared Memory** page (3 tier sections) | `pages/memory/shared.vue` (+ nav item `shared-memory` in `composables/useAppNav.ts`) |
| "used shared memory · scope (N)" chip | `pages/reports/[id]/index.vue` (system message, v-if guarded) |
| Row Remove (admin curate) | in both memory pages |

---

## 6. Dash-inspired hardening (v1.87) — 5 features

Source: deep research of **agno-agi/dash** (Analyst/Engineer/Leader team, 6-layer context, dual-schema, 5-category evals). Adopted the loop + safety patterns; SKIPPED the 3-agent team / AgentOS / Slack (don't fit our single-planner model).

| # | feature | flag | files | note |
|---|---|---|---|---|
| 1 | **Safety/reliability evals** | `HYBRID_SAFETY_EVALS` | `services/evals/safety_evals.py`, wired `eval_harness.save_completion_as_golden` | 4 LLM-judges (security/governance/boundaries/routing) + deterministic FAIL-CLOSED pre-LLM on secrets/destructive-SQL; infra-err→inconclusive-pass; log-only (no mig). Boundaries judge verifies this isolation. |
| 2 | **Structural read-only** | `HYBRID_READONLY_ENFORCE` | `data_sources/clients/postgresql_client.py`, `ai/code_execution/code_execution.py`, `services/data_source_service.py` | Postgres conn `default_transaction_read_only=on` (DB-enforced) + runtime chokepoint guard `_enforce_readonly_query` on `QueryCapturingClientWrapper.execute_query`. |
| 3 | **Materialize hot metrics** | `HYBRID_ASSET_MATERIALIZE` | `services/knowledge/materialize.py` + `GET /memory/hot-assets` | detect+surface only; DAX not materializable. |
| 4 | **Gotchas → Global memory** | `HYBRID_GOTCHA_MEMORY` | `services/knowledge_gotchas.py`, wired `ingest/post_ingest.py:557` | mixed_type/type_coercion→mistake; near-dup/near-constant/all_null→meaning. |
| 5 | **`remember_this` tool** | reuses `HYBRID_SHARED_MEMORY` | `ai/tools/implementations/remember_this.py` (+ schema) | agent-callable save (dash `save_validated_query`); auto-registers → 45 tools. |

### v1.87 AUDIT finding (important)
Before D2, the agent SQL path was **string-only and jailbreakable**: the AST scanner only checked string-*literal* args to executors, so SQL built via a variable / concat / f-string (`Name` node) reached the DB unscanned, and the runtime `QueryCapturingClientWrapper.execute_query` had NO check. Now guarded at the runtime chokepoint **and** connection level.

---

## 7. Flags (all `hybrid_flags.py`, 3-place, default OFF, DB-override ON org 7d372305)

```
HYBRID_SHARED_MEMORY      HYBRID_SAFETY_EVALS      HYBRID_READONLY_ENFORCE
HYBRID_ASSET_MATERIALIZE  HYBRID_GOTCHA_MEMORY
```
OFF ⇒ byte-identical (nothing captured, injected, judged, or enforced).

---

## 8. Verification (what was proven)

- Firewall/access units 9/9; capture DB tests (dedup 1 row, count 1→2, promote, private-active); safety-eval offline unit (fail-closed secret/DDL, inconclusive-on-infra); gotcha translation unit; read-only unit (DELETE/DROP blocked, `SELECT call, update_date` NOT flagged — no landmine); materialize DAX-vs-SQL unit.
- Live (org 7d372305, demo@test.com / CityAgent#2026): mig applied; 5 flags read True after restart; `/api/memory/shared` shows `tier=global org:…` first + data groups; seeded global "exclude total rows" visible cross-agent; `DELETE /memory/{id}` soft-deletes; `/api/memory/hot-assets` `{enabled:true}`; all imports + tool registry green.

---

## 9. Deferred / next (future recall)

1. **Durable image BAKE** — v1.85–1.87 all hot-cp + fe-sync (EPHEMERAL, revert on `--force-recreate` onto stale image). Run `bash scripts/build.sh` → verify image has code + mig `agentknow1` → `docker compose -f docker-compose.build.yaml up -d --force-recreate app`.
2. **PR to dev** — `https://github.com/raahulgupta07/rahulai-dash/compare/dev...feature/table-relevance-overview` (gh not authed; branch flow feature→dev→staging→main).
3. **F2 read-only follow-ups:** (a) dedicated read-only Postgres ROLE (GRANT SELECT — airtight vs session-resettable `SET`); (b) connection-level RO for other writable SQL connectors (mysql/mssql/snowflake/redshift — currently runtime-guard only); (c) DuckDB URI write funcs `COPY…TO`/`EXPORT DATABASE` (low risk, ephemeral).
4. Materialize: actually build the asset (reuse `build_data_asset` / ENGINEER_ASSETS) for relational candidates — v1 is detect+surface only.
5. Tier-4 idea if ever needed: cross-org global is intentionally NOT built (org is the ceiling).

---

## 10. Landmines

- `HYBRID_SHARED_MEMORY` ≠ `HYBRID_AGENT_MEMORY` (different feature + table).
- Baked image predates the v1.87 flags — DB override + restart works on the host container, but a rebake is needed for them to live in-image.
- Flags read True only after `load_overrides_from_db` (bare `docker exec python` reads False); one `docker restart ca-app` converges `--workers 4`.
- Sanitizer is CONSERVATIVE by design — ambiguous content is dropped from sharing (a false drop costs a little reuse; a false keep leaks data).
- FE served via PWA service worker (CacheFirst `_nuxt/*`) → hard-refresh Cmd+Shift+R to see new nav/tabs.
