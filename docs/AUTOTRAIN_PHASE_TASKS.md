# Autotrain — Phase‑by‑Phase Sub‑Task Plan

> Granular task breakdown for the autotrain port (see `AUTOTRAIN_BUILD_PLAN.md` for design).
> Every task: file · action · verify. Flag `HYBRID_AUTOTRAIN` (OFF). Approval‑only. Vectorless. OpenRouter‑only.
> Convention: `[ ]` todo. Each phase ends GREEN before next. Snapshot via `scripts/backup.sh` before each phase.

---

## PHASE 0 — Foundation (flag + migration + skeleton)  · ½ day

```
P0.1  [ ] add HYBRID_AUTOTRAIN flag → app/settings/hybrid_flags.py (default False, env HYBRID_AUTOTRAIN)
P0.2  [ ] alembic rev: chain HEAD sk3skillfiles1 → at1autotrain
            tables: ingest_batch, schema_contract, upload_cache
            col:    datasource_table.metadata jsonb  (add if absent)
            ALL Postgres-only SQL dialect-guarded (SQLite dev still migrates)
P0.3  [ ] create empty pkgs: app/services/ingest/__init__.py · app/services/autotrain/__init__.py
P0.4  [ ] models: app/models/ingest_batch.py · schema_contract.py · upload_cache.py (SQLAlchemy)
P0.5  [ ] backup.sh snapshot label "pre-autotrain"
VERIFY: app boots · flag OFF = zero behavior change · `alembic upgrade head` on BOTH PG + SQLite
```

---

## PHASE 1 — Ingest lane (CSV) + loader  · 2 day  ★ proves loop

```
P1.1  [ ] ingest/stage.py
            - sha256 the upload, write batch manifest jsonb → ingest_batch (status='staged')
            - dedup: if file_hash seen → skip, return existing
P1.2  [ ] ingest/readers/csv_reader.py
            - read_csv (chardet encoding detect, delimiter sniff) → DataFrame
            - normalize nulls (N/A, -, NULL → NaN)
P1.3  [ ] ingest/loader.py
            - target: `staging` schema (PG) OR a project .duckdb (reuse duckdb_client path)
            - DataFrame → staging.<safe_table>  (idempotent: load_key period|content_hash)
            - stamp lineage cols: _source_file _period _batch_id _content_hash _row_key _ingested_at
            - decide PG-table vs DuckDB-view by org/data-source type (1 config switch)
P1.4  [ ] ingest/gate.py  (minimal v1)
            - quality score (row count, null%, unnamed cols) → quarantine if score<10 & rows<5
            - else status='promoted'
P1.5  [ ] register table in catalog
            - create/refresh DataSource + datasource_table row for the new staging table
            - reuse data_source_service / metadata_resource patterns
P1.6  [ ] route: POST /api/files/{id}/use-as-data  (flag-gated)
            - calls stage → csv_reader → loader → gate → register
            - reuse metadata_indexing_job for progress
P1.7  [ ] FE: upload modal "Use as data" toggle → hits P1.6 (only when flag ON)
VERIFY: upload CSV → ingest_batch row · staging.<table> exists · datasource_table row ·
        `SELECT * FROM staging.<table> LIMIT 5` returns rows w/ lineage cols
```

---

## PHASE 2 — Autotrain orchestrator + codex → pending  · 2 day  ★ proves "train"

```
P2.1  [ ] autotrain/orchestrator.py
            async autotrain(db, data_source_id, table, *, mode='data', steps=None, job_id=None)
            - step registry (list of (name, fn, flag)); each wrapped try/except never-raise
            - progress via metadata_indexing_job (one row, step|index|total)
P2.2  [ ] autotrain/codex.py
            - read DDL (information_schema) + diverse sample (3 head/3 mid/3 tail) via code_execution
            - LLM (OpenRouter) → {purpose, grain, PK, FK, freshness, column descriptions}
P2.3  [ ] autotrain/writeback.py
            - thin adapter → brain/knowledge_proposer.propose_knowledge_from_schema
            - ALL rows status='pending' (semantic descriptions + use-cases)
P2.4  [ ] wire: P1.6 ingest success → autotrain(ds_id, table) (fire after register)
P2.5  [ ] FE: Knowledge → Review tab badge "auto-trained" (source filter)
VERIFY: upload CSV (P1) → pending semantic rows appear in Review tab ·
        approve one → agent uses it in an answer
★ END-TO-END MILESTONE: upload → auto-train → approve → answer. DONE with ~90% reuse.
```

---

## PHASE 3 — profile_v2 + lazy-on-miss  · 2 day

```
P3.1  [ ] autotrain/profiler.py
            - combined-query per-col stats (count, distinct, min, max, avg, null%, percentiles)
            - classify dimension | measure | id ; pull top-N distinct for dims (<500 uniq)
            - write JSONB → datasource_table.metadata['profile_v2']
P3.2  [ ] add 'profile' + 'dim_catalog' steps to orchestrator (P2.1 registry)
P3.3  [ ] lazy-on-miss: at query/context-build time, if table lacks profile_v2 → run profiler inline
            (port LAZY_PROFILE pattern; cap N tables; kill-switch env)
P3.4  [ ] context builder: inject compact profile_v2 (~80 char/col) into agent prompt (flag-gated)
VERIFY: add table post-train → first query auto-profiles (+~1s) → no manual retrain ·
        prompt shows dims/measures/top-values
```

---

## PHASE 4 — Verified Q&A + metrics  · 2-3 day

```
P4.1  [ ] autotrain/qa_gen.py
            - LLM generates question→SQL pairs from profile + semantic
            - EXECUTE each SQL via code_execution → keep ONLY runnable (verified)
            - strip markdown fences; reject DROP/DDL; read-only
P4.2  [ ] writeback verified Q&A → query library (status='pending')  (reuse query_cache_store shape)
P4.3  [ ] autotrain/metrics_gen.py
            - propose named metrics {name, definition, sql_calc} → metrics catalog (status='pending')
P4.4  [ ] add 'qa_verify' + 'metrics' steps to orchestrator
P4.5  [ ] FE: Review tab shows pending Q&A + metrics with "✓ verified" tag (SQL ran)
VERIFY: pending verified Q&A rows exist; re-run each one's SQL → all succeed ·
        approve a metric → agent uses it
```

---

## PHASE 5 — Robust Excel reader (MODE-3 only)  · 3 day

```
P5.1  [ ] ingest/readers/excel_reader.py — Layer 1 rules
            - header detect, banner-row strip, multi-table split on blank gaps, unpivot months→rows
P5.2  [ ] Layer 2 LLM structure plan when rules unsure
P5.3  [ ] Layer 3 validate_dataframe (NaN%, subtotals, unnamed) + auto_fix
P5.4  [ ] Layer 4 deep_extract (openpyxl unmerge + bold/color metadata → LLM re-plan)
P5.5  [ ] Layer 5 LLM rescue when actual_rows < 10% expected + write upload_cache (file-hash plan)
P5.6  [ ] Layer 5b: on re-upload, file-hash cache hit → reuse plan, 0 LLM (cross-tenant)
P5.7  [ ] route excel uploads in "Use as data" path → excel_reader (KEEP MODE-1 doc + MODE-2 add-in untouched)
VERIFY: messy multi-table xlsx → correct tables · banner rows dropped · months unpivoted ·
        re-upload same file → cache hit (0 LLM) · Office.js add-in + doc-read still work
```

---

## PHASE 6 — Schema contract + drift + consolidation  · 2 day

```
P6.1  [ ] ingest/contract.py
            - infer_contract (col names+types) → schema_contract (versioned per logical dataset)
            - check_against_contract → verdict exact | drift | new ; diff added/removed/retyped/renamed
P6.2  [ ] gate.py: drift/retype/rename → quarantine (don't corrupt existing table)
P6.3  [ ] logical-dataset consolidation
            - strip period token from filename ("MM Conso Apr 25" → "mm_conso")
            - same dataset → ONE table + _period stamp (load_key=period: DELETE WHERE _period then load)
P6.4  [ ] autotrain/drift.py — baseline snapshot (schema + value distribution) for future drift alerts
VERIFY: upload Apr + May of same template → ONE table, 2 periods (no N siblings, no UNION) ·
        rename a column on re-upload → quarantined, old table intact
```

---

## PHASE 7 (optional) — Connector autotrain  · 1 day

```
P7.1  [ ] after connection_indexing_service.refresh_schema → call autotrain(ds_id, table) per table
            (flag-gated, throttled, only new/changed tables)
P7.2  [ ] dedup: skip tables already auto-trained (fingerprint)
VERIFY: connect a live Postgres → after index, pending verified-Q&A + semantic appear for its tables
        → existing connector users get the upgrade for free
```

---

## Cross-cutting (every phase)

```
X.1  [ ] each step try/except → fail-soft (bad step ≠ broken upload); log, continue
X.2  [ ] each step flag-checked (sub-flags optional: HYBRID_AUTOTRAIN_QA, _PROFILE, ...)
X.3  [ ] all knowledge writes status='pending' — never auto-live
X.4  [ ] OpenRouter only for every LLM call
X.5  [ ] vectorless — no embedding client; rank FTS + Jaccard
X.6  [ ] unit tests per pure module (stdlib-importable, like skills S1-S5 pattern)
X.7  [ ] backup.sh before each phase; build cityagent-analytics:dev to verify, never bagofwords:latest
X.8  [ ] migrations Postgres-only-guarded → SQLite dev migrates
```

---

## Milestone map

```
  SHIP 1 (P0+P1+P2)   upload CSV → auto-train → approve → answer      ~4.5 day   ← MVP, ~90% reuse
  SHIP 2 (+P3+P4)     profiled + verified-Q&A quality                 +4-5 day
  SHIP 3 (+P5)        robust Excel ingest                             +3 day
  SHIP 4 (+P6)        drift-safe monthly re-drops                     +2 day
  SHIP 5 (+P7)        connectors auto-trained too                     +1 day
  ──────────────────────────────────────────────────────────────────────────
  total full port  ≈  16-17 dev-day, incremental, each ship usable
```

## Dependency order

```
  P0 ─▶ P1 ─▶ P2 ─▶ P3 ─▶ P4
                │           └─▶ P7 (needs P2..P4 steps)
                └─▶ P5 (excel feeds P1 ingest)
                └─▶ P6 (contract guards P1 loader)
  P5, P6 independent after P1; P7 last (needs autotrain steps mature)
```
