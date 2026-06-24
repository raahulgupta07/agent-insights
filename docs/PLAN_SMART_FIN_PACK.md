# PLAN — Smart Fin Pack (domain packs WITHOUT the native Skills engine)

Status: **ENGINE BUILT + Tier-A SHIPPED (2026-06-24).** The Domain Packs engine (this plan's
machinery) is live — see `docs/PLAN_TEACH_SKILLS_ENGINE.md` Phases 0–6. 8 packs in
`backend/app/ai/packs/library/` (ebitda + 7 Tier-A: unit-economics, returns/IRR-MOIC, 3-statement,
variance, gl-recon, nav-tie-out, portfolio-monitoring). Tier B (market-data feeds) + Tier C
(pptx/xlsx authors) remain additive/future. Below = the original design intent.
Branch `hybrid-brain`. Author intent: get the financial
expertise of Anthropic's `anthropics/financial-services` repo into this platform, but make it
**smart and self-fitting per agent** — NOT a static copy, and NOT via the `HYBRID_SKILLS` exec
engine (which livelocks and is kept OFF; see `[[project_cityagent_analytics]]` STABLE CONFIG).

Everything here rides the **default tools** (`create_data`, `create_artifact` page/slides/excel)
and the **gated context + auto-train surfaces this fork already has**. Skills engine stays off.

---

## 1. What a "Smart Fin Pack" is

A **Fin Pack** = a bundle of financial-analysis capability attached to an agent (Studio):
method playbooks + reference docs + metric definitions + value vocabulary. It lives in surfaces
already wired into the planner — NOT in the Skills loader.

**Smart** = it does not hardcode columns/entities the way a generic skill does. It:
1. **binds** its method inputs to the agent's REAL columns/values,
2. **gates** honestly (won't run a method whose inputs the data lacks),
3. **self-authors** its metrics/queries from the schema,
4. **learns** per-agent from 👍/👎 + proven SQL,
5. **verifies** its own numbers tie out before trusting.

### The core split — copy the INVARIANT, synthesize the VARIABLE
- **INVARIANT (copy once, universal):** the *method* — how DCF/comps/3-statement/margin works,
  required inputs, golden invariants (balance-sheet balances, `margin=(rev−cost)/rev`). This is
  Anthropic's `SKILL.md` gold; it ports verbatim and is data-blind on purpose.
- **VARIABLE (never copy — generate per agent):** which columns are revenue/FCF/debt, what
  "Ensure"/"Digital" mean in THIS data, the actual SQL that computes the metric in THIS warehouse.
  Machine-synthesized from the agent's schema; learned + verified over time.

> Anthropic supplies the financial brain. This fork's `column_intel + semantic + AI-suggest +
> auto-train + eval + distiller` make it fit, self-check, and improve. That wrapper is the "smart".

---

## 2. Source map — `anthropics/financial-services`

Reference impl = **11 named agents** + **7 vertical skill bundles** + 11 MCP connectors +
managed-agent cookbooks. Skills are `SKILL.md` (system prompt + step method + templates/examples)
+ optional `scripts/`/`templates/`. Commands like `/dcf`, `/comps`. File-based, fork-friendly.

**Map onto THIS platform (1:1):**

| Their layer | Our existing equivalent |
|---|---|
| Named agent (pitch-agent, model-builder) | **Studio** (NotebookLM agent = pinned sources + persona + bound packs) |
| Vertical (financial-analysis) | **Domain pack** (this plan) |
| `SKILL.md` method body | **Method playbook Instruction** |
| SKILL.md templates / reference | **KnowledgeDoc** (`HYBRID_DOC_KNOWLEDGE`, PG-FTS, vectorless) |
| SKILL.md examples | **Studio Examples** (few-shot, already assembled) |
| metric/multiple defs (EV/EBITDA, WACC) | **Metrics catalog** (`METRICS_CATALOG`) |
| commands (`/dcf`, `/comps`) | **composer macros / analysis-type selector** (prompt macros → default tools) |
| MCP connectors (FactSet…) | our connectors (~46 + MCP) — swap to own data |
| subagent handoff (`orchestrate.py`) | our subagent fan-out — keep OFF (livelocks); run single-agent |

We port **content/method**, cite Anthropic, do NOT ship their MCP server configs or paid-vendor
assumptions. We bring our own data sources.

---

## 3. All 7 packs + feasibility tiers

"All" = 7 packs (one per vertical) holding ~50 methods. Build the machinery ONCE; content is
additive. The limiter is **what data each method needs**, not the porting.

Packs: `financial-analysis · investment-banking · equity-research · private-equity ·
wealth-management · fund-admin · operations`.

### Tier A — port clean, runs on OUR warehouse data (no external feed). DO FIRST.
3-statement · margin/EBITDA · unit-economics · returns (IRR/MOIC) · variance commentary · GL
reconciliation · NAV tie-out · month-end roll-forwards · KYC rules-grid · portfolio monitoring.
→ computed from data we already have; full value immediately.

### Tier B — method ports, FULL value needs market-data feeds we don't have.
comps (peer financials) · DCF w/ market WACC · earnings-vs-consensus (transcripts) · buyer-list /
sector screens. → without those MCP connectors they run **method-only / on-our-data-only** =
partial; flagged "needs feed" until a source is wired.

### Tier C — output/format skills → map to `create_artifact`.
pptx-author · xlsx-author · deck-refresh · ib-check-deck · cim-builder · teaser. → slides/excel
generation; bounded by the dep-free sandbox (no deep Excel formula-audit).

### Enumerated method inventory (from repo listing)
- **financial-analysis (13):** comps, dcf, lbo, 3-statement, audit-xls, clean-data-xls,
  deck-refresh, competitive-analysis, ib-check-deck, pptx-author, xlsx-author, ppt-template-creator,
  skill-creator.
- **investment-banking (9):** strip-profile, pitch-deck, datapack-builder, cim-builder, teaser,
  buyer-list, merger-model, process-letter, deal-tracker.
- **equity-research (9):** earnings-analysis, earnings-preview, initiating-coverage, model-update,
  morning-note, sector-overview, thesis-tracker, catalyst-calendar, idea-generation.
- **private-equity (10):** deal-sourcing, deal-screening, dd-checklist, dd-meeting-prep,
  unit-economics, returns-analysis, ic-memo, portfolio-monitoring, value-creation-plan, ai-readiness.
- **wealth-management / fund-admin / operations:** not enumerated in the listing (≈ remaining to ~50);
  fetch exact list at import time.

---

## 4. Component ownership (who does each step — all already exist)

| Step | Owner (existing component) |
|---|---|
| Profile schema (role/values/min/max per col) | `app/ai/knowledge/column_intel.py` + `POST /data_sources/{ds}/profile` |
| Detect domain (financial?) | NEW small classifier on table/col/value scan (reuse profiler output) |
| Auto-bind pack ↔ agent | extend Studio `bootstrap_on_source_pin` (`studio_bootstrap.py`) + NEW `agent_packs` binding |
| Synthesize metrics/semantic from schema | `knowledge_proposer.propose_knowledge_from_schema` / AI-suggest |
| Generate financial queries | `HYBRID_AUTO_QUERIES` (auto-train) seeded by pack templates |
| Run + capture proven SQL | `create_data` + `QUERY_CACHE` / Studio examples |
| Generate goldens | `HYBRID_AUTO_EVALS` seeded by method invariants |
| Eval / verify ties-out | `app/services/eval_harness.py` (P4 result-set goldens) |
| Approve (gate) | existing Instruction/knowledge approval (`status pending→approved`) |
| Pre-loop pack router (per question) | reuse ambiguity-gate slot in `agent_v2.py` (1 cheap LLM call) |
| Value resolution (no-guess) | `COLUMN_INTEL` P5 directive |
| Self-improve after | distiller (👎) + 👍 loop + `studio_learn_daemon` |

NEW pieces (small): `packs` registry, `agent_packs` binding, domain detector, pack router, method
prior library import. Everything else is wiring into existing surfaces.

---

## 5. The flow

```
PHASE 0 — PORT (once)                                    [copy METHOD only]
  anthropics SKILL.md ──lift──▶ METHOD PRIOR LIBRARY
     playbook→Instruction · formulas→KnowledgeDoc · inputs list · golden invariants
     (no columns yet — data-blind on purpose)

PHASE 1 — BIND + TRAIN (per agent, one button)          [synthesize VARIABLE]
  Build Studio on financial data ─pin─▶ bootstrap detects domain
     financial? ─yes─▶ AUTO-BIND Fin Pack (agent_packs, pending)
  Hit "Auto-train" → POST /studios/{id}/train (async, 4 workers):
     1 PROFILE    column_intel
     2 BIND       method inputs ⇄ real columns → Metrics+Semantic (pending, AI-suggest)
     3 GEN QUERY  pack templates vs bound schema (HYBRID_AUTO_QUERIES)
     4 RUN        create_data → capture proven SQL → query-cache/examples (agent-bound)
     5 GEN GOLD   method invariants → eval Q + expected result (HYBRID_AUTO_EVALS)
     6 EVAL       ties out? no→FLAG  yes→APPROVE (gate)
     watermark-skip = don't redo learned parts
  ⇒ TRAINED AGENT = bound metrics + proven queries + golden evals (per-agent, gated)

PHASE 2 — RUNTIME (per question)                         [compose + verify]
  Q: "Why did gross margin drop in Q2?"
   → pre-loop PACK ROUTER (ambiguity-gate slot): pick Fin Pack · comps method · DIAGNOSTIC lens
       inject ONLY those (bounded context, top-K docs/metrics)
   → CAPABILITY GATE: inputs present? no→honest fallback  yes→continue
   → VALUE RESOLUTION (COLUMN_INTEL P5): margin→real col, Q2→real range, brands→real values
   → DEFAULT TOOLS: create_data (proven SQL) → create_artifact (contrast-safe page/slides)
   → SELF-VERIFY: eval-check ties out? fail→regenerate
   → ANSWER + 👍/👎 → distiller/learn daemon refine pack (bound to THIS agent)
```

Read it as: **copy the method once → bind+train per agent (one button) → route+gate+run+verify+learn
per question.**

---

## 6. Two axes (compose, don't flatten) — ties to `[[PLAN_ANALYSIS_MODES]]` idea

A pack method composes with an **analysis-type lens**:
- **Descriptive** (what happened) — aggregate/trend/KPI. ✅ SQL.
- **Diagnostic** (why) — contribution/variance/segment/outlier. ✅ SQL+pandas.
- **Predictive** (what next) — moving-avg/trend/seasonal-naive ONLY (sandbox is dep-free:
  numpy/pandas/math allowed, **NO sklearn/scipy**). Heavy ML = separate compute lane.
- **Prescriptive** (what to do) — rank/threshold/scenario via LLM reasoning over diag+pred output.

`Diagnostic × Financial` = "why margin dropped". `Predictive × Retail` = "project Q4 units".
Both run default tools; emergent, not a copied command.

---

## 7. Phased rollout

1. **Build the pack engine ONCE** (vertical-agnostic): `packs` registry, `agent_packs` binding,
   domain detector, pack router, method-prior import path, pack-seeded train + goldens.
2. **financial-analysis pack first** (the 13; esp. 5 modeling: dcf/comps/lbo/3-statement/merger) →
   prove Phase 0→1→2 end-to-end on a real financial data source.
3. **Bulk-import the other 6 verticals' SKILL.md** as packs (cheap, additive).
4. **Tag every method** A/B/C → Tier A live, Tier B flagged "needs feed", Tier C output-only.
5. **Auto-bind** selects the right pack(s) per agent from detected data.

---

## 8. Honest ceilings

- **Knowledge/eval training, NOT model weights** — agent gets smarter via gated context + proven
  queries + goldens, not fine-tuning (OpenRouter only, no GPU; weight-compile lane needs hardware
  we don't have — see `[[project_cityagent_analytics]]` arXiv:2605.22502 note).
- **Eval-gate only as good as the goldens** the method seeds.
- **Predictive/quant capped** by dep-free sandbox — DCF/comps/margin train fine; ML forecast,
  Monte-Carlo, optimization need a separate compute lane.
- **Tier B stays partial** until external market-data feeds are connected (or accept on-data-only).
- **Subagent orchestration OFF** (livelocks) — a named workflow = one Studio with a strong playbook,
  not a multi-agent team.
- **Licensing** — adapt Anthropic's method/content + cite; don't ship their MCP/vendor configs.

---

## 9. Flags (all NEW, default OFF, per HARD RULE 4)

Proposed (env `HYBRID_*` + compose `${...:-0}` + `.env`, or silent-OFF):
`HYBRID_DOMAIN_PACKS` (master), `HYBRID_PACK_AUTOBIND` (detect+bind on pin),
`HYBRID_PACK_ROUTER` (per-question activation). Reuse existing `SEMANTIC_LAYER`/`METRICS_CATALOG`/
`DOC_KNOWLEDGE`/`AUTO_QUERIES`/`AUTO_EVALS`/`EVAL_HARNESS`/`COLUMN_INTEL` for the sub-steps.

---

## 10. One-liner

**Smart Fin Pack = Anthropic's financial METHOD (copied, universal) + this fork's data-binding,
learning, and verification (generated, per-agent).** Port the method once, synthesize the binding
from each agent's schema, gate on what the data supports, train via the existing auto-train pipeline,
and self-verify — financial-skill behavior on the DEFAULT tools, Skills engine off.
