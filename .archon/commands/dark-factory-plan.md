---
description: Generate an implementation plan from an approved spec, validated by an architect subagent
argument-hint: (no arguments - reads issue context from workflow)
---

# Dark Factory — Plan

**Workflow ID**: $WORKFLOW_ID

---

## Phase 1: LOAD

1. Read `CLAUDE.md` for development rules, architecture, and conventions
2. The issue context has been fetched by the workflow. It is available in the conversation.
3. Read `/opt/refinement-skills/architect-prompt.md` — you will pass this to the review subagent
4. Find the spec file: look in `Docs/superpowers/specs/` for a file matching this issue's topic, or check the issue comments for a "Refinement Pipeline — Spec Generated" report that names the spec path
5. Read the spec file

## Phase 2: PLAN WRITING

Write a full implementation plan following these conventions:
- Save to `Docs/superpowers/plans/YYYY-MM-DD-<feature>.md`
- Start with the standard plan header (Goal, Architecture, Tech Stack)
- Include a File Structure table
- Break into bite-sized tasks (each step is one 2-5 minute action)
- Every task has: Files list, TDD steps (write failing test → verify fail → implement → verify pass → commit)
- No placeholders — every step has actual code blocks and exact file paths
- Exact commands with expected output

## Phase 3: ARCHITECT REVIEW

Spawn an architect subagent using the Agent tool:
- `description`: "Architect review: validate plan against spec"
- `prompt`: Content of `architect-prompt.md` with $SPEC_CONTENT and $PLAN_CONTENT replaced with the actual file contents

### If architect returns "Issues Found":
1. Fix each issue in the plan
2. Re-spawn the architect subagent for re-review
3. Repeat until approved (max 3 cycles)
4. If still not approved after 3 cycles:
   - Post the plan + architect feedback as an issue comment
   - Add `needs-discussion` label: `gh issue edit $ISSUE_NUM --add-label needs-discussion`
   - Exit cleanly

### If architect returns "Approved":
Proceed to publish.

## Phase 4: PUBLISH

1. Determine the current branch name: `BRANCH=$(git branch --show-current)`
2. Build GitHub links:
   - Plan link: `https://github.com/omniscient/markethawk/blob/$BRANCH/<plan-file-path>`
   - Branch link: `https://github.com/omniscient/markethawk/tree/$BRANCH`
3. Commit the plan
4. Post a summary comment on the issue:
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

   ### Next Steps

   - ✅ **Approve plan** — move the issue to the **Ready** column on the project board. The scheduler will automatically start implementation.
   - ✏️ **Request changes** — leave a comment on this issue with your feedback, then re-run:
     ```bash
     docker compose --profile factory run --rm dark-factory "Plan issue #$ISSUE_NUM"
     ```
   - ❓ **Need to discuss** — add the `needs-discussion` label to pause automation.

   ---
   *Posted by MarketHawk Refinement Pipeline*
   ```
5. Add label: `gh issue edit $ISSUE_NUM --add-label plan-pending-review`
6. Write status to `$ARTIFACTS_DIR/refinement-status.md`:
   ```
   STATUS: PLAN_COMPLETE
   PLAN_PATH: <path>
   BRANCH: <branch>
   TASKS: <count>
   ARCHITECT_CYCLES: <count>
   ```
