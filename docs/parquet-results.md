# Parquet result storage

Large step result sets are stored as compressed **Parquet** files on disk instead
of inline JSON in Postgres. Shrinks the DB (and `pg_dump`), speeds dashboard loads,
and sets up future DuckDB-pushdown interactive queries. **Off by default**, fully
transparent, reversible.

## Flag + knob

| Name | Type | Default | Meaning |
|---|---|---|---|
| `HYBRID_PARQUET_RESULTS` | bool flag | **ON** | Master switch. Toggle in Settings → Feature Flags (Advanced) or env. |
| `HYBRID_PARQUET_MIN_ROWS` | env int | `2000` | Results with ≥ this many rows offload to Parquet; smaller stay inline JSON. |

Flag defined in `backend/app/settings/hybrid_flags.py` (`PARQUET_RESULTS`,
`PARQUET_MIN_ROWS`, `UPGRADE_FLAGS["HYBRID_PARQUET_RESULTS"]`, `snapshot()`).

## How it works

```
generate/refresh ─▶ agent runs SQL on LIVE source ─▶ format_df_for_widget()
                                                         │ {rows, columns, info}
                                                         ▼
                                              parquet_store.maybe_offload()
                                       small? ──────────────┬──────────── large + flag on?
                                          │                 │
                                  inline JSON          write_result(): COPY → uploads/parquet/<uuid>.parquet (zstd)
                                  step.data = {...}     step.data = {__parquet__:1, path, columns, info, rows:[]}
```

- **Inline path unchanged.** Below threshold or flag off → exactly today's behavior.
- **Offload marker** keeps `columns` + `info` inline (cheap: headers, counts) and
  empties `rows`; the rows live in the Parquet file.
- **Crash-safe:** file written before the row is committed. A missing file on read
  yields empty `rows` (treated as stale → re-run), never a hard error.

### Read (transparent hydrate)

`parquet_store.hydrate(data)` returns the full widget dict with `rows` loaded.
It's a no-op for inline/flag-off data, so it's safe to call anywhere.

Wired at every read site:
- `StepSchema` / `PublicStepSchema` `data` field validator → covers all schema-based
  routes (steps, widget `last_step`, query `default_step`, CSV export via `StepSchema`).
- Raw ORM readers patched: agent `load_step`/report-context (`loadables.py`),
  `widget_context_builder.py`, `thumbnail_service.py`, `report_pdf_service.py`,
  `slack_notification_service.py`.

Frontend needs **zero changes** — it still receives `step.data.rows`.

## Storage + lifecycle

- Files: `/app/backend/uploads/parquet/<uuid>.parquet`, on the **`ca_uploads`** Docker
  volume (persists across restarts/bakes).
- **Rerun** a step deletes its old file then writes the new one (`step_service`,
  `project_manager.update_step_with_data`).
- **GC:** `parquet_store.sweep_orphans(db)` deletes files not referenced by any
  `steps.data->>'path'`. Runs at the end of the daily
  `purge_step_payloads_per_organization` maintenance task (flag-gated).

## Backup (critical)

DB and the uploads volume must be snapshotted **together** — a restore that has the
DB but not the files leaves steps pointing at missing Parquet. `scripts/safe-upgrade.sh`
captures `db_<ts>.dump` + `vol_<ts>.tgz` (PG) + `uploads_<ts>.tgz` (files) in one run.

## Enable

1. Settings → Feature Flags → **Parquet Result Storage** ON (or `HYBRID_PARQUET_RESULTS=1`).
2. Optionally tune `HYBRID_PARQUET_MIN_ROWS`.
3. Applies to **new** results going forward; existing inline results stay inline
   until their step is re-run. Fully reversible — turning the flag off keeps reading
   existing Parquet markers (hydrate still works), just stops creating new ones.

## Not yet done (future phase)

- **DuckDB-pushdown interactive endpoint:** run filter/sort/aggregate as SQL over the
  Parquet file and return only the needed slice (instead of shipping all rows to the
  browser). The storage layer here is the prerequisite; the query endpoint is the
  follow-up that delivers the big dashboard-interactivity speedup.
- **Org-scoped paths** (`uploads/parquet/<org>/…`) for defense-in-depth (files are
  server-side only today; never served by a static route).
