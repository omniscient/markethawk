---
description: AI code review of the implementation diff — blocks the PR on critical/high findings, inline-comments the rest (Gate 3)
argument-hint: (no arguments - reads issue/PR context from the workflow)
---

# Dark Factory — Code Review

**Workflow ID**: $WORKFLOW_ID

---

## Phase 1: LOAD

```bash
REPO_ROOT=$(git rev-parse --show-toplevel)
source "${REPO_ROOT}/dark-factory/scripts/gate_lib.sh"
AGENT_ID="${AGENT_ID_CODE_REVIEW}"
```

1. Read the `code_review` block from `.claude/skills/refinement/config.yaml`.
2. If `code_review.enabled` is `false`:
   - Write `$ARTIFACTS_DIR/review.md` with content: `STATUS: SKIPPED\nREASON: code_review.enabled=false`
   - Exit cleanly (`exit 0`) — `status-in-review` and `report` proceed.
3. Extract `BLOCK_THRESHOLD` from `code_review.block_threshold` (default: `high`).
4. Extract `FAIL_OPEN` from `code_review.fail_open` (default: `true`).
5. Extract `MAX_FINDINGS` from `code_review.max_findings` (default: `50`).
6. Extract `SEVERITY_ORDER_CSV` from `code_review.severity_order` in config.yaml:
   ```bash
   CONFIG_YAML=$(git rev-parse --show-toplevel)/.claude/skills/refinement/config.yaml
   SEVERITY_ORDER_CSV=$(yq '.code_review.severity_order | join(",")' "$CONFIG_YAML" 2>/dev/null || true)
   SEVERITY_ORDER_CSV="${SEVERITY_ORDER_CSV:-low,medium,high,critical}"
   ```
6. Determine `ISSUE_NUM` (from workflow context, or `git branch --show-current | grep -oP 'issue-\K\d+'`).
7. Determine `PR_NUM`:
   ```bash
   BRANCH=$(git branch --show-current)
   PR_NUM=$(gh pr list --repo omniscient/markethawk --head "$BRANCH" --json number --jq '.[0].number // empty')
   ```
   If `PR_NUM` is empty, write `STATUS: ERROR\nREASON: no PR found` to `$ARTIFACTS_DIR/review.md` and exit `0` (fail-open — never block the board on missing PR).

## Phase 2: DIFF

Build the review diff with the SAME pre-triage exclusions the conformance gate uses, and save it:

```bash
RANK_IN=$(mktemp /tmp/rank_in_XXXXXX.txt)
[ -f "$ARTIFACTS_DIR/token-opt-caps.env" ] && . "$ARTIFACTS_DIR/token-opt-caps.env" || true
git diff main...HEAD \
  -- ':!*.lock' ':!*.md' \
  ':!.archon/memory/**' \
  ':!codeindex.json' ':!symbolindex.json' \
  ':!docs/codeindex-hotspots.md' ':!docs/database-schema.md' \
  2>/dev/null > "$RANK_IN"
python3 dark-factory/scripts/diff_rank.py \
  --diff "$RANK_IN" \
  --artifacts-dir "$ARTIFACTS_DIR" \
  --config ".claude/skills/refinement/config.yaml" \
  --hotspots "docs/codeindex-hotspots.md" \
  2>/tmp/diff_rank_err.txt > "$ARTIFACTS_DIR/review_diff.txt" \
  || {
    echo "diff_rank: ranking failed ($(cat /tmp/diff_rank_err.txt)) — using raw diff"
    cp "$RANK_IN" "$ARTIFACTS_DIR/review_diff.txt"
  }
rm -f "$RANK_IN"
```

- The `diff-ranking.json` artifact in `$ARTIFACTS_DIR` records the budget allocation and which files were summarized.
- If `$ARTIFACTS_DIR/review_diff.txt` is empty, write `STATUS: PASS\nBLOCKERS: 0\nADVISORY: 0` to `$ARTIFACTS_DIR/review.md` and exit `0` (nothing to review).

## Phase 3: REVIEW

1. Build `$ISSUE_CONTEXT` = issue title + body:
   ```bash
   gh issue view "$ISSUE_NUM" --repo omniscient/markethawk --json title,body \
     --jq '"Title: \(.title)\n\n\(.body)"'
   ```
2. Read `.claude/skills/refinement/code-review-reviewer-prompt.md`.
3. Spawn a code-reviewer subagent using the Agent tool:
   - `description`: "Code review: diff vs correctness/security"
   - `model`: `claude-opus-4-8` — **always** pin this subagent to Opus 4.8; do not let it inherit the orchestrator's model.
   - `prompt`: the reviewer-prompt content with `$ISSUE_CONTEXT` replaced by the issue context from step 1 and `$DIFF_CONTENT` replaced by the contents of `$ARTIFACTS_DIR/review_diff.txt`.
4. Save the subagent's full output to `$ARTIFACTS_DIR/review_findings.md`.
   - If the subagent errored, timed out, or returned empty/unparseable output:
     - If `FAIL_OPEN=true` → write `STATUS: ERROR\nBLOCKERS: 0\nADVISORY: 0` to `$ARTIFACTS_DIR/review.md`, skip Phases 4–6, exit `0`.
     - If `FAIL_OPEN=false` → treat as a single blocker: skip to Phase 6 BLOCK with a generic "code review could not complete" message.

## Phase 4: BUILD PAYLOAD

Run the deterministic helper to parse findings, anchor them to the diff, apply the threshold, and build the GitHub review payload:

```bash
python3 dark-factory/scripts/code_review_payload.py \
  --review "$ARTIFACTS_DIR/review_findings.md" \
  --diff "$ARTIFACTS_DIR/review_diff.txt" \
  --block-threshold "$BLOCK_THRESHOLD" \
  --severity-order "$SEVERITY_ORDER_CSV" \
  --max-findings "$MAX_FINDINGS" \
  > "$ARTIFACTS_DIR/review_result.json"
```

Read fields from `$ARTIFACTS_DIR/review_result.json`:
- `STATUS = .status` (PASS | BLOCKED)
- `BLOCKERS = (.blockers | length)`
- `ADVISORY = (.advisory | length)`
- The `.payload` object is the body to POST.

If `BLOCKERS == 0` and `ADVISORY == 0` (no findings), write `STATUS: PASS\nBLOCKERS: 0\nADVISORY: 0` to `$ARTIFACTS_DIR/review.md` and exit `0` without posting an empty review.

## Phase 5: POST the review

Post a single GitHub review carrying the inline comments + body:

```bash
jq '.payload' "$ARTIFACTS_DIR/review_result.json" > "$ARTIFACTS_DIR/review_payload.json"
gh api "repos/omniscient/markethawk/pulls/$PR_NUM/reviews" \
  --method POST --input "$ARTIFACTS_DIR/review_payload.json" || \
  echo "code-review: WARNING — posting the PR review failed (continuing to gate decision)"
```

A failed POST is non-fatal — the gate decision below still applies.

## Phase 6: BLOCK or PASS

### If `STATUS` is `PASS` (no blockers)

Write to `$ARTIFACTS_DIR/review.md`:
```bash
{
  emit_verdict "code-review" "PASS" "0" "none"
  printf "BLOCKERS: 0\nADVISORY: %s\nTHRESHOLD: %s\n" \
    "${ADVISORY:-0}" "${BLOCK_THRESHOLD:-high}"
  printf "\n---\n\n"
  cat "$ARTIFACTS_DIR/review_findings.md"
} > "$ARTIFACTS_DIR/review.md"
```
Exit `0`. `status-in-review` and `report` proceed.

### If `STATUS` is `BLOCKED`

1. Post a "Code Review — Blocked" comment on the issue, listing the blocking findings (from `.blockers` in the result JSON):
   ```bash
   gh issue comment "$ISSUE_NUM" --repo omniscient/markethawk --body "## Code Review — Blocked

   The AI code reviewer found ${BLOCKERS} blocking issue(s) (severity ≥ ${BLOCK_THRESHOLD}). See the inline comments on PR #${PR_NUM}.

   $(jq -r '.blockers[] | \"- **[\(.severity)] \(.category)** \(.path):\(.line) — \(.description)\"' \"$ARTIFACTS_DIR/review_result.json\")

   ### Next Steps
   Fix the issues and re-run: \`docker compose --profile factory run --rm dark-factory \\\"Continue issue #${ISSUE_NUM}\\\"\`, or add \`needs-discussion\` if a finding is a false positive.

   ---
   *Posted by MarketHawk Dark Factory*"
   ```
2. Move the issue to **Blocked** on the project board:
   ```bash
   ITEM_ID=$(gh project item-list 1 --owner omniscient --format json --limit 200 \
     | jq -r ".items[] | select(.content.number == $ISSUE_NUM and .content.type == \"Issue\") | .id")
   if [ -n "$ITEM_ID" ]; then
     gh project item-edit \
       --project-id PVT_kwHOAAFds84BWh4w \
       --id "$ITEM_ID" \
       --field-id PVTSSF_lAHOAAFds84BWh4wzhR1VaA \
       --single-select-option-id 93d87b2f
   fi
   ```
3. Add the `needs-discussion` label:
   ```bash
   gh issue edit "$ISSUE_NUM" --repo omniscient/markethawk --add-label needs-discussion
   ```
4. Write to `$ARTIFACTS_DIR/review.md`:
   ```bash
   {
     emit_verdict "code-review" "BLOCKED" "${BLOCKER_COUNT:-0}" "high"
     printf "BLOCKERS: %s\nADVISORY: %s\nTHRESHOLD: %s\n" \
       "${BLOCKER_COUNT:-0}" "${ADVISORY_COUNT:-0}" "${BLOCK_THRESHOLD:-high}"
     printf "\n---\n\n"
     cat "$ARTIFACTS_DIR/review_findings.md"
   } > "$ARTIFACTS_DIR/review.md"
   ```
5. Write blocking findings back to memory so future runs learn from this gate failure:

```bash
# Memory write: only when STATUS=BLOCKED (blocking findings confirmed)
# (route_memory_file and write_memory_entry are sourced from gate_lib.sh at Phase 1 LOAD)

# Extract blocker file paths from review_result.json
BLOCKER_FILES=$(jq -r '.blockers[].path // empty' "$ARTIFACTS_DIR/review_result.json" 2>/dev/null | sort -u)
MEMORY_WRITTEN=0

for BLOCKER_FILE in $BLOCKER_FILES; do
  # head -1 guards against multi-line description output
  FINDING_TEXT=$(jq -r --arg p "$BLOCKER_FILE" \
    '.blockers[] | select(.path == $p) | .description' \
    "$ARTIFACTS_DIR/review_result.json" 2>/dev/null | head -1)

  [ -z "$FINDING_TEXT" ] && continue

  TARGET=$(route_memory_file "$BLOCKER_FILE")
  PATH_PREFIX=$(dirname "$BLOCKER_FILE")/

  write_memory_entry "$TARGET" "$PATH_PREFIX" "$FINDING_TEXT" code-review "${ISSUE_NUM:-unknown}"
  MEMORY_WRITTEN=$((MEMORY_WRITTEN + 1))
  echo "memory-write: wrote [AVOID] to $TARGET"
done

if [ "$MEMORY_WRITTEN" -gt 0 ]; then
  git add .archon/memory/
  git commit -m "memory: code-review lesson from #${ISSUE_NUM:-unknown}"
else
  echo "memory-write: no novel entries — skipping commit"
fi
```

6. Exit non-zero (`exit 1`) — this halts `status-in-review` (the issue stays Blocked instead of moving to In Review).
