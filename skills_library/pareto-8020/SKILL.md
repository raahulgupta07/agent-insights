---
name: pareto-8020
description: Pareto 80/20 analysis — rank items by a value column, compute cumulative share, and flag the vital few that drive ~80% of the total. Activate for "which products drive most revenue", "80/20", "top contributors", "concentration".
allowed-tools: run_skill_file read_skill_file describe_tables create_widget
category: revenue
---

# Pareto (80/20)

Finds the "vital few" items responsible for most of a total.

## Steps
1. Pick the dimension (e.g. product) and the value column (e.g. revenue).
   Use `describe_tables` if unsure.
2. Run the bundled analyzer — it sorts descending, computes cumulative % of total,
   and marks rows up to the 80% line as the vital few.
   → `run_skill_file(skill="pareto-8020", path="scripts/pareto.py")`
3. Returns: `item, value, share_pct, cum_pct, vital_few`. Chart value as bars +
   cum_pct as a line (Pareto chart) via `create_widget`.

## Data contract
Reads `(item, value)` via `ds_clients` when connected
(`execute_query("SELECT product AS item, SUM(revenue) AS value FROM sales GROUP BY product")`),
else a synthetic sample so the output shape is visible.
