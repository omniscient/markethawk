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
7. Determine `ISSUE_NUM` from the workflow context (look at the issue context passed by the workflow, or run `git branch --show-current | grep -oP 'issue-\K\d+'`)

## Phase 2: LOCATE SPEC

Locate the approved spec using this priority order:

### 2a. Check the "Plan Generated" issue comment

```bash
gh issue view $ISSUE_NUM --json comments \
  | jq -r '[.comments[] | select(.body | test("Refinement Pipeline — Plan Generated"))] | last | .body // ""'
```

Parse the **Spec:** or **Plan:** line from that comment to find the spec file path. The Plan comment typically links the plan file; look for any linked file under `Docs/superpowers/specs/`.

### 2b. Check $ARTIFACTS_DIR/refinement-status.md

```bash
cat "$ARTIFACTS_DIR/refinement-status.md" 2>/dev/null || true
```

Look for a `SPEC_PATH:` or `PLAN_PATH:` line that points to a spec.

### 2c. Scan Docs/superpowers/specs/

```bash
ls Docs/superpowers/specs/ 2>/dev/null | sort -r | head -10
```

Look for a file whose name contains keywords from the issue title. Pick the most recently created file that matches.

### 2d. No-spec fallback

If no spec file is found after all three steps:
- Set `NO_SPEC=true`
- The review will run against the issue body (advisory-only, never blocks)
- Fetch the issue body: `gh issue view $ISSUE_NUM --json body --jq '.body'`
- Log: "No spec found — running advisory-only review against issue body"

## Phase 3: CONFORMANCE REVIEW

1. Get the implementation diff:
   ```bash
   git diff main...HEAD -- ':!*.lock' ':!*.md' 2>/dev/null | head -1000
   ```
   Also read `$ARTIFACTS_DIR/implementation.md` for the implementation summary.

2. Build `$ARTIFACT_CONTENT`:
   ```
   ### Implementation Summary
   <contents of $ARTIFACTS_DIR/implementation.md, or "No implementation summary found.">

   ### Diff (truncated to 1000 lines)
   <git diff output>
   ```

3. Set `CONFORMANCE_CYCLE=0` and `CONFORMANCE_DIALOGUE=""`

4. Spawn a conformance reviewer subagent using the Agent tool:
   - `description`: "Conformance review: code vs spec"
   - `prompt`: Content of `/opt/refinement-skills/conformance-reviewer-prompt.md` with:
     - `$ARTIFACT_KIND` replaced with `IMPLEMENTATION`
     - `$SPEC_CONTENT` replaced with the spec file contents (or issue body if `NO_SPEC=true`)
     - `$ARTIFACT_CONTENT` replaced with the artifact content from step 2

5. Append the subagent's output to `CONFORMANCE_DIALOGUE`

6. Parse the **Verdict** line:
   - `✅ Conforms` or `⚠️ Minor deviations` → go to Phase 4 (PASS)
   - `⛔ Material divergence`:
     - If `NO_SPEC=true` OR `BLOCK_ON_MATERIAL=false` → treat as advisory (`⚠️ Minor deviations`), go to Phase 4
     - Otherwise → go to Phase 3.5 (reconcile loop)

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
