---
name: funnel-analysis
description: Step-by-step funnel conversion + drop-off between stages from an events table — per-stage user counts, conversion vs the previous step, overall conversion, and users lost. Activate for "funnel", "conversion", "drop-off", "where do users leave".
allowed-tools: run_skill_file read_skill_file describe_tables create_widget
category: behavioral
---

# Funnel Analysis

Measures how users move through an ordered sequence of stages and where they
drop off between stages.

## Steps
1. Identify the events table and its keys: a user id, a step/stage name.
   Use `describe_tables` if you don't know them.
2. Confirm the funnel ORDER. The builder defines a `STEPS` constant at the top
   of `generate_df` (default `Visit → SignUp → AddToCart → Checkout → Purchase`).
   Edit that list to match your product's real stages — per-step counts are
   derived against it and the funnel order is preserved.
3. Run the bundled builder: it counts unique users per step, then computes
   conversion vs the previous step, overall conversion vs the first step, and
   the users lost at each transition.
   → `run_skill_file(skill="funnel-analysis", path="scripts/funnel.py")`
4. The script returns a tidy DataFrame: `step, step_index, users,
   conversion_from_prev_pct, overall_pct, drop_off`. Render it as a funnel/bar
   chart with `create_widget` (step on the axis, users as the value).

## Data contract
The script reads via the injected `ds_clients` when available
(`execute_query("SELECT user_id, step FROM events")`) and derives per-step
unique user counts. With no data source connected it runs on a small synthetic
sample (decreasing counts) so the shape is visible.

The step ORDER is **configurable** via the `STEPS` list constant at the top of
`generate_df` — it defaults to the demo order and is the canonical ordering used
to rank, label, and compute conversion. Steps present in the data but absent
from `STEPS` are appended after the known ones; known steps absent from the data
default to 0. Swap the demo block for the real query once a source is connected.
