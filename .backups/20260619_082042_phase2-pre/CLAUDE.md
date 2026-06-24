# CLAUDE.md — CityAgent Analytics

Guide for any AI agent working in this repo. This is a **hybrid fork of bagofwords (bow)**
on branch `hybrid-brain`. Read this before touching anything.

## What this project is
Single-project agentic-analytics platform = **bow chassis** (FastAPI + Nuxt, own AgentV2
plan/execute/reflect loop, ~46 warehouse connectors, multi-tenant, Instructions + approval
gate, MCP, observability) **merged natively** with:
- **dash patterns** (agno-agi/dash) — dual-schema, Engineer view-builder, DB-level read-only.
  Ported as native bow code. Agno is NOT run. `reference/dash/` is a read-only blueprint only.
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
3. **Touch bow core MINIMALLY.** Prefer new files/modules + hook points over rewrites.
   This is a fork of a fast-moving OSS base; every core edit = future rebase tax.
4. **Everything new is flag-gated** (`app/settings/hybrid_flags.py`), default OFF, so a fresh
   deploy behaves exactly like upstream bow until a flag is on.
5. **Everything learned is gated** — memories/shared-skills/correlations land in `pending`,
   go live only after approval. Reuse bow's Instruction build/approval; do NOT build a new gate.

## LLM = OpenRouter ONLY
No Agno → no openai 2.x → bow keeps `openai 1.107`. Configure as bow `custom` provider
(`base_url=https://openrouter.ai/api/v1`, per-org DB row, Fernet-encrypted key).
VERIFIED: `app/ai/llm/clients/openai_client.py` `inference_stream_v2` = Chat Completions
streaming tool_calls → OpenRouter-compatible with PlannerV3. Pin **tool-capable** models
(default `anthropic/claude-sonnet-4` + `openai/gpt-4o-mini` router). Seed via
`backend/scripts/seed_openrouter.py` (HTTP, post-onboarding).

## Feature flags (`app/settings/hybrid_flags.py`, env `HYBRID_*`, all default OFF)
`DUAL_SCHEMA · ENGINEER_ASSETS · ANSWER_CACHE · BRAIN_READ · DISTILLER · QUERY_CACHE ·
SKILLS · FEDERATION · BRAIN_GRAPH · INSIGHT_DAEMON · QUOTAS · SEMANTIC_LAYER · METRICS_CATALOG`.
Access via `from app.settings.hybrid_flags import flags`.

## Fast dev lane (FE iteration without rebuild)
Prod image (:3007) serves a compiled `nuxt generate` static bundle — no hot-reload. For daily
frontend work, run the **Nuxt dev server on :3000**:
```
cd frontend && BOW_BACKEND=127.0.0.1:3007 yarn dev   # hot-reload, proxies /api -> ca-app:3007
```
Two lanes: **:3000** = dev/hot-reload, **:3007** = baked prod image (FE changes need a rebuild OR a
generate+`docker cp` FE-sync). `nuxt.config.ts` proxy targets are env-driven (`BOW_BACKEND`, default
8000). Host node22 at `~/.hermes/node/bin` + global `yarn@1.22.22` (no corepack).
- **NEVER run `yarn generate`/`yarn build` while `yarn dev` is live in the same dir** — corrupts
  `.nuxt` → blank app. Recover: kill nuxt, free :3000, `rm -rf .nuxt .output node_modules/.cache
  node_modules/.vite`, restart dev.
- **A new `components/**/*.vue` created mid-session is NOT picked up by Nuxt auto-import until the
  dev server restarts** — the component renders blank, silently. Restart dev after adding any new component.
- FE API calls use `useMyFetch` (auto-injects Authorization + X-Organization-Id, prepends `/api`) →
  use BARE paths (`/knowledge/queries`, NOT `/api/knowledge/...` — double-prefix 404s).

## Knowledge Layer (dash-style semantic model — Phases 0-7 done, flag-gated, approval-only)
Org-shared, per-data-source, gated port of dash's structured Knowledge Layer onto the bow chassis.
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
`query_library_schema.py` (NOT `query_schema.py` — that's bow core, don't clobber). New Nuxt component → restart
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
# 1. pre-pull bases with retry (avoids registry-EOF mid-build)
for b in ubuntu:24.04 rust:1-slim-bookworm pgvector/pgvector:pg18; do
  until docker image inspect "$b" >/dev/null 2>&1; do docker pull "$b"; done; done
# 2. build + run our image
docker compose -f docker-compose.build.yaml build
docker compose -f docker-compose.build.yaml up -d
curl localhost:3007/health     # ports: APP=3007 (internal 3000), POSTGRES=5439 (see .env)
```
DB = **PostgreSQL 18 + pgvector** (`pgvector/pgvector:pg18`). AGE dropped (not PG18-ready) →
2nd-brain graph = pgvector table + recursive CTE. Migration head `v1e2c3t4o5r6` enables the
`vector` ext. Build ~20min first time (frontend `nuxt generate` forces 6GB Node heap — give
Docker ≥10GB or build stages serially via `--target` so the generate runs alone).

## Boot status (VERIFIED LIVE 2026-06-18)
Full stack builds + boots green. First-run admin via `POST /api/auth/register`
(`{email,password,name}`; first uninvited user auto-creates an org + becomes admin).
Dev admin: `admin@cityagent.io` / `CityAgent#2026` (org "Main Org"). OpenRouter seeded via
`backend/scripts/seed_openrouter.py` (BOW_BASE_URL/BOW_ADMIN_EMAIL/BOW_ADMIN_PASSWORD/
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
found + fixed in our hybrid code: (1) `app/ai/brain/qa_pair.py` resolves Q+A across bow's TWO
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
- Agent-owned schemas in bow's managed Postgres: `analytics` (Engineer views), `staging` (ingest).
  External connections stay read-only via bow's existing query path.

## Landmines (learned the hard way)
- Alembic has merge migrations with **tuple** `down_revision` — naive head-finding gives false
  multiple heads. True head (at fork time): `d6d9a78b7b4a`.
- Docker Hub `registry EOF` on base pulls — pre-pull with retry (rule 2).
- `dev`/`build` composes shipped `image: bagofwords/bagofwords:latest` + `pull_policy: always` —
  replaced with build-from-source. Don't reintroduce.
- bow base error class is `app.errors.app_error.AppError(error_code, message, status_code=...)`,
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

## Still pointing at upstream (clean up in Phase 10)
`k8s/chart/values.yaml` repository + `.github/workflows/docker-image*.yml` push targets.
