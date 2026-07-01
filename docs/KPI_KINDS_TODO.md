# KPI-Kinds + Self-Correcting Training — Phase Plan

Goal: agent **learns the doc logic → checks answer vs doc truth → self-corrects → releases only
verified**. At release, every KPI shape (count / breakdown / rate / derived) is proven or held —
**never silently hallucinated**.

Proven baseline (2026-07-01, org `7d372305`, real 21,240-row merged CRM data): all 12 doc
questions reproduce EXACT from data. Today only 3 auto-train (scalar counts). This plan makes the
other 9 auto-train + generalizes to future KPIs of the same shapes.

---

## ⛔ ZERO-HARDCODING CONTRACT (governs every phase)
The 12 CRM questions/SQL/numbers below are **reference only — to check the engine works.** They must
**NEVER** be written into source, UI, or a checked-in fixture. This CRM is one example; the engine
must work for ANY org's ANY doc + ANY data with no code change.

Everything is **derived, stored in DB, user-editable, self-improving**:
1. **Doc is the only input.** Upload doc → engine derives definitions (name, kind, filters, expected).
   No column names, values, numbers, or SQL hand-written in code.
2. **Catalog auto-built from the uploaded data** (real columns + distinct values) — not a fixed list.
3. **Golden/verification set is auto-generated** from the doc's own expected numbers, stored per
   org+source in DB (`definition_goldens`). NOT a committed `crm_qa.json`.
4. **User owns it in UI.** Every definition viewable/editable/approvable; corrections typed as plain
   instructions; coverage + verify status + provenance all shown. No dev needed to fix a metric.
5. **Self-improving.** Mismatch → auto-repair → still-fail → surfaced in UI → user fixes once →
   engine re-verifies → learns. Re-upload new doc → re-derives. Coverage climbs over time.
6. **Code = generic engine only.** Kind rules are generic keywords; scorers are generic; repair
   searches the *data's own* catalog. Grep the source for `1544`/`Ensure`/`Retention` → must be ZERO.

Test = point the SAME engine at a different org's doc → it derives + verifies with no code edit.

Legend: `[ ]` todo · `[~]` wip · `[x]` done · `[!]` blocked
Flags (all default OFF): `HYBRID_KPI_KINDS`, `HYBRID_SELF_CORRECT`, `HYBRID_ANSWER_GROUNDING`.
Rules: stack = `docker-compose.build.yaml` only · never `down -v` · one flag wave = one
`docker restart ca-app` · bake = docker-commit · touch Dash core minimally · new work flag-gated OFF.

Reference ONLY — expected engine output for THIS doc (do NOT commit as fixture; the engine must
*derive* these, and reproduce them as proof it works):
| # | KPI | kind | derived target |
|---|---|---|---|
| Q1 | leads | count | 1544 |
| Q2 | leads by channel | breakdown | Trade1356/Eth177/Dig11 |
| Q3 | succ+unsucc by month | breakdown | table |
| Q4 | successful calls | count | 7526 |
| Q5 | unsuccessful calls | count | 4179 |
| Q6 | new Ensure users by city | breakdown | Yangon117 (all cities) |
| Q7 | new users all brands | count | 644 (w/ Recruitment Call) |
| Q8 | recruitment rate | rate | 644/2210 = 29.1% |
| Q9 | retention rate | rate | 6841/9495 = 72.0% |
| Q10 | lapsed/drop-off users | derived | 2630 |
| Q11 | drop-off rate | rate | 2630/9495 = 27.7% |
| Q12 | drop-off reasons by channel | breakdown | Ensure/normalmeals/Digital 603 |

These live in scratchpad `qrun.py` runs — used to eyeball the engine, never shipped in code.

---

## Phase 0 — Freeze + DERIVED baseline suite  (no hardcoding)  ✅ DONE 2026-07-01
Small. No behavior change. Suite is **generated from the doc's own definitions in DB**, not a
committed fixture. Same code works for any org's doc.

- [x] 0.1 `docker commit ca-app` → `cityagent-analytics:rollback-kpikinds-20260701` (safety snapshot)
- [~] 0.2 `definition_goldens` table — **deferred** (simplicity): suite reads `agent_definitions` live,
      no new table needed for baseline. Add in Phase 4 for history/provenance.
- [x] 0.3 `services/train/golden_suite.py` — **generic**: read `agent_definitions` for (org) → group by
      data_source → `golden_gen`+`eval_gate` → report `{passed, failed, rows[]}`. ZERO literals.
- [x] 0.4 Run on live org 7d372305 → baseline **3 PASS / 6 FAIL** (only the 3 scalar counts pass today)

**Verified:** suite reads DB (no fixture), scoreboard 3/6, snapshot exists, `grep 1544/Ensure` in
golden_suite.py = CLEAN. EPHEMERAL (docker cp), not baked. Held 6 = breakdowns/rates/garbage-expected.

---

## Phase 1 — KPI-Kinds  (`HYBRID_KPI_KINDS`)  → 11/12 green
Make every stage shape-aware. `kind='count'` default = today's behavior untouched.

### 1a Registry schema
- [ ] 1a.1 Migration `defkind1` (off current head): add to `agent_definitions` cols
      `kind` (default `'count'`), `dimensions` JSON, `numerator` JSON, `denominator` JSON,
      `expected_table` JSON, `tolerance` FLOAT. Idempotent.
- [ ] 1a.2 `alembic upgrade head` on live DB → columns present, existing rows default `count`

### 1b Parser — `services/ingest/logic_parser.py`
- [ ] 1b.1 `classify_kind(question, logic)` → count|breakdown|rate|derived_set (keyword rules)
- [ ] 1b.2 Rate split: parse `Numerators:(...) Denominators:(...)` → `numerator/denominator` filter dicts
- [ ] 1b.3 Breakdown: extract `dimensions` (by city/channel/month) separate from filters
- [ ] 1b.4 Expected extractor: ignore 4-digit years; breakdown→store cell/table; rate→`%` or None
- [ ] 1b.5 Fail-loud: unparseable logic → `needs_review`, emit NO garbage predicate

**Verify:** parse crmqa.docx → 12 triples, each tagged correct kind, no `2025` garbage, rates have num/den.

### 1c Generator — `services/train/golden_gen.py`
- [ ] 1c.1 `TEMPLATES[kind]`: count (unchanged) · breakdown `GROUP BY dim` · rate `SUM(CASE)/SUM(CASE)` · derived=count
- [ ] 1c.2 Route each def through its template

**Verify:** generate for all 12 defs → SQL shape matches kind, runs without error.

### 1d Eval gate — `services/train/eval_gate.py`
- [ ] 1d.1 `SCORERS[kind]`: count `==` · breakdown per-cell compare to `expected_table` · rate `abs(a-e)<=tol` · derived `==`
- [ ] 1d.2 No-expected rate → verdict `computable` (num&den>0), not `approved`
- [ ] 1d.3 Keep scalar path identical when kind=count (regression guard)

**Verify:** run gate on 12 → 11 approved (all but new-user contradiction), 1 held. Golden suite 11/12 green.

### 1e Wire + prove
- [ ] 1e.1 Flag `HYBRID_KPI_KINDS` (3-place hybrid_flags.py), default OFF
- [ ] 1e.2 Flip ON org 7d372305 (DB override) → `docker restart ca-app` (ONE restart)
- [ ] 1e.3 Real in-process train → verified_goldens stage → suite 11/12
- [ ] 1e.4 Flag OFF → old 3/12 behavior returns (proves inert-when-off)

**Verify:** train log shows 11 approved; flag-off = unchanged.

---

## Phase 2 — Self-Correct  (`HYBRID_SELF_CORRECT`)  → resilient to messy docs
Bounded auto-repair. Searches only REAL vocab, always re-verifies. Can't invent.

### 2a Catalog
- [ ] 2a.1 `services/train/catalog.py`: per-source real column list + distinct values per column (cache)
- [ ] 2a.2 Build catalog for source fd164352 → 37 cols + value sets

### 2b Repair engine — `services/train/corrector.py` (extend existing)
- [ ] 2b.1 Fuzzy value→catalog (`'Retentnion call'`→`Retention Call`, `'User)'`→`User`)
- [ ] 2b.2 Fuzzy column→schema (mangled text → real column)
- [ ] 2b.3 Strip artifacts (trailing `.`/`)`/"In the table")
- [ ] 2b.4 Re-classify kind if scalar fails but grid/ratio matches
- [ ] 2b.5 Toggle a doc-mentioned filter (± Recruitment Call), bounded ≤N tries
- [ ] 2b.6 Every repair ends with re-check vs doc number; fail → held (no infinite loop)

### 2c Prove
- [ ] 2c.1 Corrupt a known-good predicate (typo a value) → run train → repair heals it → suite still green
- [ ] 2c.2 Corrupt beyond repair → confirm it HOLDS (not force-passed)

**Verify:** deliberate corruption self-heals; unrepairable holds.

---

## Phase 3 — Answer Grounding  (`HYBRID_ANSWER_GROUNDING`)  → no hallucination at chat-time
Held/unknown → refuse, never guess. Every answer auditable.

- [ ] 3.1 Coverage ledger: every doc question → def or `uncovered`; expose in train detail
- [ ] 3.2 Refuse path: user asks a held/uncovered KPI → agent replies "not yet verified — needs review", NO number
- [ ] 3.3 Provenance: approved answer cites `definition + number-from-data` (auditable)
- [ ] 3.4 Publish breakdowns/rates as Instructions (`definition_instructions.py`) so agent answers them

**Verify:** ask held new-user → refuses; ask Q2 → returns verified breakdown with provenance.

---

## Phase 3.5 — Definitions Studio UI  (user owns + improves everything, no dev)
The whole point: user manages KPIs, not code. All data-driven from DB (Phase 1a/0.2 tables).
Reuse existing Intel/Knowledge page pattern — do NOT hardcode any KPI in Vue.

### Backend (generic REST over the definition tables)
- [ ] 3.5.1 `GET /studios/{id}/definitions` → list {name, kind, filters, dimensions, expected, status,
      actual, verdict, coverage, provenance} for org+source
- [ ] 3.5.2 `PATCH /definitions/{id}` → edit name/kind/filters/expected/tolerance → auto re-verify → new status
- [ ] 3.5.3 `POST /definitions/{id}/correct {instruction}` → corrector loop (plain-text fix) → re-verify
- [ ] 3.5.4 `POST /studios/{id}/definitions/rebuild` → re-derive from latest doc (re-run parse→registry)
- [ ] 3.5.5 `GET /studios/{id}/coverage` → doc-question→def map + PASS/FAIL scoreboard (generic)

### Frontend (Nuxt, data-driven — table renders whatever DB returns)
- [ ] 3.5.6 Definitions table: name · kind · expected · actual · ✅/⛔ · [Edit] [Correct] — rows from API, none hardcoded
- [ ] 3.5.7 Edit drawer: change kind/filters/expected → Save → live re-verify badge
- [ ] 3.5.8 Correct box: type "new user means … expected N" → runs corrector → shows new verdict
- [ ] 3.5.9 Coverage panel: green/red scoreboard + uncovered questions list
- [ ] 3.5.10 "Re-derive from doc" button → rebuild after a new doc upload

**Verify:** upload a DIFFERENT doc → Studio auto-lists its derived KPIs; user edits one held metric in UI
→ re-verifies green → agent uses it. Zero code change between the two docs.

---

## Phase 4 — Release Gate + contradiction  → release = all-fixed or explicitly-held
- [ ] 4.1 Contradiction detector: same concept, ≠ number (new-user 644 vs 658) → flag for human
- [ ] 4.2 Golden suite assertion inside `train_orchestrator` after verified_goldens → PASS/FAIL in detail + log
- [ ] 4.3 Bake gate: block ship unless suite green OR held items explicitly waived+signed
- [ ] 4.4 Human queue surfaces held/uncovered/contradiction for analyst sign-off → corrector applies

**Verify:** train emits scoreboard; bake refuses on red; contradiction shows in queue.

---

## Phase 5 — Bake + ship
- [ ] 5.1 One analyst decision resolved **in the Studio UI** (Phase 3.5), not code: user picks the
      "new user" rule (644 vs 658) via the Correct box → corrector re-verifies → suite 12/12
- [ ] 5.2 VERSION_HYBRID bump + CHANGELOG_HYBRID + DEVLOG entries
- [ ] 5.3 Bake = docker-commit ca-app → `cityagent-analytics:dev` + tag
- [ ] 5.4 Rebuild ca-app from build.yaml → suite still green (proves baked)
- [ ] 5.5 Update memory + CLAUDE.md + CODEBASE_MAP

**Verify:** fresh rebuild → golden suite green → durable.

---

## Ordering / risk
- Phase 0 first (net before build). Phase 1 = biggest win (3→11). 2/3/4 layer on independently.
- Each flag independently provable + inert when OFF → safe partial ship.
- Only non-code blocker: the new-user doc contradiction (Phase 5.1), one analyst yes/no.
- Golden suite is the spine — every phase re-runs it; red = stop.
