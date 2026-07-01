# Agent Training — Completion TODO

Plan to finish + productionize CityAgent Analytics **agent training**. Most training
work is **built but EPHEMERAL** (flag-gated, lives only in the running `ca-app`
container, not baked / not in git). "Complete" = combine + prove + bake + ship.

**Golden rule:** don't bake half-done. Snapshot to protect proven work NOW, combine,
prove, THEN clean bake.

Status legend: `[ ]` todo · `[~]` in progress · `[x]` done · `[!]` blocked

---

## Phase 0 — Freeze & audit (protect proven work TODAY)  ✅ DONE 2026-07-01
Goal: proven ephemeral work can't vanish on rebuild; get real state before trusting memory.
Full findings → [TRAINING_STATE.md](TRAINING_STATE.md).

- [x] `docker commit ca-app` → `cityagent-analytics:rollback-training-20260701` (`d848658f35a3`)
- [x] Audit LIVE state:
  - [x] flags ON via DB `organization_settings.config['hybrid_overrides']`, org **7d372305** (NOT e02b1b04)
  - [x] migs: head `defreg1`, `sessumm1`+verified-golden in chain; `colprofile1` absent (unmerged branch)
  - [x] KEY: `HYBRID_FULL_PIPELINE=true` but only gates hybrid_index+brain_graph — **combine NOT done**
  - [x] verified-golden/eval_gate/corrector unwired from `train_orchestrator` (live in `routes/pipeline.py`)
- [x] Wrote `docs/TRAINING_STATE.md`

**Verified:** rollback image exists; state doc matches reality. Memory drift corrected.

---

## Phase 1 — Baseline migrations  (#3, foundation)
Goal: fresh install = same schema as running org. No hand-DDL.

- [ ] Confirm `defreg1`, `sessumm1`, `colprofile1` in mig chain, idempotent
- [ ] Any hand-DDL-only table → author idempotent mig

**Verify:** fresh DB + `alembic upgrade head` → all training tables present, no `UndefinedColumnError`.

---

## Phase 2 — Wire verified-golden EVAL GATE into train  (#1)  ✅ CODE DONE 2026-07-01
Goal: the orphaned pipeline (`routes/pipeline.py` build-goldens chain) runs INSIDE
`train_orchestrator.run_training()`, gated `FULL_PIPELINE`+`VERIFIED_GOLDENS`.

- [x] Insight: steps 3–5 (generate→eval→save) need only existing AgentDefinitions, no doc
- [x] New fail-soft stage in `run_training` (before hybrid_index): load defs → group by
      data_source → `golden_gen.generate_for_definitions` → `eval_gate.evaluate` →
      save ONLY matches via `pipeline._save_golden`; mismatches HELD
- [x] Gated on BOTH flags (inert now — `VERIFIED_GOLDENS` OFF) → zero live-behavior change
- [x] Compiles host+container, imports resolve, ca-app healthy. EPHEMERAL (docker cp).

**NOT done (real combine of P0–P12 prototype):** the doc-parse→registry front half
(logic_parser + registry upsert) still lives only in `build-goldens`. Train-time gate
covers the trust half. Full front-half wiring = separate follow-up if wanted.

**Verify (Phase 3):** flip `VERIFIED_GOLDENS` on org 7d372305 → train → gate approves
matches / holds mismatches; reproduce proven numbers (Lead 1544 / Succ 7526 / Unsucc 4179).

---

## Phase 3 — Trust gates confirm  (#4, #5, #6)  ✅ PROVEN 2026-07-01 (except corrector)
Goal: training can't ship a wrong agent.

- [x] #4 EVAL GATE proven in a REAL in-process train (org 7d372305): `verified_goldens: 3 approved, 6 held`.
      Lead 1544 / Successful 7526 / Unsuccessful 4179 approved EXACT; wrong/error defs HELD. Flag ON (DB override).
- [ ] #5 Corrector loop — NOT auto-fixable for the held 3. New User (2025 unreproducible),
      Channel Breakdown (a pivot mis-modeled as scalar), Q8/Q9/Q11 (doc SQL errors). Needs BUSINESS
      input via instruction-driven `HYBRID_QUERY_CORRECTION`, not an auto-fix. Deferred → tickets below.
- [x] #6 Ingest completeness — confirmed: the 6 monthly files DO merge into one 21,240-row table under
      `ONE_TABLE_MERGE` (loaded from DB overrides). "Only April" was a harness artifact, not a live bug.

**Held-3 tickets (need a business analyst):**
- New User: supply the true definition + expected (2025 not derivable from data as given).
- Channel Breakdown: re-model as a breakdown/pivot, not a scalar golden.
- Q8/Q9/Q11: fix doc format so `golden_gen` produces valid SQL.

---

## Phase 4 — Data understanding decision  (#7, #8)
Goal: merge or park, explicitly.

- [ ] #7 Ingest Brain F09 (flag `HYBRID_INGEST_BRAIN` OFF, not merged) — merge-or-park DECISION
  - if merge → `feature/ingest-brain` → dev
- [ ] #8 AI column meanings — confirm `propose_column_meanings` populates Intel tabs on fresh org

**Verify:** drop messy Excel → understood; fresh org Intel tabs non-empty.

---

## Phase 5 — Clean bake + ship  (#2, #9, #10)  ✅ BAKED 2026-07-01
Goal: proven pipeline baked properly (NOT the Phase-0 safety snapshot).

- [x] #9 VERSION_HYBRID 1.62.0 → 1.63.0 + CHANGELOG_HYBRID + DEVLOG entries
- [x] Bake = docker-commit `ca-app` → `cityagent-analytics:dev` + tag `v1.63.0`
- [ ] #10 git push via branch flow feature/* → dev → staging → main — NOT done (repo not git-init'd here;
      backend is docker-cp EPHEMERAL persisted only via the commit-bake). Push when repo/flow available.

**Verify:** rebuild `ca-app` from build.yaml → training still works (proves baked). Pending full rebuild test.

---

## Critical ordering rules
- **Phase 0 snapshot ≠ Phase 5 ship bake.** Snapshot = insurance. Ship bake = after combine+gates proven.
- Bake ONLY after Phase 2+3 green. Baking now = freezing half-done.
- One flag wave → **ONE `docker restart ca-app`** (landmine: `--workers 4`).
- Stack = `docker-compose.build.yaml` ONLY. NEVER `docker compose down -v` / `docker volume rm`.
- New work flag-gated default-OFF.

## Biggest risks
1. Memory drift — Phase 0 audit MUST precede trust.
2. Combine (Phase 2) = real work, unknown prototype↔orchestrator gaps. Could be big.
3. FK-cascade delete landmine in verified-golden path.
