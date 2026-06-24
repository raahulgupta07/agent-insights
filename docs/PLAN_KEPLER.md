# PLAN — Kepler-style improvements (PHASED, feasibility-audited)

Audited against real code (2026-06-19). Every phase reuses existing plumbing; the only
genuine new component is the code_cache (Phase 2, a clone of the SQL query_cache). All flags
default OFF → byte-identical until switched on. User gates EACH phase before the next.

Order is feasibility-driven, not feature-driven: populate the empty layers FIRST (that is the
real problem — the machinery exists, the shelves are empty), then trust, then accuracy, then
the learn-loop, then evals, then defer the heavy/low-value ones.

Dev anchors: app :3007 (ca-app), PG :5439. FE = baked nuxt-generate → any .vue change needs an
image rebuild. Backend hot-iterate via `docker cp` + `py_compile`. `rtk proxy` for docker/grep.

```
PHASE 0  Populate + bulk-curate      zero build   ← DONE 2026-06-19 (Financial Market Agent: 8 sem + 6 metrics approved)
PHASE 1  Governance (owner/fresh/PII) small        ← DONE 2026-06-19 (HYBRID_GOVERNANCE, live+baked)
PHASE 2  Code memory (code_cache)     1 real build ← DONE 2026-06-19 (HYBRID_CODE_BANK, capture+recall verified)
PHASE 3  👍 memory loop               small        ← DONE 2026-06-19 (HYBRID_MEMORY_LOOP, baked; +compose-env fix for GOV/CODE/MEM)
PHASE 4  Eval canary (result-set)     medium       ← DONE 2026-06-19 (HYBRID_EVAL_HARNESS / EVAL_SCHEDULE_ENABLED, baked+verified)
PHASE 5  Docs RAG (PG-FTS)            medium       ← DONE 2026-06-19 (HYBRID_DOC_KNOWLEDGE, baked+verified; VECTORLESS PG-FTS not pgvector — no embedder in image)
PHASE 6  Join graph                   heavy/low    ← DONE 2026-06-19 (HYBRID_JOIN_GRAPH / JOIN_MINE_ENABLED, baked+verified)
```

---

## PHASE 0 — Populate + bulk-curate the layers  (ZERO build)

**Why first:** audit confirmed the knowledge layer, bounded-context, query-cache and proposer all
WORK — they're just empty (every table DRAFT, no descriptions, 0 metrics). Bounded context only
helps if there's curated content to bound. This is the actual gap, and it needs no code.

**Steps:**
1. Run `POST /api/knowledge/ai-suggest/{data_source_id}` per data source (VERIFIED e2e:
   schema → LLM → pending semantic + metric rows via `knowledge_proposer.propose_knowledge_from_schema`).
2. Bulk-review the pending rows (`GET /api/knowledge/pending` → `/{kind}/{id}/approve`).
3. Set `HYBRID_SEMANTIC_LAYER=1` + `HYBRID_METRICS_CATALOG=1` (already on in dev).
4. Smoke: ask 5 questions, confirm grounding chip shows "Grounded on N of M".

**Build:** none (maybe a bulk "approve all visible" button — tiny FE).
**Gate:** layers populated for ≥1 real data source; answers cite curated tables.
**Risk:** none — additive, approval-gated, reversible (reject).

---

## PHASE 1 — Governance: owner · freshness · PII  (small, trust)

**Reuse:** `last_synced_at` already set on sync (read via Connection); PATCH handler uses an explicit
allow-list (`routes/knowledge.py` ~L205-213) — add fields the same way.

**Build:**
- Migration: `semantic_tables` += `owner`, `pii`, `freshness_sla_hours`, `last_refreshed_at`;
  `semantic_columns` += `pii`, `sensitivity`.
- Patch schema + 4-line blocks per field in the table/column PATCH handlers.
- `semantic_context_builder.py`: one governance footer line per injected table; planner rule
  "never emit PII columns unless asked + authorized; always state data-as-of".
- `GET /api/knowledge/governance/{ds}` rollup (stale/PII/unowned counts).
- FE: card chips (owner avatar · freshness dot · PII pill) + summary strip + answer "Data as of X / 🔒".

**Flag:** `HYBRID_GOVERNANCE`. **Gate:** footer appears; PII rule honored in a probe question; chips render.
**Risk:** low — read-only metadata + one prompt rule. PII auto-hint is a *pending* proposal, never auto-enforced.

---

## PHASE 2 — Code memory: code_cache  (THE one real build, accuracy)

**Reuse:** clone `app/ai/brain/query_cache_store.py` (normalize_question + token-Jaccard top-K) and the
`query_context_builder` injection pattern. Generated python is persisted at `Step.code`; success via
`Step.status='success'`; quality via `Completion.response_score`.

**Build:**
- New model/table `code_cache` { org, data_source, question_norm, question, code TEXT, step_id,
  uses INT, last_used, status }.
- Capture: on a successful step (status='success', positive/neutral score), upsert the `Step.code`
  keyed to normalized question. (Mirror how query_cache captures SQL.)
- New `code_context_builder` (or extend the existing one): top-K closest past code → inject
  `### proven approaches` block (cap chars; bounded, respects top-K). Wire into `agent_v2.py` assembly.
- Optional FE: a "proven code" chip on the answer + a Knowledge → Code tab to review/curate.

**Flag:** `HYBRID_CODE_BANK`. **Gate:** ask a repeat-shaped question → injected code block present →
faster/consistent answer; A/B vs flag-off shows no regression on the eval suite.
**Risk:** medium — it's the only new store, but a structural copy of an existing one. Retrieval is
token-Jaccard (no embeddings needed). Never executes cached code blindly — it's *context*, the Coder
still authors fresh.

---

## PHASE 3 — 👍 memory loop  (small, compounds)

**Reuse:** `knowledge_proposer` + `distiller` already fire on 👎 (gated `DISTILLER`, write pending,
never overwrite approved) via `completion_feedback_service` (~L795-893). 👍 is captured
(`CompletionFeedback.direction==1`) but today only drafts evals.

**Build:**
- On `direction==1`: also call the proposer to draft a pending QueryLibraryItem / code_cache entry
  (the emitted SQL/python that the user just blessed) + a semantic-description draft if the question hit
  an undescribed table. Same functions, new call site.
- Inline "✏️ correct this" on an answer → captures a note → drafts a pending instruction/semantic edit
  with chat provenance.
- Surface provenance ("from chat Jun 18: <question>") in the Review tab + Promote button (gate exists).

**Flag:** `HYBRID_MEMORY_LOOP`. **Gate:** 👍 an answer → a pending row appears in Review with provenance.
**Risk:** low — reuses the proposer; everything lands pending behind the review gate.

**DONE 2026-06-19 (live, baked, verified).** Built by 3 disjoint-file sub-agents + integration.
- Flag `MEMORY_LOOP` (`hybrid_flags.py` + snapshot). New proposer `propose_from_positive_completion`
  + helper `_propose_query_library` (`knowledge_proposer.py`, owner marker `MEMORY_OWNER='ai-memory-loop'`,
  approval-safe UPSERT, dedup, never-clobber-approved). On 👍 (direction==1): promotes the blessed
  question's captured `QueryCache` SQL (read-only, any cache status, highest hit_count) → pending
  `QueryLibraryItem` (source='chat', tags=[from-chat,blessed]); + blesses the matching Phase-2 `CodeCache`
  row (hit_count++/last_used). Returns `{queries:[],code:[]}`. NO LLM call, NO new table/migration.
- Feedback wiring `completion_feedback_service.py`: `_maybe_schedule_propose_from_positive` (gate
  direction==1 + MEMORY_LOOP) + `_run_propose_from_positive` (mirrors the 👎 `_run_propose_knowledge`
  fresh-session/reload-by-PK/strong-ref discipline; strong-ref set `_propose_positive_tasks`); call site
  added in BOTH the create + update feedback branches, right after the existing eval-draft call.
- Provenance surfacing: `/api/knowledge/pending` enriched per-proposal with `source`/`owner`/`provenance`
  ("👍 from chat" | "👎 distilled" | "from chat"); `ReviewTab.vue` renders a neutral gray provenance pill.
- Verified in-container: flag+imports+methods present; `_propose_query_library` write→pending/chat/
  ai-memory-loop/tags + dedup; full `propose_from_positive_completion` against a REAL chinook completion
  + seeded QueryCache → created a pending library item (E2E_OK). Baked into `cityagent-analytics:dev`,
  HTTP 200.
- **LANDMINE FIXED:** `docker-compose.build.yaml` env list was MISSING `HYBRID_GOVERNANCE`/`CODE_BANK`/
  `MEMORY_LOOP` → those Phase-1/2/3 flags were NEVER injected into the baked prod container (only ever
  live via hot-test `os.environ`). Added all 3 as `${HYBRID_X:-0}`. Now `GOV=1 CODE=1 MEM=1` confirmed in
  the running container env. Any new HYBRID_ flag MUST be added to BOTH `.env` AND the compose `environment:`
  block, else it silently stays OFF in prod.

---

## PHASE 4 — Eval canary: result-set goldens  (medium, locks trust)  — DONE 2026-06-19

**DONE 2026-06-19** (live :3007, baked into cityagent-analytics:dev, flags `HYBRID_EVAL_HARNESS=1`
`EVAL_SCHEDULE_ENABLED=1`; backup `.backups/20260619_221251_phase4-evalcanary`):
- VERIFY-BEFORE-BUILD resolved: audit said PARTIAL, now CONFIRMED FULL. `TestRunService.
  create_and_execute_background(db, org, current_user, case_ids=None, suite_id=None,
  trigger_reason='manual', build_id=None)` truly invokes the analyst (creates run + stub report +
  `CompletionService.create_completion(background=True)` → AgentV2). `build_final_snapshot(db, report_id)`
  (2 args only) persists produced data. Live-probed: produced rows live at `result_json["data"]["rows"]`
  (list of full row dicts); columns at `data["columns"]`.
- `ResultSetRule{golden_data,golden_columns,tolerance,order_insensitive,key_columns,phase,turn}` added to
  ExpectationsSpec Rule union (NOT in UI catalog — generated, not picked). Snapshot now captures
  `create_data["rows"]` via module helper `_extract_result_rows` (tries data.rows/records/rows/.../preview,
  zips list-rows with columns, caps 200, JSON-safe). Matcher branch in `evaluate_final` gated on
  `flags.EVAL_HARNESS`: `_compare_result_sets` (relative numeric tol `abs(a-b)<=tol*max(1,|b|)`, non-numeric
  strip-equal, column-set check, multiset/positional/key_columns, names first differing cell). Disabled/empty
  golden → skipped (never fails). rule_result via existing `RuleResult(ok,status,message,actual,evidence)`
  (evidence=None — Literal has no result_set; diagnostics in actual).
- NEW `app/services/eval_harness.py`: `make_result_set_rule_from_snapshot`, `save_completion_as_golden`
  (find/create suite "Blessed goldens", TestCase auto_generated+source_completion_id+result_set rule,
  DS ids via Report.data_sources, question via `gather_feedback_context`, dedup by source_completion_id),
  `enqueue_context_change_run` (find org goldens by DS → create_and_execute_background trigger='context_change'),
  `run_scheduled_evals` (own session, gated `EVAL_SCHEDULE_ENABLED`, per-org, resolves a Membership user since
  stub-report needs non-None user, → trigger='schedule' + detect_regressions), `detect_regressions` (diff vs
  last status='success' run with same suite_ids, pass→fail/error, merge into `run.summary_json['regressions']`
  + flag_modified). NO notifications table (dash ≠ citypharma) — regressions surface via summary_json only.
- WIRING: `main.py` leader block → `scheduler.register_eval_jobs(scheduler)` (nightly cron hour=3, gated
  EVAL_SCHEDULE_ENABLED, id='phase4_nightly_evals'). `knowledge.py approve_knowledge` → fail-soft
  `enqueue_context_change_run` after commit (gated EVAL_HARNESS, guard ds_id). `completion_feedback_service`
  → `_maybe_schedule_save_golden`/`_run_save_golden` on 👍 (mirrors Phase-3 positive hook, strong-ref set
  `_save_golden_tasks`, both create+update branches). `routes/test.py` → POST /tests/golden-from-completion,
  GET /tests/regressions. FE `pages/agents/[id]/evals.vue` → new "Goldens" tab: regression banner (amber,
  dismissible, NOT blue), goldens table (auto_generated + result_set filter, GOLDEN gray pill, rows×cols×tol),
  hand-rolled pass-rate SVG sparkline (gray). Reuses `useMyFetch`.
- VERIFIED LIVE (hot-copy, flags forced on): imports OK; comparator exact/tol/drift; snapshot captured 24 real
  rows from report 50c97e90 (Country/TotalRevenue); save_completion_as_golden made golden e727e46a (24 rows,
  linked, dedup same-id); self-match pass + drift caught (row 22); enqueue_context_change_run created run
  977b5933 trigger=context_change AND fired the analyst ("Starting create_completion v2"). Gate MET.
- LANDMINE: snapshot row path is `result_json["data"]["rows"]` (probe before trusting); golden case `name`
  can show the question doubled (gather_feedback_context concat) — cosmetic, truncated to 120. Both new flags
  added to `.env` AND compose `environment:` (the Phase-3 silent-OFF landmine). EVAL_SCHEDULE_ENABLED has NO
  HYBRID_ prefix (matches plan). `create_and_execute_background` REQUIRES non-None user (stub report) — scheduler
  resolves a Membership user per org.

**Reuse:** TestSuite/Case/Run/Result models; `trigger_reason` already supports
`'context_change'|'schedule'`; `auto_generated` + `source_completion_id`; scheduler = APScheduler +
flock leader election (`app/core/scheduler.py`). Output is a DataFrame → compare result-set, NOT SQL.

**Build:**
- Golden = expected result-set snapshot (from a 👍 answer's produced `data`). New rule
  `ResultSetRule { golden_data, tolerance, order_insensitive }` in ExpectationsSpec + a matcher in
  `test_evaluation_service.py` (compare produced DataFrame vs golden; Judge only for "different code,
  same answer").
- Nightly run: `scheduler.add_job` → TestRun `trigger_reason='schedule'`.
- Context-change hook (soft "blocker" = no hook exists): at the end of `/{kind}/{id}/approve`, enqueue a
  TestRun `trigger_reason='context_change'` for that DS's suite. One added call.
- Regression: compare run vs last green → newly-failing > 0 → `dash_notifications` + dashboard banner.
- FE: Evals page — goldens table, pass-rate sparkline, regression banner; "save as golden" on 👍.

**Flag:** `HYBRID_EVAL_HARNESS` (matcher+UI), `EVAL_SCHEDULE_ENABLED` (daemon).
**Gate:** approve a knowledge change → context_change run fires → a moved number shows as a regression.
**Risk:** medium — the matcher is new; runner/scheduler are proven. Confirm `run_eval` actually invokes
the analyst + stores produced data (audit: PARTIAL — verify the invoke path before building the matcher).

---

## PHASE 5 — Docs RAG  — DONE 2026-06-19 (live, baked, verified)

**Built by 4 disjoint-file sub-agents (1 foundation + 4 wave-2) + integration.** Flag `HYBRID_DOC_KNOWLEDGE`
(default OFF, in `.env` AND compose env). **VECTORLESS — PG full-text search, NOT pgvector.** Decision: the
phase header below assumed pgvector, but recon found NO embedding client anywhere in the image (brain_graph's
vector column is dead DDL, never populated) and adding one (sentence-transformers / OpenRouter embeddings) is
exactly the offline-vendor / registry-EOF landmine. PG-FTS (`to_tsvector`/`plainto_tsquery`+`ts_rank`) is the
proven sibling-Aria stance, zero new deps, and satisfies the gate. pgvector upgrade = later flag-gated follow-up.
- **Models + migration:** `app/models/knowledge_doc.py` — `KnowledgeDoc` (table `knowledge_docs`: title, source,
  body, url, content_hash, status pending→approved gate, unique on org+ds+content_hash) + `KnowledgeDocChunk`
  (table `knowledge_doc_chunks`: doc_id FK, chunk_index, text). Migration `docknow1` (down `joingraph1`, now HEAD)
  creates both + a **Postgres-only GIN functional index** `ix_knowledge_doc_chunks_fts` on `to_tsvector('english',text)`
  (dialect-guarded so SQLite dev still migrates). Approval invariant: only chunks of a `status=='approved'` parent surface.
- **Ingest/retrieval** `app/ai/knowledge/docs_index.py` — `_chunk_text` (paragraph→sentence→hard-slice, ~1000 chars,
  cap 200), `_content_hash` (sha256), `ingest_doc(db,*,organization,title,body,source,data_source_id,url)` UPSERT on
  the unique key (re-chunk on change, status back to pending), `search_docs(db,*,organization,query,data_source_id,k)`
  RAW-SQL FTS (`ts_rank` desc, approved+non-deleted parent, ds OR org-null, omits ds clause when None). All fail-soft → [].
- **Context** `sections/docs.py` (`DocsSection` tag `docs`, `### Company definitions` block, 4-item / 600-char cap,
  xml_escape) + `builders/docs_context_builder.py` (`DocsContextBuilder`, flag-gated, QUERY-DRIVEN — empty when off or
  query-less, never raises). Wired into `context_hub.py` (gather slot #13 appended LAST + `render_docs_section`) +
  `agent_v2.py` (append after metrics block, gated `flags.DOC_KNOWLEDGE`). NO daemon — ingest is sync, FTS index auto-maintained.
- **API** `routes/knowledge.py`: `GET /knowledge/docs?data_source_id=` (list+stats), `POST /knowledge/docs`
  (paste/ingest), `POST /knowledge/docs/search` (debug), and `kind='doc'` added to the `/{kind}/{id}/approve|reject`
  catch-all (`_KIND_MODEL['doc']=KnowledgeDoc`). All flag-gated, placed BEFORE the catch-all.
- **FE** `pages/knowledge/index.vue`: "Docs" tab (between Joins/Assets), inline Add-doc paste form (title+body), doc
  list with source/chunks meta + status pill + pending Approve/Reject (neutral, no blue), empty state.
- **VERIFIED E2E** (Music Store DS, flag on): ingest "active customer definition" → 1 chunk pending → builder empty
  (gate proven) → approve → `search_docs` returns it → builder renders `### Company definitions`. Live HTTP
  `GET /api/knowledge/docs` (header `X-Organization-Id`) returns the approved doc. Migration head `docknow1`. FE baked (`CmUcPnPa.js`).

**LANDMINES:** VECTORLESS by design — do NOT "fix" by adding pgvector/an embedder (no client in image; that's the
offline-download landmine); FTS GIN index is Postgres-only (dialect-guarded in migration); gather tuple in context_hub
must stay positional (docs appended LAST, 13=13); docs builder is QUERY-DRIVEN (needs the question — empty otherwise),
unlike join_graph; org header for the route is `X-Organization-Id` (not X-Org-Id); `docker restart` keeps create-time
env so the flag reads OFF until `--force-recreate` (which reverts hot-copied .py → rebuild image first); FE Docs tab is
baked → image rebuild. Session-factory import is `app.settings.database.create_async_session_factory`.

### (original spec below — superseded: built PG-FTS not pgvector)
**Reuse:** pgvector IS already installed here (not FTS) → use it, don't build FTS. File-upload lane
exists (`routes/file.py /files`). Pattern proven in sibling Aria project.

**Build:** `knowledge_docs` table + pgvector embedding column; ingest (upload/paste) → chunk + embed;
new `docs_context_builder` (top-K vs question) injected after semantic block; Knowledge → Docs tab +
approve gate + "📄 grounded on" answer chip.
**Flag:** `HYBRID_DOC_KNOWLEDGE`. **Gate:** a term-definition question resolves from an approved doc.
**Risk:** medium. Lower priority — only matters once schema+code grounding are in and business-term
ambiguity is the remaining miss.

---

## PHASE 6 — Join / lineage graph  — DONE 2026-06-19 (live, baked, verified)

**Built by 4 disjoint-file sub-agents (1 foundation + 4 wave-2) + integration.** Flags `HYBRID_JOIN_GRAPH`
(builder/UI) + `JOIN_MINE_ENABLED` (nightly daemon), both default OFF, in `.env` AND compose env.
- **Model + migration:** `app/models/table_edge.py` (`TableEdge`, table `table_edges`) + migration `joingraph1`
  (down `kepler2cb1`, now HEAD). Cols left/right table+col, join_count, confidence, source, status(pending→approved
  gate), unique on the 6-col edge key. Approval invariant: only `status=='approved'` reaches the agent.
- **Miner** `app/ai/knowledge/join_miner.py` — REGEX parser (NO sqlglot — not installed, no dep added):
  `parse_sql_joins` (alias map from FROM/JOIN, schema-qual + quoted idents, ON + weak WHERE equi-joins, canonical
  pair orientation, dedupe) + `parse_pandas_merges` (best-effort pd.merge). `mine_join_edges(db,*,organization,
  data_source_id)` tallies QueryLibraryItem.sql_text + QueryCache.sql_text → upsert pending (never downgrades an
  approved edge). `run_join_mining()` self-contained daemon. All fail-soft.
- **Context** `sections/join_graph.py` (`### How tables join` adjacency block, most-used first, 30-line cap,
  xml_escape) + `builders/join_graph_context_builder.py` (top-20 approved edges, ds OR org-null, fail-soft).
  Wired into `context_hub.py` (gather slot #12 + `render_join_graph_section`) + `agent_v2.py` (append after
  brain_graph block, gated `flags.JOIN_GRAPH`). Daemon `register_join_mine_jobs` (cron 03:30) in scheduler + main.py.
- **API** `routes/knowledge.py`: `GET /knowledge/joins?data_source_id=`, `POST /knowledge/joins/mine`, and `kind='join'`
  added to the `/{kind}/{id}/approve|reject` catch-all (`_KIND_MODEL['join']=TableEdge`).
- **FE** `pages/knowledge/index.vue`: "Joins" tab (between Queries/Assets), Mine-joins button, edge list with seen-Nx
  badge + status pill + pending Approve/Reject (neutral, no blue).
- **VERIFIED E2E** (chinook DS, flags forced on): `mine_join_edges` → 7 edges (3 seeded + 4 from real captured chat
  SQL), builder renders the join block, approve→surfaces / pending→hidden gate proven. Migration head `joingraph1`.

**LANDMINES:** no sqlglot in image → regex parser (don't "fix" by adding the dep — vendoring/offline-download risk);
gather tuple in context_hub must stay positional (join_graph appended LAST, 12=12); `docker restart` keeps create-time
env so a hot-copied flag reads OFF until `--force-recreate` (force-recreate reverts hot-copied .py → must rebuild first);
FE Joins tab is baked → needs image rebuild. Plan originally tagged this DEFER/low-value; built on explicit request.

### (original spec below)
## PHASE 6 — Join / lineage graph  (heavy, low value — DEFER)

**Reuse:** `brain_graph_context_builder` reads the extensible `BrainGraphEdge` table (not hardcoded).
`query_cache.sql_text` + `Step.code` hold the raw material.

**Build (most effort):** `join_miner` that parses JOIN…ON from captured SQL AND `pd.merge(on=...)` from
generated python (AST/regex) → tally edges → confidence; emit a compact adjacency for in-scope tables.
**Flag:** `HYBRID_JOIN_GRAPH`. **Risk:** highest parsing effort, lowest marginal value once code-memory
(Phase 2) already carries the working joins. Build only if join-guessing is a measured failure mode.

---

## Cross-phase notes
- **Audit-confirmed soft blockers:** (a) eval context_change hook = one added call on approve; (b) docs
  "FTS missing" → sidestep with existing pgvector. Neither is a real blocker.
- **The only true new store:** code_cache (Phase 2) — and it's a clone of query_cache.
- **Verify-before-build flag:** Phase 4 — confirm the eval runner truly invokes the analyst and persists
  produced data (audit verdict was PARTIAL on the invoke path).

---
## Appendix — original per-feature detail (pre-phasing)


Source: OpenAI "Inside our in-house data agent" (Kepler). 6 context layers + continuous
evals. This plan extends our EXISTING Knowledge Layer / eval / memory code — minimal new
surface, everything additive + flag-gated (code default OFF), approval-gated where it writes
grounding. Single-analyst (`agent_v2.py`) untouched except adding render blocks.

Real anchors (verified):
- Models: `app/models/semantic_table.py` (SemanticTable + SemanticColumn), `metric_definition.py`,
  `query_library.py` (QueryLibraryItem), `instruction.py`, `eval.py` (TestSuite/Case/Run/Result),
  `data_source.py`.
- Builders dir: `app/ai/context/builders/*` (17). Assembly: `agent_v2.py` ~L1988-2104 +
  `context_hub.py`. Knowledge API: `app/routes/knowledge.py` (`/api/knowledge`).
- Eval runner: `app/services/test_evaluation_service.py`. Eval routes: `app/routes/eval_yaml.py`.
- Self-learning: `app/ai/brain/knowledge_proposer.py`, `distiller.py`.

Flag convention: `HYBRID_*` env, default OFF. Caps via env. New writes land `status='pending'`.

---

## Feature 1 — Code / pipeline grounding  (Kepler layer 4, "code matters more than schemas")

**What:** attach the SQL/dbt transform that DEFINES each table (its WHERE filters, joins, derived
columns, business assumptions) to the semantic table, and inject a trimmed version into context.
This is their #1 lesson and our biggest gap (we ground on prose description only).

**Data model** (migration, additive):
- `semantic_tables` += `code_definition TEXT default ''`, `code_source VARCHAR(50)` (`dbt|sql|git|manual`),
  `code_path VARCHAR(500)`, `code_synced_at TIMESTAMP NULL`, `code_status VARCHAR(20) default 'pending'`.
- (col-level intent already covered by `semantic_columns.meaning`.)

**Ingest (new):** `app/ai/knowledge/code_crawler.py`
- Reuse existing `GitRepository` link on DataSource (`data_source.git_repository`). Walk repo for
  `*.sql` / dbt `models/**/*.sql`; match model name → table_name; store raw SELECT as `code_definition`,
  `code_source='dbt'|'git'`, `code_path`, set `code_status='pending'` (review gate).
- Manual paste path: PATCH endpoint to set `code_definition` by hand.
- Daemon (leader-gated, `CODE_CRAWL_ENABLED` default OFF) re-syncs on commit drift (`content_hash`).

**Context wiring:** `semantic_context_builder.py` — when `HYBRID_CODE_GROUNDING=1`, append a
`### How <table> is built` block per top-K table (cap chars `CODE_DEF_MAX_CHARS=800`, summarized if
longer via small_model once, cached). Already inside the top-K loop so it respects bounded context.

**API:** extend `app/routes/knowledge.py`
- `POST /api/knowledge/code/crawl/{data_source_id}` → run crawler (pending rows).
- `PATCH /api/knowledge/semantic/table/{id}/code` → manual set / edit code_definition.
- `POST /api/knowledge/code/{id}/{approve|reject}` → review gate flips `code_status`.

**Flag:** `HYBRID_CODE_GROUNDING` (inject), `CODE_CRAWL_ENABLED` (daemon).

**UI:** semantic card gets a `</> code` chip (present/missing/stale); detail drawer shows the
defining SQL with a "Source: dbt models/finance/revenue.sql · synced 2d ago" line + Approve/Reject +
"Paste definition" editor. (mockup panel B.)

**How it works end-to-end:** user opens Knowledge → table card shows `</>` chip → clicks → drawer
shows crawled dbt SQL → approves → next analyst question about that table gets the *real filter logic*
("revenue excludes refunds & internal test accounts") in context → no more wrong assumptions.

---

## Feature 2 — Governance metadata: freshness · owner · PII  (Kepler layer 1 + trust)

**What:** every table/column carries owner, freshness, and PII flag. Agent says "data as of <date>",
warns on stale, and refuses/redacts PII columns. We currently carry only `status`.

**Data model:**
- `semantic_tables` += `owner VARCHAR`, `freshness_sla_hours INT NULL`, `last_refreshed_at TIMESTAMP NULL`
  (auto from `data_sources.last_synced_at` / table stats), `pii BOOLEAN default false`.
- `semantic_columns` += `pii BOOLEAN default false`, `sensitivity VARCHAR(20) default 'none'`
  (`none|internal|pii|secret`).
- (MetricDefinition.owner / QueryLibraryItem.owner already exist — reuse.)

**Backend:**
- Freshness: read `data_source.last_synced_at` + `TableStats`; compute stale = now - last_refreshed >
  sla. No new daemon.
- PII auto-hint: optional column-name heuristic (`email|ssn|phone|dob|address|card`) → propose
  `pii=true` pending (never auto-enforce).

**Context wiring:** `semantic_context_builder.py` adds a one-line governance footer per injected table:
`owner · freshness/stale · PII columns: [...]`. Planner prompt gets a rule: never emit PII columns
unless explicitly asked + authorized; always state data-as-of.

**API:** extend PATCH `/semantic/table/{id}` + `/semantic/column/{id}` to accept the new fields
(already a generic patch — add to allow-list). New `GET /api/knowledge/governance/{data_source_id}`
→ rollup (stale count, PII count, unowned count) for the dashboard strip.

**Flag:** `HYBRID_GOVERNANCE` (inject footer + enforce PII rule).

**UI:** card chips — owner avatar, freshness dot (green<sla / amber stale), `PII` red pill; a
Governance summary strip above the grid (N stale · N PII · N unowned). Answer header shows
"Data as of Jun 17" + a 🔒 if a PII column was touched. (mockup panel A.)

---

## Feature 3 — Continuous eval harness with golden SQL  (Kepler: "evals as unit tests, canaries in prod")

**What:** golden Question→SQL pairs per data source; run compares RESULT-SET + AST, LLM grader for
acceptable variance; runs on a schedule + on context change; regression alert. Most infra EXISTS
(`TestSuite/Case/Run/Result`, `TestEvaluationService`, `trigger_reason` already has
`'context_change'|'schedule'`, `auto_generated` flag). We add: golden-SQL rule type, result-set
matcher, scheduler, and a UI.

**Data model:** mostly reuse. Add to `ExpectationsSpec` a new rule `GoldenSqlRule`
{ golden_sql, compare: `resultset|ast|both`, tolerance }. Optional `test_cases` += `golden_sql TEXT`.

**Backend (`test_evaluation_service.py`):**
- New matcher: run golden_sql read-only → run agent's emitted SQL read-only → compare result sets
  (order-insensitive, numeric tolerance) + AST normalize (sqlglot) for structural equality; LLM grader
  (existing Judge) only for the "different SQL, same answer" case.
- Scheduler: leader-gated daemon `EVAL_SCHEDULE_ENABLED` (cron-ish) → creates TestRun
  `trigger_reason='schedule'`. Context-change hook: when a knowledge item is approved
  (`/{kind}/{id}/approve`) enqueue a TestRun `trigger_reason='context_change'` for that DS's suite.
- Regression: compare run summary vs last green → if newly-failing cases > 0 → `dash_notifications` +
  surface on dashboard.

**Auto-author goldens:** on a 👍 answer, offer "save as golden" → creates TestCase
(`auto_generated`, `source_completion_id`) with the emitted SQL as golden_sql (review before active).
Reuses the feedback plumbing.

**Flag:** `HYBRID_EVAL_HARNESS` (UI + matcher), `EVAL_SCHEDULE_ENABLED` (daemon).

**UI:** new page `Manage → Evals` (or extend existing evals route): suite list, golden pairs table
(question · golden SQL · last result · pass/fail · drift), a run button, a trend sparkline (pass-rate
over time), red "2 regressions since context change" banner. Per-answer: a small "✓ matches golden"
badge when the question maps to a passing golden. (mockup panel C.)

**How it works:** approve a new semantic description → context-change run fires → 1 case now returns a
different number → regression banner → you inspect → either the change was wrong (revert) or the golden
is stale (update). Trust becomes measurable, not vibes.

---

## Feature 4 — Institutional-knowledge RAG  (Kepler layer 5: Slack/Docs/Notion)

**What:** business terms resolve from company docs ("what counts as an *active* customer?"). We have
ZERO external-doc grounding here, but we built this exact pattern in sibling projects (Aria/DocSensei
vectorless PageIndex + PG-FTS, and OKF import). Port as a knowledge SOURCE feeding context.

**Data model (new):** `knowledge_docs` { id, org_id, data_source_id NULL, title, source
(`upload|notion|slack|gdrive|url`), body TEXT, url, content_hash, status `pending|approved`,
created_at }. + PG-FTS index (`to_tsvector`) — no embeddings (matches our vectorless stance; can add
pgvector later if recall misses).

**Backend (new):** `app/ai/knowledge/docs_index.py`
- Ingest: file upload + paste + (later) connectors. Chunk + FTS index.
- New builder `docs_context_builder.py` (gated `HYBRID_DOC_KNOWLEDGE`): FTS top-K vs the question,
  inject `### Company definitions` block (cap `DOC_TOPK=4`). Wired into `agent_v2.py` assembly after
  semantic block.

**API:** `app/routes/knowledge.py` += `GET/POST /api/knowledge/docs`, `/docs/{id}/{approve|reject}`,
`POST /api/knowledge/docs/search?q=` (debug).

**Flag:** `HYBRID_DOC_KNOWLEDGE`.

**UI:** new Knowledge tab **Docs** (alongside Semantic/Metrics/Queries/Assets/Review): list + "Add doc"
(upload/paste/connect) + approve gate + a grounded-on chip when a doc was used in an answer. (mockup
panel D.)

---

## Feature 5 — Strengthen the memory loop  (Kepler layer 6: corrections become reusable context)

**What:** Kepler — analyst corrects a mapping / labels a good answer → it becomes context. We capture
SQL (query bank) and `knowledge_proposer`/`distiller` already draft pending items on 👎, but the
"correction → durable grounding" UX is thin and one-directional. Make it a first-class, visible loop.

**Reuse:** `knowledge_proposer.py` (proposes semantic/metric/query pending on feedback),
`distiller.py` (instructions from 👎), QueryLibraryItem (`source='chat'|'promoted'`).

**Add:**
- 👍 path (today mostly 👎-driven): a 👍 with "this is right" → propose the emitted SQL as a pending
  QueryLibraryItem + (if it referenced an undescribed table) a pending semantic description draft.
- Inline correction: in the answer, an "✏️ correct this" → captures user's note → drafts a pending
  instruction or semantic edit (`source_type='ai'`, status pending) attributed to the conversation.
- "Discovered filter" capture: when the agent adds a non-obvious WHERE (e.g. `status != 'test'`),
  log it as a candidate quality_note on the table (pending).
- Surface in **Review** tab: every learned item shows provenance ("from chat on Jun 18: <question>")
  + Approve/Edit/Reject (review gate already exists via `/pending` + `/{kind}/{id}/approve`).

**Flag:** `HYBRID_MEMORY_LOOP` (enables 👍 capture + correction UI).

**UI:** answer action row gets `✏️ Correct` + `📌 Save as known`; Review tab groups by provenance with
a "Promote to grounding" button. (mockup panel E.)

---

## Feature 6 — Join / lineage inference  (Kepler layers 1-2: common joins, lineage)

**What:** infer the common join paths + table relationships from query history so the planner knows
how tables connect (FK-ish edges) without guessing. We have AGE/graph experience (CityPharma
`citypharma_kg`) and a `brain_graph_context_builder.py` already.

**Data model (new):** `table_edges` { id, org_id, data_source_id, left_table, left_col, right_table,
right_col, join_count INT, confidence FLOAT, source `inferred|declared`, status }.

**Backend (new):** `app/ai/knowledge/join_miner.py`
- Mine `query_library_items.sql_text` + captured chat SQL (sqlglot parse JOIN ... ON) → tally
  (left.col = right.col) pairs → confidence = freq. Daemon `JOIN_MINE_ENABLED` default OFF.
- Extend `brain_graph_context_builder.py` (already gated `BRAIN_GRAPH`) to read `table_edges` and emit a
  compact `### How tables join` adjacency block for the top-K tables in scope.

**Flag:** `HYBRID_JOIN_GRAPH`.

**UI:** Knowledge → Semantic card detail shows "Joins to: invoices.customer_id → customers.id (used 42×)";
optional small graph view reusing existing graph component. (mockup panel F, light.)

---

## Sequencing (recommended)

1. **F2 Governance** — low effort, instant trust (chips + footer + PII rule). Ship first.
2. **F1 Code grounding** — their #1 lesson, biggest accuracy lift. Reuses GitRepository link.
3. **F3 Eval harness** — turns accuracy into a guarantee; infra ~70% exists.
4. **F5 Memory loop** — cheap, compounds with F1-F3 (corrections feed grounding).
5. **F4 Doc RAG** — port from Aria; medium effort.
6. **F6 Join graph** — nice-to-have; extends existing brain graph.

All flags default OFF → byte-identical behavior until each is switched on per environment.
```
HYBRID_CODE_GROUNDING  HYBRID_GOVERNANCE  HYBRID_EVAL_HARNESS
HYBRID_DOC_KNOWLEDGE   HYBRID_MEMORY_LOOP HYBRID_JOIN_GRAPH
CODE_CRAWL_ENABLED  EVAL_SCHEDULE_ENABLED  JOIN_MINE_ENABLED  (daemons)
```
