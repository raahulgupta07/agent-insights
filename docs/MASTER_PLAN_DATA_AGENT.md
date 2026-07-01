# Master Plan — Data Engineering → Agent (End to End)

One plan, raw file to answered question. Goal: **data can't be silently wrong, agent
can't answer wrong.** Every stage: what it does, HAVE / DON'T, what to build, how to
verify. Flag-gated, EPHEMERAL until baked.

Reference org `7d372305-9368-409e-a189-4517e5b84e4e` · source `fd164352` (MM Conso
6-file merge, 21,240 rows) · doc `crmqa.docx` (12 questions).

Core principle: **trust the check, not the parser or the data.** Anything unverifiable
→ HELD for one-time human confirm, never shipped to the agent.

```
FILE → [1 READ] → [2 MERGE] → [3 PROFILE] → [4 VALIDATE] → [5 ENGINEER] →
       [6 UNDERSTAND] → [7 PARSE DOC] → [8 DEFINE] → [9 VERIFY/GOLDEN] →
       [10 PUBLISH] → [11 SERVE] → [12 MONITOR/LEARN]
```

Legend: ✅ have+on · ⚠️ built-off / partial · ❌ missing

---

# PART I — DATA ENGINEERING (stages 1–6)

## Stage 1 — READ / INGEST
Read any uploaded file into frames.
- ✅ CSV/Excel/TSV (pandas + robust readers), smart-header, multi-file, fail-loud on bad file
- ⚠️ messy-Excel / multi-sheet, PDF / Word / vision (ingest-brain, flag-off)
- ❌ Google Sheets / DB-connector direct-to-pipeline typing
**Build:** E1 turn on ingest-brain readers behind flag for non-CSV.
**Verify:** a messy .xlsx + a PDF table ingest to clean frames.

## Stage 2 — MERGE
Combine multi-file uploads into query-ready tables.
- ✅ same-schema merge → 1 table (col-signature), provenance `_source_period`,
  file/period coverage (reconcile), coverage→DEGRADED
- ❌ dup-file detect (same content-hash 2× → double count)
- ❌ fuzzy schema merge (renamed/extra col → splits/drops instead of maps)
- ❌ schema-drift on re-upload (changed cols → silent 2nd table)
- ⚠️ cross-source UNIFY (same concept diff name) — ingest-brain, off
**Build:** E2a dup-file hash guard · E2b fuzzy-schema map + drift warn · E2c wire UNIFY.
**Verify:** upload file w/ 1 renamed col → merges w/ note, no broken 2nd table; re-upload
same file → dup flagged.

## Stage 3 — PROFILE  (foundation for validate + engineer + understand)
Per column facts on upload.
- ⚠️ `ColumnProfile` model + mig `colprofile1` BUILT, flag-off, unmerged
- ❌ not wired: dtype (num/date/cat/text), null %, distinct count, min/max, top values, sample
- ❌ `semantic_columns.type` filled only 2/37 today
**Build:** E3 wire ColumnProfile into upload path → compute + persist profile per column.
**Verify:** 37/37 columns get a real type + profile row.

## Stage 4 — VALIDATE  (the garbage-in net — highest safety value)
Cheap loud checks using Stage-3 profiles. Never silent.
- ✅ coverage warning (`<data_coverage>`) from reconcile
- ❌ filter-value existence (`'Retentnion call'` vs `'Retention Call'` → silent 0)
- ❌ row-count floor + per-period sanity band
- ❌ null-spike / all-null column flag
- ❌ category near-duplicate detect (typos: Retention/Retentnion)
- ❌ `<data_quality>` block to the agent
**Build:** E4a value-existence check (predicate values must appear in column) · E4b
row-count sanity · E4c null/near-dup flags · E4d `<data_quality>` surface.
**Verify:** feed a typo filter → flagged loud, not silent-0; drop a month → caught.

## Stage 5 — DATA ENGINEERING  (transform, non-destructive — add typed cols, keep raw)
Make data math-ready + time-ready.
- ⚠️ dedup: implicit keep-all (matches this doc; no explicit policy)
- ❌ number cleaning: strip commas/spaces/currency → numeric (blocks SUM/AVG today)
- ❌ date parsing: real date column → date type (today month via filename only)
- ❌ whitespace trim / case normalize on category filters
- ❌ derived columns (period from real date, ratios, flags)
- ❌ standard units (%, currency)
- ❌ join keys across sources (customer/brand id)
**Build:** E5a numeric-cast (raw kept) · E5b date-parse (raw kept) · E5c trim/normalize
categories (careful, reversible) · E5d explicit dedup policy per source · E5e derived
period/measure columns.
**Verify:** a SUM-of-value question works; group-by-actual-date (not filename) works;
duplicate-loaded file → correct count under chosen policy.

## Stage 6 — UNDERSTAND  (LLM + profile)
Semantic layer the agent reads.
- ✅ LLM column meanings (37/37 `semantic_columns.meaning`)
- ❌ meaning uses only name+samples (not the Stage-3 profile)
- ❌ key/relationship detect (date key, entity, measure, join key)
- ❌ PII / sensitivity (column exists, default only)
- ❌ table-level summary + suggested metrics
**Build:** E6a feed profile into meaning LLM (sharper, detects units/PII) · E6b role
detect (date/entity/measure/key) · E6c table summary + candidate-metric suggestions.
**Verify:** LLM labels Channel Type = category{Trade,Digital,Ethical}, Call Completed
Date = date key, flags any PII column.

---

# PART II — AGENT (stages 7–12)

## Stage 7 — PARSE DOC  (business logic → structured metrics)
Turn the Q&A/Logic doc into metric specs.
- ✅ regex Q/Ans/Logic parser (BRITTLE)
- ❌ handles Numerator/Denominator (ratios) — mashes into one broken predicate
- ⚠️ year-vs-count bug: grabs first int → "Jan–Jun 2025 total 644" → 2025 (data-fixed
  for New User, parser still bugged)
- ❌ pivots / breakdowns
- ❌ adapts to new phrasing without code change
**Build:** A1 **LLM doc parser** (OpenRouter/GLM-5.2): extract name, filters, numerator,
denominator, group-by, expected — any phrasing. Golden gate still verifies → catches
hallucination. Retire brittle regex (keep as fallback).
**Verify:** crmqa.docx → all 12 parse clean; New User/Q7/Q9/Q11 give real counts not 2025.

## Stage 8 — DEFINE  (single source of truth)
- ✅ Definition Registry `agent_definitions` (mig `defreg1`), `kind` col, `build_predicate`
- ❌ ratio kind (num + den predicates)
- ❌ pivot kind (row/col dims + grid expected)
- ❌ group-by dims stored for breakdowns
**Build:** A2 add `den_predicate` + `group_by` cols + kind∈{metric,ratio,pivot}, mig
`ratiodef1` (idempotent).
**Verify:** Q8 stored as kind='ratio' with num+den; Channel Breakdown as kind='pivot'.

## Stage 9 — VERIFY / GOLDEN  (never silently wrong)
- ✅ golden generator (COUNT SQL), **EVAL GATE** (verify vs ground truth), baked v1.63.0
- ✅ correction loop (recorrect), held-queue for human confirm
- ❌ ratio scoring (run num + den, verify BOTH counts)
- ❌ pivot scoring (compare full grid, not one cell)
- ❌ data-quality gate BEFORE golden (so golden isn't verifying against bad data)
**Build:** A3a ratio scoring · A3b pivot scoring (or human-confirm grid) · A3c run Stage-4
validation before eval (fail data → hold, don't false-verify).
**Verify:** Q8 auto-approves (num 644/den 2210 = 29.14%); Channel Breakdown grid scored;
a bad-data source → held with data reason, not a lucky match.

## Stage 10 — PUBLISH  (defs → agent)
- ✅ goldens injected (QueryLibraryItem is_golden)
- ✅ approved defs → published Instructions (JUST FIXED: was 0, now 5), load_mode=always
- ❌ ratio/pivot defs → instruction text with the divide/grid rule + group-by hint
**Build:** A4 extend `definition_instructions` for ratio (num÷den) + pivot (breakdown by
dims) so agent reproduces tables itself.
**Verify:** ask "recruitment rate by brand" cold → agent builds the 12-row table.

## Stage 11 — SERVE  (answer questions)
- ✅ goldens + instructions applied every answer, coverage warning, semantic search, forecast
- ❌ answer cites data-quality state (`<data_quality>`)
- ❌ ratio/pivot answers rendered as tables by default
**Build:** A5a inject `<data_quality>` into answer context · A5b table renderer for
breakdown/pivot answers.
**Verify:** answer to a rate question shows the table + notes any data gap.

## Stage 12 — MONITOR / LEARN  (close the loop)
- ✅ live train-log, golden pass/fail visible
- ⚠️ answer accuracy = golden eval only
- ❌ ingest report card (types + nulls + warnings in UI)
- ❌ answer feedback → new/updated definition (self-learning)
- ❌ drift alert (metric count moves > band across re-uploads)
**Build:** M1 ingest report card · M2 thumbs/correction → recorrect a def · M3 drift alert.
**Verify:** bad upload → report card shows it pre-train; a user correction → def updates
+ re-verifies.

---

# BUILD ORDER

```
DATA-ENGINEERING SPINE (do first — everything downstream needs it)
  E3 profile ─┬─> E4 validate (garbage-in net)  ← highest safety
              └─> E5 engineer (numbers/dates)   ← unlocks new metric types
  E2 merge-hardening        E6 understand-upgrade

AGENT (after spine; C2 can start in parallel — clears held now)
  A2 def-kinds ─> A3 ratio+pivot scoring ─> A4 publish ─> A5 serve
  A1 LLM parser (kills future brittleness)
  M1 report card ─> M2 feedback-learn ─> M3 drift
```

Recommended sequence:
1. **E3 → E4** — profile + validation (garbage-in net; E3 mostly wiring built ColumnProfile).
2. **A2 → A3 ratio** — clear held Q8/Q9/Q11 (concrete win, user already confirmed 29.14%).
3. **A1 LLM parser** — stop hand-patching parse rules forever.
4. **E5 engineering** — numbers/dates → new metric classes.
5. **A3 pivot + A4/A5** — Channel Breakdown + table rendering.
6. **E2/E6/M** — merge hardening, deeper understanding, monitoring/self-learn.

# RULES
- Flag-gate every phase. Test ON (prove) + OFF (inert).
- EPHEMERAL (docker cp + restart) until proven → bake docker-commit + bump
  VERSION_HYBRID + CHANGELOG_HYBRID + tag.
- LANDMINE: offline flag tests MUST `load_overrides_from_db(db)` / `set_override()` first
  (else ONE_TABLE_MERGE reads OFF → wrong counts, e.g. Lead 119 not 1544).
- Golden verifies LOGIC; Stage 4 verifies DATA. Need both — golden alone caught 0 data bugs.
- Offline ORM breaks on `applications`/`OrganizationSettings` dead mappers → bypass with
  raw psql for direct def/golden writes.

# REUSE (built — wire, don't rebuild)
ColumnProfile (mig colprofile1) · ingest-brain (messy-Excel, PDF/vision, UNIFY) ·
reconcile (coverage) · one-table-merge · LLM column meanings · definition registry
(defreg1) · eval gate · correction loop · instruction publish.

# CURRENT STATE (2026-07-01)
Approved goldens 5 (Lead 1544, Successful 7526, Unsuccessful 4179, New User 658, Q10 2630).
Instructions published 5. Held 4 (Q8/Q9/Q11a ratios + Channel Breakdown/Q11b pivot).
Data clean (6/6 files) but unvalidated. All EPHEMERAL — not baked/pushed.
