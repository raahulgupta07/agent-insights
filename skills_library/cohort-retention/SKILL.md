---
name: cohort-retention
description: Build a cohort retention matrix from an orders/events table — group customers by first-activity month, then measure what % return in each later month. Activate for "retention", "cohort", "repeat customers", "churn over time".
allowed-tools: run_skill_file read_skill_file describe_tables create_widget
category: behavioral
---

# Cohort Retention

Measures how groups of customers (cohorts) keep coming back over time.

## Steps
1. Identify the events table and its keys: a customer id, an event/order date.
   Use `describe_tables` if you don't know them.
2. Run the bundled builder: it groups each customer by their FIRST month
   (the cohort), then counts how many are active in each subsequent month and
   divides by the cohort size → a retention % matrix.
   → `run_skill_file(skill="cohort-retention", path="scripts/cohort.py")`
3. The script returns a tidy DataFrame: `cohort, month_index, active, retention_pct`.
   Render it as a heatmap with `create_widget` (pivot cohort × month_index).

## Data contract
The script reads via the injected `ds_clients` when available
(`execute_query("SELECT customer_id, order_date FROM orders")`). With no data
source connected it runs on a small synthetic sample so the shape is visible.
Swap the demo block for the real query once a source is connected.
