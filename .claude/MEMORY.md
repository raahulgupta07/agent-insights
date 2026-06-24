# MEMORY — CityAgent Analytics (expert quick-recall)

Fast orientation. Full map = `CLAUDE.md` (root). Read it before touching core.

## What it is
Single-project agentic-analytics platform. **Fork of bagofwords (bow), rebranded Dash** on branch `hybrid-brain`.
Stack: FastAPI + Nuxt 3 (Vue). Dash chassis (AgentV2 plan/execute/reflect loop = SINGLE analyst
"City Agent Analyst", Planner+Coder+Judge, NOT a multi-agent team) + native ports of:
- **dash patterns** — dual-schema, Engineer view-builder, DB-level read-only. Agno NOT run; `reference/dash/` = blueprint only.
- **Karpathy 2nd-Brain** — learned memories, reasoning-cache, self-distill, insight daemon, entity/correlation graph. Default-OFF, leader-gated.
- **Self-service Skills** — Claude-Code-style SKILL.md + progressive disclosure + slash-invoke.
- **DuckDB federation** — live↔stored cross-source query.
Version `VERSION`=0.0.412. Design `docs/ARCHITECTURE.html`, tasks `docs/PENDING.md`, log `docs/PROGRESS.md`, plans `docs/PLAN_*.md`.

## HARD RULES (do not violate)
1. **NEVER pull `bagofwords/bagofwords:latest`.** Build own image `cityagent-analytics:dev` from this repo's Dockerfile. All 3 composes build-from-source.
2. **Pre-pull base images with retry** (Docker Hub `registry EOF` flake): `ubuntu:24.04`, `rust:1-slim-bookworm`, `pgvector/pgvector:pg18`, AND `docker/dockerfile:1.7` (the `# syntax` frontend — flake here fails build in ~2s, stale tag silently re-runs OLD image). `scripts/build.sh` auto-pre-pulls.
3. **Touch Dash core MINIMALLY** — new files/hook points over rewrites (rebase tax). Core touch-points: `context_hub.py`, `context_view.py`, `agent_v2.py`, `serving_funnel.py`, `main.py`.
4. **Everything new is flag-gated** (`app/settings/hybrid_flags.py`, env `HYBRID_*`, default OFF) — fresh deploy == upstream Dash until flag on.
5. **Everything learned is gated** — memories/skills/correlations land `status='pending'`, live only after approval. Reuse Dash Instruction approval, don't build a new gate. Approved-only invariant: pending rows auto-invisible to agent.

## LLM = OpenRouter ONLY
No Agno → Dash keeps `openai 1.107`. Configured as Dash `custom` provider (`base_url=https://openrouter.ai/api/v1`, per-org DB row, Fernet-encrypted key). Tool-capable models only. Defaults: `anthropic/claude-sonnet-4` (UI "Dash Pro", is_default) + `openai/gpt-4o-mini` (UI "Dash Lite"). Seed via `backend/scripts/seed_openrouter.py`. UI rename = `llm_models.name` only; BLANK reinstall reverts until seed script updated.

## Build & run
```
bash scripts/build.sh                 # pre-pull bases + build cityagent-base:dev ONCE + app image
bash scripts/build.sh --rebuild-base  # when LibreOffice/ODBC/chromium deps change
docker compose -f docker-compose.build.yaml up -d
curl localhost:3007/health
```
Ports: **APP=3007** (internal 3000), **POSTGRES=5439** (`.env`). DB = **PG18 + pgvector** (AGE dropped, not PG18-ready → graph = pgvector table + recursive CTE).
**Fast-build refactor (~29×):** heavy apt → `Dockerfile.base` (`cityagent-base:dev`, built once); app `Dockerfile` = FROM base + BuildKit cache mounts + vendored deps (`vendor/`, no build-download). Code-change rebuild = 40s–2min. `Dockerfile.orig` = pre-refactor backup.
First admin: `POST /api/auth/register` (first uninvited user auto-creates org + admin). Dev: `admin@cityagent.io` / `CityAgent#2026` (org "Main Org"). `.local` TLD rejected by email validator.

## Dev lanes (FE)
- **:3007** = baked prod static bundle (`nuxt generate`), NO hot-reload → `.vue`/config change needs REBUILD.
- **:3000** = `cd frontend && DASH_BACKEND=127.0.0.1:3007 yarn dev` (hot-reload, proxies /api → :3007).
- NEVER run `yarn generate`/`build` while `yarn dev` live in same dir (corrupts `.nuxt` → blank app).
- New `components/**/*.vue` mid-session → NOT auto-imported until dev server RESTART (renders blank silently).
- FE API calls use `useMyFetch` (auto Authorization + X-Organization-Id, prepends `/api`) → use BARE paths (`/knowledge/queries`, double-prefix 404s).
- Backend `.py` IS hot-iterable: `docker cp <f> ca-app:/app/backend/... && docker exec ca-app /opt/venv/bin/python -m py_compile <f> && docker restart ca-app` (restart keeps cp'd files + flag env; `--force-recreate` REVERTS to image).

## Feature flags (`hybrid_flags.py`; compose `${HYBRID_X:-0}`; new flag needs BOTH `.env` AND compose env or silent-OFF)
`DUAL_SCHEMA · ENGINEER_ASSETS · ANSWER_CACHE · BRAIN_READ · DISTILLER · QUERY_CACHE · SKILLS · FEDERATION · BRAIN_GRAPH · INSIGHT_DAEMON · QUOTAS · SEMANTIC_LAYER · METRICS_CATALOG · STUDIOS · GOVERNANCE · CODE_BANK · MEMORY_LOOP · EVAL_HARNESS · JOIN_GRAPH · DOC_KNOWLEDGE`. Access `from app.settings.hybrid_flags import flags`. Env daemon knobs: `STUDIO_LEARN_DAEMON_ENABLED`, `EVAL_SCHEDULE_ENABLED`, `JOIN_MINE_ENABLED`.

## Migrations
Single alembic head. Chain (fork→now): `…→ v1e2c3t4o5r6 (vector ext) → k1nowl2edge3 → m2etrics3cat4 → q3uery4lib5 → b4rain5graph6 → sk2frontmttr1 → sk3skillfiles1 → studio1base1 → studio2harness1 → kepler1gov1 → kepler2cb1 → joingraph1 → docknow1`. **HEAD = `docknow1`**. Pre-fork true head was `d6d9a78b7b4a` (tuple down_revisions in merge migrations fake multiple heads). Guard PG-only DDL: `op.get_bind().dialect.name == "postgresql"`.

## Major subsystems (all flag-gated, approval-gated, additive)
- **Knowledge Layer** (`/knowledge`, router `app/routes/knowledge.py` prefix `/api/knowledge`): tabs Semantic | Metrics | Queries | Assets | Docs | Joins | Review. Models `semantic_table/metric_definition/query_library/knowledge_doc/table_edge`. AI-suggest `POST /knowledge/ai-suggest/{ds}`. Self-learning proposer fires after distiller on 👎. **Semantic auto-seeds skeletons; rest fill from AI-suggest/distiller/QUERY_CACHE — empty tabs = by design, NOT bug.** Card-grid UI (Dashboards-style). LANDMINE: literal routes (`/assets`, `/docs`, `/joins`) BEFORE catch-all `/{kind}/{id}/approve`.
- **Studios** (`/studios`, `flags.STUDIOS`): NotebookLM-style shareable container WRAPPING Data Agents (does NOT replace `/agents`). Tables `studios/studio_*`. `Report.studio_id` nullable FK = chat inside studio. Auto-born (avatar/voice/summary on create; instructions/examples on source-pin). ST8 self-improving (rules/examples → pending; only avatar/voice/summary/suggestedQs live). Access `resolve_studio_access` (MUST await). Left-rail workspace UI.
- **Serving funnel** ①answer-cache → ②query-cache(exact+param-swap) → ③matview → ④agent. `serving_funnel.py`.
- **Brain**: distiller (👎→memory), insight daemon, brain_graph (pgvector+recursive CTE), reasoning/query/code cache, doc RAG = **PG full-text search NOT pgvector** (NO embedder in image), join miner = **regex NOT sqlglot** (NO sqlglot in image — do NOT add either dep).
- **Skills** (Claude-Code parity): `app/ai/skills/{frontmatter,tool_scope,invocation,files}.py`, per-skill allowed-tools narrows catalog, L3 bundled `skill_files`, slash `/skill args` in PromptBoxV2.
- **Connectors**: ALL un-gated (EE bypass, user-authorized self-host fork) — `data_source_registry.py` requires_license=None, `ee/license.py` ENTERPRISE_DATASOURCES=[]. Restore lists to revert.

## Conventions
- New tool → `app/ai/tools/implementations/*.py` (auto-registered). Schema → `app/ai/tools/schemas/`.
- New context → `app/ai/context/builders/` + register in `context_hub.py` AND append in `agent_v2.py` (builder alone primes cache but NEVER injects — the agent_v2 render+append is required).
- Bounded context: top-K rank via token-Jaccard (`query_cache_store` `normalize_question/_tokens/_jaccard`), env `HYBRID_*_TOP_K`, fail-safe to full list.
- Tests: `backend/tests/unit/` (mocked, CI) / `@pytest.mark.e2e`/`.ai` (DB/LLM). Local py3.9 can't import `database.py` (fastapi_mail) → some guarded-skip locally, run in CI.
- Agent-owned PG schemas: `analytics` (Engineer views), `staging` (ingest). External conns read-only.
- No git workflow for ad-hoc snapshots → `bash scripts/backup.sh <label> <files…>` → `.backups/<ts>_<label>/`.

## Top landmines
- Dash error class = `app.errors.app_error.AppError(error_code, message, status_code=)` (NOT `app.errors.AppError`).
- **rtk mangles `docker logs`/`grep`** → use `rtk proxy docker logs <c>`; read large files with Read tool. `docker cp` source must be ABSOLUTE under rtk. `docker exec` needs `-i` for heredoc/piped psql (else silent no-op exit 0).
- PG18 data dir = `/var/lib/postgresql` (NOT `/data`) → mount parent or boot unhealthy.
- `--target` cache ≠ compose cache (compose re-runs whole Dockerfile).
- babel vendored PINNED 7.26.4 (classic runtime) — babel 8 injects `import` into `<script type="text/babel">` → artifact render "Cannot use import statement outside a module" blank dashboard. Do NOT unpin.
- Write guard checks only WRITE-TARGET schema, not every referenced schema.
- SQLAlchemy JSON in-place reassign not dirty-flagged → `flag_modified(obj, "col")`. Studio routes hand-built `_serialize` (new col needs the key added).
- Report page: TDZ blank (immediate watcher reads later const); SPA-nav blank (need `definePageMeta({key, pageTransition:false})`); null-report deref (gate spinner on `report` itself). blank+refresh-works+NO-error == transition stranding; blank+error == render-time null deref.
- Auto-title hook lives in BOTH completion paths (`_create_completion_traced` + `create_completion_stream` — live UI uses stream). Lazy report: `/reports/new` no DB row until first submit.
- API: org-scoped calls need header `X-Organization-Id` (from `GET /api/organizations`); login `POST /api/auth/jwt/login` form-encoded username/password; report create uses `title` + `data_sources` (NOT name/data_source_ids — silently ignored); completions thin body → poll `GET /reports/{id}/completions`.
- Still upstream (Phase 10 cleanup): `k8s/chart/values.yaml` repo + `.github/workflows/docker-image*.yml` push targets.

## i18n
3 locales: `en`(default)/`es`/`he`(RTL ref). Catalogs `locales/{en,es,he}.json` must match shape. Resolution: X-Locale header > personal `localStorage.dash.locale` > org `OrganizationSettings.config["locale"]` > system default. See `docs/design/i18n.md`, `AGENTS.md`.

## 2026-06-20 — rename + UI unification (see CLAUDE.md for full detail)
- **bow/bagofwords → dash/Dash, platform-wide.** Env prefix now `DASH_*` (74 vars). Config = `dash_config.py` /
  class `DashConfig` / `settings.dash_config` / `DASH_CONFIG_PATH` / `dash-config*.yaml`. **DB now `dash`/`dash`/
  `dashpassword`** — a DB/user rename means the OLD pg volume is incompatible → `compose down -v` + fresh `up`
  re-inits (wipes dev data, reseed admin + OpenRouter). MCP `ui://dash/*`, server name `"dash"`, echarts theme
  `'dash'`, `data-dash-*`. k8s image now `cityagent-analytics`.
- **KEPT (wire/persistence — do NOT rename):** API-key prefixes `bow_`/`bow_oauth_`, `X-BOW-*` webhook headers, DB
  column `bow_version`, `.bowignore` format, Office.js IDs in `routes/excel.py`, "NEVER pull bagofwords/bagofwords"
  warnings, real `bagofwords.com/.io` URLs.
- **Canonical list-page** (gold ref `pages/dashboards/index.vue`) across all 13 pages: serif H1 + subtitle + ONE
  clay `#C2683F` primary top-right, tabs-above-search, clay-tile serif empty states, NO blue, NO emoji, no duplicate
  primary. Tokens: paper `#F5F4EE`, surface `#FBFAF6`, border `#E7E5DD`, tile `#F4F1EA`, clay `#C2683F`/hover
  `#A8542F`, ink `#1f2328`, muted `#6b6b6b`, faint `#9a958c`.
- **Nav (`components/nav/TopNav.vue`):** Build = Data Agents · Knowledge · Instructions · Queries · Skills;
  Manage = Monitoring · Evals · MCP Server. Mockups: `docs/design/*_mockup.html`.
- Onboarding banners removed (`layouts/default.vue` showGlobalOnboardingBanner=false; `pages/index.vue` connect-LLM
  card v-if=false). Every FE `.vue` change needs an image REBUILD (baked); batch tweaks then one rebuild.
