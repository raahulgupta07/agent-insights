# Deploy CityAgent Analytics on a new server — **nginx + public HTTPS**

End-to-end guide for a clean Linux server, fronted by **nginx** with a public
`https://your-domain.com` URL (Let's Encrypt certificate, auto-renewing).

Stack file: **`docker-compose.nginx.yaml`** — nginx publishes the port and proxies
to the app over the internal network (`app:3000`); the app is **not** exposed directly.
Containers are named `dash-*`. The app builds its **own** image (`cityagent-analytics:dev`)
from source — no external pull. First build ~10–20 min (frontend needs ~6 GB Node heap).

---

## 0. Server requirements

| | Minimum | Recommended |
|---|---|---|
| OS | Ubuntu 22.04/24.04 | Ubuntu 24.04 |
| vCPU | 4 | 8+ |
| RAM | **10 GB** (build needs it) | 16–32 GB |
| Disk | 40 GB SSD | 100 GB+ |
| Inbound ports | **80 + 443** + 22(ssh) | same |

LLM = OpenRouter (external) → no GPU. Scale guidance: `docs/INFRA_SIZING.md`.

---

## 1. Install Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER          # log out/in
docker version && docker compose version
```

## 2. DNS + firewall

- DNS **A record**: `your-domain.com → <server public IP>`. Verify `dig +short your-domain.com`.
- Open inbound **80 + 443** in the cloud security-group / `ufw allow 80,443/tcp`.

## 3. Get the code (private repo)

```bash
ssh-keygen -t ed25519 -C server-deploy -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub          # add to GitHub repo ▸ Settings ▸ Deploy keys (read-only)
git clone git@github.com:raahulgupta07/agent-insights.git
cd agent-insights && git checkout main
```

## 4. Configure `.env`

```bash
cp .env.example .env
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Edit `.env`:
```ini
ENVIRONMENT=production
DASH_BASE_URL=https://your-domain.com     # public URL (drives links/CORS/embeds)
HTTP_PORT=80                              # nginx publishes 80 (we add 443 below)
POSTGRES_PASSWORD=<strong-db-password>
DASH_ENCRYPTION_KEY=<paste generated key> # set explicitly for prod (secrets need it)
DASH_ADMIN_EMAIL=admin@your-domain.com    # auto-creates owner on first boot (idempotent)
DASH_ADMIN_PASSWORD=<strong-password>
DASH_ADMIN_NAME=Admin
```

---

## 5. Get the TLS certificate (Let's Encrypt, one-off)

nginx is not running yet, so issue the first cert with certbot **standalone** (binds 80):

```bash
mkdir -p certbot/conf certbot/www
docker run --rm -p 80:80 \
  -v "$PWD/certbot/conf:/etc/letsencrypt" \
  certbot/certbot certonly --standalone \
  -d your-domain.com -m admin@your-domain.com --agree-tos -n
# → cert at certbot/conf/live/your-domain.com/{fullchain.pem,privkey.pem}
```

## 6. Enable HTTPS in nginx

**(a)** Replace `nginx/nginx.conf`'s single `server { listen 80; … }` block with the two
blocks below (keep the `worker_processes`/`events`/`http{ … upstream dash_app … }` around
them — only swap the server block). Set `your-domain.com` in both:

```nginx
    # HTTP → redirect to HTTPS (+ serve ACME renewals)
    server {
        listen 80;
        server_name your-domain.com;
        location /.well-known/acme-challenge/ { root /var/www/certbot; }
        location / { return 301 https://$host$request_uri; }
    }

    # HTTPS
    server {
        listen 443 ssl;
        http2 on;
        server_name your-domain.com;

        ssl_certificate     /etc/letsencrypt/live/your-domain.com/fullchain.pem;
        ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;
        ssl_protocols TLSv1.2 TLSv1.3;

        location / {
            proxy_pass http://dash_app;
            proxy_set_header Host              $host;
            proxy_set_header X-Real-IP         $remote_addr;
            proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header Upgrade    $http_upgrade;
            proxy_set_header Connection $connection_upgrade;
            # SSE / streaming — never buffer or chat won't stream token-by-token
            proxy_buffering off; proxy_cache off; proxy_request_buffering off;
            chunked_transfer_encoding on;
        }
    }
```

**(b)** Create `docker-compose.nginx.tls.yaml` (an override that adds port 443 + the cert
mounts to the nginx service — leaves the tracked compose untouched):

```yaml
services:
  nginx:
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./certbot/conf:/etc/letsencrypt:ro
      - ./certbot/www:/var/www/certbot:ro
```

## 7. Deploy

```bash
docker compose -f docker-compose.nginx.yaml -f docker-compose.nginx.tls.yaml up -d --build
```

First run compiles base + frontend (~10–20 min). Watch:
```bash
docker compose -f docker-compose.nginx.yaml logs -f app     # "Application startup complete"
```

Open **https://your-domain.com**.

## 8. First sign-in + LLM key

1. Sign in with `DASH_ADMIN_EMAIL` / `DASH_ADMIN_PASSWORD` (or the one-time
   **Create super-admin** form if you left those blank).
2. **Settings → Models** → paste your **OpenRouter API key** (stored encrypted in the DB).
   Preset models light up; set Agent Defaults (analysis / data-agent + studio training / router).
3. Optional: **Settings → Identity Provider** (Google/MS/Okta/Keycloak/LDAP),
   **Settings → SMTP**, **Settings → Feature Flags**.

---

## 9. Certificate auto-renewal (no downtime — webroot)

Renewals use the ACME location the running nginx already serves. Add a cron:

```bash
sudo crontab -e
# 3:15 AM daily — renew, then reload nginx to pick up the new cert
15 3 * * * cd /home/ubuntu/agent-insights && docker run --rm \
  -v "$PWD/certbot/conf:/etc/letsencrypt" -v "$PWD/certbot/www:/var/www/certbot" \
  certbot/certbot renew --webroot -w /var/www/certbot -q && \
  docker compose -f docker-compose.nginx.yaml exec nginx nginx -s reload
```

## 10. Operate / update / backup

```bash
C="docker compose -f docker-compose.nginx.yaml -f docker-compose.nginx.tls.yaml"
$C ps                    # status
$C logs -f app           # app logs
$C restart app           # restart app only
$C down                  # stop (keeps volumes/data)

# update to a new release (keeps DB/volumes)
git pull && $C up -d --build

# backup
docker exec dash-postgres pg_dump -U dash dash > backup_$(date +%F).sql
docker run --rm -v agent-insights_uploads_data:/u -v "$PWD":/b alpine \
  tar czf /b/uploads_$(date +%F).tgz -C /u .
```

---

## 11. Landmines

- **One stack only.** The nginx stack uses `dash-*` containers + `postgres_data`/`uploads_data`
  volumes. Do NOT also run `docker-compose.build.yaml` (`ca-*` containers, separate volumes) or
  `docker-compose.yaml` (Caddy) on the same box — each is a separate project → separate database.
- **Cert first, then 443.** nginx won't start if `ssl_certificate` points at a file that doesn't
  exist yet — that's why step 5 issues the cert (standalone) BEFORE step 6/7 enable 443.
- **Ports 80 + 443 must be open** in the cloud firewall or the ACME challenge (and the site) fail.
- **Build needs ~10 GB RAM** (nuxt generate = 6 GB heap) — give the box swap or ≥16 GB.
- **PG18 data dir** = `/var/lib/postgresql` (compose already mounts the parent — don't change it).
- **SSE/streaming** requires `proxy_buffering off` (already in the 443 block above) — without it,
  chat answers don't stream token-by-token.
- **Never commit `.env`** (DB password + encryption key). Feature flags are UI-owned, not env.
- **Health:** `curl -fsS https://your-domain.com/health` should return OK.
```
