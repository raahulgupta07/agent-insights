# AWS Phase 0 — Stop the OOM restart loop + fix upload/training failure

**Host:** `insights.citygpt.xyz` · **Stack:** `docker-compose.npm.yaml` (services `postgres` → `dash-postgres`,
`redis` → `dash-redis`, **`app` → container `dash-app`, image `cityagent-analytics:dev` v1.155**,
`nginx-proxy-manager` → `dash-npm`). The app is NOT published on a host port — NPM fronts it and reaches it
internally at `app:3000`. The app health endpoint is `http://localhost:3000/health` *inside the container*.

> **Scope:** Phase 0 is **config only — no code deploy, no image rebuild.** Everything below is env / DB flag /
> NPM settings + a container recreate. There is a paste-once helper at `scripts/aws_phase0.sh` (read-only by
> default; `--apply` to act).
>
> **Service name vs container name:** `docker compose ... <service>` takes the **service** name `app`.
> `docker logs` / `docker inspect` / `docker exec` take the **container** name `dash-app`. Both are used below.

---

## 1. Diagnose first (2 min) — which problem is it?

Run these on the box:

```bash
# a. Are containers up? Is the app flapping?
docker ps -a

# b. Did the kernel OOM-kill the app? How many times has it restarted?
docker inspect dash-app --format 'OOMKilled={{.State.OOMKilled}} Status={{.State.Status}} Restarts={{.RestartCount}}'

# c. How much RAM / how many cores does the box have?
free -h
nproc

# d. What do the last 20 min of app logs say?
docker logs dash-app --since 20m 2>&1 | grep -iE "memoryerror|sigkill|killed|AUTOTRAIN_STAGING_ROLE_SECRET|worker"
```

### Decision tree

| Symptom | Path |
|---|---|
| `OOMKilled=true`, or `MemoryError` / `SIGKILL` / `Killed` in logs, or `Restarts` climbing | **Memory path — continue Fix 1 → 5 below.** |
| `AUTOTRAIN_STAGING_ROLE_SECRET ... must be set` traceback in logs (upload/train dies, no OOM) | **Do Fix 1 (secret), then Recreate + Verify.** This is the upload/training failure. |
| **No OOM**, containers healthy, but browser shows **"Load failed"** on requests that take >30s (uploads, training, long chats) | **NPM proxy-timeout path — see below. NOT a memory problem.** |

#### NPM proxy-timeout path (only if the decision tree points here)

Long requests dying at ~30–60s with "Load failed" in the browser while the container stays healthy = NPM is
buffering / timing out the response, not the app crashing. Fix it in the NPM admin UI (`http://<SERVER_IP>:81`):

**NPM → Hosts → Proxy Hosts → `insights.citygpt.xyz` → Edit → Advanced tab**, paste (this is the streaming
block from `docker-compose.npm.yaml`, with the long read/send timeouts that matter here):

```nginx
proxy_buffering off;
proxy_cache off;
proxy_request_buffering off;
proxy_http_version 1.1;
proxy_read_timeout 3600s;
proxy_send_timeout 3600s;
client_max_body_size 0;
```

Save. No container restart needed (NPM reloads its own nginx). `proxy_buffering off` fixes frozen SSE chat;
`proxy_read_timeout`/`client_max_body_size 0` fix long uploads/training dying mid-request. This path is
independent of the memory fixes — do it if and only if the diagnosis points here.

---

## 2. Fix 1 — set `AUTOTRAIN_STAGING_ROLE_SECRET` (fixes the upload/training failure)

Every autotrain upload provisions a per-org Postgres staging schema + a restricted login role, and the role
password is derived (HMAC) from `AUTOTRAIN_STAGING_ROLE_SECRET`. If it is **unset or shorter than 16 chars**,
`backend/app/services/ingest/tenant_schema.py::_secret()` raises:

```
RuntimeError: autotrain: AUTOTRAIN_STAGING_ROLE_SECRET (>=16 chars, dedicated random)
must be set to provision per-org staging roles
```

…and the upload / training run fails. The compose already wires it through
(`AUTOTRAIN_STAGING_ROLE_SECRET=${AUTOTRAIN_STAGING_ROLE_SECRET:-}` on the `app` service) — it just needs a value
in the AWS `.env`.

Generate a dedicated high-entropy secret (24 bytes → 48 hex chars, well over the 16 min):

```bash
openssl rand -hex 24
```

Add it to the AWS `.env` (the one next to `docker-compose.npm.yaml`):

```bash
AUTOTRAIN_STAGING_ROLE_SECRET=<paste the openssl output>
```

> ⚠️ **This secret must be STABLE — set it once and never change it.** The per-org staging role passwords are
> HMAC-derived from it. Rotating it re-derives every org's role password, so existing staging roles/schemas can
> no longer authenticate until they are re-provisioned. Treat it like an encryption key: back it up, don't
> regenerate on every deploy. It is a **dedicated** secret — do **not** reuse the DB password (that reuse is
> exactly what `_secret()` refuses to fall back to).

---

## 3. Fix 2 — memory cap (`mem_limit`)

The compose already ships a cgroup hard cap on the `app` service:

```yaml
mem_limit: 12g   # ~70% of box RAM — engineer: set to 0.7 * total RAM
```

> **Another agent is editing the compose file in parallel.** Do not re-add this yourself — just **verify** it is
> present and sized to **~70% of the box's total RAM** (from `free -h` in step 1). If the box is 16 GB, `12g` is
> right; if it's 8 GB use `~6g`; if 32 GB use `~22g`. This is a single-host `docker compose` deploy (Compose
> Spec, no top-level `version:` key) → `mem_limit` is honored as a real cgroup cap, so the app OOMs cleanly
> instead of thrashing the whole host. (If this were ever run under Swarm, `mem_limit` is ignored there — the
> equivalent is `deploy.resources.limits.memory`. It is not, so `mem_limit` is correct.)

A `mem_limit` change is applied by the recreate in step 5.

---

## 4. Fix 3 — enable the 3 sandbox flags for the org

The memory relief comes from three flags in `backend/app/settings/hybrid_flags.py`, all **default OFF**
(env keys / defaults):

| Flag (env key) | Default | What it does |
|---|---|---|
| `HYBRID_SUBPROCESS_SANDBOX` | `False` | Runs uploaded-file analysis code in a **fresh isolated child process** so its memory is freed after every run instead of piling up in the shared worker heap. **This is the main OOM fix.** |
| `HYBRID_SANDBOX_PUSHDOWN` | `False` | Prompt-only nudge: push filter/aggregate/LIMIT down to SQL, pull only needed rows instead of loading whole tables into pandas. Cuts per-run memory. Safe. |
| `HYBRID_SUBPROCESS_SANDBOX_LIVE` | `False` | Extends the subprocess sandbox to **live-DB-client** runs (rebuilds a plain-SQL client in the child). **HOLD for Phase 0.** |

> **HOLD `HYBRID_SUBPROCESS_SANDBOX_LIVE` until Phase 1.** Known gap: the live-subprocess path currently drops
> query capture / quota accounting / result-cache for runs that go through it. Enable **only**
> `HYBRID_SUBPROCESS_SANDBOX` + `HYBRID_SANDBOX_PUSHDOWN` now. Turn on `_LIVE` after Phase 1 verifies capture/quota/cache
> survive the child process.

### Method A — UI (recommended)

Settings → **Features** → category **Performance** → toggle **ON**:

- **Subprocess sandbox (isolated code exec)** = `HYBRID_SUBPROCESS_SANDBOX`
- **SQL pushdown (memory discipline)** = `HYBRID_SANDBOX_PUSHDOWN`

Leave **Subprocess sandbox — live DB clients** (`HYBRID_SUBPROCESS_SANDBOX_LIVE`) **OFF**.

The UI writes these to `organization_settings.config['hybrid_overrides']`. **A recreate is still required**
(step 5) — the flags are read into the process override store at boot by `load_overrides_from_db`
(`main.py` startup, ~L514), so a running process won't pick up a DB change until it restarts.

### Method B — SQL fallback (if the UI is unreachable because the app is crash-looping)

Connect to Postgres (`dash-postgres`, db/user/pass `dash`/`dash`/`dashpassword`):

```bash
docker exec -it dash-postgres psql -U dash -d dash
```

1. Discover the org id (this deploy has ONE org):

```sql
SELECT id, name FROM organizations;
```

2. Set the two flags in `hybrid_overrides` (repeat per flag). **Landmine:** `organization_settings.config` is a
   **`json`** column, NOT `jsonb` — `jsonb_set` does not exist for `json`, so you must cast **into** `jsonb` and
   back **out** to `json`:

```sql
-- Subprocess sandbox (the main OOM fix)
UPDATE organization_settings
SET config = jsonb_set(config::jsonb, '{hybrid_overrides,HYBRID_SUBPROCESS_SANDBOX}', 'true')::json
WHERE organization_id = '<org-id-from-step-1>';

-- SQL pushdown
UPDATE organization_settings
SET config = jsonb_set(config::jsonb, '{hybrid_overrides,HYBRID_SANDBOX_PUSHDOWN}', 'true')::json
WHERE organization_id = '<org-id-from-step-1>';
```

> Do **NOT** set `HYBRID_SUBPROCESS_SANDBOX_LIVE` here — leave it absent/false for Phase 0.
> `load_overrides_from_db` only honors keys that exist in `UPGRADE_FLAGS` and stores them by their full
> `HYBRID_*` env name — the keys above are exactly right. If `hybrid_overrides` doesn't exist yet on the row,
> `jsonb_set` creates the leaf as long as the parent path exists; if `config` is `NULL` first do
> `UPDATE organization_settings SET config = '{"hybrid_overrides":{}}'::json WHERE organization_id='<org>';`

Verify the write:

```sql
SELECT organization_id, config::jsonb -> 'hybrid_overrides'
FROM organization_settings WHERE organization_id = '<org-id>';
```

---

## 5. Recreate to apply

Both the `.env` secret (Fix 1), the `mem_limit` (Fix 2), and the DB flag overrides (Fix 3, loaded at boot by
`load_overrides_from_db`) need the container recreated:

```bash
docker compose -f docker-compose.npm.yaml up -d --force-recreate app
```

> **Warning:** `--force-recreate` reverts any hot-`docker cp`'d files back to the image. That is **fine here** —
> the image is `cityagent-analytics:dev` **v1.155** and Phase 0 changes nothing in the image (env + DB + NPM
> only). If someone had hot-patched code onto the running container, it would be lost — but Phase 0 doesn't.

Watch it come up:

```bash
docker logs dash-app --since 2m 2>&1 | tail -40
docker logs dash-app --since 2m 2>&1 | grep -i "hybrid flag override"   # should log "Loaded N hybrid flag override(s)"
```

---

## 6. Verify (success criteria)

```bash
# a. App answers health from inside the container (NPM fronts 3000, no host port)
docker exec dash-app curl -fsS http://localhost:3000/health && echo OK

# b. Secret is now present in the container env
docker exec dash-app printenv AUTOTRAIN_STAGING_ROLE_SECRET | head -c 8; echo " ...(set)"

# c. After putting some load on it (do an upload + a chat), the app did NOT get OOM-killed
docker inspect dash-app --format 'OOMKilled={{.State.OOMKilled}} Status={{.State.Status}} Restarts={{.RestartCount}}'
```

Then in the product:

1. **Upload a file.** Confirm a Postgres staging table appears and there is **no `AUTOTRAIN_STAGING_ROLE_SECRET`
   traceback** and **no DuckDB "same database file" error** in the logs:

   ```bash
   # a per-org staging schema + table should now exist
   docker exec dash-postgres psql -U dash -d dash -c "\dn staging_*"
   docker exec dash-postgres psql -U dash -d dash -c "\dt staging_*.*"
   # logs should be clean of the secret error
   docker logs dash-app --since 5m 2>&1 | grep -iE "AUTOTRAIN_STAGING_ROLE_SECRET|same database file|memoryerror" || echo "clean"
   ```

2. **Run a "summarise this data" chat** against the uploaded source. It should **complete** with an answer and
   the container should **not restart** during the run:

   ```bash
   docker inspect dash-app --format 'Restarts={{.RestartCount}}'   # note before
   # ...run the chat in the browser...
   docker inspect dash-app --format 'Restarts={{.RestartCount}}'   # unchanged = success
   ```

Success = health 200, secret set, no OOM after load, upload creates a `staging_<org>` table with no secret/DuckDB
traceback, and a summarise chat completes with zero restarts.

---

## 7. Rollback

All Phase 0 changes are reversible without an image change:

- **Undo the flags (UI):** Settings → Features → toggle `HYBRID_SUBPROCESS_SANDBOX` + `HYBRID_SANDBOX_PUSHDOWN`
  **OFF**, then recreate.
- **Undo the flags (SQL):** set them back to `false` (same `config::jsonb ... ::json` cast) or remove the keys:

  ```sql
  UPDATE organization_settings
  SET config = jsonb_set(config::jsonb, '{hybrid_overrides,HYBRID_SUBPROCESS_SANDBOX}', 'false')::json
  WHERE organization_id = '<org-id>';
  UPDATE organization_settings
  SET config = jsonb_set(config::jsonb, '{hybrid_overrides,HYBRID_SANDBOX_PUSHDOWN}', 'false')::json
  WHERE organization_id = '<org-id>';
  ```

- **Undo the secret:** removing `AUTOTRAIN_STAGING_ROLE_SECRET` from `.env` reverts autotrain to the failing
  state — only do this if the value was wrong, and replace it (don't leave it empty; keep the SAME value once
  chosen). Never rotate it casually (see Fix 1 warning).
- **Undo `mem_limit`:** owned by the compose file (other agent) — revert there if needed.
- **Apply any rollback:** `docker compose -f docker-compose.npm.yaml up -d --force-recreate app`.
- **Image rollback:** Phase 0 does not touch the image, so no image rollback is needed. If a *later* phase bakes
  a bad image, roll the `app` service's `image:` back to the prior tag and recreate; the running image here is
  `cityagent-analytics:dev` v1.155.
