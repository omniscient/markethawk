#!/usr/bin/env bash
# Guard: fail if weak preview credentials appear outside the allowlisted preview compose file.
# Allowlisted file: dark-factory/docker-compose.preview.yml
# Blocked literals: 'preview_password', 'preview-only-not-secret'
set -euo pipefail

ALLOWLIST="dark-factory/docker-compose.preview.yml"
# PATTERNS lists every weak preview credential literal that must not leak outside ALLOWLIST.
# When new preview credentials are introduced (e.g. new *_password / *_secret / *_key env-var
# fallbacks in docker-compose.preview.yml), add their literal values here so the guard
# catches any accidental copy-paste into other compose files.
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

# Sanity-check: if the allowlist file no longer contains ANY of the known patterns,
# the guard can be trivially defeated by removing them from it. Warn so the bypass
# is visible rather than silently passing.
ALLOWLIST_HIT=0
for pattern in "${PATTERNS[@]}"; do
  if grep -q "$pattern" "$ALLOWLIST" 2>/dev/null; then
    ALLOWLIST_HIT=1
    break
  fi
done
if [ "$ALLOWLIST_HIT" -eq 0 ]; then
  echo "WARNING: None of the blocked credential literals were found in $ALLOWLIST." >&2
  echo "The guard may have been defeated by removing them from the allowlisted file." >&2
  echo "Verify that $ALLOWLIST still contains the expected env-var fallbacks." >&2
fi

if [ "$FAILED" -ne 0 ]; then
  echo "" >&2
  echo "Weak preview credentials must not appear outside $ALLOWLIST." >&2
  echo "Use env var fallbacks (e.g. \${POSTGRES_PASSWORD:-preview_password}) in that file," >&2
  echo "and never copy these literals to other compose files." >&2
  exit 1
fi

echo "check-preview-creds: OK"
