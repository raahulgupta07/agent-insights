#!/usr/bin/env bash
# One-command build: pre-pull bases, build cityagent-base:dev once, then the app image.
# Usage: scripts/build.sh [--rebuild-base]
set -euo pipefail
export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# 1. pre-pull base images with retry (avoids registry-EOF mid-build)
for b in ubuntu:24.04 rust:1-slim-bookworm pgvector/pgvector:pg18; do
  until docker image inspect "$b" >/dev/null 2>&1; do
    echo "pulling $b ..."; docker pull "$b" || sleep 3
  done
done

# 2. build the runtime base once (or --rebuild-base to force)
if [ "${1:-}" = "--rebuild-base" ] || ! docker image inspect cityagent-base:dev >/dev/null 2>&1; then
  echo "Building cityagent-base:dev (one-time, ~15-20min) ..."
  docker build -f Dockerfile.base -t cityagent-base:dev .
else
  echo "cityagent-base:dev present — skipping base build (use --rebuild-base to force)."
fi

# 3. build the app image
echo "Building app image via docker-compose.build.yaml ..."
docker compose -f docker-compose.build.yaml build

echo "Done. Start with: docker compose -f docker-compose.build.yaml up -d"
