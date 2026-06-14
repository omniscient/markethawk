---
description: Generate an implementation plan from an approved spec, validated by an architect subagent
argument-hint: (no arguments - reads issue context from workflow)
---

# Dark Factory — Plan

**Workflow ID**: $WORKFLOW_ID

---

## SCOPE BOUNDARY

This command's only authorized file outputs are:
- Documents under `docs/superpowers/plans/` (the plan file)

Do NOT create or modify any other files. Do NOT implement code, write tests, or edit configuration.
Implementation belongs to the `Fix issue #N` workflow on a `feat/issue-N-*` branch.

---

## Phase 1: LOAD

1. Read `CLAUDE.md` for development rules, architecture, and conventions
2. The issue context has been fetched by the workflow. It is available in the conversation.
3. Read `/opt/refinement-skills/architect-prompt.md` — you will pass this to the review subagent
4. Find the spec file: look in `docs/superpowers/specs/` for a file matching this issue's topic, or check the issue comments for a "Refinement Pipeline — Spec Generated" report that names the spec path
5. Read the spec file
6. Compute the affected file set and define `load_memory` for path-tag filtering:

```bash
AFFECTED=$(git diff --name-only origin/main...HEAD 2>/dev/null || echo "")

# load_memory: reads a memory file; path-tagged entries are filtered against AFFECTED.
# Entries without a path: tag are always included (backward-compatible).
# When AFFECTED is empty (new branch, spec not yet implemented), all entries are included.
load_memory() {
  local MEMFILE=".archon/memory/$1"
  [ -f "$MEMFILE" ] || return
  while IFS= read -r line; do
    if echo "$line" | grep -q 'path:'; then
      PATH_TAG=$(echo "$line" | sed 's/.*path:\([^ >]*\).*/\1/')
      if [ -z "$AFFECTED" ] || echo "$AFFECTED" | grep -q "^${PATH_TAG}"; then
        echo "$line"
      fi
    else
      echo "$line"
    fi
  done < "$MEMFILE"
}
```

7. Run `load_memory codebase-patterns.md` and include its filtered output in context — global lessons applicable to any change.
8. Run `load_memory architecture.md` and include its filtered output in context — prior architectural decisions (if the file exists). If a memory entry marks an approach as AVOID, do not plan steps that use that approach.
9. Run area-specific memory filtering based on the spec's `Component` field:
   - Component touches `backend/app/models/`, `routers/`, `services/`, or `tasks/` → run `load_memory backend-patterns.md`
   - Component touches `frontend/src/` → run `load_memory frontend-patterns.md`
   - Component touches `docker-compose`, `Dockerfile`, or `dark-factory/` → run `load_memory dark-factory-ops.md`

  Bake relevant memory lessons directly into the plan task steps — do not leave them as a separate advisory section. For example, if `backend-patterns.md` contains a `[PATTERN]` about the `__init__.py` import requirement, the plan's "add model" task must explicitly include an `__init__.py` import step.

## Phase 2: PLAN WRITING

Write a full implementation plan following these conventions:
- Save to `docs/superpowers/plans/YYYY-MM-DD-<feature>.md`
- Start with the standard plan header (Goal, Architecture, Tech Stack)
- Include a File Structure table
- Break into bite-sized tasks (each step is one 2-5 minute action)
- Every task has: Files list, TDD steps (write failing test → verify fail → implement → verify pass → commit)
- No placeholders — every step has actual code blocks and exact file paths
- Exact commands with expected output

## Phase 3: ARCHITECT REVIEW

Before spawning the architect subagent, build `$MEMORY_CONTEXT` by selecting the memory files whose area matches the spec's `Component` field:

```bash
MEMORY_CONTEXT=""

# Filter out [PROVISIONAL] and [INVALID] lines so unverified/invalidated entries
# are excluded from authoritative prompt context (R6).
_filter_memory() {
  grep -v '^\- \[PROVISIONAL\]\|^\- \[INVALID\]' "$1"
}

# architecture.md is always included if it exists
if [ -f ".archon/memory/architecture.md" ]; then
  MEMORY_CONTEXT="$MEMORY_CONTEXT\n\n### From .archon/memory/architecture.md\n$(_filter_memory .archon/memory/architecture.md)"
fi

# Backend area — extract the Component field from the spec file header
SPEC_COMPONENT=$(grep -m1 '^\*\*Component' "$SPEC_FILE" | sed 's/.*: //')
if echo "$SPEC_COMPONENT" | grep -qE "models/|routers/|services/|tasks/"; then
  MEMORY_CONTEXT="$MEMORY_CONTEXT\n\n### From .archon/memory/backend-patterns.md\n$(_filter_memory .archon/memory/backend-patterns.md)"
fi

# Frontend area
if echo "$SPEC_COMPONENT" | grep -q "frontend/src/"; then
  MEMORY_CONTEXT="$MEMORY_CONTEXT\n\n### From .archon/memory/frontend-patterns.md\n$(_filter_memory .archon/memory/frontend-patterns.md)"
fi

# Docker / infrastructure area
if echo "$SPEC_COMPONENT" | grep -qE "docker-compose|Dockerfile|dark-factory/"; then
  MEMORY_CONTEXT="$MEMORY_CONTEXT\n\n### From .archon/memory/dark-factory-ops.md\n$(_filter_memory .archon/memory/dark-factory-ops.md)"
fi
```

Prepend `$MEMORY_CONTEXT` to the architect prompt as a "## Memory: Accumulated Patterns" section immediately before the Spec and Plan content. If `$MEMORY_CONTEXT` is empty (no relevant files exist yet), omit the section entirely.

Spawn an architect subagent using the Agent tool:
- `description`: "Architect review: validate plan against spec"
- `model`: `claude-opus-4-8` — **always** pin this subagent to Opus 4.8 (applies to every re-spawn in the review cycle below too; do not let it inherit the orchestrator's model)
- `prompt`: Content of `architect-prompt.md` with `$SPEC_CONTENT` and `$PLAN_CONTENT` replaced with the actual file contents, and with `$MEMORY_CONTEXT` prepended as shown:

  ```
  ## Memory: Accumulated Patterns
  $MEMORY_CONTEXT

  ---
  [architect-prompt.md content with $SPEC_CONTENT and $PLAN_CONTENT filled in]
  ```

### If architect returns "Issues Found":
1. Fix each issue in the plan
2. Re-spawn the architect subagent for re-review
3. Repeat until approved (max 3 cycles)
4. If still not approved after 3 cycles:
   - Post the plan + architect feedback as an issue comment
   - Add `needs-discussion` label: `gh issue edit $ISSUE_NUM --add-label needs-discussion`
   - Exit cleanly

### If architect returns "Approved":
Proceed to Phase 3.5.

## Phase 3.5: CONFORMANCE REVIEW

Read the `conformance` block from `.claude/skills/refinement/config.yaml`.

If `conformance.enabled` is `false`, skip this phase entirely and proceed to Phase 4. Record `CONFORMANCE_SKIPPED=true` for Phase 4.

1. Read `/opt/refinement-skills/conformance-reviewer-prompt.md`
2. Determine `MAX_CYCLES` from `conformance.max_reconcile_cycles` (default: 3)
3. Set `CONFORMANCE_DIALOGUE=""` and `CONFORMANCE_CYCLE=0`
4. Build the artifact content: the plan document text is `$PLAN_CONTENT`
5. Spawn a conformance reviewer subagent using the Agent tool:
   - `description`: "Conformance review: plan vs spec (cycle N)"
   - `model`: `claude-opus-4-8` — **always** pin this subagent to Opus 4.8 (applies to every reconcile re-spawn too; do not let it inherit the orchestrator's model)
   - `prompt`: Content of `conformance-reviewer-prompt.md` with:
     - `$ARTIFACT_KIND` replaced with `PLAN`
     - `$SPEC_CONTENT` replaced with the spec file contents
     - `$ARTIFACT_CONTENT` replaced with `$PLAN_CONTENT`
6. Append the subagent's output to `CONFORMANCE_DIALOGUE`
7. Parse the **Verdict** line from the output:
   - `✅ Conforms` or `⚠️ Minor deviations` → record `CONFORMANCE_VERDICT` and proceed to Phase 4
   - `⛔ Material divergence` → go to step 8
8. **Reconcile loop** (only if MATERIAL):
   a. Increment `CONFORMANCE_CYCLE`
   b. If `CONFORMANCE_CYCLE > MAX_CYCLES`:
      - Post the conformance dialogue as an issue comment:
        ```
        ## Spec Conformance — Blocked (Plan)

        The plan has material divergences from the spec that could not be resolved in $MAX_CYCLES reconcile cycle(s).

        $CONFORMANCE_DIALOGUE

        ---
        *Posted by MarketHawk Refinement Pipeline*
        ```
      - Add `needs-discussion` label: `gh issue edit $ISSUE_NUM --add-label needs-discussion`
      - Exit cleanly (do not abort — this is a known state)
   c. Read the MATERIAL deviation descriptions from the conformance reviewer output
   d. Revise the plan to address each MATERIAL deviation (update the plan file, re-read it)
   e. Re-spawn the conformance reviewer subagent (same prompt format, updated `$PLAN_CONTENT`)
   f. Append the new output to `CONFORMANCE_DIALOGUE` with a `---` separator and `Cycle N:` header
   g. Parse verdict again → loop back to step 7

## Phase 4: PUBLISH

1. Determine the current branch name: `BRANCH=$(git branch --show-current)`
2. Build GitHub links:
   - Plan link: `https://github.com/omniscient/markethawk/blob/$BRANCH/<plan-file-path>`
   - Branch link: `https://github.com/omniscient/markethawk/tree/$BRANCH`
3. Check if the issue carries the `direct-to-pr` label:
   ```bash
   IS_DIRECT_TO_PR=$(gh issue view $ISSUE_NUM --repo omniscient/markethawk \
     --json labels --jq '.labels[].name' | grep -q "direct-to-pr" && echo "yes" || echo "no")
   PLAN_GRACE=$(python3 -c "import yaml; d=yaml.safe_load(open('.claude/skills/refinement/config.yaml')); print(d.get('direct_to_pr',{}).get('plan_grace_minutes',30))" 2>/dev/null || echo "30")
   ```
   If `IS_DIRECT_TO_PR=yes`, prepend the following note to the "### Next Steps" section of the comment (replacing `$PLAN_GRACE` with the actual value):
   > ⏩ **Auto-advancing in ~`$PLAN_GRACE` min** unless you comment — the scheduler will move this to **Ready** automatically. Leave a comment to re-run the plan or redirect.
4. Commit the plan
5. Post a summary comment on the issue:
   ```
   ## Refinement Pipeline — Plan Generated

   **Plan:** [<plan-file-path>](https://github.com/omniscient/markethawk/blob/<BRANCH>/<plan-file-path>)
   **Branch:** [`<BRANCH>`](https://github.com/omniscient/markethawk/tree/<BRANCH>)
   **Tasks:** <count> tasks, <total-steps> steps

   ### Task Overview
   <numbered list of task names with a one-line description each>

   ### Architect Review

   Include the FULL dialogue from Phase 3. For each review cycle:

   > **Cycle N:**
   > **Verdict:** Approved / Issues Found
   > **Feedback:** <the architect's full feedback>
   > **Changes made:** <what you fixed, if any>

   This lets the reviewer see what the architect flagged and how it was resolved.

   ## Spec Conformance

   (If Phase 3.5 was skipped because `conformance.enabled: false`, write: _Conformance check disabled._)

   (Otherwise, include the full conformance reviewer output from Phase 3.5 — the final attestation table and verdict. If a reconcile loop ran, include the full dialogue with cycle headers.)

   ### Next Steps

   <!-- If IS_DIRECT_TO_PR=yes, insert the auto-advance note here (from step 3 above) -->

   - ✅ **Approve plan** — move the issue to the **Ready** column on the project board. The scheduler will automatically start implementation.
   - ✏️ **Request changes** — leave a comment on this issue with your feedback, then re-run:
     ```bash
     docker compose --profile factory run --rm dark-factory "Plan issue #$ISSUE_NUM"
     ```
   - ❓ **Need to discuss** — add the `needs-discussion` label to pause automation.

   ---
   *Posted by MarketHawk Refinement Pipeline*
   ```
7. Write status to `$ARTIFACTS_DIR/refinement-status.md`:
   ```
   STATUS: PLAN_COMPLETE
   PLAN_PATH: <path>
   BRANCH: <branch>
   TASKS: <count>
   ARCHITECT_CYCLES: <count>
   ```
