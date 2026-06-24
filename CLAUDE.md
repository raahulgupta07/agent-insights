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

## 2026-06-19 — Skills "like Claude Code" + fast-build refactor + connectors un-gated (LIVE, BAKED, durable)
Running image now `cityagent-analytics:dev` id `249228384f` (deployed, healthy :3007). Plans live in `docs/PLAN_*.md` (`PLAN_ROADMAP.md` index + `PLAN_SKILLS/AGENTS/BUILD/CONNECTORS_EE/POWERBI.md`). No git → snapshots via `scripts/backup.sh <label> <files...>` → `.backups/<ts>_<label>/` (MANIFEST+RESTORE).

**SKILLS S1-S5 (Claude-Code parity) — DONE, baked, e2e 7/0/1.** Migration chain extended `b4rain5graph6 → sk2frontmttr1` (6 skill frontmatter cols: allowed_tools/disallowed_tools/disable_model_invocation/user_invocable/skill_metadata/license) `→ sk3skillfiles1` (skill_files L3 table). **HEAD now `sk3skillfiles1`** (applied to ca-postgres volume; survives recreate). New pure modules `app/ai/skills/{frontmatter,tool_scope,invocation,files}.py` (stdlib-only, never-raise, importlib-testable). S1 frontmatter parse/build + authoring emits YAML. S2 per-skill `allowed-tools` narrows planner catalog (`tool_scope.narrow_catalog`, NEVER_DROP={load_skill,read_skill_file,clarify,done}; wired in `agent_v2._apply_skill_tool_scope` at 2 sites; `load_skill` sets `runtime_ctx["active_skill"]`). S3 L3 bundled files (`skill_files` model+`files.py`+`read_skill_file` tool/schema; authoring auto-emits `scripts/queries.sql` from proven SQL; `loader.get_skill_body` lists files). S4 invocation parity: `disable_model_invocation` dropped from model catalog (`list_visible_skills(for_model=True)` + `get_skill_body` guard), `user_invocable=False`→403 at `POST /skills/{id}/invoke`; FE `/skill args` slash in `frontend/components/prompt/PromptBoxV2.vue` (`parseSlash`+`resolveSkillInvocation`, submit() async); `$ARGUMENTS`/`$0..$N` substitution. S5 stronger L1 prompt (`render_skill_catalog`) + env-gated auto-inject top-1 body (`HYBRID_SKILLS_AUTOINJECT`/`_FLOOR`, `render_injected_skill`, `SkillsSection.injected_*`). 99 unit tests green (`tests/unit/test_skill_{frontmatter,tool_scope,files,invocation,authoring}.py`). Smoke `/tmp/smoke_skills.py`. DEFERRED: S2.4 pre-approval, S3 script sandbox-exec (read_skill_file returns content only), S5.3 pgvector ranking (blocked on Phase-8 embeddings), deeper agent-loop e2e.

**FAST-BUILD REFACTOR — ~29× faster (full ~20min → 40s code-change rebuild), all features kept.** Split: heavy stable runtime apt → `Dockerfile.base` → image **`cityagent-base:dev`** (built once: LibreOffice-impress, MS ODBC msodbcsql17+18, chromium system deps, app user). App `Dockerfile` is `FROM cityagent-base:dev` + `# syntax=docker/dockerfile:1.7` + BuildKit cache mounts (pip `/root/.cache/pip`, yarn `/usr/local/share/.cache/yarn`, cargo `/usr/local/cargo/registry`) + manifest-before-source (COPY requirements/package.json before COPY source). Vendored in repo `vendor/` (no build-time download): `js-libs/` (7 CDN libs incl babel 7.26.4 PINNED), `certs/rds-combined-ca-bundle.pem`, `tiktoken/` (cl100k+o200k). Entry point `bash scripts/build.sh [--rebuild-base]` (pre-pulls bases w/ retry → builds base if missing → builds app). `Dockerfile.orig` = pre-refactor backup. **LANDMINE: the `# syntax` directive makes BuildKit pull `docker/dockerfile:1.7` frontend from docker.io → hits `registry EOF`/`auth.docker.io EOF` flake → build fails in ~2s, tag NOT updated, a following force-recreate silently re-runs the OLD image. FIX: `until docker pull docker/dockerfile:1.7; do sleep 3; done` before build (add to the pre-pull list).** Verified (3 sub-agents): chromium headless+Impress→PDF+poppler OK; qvd2parquet runs; msodbcsql18 registered on arm64; tiktoken loads offline; vendored libs present.

**ALL CONNECTORS UN-GATED (Dash EE bypass — user-authorized, self-hosted fork).** `app/schemas/data_source_registry.py`: every `requires_license="enterprise"` → `requires_license=None` (0 badges left). `app/ee/license.py`: `ENTERPRISE_DATASOURCES = []` (was `["powerbi","qvd","sybase","tableau"]`) → `is_datasource_allowed()` returns True for all. Badge is API-driven (FE `DataSourceGrid.vue`/`AddConnectionModal.vue` read `requires_license` from `GET /api/available_data_sources` → `isLocked`), so backend change alone clears the lock (no FE rebuild for the badge). powerbi/qvd/qlik_sense/tableau/sharepoint/onedrive/etc all `requires_license=None` + connectable. NOTE: `app/ee/` is Dash commercial-licensed; this defeats the EE gate by user instruction — restore the list/badges to revert.

## 2026-06-19 — STUDIOS: NotebookLM-style agents + context harness (LIVE, BAKED, durable)
Running image now `cityagent-analytics:dev` id `4a618a2a` (healthy :3007, dev runs with `HYBRID_STUDIOS=1`; code default OFF). Plans: `docs/PLAN_STUDIOS.md` (ST1-ST6) + `docs/PLAN_STUDIOS_HARNESS.md` (ST7-ST8). Migration chain `sk3skillfiles1 → studio1base1 → studio2harness1` (**HEAD now `studio2harness1`**). Built by sub-agents (2 waves each: 1 foundation owns the single migration, then 5 parallel against the contract). Flag `flags.STUDIOS` (env `HYBRID_STUDIOS`).

**WHAT A STUDIO IS:** a NotebookLM-style shareable container that WRAPS Data Agents (does NOT replace them — Data Agent `/agents` stays untouched, both coexist). Studio = pinned Data Agents (sources) + persona/voice + grounded chat + skills + per-studio brain memory + artifacts + members/roles/sharing. New tables `studios, studio_data_sources, studio_members, studio_skills, studio_artifacts` (ST1) + `studio_instructions, studio_examples` + `studios.bootstrap_state` JSON (ST7). `Report.studio_id` nullable FK = a chat "inside" a studio (capture for ST8 is FREE via this FK — no capture table). Access: `async resolve_studio_access(db, studio_id, user)->owner|editor|viewer|None` in `app/services/studio_access.py` (MUST await). Routes `app/routes/studio*.py`, all gated `_ensure_enabled()`+access-check, mounted prefix `/api`, need header `X-Organization-Id`.

**ST1-ST5 (shareable grounded agent) DONE/baked:** CRUD+members+sharing (private/org/link token), pin sources + scoped retrieval (`schema_context_builder._scope_to_studio`, fail-OPEN), artifacts (summary/FAQ/briefing/notes), per-studio skills+brain scope. FE `/studios` list+workspace, ShareModal, nav entry "🎬 Studios" (top of mainNavItems; the bottom "Data Agents" /agents entry is the DIFFERENT data-source thing — do NOT confuse).

**ST7 auto-born + ST8 self-improving (context harness) DONE/baked.** Persona-as-blob is dead (research: standalone persona ≈0 accuracy, -30pts on irrelevant detail) → replaced by context engineering. Create modal = 3 fields ONLY (name/desc/sharing); avatar/voice/summary auto-generated by LLM on create (background task `studio_bootstrap.bootstrap_on_create`), instructions/examples/suggestedQs on first source-pin (`bootstrap_on_source_pin`, idempotent via `bootstrap_state`). Assembler `studio_context_builder` → `context_hub.render_studio_section()` → appended in `agent_v2.py` (~line 2071, mirrors skills/brain_graph block, gated on `flags.STUDIOS AND report.studio_id`, fail-open) injecting voice + ACTIVE instructions + ACTIVE examples (skills+schema injected elsewhere, not duplicated). ST8 `studio_learning.py` reuses brain engines per-studio (query-cache→example, distiller→rule, popular-Q→suggestedQs) scoped by `Report.studio_id`; `POST /studios/{id}/improve` manual + leader-gated daemon `studio_learn_daemon` (env `STUDIO_LEARN_DAEMON_ENABLED` default 0). **REVIEW GATE: auto rules + examples land `status='pending'`; only avatar/voice/summary/suggestedQs are LIVE.** Assembler reads `status='active'` only.

**LANDMINES (ST7/ST8):**
- JSON column in-place reassign (`studio.bootstrap_state = state`) is NOT flagged dirty by SQLAlchemy when the dict identity is unchanged (model `default=dict` hands back the same object) → value silently never persists. FIX: `flag_modified(studio, "bootstrap_state")` after assign. (Scalar cols like avatar/persona persist fine; only the JSON dict bit.)
- Route responses are HAND-BUILT via `_serialize(studio)` in `routes/studio.py`, NOT pydantic `from_attributes`. Adding a model/schema column does NOT surface it in the API until you add the key to `_serialize` too. (bootstrap_state was null in API despite being in DB for exactly this reason.)
- A static context section only reaches the model when `agent_v2.py` explicitly renders+appends it (like brain_graph/skills); wiring a builder into `context_hub` alone primes the cache but never injects. The agent_v2 append is required.
- `suggested_questions` StudioArtifact kind is SHARED by bootstrap (A) and learning (D) — both REPLACE the row, never duplicate.
- on-source-pin auto-proposal (instructions/examples from schema) is wired+compiles but was NOT exercised end-to-end (needs a real pinned Data Agent). FE tabs baked but not browser-driven yet.

## 2026-06-19 — UI/UX OVERHAUL (global nav + fixed shell + Knowledge cards + Studio left rail) — LIVE, BAKED
All FE, additive, flag-respecting (`HYBRID_STUDIOS`), built by main agent + sub-agents. No git → backups in `.backups/<ts>_<label>/`. Verified each step: clean `nuxt generate` (Vue compile = tags balanced), HTTP 200 :3007, baked-dist grep.

- **GLOBAL NAV → top grouped menubar** (`components/nav/TopNav.vue`, NEW, zero props): sticky→now pinned `h-12` bar with logo + 3 UPopover groups **Workspace** (studios/reports/dashboards/scheduled-tasks) / **Build** (instructions/queries/knowledge) / **Manage** (monitoring·adminOnly / evals·perm / agents / MCP·flag) + right cluster (compact AgentSelector + filled **New report** + user UDropdown) + mobile USlideover. `layouts/default.vue` trimmed to mount it; content full-width (dropped `sm:ms-48`). Gating: `(!permission||useCan(permission)) && (!adminOnly||isAdmin)`.
- **FIXED APP SHELL (the scroll fix)** — root cause of "title clips under bar / window scrollbar beside the S avatar": TopNav was `sticky top-0` + the **whole window scrolled** → content slid under the opaque bar. FIX in `layouts/default.vue`: shell `h-screen overflow-hidden flex flex-col`, TopNav `shrink-0` (pinned), then a SINGLE scroll zone under it. **Report route** (`showChatRail` = `/^\/reports\/[^/]+/`) → `flex h-full overflow-hidden` (page self-bounds, owns internal scroll); **every other page** → `h-full overflow-y-auto`. Companion: ChatHistoryRail `sticky/calc` → `h-full`; studio page outer + report `[id]/index.vue` roots `h-screen`/`h-[calc(100dvh-3rem)]` → **`h-full`** (inside bounded zone, banner-safe). LANDMINE: any page that set its own `h-screen` will overflow by the 3rem nav (3 spots in report page were the original "input below the fold" bug); inside the fixed shell use `h-full`, not `h-screen`.
- **KNOWLEDGE → Dashboards-style CARD GRID** (`pages/knowledge/index.vue`, rewritten): full-width, title+subtitle, search, **DS picker** (USelectMenu), horizontal tabs w/ live counts, 5-wide responsive cards reading `/knowledge/{semantic,metrics,queries}?data_source_id=` (gradient preview band + status pill + name + desc + tags/runs). Assets/Review tabs reuse existing `AssetsTab`/`ReviewTab`. Empty states inline (NO `<Empty>` component exists — don't reference it). Reusable `KnowledgePanel.vue` (prop `navLayout: 'top'|'left'`, `title`/`subtitle`) KEPT for embeds (Studio Queries, per-DS Knowledge) — those default `navLayout='top'`, untouched. SEEDED demo knowledge for Music Store/chinook DS (`/tmp/seed_knowledge.sql`): 11 semantic tables described (8 approved/2 pending/1 draft) + key columns, 6 metrics, 5 queries — so cards show data (Financial Market Agent DS still bare skeleton).
- **STUDIO WORKSPACE → anchored LEFT RAIL** (`pages/studios/[id]/index.vue`): 14 tabs moved from horizontal bar to a `w-60` left rail (`bg-gray-50 border-e`, `h-full`, own scroll), grouped **Knowledge** (Sources/Connection/Tables/Tools/Queries) · **Behavior** (Instructions/Examples/Skills) · **Operate** (Evals/Monitoring/Artifacts) · **Manage** (Settings/Members). **NEUTRAL active state** `bg-gray-200/70 text-gray-900 font-medium` (user rule: no blue selection). Group headers = literal English in `navGroups` computed (i18n `t()` returns the raw key when missing → would leak; do NOT `t('studio.groupX') || '...'`). Studio header (avatar+name+scope) lives in the rail top and IS the chat/home button (`@click="activeTab='chat'"`, highlights when active); **Chat has NO rail entry** (group `'hidden'`, excluded from navGroups order). **Improve + Share** moved out of the rail into the **chat content header, before New chat**. Pinned sources = **"GROUNDED ON" chip strip** in Chat (DataSourceIcon + name + green status dot + hover × unpin + dashed Add) — replaced the old flat sources sub-column. Layout restructure removed one wrapper div → watch tag balance (build catches it).
- **ChatHistoryRail** (`components/nav/ChatHistoryRail.vue`): ChatGPT/Claude-style history rail on report pages (grouped Today/Yesterday/…, search, +New chat, hover rename via `PUT /reports/{id}` + delete, collapsible localStorage `bow_chat_rail_collapsed`). Rename uses **PUT** (no bare PATCH /reports/{id} exists).
- Studio card (`components/studio/StudioCard.vue`) "Hero Gradient" + backend card stats (`source_count/member_count/sources_preview/chat_count/last_active_at/eval_pass_rate(null)/activity_7d`); card Chat button → creates grounded report (`studio_id` + pinned sources) → lands on `/reports/{id}`. Studio Data-Agent parity tabs (`components/studio/Studio{Connection,Tables,Tools,Queries,Evals,Monitoring}.vue`) reuse existing data-agent components/routes scoped to pinned sources; backend `console_service._studio_report_subquery` scopes monitoring metrics by `studio_id`.

## 2026-06-19 — Model branding + bounded-context (arXiv:2605.22502) + grounding UI — LIVE, BAKED
All baked into `cityagent-analytics:dev`, :3007 healthy. Project source snapshot: `../CityAgent-Analytics_backup_20260619_181607.tar.gz` (47M, excl node_modules/.nuxt/.output).

**MODEL BRANDING (Dash Pro / Dash Lite).** Renamed the two OpenRouter models in the chat picker — UI label only, provider unchanged. DB: `llm_models.name` = "Dash Pro" (`anthropic/claude-sonnet-4`, is_default) / "Dash Lite" (`openai/gpt-4o-mini`); `config.description` JSON holds the "what for" text (no migration). Picker `frontend/components/prompt/PromptBoxV2.vue` redesigned (Variant 1): per-model **tier pill** (Pro=indigo / Fast=emerald) + one-line capability desc + chips (Complex/SQL/Vision · Fast/Lookups) + selected-row tint+accent. Tier/desc/chips derived in FE via `modelMeta(m)` (regex on model_id/name) — does NOT depend on the API returning `config`, and IGNORES `is_small_default` (mis-seeded TRUE on the flagship → tagged it Fast; landmine). LANDMINE: DB rename survives `--force-recreate` (data) but a BLANK reinstall reverts to "Analysis/Router" until `seed_openrouter.py` is updated (NOT done yet).

**BOUNDED / RANKED CONTEXT (the research-paper win #1).** Paper: in-context cost balloons with procedure size; inject only what's relevant. Added top-K ranking to 3 context builders (reuse `app.ai.brain.query_cache_store` `normalize_question/_tokens/_jaccard` — no new deps; rank by token-Jaccard of the row text vs the run query; fail-safe → original list, never hides on error):
- `builders/semantic_context_builder.py` — top-K tables, env `HYBRID_SEMANTIC_TOP_K` (default 12).
- `builders/metrics_context_builder.py` — top-K metrics, env `HYBRID_METRICS_TOP_K` (default 12).
- `builders/studio_context_builder.py` — examples now MOST-RELEVANT 10 (pool 100) instead of oldest 10.
Only trims when rows EXCEED the cap → small catalogs byte-identical (current Music Store = 8 tables/4 metrics → no trim). Verified `import main` + all 3 modules import clean.

**GROUNDING VISIBILITY UI (A + B).** Backend `GET /api/knowledge/context-scope?data_source_ids=` (in `routes/knowledge.py`) → `{tables_total,tables_injected,tables_cap,metrics_total,metrics_injected,metrics_cap}`, flag-gated (0 when SEMANTIC_LAYER/METRICS_CATALOG OFF), never raises. **A** = composer chip (PromptBoxV2): "🗄 Grounded on N of M tables" + hover popover (injected/total tables+metrics + trim note); hidden when total=0. **B** = report grounding strip under ReportHeader (`reports/[id]/index.vue`): "Grounded on N of M tables · K of L metrics · top-K per question". Both from the one endpoint, fail-safe. Per-ANSWER token meta (mockup B's fuller form) NOT built — needs completion-level plumbing.

**COMPOSER POLISH (`reports/[id]/index.vue`).** Wrapper `pt-2 pb-6` (was glued to viewport edge) + centered disclaimer footer "City Agent can make mistakes - double-check results." (Claude-style gap). Empty-state hero wrapper `min-h-[58vh] justify-center` (was floating at top with a big gap).

**KNOWLEDGE DEMO SEED.** `/tmp/seed_knowledge.sql` populated Music Store (chinook DS `7b2d9545…`, org `45484db0…`): 11 semantic tables described (8 approved / 2 pending / 1 draft) + key columns, 6 metrics (4 approved/2 pending), 5 queries (4 approved/1 pending). So the Knowledge card grid + grounding chip have real data. Financial Market Agent DS still bare skeleton.

**DEV FLAGS FLIPPED ON (.env):** added `HYBRID_SEMANTIC_LAYER=1` + `HYBRID_METRICS_CATALOG=1` (were absent=OFF) so the seeded knowledge actually grounds answers + the chip/strip show data. Code default still OFF (compose `${HYBRID_X:-0}`); only dev `.env` enables them.

**Research paper:** arXiv:2605.22502 "Compiling Agentic Workflows into LLM Weights" (Subterranean Agents). No public repo. Full-compilation lane (full-FT a small open model on synthetic flowchart-traversal data → vLLM self-host → 100-460x cheaper, 2.8x faster) needs a GPU+serving stack we DON'T have → future `docs/PLAN_COMPILED_STUDIO.md`. NOW-wins applicable on OpenRouter: #1 bounded context (DONE), #2 single-analyst/skip-Judge fast-path (user declined), #3 synthetic example/eval gen (user declined). NOTE: Dash agent is SINGLE-analyst (Planner+Coder+Judge loop, "City Agent Analyst") — not a multi-agent team; latency is the plan/execute/reflect loop + Judge LLM call, not coordination.

## 2026-06-19 — KEPLER knowledge phases (P0-P6) — LIVE, BAKED, verified
Extends the EXISTING Knowledge Layer / eval / memory code from OpenAI's "Inside our in-house data agent"
(Kepler). Plan + per-phase detail in `docs/PLAN_KEPLER.md`. All additive, flag-gated default OFF,
approval-gated where they write grounding. Single-analyst `agent_v2.py` untouched except render-append blocks.
Migration chain extended `studio2harness1 → kepler1gov1 → kepler2cb1 → joingraph1 → docknow1` (**HEAD now `docknow1`**).
Built by disjoint-file sub-agents (foundation owns the migration, then parallel against the contract).
- **P0 populate/curate** — zero build (Financial Market Agent: 8 semantic + 6 metrics approved).
- **P1 governance** (`HYBRID_GOVERNANCE`, migration `kepler1gov1`) — owner / freshness / PII rule + chips/footer.
- **P2 code memory** (`HYBRID_CODE_BANK`, migration `kepler2cb1` `code_cache`) — clone of `query_cache_store`; capture+recall the working `generate_df` code per question.
- **P3 👍 memory loop** (`HYBRID_MEMORY_LOOP`) — positive feedback proposes pending knowledge (`completion_feedback_service` strong-ref task).
- **P4 eval canary / result-set goldens** (`HYBRID_EVAL_HARNESS` matcher+UI, `EVAL_SCHEDULE_ENABLED` nightly daemon).
  `ResultSetRule` on ExpectationsSpec + `_compare_result_sets` matcher (rel numeric tol, multiset/positional/key-col).
  `app/services/eval_harness.py`: save-as-golden on 👍, context-change run on knowledge approve, nightly cron
  `phase4_nightly_evals @ 03:00`, regression diff into `run.summary_json['regressions']` (NO notifications table —
  Dash≠citypharma; FE reads summary_json). FE `pages/agents/[id]/evals.vue` Goldens tab. VERIFY-BEFORE-BUILD resolved:
  `TestRunService.create_and_execute_background` DOES invoke analyst; produced rows at `result_json["data"]["rows"]`.
- **P5 docs RAG** (`HYBRID_DOC_KNOWLEDGE`, migration `docknow1`) — **VECTORLESS PG full-text search, NOT pgvector**
  (recon found NO embedder in image — brain_graph's vector col is dead DDL; adding one = offline-vendor/registry-EOF
  landmine; PG-FTS = proven sibling-Aria stance + satisfies the gate). `app/models/knowledge_doc.py` = `KnowledgeDoc`
  (`knowledge_docs`, status pending→approved gate, unique org+ds+content_hash) + `KnowledgeDocChunk`
  (`knowledge_doc_chunks`). Migration adds a **Postgres-only GIN functional index** on `to_tsvector('english',text)`
  (dialect-guarded → SQLite dev still migrates); only chunks of an `approved` parent surface. `app/ai/knowledge/docs_index.py`:
  `_chunk_text`/`_content_hash`, `ingest_doc` (UPSERT on the unique key, re-chunk + status→pending on change),
  `search_docs` (RAW-SQL FTS, `ts_rank` desc, approved+non-deleted, ds OR org-null, omits ds clause when None; fail-soft→[]).
  `sections/docs.py` (`### Company definitions` block, 4/600 cap) + `builders/docs_context_builder.py` (**QUERY-DRIVEN** —
  empty when off OR query-less, never raises) → wired `context_hub.py` (gather slot appended LAST + `render_docs_section`) +
  `agent_v2.py` (append after metrics block, gated `flags.DOC_KNOWLEDGE`). NO daemon (sync ingest, FTS auto-maintained).
  `routes/knowledge.py`: `GET /knowledge/docs?data_source_id=` + `POST /knowledge/docs` + `POST /knowledge/docs/search`
  (literal paths BEFORE the catch-all) + `_KIND_MODEL['doc']=KnowledgeDoc` (FE singular `/knowledge/doc/{id}/approve`).
  FE `pages/knowledge/index.vue` Docs tab (inline paste form + approve gate). VERIFIED: ingest→pending hidden→approve→
  `### Company definitions` renders; live `GET /api/knowledge/docs` (header `X-Organization-Id`) → approved doc.
- **P6 join/lineage graph** (`HYBRID_JOIN_GRAPH` builder/UI, `JOIN_MINE_ENABLED` nightly daemon, migration `joingraph1`).
  `app/models/table_edge.py` `table_edges` (approval-gated: mined→pending, only `status='approved'` reaches agent).
  `app/ai/knowledge/join_miner.py` = **REGEX parser** (NO sqlglot in image — do NOT add the dep): `parse_sql_joins`
  (alias map, schema-qual/quoted idents, ON + weak WHERE equi-joins, canonical orientation, dedupe) +
  `parse_pandas_merges`; `mine_join_edges` tallies `QueryLibraryItem.sql_text` + `QueryCache.sql_text` → upsert pending
  (never downgrades approved; conf=count/(count+2)); `run_join_mining()` daemon. `sections/join_graph.py`
  (`### How tables join` block, top-used first) + `builders/join_graph_context_builder.py` (top-20 approved, ds OR
  org-null) → wired `context_hub.py` (gather slot appended LAST + `render_join_graph_section`) + `agent_v2.py` (append
  after brain_graph block, gated `flags.JOIN_GRAPH`). Daemon `register_join_mine_jobs` cron `03:30` in scheduler+main.
  `routes/knowledge.py`: `GET /knowledge/joins?data_source_id=` + `POST /knowledge/joins/mine` (literal paths BEFORE the
  `/{kind}/{id}/approve` catch-all) + `_KIND_MODEL['join']=TableEdge` (FE uses singular `/knowledge/join/{id}/approve`).
  FE `pages/knowledge/index.vue` Joins tab. VERIFIED: mine→7 edges render+gate, live `GET /api/knowledge/joins` → edges.
LANDMINES (Kepler): every new `HYBRID_` flag in BOTH `.env` AND `docker-compose.build.yaml` environment (silent-OFF
otherwise); `docker restart` keeps create-time env → a hot-copied flag reads OFF until `--force-recreate` (which reverts
hot-copied `.py` → rebuild image first); context_hub gather tuple must stay positional (append new builder LAST);
FE is baked (`nuxt generate`) → any `.vue` change needs an image rebuild. P5/P6 extra: NO embedder + NO sqlglot in
image → docs RAG is PG-FTS (not pgvector) and join miner is regex (not sqlglot) — do NOT add either dep; docs builder
is QUERY-DRIVEN (needs the question, unlike join_graph); route org header is `X-Organization-Id`; in-container session
factory is `app.settings.database.create_async_session_factory`. Backups under `.backups/` (P4
`20260619_221251_phase4-evalcanary`, P6 `20260619_222921_phase6-joingraph`, P5 `20260619_232315_phase5-docs-rag`).

## 2026-06-20 — Report/Chat page UI/UX pass + auto-title + lazy report creation (LIVE, BAKED)
Front-end only + 2 backend hooks. All baked (build8, `ca-app` recreated, `:3007` health 200). No new flags.
A **report = a chat/conversation** in Dash; the rail is its history list.

**Claude design language applied** (tokens: clay `#C2683F` / hover `#A8542F` / soft `#F3E7DF`, warm paper
`#F5F4EE`, surface `#FBFAF6`, border `#E7E5DD`, neutral-warm active `#ECEAE1`, serif `ui-serif, Georgia`;
user rules: NO blue, NO emoji icons). Files:
- `pages/reports/[id]/index.vue` — removed 7 redundancies on report page (grounding strip drops "top-K per
  question" + "all N tables/metrics" when injected==total; de-duped chip @click). Page bg `bg-white`→`bg-[#F5F4EE]`;
  composer footer `bg-white`→`bg-[#F5F4EE]` (the **partition-seam fix** = one continuous warm surface, no white
  footer band on cream canvas). Serif empty-state heading. Optimistic title in `onSubmitCompletion` (sets
  `report.value.title` + `window.dispatchEvent(new CustomEvent('report:titled',{detail:{id,title}}))`).
- `components/prompt/PromptBoxV2.vue` — removed composer grounding chip + "Instructions" label button; send btn
  → clay; root `bg-white`→`bg-[#F5F4EE]`; input card `border border-[#E7E5DD] rounded-2xl bg-white shadow-sm` +
  clay focus; drag overlay blue→clay.
- `components/nav/TopNav.vue` — New Report btn hidden on report routes (`v-if="!isReportPage"`); blue→clay/slate.
- `components/nav/ChatHistoryRail.vue` — rename button "New chat"→"New report" (filled clay, plus-circle);
  `dedupedRows` computed; warm bg `#FBFAF6`; neutral-warm active `#ECEAE1`; `report:titled` listener in onMounted.
- `components/report/ReportHeader.vue` — sidebar toggle icon-only (`heroicons:view-columns`).
- `components/excel/GoBackChevron.vue` — `hover:text-blue-500`→`hover:text-gray-900`.
- Mockup: `docs/design/redundancy_mockup.html` (standalone Claude-design preview of the 7 fixes).

**Auto-title from first question** (`backend/app/services/completion_service.py`). LANDMINE: there are **TWO**
completion paths — `_create_completion_traced` (non-stream) AND `create_completion_stream` (the live UI uses this
one). Hook MUST be in BOTH (~547 and ~1909, after the head `Completion(...)`): if prompt content non-empty and
`report.title` is a placeholder ("untitled report"/empty), set `report.title` = first non-empty prompt line,
whitespace-collapsed, truncated 60c + "…". Existing untitled rows backfilled via SQL. Backend `.py` is hot-iterable
(`docker cp` + `py_compile` + `docker restart` — no rebuild).

**Lazy report creation** ("no chat/interaction → don't store"). New `pages/reports/new.vue` = blank composer
(mountain empty-state + `<PromptBoxV2>` with **NO `report_id`**), uses `useAgent()` like `pages/index.vue`. TopNav +
Rail "New report" now `router.push('/reports/new')` — **no POST, no DB row** on click. Row is created only on first
submit: `PromptBoxV2.submit()` branches `if (props.report_id)` → add completion, else `createReport()` (line ~1531)
POSTs with `new_message` then redirects `/reports/{id}?new_message=…`; report page auto-sends `?new_message`.
Cleaned 85 pre-existing empty reports (145→60), backup table `reports_deleted_backup_20260620`. FK landmine: delete
child rows first (`dashboard_layout_versions`, `report_data_source_association`, …) — most FKs are NO ACTION.

**Two FE crash/UX landmines fixed:**
- **TDZ blank page** (`Cannot access 'X' before initialization`): an `immediate:true` watcher / `watchEffect` runs
  DURING setup; if it reads a `const`/`ref` declared on a LATER line → ReferenceError (function decls hoist, the
  consts they read do NOT). Fix: declare `const groundingScope = ref({…})` ABOVE the `watch(() =>
  report.value?.data_sources, …, {immediate:true})` that calls `loadGroundingScope()`. (Was the "click New chat →
  blank screen" crash; confirmed by decoding the minified bundle — `He` = groundingScope.)
- **SPA nav blank** (click a rail chat → blank, hard-refresh works): `report_id` captured once in setup, data loads
  only in `onMounted`, no route-param watcher → SPA reuses the component on `/reports/:id`→`:id2` nav. Fix:
  `definePageMeta({ key: (route) => route.params.id as string })` forces a page re-mount on param change.
- **`Cannot read properties of null (reading 'user')` on nav (page renders blank, refresh works)** — the `key`
  remount above EXPOSED a latent bug: the report page template uses bare `report.` in ~10 spots (`report.id`,
  `report.user.name.charAt(0)` avatars at ~172/236, `report.report_type`, `report.external_platform?.…`,
  `report.forked_from_*`), and the loading gate showed the spinner ONLY while `messages.length === 0`. On the
  remount, completions/messages populate BEFORE `report.value` is set → spinner skipped → content branch renders
  `report.*` on a null `report` → throw → Vue tears the page down → blank pane. The thrown property name is whatever
  bare access renders first ('user'). Fix: gate the spinner on `report` itself —
  `v-if="(!report || !completionsLoaded) && !reportNotFound"` (was `(!reportLoaded || !completionsLoaded) &&
  messages.length === 0 && …`) so the content branch never renders with a null report; plus `report?.user?.name?.charAt(0)`
  on the two avatars as insurance. RULE: any `report.X` in this template's content branch must be reachable only when
  `report` is truthy — guard the GATE, not each access. (AG Grid console warning `invalid gridOptions property
  'autoHeaderHeight'` is harmless/ignored, unrelated to the blank.)
- **STILL blank on nav after the null fix — page renders nothing, NO console error, refresh works** (bug #2, was
  masked under the crash): global `pageTransition: { name:'page', mode:'out-in' }` (nuxt.config) + our dynamic
  `definePageMeta({ key })` remount RACE. report→report nav changes the key → `<Transition mode="out-in">` plays
  *leave* on the old page then should *enter* the new one, but with a keyed remount the new page's enter never fires
  → old removed, new stays hidden → blank pane, zero error. Refresh works (full load has no enter-transition). Fix:
  opt this route out of the fade — `definePageMeta({ key:(route)=>route.params.id, pageTransition: false })` (rest of
  app keeps the cross-fade; keep the `key` so it still remounts + reloads). SIGNATURE TO REMEMBER: blank-on-client-nav
  + works-on-refresh + NO console error == a page/route transition stranding the new page invisible, NOT a data or JS
  bug. (If it blanks WITH a console error, that's a render-time null deref — bug #1 above.)

**Chat-surface bg + mountain (later 2026-06-20 build):** removed the empty-state mountain `<img
src="/assets/empty-states/empty-integrations.png">` from BOTH `pages/reports/[id]/index.vue` and `pages/reports/new.vue`
(the `empty-integrations.png` ref left in `pages/settings/integrations/index.vue` is the correct one — don't touch).
Swapped the chat canvas bg `#F5F4EE` (cream) → `#FBFAF6` (the ChatHistoryRail color) across the report page (L23 +
composer footer), `new.vue` (root + footer) and `PromptBoxV2.vue` root, so the rail and chat area are one continuous
tone split only by the thin border (user disliked the two-tone step + the mountain).

Build/verify: `until rtk proxy docker pull docker/dockerfile:1.7; do sleep 3; done` then `rtk proxy docker compose
-f docker-compose.build.yaml build app` + `up -d --force-recreate app`; verify HTTP 200 + grep baked dist for a
unique string. `docker exec` needs `-i` for heredoc/piped psql (else silent no-op exit 0). `docker cp` source must be
ABSOLUTE under `rtk proxy`. Backups via `bash scripts/backup.sh <label> <files…>` → `.backups/<ts>_<label>/`.

## 2026-06-20 — FULL BRAND RENAME bow/bagofwords → dash/Dash (LIVE, BAKED, boot-verified)
Platform-wide rename, 7 disjoint sub-agents + fixup pass (~290 files). Pre-rename snapshot:
`../CityAgent-Analytics_PRE-RENAME_20260620_123847.tar.gz` (23M). Boots green, migrations to head
`docknow1`, `import main` = 501 routes, register/login OK on a FRESH DB.
- **Renamed:** brand text (FE pages, locales ×10, emails, MCP titles) · **74 `BOW_*` env vars → `DASH_*`**
  (code + `.env` + all 3 composes + k8s, lockstep) · config module `bow_config.py`→**`dash_config.py`**, class
  `BowConfig`→**`DashConfig`**, attr `settings.bow_config`→`.dash_config` (74 consumers), router
  `bow_settings`→**`dash_settings`**, `BOW_CONFIG_PATH`→`DASH_CONFIG_PATH` · config files
  `bow-config*.yaml`→`dash-config*.yaml`, `bow-eval.py`→`dash-eval.py` · **DB `bagofwords`/`bow`/`bowpassword`
  → `dash`/`dash`/`dashpassword`** (consistent across .env+composes+k8s+healthcheck+connstring; renaming the
  DB/user means the OLD pg volume is incompatible → `down -v` + fresh `up` re-inits) · MCP `ui://bagofwords/`
  →`ui://dash/` + server name `"dash"` · echarts theme `'bow'`→`'dash'`, `data-bow-*`→`data-dash-*` (BE prompt
  + FE parser in lockstep) · localStorage `bow.locale`/`bow_*`→`dash.*`, JSON config key `bow_credit`→`dash_credit`
  · **k8s image `bagofwords/bagofwords`→`cityagent-analytics`** + CI push targets (the old Phase-10 cleanup, DONE).
- **KEPT — list B (wire/persistence contracts; renaming breaks existing data/integrations):** API-key prefixes
  `bow_`/`bow_oauth_` (minted+validated+tested consistently in api_key_service/dependencies/auth/mcp + tests) ·
  `X-BOW-*` webhook HMAC headers · DB column `bow_version` (needs a migration) · `.bowignore` file format
  (`git_file_walker._load_bowignore`) · Office.js control IDs in `routes/excel.py` (`BowTaskpaneButton` etc —
  re-sideload breaker) · "NEVER pull bagofwords/bagofwords" warnings · real `bagofwords.com/.io` URLs · NLP
  concept "bag of words" (none found in evals). `DataSourceIcon` connector logos kept (brand, like status colors).
- **Fresh-DB note:** the `down -v` wiped the dev DB → reseed needed (admin re-created `admin@cityagent.io` /
  `CityAgent#2026`; OpenRouter key was wiped — `seed_openrouter.py` now reads `DASH_BASE_URL/DASH_ADMIN_EMAIL/
  DASH_ADMIN_PASSWORD/OPENROUTER_API_KEY`). Full pytest unit suite still blocked by the pre-existing SQLite-conftest
  migration limit (CI runs on PG); rename-regression proven via in-container `import main` + pure-module checks.

## 2026-06-20 — UI/UX UNIFICATION: one canonical list-page across all 13 pages (LIVE, BAKED)
Front-end only, additive, mockups-first (gallery files under `docs/design/*_mockup.html`). All built to a single
**canonical list-page** anatomy (gold reference `frontend/pages/dashboards/index.vue`):
- **Anatomy:** outer `flex justify-center … bg-[#FBFAF6]` + `max-w-7xl`; serif H1 (`text-2xl` + `ui-serif`) + one-line
  `#6b6b6b` subtitle + **ONE clay `#C2683F` primary action top-right**; tabs (if My/Shared) directly under header
  ABOVE search, active `border-[#C2683F] text-[#1f2328]`; search `ps-10 rounded-xl` + magnifying icon; empty state =
  **clay tile `w-11 h-11 rounded-xl bg-[#F4F1EA] border` + heroicon + serif title + `#9a958c` hint**. NO blue, NO
  emoji icons, NO duplicate primary (global TopNav owns "New report").
- **Pages done:** studios/reports/dashboards/scheduled-tasks (Workspace) · instructions(+ConsoleInstructions+7
  instruction sub-components de-blued)/queries/files/knowledge/skills (Build) · monitoring(layout
  `layouts/monitoring.vue` serif+clay tabs; ConsoleOverview dup header removed)/evals/agents (Manage). Studios empty
  dropped the duplicate ghost tile; Scheduled blue→clay; Reports removed toolbar dup "New report".
- **Nav reorg (`components/nav/TopNav.vue`):** Build = Data Agents (moved from Manage) · Knowledge · Instructions ·
  Queries · **Skills** (was orphan, now reachable; label is a literal `'Skills'` — no `nav.skills` i18n key).
  Manage = Monitoring · Evals · MCP Server. Gating unchanged.
- **Knowledge page:** AI Suggestions clay button = header primary (NEW wiring → `POST /knowledge/ai-suggest/{ds}`
  `{focus:'both'}` → `loadAll()` → switch to Review tab); DS picker moved to the search row (was a 2nd Music Store
  control stacked under the global chip); semantic cards compacted (dropped the `h-28` grey band → icon+pill row +
  footer count).
- **Data Agents page:** Create Data Agent + Show all moved to header top-right (were on the search row); de-duped
  the "N tables" stat (one footer line "N tables · M source(s)"); Connected pill to the top row; "Add Connection"
  → secondary outline (one clay primary per view); ghost tile trimmed.
- **Onboarding nudges removed:** `layouts/default.vue` `showGlobalOnboardingBanner` forced `false`;
  `pages/index.vue` connect-LLM card `v-if="false"`. Studio left-rail item text `text-sm`→`text-[13px]` (matches top nav).
- New i18n keys added to **en.json only** (`queries.subtitle`, `files.empty/emptyDescription`, `evals.title/subtitle`,
  `monitoring.overview.subtitle`) → renders (en default) but the 12-locale catalog-sync CI lint may flag missing
  translations. LANDMINE stays: every FE `.vue` change needs an image REBUILD (baked `nuxt generate`); batch tweaks
  then one `compose build app` + `up -d --force-recreate app`.

## 2026-06-20 — Skills exec + auto-select, StudioFlyout, Connectors/Studio merge (Plan A) — LIVE, BAKED
Big session. All FE baked into `cityagent-analytics:dev`, :3007 healthy through scale overlay
(`-f docker-compose.build.yaml -f docker-compose.scale.yaml`: + Redis ca-redis:6399 + pgbouncer ca-pgbouncer:6432).
DB reseeded after the earlier rename `down -v`: admin `admin@cityagent.io`/`CityAgent#2026`, OpenRouter via
`backend/scripts/seed_openrouter.py` (env DASH_ADMIN_EMAIL/DASH_ADMIN_PASSWORD/OPENROUTER_API_KEY → Analysis
claude-sonnet-4 default + Router gpt-4o-mini), chinook demo re-added (`POST /data_sources/demos/chinook` = "Music Store").

**SKILLS now runnable + auto-selected (detail in `[[project_cityagent_skill_exec]]` memory).** `run_skill_file` tool runs
a skill's bundled `generate_df(ds_clients, excel_files)` script through the existing StreamingCodeExecutor (per-user
creds + AST gate + Redis concurrency cap + SkillRun audit). 12 executable skills (8 native + 4 converted from GitHub:
ab-test/segmentation/business-metrics/programmatic-eda) + 31 imported GitHub instruction-skills (nimrodfisher) = 39 total.
AUTO-SELECT verified live (Claude-style): plain question → planner catalog injects all visible skills with hard directive
("MUST call load_skill FIRST") → agent load_skill→run_skill_file→answer, no slash. **BUG FIXED: `loader.list_visible_skills`
default `limit=20` capped catalog → raised to 200** (else top-K ranks among only 20 of 39). Converting a guidance-skill to
executable needs BOTH a generate_df script AND a PREPENDED "EXECUTE FIRST" directive in skill_md (trailing hint loses to
the body's "gather requirements first" interview steps → agent asks Qs instead of running). AST blocklist = os/sys/subprocess/
etc; numpy/math/pandas allowed (kept dep-free, no sklearn/scipy). Skills list page `/skills`: grid 3→4/row, tab filter
(All/Personal/Org/Global) wired (was dead — no @click).

**StudioFlyout (`frontend/components/StudioFlyout.vue`).** The composer source picker (`components/prompt/DataSourceSelector.vue`,
NOT the nav `AgentSelector` — two selectors share the look) showed a rich hover card for Data Agents but BLANK for Studios.
Built StudioFlyout (mirrors AgentFlyout): hover a Studio row → summary + pinned-source chips + suggested-questions (from
`GET /studios/{id}/artifacts` kinds summary/suggested_questions + `GET /studios/{id}/sources`); click a Q → grounded report
(`POST /reports` {studio_id, data_sources:[agent_ids], new_message}). Wired into BOTH selectors. LANDMINE: an empty studio
(0 pinned sources) renders blank because the card reads pinned-source schema/artifacts — pin a source first.

**CONNECTORS + STUDIO MERGE (Plan A) — admin owns connections, users live in Studios.** New admin page
`frontend/pages/connectors.vue` (Manage menu, gated `permission:'create_data_source'`) surfaces connection management
(reuses ConnectionDetailModal/AddConnectionModal/DataSourceGrid, `GET /connections`); 4-col cards + "Pin in a Studio to use"
hint + non-admin "Admins only" lock. **Data Agents removed from Build nav** (TopNav `agents` item deleted; `/agents/{id}`
detail ROUTES kept — flyouts deep-link there). **Plan A flag `STUDIOS_ONLY = true`** in DataSourceSelector + AgentSelector:
raw connectors + "Auto" hidden from the chat picker → **picker = Studios only** + "New Studio" link. Rationale: in Dash a
connection IS a data_source IS a Data Agent (one `data_sources` table) → adding a connector auto-creates a selectable agent;
Plan A hides them so a connector is DORMANT until pinned in a Studio (report carries studio_id). Flip STUDIOS_ONLY=false to
revert. The Studio "Add source" picker ALREADY EXISTED in `pages/studios/[id]/index.vue` (`openAddSource`→"Pick Source"
modal lists `pinnableAgents`→`pinSource`→`POST /studios/{id}/sources {agent_id}`; unpin DELETE; editor+ role); only relabeled
its button "Add Connection"→"Add source" (it pins existing, never creates). Merge loop: admin adds Connector → user pins in
Studio → usable; never pinned = invisible to chat.

**PAGE-BG/SPACING UNIFICATION.** Canonical list-page wrapper applied to skills/queries/instructions/knowledge/agents +
monitoring-layout + evals: `flex justify-center px-4 md:px-6 text-sm bg-[#FBFAF6] min-h-full` + inner `w-full max-w-7xl py-2`
(was asymmetric `ps-2 md:ps-4` + `px-4 ps-0` = left-hug; instructions/monitoring also lacked the `bg-[#FBFAF6]`). Knowledge was
the odd full-width `px-10` → converted to the centered 2-div. Still-old (not in scope): reports/dashboards/studios/
scheduled-tasks/files/agents-new.

## 2026-06-20 (later) — Rename DASH, Settings nav, EE un-gate, LDAP/SSO config-from-UI — LIVE, BAKED

**RENAME.** "City Agent Analyst" → "City Agent DASH" everywhere (7 FE + 4 BE defaults: index.vue, settings/general.vue,
users/sign-in.vue, report_schema.py, organization_settings_schema.py, agent_v2.py, organization_service.py,
report_service.py) + dev-org DB `config.general.ai_analyst_name` updated via jsonb_set. Home hero reads org.ai_analyst_name
|| "City Agent DASH".

**AUTO IN PICKER (Studios-only).** Plan A hid the legacy "Auto". Re-added an explicit **Auto** row to BOTH pickers
(`prompt/DataSourceSelector.vue` composer + `AgentSelector.vue` nav) — Auto = no studio pinned → agent auto-selects
sources/skills. `selectAuto()` clears studio (DataSourceSelector) / `selectStudio('')` (AgentSelector). Trigger shows bolt +
"Auto" when no studio. `contextLabel` computed. `AgentSelector.showFlyoutAtEvent` rewritten to flip the hover flyout LEFT
when it'd overflow viewport (top-right picker was clipping the StudioFlyout off-screen) + maxHeight.

**reports/new SUGGESTED QUESTIONS.** `pages/reports/new.vue` had hardcoded `starters:[]` → swapped in
`<DataSourceQuestionsHome :data_sources="selectedDataSources">` (same as landing, conversation_starters chips).

**SETTINGS = OWN TOP-NAV MENU + standalone pages.** TopNav.vue: Settings is now a 4th top-level group (sibling of
Manage), flat dropdown of tabs (Access/LLM/AI/General/Channels/Audit/Identity Provider/SMTP — license removed), each →
`/settings/{name}`, per-tab permission-gated, icon per tab. `layouts/settings.vue` REWRITTEN: dropped the left rail + the
"Settings" card heading; now canonical full-page shell with per-tab title+subtitle (driven by active route). Killed
duplicate page-titles in general/ai_settings/smtp/license pages.

**LICENSE PAGE REMOVED.** Dropped from TopNav settingsTabs + settingsTabPermissions + layout allTabs; deleted
`pages/settings/license.vue`; removed the license-expiry banner from `layouts/default.vue` (showTopBanner now =
onboarding only). Backend license validation left intact (community works).

**EE FEATURE UN-GATE (audit/scim/ldap).** `backend/app/ee/license.py`: added `COMMUNITY_FEATURES = {"audit_logs","scim",
"ldap"}`. `has_feature()` returns True for these (before licensed check); `require_enterprise()` skips its `licensed` 402
gate for these. FE `ee/composables/useEnterprise.ts` `hasFeature()` mirrors the allowlist. → Audit Logs + Identity
Provider (SCIM + LDAP) fully work in community mode. Mirrors the existing `ENTERPRISE_DATASOURCES=[]` un-gate. Empty the
set to revert. ⚠️ Bypasses BSL on app/ee — user's self-hosted call. `custom_roles`/`domain_signup`/`usage_limits` stay gated.

**LDAP + SSO CONFIG-FROM-UI (DB overrides dash-config.yaml, LIVE no restart).** Mirrors the existing SMTP pattern
(`/api/organization/smtp` → DB `config[..]` JSON, secrets Fernet via `app.services.email.secrets.encrypt_secret/
decrypt_secret`, GET/PUT/test). New endpoints on `routes/organization_settings.py` (all `@requires_permission('manage_
settings')`):
- LDAP (org-scoped): `GET/PUT /api/organization/ldap`, `POST /api/organization/ldap/test`. Stored `config['ldap']`,
  bind_password→`bind_password_enc`. `ee/ldap/routes.py::_get_ldap_config()` now **async, DB-first** (resolver
  `get_org_ldap_config(db, org_id)`), file fallback. `@require_enterprise(feature="ldap")` kept.
- SSO (instance-level, reads FIRST org's `config['sso']` since sign-in is pre-login): `GET /api/organization/sso`,
  `PUT /api/organization/sso/google|/oidc|/auth-mode`, `POST .../sso/google/test`, `.../sso/oidc/{name}/test`. Module
  resolvers `get_effective_google_oauth()/get_effective_oidc_providers()/get_effective_auth_mode()` read DB-merged-over-
  file. `services/auth_providers.py` (build_authorize_url/_handle_callback/_get_oidc_config) read these resolvers per-
  request → live. `routes/dash_settings.py` public `/settings` merges DB SSO (google_oauth.enabled, oidc_providers,
  auth.mode) so sign-in buttons appear without restart. Microsoft = generic OIDC named "microsoft", issuer auto-built
  `https://login.microsoftonline.com/<tenant>/v2.0` (+EE MS-Graph group-sync already in app/ee/oidc/).
- SIGNUP TOGGLE: `signup_enabled` DB bool (independent of EE domain `signup_policy`). `GET/PUT /api/organization/signup-
  enabled` + `get_effective_signup_enabled()` resolver; `/api/settings` exposes top-level `signup_enabled` (DB override
  else file `features.allow_uninvited_signups`).

**LOGIN-PAGE FIXES.** `users/sign-in.vue`: Google button was gated by non-existent `config.public.googleSignIn` → now
driven by `/api/settings.google_oauth.enabled`. Sign-up link now gated `v-if="signupEnabled && authMode!=='sso_only'"`
(reads `/api/settings.signup_enabled`). Copy → "City Agent DASH". OIDC providers loop already correct (uses
`/api/settings.oidc_providers`).

**IDENTITY PROVIDER UI = rows + [Configure] modal.** `pages/settings/identity-provider.vue` refactored: compact provider
rows (Google / Microsoft / each OIDC / LDAP / SCIM), each with status pill + [Configure] → opens new
`components/settings/ProviderConfigModal.vue` (teleport, backdrop/✕/Esc) holding that provider's form. Auth-mode radios +
"Allow public sign-up" toggle stay on the page. Each SSO modal has a read-only **Redirect URI** copy field
(`window.location.origin + /api/auth/<provider>/callback`). Microsoft form parses tenant_id back from issuer on load.
SCIM token modals use z-[60] to stack above z-50 provider modal.

⚠️ `base_url` is `http://0.0.0.0:3000` — backend OAuth redirect uses base_url; the modal copy field uses browser origin.
Set base_url to the real host for live Google/MS login.

## 2026-06-21 — AGENT UPGRADES #1-#6 (Claude-pattern, lift-PATTERN-not-dep) — LIVE, BAKED, verified
Six agent upgrades built with disjoint-file sub-agents (parent verified + baked each into `cityagent-analytics:dev`,
:3007 healthy through the scale overlay). ALL flag-gated default-OFF + approval-safe + vectorless + OpenRouter-only +
never-raise-into-loop. Plan + per-item integration points: `docs/AGENT_UPGRADES_PLAN.md`. Backups under `.backups/`.
Synergy stacks: **MEMORY** #1+#4 · **MULTI-AGENT** #2+#5 (conductor+worker) · **EFFICIENCY** #3+#6.

- **#1 MEMORY TOOL** (`HYBRID_AGENT_MEMORY`) — MemGPT deliberate page-in/out. `models/agent_memory.py` (`agent_memories`,
  migration `agentmem1`, FTS GIN) + `ai/brain/agent_memory.py` (`write_memory` personal→approved / shared→pending;
  `recall` FTS ts_rank + token-Jaccard fallback) + `tools/implementations/memory_tool.py` (remember/recall, auto-reg) +
  `sections/agent_memory.py` + builder, wired context_hub (gather LAST + `render_agent_memory_section`) + agent_v2 append.
  LANDMINE: recall builds the ds-clause CONDITIONALLY (binding a bare NULL `:ds` → asyncpg AmbiguousParameterError); uid
  bound as `str(user_id or "")` sentinel.
- **#2 SUBAGENT FAN-OUT** (`HYBRID_SUBAGENTS`) — orchestrator-worker. `ai/runner/orchestrator.py` (`run_subtask`
  LLM→SELECT-only→client.execute_query→distill; `decompose`; `run_fanout` Semaphore(min(cap,4))+synthesize) +
  `tools/{implementations,schemas}/delegate_subtask.py` (planner-callable, self-gated, re-entrancy guard
  `subagent_depth>=1`). N× tokens → budget + concurrency capped; single-analyst path untouched when OFF.
- **#3 SKILL AUTO-GROW** (`HYBRID_SKILL_AUTOGROW`) — Voyager. `completion_feedback_service._run_propose_skill`
  (mirrors `_run_propose_from_positive`: fresh session, reload org/user/completion by PK, small model,
  `skill_authoring.distill_skill_from_completion`) fires on 👍 at both sites → DRAFT pending skill → owner activates.
- **#4 BI-TEMPORAL** (`HYBRID_BITEMPORAL`) — Zep/Graphiti. `ai/brain/bitemporal.py` (`current_condition`→`invalid_at IS
  NULL` when on else None; `asof_conditions`; `supersede_prior`). Migrations `bitemp1` (3 cols on metric_definitions/
  semantic_tables/agent_memories) + `bitemp2_partial_unique` (drop UNIQUE → partial unique `WHERE invalid_at IS NULL AND
  status='approved'`). Read-filters in resolve_metric/metrics+semantic builders/agent_memory.recall; supersede-on-approve
  in `routes/knowledge.py` BEFORE the approve-flip; time-travel `as_of` on resolve_metric. LANDMINES: cols are TIMESTAMP
  WITHOUT TZ → supersede uses NAIVE UTC (`datetime.now(timezone.utc).replace(tzinfo=None)`, else asyncpg rejects →
  silent no-op); partial-index scoped to `status='approved'` (bare `invalid_at IS NULL` blocked pending+approved
  coexisting → broke proposer); supersede MUST precede approve-flip (else two approved-current rows collide).
- **#5 WORKFLOW RUNNER** (`HYBRID_WORKFLOWS`) — MetaGPT verifier gate, conductor for #2. `ai/workflows/runner.py`
  (`run_pipeline(items, stage_fn, judge_fn, max_concurrency, max_retries)` → per-item stage→gate→pass/retry/skip/log,
  never raises; `llm_judge` PASS/FAIL; `produced_knowledge_judge` deterministic) + `ai/workflows/jobs.py`
  (`train_connector_tables` reuses connector.py resolution + autotrain_connector per table; `WORKFLOWS` registry) +
  `routes/workflows.py` (`POST /api/workflows/{name}/run`, flag-gated+auth). LANDMINE: `autotrain_connector` writeback
  COMMITS on the SHARED async session → concurrency>1 = "Session is already flushing"/lost writes → `train_connector_
  tables` PINNED `max_concurrency=1` (runner still supports parallelism for jobs whose stage owns its own session).
- **#6 CONTEXT COMPRESS** (`HYBRID_CONTEXT_COMPACT` + sub-flags `_LLM`, `_RATIO`) — GCC/OpenDerisk. New
  `ai/context/compaction.py` `compact(instructions, model)` SYNC no-LLM (runs ~2×/iter): **EDIT** (over budget=
  context_window*RATIO[0.75], floor 4k/fallback 24k → drop lowest-priority `###` blocks via `_DROP_ORDER`:
  code_bank→agent_memory→docs→join_graph→brain_graph→proven-queries; NEVER base/schemas/messages/semantic/metrics/
  skills/studio) + **AWARENESS** (append "### Context budget: ~X of ~Y tokens"). **COMPRESS** = `maybe_compress` async
  truncate MVP, LLM digest sub-flag OFF (TODO). agent_v2 touched MINIMALLY: +1 method `_apply_context_compaction` + 3
  one-line call sites before each `PlannerInput(instructions=…)` (init ~852 uses local `instructions_text`, post-tool
  ~2272, reflect ~3924). LANDMINE FIXED: site 852 reuses `instructions_text` across knowledge-harness loop steps → a
  non-idempotent compact STACKS awareness lines + inflates the token count → made IDEMPOTENT (`_strip_awareness` drops
  the prior `### Context budget` block before re-measuring; awareness always appended LAST). Verified live in-container:
  flag True + in snapshot, compact 10021→12 tok dropped only `proven approaches` core kept, method present.

## 2026-06-21 — #7 SKILL OPTIMIZER (microsoft/SkillOpt pattern, native) — LIVE, BAKED, verified
A SKILL.md is a TRAINABLE artifact: optimize it with NL edits gated by held-out evals. Frozen LLM, no
fine-tune, no GPU, OpenRouter-only, approval-gated — same idiom as #1-#6. Plan `docs/PLAN_SKILL_OPTIMIZER.md`.
Built Wave-0 (foundation) → Wave-1 (4 disjoint-file sub-agents) → parent joined the linchpin + baked.
Loop = ROLLOUT (run skill on a held-out golden suite via TestRunService→AgentV2) → REFLECT
(Judge.score_response_quality + failing-case critiques) → AGGREGATE (LLM ≤N textual edits on skill_md,
mirrors skill_authoring) → SELECT (accept only if eval PASS-RATE strictly improves — deterministic
`_compare_result_sets` gate, can't regress) → UPDATE (persist as a NEW `skills` row `status='draft'`).
- **Migration `skillbitemp1`** (down=`bitemp2`, NEW HEAD): +`valid_at`/`invalid_at`/`superseded_by` on
  `skills` + PG partial-unique `uq_skill_current` on `(organization_id, scope, name)` WHERE
  `invalid_at IS NULL AND status='active'`. So a draft version COEXISTS with the live active row;
  promoting a 2nd version to active WITHOUT superseding the old VIOLATES the index (proven in DB).
- **`app/ai/skills/optimizer.py`** `optimize_skill(db, *, organization, user, skill_id, eval_suite_id=None,
  case_ids=None, epochs=3, max_edits_per_epoch=3, model=None)` — never raises; `{skipped:True}` when flag
  off / skill-not-active / no suite. Rollout polls TestResult rows to terminal (cap 900s); pass-rate off
  `TestResult.status=='pass'`. NAIVE-UTC for the bitemporal cols.
- **`pinned_skill` rollout pin** (dict `{name, skill_md, allowed_tools, disallowed_tools}`): AgentV2.__init__
  `+pinned_skill` → seeds `runtime_ctx["active_skill"]` at BOTH runtime_ctx sites + force-injects the
  candidate `skill_md` via S5 `render_injected_skill` in the main planner-loop append. LINCHPIN (parent-
  fixed): the eval path is `TestRunService.create_and_execute_background → CompletionService.create_completion
  → AgentV2`; CompletionService was UNTOUCHED by the wave agents (the 2 AgentV2 sites they saw, 1164/1250, are
  in `stream_run`, OFF-path) → threaded `pinned_skill` through `completion_service.py` (create_completion +
  _create_completion_traced sigs + passthrough + the 2 real on-path AgentV2 ctors at ~676/742). Without this
  the chain TypeErrors at the file boundary.
- **`loader.list_visible_skills`** + `Skill.invalid_at.is_(None)` (unconditional, no-op for existing rows —
  hides future superseded versions).
- **Routes (`app/routes/skill.py`, singular)**: `POST /api/skills/{id}/optimize` (flag-gated, returns
  `{disabled:True}` 200 when off, never 500s) + NEW `POST /api/skills/{id}/activate` (no activate endpoint
  existed) — runs an INLINE supersede (`update(Skill)...invalid_at=now, superseded_by=new` gated on
  `flags.SKILL_OPTIMIZE`, NOT bitemporal's internal HYBRID_BITEMPORAL gate) BEFORE flipping draft→active, so
  `uq_skill_current` never collides. NAIVE UTC.
- **Flags** `HYBRID_SKILL_OPTIMIZE` (+`_DAEMON`), default OFF, in .env + compose. Reuses #5 runner · Judge ·
  P4 eval matcher · #4 bitemporal.py (generic) · skill_authoring · approval gate. Backup
  `.backups/20260621_110345_skill-optimizer`. VERIFIED live: head=skillbitemp1, 3 cols+idx in DB, flag in
  snapshot, optimizer/route/pinned_skill present, fail-soft no-ops, versioning guard enforced. ~515 routes.

## 2026-06-21 — #7 POST-MVP FIXES (finalize · improve-E2E · cache-bypass · daemon-user) — all BAKED+PROVEN
Four fixes after the MVP, all live-verified on Music Store + real OpenRouter, image rebuilt.
- **Finalize fix (Option B).** The rollout's path = `create_and_execute_background` (Path 1) RUNS the analyst but NEVER finalizes TestResults (only `stream_run`'s streaming path did) → pass-rate read 0. Extracted the inline evaluate-block from `stream_run` into `TestRunService._finalize_one_result(...)`; added public `TestRunService.finalize_run_results(db, org, user, run_id)` (no SSE/queue, idempotent, fail-soft). Optimizer `_rollout` now = create_and_execute_background → NEW `_await_completions_terminal` (polls the system COMPLETIONS, not TestResult) → `finalize_run_results` → `_pass_rate`. Same Path-1 gap wired into nightly `eval_harness.run_scheduled_evals` via `_await_and_finalize_run` BEFORE `detect_regressions`. **LANDMINE:** read fresh status after the finalize (which commits in a SEPARATE session) with `select(...).execution_options(populate_existing=True)` — NOT `db.expire_all()` (expire leaves attrs expired → later sync attr access does implicit async IO outside the greenlet → `greenlet_spawn has not been called` crash).
- **Improve→draft→activate E2E PROVEN.** Format-token failing baseline (skill omits a required output token the expectation demands) → baseline 0.0/['fail'] → AGGREGATE LLM adds the format rule → re-rollout 1.0/['pass'] → `improved=true`, NEW draft `skills` row persisted, live active row untouched (invalid_at NULL). Activate→supersede verified (old row invalid_at+superseded_by=new, exactly 1 active-current, `uq_skill_current` holds). **Expectation-rule gotcha:** must be FieldRule `{"type":"field","target":{"category":"completion","field":"text"},"matcher":{"type":"text.contains","value":...}}` — a flat `{"type":"text.contains",...}` is silently push_skipped → failed==0 → VACUOUS pass.
- **Cache no-op fix.** With serve-caches on (QUERY_CACHE+ANSWER_CACHE+BRAIN_READ — the live config), each pinned CANDIDATE was answer-cache-served (cache keys on question+datasource, NOT pinned_skill; hit precedes the agent) → candidate never re-ran → SELECT gate saw no change → optimizer a SILENT NO-OP on any cached org. Single chokepoint: `agent_v2._serve_from_reasoning_cache` is the only caller of `run_serving_funnel` (only caller of serve_answer_cache+try_serve_proven_query). FIX = 2 guards in `agent_v2.py`: (a) top of `_serve_from_reasoning_cache` `if getattr(self,'pinned_skill',None): return False` (bypass both answer-cache ① + reasoning-cache ②); (b) `and not getattr(self,'pinned_skill',None)` on the answer-cache write-back (~3869) so candidate N's answer doesn't poison candidate N+1. PROVEN deterministically: seed sentinel into answer_cache → pinned rollout's completion `served_by=None` + answer is fresh (not sentinel); sentinel still cached after (no write-back).
- **Daemon user bug.** `run_scheduled_skill_optimize` (the @04:00 daemon) passed `user=None` → `create_and_execute_background` guards `requested_by_user_id` (test_run_service.py:598) but then derefs `str(current_user.id)` UNGUARDED in `_create_stub_report` (line 615) → every rollout crashed `'NoneType' object has no attribute 'id'` → daemon a SILENT PERMANENT no-op. Fixed: daemon resolves an org-member user via `_resolve_org_member_user` (imported from eval_harness, same pattern `run_scheduled_evals` uses), skips orgs with no member. Proven: baseline_scores 0.0→1.0. (`run_scheduled_evals` was already clean.) Neither daemon has an in-body leader gate (leader gating is at the APScheduler caller).
- Tidy: deleted dead `_await_run_terminal` + `_TERMINAL` from optimizer.py (superseded by `_await_completions_terminal`). Plan doc `docs/PLAN_SKILL_OPTIMIZER.md` header marked COMPLETE. #7 = fully shipped, nothing dangling; both daemons run clean, still flag-OFF in prod by design.

## 2026-06-21 — HYBRID UI SURFACES (flag admin page · memory review · workflows · skill-origin)
Closed the backend-ahead-of-frontend gap: 4 hybrid features got real per-user/admin UI (built by 9 parallel disjoint-file sub-agents + parent integrate/bake). Migration `skillorigin1` (NEW HEAD, down=skillbitemp1): +`origin` VARCHAR(20) server_default 'manual' on `skills`. All flag-gated default-OFF; baked into cityagent-analytics:dev, verified live.

- **Feature Flags admin page (the linchpin — was env-only).** Per-org live override of all 8 HYBRID_* flags WITHOUT container restart. Backend: `app/settings/hybrid_flags.py` got module-level `_OVERRIDES: dict[str,bool]` — `_bool(name)` now returns `_OVERRIDES[name]` if present else env (unchanged when empty); helpers `set_override(env,val|None)`, `overrides_snapshot()`, `async load_overrides_from_db(db)->int` (scans org_settings.config['hybrid_overrides']), and `UPGRADE_FLAGS` metadata map (8 envs → {label, role: agent|user|review}). Routes in `app/routes/organization_settings.py` (already main-registered, no main.py touch): `GET /api/organization/hybrid-flags` (list {key,env_name,label,role,default_env,override,effective}) + `PUT /api/organization/hybrid-flags/{env_name}` body {enabled:bool|null} (writes config['hybrid_overrides'] + `flag_modified(settings,'config')` since config is plain JSON not JSONB + commit + `set_override` live). Both `@requires_permission('manage_settings')`. Parent wired `load_overrides_from_db` into main.py startup_event (fail-soft) so overrides survive restart. **LANDMINE — 4 uvicorn workers:** `_OVERRIDES` is per-process; a live PUT updates only the worker that served it; others reload from DB on next restart (DB is durable). OK for dev/single-org; multi-worker live-sync = future shared store. FE `pages/settings/features.vue` (settings layout, toggle table, role chips, optimistic PUT+revert). Nav: Settings→Feature Flags tab (TopNav.vue:380 + layouts/settings.vue allTabs).
- **#1 Agent Memory review.** NEW `app/routes/agent_memory.py` (registered main.py:81 import + :262 include, prefix /api): `GET /api/agent/memories?status=&scope=` (org-scoped, invalid_at IS NULL, personal rows private to author, []-when-flag-off), `POST .../{id}/approve` (status→approved), `POST .../{id}/reject` (retires bi-temporally via invalid_at=NAIVE-UTC — no 'rejected' status exists; drops from recall+pending). Gated flags.AGENT_MEMORY (writes 403 off via AppError FEATURE_LOCKED). FE `pages/memory/index.vue` (Pending/Approved/Personal tabs, approve/reject). Nav: Build→Memory (/memory). **E2E SMOKE PROVEN live:** flagOFF→[]; override ON→flag flips; seed pending→list sees it→approve→approved (drops pending, enters approved); reject→retired.
- **#5 Workflows.** `app/routes/workflows.py` +`GET /api/workflows` (list from jobs.WORKFLOWS via WORKFLOW_METADATA dict, []-when-off) + `GET /api/workflows/{name}/status` (from new in-process `_LAST_RUNS` dict — runs are ephemeral, no persistence table) + run_workflow now records _LAST_RUNS (done/error) WITHOUT changing its signature/return. FE `pages/workflows/index.vue` (cards + DS picker via GET /api/data_sources + Run + inline summary). Nav: Manage→Workflows (/workflows, manage_settings).
- **#3 Skill origin badge.** `skill_authoring.distill_skill_from_completion(origin='manual')` (shared row-builder); auto-grow `_run_propose_skill` passes origin='auto', manual route passes 'manual'. Surfaced in BOTH read paths: routes/skill.py `_serialize` + ai/skills/loader.py `list_visible_skills` (both `getattr(...,'manual')`-safe). FE `pages/skills.vue` violet "Auto-proposed" badge when origin=='auto' (UIcon sparkles, no emoji).

VERIFY (live): image baked + ca-app healthy (0 boot errors); routes 401/400 (registered+gated, not 404); pages /memory /workflows /settings/features all 200; single head skillorigin1; memory loop + flag-override resolver + origin serialize + workflow meta all proven by in-container coroutine smoke. Deferred (need backend foundation first, NOT built): #2 subagent monitor (runs ephemeral, no table), #6 context-budget readout (metrics internal-only). Mockups: ui-mockup.html (concept) + ui-mockup-match.html (app-styled). 9 agents = BE-FLAGS/BE-MEM/BE-WF/BE-ORIGIN + FE-NAV/FE-FLAGS/FE-MEM/FE-WF/FE-BADGE; WAVE0 owned migration; parent owned main.py boot-load + bake.

## 2026-06-21 — BRAND COLOR STANDARDIZATION (clay primary, killed off-brand blue)
Symptom: "Add Member" button + active "Members" tab rendered BLUE while brand accent is CLAY #C2683F ("New report" button). ROOT CAUSE: no `frontend/app.config.ts` existed → Nuxt UI (v2.22.3) fell back to its DEFAULT blue primary, so every bare `UButton`/`UTabs`/`UBadge`/`UToggle` (no explicit color) was blue; clay was only ever hardcoded inline (`bg-[#C2683F]`). Nuxt UI v2 resolves `ui.primary` from the TAILWIND theme (`#tailwind-config/theme/colors`), not app.config alone — if the named color isn't in Tailwind it warns + falls back to green.
FIX (2 new config files + project-wide literal sweep, baked):
- NEW `frontend/app.config.ts`: `defineAppConfig({ ui: { primary: 'clay', gray: 'stone' } })`.
- NEW `frontend/tailwind.config.ts`: registers `theme.extend.colors.clay` 50–950 (500=`#C2683F` main, 600=`#A8542F` hover/dark; 50 `#FBF6F2`,100 `#F4E5DA`,200 `#E8C9B5`,300 `#DBAC8F`,400 `#CF8A65`,700 `#8B4427`,800 `#6E3620`,900 `#5A2D1B`,950 `#331810`). The @nuxtjs/tailwindcss module auto-merges it; no nuxt.config change. → all DEFAULT U components + active-tab underlines now clay.
- Swept EXPLICIT blue literals → clay across MembersComponent.vue + all pages/settings/** + ~150 components/** + 27 pages+layouts. Rules: `color="blue"`→`color="primary"`; `bg-blue-500/600`(+hover)→`bg-[#C2683F]`+`hover:bg-[#A8542F]`; `text-blue-*`→`text-[#C2683F]`(+hover `#A8542F`); active `border-blue-500`+`text-blue-600`→`#C2683F`; `focus:ring/border-blue-500`→`#C2683F`; tints `bg-blue-50`→`#F6EFEA`,`bg-blue-100`→`#F4E5DA`,`border-blue-200/300`→`#E8C9B5`,`text-blue-700/800`→`#A8542F`; brand hexes `#2563eb/#3b82f6/#60a5fa`→`#C2683F`.
- DELIBERATELY LEFT (NOT brand): chart data-series palettes (RenderVisual/EChartsVisual/ArtifactFrame/themes/index.ts/PerformanceChart 2nd-series), `colorScheme` enum string values ('blue' = palette lookup key not CSS), user color-picker swatches. Green/red/amber/emerald/teal/slate/purple semantic states untouched.
VERIFY (live, built dist CSS at /app/frontend/dist/_nuxt): clay primary compiled = 690× `C2683F` + clay rgb `194 104 63` in `--color-primary-*` vars; only 11× residual `2563eb` (all in entry.css = the kept chart palettes); /settings/members 200, ca-app healthy. Baked cityagent-analytics:dev. CONVENTION GOING FORWARD: new UI = use bare U components or `color="primary"` (now clay) / inline `bg-[#C2683F]` hover `bg-[#A8542F]`; never `color="blue"` or `bg-blue-*` for brand/interactive elements.

## 2026-06-21 — AGENT STEP VISIBILITY + AUTO-PILOT PANEL (Claude-style live run view) — LIVE, BAKED
Front-end only (+ 1 live DB instruction). Goal: show what the agent is doing every step, like Claude. Backups `.backups/*_agent-step-visibility` + `*_autopilot-panel`. Mockups at repo root: `ui-mockup-steps.html`, `ui-mockup-activity.html`, `ui-mockup-autopilot.html`.

**KEY DISCOVERY (the linchpin):** the live chat does NOT use `CompletionMessageComponent.vue` (that's legacy/unused on the report page — only a CSS comment references it). The report page (`pages/reports/[id]/index.vue`) renders agent activity DIRECTLY by iterating `m.completion_blocks` (the `v-for` at ~L267) — each block with `tool_execution` renders a tool card (`CreateDataTool.vue` = "Creating Data · Visualizing", `CreateWidgetTool`, `ClarifyTool` via `getToolComponent`). So agent steps = `completion_blocks`, NOT the documented `tool.started`/`tool.finished` SSE events (a first attempt built a parallel `steps[]` array fed by `reduceStepEvent` on those events — it stayed EMPTY because the real activity flows through `block.upsert`-built blocks). **Truth source for "what the agent did" = `completion_blocks`.**
- **`frontend/utils/stepMap.ts`** (NEW, auto-imported util): `AgentStep` shape + `prettyTool(name)` (17 tools → icon+title) + `reduceStepEvent()` (event-based, kept but UNUSED on live path) + **`blocksToSteps(blocks)`** (THE one used — maps `completion_blocks` → step rows; tool blocks → {kind tool/subagent, status from `tool_execution.status` success→done/error→warn/else→run, durationMs, body.code from sql/code, body.output from result_summary}; reasoning/answer blocks → think steps). Fully defensive, never throws.
- **`frontend/components/AgentStepTimeline.vue`** (NEW): labeled "Thought process · N steps · Done" pill (spinner while in_progress, green check done) + vertical collapsible step rows. Mounted in `CompletionMessageComponent.vue` (dead path — harmless). The LIVE inline surface = a "Thought process / Working · N steps" header added ABOVE the block `v-for` in the page (the block tool-cards ARE the per-step detail; header just frames them Claude-style). The bare `simple-dots` "···" startup state (page `shouldShowWorkingDots`, was at L367) → replaced with a labeled clay-spinner "Thinking…" pill.
- **Activity tab (4th right-panel tab, beside Summary/Dashboard/Agents).** Right panel switches on `rightPanelView` ('summary'|'artifact'/'grid'|'agent'|**'activity'**). Tab button + `#right` branch added; `activeSteps` computed = `blocksToSteps(lastSystemMessage.completion_blocks)`. Shows Progress checklist + bar, Data sources (`report.data_sources`), Skills used (badge load_skill/run_skill_file), Sub-agents (kind subagent), Outputs (create_viz/create_data/create_artifact). Token-budget line = "context budget pending — / —" (placeholder until #6 surfaces the number).

**AUTO-PILOT PANEL (`reports/[id]/index.vue`).** Default `rightPanelView='activity'` (was 'artifact'). Panel follows the run automatically:
- refs `autoPilotPanel` (default ON, localStorage `dash_autopanel`), `userPinnedView`, `userClosedPanel`.
- `setPanelView(view, manual=false)` = single entry point; `manual=true` PINS (stops auto-switch this run) + adjusts width via `panelLeftWidthFor` (Activity = narrow right / 60% chat; Dashboard = wide / 40%; Summary 55%; Agents 48%).
- Watchers: (a) run-start (`status`→in_progress) → open panel + Activity, reset per-run pins; (b) **`activityOutputs.length` grows** (per-run signal, resets each run — used INSTEAD of `hasArtifacts` which only flips false→true once so follow-up queries wouldn't re-trigger) → flip to Dashboard unless pinned; (c) run-ends text-only → Summary if it has content, else stay Activity.
- All tab buttons + `@viewDashboard`/`@openInstructions`/`@toggleArtifactView` routed through `setPanelView(...,true)`; close-x sets `userClosedPanel=true`. Header **Auto** toggle (bolt/bolt-slash). Mobile untouched.

**CACHE-SERVE RENDER FIX (the "answer blank + Activity 0/0" bug).** A repeated question is served by the answer/reasoning cache (`completions.served_by='answer_cache'`) → the agent loop is SKIPPED → **0 completion_blocks**, the answer lives on `completion.content`. The page renders ONLY blocks → blank chat + empty Activity. FIX: (1) template fallback renders `m.completion.content` when NO block carries content (`!blocks.some(b=>b.content||final_answer||assistant||tool_execution)`); (2) `activeSteps` synthesizes a single "Answered instantly (cached)" step (reads new `served_by` field, added to the completion→message map) so Activity isn't 0/0. To SEE full live steps, ask a NOVEL question (cache miss) — repeats serve instantly with no steps by design.

**DATA-DATE LANDMINE + 0-ROW FIXES.** Symptom: "Plot sales for 2009" → Execution succeeded · **0 rows** → empty chart. ROOT CAUSE: this demo's `chinook.sqlite` is **RE-DATED to 2021–2025** (83 invoices/yr), NOT chinook's classic 2009–2013 — the agent hardcoded `WHERE year=2009` from training prior → matched nothing. Two fixes: (1) **published org Instruction** (live, no rebuild — `instructions` table, org 55278108, category 'general', status 'published'; NOT-NULL cols need `thumbs_up=0`+`is_seen=false`): "before filtering/grouping by date, FIRST inspect MIN/MAX of the date column; never assume years from dataset name". (2) **RenderVisual.vue 0-row empty-state** improved (it ALREADY gated `!props.data?.rows?.length` — chart was never faking data; the blank frame WAS the empty-state) → now clearer "Query returned 0 rows · check the date/year range" with icon. VERIFY: head/health 200, baked; `blocksToSteps`/`dash_autopanel`/`Thought process`/`Thinking…` all in dist.

**AUTO-PILOT TRIGGER FIX (don't open empty Dashboard on inline charts).** Bug: an inline chart (`create_data`/`create_viz`) auto-flipped the panel to Dashboard, which was EMPTY ("No artifacts yet") — an inline chart lives in the CHAT, it does NOT populate the Dashboard tab. The Dashboard tab only fills from a REAL artifact (`create_artifact` / "Generate Dashboard"). FIX: the auto-flip watcher now triggers on **`hasArtifacts`** (real artifact, set live at agent_v2 L2590 on `create_artifact`), NOT on `activityOutputs`. Net behavior: inline-chart run → stays **Activity** (chart in chat); real dashboard artifact → flips **Dashboard**; text-only → **Summary**. Manual click still pins.

## 2026-06-21 — MULTI-TENANT cache scoping + AMBIGUITY GATE (R3) + cache-blank fix — LIVE, BAKED
3 fixes (A/B/C) built by disjoint-file sub-agents, parent wired the shared `agent_v2.py` + flag plumbing. Driven by a multi-tenant SaaS reality: **100 users, Studios pin same-or-different data sources, per-user results.** KEY INSIGHT: the scope unit is the **data-source SET a Studio pins** (+ studio context), NOT user/org. Caches are already org-scoped + studio-namespaced (`answer_cache._scoped_hash(norm, studio_id)`), but the agent_v2 funnel caller passed only the FIRST source id + NO studio_id → the namespacing wasn't actually exercised, and multi-source Studios could mis-share.

- **A — full-source-set cache key (no migration).** `answer_cache`/`query_cache_store`/`code_cache_store`/`serving_funnel`/`query_cache_serve` take a new optional `data_source_ids: list[str]`. Helper `_sources_fp(ids)=",".join(sorted(map(str,ids)))` folded into the hash **ONLY when len(ids)>1** → single-source/None is byte-identical (existing rows still hit, zero cache invalidation); multi-source sets get distinct, order-independent keys. DB WHERE on the single `data_source_id` col untouched (uniqueness comes from the hash). **Parent wired** `agent_v2.py` `run_serving_funnel(...)` (~L1797) to pass `data_source_ids=[str(d.id) for d in self.data_sources]` + `studio_id=str(self.report.studio_id) if report.studio_id else None` (was first-source-only, studio_id never passed). → Studios on same source set share (cost win across the 100 users), different sets isolate, studio context namespaced.
- **B — AMBIGUITY GATE / "ask before assuming" (R3, AmbiSQL pattern).** Kills the 2009-bug class. NEW `app/ai/clarify/{__init__,ambiguity_gate}.py`: `async detect_ambiguity(db, *, organization, question, schema_summary=None, data_source_hint=None, model=None) -> {ambiguous, kind, clarifying_question, suggested_options}`. ONE cheap LLM call (reuses `app.ai.llm.llm.LLM(model, usage_session_maker=async_session_maker).inference(prompt, usage_scope="ambiguity_gate")` — SYNC blocking call from async, the repo's brain-module idiom; small model via `LLMService().get_default_model(db, org, None, is_small=True)`). Detects kinds: `missing_date_range` (incl. a specified year that may not exist), `undefined_relative_time`, `ambiguous_metric`, `ambiguous_entity`. Self-gates `getattr(flags,"AMBIGUITY_GATE",False)`, never raises, OpenRouter-only, vectorless. **Parent wired** into `agent_v2.py` ONCE pre-loop (after the code_bank instructions block ~L2196, where all hybrid `_X_block`s append — region runs ONCE before the agent loop; loop init `observation/active_artifact` starts right after): if ambiguous → injects a `### Clarify before answering` directive telling the planner to **call the existing `clarify` tool** (reuses ClarifyTool.vue → NO new FE) instead of guessing. New flag `AMBIGUITY_GATE` (`@property` in `hybrid_flags.py`, env `HYBRID_AMBIGUITY_GATE`) added to hybrid_flags + `.env`(=1 dev) + `docker-compose.build.yaml`(`:-0`) — LANDMINE: all THREE or silent-OFF. VERIFIED in-container: `flags.AMBIGUITY_GATE=True`, `detect_ambiguity` is async coro.
- **C — scroll-up cache-blank bug.** `loadPreviousCompletions` (FE pagination map, ~L3133) was MISSING `completion` + `served_by` (the main `loadCompletions` map has them) → older cache-served answers (`served_by='answer_cache'`, 0 blocks, answer on `completion.content`) rendered BLANK on scroll-up. Added both fields. FE-only.

VERIFY: `import main` clean (≈515 routes), all py_compile OK, baked + ca-app healthy :3007 200, funnel signature has `data_source_ids`. TEST B: ask "plot sales revenue by month for 2009" → agent should `clarify` ("which year? 2021/2022/2023/all") instead of 0-row chart. Research basis: arXiv AmbiSQL (ambiguity gate 42.5%→92.5%) + competitive landscape (Wren/Snowflake VQR/Genie/ThoughtSpot value-resolution) + OpenWork (plan+permission/clarify as UI objects). Full roadmap R1–R12 in the session; R1 value-resolution via `pg_trgm` (no embeddings) + R4 verified-query repo are the next biggest levers, both scope per-data-source = multi-tenant amplified.

## 2026-06-21 — RENAME "Studios" → "Agent Studios" (UI label only)
Feature display name changed Studio/Studios → **Agent Studio / Agent Studios**. UI label ONLY — routes `/studios`, i18n KEYS (`studio.*`, `nav.studios`), vars/components (`selectedStudio`, `StudioFlyout`, `studio_id` col) UNCHANGED.
- `locales/en.json` (repo-root `locales/`, NOT frontend/locales): `nav.studios` + `studio.{title,yourStudios,newStudio,createStudio,createTitle,empty,disabled,disabledHint,notFound,backToStudios,deleteStudio,studioCreated,studioDeleted,settingsTitle}`.
- Hardcoded Vue labels: `components/AgentSelector.vue` (Studios header + New Studio), `components/prompt/DataSourceSelector.vue` (Studios header + New Studio ×2), `components/nav/ChatHistoryRail.vue` (`title="Studio"`).
- LEFT inline prose (`this studio's pinned sources` etc.) lowercase — reword = noise, reads fine.
- FE baked SPA → i18n COMPILED INTO JS bundle (`/app/frontend/dist/_nuxt/*.js`), NO standalone en.json in container. Needs full image rebuild + hard-refresh. Baked + ca-app 200.

## 2026-06-21 — UPLOAD LOCAL EXCEL/CSV → Data Agent + TRAIN surfaces (Knowledge docs) — LIVE, BAKED
User gap: Studio "Add source" only PINS existing Data Agents (both already pinned → "No Data Agents available to pin"), and the connector picker had NO file-upload tile → **no UI path to bring local data in**. Fixed with a new `spreadsheet` connector + upload UI + a studio Knowledge-docs surface. Built by 3 disjoint-file sub-agents (BE / FE-connectors / FE-studio) against a pinned API contract; parent fixed a body-binding bug + baked. Mockup at repo root `mockup-upload-train.html`.
- **BACKEND — `spreadsheet` connector (DuckDB in-memory, un-gated).** NEW `app/data_sources/clients/spreadsheet_client.py` (`SpreadsheetClient(DataSourceClient)`: pandas `read_csv`/`read_excel` per sheet → `con.register` as DuckDB tables; sanitizes sheet→table names; honors optional `sheet_names`; full base iface test_connection/get_schemas/get_tables/get_schema/prompt_schema/execute_query; traversal-safe path under `<cwd>/uploads/files/`). Registered in `app/schemas/data_source_registry.py` (`spreadsheet` → client_path, `requires_license=None`, data_shape=tables, shared, ui_form=data_source, auth none) + `app/schemas/data_sources/configs.py` (`SpreadsheetConfig{file_id,sheet_names,path}` + `SpreadsheetNoAuthCredentials`). NEW route `app/routes/data_source_from_file.py` `POST /api/data_sources/from-file` (`@requires_permission('create_data_source')`), included in `backend/main.py` BEFORE `data_source.router`.
- **CONTRACT.** `POST /api/data_sources/from-file` body `{file_id (from POST /api/files), data_source_name?, sheet_names?, description?}` → creates `Connection(type='spreadsheet')` + `DataSource`, links via the REAL junction **`domain_connection`** (`models/domain_connection.py`; recon's "DomainConnection" guess was WRONG — it's the lowercase Table, `DataSource.connections`↔`Connection.data_sources` M:N), runs the canonical discovery `ConnectionService.refresh_schema → DataSourceService.sync_domain_tables_from_connection` (same path as the demo loader; `_create_memberships(...,['manage'])` so creator can read), returns the full `DataSourceSchema` dict **+ additive top-level `tables[]`** (base schema has no tables field; route has no response_model so it's additive). Errors: 404 file-not-in-org, 400 unreadable/unsupported, 409 dup name. Schema discovery is **fail-soft** (bad file → ds still created, `tables:[]`).
- **LANDMINE (cost me a smoke cycle): `from __future__ import annotations` + the `@requires_permission` wrapper made FastAPI mis-read the pydantic body param as a QUERY param** → `422 {"loc":["query","payload"],"missing"}`. The decorator wraps the endpoint and FastAPI couldn't resolve the stringized annotation `payload: DataSourceFromFileRequest` to a BaseModel → treated it as a primitive (query). FIX: removed `from __future__ import annotations` from the route file (it only used `Optional[...]`, no PEP-604 `|`, so safe). RULE for new routes with body models behind `@requires_permission`: do NOT use future-annotations, or FastAPI won't see the body.
- **`/api/files` now exposes `preview`.** Added `preview: Optional[Any]=None` to `FileSchema` (`app/schemas/file_schema.py`) — `from_attributes` auto-populates from the `File.preview` JSON the upload already generates (excel `{type,sheet_names,sheet_previews{sheet:{raw_cells,shape}}}` / csv `{type,raw_cells,shape}`). Purely additive; the upload modal's sheet/column preview reads it. (Was stripped before → preview was blank.)
- **FRONTEND.** NEW reusable `frontend/components/data/UploadSpreadsheetModal.vue` (props `{open:Boolean, studioId:String|null}`, emits `close`/`created(dataSource)`; drag-drop .xlsx/.xls/.csv ≤50MB → `POST /files` (FormData, field `file`) → render sheets+column preview from `preview` → name/desc → `POST /data_sources/from-file` → emit created; uses `useMyFetch` BARE paths + `useToast`, clay theme). `frontend/pages/connectors.vue` — added a first "Upload File / Spreadsheet" tile opening the modal. `frontend/pages/studios/[id]/index.vue` — (a) Sources header split: **Pin existing | Upload file**; Upload opens the modal with `:studio-id`, and on `@created` AUTO-PINS via the existing `pinSource(ds)` (`POST /studios/{id}/sources {agent_id:ds.id}`) + `fetchSources()` (solves the "nothing to pin" dead-end); (b) NEW left-rail **Knowledge docs** tab (KNOWLEDGE group) = paste form (title+body+DS picker of pinned sources or org-wide null) → `POST /knowledge/docs {title,body,source:'paste',data_source_id}` + list `GET /knowledge/docs[?data_source_id=]` with status pills + Approve (`POST /knowledge/doc/{id}/approve`) / Reject (`/reject`, hidden if 404). `{disabled:true}` → "Enable Knowledge Docs in Settings → Feature Flags" hint.
- **Flags (already ON in dev):** `HYBRID_DOC_KNOWLEDGE=1`, `HYBRID_STUDIOS=1`, `HYBRID_AUTOTRAIN=1`. The `spreadsheet` connector itself is UN-gated.
- **VERIFIED LIVE (E2E, real OpenRouter org):** login → `POST /files` (preview type=csv present) → `POST /data_sources/from-file` → DataSource created with discovered `tables[0].columns = [region,product,units,revenue]`. Post-bake re-smoke OK. Routes mounted (`/api/data_sources/from-file`, `/api/knowledge/docs`), connector resolves (`resolve_client_class('spreadsheet')→SpreadsheetClient`), all FE strings baked in `_nuxt/*.js`. COSMETIC: CSV table name = stored filename stem (uuid-prefixed, e.g. `<uuid>_smoke`) — valid SQL, agent sees columns fine; could later name from data_source_name. Backups not taken (small, additive).

## 2026-06-21 — REPORT-PAGE FIXES: Summary→Outputs · softer errors · OpenRouter retry · locals() self-heal · dashboard skeleton — LIVE, BAKED
5 fixes from a user bug report (3 screenshots: empty Summary, red error walls, stuck "Generating dashboard…"). Built by 4 disjoint-file sub-agents, one rebuild bakes BE+FE. Mockups `mockup-fixes.html` (before/after). 523 routes, healthy.
- **2A OpenRouter stream retry (`app/ai/llm/clients/openai_client.py`).** ROOT: a single OpenRouter network blip surfaced as red `LLM v2 streaming failed: Connection error` (zero retry). FIX: new `_open_stream_with_retry()` wraps `chat.completions.create` — retries ONLY transient (`httpx.ConnectError/ReadError/RemoteProtocolError/TimeoutException` + `openai.APIConnectionError/APITimeoutError`, name/msg fallback), NOT `BadRequestError`/auth. 3 attempts, exp backoff 0.5→1s, WARNING log. LANDMINE handled: **idempotent** — `yielded_any` flag, retry ONLY if no chunk yielded yet (mid-stream fail re-raises, no duplicate text). `llm.py:439` RuntimeError wrapper unchanged (fires only after retries exhausted).
- **2B locals() self-heal + prompt steer (`code_execution.py` + `agents/coder/coder.py`).** ROOT: model emitted `locals()`; AST blocklist blocks it (`FORBIDDEN_BUILTINS` UNCHANGED — still blocks locals/globals/vars/eval/exec/open) and `except CodeSecurityError` did `break` (dead red end). FIX: (1) coder `generate_code` prompt rule **9. Sandbox safety** forbids locals/globals/vars/getattr/eval/exec/open + says use try/except NameError (live path = create_data v2 `code_generator_fn=coder.generate_code`, NOT the dead alt-prompts at coder.py ~188/454). (2) `generate_and_execute_stream_v2` (the real loop — recon's create_data.py:1374 was wrong, it's in code_execution.py) gets `security_retry_budget=1`: first violation appends corrective feedback + `continue` (regenerate) instead of break; 2nd → final break. `security_violation` event yielded every block → audit `log_tool_audit('security.unsafe_code_blocked')` preserved. Successful regen ends clean.
- **1 Summary→Outputs + Answer card (`components/report/ChatSummary.vue` + `pages/reports/[id]/index.vue` + `locales/en.json`).** ROOT: `ChatSummary.hasAnything` = queries||artifacts||queryExecutions||instructions → text-only answers = "No items yet"; webhook button was the centerpiece. FIX: report page computes `latestAnswer` (walks `lastSystemMessage.completion_blocks` from end, skips error/clarify → `block.content||plan_decision.final_answer||assistant`, falls back to cache-served `completion.content`) + passes to BOTH ChatSummary mounts (desktop ~L695 + mobile ~L66); ChatSummary renders a clay "Answer" card (MarkdownRender from markstream-vue) at top, `hasAnything = hasAnswer || …`. Tab label en.json `reportView.tabSummary` "Summary"→"Outputs" (KEY/route 'summary' unchanged). Webhook demoted to faint dashed footer link.
- **2C soften recovered errors (`utils/stepMap.ts` + report page Activity render + `components/tools/CreateDataTool.vue`).** `blocksToSteps`: Pass-0 computes `progressAfter[i]`+`runReachedAnswer`; an errored tool block becomes **warn (amber 'retried'/'self-fixed')** if the run progressed after it / ultimately answered / matches `RECOVERABLE_PATTERNS` (LLM streaming/connection/timeout → "retried"; security/unsafe_python/forbidden/locals → "self-fixed"); stays red ERR only on final no-recovery failure. Activity step UI + CreateDataTool inline error show amber pill + raw error collapsed behind "show detail" (default hidden). CreateDataTool was already amber; message-level red (`m.status==='error'`) left red (true final fail).
- **3 dashboard skeleton + anti-stuck (`components/dashboard/ArtifactFrame.vue` + NEW `DashboardSkeleton.vue`).** ROOT: pending = bare `<Spinner>"Generating dashboard…"` (ArtifactFrame:147) + NO poll/timeout → status stuck 'pending' (agent fails mid-build) = infinite spin. FIX: NEW `DashboardSkeleton.vue` (prop mode page|slides, widgetCount; shimmer KPI row + 2-col widget grid mirroring real layout; warm/clay shimmer keyframe, no blue/emoji) swapped into the pending branch. Anti-stuck: while `isPendingArtifact`, poll `fetchSelectedArtifact()` every **5s** (double-interval guarded, cleared in onUnmounted); after **90s** or fetch-error → `buildError=true` → ERROR panel ("Dashboard build stopped" + clay **Retry build** → clears state, re-fetch, best-effort POST `/api/reports/{id}/rerun`, resume poll). Success iframe/SlideViewer path + props/emits unchanged.
- VERIFIED LIVE: `import main` 523 routes no crash; openai_client retry present; security_retry_budget + coder steer present; FE baked (Outputs label, DashboardSkeleton "building", "self-fixed"/"Dashboard build stopped" in `_nuxt/*.js`). Hard-refresh to clear cached JS chunk. Mockup `mockup-fixes.html`.

## 2026-06-21 — REPORT-PAGE FIXES R2: skill silent-fake-data · tab crowding · panel-jump · step narration — LIVE, BAKED
4 issues from a user bug report (4 screenshots). 2 disjoint sub-agents (1 skill/BE, 1 FE-all-3 since same file), one rebuild bakes BE+FE. Mockup `mockup-issues2.html` (tab A/B/C options, before/after each). Container healthy :3007.
- **SKILL SILENT-FAKE-DATA (the dangerous one — 3× bigger than the screenshot showed).** ROOT: `skills_library/programmatic-eda/scripts/eda.py` hardcoded `SELECT * FROM orders LIMIT 5000` in a bare `try/except → df=None → synthetic 300-row np.random fallback`. Source w/o an `orders` table (e.g. RTM) → query throws → skill reports **success but analyzed FABRICATED data**. AUDIT: **ALL 12 GitHub-sourced skills had the same pattern** (hardcoded tables: orders/customers/experiment_events/events/sales + np.random fallbacks): programmatic-eda, data-profile, ab-test-analysis, anomaly-detection, business-metrics-calculator, cohort-retention, funnel-analysis, kpi-snapshot, pareto-8020, rfm-segmentation, segmentation-analysis, time-series-trend. FIX (all 12): introspect via **`client.get_schemas()`** (abstract base `app/data_sources/clients/base.py`, returns `Table` w/ `.name`, all connectors implement) → quote discovered table `SELECT * FROM "<table>" LIMIT 5000` → iterate clients until rows → **FAIL LOUD** `raise RuntimeError(...)` if no client/table/rows. Synthetic fallback DELETED everywhere. **LOAD PATH: skills load from BOTH disk + DB — `importer.py` seeds disk→DB once, but `run_skill_file` reads EXCLUSIVELY from `skill_files.content` at runtime.** So BOTH updated: host files fixed + `docker cp`'d into `ca-app:/app/skills_library/` + `py_compile` clean ×12, AND 15 `skill_files` rows updated via psycopg2 to `ca-postgres` (verified no `FROM orders`/`np.random` remnants). 3 residual DB `FROM orders` matches are HARMLESS — demo/example SQL strings in `sql_lint.py`/`sql_anti_patterns.md`/`sql_explainer.py`, not data-loaders.
- **TAB CROWDING (Option A) — right-panel tab bar `pages/reports/[id]/index.vue` `#right-header` (~L626-700).** ROOT: tabs icon+full-text `px-3 py-1.5` + Auto toggle + ✕, no overflow → wrap/crowd on narrow panel. FIX: compact tabs `px-2 py-1`, `whitespace-nowrap` + `flex-none` icons; **"Dashboard"→"Dash"** (L651, `title="Dashboard"` kept); tab group wrapped `overflow-x-auto no-scrollbar min-w-0` (scrolls not wraps); **Auto toggle → icon-only bolt** (`w-7 h-7`, bolt vs bolt-slash, `aria-label="Auto-pilot"`, clay-filled active/muted off); **✕ pinned far right** `flex-none ms-1` separated from bolt (`ms-auto`). Added `.no-scrollbar` to scoped `<style>`. All handlers/active-styling/focus-ring preserved.
- **PANEL-JUMP ("right screen moves too much") — PROGRESS card (~L722).** ROOT: PROGRESS card grew as steps streamed (no reserved height) → shoved Data sources/Skills/Sub-agents/Outputs sections down each step. FIX: `min-h-[180px] flex flex-col` reserves ~4 steps; progress bar pinned bottom `mt-auto` → streaming steps fill reserved space, siblings stop reflowing. NOTE: no Activity-panel auto-scroll existed (only left-chat reasoning box + chat container scroll, untouched) → "remove auto-scroll" was a no-op.
- **STEP NARRATION ("its working, I don't know what's working — explain what's going/coming") — `utils/stepMap.ts` + Activity render.** ROOT: model's plain-language reasoning ALREADY emitted at `block.plan_decision.reasoning` (shown left-chat thinking-box) but Activity panel only showed terse hardcoded TOOL_MAP labels. FIX: `stepMap.ts` `blocksToSteps` adds optional `why?` field via new `whyFromBlock()` (collapse whitespace, ~140-char cap, `''` when absent; recovered steps use friendly recovery note — honest about retries; RECOVERABLE_PATTERNS/amber-pill untouched). `index.vue` Activity: per-step muted `why` line under each label (`v-if="step.why"`) + **Now/Next banner** atop panel (`activityNow`=narration/label of in-progress-or-latest step; `activityNext`=pending step after current, OMITTED when none — stream exposes no forward plan, degrades honest rather than fabricating). Amber retried/self-fixed pills still render.
- VERIFIED LIVE: build exit 0, force-recreate, `health: healthy`; DB skill rows clean (`get_schemas`, no fake-data); SFC/template compile 0 errors. Hard-refresh to clear cached JS. Mockup `mockup-issues2.html`.

## 2026-06-21 — R3 FIXES: empty-state card grid · skill hasattr sandbox-block · Activity panel height+width — LIVE, BAKED
- **EMPTY-STATE REDESIGN (`components/DataSourceQuestionsHome.vue`, used by `pages/index.vue` + `pages/reports/new.vue`, same `@update-content` emit → both inherit).** Floating rotating pills → **6-card 2×3 grid** (`grid grid-cols-1 sm:grid-cols-2 gap-3`, collapses 1-col narrow, `max-w-2xl`). Each card = category tag + heroicon + 2-line prompt (`line-clamp-2`). Auto-categorize from prompt verb via `categorize()`: `Compare`(vs/correlation) `i-heroicons-arrows-right-left` · `Dashboard`(build/overview) `squares-2x2` · `Trend`(over time/avg) `arrow-trending-up` · `Rank`(top/most/which) `chart-bar` · `Explore`(fallback) `magnifying-glass`. Clay `#C2683F` tag + border-hover. Pool still from `data_sources[].conversation_starters` (split on `\n`, label=first line, value=full). Kept rotate-one (6s) + `↻ shuffle` link (shown when pool>6). Heading untouched (`reports.emptyTitle`). Convention: `<UIcon name="i-heroicons-...">`.
- **SKILL SANDBOX-BLOCK (`hasattr`) — run_skill_file errored "Forbidden function call: 'hasattr()'".** ROOT: all 12 skill scripts had `tname = table.name if hasattr(table, 'name') else str(table)` (the get_schemas introspect line from R2). Sandbox AST gate `FORBIDDEN_BUILTINS` (`app/ai/code_execution/code_execution.py:205`) bans `hasattr`/`getattr`/`setattr`/`eval`/`exec`/`open`/`locals`/`globals`/`vars`/... → script rejected pre-exec → agent fell back to raw SQL (the amber "self-fixed" / "skill blocked, I'll use SQL"). FIX: `hasattr(table,'name')` → **`'name' in dir(table)`** (`dir` NOT forbidden), sandbox-safe, same behavior. Applied 12 disk files (perl) + **15 `skill_files` DB rows** (psql replace) + `docker cp` into container + `py_compile` clean ×12. Runtime reads DB → live, no rebuild for this part. **LANDMINE: skill scripts run in the AST-gated sandbox — NO introspection builtins (hasattr/getattr), NO eval/exec/open/locals; use `'x' in dir(obj)` or try/except AttributeError instead.**
- **ACTIVITY PANEL HEIGHT (`pages/reports/[id]/index.vue` PROGRESS card ~L753).** ROOT: R2 added `min-h-[180px]` but NO max → card grew with steps (1→5 + per-step `why` narration) → shoved Data sources/Skills/Sub-agents down (the "expands more" jump). FIX: card `max-h-[340px]`; step-list wrapper (`v-if="activityTotal>0"`) → `flex-1 min-h-0 overflow-y-auto no-scrollbar -mx-1 px-1` (scrolls internally). Progress bar + footer pinned (`mt-auto`). Card holds stable size regardless of step count.
- **ACTIVITY=OUTPUTS WIDTH.** ROOT: right-panel width = window minus `leftPanelWidth` (left/chat px, `SplitScreenLayout.vue`). 4 conflicting setters; `activity` had NO explicit branch → always hit catch-all `else 0.37` → right panel **63% (wide)**, while `summary`(=Outputs) → left 0.55 → right **45%**. FIX: give `activity` the SAME 0.55 as `summary` in all 3 relevant setters — `panelLeftWidthFor` (L1685 `0.60→0.55`), `watch(rightPanelView)` (L2184 `'summary'||'activity'`), `toggleSplitScreen` ternary (L3473 add `||'activity'`). Auto-open L4038 = artifact-only, left. Now Outputs↔Activity = identical 45% right, no resize on switch; Dash/artifact stay wide (63%) for charts.
- TESTED LIVE: skills #3 CONFIRMED working (SKILLS USED panel shows Loaded skill / Ran skill = used). Sub-agents #2 trigger = multi-part "research each independently" prompt in Analysis/deep mode. AMBIGUITY GATE fires twice on demo data (2021-2025 vs today June 2026) for "last 12 months" — by design, not a bug. **OPEN/NEXT: new skill bug surfaced — `run_skill_file → Validation failed: tables_by_source: Input should be a valid list` (cohort skill passes non-list to tables_by_source); NOT yet fixed.** `#6 context-budget readout` still hardcoded placeholder `context budget pending — / — tokens` (no backend). VERIFIED: build exit 0, force-recreate, `health: healthy`. Hard-refresh for cached JS.

## 2026-06-21 — RECURSIVE VERIFY (RecursiveMAS-inspired, text-space critic+retry on subagent path) — BAKED, flag-OFF
- **WHAT.** Studied RecursiveMAS (arxiv 2604.25917 / recursivemas.github.io). Paper's real mechanism = latent-space hidden-state transfer via trainable RecursiveLink modules + gradient training on local HF weights/vLLM/GPU → **IMPOSSIBLE on our OpenRouter-only, API-only stack** (no weights, no internals, no training). Did NOT implement that. Stole the transferable text-space lesson: recursion = draft→critique→re-do (bounded), + compressed handoffs cut tokens.
- **DESIGN (self-contained on the subagent path; NO agent_v2.py surgery, NO migration):** each `delegate_subtask` worker finding is graded by a cheap CRITIC; HARD-error findings re-delegate with the reviewer note appended (bounded loop). Rides on `delegate_subtask` so it is a no-op unless `HYBRID_SUBAGENTS` is also on.
- **FLAG:** `HYBRID_RECURSIVE` (default OFF) — `hybrid_flags.py` property `RECURSIVE` + `UPGRADE_FLAGS["HYBRID_RECURSIVE"]={"label":"Recursive Verify","role":"agent"}` (→ shows in admin Feature-Flags page) + added to `snapshot()` (also added missing `SUBAGENTS`). Env knob `HYBRID_RECURSIVE_MAX_RETRIES` (default 2, hard-clamped 0..3).
- **BACKEND (`app/ai/runner/orchestrator.py`):** `critique_finding(model,question,result)` → `{passed,reason,hint}`, HARD-errors-only prompt (no data/wrong entity/time/metric/ungrounded numbers; PASS when in doubt), **FAIL-OPEN** (empty/unparsed critic reply → passed=True; deterministic fast-fail only on empty answer). `run_subtask_verified(...)` wraps existing `run_subtask` in the loop: `while attempts<=max_retries` (so 1+max_retries runs, ≤3), pass+ok → return verified; fail → carry hint into next attempt's question; **no ds_clients → max_retries forced 0** (nothing to re-query = zero token burn). Returns run_subtask dict + `verified`/`attempts`/`critic_reason`.
- **TOOL (`delegate_subtask.py` + schema):** `DelegateSubtaskOutput` += `verified:Optional[bool]`, `attempts:Optional[int]` (None when flag off → byte-identical). When `flags.RECURSIVE`: call `run_subtask_verified`, message = "verified" / "verified (self-fixed after N retries)" / "unverified after N attempt(s): <reason>"; observation summary prefixed `[verified] `/`[unverified] `.
- **FRONTEND (`frontend/utils/stepMap.ts`, subagent branch only):** reads `te.result_json.verified/attempts` (fallback parse `[verified]`/`[unverified]` prefix). verified-after-retry (attempts>1) → reuse `recovered`+`recoveredLabel:'verified'` amber pill; unverified → `status:'warn'`+`recoveredLabel:'unverified'` (amber caution, never red); clean first-try / flag-off → no pill (identical to today). Null-safe.
- **VERIFIED LIVE:** py_compile ×4 clean; container imports OK; `flags.RECURSIVE`=False default, in UPGRADE_FLAGS + snapshot; output fields None when off. Functional smoke (mock LLM): empty→deterministic fail; persistent-fail loops **exactly 3** (1+2) then unverified+reason; pass→attempts 1; no-clients→attempts 1 (retries skipped). Build exit 0, force-recreate, `ca-app healthy`.
- **LANDMINES:** (1) bounded ALWAYS — `max_retries` clamped 0..3, no-clients→0; never remove caps (infinite loop / token burn). (2) critic = HARD-errors-only + fail-open; if tuned strict it wastes retries rejecting good findings. (3) rides on SUBAGENTS — useless alone; both flags must be ON. (4) per-finding critic = +1 cheap LLM call each; simple Qs (no fan-out) never hit it.
- **TO ENABLE:** `HYBRID_SUBAGENTS=1` + `HYBRID_RECURSIVE=1` (env or admin Feature-Flags per-org override). NOT YET turned on / not E2E-proven on a real multi-part question — Phase 4 live-run pending user.

## 2026-06-21 — SLIDES + EXCEL TABS (report right-panel) + Workspace nav pages — BAKED, LIVE
- **WHAT.** Two NEW right-panel tabs on the report page — **Slides** (deck builder) + **Excel** (workbook) — as peers of Dash (NOT inside the dashboard). Plus two new Workspace-nav library pages (Presentations / Spreadsheets). User wanted slides/sheets OUT of the dashboard. Mockup `mockup-slides-excel.html` (interactive: tab + 3 theme switch).
- **COMPONENTS (NEW, presentational, props-only, no API/Pinia):** `frontend/components/report/SlidesPanel.vue` props `{visualizations?:any[], reportTitle?:string}` — thumbnail rail + aspect-video canvas, slide 1 auto-title then 1 slide/viz, **3 themes** (theme-clay/dark/edit CSS gradients), `Export .pptx` (lazy `import('pptxgenjs')`, try/catch). `frontend/components/report/ExcelPanel.vue` props `{sheets?:{name,columns,rows}[], workbookTitle?:string}` — sheet-tab strip + read-only grid (cap 200 rows), normalizes array-of-objects→array-of-arrays, `Export .xlsx` (lazy `import('xlsx')`). Both empty-safe → empty-state when no data.
- **DEPS:** `yarn add xlsx@^0.18.5 pptxgenjs@^4.0.1` (frontend/package.json) — client-side export, browser-safe, no backend. Imported LAZILY inside export handlers (missing dep can't break render).
- **WIRING (`frontend/pages/reports/[id]/index.vue`):** `rightPanelView` union += `'slides'|'excel'` (2 spots: ref decl L1663 + `setPanelView` sig). Explicit imports added (after ChatSummary import). 2 tab buttons after Activity (heroicons `presentation-chart-line` / `table-cells`, labels `reportView.tabSlides`/`tabExcel`). 2 panel branches after Activity div, before Agent View (`v-else-if rightPanelView==='slides'|'excel'`). Width: slides/excel fall through `panelLeftWidthFor` else→0.40 left = wide right (matches Dash); NO width-setter change needed. NEW computed `excelSheets` (after `visualizations` ref ~L1216): walks `messages[].completion_blocks[].tool_execution.result_json` for tabular data (`data_model.columns`+rows, either row shape), fully try/catch fail-soft → []. SlidesPanel fed `visualizations` (same source as Dash), ExcelPanel fed `excelSheets`.
- **WORKSPACE NAV (`frontend/components/nav/TopNav.vue` ~L400):** added 2 items to workspace group after `dashboards`: `{key:'presentations',href:'/presentations',icon:'heroicons-presentation-chart-line',label:'nav.presentations'}` + `{...spreadsheets, heroicons-table-cells, nav.spreadsheets}`. NEW pages `frontend/pages/presentations/index.vue` + `pages/spreadsheets/index.vue` (copied canonical list-page shell from `pages/dashboards/index.vue` — same wrapper/max-w-7xl/grid/`definePageMeta({auth:true})`); v1 = static EMPTY STATE (no backend) pointing user to report→Slides/Excel tab→Export, "Browse reports"→/reports.
- **i18n (`locales/en.json` — repo-root, NOT frontend/locales):** `nav.presentations`="Presentations", `nav.spreadsheets`="Spreadsheets", `reportView.tabSlides`="Slides", `reportView.tabExcel`="Excel". (i18n compiled into _nuxt bundle → rebuild required, done.)
- **NAMING:** tab labels short (**Slides**/**Excel**); workspace library pages formal (**Presentations**/**Spreadsheets**). Avoid PowerPoint/Excel trademark words in nav; `.pptx`/`.xlsx` only on export buttons.
- **VERIFIED:** frontend build exit 0 (nuxt generate clean — TS union + new SFCs + computed all valid), force-recreate, `ca-app healthy`. Hard-refresh for cached JS.
- **v1 SCOPE / NEXT:** Slides = view + reorder placeholder + pptx export (canvas shows framed viz placeholder, NOT live ECharts render — wire real chart-to-image later). Excel = view + xlsx export, read-only (no cell edit, no formulas — v2). Presentations/Spreadsheets pages = empty-state only (no saved-deck/workbook backend yet — future: persist exports + list them). `+ New sheet` / `+ Add slide` = placeholders.

## 2026-06-21 — TAB ROW = ICON-ONLY COLORFUL PRODUCT ICONS (cosmetic) — BAKED LIVE
- Report right-panel tab row (`reports/[id]/index.vue` #right-header ~L631): replaced heroicon+text tabs with **icon-only** colored inline-SVG buttons (no labels; native `title` tooltip carries the name). Buttons now `w-9 h-8` square, active = bg-gray-100 (Activity = #F6EFEA). Mockups `mockup-tab-icons.html` (A/B options) + `mockup-real-icons.html` (chosen).
- Icons (real product look, gradient SVGs; gradient `<defs>` declared ONCE in #right-header, referenced `url(#id)`): Outputs=blue data-table (tblB) · Dash=**Power BI** gold bars (pbiY) · Agents=**Copilot** swirl violet→cyan (agV; dropped the old per-agent DataSourceIcon/name) · Activity=pulse amber→red (acR) · Slides=**PowerPoint** orange swoosh+magenta P (ppO/ppP) · Excel=**Excel** gray doc+green X (xlG). LANDMINE: gradient IDs (ppO/ppP/xlG/pbiY/tblB/agV/acR) are GLOBAL in the DOM — keep unique; the hidden `<svg width=0>` defs block must stay rendered or fills go black. `DataSourceIcon` import now unused on this tab (still imported; harmless). TRADEMARK: PowerPoint/Excel/Power BI = MS marks — fine internal, flag if shipped public. Build0+healthy; hard-refresh for cached JS.

## 2026-06-21 — TAB TOOLTIP + ARTIFACT-BY-MODE ROUTING — BAKED LIVE
- **TAB TOOLTIP (cosmetic).** Icon-only tabs: native `title` → styled dark pill BELOW icon (`reports/[id]/index.vue` #right-header). Each button = `tabico relative` + child `<span class="ttip">label</span>`; scoped CSS `.tabico .ttip` (#1F2937 pill, white 10px, arrow-up via ::before, 120ms fade, z-50, no reflow) + `.tabico:hover .ttip`. **LANDMINE: removed the tab-group `overflow-x-auto whitespace-nowrap no-scrollbar`** (it clipped the dropping tooltip; 6 small icons fit without scroll). Header wrapper (SplitScreenLayout.vue L20 `flex-shrink-0 flex items-center justify-between`) does NOT clip → tooltip shows.
- **ARTIFACT-BY-MODE ROUTING (the real fix: decks→Slides, dashboards→Dash).** ROOT of "presentation generates under Dashboard": deck = backend **Artifact** with `mode='slides'` (vs dashboard `mode='page'`); `ArtifactFrame` rendered ANY mode + auto-pilot always flipped to `'artifact'` (Dash) — nothing routed on mode. KEY: discriminator **already exists** = `Artifact.mode` (`backend/app/models/artifact.py:36`, VARCHAR; `'page'`|`'slides'`; API `GET /api/artifacts/report/{id}` + `/{id}` return it; `create_artifact` tool sets it). **NO migration.** Excel is NOT a backend artifact (`WriteToExcelTool` = Office-taskpane postMessage only, no Artifact record) → Excel tab stays client-only.
- **FIX (frontend-only, 2 files, 1 sub-agent, backup `frontend/_backup_artifact_routing_20260621-211200/`):** (1) `components/dashboard/ArtifactFrame.vue` += OPTIONAL prop `modeFilter?:'page'|'slides'` (default undefined = NO filter = byte-identical for every other caller); `applyModeFilter()` filters the fetched list before dropdown/auto-select-first/hasArtifact/render; `handleArtifactCreated` only adopts an incoming artifact if it survives this frame's filter (Dash ignores slides, Slides ignores page). (2) `reports/[id]/index.vue`: per-mode computeds off already-loaded `reportArtifacts` (`hasSlidesArtifact`= any mode==='slides', `hasPageArtifact`= any mode!=='slides'; NO new fetch); Dash branch ArtifactFrame `mode-filter="page"`; Slides branch = `<ArtifactFrame mode-filter="slides">` when `hasSlidesArtifact` ELSE `<SlidesPanel>` fallback (SlidesPanel unmodified, conditional render — it renders client viz-decks, CANNOT render the React artifact code, so real decks MUST use ArtifactFrame); auto-pilot `watch(hasArtifacts)` now async → `await checkHasArtifacts()` then route `setPanelView('slides')` when `hasSlidesArtifact && !hasPageArtifact` else `'artifact'` (re-checks userPinnedView post-await; still gated by autoPilotPanel/userClosedPanel).
- **BACKWARD-SAFE:** modeFilter default=none → other ArtifactFrame mounts untouched; page-only reports = Dash as before; no-artifact = unchanged; both modes present → deck in Slides + dashboard in Dash, **auto-pilot defaults to Dash** (the `!hasPageArtifact` guard). Build0+healthy.
- **OPEN/NEXT:** (a) both-modes auto-focus = Dash (deck one click away in Slides) — flip to deck-wins if wanted. (b) TRUE Excel artifact = future epic (needs `mode='excel'` + backend spreadsheet generator; today Excel tab = client-side xlsx export only, no persisted artifact). (c) SlidesPanel client viz-deck now = fallback-only when no slides artifact.

## 2026-06-22 — STABILITY PASS: skills+subagents OFF, pgbouncer fix, stop button, dashboards build (LIVE, BAKED)
Multi-round debugging of "agent loops / dashboard never builds / UI hangs". Root causes found by DEEP verification (4 research agents were WRONG twice — Python-3.8-union-bug FALSE (runtime is 3.12), skill-steps-not-default FALSE (DB showed is_default=t). VERIFY claims live before acting.). Net decision: **DISABLE skills + sub-agents** — they were the instability source; the core `create_data → create_artifact` path is reliable and builds dashboards cleanly.
- **DECISION / STABLE CONFIG: `HYBRID_SKILLS=0` + `HYBRID_SUBAGENTS=0` in `.env`** (verified `flags.SKILLS=False`/`SUBAGENTS=False` at runtime). Reversible (set =1 + recreate). Skills/sub-agents need a redesign before re-enabling (executable skills should feed create_data; advisory skills must NOT be in the action catalog). The big multi-angle dashboard now builds via pure core: create_data ×3 (distinct titles) → create_artifact → KPIs+Pareto+genre+country. PROVEN live.
- **(R1) 120s "Thinking" hang = `ConnectionDoesNotExistError +120135ms`.** Cause: `ca-pgbouncer` `pool_mode=session` + `DEFAULT_POOL_SIZE=25`, but SQLAlchemy keeps `pool_size 20 + max_overflow 20 = 40` persistent client conns → in session mode each pins a server conn → >25 block on pgbouncer `query_wait_timeout` (default 120s) → conn dies → run crashes. FIX (`docker-compose.scale.yaml` pgbouncer env): `DEFAULT_POOL_SIZE 25→60`, `MIN_POOL_SIZE 5→10`, `QUERY_WAIT_TIMEOUT 30` (fail-fast, not 120). postgres max_connections=100 (60 fits). Recreate pgbouncer only. Transaction-mode flip AVOIDED (asyncpg prepared-stmt risk) — note as future for multi-user.
- **(P2) Flag→catalog gate.** `registry.py get_catalog_for_plan_type` now drops `load_skill/run_skill_file/read_skill_file` when `not flags.SKILLS` and `delegate_subtask` when `not flags.SUBAGENTS`, read at CALL time (live flip honored). Stops phantom "Sub-agent"/skill no-op steps (delegate_subtask self-no-ops "subagents disabled; no work done" but still showed as a step). Central — all callers inherit.
- **(P1) Stop button mid-run.** `reports/[id]/index.vue` new computed `runActive = isStreaming || lastSystemMessage.status==='in_progress'`; composer `PromptBoxV2.vue` Stop-vs-Send gates on it (was `isCompletionInProgress` which flipped false on `completion.finished` while the harness tail still ran → reverted to Send). `abortStream()` already POSTs `/api/completions/{id}/sigkill` + AbortController + status='stopped'. 
- **(P3) Spinner clears on terminal.** `completion.finished` SSE now defaults status→`'success'` when payload omits it → "Thinking" dots clear (don't wait for `[DONE]`). Kept the 150s watchdog `failRunUnexpectedly` + silent-close handling.
- **(E1) Scalar → KPI card.** `create_data.py` viz-infer: single 1×1 numeric result forced to `metric_card` (was blank chart). **(E2) soft-reason not red.** `GenericTool.vue` + `stepMap.ts`: agent skip/already-exists/recovered narration on an error-status tool renders gray info, not red ✗; genuine errors stay red.
- **DORMANT (skills off, kept in code for re-enable):** `run_skill_file` `sql=`→`input_df` threading (code_execution `_invoke_generate_df` delivers input_df when fn has **kwargs), run_skill_file emits Step+Viz (agent_v2 allowlist), descriptive `title` arg, skill-name code view (`created_step.code` via `arguments_json` added to `ToolExecutionMinifiedSchema`), agent_v2 stall guard (`skill_calls_since_build` steer@5/abort@10, independent of produced_output) + false-done fix (`produced_output` gate). Advisory skills `executive-summary-generator`+`dashboard-specification` set `status='archived'` (revert: status='active').
- **MODELS curated** to 3: Claude Sonnet 4.6 (default), Claude Haiku 4.5 (small-default), GPT-5.4 Mini; glm-5.2 + gemini-3.5-flash removed.
- **LANDMINE:** DB password is `dashpassword` (not `dash`). pgbouncer `pool_mode=session` — keep SQLAlchemy total conns (pool_size+overflow) under DEFAULT_POOL_SIZE or runs die at query_wait_timeout.

## 2026-06-22 — KNOWLEDGE-TRAIN + ROBOT ASSISTANT (5 features, baked LIVE)
Use case: load Abbott Myanmar nutrition CRM (6 monthly CSVs, 35 Salesforce-style cols) + a Definitions.xlsx (56 col-defs + KPI formulas) + an explanation deck, train the agent to be expert. **Per-studio knowledge** = each studio pins its own sources + own column-descriptions/instructions/examples.
- **DATA loaded (test studio):** merged 6 CSVs → `Abbott_MM_CRM_Jan-Jun2025.csv` (21,240 rows, 36 cols incl added `report_month`, gender normalized) → spreadsheet datasource **"Abbott MM CRM"** `84ee1ed9-7fa1-43fc-9c61-1c51e7e12fe6` (table `22a404f2-...`, DuckDB name `e59e494a_..._abbott_mm_crm_jan_jun2025`), pinned to studio **test** `2335870e-4137-444c-81bf-797885352ef6`, org `55278108-...`. 36 column descriptions written + 3 active KPI/classification/compliance instructions + 2 examples. **E2E PROVEN**: agent generated exact KPI SQL (Completed+Unsuccessful+User+Lapsed) → dropout by brand = Ensure 1995 / total 2632 (matches pandas ground truth 7/7).
- **TRAINING = 2 layers** (both fed to agent context, verified): (1) per-column `DataSourceTable.columns[].description` (schema_context_builder/prompt_formatters render inline); (2) StudioInstruction `status='active'` (studio_context_builder → agent_v2 ~L2137 appends `<studio_context>` when `flags.STUDIOS` ON + report.studio_id set). StudioExample active rows = few-shot. Metrics surface AS StudioExample rows.
- **API runbook (host→:3007):** login `POST /api/auth/jwt/login` form `username=admin@cityagent.io&password=CityAgent#2026` → bearer; ALL calls need `X-Organization-Id`. Upload `POST /api/files` (multipart field `file`) → file_id. Create source `POST /api/data_sources/from-file {file_id,data_source_name,description}`. Pin `POST /api/studios/{id}/sources {agent_id:<ds_id>}`. Instruction `POST /api/studios/{id}/instructions {content,source:'manual',status:'active'}`. Example `POST .../examples {question,answer,sql,source,status}`. Column desc has NO write API in core → direct SQL UPDATE datasource_tables.columns (or new F2 route below). Spreadsheet DuckDB = IN-MEM per query (re-reads uploaded file each call); PG holds descriptions/instructions → survive restart, `down -v` wipes.
- **5 NEW FEATURES (flag-gated default-OFF, ON in dev .env):**
  - **F1 auto-configure-from-doc** (`flags.AUTOMAP`/HYBRID_AUTOMAP): `backend/app/routes/studio_autoconfigure.py` + `app/ai/knowledge/doc_extractor.py`. `POST /api/studios/{id}/auto-configure/preview {file_ids[],data_source_id}` → LLM reads xlsx(openpyxl)/pptx(python-pptx) digest → strict-JSON {column_descriptions,instructions,examples,compliance} + fuzzy-match cols to live schema (difflib 0.6 + exact/ci/strip); offline fallback parses 2-col xlsx directly. `.../apply` → writes descriptions live + creates instructions/examples `status='pending'` (review-gated). PROVEN: Definitions.xlsx → 36/36 matched, 11 instr, 4 ex, 3 compliance. openpyxl+python-pptx already in requirements_versioned.txt.
  - **F2 column-desc editor**: `backend/app/routes/datasource_columns.py` GET/PUT `/api/data_sources/{ds}/tables/{tbl}/columns` body `{descriptions:{col:desc}}`. Perm = `@requires_resource_permission('data_source','view_schema')` (there is NO `update_data_source` perm). JSON-persist needs `flag_modified(table,'columns')`. FE: `components/studio/StudioTables.vue` REBUILT to render own list w/ editable desc grid (LANDMINE: this DROPPED TablesSelector delegation in the *studio* Tables tab → lost activation-toggle/stats/refresh there; agent Tables tab `agents/[id]/tables.vue` still uses TablesSelector).
  - **F3 KPI metric registry** (reuse `flags.METRICS_CATALOG`): `backend/app/routes/studio_metrics.py` — stores metrics AS StudioExample rows (question=`[METRIC] <name>: <def>`, status active) → already surfaced via studio examples, NO new table/migration. POST/GET/DELETE `/api/studios/{id}/metrics`. (Org-level MetricDefinition catalog also exists separately — not studio-scoped.)
  - **F4 compliance scan** (NEW `flags.COMPLIANCE_GATE`/HYBRID_COMPLIANCE_GATE; NOT reusing GOVERNANCE=agent-prompt-metadata): `backend/app/routes/compliance_scan.py` + `app/ai/compliance/scanner.py`. `POST /api/data_sources/{ds}/compliance/scan {phone_column?,required_fields?}` read-only via `DataSource.get_client().aexecute_query()` (helper at knowledge.py:470). dedup auto-picks /phone|contact|mobile/i col (Abbott has none → 'skipped'; "Contact Name" matches /contact/ = false-pick, pass phone_column to override), quality = missing-count per required field. PROVEN live: District 72% missing, quality_score 0.64.
  - **F5 self-learning review queue** (FE): studios/[id]/index.vue Instructions tab — lists `status=pending` instr+ex w/ Approve/Reject. Real endpoints: `POST /api/studios/{id}/instructions/{rid}/approve|reject` + same for examples (studio_instructions.py:237/262).
- **ROBOT ASSISTANT** (floating pixel Claude-Code-style mascot + live activity console): `frontend/components/RobotAssistant.vue` + `composables/useActivity.ts` (Nuxt useState singleton key `cityagent-activity`; contract: state idle|thinking|processing|success|error, start/setState/log/done/fail/openPanel/closePanel/clear, busy computed) + NEW `frontend/app.vue` (created — was none; MUST keep `<NuxtLayout><NuxtPage/></NuxtLayout>` + `<RobotAssistant/>`). Wired: studios/[id]/index.vue (auto-configure/compliance call sites push events) + reports/[id]/index.vue (watch runActive + activeSteps=blocksToSteps → log each step once, de-dup by step id). **SCOPED PER-AGENT**: `visible` computed = route matches `/(studios|agents|reports)/:id` (excl `/new`); `watch(agentKey)`→clear()+closePanel() so logs don't bleed across studios. **Launcher = NO disc** (user: "why circle around robo") — `.ra-bot-btn` background transparent + `filter:drop-shadow`, border-radius 0; busy pulse-ring only while working.
- **Mockups**: mockup-studio-train.html (real studio shell keep/add map), mockup-knowledge-train{,-real}.html, mockup-robot-logs.html, mockup-robot-claude.html (the animated pixel robot source for the component).
- **BUILD/DEPLOY**: FE change → `docker compose -f docker-compose.build.yaml build app` then `up -d --force-recreate app` (force-recreate picks up new compose env like HYBRID_AUTOMAP/COMPLIANCE_GATE; plain `docker restart` keeps OLD env → flags stay OFF). Backend-only → docker cp + restart works for code but NOT env. main.py registers routers explicitly (import block ~L50 + `app.include_router(x.router, prefix='/api')`); flags in `app/settings/hybrid_flags.py` (@property reading HYBRID_*) + `.env` + `docker-compose.build.yaml ${VAR:-0}` (all-three-or-silent-OFF landmine).

## 2026-06-22 — PRE-TRAIN BRAIN (Column Intelligence, Batch A/B/C) + studios blank-nav fix — LIVE, BAKED
User goal: fix 1000-row cap, make the agent "prepare already instead of training after question", know each column's type/role/values. All gated `HYBRID_COLUMN_INTEL` (default OFF / dev .env ON), baked into `cityagent-analytics:dev`, ca-app healthy :3007 (scale overlay ca-pgbouncer/ca-redis).
- **Batch A** — (1) row cap killed: org setting `limit_row_count` → value 0 / state `disabled` (config col is `json` not jsonb → `update organization_settings set config=(jsonb_set(jsonb_set(config::jsonb,'{limit_row_count,value}','0'),'{limit_row_count,state}','"disabled"'))::json where (config::jsonb) ? 'limit_row_count';`). Cap applies at `format_df_for_widget` (`code_execution.py:1091` `df.head`). (2) robot scope `RobotAssistant.vue:97` regex `(studios|agents|reports)`→`(studios|agents)` (agent-studio only, no report pages). (3) en.json `studio.tabKnowledge`/`addToKnowledge` keys. (4) active aggregate-in-SQL StudioInstruction (FK `instruction_id` is nullable → omit on manual insert).
- **Batch B = COLUMN INTELLIGENCE (the core)** — NEW `backend/app/ai/knowledge/column_intel.py`: client-based profiler that runs through `DataSource.get_client().aexecute_query()` (live DuckDB for the spreadsheet connector — NOT the dead `services/autotrain/profiler.py` which targets PG staging). Per column → `{role,distinct,null_pct,min,max,values}` (role = id/date/measure/dimension; `values` list only for dimensions with 0<distinct≤50, top 20). Read-only guarded, never raises. NEW `backend/app/routes/column_profile.py`: `POST /api/data_sources/{ds}/profile` merges into `DataSourceTable.columns[].metadata` keys role/values/distinct/null_pct/min/max (NEVER touches `description`; `flag_modified(t,'columns')` + commit) + `GET .../columns/intel`. Agent reads them: `ai/context/sections/tables_schema_section.py` (BOTH render paths) emits `<column ... role= values="a, b …+N more" distinct= nulls="X%"/>`. Flag in hybrid_flags.py @property + .env + compose `${HYBRID_COLUMN_INTEL:-0}`; router import+include in main.py. **LANDMINE: the model file is `app/models/datasource_table.py` (class `DataSourceTable`), NOT `data_source_table.py`.** E2E proven Abbott 21,240 rows / 36 cols (Brand→Ensure/Glucerna…, Channel→Digital/Trade/Ethical, District 72% null).
- **Batch C** — **P5 no-guess/value-resolution**: static directive in `agent_v2.py` (after the ambiguity-gate block ~L2222, gated COLUMN_INTEL, fail-open) "### Use real column values (no guessing)" — match the user term to an ACTUAL listed value case-insensitively, NEVER invent a filter value not in `values`, prefer cols by `role`, caveat high-null. **P6 one-click pre-train**: NEW `POST /api/data_sources/{ds}/pretrain {table_name?,suggest_knowledge=true,auto_approve=false}` in column_profile.py — (1) profile+store (shared helpers `_store_profile`/`_dimensions_summary`), (2) if suggest_knowledge & (SEMANTIC_LAYER|METRICS_CATALOG): `propose_knowledge_from_schema(focus=both)`→pending, (3) if auto_approve: `_auto_approve` flips returned SemanticTable/MetricDefinition ids status='approved' (SAFE — freshly-proposed rows have no competing approved-current row, so a plain flip can't collide with the bitemporal `uq_*_current` partial-unique index). FE `frontend/pages/agents/[id]/queries.vue`: clay **Auto-train** button + **Auto-approve** checkbox (admin-only `isAdmin=useCan('update_entities')`) + result card (rows·cols + dimension value chips). **P7 robot pre-train stream**: `runPretrain()` drives `useActivity` (start/openPanel/log per dimension/done/fail); robot already agents-route-scoped (Batch A) → live console on the queries page. E2E PROVEN: pretrain ok, 21240 rows, 36 written, 7 knowledge proposed (auto_approve=False) / 7 approved (auto_approve=True). **DEFERRED: P6 "benchmark gate"** (post-train eval run) NOT built — no safe per-agent eval-trigger without goldens; use the Evals page. In-container smoke = run host python → :3007 (the app listens :3000 inside; can't sed files in container /tmp — perms).
- **STUDIOS BLANK-ON-FIRST-NAV FIX.** Symptom: click Workspace → Agent Studios (and other Workspace pages) → blank, works on 2nd click. ROOT: global `app.pageTransition { name:'page', mode:'out-in' }` (`nuxt.config.ts`) stranded the ENTERING page at `.page-enter-from { opacity:0 }` on the first SPA nav (enter hook skipped) — the same strand class the report page had opted out of individually via `pageTransition:false`. FIX: disable it globally — `app: { pageTransition: false, layoutTransition: false }`. Fixes every page at once; `.ca-*` entrance helpers in `assets/css/transitions.css` still animate. SIGNATURE: blank-on-client-nav + works-on-2nd-click/refresh + NO console error == a route/page transition stranding the new page invisible (NOT a data/null bug).

## 2026-06-22→23 — STUDIO AUTO-PILOT + AUTO-TRAIN PIPELINE (sources merge · auto-queries/evals · async train · wizard) — LIVE, BAKED
Big multi-day push turning per-studio training into a one-button, self-driving pipeline. All gated, OpenRouter-only, baked into `cityagent-analytics:dev` (:3007, scale overlay). Full detail + landmines in memory `project_cityagent_autotrain_pipeline.md`.

**SOURCES PAGE = "Sources & Knowledge" (Design A merge).** `frontend/pages/studios/[id]/index.vue`: Knowledge tab folded INTO Sources; Connection + Tables folded INTO each source card as in-card tabs (Tables · Knowledge · Insights · Connection). Skills rail item HIDDEN (off for stability). Per-card knowledge add = inline form (no dropdown → killed the "why org-wide default" bug). Federation panel (auto-mined joins, % conf · ×N seen, enable/auto-enable) + Studio-insights panel (varied: coverage · widest-breakdown · sample values · date span · measure range · ONE null caveat) + Auto-configure-from-doc (one shared block).

**AI AUTO-PILOT page** (NEW rail tab `autopilot`, group 'main', DEFAULT landing): readiness ring (0-100 from sources/cols/docs/instr/examples/joins/artifacts — counts EXISTENCE not just active), stat grid, Connected-data cockpit (per-source trained/not + tables·cols), capability map (Tables/Knowledge/Evals/Artifacts/Federation/Skills-not-needed), AI suggestions, Pin/Upload + ONE **Auto-train everything** button. LANDMINE FIXED: `intelFor()` must be a PURE reader — writing a default slot inside a computed getter broke Vue tracking → "0 columns trained" while panel showed trained. fetchIntel owns slot creation.

**AUTO-TRAIN PIPELINE (4 sub-agents wave 1).** Per pinned source, all flag-gated:
- profile-all-cols fix (`column_intel.py`: values cap 50→200, distinct ALWAYS computed/None-on-fail, role always set).
- **CONNECTOR MULTI-TABLE fix** (`column_profile.py` `_profile_all_tables`): pretrain/profile looped ONE table only → connector's other tables stayed blank. Now loops EVERY active table, scoped per table (`_store_profile(only_table=)` — no shared-name cross-contamination). Music Store 11 tables/64 cols.
- **auto-queries** (`HYBRID_AUTO_QUERIES`, `ai/knowledge/auto_queries.py` + route): LLM proposes SELECTs → validates read-only → RUNS → saves passing to QueryLibrary (status='approved', source='auto').
- **auto-evals** (`HYBRID_AUTO_EVALS`, `ai/knowledge/auto_evals.py` + route): LLM Q+SQL → runs to derive REAL expected → TestCase golden (FieldRule shape, not flat — landmine). Creation only.
- **3 new artifact kinds** (`studio_artifacts.py` GENERATED_KINDS += notes/kpi_pack/data_dictionary; data_dictionary = DETERMINISTIC from intel).
- auto-approve toggle + parallel **Approve all** (FE) for pending instructions/examples/docs.

**THE BIG ROOT-CAUSE BUG (`_is_read_only_sql`).** The read-only guard (3 copies: column_intel, routes/knowledge, compliance/scanner) rejected ANY SQL containing the word **`call`** (CALL = stored-proc statement) → every query touching a `"Call Type"`/`"Call Outcome"`/`"Call Category"` column was blocked BEFORE running → killed profiler (distinct=None), auto-queries (Abbott 0 saved), evals. FIX: strip `"quoted idents"` + `'string literals'` before the write-keyword scan in all 3 copies. Abbott went 0→36/36 profiled, auto-queries 0→5+ saved. (Headers were CLEAN — NOT a ZWSP issue as first theorized; VERIFY-LIVE caught it via an in-container probe showing `_is_read_only_sql` False for "Call Type".) Also `_classify_role` reworked: id ONLY by id-name OR near-unique NUMERIC (text near-unique = dimension); date wins over surrogate-key rule.

**ASYNC BACKGROUND TRAINING (wave 2).** Auto-train was synchronous (FE awaited 30-90s of LLM). NEW `ai/knowledge/train_orchestrator.py` (in-proc `_RUNS` + strong `_TASKS` ref, own session, fail-soft per stage: profile→queries→evals→artifacts→value-joins) + `routes/studio_train.py` `POST /studios/{id}/train` (returns 0.1s) + `GET .../train/status`. FE `runFullTrain` POSTs + polls a %, non-blocking — navigate away, job continues. **LANDMINE: `_RUNS` is per-uvicorn-worker (4 workers) → poll hits wrong worker = "idle" flicker. FIXED: `_persist_db` mirrors status to `Studio.config['_train_status']` at each stage; GET route reads it when in-proc idle.** Proven done/100%.

**INCREMENTAL + DRIFT + DAY-1 JOINS + GENERIC COMPLIANCE (wave 2).**
- **Watermark skip** (`column_profile.py`): per-table `row_count` in `DataSourceTable.metadata_json['_profile_watermark']`; `_profile_all_tables(force=)` skips unchanged tables (ProfileRequest/PretrainRequest +`force`, `skipped_unchanged` in response).
- **Schema-drift** `GET /data_sources/{id}/schema-drift` (NEW `ai/knowledge/schema_drift.py`, live-vs-stored col diff, no persist).
- **Value-overlap joins** (`join_miner.py mine_value_overlap_edges` + route `value_joins.py POST /data_sources/{id}/mine-value-joins`): samples DISTINCT values, overlap≥0.5 → pending TableEdge source='value_overlap'. Works day-1 (no query history). Orchestrator runs it. Proven 40 edges.
- **Compliance genericized** (`scanner.py`): `_derive_required_fields` from live schema (geo/name/id/contact/date patterns); explicit list still overrides; City/District = last-resort generic fallback.
- **New-agent WIZARD** `frontend/pages/studios/new-agent.vue` (4 steps Name→Data→Train→Ready, real APIs + async train poll; Skip=background). `STUDIO_LEARN_DAEMON_ENABLED=1`.

**FLAGS added:** `HYBRID_AUTO_QUERIES`, `HYBRID_AUTO_EVALS` (+ existing COLUMN_INTEL/JOIN_GRAPH/STUDIOS/DOC_KNOWLEDGE). Env knob `STUDIO_LEARN_DAEMON_ENABLED`. main.py +auto_queries/auto_evals/studio_train/value_joins routers. NO migration (watermark in existing `metadata_json`; reused QueryLibraryItem/TestCase/StudioArtifact). Mockups: mockup-{sources-unified,studio-ai-autopilot,autotrain-pipeline,new-agent-wizard}.html. Agent analysis Python + dashboards = core `create_data`→`create_artifact` (claude-sonnet-4.6); NO skills/subagents/MCP (off for stability).

## 2026-06-23 — SUGGESTED FOLLOW-UP QUESTIONS (per-agent, ChatGPT/Claude style) — LIVE, BAKED
After every chat answer, 3-4 clickable follow-up chips render under the LAST assistant message; click → re-submits as a new question. **Per-agent**: each Studio generates its OWN follow-ups (not one global set). Flag `HYBRID_FOLLOWUPS` (default OFF / dev .env ON). 2 sub-agents (BE generator + FE wiring) + parent route/flag/bake. Plan-first (presented in CLI), then built.
- **GENERATOR `backend/app/ai/knowledge/followups.py`** (NEW, clones `auto_queries.py` idiom — same `LLM(...).inference(usage_scope="followups")` SYNC→`asyncio.to_thread`, `LLMService().get_default_model(is_small=True)`, `_introspect_schema_text` schema digest, tolerant fence-strip JSON parse, flag self-gate, NEVER raises, writes NOTHING). `async generate_followups(db,*,organization,current_user,report_id,answer_text="",question_text="",model=None,max_n=4) -> {ok,followups:[str],source:"studio"|"report"}` (`{disabled:True}` when flag off). **PER-AGENT grounding** = load Report→`studio_id`; if studio: voice=`Studio.persona` + ACTIVE `StudioInstruction.content` (status=='active') + optional explicit override `StudioArtifact(kind=='followup_policy')` (NOTE: StudioArtifact has NO status col → take most-recent non-deleted) + pinned-source schema digest (so chips reference REAL columns). ONE small-model call → JSON array of short Qs, clamp max_n 1..6. answer/question passed from FE (fallback loads latest `Completion.completion` — `Completion` has NO `content` col, only `.completion` JSON; roles are 'system'/'user'/'external', not 'ai_agent').
- **ROUTE `backend/app/routes/followups.py`** (NEW): `POST /api/reports/{report_id}/followups` body `{answer_text?,question_text?,max_n?}`. Auth mirrors `routes/completion.py` (`@requires_permission('create_reports')` + org-scoped Report load → 404 if not in org). **LANDMINE re-confirmed: NO `from __future__ import annotations`** (permission-decorated body → FastAPI mis-reads as query 422); body = `Dict[str,Any] = Body(default={})`. Route declares full `/api/...` path → registered in main.py via `app.include_router(followups.router)` WITHOUT `prefix` (like completion.py), NOT the `prefix="/api"` form the studio routers use.
- **FLAG** `HYBRID_FOLLOWUPS`: `hybrid_flags.py` @property `FOLLOWUPS` + `UPGRADE_FLAGS["HYBRID_FOLLOWUPS"]={"label":"Suggested Follow-ups","role":"user"}` (→ admin Feature-Flags page) + in `snapshot()` + `.env`(=1) + `docker-compose.build.yaml`(`${...:-0}`). All-three-or-silent-OFF.
- **FRONTEND `frontend/pages/reports/[id]/index.vue`** (only FE file): `ChatMessage` += `followups?:string[]`/`followups_loading?:boolean`. `fetchFollowups(m)` (guard: system msg + status==='success' + not training + not already loaded) derives `answer_text` by walking `m.completion_blocks` from end (content/final_answer/assistant, `completion.content` fallback for cache-served) → `POST` bare `/reports/${id}/followups` via `useMyFetch` → sets `m.followups`; fail-soft ([] on error/`{disabled:true}`, no re-fetch spam). Triggers: SSE `completion.finished` handler (fire-and-forget `setTimeout(...,0)`) + `watch(lastSystemMessage)` for already-finished reopens. RENDER: `mt-3` block under the message gated `m.id===lastSystemMessage?.id` + non-training — shimmer "Thinking of follow-ups…" while loading, else clay chips (verbatim empty-state starter class `border-gray-200 bg-gray-50 hover:bg-[#F3E7DF] hover:border-[#C2683F]`, no blue/emoji) `@click="handleExampleClick(q)"` (existing re-submit fn). Cache-served answers (0 blocks) still get chips.
- **VERIFIED LIVE (pre-bake, in-container, real OpenRouter):** route registered `/api/reports/{report_id}/followups`, `flags.FOLLOWUPS=True` + in snapshot, `generate_followups` on a real Abbott studio report → `source="studio"`, ok=True, 4 grounded Qs referencing real cols (channel types, call categories, Jan–June period). Then full image rebuild + force-recreate. Default OFF in prod (flag); reuses small model · no migration · no new table.

## 2026-06-23 — STUDIO LAUNCHER TAB (NotebookLM-style outputs + merged Activity) — LIVE, BAKED, FE-ONLY
Right-panel reworked into ONE **Studio** tab = output-launcher cards on top + live run-state below. NotebookLM "Studio" parity adapted to analytics. Plan/mockup-first in CLI (mockups `mockup-studio-{outputs,combined,actions,compact,merged}.html` in repo root), built across **3 sub-agents** (each baked). ALL in `frontend/pages/reports/[id]/index.vue` (single file, no backend, no migration). Bake = full image rebuild + force-recreate (baked Nuxt SPA); hard-refresh browser for new JS chunk.
- **NEW `'studio'` view** added to `rightPanelView` union (+ `setPanelView` sig). **Default landing = `'studio'`** (was `'activity'`); persists on fresh/new chat (onMounted only sets `'artifact'`/`'summary'` when pre-existing content → empty chat falls through to studio). Tab button = FIRST in row, clay sparkle SVG (flat `#C2683F` fill, no gradient), active `bg-[#F6EFEA]`. `panelLeftWidthFor('studio')`=0.55 (Outputs width); 'studio' added to the watch + toggleSplitScreen + leftPanelWidth branches (alongside summary/activity).
- **TOP = 2×3 output cards (`grid-cols-2`, compact `p-2` tiles, 15px icon + 11px label + 9px badge).** Click → GENERATE: Dashboard/Report/Infographic = `handleExampleClick('<preset prompt> ' + (lastUserQuestion||report?.title))` (real agent run via existing submit path — `lastUserQuestion` computed = latest `messages.value` role==='user' `m.prompt.content`, fallback report.title). Slides/Excel = INSTANT `setPanelView('slides'|'excel',true)` (SlidesPanel from `visualizations` / ExcelPanel from rows build on view, no LLM). Insight Map = SOON disabled `<div cursor-default opacity-65>`. NO new endpoint — agent cards just preset-prompt the existing pipeline.
- **BOTTOM = Activity tab MERGED in** (3rd sub-agent): the separate **Activity tab button was REMOVED**; its content now lives in the Studio pane below the cards, reusing the EXACT existing computeds verbatim (NO new ones): **NOW banner** (`activityNow`, clay pulse, "Idle" when not running) + **Progress card** (`activeSteps` done/run/warn rows + retry pill + `activityProgressPct` bar + `activityDoneCount`/`activityTotal`, internal `max-h` scroll) + **Data sources** `<details open>` (`report?.data_sources` + active pills) + **Skills used** `<details>` (`activitySkills`) + **Sub-agents** `<details>` (`activitySubagents`, `kind==='subagent'`) + **Outputs this run** card (`activityOutputs` rows → click `setPanelView('artifact',true)`). `<details>` summaries hide marker + `.chev` rotate-on-open (scoped CSS).
- **Run-start auto-flip REPOINTED**: `if (!userPinnedView.value) setPanelView('activity')` → `setPanelView('studio')` (so live run state shows IN Studio). Auto-pilot still flips to Dashboard on REAL artifact (kept).
- **LANDMINES / dead code:** old `v-else-if="rightPanelView === 'activity'"` pane block left in place but **unreachable** (no button) — harmless, `'activity'` still in union + width branches so nothing breaks; an intermediate `studioFeed` ref (Activity/Agents/Skills segmented switch from the 2nd sub-agent) is now UNUSED (superseded by the merged layout) — left in, harmless. Cleanup optional.
- **OPEN (not built):** Infographic = BETA (fires a prompt, no real infographic builder yet); Insight Map / Forecast / Anomaly = SOON stubs. Cheapest next real: Infographic builder (compose existing KPI cards + 1 chart → poster + export) or Exec Summary (one small-model call). NOT yet eyeballed live by user during a real run.

## 2026-06-23 — DESIGN SYSTEM STANDARDIZATION (UI/UX source-of-truth + Tier-1 sweep) — LIVE, BAKED, FE-ONLY
NEW spec file **`DESIGN_SYSTEM.md`** (repo root) = single source of truth. Locks: 13 color tokens (clay=brand/action, green=status only, red=error only, NO `gray-*`, NO raw blue except charts), type scale (serif H1 `text-2xl font-semibold` + `ui-serif,Georgia,serif`; serif H2 `text-[15px]`; sans body 14px `text-sm #6b6b6b`; muted `text-xs #9a958c`), **exactly 3 button variants** (primary `rounded-xl px-4 py-2.5 bg-[#C2683F] hover:bg-[#A8542F]` · secondary `rounded-lg px-3 py-2 border-[#E7E5DD] hover:bg-[#F4F1EA]` · ghost dashed `rounded-lg border-dashed text-[#C2683F]`), 3 card types (interactive `rounded-2xl` hover-lift · feature `bg-[#F6EFEA] border-[#E8C9B5]` · info `rounded-lg`), page shell (`max-w-7xl px-4 md:px-6`, serif H1 header row `flex items-start justify-between gap-4 mb-6`), empty/loading (skeleton > spinner), status pills, a11y checklist. Working reference mockup **`mockup-design-system.html`** (nav-switchable: Auto-pilot / Studios / Settings / Components&Tokens, real clay tokens).
- **Audit (Explore agent, 40+ pages):** app was ~65% on-spec. Strong already = clay scale + serif H1 + heroicons + `max-w-7xl`. Broken = **7 button variants**, legacy `gray-*` in index/identity-provider/evals, settings section-H2 drift, empty-state/spinner inconsistency.
- **Tier-1 sweep applied (3 sub-agents, disjoint FILE sets to avoid concurrent-edit conflict, edit-only → ONE build → force-recreate):** ~250 `gray-*` tokens purged in `settings/identity-provider.vue` alone (+~27 audit, +general/ai_settings/smtp/overview/members/index/evals); buttons collapsed to 3 variants across settings + connectors/skills/studios (radii/padding normalized, `cursor-pointer transition-colors` added, Cancel→secondary, clay-Save→primary `rounded-xl`); `index.vue` landing title→serif; evals serif-on-body removed + `UButton color="orange"`→`color="primary"`.
- **KEY FINDING:** settings page TITLE is rendered by `layouts/settings.vue` per-tab (already serif H1) — the audit's "settings header divergence" was section **H2s**, not the page title; so NO per-page H1 added to settings content panes (would double-up). `overview.vue` had its own visible title → upgraded to serif H1.
- **VERIFIED:** Docker build ran `nuxt generate` (fails loud on any broken SFC — PASSED, all tags balanced), `ca-app` healthy, `:3007` → 200. FE-only, NO backend/migration.
- **LEFTOVER (out of Tier-1 scope, cosmetic stray `gray-*`, non-blocking):** `settings/integrations/*`, `settings/members.vue` (1 token), `evals/runs/[id].vue`. **TODO Tier-2:** hoist serif to `tailwind.config.ts fontFamily.serif`; define `.ca-btn-primary`/`.ca-card` global css classes so pages stop repeating long class strings.

## 2026-06-23 — PER-AGENT SCOPE GUARDRAIL + STUDIO SOURCE-LOCK — LIVE, BAKED, default-ON
Two coupled fixes after an agent answered "who is president of usa" (general knowledge) then only soft-deflected, AND its Activity panel listed all 8 org data sources instead of the agent's 3.
- **WHY guardrail was missing:** this fork only ever had the *ambiguity* (clarify) gate — NO *scope* gate. Topic-boundary was 100% base-model behavior (knows the fact, answers, politely deflects after). Citypharma has a scope gate; this fork never got one.
- **SCOPE GUARDRAIL (BE):** new flag **`HYBRID_SCOPE_GATE`** (`settings/hybrid_flags.py`: property `_bool("HYBRID_SCOPE_GATE", True)` — **default ON** + UPGRADE_FLAGS `{"label":"Scope Guardrail","role":"user"}` → admin Feature-Flags page + snapshot). **Zero-LLM directive** injected pre-loop in `ai/agent_v2.py` right AFTER the ambiguity block (mirrors that pattern: flag-gated, fail-open, `try/except pass`). Grounded per-agent by `self.data_sources` names (= report's pinned sources): "you are a data agent for THIS workspace; scope = <source names>; OFF-TOPIC (general knowledge/world facts/current events/politics/trivia) → do NOT answer EVEN IF you know, no answer-then-deflect → 1-sentence 'outside this agent's data scope' + what it CAN do; data-shaped Qs lean in-scope." Compose `${HYBRID_SCOPE_GATE:-1}`, `.env=1`. Verified in-container `flags.SCOPE_GATE=True` + in snapshot. Per-agent override still possible via StudioInstructions.
- **STUDIO SOURCE-LOCK (BE):** root cause of the 8-vs-3 leak — the chat composer's source picker DEFAULTS to ALL org sources → posts them → `report_service.create_report` (and `update_report`) **unioned** composer-sent ids with the studio's pinned `StudioDataSource` set → a studio report grabbed all 8 (music+finance+bakery+RTM+pharma). FIX: both paths now **LOCK a studio report to the agent's pinned Data Agents** — keep only composer ids ∈ pinned, fall back to full pinned set if none. So a studio report's `data_sources` ≡ the agent's pinned set; this also tightens the guardrail (`self.data_sources` = pinned, refusal names only real data) and query access. **Ground truth (dev):** studio "Work" pins 3, "CRM" pins 1, org total 8. **Backfill:** one-time SQL deleted **62** leaked `report_data_source_association` rows (studio reports → strip any data_source not pinned to that studio, only when the studio HAS pins); viewed report dropped 8→3.
- **LANDMINES:** report↔source = `report_data_source_association` M2M; studio pins = `studio_data_sources` (col `agent_id` = data_source id, soft-delete `deleted_at`). Report `data_sources` count comes from COMPOSER selection at create-time, NOT the studio pin (same studio had reports with 8/3/3 before the lock). Composer UI still *visually* lets you select all-org — BE overrides on save; **FE composer not yet locked to pinned in studio mode (TODO).**
- **VERIFIED:** py_compile OK, build OK, `ca-app` healthy. NO migration (flag + code + data-backfill only).

## 2026-06-24 — SLIDES + DASHBOARD CONTRAST FIX (dark-on-dark invisible charts/text) — backend LIVE, FE pending build
Symptom: generated decks/dashboards used a dark navy theme but charts + some text rendered dark-on-dark (invisible), and the slide "1/6" counter + thumbnail strip clipped off the bottom.
- **ROOT CAUSE (two render paths, both LLM-authored):**
  1. **Slides** = LLM writes **python-pptx code** (`create_artifact.py:_build_slides_prompt`) → executed (`code_execution/pptx_executor.py`) → PNG previews → `frontend/components/dashboard/SlideViewer.vue`. Native python-pptx charts default their **axis-label / legend / data-label fonts to BLACK** → invisible on the slate-900 slides the prompt pushed. The prompt **never recolored chart fonts** (textboxes got white, charts didn't).
  2. **Dashboard** = LLM writes **React+ECharts in an iframe** (`_build_page_prompt` → `frontend/utils/artifactIframe.ts` → `ArtifactFrame.vue`). The `dash` ECharts theme + `KPICard`/`SectionCard` defaults are **light-tuned**; when the LLM chose a dark page, axis labels/legend/cards stayed dark → dark-on-dark. No hard contrast rule forced light text on dark.
- **FIX (prompt-level, agent picks light/dark PER TOPIC + contrast enforced both modes — user choice):**
  - `_build_slides_prompt`: added a mandatory **`style_chart_text(chart, color)`** helper (recolors category/value axis ticks + legend + data-labels) to the QUICK REFERENCE + the OUTPUT example, defined `TEXT_DARK`/`TEXT_ON_BG`, and a **"CONTRAST IS NON-NEGOTIABLE"** block: pick ONE bg mode, native pptx charts are BLACK by default so you MUST call `style_chart_text` on EVERY chart.
  - `_build_page_prompt`: added a **"CONTRAST CONTRACT"** block before AVAILABLE COMPONENTS — on a dark page, pass light `className/titleClassName` to every card AND explicit light `textStyle/axisLabel/legend/axisLine` in every ECharts option (the `dash` theme is light-tuned); on a light page keep the defaults; self-check for same-lightness-as-surface.
  - `SlideViewer.vue`: compacted the bottom bar to **one row** (counter inline + smaller `w-12 h-7` thumbs, `py-1.5`) + added `no-scrollbar` `<style>`, so the counter+thumbs stay inside the viewport (the report-route `h-screen` overflow pushed the old taller two-row bar off the bottom).
- **STATUS:** backend `create_artifact.py` **hot-copied to `ca-app` + restarted = LIVE** (regenerate a deck/dashboard → readable; py_compile OK). `SlideViewer.vue` edit is on disk, **NOT yet baked** (needs a FE image rebuild — deferred to save laptop resources). Snapshot `.backups/20260624_062419_slide-dash-contrast-fix`.
- **CAVEAT:** prompts STEER the LLM (much less likely, not a hard guarantee per generation). Deterministic backstops if a deck still slips: force-recolor chart fonts in `pptx_executor.py` after exec; inject a contrast CSS reset into the dashboard iframe in `artifactIframe.ts`. Not built yet.
- **RESOURCE LANDMINE (this session):** the FE image build's `nuxt generate` (6GB Node heap) pinned ~9 host cores via Docker's `Virtualization` VM → laptop heat. `docker cp` hot-copy is near-free; the BUILD is the hog. Also user had **many idle project stacks running** (pharmacy-agent-*, dash-*, citybrain, cp-*, bcp, musing) — stopped all non-`ca-*` (17 containers) → VM 900%→117% CPU. `docker start <name>` to bring any back.

## 2026-06-24 — PLAN: Smart Fin Pack (domain packs WITHOUT the Skills engine) — `docs/PLAN_SMART_FIN_PACK.md`
PLAN ONLY (not built). Goal: get the financial expertise of Anthropic's `anthropics/financial-services` repo (11 agents + 7 vertical SKILL.md bundles + MCP connectors, ~50 methods) into this platform, but **smart per-agent, NOT a static copy**, and **NOT via `HYBRID_SKILLS`** (livelocks, kept OFF). Everything rides the **default tools** (`create_data`/`create_artifact`) + existing gated context + auto-train surfaces.
- **CORE SPLIT — copy the INVARIANT, synthesize the VARIABLE:** the *method* (how DCF/comps/3-statement works, required inputs, golden invariants) is universal → copy Anthropic's SKILL.md verbatim, data-blind. The *binding* (which columns are revenue/FCF/debt, what entities mean here, the actual SQL) is per-warehouse → **machine-synthesize from the agent's schema**, then learn + verify. Anthropic = the financial brain; our `column_intel + semantic + AI-suggest + auto-train + eval + distiller` = the "smart" wrapper.
- **STRUCTURAL MAP (1:1, no Skills engine):** their *named agent* → our **Studio**; their *vertical* → our **domain pack**; *SKILL.md body* → **method-playbook Instruction**; *templates/reference* → **KnowledgeDoc** (PG-FTS); *examples* → **Studio Examples**; *metric defs* → **Metrics catalog**; *commands `/dcf`* → **composer macro / analysis-type selector** (prompt macro → default tools); *MCP feeds* → our connectors (bring own data). Port CONTENT + cite; subagent orchestration stays OFF (single-agent).
- **3-PHASE FLOW:** (0) PORT once → METHOD PRIOR LIBRARY (playbook/doc/inputs/invariants, no columns). (1) BIND+TRAIN per agent, one button: build Studio on financial data → `bootstrap_on_source_pin` detects domain → AUTO-BIND pack → `POST /studios/{id}/train` runs profile→bind metrics/semantic→gen financial queries (`AUTO_QUERIES`)→run+capture proven SQL→gen goldens (`AUTO_EVALS`)→eval ties-out→approve (gate). (2) RUNTIME per question: pre-loop **pack router** (ambiguity-gate slot) picks pack+method+analysis-lens → capability-gate (inputs present? else honest fallback) → value-resolution (`COLUMN_INTEL` P5) → default tools → self-verify eval → 👍/👎 learn.
- **TRAINING = the pack is the CURRICULUM** (not weights): method tells WHAT to compute, schema tells HOW (bound metrics), invariants seed the GOLDENS. Turns blind auto-train into targeted, self-checking financial training, per agent.
- **ALL 7 PACKS, tiered by data-need:** Tier A (runs on our data: 3-statement/margin/unit-economics/returns/GL-recon/NAV/KYC/portfolio) → DO FIRST; Tier B (needs market feeds we lack: comps/DCF-market-WACC/earnings-vs-consensus/buyer-list) → method-only until a feed wired; Tier C (output: pptx/xlsx/deck-refresh/ib-check) → via `create_artifact`. Build engine ONCE, financial-analysis pack first (13 methods, esp 5 modeling), then bulk-import the other 6 verticals (additive).
- **NEW flags (default OFF):** `HYBRID_DOMAIN_PACKS` (master) · `HYBRID_PACK_AUTOBIND` · `HYBRID_PACK_ROUTER`; reuse SEMANTIC_LAYER/METRICS_CATALOG/DOC_KNOWLEDGE/AUTO_QUERIES/AUTO_EVALS/EVAL_HARNESS/COLUMN_INTEL for sub-steps. **NEW small pieces:** `packs` registry, `agent_packs` binding, domain detector, pack router, method-prior import — rest is wiring into existing surfaces.
- **CEILINGS:** knowledge/eval training NOT model weights (OpenRouter, no GPU); eval-gate only as good as goldens; predictive capped by dep-free sandbox (numpy/pandas/math, NO sklearn/scipy → moving-avg/trend/seasonal-naive only, heavy ML = separate compute lane); Tier B partial without feeds.

## 2026-06-24 — BUILT Phase 0: Domain Packs engine (lightweight "Skills") — `docs/PLAN_TEACH_SKILLS_ENGINE.md`
DONE + verified live (flags default OFF → byte-identical when off). The data-gated alternative to native `HYBRID_SKILLS` (heavy/sandbox/livelocks/wrong-pick). A **pack** = declarative `.yaml` (method + required_inputs + output_spec + goldens), NEVER executed — it only injects `[METHOD]+[BINDING]` into the AgentV2 planner so the default `create_data`/`create_artifact` loop follows it. Copy the INVARIANT method, machine-synthesize the per-agent VARIABLE binding.
- **3-layer selection fixes "agent picks wrong skill":** (1) BIND gate (hard) — pack invisible unless its required_inputs bind to THIS agent's columns; (2) TRIGGER gate — question must hit the pack's `trigger_hints` (else it never fires, even when bound); (3) SCORE `0.5·trigger+0.3·conf+0.2·winrate` top-1; winrate adaptive (Phase 5). Off-topic Q on a bound agent → no pack (proven). Wrong-data pack → can't bind → invisible (proven on a music dataset).
- **FILES (new):** `backend/app/ai/packs/{__init__,registry,binder,router,runtime}.py` + `packs/library/ebitda_good_bad_ugly.yaml` (first real skill = user's CEO/CFO EBITDA Good/Bad/Ugly SOP) + migration `studiopack1_studio_bound_packs.py`. **(edited):** `models/studio.py` (+`StudioBoundPack` table: studio_id, pack_id, binding_map, output_spec, eval_goldens, status[pending|active|dormant|rejected], source[pack|user], conf, missing), `settings/hybrid_flags.py` (+`HYBRID_DOMAIN_PACKS`/`PACK_AUTOBIND`/`PACK_ROUTER`, snapshot, UPGRADE_FLAGS), `ai/agent_v2.py` (+pack injection after the scope-guardrail block ~L2258, `await packs.runtime.resolve_injection(self.db, self.report.studio_id, question)`, flag-gated, fail-open).
- **MIGRATION HEAD now `studiopack1`** (was `dashversions1`). Applied live on `ca-postgres`. Table verified.
- **BINDER LANDMINES (all fixed, see plan):** role-boost manufacturing false binds from weak names → eligibility on NAME score only (`_MIN_CONF=0.6`), role only ranks; bidirectional substring over-match → term-in-column only; camelCase warehouse names (`BusinessUnit`) didn't tokenize → camel-split in `_norm`. `BaseSchema` has `updated_at` too (migration must include it).
- **STATUS:** engine unit-proven (bind=1.0 clean, missing-budget→dormant, music→unbound, on-topic selects, off-topic→None); app healthy 200. Backups: `.backups/20260624_phase0_domain_packs/`. Deploy = hot-copy + `docker restart ca-app` (never force-recreate).

## 2026-06-24 — DONE Phase 1: Domain Packs live on real data (E2E proven)
EBITDA Good/Bad/Ugly pack bound to a real studio + flags ON + live agent run → method followed end-to-end.
- **Setup:** test studio **EBITDA Pack Test** `5ac4444c-2df0-423b-9457-7bc080128970` (org `55278108`); synth `ebitda.csv` (5 sectors, EBITDA actual/LY/budget + revenue) → DataSource `883a57ef…` pinned + profiled. Binder on real `column_intel` → `bound=true`, 7/7 mapped, conf 0.7, missing=[]. `studio_bound_packs` row `74614ae7…` status=`active`.
- **Run:** flags flipped via per-org override (`PUT /api/organization/hybrid-flags/{HYBRID_DOMAIN_PACKS,HYBRID_PACK_ROUTER}` `{enabled:true}`). Q "monthly EBITDA performance summary by sector — good bad ugly, vs LY and vs budget" → log `[DOMAIN_PACKS] injected pack block (chars=1801)`, no errors. Agent computed vs-LY/vs-Budget %, flagged Food revenue +11% (>10% rule), bucketed GOOD(Pharma,Food)/BAD(Retail)/UGLY(Logistics,Construction), built the slide deck. Numbers match hand-calc. 5 goldens snapshotted into `eval_goldens`.
- **LANDMINES:** (1) EBITDA numeric cols profile `role="id"` not `measure` — binder still binds (role only ranks, ×0.7→0.7≥floor 0.6); don't tighten. (2) **Flip flags with the per-org override API, NEVER `--force-recreate`** — recreate re-bakes from image (no hot-copied pack code) → wipes Phase 0/1; `set_override` applies live + persists to org `settings.config.hybrid_overrides`; `docker restart` keeps `docker cp` files. (3) Added a `[DOMAIN_PACKS]` injection log line in `agent_v2.py` (~L2281, logger `app.ai.packs`).
- **Flags now ON (override) for org 55278108** — other studios unaffected (no active bound packs → no-op). Revert: `PUT …/{env}` `{"enabled":null}`.

## 2026-06-24 — DONE Phase 2: Teach Box backend (paste analysis → trained agent) — E2E PROVEN
Paste an existing analysis/SOP → ONE small-model LLM call classifies into SKILL|INSTRUCTION|DATA_RULE|KNOWLEDGE spans → each routed to its surface, all born pending (review gate).
- **Routes** (`app/routes/studio_teach.py`, gated `HYBRID_TEACH_BOX`, editor-only): `POST /studios/{id}/teach` = classify + bind-preview (NO writes); `POST /studios/{id}/teach/approve` = persist spans (+optional `train:true` → `train_orchestrator.start_training`).
- **Engine** (`app/ai/packs/teach.py`): SKILL→user Domain Pack (`build_skill_pack`→`binder.bind_pack`→`StudioBoundPack` source='user', full dict in `pack_body`, active if bound else dormant); INSTRUCTION/DATA_RULE→`StudioInstruction` (DATA_RULE prefixed `[DATA RULE]`); KNOWLEDGE→`KnowledgeDoc` via `docs_index.ingest_doc`. **Column-aware classify**: studio's real column names fed into the prompt so SKILL input synonyms map to real columns (else loose LLM names score <0.6 → dormant).
- **NEW `studio_bound_packs.pack_body` JSON col** (mig `studioteach1`, **head now studioteach1**): user packs have no yaml file → whole pack dict stored inline; `runtime.resolve_injection` does `registry.get_pack(id) or row.pack_body`.
- **E2E** on studio `5ac4444c`: pasted mixed EBITDA SOP → 5 spans correctly typed → SKILL bound active → approve wrote 1 instruction + 2 data-rules + 1 knowledge-doc + 1 user pack → library pack set dormant to isolate → live run logged `[DOMAIN_PACKS] injected pack block (chars=1594)` → agent computed identical GBU. The pack_body-reconstructed user pack drove the loop.
- **LANDMINES:** (1) registry is FILE-ONLY → DB-only user pack invisible to `get_pack` → `pack_body` col + runtime fallback (don't write yaml into container, not baked). (2) feed real column names into classify or SKILL won't bind. (3) bare in-container scripts hit `InvalidRequestError: 'Completion'` (mappers not all imported) + `resolve_injection` swallows → silent ""; test pack runtime via REAL HTTP completion, not a script. (4) column shape `{name,dtype,metadata:{role}}` — hoist `metadata.role` for binder.
- **Files new:** `app/ai/packs/teach.py`, `app/routes/studio_teach.py`, `alembic/.../studioteach1_pack_body.py`. **edited:** `models/studio.py`(+pack_body), `ai/packs/runtime.py`(fallback), `settings/hybrid_flags.py`(+TEACH_BOX), `main.py`(register). Backups `.backups/20260624_phase2_teach_box/`. Flags `HYBRID_TEACH_BOX` ON (override) org 55278108.

## 2026-06-24 — DONE Phase 3: Teach Box UI — E2E PROVEN
The paste→classify→review→approve flow now has a studio-tab UI.
- **`components/studio/StudioTeach.vue`** (new, self-contained): paste box (20k cap) + "✦ Teach AI" → `POST /studios/{id}/teach`; one review card per span (type badge SKILL/INSTRUCTION/DATA_RULE/KNOWLEDGE, inline-editable title+content, include checkbox, SKILL bind status active/dormant + `key → column` map); footer "re-train after saving" toggle + green "Approve & save" → `POST /studios/{id}/teach/approve`. Clay/coral DESIGN_SYSTEM tokens, `useMyFetch`, `useToast`.
- **`pages/studios/[id]/index.vue`** (edited): import + `teach` tab in **behavior** group, gated by `teachEnabled` ref (`loadTeachFlag()` reads `/api/organization/hybrid-flags`→`HYBRID_TEACH_BOX.effective`, fail-soft OFF, called in onMounted) + `<StudioTeach>` section mount.
- **LANDMINES:** (1) FE `dist` is **baked into image, NOT bind-mounted** → `NODE_OPTIONS=--max-old-space-size=6144 npm run generate` on host (output in BOTH `dist/` + `.output/public/`) then `docker cp dist/. ca-app:/app/frontend/dist` — static served from disk, **NO restart**. Never `--force-recreate` (re-bakes stale dist + wipes hot-copied backend). (2) `useMyFetch` baseURL `/api`; ufo `withBase` skips double-prefix → use `/studios/...` for studio routes, `/api/organization/...` for org. (3) approve summary keys = `skills_active`/`skills_dormant`/`data_rules`/`instructions`/`knowledge` (NOT `skills`). (4) hybrid-flags GET is `manage_settings`-gated → tab only loads for admins/owners.
- **E2E:** built+deployed; teach string in chunk `dist/_nuxt/Cqo-F34R.js`; `HYBRID_TEACH_BOX effective=True`; live `POST /studios/5ac4444c/teach`→HTTP 200, 3 spans (2 DATA_RULE+1 SKILL "active skill"). Backups `.backups/20260624_phase3_teach_ui/`.

## 2026-06-24 — DONE Phase 4: Pack train wiring — E2E PROVEN
Train run now binds packs + biases the generators + surfaces dormant skills. NEW `backend/app/ai/packs/pack_train.py` (3 fns), wired into `train_orchestrator` as stage 1b (after profile) + stage 3b (after evals). Hot-copy + restart deploy (NO FE rebuild).
- **`autobind_library_packs`** (gated `flags.PACK_AUTOBIND`): try EVERY library pack vs the studio's profiled columns. Full bind → `pending` StudioBoundPack row (review gate, source=`pack`); partial (≥1 input, a required missing) → `dormant` row w/ `missing`; 0-match → skip. Idempotent — existing (studio,pack_id) rows untouched. Summary `{bound,dormant:[{pack_id,name,missing}],skipped,existing}` → `train_status.detail.packs`.
- **`build_skill_context`** → text block (method snippet + trigger hints + binding) of the studio's ACTIVE packs; threaded as new `skill_context=` kwarg into `generate_queries_for_studio`/`generate_evals_for_studio` (both `_build_prompt` now take it) so seeded queries/evals cover the skills' math ("seed from method").
- **`materialize_pack_goldens`** (gated `flags.DOMAIN_PACKS`): any `eval_goldens` an active pack carries → `TestCase` rows (same suite + FieldRule shape as auto_evals, dedupe by name). No-op until goldens exist.
- **LANDMINES:** (1) bare-script (`python -c`) hits the `Completion` mapper-init error → `studio_columns`/`_active_packs` swallow it → []; **test via REAL HTTP train**, not a bare script. (2) per-org flag overrides are NOT in process env → `flags.PACK_AUTOBIND` reads OFF in bare scripts; flip via `PUT /api/organization/hybrid-flags/HYBRID_PACK_AUTOBIND {"enabled":true}` (body key `enabled`, not `override`). (3) train status is per-worker, persisted to `Studio.config['_train_status']`; polls bounce across workers — read `detail` off the `done` snapshot.
- **DEFERRED:** generatively snapshotting a method on real data to MINT goldens (needs full agent loop) — later pass.
- **E2E:** PACK_AUTOBIND flipped ON (org 55278108); deleted stale `ebitda-good-bad-ugly` pack row on studio `5ac4444c`, HTTP train → `detail.packs={bound:1,...,existing:0}`, DB row recreated `pending`/`pack`/conf 0.7 all 7 inputs bound; `queries.saved=6`+`evals.created=6` (w/ skill_context from active user pack); `pack_goldens={created:0}`. Backups `.backups/20260624_phase4_train_wiring/`.

## 2026-06-24 — DONE Phase 5: Domain Packs adaptive + harden — E2E PROVEN
Win-rate demote + drift re-check + promote-to-org. Migration head **packwin1** (3 tables: `pack_winrates`, `pack_fire_events`, `org_packs`). Hot-copy + `alembic upgrade head` + restart (NO FE rebuild).
- **pack_winrate (feedback demote):** at injection `runtime.resolve_pack` records WHICH pack fired on the completion (agent_v2 → `winrate.record_fire` writes `pack_fire_events`). A later 👍/👎 (`completion_feedback_service._maybe_record_pack_signal`, BOTH directions) → `record_signal_for_completion` upserts passes/fails+score on `pack_winrates(studio,pack,question_cluster)`. `resolve_pack` reads `get_winrate(cluster)` per candidate → feeds `router.score_candidate` (ranking demote) AND benches a proven loser (`is_benched`: score<0.15 over ≥5 samples → skipped). Cluster = matched trigger hint (per-pattern).
- **recheck_bindings (drift):** `pack_train.recheck_bindings` each train (orchestrator stage 1b, after autobind): re-bind existing dormant/active/pending rows vs current cols → dormant→pending (missing input reappeared; never auto-activate), active/pending→dormant (bound col vanished); `rejected` untouched. → `detail.pack_recheck`.
- **promote-to-org:** `org_packs` table + `OrgPack` + `POST /studios/{id}/packs/{pack_id}/promote` (editor+, copies user pack `pack_body`→org store) + `GET /organization/packs`. `autobind_library_packs(db,sid,organization)` now binds org packs alongside yaml library (`source='org'`, inline `pack_body`) → every org studio picks it up next train. Runtime unchanged (serves from pack_body). Router registered in `main.py`.
- **Files:** mig `alembic/versions/packwin1_pack_winrate.py`; NEW `app/ai/packs/winrate.py`, `app/routes/studio_packs.py`; EDITED `models/studio.py` (+PackFireEvent/PackWinrate/OrgPack), `ai/packs/runtime.py`, `ai/packs/pack_train.py`, `ai/agent_v2.py`, `services/completion_feedback_service.py`, `ai/knowledge/train_orchestrator.py`, `main.py`. Backups `.backups/20260624_phase5_adaptive/`.
- **LANDMINES:** (1) bare-script flag landmine again — `recheck`/`record_*` read DOMAIN_PACKS OFF in a bare `python -c` → test via HTTP. (2) `ErrorCode.VALIDATION` (NOT `VALIDATION_ERROR`). (3) `StudioBoundPack.source` now also `'org'` (+`pack`/`user`). (4) **DEPLOY: copy EVERY edited file** — missed `train_orchestrator.py` first pass → `pack_recheck=null` silently; run `alembic upgrade head` in container after a migration.
- **E2E:** (a) promote → OrgPack `created` + listed; (b) seeded `pack_fire_event` + `POST /completions/{id}/feedback {direction:-1}` → `pack_winrates` row `passes=0 fails=1 score=0`, `get_winrate=(0.0,1)`, `is_benched(0.0,5)=True`; (c) forced ebitda row dormant → HTTP train → `pack_recheck={revived:[ebitda-good-bad-ugly],rebound:2,checked:2}`, row→pending.

## 2026-06-24 — DONE Phase 6: scale packs (Tier-A fin yaml) — E2E PROVEN
Poured **7 Tier-A fin packs** as pure yaml data files in `backend/app/ai/packs/library/` (NO code — registry auto-loads every `*.yaml`): `unit_economics`, `returns_analysis` (IRR/MOIC/TVPI), `three_statement_integrity`, `variance_commentary`, `gl_reconciliation`, `nav_tie_out`, `portfolio_monitoring` → with shipped `ebitda_good_bad_ugly` = **8 packs**. Each = INVARIANT method_text (data-blind) + logical `required_inputs` (role/synonyms/optional) + output_spec/format + `eval_goldens: []`.
- **Deploy:** `docker cp *.yaml ca-app:/app/backend/app/ai/packs/library/` + **restart** (registry caches in-process → restart clears; NO migration, NO FE rebuild).
- **Tier B/C deferred** (additive): Tier B (comps/DCF/consensus) needs market-data feeds; Tier C (pptx/xlsx) folds into `create_artifact`. Map: `docs/PLAN_SMART_FIN_PACK.md`.
- **LANDMINE:** binder gates on NAME score with a role penalty — input role (measure/dimension) mismatching the column's profiled role drops 0.85→0.595 (<0.6 floor) → won't bind (live: variance-commentary skipped on EBITDA studio, its measure inputs hit dimension-typed cols). Honest gating; widen synonyms or fix column role.
- **E2E:** registry loads 8; all 7 new `bind_pack`=True on representative cols (unit-economics conf 1.0); router routes ("IRR/MOIC by deal"→returns-analysis, "reconcile gl vs subledger"→gl-reconciliation); live HTTP train of studio 5ac4444c autobound new packs → portfolio-monitoring `dormant` (partial), 6 non-matching skipped, existing untouched. **Domain Packs engine COMPLETE (Phases 0–6).**

## 2026-06-24 — DONE Packs review/approve UI (the missing surface) — E2E PROVEN
Autobound packs landed `pending`/`dormant` with no human surface; added a studio **Skills** tab.
- **Backend** (`app/routes/studio_packs.py`, +3 endpoints): `GET /studios/{id}/packs` (viewer+, rows + binding + missing + source + per-pack win-rate + `promotable`), `POST /studios/{id}/packs/{pack_id}/status` (editor+, body `{status: active|rejected|pending}`; **can't go active while `missing` non-empty** → 400 with the missing cols), plus the existing `/promote`. Hot-copy + restart.
- **FE** `components/studio/StudioSkills.vue` (new): one card per bound pack — name + status badge (active/pending/dormant/rejected) + source chip (library/authored/org-shared) + bind% + win-rate pill + binding `key→col` + dormant "needs column" hint + collapsible method. Actions (editor): Approve / Deactivate / Reject / Restore / Promote-to-org. `pages/studios/[id]/index.vue` (4 edits): import + `skills` tab (behavior group, gated `packsEnabled` ← `HYBRID_DOMAIN_PACKS.effective`) + section mount + `loadPacksFlag()` in onMounted. One `nuxt generate` + `docker cp dist`.
- **E2E:** `GET …/packs` → 3 rows (active user / pending ebitda / dormant portfolio-monitoring) w/ win-rate; approve pending→active OK; activate dormant → 400 "unbound inputs: company, revenue, period"; StudioSkills + `puzzle-piece` tab present in `dist/_nuxt/Jltb8j_1.js`, copied + served. Backups `.backups/20260624_packs_ui/`.

## 2026-06-24 — DONE Follow-up phases A–F (durability + Tier C/B + golden-minting + observability) — E2E PROVEN
Ran the pending plan A→F (sub-agents for authoring, I deployed/tested). Code pushed to **`github.com/raahulgupta07/rahulai-dash`** (branch `main`, orphan root commit — fork was shallow so bagofwords history dropped; secret-scan blocked a dummy `dapi…` doc token in `connectorDocs/cloud.ts:407`→placeholdered).
- **A — Bake durability:** the project's bake pattern is `docker commit ca-app cityagent-analytics:<tag>` (the `bi-pX` tags are the same) NOT a from-disk rebuild (running `ca-app` ≠ the `dash-*` compose). Committed → `:packs-complete` then (after F) `:packs-full`, both retagged `:dev`. Hot-copied backend + `docker cp`'d dist live in the container fs (not mounts) so commit captures them. A recreate from `:dev` now keeps everything.
- **B — Tier C output packs (4):** `pptx_author`/`xlsx_author`/`teaser_builder`/`deck_refresh` yaml. LANDMINE: binder only marks bound when ≥1 NON-optional input binds (`len(req)>0`) → output packs each carry ONE broad `subject` dimension (synonyms name/company/entity/…) + optional measure/period so they activate on almost any data. E2E: all 4 bind; router deck→pptx, excel→xlsx, teaser→teaser.
- **C — Generative golden-minting:** NEW `app/ai/packs/pack_goldens.py::mint_pack_goldens` (gated DOMAIN_PACKS+AUTO_EVALS), wired into orchestrator stage 3c. Per ACTIVE pack: small-LLM builds question+single-value SQL from method+binding+schema → runs read-only → `_derive_expected` → `TestCase` named `[pack] question` in the studio goldens suite (reuses auto_evals helpers). E2E: train → `pack_goldens_minted={created:4}` (2/pack), real `[pack]`-named goldens written.
- **D — Observability:** backend `GET /organization/pack-analytics` (fires/wins/losses/score per pack + status mix + dormant backlog; in `studio_packs.py`); FE `pages/settings/pack-analytics.vue` (Settings nav, gated `HYBRID_DOMAIN_PACKS`+`manage_settings`, totals strip+table+dormant backlog). E2E: endpoint returns ebitda fires=1/losses=1/win_rate=0, portfolio-monitoring dormant=1; page in bundle + served.
- **E — Upload dup-name fix:** backend `data_source_from_file.py` auto-suffixes a colliding DataSource name (` (2)`,` (3)`…) instead of 409 (org-unique `uq_data_sources_org_name`); FE `UploadSpreadsheetModal.vue` shows neutral "will be saved as 'X (2)'" hint + softens the 409. E2E: backend dedupe proven; hint in bundle.
- **F — Tier B packs (3, partial by design):** `comps_analysis`/`dcf_valuation`/`earnings_vs_consensus` yaml. Declare the EXTERNAL market-data fields as NON-optional → on normal data they bind **dormant** (`missing:[peer_ev_ebitda]/[free_cash_flow,wacc]/[actual_eps,consensus_eps]`) = the honest "needs feed" signal in the dormant backlog. **F1 (the market-data CONNECTOR) NOT built** — real vendor/infra work, deferred. E2E: 15 packs total; Tier-B all dormant on ebitda data.
- **Deploy:** B/F yaml = `docker cp *.yaml`+restart; C = backend hot-copy+restart; D backend hot-copy + D/E FE = 1 `nuxt generate`+`docker cp dist`. Final `docker commit`→`:packs-full`/`:dev`. Backups `.backups/20260624_packs_ui/` (+ git history). Registry now **15 packs** (ebitda + 7 Tier-A + 4 Tier-C + 3 Tier-B).
