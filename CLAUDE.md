# CLAUDE.md — CityAgent Analytics

Guide for any AI agent working in this repo. This is a **hybrid fork of bagofwords (bow), rebranded Dash**
on branch `hybrid-brain`. Read this before touching anything.

## What this project is
Single-project agentic-analytics platform = **Dash chassis** (FastAPI + Nuxt, own AgentV2
plan/execute/reflect loop, ~46 warehouse connectors, multi-tenant, Instructions + approval
gate, MCP, observability) **merged natively** with:
- **dash patterns** (agno-agi/dash) — dual-schema, Engineer view-builder, DB-level read-only.
  Ported as native Dash code. Agno is NOT run. `reference/dash/` is a read-only blueprint only.
- **Karpathy 2nd-Brain** — gated learned memories, reasoning-cache, self-distill, insight
  daemon, entity/correlation graph. All default-OFF, leader-gated.
- **Self-service Skills** — Claude-style SKILL.md + progressive disclosure, scope
  personal/org/global, promote-from-chat authoring.
- **DuckDB federation** — live↔stored 2-way query, cross-source correlation via gated key-map.

Design: `docs/ARCHITECTURE.html` (v0.2). Tasks: `docs/PENDING.md`. Progress log: `docs/PROGRESS.md`.

## HARD RULES
1. **NEVER pull `bagofwords/bagofwords:latest`.** Always build our own image
   `cityagent-analytics:dev` from this repo's Dockerfile. All 3 composes do this.
2. **Pre-pull base images before building** (Docker Hub flakes with `registry EOF`):
   `ubuntu:24.04`, `rust:1-slim-bookworm`, `pgvector/pgvector:pg18` — pull with retry, then build
   runs from cache. (rust is only the qvd2parquet/QlikView converter; ubuntu carries
   chromium/LibreOffice/ODBC — can't drop without rewriting the Dockerfile.)
   `scripts/build.sh` does this pre-pull-with-retry automatically.
   **Split build (refactor):** the heavy runtime apt (LibreOffice, MS ODBC, chromium system
   deps) now lives in `Dockerfile.base` → image `cityagent-base:dev`, built ONCE. The app
   `Dockerfile` is `FROM cityagent-base:dev` and uses BuildKit cache mounts for pip/yarn/cargo;
   JS libs + RDS cert + tiktoken are vendored under `vendor/` (no build-time download). So a
   code-change rebuild no longer re-downloads dependencies (~20min → seconds-2min).
   `Dockerfile.orig` is the pre-refactor backup.
3. **Touch Dash core MINIMALLY.** Prefer new files/modules + hook points over rewrites.
   This is a fork of a fast-moving OSS base; every core edit = future rebase tax.
4. **Everything new is flag-gated** (`app/settings/hybrid_flags.py`), default OFF, so a fresh
   deploy behaves exactly like upstream Dash until a flag is on.
5. **Everything learned is gated** — memories/shared-skills/correlations land in `pending`,
   go live only after approval. Reuse Dash's Instruction build/approval; do NOT build a new gate.

## LLM = OpenRouter ONLY
No Agno → no openai 2.x → Dash keeps `openai 1.107`. Configure as Dash `custom` provider
(`base_url=https://openrouter.ai/api/v1`, per-org DB row, Fernet-encrypted key).
VERIFIED: `app/ai/llm/clients/openai_client.py` `inference_stream_v2` = Chat Completions
streaming tool_calls → OpenRouter-compatible with PlannerV3. Pin **tool-capable** models
(default `anthropic/claude-sonnet-4` + `openai/gpt-4o-mini` router). Seed via
`backend/scripts/seed_openrouter.py` (HTTP, post-onboarding).

## Feature flags (`app/settings/hybrid_flags.py`, env `HYBRID_*`, all default OFF)
`DUAL_SCHEMA · ENGINEER_ASSETS · ANSWER_CACHE · BRAIN_READ · DISTILLER · QUERY_CACHE ·
SKILLS · FEDERATION · BRAIN_GRAPH · INSIGHT_DAEMON · QUOTAS · SEMANTIC_LAYER · METRICS_CATALOG ·
STUDIOS`.
Access via `from app.settings.hybrid_flags import flags`. Env-only daemon knob:
`STUDIO_LEARN_DAEMON_ENABLED` (default 0) + `STUDIO_LEARN_*` thresholds.

## Fast dev lane (FE iteration without rebuild)
Prod image (:3007) serves a compiled `nuxt generate` static bundle — no hot-reload. For daily
frontend work, run the **Nuxt dev server on :3000**:
```
cd frontend && DASH_BACKEND=127.0.0.1:3007 yarn dev   # hot-reload, proxies /api -> ca-app:3007
```
Two lanes: **:3000** = dev/hot-reload, **:3007** = baked prod image (FE changes need a rebuild OR a
generate+`docker cp` FE-sync). `nuxt.config.ts` proxy targets are env-driven (`DASH_BACKEND`, default
8000). Host node22 at `~/.hermes/node/bin` + global `yarn@1.22.22` (no corepack).
- **NEVER run `yarn generate`/`yarn build` while `yarn dev` is live in the same dir** — corrupts
  `.nuxt` → blank app. Recover: kill nuxt, free :3000, `rm -rf .nuxt .output node_modules/.cache
  node_modules/.vite`, restart dev.
- **A new `components/**/*.vue` created mid-session is NOT picked up by Nuxt auto-import until the
  dev server restarts** — the component renders blank, silently. Restart dev after adding any new component.
- FE API calls use `useMyFetch` (auto-injects Authorization + X-Organization-Id, prepends `/api`) →
  use BARE paths (`/knowledge/queries`, NOT `/api/knowledge/...` — double-prefix 404s).

## Knowledge Layer (dash-style semantic model — Phases 0-7 done, flag-gated, approval-only)
Org-shared, per-data-source, gated port of dash's structured Knowledge Layer onto the Dash chassis.
Nuxt page `/knowledge` (nav in `layouts/default.vue`, i18n `nav.knowledge`) with 5 tabs:
**Semantic | Metrics | Queries | Assets | Review** (`pages/knowledge/index.vue`; components auto-imported
from `components/knowledge/`). All routes on ONE router `app/routes/knowledge.py`
(`APIRouter(prefix="/api/knowledge")`, included in main.py). Migration chain off head:
`v1e2c3t4o5r6 → k1nowl2edge3` (semantic) `→ m2etrics3cat4` (metrics) `→ q3uery4lib5` (query lib)
`→ b4rain5graph6` (brain_graph_edges); **head `b4rain5graph6`** (single head, applied).
- **Semantic** (`models/semantic_table.py`, `flags.SEMANTIC_LAYER`): per-table description/use_cases +
  per-column meaning. `GET /semantic?data_source_id=` seeds empty rows from schema (idempotent).
- **Metrics** (`models/metric_definition.py`, `flags.METRICS_CATALOG`): name→definition→table_ref→sql_calc.
  `POST /metrics/{id}/test` runs sql_calc read-only (`_is_read_only_sql` guard + `get_client().aexecute_query`, 100-row cap).
- **Queries** (`models/query_library.py`): saved SQL + `POST /queries/{id}/run` (same guard/executor, run_count++).
- **Context wiring (Ph4)**: only `status=='approved'` rows reach the agent. Builders
  `context/builders/{semantic,metrics}_context_builder.py` + sections + tool `resolve_metric`
  (native `tools/implementations/`, auto-registered). Render path (all 4 steps or it silently no-injects):
  `builder.build()` → `ContextHub._static_cache` → `get_view()`→`StaticSections` → `agent_v2.py` `.render()`
  appends to planner instructions. **Touches 3 core files** (`context_hub.py`, `context_view.py`, `agent_v2.py`)
  — mirrors the brain/skills path exactly; rebase-tax noted.
- **Self-learning (Ph5)**: `app/ai/brain/knowledge_proposer.py` fires after the distiller on 👎
  (gate `DISTILLER AND (SEMANTIC_LAYER OR METRICS_CATALOG)`) → UPSERTs `status='pending'` proposals (never
  overwrites approved). Trigger in `completion_feedback_service.py` (same fresh-session/reload-by-PK/strong-ref
  discipline as distiller). `GET /knowledge/pending` + `POST /knowledge/{kind}/{id}/approve|reject`
  (kind∈semantic|metric|query; reject is soft→'rejected'). FE Review tab. Pending rows are auto-invisible
  to the agent (approved-only invariant). No migration — `status` is a plain String, 'pending' just works.
- **Engineer Assets (Ph6)**: SURFACES existing assets — NO new model/migration. `build_data_asset` tool
  already records each `analytics.*` view as an `Instruction` (`category='data_asset'`, `ai_source='engineer_asset'`,
  `structured_data={object,kind}`). `GET /knowledge/assets` reads those rows (org-scoped, flag `ENGINEER_ASSETS`,
  empty when OFF) + `POST /knowledge/assets/{id}/approve|reject` flips Instruction.status published↔draft.
  Schema `schemas/knowledge_assets_schema.py`. FE `AssetsTab.vue`. Assets carry NO per-DS link → `data_source_id`
  is echo-only. LANDMINE: register `/assets/{id}/approve` BEFORE the catch-all `/{kind}/{id}/approve` (else 'assets'
  treated as a pending-kind).
- **Embed + AI-suggest (Ph7)**: all 5 tabs take optional `dataSourceId` prop → pin DS + hide picker
  (`showPicker`/`activeDataSourceId`). Reusable `components/knowledge/KnowledgePanel.vue` (props `dataSourceId?`,
  `hideReview?`) owns tab bar + AI-suggest button; `pages/knowledge/index.vue` is now just `<KnowledgePanel/>`
  (picker mode). Embedded `<KnowledgePanel :dataSourceId>` in per-DS `pages/onboarding/data/[ds_id]/context.vue`.
  **AI-suggest**: `POST /knowledge/ai-suggest/{data_source_id}` body `{focus:semantic|metrics|both}` — introspects
  schema (`get_client().get_schemas()`, cap 40 tbl/30 col), LLM extracts table descs + metrics, writes `status='pending'`
  via Phase-5 `knowledge_proposer` helpers (new fn `propose_knowledge_from_schema`, approval-safe, never raises) →
  Review tab. Flag gate (`SEMANTIC_LAYER or METRICS_CATALOG`) short-circuits to `{disabled:true}` BEFORE DS lookup/LLM.
  Button renders only when DS pinned (needs concrete schema). Skeletons gated `loading && !items.length`.
NOT yet baked into the image — lives via `docker cp` + dev :3000 (Phase 8 = rebake). Schema file is
`query_library_schema.py` (NOT `query_schema.py` — that's Dash core, don't clobber). New Nuxt component → restart
dev server (auto-import scans on start only). Parallel agents on same file race → confirm on disk after.

## Coding gaps closed (2026-06-18, "finish coding before build") — C1-C4, all flag-gated/default-OFF, NOT committed
Before the Phase-8 bake, four incomplete code paths were finished (subagents, disjoint file ownership to avoid races):
- **C1 BRAIN_GRAPH** — was a flag with **0 consumers, no module**. Built pgvector + recursive-CTE graph
  (**NOT Apache AGE** — AGE dropped, not PG18-ready): migration `b4rain5graph6` + `brain_graph_edges` table,
  `models/brain_graph_edge.py`, `ai/brain/brain_graph.py` (`propose_edges_from_entities` pending/approval-safe +
  `neighbors()` multi-hop CTE), `ai/context/sections/brain_graph.py` + `builders/brain_graph_context_builder.py`,
  wired into `context_hub.py` (`render_brain_graph_section`) + `agent_v2.py` (after BRAIN_READ block). OFF → empty, no DB hit.
- **C2 serving-funnel tiers** — Tier ① answer-cache was already real (only stale "NOT built" comment removed);
  **Tier ③ matview built** (`analytics_engine.py`: `pg_matviews` scan + conservative single-match serve, gated `DUAL_SCHEMA`).
  Funnel order ①→②→③→④ intact; only helper bodies/docstrings changed, not the funnel dispatch.
- **C3 FEDERATION** — `duckdb_engine.snapshot_to_parquet` was `NotImplementedError`; now writes Parquet to S3/MinIO
  (httpfs, env `FEDERATION_S3_*`) or local fallback (`FEDERATION_SNAPSHOT_DIR`), honors `freshness.py` TTL. DuckDB
  `federate()` wired into `code_execution.py` behind `flags.FEDERATION` AND only when run spans ≥2 sources; bounded
  `memory_limit`/spill/threads. No new table/migration (env-driven config). OFF → code-exec byte-identical.
- **C4 skill top-K** — `skill_context_builder.py` was inject-all; now top-K (K=8, `HYBRID_SKILLS_TOP_K`), user-scoped,
  ranked by **token-Jaccard** (reused reasoning-cache idiom — **no embeddings client exists in repo**; a future
  C1-owned migration could add a pgvector column + OpenRouter embeddings and swap `_rank_skills`). Graceful fallback to full catalog.
Verified: single alembic head `b4rain5graph6`, `import main` OK (456 routes), all flag-OFF paths clean no-op.

## Why the Knowledge tabs look empty (NOT a bug — earned/learned layers)
Fresh install + no agent traffic = empty by design. **Semantic** is the only auto-seeded tab (table/column skeletons
from the DS schema on first open; descriptions blank until AI-suggest/human fills → 0% described). **Metrics/Review**
fill from AI-suggest or distiller (👎). **Queries** fills from `QUERY_CACHE` capturing proven SQL on real chat answers.
**Assets** needs `ENGINEER_ASSETS` ON + a `build_data_asset` run. If a tab is *totally blank* (no picker, no empty-state),
that's the stale-dev-server landmine above → restart `yarn dev`.

## "AI Analyst" → "City Agent Analyst" (renamed platform-wide)
FE (`pages/index.vue`, `settings/general.vue`) + BE defaults (report_schema, organization_settings_schema,
ai/agent_v2.py, organization_service, report_service). LANDMINE: a stored
`organization_settings.config.general.ai_analyst_name` overrides the code default → also UPDATE the DB row
(`config` is `json` not jsonb → cast: `jsonb_set(config::jsonb, '{general,ai_analyst_name}', '"City Agent Analyst"')::json`).

## Build & run (local dev, own image)
```
# 1. one command: pre-pulls bases (with retry), builds cityagent-base:dev ONCE,
#    then builds the app image cityagent-analytics:dev via docker-compose.build.yaml.
bash scripts/build.sh
#    Force a base rebuild when system deps (LibreOffice/ODBC/chromium) change:
#    bash scripts/build.sh --rebuild-base
# 2. run our image
docker compose -f docker-compose.build.yaml up -d
curl localhost:3007/health     # ports: APP=3007 (internal 3000), POSTGRES=5439 (see .env)
```
`scripts/build.sh` is the entry point: it pre-pulls `ubuntu:24.04`/`rust:1-slim-bookworm`/
`pgvector/pgvector:pg18` with retry, builds the heavy runtime base `cityagent-base:dev` once
(skipped if it already exists; `--rebuild-base` forces it), then builds the app image. After
the one-time base build, code-change rebuilds are seconds-2min (BuildKit cache mounts +
vendored deps under `vendor/`, no re-download). `Dockerfile.orig` is the pre-refactor backup.

DB = **PostgreSQL 18 + pgvector** (`pgvector/pgvector:pg18`). AGE dropped (not PG18-ready) →
2nd-brain graph = pgvector table + recursive CTE. Migration head `v1e2c3t4o5r6` enables the
`vector` ext. First-ever build (base + app) ~20min (frontend `nuxt generate` forces 6GB Node
heap — give Docker ≥10GB or build stages serially via `--target` so the generate runs alone).

## Boot status (VERIFIED LIVE 2026-06-18)
Full stack builds + boots green. First-run admin via `POST /api/auth/register`
(`{email,password,name}`; first uninvited user auto-creates an org + becomes admin).
Dev admin: `admin@cityagent.io` / `CityAgent#2026` (org "Main Org"). OpenRouter seeded via
`backend/scripts/seed_openrouter.py` (DASH_BASE_URL/DASH_ADMIN_EMAIL/DASH_ADMIN_PASSWORD/
OPENROUTER_API_KEY env); default analysis `anthropic/claude-sonnet-4` + router `openai/gpt-4o-mini`.
**Smoke 1.4 PASSED** — planner ran, claude-sonnet-4 answered through OpenRouter, completion
`status=success`. **A.1 PASSED (2026-06-18) — FULL native tool_use**: chinook demo (`POST
/api/data_sources/demos/chinook`) → `refresh_schema` (11 tables auto-active) → report → agent
ran `create_data` tool → `SELECT COUNT(*) FROM Artist` → "275 rows". Smoke script `/tmp/smoke_a1.py`.
API gotchas: all org-scoped calls need header `X-Organization-Id: <org id from GET /api/organizations>`;
login `POST /api/auth/jwt/login` form-encoded `username/password`; report create body uses
`title` (not name) + `data_sources` (NOT data_source_ids — silently ignored → unlinked report);
`POST /reports/{id}/completions` returns thin body, poll `GET /reports/{id}/completions` for blocks/answer.

**Phase A flag proofs ALL PASS (2026-06-18, flags ON via `.env`):** A.2a/b ANSWER_CACHE funnel ①
(warm 0.2s/157ms vs cold ~20s, `GET /api/funnel/stats` by_tier); A.2c DISTILLER (👎 → ai/learned
pending Instruction, live); A.2d SKILLS (author draft skill from completion). Two real bugs were
found + fixed in our hybrid code: (1) `app/ai/brain/qa_pair.py` resolves Q+A across Dash's TWO
sibling Completion rows (user row=`prompt`, system row=`completion`, paired by `turn_index`) —
distiller + skill-authoring previously read both from one row → got half → no-op; (2) the live
👎 distill worker reloaded org/user by PK in its own session (were detached) + keeps a strong
task ref (asyncio GC). Toggle flags: set `HYBRID_X=1` in `.env` → `up -d --force-recreate app`
(compose lists all 11 as `${HYBRID_X:-0}`, default OFF).

**FULL REBUILD BAKED (2026-06-18) — durable `cityagent-analytics:dev`:** babel pinned 7.26.4
(artifact render fix), CityAgent logo swapped platform-wide (`frontend/public/assets/logo.png` +
`logo-128.png` + `favicon.ico`, source master `cityagent-logo-source.png`), Intercom REMOVED
entirely (module + boot + config + links, 0 refs in bundle), Documentation nav button removed
(left sidebar + home; 3 enterprise `docs.bagofwords.com` help-links inside Settings pages remain).
FE is a compiled static bundle (`nuxt generate` → `.output/public` → served `/app/frontend/dist`);
`.vue`/config edits need a REBUILD to show (no prod hot-reload). Backend `.py` can be hot-iterated:
`docker cp <f> ca-app:/app/backend/... && docker exec ca-app /opt/venv/bin/python -m py_compile <f>
&& docker restart ca-app` (restart preserves cp'd files + flag env; `--force-recreate` reverts to
image). Standalone in-container scripts: `cd /app/backend && PYTHONPATH=/app/backend
/opt/venv/bin/python s.py`, and `import main` first to register all ORM models.

## Conventions
- New tools → `app/ai/tools/implementations/*.py` (auto-registered by ToolRegistry; just drop the file).
  Schemas → `app/ai/tools/schemas/`. Events → `app/ai/tools/schemas/events.py`.
- New context → `app/ai/context/builders/` + register in `context_hub.py`.
- Migrations → chain off the **true single head** (verify: a revision no one lists as
  `down_revision`, accounting for **tuple** down_revisions in merge migrations). Guard
  Postgres-only DDL with `op.get_bind().dialect.name == "postgresql"` (SQLite has no schemas).
- Tests → `backend/tests/unit/` for deterministic mocked tests (run in CI); `@pytest.mark.e2e`
  / `@pytest.mark.ai` for DB/LLM integration.
- Agent-owned schemas in Dash's managed Postgres: `analytics` (Engineer views), `staging` (ingest).
  External connections stay read-only via Dash's existing query path.

## Landmines (learned the hard way)
- Alembic has merge migrations with **tuple** `down_revision` — naive head-finding gives false
  multiple heads. True head (at fork time): `d6d9a78b7b4a`.
- Docker Hub `registry EOF` on base pulls — pre-pull with retry (rule 2).
- `dev`/`build` composes shipped `image: bagofwords/bagofwords:latest` + `pull_policy: always` —
  replaced with build-from-source. Don't reintroduce.
- Dash base error class is `app.errors.app_error.AppError(error_code, message, status_code=...)`,
  NOT `app.errors.AppError`.
- The analytics write guard must check only the **write target's** schema, not every schema
  referenced — an analytics view legitimately SELECTs from public/company data.
- **PG18 data dir**: PG18 images store data in `/var/lib/postgresql` (major-version subdir), NOT
  `/var/lib/postgresql/data`. Mounting `/data` → container errors `unhealthy` on boot. All composes
  mount the parent. (Re-mount → drop the old empty volume first.)
- **`--target` cache ≠ compose cache**: pre-building stages with `docker build --target X` does NOT
  feed `docker compose build`'s cache — compose re-runs the whole Dockerfile. To serialize for RAM,
  build `--target` AND accept compose re-runs, or just `docker compose build` direct (parallel).
- **rtk mangles `docker logs`/`grep`**: it returns a summarized stub. Use `rtk proxy docker logs <c>`
  for raw container logs; read large files with the Read tool, not piped `grep`.
- Email validator rejects `.local` TLD (reserved) — use a real-format domain for admin email.
- Curl'd API JSON can carry control chars (planning glyphs) → `json.loads(..., strict=False)`.
- **Artifact render "Cannot use import statement outside a module"** (blank dashboard): vendored
  `@babel/standalone` must stay PINNED to 7.x in `scripts/download-vendor-libs.sh`. Babel 8
  defaults preset-react `runtime:'automatic'` → injects `import {jsx} from "react/jsx-runtime"`
  into the classic `<script type="text/babel">` (artifact code inlined raw by
  `frontend/utils/artifactIframe.ts`). 7.26.4 = classic runtime → `React.createElement` + global
  React, no import. Do NOT unpin.
- **FE changes are invisible until rebuild** — prod image serves a pre-compiled `nuxt generate`
  bundle, no hot-reload. Backend `.py` is hot-iterable via `docker cp`+`py_compile`+`docker restart`.



## Changelog → `DEVLOG.md`

The full dated per-feature changelog (every `## YYYY-MM-DD` entry from 2026-06-19 on) now lives in
**`DEVLOG.md`**. This file stays the living map: rules, current state, landmines. When you finish a
feature, append the dated entry to `DEVLOG.md` (not here) and update the relevant map section above
if the current state changed.

## Intelligence Layer (dash-parity, 2026-06-25 — see DEVLOG)
8 capabilities closing the gap vs `reference/dash` prompt-context layers. All flag-gated default-OFF,
additive. Flags in `hybrid_flags.py` (each needs @property + `UPGRADE_FLAGS` entry + `snapshot()`):
`HYBRID_PROFILE_V2` (P1 Deep Profiler + P5 Lazy Profile), `HYBRID_PROACTIVE_INSIGHTS` (P2),
`HYBRID_FORECAST` (P3, needs prophet bake), `HYBRID_GOLDEN_QUERIES` (P4), `HYBRID_CODE_ENRICH` (P6),
`HYBRID_VERIFIED_METRICS` (P7), `HYBRID_SEMANTIC_SEARCH` (P8 scaffold). Mig chain
`resultcache1 → goldenq1 → verifmetric1 → hybridsearch1`.
- **UI**: Studio rail group `intelligence` (`pages/studios/[id]/index.vue`), 8 tabs `i_*` →
  `components/studio/StudioIntelligence.vue` (live fetch + real toggle via existing hybrid-flags PUT).
- **Data API**: `routes/intelligence.py` `GET /api/intelligence/layer/{layer}?studio_id=` — read-only,
  org-scoped, fail-soft. profiler/codeenrich=metadata_json, metrics/golden=DB, search=BrainGraphEdge,
  lazy/insights/forecast=note (transient).
- **Default-ON org 55278108**: PROFILE_V2, VERIFIED_METRICS, GOLDEN_QUERIES, PROACTIVE_INSIGHTS via
  `config['hybrid_overrides']`. OFF: CODE_ENRICH (cost), FORECAST (prophet), SEMANTIC_SEARCH (scaffold).
  Per-org flag auto-inherits to all/new agents; true per-agent resolver NOT built.

## Agent Templates — share an agent's best practices (2026-06-25, BAKED)
Export a Studio's data-agnostic know-how (rules/metric-formulas/example-patterns/skills/persona) as a
portable versioned template; others bind it to their columns → their own agent. Flag `HYBRID_AGENT_TEMPLATES`.
- Model `agent_template.py` (`AgentTemplate`: slug+version, scope org/global, status draft/published,
  body_md + manifest JSON). Mig **`agtmpl1`** off `chlogseen1`. Head now `agtmpl1`.
- Contract: frontmatter `requires_columns:[{role,as}]` + `{as}` placeholders in body. Export
  generalizes columns→`{role}` via profile_v2 roles. Placeholder scheme = role-lowercased,
  index-suffixed for dupes (`{measure}`,`{measure_2}`); `requires_columns` = placeholders actually used.
- Services `app/services/templates/`: `exporter.py` (studio→template, strips data/creds),
  `parser.py` (frontmatter, PyYAML+hand-rolled fallback), `binder.py` (auto_match via difflib —
  no embeddings; apply_binding; `instantiate_template` → new Studio, items born **pending**, skills via
  StudioBoundPack, metrics draft). Routes `routes/agent_templates.py` `/api/templates`:
  list/detail/publish/import/delete + `from-studio/{id}` (export) + `{id}/bind-preview` + `{id}/instantiate`.
  All flag-gated + fail-soft. Registered main.py.
- FE: nav **Templates** in Studios group; `pages/templates/index.vue` (gallery) + `[id].vue` (detail) +
  `components/templates/BindWizard.vue` (4-step). **Export as Template** button in studio header
  (`studios/[id]/index.vue`, gated canEdit). Raw golden SQL OFF by default in exports.
- E2E verified live (org 55278108, flag ON): export CRM→template → list → publish → bind-preview →
  instantiate → new Studio created. LANDMINE: `requires_columns` empty until the source studio has
  profile_v2 (train it first); imported items always pending (review gate).
- **v1.4.1 popup journey:** `BindWizard.vue` = MODAL (v-model) from gallery card, 5 steps
  Preview→Data→Map→Review→Build (Map auto-skipped unless existing-source+requires). Step 2 = 3-way
  (existing / connect-upload / **skip**). `instantiate` route ALLOWS empty data_source_ids (skip =
  agent now, placeholders intact, bind later). Gallery "Use template"→openWizard (in place);
  card click→detail.
- **v1.4.2 Studios page UX:** `StudioCard.vue` lifecycle chip draft(no src)→ready(src,0 chats)→
  live(active<7d)→idle from source_count/chat_count/last_active_at — replaces live/idle dot + the
  4-zero stat grid; per-card next step (draft→Add data + "connect data"; ready→train hint;
  live/idle→real stats + Open/Chat); action bar persistent (was hover-only). Removed duplicate ghost
  add-card in `pages/studios/index.vue` (top-right = only add). Demoted nav "New report" to outline
  (`nav/TopNav.vue`) — one filled primary per zone.

## PWA — installable desktop/mobile app (2026-06-25, BAKED)
App installs from the browser (standalone window, dock icon, offline shell). Module `@vite-pwa/nuxt`.
- `nuxt.config.ts` `pwa{}`: manifest (name/short_name, `display:standalone`, `start_url:/`,
  `theme_color #C2683F`, icons 192/512 + maskable), `registerType:autoUpdate`, `devOptions.enabled:false`.
- workbox: `navigateFallback:'/'`, precache shell; **`/api` + `/ws` = `NetworkOnly`** (never cache
  API/auth/data); `_nuxt/*` CacheFirst. `globIgnores` the giant editor blobs (Monaco TS worker ~9MB,
  babel ~3MB) + `maximumFileSizeToCacheInBytes:4MB` — else `yarn generate` ERRORS on precache size.
- icons in `frontend/public/`: `pwa-192x192.png`, `pwa-512x512.png`, `pwa-maskable-512x512.png`,
  `apple-touch-icon.png` (generated from `assets/logo-mark-512.png` via PIL).
- `components/nav/InstallApp.vue` — one-click Install button (catches `beforeinstallprompt`, shows only
  when installable + not already standalone), wired into `nav/TopNav.vue` left of the bell.
- SPA (`ssr:false`) → manifest link + SW register are injected at RUNTIME by the module plugin, NOT in
  static index.html (curl of `/` won't show them; they're in the JS bundle — verify there).
- LANDMINE: **prod install needs HTTPS** (localhost exempt for testing); without TLS the prompt + SW
  silently don't activate. iOS = manual Share→Add to Home Screen (no programmatic prompt). Silent
  zero-click auto-install is impossible in any browser — the button is the 1-click path.

## Rebrand → City Agent Insights + new logo (2026-06-25, v1.8.0, BAKED)
- **Logo**: new brand PNG (transparent — the orange preview bg is alpha 0) processed via PIL from
  `~/Downloads/ChatGPT Image Jun 25 ...`. Overwrote `frontend/public/assets/`: full logo (mark+"CityAgent
  INSIGHTS") → `cityagent-dash-logo.png` (home) + `cityagent-insights-logo.png`; square C-mark → `logo-mark.png`,
  `logo-128.png`, `logo-mark-128/512.png`, `logo.png` (nav `TopNav.vue`, sign-in, onboarding, chat avatar — all
  reference these filenames, so no .vue change needed for the mark). LANDMINE: original PNG has a tall faint glow
  → trim/crop with a SOLID-alpha threshold (>90), not `getbbox()`, else huge empty padding.
- **Rename** "City Agent DASH" → "City Agent Insights" everywhere (sed over index.vue, settings/general.vue,
  SlidesPanel.vue, sign-in.vue + backend defaults report_schema/organization_settings_schema/agent_v2/
  organization_service/report_service). Org 55278108 DB `config.general.ai_analyst_name` also patched.
- **Sign-in** (`pages/users/sign-in.vue`): wordmark span DASH→Insights, greeting + footer updated, logo wrapper
  gradient → white box (mark has its own orange C), **sign-up block removed**.
- **LDAP enabled by default**: `organization_settings_service.get_ldap` default `enabled` False→**True**
  (UI shows it on). Login auth uses GLOBAL `dash_config.ldap` (unaffected — no break risk); per-org enable only
  drives the EE admin UI + sync. Org 55278108 `config.ldap.enabled=true` set in DB too.

## Slide workspace — "Open" a presentation (2026-06-25, v1.7.0, BAKED)
Fix: "Open" on a deck (`pages/presentations/index.vue` `openSlides` → `/reports/{id}?focus=slides`) used to
show the deck + the FULL report conversation (clutter). Now it's a clean slide workspace.
- `pages/reports/[id]/index.vue`: new `slidesFocus` ref (set in the `focus==='slides'` branch, cleared in
  `exitDashboardFirst`). When ON: left = deck only (the dock **tab strip hidden**, `v-if="!slidesFocus"`);
  the in-file header shows **"Edit & analyze slides"** + a Chat-first button instead of `ReportHeader`; a hint
  chip **"Ask to edit a slide or analyze the deck…"** sits above the unchanged `PromptBoxV2`. LANDMINE noted:
  `PromptBoxV2` placeholder + `ReportHeader` title are computed INSIDE those child components (no override
  prop) → framing done in-file rather than mutating children (one-file constraint). Empty deck (0 slides/0 viz,
  e.g. "Monthly EBITDA") → in-file clay empty state "No slides yet — ask chat to create a deck".
- `components/dashboard/ArtifactFrame.vue`: expand ⛶ now = TRUE fullscreen — Fullscreen API on a Teleported
  `fixed inset-0 z-[100]` overlay wrapper (NOT the sandboxed iframe), auto-falls-back to the overlay if the API
  rejects; Esc + ✕ close (synced via `fullscreenchange` + keydown, listeners removed on unmount); icon swaps to
  `arrows-pointing-in`. SlideViewer re-rendered large, prev/next stays usable. PPTX/version dropdown untouched.
- `pages/presentations/index.vue`: button tooltips (Open = slide workspace, Open in chat = conversation);
  0-slide decks show a "No slides yet" chip + relabel Open → **"Open & generate"** (`slideCount(p)` helper).

## Whole-folder upload (one-shot, browser) (2026-06-25, v1.6.0, BAKED)
DIFFERENT from Folder Sync (below): a one-shot browser folder pick, no desktop app, no flag.
`components/data/UploadSpreadsheetModal.vue` — added a 2nd hidden `<input webkitdirectory directory multiple>`
+ "Upload a whole folder" button + `onFolderInput` (filters `.xlsx/.xls/.csv`, drops `~$` lock files) →
reuses the existing `batchUpload()` (each file → `/files` → `/data_sources/from-file`, auto-pins via
`created` emit). No backend change. Folder Sync ⟳ = continuous; this = grab-everything-once.

## Folder Sync — local folder auto-ingest, "like Claude Code" (2026-06-25, BAKED)
A desktop tray agent watches a local folder and pushes changed Excel/CSV files to the server; each
push delta-upserts into a per-agent DataSource. Flag `HYBRID_FOLDER_SYNC` (default OFF; ON org 55278108).
- **Server delta ledger** `folder_sync.py` (`FolderSyncState`: org, user, machine_label, source_path
  [the upsert key], file_hash sha256, file_id, data_source_id, studio_id, status new|updated|skipped|error,
  last_sync_at). Unique idx (org, source_path). Mig **`foldersync1`** off `agtmpl1`. **Head now `foldersync1`.**
- **Route** `routes/sync.py` (paths declared w/o `/api`, included w/ `prefix="/api"` in main.py):
  - `POST /api/sync/file` (hot path, multipart `file`+`source_path`+`sha256`+`machine_label`+`target_studio_id`):
    unchanged hash→`skipped` (no ingest); new path→ingest+`new`; changed hash→re-ingest+`updated`. Reuses
    `file_service.upload_file` + `create_data_source_from_file` (which already does content-hash dedup +
    same-schema merge → edited file feeds the SAME source). Optional Studio bind via StudioDataSource.
  - `GET /api/sync/status` (machines grouped), `GET /api/sync/agents` (org Studios for the tray dropdown),
    `POST /api/sync/key` (mint `bow_` key, plaintext once).
  - **Auth = `mcp_auth`** (reused from routes/mcp.py): JWT OR `X-API-Key` `bow_` key → headless agent pairs
    with just a key. All flag-gated.
- **LANDMINE (greenlet):** `create_data_source_from_file` commits internally → expires ALL ORM objects in
  the session. Touching `user.id`/`organization.id`/a pre-ingest `row` after it triggers a SYNC lazy reload
  → `MissingGreenlet`. FIX: capture `org_id`/`user_id`/`file_name` as strings up-front, and **re-query** the
  ledger row fresh after ingest. Never touch the expired ORM objects.
- **LANDMINE:** `StudioDataSource` has ONLY `studio_id` + `agent_id` (no `organization_id` column) —
  passing org_id to its ctor → `TypeError invalid keyword`. Org-scope via the verified Studio instead.
- **FE:** `components/studio/FolderSyncCard.vue` (per-agent card on Sources tab: empty→"Set up folder sync",
  live→folder/N files/synced-ago + Manage), `components/sync/FolderSyncSetupModal.vue` (3-step: download
  app / generate key / pick folder; `POST /sync/key`), `components/sync/FolderSyncPanel.vue` +
  `pages/settings/folder-sync.vue` (connected machines, folder→agent map, status pills). "Add data → **Sync
  a folder ⟳**" 3rd option in studio Auto-pilot STEP 1 (`studios/[id]/index.vue`). Settings tab in
  `layouts/settings.vue` + `nav/TopNav.vue` Manage→Settings. All `useMyFetch` BARE paths.
- **Desktop agent** (standalone, NOT in image, NOT deployed): `folder-sync-agent/` — `sync_agent.py`
  (stdlib + `requests`+`watchdog`; `setup`/`run`/`status`/`agents` CLI; `~/.cityagent-sync/{config,state}.json`;
  sha256 local-state delta, atomic writes; sends `X-API-Key`; debounced watcher; deletes ignored) +
  optional `tray.py` (pystray/Pillow) + README.
- **Download (v1.5.1, WORKING):** `GET /api/sync/download/{macos|windows|linux}` (in sync.py) — PUBLIC (no
  auth, flag-gated only) so a plain `<a download>` works; zips the agent files in-memory + a per-OS
  INSTALL.txt → `cityagent-folder-sync-<os>.zip`. Modal buttons (`FolderSyncSetupModal.vue` osButtons) →
  `/api/sync/download/<os>` with `download` attr. Agent source is BAKED into the image at
  `/app/folder-sync-agent` (via docker cp + commit); endpoint falls back to a repo-relative path.
  Dockerfile COPYs `./folder-sync-agent → /app/folder-sync-agent` (after skills_library) so a clean build
  includes it; if that COPY is ever removed the download 503s (re-bake via docker cp + commit as a stopgap).
  No signed native installer yet (Phase 6) — zip ships the Python agent (pip + run).
- **E2E verified live** (org 55278108, flag ON, minted key): agents 200 → new push (created ds) → same file
  →`skipped` (delta) → edited file →`updated` (same ds reused, same-schema merge) → bind to CRM studio →
  StudioDataSource link created + `studio_id` returned → status grouped by machine. Test rows cleaned.

## Changelog / "What's new" (2026-06-25, BAKED)
Versioned feature feed surfaced as a 🔔 bell popover in TopNav (before profile).
- Source: `CHANGELOG_HYBRID.md` (repo root, `## v<semver> — <title>  (<date>)` + `-` bullets) +
  `VERSION_HYBRID` (current semver, now `1.2.0`). Separate from upstream `VERSION`/`CHANGELOG.md`.
- BE: `app/services/changelog.py` (parser, fail-soft) + `routes/changelog.py`
  (`GET /api/changelog`, `GET /api/changelog/unseen`, `POST /api/changelog/seen`) + per-user
  `users.last_seen_changelog` (mig `chlogseen1`). Registered in main.py.
- FE: `components/nav/WhatsNew.vue` (bell+badge+popover, Activity/What's new tabs, version chip,
  per-release cards) + `pages/changelog/index.vue` (See all). Wired into `nav/TopNav.vue`
  (explicit import, between New-Report and profile). RULE: every shipped feature bumps
  `VERSION_HYBRID` + adds a `CHANGELOG_HYBRID.md` entry.

**Current state (2026-06-25):** image `cityagent-analytics:dev` on `:3007`, branch `hybrid-brain`,
mig head **`foldersync1`**, `VERSION_HYBRID`=**1.9.0**.

**v1.9.0 Default OpenRouter LLM + .env.example:** new orgs auto-seed an OpenRouter
provider (current models: claude-sonnet-4.6 DEFAULT, claude-haiku-4.5 SMALL, claude-opus-4.8,
gpt-5.4-mini, gemini-2.5-flash) via the existing `set_default_models_from_config` org-create hook
(`llm_service.py`), driven by a `default_llm:` block in `dash-config.yaml` + `configs/dash-config.dev.yaml`.
Config `LLMProvider` schema (`dash_config.py`) extended: `api_key` defaults `""`, new `is_preset`
(default True) and `additional_config`. Seeded provider is **custom** type (base_url
https://openrouter.ai/api/v1, verify_ssl), **is_preset:false** so the key is editable from the UI
(Settings→Models) — key left BLANK (never in repo). LANDMINE: native `openrouter` + custom both
`decrypt_credentials()` unconditionally at LLM init (`llm.py:60`) → a NULL key CRASHES; seeder always
`encrypt_credentials("", "")` so blank → valid blob → "" → client builds, 401 until key set. Existing
org 55278108 untouched (already configured). Added root `.env.example` (placeholders only; `!.env.example`
allow-rule in gitignore; OpenRouter key is UI-set not env). LANDMINE: `docker cp` onto the bind-mounted
`/app/dash-config.yaml` fails "device busy" AND leaves a truncated stale view (macOS file-share cache) —
edit the repo file + `docker restart` to refresh; never cp over it.
Folder Sync (desktop folder auto-ingest, per-agent bind, delta upsert; flag ON org 55278108; E2E proven)
BUILT+BAKED — desktop agent in `folder-sync-agent/` (not packaged/shipped yet).
Agent Templates (export/gallery/bind + popup
journey + Studios-page lifecycle UX) BUILT+BAKED.
PWA (installable app + Install button) BUILT+BAKED.
Changelog/"What's new" bell BUILT+BAKED.
Intelligence Layer (8 caps + Studio rail UI) BUILT + BAKED, 5 safe flags
ON by default org-wide. Auto-pilot tab + org-library connector model + 48 Domain Packs + async
auto-train all BUILT + BAKED. STABLE config = `HYBRID_SKILLS=0` / `SUBAGENTS=0`. OPEN BUG: Studio
Queries tab renders blank despite approved `query_library_items` (needs browser console error).
TODO: rebuild image to bake prophet (FORECAST); run train to populate profiler/code-enrich data.
Next ingest work planned in `docs/PLAN_INGEST_STORAGE.md` (Parquet canonical store + LLM merge-judge).
All HTML mockups removed (root `mockup-*`/`ui-mockup*` + `docs/design/*`); `docs/ARCHITECTURE.html` kept.

**Git:** repo on branch `main`, remote `origin` = `git@github.com:raahulgupta07/rahulai-dash.git`
(the older "No git → backups via scripts/backup.sh" note is superseded — git IS live; backups still fine).
