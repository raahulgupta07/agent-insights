---
name: kpi-snapshot
description: Headline KPIs for the current period with delta vs the prior period (total, orders, avg order value) from a date+amount table. Activate for "current revenue", "this month", "KPIs", "how are we doing".
allowed-tools: run_skill_file read_skill_file describe_tables resolve_metric create_widget
category: descriptive
---

# KPI Snapshot

Headline metrics for the current period (latest month) compared to the prior
month — a one-glance "how are we doing" card.

## Steps
1. Identify the orders/transactions table and its keys: an order/event date and
   a numeric amount. Use `describe_tables` if you don't know them; use
   `resolve_metric` if the org has a defined revenue/amount metric.
2. Run the bundled builder: it splits rows into the latest month (current) vs
   the month before (prior) and computes Total (sum amount), Orders (row count)
   and Avg Order Value (mean amount) for each, plus the delta.
   → `run_skill_file(skill="kpi-snapshot", path="scripts/kpi.py")`
3. The script returns one row per KPI: `kpi, current, prior, delta, delta_pct,
   direction` (up/down/flat). Render it with `create_widget` as a KPI/stat card
   row (current value + delta arrow per KPI).

## Data contract
The script reads via the injected `ds_clients` when available
(`execute_query("SELECT order_date, amount FROM orders")`). With no data source
connected it runs on a small synthetic sample spanning at least two months so
the shape is always visible. Swap the demo block for the real query once a
source is connected. Output columns: `kpi` (Total | Orders | Avg Order Value),
`current`, `prior`, `delta`, `delta_pct` (null when prior is 0), `direction`.
