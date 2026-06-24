# Autotrain Review — Fix Plan (all H/M/L)

> Fixes for the review findings. Engine architecture is the core change; everything else hangs off it.

## Core idea: 3-engine split (fixes H2 + H3 + M6 together, reverts the risky core widening)

```
AGENT engine   get_analytics_write_engine()  guarded {analytics, staging} ONLY (REVERT staging_* widening)
               -> the Engineer agent's view-builder. Cannot write staging_<otherorg>. (M6 closed)
LOADER engine  NEW raw server engine (superuser, NO write-guard) used ONLY by loader.py with a
               SERVER-DERIVED schema (staging_<org>). Quoted idents work (H2 solved — no guard on it).
READ engine    NEW per-org restricted RO engine (role at_ro_<org>, search_path=staging_<org>, NO public)
               -> codex / profiler / qa_gen run their SELECTs here. LLM-generated SQL physically cannot
                  read public.* (role lacks USAGE) (H3 closed).
```

## Batch A — engines + isolation (CORE, me)
- `analytics_engine.py`: REVERT `_is_writable_schema` staging_* widening → back to `{analytics, staging}`. (M6, and H2-via-guard becomes moot.)
- `tenant_schema.py`:
  - `org_read_engine(org_id)` → cached create_engine as `at_ro_<org>` w/ `search_path=staging_<org>` (no public).
  - `loader_write_engine()` → cached raw superuser engine (no write-guard) for loader.
  - H4: `_secret()` requires `AUTOTRAIN_STAGING_ROLE_SECRET` (drop DB-pw fallback; warn+raise if unset). Harden role: `NOINHERIT NOCREATEDB NOCREATEROLE NOSUPERUSER NOBYPASSRLS` + `REVOKE ALL ON ALL TABLES IN SCHEMA public`.
- `.env` + compose: add random `AUTOTRAIN_STAGING_ROLE_SECRET`.

## Batch B — correctness (subagent 1, owns orchestrator.py)
- H1: `_persist_qa` → `seen` dedup + `async with db.begin_nested()` SAVEPOINT per insert (IntegrityError rolls back only that row; shared session stays usable). Same for `_persist_profile`.
- H3 wire: codex/profiler/qa get the per-org READ engine (when schema startswith `staging_`); fall back to write engine for shared `staging`.
- M5: wrap sync sub-calls (`profiler.profile_table`, `codex.codex_enrich`, `qa_gen.generate_verified_qa`, the LLM `inference`) in `await asyncio.to_thread(...)`.

## Batch C — loader + readers (subagent 2, owns loader.py + csv_reader.py + excel_reader.py)
- loader: use `tenant_schema.loader_write_engine()` (raw) instead of `get_analytics_write_engine()`. M3: `pg_advisory_xact_lock(hashtext(schema||'.'||tbl))` around load to serialize concurrent same-table.
- M2: skip numeric coercion when column name is id-like (id/code/zip/postal/phone/sku/account/_id) OR values have leading zeros OR exceed 2^53. (csv_reader + excel_reader `_clean_frame`.)
- L4: `safe_table_name`/`_safe_table` add a short hash suffix when slug degenerates to `t_`/`table`.

## Batch D — route + FE (subagent 3, owns autotrain.py route + KnowledgePanel.vue)
- M1: top-level `degraded: bool` + `knowledge_errors: [...]` when any result's `autotrain.errors` non-empty or sem+met+qa all 0; fix `note`.
- M4: wire drift — on re-upload, load prior promoted batch's `manifest.baseline` for the logical dataset, `drift.compare_baseline`, surface `drift` in result. (Or remove if too heavy — prefer wire.)
- M5 (route side): `await asyncio.to_thread(loader.load_dataframe_to_staging, ...)` + `tenant_schema.ensure_org_staging` in thread.
- L3: drop the dead `infer_contract_from_columns` hasattr branch → call `contract.infer_contract`-style on columns directly.
- M7 + FE1/FE5: check `error` on the `/files` upload call; show quarantine message from `results[0].quarantined` (per-result, not top-level).

## Batch E — low/cleanup (me, after)
- L1: partial-unique handling — catch IntegrityError on Connection create + re-fetch (register); partial-unique idx note for SchemaContract (or ON CONFLICT).
- L2: quote `schema` in codex `_read_schema_and_sample`.
- L5: upload byte cap (note; add a max-bytes guard in route before read) — document if file_service already caps.

## Verify after
- re-run write-guard test (now reverted → only analytics/staging allowed; loader uses raw engine).
- H3 proof: as at_ro_<org>, `SELECT FROM public.users` via the read engine → DENIED.
- H1: persist 2 identical question names → no session poison (savepoint), 1 row kept.
- re-run full HTTP e2e (from-file) + from-connector → still green.
- bake.

## STATUS — ALL FIXED + VERIFIED + BAKED (2026-06-21)

```
FIX_VERIFY: zip_text=True qa=8 sem=1 met=6 h3_denied=True h1_session_ok=True errors=[]
```
| id | fixed | proof |
|----|-------|-------|
| H1 | ✅ savepoint(begin_nested)+seen dedup in _persist_qa | dup question -> session usable, not poisoned |
| H2 | ✅ loader uses raw loader_write_engine (no guard) | quoted/reserved table names load (guard no longer in path) |
| H3 | ✅ codex/profiler/qa run via per-org RESTRICTED read engine (search_path=staging_<org>, no public) | `SELECT public.users` -> permission denied |
| H4 | ✅ dedicated AUTOTRAIN_STAGING_ROLE_SECRET required (no DB-pw fallback) + role NOINHERIT/NOCREATE*/NOSUPERUSER/NOBYPASSRLS + REVOKE public tables | role_secret required; ensure_org_staging hardened |
| M1 | ✅ top-level `degraded`+`knowledge_errors` | route no longer claims success on empty/errored |
| M2 | ✅ _should_skip_numeric (id-name/leading-zero/>2^53) csv+excel | zip '02115' stays text |
| M3 | ✅ pg_advisory_xact_lock(schema.table) around load | concurrent same-table serialized |
| M4 | ✅ drift.compare_baseline wired vs prior batch baseline | surfaces `drift` verdict |
| M5 | ✅ asyncio.to_thread on loader/profiler/codex/qa/ensure | event loop unblocked |
| M6 | ✅ write-guard REVERTED to {analytics,staging} | agent can't write staging_<other> (guard staging_x=False) |
| M7 | ✅ FE: /files error check + per-result quarantine msg + degraded surface | |
| L2 | ✅ codex schema quoted | |
| L3 | ✅ dead infer_contract_from_columns branch removed | |
| L4 | ✅ degenerate slug -> t_<hash>/table_<hash> | no empty-slug collisions |
| BONUS | ✅ qa_gen hardcoded `staging.<table>` -> now schema-threaded | qa works on per-org schema (was latent-broken) |

ACCEPTED-LOW (not fixed, documented):
- L1: concurrent first-ever upload -> 2 staging Connections (uq race) -> loser's register skipped (table still
  loaded+autotrained, just not agent-queryable that one time; non-corrupting). SchemaContract dup-active under
  race. Narrow; revisit with a partial-unique idx / ON CONFLICT if it surfaces.
- L5: no explicit upload byte cap in the autotrain path (whole-file in RAM). file_service/Caddy body limits apply;
  add an explicit max-bytes guard for very large xlsx if needed.

BAKED: cityagent-analytics:dev rebuilt + force-recreated. health 200, secret in env, guard reverted, 512 routes.
Snapshot `.backups/…_autotrain-review-fixes/`.
