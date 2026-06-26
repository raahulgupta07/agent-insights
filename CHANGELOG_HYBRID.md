# What's new — CityAgent Analytics

Hybrid feature changelog (our additions on top of the bagofwords/Dash base). Newest first.
Format per entry: `## v<semver> — <title>  (<YYYY-MM-DD>)` followed by `-` feature bullets.
Every shipped feature bumps `VERSION_HYBRID` and adds an entry here.

## v1.24.0 — Per-agent Channels (two-pane) + per-agent Email/SMTP + Dockerfile build speedups  (2026-06-26)
- **Per-agent Channels tab** (`components/studio/StudioChannels.vue`): the agent's channels move out of "Access & Channels" into their own left-rail **Channels** tab, redesigned as the org-style **two-pane picker** (platform list + detail pane) instead of a flat card. Same config method (reuses the Slack/Teams/WhatsApp/AI-Mailbox modals + Telegram/MCP) — only re-laid-out. Status dots, set-up/reconfigure/enable/disable/delete per platform. Scoped to this agent's data.
- **Per-agent Email / SMTP tab** (NEW, `components/studio/StudioEmail.vue`): an agent can send its outbound mail (shares, scheduled results, channel/mailbox replies) from the **global default** OR its **own custom SMTP**. Mode radio; custom fields mirror org SMTP (host/port/security/user/pass/from/validate-certs) + connection test. Stored in `Studio.config['smtp']` (Fernet password), no migration.
  - Backend: `email_client_resolver` gains a **per-agent SMTP tier** (`get_studio_smtp` + `studio_smtp` precedence in `choose_outbound`; `resolve_outbound(..., studio_id=)`) — agent custom SMTP wins over org/global. Routes `GET/PUT/POST-test /api/studios/{id}/smtp` (flag `HYBRID_AGENT_CHANNELS`, owner/editor). Wired `studio_id` through `notification_service` (dispatch + send_custom_email + _resolved_send), report-share (`report.py`), and channel replies (`email_send_service`). NULL studio / global mode = unchanged behavior.
  - Rail split: **Access & Members** (who/model/members/connections) + **Channels** + **Email / SMTP**.
- **Dockerfile build speedups**: dropped non-deterministic `apt-get upgrade -y` from the backend + frontend builder stages (pin to base image, cache-stable); added BuildKit cache mounts for the Vite/Nuxt transform caches on `yarn generate` → faster repeat FE rebuilds. Runtime `base` stage keeps its security upgrade.

## v1.23.0 — Parquet result storage + interactive query endpoint + per-agent channels  (2026-06-26)
- **Parquet result storage** (`backend/app/services/parquet_store.py`): large step results (≥`HYBRID_PARQUET_MIN_ROWS`=2000 rows) offload to compressed Parquet on the `ca_uploads` volume instead of inline JSON in Postgres — smaller DB, faster dashboards. Transparent hydrate on read (CSV/PDF/agent paths uncompromised). Flag `HYBRID_PARQUET_RESULTS` **default ON**. Crash-safe, fail-soft, GC via daily purge sweep. Docs: `docs/parquet-results.md`.
- **Interactive query endpoint** `POST /steps/{id}/query`: declarative allow-listed DuckDB pushdown (filter/group/agg/sort/page) over the Parquet — returns only the slice + true total_rows. No raw SQL; cols/ops allow-listed; limit cap 5000. Frontend `useStepQuery` + dashboard routes cross-filter/sort/page through it for `source:"parquet"` steps; inline steps keep client-side path.
- **Per-agent channels** (flag `HYBRID_AGENT_CHANNELS` default ON): each agent/studio configures its own Slack/Teams/WhatsApp/AI Mailbox/MCP/Telegram (Studio → Access & Channels), scoped to that agent's pinned data. Backend per-studio CRUD for all types (upsert, Fernet creds, audience). **Inbound routing** (phase 2): Slack/Teams/WhatsApp webhooks bind the report to the matched channel's `studio_id` → ReportService auto-scopes to that studio's sources (data isolation). Per-agent rows preferred over org-wide. NULL studio_id = unchanged org behavior.
- **`scripts/safe-upgrade.sh`** (NEW): guarded bake — rollback-tag image, backup DB+uploads volume together, health-gate, auto-rollback on failure.

## v1.22.0 — Full app warm-theme sweep (every remaining page/component)  (2026-06-26)
- Completed the warm-palette rollout across the ENTIRE app: 32 remaining pages + 148 components + 3 layouts migrated. Zero clay residue anywhere.
- Covers report detail/chat workspace, agents (all tabs), monitoring console, evals runs, templates/queries detail, onboarding, auth pages, excel, files, changelog, public share/embed (`c/`, `r/`).
- Token-only migration: clay→coral (`#C2541E`/`#A8330F`), borders `#E9E0D3`, surfaces `#F4EEE5`, headers → Spectral 32px. **Zero icons/logos/logic changed.**

## v1.21.0 — Settings warm-theme restyle (all 11 tabs)  (2026-06-25)
- Migrated all Settings tabs to the warm design palette: Members/Access, LLM/Models, AI Settings, General, Channels/Integrations, Folder Sync, Audit, Identity Provider (SSO/SCIM/LDAP), SMTP, Feature Flags, Pack Analytics.
- Recolored the settings layout (`layouts/settings.vue`) + settings-imported components (`sync/FolderSyncPanel.vue`, Email/WhatsApp/Teams/Slack integration modals).
- Token-only migration: clay→coral (`#C2541E`/`#A8330F`), borders `#E9E0D3`, surfaces `#F4EEE5`, headers → Spectral 32px. **Zero icons/logos changed, zero functionality touched** (per request).

## v1.20.0 — Nav rail (no dropdowns) + Workspace/Build/Manage page restyle  (2026-06-25)
- **Nav rail** — replaced the top-nav dropdowns (Workspace/Build/Manage/Settings) with a contextual **left rail** (`components/nav/AppRail.vue`). Top items now route to the group's first page; the rail shows ONLY that group's items (one group at a time). Nav model extracted to shared `composables/useAppNav.ts` (single source for TopNav + AppRail). Mounted in `layouts/default.vue` non-report branch; self-hides on Home / Agent Studios / detail pages that own a rail.
- **Studio detail tab persists in URL** (`pages/studios/[id]/index.vue`): `?tab=` query — refresh keeps the sub-tab instead of resetting to Auto-pilot.
- **Workspace** — Templates page (`pages/templates/index.vue`) restyled to `Workspace v2` design: Spectral header, segmented Org/Global/All, gradient icon-tile cards, coral "Use template".
- **Build** (all 5: Knowledge, Instructions, Queries, Skills, Memory) — warm palette migration (clay→coral `#C2541E`/`#A8330F`, borders `#E9E0D3`, surfaces `#F4EEE5`), Spectral 32px headers.
- **Manage** (Connectors, Evals, Workflows) — same warm migration + Spectral headers. (Monitoring deferred — own `layout: 'monitoring'` console.)
- Restyle only; all data/logic/permissions/tabs unchanged. Remaining Workspace views (Reports/Dashboards/Presentations/Spreadsheets/Scheduled) + Settings + Monitoring console pending.

## v1.19.0 — Studio detail retheme + Open/refresh crash fix (bake)  (2026-06-25)
- Rethemed the studio detail/workspace page (`pages/studios/[id]/index.vue`) to the warm design system: cream bg + Hanken body, coral accents (`#C2541E`/`#A8330F`), Spectral serif headings, warm borders (`#E9E0D3`).
- **Fixed studio Open → refresh crash** (`Cannot read properties of null (reading 'name')`): teleported `FolderSyncSetupModal` + `FolderSyncCard` read `studio.name` in a separate reactive scope during the cold-load null window, before `fetchStudio` resolved — not covered by the parent `v-else-if` guard. Added `v-if="studio"` + `studio?.name || ''` on both.
- Bakes durable everything previously shipped via ephemeral FE-sync (studio retheme, crash fix, AgentThinking widget).
- Added `scripts/fe-sync.sh` — host `nuxt generate` + `docker cp` into `ca-app` for FE iteration without a full image rebuild (ephemeral; reverts on force-recreate).

## v1.18.0 — Design system rollout: Studios, Home, Nav, Reports + Agent status widget  (2026-06-25)
- Applied the Claude Design warm palette (cream `#F6F1EA`, ink `#1A1611`, coral `#C2541E`/`#A8330F`/`#D67037`, Spectral serif + Hanken Grotesk) across the authed app — restyle only, no functional changes.
- **Studios** (`pages/studios/index.vue` + `components/studio/StudioCard.vue`): cream bg, Spectral 38px header, "YOUR AGENT STUDIOS" label, coral New button. Card → Studios v2 mock: dark live-activity header (gradient + grid-drift + orange blob + animated equalizer on live / dashed "awaiting first source" on draft), white overlapping icon badge, Spectral italic persona, live-stats vs draft/ready progress, coral + ghost action bar. Equalizer + Live dot keep animating under reduced-motion.
- **Home** (`pages/index.vue`): cream bg, orange orb glow, greeting eyebrow, Spectral 46px "What should we *explore* today?", subtitle; dropped purple bottom-glow + full-logo hero. Real composer/suggestions/reports children unchanged.
- **Top nav** (`components/nav/TopNav.vue`): cream translucent bar (blur + `#E9E0D3` border), gradient logo mark + "City Agent Insights" wordmark, warm nav links (active `#A8330F`), cream New-report pill, dark-gradient avatar. Full-width — flush left/right, no side gap. Spectral + Hanken loaded app-wide here.
- **Reports** (`components/home/RecentReports.vue` + `RecentReportCard.vue`): scope dropdown → **segmented tab** (Main Org / My Reports). Cards restyled (badge + Chat/Dashboard buttons) keeping the **real** server thumbnail preview — no fake numbers; no-preview falls back to a mode icon.
- **Agent status widget** (`components/agent/AgentThinking.vue`, global in `layouts/default.vue`): floating coral robot launcher → dark terminal popover typing real boot lines (`synced N sources · M tables` from `/data_sources`, `vector index warm`, `ready.`) with blinking cursor; footer = Idle + real default model from `/llm/models`. Fail-soft, counts warmed in background.

## v1.17.0 — Login page redesign (Claude Design handoff)  (2026-06-25)
- Reimplemented `pages/users/sign-in.vue` pixel-faithful to the Claude Design mock (`City Agent Insights Login.dc.html`). New warm palette (`#F6F1EA` bg, `#C2541E`/`#A8330F` accent), Spectral serif headline + Hanken Grotesk body (loaded via `useHead`), gradient logo mark, floating-label EMAIL/PASSWORD fields with a Show/Hide pill.
- Removed the `4 sources · 11 tables · 67 columns · data 2026-06-20` stat line from the left column (per request).
- ALL auth buttons now present: Google + Microsoft (2-col social row) and a dedicated **Enterprise Sign-in** box with **SSO / Keycloak / LDAP**. Wiring: Google → `/api/auth/google/authorize`; Microsoft/Keycloak/SSO → `signInWithProvider()` matched against the org's configured OIDC providers (regex map, fail-soft message when a provider isn't configured); LDAP → reveals + focuses the directory username/password form (LDAP authenticates through the same `/api/auth/jwt/login`).
- Right panel replaced with an animated "agent at work" showcase: a 3-turn loop (pick data source → live progress checklist → result card with growing bar chart + delta), ported from the design's `DCLogic` state machine to Vue refs + timers, cleaned up on unmount, and disabled under `prefers-reduced-motion`. Hidden below 1024px (single-column form on mobile).
- Version chip stays dynamic (`hybrid_version` from `/api/settings`).

## v1.16.1 — Login version chip is real (was hardcoded v2.4.0)  (2026-06-25)
- Sign-in page chip showed a stale hardcoded `v2.4.0 · local`. Now reads the real product version from `/api/settings.hybrid_version` (= VERSION_HYBRID) and derives the env label from the host (localhost → local, else prod).
- `/api/settings` (public, pre-auth) now returns `hybrid_version` via `changelog.current_version()` — distinct from the upstream-base `version` (PROJECT_VERSION).
- Dockerfile fix: `VERSION_HYBRID` + `CHANGELOG_HYBRID.md` are now COPY'd into the image at `/app/` (final stage). They were never copied, so `current_version()` always fell back to `0.0.0` — this also silently broke the in-app changelog popover. LANDMINE: `app/services/changelog.py` resolves `_REPO_ROOT=/app`; both files must live there in the image.

## v1.16.0 — Feature flags fully UI-owned; ENV is infra-only  (2026-06-25)
- ENV/compose stripped of all ~50 `HYBRID_*` flags + skill-exec knobs + compaction ratio. They now live exclusively in the UI (Settings → Features), persisted per-org in `organization_settings.config['hybrid_overrides']`.
- Defaults are now CODE-owned (`hybrid_flags.py`): 37 product-visible features default ON (Studios, Templates, Folder Sync, Intelligence + Knowledge layer, caches, autotrain, etc.), the rest OFF — so a fresh deploy is fully featured with zero env flags. Previously only `SCOPE_GATE` + `DASH_VERSIONS` defaulted ON and the nginx compose carried the real defaults.
- Resolution order unchanged: per-org override > env > code default. `load_overrides_from_db()` at boot (`main.py:431`) hydrates the process override store from DB — verified live ("Loaded 65 hybrid flag override(s)").
- One-shot migration froze each org's current effective env values into `hybrid_overrides` (org 55278108: 65 overrides, 51 ON) so removing env changed no live behaviour. Pre-existing UI overrides preserved (never clobbered).
- Lean `.env` (~15 vars): DB conn, `DASH_ENCRYPTION_KEY`, `REDIS_URL`, ports, `DASH_CONFIG_PATH`, `DASH_LICENSE_KEY`, `AUTOTRAIN_STAGING_*`, plus bootstrap seeds (LLM key/models via dash-config or UI; super-admin `DASH_ADMIN_*`).
- LANDMINE: do NOT re-add flag vars to compose/.env — they shadow the UI until an org sets an override. New flags get their default in `hybrid_flags.py` (`_bool("NAME", default)`), not in compose.

## v1.15.0 — Hybrid Search is real: embeddings via OpenRouter  (2026-06-25)
- `HYBRID_SEMANTIC_SEARCH` was a scaffold (empty index, no embedder, never wired). It now works end-to-end:
  - **Embedder** (`app/ai/knowledge/embeddings.py`) — reuses the org's existing OpenRouter key (OpenAI-compatible `/embeddings`), model `openai/text-embedding-3-small` (1536-dim → matches the existing `embedding vector(1536)` column, no migration). Batched, fail-soft. Env knobs `HYBRID_EMBED_MODEL/DIM/BATCH`.
  - **Indexer** (`app/ai/knowledge/indexer.py`) — `reindex_org()` rebuilds `knowledge_search_index` from approved semantic tables / metrics / query library / docs, sets the PG `tsv` and the `embedding` vector.
  - **Retrieval** — `hybrid_search()` gained a pgvector cosine-KNN arm; now fuses FTS + vector + token-Jaccard via 3-way RRF.
  - **Wired into the agent** — new `HybridSearchContextBuilder` + section, primed in `context_hub` and appended to the planner instructions in `agent_v2` (gated by SEMANTIC_SEARCH). Top approved knowledge is injected as grounding for each question.
  - **UI + API** — `POST /api/knowledge/reindex` + `GET /api/knowledge/search-index/status`; a "Rebuild search index" button appears on the Hybrid Search row in Settings → Features when it's on.
- Proven live: 293 assets indexed + embedded via OpenRouter (200 OK); "revenue by month" returns Total Revenue / Revenue-by-Country etc. ranked by RRF.
- Flag reclassified `unstable` → `experimental` (works once a key is set). Without a key, only the full-text arm builds (still useful).

## v1.14.0 — All feature flags toggleable from the UI  (2026-06-25)
- Settings → Features now lists **every** hybrid flag (65, up from ~32), grouped into 8 sections (Core, Knowledge, Intelligence, Agents & Access, Ingest, Learning, Advanced, Daemons). Previously most flags — including Agent Studios itself, the caches, semantic/metrics layer, autotrain and the daemons — weren't registered, so they couldn't be toggled from the UI and the override was silently ignored.
- Each flag carries a status badge so risky ones are honest, not silently broken: `needs setup` (Forecast → needs Prophet bake; Federation → needs S3), `unstable` (Skills sandbox can livelock; Hybrid Search is a scaffold), `experimental` (Subagents/token-heavy, Bitemporal, etc.), `needs restart` (the boot-read daemons). Enabling an unstable/needs-setup flag pops a confirm dialog with the caveat.
- Page gained search + an Enabled/Disabled filter and an "N / M on" counter.
- Backend: extended `UPGRADE_FLAGS` with `category`/`status`/`note` per flag (and added every missing flag); `_effective()` now falls back to override-or-env for the env-only daemon knobs (no `flags` property). Same `GET/PUT /api/organization/hybrid-flags` endpoints — no new routes, no migration. Per-org overrides still beat `.env` and apply live (daemons after a restart).

## v1.13.2 — Fix "Sign-up is disabled" when admin creates a user  (2026-06-25)
- Direct user creation hit the fastapi-users registration gate (`_validate_user_creation`), which rejects any non-first signup when uninvited-signups are off → "Sign-up is disabled. Ask your admin for an invite." That gate is the invite flow the admin is explicitly opting out of. Admin-initiated creation now inserts the user directly (hash password + active/verified), bypassing the gate, then attaches the org membership. Mirrors the OAuth path's direct `user_db` create.

## v1.13.1 — Fix blank charts in dashboard full-screen  (2026-06-25)
- Clicking full-screen on a dashboard showed only the static header card with the rest black. The full-screen overlay renders a SECOND iframe, but the data was only ever posted to the background iframe — so the full-screen one rendered its chrome with empty charts. Now `ARTIFACT_DATA` is broadcast to both iframes (background + full-screen), plus a belt-and-suspenders re-send on the full-screen iframe's load. Charts now render in full-screen.

## v1.13.0 — Super-admin creates users directly + features ON in nginx deploy  (2026-06-25)
- Add user with email + password directly — NO email invitation. Settings → Members → "Add user" now takes a name, email and password and creates an active, verified account the user can sign in with immediately. New endpoint `POST /api/organizations/{id}/members/create-user` (admin-gated, `manage_members`); the password is set by the admin and shown in plain text in the form so it can be shared. The old email-invite path still exists for SMTP deployments.
- Fix "Agent Studios are not enabled" (and other locked pages) on the nginx deploy: `docker-compose.nginx.yaml` was missing the `HYBRID_*` env block entirely, so every feature flag fell back to its default-OFF. It now passes the full flag set with product-visible, stable features defaulting ON (Studios, Agent Templates, Folder Sync, per-agent ACL/Channels, follow-ups, semantic/metrics layer, deep profiler, proactive insights, golden queries, verified metrics, query/result/answer cache, domain packs, teach box, agent memory, auto-train, dual-schema/engineer assets, brain read/distiller). Daemons, experimental and token-heavy paths (Skills sandbox, Subagents, Skill Optimizer, Workflows, context compaction, federation, forecasting, all background daemons) stay OFF — enable per `.env`.
- `docker-compose.nginx.yaml` gains a Redis service (`dash-redis`) so the cache-backed features have a backing store; `REDIS_URL` defaults to `redis://redis:6379/0`.
- Apply on the server: `docker compose -f docker-compose.nginx.yaml up -d --build` (rebuilds the image with the new user-create UI/endpoint and recreates the app with flags on). To override any flag, set it in `.env` (e.g. `HYBRID_SUBAGENTS=1` or `HYBRID_STUDIOS=0`).

## v1.12.0 — nginx reverse-proxy stack  (2026-06-25)
- New `docker-compose.nginx.yaml` + `nginx/nginx.conf`: front the app with nginx (the default proxy for this deployment). nginx publishes the host port (`HTTP_PORT`, default 8001) and proxies to the app over the internal network; the app is not exposed directly.
- nginx tuned for this app: SSE streaming (`proxy_buffering off` so chat streams token-by-token), websocket upgrade passthrough, unlimited upload size, 1h read/send timeouts (no 504 on long agent runs).
- Run it: `docker compose -f docker-compose.nginx.yaml up -d --build` → `http://<host>:<HTTP_PORT>`. Set `HTTP_PORT` + `DASH_BASE_URL` in `.env`.
- Caddy stack (`docker-compose.yaml`, auto-HTTPS) and direct-port (`APP_PORT`) paths still available.

## v1.11.1 — Publish app on configurable host port  (2026-06-25)
- The main `docker-compose.yaml` (Caddy/SSL variant) now publishes the app on the host via `APP_PORT` (default 3000) instead of `expose:` only — fixes "app only shows 3000, can't reach my chosen port". Set `APP_PORT=8001` in `.env` to reach it at `http://<host>:8001`. The container always listens on 3000 internally; this maps host→3000.
- `.env.example` documents `APP_PORT` (and that `DASH_BASE_URL` should match it / your domain)
- Caddy front-door path unchanged: for HTTPS you can drop the published port and let Caddy proxy to `app:3000`

## v1.11.0 — One-command deploy + env super-admin  (2026-06-25)
- `docker compose up -d --build` now works on a clean machine with no pre-step — the runtime base image is folded into the main Dockerfile (no more "cityagent-base:dev pull access denied")
- New `deploy.sh`: one friendly command — bootstraps `.env` from the template, warns on a missing encryption key, then builds and starts everything
- Create the first owner/admin straight from env: set `DASH_ADMIN_EMAIL` + `DASH_ADMIN_PASSWORD` and a fresh deploy seeds the account automatically (idempotent — ignored once any user exists), no sign-up link or curl needed
- `.env.example` + `docker-compose.yaml` document the new admin vars; README/DEPLOY gained a one-command deploy section

## v1.10.0 — Per-agent access control + Telegram channels  (2026-06-25)
- Each agent (Studio) gets an "Access & Channels" settings tab
- Who-can-use: Master (whole org), Scoped (pick specific users/roles) or Link — enforced at chat time, not just in listings (flag HYBRID_AGENT_ACL)
- Per-agent model override: an agent can pin its own model (e.g. Opus) — precedence: request model > agent model > org default
- Per-agent Telegram channel: give an agent its own Telegram bot; only verified members can use it (or open to anyone), each bot is bound to exactly one agent (flag HYBRID_AGENT_CHANNELS)
- Reuses existing per-agent data connections + credential modes (shared vs per-user) so each agent stays data-isolated
- Both features default OFF — behaviour unchanged until enabled per org

## v1.9.0 — Default OpenRouter LLM + .env.example  (2026-06-25)
- New organizations are seeded with a ready OpenRouter provider and the current model set (Claude Sonnet 4.6 default, Claude Haiku 4.5 fast/small, plus Claude Opus 4.8, GPT-5.4 Mini, Gemini 2.5 Flash) — no manual provider setup
- The OpenRouter API key is left blank and entered from the UI (Settings → Models) — never stored in the repo or config; the seeded provider is editable (non-preset)
- Config-driven: `default_llm` block in dash-config supports `provider_type`, `additional_config` (base_url/verify_ssl) and `is_preset:false` for an editable, key-from-UI provider
- A blank key encrypts to a valid blob, so the model is listed and fails with a clear 401 until a real key is set — no decrypt crash
- Added a root `.env.example` documenting every environment variable (DB, encryption key, SSO, SMTP, license, ops) with placeholders only

## v1.8.0 — Rebrand to City Agent Insights  (2026-06-25)
- New CityAgent Insights logo across the app — top nav, home page and the sign-in page
- Renamed "City Agent DASH" → "City Agent Insights" everywhere (default analyst name too)
- Sign-in page cleaned up: removed the sign-up link
- LDAP is now enabled by default in org settings

## v1.7.0 — Slide workspace: Open a deck to edit & analyze  (2026-06-25)
- "Open" on a presentation now opens a clean slide workspace — the deck big on the left, a chat on the right
- The right chat is framed for slides ("Edit & analyze slides") — ask it to edit a slide or analyze the deck
- The cluttered panel tabs are hidden in this mode — just the deck
- Expand a slide to true fullscreen (Esc to exit); slide navigation stays usable
- Empty decks show a clear "No slides yet — generate a deck" instead of a blank panel
- Clearer list buttons: Open (slide workspace) vs Open in chat (the conversation); 0-slide decks say "Open & generate"

## v1.6.0 — Upload a whole folder at once  (2026-06-25)
- New "Upload a whole folder" button in the file-upload modal — picks every Excel/CSV inside a folder in one go
- Each spreadsheet becomes its own data agent (Office lock files and non-spreadsheets are skipped)
- One-shot from the browser — no desktop app needed (for continuous auto-sync, use Folder Sync ⟳)

## v1.5.1 — Folder Sync: working download buttons  (2026-06-25)
- The macOS / Windows / Linux buttons now actually download the sync app (a small Python program) as a zip
- Each download includes an INSTALL.txt with the exact setup commands for that OS
- (Signed native installers still to come — for now: pip install + python sync_agent.py)

## v1.5.0 — Folder Sync: a local folder, like Claude Code  (2026-06-25)
- Desktop sync app: point it at a folder and new/changed Excel & CSV files become data agents automatically — no clicks
- Per-agent binding: a folder syncs into a specific agent; the tray app picks which one
- Smart deltas: byte-identical files are skipped, edited files replace the same agent (no duplicates), deletes are ignored
- API-key auth: the headless agent pairs with a one-time sync key — generate it from Settings → Folder Sync or any agent's "Add data → Sync a folder"
- Connected-machines view: see every machine, its folder→agent mappings, file counts and last sync time
- Off by default (HYBRID_FOLDER_SYNC) — turn it on per org

## v1.4.2 — Clearer Agent Studios page  (2026-06-25)
- One "New Agent Studio" button (removed the duplicate add card)
- Lifecycle status on every card: Draft → Ready → Live → Idle
- Agents with no data now clearly say "needs data" with an Add-data button
- Cleaner cards — real stats only once they exist, no rows of zeros

## v1.4.1 — Smoother "Use template" journey  (2026-06-25)
- Use template now opens a guided popup (preview → data → map → review → build) instead of a page jump
- Three ways to add data: use an existing source, connect/upload new, or skip and add it later
- Skip builds the agent with the playbook now; bind columns when your data arrives

## v1.4.0 — Agent Templates: share an agent's best practices  (2026-06-25)
- Export a smart agent as a portable, versioned Template — rules, metric formulas, example patterns, skills and persona, with data and credentials stripped
- Template Gallery: browse Org and Global templates and reuse them
- Bind wizard: map a template's required columns to your own data, then build your own agent
- Imported rules and metrics land pending for review — never auto-applied

## v1.3.0 — Install as an app  (2026-06-25)
- Installable PWA: add CityAgent to your desktop or home screen as a standalone app
- One-click "Install app" button in the top bar (next to notifications)
- Offline app shell — the interface loads even on a flaky connection
- Auto-update: the app refreshes to the latest version on its own

## v1.2.0 — Intelligence Layer — 8 agent grounding capabilities  (2026-06-25)
- Deep Profiler: per-column role catalog (dimension / measure / identifier / temporal) plus value distribution and variant warnings
- Verified Metrics: locked, authoritative metric values that override improvised formulas
- Golden Queries: proven SQL is promoted and reused first
- Proactive Insights: anomaly and trend chips surfaced on every result
- Lazy Profile: tables added after training are profiled inline at query time
- Studio Intelligence rail: a new per-agent panel to view and toggle all eight capabilities
- "What's new" notifications: a release feed in the top bar with a version chip

## v1.1.0 — Studios, Auto-train pipeline & Domain Packs  (2026-06-23)
- Agent Studios: wrap pinned data sources into a grounded, shareable analytics agent
- Auto-train everything: one button to profile columns, mine joins, write example queries and generate artifacts
- Domain Packs: 48 lightweight skill recipes that steer the planner without executing code
- Teach Box: paste an analysis and have it classified into a skill, instruction, data rule or knowledge
- Auto-pilot studio home: add a source or upload files, then train in three steps
- BI dashboards: cross-filtering, conditional formatting, KPI cards and data bars

## v1.0.0 — Hybrid brain foundation  (2026-06-18)
- OpenRouter-only LLM wiring (per-org Fernet-encrypted key)
- Knowledge Layer: semantic model, metrics catalog and query library with an approval gate
- 2nd-brain learning: self-distillation from feedback, query cache and a serving funnel
- Self-service Skills with progressive disclosure and promote-from-chat authoring
- Answer cache and verified-metric grounding for faster, more reliable answers
