# Power BI Connectors — Reference

CityAgent Analytics has **three** Power BI connectors. Two hit the **cloud** Power BI
Service (live DAX over semantic models); one hits an **on-prem** Report Server.

| Connector | `type` | Auth | Target | Semantic layer (live DAX) |
|-----------|--------|------|--------|---------------------------|
| `PowerBIClient` | `powerbi` | Service Principal **or** Sign-in-with-Microsoft (OAuth/OBO) | Power BI cloud Service | ✅ `executeQueries` |
| `PowerBIUserClient` | `powerbi_user` | User login — ROPC (email + password) | Power BI cloud Service | ✅ (inherits engine) |
| `PowerBIReportServerClient` | `powerbi_report_server` | NTLM (on-prem domain user) | On-prem Report Server | ❌ downloads `.pbix`, reads offline |

Files:
- `backend/app/data_sources/clients/powerbi_client.py` (base engine, 948 lines)
- `backend/app/data_sources/clients/powerbi_user_client.py` (subclass — overrides only `connect()`)
- `backend/app/data_sources/clients/powerbi_report_server_client.py`
- Registry: `backend/app/schemas/data_source_registry.py` (entries `powerbi`, `powerbi_user`, `powerbi_report_server`)
- Cred schemas: `backend/app/schemas/data_sources/configs.py`
- OAuth/OBO: `backend/app/services/connection_oauth_service.py`, `backend/app/routes/connection_oauth.py`

---

## Key fact (read first)

**Power BI cloud API only accepts tokens from Entra ID (Azure AD)**, audience
`https://analysis.windows.net/powerbi/api`. No other IdP (Keycloak, on-prem AD,
Okta…) can mint that token directly. Every cloud path below ends in an Entra token.

---

## Connector 1 — `powerbi` (cloud)

Base engine. **Two auth modes** (registry `by_auth`):

### 1a. Service Principal (app identity)
```
ADMIN SETUP (once, external):
  Azure: register app → client_id + client_secret
  Power BI admin: enable "SP can use APIs" + add app to workspace + dataset Build perm
        │
        ▼
  POST /token  grant_type=client_credentials  ──► Entra ──► app token (NO user, NO 2FA)
        │
        ▼
  GET /datasets + POST /executeQueries (DAX) ──► Power BI semantic model ──► rows
```
- **2FA:** N/A — no user, immune.
- **Headless:** ✅ scheduled jobs OK.
- **Blocker:** admin must grant SP + Build. (This is the P8 wall.)
- Creds (`PowerBICredentials`): `tenant_id`, `client_id`, `client_secret` (+ optional `oauth_client_id/secret`).

### 1b. Sign in with Microsoft (delegated, **OBO**) — the 2FA-safe path ✅
```
User → "Sign in with Microsoft" (Entra SSO)
       └─ 2FA happens HERE in browser ✓  (Entra handles MFA natively: push / TOTP / FIDO)
            │  app receives user's Entra login token
            ▼
       OBO exchange (grant_type = urn:ietf:params:oauth:grant-type:jwt-bearer)  ──► Entra
            │  scope: https://analysis.windows.net/powerbi/api/.default offline_access
            ▼
       Power BI access token + REFRESH token (silent renew, no re-login) ✓
            │
            ▼
       POST /executeQueries (DAX) ──► semantic model ──► rows
```
- Runs **as the user**, with the user's own dataset permissions.
- **2FA:** handled natively by the Entra browser sign-in.
- `powerbi` is registered in `ENTRA_OBO_CONNECTION_TYPES` (`connection_oauth_service.py`).
- **Blocker:** an app registration (client_id+secret) with the **delegated** Power BI
  API permission + redirect URI. NO admin Build-grant headache (runs as user).
- **This is the recommended 2FA-user path. Already built.**

---

## Connector 2 — `powerbi_user` (cloud, ROPC) — legacy/weak

```
NO admin setup. Uses YOUR account + YOUR permissions.
  creds: tenant_id + email + password
        │
        ▼
  POST /token  grant_type=password  ──► Entra
        │   MFA ON?  → AADSTS50076 / 50079  ✗  BLOCKED
        │   MFA OFF? → token                ✓
        ▼
  GET /datasets + POST /executeQueries (DAX) ──► semantic model ──► rows
```
- Subclass of `PowerBIClient`; overrides only `connect()` (token grab). All discovery /
  DAX / schema inherited.
- Creds (`PowerbiUserCredentials`): `tenant_id`, `username` (email), `password`,
  optional `client_id` (public client; default = Microsoft public client
  `1950a258-227b-4e31-a9cf-717495945fc2`).
- **2FA: DIES** — ROPC password grant is blocked by MFA (`AADSTS50076`). The client
  surfaces the raw `AADSTS` code and hints "use device-code or service principal".
- **Use only** for service-style accounts with MFA explicitly OFF and ROPC allowed.

### 2c. Cross-tenant B2B guest — the real-world case (PROVEN LIVE 2026-07-01)

The common enterprise split: a user's **Office-365 identity is in tenant A** (home) but the
**Fabric/Power BI workspaces live in tenant B** (a different org) where they're a **B2B guest**.
A token minted against the home tenant can NEVER see tenant B's workspaces (`/groups` returns
only home). The whole fix = **authenticate ROPC against tenant B's id** with the SAME home
email+password — guest password grant works (device-code NOT required when MFA is off).

- **`tenant_id` lives in `PowerbiUserCredentials` (per-user)**, not in Config → each user enters
  their OWN (guest) tenant → cross-tenant per-user works natively. Two users on the same source
  can point at two different tenants.
- **Proven** (org: `<pbi-test-user>`): home City Holdings `0f69909c` (MM) vs guest
  City Mart Holding `0a8a4f2c` (Singapore, domain `citymartholdinglimited.onmicrosoft.com`) where
  `DataAgent_TestRun` lives. ROPC against `0a8a4f2c` → `/groups` shows it → `executeQueries` on
  `Open Project Tracking` (PremiumFiles) returned 258 project rows.

### 2d. Tenant auto-discovery (P2, built 2026-07-01)

Users rarely know their guest tenant GUID. `services/powerbi_tenant_discovery.py`
`discover_tenants(username, password)` mints a `management.azure.com/.default` ROPC token and calls
ARM `GET /tenants?api-version=2020-01-01` → lists EVERY tenant the identity can reach (home + all
guest). Route `POST /api/data_sources/powerbi/discover-tenants` (flag `POWERBI_USER`, fail-soft).
FE `UserDataSourceCredentialsModal.vue` → **"Find my tenants"** button under the tenant_id field
fills a click-to-pick list. Verified live: returns both tenants above.

### Per-user access SCAN (how "what can this user see" works)

The access scan = `PowerBIClient.get_schemas()` run **with the caller's per-user token** (resolved
via `auth_policy=user_required` + `UserDataSourceCredentialsService`):
`list_workspaces()` (`/groups`, their tenant only) → `list_datasets(ws)` (parallel) → tables via
**batch admin scan → COLUMNSTATISTICS → get_dataset_tables** (COLUMNSTATISTICS returns column
metadata WITHOUT `INFO.TABLES`, which is API-blocked) → assembles `"{Dataset}/{Table}"` Tables +
relationships. Result persists as a **per-user overlay** (`UserDataSourceTable`/`UserDataSourceColumn`)
so two users on one source get different, isolated catalogs. Trigger: auto on first query
(`read_user_data_source_schema` live-fallback warms the overlay) or an explicit per-user Refresh schema.
Gap: one connection scans the ONE tenant in its creds — a "scan ALL my discovered tenants → merged
overlay" loop is not built (see backlog #8).

---

## Connector 3 — `powerbi_report_server` (on-prem) — unrelated to 2FA

- On-prem Power BI Report Server. **NTLM** auth (domain or local Windows user).
- Discovers reports / paginated reports / shared datasets / KPIs / upstream lineage.
- PBIX semantic models queried via **DuckDB over a cached Parquet snapshot** — data
  reflects the **last PBIX refresh, not live** upstream.
- No Entra, no cloud API, no live DAX. Not part of the 2FA discussion.

---

## "I have a 2FA user — what works?"

| Path | 2FA | Admin needed | Headless | Status |
|------|-----|--------------|----------|--------|
| `powerbi` Service Principal | immune (no user) | YES (SP + Build) | ✅ | built; blocked on admin grant |
| `powerbi` Sign-in-with-Microsoft (**OBO**) | ✅ native | app reg only | ❌ (per-user) | **built — recommended** |
| `powerbi_user` ROPC | ❌ breaks | NO | ❌ | built; unusable with MFA |
| device-code (into `powerbi_user`) | ✅ | NO | ❌ | **not built** (optional add) |

**Bottom line:** for a 2FA user, use **`powerbi` → Sign in with Microsoft (OBO)**. It's
already coded, 2FA-native, and refresh-token backed.

---

## Keycloak (already federated to AD) — does it help?

Power BI cloud needs an **Entra** token. So:

- **Keycloak → on-prem AD only (LDAP/Kerberos):** that's your domain AD, *not* Entra
  cloud. Power BI cloud rejects it. **No help for cloud Power BI.** (Only relevant to
  the on-prem `powerbi_report_server`, which is NTLM.)

- **Keycloak → brokers Entra ID (Azure OIDC):** CAN work, but adds a hop:
  1. Add the `https://analysis.windows.net/powerbi/api` scope to the Azure IdP in Keycloak.
  2. Enable **Store Tokens** on that IdP.
  3. Retrieve the brokered Azure token via Keycloak's broker endpoint → feed to OBO.
  - 2FA happens at Entra during the brokered login.
  - Works, but config-heavy and fragile vs. just using "Sign in with Microsoft" directly.

**Recommendation:** skip Keycloak for Power BI data access. Use the built-in
"Sign in with Microsoft" + OBO. Keycloak only earns its keep if you specifically want
the app's SSO login to *also* mint the Power BI token (store-tokens + OBO).

---

## Improvement backlog

### `powerbi_user` (ROPC)
1. **Device-code mode** — add `auth_mode: device_code` so 2FA users can self-serve
   without admin. (Browser code login; refresh-token backed.) *Optional now that OBO exists.*
   **(P3 — still not built; the only remaining blocker for MFA-on accounts.)**
2. **Refresh-token storage** — ROPC token ~1h, no refresh → re-login churn.
3. **Build-permission preflight** — connect succeeds but DAX later 403s. Probe each
   dataset (`EVALUATE ROW("ok",1)`) on connect; label queryable vs read-only up front.
   **(P5 — storage-mode gate: also skip AAS-live/on-prem-gateway datasets which REST can't query.)**
4. **Cut speculative `client_id` field** if unused (Simplicity-first).
8. **Scan ALL discovered tenants** — after tenant-discovery (2d), loop `get_schemas()` per
   discovered tenant → single merged per-user overlay tagged by tenant. Makes "show me everything
   I can access anywhere" real. Today one connection = one tenant.
9. **P4 brute table-discovery fallback** — for datasets where admin-scan AND COLUMNSTATISTICS both
   fail, probe common table names (`EVALUATE TOPN(1,'Name')`) as a last resort; cache per dataset.

**DONE 2026-07-01 (v1.63.x):** per-user cross-tenant sign-in (2c) + tenant auto-discovery (2d) + per-user
access scan/overlay. Flag `POWERBI_USER`.

**DONE 2026-07-01 (v1.64.0, BAKED):** #8 scan-ALL-tenants + P5 storage-mode gate + P4 brute table-discovery.
- **#8** `services/powerbi_multi_tenant_scan.py::scan_all_tenants` loops `get_schemas()` per discovered tenant
  (ThreadPool, fail-soft per tenant) → tables tagged `powerbi.tenantId/tenantName` → merged per-user overlay via
  `_upsert_user_overlay`. Route `POST /data_sources/{id}/my-credentials/scan-all-tenants` + FE "Scan all my tenants"
  button. Makes "everything I can access anywhere" real.
- **P5** `_is_dataset_queryable` tags each table `powerbi.queryable` (+ storageMode/isOnPremGatewayRequired) at scan
  time; on-prem-gateway/AAS-live surfaced but flagged non-queryable so the agent skips them.
- **P4** `_brute_discover_tables` probes ~40 common names via `EVALUATE TOPN(1,'Name')` for lakehouse/warehouse
  models that reject COLUMNSTATISTICS. HARDENED: skip empty DBs ("…at least one table" error) + abort on first 429.
- Proven live: 1 identity → 2 tenants, 24 merged tables, 18 queryable/6 not, tenant-tagged, no 429 storm.
- Baked `cityagent-analytics:v1.64.0` (build + commit), flag ON org 7d372305, rollback `pre-powerbi-rollback`.
  NOT git-pushed. See DEVLOG 2026-07-01.

**DONE 2026-07-01 (v1.65.0, BAKED) — P3 device-code sign-in (MFA-safe):** `services/powerbi_device_code.py`
(`start_device_code`/`poll_device_code`, MS public client, scope `…/powerbi/api/.default offline_access`). Routes
`POST /data_sources/{id}/my-credentials/device-code/{start,poll}`; poll-success persists the refresh_token
(Fernet-encrypted). `PowerBIUserClient` gains a `refresh_token` param + refresh-grant branch in `connect()`
(rotates the refresh token) taking precedence over ROPC. `PowerbiUserCredentials`: username/password optional +
hidden `refresh_token`. FE "Sign in with a code" button (show user_code + verification_uri, poll to approval).
Proven live (SG tenant): approved in browser → refresh_token → list_workspaces = 3 SG workspaces. Baked `:v1.65.0`,
rollback `pre-p3-rollback`. **Now any Power BI user (MFA or not, any/guest tenant) can self-connect.** Tester:
`scratchpad/pbi_devicecode_app.py` (:8901, device-code + password + find-tenants + scan + DAX; in-memory tokens).

### `powerbi` (SP)
5. **Clearer 403** — when admin grant missing, return "App connected but lacks
   Build/workspace access — admin must grant", not bare 403.
6. **Dataset Build surfacing** — same preflight as #3.

### Shared
7. **Unified preflight helper** — one probe both connectors call; returns
   `queryable` / `read-only` / `no-access` per dataset. Stops "connected but answers fail".

**Explicitly NOT planned** (speculative, unrequested): caching layer, retry/backoff,
multi-tenant token vault, async refresh daemon.

**Priority:** OBO path (already built) covers 2FA. Highest-value new work = the shared
preflight (#3/#5/#6/#7) — ~30 lines, low risk, kills the biggest user confusion.
