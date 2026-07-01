# INBOX — deferred / future work

Running list of approved-but-not-yet-done work. Newest on top.

---

## SQL-guard permanent fix — remaining phases (2026-06-30)

Context: chat `create_data` failed with `Security violation (unsafe_python): Forbidden SQL operation 'Call Rate (' ...` on a column named `"Successful Call Rate (%)"`. Root cause = AST guard scanned EVERY python string literal for SQL keywords → false-positive on data/column names (unbounded, leaky by design).

**DONE (live local, EPHEMERAL — not yet baked):**
- Phase 1 — scoped SQL-write scan to executor call-sites only (`code_execution.py`, `SQL_EXECUTOR_CALLS`). Free-floating literals (column names/titles/keys) never scanned. Permanent kill of the false-positive class, dialect-agnostic.
- Phase 3 — regression test `backend/tests/test_sql_guard_scoping.py` (8 allow + 8 block + 5 escape, all pass standalone).
- Backup: `backups/sql-guard-permfix/code_execution.py.bak`.

**TODO:**

### Phase 2 — Write-impossible boundary (the real guarantee) — medium risk
Read-only enforcement at the SQLAlchemy connect layer (shared helper in `data_sources/clients/base.py`), per-dialect:
- PG / MySQL / MariaDB / Oracle → `SET TRANSACTION READ ONLY`
- SQLite → `PRAGMA query_only = ON`
- MSSQL → applies-intent / documented gap
- Snowflake / Trino / Presto / Redshift / Teradata / Vertica / ClickHouse / Databricks → per-dialect read-only stmt or warehouse role
- DuckDB already read-only ✓ · federation PG attach already `READ_ONLY` ✓
- Rollout: PG first, then live SQL clients. API "other" connectors = no SQL-write surface, N/A.
- Gate: setting `SQL_READ_ONLY_ENFORCE` default ON, flip-off escape hatch.
- ~20 clients. Needs its OWN per-dialect test pass (a bad read-only stmt could break all queries for that connector). Do NOT bundle into an urgent fix.

### Phase 4 — DB-role belt (ops) — low risk, optional
Warehouse/analytics login → SELECT-only grant. App-bypass still can't write. Defense-in-depth.

### Phase 5 — Verify → bake → ship (do whenever baking next)
1. Verify: regression test + `curl :3007/health` + 4 delivery modes.
2. Rollback tag: `docker tag cityagent-analytics:dev cityagent-analytics:pre-guardfix`.
3. Bake: `docker commit ca-app cityagent-analytics:dev` — bundles guard-fix + plan-leak + merged-panel + autopilot-v2.
4. Local confirm: restart from baked image, re-check health + column-name case.
5. Ship to AWS (`13.251.74.176`): fast = `docker cp code_execution.py` + restart; clean = push image → AWS pull → force-recreate.

### Cleanup
- Wire `test_sql_guard_scoping.py` into CI without the DB conftest fixture (autouse `run_migrations` breaks on sqlite — `NotImplementedError: No support for ALTER of constraints in SQLite`). Mark `no_db` / skip migrations for this pure-function test.

---

## Other pending (carried from prior sessions)
- BAKE all EPHEMERAL FE/BE into `cityagent-analytics:dev`: plan-leak fix (`reports/[id]/index.vue:387`), merged Create/Activity panel, Auto-pilot v2 (flag `HYBRID_AUTOPILOT_V2` ON org e02b1b04).
- Re-ingest 5 missing months (Jan/Feb/Mar/May/Jun) + 1 held inbox file into CRM source `0b9b39ac` (April-only partial-ingest fix).
- VERSION_HYBRID + CHANGELOG_HYBRID bump + DEVLOG entry for shipped features.
