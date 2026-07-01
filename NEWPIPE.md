# NEWPIPE.md — CityAgent Analytics Full Data Pipeline (15 phases)

> The end-to-end "ingest → train → serve" pipeline. Fixes the 3 chronic pains:
> **(1) Python crash again+again** = dependency drift + stdlib module-shadowing,
> **(2) KPIs not matching** = freehand ad-hoc SQL with no governed layer,
> **(3) want highest accuracy** = no golden/answer eval gate.
> Status legend: ✅ in product · 🔧 net-new graft · ⚙️ extend existing · 🧪 proven in prototype only.

---

## The 15 phases (target product pipeline)

```
P0 Upload → P1 Classify → P2 Ingest(dlt) → P3 Dedup/Merge → P4 Persist(parquet)
→ P5 Profile → P6 Quality-Gate → P7 Semantic → P8 Metrics → P9 Golden-Eval
→ P10 Agent-SQL → P11 Answer-Eval → P12 Durability → P13 Hybrid-Search
→ P14 Brain-Graph → (P15 Forecast = runtime on-demand)
```

| # | Phase | Real-app home | Status | Notes |
|---|---|---|---|---|
| P0 | Upload | `POST /api/files` → uploads volume | ✅ | durable |
| P1 | Classify | `smart_upload` classify (heuristic+LLM) | ✅ | conf log + Hold-for-Review |
| P2 | **Ingest (dlt)** | `routes/data_source_from_file.py` (pandas) | 🔧 | flag `INGEST_ENGINE=dlt`, DuckDB FILE not `:memory:` |
| P3 | **Dedup/Merge** | `merged_paths` JSON append | 🔧 | dlt `write_disposition="merge"` by `(_source_period + content-hash)` |
| P4 | Persist | `persist_upload_to_warehouse` + Parquet-results | ⚙️ | partition by `_source_period`, boot-rehydrate |
| P5 | Profile | profiling stage (pct 10/40) | ✅ | + drift snapshot |
| P6 | **Quality-Gate** | flag `HYBRID_INGEST_RECONCILE` | 🔧 | expectations: not-null keys, row>0, 6-period coverage, unique key |
| P7 | Semantic | `build_data_asset` / semantic layer | ✅ | governed dims+meanings from `Definitions.xlsx` |
| P8 | Metrics | `metric_definitions` | ✅ | KPI = locked filter, no freehand |
| P9 | **Golden-Eval** | verified-pipeline EVAL GATE | ✅ | golden number must == source-doc number |
| P10 | Agent-SQL | `agent_v2` + `resolve_metric` | ✅ | KPI→governed; ad-hoc→schema-link→revise |
| P11 | **Answer-Eval** | answer-time check | 🔧 | re-run governed measure, mismatch→DEGRADED, block fabrication |
| P12 | Durability | `scripts/backup.sh` + parquet | ✅ | pg_dump + uploads tar + rehydrate |
| P13 | **Hybrid-Search** | `train_orchestrator` stage `hybrid_index` (pct 99) | ✅ WIRED | reindex_org → tsv+pgvector, RRF k=60 |
| P14 | **Brain-Graph** | `train_orchestrator` stage `brain_graph` (pct 99) | ✅ WIRED | build_knowledge_graph + auto-publish edges |
| P15 | Forecast | `forecast_df` tool (statsmodels ETS) | ✅ ON | runtime/on-demand, tab transient by design |

---

## Proven results (real CRM data, 6 months Jan–Jun 2025, org Main Org `7d372305`)

```
Ingest      : 21,240 raw → 21,231 unique (9 byte-dups removed), idempotent (re-run = same)
KPIs locked : lead=1544  successful=7526  unsuccessful=4179   (EXACT vs source baseline)
Golden gate : caught wrong new_user 658→644, self-corrected (Recruitment-Call filter)
Answer eval : blocked 2/2 wrong numbers (stale-def + hallucination)
Hybrid idx  : 17 indexed + embedded (1 table + 5 metric + 11 query)
Brain graph : 10 edges published (metric↔table)
Forecast    : ETS 3-month projection + 95% bands, engine OK
```

### Root cause of "Python crash again+again" (found live)
```
1. numpy ABI drift  — `dlt` install bumped numpy→2.4.2 vs pandas → "No module named 'main'"
                      FIX: pin numpy<2.4
2. module shadowing — a stray `inspect.py` in cwd shadowed stdlib inspect → import chain dies
                      FIX: run from a clean dir, never name files after stdlib modules
```

---

## Combine plan (A+B+C) — make it real, pretty, verified, baked

| Step | Does | Source |
|---|---|---|
| **S1** | dlt ingest+merge graft, flag `INGEST_ENGINE=dlt` (pandas = default fallback) | P2+P3 |
| **S2** | quality-gate into `HYBRID_INGEST_RECONCILE` path | P6 |
| **S3** | answer-eval gate | P11 |
| **S4** | prettify graph edges → real metric/table names (not `metric:fa75…`) | B |
| **S5** | chain ALL 15 as ordered stages, master flag `HYBRID_FULL_PIPELINE` | sequence |
| **S6** | bake image `cityagent-analytics:dev` → permanent | C |
| **S7** | run ONE real train on CRM studio → all 15 fire | C+A |
| **S8** | verify in UI (Intelligence Search edges, index 17+, KPIs, forecast) | A |

**Order logic:** grafts first (chain needs them) → pretty before bake (ship pretty labels) →
chain → bake (makes S1-5 permanent) → train (fire once) → verify.

**One flag:** `HYBRID_FULL_PIPELINE=ON` → click Train → all 15 fire. OFF → upstream behavior.

---

## Two builds — what is product vs prototype

```
P0–P12 dlt pipeline   = SEPARATE prototype (scratchpad/p2run/*.py). Real data, NOT in product.
                        Files: dlt_ingest.py, semantic_layer.yaml, agent_sql.py, eval_gate.py, backup.sh
P13–P15 + DB rows     = LIVE in product (ca-app + ca-postgres). EPHEMERAL orchestrator edits (not baked).
```

### Live-in-UI map
```
Brain Graph   → Studio → Intelligence → Search/Graph tab   (10 edges render)
Hybrid Search → Settings → Features → Rebuild index         (17 indexed)
Forecast      → chat: "forecast next 3 months"              (tab blank by design)
Code Enrich   → still blank (flag OFF by cost; flip HYBRID_CODE_ENRICH + retrain)
```

---

## Backup / rollback (taken before replace, 2026-06-30)

```
scratchpad/pipeline_backup_20260630_215541/
  dash_full.sql.gz (494KB) · uploads.tgz (14.7MB/149 files) · source/*.py (4) · state_before.txt
docker image  cityagent-analytics:rollback-20260630_215541
git tag       pre-full-pipeline-20260630_215541

ROLLBACK:
  DB    gunzip < dash_full.sql.gz | docker exec -i ca-postgres psql -U dash -d dash
  CODE  cp source/*.py back → docker cp → docker restart ca-app
  IMAGE compose up with rollback image
  GIT   git checkout pre-full-pipeline-20260630_215541
```

---

## Landmines specific to this pipeline
1. **uploads volume = `cityagentanalytics_ca_uploads`** (NOT `ca_uploads` — that's empty/stale).
   Postgres vol = `cityagentanalytics_ca_postgres_data`.
2. **Standalone in-container scripts:** `cd /app/backend && PYTHONPATH=/app/backend python s.py`,
   and `import main` FIRST (registers all ORM mappers; bare `import app.models` misses `Completion`/`Application`).
3. **4 uvicorn workers:** a flag override patches ONE worker → ONE `docker restart ca-app` to converge.
4. `SEMANTIC_SEARCH` and `FORECAST` DO have `@property` accessors, default **True** (a prior agent
   report wrongly said OFF). Real blockers were empty index/edges + the approval/publish gate.
5. orchestrator edits are EPHEMERAL (hot-cp) — `--force-recreate`/rebuild WIPES them until baked.
6. Graph edges from `build_knowledge_graph` are `status='draft'`; the Intelligence tab shows all
   statuses but the agent `neighbors()` reads published-only → must auto-publish.
