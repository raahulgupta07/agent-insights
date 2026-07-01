#!/usr/bin/env bash
# Upstream release triage — group what a bagofwords release changed, for porting.
# Usage: scripts/upstream_triage.sh <fromTag> <toTag>   e.g. v0.0.427 v0.0.428
# Ancestry-free (works even though our fork shares no history with upstream).
set -euo pipefail

FROM="${1:?from tag, e.g. v0.0.427}"
TO="${2:?to tag, e.g. v0.0.428}"

git fetch upstream --tags -q 2>/dev/null || true

echo "==================================================================="
echo " Upstream triage: $FROM -> $TO"
echo "==================================================================="
git diff --shortstat "$FROM" "$TO"
echo

echo "### NEW FILES (pure adds — easiest to port, low conflict) ###"
git diff --stat --diff-filter=A "$FROM" "$TO" | grep -vE "locales/|sandbox-feedback|_icons/|\.png|\.svg|\.json " || echo "  (none of interest)"
echo

echo "### BACKEND changes (services / routes / models / ai) ###"
git diff --stat "$FROM" "$TO" -- backend/app/services backend/app/routes backend/app/models backend/app/ai | tail -40
echo

echo "### MIGRATIONS (must re-author idempotent in our chain) ###"
git diff --stat --diff-filter=A "$FROM" "$TO" -- backend/alembic backend/migrations 2>/dev/null || echo "  (none)"
echo

echo "### FRONTEND components/pages (skip locales) ###"
git diff --stat "$FROM" "$TO" -- frontend/components frontend/pages frontend/composables | tail -40
echo

echo "Next: git diff $FROM $TO -- <path>   to read a feature; port behind a HYBRID_* flag."
