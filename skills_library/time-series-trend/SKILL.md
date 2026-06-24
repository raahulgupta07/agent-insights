---
name: time-series-trend
description: Monthly trend with MoM %, YoY %, and a 3-month moving average from any date+value table. Activate for "trend", "over time", "growth", "month over month", "seasonality".
allowed-tools: run_skill_file read_skill_file describe_tables create_widget
category: descriptive
---

# Time-Series Trend

Turns any date+value table into a monthly trend line with momentum signals.

## Steps
1. Identify the source table and its two keys: a date/timestamp column and a
   numeric value column (revenue, amount, count, …). Use `describe_tables` if
   you don't know them.
2. Run the bundled builder: it resamples the value to MONTHLY buckets (sum),
   then computes month-over-month %, year-over-year % (vs 12 months prior when
   available), and a 3-month moving average.
   → `run_skill_file(skill="time-series-trend", path="scripts/trend.py")`
3. The script returns a tidy DataFrame: `period, value, mom_pct, yoy_pct, roll3`.
   Render it with `create_widget`: plot `value` as bars and `roll3` as an
   overlaid line, x-axis = `period`.

## Data contract
The script reads via the injected `ds_clients` when available
(`execute_query("SELECT order_date, amount FROM orders")`). With no data source
connected it runs on a synthetic 12+ month sample so the shape is visible. It
uses the first two columns of whatever frame it gets (col 0 = date, col 1 =
value), coercing types, so swap the demo query for your real table once a source
is connected.
