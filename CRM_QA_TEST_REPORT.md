# CRM Agent Q&A — Test Report (doc vs Rahul vs CRM agents)

**Date:** 2026-06-30
**Source of truth:** `~/Downloads/CRM/2026-06-29 CRM Agent Q&A , Logic.docx` (12 human-verified Q&A)
**Method:** frontend-faithful — logged in as org admin (`admi@cityagent.com`, org `e02b1b04`), each question asked in a **fresh chat** bound to the studio (`POST /api/reports` + `studio_id` → `POST /api/reports/{id}/completions`), exactly the web UI path. No shortcuts.
**Agents tested:** `Rahul` studio (`0e0cc096`) and `CRM Agent` studio (`303200f3`). 12 Q × 2 agents = 24 live runs.

---

## Scorecard vs document golden

| Q | Metric | Doc golden | Rahul | CRM | Verdict |
|---|--------|-----------|-------|-----|---------|
| Q1 | Total leads | **1,544** | 2,967 | 2,967 | ❌ both ~1.9× over |
| Q2 | Lead channel split | Trade 1356 / Ethical 177 / Digital 11 (tot 1,544) | total 1,544 ✓ but channel table malformed | total 1,544 ✓ but channel table malformed | ⚠ total right, breakdown wrong |
| Q3 | Succ/Unsucc by month | Jan 1,813/1,563 … (doc flags % inconsistent) | Jan 3,588 (~2×); **April matches** | same | ❌ over-count, April OK |
| Q4 | Successful calls total | **7,526** | Loyalty 8,843 / Trade 3,063 … (8 raw types) | same | ❌ wrong grouping & total |
| Q5 | Unsuccessful calls total | **4,179** | no clean total | **states 4,179 ✓** | CRM ✓ total / Rahul ✗ |
| Q6 | Ensure new users by city | Yangon **117** | Yangon **234** | Yangon **234** | ❌ exactly **2×** |
| Q7 | New users all brands total | **644** | **1,276** (~2×) | **658** (+14, close) | ⚠ agents DIVERGE |
| Q8 | Recruitment rate | *(doc blank)* | 18.52% (1,248/6,738) | 18.52% (same) | — can't validate |
| Q9 | Retention rate | per-channel 66–87% | **1.35%** (240/17,764) | **1.35%** (same) | ❌ wrong metric def |
| Q10 | Drop-off / lapsed total | **2,630** | **4,909** | **4,909** | ❌ both ~1.87× over |
| Q11 | Drop-off rate | table | **asked clarifying Q** | **asked clarifying Q** | ⚠ no answer (ambiguity gate) |
| Q12 | Drop-off reasons by channel | Digital/Ethical/Trade columns | by 8 raw channel types | by 8 raw channel types | ⚠ structure differs |

**Clean numeric matches vs doc:** CRM 1 (Q5; Q7 near) · Rahul 0. Both fail the majority.

---

## Rahul vs CRM (agent-to-agent)

- **Near-identical** on Q1, Q2, Q3, Q4, Q6, Q8, Q9, Q10 — same data, same training, same answers (same errors).
- **Diverge** on:
  - **Q7** — Rahul 1,276 vs CRM 658 (CRM ≈ doc 644).
  - **Q5** — CRM gives correct total 4,179; Rahul does not.
- **Both** gate Q11 with a clarifying question instead of answering.

CRM agent is marginally more correct than Rahul (Q5, Q7).

---

## Why they're wrong — verified root causes

**Ground-truth check:** the bound source `CRM Monthly (one-table)` (`0b9b39ac`) physically contains **only April 2025** — 2 tables (`t_441866f9…`, `t_483de7b7…`), 2,447 rows each, **every row month = 4**. Jan/Feb/Mar/May/Jun were never ingested. The agent's own generated SQL queries `t_441866f9…_mm_conso_data_report_apr_25`.

1. **Data is April-only (incomplete).**
   Doc goldens span Jan–Jun; the source has only April. Any 6-month answer rests on missing data.

2. **The agent fabricates the missing months.**
   Asked "Jan–Jun", it returns a full 6-month table from April-only data — inventing the other 5 months. Tell: agent **April** figure ≈ doc April (Q3 1,299 vs 1,307); the rest is made up.

3. **April loaded twice (duplicate).**
   Two identical 2,447-row tables. Anything unioning both doubles counts → the ~2× pattern (Q6 Yangon **234 = 2×117**, Q1 2,967, Q10 4,909, Q3 Jan 6,708). Counts also exceed what one table holds (agent 4,909 lapsed vs table's 509) → querying across both copies + invention.

4. **Channel-type mapping mismatch.**
   Raw data types = Loyalty / Trade Activation / Clinic / Hospital/Clinic / Drug Store/Pharmacy / Facebook / Unknown. Doc rolls into **3 buckets** (Trade / Ethical / Digital). No rollup mapping → Q2/Q4/Q5/Q12 breakdowns never align even when a total is right.

5. **Wrong metric definitions** (esp. Q9 retention).
   Agents: retention = 240 / 17,764 = **1.35%**. Doc: numerator = Retention Calls Successful & status Retained/Existing → per-channel **66–87%**. Definitions don't match doc logic.

**Conclusion:** not an LLM-quality problem — **bad inputs**. Incomplete + duplicated data, no channel rollup, undefined metrics.

---

## Fix priorities

- **P0 — De-duplicate the bound merged source** (`0b9b39ac`). Two identical April staging tables exist (`t_483de7b7…` and `t_441866f9…`, both 2,447 rows). Kill the duplicate, re-materialize the one-table merge, re-ingest the genuinely-missing months. Removes the ~2× error class across Q1/Q3/Q6/Q7/Q10.
- **P1 — Add channel-type rollup** (Trade/Ethical/Digital) as a derived column / glossary mapping so breakdowns match the doc's 3-bucket model (Q2/Q4/Q5/Q12).
- **P2 — Pin metric definitions** for recruitment/retention/drop-off as verified goldens (Q8/Q9/Q11) so the agent stops re-deriving them.

Raw results: `scratchpad/qa_full.json` (full answers + block trace per run).
