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

# --- Concurrency guard: only one factory container at a time ---
MY_ID=$(cat /proc/self/cgroup 2>/dev/null | grep -oP '[a-f0-9]{64}' | head -1 || hostname)
RUNNING=$(docker ps --format '{{.ID}} {{.Names}}' 2>/dev/null \
  | grep 'markethawk-dark-factory-run-' \
  | grep -v "${MY_ID:0:12}" \
  | wc -l || echo "0")
if [ "$RUNNING" -gt 0 ]; then
  echo "ERROR: Another dark factory container is already running. Only one allowed at a time (Claude Max rate limit)." >&2
  echo "       Use 'docker ps --filter name=dark-factory' to see it." >&2
  exit 1
fi

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

# --- Helper: post or update cost report on issue ---
COST_MARKER="<!-- dark-factory-cost-report -->"

post_cost_report() {
  if [ -z "${ISSUE_NUM:-}" ]; then return; fi

  # Get this run's cost data as JSON
  # Archon's pino logger writes to stdout; use --quiet to suppress, fall back to jq filtering
  local RAW_OUTPUT RUN_JSON
  RAW_OUTPUT=$(archon workflow cost --last --json --quiet 2>/dev/null || true)
  RUN_JSON=$(echo "$RAW_OUTPUT" | jq -s 'map(select((.run_id // .runId) != null)) | .[0] // empty' 2>/dev/null || true)
  if [ -z "$RUN_JSON" ] || [ "$RUN_JSON" = "null" ]; then return; fi

  echo "Posting cost report to issue #${ISSUE_NUM}..."

  # Find existing cost report comment by marker
  local COMMENT_ID
  COMMENT_ID=$(gh api "repos/omniscient/markethawk/issues/${ISSUE_NUM}/comments" \
    --jq "[.[] | select(.body | contains(\"$COST_MARKER\"))] | last | .id // empty" 2>/dev/null || true)

  # Build the new run's markdown table rows
  local RUN_ROWS TOTAL_COST TOTAL_IN TOTAL_OUT RUN_STATUS TIMESTAMP
  TIMESTAMP=$(date -u +"%Y-%m-%d %H:%M UTC")
  RUN_STATUS=$(echo "$RUN_JSON" | jq -r '.status // "unknown"')
  TOTAL_COST=$(echo "$RUN_JSON" | jq -r '.totals.cost_usd // .totals.costUsd // 0')
  TOTAL_IN=$(echo "$RUN_JSON" | jq -r '.totals.input_tokens // .totals.inputTokens // 0')
  TOTAL_OUT=$(echo "$RUN_JSON" | jq -r '.totals.output_tokens // .totals.outputTokens // 0')

  # jq helper functions for human-readable formatting
  RUN_ROWS=$(echo "$RUN_JSON" | jq -r '
    def fmt_tokens: if . >= 1000000 then "\(. / 1000000 * 10 | round / 10)M"
                    elif . >= 1000 then "\(. / 1000 * 10 | round / 10)K"
                    else "\(.)" end;
    def fmt_dur: if . < 1000 then "\(.)ms"
                 elif . < 60000 then "\(. / 100 | round / 10)s"
                 else "\(. / 60000 | floor)m \((. % 60000 / 1000) | round)s" end;
    def fmt_cost: "$\(. * 10000 | round / 10000)";
    def fmt_model: (((.modelUsage // .model_usage) // {}) | keys[0] // "") |
                   gsub("^claude-"; "") | gsub("-2025.*$"; "");
    (.nodes // [])[] |
    "| \(.nodeId // .node_id) | \(fmt_model) | \((.inputTokens // .input_tokens // 0) | fmt_tokens) | \((.outputTokens // .output_tokens // 0) | fmt_tokens) | \((.costUsd // .cost_usd // 0) | fmt_cost) | \((.durationMs // .duration_ms // 0) | fmt_dur) |"
  ' 2>/dev/null || true)

  if [ -z "$RUN_ROWS" ]; then return; fi

  # If there's an existing comment, extract prior run sections and cumulative totals
  local PRIOR_RUNS="" PREV_COST="0" PREV_IN="0" PREV_OUT="0"
  if [ -n "$COMMENT_ID" ]; then
    local EXISTING_BODY
    EXISTING_BODY=$(gh api "repos/omniscient/markethawk/issues/${ISSUE_NUM}/comments/${COMMENT_ID}" \
      --jq '.body' 2>/dev/null || true)
    PRIOR_RUNS=$(echo "$EXISTING_BODY" | sed -n '/^### Run /,/^---$/p' | head -n -1 || true)
    # Extract previous grand total from hidden data marker
    PREV_COST=$(echo "$EXISTING_BODY" | grep -oP '<!-- cumulative: cost=\K[0-9.]+' || echo "0")
    PREV_IN=$(echo "$EXISTING_BODY" | grep -oP '<!-- cumulative: cost=[0-9.]+ in=\K[0-9]+' || echo "0")
    PREV_OUT=$(echo "$EXISTING_BODY" | grep -oP '<!-- cumulative: cost=[0-9.]+ in=[0-9]+ out=\K[0-9]+' || echo "0")
  fi

  # Calculate cumulative totals
  local CUM_COST CUM_IN CUM_OUT
  CUM_COST=$(echo "$PREV_COST + $TOTAL_COST" | bc)
  CUM_IN=$(( PREV_IN + TOTAL_IN ))
  CUM_OUT=$(( PREV_OUT + TOTAL_OUT ))
  local RUN_COUNT
  RUN_COUNT=$(echo "$PRIOR_RUNS" | grep -c '^### Run ' || echo "0")
  RUN_COUNT=$(( RUN_COUNT + 1 ))

  # Format token counts for display
  fmt_tokens() {
    local n=$1
    if [ "$n" -ge 1000000 ]; then
      echo "$(echo "scale=1; $n / 1000000" | bc)M"
    elif [ "$n" -ge 1000 ]; then
      echo "$(echo "scale=1; $n / 1000" | bc)K"
    else
      echo "$n"
    fi
  }

  # Build the full comment body
  local BODY
  BODY="${COST_MARKER}
<!-- cumulative: cost=${CUM_COST} in=${CUM_IN} out=${CUM_OUT} -->
## Dark Factory — Cost Report

**${RUN_COUNT} run(s) — Total: \$${CUM_COST} ($(fmt_tokens "$CUM_IN") in / $(fmt_tokens "$CUM_OUT") out)**

${PRIOR_RUNS}
### Run: ${TIMESTAMP} (${INTENT:-fix}, ${RUN_STATUS})

| Step | Model | In tokens | Out tokens | Cost | Duration |
|------|-------|-----------|------------|------|----------|
${RUN_ROWS}
| **Subtotal** | | **$(fmt_tokens "$TOTAL_IN")** | **$(fmt_tokens "$TOTAL_OUT")** | **\$${TOTAL_COST}** | |

---
*Updated by MarketHawk Dark Factory*"

  # Create or update the comment
  local TMPFILE
  TMPFILE=$(mktemp /tmp/cost-report-XXXXXX.md)
  echo "$BODY" > "$TMPFILE"

  if [ -n "$COMMENT_ID" ]; then
    gh api "repos/omniscient/markethawk/issues/${ISSUE_NUM}/comments/${COMMENT_ID}" \
      --method PATCH -F "body=@${TMPFILE}" > /dev/null 2>&1 \
      || echo "WARNING: Could not update cost report comment"
  else
    gh issue comment "$ISSUE_NUM" --body-file "$TMPFILE" 2>/dev/null \
      || echo "WARNING: Could not post cost report"
  fi
  rm -f "$TMPFILE"
}

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
  # Cost report runs LAST and is non-fatal: a failure here (missing dependency,
  # cost-JSON schema drift) must never abort the trap before the Blocked transition
  # and failure comment above have run.
  post_cost_report || true
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
cp -r /opt/dark-factory/seed/ "$CLONE_DIR/dark-factory/seed/"

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
archon workflow run archon-dark-factory "$ARGUMENTS"

# --- Post cost report to GitHub issue (success path) — non-fatal ---
post_cost_report || true
