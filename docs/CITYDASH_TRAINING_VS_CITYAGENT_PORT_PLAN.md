# How City‑Dash Trains Agents on Data — and How to Bring It into CityAgent Analytics

> Study + port plan. Source studied: `/City-Dash/dash` (FastAPI + SvelteKit "agentic data notebook", PG18+pgvector, OpenRouter).
> Target: this repo, **CityAgent Analytics / "City Agent DASH"** (bagofwords fork, FastAPI + Nuxt3, PG18, OpenRouter).
> Date: 2026‑06‑20.

---

## TL;DR

City‑Dash and CityAgent are **two philosophies for the same goal** (chat with your data):

| | City‑Dash | CityAgent Analytics (this repo) |
|---|---|---|
| Mental model | **PUSH** — upload a file, the agent *trains itself* on it, then answers | **CONNECT + APPROVE** — connect a live DB, *index its metadata*, a human approves knowledge, then answer |
| Data entry | File upload (Excel/CSV/PDF/…) → loaded into a per‑project Postgres schema | 40+ live connectors (Postgres/Snowflake/BigQuery/…) + file upload → DuckDB/SQLite |
| "Training" | Automatic 14‑step pipeline on every upload (no human in loop) | Metadata indexing job + **human‑approved** knowledge rows + user‑written instructions |
| Knowledge served | 16 context layers injected into the agent prompt at query time | Semantic/Metrics/Queries/Docs/Joins/Brain — **flag‑gated, approval‑only** (Phases 0‑7 + KEPLER P0‑P6 already ported) |
| Retrieval | pgvector hybrid + keyword | **vectorless** by design (Postgres FTS + token‑Jaccard) |

**The gap to close** is the part City‑Dash calls *"training"*: **upload Excel/CSV/PDF → auto‑profile → auto‑build a semantic model + verified Q&A + persona + KG → answer**, with **no human approval step**. CityAgent already has the *receiving* structures (semantic model tables, metrics, query library, docs RAG, join miner, brain). What it lacks is the **auto‑populate‑on‑upload pipeline** and an **ingest lane that turns a flat file into a queryable table**.

---

## Part 1 — How City‑Dash adds data and "trains" the agent

City‑Dash's whole product is built on one idea (lifted from OpenAI's in‑house data agent + BagOfWords): **the agent's quality comes from a rich, auto‑built knowledge layer, not from a bigger model.** Three stages.

### 1.1 Data IN — the Staged Ingest Pipeline

Files never hit the database directly. Path (`dash/ingest/` + `app/upload.py` + `app/upload_stream.py`):

```
upload → STAGE (file on disk, sha256-hashed, NO db write)
       → VALIDATE + SCHEMA-CONTRACT check (drift / dup / quality score)
       → DRY-RUN diff
       → GATE (auto-promote EXACT; quarantine on drift/dup/score<10)
       → PROMOTE (idempotent, lineage-stamped) into proj_{slug} schema
       → TRAIN
```

Key modules:

- **`dash/ingest/staging.py`** — writes a per‑batch manifest JSON, content‑hashes the file (skip exact re‑uploads).
- **`dash/ingest/contract.py`** — a **versioned Schema Contract** per *logical dataset*. Detects column drift (added / removed / **retyped** / renamed) and quarantines instead of silently corrupting a table. Auto‑detects a `load_key` in 4 tiers: single PK → composite → **period** (filename month token → `DELETE WHERE _period` then load — the right strategy for monthly drops) → content‑hash.
- **`dash/ingest/loader.py`** — idempotent `promote_file`, stamps lineage columns on every row: `_source_file, _period, _batch_id, _content_hash, _row_key, _ingested_at`. Enables surgical undo (`DELETE WHERE _batch_id=X`).
- **Logical dataset consolidation** — `"MM Conso Apr 25.csv"` + `"MM Conso May 25.csv"` → one table `mm_conso` with a `_period` stamp, **not** two sibling tables that every query must UNION. (This solved a real "1804 vs 1544" miscount class.)
- **GB‑scale path** — `dash/ingest/copy_stream.py` uses psycopg3 `COPY FROM STDIN`, no RAM cap, CSV/Excel/Parquet.

**Excel is hard** — City‑Dash has a 5‑layer self‑correcting Excel reader (`app/upload.py`):
1. Rules engine ($0) — header detection, banner‑row strip, multi‑table split on blank gaps, unpivot months→rows.
2. LLM structure plan when rules are unsure.
3. `_validate_dataframe()` quality score (NaN%, subtotals, unnamed cols) + `_auto_fix_dataframe()`.
4. `_deep_extract_cells()` — openpyxl unmerge + bold/colour metadata → LLM re‑plans.
5. **LLM rescue + file‑hash cache** — when `actual_rows < 10% of expected`, one cheap LLM call re‑reads the sheet with corrected header/skip rows; the plan is cached by file sha256 **cross‑tenant** (same vendor template = 1 LLM call ever).

**PDF/PPTX/DOCX** are a separate "doc‑only" lane: text extraction (`pymupdf4llm` → Markdown), section‑aware chunking, hierarchical summarisation, OCR (Tesseract) + Vision LLM fallback for charts, image description. Structured **tables** inside PDFs/PPTX/DOCX are extracted into real Postgres tables too.

### 1.2 The "TRAIN" — what training actually produces

`POST /train` (or `/retrain`) runs **14 steps for data, 18 for doc‑only**, tracked in `dash_training_runs` (`step|table|index|total`). This is the heart of "train the agent." None of it is model fine‑tuning — it's **knowledge generation**:

| # | Step | Produces |
|---|---|---|
| 1 | catalog | SQL profile of every column (zero RAM, pure Postgres) |
| 2 | profile | MIN/MAX/AVG/percentiles; classify dimension vs measure vs id |
| 3 | dim catalog | `SELECT DISTINCT` for categoricals (<500 uniques) → `dimensions/{table}.json` (exact values + frequencies) |
| 4 | hierarchy | parent→child dimension mapping (region→city) |
| 5 | sample | 20 *diverse* rows (3 start + 3 mid + 3 end + outliers + null patterns) |
| 6 | **codex enrich** | LLM reads **view/table DDL** → `{purpose, grain, PK, FK, usage patterns, freshness}` per table. *(This is the #1 quality unlock — meaning lives in the code that builds the table, not the rows.)* |
| 7 | Q&A verify | LLM generates question→SQL pairs, **executes the SQL**, saves only the ones that run → *verified* Q&A |
| 8 | relationships | cross‑table joins (LLM proposes, verified by actual value overlap) |
| 9 | persona | a project persona derived from the data shape |
| 10 | domain knowledge | glossary / calculations / value‑maps / KPIs / quality notes / negative examples |
| 11 | KG triples | SPO extraction + entity standardisation (fuzzy + LLM) + community detection |
| 12 | LangExtract | grounded facts with source character positions |
| 13 | drift baseline | schema + value‑distribution snapshot for future drift detection |
| 14 | watermark register | register the provider, emit per‑source tools |

`profile_v2` (`dash/training/profile_v2.py`) is the advanced profiler (combined‑query + `pg_stats` + `TABLESAMPLE` + variant detect + role classify), stored as JSONB in `dash_table_metadata.metadata['profile_v2']` and read at chat time. It can be run **lazily on a cache miss** at query time (add a table after training → first query +1.4s → auto‑profiled), so the user never has to "retrain."

Training is **non‑blocking and queued** (`dash/training/train_queue.py` + Redis): `POST /retrain-queued` returns 202, an in‑process worker drains the queue with a per‑project lock (fair multi‑tenant), 5‑min SIGALRM per job, parent run auto‑finalises when the last child job completes.

### 1.3 How the trained agent ANSWERS

At chat time the Leader orchestrator routes to a team (Analyst / Engineer / Researcher / Data Scientist + 10 specialists). The Analyst's prompt is assembled from **16 context layers** (budget ~50K chars, weighted truncation), e.g.:

```
1  Table usage + proven query patterns      9  Human annotations (rerun)
2  Human annotations (override LLM)         10  Self-correction strategies
3  Codex-enriched knowledge (purpose/grain) 11  Evolved instructions (versioned)
4  Institutional knowledge (pgvector)       12  Knowledge graph (entity→table)
5  Memory (personal/project/global)         13  Company brain (3-scope)
6  Runtime context (live introspect)        14  Anti-patterns (dream reflection)
7  Grounded facts (LangExtract)             15  Proven skills (Voyager library)
8  Table usage (rerun, post-narrowing)      16  Precompute cache hints
```

Plus closed‑loop self‑correction (Analyst retries SQL ≤3× on error/zero‑rows, schema‑introspects, cross‑checks COUNT) and a **verified‑metric / cached‑answer shortcut** that serves a pinned answer with 0 LLM when the question matches a known metric.

**The loop closes:** every chat runs ~11 background agents that mine new query patterns, promote memories, extract KG triples, score quality — so the knowledge layer grows with use, and a nightly self‑learning + "dream reflection" cycle distils it.

---

## Part 2 — What CityAgent Analytics already has

Good news: a large slice of Part 1 is **already ported into this repo**, flag‑gated and approval‑only.

- **Knowledge Layer (Phases 0‑7)** — `pages/knowledge/index.vue` tabs: **Semantic | Metrics | Queries | Assets | Docs | Joins | Review**. Models exist: `knowledge_doc`, `datasource_table`, `metadata_resource`, `instruction*` (versioned). Only `status=='approved'` rows reach the agent (`app/ai/context/builders`).
- **Vectorless retrieval** — `app/ai/knowledge/docs_index.py` (Postgres FTS + token‑Jaccard, `knowledge_doc_chunks` + GIN index), **no embedding client anywhere by design.**
- **Join miner** — `app/ai/knowledge/join_miner.py` learns join paths from SQL the agent actually ran + `pd.merge` calls.
- **Karpathy "2nd brain"** — `app/ai/brain/`: `answer_cache`, `query_cache_{store,serve,curator}`, `qa_pair`, `distiller`, `knowledge_proposer`, `brain_graph`, `serving_funnel`. Self‑learning fires after the distiller on 👎.
- **Agent team** — `app/ai/agents/`: planner, coder, answer, judge, reporter, dashboard_designer, data_source, doc, excel, router, suggest_instructions. Skills system ("like Claude Code", S1‑S5 done).
- **Data IN** — 40+ live connectors (`app/data_sources/clients/`), `connection_indexing_service.py` (background `refresh_schema`), `file_service.py`, agent‑owned schemas `analytics` (Engineer views) + `staging` (ingest).

So CityAgent already has the **receiving structures** and a **connect‑and‑index** path. What it does **not** have is City‑Dash's **upload‑a‑flat‑file‑and‑auto‑train** push pipeline.

---

## Part 3 — The gap, and how to close it (port plan)

### 3.1 Gap analysis

| City‑Dash capability | CityAgent today | Gap |
|---|---|---|
| Staged ingest (stage→contract→promote) for **flat files** into a queryable schema | File upload exists; live‑DB indexing exists | **No "flat file → table in `staging`/DuckDB" ingest with schema contract + lineage** |
| 5‑layer self‑correcting Excel reader | `excel` agent exists | Partial — no rules‑engine + LLM‑rescue + file‑hash cache |
| **Auto‑train on upload** (14‑step, no approval) | Knowledge layer is **approval‑only** | **No auto‑populate of semantic/metrics/Q&A from a freshly ingested table** |
| `profile_v2` JSONB + lazy profile on cache‑miss | — | Missing |
| Codex DDL enrichment (purpose/grain/PK/FK) | Semantic rows exist (human/proposer) | No DDL‑reading auto‑enricher |
| Verified Q&A (generate→execute→keep) | Query library exists | No auto‑generated *verified* Q&A on ingest |
| Drift baseline + schema contract | — | Missing |

### 3.2 Design principle for the port

**Don't break the approval model — extend it.** City‑Dash auto‑promotes; CityAgent gates on human approval. Reconcile by making the auto‑pipeline write rows with **`status='pending'` (or a new `status='auto'`)** so they appear in the **Review** tab. The user gets City‑Dash's "it just trained itself" speed *and* keeps CityAgent's governance. Add a per‑org flag `HYBRID_AUTOTRAIN` (default OFF, like every other hybrid flag).

### 3.3 Proposed architecture (full)

```
                          ┌──────────────────────────────────────────┐
  UPLOAD (xlsx/csv/pdf)   │  FE: pages/knowledge + file upload         │
        │                 └──────────────────────────────────────────┘
        ▼
┌───────────────────────────────────────────────────────────────────────┐
│  NEW: app/services/ingest/  (mirrors dash/ingest/)                      │
│   stage.py     → hash file, write manifest, NO db write                 │
│   contract.py  → schema contract (drift/retype/rename) per logical ds   │
│   reader/      → excel_reader.py (5-layer + file-hash cache)            │
│                  csv_reader.py · parquet_reader.py                       │
│                  doc_reader.py  (pdf/pptx/docx → text + tables)         │
│   loader.py    → promote into `staging.<table>` (DuckDB or PG),         │
│                  lineage cols _source_file/_period/_batch_id/...        │
│   gate.py      → auto-promote EXACT, quarantine drift/dup/low-score     │
└───────────────────────────────────────────────────────────────────────┘
        │ table now queryable
        ▼
┌───────────────────────────────────────────────────────────────────────┐
│  NEW: app/services/autotrain/  (mirrors dash/training/)                 │
│   profiler.py   → profile_v2 JSONB → datasource_table.metadata          │
│   codex.py      → read DDL/sample → {purpose,grain,PK,FK,freshness}     │
│                   → SemanticModel rows  (status='auto')                 │
│   qa_gen.py     → LLM Q&A → EXECUTE via existing code-exec → keep verified
│                   → QueryLibrary rows   (status='auto')                 │
│   metrics_gen.py→ propose metrics       → MetricsCatalog (status='auto')│
│   kg.py         → reuse join_miner + brain_graph                        │
│   drift.py      → baseline snapshot for future drift                    │
│   ↑ ALL reuse app/ai/brain/knowledge_proposer.py (already approval-safe)│
└───────────────────────────────────────────────────────────────────────┘
        │ writes pending/auto rows
        ▼
┌───────────────────────────────────────────────────────────────────────┐
│  EXISTING: Review tab → human approves → only approved reach the agent  │
│  EXISTING: 16-layer-equivalent context builders inject approved rows    │
│  EXISTING: agent team answers; brain caches; distiller learns on 👎     │
└───────────────────────────────────────────────────────────────────────┘
```

### 3.4 Concrete steps (smallest viable → full)

**Step 0 — flag.** Add `HYBRID_AUTOTRAIN` to `app/settings/hybrid_flags.py` (default OFF). Everything below is dead code until flipped.

**Step 1 — flat‑file ingest lane (highest value).** Port `dash/ingest/{staging,contract,loader}.py` into `app/services/ingest/`. Target `staging` schema (already a convention in this repo) or DuckDB (`duckdb_client.py` already exists). Stamp lineage columns. This alone gives "upload a CSV → chat with it" without writing instructions.

**Step 2 — robust Excel.** Port City‑Dash's 5‑layer reader (rules → LLM plan → validate/fix → deep‑cell → LLM‑rescue + file‑hash cache). The existing `excel` agent can call it as a tool. The file‑hash cache table is a small migration.

**Step 3 — `profile_v2` profiler.** Write JSONB profile into `datasource_table.metadata`; add a **lazy profile on cache‑miss** at query time (port the `LAZY_PROFILE_V2` pattern) so new tables don't need a manual retrain.

**Step 4 — auto‑enrich → pending rows.** Reuse `app/ai/brain/knowledge_proposer.py` (already has `propose_knowledge_from_schema`, approval‑safe, never raises). Add `codex.py` (DDL/sample → purpose/grain/PK/FK) and `qa_gen.py` (generate → **execute via existing `code_execution`** → keep only verified). Write rows with `status='pending'/'auto'`.

**Step 5 — wire to upload.** On file upload (or on a "Train" button), if `HYBRID_AUTOTRAIN` is ON: stage → contract‑check → promote → profile → enrich → write pending knowledge. Surface progress like City‑Dash's `dash_training_runs` (reuse `metadata_indexing_job` model — it already tracks background indexing progress).

**Step 6 — drift + contract on re‑upload.** Port `contract.py` drift detection so a monthly re‑drop quarantines on retype/rename instead of corrupting the table; consolidate logical datasets (strip period tokens) so you get one `_period`‑stamped table, not N siblings.

### 3.5 What to reuse vs build

| Need | Reuse (exists here) | Build (port from City‑Dash) |
|---|---|---|
| Background job + progress | `metadata_indexing_job_service.py`, `connection_indexing_service.py` | — |
| Approval gate + Review UI | Knowledge layer Phases 0‑7 | — |
| Knowledge writes (approval‑safe) | `brain/knowledge_proposer.py` | thin codex/qa_gen wrappers |
| SQL execution for Q&A verify | `app/ai/code_execution/` | qa_gen orchestration |
| Join graph / KG | `knowledge/join_miner.py`, `brain/brain_graph.py` | — |
| Vectorless retrieval | `knowledge/docs_index.py` (FTS+Jaccard) | — (keep vectorless — do NOT add pgvector) |
| Flat‑file → table | DuckDB/SQLite clients + `staging` schema | `ingest/{staging,contract,loader}.py` |
| Excel robustness | `excel` agent | 5‑layer reader + file‑hash cache |
| Per‑column profile | — | `profile_v2` |
| Codex DDL enrich | — | `codex.py` |
| Verified Q&A | query library tables | `qa_gen.py` |
| Drift baseline | — | `drift.py` |

### 3.6 Landmines to respect (this repo's rules)

- **OpenRouter ONLY** for LLM. **Vectorless ONLY** — there is no embedding client; rank with FTS + token‑Jaccard (City‑Dash uses pgvector; do **not** copy that part).
- All new behaviour **flag‑gated, default OFF**, and **approval‑only** (write `pending`, never auto‑inject unapproved rows into the agent).
- Migrations: extend the alembic chain (current HEAD per CLAUDE.md is `sk3skillfiles1`); guard Postgres‑only SQL so SQLite dev still migrates.
- No git → snapshot via `scripts/backup.sh` before structural edits.
- Build the app image `cityagent-analytics:dev`; never pull `bagofwords:latest`.

---

## Part 4 — Recommended first slice (1 PR)

Ship the **smallest thing that delivers the City‑Dash feel**:

1. `HYBRID_AUTOTRAIN` flag (OFF).
2. `app/services/ingest/{stage,contract,loader}.py` + a CSV reader → promote into `staging`.
3. On upload, stage→promote a CSV into a queryable table with lineage columns.
4. Reuse `knowledge_proposer.propose_knowledge_from_schema` to write `pending` semantic rows for the new table.
5. New rows show in the existing **Review** tab; once approved, the agent can already answer.

That proves the end‑to‑end "upload → (auto) → answer" loop using almost entirely existing machinery. Excel 5‑layer, `profile_v2`, codex DDL enrich, verified Q&A, and drift contracts are follow‑on PRs that each raise answer quality.

---

### Appendix — file map cheat‑sheet

| Concept | City‑Dash | CityAgent (here) |
|---|---|---|
| Ingest | `dash/ingest/*` | **(to build)** `app/services/ingest/*` |
| Training orchestration | `app/upload.py`, `dash/training/*` | **(to build)** `app/services/autotrain/*` |
| Profiler | `dash/training/profile_v2.py` | **(to build)** `autotrain/profiler.py` |
| Codex enrich | `dash/tools/codex_code.py` | **(to build)** `autotrain/codex.py` |
| Knowledge writes | `app/brain.py`, KG tools | `app/ai/brain/knowledge_proposer.py` ✅ |
| Docs RAG | pgvector | `app/ai/knowledge/docs_index.py` (vectorless) ✅ |
| Join graph | `dash/tools/knowledge_graph.py` | `app/ai/knowledge/join_miner.py` ✅ |
| Brain/cache | `dash_company_brain`, dream cycle | `app/ai/brain/*` ✅ |
| Agent team | `dash/team.py` + agents | `app/ai/agents/*` ✅ |
| Context layers | `dash/instructions.py` (16) | `app/ai/context/builders` ✅ |
| Approval gate | auto‑promote | Knowledge Review tab ✅ (keep) |
