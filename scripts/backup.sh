#!/usr/bin/env bash
# Timestamped file backup for a non-git working tree.
# Usage:
#   scripts/backup.sh <label> <file-or-dir> [<file-or-dir> ...]
# Copies each path into .backups/<YYYYmmdd_HHMMSS>_<label>/ preserving the
# relative path, and writes a MANIFEST.txt. Restore = copy a file back from the
# snapshot dir to its original relative path (see RESTORE.txt in each snapshot).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

LABEL="${1:-snapshot}"; shift || true
TS="$(date +%Y%m%d_%H%M%S)"
DEST=".backups/${TS}_${LABEL}"
mkdir -p "$DEST"

MANIFEST="$DEST/MANIFEST.txt"
echo "# backup ${TS} label=${LABEL}" > "$MANIFEST"
echo "# root: $ROOT" >> "$MANIFEST"

count=0
for p in "$@"; do
  if [ ! -e "$p" ]; then
    echo "MISSING  $p" >> "$MANIFEST"
    continue
  fi
  mkdir -p "$DEST/$(dirname "$p")"
  cp -a "$p" "$DEST/$p"
  echo "OK       $p" >> "$MANIFEST"
  count=$((count+1))
done

cat > "$DEST/RESTORE.txt" <<EOF
Restore a single file:
  cp -a "$DEST/<relpath>" "<relpath>"
Restore everything in this snapshot:
  (cd "$DEST" && find . -type f ! -name MANIFEST.txt ! -name RESTORE.txt -print0 | \\
     while IFS= read -r -d '' f; do mkdir -p "$ROOT/\$(dirname "\${f#./}")"; cp -a "\$f" "$ROOT/\${f#./}"; done)
EOF

echo "Backed up $count path(s) -> $DEST"
