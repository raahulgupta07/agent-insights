# Agent Training — LIVE STATE (Phase 0 audit)

Audit date: **2026-07-01**. Source: running `ca-app` container + `ca-postgres`.
This is GROUND TRUTH — overrides prior memory where they conflict (drift noted).

Companion plan: [TRAINING_TODO.md](TRAINING_TODO.md).

---

## Safety snapshot
- Rollback image: `cityagent-analytics:rollback-training-20260701` (`d848658f35a3`), 6.47GB.
- Ephemeral proven work now protected against rebuild.

## Container / image
- `ca-app` Up, healthy. Image = bare id `e609996cfab3` (prior commit-bake, `dev` tag `6a81fb03ff71`).

---

## Migrations — SOLID
- Single head: **`defreg1`**, DB at head (`alembic current` == `defreg1`).
- In chain: `sessumm1` (P3 agent_definitions), `goldenq1` + `resultcache1` + `verifmetric1` (verified-golden), `connvis1`.
- `colprofile1` **absent** — expected (on unmerged `feature/ingest-brain`).
- 183 migrations total. No hand-DDL drift found for training tables.

## Flag mechanism
- Defined in `app/settings/hybrid_flags.py`, registry `UPGRADE_FLAGS`.
- Default OFF via env; per-org overrides stored in
  `organization_settings.config['hybrid_overrides']`, loaded at boot by
  `load_overrides_from_db()` into a **per-process** `_OVERRIDES` store.
- **No `HYBRID_*` env vars set** in container — all ON-state comes from the DB override layer.

## ⚠️ DRIFT vs memory (corrected)
- Real org with overrides = **`7d372305`** (the proven CRM org), NOT `e02b1b04`.
  `e02b1b04` has no `hybrid_overrides` row live.
- `HYBRID_FULL_PIPELINE` = **true** in DB — but see below, the flag does NOT mean combine is done.

---

## Flags ON (org 7d372305)
`HYBRID_FORECAST, DLT_INGEST, PROFILE_V2, BRAIN_GRAPH, CODE_ENRICH, SMART_UPLOAD,`
`FULL_PIPELINE, ROBUST_INGEST, TRAIN_ROUTING, GOLDEN_QUERIES, SEMANTIC_LAYER,`
`METRICS_CATALOG, ONE_TABLE_MERGE, SEMANTIC_SEARCH, INGEST_RECONCILE, VERIFIED_METRICS,`
`AUTO_MAP_GLOSSARY, MERGE_SAME_SCHEMA, PERSIST_WAREHOUSE, PROACTIVE_INSIGHTS`

## Flags OFF (matter for training trust)
- `HYBRID_VERIFIED_GOLDENS` — P4/P5 eval gate. **OFF.**
- `HYBRID_QUERY_CORRECTION` — P6 corrector. **OFF.**
- `HYBRID_DEF_REGISTRY` — P3 definition registry. **OFF.**
- `HYBRID_LOGIC_PARSER` — P2 doc→triples. **OFF.**

---

## What `HYBRID_FULL_PIPELINE` ACTUALLY does (key finding)
In `train_orchestrator.py`, `FULL_PIPELINE` gates **only**:
- `hybrid_index` (line ~996) — same as `SEMANTIC_SEARCH`
- `brain_graph` (line ~1015) — same as `BRAIN_GRAPH`

It does **NOT** wire the S1–S8 / P0–P12 doc-driven verified pipeline. The flag's
"15 stages" label is aspirational. **Combine is genuinely NOT done.**

`run_training()` real stages: profile → queries → evals → artifacts + route_inbox
(HYBRID_TRAIN_ROUTING) + hybrid_index + brain_graph.

## Verified-golden pipeline — built but NOT wired into train
Zero references to verified-golden / eval_gate / corrector / def_registry / logic_parser
in `train_orchestrator.py`. They live as standalone components + a separate HTTP route:
- `app/routes/pipeline.py` (197 lines) — endpoints `POST .../pipeline/build-goldens`
  (logic_parser → registry → golden_gen → eval_gate → _save_golden) and
  `POST .../pipeline/recorrect` (corrector).
- `app/services/ingest/logic_parser.py` (P2)
- `app/services/train/eval_gate.py` (P4/P5), `corrector.py` (P6), `registry.py`, `golden_gen.py`
- `app/models/agent_definition.py` (P3)

**Implication:** Phase 2 combine = invoke `pipeline.py`'s stage chain from inside
`run_training()`, gated on `FULL_PIPELINE` + `VERIFIED_GOLDENS`. Services already
exist — this is wiring, not new logic. Medium size, low-ish risk (fail-soft per stage).

---

## Corrected TODO deltas
- **Phase 2** is the true center of gravity: the eval-gate/corrector/def-registry
  services exist but are orphaned from the live train run. Wire them, don't rebuild.
- **Phase 3** flags (`VERIFIED_GOLDENS`, `QUERY_CORRECTION`, `DEF_REGISTRY`,
  `LOGIC_PARSER`) are OFF *and* unwired — flipping them alone does nothing to the
  main train until Phase 2 wiring lands.
- Migrations (Phase 1) essentially DONE for the merged path; only `colprofile1`
  outstanding and only if `feature/ingest-brain` is merged (Phase 4 decision).
- Target org for E2E verify = **7d372305** (has the data + flags), not e02b1b04.
