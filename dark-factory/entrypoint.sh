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
OWNER="omniscient"
PROJECT_ID="PVT_kwHOAAFds84BWh4w"
STATUS_FIELD="PVTSSF_lAHOAAFds84BWh4wzhR1VaA"
STATUS_IN_PROGRESS="47fc9ee4"
STATUS_IN_REVIEW="df73e18b"
STATUS_BLOCKED="93d87b2f"

# Conflict resolution
CONFLICT_RESOLUTION_AI_TIER="${CONFLICT_RESOLUTION_AI_TIER:-true}"

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
INTENT=$(echo "$ARGUMENTS" | grep -oiP '^\s*\K(fix|continue|close|refine|plan|deconflict)' | head -1 | tr '[:upper:]' '[:lower:]')
INTENT=${INTENT:-fix}

# --- Concurrency guard: cap factory containers at FACTORY_WIP_LIMIT ---
# RUNNING counts OTHER run containers (self excluded), so at-capacity is
# RUNNING >= limit. Must stay in sync with the scheduler's capacity guard —
# the scheduler dispatches into free slots and this backstop must not veto
# them (#347). The var arrives via the service env_file (.archon/.env).
FACTORY_WIP_LIMIT="${FACTORY_WIP_LIMIT:-1}"
MY_ID=$(cat /proc/self/cgroup 2>/dev/null | grep -oP '[a-f0-9]{64}' | head -1 || hostname)
RUNNING=$(docker ps --format '{{.ID}} {{.Names}}' 2>/dev/null \
  | grep 'markethawk-dark-factory-run-' \
  | grep -vc "${MY_ID:0:12}" || true)
RUNNING=${RUNNING:-0}
if [ "$RUNNING" -ge "$FACTORY_WIP_LIMIT" ]; then
  echo "ERROR: ${RUNNING} other dark factory container(s) already running — at FACTORY_WIP_LIMIT=${FACTORY_WIP_LIMIT}." >&2
  echo "       Use 'docker ps --filter name=dark-factory' to see them." >&2
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
if [ -n "$ISSUE_NUM" ] && [ "$INTENT" != "close" ] && [ "$INTENT" != "refine" ] && [ "$INTENT" != "plan" ] && [ "$INTENT" != "deconflict" ]; then
  echo "Moving issue #$ISSUE_NUM to In Progress..."
  set_board_status "$STATUS_IN_PROGRESS" || echo "WARNING: Could not update project board"
fi

# --- Helper: post or update cost report on issue ---
COST_MARKER="<!-- dark-factory-cost-report -->"
REFINE_FAILURE_MARKER="<!-- df-refine-failure -->"
FACTORY_FAILURE_MARKER="<!-- df-factory-failure -->"
DF_POST_MORTEM_MARKER="<!-- df-post-mortem -->"

post_or_update_comment() {
  local marker="$1"
  local body="$2"
  local COMMENT_ID
  COMMENT_ID=$(gh api "repos/omniscient/markethawk/issues/${ISSUE_NUM}/comments" \
    --jq "[.[] | select(.body | contains(\"$marker\"))] | last | .id // empty" 2>/dev/null || true)
  local TMPFILE
  TMPFILE=$(mktemp /tmp/failure-comment-XXXXXX.md)
  echo "$body" > "$TMPFILE"
  if [ -n "$COMMENT_ID" ]; then
    gh api "repos/omniscient/markethawk/issues/comments/${COMMENT_ID}" \
      --method PATCH -F "body=@${TMPFILE}" >/dev/null 2>&1 || true
  else
    gh issue comment "$ISSUE_NUM" --body-file "$TMPFILE" 2>/dev/null || true
  fi
  rm -f "$TMPFILE"
}

run_post_mortem() {
  local exit_code="${1:-1}"
  local transcript_file="${2:-}"

  # Only run post-mortem for implement/continue failures, not pipeline phases
  case "${INTENT:-fix}" in
    refine|plan|deconflict) return 0 ;;
  esac

  [ -z "${ISSUE_NUM:-}" ] && return 0

  # Gather evidence: transcript tail + artifacts
  local transcript_tail=""
  if [ -n "$transcript_file" ] && [ -f "$transcript_file" ]; then
    transcript_tail=$(tail -200 "$transcript_file" 2>/dev/null || true)
  fi

  local artifacts_context=""
  local ARTIFACTS_DIR="${HOME}/.archon/workspaces/omniscient/markethawk/artifacts/runs"
  # Find the most recent run artifacts directory for this issue
  local run_dir
  run_dir=$(ls -dt "${ARTIFACTS_DIR}"/*/issue.json 2>/dev/null \
    | xargs grep -l "\"resolved_number\": ${ISSUE_NUM}" 2>/dev/null \
    | head -1 | xargs dirname 2>/dev/null || true)

  if [ -n "$run_dir" ]; then
    for f in implementation.md conformance.md review.md plan.md; do
      if [ -f "${run_dir}/${f}" ]; then
        artifacts_context="${artifacts_context}

=== ${f} ===
$(head -100 "${run_dir}/${f}" 2>/dev/null || true)"
      fi
    done
  fi

  local prompt
  prompt="You are analyzing a failed dark factory run for issue #${ISSUE_NUM}.
Exit code: ${exit_code}
Intent: ${INTENT:-fix}

Write a concise post-mortem paragraph (3-5 sentences) explaining:
1. What phase or step likely failed (based on the transcript tail)
2. The probable root cause
3. What the next run should do differently

Keep it factual and actionable. No markdown headers, just a plain paragraph.

=== Transcript tail (last 200 lines) ===
${transcript_tail:-<no transcript available>}
${artifacts_context}"

  local post_mortem_text
  post_mortem_text=$(echo "$prompt" | claude -p --model claude-haiku-4-5-20251001 2>/dev/null || true)

  if [ -z "$post_mortem_text" ]; then
    post_mortem_text="Post-mortem generation failed — no output from haiku agent. Exit code was ${exit_code}. Check the factory logs for details."
  fi

  # Post idempotent marker comment
  local PROMOTED_AT
  PROMOTED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  post_or_update_comment "$DF_POST_MORTEM_MARKER" \
    "${DF_POST_MORTEM_MARKER}
## Dark Factory — Post-Mortem

${post_mortem_text}

**Exit code:** ${exit_code} | **Phase:** ${INTENT:-fix} | **Timestamp:** ${PROMOTED_AT}

---
*Posted by MarketHawk Dark Factory*" || true

  # Append to eval corpus and commit
  local JSONL_PATH="${CLONE_DIR}/dark-factory/evals/factory-failures.jsonl"
  if [ -d "${CLONE_DIR}" ] && [ -f "$JSONL_PATH" ]; then
    local excerpt
    excerpt=$(echo "$post_mortem_text" | head -c 500 | tr '\n' ' ')
    printf '{"issue":%s,"title":"%s","phase":"%s","exit_code":%s,"postmortem":"%s","promoted_at":"%s"}\n' \
      "${ISSUE_NUM}" \
      "$(gh issue view "${ISSUE_NUM}" --repo "omniscient/markethawk" --json title --jq '.title' 2>/dev/null | sed 's/"/\\"/g' || echo "unknown")" \
      "${INTENT:-fix}" \
      "${exit_code}" \
      "$(echo "$excerpt" | sed 's/"/\\"/g')" \
      "$PROMOTED_AT" \
      >> "$JSONL_PATH" 2>/dev/null || true

    (cd "${CLONE_DIR}" && git add dark-factory/evals/factory-failures.jsonl \
      && git commit -m "eval: record factory failure for issue #${ISSUE_NUM}" \
      && git push origin "$(git branch --show-current)" 2>/dev/null) 2>/dev/null || true
  fi
}

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
    # Single-comment endpoint omits the issue number: /issues/comments/{id}, NOT
    # /issues/{n}/comments/{id} (the latter 404s — it silently lost all prior-run
    # history and left the report frozen on its first run).
    EXISTING_BODY=$(gh api "repos/omniscient/markethawk/issues/comments/${COMMENT_ID}" \
      --jq '.body' 2>/dev/null || true)
    PRIOR_RUNS=$(echo "$EXISTING_BODY" | sed -n '/^### Run:/,/^---$/p' | head -n -1 || true)
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
  # grep -c already prints the count (incl. "0"); the old `|| echo "0"` appended a
  # SECOND "0" on no-match (grep exits 1), making RUN_COUNT="0\n0" → arithmetic syntax error.
  RUN_COUNT=$(echo "$PRIOR_RUNS" | grep -c '^### Run:' || true)
  RUN_COUNT=$(( ${RUN_COUNT:-0} + 1 ))

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
    # Same canonical single-comment endpoint (no issue number). Let gh's stderr through
    # on failure — swallowing it with 2>&1 is what hid the 404 path bug for so long.
    if ! gh api "repos/omniscient/markethawk/issues/comments/${COMMENT_ID}" \
        --method PATCH -F "body=@${TMPFILE}" >/dev/null; then
      echo "WARNING: Could not update cost report comment ${COMMENT_ID}"
    fi
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
    if [ "$INTENT" = "refine" ] || [ "$INTENT" = "plan" ] || [ "$INTENT" = "deconflict" ]; then
      # No board status change here — the scheduler's trip_to_blocked() handles the
      # Blocked transition after N attempts. Setting Blocked from on_failure would put
      # the issue in Blocked before the scheduler's counter accumulates; Priority 3
      # would then retry it as "Fix" (implement) — wrong intent for a pipeline phase.
      echo "Refinement pipeline failed (exit $EXIT_CODE) for issue #$ISSUE_NUM"
      post_or_update_comment "$REFINE_FAILURE_MARKER" \
        "${REFINE_FAILURE_MARKER}
## Refinement Pipeline — Failed

The refinement pipeline encountered an error (exit code $EXIT_CODE) and could not complete.

\`\`\`bash
# Retry
docker compose --profile factory run --rm dark-factory \"$ARGUMENTS\"
\`\`\`

---
*Posted by MarketHawk Refinement Pipeline*"
    else
      echo "Dark factory failed (exit $EXIT_CODE). Moving issue #$ISSUE_NUM back to Ready..."
      run_post_mortem "$EXIT_CODE" "" || true
      set_board_status "$STATUS_BLOCKED" 2>/dev/null || true
      post_or_update_comment "$FACTORY_FAILURE_MARKER" \
        "${FACTORY_FAILURE_MARKER}
## Dark Factory Run — Failed

The dark factory encountered an error (exit code $EXIT_CODE) and could not complete.
Issue has been moved to **Blocked**.

\`\`\`bash
# Retry
docker compose --profile factory run --rm dark-factory \"$ARGUMENTS\"
\`\`\`

---
*Posted by MarketHawk Dark Factory*"
    fi
  fi
  # Cost report runs LAST and is non-fatal: a failure here (missing dependency,
  # cost-JSON schema drift) must never abort the trap before the Blocked transition
  # and failure comment above have run.
  post_cost_report || true
}
trap on_failure ERR

# =============================================================================
# --- Conflict resolution helpers (tiered: mechanical → AI → escalate) ---
# =============================================================================

# Tier 1: mechanical, no-AI resolution for one file.
# Returns 0 if the file is in the allowlist and was resolved; 1 otherwise.
_conflict_tier1() {
  local f="$1"
  case "$f" in
    codeindex.json|symbolindex.json|docs/codeindex-hotspots.md)
      git checkout --theirs "$f" 2>/dev/null && git add "$f" || return 1
      ;;
    frontend/package-lock.json)
      cd "$CLONE_DIR/frontend" && npm install --silent 2>/dev/null && cd "$CLONE_DIR" || return 1
      git add frontend/package-lock.json || return 1
      ;;
    backend/app/models/__init__.py)
      python3 - "$f" << '_PYEOF' || return 1
import sys
path = sys.argv[1]
with open(path) as fh:
    content = fh.read()
lines = content.split('\n')
result = []
for line in lines:
    if line.startswith('<<<<<<<') or line.startswith('=======') or line.startswith('>>>>>>>'):
        continue
    result.append(line)
seen = set()
final = []
for line in result:
    stripped = line.strip()
    if stripped and (stripped.startswith('from ') or stripped.startswith('import ')):
        if stripped not in seen:
            seen.add(stripped)
            final.append(line)
    else:
        final.append(line)
with open(path, 'w') as fh:
    fh.write('\n'.join(final))
_PYEOF
      git add "$f" || return 1
      ;;
    backend/alembic/versions/*.py)
      git checkout --theirs "$f" 2>/dev/null && git add "$f" || return 1
      ;;
    *)
      return 1
      ;;
  esac
}

# Tier 2: AI resolution via claude -p for one conflicted file.
# Returns 0 if resolved cleanly; 1 if uncertain or Claude unavailable.
_conflict_tier2() {
  local f="$1"
  [ -f "$f" ] || return 1

  local issue_body git_log conflict_content tmpfile resolved
  issue_body=$(gh issue view "$ISSUE_NUM" --repo "${OWNER}/markethawk" --json body --jq '.body' 2>/dev/null || echo "")
  git_log=$(git log --oneline -15 HEAD 2>/dev/null || echo "")
  conflict_content=$(cat "$f" 2>/dev/null) || return 1

  tmpfile=$(mktemp /tmp/conflict-prompt-XXXXXX.txt)
  printf 'Resolve the git merge conflict markers in this file, preserving both intents (what the feature branch added AND what main added).\n\nReturn the COMPLETE resolved file content between two marker lines, EXACTLY like this and nothing else:\n===BEGIN_RESOLVED_FILE===\n<complete resolved file content>\n===END_RESOLVED_FILE===\n\nNo explanation, commentary, or markdown code fences — inside or outside the markers.\n\nFile: %s\n\nIssue context:\n%s\n\nRecent git log:\n%s\n\nFile content with conflict markers:\n%s\n' \
    "$f" "$issue_body" "$git_log" "$conflict_content" > "$tmpfile"

  local raw
  raw=$(claude -p --model sonnet < "$tmpfile" 2>/dev/null)
  local exit_code=$?
  rm -f "$tmpfile"
  [ "$exit_code" -ne 0 ] && return 1

  # Extract ONLY the content between the sentinel markers. Claude often ignores
  # "output only file content" and prepends prose ("The resolved content is ready,
  # here's what I chose…"); writing that raw output silently corrupts the file and only
  # surfaces later as a CI failure (#207: prose overwrote 01_scanner_configs.sql). If the
  # markers are missing the response was malformed — treat as uncertain and escalate
  # (return 1) rather than writing anything.
  if ! printf '%s' "$raw" | grep -q '^===BEGIN_RESOLVED_FILE===$' \
     || ! printf '%s' "$raw" | grep -q '^===END_RESOLVED_FILE===$'; then
    return 1
  fi
  resolved=$(printf '%s\n' "$raw" | sed -n '/^===BEGIN_RESOLVED_FILE===$/,/^===END_RESOLVED_FILE===$/p' | sed '1d;$d')
  if [ -z "$resolved" ] || printf '%s' "$resolved" | grep -qE '^(<<<<<<<|>>>>>>>)'; then
    return 1
  fi
  printf '%s\n' "$resolved" > "$f"
  git add "$f"
}

# Tier 3: move issue to Blocked and post an explanatory comment.
# Does NOT exit — caller decides whether to exit after this.
_conflict_escalate() {
  local reason="$1"
  echo "[deconflict] Tier 3 escalation: ${reason}"
  set_board_status "$STATUS_BLOCKED" 2>/dev/null || true
  gh issue comment "$ISSUE_NUM" --repo "${OWNER}/markethawk" --body \
"## Dark Factory — Conflict Resolution Escalated

The factory attempted automatic merge conflict resolution but could not complete it.

**Reason:** ${reason}

**To fix manually:**
\`\`\`bash
git checkout feat/issue-${ISSUE_NUM}-*
git fetch origin main
git merge origin/main
# Resolve conflicts manually, then push
\`\`\`

---
*Posted by MarketHawk Dark Factory*" 2>/dev/null || true
}

# Main resolver: merge origin/main into HEAD, apply Tier 1 → Tier 2 → Tier 3.
# Returns 0 on clean merge or successful resolution.
# Returns 1 after escalation (Tier 3); the caller must then exit.
_resolve_merge_conflicts() {
  echo "[deconflict] Fetching origin/main..."
  git fetch origin main 2>&1 || true

  local merge_exit=0
  git merge origin/main --no-edit --no-ff 2>&1 || merge_exit=$?

  if [ "$merge_exit" -eq 0 ]; then
    echo "[deconflict] Clean merge — no conflicts."
    return 0
  fi

  local conflicted
  conflicted=$(git diff --name-only --diff-filter=U 2>/dev/null || true)
  if [ -z "$conflicted" ]; then
    git merge --abort 2>/dev/null || true
    _conflict_escalate "Merge failed with no resolvable conflict markers (possibly a binary file or submodule conflict)."
    return 1
  fi

  echo "[deconflict] Conflicted files: $(echo "$conflicted" | tr '\n' ' ')"

  # --- Tier 1: mechanical resolution ---
  local tier2_needed=""
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    if _conflict_tier1 "$f"; then
      echo "[deconflict] Tier1 resolved: $f"
    else
      tier2_needed="$tier2_needed $f"
    fi
  done <<< "$conflicted"

  # Alembic multi-head merge (run after Tier 1 migration file resolution)
  local heads_count=0
  heads_count=$(cd "$CLONE_DIR/backend" && python -m alembic heads 2>/dev/null | grep -c '^[a-f0-9]' || echo "0")
  if [ "${heads_count:-0}" -gt 1 ]; then
    echo "[deconflict] Multiple alembic heads (${heads_count}) — creating merge migration..."
    (cd "$CLONE_DIR/backend" && python -m alembic merge heads -m "merge_branches_issue_${ISSUE_NUM}" 2>/dev/null) || true
    git add backend/alembic/versions/ 2>/dev/null || true
  fi

  # --- Tier 2: AI resolution ---
  local ai_uncertain=""
  if [ -n "$tier2_needed" ]; then
    if [ "${CONFLICT_RESOLUTION_AI_TIER:-true}" = "true" ]; then
      for f in $tier2_needed; do
        if _conflict_tier2 "$f"; then
          echo "[deconflict] Tier2 resolved: $f"
        else
          ai_uncertain="$ai_uncertain $f"
        fi
      done
    else
      ai_uncertain="$tier2_needed"
      echo "[deconflict] AI tier disabled; escalating: ${tier2_needed}"
    fi
  fi

  # --- Hard grep: surviving conflict markers (safety net) ---
  local survivors
  survivors=$(find . -not -path './.git/*' -type f \
    \( -name '*.py' -o -name '*.ts' -o -name '*.tsx' -o -name '*.js' \
       -o -name '*.json' -o -name '*.yaml' -o -name '*.yml' \
       -o -name '*.md' -o -name '*.sh' -o -name '*.sql' \) \
    -exec grep -l '^<<<<<<' {} \; 2>/dev/null | head -20 || true)

  if [ -n "$ai_uncertain" ] || [ -n "$survivors" ]; then
    local reason=""
    [ -n "$ai_uncertain" ] && reason="AI could not resolve:${ai_uncertain}."
    [ -n "$survivors" ] && reason="${reason} Surviving markers in: $(echo "$survivors" | tr '\n' ' ')."
    git merge --abort 2>/dev/null || true
    _conflict_escalate "${reason}"
    return 1
  fi

  # Commit the resolution
  git commit -m "chore: merge origin/main, resolve conflicts [#${ISSUE_NUM}]" 2>/dev/null || true
  echo "[deconflict] Merge resolution committed."
}

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
# --no-warn-script-location: pip installs as non-root into ~/.local/bin (off
# PATH); harmless because all tools run via `python -m`, so mute the 20+ warnings.
cd "$CLONE_DIR/backend" && pip install --quiet --no-warn-script-location -r requirements.txt
echo "Installing frontend dependencies..."
cd "$CLONE_DIR/frontend" && npm install --silent
cd "$CLONE_DIR"

# --- Write factory-scoped Claude settings (gitignored, never committed) ---
# Uses the absolute codeindex path (required — Claude Code does not inherit shell PATH).
# disableWorkflows: the factory never uses Claude Code's Workflow tool — Archon owns
# orchestration and refine/plan spawn subagents via the Agent tool — so dropping that
# tool's (large) schema from each request trims input tokens at no functional cost.
# Kept here, NOT in the committed .claude/settings.json, so local dev sessions are
# unaffected and keep the Workflow tool.
CODEINDEX_BIN=$(which codeindex 2>/dev/null || true)
mkdir -p "$CLONE_DIR/.claude"
if [ -n "$CODEINDEX_BIN" ]; then
  printf '{\n  "disableWorkflows": true,\n  "mcpServers": {\n    "codeindex": { "command": "%s", "args": ["serve", "--mcp"] }\n  }\n}\n' \
    "$CODEINDEX_BIN" > "$CLONE_DIR/.claude/settings.local.json"
  echo "codeindex MCP registered at $CODEINDEX_BIN; Workflow tool disabled"
else
  printf '{\n  "disableWorkflows": true\n}\n' > "$CLONE_DIR/.claude/settings.local.json"
  echo "WARNING: codeindex not found; MCP server will not be registered (Workflow tool disabled)"
fi

# --- Install pre-commit hooks so codeindex-blast warn hook fires in the run log ---
pre-commit install --allow-missing-config 2>/dev/null || true

# =============================================================================
# --- Deconflict flow: resolve → validate → push → report → exit ---
# 'continue' sync is handled by the archon workflow's de-conflict node.
# =============================================================================
if [ "$INTENT" = "deconflict" ]; then
  git fetch --all 2>/dev/null || true
  FEATURE_BRANCH=$(git branch -r 2>/dev/null | grep -E "origin/feat/issue-${ISSUE_NUM}-" | head -1 | tr -d ' ' | sed 's|origin/||')

  if [ -z "$FEATURE_BRANCH" ]; then
    echo "ERROR: No feature branch found for issue #${ISSUE_NUM}" >&2
    _conflict_escalate "No feature branch matching feat/issue-${ISSUE_NUM}-* was found."
    exit 0
  fi

  # The shared setup above (clone → cp baked seed/preview/settings into the tree) leaves the
  # working tree dirty. `git checkout <feature-branch>` then ABORTS when the branch touches
  # those paths (e.g. a seed-file PR like #207), and the old `|| true` masked the failure: the
  # run silently stayed on main, did a no-op "Already up to date" merge, then failed to push a
  # branch it never checked out (`src refspec ... does not match any`). Reset to a pristine tree
  # first. Scope clean to the copied dirs and never use -x, so gitignored node_modules survives
  # for the tsc validation below.
  git reset --hard HEAD >/dev/null 2>&1 || true
  git clean -fd dark-factory/ .claude/ >/dev/null 2>&1 || true

  if ! git checkout "$FEATURE_BRANCH" 2>&1 \
       && ! git checkout -b "$FEATURE_BRANCH" "origin/$FEATURE_BRANCH" 2>&1; then
    _conflict_escalate "Could not check out branch ${FEATURE_BRANCH} for conflict resolution."
    exit 0
  fi

  # Hard guard: never run the merge/push on the wrong branch — this is the failure mode that
  # turned a routine conflict into a silent no-op-merge + failed-push loop until the breaker
  # tripped the PR to Blocked. If checkout didn't land us on the feature branch, escalate loudly.
  CURRENT_BRANCH=$(git branch --show-current)
  if [ "$CURRENT_BRANCH" != "$FEATURE_BRANCH" ]; then
    _conflict_escalate "Checkout did not land on ${FEATURE_BRANCH} (HEAD on '${CURRENT_BRANCH}')."
    exit 0
  fi

  if ! _resolve_merge_conflicts; then
    # Tier 3 escalation already handled inside _resolve_merge_conflicts
    exit 0
  fi
fi

if [ "$INTENT" = "deconflict" ]; then
  # --- Validate: TypeScript type-check (lightweight; no running DB needed) ---
  DECONFLICT_VALIDATION="PASS"
  echo "[deconflict] Running TypeScript validation..."
  if ! (cd "$CLONE_DIR/frontend" && npx tsc --noEmit 2>&1); then
    DECONFLICT_VALIDATION="FAIL"
    echo "[deconflict] TypeScript validation failed — escalating to Blocked."
    _conflict_escalate "TypeScript type errors after merge. Run 'cd frontend && npx tsc --noEmit' to see them."
    exit 0
  fi

  # --- Push the resolved branch ---
  echo "[deconflict] Pushing resolved branch ${FEATURE_BRANCH}..."
  git push origin "$FEATURE_BRANCH" 2>&1

  # --- Move board back to In Review ---
  set_board_status "$STATUS_IN_REVIEW" 2>/dev/null || true

  # --- Write artifact ---
  DECONFLICT_ARTIFACTS_DIR="${HOME}/.archon/workspaces/omniscient/markethawk/artifacts"
  mkdir -p "$DECONFLICT_ARTIFACTS_DIR"
  cat > "$DECONFLICT_ARTIFACTS_DIR/conflict_resolution.md" << EOF
# Conflict Resolution — Issue #${ISSUE_NUM}

**Status:** RESOLVED
**Branch:** ${FEATURE_BRANCH}
**TypeScript validation:** ${DECONFLICT_VALIDATION}

Merged origin/main into the feature branch using the tiered resolution strategy.
EOF

  # --- Post success comment ---
  gh issue comment "$ISSUE_NUM" --repo "${OWNER}/markethawk" --body \
"## Dark Factory — Merge Conflicts Resolved

\`main\` has been merged into \`${FEATURE_BRANCH}\` and all conflicts were resolved automatically.

The branch has been pushed and is ready for re-review.

---
*Posted by MarketHawk Dark Factory*" 2>/dev/null || true

  echo "[deconflict] Done — issue #${ISSUE_NUM} conflicts resolved and pushed."
  exit 0
fi

# --- Run via Archon workflow ---
export CLAUDE_BIN_PATH=/usr/bin/claude
export IS_SANDBOX=1
export ARCHON_SUPPRESS_NESTED_CLAUDE_WARNING=1
echo "Starting dark factory: $ARGUMENTS"
while true; do
  set +e
  TMP_OUT=$(mktemp)
  archon workflow run archon-dark-factory "$ARGUMENTS" 2>&1 | tee "$TMP_OUT"
  EXIT_CODE=${PIPESTATUS[0]}
  set -e

  if [ "$EXIT_CODE" -ne 0 ]; then
    if grep -qiE "usage limit|rate limit|429|credit balance|session limit" "$TMP_OUT"; then
      # Attempt to parse specific reset time from: "You've hit your session limit · resets 11:10pm (America/Toronto)"
      RESET_TIME=$(grep -ioP "resets\s+\K([0-9]{1,2}:[0-9]{2}[a-z]{2})" "$TMP_OUT" | head -1)
      RESET_TZ=$(grep -ioP "resets\s+[0-9]{1,2}:[0-9]{2}[a-z]{2}\s*\(\K([^)]+)" "$TMP_OUT" | head -1)
      
      SLEEP_SECS=300 # default to 5 mins if parsing fails
      if [ -n "$RESET_TIME" ]; then
        if [ -n "$RESET_TZ" ]; then
          TARGET_EPOCH=$(TZ="$RESET_TZ" date -d "$RESET_TIME" +%s 2>/dev/null || echo "")
        else
          TARGET_EPOCH=$(date -d "$RESET_TIME" +%s 2>/dev/null || echo "")
        fi
        
        if [ -n "$TARGET_EPOCH" ]; then
          NOW_EPOCH=$(date +%s)
          if [ "$TARGET_EPOCH" -lt "$NOW_EPOCH" ]; then
            TARGET_EPOCH=$((TARGET_EPOCH + 86400))
          fi
          SLEEP_SECS=$((TARGET_EPOCH - NOW_EPOCH + 60)) # Add 60s buffer to ensure it actually resets
          
          # Failsafe for absurd values (e.g., more than 24 hours or negative)
          if [ "$SLEEP_SECS" -lt 0 ] || [ "$SLEEP_SECS" -gt 90000 ]; then
            SLEEP_SECS=300
          fi
        fi
      fi

      echo "Claude Max subscription limit reached. Sleeping for ${SLEEP_SECS}s before retrying..."
      rm -f "$TMP_OUT"
      sleep "$SLEEP_SECS"
      echo "Waking up and retrying..."
      continue
    fi
    run_post_mortem "$EXIT_CODE" "$TMP_OUT" || true
    rm -f "$TMP_OUT"
    exit "$EXIT_CODE"
  fi
  rm -f "$TMP_OUT"
  break
done

# --- Post cost report to GitHub issue (success path) — non-fatal ---
post_cost_report || true
