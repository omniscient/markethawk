#!/usr/bin/env bash
# Guard: fail if weak preview credentials appear outside the allowlisted preview compose file.
# Allowlisted file: dark-factory/docker-compose.preview.yml
# Blocked literals: 'preview_password', 'preview-only-not-secret'
set -euo pipefail

ALLOWLIST="dark-factory/docker-compose.preview.yml"
PATTERNS=("preview_password" "preview-only-not-secret")
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)

cd "$REPO_ROOT"

FAILED=0
for pattern in "${PATTERNS[@]}"; do
  # Search all docker-compose*.yml files for the literal string
  while IFS= read -r match_file; do
    # Normalise path: strip leading ./
    norm="${match_file#./}"
    if [ "$norm" != "$ALLOWLIST" ]; then
      echo "ERROR: Forbidden credential literal '$pattern' found in $norm (only allowed in $ALLOWLIST)" >&2
      FAILED=1
    fi
  done < <(grep -rl "$pattern" . --include="docker-compose*.yml" 2>/dev/null || true)
done

if [ "$FAILED" -ne 0 ]; then
  echo "" >&2
  echo "Weak preview credentials must not appear outside $ALLOWLIST." >&2
  echo "Use env var fallbacks (e.g. \${POSTGRES_PASSWORD:-preview_password}) in that file," >&2
  echo "and never copy these literals to other compose files." >&2
  exit 1
fi

echo "check-preview-creds: OK"
