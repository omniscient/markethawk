#!/usr/bin/env bash
# Shared gate functions sourced by dark-factory-conformance.md and dark-factory-code-review.md.
# Do not add gate-specific logic here — only the three shared primitives.
# Do NOT add set -euo pipefail: this file is sourced and must not alter caller shell options.

route_memory_file() {
  local FILE="$1"
  case "$FILE" in
    backend/app/*)            echo ".archon/memory/backend-patterns.md" ;;
    frontend/src/*)           echo ".archon/memory/frontend-patterns.md" ;;
    .archon/*|dark-factory/*) echo ".archon/memory/dark-factory-ops.md" ;;
    ARCHITECTURE.md)          echo ".archon/memory/architecture.md" ;;
    *)                        echo ".archon/memory/codebase-patterns.md" ;;
  esac
}

write_memory_entry() {
  # Usage: write_memory_entry TARGET PATH_PREFIX VIOLATION_TEXT SOURCE ISSUE_NUM
  local TARGET="$1" PATH_PREFIX="$2" TEXT="$3" SOURCE="$4" ISSUE="$5"

  # Dedup: skip if core sentence already present
  if grep -qF "$TEXT" "$TARGET" 2>/dev/null; then
    echo "memory-write: duplicate entry skipped — already in $TARGET"
    return 0
  fi

  # Expiry cleanup (mawk-compatible two-argument match form)
  TODAY=$(date +%Y-%m-%d)
  awk -v today="$TODAY" '
    /expires:[0-9]{4}-[0-9]{2}-[0-9]{2}/ {
      found=match($0, /expires:[0-9]{4}-[0-9]{2}-[0-9]{2}/)
      if (found) { expiry_date=substr($0, RSTART+8, 10); if (expiry_date < today) next }
    }
    { print }
  ' "$TARGET" > "$TARGET.tmp" && mv "$TARGET.tmp" "$TARGET"

  # Cap check (30 authoritative entries per file)
  COUNT=$(grep -c '^\- \[PATTERN\]\|^\- \[AVOID\]\|^\- \[FIX\]' "$TARGET" 2>/dev/null || echo 0)
  if [ "$COUNT" -ge 30 ]; then
    echo "memory-write: cap reached ($COUNT entries) in $TARGET — skipping write"
    return 0
  fi

  EXPIRES=$(date -d '+6 months' +%Y-%m-%d 2>/dev/null || date -v+6m +%Y-%m-%d)
  ENTRY="- [AVOID] $TEXT <!-- issue:#$ISSUE date:$(date +%Y-%m-%d) expires:$EXPIRES source:$SOURCE path:$PATH_PREFIX -->"

  # Insert before the PROVISIONAL section delimiter (or append if no delimiter)
  if grep -q '^---$' "$TARGET" 2>/dev/null; then
    sed -i "/^---$/i $ENTRY" "$TARGET"
  else
    echo "$ENTRY" >> "$TARGET"
  fi
}

emit_verdict() {
  # Usage: emit_verdict GATE_TYPE STATUS FINDINGS_COUNT SEVERITY
  local GATE="$1" STATUS="$2" COUNT="$3" SEV="$4"
  printf "STATUS: %s\nGATE_TYPE: %s\nFINDINGS_COUNT: %s\nSEVERITY: %s\n" \
    "$STATUS" "$GATE" "$COUNT" "$SEV"
}
