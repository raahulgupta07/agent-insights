# Data + Agent Cleanup Plan

Goal: **data can't be silently wrong, agent can't answer wrong.** Clean the data side
(load → merge → understand → validate → engineer) AND the agent side (parse → verify →
serve). Every phase flag-gated, EPHEMERAL until baked. Verify each before next.

Real org = `7d372305-9368-409e-a189-4517e5b84e4e` · source `fd164352` (MM Conso 6-file
merge, 21,240 rows, coverage ok) · doc `crmqa.docx` (12 questions).

Principle: **never trust the parser or the data — trust the check.** Unverifiable →
HELD for one-time human confirm, never shipped.

---

## Status baseline (verified 2026-07-01)

HAVE + ON: multi-file load, one-table merge, file/period coverage (reconcile),
LLM column meanings (37/37), definition registry, **EVAL GATE** (baked v1.63.0),
correction loop, instruction publish (5 approved defs, just fixed from 0).

WEAK / MISSING: data validation, column typing/profiling (built-off), data
engineering (numbers/dates raw), regex doc parser (brittle), ratio + pivot scoring.

Held now (4): Q8 recruitment rate, Q9 retention rate, Q11a drop-off rate (ratios),
Channel Breakdown / Q11b drop-off reasons (pivot).

---

## TRACK A — CLEAN THE DATA (ingest side, do first)

### D1 — Column profiling  [mostly WIRING; ColumnProfile built, mig colprofile1, flag-OFF]
Per column on upload: dtype (number/date/category/text), null %, distinct count,
min/max, top values, sample. Fills the empty `type` (today 2/37).
Verify: 37/37 columns get a real type + profile.

### D2 — Data validation gate  [NEW, small, BIGGEST safety win]
Using D1 profiles, loud checks (not silent):
- filter-value existence (catches `Retentnion call` vs `Retention Call` → silent 0)
- row-count floor + per-period sanity
- null-spike / all-null column
- dup-file detect (same content-hash twice → double-count)
Verify: typo filter → flagged, not silent-0.

### D3 — Typing + light data engineering  [NEW, non-destructive]
Add typed columns alongside raw (never mutate silently):
- numbers: strip commas/spaces → numeric (unlocks SUM/AVG metrics)
- dates: parse real date column → date type (real month/quarter grouping, not just
  filename period)
- trim whitespace / normalize case on category filters (careful)
Verify: a SUM-of-value + group-by-actual-date question works.

### D4 — Smart merge  [NEW]
- fuzzy schema match (renamed/extra col still merges, mismatch flagged not dropped)
- schema-drift on re-upload (changed cols → warn + map, not silent 2nd table)
- explicit dup-row policy per source (keep/drop; this doc = keep)
Verify: file with 1 renamed col → merges with a note, no broken 2nd table.

### D5 — Deep understanding  [WIRE ingest-brain, built-OFF]
- feed LLM the D1 profile (distinct values, type, range) not just name+samples →
  sharper meanings + units + PII detect
- key/relationship detect (date key, entity, measure, join key)
- cross-source UNIFY (same concept named differently)
Verify: LLM labels Channel Type as category{Trade,Digital,Ethical}, Call Completed
Date as date key.

### D6 — Ingest report card  [NEW, small, makes it visible]
One coverage+quality summary per upload → UI + agent:
- files/periods/rows (have) + per-column type/null%/distinct
- validation warnings (typos, dup files, null spikes)
- `<data_coverage>` (have) + new `<data_quality>` block so agent SAYS what's wrong
Verify: bad upload → report card shows the problem before training.

---

## TRACK B — FIX THE AGENT (train + serve side)

### C1 — LLM doc parser  [NEW, replaces brittle regex]
Feed doc to LLM (OpenRouter/GLM-5.2): extract name, filters, numerator, denominator,
group-by, expected — adapts to ANY phrasing. Kills the "write every rule in advance"
problem (Num/Denom, year-vs-count 2025 bug, pivots). Golden gate still verifies →
catches LLM hallucination.
Verify: crmqa.docx → all 12 parsed clean; New User/Q7/Q9/Q11 give real counts not 2025.

### C2 — Ratio scoring  [NEW; agent_definitions kind='ratio' + den_predicate + group_by]
kind='ratio' → golden_gen emits num_sql + den_sql; eval_gate runs both, verifies BOTH
counts vs ground truth (stronger than % alone). Migration `ratiodef1` (idempotent).
Verify: Q8 recruitment rate auto-approves (num 644 / den 2210 = 29.14%); then Q9/Q11a.

### C3 — Pivot scoring  [NEW]
Parse logic → grid {row,col}→N; eval compares full grid, not one cell. Or human-confirm
once for the grid.
Verify: Channel Breakdown / Q11b drop-off reasons scored as pivot, not 603-scalar.

### C4 — Easy counts backlog  [DATA edits + confirm]
Add Q2 (lead channel breakdown 1544/Trade1356/Ethical177/Digital11), Q6 (Ensure new
users by city), Q7 (all-brand new users by channel/month = 644). Counts + breakdown,
confirm once → goldens.
Verify: each total matches doc.

---

## ORDER

```
DATA (first — foundation)          AGENT (after / parallel)
 D1 profile ─┬─> D2 validate        C1 LLM parser ─> C2 ratio ─> C3 pivot
             └─> D3 typing                                └─> C4 counts backlog
 D4 merge   D5 understand  D6 report
```

Rec sequence: **D1 → D2** (garbage-in net, mostly wiring) → **C2** (clear held ratios,
concrete win) → **C1** (LLM parser, kills future brittleness) → rest.

## Rules
- Flag-gate every phase. Test ON (prove) + OFF (inert).
- EPHEMERAL (docker cp + restart) until proven, then bake docker-commit + bump
  VERSION_HYBRID + CHANGELOG.
- LANDMINE: offline flag tests MUST `load_overrides_from_db` / `set_override` first
  (else ONE_TABLE_MERGE reads OFF → wrong counts).
- Golden verifies LOGIC, not DATA — that's why Track A (validation) exists.

## Reuse (built, just wire)
ColumnProfile (colprofile1), ingest-brain (messy-Excel, PDF/vision, UNIFY), reconcile,
one-table-merge, column meanings, eval gate, correction loop.
