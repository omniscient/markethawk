#!/usr/bin/env bash
# Launch repowise local dashboard
# Install first: python3 -m venv ~/.venvs/repowise && ~/.venvs/repowise/bin/pip install repowise
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# Allow override via env (useful if venv lives elsewhere)
REPOWISE_VENV="${REPOWISE_VENV:-$HOME/.venvs/repowise}"
REPOWISE="${REPOWISE_VENV}/bin/repowise"

if [ ! -f "$REPOWISE" ]; then
  echo "ERROR: repowise not found at $REPOWISE" >&2
  echo "Install:" >&2
  echo "  python3 -m venv ~/.venvs/repowise" >&2
  echo "  ~/.venvs/repowise/bin/pip install repowise" >&2
  echo "Or set REPOWISE_VENV to the path of an existing venv that has repowise." >&2
  exit 1
fi

echo "Regenerating repowise index (index-only, no LLM)..."
"$REPOWISE" init --index-only .

echo ""
echo "Launching repowise dashboard (Ctrl+C to stop)"
"$REPOWISE" serve
