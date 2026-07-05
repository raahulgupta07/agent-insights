# CLAUDE.md — CityAgent Analytics

Guide for any AI agent working in this repo. This is a **hybrid fork of bagofwords (bow), rebranded Dash**
on branch `hybrid-brain`. Read this before touching anything.

@docs/CODEBASE_MAP.md
@docs/andrej-karpathy-skills/CLAUDE.md

> **Karpathy guidelines vendored** at `docs/andrej-karpathy-skills/` (4 behavioral rules:
> Think-before-coding · Simplicity-first · Surgical-changes · Goal-driven-execution), imported above.
> Apply to every agent in this repo. On conflict, this file's HARD RULES win.

## Full Data Pipeline → `NEWPIPE.md` (2026-06-30)
The end-to-end 15-phase ingest→train→serve pipeline + the A+B+C combine plan (S1–S8) live in
**`NEWPIPE.md`**. Read it before touching ingest/train. Headlines:
- **3 chronic pains diagnosed+fixed:** (1) "Python crash again+again" = numpy ABI drift (`dlt` bumped
  numpy→2.4.2 vs pandas) + stdlib **module-shadowing** (stray `inspect.py` in cwd) → pin `numpy<2.4`,
  run from clean dir; (2) "KPIs not matching" = freehand ad-hoc SQL → **governed semantic layer** (locked
  filters); (3) "highest accuracy" = **golden + answer eval gates**.
- **Proven on real CRM data** (org Main Org `7d372305`, 6mo): 21,240→21,231 idempotent; KPIs lead=1544/
  succ=7526/unsucc=4179 EXACT; golden gate caught new_user 658→644; answer-eval blocked 2/2 wrong numbers.
- **P13 Hybrid Search + P14 Brain Graph WIRED into `train_orchestrator`** (stages `hybrid_index`+`brain_graph`,
  pct 99, fail-soft, auto-publish edges) — LIVE in product (index 17, edges 10) but **EPHEMERAL (hot-cp, not baked)**.
- **P0–P12 dlt pipeline = SEPARATE prototype** (`scratchpad/p2run/`), real data, NOT in product.
- **Backup before replace:** `scratchpad/pipeline_backup_<ts>/` + image `cityagent-analytics:rollback-<ts>` +
  git tag `pre-full-pipeline-<ts>`. uploads vol = `cityagentanalytics_ca_uploads` (NOT `ca_uploads`).
- **Correction:** `SEMANTIC_SEARCH` & `FORECAST` DO have `@property`, default True — a prior map note saying
  OFF was wrong; real blockers were empty index/edges + the approval/publish gate.

## Boot protocol (READ FIRST — do not scan the tree)
You become the codebase expert by READING, not scanning. On session start, these load automatically and
are authoritative: **CLAUDE.md** (this file — rules/current state), **`docs/CODEBASE_MAP.md`** (entry points +
extension patterns + landmines — the expert primer, imported above), **`ROADMAP.md`** (forward plan), and the
HEAD of **`DEVLOG.md`** (recent dated history). That is enough to work fast.
- Do **NOT** read every file or run a full tree scan. Trust the map; open a specific file only when you need
  its exact contents to edit it.
- If the map is missing a path you need, read that one file, then **add it to `docs/CODEBASE_MAP.md`** so next
  session is faster (the map is the durable memory — keep it current, same habit as the DEVLOG/VERSION bump).
- The map covers the load-bearing 20%; `DEVLOG.md` has full per-feature history if you need depth.

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

**2026-06-29 FE EPHEMERAL (fe-sync only, NOT baked — pending `docker commit`):** (1) **plan-block chat leak FIXED** — `HYBRID_AGENT_PLAN` flag-on (org e02b1b04, default OFF) emits a `source_type='plan'` block; chat body renderer `reports/[id]/index.vue:387` was the 1-of-4 consumer missing the plan-skip guard → dumped raw `{"tasks":[...]}`. Fix = `&& block.source_type !== 'plan'`. RULE: skip `source_type='plan'` in EVERY render path (Progress=stepMap.ts:348/484, context=message_context_builder.py:597/1221 already do). (2) **merged Create/Activity into ONE no-tabs panel** (Option A) in the `coworkEnabled` block of `reports/[id]/index.vue` (removed `coworkTab` toggle; Create grid top + Activity below, one scroll). (3) **"only April summary" ROOT CAUSE = silent partial ingest:** CRM Agent source `0b9b39ac` has 1 table, 2447 rows ALL `_source_period=2025-04` (6 months uploaded, 5 never materialized; merged table mis-NAMED `_apr_25` → agent frames answer "April"). Guardrails proposed (manifest+reconcile / coverage-context to agent / neutral table naming / atomic batch merge / post-ingest verify-gate), NOT built. Detail → [[project_cityagent_panel_ingest_completeness]].

**Current state (2026-07-05, LATEST):** `VERSION_HYBRID`=**1.124.0** on branch `integration/merge-all-20260705` (NEVER push straight to main). v1.108–1.124 = FE-sync/hot-cp + git-committed, **NOT pushed**. Org `b2bec83d` ("Main Org", ONLY org), admin `admin@cityagent.io`/`Admin12345`.
- **v1.124.0** (`704e1856`): **Connector Sync Hero** — the 1–10 min connector sync is now a live table-by-table experience on `/agents/{id}?sync=live` (stage strip Sign-in→Discover→Import→Learn→Ready, overall bar + elapsed + ETA, each table ✓ with row count, background + 🔔 notify, done ribbon, partial/retry). **Additive + fail-soft, BULK DB SEED UNCHANGED**: `services/connector_sync.py::log_step` gained optional `status`/`rows` keys (JSON `log`, no migration); `services/per_user_connector.py::sync_clone_bg` runs the bulk `DataSourceService_seed` FIRST (unchanged) then emits paced (`0.15s`, 0 if >40 tbl) per-table `syncing→done(rows)` events from the real catalog (`ConnectionTable.no_rows`), `inc_tables` advancing the bar, whole loop try/except-wrapped. FE `components/agents/AgentSyncLog.vue` rebuilt into the Sync Hero (computeds `stageState`/`tableRows`[group `log[]` by `entry.table`]/`eta`; poll 1.5s + `emit('phase')` + `hasRun` self-hide preserved); `pages/agents/[id]/index.vue` `isSyncing` (from `onSyncPhase`) gates a "Learning your data…" skeleton, disables the report launcher, hides the redundant discovering bar, refetches `injectedFetchIntegration()` on done. Backup: git tag **`pre-sync-hero-redesign`** + scratchpad copies. LANDMINE: `_LOG_CAP=300` → >140-table connectors trim earliest log lines (counters unaffected, separate cols).
- **v1.123.0–1.123.3**: connector Settings/Data-Agents visibility + misc. **v1.123.0** (`24e1a28c`): **Show/Hide toggle on every connector row** (`settings/connectors.vue` `UToggle` all 4 rows) → per-org `organization_settings.config.connectors_hidden` list (works for keyless coming-soon, no migration); `ConnectorsMsHub.visibleCatalog` drops hidden keys for everyone; removed old `publish_status` Disable button. **Test-before-save** in Configure modal → `POST /connectors/{key}/test-template` (`routes/data_source.py`, fail-soft 200 `{ok,reason}`, GUID + Fabric hostname `*.fabric.microsoft.com` DNS via `asyncio.to_thread`); Save gated on pass + "Save anyway". **v1.123.1** (`56f5c0e4`) ★LANDMINE: `connectors_hidden` saved to DB json col but STRIPPED on read — `GET /organization/settings` serializes `config` through `OrganizationSettingsConfig` Pydantic schema which WHITELISTS keys; any new config key is dropped on read unless declared. Fix = add `connectors_hidden: List[str] = []` to `schemas/organization_settings_schema.py`. **RULE: new `organization_settings.config` key → also declare it in `OrganizationSettingsConfig` or it round-trips as empty.** **v1.123.2** (`c92e1de4`): removed "+New agent" button from `/agents` (agents come from connector sign-in; `pages/agents/index.vue` both header + empty-state NuxtLinks dropped, route left intact). **v1.123.3** (`831bcf29`): show-password eye toggle on `ConnectorsRegisterModal.vue` (`showPassword` ref flips input type). NOTE connector catalog keys = `fabric/powerbi/sharepoint/onedrive` (NOT the conn `type`) — shared identically by `settings/connectors.vue` + `ConnectorsMsHub.vue`.
- **v1.122.0** (`959d05b3`): (Bug1) 5 missing `connectors.*` i18n keys (`disable/enable/disabledChip/disabled/enabled`) → toggle showed raw key; `$t()||fallback` can't save it (vue-i18n returns the key string=truthy) → added to `locales/en.json` (repo-root, loaded via `frontend/plugins/i18n.ts` `../../locales/en.json`). (Bug2) **report now locked to the selected agent's data**: working-folders + grounding scope to persisted `report.data_sources` but the composer picker only mutated live `currentAgents` (header) → mismatch. Fix `pages/reports/[id]/index.vue` `onAgentPickerChange`: fresh report → PUT `/reports/{id}` `{data_sources}` + reload grounding; report WITH history → seed `useAgent().selectAgents` + `/reports/new` (**user chose: switch mid-history = new report**). `reports/new.vue` `isReusable` also requires the stale draft's sources match the picked agent. `report_service.create_report` Data-Agent path (no `studio_id`) drops any `data_source_id` not in the org (fail-soft, all-valid = no-op).
- **v1.121.0** (`91391e5e`): **Teach the agent now creates Metrics/Queries/Examples too** (was only Skill/Instruction/Data-rule/Knowledge). `ai/packs/teach.py` `_SPAN_TYPES` = 7 (added `METRIC`/`QUERY`/`EXAMPLE`); `_CLASSIFY_PROMPT` + `_normalise_spans` + `apply_spans` persist METRIC→`metric_definitions` (locked/`last_value` when value given), QUERY→`query_library_items` (`source=teach`,`is_golden`), EXAMPLE→`studio_examples` (pending, `source='auto'`), each fail-soft; `preview_spans` passes sub-objects + `will_be` through. NEW `ai/packs/teach_template.py` (`build_template_md`/`build_template_xlsx`[openpyxl]/`parse_upload`). Routes `GET /studios/{id}/teach/template?fmt=md|xlsx` (download) + `POST /studios/{id}/teach/upload` (multipart→parse→same classify+preview, ≤2MB) on `routes/studio_teach.py`. FE `components/studio/StudioTeach.vue`: download dropdown, upload button, METRIC/QUERY/EXAMPLE badges + card enrichment (example keys `question/answer` NOT `q/a`). Flag `TEACH_BOX` (already ON). Three ways to teach: one-at-a-time / bulk paste / upload template.
- **v1.115–1.120**: robot/train/ingest/connector polish. v1.115 robot dock (model line only while running, single left timestamp, day-breaker divider on date change). v1.116–1.118 train UI = BPMN process flow (`StudioAutopilotV2.vue` `FLOW_PHASES`/`bpmn-*` nodes) + skipped-state (`runComplete`+`_resolvedFlow` remap queued→skipped, `flowPct` counts done+skipped+held). **v1.117 Gemini-as-training-default**: `ai/knowledge/train_orchestrator.py` main resolver now reads org `default_train_model_id` (studio model → org default → analysis default) mirroring `route_inbox`. v1.119 dlt_ingest + quality_gate SKIP when the direct loader already persisted (`routes/data_source_from_file.py` both new-source + append branches, guard `not _loader_persisted`) — fixes DuckDB single-writer lock + quality_gate querying a `t_<ds_id>` table the loader never made. v1.120 robot log color-code (`StudioRobotDock.vue` `lineClass` err/held/ok/stage/model/info + `renderMsg` cyan counts) + wider (`min(92vw,620px)`); connector enable/disable (publish_status) + only-configured hub (`isConfigured`/`readyCloneFor`/`visibleCatalog`); `per_user_connector.list_available_templates` adds `publish_status`+`config`.
- **v1.114.0** (`cf068e8e`): studio-bound uploads (e.g. a CSV that belongs to a Studio) wrongly showed as their own "Data Agent" line in the New-report picker + top-nav picker, duplicating the studio's data. `/agents` already filtered by `connector_kind` (v1.104) but the pickers didn't, AND `data_source_service.py::get_active_data_sources` (endpoint `/data_sources/active`) never populated `connector_kind` (always null). Fix: derive `connector_kind` in `get_active_data_sources` (mirror `get_data_sources`, conn.type ∈ {powerbi_user,ms_fabric,sharepoint,onedrive} else null, reuse eager-loaded conn, no N+1) + FE `components/prompt/DataSourceSelector.vue` (`getDataSources`) + `components/AgentSelector.vue` (`dataAgents`) require `CONNECTOR_KINDS.has(connector_kind)`. Agent Studios group untouched (file still shows inside its studio). Verified live: `/data_sources/active` → PBI=powerbi_user, Fabric=ms_fabric, CSV=null. LANDMINE: `get_data_sources` and `get_active_data_sources` are TWO separate row-builders for the SAME `DataSourceListItemSchema` — a field added to one is null on the other; keep them in sync.
- **v1.113.0** (`0f0761d6`): SPLIT joint MS connector → **two separate cards** (Power BI + Microsoft Fabric) on `/agents`. Connect Fabric→Fabric agent, connect Power BI→Power BI agent, no fan-out/dupes; existing agents untouched. The joint "Microsoft (Fabric + Power BI)" tile was flag-gated (`HYBRID_MS_UNIFIED_SIGNIN`), NOT hardcoded — ONE load-bearing change: `frontend/components/connectors/ConnectorsMsHub.vue` `catalog` computed (dropped `combinedTile`/`unifiedEnabled` + `unified`/`fanout` sign-in path) → `catalog=baseCatalog` always. Flag → `superseded_by:[HYBRID_PER_USER_CONNECTOR]` (inert, Features Legacy tab) + DB override OFF org `b2bec83d`. Backend already made separate agents (per template `type` `ms_fabric` vs `powerbi_user`; `_build_fabric_sibling` only fires on `fanout=true`, only from the combined tile).
- **v1.108–1.112** (committed `9055dbc5`/`37f24f72`/`04024146`/`cb116b5f`/`13d8240b`): studio-chat 403 gate (`studio_chat_gate`), Fabric staging-warehouse skip, SOURCE-LOCK sync-gate (`HYBRID_SOURCE_SYNC_GATE`), chat table CSS scroll-fix, empty-bubble 0-row serving-cache fix (`agent_v2._serve_from_reasoning_cache`), Claude-style streaming thinking timeline (`AgentStepTimeline.vue` expand-while-running→auto-collapse). Backup tag `pre-thinking-ui-1783256770`.

**Prior baked state (2026-07-05):** `VERSION_HYBRID` was **1.105.0**, **DURABLE-BAKED** into `cityagent-analytics:dev` (build.sh + force-recreate, verified code-in-image), **NOT git-committed**. Three ships baked together:
- **v1.103.0 — Intelligence/dashboard UX:** (1) Verified Metrics "Data temporarily unavailable" FIXED — `routes/intelligence.py::get_layer` had a duplicate LOCAL `import MetricDefinition` in the `search` branch → made it function-local → `UnboundLocalError` when the `metrics` branch ran first. Fix = drop the local dup (module-top import at L24 stands). (2) 3 predictive Studio-Intelligence tabs MERGED → one **"Insights & Forecasts"** (`i_insights_forecasts`) with 3 buttons Scan/Forecast/Find-patterns (`pages/studios/[id]/index.vue` + `StudioIntelligence.vue` `combined` prop; runs reuse `POST /intelligence/layer/{layer}/run`, actions scan/run/discover). (3) Dashboard+Slides "Generate" now route to CHAT (`reports/[id]/index.vue::onOutputGenerate` → `handleExampleClick`) instead of the silent synchronous `/dashboard/generate` → fixes stuck spinner + wrong artifact name (chat build → LLM names it).
- **v1.104.0 — no duplicate agents (hub connectors-only + create-first):** in this fork a DataSource==Data Agent, so a Studio's uploaded `spreadsheet` DS was listed on `/agents` as a twin. Backend `connector_kind` on the DS list (`schemas/data_source_schema.py` + `services/data_source_service.py::get_data_sources`, = backing conn type when in {powerbi_user,ms_fabric,sharepoint,onedrive} else null, reuses eager-loaded conn, fail-soft). FE `pages/agents/index.vue` `allAgents` now includes ONLY items with `connector_kind` ∈ the 4 (uploads/null excluded → twin gone); added a "New agent" button → `/agents/new`; `pages/agents/new/index.vue` gained an Add-data toggle (Upload files | Connect a source) — upload branch creates the agent FROM the file (`/files`→`/data_sources/from-file` named from wizard), not a standalone. No upload path sets is_public (audited).
- **v1.105.0 — self-healing ingest (kills "only April" permanently, ANY dataset):** 4 flags in `hybrid_flags.py` — `HYBRID_ONE_TABLE_MERGE` + `HYBRID_INGEST_RECONCILE` flipped ON, NEW `HYBRID_INGEST_SELFHEAL` + `HYBRID_AUTOEDA_AUTOAPPROVE` (default ON). **P1 cross-session merge** (`routes/data_source_from_file.py` + `data_sources/clients/spreadsheet_client.py`): `_try_merge_same_schema` matches by TOLERANT column-signature (`_same_template`: order/case-insensitive + bounded ±10% col drift), prefers the target studio's bound source (new optional `studio_id` on the from-file request + `_studio_bound_ds_ids`); `_load_frames` groups by same-template signature (not exact hash) so tolerant matches stack into ONE table + `_source_period` col. **P2 fail-loud** (`services/ingest/reconcile.py`, already-complete, now flag-ON): multi-file merge records per-file outcome, flips source DEGRADED on shortfall, stamps `ingest_coverage`, `tables_schema_section._render_coverage_note` injects "do NOT fabricate missing periods". **P3 self-heal** (NEW `services/ingest/selfheal.py::selfheal_data_source`): finds unclaimed same-signature orphan staging tables in the org schema, backs up, single-txn `INSERT…SELECT…WHERE NOT EXISTS` (idempotent on `_row_key`/`_content_hash`), updates `no_rows`, optional drop-orphans; wired as fail-soft train Stage 0b (`train_orchestrator.py`) + `POST /api/data_sources/{id}/repair` (`data_source.py`, `?dry_run`, owner/admin) + "Repair data" button (`StudioAutopilotV2.vue`). **P4 auto-approve** (`ai/knowledge/docs_index.py`): single choke-point `ingest_doc` + `_resolve_ingest_status(source,approve)` → first-party (`source='upload'`/`approve=True`) lands approved when flag ON; learned/AI-proposed knowledge (separate models, never via ingest_doc) keeps the review gate. Built via me (flags) + parallel disjoint-file subagents.
- **DATA FIXES (org b2bec83d, this session, live — data not code):** CRM agent (studio `3acb8dea`, DS `28025e96`) was APRIL-ONLY (2447 rows, active table `staging_b2bec83d691b4064.t_1b2a1487_..._mm_conso_data_report`); hand-merged all 6 months → **21,240 rows** (6 `_period` groups), dropped 11 orphan mm_conso tables, backup `scratchpad/mmconso_staging_backup_*.sql`. 12 Auto-EDA knowledge_docs were all `pending` → approved all 12 + reindexed (25 embedded). KPIs on full set: total 21240, Successful 7526, Unsuccessful 4179.
- **LANDMINE:** the recurring "only April" = same-schema monthly files uploaded in SEPARATE sessions each mint their own table/DS; single-batch merge only caught within-batch; v1.105 P1+P3 fix this going forward + repair the past. `HYBRID_MERGE_SAME_SCHEMA` was already ON but only matched exact-signature within one upload. Superuser THIS DB = `admin@cityagent.io`/`Admin12345`, org `b2bec83d` (ONLY org). Prior "STUDIO FLYOUT LATEST" (v1.93) block below is historical.

**Prior state (2026-07-05):** STUDIO FLYOUT = DATA-AGENT TABS — **BAKED**, `VERSION_HYBRID` 1.92→**1.93.0** + `CHANGELOG_HYBRID`, **NOT git-committed**. Studio hover preview now shows the SAME Overview/Tables/Instructions/Queries tabs as a Data Agent (was overview-only).
- **Root cause:** two separate preview components drifted — `AgentFlyout.vue` (tabbed) vs `StudioFlyout.vue` (overview-only). (Studio detail PAGE `pages/studios/[id]` was already fully tabbed; the ONLY overview-only surface was the hover flyout, mounted by `AgentSelector.vue` + `prompt/DataSourceSelector.vue`.)
- **Fix (DRY):** NEW `components/AgentDetail.vue` = the tabbed body (Overview/Tables/Instructions/Queries + fetches `/data_sources/{id}` · `/data_sources/{id}/schema` · `/api/instructions` · `/api/entities`, driven by `agentId`; emits `loaded`+`connect`; props `reportGrounding`, `showStarters`; `overview-lead` slot). `AgentFlyout.vue` → thin header+position wrapper around it. `StudioFlyout.vue` resolves bound source (`/studios/{id}/sources[].agent_id`), embeds `AgentDetail` with studio summary+questions in `overview-lead`, grounds reports on studio+all sources, `showStarters=false`; multi-source studios get a clickable source-switcher chip row (all studios currently bind exactly 1 source via `studio_data_sources`). Both pickers unchanged (inherit). FE-validated `./node_modules/.bin/nuxt generate` clean.
- **v1.93.1 follow-up (interactivity fix):** the composer (prompt-box) picker's preview snapped shut when moving to click a tab. ROOT: `prompt/DataSourceSelector.vue::showFlyoutAtEvent` **bottom-anchored** the flyout (`flyout.bottom`) → detached above the upward-opening composer dropdown → cursor gap → 120ms hide fired. FIX = top-anchor to the hovered row like `AgentSelector.vue` (`flyout.top = rect.top-8`, `flyout` reactive now carries `top` not `bottom`). Covers both agent + studio flyout (shared position obj). LANDMINE: hover-preview flyouts that became INTERACTIVE (tabs) must anchor to the row (no gap) or the mouseleave hide-timer kills them mid-reach.
- Detail → [[project_cityagent_studio_agent_layout_unify]].

**Prior state (2026-07-05):** AGENT OVERVIEW AUTOFILL — **BAKED**, `VERSION_HYBRID` 1.91→**1.92.0** + `CHANGELOG_HYBRID`, **NOT git-committed**. Fixes the blank "No primary instruction / No conversation starters" Overview on fresh agents.
- **Root cause:** Overview panel (`components/report/ReportAgentPanel.vue`) reads TWO dedicated `data_sources` columns — `primary_instruction_id` + `conversation_starters` — that the train pipeline never populated. The **Instructions(N)** tab counts agent-linked + org-global instructions (different source, `instruction.py:830` fetch) so N>0 while primary stays blank; the report's middle starter chips are a **frontend-only generic fallback** (`reports/[id]/index.vue`), NOT saved starters. So both slots read empty on a fresh agent.
- **Fix (permanent):** NEW `services/knowledge/agent_overview.py::autofill_agent_overview(db, *, organization, data_source)` — pins best existing non-guardrail instruction (prefer general/overview/definition/semantic/business; skips `data_quality`) else synthesizes+links a 1-para primary from the agent name; seeds 4 default starters (`"title\nprompt"`). Fills ONLY what's missing, fail-soft, commits on change. Wired as fail-soft `agent_overview` stage (pct 99, before Done) in `ai/knowledge/train_orchestrator.py` over `sources`. Flag `HYBRID_AUTOFILL_AGENT_OVERVIEW` (3-place, default ON). Tested: blank throwaway DS → 4 starters + synth pinned primary; populated agents → no-op; cleaned up.
- **Data backfill (live, no rebuild):** both MM Conso agents (`5b3bbcea` Gemini3.5-fresh + `80725fa2` Jan-Jun) got a custom primary instruction + 4 period-grounded starters via `PUT /api/data_sources/{id}` (admin login → JWT + `X-Organization-Id`). starters format = array of `"title\nprompt"` strings; PUT body `{primary_instruction_id}` / `{conversation_starters:[...]}`.
- Detail → [[project_cityagent_agent_overview_autofill]].

**Prior state (2026-07-05):** UPSTREAM **0.0.433 PORT** — **BAKED** (`cityagent-analytics:dev`, recreated + live-verified), `VERSION_HYBRID` 1.90→**1.91.0** + `CHANGELOG_HYBRID` entry, **NOT git-committed**. Full tar backup made first (`CityAgent_Analytics_backup_<ts>.tar.gz`, 480M). No migration; no new user-facing flag. 4 upstream items:
- **① Claude Fable 5 — adopted our way.** OpenRouter-only deploy (runtime models = DB rows under ONE `custom` provider "OpenRouter", `model_id`=slug). Added anthropic preset to `models/llm_model.py` (fresh-install parity) + inserted LIVE DB row `Claude Fable 5`/`anthropic/claude-fable-5` (vision, 1M ctx, cloned sibling org/provider/config). Smoke = in-container `LLM(m).inference` → OpenRouter HTTP 200 → `FABLE_OK` (survives recreate; DB untouched). `LLM.inference` is SYNC (str, not awaitable); session = `app.settings.database.create_async_session_factory`.
- **② Mobile pass (PR #534) — partial.** NEW `frontend/assets/css/mobile.css` (16px min input <640px + `overflow-x:hidden`) reg'd in `nuxt.config.ts`; `composables/useSidebar.ts` `mobileOpen` (parity, UNUSED — our drawer is in `nav/TopNav.vue`); `layouts/default.vue` `h-screen`→`h-dvh`; per-file: `AgGridComponent` (flex cols + pagination only rows>50), `RenderTable` (paging wrap), `EChartsVisual` (≤5 cats `hideOverlap:true`, the line WITHOUT `color:` param), `PromptBoxV2`/`SplitScreenLayout`/`reports/[id]`/`r/[id]` mobile spacing + `useHead` report-title tab name (public `r/[id]` top bar icon-only on mobile). **Our `default.vue`=119L TopNav+AppRail arch, NOT upstream ~570L `<aside>` drawer → hamburger port N/A (TopNav already has one).**
- **③ /agents connections-footer overflow — N/A** (fix lives in `KnowledgeExplorer.vue`, absent in our fork; our `/agents` = different structure).
- **④ MCP connector icon — adopted.** `schemas/data_source_schema.py` `ConnectionEmbedded.connector_key` + `derive_connector_key` validator (`config.catalog_key` fallback); `components/tools/MCPTool.vue` `DataSourceIcon`/`McpIcon` via `connectorKey`/`mcpConnection` computeds + `dataSources` prop (report page already binds `:data-sources` at `reports/[id]/index.vue:406`).
- **LANDMINES:** validate FE FAST before the ~90s image bake via `./node_modules/.bin/nuxt generate` (`npx nuxt`/`npm nuxt` break under rtk hook); `rtk` garbles `grep -n` → read files directly or `grep -nE`. Verified code IN image via `docker run --rm --entrypoint sh cityagent-analytics:dev -c 'grep …'`. Detail → [[project_cityagent_upstream_port_433]].

**Prior state (2026-07-05):** TIMELESS TABLE NAMING + GENERIC DOC→KNOWLEDGE — both **BAKED** (`cityagent-analytics:dev`, recreated), NOT git-committed. Org `b2bec83d` "Main Org" (admin `admin@cityagent.io`/`Admin12345`). No migration (pure code + 1 flag).
- **Fix1 — timeless table naming (fixes the OLD "only April"/`_apr_25` misnomer permanently):** same-schema monthly files (`…_jan_25`) FROZE the table name at the FIRST file's slug forever → adding August would break it again. ROOT: `data_sources/clients/spreadsheet_client.py::_load_frames` fast path (single file, `merged_paths` empty) slugged with NO period strip; the `_canon`/`derive_period_and_stem` strip only ran on the merge read. FIX = compute `ONE_TABLE_MERGE` flag up-front + new `_timeless_name()` (slug THEN `derive_period_and_stem`) at CREATION + `_canon` slug-before-strip. Now `jan_25`/`aug_25`/`2025_08` ALL → `…_mm_conso_data_report` (Aug-proof; a new month just appends rows). Agents re-derive the table name LIVE at query time → existing agents self-heal, ZERO breakage. Synced existing `datasource_tables.name`+`connection_tables.name`; rewrote overview `studio_artifacts` (human → friendly "MM Conso Data Report") + agent-guidance instructions (→ real live name).
- **Fix2 — generic any-type attached-doc → searchable Knowledge (flag `HYBRID_DOC_KNOWLEDGE`, 3-place, default ON):** attached docs sat as `data_source_file_association` rows, never in `knowledge_docs` → agent couldn't cite them. NEW `services/knowledge/file_ingest.py`: `_extract_text` dispatches by ext (pdf/docx/pptx via ingest_brain `extract_pdf/docx/pptx`; xlsx digest; txt/md/html/json readers) → `ai/knowledge/docs_index.ingest_doc` → KnowledgeDoc+chunks; first-party uploads set `status='approved'`; idempotent (content-hash), fail-soft. TWO hooks: `services/file_service.upload_file` (immediate on attach, non-CSV) + `ai/knowledge/train_orchestrator` new **`ingest_docs`** stage before `hybrid_index`. `backfill_data_source_docs()` = on-demand repair. PROVEN: agent read the CRM Q&A Logic doc's Lead definition and returned **1,544** (golden match); 3 docs → 9/20/12 chunks, 52 embedded.
- **Fresh pipeline-test agent** (built to verify the above): Studio `a72a6184` "CRM (Gemini3.5 — Fresh 9-file)" on `google/gemini-3.5-flash`, DS `5b3bbcea` = all 9 MM Conso files (6 CSVs merged 21,240 rows/6mo `_source_period`, +3 docs). Golden KPIs live-verified (total 21240, Successful 7526, Unsuccessful 4179). To isolate a fresh source w/o wiping the 4 existing test studios: temp `deleted_at` old spreadsheet-1 conn, upload, restore.
- **LANDMINES:** offline `docker exec python` needs `import main` first (ORM `Completion` KeyError) AND reads env-default flags (skip `load_overrides_from_db`) → `import app.settings.hybrid_flags as HF; HF.set_override('HYBRID_X',True)`. Build exit-0 lies → verify code in image via `docker run --rm --entrypoint sh cityagent-analytics:dev -c 'grep …'`. Recreate keeps DB/volume (renamed table/docs/studios persist), only reverts code to image. Detail → [[project_cityagent_timeless_naming_doc_knowledge]].

**Prior state (2026-07-04):** UPSTREAM PORT **ALL 5 WAVES DONE (W0-W4)** + flag flips + F09 bake + STUDIO UX OVERHAUL. Branch `feature/table-relevance-overview`, **NOTHING pushed**. Mig head **single `sidesort1`**.
- **Port 0.0.412→0.0.432 COMPLETE.** W3=RBAC depth (6 feats, mig `fileref1`). **W4=polish (mig `sidesort1`):** #479 sidebar last-activity sort · #494 tree lazy-load · #527 PDF hydration · #468 OpenShift logs(env-opt-in)+ssl(no flag) · #478 global-evals nav · #521 RTL followups · 430 week-start(planner prompt). Skipped: #425 Infor/#522 CSV-path/#531/#528/auto-publish(W3). **W4's 6 flags flipped code-default ON** (all orgs). Detail → [[project_cityagent_upstream_port]].
- **Flag decisions (post-W4):** **Held-5 flipped code-default ON** (FULL_PIPELINE·CROSS_SOURCE_UNIFY·PERSIST_WAREHOUSE·CODE_ENRICH_PLUS·INGEST_BRAIN) + **F09 LIGHT-BAKE** (added pdfplumber/beautifulsoup4/PyMuPDF pure-pip wheels, bumped pdfminer.six→20260107 to satisfy pdfplumber's EXACT pin; SKIPPED heavy camelot+ghostscript). **4 superseded flags → Legacy tab** via `superseded_by:[...]` metadata (DLT→ROBUST_INGEST+ONE_TABLE_MERGE · AUTOTRAIN_ON_INDEX→TRAIN_ROUTING · MOA→AUTO_MODEL · STUDIO_LEARN_DAEMON→SelfLearn); Features page now has **[Active | Legacy N] tabs** (`settings/features.vue`, driven by `superseded_by` field added to flags API `_flag_row`). **MoA-as-model already existed** (commit `a5e1092e`: backend `_resolve_moa_answering_model` + `model_id=="moa"` branch + FE `PromptBoxV2` picker) → just enabled HYBRID_MOA on Main Org. NOTE org `config` col is **json NOT jsonb** → jsonb_set needs `config::jsonb…::json` cast.
- **STUDIO UX OVERHAUL (user "non-technical users, one flow"):** (1) **Smart Upload → single flow** (`SmartUploadModal.vue`: killed inbox-vs-route-now mode; drop→classify→auto-apply, Review collapsed). (2) **Auto-train-on-upload** flag `HYBRID_AUTOTRAIN_ON_UPLOAD` (default ON) — `smart_upload.py` apply `if body.train or flags.AUTOTRAIN_ON_UPLOAD` → `start_training`; distinct from risky warehouse-wide AUTOTRAIN_ON_INDEX. (3) **Inline upload + robot CLI dock** flag `HYBRID_ROBOT_DOCK` (default ON): `components/studio/StudioInlineUpload.vue` (inline, `hideDropzone` prop, emits `@log`) + `StudioRobotDock.vue` (floating bottom-right terminal, cloned from `agents/AgentRobotDock.vue`, streams upload→classify→train stages one-by-one from `trainLogLines`/`trainStages`; `trainModel` computed parses REAL model from log — org uses route glm-5.2 + analysis claude-sonnet-4.6). (4) **ADD source-button row** (`StudioAutopilotV2.vue`: one row Database·Upload·OneDrive·SharePoint·Folder; `@add`→`onAutopilotAdd`→`openConnect(type)`/`inlineUploadRef.pick()`/`openFolderSync`; dropped PBI/Fabric=Data Agents). **LANDMINE: studio page has TWO layouts — `StudioAutopilotV2` (flag AUTOPILOT_V2, LIVE) vs legacy `v-else`; mount shared bits at TOP of autopilot `<section>` (before v-if/v-else) to render in BOTH.** Newer HYBRID flags all default-ON, 3-place, unpushed.

**Prior state (2026-07-04):** UNIFIED MS SIGN-IN + `/agents` robot dock + login hero.
- **Unified MS sign-in (BAKED at session start, `cityagent-analytics:dev`):** flag `HYBRID_MS_UNIFIED_SIGNIN`
  (default OFF, ON org 7d372305). One Microsoft sign-in on the combined tile → provisions BOTH a Power BI agent
  AND a Fabric agent (shared FOCI refresh_token). New `SCOPE_FABRIC_REST` + `services/ms_fabric_discovery.py`
  (`discover_fabric_endpoint` redeems FOCI→api.fabric.microsoft.com, lists workspaces/warehouses→connectionString;
  None→NO dead Fabric agent). Fan-out in `per_user_connector.py` (`_build_fabric_sibling`, `_register_clone_fresh_session(fanout=True)`
  returns `(primary_id, sibling_ids)`); `data_source.py` poll/connect take `fanout` → sync BOTH, skip journey-v2 consent.
  PROVEN live: real sign-in → Power BI 25 tables + Fabric 0 tables (no warehouse = honest empty-state). Detail →
  [[project_cityagent_unified_signin_login_hero]].
- **FE polish (EPHEMERAL — fe-sync only, NOT baked/committed):**
  (1) **MS tile-swap** — `ConnectorsMsHub.vue` `catalog` computed: when `unifiedEnabled`, REPLACES the individual
  Microsoft Fabric + Power BI (User Sign-in) tiles with the single combined tile (SharePoint/OneDrive stay);
  flag OFF → individual tiles return. Super-admin toggles via Settings → Features (`MS_UNIFIED_SIGNIN`).
  (2) **`/agents` robot dock** — NEW `components/agents/AgentRobotDock.vue`: always-on blocky-terracotta robot
  pinned bottom-right, click → CLI log panel polling each agent's `/data_sources/{id}/sync-status`. LANDMINE:
  a mid-session new component auto-imports as a LAZY `resolveComponent` chunk that gets TREE-SHAKEN out of
  `nuxt generate` → renders nothing; FIX = EXPLICIT `import` in `pages/agents/index.vue` (verify class in dist:
  `grep car-dock /app/frontend/dist`). Clear `.nuxt`+`.vite` before generate for new components.
  (3) **Login hero** — `components/auth/AuthShowcase.vue` = "how City Agent works" pipeline (5-step sweep +
  mini-widgets + rotating platform messages + feature marquee + canvas data-spine). Self-contained: PAINTS the
  whole dark panel (`.cai-right` in `sign-in.vue` stripped to `<AuthShowcase/>` only, no padding/bg/header/footer).
  LANDMINE: old `runShowcase` scene machine + its refs in `sign-in.vue` are now DEAD CODE (driver call commented,
  `<AuthShowcase/>` owns the panel) — harmless, strip on next real edit. Iterated many hero versions this session
  (video cabinet → pipeline → cinematic core → journey card → light stream); LIVE = the v3 enriched pipeline.
  Standalone previews in scratchpad `login_all_improvements.html` / `v3_pipeline_enriched.html`.
- **PENDING: bake** (`scripts/build.sh` + build.yaml recreate) to make the 3 FE items durable. UI/UX review done
  (all-improvements mockup at `scratchpad/login_all_improvements.html`, NOT ported to `sign-in.vue` yet).

**Current state (2026-07-03, prior):** `VERSION_HYBRID`=**1.90.0**, mig head **single `docacl1`**
(`docacl1_knowledge_doc_acl.py`, per-doc ACL `allowed_user_ids`; 182 revisions, verified single leaf).
v1.90 = Phase 4 = **LEAN_TOOLS** (F1, flag removes 7 audited dup tools from planner catalog, 24→13) +
**DOC_ACL** (F3, `HYBRID_DOC_ACL` per-user KnowledgeDoc gate). Both flag-OFF default. Branch
`feature/table-relevance-overview`. Superuser THIS DB = `demo@test.com`/`CityAgent#2026`.

**PRE-PROD HARDENING PASS (2026-07-03, SOURCE-ONLY — NOT baked/committed/hot-cp'd yet):** 11
prod-breaking issues fixed via 8 parallel disjoint-file subagents + 2 follow-ups, all flag-gated /
fail-soft / backward-compatible / `py_compile`-verified. (1) multi-worker `--workers 4` state →
Redis key-poll for confirmation + officejs (`ai/tools/confirmation.py`, `officejs_registry.py`; unset
`REDIS_URL`=identical), train-status early DB-persist (`train_orchestrator.py`); (2) flag tenant-bleed
→ per-org map + `set_current_org` ContextVar in `hybrid_flags.py`, WIRED via pure-ASGI
`OrgFlagContextMiddleware` in `main.py` + `dependencies.py` (single-org=no-op); (3) console cross-org
LEAK → org-filter on `console_service.get_tool_executions_diagnosis` + defined missing
`_classify_error_type`; (4) Fernet durability → prod refuses boot on auto-gen key, demands explicit
`DASH_ENCRYPTION_KEY` (`start.sh`, `app/settings/config.py`); (5) sandbox → SyntaxError hard-reject +
curated `__builtins__` + `RLIMIT_AS` (`code_execution.py`); (6) `READONLY_ENFORCE` default flipped
**ON** + all warehouse clients confirmed through string guard; (7) MCP `_load_report` org-check, git
creds redacted + `--force-with-lease`, SSRF IP-pin (`safe_client.py`), WS `/ws/api/reports/{id}`
token-auth (+2 FE files); (9) auto_evals vacuous-pass → evaluator `test_evaluation_service.py`
fail-closed (malformed spec→error, unknown matcher/op→fail; `length.cmp` un-broken); (10) RESULT_CACHE
ported into LIVE `implementations/create_data.py` (was only in unused `mcp/create_data.py`); (11) LDAP
config-split verified already correct. **3 caveats set in `docker-compose.build.yaml`:**
`SANDBOX_MEM_LIMIT_MB=0` (disables risky process-wide virtual rlimit) + commented `mem_limit:` (cgroup
= correct real-mem cap, size ~70% host RAM); `DASH_ENCRYPTION_KEY` already valid Fernet in `.env`;
`REDIS_URL` already wired. **APPLY-ORDER LANDMINE: env change needs container RECREATE → reverts
ca-app to IMAGE → WIPES hot-cp'd fixes. MUST BAKE FIRST:** `bash scripts/build.sh` →
`docker compose -f docker-compose.build.yaml up -d` → `bash scripts/fe-sync.sh` (FE WS-token) →
`curl :3007/health`. PENDING: bake + `git commit` + live smokes (multi-worker confirm/officejs,
RESULT_CACHE hit, webhook sig-verify with signed payload). Sandbox caveat: `RLIMIT_AS` is process-wide
virtual — prefer the cgroup `mem_limit` over a low `SANDBOX_MEM_LIMIT_MB` (false-trips duckdb/pandas).

**Prior state (2026-07-03, superseded above):** branch PUSHED; PR to `dev` = user's click; mig head **`wf2save1`**,
`VERSION_HYBRID`=**1.89.0**. **v1.88.0 = OpenAI-data-agent gap-closers P2-P6** (`cd8312be`, 5 subagents, all flag-OFF ON org 7d372305): USAGE_TRUST (trust-rank tables, schema_context_builder), TABLE_CARD (unified card + Shared-Memory overlay, semantic_context_builder extra_cards, coupled SEMANTIC_LAYER), INSTITUTIONAL_KB (docs FTS→planner, org+approved), EVAL_CANARY (`/api/eval/canary/health|drift`+FE eval-health.vue), TOOL_AUDIT (`docs/TOOL_AUDIT.md` 24→13, consolidation deferred). **v1.89.0 = data-agent parity Parts A-E** (`2bf96125`, 5 subagents, mig `wf2save1`): WORKFLOWS_V2 (save/replay analysis, PromptBoxV2 "Use a workflow" chip, `models/analysis_workflow.py`+`services/workflows/`+`routes/workflows_v2.py`+`WorkflowPicker.vue`), OFFLINE_CONTEXT (nightly per-table context_doc+embed, `services/context_offline/`+scheduler 02:30, coupled TABLE_CARD, proven 28 docs), CODE_ENRICH_PLUS (PK/downstream/alternate into pipeline_logic, `code_enrich.py`+`enrich_signals.py`, rendered in table_card), GOLDEN_SQL (`services/evals/golden_sql.py`, `ResultSetRule.golden_sql`+eval_harness capture; DEFERRED live grade), NOTION_KB (`notion/slack_ingest.py`→KnowledgeDoc→P4, `routes/kb_sources.py`). import main 677 routes. Detail memory [[project_cityagent_openai_gapclosers]] + [[project_cityagent_dataagent_parity]]. Superuser THIS DB = `demo@test.com` / `CityAgent#2026`.
**Prior v1.83.0 baseline** (superseded above; mig was `colprofile1`). Superuser THIS DB = `demo@test.com` / `CityAgent#2026` (NOT admin@cityagent.io — that email not on this DB).
**v1.79.2→1.83.0 BRANCH CONSOLIDATION (baked+pushed):** every parked branch merged onto this feature branch, each flag-gated default OFF, image==git per step — v1.79.2 dup-agent fix (`_find_reusable_connection` adopts orphan conn, `delete_data_source` cascade-deletes owner-private conn+children), v1.80 **Mixture-of-Agents** (`HYBRID_MOA`, `ai/mixture_of_agents.py` 3-model consult→glm-5.2 aggregator, picker option `model_id="moa"` in `PromptBoxV2.vue`), v1.81 smart-excel+drop-tile, v1.82 smart-slides+dashboard (`HYBRID_SMART_SLIDES/DASHBOARD`), v1.83 **Ingest-Brain F09** (`HYBRID_INGEST_BRAIN`, `services/ingest_brain/*`, mig `colprofile1`). RECURRING MERGE LANDMINES (all in DEVLOG): parked branches call non-existent `LLMService._find_openrouter_provider`→direct provider query; keep-both perl DROPS `@property` on `hybrid_flags.py`→verify `flags.X` is bool; old-base migration forks alembic head→re-parent `down_revision`.
**v1.84.0 FE UI FIXES — WIP, EPHEMERAL (fe-sync only, NOT baked, NOT committed; VERSION still 1.83.0):** (1) home scroll `pages/index.vue` `home-root` `min-h-screen`→`h-full overflow-y-auto`; (2) home output-type TABS `components/home/RecentReports.vue` REWRITTEN (Reports/Dashboards/Presentations/Spreadsheets tabs + count badges + per-tab View-All, derived from `artifact_modes`); (3) agent rail always-renders `layouts/data.vue` (real `<aside cag-side>` moved OUT of `v-if=isLoading`) + `timeout:15000` on `$fetch(/data_sources/{id})`; (4) agent rail reskin → workspace parity (`.cag-side` 224px flush white → 240px cream `#FBFAF6` floating card, full border, radius 16, `m-2`; shell bg `#FAFAF9`→`#F1ECE3`); (5) agent main `bg-white`→`bg-[#FBFAF6]` (rail+main same cream, inner KPI/knowledge cards stay white = workspace pattern). 🔴 **PWA SERVICE-WORKER LANDMINE:** SW caches `_nuxt/*` CacheFirst → after fe-sync the browser serves STALE chunks (FE change looks "not working" though dist is fresh + endpoints 200). Debug rule: verified-fresh dist + 200 endpoints + still-broken UI = suspect the SW, not the code. Fix = hard-refresh Cmd+Shift+R (new content-hash chunk forces SW update) / DevTools→Application→Service Workers→Unregister. Pending: bake v1.84.0 after user hard-refresh confirm.
**Prior current state (2026-07-02):** was baked `:v1.76.0`, HEAD `1421d518`, mig `connsyncrun1`, VERSION 1.76.0. **v1.76.0 = LEARN-FROM-DATA (kills connector domain hallucination; committed
`1421d518`, baked via `docker commit`, NOT pushed, rollback tag `pre-learn-from-data`).** A per-user Power BI
connector named after its sign-in method ("Power BI (User Sign-in)") + a name-only schema (PBI has no FKs / col
descriptions) made the 4 onboarding generators in `ai/agents/data_source/data_source.py` anchor on the name and
INVENT a fake domain (@SignInLogs, "Frequent Sign-in Failures") for data that's actually retail membership +
project tracking. **Fix1 grounding (always-on):** `_clean_ds_name` strips "(User Sign-in) · email"→"Power BI";
`_grounding_block`+`_table_allowlist` inject "name = login method IGNORE for domain; reference ONLY these real
tables; never invent" into all 4 prompts. **Fix2 learn-from-data (flag `HYBRID_LEARN_FROM_DATA`, default OFF, ON
org 7d372305):** new `services/connector_sampler.py` samples `EVALUATE TOPN(8,'Table')` per ACTIVE table → ≤6
example values/col into `DataSourceTable.columns[i].metadata['values']` (schema renderer already surfaces
`values="…"`); PII col-names never sampled; 429-abort, per-table timeout, fail-soft, PBI-only; wired
`per_user_connector.sync_clone_bg` 4b-2 (after relevance, before llm_sync). PROVEN live agent d305b1a4: grounded
summary/starters/primary-instruction w/ SAMPLED values (sectors CH/CP/CV, status On-Track/Off-Track), 10/25 active,
sign-in fabrication gone. **LANDMINES:** (1) PBI TOPN df cols come as `Table[col` (pandas drops trailing `]`) →
`_strip_bracket` handles both. (2) flag DB override MUST use ENV-key `HYBRID_LEARN_FROM_DATA` (short key silently
ignored — `load_overrides_from_db` only honours `UPGRADE_FLAGS` keys). (3) `llm_sync` writes an `audit_logs` row
w/ `current_user.id` — a None/detached user → `ForeignKeyViolationError` rolls back the WHOLE learn; pass a real
attached User. (4) sync diff-gate (4c) skips re-learn on unchanged table-set (new connectors always learn, so the
hallucination can't recur on new agents; force an existing agent by nulling `primary_instruction_id` then llm_sync
+ promote). Detail → memory `project_cityagent_table_relevance` + DEVLOG 2026-07-02. — prior **v1.74.5 = Power BI query SPEEDUP + reliability** (flag
`HYBRID_CONNECTOR_ROBUSTNESS`, OFF=byte-identical, ON org 7d372305; rollback img `pre-connectorfix`; NOT git-pushed).
ROOT CAUSE of "PBI query slow" = the QUERY path builds its client via `data_source_service.construct_client(s)`,
which NEVER installed the offline table→{datasetId,workspaceId} index (only `connection_service.construct_client`
did) → every query fell back to LIVE `get_schemas()` fanning `COLUMNSTATISTICS` across EVERY dataset (slow +
429/400 spam on empty datasets). FIX = new `DataSourceService._install_pbi_offline_index()` called from BOTH
construct paths (built from `ConnectionTable.metadata_json.powerbi`). VERIFIED live: index size=18, discovery
calls 0 (was ~11), 46.7s→26.5s, answer unchanged (258 projects). +DAX result cache (`powerbi_client._dax_cache`,
class-level, TTL 300s/cap 256, keyed tenant|ws|dataset|max_rows|dax, serves `.copy()`; unit PASS) collapses
intra-completion retries + exact repeats. +401 auto-reauth on DAX path (`_reauth()` re-mints once, fail-soft).
+fail-loud Fabric reindex (`ms_fabric_client.get_tables` logs WHY on 0/0 — was silent). +empty-dataset
COLUMNSTATISTICS 400 → DEBUG. **LANDMINE: the result-cache serve/store lives in `mcp/create_data.py`
(`CreateDataMCPTool`) = a SEPARATE MCP-server tool the agent NEVER calls; the live tool =
`implementations/create_data.py` (`CreateDataTool`) has NO cache → that's why 0 rows ever cached. A question-keyed
cache in the LIVE tool (sub-2s cross-session repeats) is DEFERRED to its own verified change.** ALSO v1.74.5
FE (EPHEMERAL fe-sync, NOT baked): first-"Open" on a Data Agent stalled because the Open button uses
`navigateTo` (programmatic) which Nuxt does NOT auto-prefetch → the `/agents/[id]` JS chunk downloaded at
click time. Fixed: `pages/agents/index.vue` `watch(allAgents,…,{immediate:true})` calls
`preloadRouteComponents('/agents/'+first.id)` (all agents share the `[id]` chunk) → first Open instant. All
detail-page APIs already <0.02s (backend was never the delay). — prior
**v1.74.4 = P3 no-fail-cache** (`result_cache._looks_failed`
guards store+lookup; a failed/empty create_data result is never persisted or replayed, legacy bad entries self-heal
via soft-delete on lookup; unit 8/8). Completes the connector-reliability bundle. **v1.74.3 = connector query
reliability + Data Agents UI redesign (baked, NOT git-pushed):** DataAgentCard Studios skin + Settings›Connectors
(super-admin config, `manage_connections`) + ConnectorsMsHub sign-in-only + compact search + i18n leak fix. Backend
flag `HYBRID_CONNECTOR_ROBUSTNESS` (OFF-default=byte-identical, ON org 7d372305; rollback img
`cityagent-analytics:pre-connectorfix`). Live Power BI/Fabric agent Qs went 5-attempt/~148s flaky → **1 tool
call/1 attempt clean** (subjects 7299, projects 258, sectors 8). Three fixes: **P1** auto-fill tables when the
model omits `tables_by_source` (`create_data._resolve_all_active_tables`, cap 30); **P2** PBI 429 backoff on the
DAX path (`powerbi_client._post_dax_with_retry`, honor Retry-After, +typed `PowerBIRateLimitError`); **P4**
`dataset_id is required` ROOT = `execute_query`→`get_schema()` did a LIVE `get_schemas()` re-discovery that 429'd →
fix = OFFLINE `set_table_index()` populated in `construct_client` from `ConnectionTable.metadata_json.powerbi`.
Plus `TablesBySource` accepts `table_names`/`table` aliases + coercion (gemini arg-shape). LANDMINE: PBI
`get_schema()`/`get_schemas()` = LIVE discovery, 429-prone — never on the query path; use the offline index.
Deferred P3 (don't cache FAILED completions) → v1.74.4. — prior **v1.74.2 = 3 bug fixes (baked, NOT git-pushed):** (1)
**connector connect 500** — per-user `connect()`/`device_code_poll()` fed the request session's expired `organization`
into `create_connection`; sync `organization.id` access → AsyncSession lazy-load → `MissingGreenlet`. Fix
(`per_user_connector.py`): `_register_clone_fresh_session()` builds the clone in a fresh `async_session_maker` session,
`expunge()`s force-loaded org/user (detached+populated → no lazy-load), and offloads blocking MS `requests`
(`ropc_token`/`start_device_code`/`poll_device_code`) via `asyncio.to_thread`. Verified E2E → 200 → 18/18 tables.
(2) **query crash "Invalid format specifier" on every chat** — `prompt_builder_v3.py` f-string had unescaped literal
JSON braces in the clarify examples (lines 217/223) → `{expr:format_spec}` misparse. Fix = doubled braces `{{ }}`.
(3) **removed duplicate Available Connectors page** — nav item (`useAppNav.ts`) + `pages/connectors/available.vue`
deleted; `/connectors/available` API endpoint STAYS (Data Agents hub loads templates from it). LANDMINE: any prompt
f-string with literal JSON examples MUST double its braces. — prior **v1.74.0 = AUTO-LEARN→PRIMARY + rich learn log + dramatic
terminal:** fixed "No primary instruction" — `sync_clone_bg` now promotes the `llm_sync` onboarding instruction to
`status="published"` + sets `data_sources.primary_instruction_id` (was draft/unset). Learn runs AFTER seed → instruction
references real tables; rich per-step `log_step(phase="learning")` lines (reading→joins→description→starters→overview→published);
distinct-`ConnectionTable` dedup → `18/18` (was `26/18`). FE `AgentSyncLog.vue` dramatic terminal (typewriter reveal,
spinning ⟳ + cursor, colored tokens, done=flash+✓pop+confetti+Start-chat; `‹table› · ‹msg›` separator, `· catalog` for
0-row lines, `Math.min(done,total)`). LANDMINE: bare `docker exec python` on `sync_clone_bg` needs `import main` first
(Widget/Report mapper); real BG task fine. **v1.73.0 = LIVE IN-AGENT SYNC LOG:** connector clone build moved
to a BG task (`per_user_connector.sync_clone_bg`, scheduled by `connect`/`device_code_poll` after `register_template_for_user(defer_sync=True)`
returns the shell fast) writing a DB-backed live log (`ConnectorSyncRun`, mig `connsyncrun1`, `services/connector_sync.py`
`start_run`/`log_step`/`finish_run`) through phases connecting→syncing(per-table)→learning(auto-learn)→done. Route `GET
/api/data_sources/{id}/sync-status`. FE `components/agents/AgentSyncLog.vue` = warm-dark CLI terminal on the agent
Overview (poll 1.5s, self-hides on `{}`), hub navigates `/agents/{id}?sync=live`. LANDMINES: DB-backed (in-mem breaks
across `--workers 4`); alembic dir = `backend/alembic/` NOT `backend/app/alembic/`; per-table `rows`=`ConnectionTable.no_rows`
best-effort (0 for PBI/on-prem). **v1.72.1 = wired the adaptive modal into the `/agents` hub
tiles** — `ConnectorsMsHub.vue` `startConnect(key)` now opens `ConnectorsRegisterModal` (email+pw→`/connect`→device-code
fallback) instead of jumping straight to `/device-code/start` (the v1.72.0 modal was orphaned — tile showed the code
screen directly). LANDMINE: the hub OWNS the connector tiles; the RegisterModal must be MOUNTED + wired there, not just
built. **v1.72.0 = ADAPTIVE CONNECTOR SIGN-IN:** one flow — user
types email+password, Connect. BE tries ROPC (`powerbi_device_code.ropc_token`, password grant + offline_access →
refresh_token; classifies AADSTS 50076/50079/50158/50072/53000/7000218 = MFA→fallback, else real fail). No MFA →
`per_user_connector.connect()` builds clone now (auth_mode `device_code`, `{refresh_token}` creds); MFA → auto
`start_device_code` → `{status:"mfa_required",device_code,user_code,verification_uri}` → FE polls EXISTING
`/device-code/poll`. Route `POST /api/connectors/{id}/connect` (auto-`autolearn_clone` on direct connect). FE
`ConnectorsRegisterModal.vue` = in-modal device-code view + poll on `mfa_required`, 404→legacy `/register` fallback.
**Both paths end at identical `refresh_token→clone` builder.** Flag `HYBRID_ADAPTIVE_CONNECT` (default OFF, DB-override ON
org 7d372305). Built via 2 parallel subagents. LANDMINE: flag needs `load_overrides_from_db` (bare `import main` reads
False); `--workers 4` → one `docker restart ca-app` to converge. **v1.71.2 = blank-clarify fix (3 layers):** prompt told model
to emit singular `question` STRING but clarify schema wants `questions:[{text,options}]` → weak models emitted strings →
`ClarifyTool.vue` read `q.text`=undefined → blank box. Fixed: (A) FE `ClarifyTool.vue` `questions` computed normalizes
string/alt-key items→`{text}`+drops empties; (B) BE `ai/tools/schemas/clarify.py` `@field_validator("questions",before)`
coerces+drops; (C) `prompt_builder_v3.py` clarify block rewritten to schema shape + worked example. **v1.71.1:** Data
Agents now in New-Report picker (`DataSourceSelector.vue` dropped `STUDIOS_ONLY` gate → shows Studios + Data Agents).
**Auto-learn backfill:** pre-v1.71.0 clone `d0c33ff1` (`use_llm_sync=false`) backfilled via in-container
`per_user_connector.autolearn_clone` (`import main` first) → description + 4 starters + overview build #4. NEW clones
auto-learn by default. **v1.71.0:** (A) `/agents` PERSONAL VIEW — `allAgents` drops
public agents you don't own (keep `!is_public` OR `owner_user_id===myUserId` via `useAuth()`) + `!is_user_template`;
(B) AUTO-LEARN on connect — clone `use_llm_sync=True` + `per_user_connector.autolearn_clone()` (own `async_session_maker`
session → `DataSourceService.llm_sync` = description+starters+overview instruction) scheduled via `BackgroundTasks` on
`/connectors/{id}/device-code/poll` after success. `llm_sync` (`data_source_service.py:630`) = same routine as manual
wizard "Use LLM to learn agent". **v1.70.3:** agent-detail rail = EXACT copy of
`components/nav/AppRail.vue` `.cag-rail-card` (Workspace/Manage parity): shell `flex bg-[#F1ECE3]`, rail 240px `#FBFAF6`
radius16 m-2, `.cag-eyebrow`/`.cag-sec-link`/`.cag-sec-active`(bg#ECEAE1) copied verbatim into `layouts/data.vue` scoped
CSS + `tabIcon()` heroicons + main `#FBFAF6` card. LANDMINE: agent rail is a HARDCODED replica (tabs are per-id dynamic,
don't fit static `useAppNav.ts` array) — if AppRail styling changes, update data.vue's copy too. **v1.70.x = ONE-CLICK connector agents + Manage-style agent
detail (BAKED):** v1.70.0 sign-in IS agent creation (wizard `/agents/new` bypassed for MS); `DataSourceService_seed`
auto-activates ALL tables (`max_auto_select=100000`); FE `agents/index.vue` `connectorMeta(ds)`→LOGO+NAME+email, removed
show-all/Create btns. v1.70.1 `allAgents` filters `is_user_template` (admin template no longer a phantom agent card).
v1.70.2 agent detail redesign — **tabs live in `layouts/data.vue`** (NOT `[id]/index.vue` = Overview slot only): moved to
sticky LEFT RAIL (identity via `connectorMeta` + `tabGroups` Explore/Configure/Observe + **Test** GET
`/data_sources/{id}/test_connection` + **Disconnect** gated `isClone`→DELETE ds then DELETE each `/connections/{id}`).
Isolation unchanged (v1.69.4 guard). Agent-detail (D) DONE.
**v1.69.x = MICROSOFT CONNECTORS HUB on `/agents` (BAKED,
rollback `pre-connector-hub-revamp`):** admin configures a connector TEMPLATE once (`is_user_template=True` DataSource +
`auth_policy=user_required` Connection); each user (incl. admin) signs in via **device-code** (FOCI public client
`1950a258…`, no app-reg, MFA-safe) → private per-user clone syncs under THEIR token. **Fabric + Power BI (User Sign-in)
LIVE**; SharePoint/OneDrive coming-soon. `powerbi_device_code.py` scope-parametric (`SCOPE_FABRIC/POWERBI/GRAPH`) +
`refresh_to_access_token()` (redeem refresh_token→Fabric SQL token, feeds `MsFabricClient(refresh_token=)`→ODBC
`attrs_before={1256}`). Routes **`/api/connectors/*`** (`available`/`register`/`device-code/{start,poll}`; router NO
prefix, main.py adds `/api`). FE `components/connectors/ConnectorsMsHub.vue` (COMPACT tiles + ⚙gear=configure) top of
`pages/agents/index.vue`; **Connections chips section REMOVED**; NEW **Manage connectors** page `pages/connectors/manage.vue`.
Admin no-typed-DB → `MSFabricConfig.database` optional + `MsFabricClient` auto-discovers accessible warehouses
(`_accessible_databases`, NEEDS-LIVE-TEST). Flag `HYBRID_PER_USER_CONNECTOR` ON org 7d372305. LANDMINES: (1) private
(owner_user_id) connections must NEVER trigger the CONNECTOR_AS_AGENT hook — guard `if not owner_user_id:` in
`create_connection` (else it spawns a 2nd PUBLIC agent = dupe+leak); (2) `_resolve_client_by_type` must use
`resolve_client_class` (registry client_path), not derive names (`powerbi_user`→`PowerBIUserClient`); (3) per-user
connect uses `create_connection(validate=False)` — empty/on-prem PowerBI catalog must not hard-fail connect. Detail →
memory `project_cityagent_ms_connector_hub` + DEVLOG 2026-07-01. PENDING (D): agent-detail redesign (tabs + left summary
+ chat bar), NOT built. **v1.67.0 = Data Agents page + connector→org-visible-agent (BAKED):**
the full bagofwords Data Agents page already existed at `/agents` (DataSource=agent) — surfaced it in the TOP nav between
Studios & Workspace (`useAppNav.ts` `direct:'/agents'`, top-bar-only) + reworked `services/connector_agent.py` to make a
connected source an **org-visible Data Agent** (`is_public=True`, Studio path REMOVED). `is_public` + `user_required` =
admin connects once → whole org sees it on `/agents`, each signs in own account (per-user gate + `resolve_credentials` by
user_id). Flag `HYBRID_CONNECTOR_AS_AGENT` ON org 7d372305, rollback `pre-dataagent-rollback`, NOT git-pushed. SUPERSEDES
v1.66 Studio auto-agent (removed). Detail → DEVLOG 2026-07-01.
**v1.66.0 = Connector → Data Agent (superseded by v1.67):** admin connects a
source once → `services/connector_agent.py::auto_create_agent_for_connection` auto-spawns an org-shared Studio bound to
it (flag `HYBRID_CONNECTOR_AS_AGENT`, idempotent via `Studio.config.source_connection_id`, greenlet-safe, fail-soft;
hooked in `connection_service.create_connection`). Power BI `tenant_id`→`PowerbiUserConfig` (admin-set-once), optional
in creds; `construct_client(s)` strip-None-from-creds-pre-merge guard so a blank user field can't wipe the admin tenant.
Phases 3-5 reuse (org studio-list `share_scope=='org'`, `ReportAgentPanel` sign-in gate, per-user `resolve_credentials`
+overlay). Flag ON org 7d372305, rollback `pre-connector-agent-rollback`, NOT git-pushed. Detail → DEVLOG 2026-07-01.
**v1.65.0 = Power BI P3 device-code sign-in (MFA-safe, BAKED):**
`services/powerbi_device_code.py` (start/poll, MS public client, offline_access→refresh_token) + routes
`POST /data_sources/{id}/my-credentials/device-code/{start,poll}` (poll-success persists Fernet refresh_token) +
`PowerBIUserClient.refresh_token` param + refresh-grant branch in `connect()` + FE "Sign in with a code" button.
Proven live (SG tenant approved in browser → refresh_token → 3 workspaces). Rollback `pre-p3-rollback`, flag ON org
7d372305, NOT git-pushed. Tester `scratchpad/pbi_devicecode_app.py` (:8901). Detail → DEVLOG 2026-07-01.
**v1.64.0 = Power BI per-user connector NEXT PHASE (BAKED):**
#8 scan-ALL-tenants (`services/powerbi_multi_tenant_scan.py` → merged tenant-tagged per-user overlay via `_upsert_user_overlay`;
route `POST /data_sources/{id}/my-credentials/scan-all-tenants` + FE "Scan all my tenants" btn) + P5 storage-mode gate
(`powerbi_client.py` tags `powerbi.queryable`) + P4 brute table-discovery (`_brute_discover_tables`, HARDENED: skip empty DBs +
abort on 429). Flag `HYBRID_POWERBI_USER` ON org 7d372305, rollback `pre-powerbi-rollback`, NOT git-pushed. Detail → DEVLOG 2026-07-01. **GIT: v1.51→1.58 pushed `e92eb8c` (main); everything after — v1.59 through v1.66 (PowerBI P1–P3 + #8/P4/P5, Connector→Data-Agent, verified-golden train, E3/E4 ingest) — EPHEMERAL/commit-baked only, NOT pushed. Image tags: `:v1.65.0`=`:dev`, rollbacks `pre-p3-rollback`(=1.64)/`pre-powerbi-rollback`(=1.64 base)/`pre142-rollback`… Baked work lives only in the local image → PUSH is the top open risk.**
**v1.63.0 = verified-golden EVAL GATE wired INTO training** — new fail-soft stage in `ai/knowledge/train_orchestrator.run_training` (after `joins`, before `hybrid_index`), gated `HYBRID_VERIFIED_GOLDENS` AND `HYBRID_FULL_PIPELINE`: loads `AgentDefinition`s → `golden_gen`→`eval_gate` → saves only matches (`pipeline._save_golden`), HOLDS mismatch/error. Proven real train org **7d372305**: 3 approved (Lead 1544/Succ 7526/Unsucc 4179 EXACT)/6 held. Detail `docs/TRAINING_TODO.md`+`TRAINING_STATE.md`, DEVLOG 2026-07-01. **LANDMINE: offline `docker exec python` skips `load_overrides_from_db` → flags read OFF (e.g. `ONE_TABLE_MERGE`) → wrong results; `set_override`/load first.** Snapshot `rollback-training-20260701`.
**E3/E4 INGEST WIRED (2026-07-01, EPHEMERAL, flags OFF):** agent file-upload route `routes/data_source_from_file.py` block **4c4** (after reconcile, before post-ingest, gated `COLUMN_PROFILE or DATA_VALIDATION`, fail-soft): E3 `column_profile.profile_frame`→`persist_profile` into `DataSourceTable.columns[].metadata` (auto-surfaces via existing column-metadata render — distinct/nulls/values); E4 `data_validator.null_and_dup_checks`→`build_data_quality_block`→`metadata_json['data_quality']` per table (findings only). Render: `ai/context/sections/tables_schema_section._render_data_quality_note()` wired into both table render paths. Flags `HYBRID_COLUMN_PROFILE`+`HYBRID_DATA_VALIDATION` default OFF. NOT ON org 7d372305 yet, NOT baked. See DEVLOG 2026-07-01.
**PowerBI probe (2026-07-01):** `scratchpad/pbi_probe.py` (stdlib :8899, email+pw→token/workspaces/datasets/query-test/diagnosis). CONFIRMED identity `<pbi-test-user>` correct, standard Pro member (not admin). Hub Team datasets Abf+onPrem → constant DAX 200 but INFO.TABLES 400 (on-prem-gateway = non-REST-queryable, LIVE). `DataAgent_TestRun` still not visible → wrong grant/workspace. → [[project_cityagent_powerbi_item_access]].
**v1.56–1.58.2 = PROGRESS WAVE + DOCK + AUTO-ARTIFACT + OutputsFeed FIX — detail → DEVLOG/CHANGELOG 2026-06-28:**
- **v1.56–1.57 progress wave/dock:** flat "Thinking…" → warm clay `wave · live step · wave · m:ss` in the report chat. **Real renderer = `pages/reports/[id]/index.vue` inline header + bare-dots block** (NOT `AgentStepTimeline.vue` — that's a different surface; `runningStageText(m)` from `blocksToSteps`). `.cai-wave` CSS (4-hump path, scaleY 0.35–1.15, 1.3s, `cc-shimmer` text). Home idle wave (`pages/index.vue .home-wave`). Docked status strip above composer = **autoBuilding-phase ONLY** (v1.58.1 dropped the `runActive` branch — it duplicated the inline indicator).
- **v1.58.0 AUTO-ARTIFACT (`HYBRID_AUTO_ARTIFACT`, default OFF, ON org 1a073f60):** data turn with zero artifacts → background dashboard build. `services/auto_artifact.py schedule_auto_artifact()` → strong-ref'd `asyncio.create_task` → fresh session (reload by PK) → reuse `report_slides._generate_artifact(mode='page')`; idempotent (zero-artifact gate = 1 build/report), fail-soft. Hooks `completion_service.py` non-stream + stream after answer+sense_making. FE polls `/artifacts/report/{id}` 6s×30 (`autoBuilding`) + dock "Building a dashboard…". VERIFIED LIVE end-to-end (page:completed ~50s). Clarify turns (ambiguous ask, multiple active sources) run no create_data → no artifact = EXPECTED.
- **v1.58.2 BUG FIX (Outputs "No items yet" despite built artifacts):** ROOT CAUSE = both `ChatSummary` mounts (mobile L123 + desktop L1045) in `reports/[id]/index.vue` never passed `:messages` → `OutputsFeed` had 0 turns → empty state even with completed `page`/`slides` artifacts (artifacts render only inside turn blocks). FIX = `:messages="messages"` on both. ChatSummary already declared+forwarded the prop.
**v1.52–1.55.1 = CONNECTOR VISIBILITY + TABLE/SHARING UI + EDIT FIXES + AUTHZ HARDENING — detail → [[project_cityagent_connector_tiers]] (sections G–K) + DEVLOG/CHANGELOG 2026-06-28; pushed `e92eb8c`.** Headlines: v1.53 added `connections.visibility` enum private|shared|org (mig **connvis1**) + self-service `PATCH /connections/{id}/visibility`; v1.54 table UI (`ConnectorsTable.vue` + `ConnectorSharingPanel.vue`, default-private) on per-agent + org Connectors pages; v1.55 edit fixes (roomy `ConnectionDetailModal`, OWNER-OR-ADMIN `_guard_private_owner` super-admin override, Connectors nav open to all members); **v1.55.1 = authz hardening — `_guard_private_owner` wrapped as FastAPI dependency `guard_owned_connection`, wired `Depends(...)` into all 9 connector mutate/test/reindex/tools routes so a new route can't ship without the owner/admin check (RULE: new connector mutate route → add `_guarded=Depends(guard_owned_connection)`).** Below is the older v1.51 baseline (still applies):
**v1.51.0 = CONNECTORS INSIDE EACH AGENT (Activate for agent) — flag `HYBRID_AGENT_CONNECTORS` (already ON), reuses `StudioDataSource` pin model so NO new table/migration, EPHEMERAL (docker cp + restart + fe-sync), NOT baked/pushed.** Per-agent **Connectors page** in studio left rail (tab `connectors` already mounted in `pages/studios/[id]/index.vue` ~L2253/L1071 — no index.vue edit). FE `components/studio/StudioConnectors.vue` REWRITTEN: two tabs **My Connectors** (caller's private studio-bound connectors — create/edit/test/delete) / **Shared Connectors** (admin-configured, reusable); per-card **Activate for agent** ↔ **✓ Active · Deactivate** + sync date; "Add connector" modal creates+auto-activates a private connector; cards key off `conn.connection_id`. BE `routes/studio_sources.py`: `GET /studios/{id}/connectors` now returns `{mine, shared}` (`StudioConnectorListItem{connection_id,name,type,owner_user_id,is_org,active,data_source_id,sync_status,last_synced_at}`; shared visibility reuses connection.py `_conn_visible` — admin→all org connectors, member→granted/public-DS-backed, private-not-owned NEVER listed; `_pinned_ds_ids` → `active`). New `POST/DELETE /studios/{id}/connectors/{connection_id}/activate` (editor+): ensure a DataSource wraps the connector (reuse first, else create private DS w/ name-clash fallback) → pin/unpin `StudioDataSource` (dedupe + undelete) → `schedule_bootstrap_on_source_pin` sync. Added import `permission_resolver.resolve_permissions, FULL_ADMIN`. VERIFIED live (studio d4fb8a10): list `{mine:[], shared:[3]}` all inactive → activate SQLite Chinook → `active:true` → deactivate → `active:false`. LANDMINE: EPHEMERAL — new `studio_sources.py`+`StudioConnectors.vue` lost on force-recreate; bake must ship them with v1.50's connection model/guard/route + agentconn1. Detail → DEVLOG/CHANGELOG 2026-06-28 + [[project_cityagent_connector_tiers]]. **v1.50.0 = TWO-TIER CONNECTORS + MEMBER EMAIL REDACTION + AGENT-AS-PROXY (confirmed) — flags `HYBRID_AGENT_CONNECTORS`+`AGENT_ACL` already ON, manual DDL (`connections.owner_user_id`+`studio_id`), EPHEMERAL (docker cp + ONE restart + fe-sync), NOT baked/pushed.** THREE sharing models: (1) connector-grant (`resource_grants` user/group→connection, reuse `rbac.py` `/organizations/{org}/resource-grants` GET/POST/DELETE) → member SEES+reuses connector; (2) agent-as-proxy (share a STUDIO → member QUERIES via the studio's bound connection creds under `auth_policy=system_only` for ANY caller; `private_connector_guard.require_owner`/`filter_visible` guard ONLY the management plane, never `data_source_service.resolve_credentials_for_connection`; who-may-run=`AGENT_ACL`, whose-creds=`auth_policy` — NO code change, confirmed by trace); (3) personal connector (`ConnectionCreate.scope="personal"`→`owner_user_id=current_user.id` FORCED, any member; `scope="shared"`→admin-only owner NULL). `routes/connection.py` DROPPED blanket `@requires_permission('manage_connections')` on POST → manual scope branch; `_conn_visible` also keeps a member's OWN private connector; `owner_user_id` added to `ConnectionSchema` (3 build sites). Member PII: `routes/organization.py get_members` redacts non-admin viewers — `_mask_email` (`a***@domain`) + null note/auth_sources/invite/login/external on OTHER rows; own + admin (full_admin/manage_members/superuser) full. FE: `connectors.vue` two sections (Shared/My Connections) + open to all + admin "Manage access"; `AddConnectionModal` scope picker; `ConnectForm` `scope` prop; NEW `ManageConnectionAccessModal.vue` (user/group grant editor). VERIFIED live: member shared-create→403, personal→200 owner-forced, isolation (admin can't see member's private), grant flow (admin grant spreadsheet-1→rahul→visible), email mask. 🔴 **LANDMINE: agentconn1 NEVER BAKED** — running `ca-app` was MISSING `services/private_connector_guard.py` AND its `models/connection.py` lacked the owner cols (lost on prior force-recreate) → `/connections` 500'd for everyone; hot-cp'd both + ran column DDL. ALL EPHEMERAL — force-recreate wipes again until a proper bake runs migration agentconn1. Test residue org 1a073f60: `Rahul Personal Chinook` conn + spreadsheet-1→rahul grant + rahul pw reset `Rahul12345`. Detail → DEVLOG/CHANGELOG 2026-06-28 + [[project_cityagent_connector_tiers]]. **v1.49.0 = SLIDES BUILD-FIX + OUTPUTS Q/A FEED + SESSION SUMMARY + ARTIFACT-OPEN ROUTING — flag `session_summary` (org setting, default ON), ONE manual DDL (`ALTER TABLE reports ADD COLUMN session_summary json`), EPHEMERAL (docker cp + restart + fe-sync), NOT baked/pushed.** Five things, built via sub-agents. (A) **Slides actually build now.** ROOT CAUSE decks failed silently: `create_artifact` slides-mode LLM wrote python-pptx using `getattr()` (the prompt's OWN `style_chart_text` example used it twice → LLM copied verbatim) → sandbox AST gate (`code_execution.FORBIDDEN_BUILTINS` bans getattr/hasattr/setattr/eval/exec/open/...) rejected → `artifact.status='failed'`, no pptx/previews → Slides panel empty; chat STILL said "✅ created" (LLM text decoupled from exec result). FIX: hard SANDBOX-RULES header in slides prompt (use `'x' in dir(obj)`/try-except) + rewrote both example helpers getattr-free; HONEST failure — observation summary now says "Slide deck generation FAILED… do NOT claim success" + `observation.failed/status/error`, success wording gated on `status!='failed'`. Verified: a clean deck rebuilt `completed`. (B) **Outputs = per-turn Q/A/Decision feed** (`OutputsFeed.vue`): each turn = timestamp + ASKED question + ANSWER card + `DecisionCard` + artifact chips (status + Open/Retry); newest expanded, older collapsed; Q(user row)↔A+sense_making(system row) paired; artifacts mapped by recency. ChatSummary now takes `:messages`. (C) **SESSION SUMMARY** — pinned card atop Outputs synthesising ALL turns via ONE cheap haiku pass (`is_small=True`) → `{headline, decision, key_findings[], produced[], next_steps[]}`; `app/ai/knowledge/session_summary.py` (mirrors sense_maker, never raises) + GET/POST `/reports/{id}/session-summary` on report_slides.py + cached in NEW `reports.session_summary` JSON col (manual ALTER) with `generated_from` marker → FE `SessionSummaryCard.vue` (stale badge + Refresh, auto-builds once when empty+completed-turn). Flag `session_summary` org setting default ON. (D) **Slides panel honest states**: `hasGoodSlidesArtifact` requires `status==='completed'` (was `!=='failed'` → pending mounted empty frame); new `pendingSlides` → "Building your slide deck…"; `failedSlides` → failed card + **Retry**; refetch artifacts on run-end (failed builds never flip `hasArtifacts`); `generateSlideDeck` POLLS up to 4min for the finished deck (build ~120s > tool timeout 60s + HTTP patience → one-shot refetch missed it). (E) **Artifact-open routing**: `handleOpenArtifact` ROOT CAUSE hardcoded `rightPanelView='artifact'` (dashboard frame) for every artifact → slides opened the dashboard; now routes by `mode` (slides→'slides' view) AND when the clicked artifact isn't `completed` (chat card points at the failed id), selects the latest COMPLETED same-mode artifact instead of dispatching `artifact:select` on the broken one (which rendered blank). LANDMINES: (1) slides Explain/pptx is LLM-emitted — re-verify grounded. (2) session summary auto-build fires once/page-session; mobile ChatSummary mount lacks `:messages` so feed empty there (card still renders). (3) `reports.session_summary` col is manual DDL → survives restart, LOST on force-recreate until baked. (4) ONE `docker restart ca-app` for the cp'd backend (workers=4). Detail → DEVLOG/CHANGELOG 2026-06-28 + [[project_cityagent_explainable_dash]]. **v1.48.0 = EXPLAINABLE DASHBOARD + DECISION-IS-NO-SURPRISE + OUTPUTS LOADER + PICKER DEFAULTS AUTO — flag `dashboard_key_insights` (org setting, default ON), NO migration, EPHEMERAL (docker cp + restart + fe-sync), NOT baked, NOT pushed.** Four UI/AI upgrades. (A) **Explainable dashboard**: `create_artifact.py` page/React prompt (`_build_page_prompt`) now bakes — gated on `dashboard_key_insights` via `organization_settings.get_config(...)` (threaded from `runtime_ctx['settings']`, default-ON) — a top Decision callout (`DECISION · Watch/Act/Hold · confidence`) + Key Insights card (3–5 bullets, each must cite real number/site/period from the build-time viz/observation data) ABOVE the KPI row, plus **per-widget Explain** on every KPICard/SectionCard = collapsible `<details>` with up to 4 tiers Reading/Why/So-what/Do (descriptive→diagnostic→prescriptive, beyond Power-BI) + WATCH badge on anomaly widgets; grounding rules non-negotiable (cite-only-real, fewer-true-beats-guessed). Render path = native `<details>` JSX (the existing `InfoPopover`/`viz` prop only has Data/Code tabs, no prose slot). Independent of sense_making timing (root cause: dashboards build mid-run, sense_making is post-run → old `decision_banner_block` was always empty; kept as bonus). NOTE: my earlier same-day edit to `create_dashboard.py` (semantic-grid builder) was the WRONG builder — real dashboards = `create_artifact` page React; that edit is harmless/dormant. (B) **Decision no surprise + composer lock**: `completion_service.py` streaming path emits NEW SSE `sense_making.pending` right before `build_sense_making` (existing `completion.finished` = ready/unlock). FE `index.vue` `decisionPending` ref: `sense_making.pending`→true, `finished`/error/abort/`[DONE]`→false (FAIL-OPEN — never locks if event absent); drives pending shimmer DECISION card in chat+Outputs ("Reading the result… forming a decision") + locks composer (`PromptBoxV2.canSubmit` adds `&& !props.decisionPending` + inline "forming the decision…" note). (C) **Outputs loader**: `ChatSummary.vue` shows `<DashboardSkeleton mode="page" />` while `runActive` (`generating` prop from `index.vue`, both mounts) until answer/decision lands. (D) **Picker defaults to Auto**: `PromptBoxV2.loadModels` defaults `selectedModel='auto'` when nothing persisted (loads auto-flag first); saved/explicit model preserved; other options untouched. LANDMINES: (1) `create_artifact` page-mode Explain is LLM-emitted JSX — verify it actually renders grounded `<details>`, not generic. (2) pending-lock is belt-and-suspenders — during the window the stream is open so composer already shows Stop (Send not rendered); visible change = inline note + pending card. (3) two backend files hot-cp'd + ONE `docker restart ca-app` (workers=4). Detail → DEVLOG/CHANGELOG 2026-06-28 + [[project_cityagent_analytics]]. **v1.47.0 = AUTO MODEL SELECTION — flag `HYBRID_AUTO_MODEL` (default OFF, ON org `1a073f60`), NO migration, EPHEMERAL (docker cp + fe-sync), NOT baked, NOT pushed.** Model picker gains an **"Auto"** option (sentinel `model_id="auto"`) → `app/ai/knowledge/auto_model.py` complexity classifier (deterministic 0..1 score → Fast/Balanced/Reason → cheapest capable of the org's enabled models; ONE cheap LLM tie-break only in fuzzy band [0.40,0.60]; NEVER raises → org default). Hooked at 3 model-resolution sites in `completion_service.py` (estimate skips classifier); decision persisted to `completion.auto_model` + emitted LIVE as `auto_model` SSE at stream start + v2 top-level field. FE: Auto picker option + live `⚡ Auto → <Model>` chip + "Auto · <Model>" label + Outputs "routed to" pill. LANDMINE: flag-enable needs ONE `docker restart ca-app` (workers=4); two `messages.value` maps differ in indent (tabs vs spaces). Detail → [[project_cityagent_automodel]] + DEVLOG/CHANGELOG 2026-06-28. **v1.46.0 = SAFE-ENABLE WAVE + LIGHTWEIGHT FORECASTING + PER-AGENT SELF-LEARNING — image `d5399fbdbea5`, NO migration, NOT git-pushed.** Enabled the stable hybrid set on org `1a073f60` via DB overrides (62 effective): Wave A (governance/column-intel/compliance/file-browser/agent-connectors) + Wave B (oneclick-artifacts/rich-email/agent-reports/automap/bitemporal/join-graph/quotas/workflows) + safe experimental (context-compact/brain-graph/skill-autogrow/skill-optimize) + cheap daemons (join-mine + studio-learn). Held (cost/risk): ambiguity-gate, autotrain-on-index, pack-autobind, federation (no S3), costly daemons. **Forecast → statsmodels** (`forecast.py` Prophet→`ExponentialSmoothing` seasonal/trend/linear cascade + ±1.96σ band + fail-soft LLM narrative from `runtime_ctx['model']`; `requirements_versioned.txt` `prophet`→`statsmodels==0.14.2`+`patsy`, 10MB not 200MB; flag meta `needs_dep`→`stable`). **Per-agent self-learning** = `studio.config['self_learn']{enabled,cadence(6h|daily|weekly|monthly|off),hour_utc,last_run_at}` (no migration) + NEW `routes/studio_self_learn.py` GET/PUT (owner/editor) + `schemas/self_learn_schema.py` + FE `components/studio/StudioSelfLearn.vue` (Autopilot tab); `studio_learn_daemon.py` rewritten override-aware (`flags.STUDIO_LEARN_DAEMON` — fixed UI toggle being IGNORED) + per-studio `is_due()` cadence + hourly tick + stamps `last_run_at`; `flags.STUDIO_LEARN_DAEMON` property+snapshot; 12/12 cadence tests. Dead toggle `HYBRID_CONTEXT_COMPACT_LLM` (TODO stub) → `HIDDEN_FLAGS` (69 visible). Self-tested local w/ real LLM (forecast ETS+narrative, oneclick dashboard `completed`, compliance/column/workbook). **LANDMINES: (1) `ca-app` `--workers 4` → PUT `set_override` patches ONE worker; every enable wave needs ONE `docker restart ca-app` to converge from DB. (2) daemons that read `os.environ` direct (studio-learn did) ignore the UI override → read `flags.X`. (3) host `main.py` AHEAD of image → `studio_reports.py`+`report_slides.py`+`connection_files.py` were hot-cp-only/missing from image → cp host main.py = ImportError loop until all re-cp'd (now baked). (4) statsmodels pip-installed in container survives restart, LOST on force-recreate until baked.** Prod box 13.251.74.176 still needs this image/files. Full detail [[project_cityagent_analytics]] + DEVLOG 2026-06-27. **v1.45.0 = UI FIRST-RUN SETUP + CONNECTOR ORG AUTO-JOIN + OPENROUTER-FROM-UI — image `b73a9df22e87`, NO migration, NO flag, NOT committed.** Three permanent fresh-install fixes. (A) Zero-user install shows a "Create super-admin" form on `pages/users/sign-in.vue` (same clay page), gated by `needs_setup`=`user_count==0` on `GET /api/settings` (**FAIL-CLOSED**: count error→False→login, never signup); `createAdmin()` POSTs `/api/auth/register`; `auth.py on_after_register` elevates the first user (`users==1&orgs==0`) to `is_superuser`; signup locks after user#1 → screen never returns. Env-free (but `docker-compose.build.yaml` now ALSO passes `DASH_ADMIN_*` through for the headless seed path — compose only used `.env` for `${VAR}` interp, never injected → original prod login-400). (B) ALL external connectors (LDAP/Google/MS/Keycloak/SSO) auto-join the PRIMARY org via NEW `auth.py _ensure_user_in_org(email)` at **6 hooks** (LDAP existing+new, oauth_callback returning+linked+new) — kills the post-login "Create Organization" dump; `Membership(role='member')`+system RoleAssignment, idempotent, fail-soft, rescues orphans on next login. (C) Set the OpenRouter key from Settings→LLM and the 5 seeded models light up: `services/llm_service.py create_provider` now UPSERTS via `_find_upsert_target` (matches the shipped provider across the **openrouter↔custom family** by base_url) + `_apply_key_and_models_to_existing` (set key, add only new model_ids, `_enable_preset_models` on blank→set) — fixes the duplicate/409 that left the preset models keyless (the `"No cookie auth credentials found"` 401); `update_provider` preset-block removed; keys stay DB-only Fernet, FE unchanged. Fresh-install test harness `scratchpad/docker-compose.test.yaml` (`-p catest`, :3017). **LANDMINES: FE OpenRouter card type=`openrouter` but seed=`custom` → matcher must span both; create→update delegation breaks (`_update_models` wants `.id` objects, create sends dicts) → use the `_create_models` dict path; seed encrypts BLANK key so `api_key<>''` SQL is NOT a blank-check, only decrypt is.** Prod box 13.251.74.176 still needs this image/files. Full detail [[project_cityagent_analytics]] + DEVLOG 2026-06-27. **v1.44.0 = PERSONAL GROUPS (My Groups) — image `20316475`, rollback `pre144-rollback`, flag `HYBRID_USER_GROUPS` (ON for org 1a073f60), NO alembic migration but ONE manual DDL.** Any member creates personal contact groups: `routes/me_groups.py` (`/api/me/groups` CRUD + `/api/me/contacts`) + `services/me_groups_service.py`, gated `flags.USER_GROUPS` (404 off). Personal group = `Group` row with `owner_user_id` set; every query scoped `owner_user_id == current_user.id` (can't touch org/admin/LDAP groups); creator auto-added; unique name org-wide via existing `UNIQUE(organization_id,name)` → 409. FE: NEW `pages/settings/my-groups.vue` (full CRUD, DEFAULT layout — visible to ALL via no-permission nav item in `composables/useAppNav.ts`, NOT the permission-gated Settings rail); `StudioAccessPicker.loadGroups` merges `/me/groups` (badge "mine") + admin `/organizations/{org}/groups` (skipped on 403 for non-admins); `StudioCreateGroup` now POSTs `/me/groups` + members from `/me/contacts` (kills old 402/403 on admin org-groups route). **DB LANDMINE: prod `groups` table lacked `owner_user_id` (model had it, never migrated) → manual `ALTER TABLE groups ADD COLUMN owner_user_id varchar(36) REFERENCES users(id)` + index.** **DEPLOY LANDMINE: running image `main.py` predated the me_groups route files → restore IMAGE `main.py` (`docker create`+`cp`) and surgically add only the `me_groups` import + `include_router`; do NOT cp host `main.py` (host is ahead, imports `studio_reports` etc. absent in image → boot ImportError loop).** v1.43.0 = USER PROVENANCE + super-admin-only user creation + email-merge hardening (image `0b2b275d`, rollback pre143-rollback, NO migration/flag, 4 parallel subagents). Identity keyed by EMAIL = one `users` row multi-credential (local pw + `ldap_dn` + `oauth_accounts[]` + `scim_external_id`); SSO `oauth_callback` LINKS by email, LDAP find-or-provision by email → local+LDAP+SSO same email AUTO-MERGE into one id. Members table Source badge via NEW `MembershipSchema.auth_sources` (`_derive_auth_sources` in routes/organization.py: ldap/sso:<provider>/scim/else local; get_members re-queries `selectinload(User.oauth_accounts)` + sets on pydantic schemas). Manual create LOCKED: `add_member`+`create_user_directly` add `is_superuser` 403 (FE hides Add Member+Import unless session `is_superuser`); LDAP/SSO auto-provision untouched. GroupsManager Source badge from `Group.external_provider` (synced groups disable member edit). NEW env `OAUTH_TRUST_EMAIL` default TRUE (no regression); false→refuse SSO email-link unless verified. OpenWebUI parity = their opt-in `OAUTH_MERGE_ACCOUNTS_BY_EMAIL`. v1.42–1.42.1 = GROUP access [share studio→group] + custom_roles un-gate (license.py + useEnterprise.ts BOTH).**
**v1.42.0 = GROUP-based agent access + merged Access tab.
Share a studio to a GROUP (incl. AD/LDAP-synced) → every member auto-sees it in studios list + chat dropdown.
Flag **HYBRID_GROUP_ACCESS** (default OFF; org `1a073f60` now has **9** overrides). NO migration — reuses
`ResourceGrant`(`resource_type='studio'`,`principal_type='group'`,`permissions` JSON). Backend `studio_access.py`
(`group_granted_studio_roles`+`user_group_ids`, resolver step 2.5 write→editor/read→viewer, **`GET /studios` query
OR-includes group-granted ids** = the auto-appear mechanism, both list+`AgentSelector` source `/studios`) + routes
`GET/POST/DELETE /studios/{id}/group-grants`. FE: merged `members` tab INTO `access` (`?tab=members`→access, Delete
in `StudioAccess.vue`); Private/Public toggle (Link=advanced); Groups list + `StudioAccessPicker.vue` (AD-badge,
member counts, Viewer/Editor, `POST /enterprise/ldap/sync`). LANDMINE: `ResourceGrant` col is **`permissions`**
(JSON list), NOT scalar `permission`. P5 inline create-group deferred (toasts pointer). Reuses existing
`ee/ldap/sync_service.py`+`ee/oidc/group_sync_service.py`+RBAC group CRUD — ~70% pre-built; ONLY gap was studio
resolver/list never checking groups. Rollback `pre142-rollback`.**
**v1.41.0 = live studio Training-log (Claude-Code CLI
terminal: per-stage ▸ markers + model/tokens/errors, Logs⇄Steps toggle, Reset/Retry; `train_orchestrator` log[]
buffer + `_RunLogHandler` + `POST /studios/{id}/train/reset`) + AI column meanings (closes gap: nothing wrote
`SemanticColumn.meaning`; new `propose_column_meanings` + `POST /knowledge/ai-suggest-columns/{ds}` gated
SEMANTIC_LAYER + folded into Auto-train semantic_metrics stage auto-approved) + Infographic/InsightMap → SOON.
EPHEMERAL (docker cp + `docker commit`, NOT Dockerfile build). Org `1a073f60` got 8 hybrid_overrides (Intel
flags ON, FORECAST off=needs prophet). Rollback tags `pre140-rollback`/`pre141-rollback`, backups in scratchpad.**
**v1.40.0 = cosmetic chat redesign (Claude/ChatGPT
grammar: collapsible thinking, threaded tool steps, warm `#FAF8F3` canvas incl Outputs pane) + CreateDataTool
no-garble count chip + `awaitingClarify` paused-chip + fresh-DB `create_report` stale-`studio_id` FK guard.
Cosmetic-only, no agent-loop change. EPHEMERAL (FE `yarn generate`+docker cp, backend docker cp+restart) —
NOT baked. Rollback backups in session scratchpad `rollback_phaseA/`.** **v1.37.0 = per-agent scheduled reports + universal
report-delivery (pushed `a5444ab`). v1.38–1.39 = one-click artifacts (flag `HYBRID_ONECLICK_ARTIFACTS`, ON org
55278108): empty report panels become builders — `Generate slide deck` (real python-pptx deck), `Generate
dashboard` (page artifact), and Excel auto-fills via read-only `GET /api/reports/{id}/workbook`. BE
`routes/report_slides.py` (shared `_generate_artifact(mode)` reuses the chat `create_artifact` pipeline);
fixed two pre-existing slides bugs (pptx AST gate forbade `getattr` → `PPTX_ALLOWED_BUILTINS`; empty-category
charts crash → slides-prompt DATA SAFETY rule). v1.38–1.39 EPHEMERAL (`docker cp` + `fe-sync`, NOT baked, NOT
pushed).** Earlier source-only stack (v1.31.0–1.33.1) still applies. Pre-1.28 local backlog still applies. v1.22
= full warm-theme sweep (every page + 148 comps). **v1.23.0 BAKED** = Parquet result storage +
interactive query endpoint (flag `HYBRID_PARQUET_RESULTS` **default ON**) — large step results
(≥`HYBRID_PARQUET_MIN_ROWS`=2000 rows) offload to compressed Parquet on `ca_uploads`; dashboards
push filter/sort/agg to DuckDB via `POST /steps/{id}/query` (allow-listed, no raw SQL). See
`docs/parquet-results.md`. `scripts/safe-upgrade.sh` = guarded bake (backup DB+uploads, health-gate,
auto-rollback).

**v1.25–1.27 (BAKED + live):**
- **v1.25.0 plain-language "What's new":** `CHANGELOG_HYBRID.md` IS the user-facing popover source,
  so it must read plain. Parser `backend/app/services/changelog.py` now splits bullets — **top-level
  `- `** → `features` (user-facing, shown in `WhatsNew.vue` popover, render plain, NO markdown/paths/
  jargon), **indented `  - `** → `details` (technical, hidden from popover, collapsed `<details>`
  toggle on `/changelog` page only). Recent entries rewritten plain. RULE going forward: write
  top-level bullets as plain user copy, push file paths/flags/internals to indented detail bullets.
- **v1.26.0 Channels global-vs-custom:** per-platform mode radio in `StudioChannels.vue` ("Use
  organization default" vs "Custom for this agent") mirroring the Email tab. Mode DERIVED from data
  (per-studio channel row = custom; none = org default) + local override to flip before a row exists;
  global branch shows org-default note + "Remove custom" revert. Mode-aware status chip. Replaced the
  old "🔒 Locked" banner with a data-scope note. **NO backend change** — reuses NULL studio_id → org
  fallback.
- **v1.27.0 equal card buttons:** Decks (`pages/presentations/index.vue`) labels shortened
  (Open & generate→Generate, Open in chat→Chat) + `whitespace-nowrap`+`box-border`+`min-w-0` so the
  `grid-cols-2` buttons stay flat + equal. Dashboards/Home (`components/home/RecentReportCard.vue`)
  button CSS `flex:1 1 0; width:0; box-sizing:border-box; white-space:nowrap` — bordered ghost +
  borderless primary now render identical width.

**v1.28–1.30.2 Identity Provider + LDAP overhaul (v1.30.1 BAKED; v1.30.2 source-only):**
- **v1.28.0 login shows only enabled providers:** `pages/users/sign-in.vue` per-button `v-if` on enabled
  state; `/api/settings` exposes `ldap_enabled` (+ later `ldap_logo`). Google/Microsoft/Keycloak come
  via `oidc_providers` (MS+Keycloak stored AS oidc providers, names microsoft/keycloak).
- **v1.29.0 IdP brand logos + toggles + provider library:** `utils/idpLogos.ts` (preset brand SVGs +
  `idpLogoSvg`), `utils/idpTemplates.ts` (`IDP_TEMPLATES`), `components/idp/IdpLogoPicker.vue`,
  `IdpProviderLibraryModal.vue`. `identity-provider.vue` rows = `ssoRows` computed (Google·Microsoft·
  Okta·Keycloak defaults·custom OIDC) w/ logo + smart 4-state pill (`pillText`/`pillClass`) + inline
  quick-toggle (saves immediately) + "Add provider" library. Logo picker in every config modal.
  Backend `logo:str` on Google/OIDC/LDAP (`_clean_logo`=preset key OR data:image ≤400KB, fail-soft "").
  SCIM has no config object → no logo.
- **v1.29.1 LDAP LOGIN FIX (root cause):** login `core/auth.py` read FILE config `settings.dash_config.ldap`
  while the admin UI saves LDAP to DB `OrganizationSettings.config['ldap']` → UI LDAP IGNORED at login
  (Test worked, login didn't). Fix: `get_effective_ldap_config()` (DB-over-file, own session);
  `UserManager._do_authenticate`/`_ldap_authenticate` use it. `_build_server` derives use_ssl from URL
  scheme (no SSL toggle in UI).
- **v1.30.0 MULTIPLE LDAP directories + username login:** storage `config['ldap_directories']` (list;
  legacy single `config['ldap']` auto-migrates to id="default"). Backend `find_user_by_username`
  ({username} filter, `escape_filter_chars`) = DocSensei-style USERNAME login (not email-only);
  `get_effective_ldap_directories()`; login ITERATES all enabled dirs (username-first → email fallback →
  first success wins → all-unreachable → local break-glass; binds with the dir's email). Routes
  **`/api/enterprise/ldap/directories[/{id}][/test]`** (GET/POST/PUT/DELETE/POST-test) on `ldap_admin_router`
  (prefix `/enterprise/ldap`, mounted `main.py` `enterprise_router` prefix `/api`; EE-gated +
  manage_identity_providers). Pw Fernet, never returned (`bind_password_set`). FE
  `components/idp/LdapDirectoriesPanel.vue` (multi-dir list: row toggle/test/configure/delete + "Add
  LDAP / AD directory") + `LdapDirectoryModal.vue` (DocSensei default fields: name/host/port/bind DN/
  bind pw/base DN/user filter {username}/email+name attr; Advanced collapsed = ssl/tls/group sync/etc).
  Replaced the single-LDAP row+modal in identity-provider.vue. Built by 2 parallel agents.
- **v1.30.1 removed floating robot:** dropped `<RobotAssistant />` (app.vue) + `<AgentThinking />`
  (layouts/default.vue) — gone from all screens. Components kept, just unmounted.
- **v1.30.2 LDAP panel render fix (NOT baked):** LANDMINE — Nuxt auto-imports `components/idp/*` with an
  **`Idp` prefix**, so `LdapDirectoriesPanel.vue`/`LdapDirectoryModal.vue` registered as
  `IdpLdapDirectoriesPanel`/`IdpLdapDirectoryModal`; bare `<LdapDirectoriesPanel>`/`<LdapDirectoryModal>`
  tags resolved to nothing → panel invisible. (`IdpLogoPicker` worked only because its filename already
  starts with `Idp`.) FIX = EXPLICIT imports in `identity-provider.vue` + `LdapDirectoriesPanel.vue`.
  RULE: any component under `components/<dir>/` whose filename doesn't start with `<Dir>` must be
  explicitly imported (or referenced with the dir-prefixed name). User stopped the bake — pending.

**v1.24.0 Per-agent Channels + Email/SMTP + Docker build speedups (BAKED + live):**
- **Channels** + **Email / SMTP** are now their OWN left-rail tabs in the Studio MANAGE group
  (split from the old combined "Access & Channels"): rail = Settings · Access & Members · Channels ·
  Email / SMTP · Members & Share.
- **Channels tab** (`components/studio/StudioChannels.vue`) — org-style **two-pane picker**
  (platform list + detail pane, status dots, set-up/reconfigure/enable/disable/delete). Reuses the
  existing Slack/Teams/WhatsApp/AI-Mailbox config modals + Telegram/MCP inline; same config method,
  org layout. Channels code REMOVED from `StudioAccess.vue` (now "Access & Members" = who/model/
  members/connections only).
- **Email / SMTP tab** (`components/studio/StudioEmail.vue`) — per-agent outbound mail: mode radio
  **global default** (inherit, zero-config) OR **custom SMTP for this agent**. Custom fields mirror
  org SMTP (host/port/security/user/pass/from/validate-certs) + connection test. Stored in
  `Studio.config['smtp']` (Fernet `password_enc`, no migration; `mode` key gates it).
  - Backend resolver `email_client_resolver.py`: new **per-agent SMTP tier** wins over org/global —
    `get_studio_smtp(db, studio_id)` (only when `mode=='custom'`+host), `_studio_smtp_resolved`,
    `choose_outbound(..., studio_smtp=)`, `resolve_outbound(..., studio_id=)`. `studio_id` threaded
    through `notification_service` (dispatch + send_custom_email + _resolved_send), report-share
    (`report.py`, now passes db+org+studio_id → org-SMTP now applies to shares too), and channel
    replies (`email_send_service.py`, `studio_id=report.studio_id`). NULL studio / global mode =
    byte-identical old behavior.
  - Routes `GET/PUT/POST-test /api/studios/{id}/smtp` in `external_platform.py` (flag
    `HYBRID_AGENT_CHANNELS`, owner/editor via `_require_channel_manager`). `StudioSmtpSchema`/
    `StudioSmtpUpdate` mirror `OrgSmtp*`. Verified live: precedence=studio_smtp, routes registered.
- **Dockerfile speedups** — dropped non-deterministic `apt-get upgrade -y` from backend +
  frontend builder stages (pin to base image = cache-stable; runtime `base` keeps its security
  upgrade); added BuildKit cache mounts on `yarn generate`
  (`node_modules/.cache` + `node_modules/.vite`, `sharing=locked`) → warm vite cache makes repeat
  FE rebuilds much faster (v1.24 FE rebuild hit "exporting layers" in seconds vs cold ~4min).
  NOT caching `.nuxt` (stale-module risk). Bake = slow only because `nuxt generate` is inherently
  minutes on first/cold; backend-only changes skip it (FE stage cache-hits).

**v1.20 Nav rail + v1.21 Settings restyle (BAKED):** killed the top-nav **dropdowns**
(Workspace/Build/Manage/Settings). Top items now route directly to the group's first page; a contextual
**left rail** (`components/nav/AppRail.vue`) shows ONLY the active group's items (one group at a time, like
the Skills sub-rail). Nav model extracted to shared composable `composables/useAppNav.ts` (single source for
TopNav + AppRail — `visibleGroups`/`activeGroup`/`isRouteActive`/`firstHref`/`showMcpModal`; module-level
singleton refs OK since SPA/`nuxt generate`). AppRail mounted in `layouts/default.vue` non-report branch
(`<div class="flex"><AppRail/><div class="flex-1 overflow-y-auto"><slot/></div></div>`); self-hides when
`activeGroup` is null (Home, Agent Studios [direct, excluded], detail pages w/ own rail). Studio-detail tabs
persist in URL (`?tab=`). **Warm-theme restyle (token-only migration, NO icon/logo/logic changes — applied
via per-file perl: `#C2683F`→`#C2541E`, `#A8542F`→`#A8330F`, `#E7E5DD`→`#E9E0D3`, `bg-[#FBFAF6]`→`bg-[#F6F1EA]`,
`bg-[#F4F1EA]`→`bg-[#F4EEE5]`, `bg-[#F3E7DF]`→`bg-[#FBEFE4]`, `ui-serif,Georgia[,'Times New Roman'],serif`
→`'Spectral',...`, h1 `text-2xl font-semibold text-[#1f2328]`→`text-[32px] font-medium text-[#211B14]`):**
Workspace Templates (full design rewrite); Build×5 (Knowledge/Instructions[ConsoleInstructions]/Queries/Skills/Memory);
Manage×3 (Connectors/Evals/Workflows); Settings×11 + `layouts/settings.vue` + FolderSyncPanel + Email/WhatsApp/Teams/Slack
integration modals. DESIGN MOCKS at `~/Downloads/login-screen-redesign-request/project/*.dc.html`
(Studios/Home/Workspace/Build/Manage/Settings v2). Pending: Workspace Reports/Dashboards/Presentations/Spreadsheets/Scheduled
+ Monitoring (own `layout: 'monitoring'` console, sits outside AppRail).
LANDMINE: pages with their OWN sub-rail (Skills category rail, Knowledge) show TWO rails (group rail + page rail) — acceptable.
LANDMINE: stack runs on **`docker-compose.build.yaml`** (ca-app/ca-postgres/ca-redis, vol `ca_postgres_data`).
NEVER recreate via plain `docker-compose.yaml` — different project (dash-* names, vol `postgres_data`) = fresh empty DB.

**v1.17–1.18 Claude Design rollout (FE restyle, BAKED, see DEVLOG):** warm palette app-wide
(bg `#F6F1EA`, accent `#C2541E`/`#A8330F`, Spectral + Hanken via `useHead` from TopNav). Login
(v1.17) + Studios/Home/Nav/Reports + new floating **AgentThinking** status widget
(`components/agent/AgentThinking.vue`, global in `layouts/default.vue`, REAL counts from
`/data_sources`+`/llm/models`, no fakes) (v1.18). TopNav now full-width (no `max-w` centering).
Report scope = segmented tab; report cards keep REAL `thumbnail_url` preview. Studio **detail** page
also rethemed warm. **FIXED studio-Open crash** (`reading 'name' of null` on REFRESH): teleported
`FolderSyncSetupModal`/`FolderSyncCard` read `studio.name` in a separate reactive scope during the
cold-load null window → `v-if="studio"` + `studio?.name`. LANDMINE: teleported modal/popover props
that read a fetched ref are NOT covered by the parent's `v-else-if="data"` guard — `?.`-guard them.
New `scripts/fe-sync.sh` = host `nuxt generate` + `docker cp`→ca-app dist (no rebuild, EPHEMERAL).
Local admin reset to `admin@cityagent.io`/`Admin12345` (fastapi-users = **argon2id**, not bcrypt).

**v1.13–1.15 (2026-06-25):**
- **v1.13.0** super-admin DIRECT user create (no invite): `POST /api/organizations/{id}/members/create-user`
  (admin-gated) + Members "Add user" modal. LANDMINE: do NOT route through `manager.create()` — its
  `_validate_user_creation` gate 400s non-first signups ("Sign-up is disabled"); insert the User directly
  (`PasswordHelper().hash` + is_active/is_verified) like the OAuth path, then add Membership. Also added the full
  `HYBRID_*` env block to `docker-compose.nginx.yaml` (it had NONE → every flag defaulted OFF, Studios locked) with
  visible features ON + a `redis` service.
- **v1.13.1** dashboard fullscreen black-charts fix: `ArtifactFrame` renders a 2nd iframe; `sendDataToIframe()` only
  posted to the bg iframe → fullscreen got no `ARTIFACT_DATA`. Now broadcasts to both + re-send on its load.
- **v1.13.2** see v1.13.0 LANDMINE (the direct-insert fix).
- **v1.14.0** ALL 65 hybrid flags toggleable in **Settings → Features** (was ~32). Extended `UPGRADE_FLAGS` with
  `category`/`status`/`note` for every flag + grouped/searchable UI + confirm dialog on risky enables. `_effective()`
  in `routes/organization_settings.py` falls back to override-or-env for the env-only daemon knobs
  (`EVAL_SCHEDULE_ENABLED`/`JOIN_MINE_ENABLED`/`STUDIO_LEARN_DAEMON_ENABLED` have no `flags` property). LANDMINE
  reconfirmed: a flag absent from `UPGRADE_FLAGS` is invisible in the UI AND its PUT 400s.
- **v1.15.0** Hybrid Search (`HYBRID_SEMANTIC_SEARCH`) is now REAL. **OpenRouter SUPPORTS embeddings** via its
  OpenAI-compatible `/embeddings` — `openai/text-embedding-3-small` (1536d = matches the existing
  `knowledge_search_index.embedding vector(1536)` column, NO migration), reusing the org's existing OpenRouter key.
  New `app/ai/knowledge/embeddings.py` (AsyncOpenAI, batched, fail-soft) + `indexer.py` (`reindex_org` from approved
  semantic/metrics/queries/docs → tsv + vectors); `hybrid_search.py` gained a pgvector cosine arm + 3-way RRF;
  `HybridSearchContextBuilder`+section wired into `context_hub` (gather tail) + `agent_v2` (gated). Routes
  `POST /api/knowledge/reindex` + `GET /api/knowledge/search-index/status`; Rebuild-index button on the Features
  Hybrid-Search row. Proven live (293 indexed+embedded, OpenRouter 200, relevant RRF hits). Optional reranker NOT
  added (RRF deemed enough; bolt-on later via OpenRouter rerank if needed).

**v1.11.0 One-command deploy + env super-admin:** (1) DEPLOY FIX: `Dockerfile` was `FROM cityagent-base:dev`
(local-only image from `Dockerfile.base`, never in a registry) → clean prod `docker compose up --build`
failed "pull access denied". FIXED by folding base into main Dockerfile as internal stage `FROM ubuntu:24.04 AS base`
(byte-for-byte Dockerfile.base content: MS ODBC/FreeTDS/libreoffice/poppler/playwright-deps + app user) +
final stage `FROM base`. Stages now: backend-builder, qvd2parquet-builder, frontend-builder, base, final.
`Dockerfile.base`+`scripts/build.sh` kept as optional fast-dev path. New `deploy.sh` (bootstrap .env→warn key→
compose up). (2) ENV SUPER-ADMIN: no global-superadmin existed (model=first registered user→org owner via
auth.py:715 `user_count==0` + `_ensure_org_for_first_uninvited_user`); sign-up link removed v1.8.0 so fresh box
was stuck. NEW `backend/scripts/seed_admin.py` (async, idempotent, fail-soft) run ONCE in `start.sh` after
alembic before uvicorn: reads DASH_ADMIN_EMAIL/PASSWORD/NAME, skips if unset OR email exists, else creates via
real user-manager (`get_user_db`→`get_user_manager`→`manager.create(UserCreate, safe=False)` → fires
on_after_register→org+owner) then fresh-session sets is_active/is_verified/is_superuser=True. Imports:
`app.dependencies.async_session_maker`/`get_user_db`, `app.core.auth.get_user_manager`,
`app.schemas.user_schema.UserCreate` (name min_length 3). Vars in docker-compose.yaml app env + .env.example.
PROVEN live: no-env→skip, existing-email→"already exists skipping". Baked. LANDMINE: seeder gates on email-exists
NOT user_count==0 — a NEW email on a populated DB would create a non-first user (no bootstrap org); intended use =
fresh deploy only.

**v1.10.0 Per-agent access control + Telegram channels:** an agent = a `Studio`. New flags
`HYBRID_AGENT_ACL` + `HYBRID_AGENT_CHANNELS` (`hybrid_flags.py`, default OFF, ON org 55278108).
(1) ACL: chat-time enforcement in `completion_service.py` — if `flags.AGENT_ACL` and
`report.studio_id`, calls `resolve_studio_access` (studio_access.py); None→403. Applied to BOTH
non-stream + stream completion paths (NOT the token-estimate path). Most ACL primitives already
existed: `Studio.share_scope` (private/org/link), `StudioMember`, member CRUD + `/share` routes.
(2) Per-agent model override: precedence request `prompt.model_id` > `studio.config['model_id']` >
org default (same 2 paths, flag-gated). (3) Telegram: mig `agentchan1` adds `studio_id`+`audience`
to `external_platforms`; routes in `external_platform.py` (`POST/GET/enable/disable/DELETE
/api/studios/{id}/channels[/telegram]`) + public inbound `telegram_webhook.py`
(`POST /api/ext/telegram/{studio_id}/webhook`, registered in `main.py`). Reuses ExternalPlatform
encrypt/decrypt_credentials, ExternalUserMapping verification (24h token), ReportService.create_report,
CompletionService.create_completion (foreground, reads back final answer), `telegram_send` via httpx.
Audience members(verify) | anyone(runs as owner). Webhook ALWAYS returns 200 {ok:true} (Telegram
no-retry). UI: `StudioAccess.vue` "Access & Channels" tab in `studios/[id]/index.vue` (who-can-use
radios, members, model dropdown, channels list + Telegram add modal); uses `useMyFetch`, fails soft
on 404. Members GET shape = existing `{id,user_id,role,user_name,user_email}` (NOT email/name).
LANDMINE v1: Telegram reply is SYNC foreground completion (slow agents may exceed webhook timeout —
v2 needs background + adapter). LANDMINE: `/verify/{token}` FE page not built (verify loop open).
LANDMINE: `/app/frontend/dist` owned by ROOT — `docker cp` needs `docker exec -u 0` rm + chown app:app.

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
