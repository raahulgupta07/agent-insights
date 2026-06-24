---
name: anomaly-detection
description: Flag spikes and dips in a numeric series via z-score + IQR. Activate for "anomaly", "outlier", "anything weird", "unusual", "spike".
allowed-tools: run_skill_file read_skill_file inspect_data create_widget
category: diagnostic
---

# Anomaly Detection

Finds unusual points in a numeric time/series — values that jump far above or
fall far below the norm — using two complementary methods.

## Steps
1. Identify the series: a period/date column and the numeric value to watch
   (e.g. daily `amount`). Use `inspect_data` if you don't know the columns.
2. Run the bundled detector: it computes the mean & std, a per-row z-score,
   and IQR fences, then flags any point with `|z| >= 3.0` OR outside the
   IQR fence as an anomaly (spike if above the mean, dip if below).
   → `run_skill_file(skill="anomaly-detection", path="scripts/anomaly.py")`
3. The script returns the FULL series as a tidy DataFrame:
   `period, value, z_score, is_anomaly, method, direction`, sorted by period.
   Chart it with `create_widget` (line of `value` over `period`, mark the
   `is_anomaly` rows) and call out the flagged spikes/dips in plain language.

## Data contract
The script reads via the injected `ds_clients` when available
(`execute_query("SELECT order_date, amount FROM orders")`). With no data
source connected it runs on a synthetic daily series with a couple of planted
spikes and a dip so the detection is always visible. Swap the demo query for
the real one once a source is connected.

- `z_score` = (value − mean) / std, rounded to 2 (guards std == 0).
- `is_anomaly` = `abs(z) >= 3.0` (override via `z_thresh`) **OR** an IQR
  outlier (`value < Q1 − 1.5·IQR` or `value > Q3 + 1.5·IQR`).
- `method` names which test(s) fired (`zscore`, `iqr`, or `zscore+iqr`).
- `direction` is `spike` (≥ mean) or `dip` (< mean); empty for normal rows.
- The script prints `rows: <N> anomalies: <K>` so the count is always logged.
