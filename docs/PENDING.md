# Pending Plan — CityAgent Analytics hybrid

Branch: `hybrid-brain`. Build OUR OWN image always — never pull `bagofwords/bagofwords:latest`.

## Done
- ✅ Phase 0 (`950d2eb`) — branch, `reference/dash` blueprint, `hybrid_flags.py` (10 flags, all OFF).
- ✅ Phase 1 prep (`8bab6b7`) — `backend/scripts/seed_openrouter.py` (HTTP seed, OpenRouter custom provider).
- ✅ `.env` — Fernet key generated, ports `APP_PORT=3007` / `POSTGRES_PORT=5439` (collision-safe).
- ✅ `docker-compose.build.yaml` — builds app from THIS repo's Dockerfile (own image `cityagent-analytics:dev`).

## Inputs
- ✅ OpenRouter key (provided; **rotate after wiring** — was pasted in chat).
- ⏳ Onboarding admin email/password (created during first-run onboarding).
- ⏳ Model pick — default `anthropic/claude-sonnet-4` (analysis) + `openai/gpt-4o-mini` (router), or your choice.

---

## PENDING — infra (gating, NEW)
**P0.5 · Build own image** (replaces pulling upstream)
- DB image = **`pgvector/pgvector:pg18`** (all 3 composes; PG18 + pgvector preinstalled for Phase 8). Migration `v1e2c3t4o5r6` enables `vector` ext (PG-guarded). NOTE: a pre-existing pg16 `ca_postgres_data` volume is incompatible w/ PG18 — `docker volume rm` it before first boot (none yet = clean).
- [x] pre-pull bases w/ retry: `ubuntu:24.04` `rust:1-slim-bookworm` `pgvector/pgvector:pg18`.
- [x] `docker compose -f docker-compose.build.yaml build` — DONE (~20min, serialized for RAM). Image `cityagent-analytics:dev` (6.4GB).
- [x] `docker compose -f docker-compose.build.yaml up -d` — BOOTED (after PG18 `/var/lib/postgresql` mount fix).
- [x] verify `curl localhost:3007/health` → **200** ✅. PG 18.4, pgvector 0.8.2, head `v1e2c3t4o5r6`.
- [x] **Phase-A prep DONE** (boot-free): composes→pg18, `vector` migration (new head `v1e2c3t4o5r6`), `backend/scripts/loadtest_funnel.py` (100-conc gate instrument, reads `/api/funnel/stats`). AGE dropped (not PG18-ready) → Phase-8 graph = pgvector table + recursive CTE.

## PENDING — Phase 1 · OpenRouter
- [x] migrations auto-run on boot → head `v1e2c3t4o5r6`.
- [x] admin created via `POST /api/auth/register` → `admin@cityagent.io` / `CityAgent#2026` (auto org "Main Org").
- [x] seeded OpenRouter (`seed_openrouter.py` in-container) → custom provider + claude-sonnet-4 + gpt-4o-mini.
- [x] analysis model default = `anthropic/claude-sonnet-4` (`is_default=true`).
- [x] **smoke 1.4** — capability Q → `status=success`, real answer from claude-sonnet-4 via OpenRouter. ✅ (full native tool_use/SQL round-trip pending a connected data source.)

## PENDING — Phase 2 · Dual-schema + DB read-only  `HYBRID_DUAL_SCHEMA`
- [ ] alembic: create `analytics` + `staging` schemas.
- [ ] engine factory: read-only engine (`default_transaction_read_only=on`).
- [ ] engine factory: write engine `search_path=analytics,public`.
- [ ] `before_execute` listener blocks DDL/DML on `public`.
- [ ] wire `ai/code_execution` reads → RO engine.
- [ ] test: write-to-public REJECTED, read works.

## Phase 6 · Skills (self-service)  `HYBRID_SKILLS`  — SCAFFOLD DONE
- [x] `skills` table + model + migration `sk1l2l3s4t5b6` (scope personal/org/global, owner_user_id/organization_id, skill_md L2, status gate).
- [x] `app/ai/skills/loader.py` — `list_visible_skills` / `get_skill_body` (scope-visibility SQL, gated SKILLS) / `render_skill_catalog` (L1 block).
- [x] `load_skill` tool (`tools/implementations/load_skill.py` auto-registered) — returns SKILL.md as observation (L2 on demand; no dynamic tool mutation).
- [x] `SkillContextBuilder` + `SkillsSection` → primed into `view.static.skills`; agent_v2 injects L1 catalog into planner instructions.
- [x] 7 loader unit tests. Flag OFF default.
- [x] **"Save as skill"** distill-from-chat authoring — `app/services/skill_authoring.py` (`build_skill_prompt`/`parse_skill_draft` pure + `distill_skill_from_completion`: question+answer+best-effort proven-SQL → LLM → SKILL.md draft, inserts `scope='personal' status='draft'`, NEVER active) + `app/routes/skill.py` (`GET /skills`, `GET /skills/{id}`, `POST /skills/from-completion/{id}` [requires create_reports], `POST /skills/{id}/promote` [personal→org resets status=draft = admin must activate], `DELETE`). SKILL.md contract: `NAME:`/`DESCRIPTION:`/`---`/body. WIRED: `main.py` include_router (gated HYBRID_SKILLS — flag-off → list [], others 404). Nuxt `pages/skills.vue` + `components/SkillDetailsModal.vue` (reuse `useMyFetch`+`<MDC>`; NOT in nav; build-verify deferred to boot). 18 backend unit tests.
- [ ] L3 bundled assets (queries.sql/helpers.py via read_file) + pgvector top-K when >~50 skills (currently all-visible capped at 20). Nuxt `pages/skills/`. Org-share approval gate (reuse Instruction gate).

## PENDING — Phase 3 · Engineer capability  `HYBRID_ENGINEER_ASSETS`
- [ ] `ai/tools/implementations/build_data_asset.py` (CREATE VIEW analytics.*).
- [ ] register in `ai/registry.py` + metadata.
- [ ] built view → record as Instruction (Analyst discovers).
- [ ] prompt nudge: prefer `analytics.*`, route builds to Engineer.
- [ ] test: agent builds view → Analyst reuses.

## PENDING — Tier 0/1 cache + GATE
- [x] **Tier-① answer-cache**  `HYBRID_ANSWER_CACHE` — PG-resident (NO Redis dep): `app/models/answer_cache.py` + migration `aac1c2c3c4c5` (new single head, chains off `sk1l2l3s4t5b6`) + `app/ai/brain/answer_cache.py` (`serve_answer_cache` exact-hash + TTL-expiry + hit-count bump; `store_answer` upsert). WIRED: funnel ① `_try_answer_cache` → `serve_answer_cache`; agent_v2 finally-success → `store_answer` write-back (skips when `served_by` set; TTL env `HYBRID_ANSWER_CACHE_TTL_S` default 3600s). 15 unit tests. e2e pending boot.
- [x] `query_cache` table + capture/recall/curator  `HYBRID_QUERY_CACHE`.
- [x] **Tier-② param-swap serve** — `query_cache_serve.py` (`try_serve_proven_query` exact-match + live re-run + `render_answer_markdown`) wired pre-loop in `agent_v2._serve_from_reasoning_cache` (zero-LLM short-circuit, gated QUERY_CACHE+BRAIN_READ, default OFF). 14 unit tests green. e2e proof pending boot.
- [x] **Mode-2 literal-swap (fuzzy param-swap)** — `query_cache_serve.py` now has pure `swap_literals(stored_q, stored_sql, new_q)` + fires AFTER exact-miss: best fuzzy candidate (token-Jaccard >= `PARAM_SWAP_FLOOR=0.8`) whose ONLY question-diff is concrete literal(s) → swap the verbatim SQL literal(s) (case-preserving), re-confirm read-only, re-run live. Conservative: bails to None on structural diff / count-mismatch / literal-absent / ambiguous (literal twice in SQL) / non-read-only result. Exact path unchanged + first. 12 pure unit tests.
- [x] **cache-hit metric + perf endpoint** — `Completion.served_by`+`elapsed_ms` (migration `s1e2r3v4e5d6`); `GET /api/funnel/stats?days=N` (`app/routes/funnel.py`, pure `compute_funnel_stats`: by_tier counts, cache_hit_rate, p50/p95 + p50_cache/p50_cold). NULL served_by = agent_loop. agent_v2 stamps tier+elapsed on serve, elapsed in `finally` on loop success.
- [x] **funnel wiring: check ①②③ before agent loop** — `app/ai/brain/serving_funnel.py` `run_serving_funnel` (① answer-cache stub, ② reasoning-cache LIVE, ③ matview stub) called from `agent_v2._serve_from_reasoning_cache` pre-loop. ①③ = flag-gated extension points.
- [ ] **100-conc load test → record hit-rate, p50/p95. DECISION GATE.** ← needs boot; instrument now READY (`/api/funnel/stats`).

## PENDING — Slice 2 (after gate)
- Phase 4 brain-read `HYBRID_BRAIN_READ` · Phase 5 brain-write `HYBRID_DISTILLER`/`HYBRID_QUERY_CACHE` · Phase 6 skills `HYBRID_SKILLS`.

## PENDING — Slice 3
- [x] **Phase 7 DuckDB federation engine** `HYBRID_FEDERATION` — `app/ai/code_execution/duckdb_engine.py` (lazy `import duckdb` so module imports w/o dep; bounded `duckdb_connection()` ctx-mgr w/ `DUCKDB_MEMORY_LIMIT`/`DUCKDB_TEMP_DIR`/`DUCKDB_THREADS`; `attach_postgres` READ_ONLY, `register_dataframe`, `read_parquet`, `run_federated_sql` flag-gated→None; `_safe_identifier` guard; `snapshot_to_parquet` STUB=NotImplemented) + `freshness.py` (`FreshnessPolicy` live/cached/materialized + `resolve_policy`). `duckdb==1.4.2` already pinned (`requirements_versioned.txt:188`). 22 unit tests. NOT yet wired into code-exec path (standalone gated engine; agent code-exec hook + MinIO snapshot = follow-up, needs boot). Default OFF.
- Phase 8 AGE correlation `HYBRID_BRAIN_GRAPH`/`HYBRID_INSIGHT_DAEMON` (insight daemon DONE; AGE graph + non-text ingest pending).
- [ ] **cross-encoder rerank** — BLOCKED on pgvector (Phase 8). Can't build until embeddings/pgvector land. Deferred.

## Slice 4 — Phase 9 · Scale harden  — CODE DONE (boot-free; load test still ON HOLD)
- [x] **LLM concurrency semaphore** — `app/ai/llm/concurrency.py` (`get_llm_semaphore`/`llm_slot()`/`_reset_for_tests`), loop-aware lazy singleton, env `LLM_MAX_CONCURRENCY` (unset/≤0/invalid → None = NO limit = byte-identical to upstream). Wrapped the async stream call sites in `clients/openai_client.py` (`inference_stream`+`inference_stream_v2`) + `clients/openai_responses_client.py` — slot held for full stream duration. Sync path untouched. 6 unit tests. *(DocSensei-proven highest lever under load.)*
- [x] **DB pool env-tunable** — `settings/database.py` PG branch: `DB_POOL_SIZE`/`DB_MAX_OVERFLOW`/`DB_POOL_TIMEOUT`/`DB_POOL_RECYCLE`(-1 ok)/`DB_POOL_PRE_PING`, defaults = prior hardcoded values (20/20/30/1800/true). SQLite branch untouched. Helpers `_pool_int`/`_pool_bool`. 14 tests (CI; local skips — `fastapi_mail` absent).
- [x] **Quota guard** — `app/services/quota_guard.py`: gated `flags.QUOTAS` (`HYBRID_QUOTAS`, OFF→always allow), reuses EXISTING `UsagePolicy`/`UsageCounter` (no new table), pure `_evaluate` core, current-month window via reused `usage_policy_service.current_month_window()`, metrics `llm_tokens`/`data_queries`/`data_bytes`, fail-open on error, `quota_exceeded_error`→AppError 429. 13 tests. WIRED: `dependencies.enforce_org_quota()` called at top of `create_completion` (`metric="data_queries"`, no-op when flag OFF).
- [x] **OLTP/OLAP split** — already delivered Phase 2 (`analytics_engine.py` RO + write-guard sync engines, gated DUAL_SCHEMA). No new work.
- [x] **k8s HPA + CPU limits** — `k8s/chart/templates/hpa.yml` (autoscaling/v2, `{{- if .Values.autoscaling.enabled }}`, default OFF), `values.yaml` `autoscaling:` block (min2/max8/CPU70) + `resources.limits.cpu` + `replicaCount`, `deployment.yml` replicas conditional (HPA owns count when enabled). `k8s/SCALING.md` doc. `helm template` renders clean both modes.
- [x] **Leader-gating** — ALREADY EXISTS (`core/scheduler.py` file-lock `try_acquire_scheduler_leader` + cross-pod PG `claim_scheduled_run`). Daemons multi-replica-safe; HPA can scale freely. Documented in SCALING.md.
- [ ] **100-conc LOAD TEST → tune `LLM_MAX_CONCURRENCY`/`DB_POOL_*`, validate HPA + quota.** ← needs boot. ON HOLD.
- Total-conns landmine (SCALING.md): `replicas × workers × (DB_POOL_SIZE+DB_MAX_OVERFLOW)` ≤ PG `max_connections` (HPA-max worst case 8×4×40 = 1280 → use PgBouncer or cap pool).

## PENDING — Slice 4 · Phase 10 · Clean project (boot-needed for verify)
- Brand Dash→CityAgent Analytics · delete `reference/dash` · repoint k8s/CI image targets off `bagofwords/bagofwords` · flag cleanup.

---

## PENDING — research-derived (from `docs/RESEARCH_obsidian_second_brain.md`, 2026-06-18)
Verified deep-research on Obsidian/Claude 2nd-brain. Verdict: keep DB-backed model; steal retrieval recipe + data-type honesty. Tasks:

**Phase 4 (brain-read) — hybrid retrieval upgrade**
- [ ] cross-encoder rerank on `recall_proven_queries` candidates (currently exact-hash + token-Jaccard 0.6). Add vector + BM25 + rerank when pgvector lands (Phase 8). Same engine reused for skills/qbank top-K.
- [x] **refactor direct agent_v2 hook → `BrainContextBuilder`** — `sections/brain.py` (`ProvenQueriesSection`/`ProvenQueryItem`) + `builders/brain_context_builder.py`; primed in `context_hub.prime_static(query=)` → `view.static.brain`; agent_v2 inline recall hook REMOVED (reads the section). 10 unit tests (run in CI — local py3.9 can't import the context pkg). *Note:* active AI memories already flow via InstructionContextBuilder (source_type mixed, status='published' = the gate) — NOT duplicated into the brain builder. Folding top-K memories into one builder = optional future (currently two builders, no dup).

**Phase 5 (brain-write) — surgical write-back**
- [x] **DISTILLER 👎→pending memory** — `app/ai/brain/distiller.py` (`distill_and_store`: gather Q/bad-answer/correction → LLM one-shot → gated write via `InstructionService.create_instruction` source_type='ai' = draft/pending_approval build, NOT raw published; dedup by normalized text = surgical no-clobber). Hook: `completion_feedback_service._maybe_schedule_distill` + `_run_distill_from_feedback` (own session, resolves small model) fired on direction==-1 in both feedback branches. Flag `HYBRID_DISTILLER` OFF. 13 unit tests. e2e pending boot.
- [x] **surgical PATCH/append** — `distiller.py` pure `merge_memory_text(existing, new)`: identical/whitespace-only/already-covered → None (true skip); genuine new nuance → original preserved + only novel sentences appended (no dup). Step-5 dedup broadened to near-dup (normalized-equal OR substring); on match calls merge → merged text flows into the SAME approval-gated write (fresh pending build, NOT in-place mutation — reviewer supersedes old on approval). 12 unit tests (+25 incl. existing distiller, no regression).

**Phase 6 (skills) — progressive disclosure**
- [ ] L1/L2/L3 maps to Obsidian 3-level disclosure; atomic + concept-oriented note model = atomic Instructions/skills. Embed descriptions (pgvector) → top-K user-scoped when >~50 skills.

**Phase 8 (unstructured + graph) — DIFFERENTIATOR**
- [x] **insight daemon** `HYBRID_INSIGHT_DAEMON` — `app/services/brain_service.py`: `build_insight_prompt` (pure) · `gather_insight_signals` (recent active QueryCache questions) · `run_insight_scan_for_org` (mirrors distiller: distill ONE generalizable insight → surgical dedup → PENDING approval-gated Instruction, category="insight") · `run_insight_daemon_tick` (flag-gate → `try_acquire_scheduler_leader` → `claim_scheduled_run("hybrid_insight_scan")` → per-org cap 10). WIRED: `main.py` scheduler registers hourly `hybrid_insight_daemon` job ONLY when leader AND `HYBRID_INSIGHT_DAEMON`. Double leader-gated (job-reg + tick). 13 unit tests. Default OFF.
- [ ] **non-text semantic ingest** (image-caption / audio-transcribe / PDF-extract / CSV-parse) — the gap NO 2025-26 Obsidian setup solves. Reuse connector + vision lane (cf. DocSensei vision-once + page-image). Unstructured → pgvector + AGE entity graph. Be EXPLICIT which modalities are semantically indexed vs only referenced (no overstating — PixelRAG-rejection discipline).

**Optional integration (not a phase)**
- [ ] Obsidian MCP interop — expose CityAgent memories/skills over an MCP server (dash already has MCP) so a user's Obsidian vault can read/write our brain. Evaluate only if user demand; not core.

---
Full design: `docs/ARCHITECTURE.html`. Research input: `docs/RESEARCH_obsidian_second_brain.md`.
