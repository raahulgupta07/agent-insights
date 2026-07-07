#!/usr/bin/env bash
# =============================================================================
# aws_phase0.sh — Phase 0 diagnose + (guarded) apply for CityAgent Analytics
# on the AWS box (host insights.citygpt.xyz, docker-compose.npm.yaml).
#
# Goal: stop the OOM/unhealthy restart loop and fix the upload/training failure.
# Config only — no code deploy, no image rebuild. Full context: docs/AWS_PHASE0_RUNBOOK.md
#
# Usage:
#   ./scripts/aws_phase0.sh            # READ-ONLY: diagnose + PRINT recommended next steps
#   APP=dash-app ./scripts/aws_phase0.sh
#   ./scripts/aws_phase0.sh --apply    # ALSO: append generated secret to .env + recreate app
#
# Safe to run read-only first. --apply only touches .env (the autotrain secret) and
# recreates the app container. Flag toggles + NPM changes are printed, never auto-run.
# =============================================================================
set -euo pipefail

APP=${APP:-dash-app}                       # container name (docker logs/inspect/exec)
SERVICE=${SERVICE:-app}                     # compose service name (docker compose ...)
COMPOSE_FILE=${COMPOSE_FILE:-docker-compose.npm.yaml}
ENV_FILE=${ENV_FILE:-.env}
SECRET_KEY="AUTOTRAIN_STAGING_ROLE_SECRET"

APPLY=0
[[ "${1:-}" == "--apply" ]] && APPLY=1

hr() { printf '%s\n' "----------------------------------------------------------------------"; }

# ----------------------------------------------------------------------------
# 1. DIAGNOSIS (read-only)
# ----------------------------------------------------------------------------
hr; echo "== Phase 0 diagnosis for container: ${APP} =="; hr

echo "[containers]"
docker ps -a || true
echo

echo "[OOM / restart state]"
docker inspect "${APP}" --format \
  'OOMKilled={{.State.OOMKilled}} Status={{.State.Status}} Restarts={{.RestartCount}}' \
  2>/dev/null || echo "  (container ${APP} not found)"
echo

echo "[host memory / cpu]"
free -h || true
echo "nproc=$(nproc 2>/dev/null || echo '?')"
echo

echo "[app logs — last 20m, filtered]"
docker logs "${APP}" --since 20m 2>&1 \
  | grep -iE "memoryerror|sigkill|killed|${SECRET_KEY}|worker" \
  || echo "  (no matching lines — no obvious OOM/secret error in the last 20m)"
echo

echo "[${SECRET_KEY} in container env]"
SECRET_STATE="$(docker exec "${APP}" printenv "${SECRET_KEY}" 2>/dev/null || echo MISSING)"
if [[ -z "${SECRET_STATE}" || "${SECRET_STATE}" == "MISSING" ]]; then
  echo "  ${SECRET_KEY}=MISSING  -> upload/training WILL fail (RuntimeError in tenant_schema._secret)"
  SECRET_MISSING=1
else
  echo "  ${SECRET_KEY} is SET (len=${#SECRET_STATE})"
  SECRET_MISSING=0
fi
echo

# ----------------------------------------------------------------------------
# 2. RECOMMENDED NEXT STEPS (printed — review before applying)
# ----------------------------------------------------------------------------
hr; echo "== Recommended Phase 0 actions (review, then apply) =="; hr
cat <<EOF
Fix 1 — ${SECRET_KEY} (fixes upload/training):
  Generate a STABLE dedicated secret (>=16 chars) and add it to ${ENV_FILE}:
      openssl rand -hex 24
      echo "${SECRET_KEY}=<value>" >> ${ENV_FILE}
  WARNING: set once, never rotate — role passwords are HMAC-derived from it.

Fix 2 — memory cap (verify only; owned by the compose file / another agent):
  Confirm the '${SERVICE}' service has:  mem_limit: <~70% of box RAM>
  (see 'free -h' above; 16GB box -> 12g, 8GB -> 6g, 32GB -> 22g)

Fix 3 — enable the sandbox flags for the org (pick ONE method):
  A) UI: Settings -> Features -> Performance -> ON:
       Subprocess sandbox (isolated code exec)  = HYBRID_SUBPROCESS_SANDBOX
       SQL pushdown (memory discipline)          = HYBRID_SANDBOX_PUSHDOWN
     HOLD: Subprocess sandbox — live DB clients  = HYBRID_SUBPROCESS_SANDBOX_LIVE  (leave OFF until Phase 1)
  B) SQL (config is json NOT jsonb -> cast ::jsonb ... ::json):
       docker exec -it dash-postgres psql -U dash -d dash
       SELECT id,name FROM organizations;
       UPDATE organization_settings
         SET config = jsonb_set(config::jsonb,'{hybrid_overrides,HYBRID_SUBPROCESS_SANDBOX}','true')::json
         WHERE organization_id='<org-id>';
       UPDATE organization_settings
         SET config = jsonb_set(config::jsonb,'{hybrid_overrides,HYBRID_SANDBOX_PUSHDOWN}','true')::json
         WHERE organization_id='<org-id>';

Recreate to apply (env + DB flags both load on boot):
      docker compose -f ${COMPOSE_FILE} up -d --force-recreate ${SERVICE}
  (--force-recreate reverts hot-cp'd files to the image; fine — image v1.155, Phase 0 = config only)

Verify:
      docker exec ${APP} curl -fsS http://localhost:3000/health && echo OK
      docker inspect ${APP} --format 'OOMKilled={{.State.OOMKilled}} Restarts={{.RestartCount}}'
      docker exec dash-postgres psql -U dash -d dash -c "\\dt staging_*.*"

If NO OOM but requests >30s die with "Load failed" in the browser -> NPM proxy timeout, not memory.
  NPM UI (:81) -> Proxy Host insights.citygpt.xyz -> Advanced: proxy_buffering off; proxy_read_timeout 3600s; client_max_body_size 0;  (see runbook)
EOF
echo

# ----------------------------------------------------------------------------
# 3. APPLY (guarded — only with --apply)
# ----------------------------------------------------------------------------
if [[ "${APPLY}" -eq 0 ]]; then
  hr
  echo "Dry-run complete (read-only). Re-run with --apply to append the ${SECRET_KEY} to"
  echo "${ENV_FILE} and recreate '${SERVICE}'. Flag toggles + NPM changes are never auto-applied."
  hr
  exit 0
fi

hr; echo "== --apply: appending ${SECRET_KEY} to ${ENV_FILE} + recreating ${SERVICE} =="; hr

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "ERROR: ${ENV_FILE} not found in $(pwd). Run from the compose dir or set ENV_FILE=." >&2
  exit 1
fi

if grep -qE "^${SECRET_KEY}=.+" "${ENV_FILE}"; then
  echo "  ${SECRET_KEY} already has a value in ${ENV_FILE} — leaving it UNCHANGED (never rotate)."
else
  NEW_SECRET="$(openssl rand -hex 24)"
  # Replace an empty 'KEY=' line if present, else append.
  if grep -qE "^${SECRET_KEY}=$" "${ENV_FILE}"; then
    tmp="$(mktemp)"
    grep -vE "^${SECRET_KEY}=$" "${ENV_FILE}" > "${tmp}"
    mv "${tmp}" "${ENV_FILE}"
  fi
  printf '%s=%s\n' "${SECRET_KEY}" "${NEW_SECRET}" >> "${ENV_FILE}"
  echo "  Appended ${SECRET_KEY} (len=${#NEW_SECRET}) to ${ENV_FILE}. KEEP THIS STABLE."
fi
echo

echo "  Recreating ${SERVICE}..."
docker compose -f "${COMPOSE_FILE}" up -d --force-recreate "${SERVICE}"
echo

echo "  Post-recreate health:"
sleep 5
docker exec "${APP}" curl -fsS http://localhost:3000/health && echo " OK" || echo " (health not ready yet — check 'docker logs ${APP}')"
echo
echo "NOTE: --apply set the secret + recreated. It did NOT toggle the hybrid flags"
echo "(do Fix 3 via UI or SQL) and did NOT change NPM. See docs/AWS_PHASE0_RUNBOOK.md."
