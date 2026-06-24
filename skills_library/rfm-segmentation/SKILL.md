---
name: rfm-segmentation
description: Segment customers by Recency/Frequency/Monetary into actionable tiers (Champions, Loyal, Big Spenders, At Risk, New). Activate for "segment customers", "RFM", "best customers", "who to retain".
allowed-tools: run_skill_file read_skill_file describe_tables
category: customer
---

# RFM Segmentation

Scores every customer on Recency (how recently they bought), Frequency (how often)
and Monetary (how much), then rolls those scores into a named, actionable tier.

## Steps
1. Identify the orders table and its keys: a customer id, an order date, an order
   amount. Use `describe_tables` if you don't know them.
2. Run the bundled builder: per customer it computes recency (days since last order
   vs the latest date in the data), frequency (order count) and monetary (total
   amount), scores each 1-5 by quantile, and labels a segment.
   → `run_skill_file(skill="rfm-segmentation", path="scripts/rfm.py")`
3. The script returns one row per customer:
   `customer_id, recency_days, frequency, monetary, r, f, m, segment`.
   Segments: **Champions** (R>=4 & F>=4), **Loyal** (F>=4), **Big Spenders** (M>=4),
   **At Risk** (R<=2 & F>=3), **New** (R>=4 & F<=2), **Others**. Surface the tier
   counts and the Champions / At Risk lists for retention action.

## Data contract
The script reads via the injected `ds_clients` when available
(`execute_query("SELECT customer_id, order_date, amount FROM orders")`). With no
data source connected it runs on a small synthetic sample (10 customers, several
orders each) so the shape is always visible. Swap the demo block for the real query
once a source is connected.
