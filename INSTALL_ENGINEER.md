# CityAgent Analytics — Install Guide

Self-hosted install. Builds from source; reproduces the audited default state
(commit `049f0e2`+ on `main`). ~15–20 min on first build.

## 0. Prerequisites
- Docker + Docker Compose (Docker Desktop or engine).
- Give Docker **≥ 10 GB memory** (the frontend build needs ~6 GB; less → OOM).
- `git`.
- An **OpenRouter API key** (https://openrouter.ai) — you'll paste it in the UI, NOT in any file.

## 1. Get the code
```bash
git clone git@github.com:raahulgupta07/rahulai-dash.git cityagent-analytics
cd cityagent-analytics
git checkout main
```

## 2. Configure `.env`
```bash
cp .env.example .env
```
Edit `.env` and set the ONE required secret — the encryption key (encrypts stored
credentials). Generate one:
```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```
Paste it into `.env`:
```
DASH_ENCRYPTION_KEY=<paste the generated key>
```
Defaults you can leave as-is: `APP_PORT=3007`, `POSTGRES_PORT=5439`, `REDIS_PORT=6399`,
`DASH_BASE_URL=http://localhost:3007`, `ENVIRONMENT=development`.

> Do NOT put the OpenRouter key or an admin password in `.env` — both are set from the UI (step 6–7).
> (Optional alternative: uncomment `DASH_ADMIN_EMAIL` / `DASH_ADMIN_PASSWORD` to auto-seed the admin at boot instead of the UI signup in step 6.)

## 3. Build the image
```bash
bash scripts/build.sh
```
Builds `cityagent-base:dev` once, then `cityagent-analytics:dev`. Re-run anytime; later builds are fast.

## 4. Start
```bash
docker compose -f docker-compose.build.yaml up -d
```
Brings up `ca-postgres` (Postgres 18 + pgvector), `ca-redis`, `ca-app`.
**Database migrations run automatically on boot** (no manual step).

Wait until healthy (~30–60 s):
```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3007/   # expect 200
```

## 5. Open the app
http://localhost:3007

## 6. Create the admin (first run)
Go to **http://localhost:3007/users/sign-up** and register.
**The very first account becomes the super-admin** and its organization is created automatically.

## 7. Add the LLM key (one-time, in the UI)
Settings → **Models** → the pre-seeded **OpenRouter** provider → paste your OpenRouter API key → Save.
The default models light up. The app is OpenRouter-only; the key is stored encrypted in the DB.

That's it. Add data sources (upload a CSV/Excel, or connect a warehouse) from the UI and start asking questions.

---

## Feature defaults (already baked — no config needed)
Everything fail-soft is **ON** out of the box. Only **8 are OFF**:
- **Visible, OFF on purpose (toggle in Settings → Feature Flags if you want them):**
  - `AMBIGUITY_GATE` — off because it forced clarify-loops; the agent still asks when genuinely stuck via the native clarify tool.
  - `AUTOTRAIN_ON_INDEX` — off because it auto-trains *every* table on connector index (can be very costly on a big warehouse). Turn on only deliberately.
- **Hidden/retired (do not use):** SKILLS, SUBAGENTS, RECURSIVE, SKILL_AUTOGROW, SKILL_OPTIMIZE, SKILL_OPTIMIZE_DAEMON — use **Domain Packs** instead.

Some ON features only do something once their backend is configured (no error, just inert until then):
- **File Browser** → needs Microsoft/Google OAuth + a SharePoint/OneDrive/Drive connector.
- **Scheduled Reports / Rich Report Emails** → need SMTP configured.
- **DuckDB Federation** → needs S3/MinIO (`FEDERATION_S3_*`).
- **Daemons** (Insight, Eval, Join-Mining, Studio-Learn, Brain-Graph) → run in the background after the container starts.

To change a flag per-organization: Settings → Feature Flags → toggle → then **`docker restart ca-app`** (the app runs 4 workers; a restart makes all of them + the daemons pick up the change).

## Common operations
```bash
# logs
docker logs -f ca-app

# restart (after toggling flags / config)
docker restart ca-app

# stop / start
docker compose -f docker-compose.build.yaml stop
docker compose -f docker-compose.build.yaml up -d

# rebuild after pulling new code
git pull && bash scripts/build.sh && docker compose -f docker-compose.build.yaml up -d --force-recreate ca-app
```

## Notes / gotchas
- **Never** run `docker compose down -v` — that deletes the Postgres volume (all data).
- The container always listens on port **3000** internally; the host port is `APP_PORT` (default 3007).
- Migrations are idempotent and run on every boot; a fresh DB self-builds to the latest schema.
- Keep `DASH_ENCRYPTION_KEY` stable and backed up — it decrypts every stored credential (incl. the LLM key). Losing it means re-entering all credentials.
