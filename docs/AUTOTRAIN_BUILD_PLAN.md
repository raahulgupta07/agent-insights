# Autotrain Build Plan — port City‑Dash agent‑training onto CityAgent

> Goal: "upload a file (or point at a connector) → agent trains itself → answers" — City‑Dash's
> push model, landed on CityAgent's existing **connect + approve + vectorless + brain** design.
> Date: 2026‑06‑20. Flag‑gated (`HYBRID_AUTOTRAIN`, default OFF). Approval‑only. OpenRouter‑only. No pgvector.

---

## North star

```
  TRAIN-TIME auto-learn (City-Dash 14-step) feeds the SAME pending→curator→active
  brain pipeline that USE-TIME auto-learn (distiller/proposer/curator) already uses.
  → one knowledge bus, two producers (train-time + use-time), one approval gate.
```

## 5 principles (non‑negotiable)

```
  1. SOURCE-AGNOSTIC   autotrain(ds_id, table) — never a file path.
                       Same code trains uploaded files AND live connector tables.
  2. APPROVAL-SAFE     all writes status='pending'; curator/human promotes. Never auto-live.
  3. VECTORLESS        rank with PG-FTS + token-Jaccard. NO embedding client (repo has none).
  4. FLAG-GATED        HYBRID_AUTOTRAIN default OFF → dead code until flipped per-org.
  5. REUSE-FIRST       call existing brain/code-exec/join_miner; build only the missing engine.
```

---

## What's built vs what to build

```
  ✅ HAVE (reuse)                          ❌ BUILD (port)
  ─────────────────────────────────────────────────────────────────
  40+ connectors + metadata index          ingest lane (file → staging table)
  file_service (disk) + excel agent         5-layer excel reader (robust)
  duckdb read_csv_auto VIEW                  profile_v2 (per-col JSONB)
  knowledge_proposer (pending writes)        codex DDL enrich (purpose/grain/PK/FK)
  code_execution (run SQL)                   qa_gen (generate→EXECUTE→keep verified)
  join_miner · brain_graph                   metrics_gen (propose metrics)
  query_cache_curator (auto-promote)         drift baseline + schema contract
  serving_funnel · answer/query cache        metadata_indexing_job progress reuse
  Review tab + context builders              autotrain orchestrator (ds_id, table)
```

---

## New packages

```
  backend/app/services/ingest/                ← file → queryable table
    stage.py        hash file, manifest, NO db write
    contract.py     schema contract: drift / retype / rename → quarantine
    readers/
      excel_reader.py   5-layer (rules→LLM→fix→deepcell→rescue) + file-hash cache
      csv_reader.py
      parquet_reader.py
      doc_reader.py     pdf/pptx/docx → text + extracted tables
    loader.py       promote → staging.<table> + lineage cols
    gate.py         auto-promote EXACT / quarantine drift+dup+low-score

  backend/app/services/autotrain/             ← table → knowledge (source-agnostic)
    orchestrator.py   autotrain(ds_id, table, *, mode) — runs steps, tracks progress
    profiler.py       profile_v2 JSONB → datasource_table.metadata
    codex.py          read DDL/sample → {purpose,grain,PK,FK,freshness} → semantic
    qa_gen.py         LLM Q&A → EXECUTE via code_execution → keep verified → query lib
    metrics_gen.py    propose metrics → metrics catalog
    drift.py          baseline snapshot
    writeback.py      thin adapter → knowledge_proposer (status='pending')
```

Lineage columns stamped by `loader.py` on every uploaded row:
```
  _source_file  _period  _batch_id  _content_hash  _row_key  _ingested_at
  → enables idempotent re-upload + surgical undo (DELETE WHERE _batch_id=X)
```

---

## The one interface everything hangs off

```python
# app/services/autotrain/orchestrator.py
async def autotrain(
    db, data_source_id: str, table: str, *,
    mode: Literal["data","doc"] = "data",
    steps: list[str] | None = None,        # default: all enabled+flag-gated
    job_id: str | None = None,             # reuse metadata_indexing_job for progress
) -> AutotrainResult:
    """
    Source-agnostic. Called by BOTH:
      • file upload  → ingest → register datasource_table → autotrain(ds_id, table)
      • live connect → index  → register datasource_table → autotrain(ds_id, table)
    Every step: flag-checked, never-raises, writes status='pending'.
    """
```

Wiring at both producers:
```
  File upload  ─▶ ingest.promote ─▶ register datasource_table ─┐
                                                                ├▶ autotrain(ds_id, table)
  Live connect ─▶ index/refresh  ─▶ register datasource_table ─┘
  ── connector tables ALSO get auto verified-Q&A + semantic. Free upgrade for existing users.
```

---

## Migration

```
  alembic: extend chain from HEAD  sk3skillfiles1  →  at1autotrain
    + table  ingest_batch        (batch_id, ds_id, file_hash, status, manifest jsonb)
    + table  schema_contract     (logical_dataset, version, columns jsonb, ds_id)
    + table  upload_cache        (file_hash PK, plan jsonb, hit_count)   # excel rescue cache
    + col    datasource_table.metadata  (jsonb)  -- if absent: profile_v2 lands here
    + reuse  metadata_indexing_job        for autotrain progress (no new job table)
  RULE: Postgres-only SQL dialect-guarded → SQLite dev still migrates.
```

---

## Reuse map (don't rebuild)

```
  need                          reuse (exists)                         build
  ──────────────────────────────────────────────────────────────────────────
  background job + progress     metadata_indexing_job_service          —
  run SQL for Q&A verify        app/ai/code_execution/                  qa_gen orchestration
  pending knowledge writes      brain/knowledge_proposer.py            codex/qa_gen wrappers
  auto-promote pending→active   brain/query_cache_curator.py           —
  serve learned knowledge       brain/serving_funnel.py                —
  join graph / KG               knowledge/join_miner · brain_graph     —
  vectorless retrieval          knowledge/docs_index.py (FTS+Jaccard)  — (keep, no pgvector)
  approval UI                   Knowledge Review tab                   "pending" badge filter
  excel read (basic)            ExcelAgent + read_excel_as_csv         5-layer robustness
  file→view                     duckdb read_csv_auto                   loader→staging persist
```

---

## Frontend touchpoints (small)

```
  • Upload modal: add "Use as data" toggle → triggers ingest+autotrain (vs doc/add-in)
  • Knowledge → Review tab: rows already show; add source badge "auto-trained"
  • Progress: reuse metadata_indexing_job progress component (connector indexing already uses it)
  • Composer grounding chip already shows "Grounded on N of M tables" → auto-trained tables appear
  NO new page. All inside existing knowledge + upload surfaces.
```

---

## PR sequence (ship incrementally, each verifiable)

```
  P0  flag + migration                                            ½ day
      HYBRID_AUTOTRAIN in hybrid_flags.py (OFF). alembic at1autotrain.
      VERIFY: boots, flag OFF = zero behavior change, SQLite+PG both migrate.

  P1  ingest lane (CSV first) + loader                            2 day   ★ proves loop
      stage→csv_reader→loader→staging.<table> + lineage.
      register datasource_table for the new table.
      VERIFY: upload CSV → row in datasource_table → SELECT works in staging.

  P2  autotrain orchestrator + writeback (pending)               2 day   ★ proves "train"
      autotrain(ds_id, table): codex(DDL/sample)→pending semantic via knowledge_proposer.
      reuse metadata_indexing_job for progress.
      VERIFY: after P1 upload, pending semantic rows appear in Review tab.
      → END-TO-END: upload CSV → auto pending knowledge → approve → agent answers. DONE.

  P3  profile_v2 + lazy-on-miss                                  2 day
      profiler.py → datasource_table.metadata JSONB; lazy profile at query time on cache-miss.
      VERIFY: new table queried → profile auto-fills, no manual retrain.

  P4  verified Q&A + metrics_gen                                 2-3 day
      qa_gen: LLM Q&A → EXECUTE via code_execution → keep only runnable → pending query-lib.
      metrics_gen → pending metrics.
      VERIFY: pending verified Q&A rows; each one's SQL actually runs.

  P5  robust Excel reader + file-hash cache                      3 day
      5-layer reader replaces basic pandas path for ingest (MODE-3 only;
      keep MODE-1 doc + MODE-2 Office.js add-in untouched).
      VERIFY: messy multi-table xlsx ingests correctly; re-upload = cache hit, 0 LLM.

  P6  schema contract + drift + dataset consolidation            2 day
      contract.py: monthly re-drop → quarantine on retype/rename; strip period token →
      one _period-stamped table (not N siblings).
      VERIFY: upload Apr+May of same template → one table, 2 periods, no UNION needed.

  P7 (optional)  connector autotrain                             1 day
      call autotrain(ds_id, table) after connector index too → existing connector
      users get auto verified-Q&A + semantic for free.
```

Smallest valuable ship = **P0+P1+P2** (upload CSV → auto pending knowledge → approve → answer).

---

## Step coverage vs City‑Dash 14‑step

```
  City-Dash step            →  CityAgent autotrain        PR    reuse?
  ─────────────────────────────────────────────────────────────────────
  1 catalog / 2 profile     →  profiler.py (profile_v2)   P3
  3 dim catalog             →  profiler.py (DISTINCT)     P3
  4 hierarchy               →  profiler.py (opt)          P3
  5 sample                  →  codex.py (diverse rows)    P2
  6 codex enrich            →  codex.py                   P2
  7 Q&A verify              →  qa_gen.py                  P4    code_execution ✅
  8 relationships           →  (reuse join_miner)         —     ✅
  9 persona                 →  codex.py (project persona) P2/opt
  10 domain knowledge       →  metrics_gen + codex        P4
  11 KG triples             →  (reuse brain_graph)        —     ✅
  12 grounded facts         →  doc_reader → docs_index    P5    docs_index ✅
  13 drift baseline         →  drift.py + contract.py     P6
  14 register/emit tools    →  register datasource_table  P1
```

---

## Landmines checklist (this repo)

```
  [ ] OpenRouter ONLY for every LLM call (no other provider)
  [ ] VECTORLESS — FTS + Jaccard only, never add an embedding client
  [ ] every new path flag-gated HYBRID_AUTOTRAIN, default OFF
  [ ] every knowledge write status='pending' — never auto-inject unapproved
  [ ] never-raise: each step try/except, fail-soft (a bad step ≠ broken upload)
  [ ] alembic from HEAD sk3skillfiles1; Postgres-only SQL dialect-guarded
  [ ] no git → scripts/backup.sh <label> <files> before structural edits
  [ ] build image cityagent-analytics:dev; never pull bagofwords:latest
  [ ] keep Excel MODE-1 (doc) + MODE-2 (Office.js add-in) untouched — only ADD MODE-3
  [ ] source-agnostic: autotrain takes (ds_id, table), never a file path
```

---

## One-paragraph summary

CityAgent already has the **answer** stack (agents, context builders, brain, Review gate) and the **use‑time** auto‑learn (distiller / proposer / curator). The only missing half is City‑Dash's **train‑time** auto‑learn — the upload‑time pipeline that pre‑seeds knowledge before the first chat. Build it as two small packages (`ingest/` + `autotrain/`) behind `HYBRID_AUTOTRAIN`, make `autotrain(ds_id, table)` source‑agnostic so **both uploads and live connectors** get trained, and route every output through the **existing** `pending → curator → active` brain bus. First ship (P0‑P2) proves "upload CSV → auto‑trains → answer" using ~90% existing code; P3‑P7 raise answer quality (profile, verified Q&A, robust Excel, drift).
