# PLAN — Changelog System + "What's new" Notification

Versioned changelog for our hybrid features, surfaced as a **🔔 What's new** popover in the
top nav (bell before the user profile), matching the target design (Activity / What's new tabs,
version chip, per-release cards, "See all").

Additive, flag-gated where it touches the agent path (here: pure UI + read-only API, low risk).
Backups before touching `TopNav.vue`. No migration except one tiny per-user "last seen" store.

## Decisions (defaults chosen — override if you disagree)
- **Version scheme:** new **hybrid semver** in `VERSION_HYBRID` starting `1.2.0` (separate from
  upstream `VERSION=0.0.412`). Keeps our features clean, doesn't fight bagofwords bumps.
- **Source of truth:** human-written `CHANGELOG_HYBRID.md` → parsed to structured JSON at build
  (write prose, machine reads it). One file, no double-entry.
- **Activity tab:** placeholder for now (tab renders, empty-state) — wire to real events later.

---

## Data model / source

`CHANGELOG_HYBRID.md` — strict, parseable format:
```
## v1.2.0 — Intelligence Layer — 8 agent grounding capabilities  (2026-06-25)
- Deep Profiler: per-column role catalog + value distribution
- Verified Metrics: locked, authoritative metric values
- Golden Queries: proven SQL reused first
- Proactive Insights: anomaly chips on every result
- Studio → Intelligence rail UI
```
- `## v<semver> — <title>  (<YYYY-MM-DD>)` header + `-` bullets = features.
- Newest on top. `VERSION_HYBRID` = top entry's version (build asserts they match).

---

## Phase 1 — Changelog parse + API (backend)

### 1a `changelog_parser.py` (new, pure)
- `app/services/changelog.py`: `parse_changelog(md_text) -> [{version,title,date,features:[...]}]`.
  Regex header + bullets; never-raise → `[]` on bad input.
- `current_version()` reads `VERSION_HYBRID`.

### 1b last-seen store (per user)
- Reuse `user_settings` / `organization_settings` JSON if present; else 1 column
  `users.last_seen_changelog` (String, nullable). **Tiny migration** off head `hybridsearch1`
  (`chlogseen1`). Guard PG-only DDL.

### 1c routes `app/routes/changelog.py` (new, registered in main.py)
- `GET /api/changelog` → `{current, entries:[...]}` (full list, public-authed).
- `GET /api/changelog/unseen` → `{count, latest, current}` (entries newer than user's last_seen).
- `POST /api/changelog/seen` → set user's last_seen = current. (clears badge)
- Read-only, fail-soft (parse error → empty, never 500).

---

## Phase 2 — "What's new" popover (frontend)

### 2a `components/nav/WhatsNew.vue` (new)
- Bell button + badge (unseen count) → `UDropdown`/popover (bottom-end), matches mockup:
  - Tabs: **Activity** (placeholder empty-state) · **What's new** (default when unseen>0).
  - Version chip: `v1.2.0 · baked · ● Up to date` (green) / `Update available` if newer.
  - Per-release cards: latest expanded, older collapsed; **See all (N)** → `/changelog`.
- Fetch via `useMyFetch('/changelog')` + `/changelog/unseen`; on open → `POST /changelog/seen`
  (optimistic clear badge).
- Clay tokens, serif title, DESIGN_SYSTEM-compliant. No `gray-*`.

### 2b wire into TopNav (backup first)
- `frontend/components/nav/TopNav.vue` right cluster (~L130 `ms-auto` row): insert
  `<WhatsNew />` **between New-Report button and the user `UDropdown`** (bell before profile).
  Explicit import (Nuxt path-prefix landmine). Mobile: bell in the hamburger sheet or icon-only.

### 2c full changelog page
- `pages/changelog/index.vue` — all entries, version-grouped (reuse popover card). Nav: optional
  link under a Help/About menu, or just reachable via "See all".

---

## Phase 3 — seed + automate
- Backfill `CHANGELOG_HYBRID.md` with our real history (compressed from DEVLOG):
  v1.2.0 Intelligence Layer · v1.1.0 (prior baked set) · etc. (one entry per shipped wave).
- Convention (add to CLAUDE.md): **every shipped feature bumps `VERSION_HYBRID` + a
  `CHANGELOG_HYBRID.md` entry** (mirrors the CityPharma version-release discipline).
- Optional: build step parses md → `frontend/public/changelog.json` so the FE can render even if
  the API is down (static fallback).

---

## Build order / fan-out
- P1 (backend API+parse) and P2a (WhatsNew.vue) are independent → parallel.
- P2b (TopNav wire) depends on P2a; one owner for TopNav.vue (+ backup).
- Migration (1b) owned by the P1 agent only.
- Suggested: Agent1 = P1 (parser+routes+migration), Agent2 = P2a (WhatsNew.vue + changelog page),
  parent = P2b wire + seed CHANGELOG_HYBRID.md + main.py register + backups.

## Risk / guards
- Pure UI + read-only API + 1 nullable column → near-zero risk; fail-soft everywhere.
- No agent-path / prompt change → no flag needed (optional `HYBRID_WHATSNEW` if you want a kill-switch).
- TopNav is high-traffic → backup + explicit import + verify build.

## Verify
- `import main` clean, single alembic head `chlogseen1`, badge shows unseen count, opening clears it,
  "See all" page lists all, version chip reflects `VERSION_HYBRID`. Bake FE + commit.
