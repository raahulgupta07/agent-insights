# Scaling CityAgent Analytics on Kubernetes

How to scale the app horizontally, why it is safe to run many replicas, and the
runtime knobs that bound per-pod load.

## 1. Enabling the HorizontalPodAutoscaler (HPA)

The HPA is **off by default** — `replicaCount` (default `1`) fixes the pod count.
Turn it on:

```bash
helm upgrade --install dashapp k8s/chart \
  --set autoscaling.enabled=true \
  --set autoscaling.minReplicas=2 \
  --set autoscaling.maxReplicas=8 \
  --set autoscaling.targetCPUUtilizationPercentage=70
```

Knobs (`values.yaml` → `autoscaling`):

| Key | Default | Meaning |
|-----|---------|---------|
| `enabled` | `false` | Render the HPA; when on, it owns replica count (Deployment `replicas` is omitted). |
| `minReplicas` | `2` | Floor. |
| `maxReplicas` | `8` | Ceiling. |
| `targetCPUUtilizationPercentage` | `70` | Scale to keep avg CPU at this % of the **request**. |
| `targetMemoryUtilizationPercentage` | _(commented out)_ | Optional second metric; uncomment to also scale on memory. |

CPU-utilization scaling needs both a CPU **request** and **limit** on the container.
Both are set under `resources` in `values.yaml` (request `cpu: 2`, limit `cpu: "4"` —
override the limit with `--set resources.limits.cpu="8"`). The metrics-server must be
installed in the cluster for the HPA to read CPU/memory.

## 2. Running many replicas is safe (no double-run of scheduled jobs)

Background daemons (scheduled runs, etc.) are **already multi-replica-safe**, so the
HPA can scale out freely:

- **Per-pod leader file-lock** — `backend/app/core/scheduler.py`
  `try_acquire_scheduler_leader()` takes a file lock (`/tmp/dash-scheduler.lock`) so only
  one worker *within a pod* runs the scheduler loop.
- **Cross-pod claim dedup** — `claim_scheduled_run(job_id, window)` writes to the Postgres
  `scheduled_job_runs` table under a unique constraint, so even if every pod's leader fires
  in the same window, exactly one pod wins the claim and the rest skip. This is what makes
  scaling across pods safe.

Env overrides: `DASH_SCHEDULER_DISABLED`, `DASH_SCHEDULER_LEADER`, `DASH_SCHEDULER_LOCK_PATH`.

## 3. Uvicorn worker model → total concurrency

`start.sh` launches uvicorn with `workers = min(CPUs / 2, 4)` (min 1), overridable with
`UVICORN_WORKERS`. So:

```
total request concurrency = replicas × workers_per_pod
```

e.g. 4 replicas × 4 workers = 16 worker processes serving requests.

## 4. Related per-pod runtime knobs (Phase 9)

These cap load **per pod** (or per worker), so multiply by the replica/worker count to get
the cluster total — size downstream resources accordingly.

| Env | Scope | Notes |
|-----|-------|-------|
| `LLM_MAX_CONCURRENCY` | per pod | Cap on concurrent in-flight LLM calls. The real ceiling under load is usually your OpenRouter rate/cost budget, not the pod. |
| `DB_POOL_SIZE` | per worker per pod | SQLAlchemy connection pool size. |
| `DB_MAX_OVERFLOW` | per worker per pod | Extra connections allowed above the pool. |
| `HYBRID_QUOTAS` | per org | Per-organization usage quota. |

### Database connections — size Postgres `max_connections`

The DB pool is **per worker per pod**, so the worst case is:

```
total DB connections = replicas × workers_per_pod × (DB_POOL_SIZE + DB_MAX_OVERFLOW)
```

Example: 8 replicas (HPA max) × 4 workers × (10 pool + 10 overflow) = **640 connections**.

⚠️ Set Postgres `max_connections` (or your PgBouncer/RDS limit) at or above that worst-case
total, or pods will fail to acquire connections under load. If you cannot raise
`max_connections`, lower `DB_POOL_SIZE` / `DB_MAX_OVERFLOW`, cap `autoscaling.maxReplicas`,
or front Postgres with a connection pooler (PgBouncer in transaction mode).
