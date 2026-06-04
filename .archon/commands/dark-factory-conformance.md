---
description: Verify that the implementation conforms to its approved spec (Gate 2 — code vs spec)
argument-hint: (no arguments - reads issue context from workflow)
---

# Dark Factory — Conformance

**Workflow ID**: $WORKFLOW_ID

---

## Phase 1: LOAD

1. Read `.claude/skills/refinement/config.yaml` and extract the `conformance` block.
2. If `conformance.enabled` is `false`:
   - Write `$ARTIFACTS_DIR/conformance.md` with content: `STATUS: SKIPPED\nREASON: conformance.enabled=false`
   - Exit cleanly (proceed to push-and-pr)
3. Read `/opt/refinement-skills/conformance-reviewer-prompt.md`
4. Read `$ARTIFACTS_DIR/implementation.md` for what was implemented (may be missing if validate wrote nothing — continue anyway)
5. Extract `MAX_CYCLES` from `conformance.max_reconcile_cycles` (default: 3)
6. Extract `BLOCK_ON_MATERIAL` from `conformance.block_on_material` (default: true)
7. Extract `SCOPE_ENFORCEMENT` from `conformance.scope_enforcement` (default: true)
8. Extract `EXCISE_OOS` from `conformance.excise_out_of_scope` (default: true)
9. Extract `BACKLOG_LABEL` from `conformance.backlog_label` (default: `scope-spillover`)
10. Determine `ISSUE_NUM` from the workflow context (look at the issue context passed by the workflow, or run `git branch --show-current | grep -oP 'issue-\K\d+'`)

## Phase 2: LOCATE SPEC

Locate the approved spec using this priority order:

### 2a. Check the "Plan Generated" issue comment

```bash
gh issue view $ISSUE_NUM --json comments \
  | jq -r '[.comments[] | select(.body | test("Refinement Pipeline — Plan Generated"))] | last | .body // ""'
```

Parse the **Spec:** or **Plan:** line from that comment to find the spec file path. The Plan comment typically links the plan file; look for any linked file under `docs/superpowers/specs/`.

### 2b. Check $ARTIFACTS_DIR/refinement-status.md

```bash
cat "$ARTIFACTS_DIR/refinement-status.md" 2>/dev/null || true
```

Look for a `SPEC_PATH:` or `PLAN_PATH:` line that points to a spec.

### 2c. Scan docs/superpowers/specs/

```bash
ls docs/superpowers/specs/ 2>/dev/null | sort -r | head -10
```

Look for a file whose name contains keywords from the issue title. Pick the most recently created file that matches.

### 2d. No-spec fallback

If no spec file is found after all three steps:
- Set `NO_SPEC=true`
- The review will run against the issue body (advisory-only, never blocks)
- Fetch the issue body: `gh issue view $ISSUE_NUM --json body --jq '.body'`
- Log: "No spec found — running advisory-only review against issue body"

## Phase 3: PRE-TRIAGE AND CONFORMANCE REVIEW

### Step 3.0 — Pre-triage: strip housekeeping

Before feeding the diff to the reviewer, strip noise that would pollute the out-of-scope analysis:

```bash
# Get raw diff excluding lock files, auto-generated artifacts, and agent memory
git diff main...HEAD \
  -- ':!*.lock' ':!*.md' \
  ':!.archon/memory/**' \
  ':!codeindex.json' ':!symbolindex.json' \
  ':!docs/codeindex-hotspots.md' \
  ':!docs/database-schema.md' \
  2>/dev/null | head -1000
```

These files are housekeeping that does not belong to the feature's spec surface; excluding them prevents the reviewer from mis-classifying them as out-of-scope.

Also check for an `out-of-scope.md` recorded by the implement agent:
```bash
OOS_LOG=""
if [ -f "$ARTIFACTS_DIR/out-of-scope.md" ]; then
  OOS_LOG=$(cat "$ARTIFACTS_DIR/out-of-scope.md")
fi
```

### Step 3.1 — Build artifact content and run review

1. Get the pre-triaged implementation diff (Step 3.0 above).
   Also read `$ARTIFACTS_DIR/implementation.md` for the implementation summary.

2. Build `$ARTIFACT_CONTENT`:
   ```
   ### Implementation Summary
   <contents of $ARTIFACTS_DIR/implementation.md, or "No implementation summary found.">

   ### Out-of-Scope Log (from implement agent)
   <contents of $ARTIFACTS_DIR/out-of-scope.md, or "None recorded.">

   ### Diff (pre-triaged, truncated to 1000 lines)
   <git diff output from Step 3.0>
   ```

3. Set `CONFORMANCE_CYCLE=0` and `CONFORMANCE_DIALOGUE=""`

4. Spawn a conformance reviewer subagent using the Agent tool:
   - `description`: "Conformance review: code vs spec"
   - `prompt`: Content of `/opt/refinement-skills/conformance-reviewer-prompt.md` with:
     - `$ARTIFACT_KIND` replaced with `IMPLEMENTATION`
     - `$SPEC_CONTENT` replaced with the spec file contents (or issue body if `NO_SPEC=true`)
     - `$ARTIFACT_CONTENT` replaced with the artifact content from Step 3.1

5. Append the subagent's output to `CONFORMANCE_DIALOGUE`

6. Parse the **`## Out-of-Scope Changes`** section from the reviewer output:
   - Extract each `[OOS]` bullet
   - If `SCOPE_ENFORCEMENT=true` and any `[OOS]` entries exist → go to Phase 3.6 (scope remediation) BEFORE processing the verdict
   - If `SCOPE_ENFORCEMENT=false` or no `[OOS]` entries → skip Phase 3.6

7. Parse the **Verdict** line:
   - `✅ Conforms` or `⚠️ Minor deviations` → go to Phase 4 (PASS)
   - `⛔ Material divergence`:
     - If `NO_SPEC=true` OR `BLOCK_ON_MATERIAL=false` → treat as advisory (`⚠️ Minor deviations`), go to Phase 4
     - Otherwise → go to Phase 3.5 (reconcile loop)

## Phase 3.6: SCOPE REMEDIATION (Out-of-scope changes only)

This phase runs when the reviewer found `[OOS]` entries and `SCOPE_ENFORCEMENT=true`.

For each `[OOS]` entry:

### 3.6.1 — Attempt excision (if `EXCISE_OOS=true`)

Try to revert the out-of-scope change from the branch:

```bash
# For a whole file change, restore from main:
git checkout main -- <file>
git add <file>
git commit -m "revert: excise out-of-scope change in <file> (scope enforcement)"

# For a partial hunk: apply a targeted reverse patch
# If excision cannot be applied cleanly (conflicts), fall back to Block (see below).
```

After excision:
- Re-run the in-scope tests to confirm the excision didn't break anything:
  ```bash
  cd backend && python -m pytest tests/ -x -q 2>/dev/null || true
  ```
- If tests pass → excision succeeded; continue to 3.6.2.
- If tests fail or revert won't apply cleanly → skip excision, note the failure, proceed to 3.6.2 anyway (backlog ticket is always created regardless of excision outcome).

### 3.6.2 — Create backlog ticket

For each `[OOS]` entry (whether excision succeeded or not), create one GitHub issue:

```bash
SPILLOVER_TITLE="<short title derived from the OOS description>"
SPILLOVER_BODY="## Scope spillover from #${ISSUE_NUM}

The dark factory noticed this pre-existing defect while implementing issue #${ISSUE_NUM} but did not fix it inline (scope enforcement).

**File/area:** <file>
**Defect:** <description from OOS entry>

---
*Automatically triaged by MarketHawk Dark Factory scope enforcement.*"

SPILLOVER_NUM=$(gh issue create \
  --repo omniscient/markethawk \
  --title "$SPILLOVER_TITLE" \
  --body "$SPILLOVER_BODY" \
  --label "needs-triage,${BACKLOG_LABEL}" \
  --json number --jq '.number')
echo "Created spillover ticket #${SPILLOVER_NUM}"
```

Collect all created ticket numbers into `SPILLOVER_TICKETS` (space-separated list).

### 3.6.3 — Comment on origin issue

After all OOS entries are processed:

```bash
EXCISED_COUNT=<number of successfully excised changes>
TICKET_LIST=$(echo "$SPILLOVER_TICKETS" | tr ' ' '\n' | sed 's/^/#/' | tr '\n' ' ')
gh issue comment "$ISSUE_NUM" --body "**Scope enforcement:** excised ${EXCISED_COUNT} out-of-scope change(s) from this branch. Each unrelated defect has been filed as a linked backlog ticket: ${TICKET_LIST}

The branch is now clean. These tickets are ready for triage."
```

### 3.6.4 — Resume normal flow

After scope remediation (regardless of excision success/failure), re-run the conformance review with the updated diff (Step 3.1 again), then proceed to the verdict check (Step 3.1 step 7).

Store `SPILLOVER_TICKETS` so the `report` node can include it.

## Phase 3.5: RECONCILE LOOP (Material divergence only)

1. Increment `CONFORMANCE_CYCLE`
2. If `CONFORMANCE_CYCLE > MAX_CYCLES` → go to Phase 5 (BLOCKED)
3. Read the MATERIAL deviation descriptions from the conformance reviewer output
4. Fix the code to align with the spec:
   - Write a failing test that targets the missing/wrong behavior
   - Run the test to confirm it fails: `cd backend && python -m pytest <test_path> -x -v`
   - Implement the fix
   - Run the test to confirm it passes
   - Commit: `git add -A && git commit -m "fix: align implementation with spec (conformance cycle $CONFORMANCE_CYCLE)"`
5. Re-get the diff:
   ```bash
   git diff main...HEAD -- ':!*.lock' ':!*.md' 2>/dev/null | head -1000
   ```
6. Re-spawn the conformance reviewer subagent (same prompt format, updated diff)
7. Prepend `Cycle $CONFORMANCE_CYCLE:` header and append the new output to `CONFORMANCE_DIALOGUE` with a `---` separator
8. Parse verdict again → loop back to step 1

## Phase 4: PASS — Write attestation

Write the attestation to `$ARTIFACTS_DIR/conformance.md`:

```
STATUS: PASS
VERDICT: <CONFORMS | MINOR | ADVISORY>
CYCLES: $CONFORMANCE_CYCLE
NO_SPEC: <true|false>
OOS_EXCISED: <count of successfully excised out-of-scope changes, or 0>
OOS_TICKETS: <space-separated spillover ticket numbers, e.g. "207 208", or empty>

---

$CONFORMANCE_DIALOGUE
```

Exit `0`. The `push-and-pr` and `report` nodes will proceed normally.

## Phase 5: BLOCKED — Material divergence unresolved

This phase is only reached if reconcile failed after `MAX_CYCLES`.

1. Post a "Spec Conformance — Blocked" comment on the issue:
   ```bash
   gh issue comment $ISSUE_NUM --body "## Spec Conformance — Blocked

   The implementation has material divergences from the spec that could not be resolved in $MAX_CYCLES reconcile cycle(s).

   $CONFORMANCE_DIALOGUE

   ### Next Steps

   Review the deviations above and either:
   - Fix the implementation to match the spec, then re-run: \`docker compose --profile factory run --rm dark-factory \"Continue issue #$ISSUE_NUM\"\`
   - Update the spec to document the deviation as intentional, then re-run.
   - Add \`needs-discussion\` if the spec itself needs revisiting.

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

3. Add `needs-discussion` label:
   ```bash
   gh issue edit $ISSUE_NUM --add-label needs-discussion
   ```

4. Write blocked status to `$ARTIFACTS_DIR/conformance.md`:
   ```
   STATUS: BLOCKED
   VERDICT: MATERIAL
   CYCLES: $CONFORMANCE_CYCLE

   ---

   $CONFORMANCE_DIALOGUE
   ```

5. Exit non-zero (`exit 1`) — this prevents `push-and-pr` and `status-in-review` from running.
