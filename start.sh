#!/bin/bash

# Set environment variables
export ENVIRONMENT=production

# Resolve DASH_ENCRYPTION_KEY (must happen BEFORE workers fork).
# Precedence: explicit env/.env  >  key persisted on the uploads volume  >  generate once.
# The persisted file lives on the durable `ca_uploads` volume, so an auto-generated
# key SURVIVES restarts/rebuilds — saved (encrypted) API keys keep decrypting. This
# makes the key fully automatic: no .env edit required for a fresh install.
DASH_SECRET_FILE="${DASH_ENCRYPTION_KEY_FILE:-/app/backend/uploads/.dash_encryption.key}"

# Mask a secret for logs: show a short prefix + length, never the full key.
_mask_key() {
    local k="$1"; local n=${#k}
    if [ "$n" -le 6 ]; then printf '****(%s chars)' "$n";
    else printf '%s…****(%s chars)' "${k:0:6}" "$n"; fi
}

# Phase-5 durability guard: in production (or when explicitly required) we must NOT
# silently mint a fresh key. An auto-generated key lives only on THIS node's uploads
# volume — lose that volume, or add a 2nd node without it, and every Fernet-encrypted
# secret (connector creds / SMTP / LDAP / refresh-tokens) becomes undecryptable.
DASH_REQUIRE_EXPLICIT_KEY=0
if [ "$ENVIRONMENT" = "production" ] || [ "$DASH_REQUIRE_EXPLICIT_ENCRYPTION_KEY" = "1" ]; then
    DASH_REQUIRE_EXPLICIT_KEY=1
fi

DASH_KEY_SOURCE=""
if [ -z "$DASH_ENCRYPTION_KEY" ]; then
    if [ -s "$DASH_SECRET_FILE" ]; then
        # A key already exists on the volume. Keep using it — NEVER rotate (rotating
        # would orphan every secret already encrypted with it). Allowed even in prod.
        export DASH_ENCRYPTION_KEY="$(cat "$DASH_SECRET_FILE")"
        DASH_KEY_SOURCE="volume"
    else
        # No key anywhere. In a require-explicit environment, refuse to boot rather
        # than auto-generate a volume-only key (the exact durability risk of Issue #4).
        if [ "$DASH_REQUIRE_EXPLICIT_KEY" = "1" ]; then
            echo "❌ FATAL: DASH_ENCRYPTION_KEY is not set and no persisted key exists at $DASH_SECRET_FILE." >&2
            echo "   ENVIRONMENT=$ENVIRONMENT (or DASH_REQUIRE_EXPLICIT_ENCRYPTION_KEY=1) requires an EXPLICITLY" >&2
            echo "   provided encryption key so connector creds / SMTP / LDAP / refresh-tokens stay decryptable" >&2
            echo "   across restarts, nodes, and volume loss. Refusing to auto-generate a throwaway volume-only key." >&2
            echo "   Fix — generate a stable key once:" >&2
            echo "     DASH_ENCRYPTION_KEY=\$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')" >&2
            echo "   then set it as a durable env/secret on EVERY node (not just the uploads volume)." >&2
            echo "   (Dev only: run with a non-production ENVIRONMENT to allow auto-generation.)" >&2
            exit 1
        fi
        export DASH_ENCRYPTION_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
        mkdir -p "$(dirname "$DASH_SECRET_FILE")"
        # write atomically + lock down perms
        ( umask 177; printf '%s' "$DASH_ENCRYPTION_KEY" > "$DASH_SECRET_FILE.tmp" ) \
            && mv -f "$DASH_SECRET_FILE.tmp" "$DASH_SECRET_FILE"
        DASH_KEY_SOURCE="generated"
    fi
else
    DASH_KEY_SOURCE="explicit"
    # Explicit key wins. Mirror it to the volume so an accidental later unset still resolves.
    if [ ! -s "$DASH_SECRET_FILE" ]; then
        mkdir -p "$(dirname "$DASH_SECRET_FILE")"
        ( umask 177; printf '%s' "$DASH_ENCRYPTION_KEY" > "$DASH_SECRET_FILE.tmp" ) \
            && mv -f "$DASH_SECRET_FILE.tmp" "$DASH_SECRET_FILE" 2>/dev/null || true
    fi
fi

# Boot log: make key provenance (and any risky volume-only state) visible to ops.
case "$DASH_KEY_SOURCE" in
    explicit)
        echo "🔑 DASH_ENCRYPTION_KEY source=EXPLICIT (env/secret) $(_mask_key "$DASH_ENCRYPTION_KEY") — durable + node-portable ✅" ;;
    volume)
        if [ "$DASH_REQUIRE_EXPLICIT_KEY" = "1" ]; then
            echo "🔑 DASH_ENCRYPTION_KEY source=VOLUME $(_mask_key "$DASH_ENCRYPTION_KEY") from $DASH_SECRET_FILE — kept (no rotation)." >&2
            echo "   ⚠️  This key lives ONLY on the uploads volume. If the volume is lost or a 2nd node lacks it, ALL stored secrets become undecryptable. Promote it to a durable env/secret (set DASH_ENCRYPTION_KEY)." >&2
        else
            echo "🔑 DASH_ENCRYPTION_KEY source=VOLUME $(_mask_key "$DASH_ENCRYPTION_KEY") from $DASH_SECRET_FILE (stable across restarts)." ;
        fi ;;
    generated)
        echo "🔑 DASH_ENCRYPTION_KEY source=AUTO-GENERATED $(_mask_key "$DASH_ENCRYPTION_KEY"), persisted to $DASH_SECRET_FILE (dev fallback; lives only on this volume)." ;;
esac

# =============================================================================
# Detect available CPUs (cgroup-aware for containers)
# Works with: K8s, Docker, Docker Compose (with or without CPU limits)
# =============================================================================
get_container_cpus() {
    local cpus=0
    
    # Method 1: cgroups v2 (modern K8s 1.25+, Docker with cgroupv2)
    # File contains "quota period" e.g., "200000 100000" for 2 CPUs, or "max 100000" for unlimited
    if [ -f /sys/fs/cgroup/cpu.max ] 2>/dev/null; then
        local quota period
        read -r quota period < /sys/fs/cgroup/cpu.max 2>/dev/null
        if [ "$quota" != "max" ] && [ -n "$quota" ] && [ -n "$period" ] && [ "$period" -gt 0 ] 2>/dev/null; then
            cpus=$((quota / period))
            if [ "$cpus" -gt 0 ] 2>/dev/null; then
                echo "cgroups-v2:$cpus"
                return
            fi
        fi
    fi
    
    # Method 2: cgroups v1 (older K8s, older Docker)
    # -1 means unlimited
    local cg_base=""
    for path in /sys/fs/cgroup/cpu /sys/fs/cgroup/cpu,cpuacct; do
        if [ -f "$path/cpu.cfs_quota_us" ] 2>/dev/null; then
            cg_base="$path"
            break
        fi
    done
    
    if [ -n "$cg_base" ]; then
        local quota=$(cat "$cg_base/cpu.cfs_quota_us" 2>/dev/null)
        local period=$(cat "$cg_base/cpu.cfs_period_us" 2>/dev/null)
        if [ -n "$quota" ] && [ "$quota" -gt 0 ] && [ -n "$period" ] && [ "$period" -gt 0 ] 2>/dev/null; then
            cpus=$((quota / period))
            if [ "$cpus" -gt 0 ] 2>/dev/null; then
                echo "cgroups-v1:$cpus"
                return
            fi
        fi
    fi
    
    # Method 3: Fallback to nproc (no container CPU limit set)
    cpus=$(nproc 2>/dev/null || echo 1)
    echo "nproc:$cpus"
}

# Detect CPUs and parse result
CPU_RESULT=$(get_container_cpus)
CPU_SOURCE="${CPU_RESULT%%:*}"
CPUS="${CPU_RESULT##*:}"

# Ensure CPUS is a valid number
if ! [[ "$CPUS" =~ ^[0-9]+$ ]] || [ "$CPUS" -le 0 ]; then
    CPUS=1
    CPU_SOURCE="fallback"
fi

# Calculate workers: half of available CPUs
# - Minimum: 1 worker
# - Maximum: 4 workers (safety cap to prevent OOM)
DEFAULT_WORKERS=$(( CPUS > 1 ? CPUS / 2 : 1 ))
DEFAULT_WORKERS=$(( DEFAULT_WORKERS > 4 ? 4 : DEFAULT_WORKERS ))
DEFAULT_WORKERS=$(( DEFAULT_WORKERS < 1 ? 1 : DEFAULT_WORKERS ))

# Allow override via environment variable
WORKERS=${UVICORN_WORKERS:-$DEFAULT_WORKERS}

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔧 CPU Detection: $CPU_SOURCE"
echo "🖥️  Available CPUs: $CPUS"
echo "🚀 Uvicorn Workers: $WORKERS (max 4, override with UVICORN_WORKERS)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Run database migrations with retries
cd /app/backend
for i in {1..3}; do
    alembic upgrade head && break
    echo "Migration attempt $i failed. Retrying in $((4 * i)) seconds..."
    if [ $i -eq 3 ]; then
        echo "Migration failed after 3 attempts. Exiting."
        exit 1
    fi
    sleep $((4 * i))
done

# Bootstrap the first super-admin from env (idempotent, fail-soft).
# Runs ONCE here, before uvicorn forks its workers (a FastAPI startup_event
# would run per-worker and race N workers). cwd is /app/backend (set above for
# alembic), so scripts/ resolves. The script always exits 0 — never blocks boot.
if [ -n "$DASH_ADMIN_EMAIL" ] && [ -n "$DASH_ADMIN_PASSWORD" ]; then
    echo "Seeding super-admin from env (DASH_ADMIN_EMAIL)..."
    python scripts/seed_admin.py || echo "⚠️  Admin seed skipped/failed (continuing)"
fi

# Start uvicorn as the single foreground process (SPA is served from the
# same process via SERVE_FRONTEND=1). tini reaps it on shutdown.
exec uvicorn main:app \
    --host 0.0.0.0 \
    --port 3000 \
    --ws websockets \
    --log-level info \
    --workers "$WORKERS" \
    --loop uvloop \
    --http httptools
