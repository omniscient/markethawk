#!/usr/bin/env bash
# Shared gate functions sourced by dark-factory-conformance.md and dark-factory-code-review.md.
# Do not add gate-specific logic here — only the three shared primitives.
# Do NOT add set -euo pipefail: this file is sourced and must not alter caller shell options.

GATE_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=dark-factory/scripts/agent_roles.sh
source "${GATE_LIB_DIR}/agent_roles.sh"

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
  # Usage: write_memory_entry TARGET PATH_PREFIX VIOLATION_TEXT SOURCE ISSUE_NUM [AGENT_ROLE]
  local TARGET="$1" PATH_PREFIX="$2" TEXT="$3" SOURCE="$4" ISSUE="$5"
  local ROLE="${6:-${AGENT_ID:-unknown}}"

  # Dedup: skip if the same TEXT from the same project+agent is already present.
  # Including project/agentId in the key allows different projects or agents to
  # write the same prose without the first writer's scope suppressing later ones.
  if grep -qF "$TEXT" "$TARGET" 2>/dev/null && \
     grep -qF "project:${MEMORY_PROJECT}" "$TARGET" 2>/dev/null && \
     grep -qF "agentId:${ROLE}" "$TARGET" 2>/dev/null; then
    local match
    match=$(grep -F "$TEXT" "$TARGET" 2>/dev/null | grep -F "project:${MEMORY_PROJECT}" | grep -F "agentId:${ROLE}" | head -1)
    if [ -n "$match" ]; then
      echo "memory-write: duplicate entry skipped — already in $TARGET"
      return 0
    fi
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
  # Sanitize values that are inlined into the HTML comment to prevent --> or
  # newline characters from breaking the metadata structure.
  local SAFE_PROJECT SAFE_ROLE
  SAFE_PROJECT=$(printf '%s' "${MEMORY_PROJECT}" | tr -d '\n\r' | sed 's/-->//g')
  SAFE_ROLE=$(printf '%s' "${ROLE}" | tr -d '\n\r' | sed 's/-->//g')
  ENTRY="- [AVOID] $TEXT <!-- project:${SAFE_PROJECT} agentId:${SAFE_ROLE} issue:#$ISSUE date:$(date +%Y-%m-%d) expires:$EXPIRES source:$SOURCE path:$PATH_PREFIX -->"

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
