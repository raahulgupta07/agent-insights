# Microsoft Connectors — what we have, what we understand

> Reference for the Microsoft data-source connectors (Fabric, Azure SQL, Power BI, SharePoint/OneDrive)
> and the **per-user identity / Row-Level-Security (RLS)** story. Companion to
> `docs/fabric-rls-architecture` (diagrams) and `CODEBASE_MAP.md`.
> Status: analysis + current implementation. Nothing new built here.

---

## 0. The principle

Microsoft enforces RLS using **`USER_NAME()`** — whoever the SQL connection authenticated as. So the
platform's only job is to make each query run as the **real end-user's Entra identity** (a delegated token),
not a shared service principal. **RLS is enforced by Microsoft, not implemented in the app.** Everything
below exists to carry one person's identity from an LDAP login to `USER_NAME()` inside Fabric.

---

## 1. The connectors we have

| Connector | Auth mechanism | Identity at query time | File:line |
|---|---|---|---|
| **`ms_fabric`** | Service principal **OR** delegated OAuth. SP: `ClientSecretCredential(tenant,client,secret)` → token via ODBC `SQL_COPT_SS_ACCESS_TOKEN`. Delegated: user token, scope `database.windows.net/user_impersonation`. | SP → shared (RLS broken). Delegated → **real user (RLS works)**. | `ms_fabric_client.py:86-92`, `:68` · `connection_oauth_service.py:90` |
| **`ms_fabric_user`** | ODBC `ActiveDirectoryPassword` (Entra user login / ROPC). `Authentication=ActiveDirectoryPassword; UID; PWD`. No app reg. | The Entra user in the connection string (one stored account, shared by all app users). | `ms_fabric_user_client.py:59-68` |
| **`mssql`** | Basic `UID/PWD` ODBC. | One SQL login, shared. | `mssql_client.py:26-70` |
| **`powerbi`** | Service principal, `client_credentials` → scope `…/powerbi/api/.default`. | SP, shared. | `powerbi_client.py:89-95` |
| **`sharepoint` / `onedrive`** | Service principal **OR** per-user delegated OAuth (Graph). | SP (shared) or **per-user delegated token**. | `graph_drive_client.py:82-134` · `connection_oauth_service.py:72-106` |

**Takeaway:** `ms_fabric` (delegated) and `graph_drive` (delegated) are the only paths that carry the
**real end-user identity** downstream — i.e. the only paths where Microsoft RLS / per-user permissions
actually apply. `ms_fabric_user`, `mssql`, `powerbi`, and the service-principal modes all use ONE shared
identity → every app user sees the same rows.

---

## 2. How credentials are chosen at query time

Single decision point: **`resolve_credentials()`** — `connection_service.py:957-1056`.

```
auth_policy = system_only
    → connection.decrypt_credentials()            # ONE shared cred  (RLS bypassed)

auth_policy = user_required  AND  'oauth' in allowed_user_auth_modes
    → user has stored token?  → UserConnectionCredentials.decrypt()   # per-user (RLS enforced)
    → admin chose 'service_account'? → connection.decrypt_credentials() # shared fallback
    → else → 403 "Connect required"
```

- **Per-connection creds** (shared): `Connection.credentials`, Fernet blob — `connection.py:22`,
  decrypt `connection.py:178-183`.
- **Per-user creds**: `UserConnectionCredentials(connection_id, user_id, auth_mode, encrypted_credentials)`
  — `user_connection_credentials.py:10-52`; fetched via `get_user_conn_cred_row()` — `connection_identity.py:56-72`.
- **Refresh-on-query**: `maybe_refresh_oauth_credentials()` — `connection_service.py:1006-1010`.

**To get per-user Fabric RLS, a connection must be:** `auth_policy='user_required'` **+**
`allowed_user_auth_modes=['oauth']`, and the user must have completed a Microsoft Connect (stored token).

---

## 3. Login vs Microsoft identity (the gap)

- **Login:** LDAP bind → internal JWT `{sub:user_id}`, 7-day. **Carries NO Microsoft token.**
  `_ldap_authenticate` — `auth.py:166-199`. LDAP config is DB-sourced via
  `get_effective_ldap_directories()` — `auth.py:99` (not a file).
- **Microsoft tokens** live separately in `OAuthAccount` / `UserConnectionCredentials` (access + refresh,
  Fernet) — `auth.py:671-679`. The JWT does **not** carry them.
- **No global OBO / token-exchange.** Per-user delegated OAuth is supported for connections, but a
  freshly-LDAP'd user has **no Microsoft token** until they do a one-time **Connect** (OAuth consent).

So: **login (LDAP) and data-consent (Microsoft) are two separate identity acts.** For RLS to key off the
right person, the LDAP identity must map to the Entra identity (ideally **AD→Entra federation via Azure AD
Connect**, so LDAP UPN == Entra UPN).

---

## 4. Connector visibility tiers (do NOT confuse with auth)

`Connection.visibility ∈ {private, shared, org}` — `connection.py:78`. Governs **who can SEE / list /
activate** a connector. **Does NOT affect which credential runs the query** (`connection.py:71` comment).
Query-time identity is driven solely by `auth_policy` (§2). `guard_owned_connection` (`connection.py:121-135`)
restricts mutate/test routes to owner-or-admin.

---

## 5. How Fabric RLS / security groups work (Microsoft side)

| Layer | Mechanism | Keyed on | Group support |
|---|---|---|---|
| Workspace role | Admin/Member/Contributor → **RLS bypassed**; Viewer → RLS applies | Entra user/group on workspace | yes |
| OneLake security role *(preview)* | Row filters + folder access, enforced across all engines | Entra **security group** | **native** (cleanest) |
| Warehouse / SQL RLS *(classic)* | `CREATE SECURITY POLICY` + inline TVF predicate | `USER_NAME()` (user UPN) | indirect (user→group map) |
| Object / column perms | `GRANT` / `DENY` on table/column | the connected user | yes |

Classic RLS predicate:

```sql
CREATE FUNCTION Security.tvf_predicate(@SalesRep nvarchar(50))
  RETURNS TABLE WITH SCHEMABINDING AS
  RETURN SELECT 1 AS ok
  WHERE @SalesRep = USER_NAME()           -- must be the REAL user, not a service principal
     OR USER_NAME() = 'manager@contoso.com';
CREATE SECURITY POLICY SalesFilter
  ADD FILTER PREDICATE Security.tvf_predicate(SalesRep) ON sales.Orders WITH (STATE = ON);
```

**Two silent-bypass traps:**
1. App identity holding **Admin/Member/Contributor** workspace role → RLS bypassed entirely. Must be **Viewer**.
2. RLS only applies to **Warehouse / SQL-endpoint** queries. Raw **OneLake file** reads obey OneLake
   security roles, not SQL RLS.

**Group-based RLS decision** ("Myanmar group → Myanmar rows"):
- **Option A** — OneLake security roles bound to Entra security groups (preview, all-engine, clean).
- **Option B** — classic SQL `SECURITY POLICY` + a user→group mapping table (SQL-only, more code).
Both require the real user identity to reach Fabric.

---

## 6. Two tenants

| Concern | Singapore (AWS) · Fabric | Myanmar · Office 365 |
|---|---|---|
| Entra app reg | App reg #1 (or one multi-tenant app) | App reg #2 |
| Authority | `login.microsoftonline.com/<SG-tenant-id>` | `…/<MM-tenant-id>` |
| Delegated scope | `database.windows.net/user_impersonation` + `offline_access` | Graph `Sites.Read.All`, `Files.Read.All` + `offline_access` |
| RLS engine | Warehouse SECURITY POLICY / OneLake roles | SharePoint / site permissions (not SQL RLS) |
| Connector | `ms_fabric` (delegated) | `graph_drive_client` (delegated) |

Each Fabric/O365 connection needs its own app registration (or one multi-tenant app) targeting the right
authority. This is **config**, not new code — `connection_oauth_service` handles the OAuth dance.

---

## 7. What we have vs what's missing

**Have (in code):**
- `ms_fabric` delegated OAuth (`user_impersonation`) — RLS-capable query path. `connection_oauth_service.py:90`
- Per-user token store + query-time resolution. `connection_service.py:957`
- OAuth refresh-on-query. Visibility tiers. LDAP login (DB-config).

**Config / wire-up (not code):**
- Flip Fabric/O365 connections to `auth_policy=user_required` + `allowed_user_auth_modes=['oauth']`.
- Create 2 Entra app regs (SG, MM) + scopes + `offline_access`.
- AD→Entra federation (Azure AD Connect) so login identity == RLS identity.
- App's Fabric workspace role = **Viewer**.

**Gaps to BUILD / VERIFY (security-critical — UNVERIFIED):**
- 🔴 **Result/answer cache must be per-user.** If keyed only by query-hash, user B reads user A's
  RLS-filtered rows. Audit before enabling per-user mode.
- 🔴 **Scheduled reports / agent runs** on a `user_required` connection have no interactive user token →
  if they fall back to the service account, scheduled output **bypasses RLS**. Policy: block scheduling on
  user_required connections, or run-as a named user.
- 🟠 **Permission-denied passthrough** — `ms_fabric_client.execute_query` must surface a Microsoft
  permission error ("no access to table X"), not swallow it into "0 rows".
- 🟠 **UPN match** — optionally block a user who consents with a different Microsoft account than their AD login.
- 🟠 **Token expiry mid-session** — what the user sees when refresh fails (must not silently fall back to
  service creds → would bypass RLS).

---

## 8. Open questions (not yet understood)

- **Cross-tenant guest:** can a Myanmar (tenant-2) user get a delegated token for Singapore Fabric
  (tenant-1) at all, or must they be B2B guests? How does RLS see a guest UPN via `USER_NAME()`?
- **LDAP-only identities:** users in local AD but not in Entra can never get a Fabric token. How many? Fallback?
- **OneLake file vs SQL:** when reading OneLake parquet directly (not the SQL endpoint), does classic SQL
  RLS apply at all, or only OneLake security roles? Which path does `ms_fabric_client` actually use?
- **Group→row map ownership:** if classic RLS needs a user→group table, who maintains it; does it drift
  from Entra group membership?
- **Per-user cache scale:** N×users cache entries — memory / eviction impact?
- **Schema introspection leak:** does `get_schemas` reveal table/column names a user can't query? Is schema
  discovery permission-scoped?
- **"Specific data" scope:** rows only, or also column-level (CLS) / cell masking?

---

## 9. Next steps

1. Confirm AD↔Entra federation + UPN identity *(customer IT)* — unblocks everything.
2. Confirm Fabric RLS style: OneLake roles vs SQL policy, group vs user *(customer Fabric admin)*.
3. **Code audit:** result-cache key + workspace-role + scheduler fallback + error passthrough *(engineering)*.
4. Stand up 2 Entra app regs (SG, MM) in a test tenant.
5. One-user E2E proof: LDAP login → Connect → query Fabric → RLS filters rows → go/no-go.

---

*Grounded in: `auth.py`, `connection_service.py`, `connection_oauth_service.py`, `connection_identity.py`,
`ms_fabric_client.py`, `ms_fabric_user_client.py`, `graph_drive_client.py`, `connection.py`,
`user_connection_credentials.py`, and Microsoft Learn (Fabric RLS, OneLake security).*
