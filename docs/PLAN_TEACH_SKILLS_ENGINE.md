# PLAN — Domain Packs + Teach Box (lightweight "Skills" engine)

**Status:** Phase 0–6 DONE (2026-06-24). Engine complete; Tier-A fin packs shipped (Tier B/C additive, future).
**Flags:** `HYBRID_DOMAIN_PACKS` · `HYBRID_PACK_AUTOBIND` · `HYBRID_PACK_ROUTER` (all default OFF).
**Why:** native Skills (`HYBRID_SKILLS`) is heavy (sandbox exec per call → livelocks) and the agent picks the wrong skill from a flat name list. This engine rebuilds the *behaviour* without the sandbox: declarative method files, data-gated selection, learned re-rank. Rides the stable `create_data`/`create_artifact` loop. UI can still call them "Skills".

---

## Architecture (the whole idea)

A **pack** = one declarative `.yaml` (method + required inputs + output spec + goldens). Never executed — it only INJECTS a method + per-agent binding into the planner context.

- **INVARIANT** (method) = copied from the pack file, same for every agent.
- **VARIABLE** (binding) = synthesised per-agent from `column_intel` at train time.
- Copy the method, generate the binding = "smart", not "copy".

**3-layer selection fixes the "wrong skill" problem** (native has only a soft layer 2):
1. **Bind gate (hard):** a pack is invisible unless its required inputs bind to THIS agent's columns. Wrong-data pick = structurally impossible.
2. **Trigger gate + score:** the question must match the pack's `trigger_hints` (intent gate); then `score = 0.5·trigger + 0.3·bind_conf + 0.2·winrate`, top-1.
3. **Win-rate (adaptive, Phase 5):** eval/feedback demotes packs that keep failing a question pattern.

```
question → router
  candidate gate: only ACTIVE studio_bound_packs for this studio
  trigger gate:   question must hit the pack's trigger_hints
  score → top-1 (or none → plain analyst loop)
inject [METHOD]+[BINDING] into AgentV2 planner instructions
create_data (pandas+SQL) → create_artifact (slide/dash)   ← UNCHANGED
eval_harness vs pack goldens → pass/fail → winrate
```

**Data model:** one new table `studio_bound_packs` (studio_id, pack_id, binding_map, output_spec, eval_goldens, status[pending|active|dormant|rejected], source[pack|user], conf, missing). Everything else reuses existing surfaces (column_intel, scope-gate injection point, eval_harness, review gate, auto_queries/auto_evals).

---

## Phase plan

### Phase 0 — Engine Core  ✅ DONE (2026-06-24)
- [x] T0.1 migration `studiopack1_studio_bound_packs.py` (chains off head `dashversions1`). Applied live; head now `studiopack1`.
- [x] T0.2 model `StudioBoundPack` in `app/models/studio.py`.
- [x] T0.3 registry `app/ai/packs/registry.py` — load+validate+cache yaml library.
- [x] T0.4 binder `app/ai/packs/binder.py` — match required_inputs → columns (name/synonym/role, camel-split, eligibility on NAME score only).
- [x] T0.5 router `app/ai/packs/router.py` — bind-gate + trigger-gate + score + inject block.
- [x] T0.6 runtime `app/ai/packs/runtime.py` — DB glue (active rows → candidates → select → block).
- [x] T0.7 flags `HYBRID_DOMAIN_PACKS/PACK_AUTOBIND/PACK_ROUTER` + snapshot + UPGRADE_FLAGS.
- [x] T0.8 injection wired in `agent_v2.py` (after scope block, `await resolve_injection`, flag-gated, fail-open).
- [x] T0.9 first pack file `app/ai/packs/library/ebitda_good_bad_ugly.yaml`.
- [x] Verified: unit smoke (bind=1.0, missing-budget→dormant, music dataset→unbound, on-topic selects, off-topic→None); migration applied; app healthy 200; flags default OFF.
- **NOT yet done:** live agent run with flag ON binding to a REAL studio (that's Phase 1).

### Phase 1 — First skill live on real data  ✅ DONE (2026-06-24)
- [x] T1.1 created test studio **EBITDA Pack Test** `5ac4444c-2df0-423b-9457-7bc080128970` (org `55278108`); uploaded synth `ebitda.csv` (5 sectors, EBITDA actual/LY/budget + revenue) → DataSource `883a57ef…` pinned + profiled (7 cols, `POST /data_sources/{id}/profile`).
- [x] T1.2 binder ran on real `column_intel` profile → `bound=true`, all 7 inputs mapped, `overall_conf=0.7`, `missing=[]`. Inserted `studio_bound_packs` row `74614ae7…` status=`active`, source=`pack`.
- [x] T1.3 flags ON via per-org override (`PUT /api/organization/hybrid-flags/{HYBRID_DOMAIN_PACKS,HYBRID_PACK_ROUTER}` `{enabled:true}`) — **live, no recreate** (recreate would wipe hot-copied Phase 0). Asked "monthly EBITDA performance summary by sector — good bad ugly, vs LY and vs budget". Log confirmed `[DOMAIN_PACKS] injected pack block (chars=1801)`. Agent computed vs-LY/vs-Budget %, **flagged Food revenue +11% (>10% rule)**, bucketed GOOD(Pharma+20/+10, Food+18/+8) / BAD(Retail+7/-7) / UGLY(Logistics-15/-13, Construction-23/-17), built the slide deck. All numbers match hand-calc.
- [x] T1.4 snapshotted 5 per-sector goldens (vs_ly_pct/vs_budget_pct/bucket) into `studio_bound_packs.eval_goldens`. (Full eval_harness auto-wiring = Phase 4.)

**Phase 1 landmines:**
- EBITDA numeric cols profile as `role="id"` (near-unique) not `measure` — binder still binds (role only *ranks*, ×0.7 → conf 0.7 ≥ floor 0.6). Design held; do NOT tighten binder to require role match.
- **Flip flags with the per-org override API, NOT compose `--force-recreate`** — recreate re-bakes the container from the image, which has NONE of the hot-copied Phase 0/1 code → reverts everything. `set_override` (via `PUT /organization/hybrid-flags/{env}`) applies live in-process + persists to `org settings.config.hybrid_overrides`. `docker restart` (not recreate) is safe — reloads code from the container FS (keeps `docker cp` files).
- Flags now **ON (override) for org 55278108**. Other studios unaffected (no active bound packs → `resolve_injection` returns ""→ no-op). To revert: `PUT …/{env}` `{"enabled":null}` clears override → env default OFF.

### Phase 2 — Teach Box backend  `HYBRID_TEACH_BOX`  ✅ DONE (2026-06-24)
- [x] classifier `POST /studios/{id}/teach` → 1 LLM call (small default model) → spans tagged SKILL|INSTRUCTION|DATA_RULE|KNOWLEDGE, each with a bind preview. **Column-aware**: the studio's real column names are fed into the prompt so SKILL `required_inputs.synonyms` map to real columns (without this the LLM's loose logical names — `ebitda_current` vs col `ebitda_actual` — scored <0.6 and the skill stayed dormant).
- [x] span→surface builder (`app/ai/packs/teach.py`): SKILL→user-authored Domain Pack (`build_skill_pack` → `binder.bind_pack` → `StudioBoundPack` source='user', full dict in `pack_body`, status active if bound else dormant); INSTRUCTION→`StudioInstruction`; DATA_RULE→`StudioInstruction` prefixed `[DATA RULE]`; KNOWLEDGE→`KnowledgeDoc` via `docs_index.ingest_doc`. All born **pending** (review gate).
- [x] `POST /teach/approve` → persist spans → optional `train:true` kicks `train_orchestrator.start_training`.
- [x] **NEW: `studio_bound_packs.pack_body` JSON column** (mig `studioteach1`, head now `studioteach1`) — user packs have no yaml file, so the whole pack dict lives inline; `runtime.resolve_injection` reconstructs the pack from `pack_body` when the registry misses (`registry.get_pack(id) or row.pack_body`).
- [x] flag `HYBRID_TEACH_BOX` (+snapshot +UPGRADE_FLAGS); route registered in `main.py`.
- [x] **E2E PROVEN** on studio `5ac4444c`: pasted a mixed EBITDA SOP → classifier returned 5 spans correctly typed → SKILL bound active (sector/ebitda_actual/ly/budget) → approve wrote 1 instruction + 2 data-rules + 1 knowledge-doc + 1 user pack (pack_body set). Library pack set dormant to isolate → live agent run logged `[DOMAIN_PACKS] injected pack block (chars=1594)` → agent computed identical GBU (Pharma +20/+10 GOOD … Construction −23/−17 UGLY). **The user-authored pack, reconstructed from `pack_body`, drove the loop.**

**Phase 2 files — new:** `app/ai/packs/teach.py`, `app/routes/studio_teach.py`, `alembic/versions/studioteach1_pack_body.py`. **edited:** `models/studio.py` (+`pack_body`), `ai/packs/runtime.py` (pack_body fallback), `settings/hybrid_flags.py` (+`TEACH_BOX`), `main.py` (register router). Backups `.backups/20260624_phase2_teach_box/`.

**Phase 2 landmines:**
- Registry is FILE-ONLY → a DB-only user pack is invisible to `registry.get_pack`. FIX = `pack_body` column + runtime fallback. (Don't try to write yaml into the container library dir — not baked in the image, lost on rebuild.)
- LLM-authored SKILL inputs don't bind unless the classifier sees the real column names → feed `studio_columns` names into the classify prompt.
- Standalone in-container test scripts hit `InvalidRequestError: 'Completion'` (SQLAlchemy mappers not all imported) — `resolve_injection` swallows it → silent "". Test pack runtime via a REAL HTTP completion (full app context), not a bare script.
- Stored column shape is `{name, dtype, metadata:{role,values,...}}` — hoist `metadata.role` up before handing to the binder.
- `HYBRID_TEACH_BOX` now ON (override) org 55278108. Gated to the teach endpoints only.

### Phase 3 — Teach Box UI  ✅ DONE (2026-06-24)
- [x] `components/studio/StudioTeach.vue` — self-contained: paste box (20k cap) + "✦ Teach AI" button → `POST /studios/{id}/teach`; review cards per span (type badge SKILL/INSTRUCTION/DATA_RULE/KNOWLEDGE, inline-editable title+content, include checkbox, SKILL bind status active/dormant + binding map); footer "re-train after saving" toggle + "Approve & save" → `POST /studios/{id}/teach/approve`. Clay/coral DESIGN_SYSTEM tokens.
- [x] `pages/studios/[id]/index.vue` — added import + `teach` tab in **behavior** group, gated by `teachEnabled` ref (loads `/api/organization/hybrid-flags`, finds `HYBRID_TEACH_BOX.effective`, fail-soft OFF) + section mount.
- **Landmines:**
  - FE `dist` is **baked into the image** (NOT a bind-mount) → must `nuxt generate` on host then `docker cp dist/. ca-app:/app/frontend/dist`. Static files served from disk, **no restart needed**. (Backend stays hot-copy; this is the one FE-rebuild step. `NODE_OPTIONS=--max-old-space-size=6144 npm run generate`, ~min, output lands in BOTH `dist/` and `.output/public/`.)
  - `useMyFetch` baseURL=`/api`; ufo `withBase` **skips double-prefix** so both `/studios/...` and `/api/organization/...` resolve — mirror existing call sites (`/studios/...` for studio routes, `/api/organization/hybrid-flags` for flags).
  - apply summary keys are `skills_active`/`skills_dormant`/`data_rules`/`instructions`/`knowledge` (NOT `skills`) — toast maps accordingly.
  - hybrid-flags GET is `@requires_permission('manage_settings')` → flag only loads for admins/owners; non-admin editors see tab hidden (acceptable parity w/ dash-versions flag; revisit if editors need it).
- **E2E proof:** built+deployed; `HYBRID_TEACH_BOX effective=True` (org 55278108); live `POST /studios/5ac4444c/teach` → HTTP 200, 3 spans (2 DATA_RULE + 1 SKILL "will_be active skill") — exactly the shape the cards render. Teach string present in chunk `dist/_nuxt/Cqo-F34R.js`.

### Phase 4 — Train wiring ✅ DONE (2026-06-24)
- [x] **PACK_AUTOBIND at train** — orchestrator stage 1b tries EVERY library pack against the studio's freshly-profiled columns; full match → `pending` row (review gate), partial match (≥1 input, a required one missing) → `dormant` row carrying `missing` (UI "needs a Budget column"), 0-match → skipped. Idempotent: existing (studio,pack_id) rows never touched. Gated `flags.PACK_AUTOBIND`.
- [x] **seed from method** — `build_skill_context` renders the studio's ACTIVE packs (method snippet + trigger hints + binding) into a text block; passed as new `skill_context=` kwarg into `generate_queries_for_studio` / `generate_evals_for_studio` so the cheap schema-grounded generators bias toward the skills' computations.
- [x] **auto_evals from goldens** — `materialize_pack_goldens` turns any `eval_goldens` an active pack carries into `TestCase` rows (same suite + FieldRule shape as auto_evals; dedupe by name). No-op until goldens exist (library ships `eval_goldens: []`).
- [x] **dormant surfaced** — autobind summary `{bound, dormant:[{pack_id,name,missing}], skipped, existing}` lands in `train_status.detail.packs`.
- **Files:** NEW `backend/app/ai/packs/pack_train.py`; EDITED `train_orchestrator.py` (stage 1b + skill_context threaded + stage 3b goldens), `auto_queries.py` + `auto_evals.py` (+`skill_context` param). Backups `.backups/20260624_phase4_train_wiring/`.
- **Landmines:** (1) bare-script E2E hits the `Completion` mapper-init error → `studio_columns`/`_active_packs` return [] (try/except) — TEST VIA REAL HTTP TRAIN, not a bare `python -c`. (2) per-org flag overrides are NOT in process env; `flags.PACK_AUTOBIND` reads OFF in a bare script — enable via `PUT /api/organization/hybrid-flags/HYBRID_PACK_AUTOBIND {"enabled":true}` (body key is `enabled`, NOT `override`). (3) train status is per-uvicorn-worker, persisted to `Studio.config['_train_status']`; polls bounce non-monotonically across workers — read `detail` on the `done` snapshot.
- **DEFERRED (not Phase 4):** generatively SNAPSHOTTING a pack method on real data to MINT goldens (needs full agent loop) — left for a later pass; Phase 4 biases the existing generators instead.
- **E2E proof:** flag flipped ON for org 55278108; deleted the stale `ebitda-good-bad-ugly` pack row on studio `5ac4444c`, ran real HTTP train → `detail.packs = {bound:1, dormant:[], existing:0, skipped:0}`, DB row recreated `status=pending source=pack conf=0.7` with all 7 inputs bound; `detail.queries.saved=6` + `detail.evals.created=6` (ran with skill_context from the active user pack); `pack_goldens={created:0}` (empty goldens → no-op). Hot-copy + restart deploy (no FE rebuild).

### Phase 5 — Adaptive + harden ✅ DONE (2026-06-24)
- [x] **pack_winrate + feedback demote** — new `pack_winrates(studio_id, pack_id, question_cluster, passes, fails, score)` + `pack_fire_events(completion_id→pack_id,cluster)`. At injection time `runtime.resolve_pack` records WHICH pack fired on the completion (agent_v2 → `winrate.record_fire`); a later 👍/👎 (`completion_feedback_service._maybe_record_pack_signal`, fires both directions) → `record_signal_for_completion` upserts passes/fails + score. `resolve_pack` reads `get_winrate(cluster)` per candidate, feeds it into `router.score_candidate` (demote in ranking) AND BENCHES a proven loser (`is_benched`: score<0.15 over ≥5 samples → skipped as a candidate). Cluster = the matched trigger hint (per-pattern, not global).
- [x] **dormant re-check on drift** — `pack_train.recheck_bindings` runs each train (orchestrator stage 1b, after autobind): re-binds existing dormant/active/pending rows vs the just-profiled columns → dormant→pending when a missing input reappears (re-surface for approval, never auto-activate), active/pending→dormant when a bound column vanishes. `rejected` rows left alone. Summary → `train_status.detail.pack_recheck`.
- [x] **promote-to-org** — new `org_packs` table + `OrgPack` model + `POST /studios/{id}/packs/{pack_id}/promote` (editor+, copies a user pack's inline `pack_body` → org store) + `GET /organization/packs`. `pack_train.autobind_library_packs(db, sid, organization)` now binds org packs alongside the yaml library (org pack written with inline `pack_body`, `source='org'`) → every studio in the org picks it up at its next train. Runtime needs NO change (serves from `pack_body`). Router registered in `main.py`.
- **Files:** migration `backend/alembic/versions/packwin1_pack_winrate.py` (head `packwin1`, 3 tables); NEW `backend/app/ai/packs/winrate.py`, `backend/app/routes/studio_packs.py`; EDITED `models/studio.py` (+3 models), `ai/packs/runtime.py` (`resolve_pack`), `ai/packs/pack_train.py` (org packs + `recheck_bindings`), `ai/agent_v2.py` (record fire), `services/completion_feedback_service.py` (signal hook), `ai/knowledge/train_orchestrator.py` (recheck + org param), `main.py`. Backups `.backups/20260624_phase5_adaptive/`.
- **Landmines:** (1) same bare-script flag landmine — `recheck_bindings`/`record_*` read DOMAIN_PACKS OFF in a bare `python -c` (override not in process env) → test via HTTP. (2) `ErrorCode` has `VALIDATION`, NOT `VALIDATION_ERROR`. (3) `source` col now carries `'org'` in addition to `pack`/`user` (String(20), fits). (4) DEPLOY: hot-copy ALL edited files — easy to miss one (missed `train_orchestrator.py` first pass → recheck silently absent, `pack_recheck=null`); after a migration run `alembic upgrade head` in the container.
- **E2E proof:** migration applied (`packwin1`, 3 tables). (a) Promote: `POST /studios/5ac4444c/packs/user-…/promote` → OrgPack `created`, listed by `GET /organization/packs`. (b) Winrate: seeded a `pack_fire_event` for a real completion, `POST /completions/{id}/feedback {direction:-1}` → background task wrote `pack_winrates` row `passes=0 fails=1 score=0`; `get_winrate=(0.0,1)`, `is_benched(0.0,5)=True`. (c) Drift: forced ebitda row dormant, real HTTP train → `detail.pack_recheck={revived:[ebitda-good-bad-ugly], rebound:2, checked:2}`, row flipped to `pending`.

### Phase 6 — Scale packs (data-only) ✅ DONE (2026-06-24)
- [x] Poured **7 Tier-A fin packs** as pure yaml data files in `backend/app/ai/packs/library/` (NO code change — the registry auto-loads every `*.yaml`): `unit_economics`, `returns_analysis` (IRR/MOIC/TVPI), `three_statement_integrity`, `variance_commentary`, `gl_reconciliation`, `nav_tie_out`, `portfolio_monitoring` — joining the shipped `ebitda_good_bad_ugly` = **8 packs**. Each = INVARIANT method_text (data-blind) + logical `required_inputs` (role/synonyms/optional) the binder maps to real columns + output_spec/format + `eval_goldens: []`.
- **Tier B/C deferred** (additive, future): Tier B (comps/DCF/consensus) needs market-data feeds; Tier C (pptx/xlsx authors) folds into `create_artifact` prompts. Source map + tiers: `docs/PLAN_SMART_FIN_PACK.md`.
- **Deploy:** `docker cp *.yaml ca-app:/app/backend/app/ai/packs/library/` + **restart** (registry caches in-process at first load → restart clears it; no migration, no FE).
- **Landmine:** binder gates on NAME score with a role penalty — an input whose role (measure/dimension) mismatches the column's profiled role drops 0.85→0.595 (<0.6 floor) and won't bind (seen live: `variance-commentary` skipped on the EBITDA studio because its measure inputs hit dimension-typed columns). Honest gating, not a bug; widen synonyms or fix the column role to bind.
- **E2E proof:** registry loads 8 packs; all 7 new packs `bind_pack`=True on representative columns (unit-economics conf 1.0, others 0.7); router picks correctly ("IRR/MOIC by deal"→`returns-analysis`, "reconcile gl vs subledger"→`gl-reconciliation`). Live HTTP train of studio `5ac4444c` autobound the new packs through the real path → `portfolio-monitoring` landed `dormant` (partial), the 6 non-matching skipped, existing rows untouched.

---

## Files (Phase 0)

**New:**
- `backend/app/ai/packs/__init__.py` · `registry.py` · `binder.py` · `router.py` · `runtime.py`
- `backend/app/ai/packs/library/ebitda_good_bad_ugly.yaml`
- `backend/alembic/versions/studiopack1_studio_bound_packs.py`

**Edited:**
- `backend/app/models/studio.py` (+`StudioBoundPack`)
- `backend/app/settings/hybrid_flags.py` (+3 flags, snapshot, UPGRADE_FLAGS)
- `backend/app/ai/agent_v2.py` (+pack injection block after scope guardrail, ~line 2258)

**Backups (recovery):** `.backups/20260624_phase0_domain_packs/` holds the pre-edit `agent_v2.py`, `hybrid_flags.py`, `studio.py`. To revert: copy them back, `docker cp` to `ca-app`, restart; `alembic downgrade dashversions1` to drop the table.

---

## Resume / recovery notes
- **Deploy = hot-copy backend** (free, no heat): `docker cp <file> ca-app:/app/backend/<path>` then `docker restart ca-app`. NEVER `--force-recreate` (reverts cp'd files; rebuild re-bakes from disk instead). Image build (`nuxt generate`) only for FE (Phase 3) — 6 GB heap, laptop heat, batch it.
- **Migration head** is now `studiopack1`. Next migration chains off it.
- **Container:** `ca-app` (image `cityagent-analytics:dev`), DB `ca-postgres` (user/db `dash`, pw `dashpassword`), app `:3007`.
- **Compile in container:** `docker exec -e PYTHONPYCACHEPREFIX=/tmp/pyc ca-app sh -lc 'cd /app/backend && python -m py_compile ...'` (the source `__pycache__` is read-only).
- **rtk landmines:** `ls`/`grep`/`find -exec`/`find -printf` get mangled — use `rtk proxy grep`, plain `find`, or Read.
- **Flags need BOTH** `.env` AND compose env or they read silent-OFF.

## Landmines found (Phase 0)
- Binder: role-match boost could manufacture a false bind from a weak name (revenue_ly→EBITDA_PY). FIX: eligibility on NAME score only (`ns >= _MIN_CONF=0.6`); role just ranks.
- Binder: bidirectional substring over-matched (generic `revenue` ⊂ specific `revenue ly`). FIX: substring strong only when the input TERM is inside the column name, not vice-versa.
- Router: high bind-conf alone cleared the score floor → pack injected on EVERY question (incl. off-topic) = the wrong-skill bug. FIX: mandatory trigger gate (`trigger_score > 0`) before scoring.
- Warehouse camelCase (`BusinessUnit`) didn't tokenize vs multi-word synonyms. FIX: camel-split in `_norm`.
- `BaseSchema` has `updated_at` too (not just created/deleted) — migration must include it.
