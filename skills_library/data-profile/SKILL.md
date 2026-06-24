---
name: data-profile
description: Profile any table — per-column dtype, null %, distinct count, and a sample value — to understand data shape before analysis. Activate for "profile", "data quality", "what's in this table", "describe the data".
allowed-tools: run_skill_file read_skill_file describe_tables
category: profiling
---

# Data Profile

Gives a one-glance health check of a table: for every column, its type, how
complete it is, how many distinct values it holds, and an example value.

## Steps
1. Find the table and its columns. Use `describe_tables` if you don't know
   what's available, then point the script's query at the right table.
2. Run the bundled profiler: it loads the table (capped at 5000 rows) and emits
   one row per column with `dtype`, `non_null`, `null_pct`, `distinct`,
   `sample_value`.
   → `run_skill_file(skill="data-profile", path="scripts/profile.py")`
3. Review the per-column report: high `null_pct` flags missing data, `distinct`
   near the row count flags an id/key column (≈1 flags a constant), and
   `sample_value` shows the actual shape of each field.

## Data contract
The script reads via the injected `ds_clients` when available
(`execute_query("SELECT * FROM orders LIMIT 5000")`). With no data source
connected it runs on a small synthetic sample so the profile shape is always
visible. Swap the demo query for your real table once a source is connected.
It returns a tidy DataFrame: `column, dtype, non_null, null_pct, distinct,
sample_value`.
