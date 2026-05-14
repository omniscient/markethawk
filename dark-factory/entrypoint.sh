#!/usr/bin/env bash
set -euo pipefail

# --- Configuration ---
REPO_URL="https://${GH_TOKEN}@github.com/omniscient/markethawk.git"
CLONE_DIR="/workspace/markethawk"
FACTORY_NAME="MarketHawk Factory"
FACTORY_EMAIL="factory@markethawk"

# --- Validate required environment ---
if [ -z "${GH_TOKEN:-}" ]; then
  echo "ERROR: GH_TOKEN is not set. Add it to .archon/.env" >&2
  exit 1
fi
if [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] && [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "ERROR: Set CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY in .archon/.env" >&2
  exit 1
fi

# --- Git identity ---
git config --global user.name "$FACTORY_NAME"
git config --global user.email "$FACTORY_EMAIL"

# --- GitHub CLI auth (GH_TOKEN env var is auto-detected by gh) ---
echo "GitHub auth: $(gh auth status 2>&1 | head -2 | tail -1 || echo 'using GH_TOKEN env var')"

# --- Project board constants ---
PROJECT_ID="PVT_kwHOAAFds84BWh4w"
STATUS_FIELD="PVTSSF_lAHOAAFds84BWh4wzhR1VaA"
STATUS_IN_PROGRESS="47fc9ee4"
STATUS_BLOCKED="93d87b2f"

# --- Parse arguments ---
ARGUMENTS="${*}"
if [ -z "$ARGUMENTS" ]; then
  echo "Usage: docker compose --profile factory run --rm dark-factory \"Fix issue #3\""
  echo "       docker compose --profile factory run --rm dark-factory \"Continue issue #3\""
  echo "       docker compose --profile factory run --rm dark-factory \"Close issue #3\""
  echo "       docker compose --profile factory run --rm dark-factory \"Refine issue #3\""
  echo "       docker compose --profile factory run --rm dark-factory \"Plan issue #3\""
  exit 1
fi

# --- Extract issue number and intent immediately (no AI needed) ---
ISSUE_NUM=$(echo "$ARGUMENTS" | grep -oP '#\K\d+' | head -1)
INTENT=$(echo "$ARGUMENTS" | grep -oiP '^\s*\K(fix|continue|close|refine|plan)' | head -1 | tr '[:upper:]' '[:lower:]')
INTENT=${INTENT:-fix}

# --- Helper: look up project board item for this issue ---
find_board_item() {
  gh project item-list 1 --owner omniscient --format json --limit 200 \
    | jq -r ".items[] | select(.content.number == $ISSUE_NUM and .content.type == \"Issue\") | .id"
}

# --- Helper: move issue to a board status ---
set_board_status() {
  local OPTION_ID="$1"
  local ITEM_ID
  ITEM_ID=$(find_board_item)
  if [ -n "$ITEM_ID" ]; then
    gh project item-edit --project-id "$PROJECT_ID" --id "$ITEM_ID" \
      --field-id "$STATUS_FIELD" --single-select-option-id "$OPTION_ID"
  fi
}

# --- Move to "In Progress" immediately (skip for close) ---
if [ -n "$ISSUE_NUM" ] && [ "$INTENT" != "close" ] && [ "$INTENT" != "refine" ] && [ "$INTENT" != "plan" ]; then
  echo "Moving issue #$ISSUE_NUM to In Progress..."
  set_board_status "$STATUS_IN_PROGRESS" || echo "WARNING: Could not update project board"
fi

# --- Error handler: move ticket back to Ready and post comment ---
on_failure() {
  local EXIT_CODE=$?
  if [ -n "${ISSUE_NUM:-}" ] && [ "$INTENT" != "close" ]; then
    if [ "$INTENT" = "refine" ] || [ "$INTENT" = "plan" ]; then
      echo "Refinement pipeline failed (exit $EXIT_CODE) for issue #$ISSUE_NUM"
      gh issue comment "$ISSUE_NUM" --body "## Refinement Pipeline — Failed

The refinement pipeline encountered an error (exit code $EXIT_CODE) and could not complete.

\`\`\`bash
# Retry
docker compose --profile factory run --rm dark-factory \"$ARGUMENTS\"
\`\`\`

---
*Posted by MarketHawk Refinement Pipeline*" 2>/dev/null || true
    else
      echo "Dark factory failed (exit $EXIT_CODE). Moving issue #$ISSUE_NUM back to Ready..."
      set_board_status "$STATUS_BLOCKED" 2>/dev/null || true
      gh issue comment "$ISSUE_NUM" --body "## Dark Factory Run — Failed

The dark factory encountered an error (exit code $EXIT_CODE) and could not complete.
Issue has been moved to **Blocked**.

\`\`\`bash
# Retry
docker compose --profile factory run --rm dark-factory \"$ARGUMENTS\"
\`\`\`

---
*Posted by MarketHawk Dark Factory*" 2>/dev/null || true
    fi
  fi
}
trap on_failure ERR

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
export CLAUDE_BIN_PATH=/usr/bin/claude
export IS_SANDBOX=1
export ARCHON_SUPPRESS_NESTED_CLAUDE_WARNING=1
echo "Starting dark factory: $ARGUMENTS"
archon workflow run archon-dark-factory "$ARGUMENTS" --verbose
