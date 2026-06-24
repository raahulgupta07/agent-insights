# CityAgent Analytics

Hybrid agentic-analytics platform — a fork of bagofwords (rebranded **Dash**) on branch `hybrid-brain`, merged with dash dual-schema patterns, a Karpathy-style 2nd-brain, self-service skills, and a per-studio **Auto-train pipeline**.

FastAPI backend + Nuxt 3 SPA frontend. **OpenRouter only** for LLM. Single image `cityagent-analytics:dev`, served on `:3007`.

> Full engineering guide + changelog: **`CLAUDE.md`** (read it before touching anything). Architecture: `docs/ARCHITECTURE.html` · Plans: `docs/PLAN_*.md`.

---

## What it is

An **Agent Studio** wraps a set of pinned data sources (file uploads or warehouse connectors) into a grounded, shareable analytics agent. The agent answers questions over your data, builds dashboards, and gets **trained automatically** — no per-dataset code.

- **Agent Studios** — NotebookLM-style containers: pinned sources + persona + grounded chat + knowledge + evals + artifacts + members/sharing.
- **AI Auto-pilot** — the studio home: a readiness score + one **Auto-train everything** button that profiles columns, learns real values, extracts knowledge from docs, mines joins, writes example queries + eval goldens, and regenerates artifacts — all in the background.
- **Single-analyst loop** — `create_data` (writes/runs pandas+SQL) → `create_artifact` (builds the dashboard), via the AgentV2 plan/execute/reflect loop on `claude-sonnet-4.6` through OpenRouter. Skills / sub-agents / MCP are OFF by default (stability).

---

## Quick start (local dev)

```bash
# one command: pre-pull base images (retry), build cityagent-base:dev once, then the app image
bash scripts/build.sh
# run (scale overlay adds Redis + pgbouncer)
docker compose -f docker-compose.build.yaml -f docker-compose.scale.yaml up -d
curl localhost:3007/health
```

Ports: app `:3007` (internal 3000) · Postgres `:5439` · pgbouncer `:6432` · Redis `:6399`.
Dev admin: `admin@cityagent.io` / `CityAgent#2026` (org "Main Org"). Seed OpenRouter via `backend/scripts/seed_openrouter.py`.

**Frontend is baked** (`nuxt generate`) into the image — `.vue`/config edits need a rebuild + force-recreate. Backend `.py` can be hot-iterated (`docker cp` + `py_compile` + `docker restart`).

```bash
# rebuild after a change
docker compose -f docker-compose.build.yaml build app
docker compose -f docker-compose.build.yaml -f docker-compose.scale.yaml up -d --force-recreate app
```

---

## Onboarding a new agent (any data, any domain)

The pipeline is fully generic — proven on unrelated datasets (CRM, music catalog, financial).

1. **New Studio** → name + sharing (avatar/voice/summary auto-written).
2. **Add data** → upload `.csv`/`.xlsx` (auto-pins) **or** pin a warehouse connector (46 types). A connector with N tables trains every table.
3. **Auto-train everything** → profile · knowledge · joins · queries · evals · 6 artifacts. Readiness climbs 0→100 in the background.
4. Done — the agent answers grounded on your data.

A guided wizard lives at **`/studios/new-agent`** (Name → Data → Train → Ready).

---

## Auto-train pipeline (per pinned source)

| Stage | What | Module |
|---|---|---|
| Profile | every column → role · distinct · sample values · null % (all tables of a connector) | `column_intel` |
| Knowledge | extract definitions from uploaded `.xlsx`/`.pptx`, applied live | auto-configure |
| Queries | LLM example SQL, **verified read-only** before saving | `auto_queries` |
| Evals | golden Q→expected from real aggregates | `auto_evals` |
| Joins | value-overlap mining (works day-1, no query history) + proven-SQL mining | `join_miner` |
| Artifacts | Summary · FAQ · Briefing · Notes · KPI pack · Data dictionary | `studio_artifacts` |

Training is **async** (`POST /studios/{id}/train`, poll `GET .../train/status`) — non-blocking. Re-trains skip unchanged tables (row-count watermark) and surface schema drift (new/dropped columns).

---

## Feature flags

New features are flag-gated (`backend/app/settings/hybrid_flags.py`, env `HYBRID_*`, default OFF; dev `.env` turns them on). Per-org live overrides via Settings → Feature Flags. Key flags: `COLUMN_INTEL · AUTO_QUERIES · AUTO_EVALS · JOIN_GRAPH · DOC_KNOWLEDGE · STUDIOS · SEMANTIC_LAYER · METRICS_CATALOG`. Env knob `STUDIO_LEARN_DAEMON_ENABLED`.

---

## Hard rules

1. **Never** pull `bagofwords/bagofwords:latest` — always build `cityagent-analytics:dev` from this repo.
2. **OpenRouter only** for LLM (Dash `custom` provider, per-org Fernet-encrypted key).
3. Touch Dash core **minimally** — prefer new files + hook points (this is a fast-moving OSS fork).
4. Everything new is **flag-gated** (default OFF); everything learned is **review-gated** (pending → approve).
5. New routes registered in `backend/main.py`; migrations chain off the single true head; no `from __future__ import annotations` on body+permission routes.

6. **UI/UX = `DESIGN_SYSTEM.md`** (repo root, source of truth): clay brand tokens, serif H1, **exactly 3 button variants**, 3 card types, no `gray-*`. Reference mockup `mockup-design-system.html`. New/edited `.vue` must conform.
7. **Agents are scoped to their data.** Every agent has a **scope guardrail** (flag `HYBRID_SCOPE_GATE`, default ON) — refuses off-topic/general-knowledge, answers only from its connected sources. A **studio report is locked to the studio's pinned Data Agents** (composer can't leak other org sources into an agent).
8. **Generated slides + dashboards must stay readable.** Both are LLM-authored (slides = python-pptx, dashboards = React+ECharts). The generator prompts (`backend/app/ai/tools/implementations/create_artifact.py`) enforce a **contrast contract**: the agent picks a light or dark theme per topic, but ALL text, chart axis labels, legends and data-labels must contrast the background (native pptx charts default to black fonts; the `dash` ECharts theme is light-tuned — both must be recolored on dark).

## Roadmap

- **Smart Fin Pack** (`docs/PLAN_SMART_FIN_PACK.md`, PLAN only) — port Anthropic's `anthropics/financial-services` financial expertise (DCF, comps, 3-statement, …) as **domain packs**, WITHOUT the native Skills engine. Copy the universal *method*, machine-synthesize the *data binding* from each agent's schema, auto-bind by detected domain, train via the existing auto-train pipeline, and self-verify — all on the default `create_data`/`create_artifact` tools. 7 packs tiered by data-need (runs-on-our-data / needs-market-feed / output-only).

See `CLAUDE.md` for the complete codebase map, landmines, and per-feature changelog.
