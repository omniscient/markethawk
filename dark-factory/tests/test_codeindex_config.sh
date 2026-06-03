#!/usr/bin/env bash
# Static configuration tests for issue #159 — codeindex dark factory integration.
# Validates that all committed config changes are in place without requiring the
# dark-factory image to be built.
# Run: bash dark-factory/tests/test_codeindex_config.sh
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PASSED=0; FAILED=0

assert_contains() {
  local desc="$1" file="$2" pattern="$3"
  if grep -qF "$pattern" "$file" 2>/dev/null; then
    echo "  PASS: $desc"; PASSED=$((PASSED+1))
  else
    echo "  FAIL: $desc — pattern not found in $file" >&2
    echo "        pattern: $pattern" >&2
    FAILED=$((FAILED+1))
  fi
}

assert_file_exists() {
  local desc="$1" file="$2"
  if [ -f "$file" ]; then
    echo "  PASS: $desc"; PASSED=$((PASSED+1))
  else
    echo "  FAIL: $desc — file does not exist: $file" >&2; FAILED=$((FAILED+1))
  fi
}

assert_executable() {
  local desc="$1" file="$2"
  if [ -x "$file" ]; then
    echo "  PASS: $desc"; PASSED=$((PASSED+1))
  else
    echo "  FAIL: $desc — file is not executable: $file" >&2; FAILED=$((FAILED+1))
  fi
}

echo "=== #159 codeindex config tests ==="
echo ""

echo "--- A: Dockerfile ---"
assert_contains "Dockerfile installs codeindex via git URL" \
  "$REPO_ROOT/dark-factory/Dockerfile" \
  'pip install --quiet "git+https://github.com/scheidydude/codeindex.git"'
assert_contains "Dockerfile installs pre-commit" \
  "$REPO_ROOT/dark-factory/Dockerfile" \
  "pre-commit"

echo ""
echo "--- B: entrypoint.sh ---"
assert_contains "entrypoint.sh writes settings.local.json" \
  "$REPO_ROOT/dark-factory/entrypoint.sh" \
  "settings.local.json"
assert_contains "entrypoint.sh registers MCP server" \
  "$REPO_ROOT/dark-factory/entrypoint.sh" \
  "mcpServers"
assert_contains "entrypoint.sh runs pre-commit install" \
  "$REPO_ROOT/dark-factory/entrypoint.sh" \
  "pre-commit install"

echo ""
echo "--- C: archon-dark-factory.yaml workflow ---"
assert_contains "workflow has update-codeindex node" \
  "$REPO_ROOT/.archon/workflows/archon-dark-factory.yaml" \
  "update-codeindex"
assert_contains "workflow has regen-codeindex node" \
  "$REPO_ROOT/.archon/workflows/archon-dark-factory.yaml" \
  "regen-codeindex"
assert_contains "implement depends on update-codeindex" \
  "$REPO_ROOT/.archon/workflows/archon-dark-factory.yaml" \
  "depends_on: [update-codeindex, fetch-issue]"
assert_contains "preview-up depends on regen-codeindex" \
  "$REPO_ROOT/.archon/workflows/archon-dark-factory.yaml" \
  "depends_on: [regen-codeindex]"
assert_contains "push-and-pr includes blast radius section" \
  "$REPO_ROOT/.archon/workflows/archon-dark-factory.yaml" \
  "Blast radius"

echo ""
echo "--- D: dark-factory-implement.md ---"
assert_contains "implement command has get_impact instruction" \
  "$REPO_ROOT/.archon/commands/dark-factory-implement.md" \
  "get_impact"
assert_contains "implement command has lookup_symbol instruction" \
  "$REPO_ROOT/.archon/commands/dark-factory-implement.md" \
  "lookup_symbol"

echo ""
echo "--- E: .pre-commit-config.yaml ---"
assert_contains "pre-commit has codeindex-blast hook" \
  "$REPO_ROOT/.pre-commit-config.yaml" \
  "codeindex-blast"
assert_contains "codeindex-blast hook always exits 0" \
  "$REPO_ROOT/.pre-commit-config.yaml" \
  "exit 0"

echo ""
echo "--- F: CLAUDE.md ---"
assert_contains "CLAUDE.md has ## Codeindex section" \
  "$REPO_ROOT/CLAUDE.md" \
  "## Codeindex"
assert_contains "CLAUDE.md references lookup_symbol" \
  "$REPO_ROOT/CLAUDE.md" \
  "lookup_symbol"
assert_contains "CLAUDE.md references get_impact" \
  "$REPO_ROOT/CLAUDE.md" \
  "get_impact"
assert_contains "CLAUDE.md references scripts/codeindex.sh" \
  "$REPO_ROOT/CLAUDE.md" \
  "scripts/codeindex.sh"
assert_contains "CLAUDE.md references codeindex-hotspots.md" \
  "$REPO_ROOT/CLAUDE.md" \
  "codeindex-hotspots.md"

echo ""
echo "--- G: scripts/codeindex.sh ---"
assert_file_exists "scripts/codeindex.sh exists" \
  "$REPO_ROOT/scripts/codeindex.sh"
assert_executable "scripts/codeindex.sh is executable" \
  "$REPO_ROOT/scripts/codeindex.sh"
assert_contains "scripts/codeindex.sh uses serve --viz" \
  "$REPO_ROOT/scripts/codeindex.sh" \
  "serve --viz"

echo ""
echo "--- H: docs/codeindex-hotspots.md ---"
assert_file_exists "docs/codeindex-hotspots.md exists" \
  "$REPO_ROOT/docs/codeindex-hotspots.md"

echo ""
echo "--- I: backend/requirements.txt unchanged ---"
if grep -q "codeindex" "$REPO_ROOT/backend/requirements.txt" 2>/dev/null; then
  echo "  FAIL: codeindex must NOT be in backend/requirements.txt" >&2; FAILED=$((FAILED+1))
else
  echo "  PASS: codeindex not in backend/requirements.txt"; PASSED=$((PASSED+1))
fi

echo ""
echo "Results: ${PASSED} passed, ${FAILED} failed"
[ "$FAILED" -eq 0 ]
