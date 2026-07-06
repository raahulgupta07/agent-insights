# Infrastructure sizing — 500 users, 50% concurrent

Reference sizing for a production deployment of **CityAgent Analytics** at **500 registered users**
with **50% concurrency** (≈250 users active in the peak window), covering interactive **queries**,
**data uploads**, and **warehouse/BI connectors**.

> **The single most important fact:** the LLM runs on **OpenRouter (external)**, not on your hardware.
> There is **no GPU requirement**. Your infrastructure orchestrates, executes SQL, ingests files, and
> streams tokens back — it does not run the model. Your biggest *variable cost* is OpenRouter tokens
> (OPEX), not servers.

---

## 1. Workload model

A "query" is one agent completion: **plan → tool calls (`create_data` = SQL to a warehouse or DuckDB
over uploaded data) → answer / dashboard**. Typical wall-clock 10–40s; a dashboard/slide build 60–120s.

Each completion is **I/O-bound** — most of its life is spent awaiting OpenRouter and the data source.
So one async worker holds many completions at once. The real limiters are:

- **CPU/RAM bursts** — sandboxed `pandas`/`duckdb` for uploaded-data queries, and artifact rendering
  (bundled **Chromium** for dashboards, **LibreOffice** for PPTX/PDF). These spike 300 MB–1 GB each.
- **DB connections** — many workers × pool size (mitigated by PgBouncer).
- **OpenRouter rate limits** — 100+ concurrent token streams need an adequate OpenRouter tier.

### Concurrency math
| Quantity | Value | Basis |
|---|---|---|
| Registered users | 500 | given |
| Active in peak window (50%) | ~250 | given |
| Queries per active user | ~1 / 45 s | typical analyst cadence |
| Avg completion hold time | ~20 s | plan + tools + stream |
| **Concurrent in-flight completions (peak)** | **~100–130** | 250 × 20/45 |
| Concurrent heavy builds (dashboard/slides) | ~10–20 | fewer, longer |
| Concurrent uploads / connector syncs | ~5–10 | bursty, queued |

---

## 2. Recommended production topology

```
                        ┌─────────────────────────────┐
   users ── HTTPS ──▶    │  Load balancer (ALB / nginx)│  SSE + WebSocket, idle timeout ≥300s
                        └──────────────┬──────────────┘
                       ┌───────────────┼───────────────┐
                 ┌─────▼─────┐   ┌─────▼─────┐   ┌─────▼─────┐
                 │  app x N  │   │  app x N  │   │  app x N  │   cityagent-analytics:dev
                 │ 4 workers │   │ 4 workers │   │ 4 workers │   (uvicorn, Chromium, LibreOffice, ODBC)
                 └─────┬─────┘   └─────┬─────┘   └─────┬─────┘
                       └───────┬───────┴───────┬───────┘
                     ┌─────────▼──────┐  ┌──────▼──────┐   ┌──────────────┐
                     │ PgBouncer      │  │   Redis     │   │ Object store │
                     │   ↓            │  │ (state/cache)│  │ S3 / MinIO   │
                     │ PostgreSQL 18  │  └─────────────┘   │ uploads +    │
                     │ + pgvector     │                    │ parquet      │
                     │ (meta + vector │                    └──────────────┘
                     │  + uploaded    │
                     │  warehouse)    │        OpenRouter (external LLM)  ◀── egress, no GPU
                     └────────────────┘
```

The app image bundles Chromium + LibreOffice + MS ODBC, so **any** app node can render and query — no
separate render tier required. Scale the app tier **horizontally**; `start.sh` caps each container at
**4 uvicorn workers** (`CPUS/2`, max 4), so add containers, not workers.

---

## 3. Component sizing (500 users / ~120 concurrent)

| Component | Recommended | Notes |
|---|---|---|
| **App tier** | **4 containers × 4 vCPU / 16 GB** (16 vCPU, 64 GB total) | 16 uvicorn workers. Autoscale 3–6 on CPU/latency. Cap concurrent artifact renders (~2–3/container) — Chromium/LibreOffice are the RAM sinks. |
| **PostgreSQL 18 + pgvector** | **8 vCPU / 32 GB**, gp3 SSD **500 GB–1 TB @ 6–12k IOPS** | Holds metadata + 1536-d embeddings **+ the uploaded-data warehouse** (staging/analytics schemas). Storage scales with uploaded data. Managed (RDS/Cloud SQL with pgvector) or self-host `pgvector/pgvector:pg18`. Enable PITR + backups. |
| **PgBouncer** | 2 vCPU / 2 GB (or sidecar) | Transaction pooling. Without it, 16 workers × pool 10 = ~160 conns → Postgres pressure. With it, real conns ~50–100. |
| **Redis** | **2 vCPU / 4–8 GB** (ElastiCache cache.t4g.medium/large) | Multi-worker state (confirmation keys, per-org flag context), answer/result caches. Required once workers > 1. |
| **Object storage** | S3 bucket (or MinIO) **200 GB–1 TB+** | Raw uploads (`ca_uploads`), Parquet result offload (`HYBRID_PARQUET_RESULTS`, ≥2000-row steps), federation snapshots. Lifecycle-expire old parquet. |
| **Load balancer** | ALB / nginx | Must pass **SSE + WebSocket (`/ws`)**; idle timeout **≥ 300s** (long completions). **HTTPS required** (PWA install + WS token). Sticky sessions simplest for WS. |
| **LLM** | **OpenRouter** (external) | No GPU, no local model. Ensure the OpenRouter tier/rate-limit supports **100+ concurrent streams**. This is your main OPEX — budget tokens, not servers. |

**Rough total (excl. OpenRouter):** ~**26 vCPU / ~110 GB RAM** + ~1 TB SSD across app + DB + Redis.
On AWS ≈ 4× `c6i.xlarge` (app) + `db.m6g.2xlarge` (Postgres) + `cache.t4g.medium` (Redis) + S3.

---

## 4. Data upload path (sizing)

Ingest = parse (`pandas`/`duckdb`, LibreOffice/qvd converters for xls/qvd) → **load into the Postgres
warehouse** (staging/analytics). CPU- and RAM-heavy per file; a large `.xlsx` spikes memory.

- **Run ingest asynchronously** and **cap global concurrency** (≈4–8 simultaneous ingests). DuckDB is a
  single-writer per file — uncapped parallel ingest causes lock contention + OOM.
- **Scratch disk** on app nodes for staging uploads (ephemeral): size ≈ *largest expected file ×
  concurrent ingests* (e.g. 200 MB × 8 = ~2 GB headroom, more for big workbooks).
- Uploaded data lands in Postgres → **this is the main driver of DB storage growth**. Budget storage by
  (users × avg dataset size); 500 users × ~500 MB ≈ ~250 GB, hence the 500 GB–1 TB DB volume above.

## 5. Connector path (sizing)

Connectors (Power BI, Microsoft Fabric, ~46 warehouse types) **query the customer's external systems** —
the heavy query compute runs **there, not on your infra**. Locally you pay:

- **Network egress** + outbound connection management; per-user OAuth/creds stored **Fernet-encrypted**.
- **Bundled MS ODBC** drivers (in the image) for SQL Server / Fabric.
- **Connector sync (bulk seed)** is memory-heavy locally and rate-limited externally — it is already
  **paced** (`ConnectorSyncRun`); keep concurrent first-time syncs capped (≈2–4) to avoid 429s + spikes.

No extra tier is needed for connectors; they ride the app tier. Ensure the app subnet has **outbound
internet** (Power BI/Fabric REST) and any required VPC peering/PrivateLink to on-prem warehouses.

---

## 6. Scaling levers & guardrails

- **Scale app horizontally** (more containers), not workers-per-container (capped at 4).
- **Turn on `HYBRID_QUOTAS`** to bound per-org token spend and protect OpenRouter rate limits.
- **Result/answer caches** (`ANSWER_CACHE`, `QUERY_CACHE`, `RESULT_CACHE`) cut repeat-query cost — keep on.
- **`HYBRID_PARQUET_RESULTS`** offloads big result sets to object storage → lighter Postgres + DuckDB
  interactive re-query.
- **Cap concurrent artifact renders and ingests** — they are the OOM risks, not the LLM (which is remote).
- **PgBouncer is not optional** at this scale (multi-container × multi-worker connection fan-out).
- **Redis is required** once you run more than one worker (multi-worker confirmation/flag state).

## 7. Smaller footprints (for reference)

| Tier | Users / concurrent | App | Postgres | Redis |
|---|---|---|---|---|
| **Pilot** | ~50 / ~15 | 1 × 4 vCPU / 16 GB | 4 vCPU / 16 GB, 100 GB | 1 GB |
| **Team** | ~150 / ~50 | 2 × 4 vCPU / 16 GB | 4 vCPU / 16 GB, 250 GB | 2 GB |
| **Prod (this doc)** | **500 / ~120** | **4 × 4 vCPU / 16 GB** | **8 vCPU / 32 GB, 500 GB–1 TB** | **4–8 GB** |

> These are **starting points** — measure real query mix (upload-heavy vs connector-heavy vs cached) and
> adjust. Upload-heavy tenants push **Postgres** first; connector-heavy tenants push **egress + app CPU**;
> everyone pushes **OpenRouter tokens**.
