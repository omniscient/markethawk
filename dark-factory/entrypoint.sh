#!/usr/bin/env bash
set -euo pipefail

# --- Configuration ---
REPO_URL="https://${GH_TOKEN}@github.com/omniscient/markethawk.git"
CLONE_DIR="/workspace/markethawk"
FACTORY_NAME="MarketHawk Factory"
FACTORY_EMAIL="factory@markethawk"

# --- Validate required environment ---
for var in GH_TOKEN ANTHROPIC_API_KEY; do
  if [ -z "${!var:-}" ]; then
    echo "ERROR: $var is not set. Add it to .archon/.env" >&2
    exit 1
  fi
done

# --- Git identity ---
git config --global user.name "$FACTORY_NAME"
git config --global user.email "$FACTORY_EMAIL"

# --- GitHub CLI auth (GH_TOKEN env var is auto-detected by gh) ---
echo "GitHub auth: $(gh auth status 2>&1 | head -2 | tail -1 || echo 'using GH_TOKEN env var')"

# --- Parse arguments ---
ARGUMENTS="${*}"
if [ -z "$ARGUMENTS" ]; then
  echo "Usage: docker compose --profile factory run --rm dark-factory \"Fix issue #3\""
  echo "       docker compose --profile factory run --rm dark-factory \"Continue issue #3\""
  echo "       docker compose --profile factory run --rm dark-factory \"Close issue #3\""
  exit 1
fi

# --- Clone the repo ---
echo "Cloning markethawk..."
if [ -d "$CLONE_DIR" ]; then
  rm -rf "$CLONE_DIR"
fi
git clone "$REPO_URL" "$CLONE_DIR"
cd "$CLONE_DIR"

# --- Copy preview template and seed data into clone ---
mkdir -p "$CLONE_DIR/dark-factory"
cp /opt/dark-factory/docker-compose.preview.yml "$CLONE_DIR/dark-factory/docker-compose.preview.yml"
cp /opt/dark-factory/seed_preview.sql "$CLONE_DIR/dark-factory/seed_preview.sql"

# --- Install backend/frontend deps for local testing ---
echo "Installing backend dependencies..."
cd "$CLONE_DIR/backend" && pip install --quiet -r requirements.txt
echo "Installing frontend dependencies..."
cd "$CLONE_DIR/frontend" && npm install --silent
cd "$CLONE_DIR"

# --- Run via Archon workflow ---
export ARCHON_SUPPRESS_NESTED_CLAUDE_WARNING=1
echo "Starting dark factory: $ARGUMENTS"
archon workflow run archon-dark-factory "$ARGUMENTS"
