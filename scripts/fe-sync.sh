#!/usr/bin/env bash
# FE-sync: build the static Nuxt bundle on the host and push it into the running
# ca-app container WITHOUT a full Docker rebuild. Skips base/pip/yarn-install
# layers + image commit — only cost is `nuxt generate`.
#
# Ephemeral: a `docker compose ... --force-recreate` reverts to the baked image.
# For a durable image, bake (`docker compose -f docker-compose.build.yaml up -d --build`).
#
# Usage:  bash scripts/fe-sync.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FE="$ROOT/frontend"
CONTAINER="${CA_CONTAINER:-ca-app}"

echo "==> freeing :3000 (generate corrupts .nuxt if dev is live)"
pkill -f 'nuxt dev' 2>/dev/null || true

echo "==> cleaning stale build caches"
cd "$FE"
rm -rf .nuxt .output node_modules/.cache node_modules/.vite

echo "==> nuxt generate (static bundle; heavy, ~2-5 min)"
npm run generate

echo "==> pushing bundle into $CONTAINER:/app/frontend/dist (dist owned by root)"
docker exec -u 0 "$CONTAINER" sh -c 'rm -rf /app/frontend/dist/*'
docker cp "$FE/.output/public/." "$CONTAINER:/app/frontend/dist/"
docker exec -u 0 "$CONTAINER" chown -R app:app /app/frontend/dist

echo "==> done. FE live on the container's port (no restart needed)."
