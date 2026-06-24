# Autotrain — Build Progress

> What's built + LIVE-verified vs remaining. Plan: `AUTOTRAIN_BUILD_PLAN.md` / `AUTOTRAIN_PHASE_TASKS.md`.
> All flag-gated `HYBRID_AUTOTRAIN` (default OFF). Approval-only. Vectorless. OpenRouter-only.
> Snapshot: `.backups/20260620_225956_autotrain-p0-p2/`. Alembic head: `at1autotrain`.

## Status

| Phase | State | Verified |
|---|---|---|
| **P0** foundation | ✅ DONE | migration applied (`skillrun1 → at1autotrain`), 3 tables live, `import main` green (511 routes), flag OFF = no-op |
| **P1** ingest CSV + loader | ✅ DONE | LIVE: CSV → `staging.sales_apr` (3 rows + all 6 lineage cols, period-stamped) |
| **P1** route | ✅ DONE | `POST /api/autotrain/from-file` registered, server health 200, flag-gated |
| **P2** orchestrator + codex + writeback | ✅ DONE | LIVE: `autotrain()` (flag ON) → **pending** `SemanticTable` on Music Store DS |
| **P3** profiler | ✅ DONE | LIVE: profiles `staging.sales_apr` → 3 rows, dim/measure/id roles; default engine = write (pgbouncer-safe); fed metrics + persisted (profiled=True) |
| **P4** qa_gen | ✅ DONE | LIVE (real LLM): generated → executed → kept **8 verified** Q&A → 8 pending `query_library_items` |
| **P4** metrics_gen | ✅ DONE | LIVE: heuristic + LLM → 8 pending `metric_definitions`; wired in orchestrator codex step |
| **P5** excel_reader (5-layer) | ✅ DONE | LIVE: multi-sheet; **banner-row stripped** (Sales→[region,product,units]); clean sheet (Prices) ✓; route handles xlsx/xls (multi-table) |
| **P6** contract | ✅ DONE | LIVE: new/exact/**drift+retyped** verdicts; wired into route → quarantine on drift |
| **P6** drift | ✅ DONE | LIVE: make_baseline + compare (new/schema_drift); baseline stashed in batch manifest |
| **P1** register (agent-queryability) | ✅ DONE + PROVEN | restricted role `autotrain_ro` created (staging-only, public DENIED); wired into route; e2e: agent `get_client()` SELECT over `staging.e2e_sales` → count=6, SUM(revenue)=910.0 ✓ |

### E2E PROOF (2026-06-20) — upload → chat-queryable
```
CSV(6 rows) -> stage -> staging.e2e_sales -> autotrain(1 semantic +6 metrics +8 verified Q&A)
            -> register(restricted role autotrain_ro) -> approve
            -> agent client SELECT: count=6, SUM(revenue)=910.0  (matches seed) ✓
            -> cleanup: Music Store restored to original (SQLite Chinook only) ✓
SECURITY: autotrain_ro reads staging.* , DENIED on public.users/organizations (proven both
          direct + via pgbouncer auth_query). Connect host=ca-postgres:5432 (or pgbouncer).
CAVEAT(S) — both FIXED + PROVEN (2026-06-20):
  1. CLOBBER: register named ConnectionTable bare "<table>" but create_connection's
     background refresh_schema discovers schema-qualified "staging.<table>" -> deleted
     register's row + its DataSourceTable. FIX: build the staging Connection DIRECTLY
     (no create_connection -> no auto-index -> no clobber, and no cross-tenant full-staging
     scan) + name ConnectionTable "staging.<table>". 
  2. M:N LINK: data_source.connections.append() silently no-ops on the async lazy
     collection -> agent never got the staging client. FIX: direct idempotent
     INSERT INTO domain_connection (data_source_id, connection_id).
  PROOF (real agent path, selectinload connections -> get_client -> SELECT):
     mn_link=1 · agent_sees=['City Agent Staging','SQLite Chinook'] · count=5 · sum=846.5 ✓
  RESIDUAL (design, not a bug): `staging` schema is shared across orgs. No auto-index means
     the agent only sees ITS OWN registered tables, but the autotrain_ro role can SELECT any
     staging.* — a hand-crafted query could reach another org's table. For full isolation,
     move to a PER-ORG staging schema (staging_<orgid>) + per-schema grants. Recommended
     before multi-tenant prod.
```
Enable env: `AUTOTRAIN_STAGING_DB_USER=autotrain_ro` `AUTOTRAIN_STAGING_DB_PASSWORD=…`
`AUTOTRAIN_STAGING_DB_HOST=ca-postgres` `AUTOTRAIN_STAGING_DB_PORT=5432` (+ HYBRID_AUTOTRAIN/_QA/_PROFILE).
| FE "Use as data" toggle | ❌ not built | baked FE → needs image rebuild |

### P3–P6 verification log (2026-06-20)
```
P3 profiler   staging.sales_apr -> rows=3, roles: region/product=dimension, units/revenue=measure ✓
P4 qa_gen     orchestrator (LLM=claude-sonnet-4) -> qa=8 verified -> 8 pending query_library_items ✓
P4 metrics    -> 8 pending metric_definitions (heuristic total_/row_count/<measure>_by_<dim> + LLM) ✓
P5 excel      2-sheet xlsx: Sales (banner stripped) [region,product,units], Prices [sku,price] ✓
P6 contract   new->new, same->exact, retype units int64->object -> drift (retyped reported) ✓
P6 drift      compare new->new, add col -> schema_drift ✓
route         /api/autotrain/from-file handles csv + xlsx(multi-table) + contract gate + drift baseline ✓
server        ca-app restart -> health 200 (all modules live) ; smoke rows cleaned ✓
```

## Files (all on host + cp'd into ca-app, snapshotted)

```
backend/app/settings/hybrid_flags.py            +AUTOTRAIN / _QA / _PROFILE
backend/app/models/{ingest_batch,schema_contract,upload_cache}.py
backend/alembic/env.py                          +3 model imports
backend/alembic/versions/at1autotrain_autotrain_foundation.py
backend/app/services/ingest/{__init__,stage,csv_reader,loader,gate,contract,register}.py
backend/app/services/autotrain/{__init__,orchestrator,codex,writeback,profiler,qa_gen}.py
backend/app/routes/autotrain.py                 POST /api/autotrain/from-file
backend/main.py                                 +include_router(autotrain)
```

## LIVE verification log

```
P0:  alembic upgrade head      skillrun1 -> at1autotrain  ✓
     pg_tables                 ingest_batches, schema_contracts, upload_caches ✓
     import main               510 routes ✓
P1:  loader smoke              staging.sales_apr = 3 rows, cols incl
                               _source_file _period _batch_id _content_hash _row_key _ingested_at ✓
P2:  orchestrator.autotrain    summary semantics=[<id>] steps_run=[codex] ✓
     semantic_tables           ('sales_apr','pending','Table sales_apr with columns: region...') ✓
route: import main             511 routes, '/api/autotrain/from-file' present ✓
     ca-app restart            health 200 ✓
```

## The one decision before going live (register / agent-queryability)

`register.py` makes a `staging.<table>` queryable by the agent (ConnectionTable + DataSourceTable on a
managed-postgres Connection). **It refuses to run** unless `AUTOTRAIN_STAGING_DB_USER` /
`AUTOTRAIN_STAGING_DB_PASSWORD` are set to a **restricted Postgres role GRANTed only on `staging`** —
because a full-privilege Connection pointed at dash's own DB would let agent SQL read `public.users`, etc.
City-Dash's analytics_engine notes this role as "Phase 9". **Action to enable agent SQL over uploaded
tables:** create that role + GRANT USAGE/SELECT on `staging`, set the two env vars, then call `register_table`
from the route after `loader`. The knowledge half (codex → pending semantic/metrics) needs none of this and
is already safe + live.

## Durability — DONE (4b, 2026-06-21, BAKED + HTTP-PROVEN)

Image `cityagent-analytics:dev` rebaked from host source (build app + up -d --force-recreate
via build+scale composes). Verified durable:
```
env baked:  HYBRID_AUTOTRAIN=1 _QA=1 _PROFILE=1 · AUTOTRAIN_STAGING_{USER,PASSWORD,HOST,PORT} ✓
code baked: register.py M:N INSERT + all 15 ingest/autotrain modules in image (not cp) ✓
volume:     migration head at1autotrain · role autotrain_ro persist ✓
REAL HTTP E2E (curl in ca-app, baked server):
  POST /api/autotrain/from-file -> 200
  ok=true rows=5 registered=true staging_rows=5 pending_sem=1 pending_met=6 mn_link=1
  gate=promote · contract=new · autotrain{semantics:1, metrics:6, qa:8, profiled:true, errors:[]}
  cleanup restored Music Store to ['SQLite Chinook']
```
Config persisted: `.env` (dev flags ON + staging creds) + `docker-compose.build.yaml` app env
(`HYBRID_AUTOTRAIN/_QA/_PROFILE` + `AUTOTRAIN_STAGING_*`, default-OFF/empty so prod stays opt-in).
Snapshot `.backups/…_autotrain-baked-4b/`.
⚠️ `.env` holds the staging-role password in plaintext (dev). For prod use a real secret + rotate.

## FE "Use as data" — DONE (step 5, 2026-06-21, BAKED)

`frontend/components/knowledge/KnowledgePanel.vue` — added a **"⬆ Upload data"** button next to
**AI Suggest** (both nav layouts, gated on a pinned data source). Flow: pick CSV/xlsx → `POST /files`
(multipart, data_source_id) → `POST /autotrain/from-file` {file_id, data_source_id, load_key:'replace'}
→ note "Auto-trained <table> (N rows): X semantic + Y metrics + Z verified Q&A proposed — review in
the Review tab" → bumps `reviewRefreshKey` + switches to Review tab. 403 → "Auto-train is disabled".
Reuses existing `suggestNote`/`suggestError` banner + `reviewRefreshKey` (ReviewTab `:key`). Mirrors
`aiSuggest()` exactly; aiSuggest untouched. Baked: dist bundle `_nuxt/DWMwp0fB.js` contains
`autotrain/from-file`; :3007 health 200. Snapshot `.backups/…_autotrain-fe-toggle/`.

**User-facing loop now complete:** Knowledge → pick data source → ⬆ Upload data → CSV/xlsx auto-trains
→ pending semantic/metrics/Q&A land in Review → approve → agent queries the table.

## Per-org staging isolation — DONE + PROVEN + BAKED (2026-06-21)

Each org's uploads now land in a dedicated schema `staging_<orgid>`, readable only by that org's
own restricted login role `at_ro_<orgid>` (GRANT USAGE+SELECT on its schema only, REVOKE public).
- NEW `app/services/ingest/tenant_schema.py`: `ensure_org_staging(org_id)` (idempotent CREATE SCHEMA +
  role via DO-block + grants on a RAW admin engine — the guarded engine blocks CREATE SCHEMA/ROLE/GRANT).
  Role password = HMAC(AUTOTRAIN_STAGING_DB_PASSWORD, org_id) — deterministic, reconstructable.
- `loader.py` gained `schema=` kwarg; `register.py` + route thread the per-org schema/role; ConnectionTable
  named `<org_schema>.<table>`. Falls back to shared `staging` + skips register if no secret.
- CORE EDIT `analytics_engine.py`: write-guard `_is_writable_schema` now allows `staging_*` (CREATE/DROP
  SCHEMA + GRANT still always-blocked on the guarded engine).
- PROOF: `ISO_RESULT: A_reads_A=1 A_reads_B=DENIED` — org-A's role reads its own schema, permission-denied
  on org-B's schema. Hard tenant isolation. ✓

## P7 connector autotrain — DONE + PROVEN + BAKED (2026-06-21)

Existing live connector tables get the same auto pending knowledge (no upload, no register — already queryable).
- NEW `app/services/autotrain/connector.py` `autotrain_connector(...)`: reads columns from the catalog +
  sample/Q&A via the data_source's CLIENT (`get_client().execute_query` → DataFrame), codex description +
  heuristic metrics + verified Q&A (run against the live connector) → PENDING.
- NEW route `POST /api/autotrain/from-connector` {data_source_id, table?, max_tables=10}.
- PROOF (chinook Music Store, Artist): `P7_RESULT: sem=1 met=1 qa=5` — 5 verified Q&A executed against live
  SQLite (a 6th rejected for unsupported REGEXP = proof it runs on the real client). ✓

## Status: FEATURE COMPLETE
All baked into `cityagent-analytics:dev` (512 routes, health 200). Upload OR connector → autotrain →
pending → approve → agent queries, with per-org tenant isolation. Snapshots in `.backups/`.
Remaining (optional, not blockers): auto-fire P7 after connector indexing (currently manual endpoint);
UI surface for the from-connector endpoint (the from-file "⬆ Upload data" button is already live).

## Remaining phases (per plan)

- P4: `metrics_gen.py` + persist verified Q&A end-to-end (qa_gen wired, needs LLM live-run).
- P5: `excel_reader.py` 5-layer + file-hash cache (`upload_caches` table already exists).
- P6: `drift.py` + wire `contract.py` into the route (quarantine on retype/rename; consolidate monthly drops).
- P7: call `autotrain(ds_id, table)` after connector indexing too (free upgrade for connector users).
