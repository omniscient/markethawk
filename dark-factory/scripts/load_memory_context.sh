#!/usr/bin/env bash
# Load memory context for a given phase.
# Usage: load_memory_context.sh <phase>
# Env:   ARTIFACTS_DIR (required), REPO_ROOT (optional, defaults to git rev-parse),
#        ISSUE_NUM (optional)
# Stdout: memory context text (empty string if memory_retrieve.py fails or has no output)
# Side effects:
#   - writes $ARTIFACTS_DIR/memory-context.md
#   - writes $ARTIFACTS_DIR/memory-trace.json (via memory_retrieve.py --emit-trace-to)
set -euo pipefail

PHASE="${1:?Usage: load_memory_context.sh <phase>}"
REPO_ROOT="${REPO_ROOT:-$(git rev-parse --show-toplevel)}"
ARTIFACTS_DIR="${ARTIFACTS_DIR:?ARTIFACTS_DIR must be set}"

AFFECTED=$(git -C "${REPO_ROOT}" diff --name-only origin/main...HEAD 2>/dev/null || echo "")

ISSUE_ARG=""
[[ "${ISSUE_NUM:-}" =~ ^[0-9]+$ ]] && ISSUE_ARG="--issue ${ISSUE_NUM}"

mkdir -p "$ARTIFACTS_DIR"

MEMORY_CONTEXT=$(python3 "${REPO_ROOT}/dark-factory/scripts/memory_retrieve.py" \
  --phase "$PHASE" \
  --files "$AFFECTED" \
  ${ISSUE_ARG} \
  --memory-dir "${REPO_ROOT}/.archon/memory" \
  --emit-trace-to "${ARTIFACTS_DIR}/memory-trace.json" 2>/dev/null || true)
printf '%s\n' "$MEMORY_CONTEXT" > "${ARTIFACTS_DIR}/memory-context.md"
printf '%s\n' "$MEMORY_CONTEXT"
