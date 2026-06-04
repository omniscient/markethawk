#!/usr/bin/env bash
# Launch codeindex local visualization on http://localhost:8080
# Install first: pip install "git+https://github.com/scheidydude/codeindex.git"
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

if ! command -v codeindex &>/dev/null; then
  echo "ERROR: codeindex not found." >&2
  echo "Install: pip install \"git+https://github.com/scheidydude/codeindex.git\"" >&2
  exit 1
fi

echo "Regenerating dependency index..."
codeindex analyze .
codeindex symbols . --inline

echo ""
echo "Launching visualization on http://localhost:8080 (Ctrl+C to stop)"
codeindex serve --viz
