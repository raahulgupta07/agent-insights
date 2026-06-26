#!/usr/bin/env bash
# Safe upgrade for the CityAgent Analytics stack.
#
# What it does, in order:
#   1. Reads VERSION_HYBRID and snapshots the CURRENT running image as a rollback tag.
#   2. Logical DB backup (pg_dump) + physical volume tar — both timestamped, to ./backups.
#   3. Builds the new image and tags it cityagent-analytics:<version> AND :dev.
#   4. Recreates ca-app (start.sh runs `alembic upgrade head` automatically).
#   5. Health-gates: waits for healthy + /healthz 200 + verifies VERSION_HYBRID + user count.
#   6. On ANY failure → AUTO-ROLLBACK: retags :dev back to the previous image and recreates.
#
# Data lives in the ca_postgres_data volume and is never dropped by an image swap;
# the backups in step 2 are the safety net for a bad MIGRATION (forward-only).
#
# Usage:  bash scripts/safe-upgrade.sh
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
COMPOSE="docker-compose.build.yaml"          # the ONLY correct compose file for this stack
APP=ca-app
PG=ca-postgres
IMAGE=cityagent-analytics:dev
BK="$ROOT/backups"; mkdir -p "$BK"
TS="$(date +%Y%m%d_%H%M%S)"
VER="$(cat VERSION_HYBRID | tr -d '[:space:]')"

die(){ echo "❌ $*" >&2; exit 1; }

echo "==> [1/6] snapshot current image for rollback"
PREV_ID="$(docker inspect -f '{{.Image}}' "$APP" 2>/dev/null || true)"
[ -z "$PREV_ID" ] && die "ca-app not running — start the stack first (docker compose -f $COMPOSE up -d)"
docker tag "$PREV_ID" "cityagent-analytics:rollback-$TS"
echo "    rollback tag = cityagent-analytics:rollback-$TS  ($PREV_ID)"

echo "==> [2/6] backup DB (logical pg_dump + volume tar)"
docker exec "$PG" pg_dump -U dash -d dash -Fc > "$BK/db_${TS}.dump" || die "pg_dump failed — aborting BEFORE any change"
VOL="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql"}}{{.Name}}{{end}}{{end}}' "$PG")"
[ -n "$VOL" ] && docker run --rm -v "$VOL":/v -v "$BK":/b alpine tar czf "/b/vol_${TS}.tgz" -C /v . 2>/dev/null
# uploads volume = uploaded files + Parquet result files (HYBRID_PARQUET_RESULTS).
# Must be captured WITH the DB so a restore never leaves steps pointing at missing files.
UPV="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/app/backend/uploads"}}{{.Name}}{{end}}{{end}}' "$APP")"
[ -n "$UPV" ] && docker run --rm -v "$UPV":/v -v "$BK":/b alpine tar czf "/b/uploads_${TS}.tgz" -C /v . 2>/dev/null
echo "    saved: $BK/db_${TS}.dump  +  $BK/vol_${TS}.tgz  +  $BK/uploads_${TS}.tgz"

echo "==> [3/6] build new image (v$VER)"
docker compose -f "$COMPOSE" build app || die "build failed (nothing deployed, current stays up)"
# version-stamp the image so we always have an immutable tag to roll back TO later
docker tag "$IMAGE" "cityagent-analytics:$VER"
echo "    tagged cityagent-analytics:$VER"

echo "==> [4/6] recreate ca-app (alembic upgrade head runs on boot)"
docker compose -f "$COMPOSE" up -d --force-recreate app || die "recreate failed"

echo "==> [5/6] health gate"
ok=""
for i in $(seq 1 45); do
  s="$(docker inspect -f '{{.State.Health.Status}}' "$APP" 2>/dev/null || echo none)"
  [ "$s" = "healthy" ] && ok=1 && break
  [ "$s" = "unhealthy" ] && break
  sleep 4
done
code="$(curl -s -o /dev/null -w '%{http_code}' http://localhost:3007/healthz || echo 000)"
got="$(docker exec "$APP" cat /app/VERSION_HYBRID 2>/dev/null | tr -d '[:space:]')"
users="$(docker exec "$PG" psql -U dash -d dash -tAc 'select count(*) from users;' 2>/dev/null | tr -d '[:space:]')"

if [ -n "$ok" ] && [ "$code" = "200" ] && [ "$got" = "$VER" ]; then
  echo "==> [6/6] ✅ upgrade OK — v$got, /healthz $code, users=$users"
  echo "    rollback image kept: cityagent-analytics:rollback-$TS (delete when confident)"
  exit 0
fi

echo "⚠️  health gate FAILED (health=$s, /healthz=$code, ver=$got, users=$users) — ROLLING BACK"
docker tag "cityagent-analytics:rollback-$TS" "$IMAGE"
docker compose -f "$COMPOSE" up -d --force-recreate app
echo "    rolled back to previous image. DB backups: $BK/db_${TS}.dump"
echo "    if a migration changed the schema, restore data with:"
echo "      docker exec -i $PG pg_restore -U dash -d dash --clean --if-exists < $BK/db_${TS}.dump"
exit 1
