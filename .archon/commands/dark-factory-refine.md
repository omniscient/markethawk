---
description: Refine a GitHub issue into a design spec using multi-agent brainstorming
argument-hint: (no arguments - reads issue context from workflow)
---

# Dark Factory — Refine

**Workflow ID**: $WORKFLOW_ID

---

## CRITICAL: Skip Guard

If the issue has any of these labels, STOP immediately and exit with code 0 (not an error):
- `spec-pending-review` — already processed
- `needs-discussion` — waiting for human input
- `epic` — needs manual decomposition

## Phase 1: LOAD

1. Read `CLAUDE.md` for development rules, architecture, and conventions
2. Read `ARCHITECTURE.md` for service topology and module map
3. The issue context has been fetched by the workflow. It is available in the conversation.
4. Read `/opt/refinement-skills/orchestrator-prompt.md` for your process instructions
5. Read `/opt/refinement-skills/product-owner-prompt.md` — you will pass this to subagents
6. Read `/opt/refinement-skills/config.yaml` for pipeline configuration

### If this is a re-run (feedback present in issue comments after a previous refinement report)

Read the latest comments after any "Refinement Pipeline" report. Treat these as additional requirements from the user. Do NOT start from scratch — build on the previous spec if one exists on this branch.

## Phase 2: PRE-FLIGHT

Check the issue body length. If fewer than 20 characters:
1. Post a comment: "This issue needs more detail before it can be refined. Please add a description of what you'd like to build and any constraints."
2. Add `needs-discussion` label: `gh issue edit $ISSUE_NUM --add-label needs-discussion`
3. Exit cleanly

## Phase 3: CONTEXT ASSEMBLY

Build a context package by exploring the codebase:
1. Identify which area of the codebase the issue touches (backend models? services? frontend pages?)
2. Read the relevant existing files to understand current patterns
3. Assemble this into a context summary you will pass to every product-owner subagent

## Phase 4: BRAINSTORMING LOOP

Follow the process in `orchestrator-prompt.md`:
1. Formulate one clarifying question at a time
2. For each question, spawn a product-owner subagent using the Agent tool:
   - `description`: "Product owner: <short question summary>"
   - `prompt`: Content of `product-owner-prompt.md` with the $ISSUE_CONTEXT, $QA_HISTORY, and $QUESTION placeholders replaced with actual values
   - The subagent needs Glob, Grep, and Read tools to explore the codebase
3. If the subagent returns a response starting with `UNCERTAIN:`:
   - Post a comment on the issue explaining the question and context gathered so far
   - Run: `gh issue edit $ISSUE_NUM --add-label needs-discussion`
   - Write a brief summary to `$ARTIFACTS_DIR/refinement-status.md` noting the abort reason
   - Exit cleanly (exit code 0)
4. Record the answer and continue until you have enough information

## Phase 5: SPEC WRITING

1. Propose 2-3 approaches with trade-offs
2. Select the best approach based on Q&A answers and codebase patterns
3. Write the spec to `Docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md` following existing spec format:
   - Overview / problem statement
   - Requirements (from Q&A)
   - Architecture / approach
   - Alternatives considered
   - Open questions (non-blocking)
   - Assumptions (flagged)
4. Self-review: placeholder scan, consistency check, scope check, ambiguity check. Fix inline.
5. Commit the spec

## Phase 6: PUBLISH

1. Post a summary comment on the issue:
   ```
   ## Refinement Pipeline — Spec Generated

   **Spec:** `<spec-file-path>`
   **Branch:** `<branch-name>`

   ### Summary
   <2-3 sentence overview>

   ### Requirements
   <bulleted list of key requirements>

   ### Approach
   <1-2 sentences on chosen approach>

   ### Assumptions
   <bulleted list if any>

   ---
   *Posted by MarketHawk Refinement Pipeline*
   ```
2. Add label: `gh issue edit $ISSUE_NUM --add-label spec-pending-review`
3. Write status to `$ARTIFACTS_DIR/refinement-status.md`:
   ```
   STATUS: SPEC_COMPLETE
   SPEC_PATH: <path>
   BRANCH: <branch>
   QUESTIONS_ASKED: <count>
   ```
