---
description: Auto-address advisory code-review findings — spawns a fix agent, commits, and pushes. Fail-open; never blocks "In Review".
argument-hint: (no arguments - reads review artifacts written by dark-factory-code-review)
---

# Dark Factory — Revise Advisory

**Workflow ID**: $WORKFLOW_ID

---

## Phase 1: LOAD

```bash
REPO_ROOT=$(git rev-parse --show-toplevel)
source "${REPO_ROOT}/dark-factory/scripts/gate_lib.sh"
```

1. Check whether `$ARTIFACTS_DIR/review_result.json` exists. If missing → exit 0 (code-review was
   skipped or errored fail-open; nothing to revise).
2. Read `ADVISORY_COUNT`:
   ```bash
   ADVISORY_COUNT=$(jq '.advisory | length' "$ARTIFACTS_DIR/review_result.json" 2>/dev/null || echo 0)
   ```
3. If `ADVISORY_COUNT == 0` → exit 0 (no advisory findings; fast no-op).
4. Read `STATUS`:
   ```bash
   STATUS=$(jq -r '.status' "$ARTIFACTS_DIR/review_result.json" 2>/dev/null || echo "PASS")
   ```
5. If `STATUS != "PASS"` → exit 0 (blocked run; code-review already halted the pipeline).
6. Determine `ISSUE_NUM` and `PR_NUM`:
   ```bash
   ISSUE_NUM=$(jq -r '.resolved_number' "$ARTIFACTS_DIR/issue.json" 2>/dev/null || \
     git branch --show-current | grep -oP 'issue-\K\d+')
   BRANCH=$(git branch --show-current)
   PR_NUM=$(gh pr list --repo omniscient/markethawk --head "$BRANCH" --json number --jq '.[0].number // empty')
   ```
   If `PR_NUM` is empty → log a warning and exit 0 (fail-open; can't push comments without a PR).

## Phase 2: BUILD CONTEXT

1. Build a human-readable findings list from `.advisory[]` in `review_result.json`:
   ```bash
   FINDINGS_TEXT=$(jq -r '
     .advisory[] |
     "### [\(.severity | ascii_upcase)] \(.category) — \(.path)\(if .line then ":\(.line)" else "" end)\n\(.description)\n"
   ' "$ARTIFACTS_DIR/review_result.json")
   ```
2. Read the diff (already written by code-review):
   ```bash
   DIFF_CONTENT=$(cat "$ARTIFACTS_DIR/review_diff.txt" 2>/dev/null || echo "(diff unavailable)")
   ```
3. Announce on the issue:
   ```bash
   gh issue comment "$ISSUE_NUM" --repo omniscient/markethawk \
     --body "Addressing ${ADVISORY_COUNT} advisory finding(s) from code review..."
   ```

## Phase 3: SPAWN FIX AGENT

Spawn a subagent using the Agent tool:

- `description`: "Revise advisory findings: ${ADVISORY_COUNT} item(s)"
- `model`: inherit (do not override — Sonnet is appropriate for targeted edits)
- `prompt`:

```
You are a software engineer addressing advisory findings from a code review.
Your task: fix each finding below by editing the relevant source files.

## Advisory Findings

{FINDINGS_TEXT}

## Diff context (what was changed in this PR)

```diff
{DIFF_CONTENT}
```

## Instructions

For each finding:
1. Read the file at the given path.
2. Apply the fix the finding describes. Stay minimal — fix exactly what is flagged, no refactors.
3. Write the updated file.

When done, output a brief summary of what you changed (one line per finding).
Do NOT commit or push — the workflow handles that.
Do NOT modify test files unless the finding explicitly targets a test file.
```

Replace `{FINDINGS_TEXT}` with `$FINDINGS_TEXT` and `{DIFF_CONTENT}` with `$DIFF_CONTENT`.

Save the agent's summary output to `$ARTIFACTS_DIR/revise_summary.txt`.

If the agent errors or returns empty output → log a warning and proceed to Phase 4 (the diff
check will detect no changes and exit 0 cleanly).

## Phase 4: COMMIT AND PUSH

1. Check for actual changes:
   ```bash
   if git diff --quiet && git diff --staged --quiet; then
     echo "revise-advisory: agent produced no file changes — skipping commit"
     exit 0
   fi
   ```
2. Stage all modified tracked files (no untracked):
   ```bash
   git add -u
   ```
3. Commit:
   ```bash
   git commit -m "fix(review): address ${ADVISORY_COUNT} advisory finding(s) from AI code review"
   ```
4. Push:
   ```bash
   git push origin HEAD
   ```
   If push fails → log error and exit 0 (fail-open; PR already exists, findings still visible).

## Phase 5: REPORT

Post a follow-up comment on the PR listing what was addressed:

```bash
SUMMARY=$(cat "$ARTIFACTS_DIR/revise_summary.txt" 2>/dev/null || echo "(no summary)")
gh api "repos/omniscient/markethawk/pulls/$PR_NUM/reviews" \
  --method POST \
  --field body="## Advisory Findings Addressed

Automatically addressed **${ADVISORY_COUNT}** advisory finding(s):

${SUMMARY}

---
*Posted by MarketHawk Dark Factory*" \
  --field event="COMMENT" || \
  echo "revise-advisory: WARNING — posting follow-up review comment failed (continuing)"
```

Write artifact:
```bash
printf "STATUS: DONE\nADVISORY_FIXED: %s\n" "$ADVISORY_COUNT" > "$ARTIFACTS_DIR/revise_advisory.md"
```

Exit 0.
