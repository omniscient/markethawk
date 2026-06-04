# Auto-Refinement Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a multi-agent refinement pipeline that automatically produces specs and implementation plans from raw GitHub issues, integrated into the existing backlog scheduler.

**Architecture:** An orchestrator agent drives brainstorming and spawns stateless product-owner subagents to answer clarifying questions. After human approval, a plan-writing stage with architect validation advances the issue to Ready. The pipeline integrates into `scheduler.sh` as new waterfall tiers for Backlog and Refined columns.

**Tech Stack:** Bash (scheduler integration), Claude Code Agent tool (orchestrator/subagent communication), Archon workflow YAML (intent routing), GitHub CLI (issue/board manipulation)

---

## File Structure

| File | Responsibility |
|------|---------------|
| `.claude/skills/refinement/SKILL.md` | Skill entry point — loaded when manually invoking refinement |
| `.claude/skills/refinement/product-owner-prompt.md` | Product owner persona for answering brainstorming questions |
| `.claude/skills/refinement/architect-prompt.md` | Architect persona for validating implementation plans |
| `.claude/skills/refinement/orchestrator-prompt.md` | Orchestrator instructions for driving the brainstorming loop |
| `.claude/skills/refinement/config.yaml` | Tunable parameters (WIP limits, skip labels, thresholds) |
| `.archon/commands/dark-factory-refine.md` | Archon command for Phase 1 (spec generation) |
| `.archon/commands/dark-factory-plan.md` | Archon command for Phase 2 (plan generation) |
| `.archon/workflows/archon-dark-factory.yaml` | Modified: add `refine` and `plan` intents |
| `dark-factory/scheduler.sh` | Modified: add Backlog and Refined waterfall tiers |
| `dark-factory/Dockerfile` | Modified: copy refinement skill files into image |
| `dark-factory/entrypoint.sh` | Modified: handle `refine` and `plan` intents |

---

### Task 1: Refinement Skill Files

Create the four prompt files and config that define the refinement pipeline's behavior. These are the adjustable building blocks.

**Files:**
- Create: `.claude/skills/refinement/SKILL.md`
- Create: `.claude/skills/refinement/product-owner-prompt.md`
- Create: `.claude/skills/refinement/architect-prompt.md`
- Create: `.claude/skills/refinement/orchestrator-prompt.md`
- Create: `.claude/skills/refinement/config.yaml`

- [ ] **Step 1: Create the config file**

```yaml
# .claude/skills/refinement/config.yaml
refine:
  wip_limit: 2
  skip_labels:
    - needs-discussion
    - epic
    - spec-pending-review
  min_issue_body_length: 20

plan:
  auto_advance_to_ready: true
```

- [ ] **Step 2: Create the product owner prompt**

```markdown
<!-- .claude/skills/refinement/product-owner-prompt.md -->

# Product Owner — MarketHawk

You are the product owner for MarketHawk, a full-stack stock scanning platform that identifies pre-market volume spikes and unusual trading patterns.

## Your Role

You answer clarifying questions from a brainstorming agent that is refining a feature idea into a spec. Base your answers on:

1. **The GitHub issue** — title, body, labels, comments (provided below)
2. **The codebase** — explore files, read existing patterns, check architecture
3. **Domain documentation** — CLAUDE.md, ARCHITECTURE.md, and any docs referenced in the issue
4. **The Q&A history** — stay consistent with your earlier answers

## How to Answer

- Be concrete and specific. "Use PostgreSQL" not "use a database."
- Reference existing codebase patterns when relevant. "Follow the ScannerEvent model pattern in backend/app/models/scanner.py."
- If the issue or codebase clearly implies an answer, state it directly.
- If you need to make a judgment call, explain your reasoning briefly.
- Keep answers focused — 2-5 sentences is usually enough.

## When You Cannot Answer

If the question requires information that is NOT available in the issue, codebase, or documentation — and answering would require guessing about business intent, user preferences, or external constraints — respond with exactly:

```
UNCERTAIN: <one-sentence explanation of what information is missing>
```

Examples of UNCERTAIN situations:
- "What's the expected SLA for this endpoint?" (no SLA docs exist)
- "Should this be behind a feature flag?" (no feature flag policy documented)
- "What's the priority relative to issue #X?" (requires human judgment)

Examples where you SHOULD answer (not UNCERTAIN):
- "What database should this use?" → PostgreSQL, it's the existing stack
- "Should this be a Celery task?" → Yes, it's async and matches existing patterns
- "What's the API route convention?" → Follow /api/{resource} pattern from existing routers

## Context

### Issue
$ISSUE_CONTEXT

### Q&A History
$QA_HISTORY

### Question
$QUESTION
```

- [ ] **Step 3: Create the architect prompt**

```markdown
<!-- .claude/skills/refinement/architect-prompt.md -->

# Architect Reviewer — MarketHawk

You are an architect reviewing an implementation plan for the MarketHawk stock scanning platform.

## Your Role

Validate that the implementation plan is complete, consistent, and follows codebase conventions. You are the last gate before the plan is handed to an autonomous agent for implementation.

## What to Check

### 1. Spec Coverage
Read the spec (provided below). For each requirement, verify there is a corresponding task in the plan. List any requirements that have no task.

### 2. File Path Consistency
Check that file paths, function names, and interfaces used in later tasks match what was defined in earlier tasks. Flag any mismatches.

### 3. Task Decomposition
Each task should:
- Be self-contained (produces a working, testable change)
- Follow TDD (test first, then implementation)
- Include exact file paths and code blocks
- Have a commit step

Flag tasks that are too large (should be split) or too vague (missing code blocks).

### 4. Codebase Conventions
Verify the plan follows patterns from the existing codebase:
- Backend: FastAPI routers, SQLAlchemy models, Pydantic schemas, service layer
- Frontend: React components, React Query hooks, Axios API layer
- Testing: pytest for backend, tsc for frontend

### 5. No Placeholders
Flag any: "TBD", "TODO", "implement later", "add appropriate error handling", "similar to Task N", or steps without code blocks.

## Output Format

## Architect Review

**Status:** Approved | Issues Found

**Issues (if any):**
- [Task N / Section]: [specific issue] — [why it matters]

**Recommendations (advisory, do not block approval):**
- [suggestions]

## Context

### Spec
$SPEC_CONTENT

### Plan
$PLAN_CONTENT
```

- [ ] **Step 4: Create the orchestrator prompt**

```markdown
<!-- .claude/skills/refinement/orchestrator-prompt.md -->

# Refinement Orchestrator

You are a brainstorming agent that refines raw GitHub issues into complete design specs for the MarketHawk stock scanning platform.

## Your Process

### Phase 1: Context Gathering
1. Read the GitHub issue (title, body, labels, comments)
2. Read `CLAUDE.md` for tech stack, architecture, and conventions
3. Read `ARCHITECTURE.md` for service topology
4. Explore the codebase areas relevant to the issue (models, services, routers, frontend components)
5. Build a mental model of what already exists and what the issue is asking for

### Phase 2: Clarifying Questions
Ask questions one at a time to refine the idea. For each question:
1. Formulate a clear, specific question (prefer multiple choice when possible)
2. Spawn a product-owner subagent with the question and full context
3. Record the answer
4. If the product owner returns `UNCERTAIN: <reason>`:
   - Post a comment on the issue with the question, context gathered so far, and what you need to proceed
   - Add `needs-discussion` label to the issue
   - Exit immediately
5. Continue until you have enough information to write the spec

Focus questions on:
- Purpose and success criteria
- Scope boundaries (what's in, what's out)
- Integration points with existing code
- Data model decisions
- UI/UX requirements (if applicable)
- Error handling and edge cases

### Phase 3: Approach Selection
Propose 2-3 approaches with trade-offs. Select the best one based on:
- Product owner answers
- Codebase conventions and existing patterns
- YAGNI — remove unnecessary features
- Simplicity and maintainability

### Phase 4: Spec Writing
Write the spec to `Docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md` following the existing spec format. Include:
- Overview (problem statement from issue)
- Requirements (distilled from Q&A)
- Architecture / approach
- Alternatives considered (from Phase 3)
- Open questions (non-blocking)
- Assumptions (flagged explicitly)

### Phase 5: Self-Review
Run this checklist on the spec:
1. Placeholder scan — any "TBD", "TODO", incomplete sections?
2. Internal consistency — do sections contradict each other?
3. Scope check — focused enough for a single implementation plan?
4. Ambiguity check — could any requirement be interpreted two different ways?
Fix issues inline.

### Phase 6: Publish
1. Commit the spec to the current branch
2. Post a summary comment on the issue with the spec highlights
3. Add `spec-pending-review` label to the issue

## Subagent Invocation

To ask the product owner a question, spawn a subagent with:
- Description: "Product owner: <short question summary>"
- Prompt: The full content of `product-owner-prompt.md` with $ISSUE_CONTEXT, $QA_HISTORY, and $QUESTION replaced
- The subagent should have access to Read, Grep, and Glob tools for codebase exploration

## Issue Context
$ISSUE_CONTEXT

## Feedback (if re-run after changes requested)
$FEEDBACK
```

- [ ] **Step 5: Create the SKILL.md entry point**

```markdown
<!-- .claude/skills/refinement/SKILL.md -->
---
name: refinement
description: >
  Multi-agent refinement pipeline for GitHub issues. Drives brainstorming via an
  orchestrator + product-owner subagent pair, produces specs, then generates
  implementation plans validated by an architect subagent. Integrates with the
  backlog scheduler for automatic processing.
---

# Refinement Pipeline

Invoke this skill to refine a GitHub issue into a complete spec and implementation plan.

## Usage

Manual invocation (in Claude Code session):
```
Refine issue #<number>
```

Automated invocation (via scheduler or dark factory):
```bash
docker compose --profile factory run --rm dark-factory "Refine issue #12"
docker compose --profile factory run --rm dark-factory "Plan issue #12"
```

## What It Does

**Phase 1 — Spec Generation (`refine` intent):**
1. Reads the issue and explores the codebase
2. Asks clarifying questions via product-owner subagent
3. Selects best approach from 2-3 alternatives
4. Writes and self-reviews the spec
5. Posts spec to the issue, adds `spec-pending-review` label

**Phase 2 — Plan Generation (`plan` intent):**
1. Reads the approved spec
2. Writes a full implementation plan (TDD, bite-sized tasks)
3. Validates via architect subagent
4. Posts plan to the issue, moves to Ready

## Configuration

See `config.yaml` for tunable parameters.

## Prompt Files

- `product-owner-prompt.md` — Persona for the Q&A subagent (adjustable)
- `architect-prompt.md` — Persona for the plan reviewer (adjustable)
- `orchestrator-prompt.md` — Instructions for the brainstorming orchestrator
```

- [ ] **Step 6: Commit**

```bash
git add .claude/skills/refinement/
git commit -m "feat(refinement): add skill files for auto-refinement pipeline (issue #52)

Create product-owner, architect, and orchestrator prompts plus config.
These are the adjustable building blocks of the refinement pipeline."
```

---

### Task 2: Archon Commands for Refine and Plan

Create the two Archon command files that Claude executes inside the dark factory container — one for spec generation (Phase 1), one for plan generation (Phase 2).

**Files:**
- Create: `.archon/commands/dark-factory-refine.md`
- Create: `.archon/commands/dark-factory-plan.md`

- [ ] **Step 1: Create the refine command**

```markdown
<!-- .archon/commands/dark-factory-refine.md -->
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
4. Read `.claude/skills/refinement/orchestrator-prompt.md` for your process instructions
5. Read `.claude/skills/refinement/product-owner-prompt.md` — you will pass this to subagents
6. Read `.claude/skills/refinement/config.yaml` for pipeline configuration

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
```

- [ ] **Step 2: Create the plan command**

```markdown
<!-- .archon/commands/dark-factory-plan.md -->
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
3. Read `.claude/skills/refinement/architect-prompt.md` — you will pass this to the review subagent
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

1. Commit the plan
2. Post a summary comment on the issue:
   ```
   ## Refinement Pipeline — Plan Generated

   **Plan:** `<plan-file-path>`
   **Branch:** `<branch-name>`
   **Tasks:** <count> tasks, <total-steps> steps

   ### Task Overview
   <numbered list of task names>

   ---
   *Posted by MarketHawk Refinement Pipeline*
   ```
3. Write status to `$ARTIFACTS_DIR/refinement-status.md`:
   ```
   STATUS: PLAN_COMPLETE
   PLAN_PATH: <path>
   BRANCH: <branch>
   TASKS: <count>
   ARCHITECT_CYCLES: <count>
   ```
```

- [ ] **Step 3: Commit**

```bash
git add .archon/commands/dark-factory-refine.md .archon/commands/dark-factory-plan.md
git commit -m "feat(refinement): add Archon commands for refine and plan intents (issue #52)

dark-factory-refine.md drives Phase 1 (spec generation with product-owner subagent).
dark-factory-plan.md drives Phase 2 (plan generation with architect validation)."
```

---

### Task 3: Extend the Archon Workflow with Refine and Plan Intents

Modify the dark factory Archon workflow to route `refine` and `plan` intents alongside the existing `new`/`continue`/`close` intents.

**Files:**
- Modify: `.archon/workflows/archon-dark-factory.yaml`

- [ ] **Step 1: Update the parse-intent node to recognize refine and plan**

In `.archon/workflows/archon-dark-factory.yaml`, replace the `parse-intent` node's prompt and output_format:

```yaml
  - id: parse-intent
    prompt: |
      Parse this command and extract two things:
      1. The GitHub issue number
      2. The intent: "new" (first time working on this issue), "continue" (iterate on existing work), "close" (merge and tear down), "refine" (generate a design spec), or "plan" (generate an implementation plan)

      Command: $ARGUMENTS

      Output ONLY valid JSON, nothing else:
      {"issue_number": <int>, "intent": "<new|continue|close|refine|plan>"}
    allowed_tools: []
    model: haiku
    output_format:
      type: object
      properties:
        issue_number:
          type: integer
        intent:
          type: string
          enum: [new, continue, close, refine, plan]
      required: [issue_number, intent]
```

- [ ] **Step 2: Add refine-specific branch setup node**

Add this node after the existing `setup-branch` node:

```yaml
  - id: setup-refine-branch
    bash: |
      ISSUE=$(echo $fetch-issue.output | jq -r '.resolved_number')
      INTENT=$parse-intent.output.intent
      SLUG=$(echo $fetch-issue.output | jq -r '.title // "feature"' | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | head -c 40)
      BRANCH="refine/issue-${ISSUE}-${SLUG}"

      EXISTING=$(git branch -r --list "origin/$BRANCH" 2>/dev/null)
      if [ -n "$EXISTING" ]; then
        git fetch origin "$BRANCH" && git checkout "$BRANCH"
      else
        git checkout -b "$BRANCH"
      fi
      echo "$BRANCH"
    depends_on: [parse-intent, fetch-issue]
    when: "$parse-intent.output.intent == 'refine' || $parse-intent.output.intent == 'plan'"
    timeout: 15000
```

- [ ] **Step 3: Add the refine node**

Add after `setup-refine-branch`:

```yaml
  - id: refine
    command: dark-factory-refine
    depends_on: [setup-refine-branch, fetch-issue]
    when: "$parse-intent.output.intent == 'refine'"
    idle_timeout: 600000
```

- [ ] **Step 4: Add the plan node**

Add after `refine`:

```yaml
  - id: plan
    command: dark-factory-plan
    depends_on: [setup-refine-branch, fetch-issue]
    when: "$parse-intent.output.intent == 'plan'"
    idle_timeout: 600000
```

- [ ] **Step 5: Add the refine push-and-label node**

Add after the plan node. This handles pushing the refine/plan branches (no PR creation — just push and label):

```yaml
  - id: refine-push
    bash: |
      ISSUE=$(echo $fetch-issue.output | jq -r '.resolved_number')
      BRANCH=$(git branch --show-current)

      git push -u origin "$BRANCH"
      echo "Pushed $BRANCH for issue #$ISSUE"
    depends_on: [refine]
    when: "$parse-intent.output.intent == 'refine'"
    timeout: 30000

  - id: plan-push-and-advance
    bash: |
      ISSUE=$(echo $fetch-issue.output | jq -r '.resolved_number')
      BRANCH=$(git branch --show-current)

      git push -u origin "$BRANCH"

      # Move issue to Ready
      ITEM_ID=$(gh project item-list 1 --owner omniscient --format json --limit 200 \
        | jq -r ".items[] | select(.content.number == $ISSUE and .content.type == \"Issue\") | .id")
      if [ -n "$ITEM_ID" ]; then
        gh project item-edit \
          --project-id PVT_kwHOAAFds84BWh4w \
          --id "$ITEM_ID" \
          --field-id PVTSSF_lAHOAAFds84BWh4wzhR1VaA \
          --single-select-option-id 61e4505c
        echo "Moved issue #$ISSUE to Ready"
      fi

      gh issue comment "$ISSUE" --body "Refinement pipeline complete. Spec and plan are on branch \`$BRANCH\`. Issue moved to **Ready** for implementation.

      ---
      *Posted by MarketHawk Refinement Pipeline*"
    depends_on: [plan]
    when: "$parse-intent.output.intent == 'plan'"
    timeout: 30000
```

- [ ] **Step 6: Update the existing setup-branch 'when' clause**

The existing `setup-branch` node currently uses `when: "$parse-intent.output.intent != 'close'"`. Update it to exclude refine and plan intents too:

```yaml
  - id: setup-branch
    # ... existing bash unchanged ...
    when: "$parse-intent.output.intent == 'new' || $parse-intent.output.intent == 'continue'"
```

- [ ] **Step 7: Update existing implement, preview-up, validate, push-and-pr, status-in-review, report nodes**

Each of these nodes currently has `when: "$parse-intent.output.intent != 'close'"`. Update them all to:

```yaml
    when: "$parse-intent.output.intent == 'new' || $parse-intent.output.intent == 'continue'"
```

This ensures the dark factory's implementation/preview/PR pipeline only runs for `new` and `continue` intents, not for `refine` or `plan`.

- [ ] **Step 8: Commit**

```bash
git add .archon/workflows/archon-dark-factory.yaml
git commit -m "feat(refinement): extend Archon workflow with refine and plan intents (issue #52)

Add refine/plan branch setup, refine and plan command nodes, push nodes,
and update existing nodes to only trigger on new/continue intents."
```

---

### Task 4: Update the Entrypoint for Refine and Plan Intents

The dark factory `entrypoint.sh` currently parses `fix`, `continue`, and `close` intents from the command string and moves the issue to "In Progress". For `refine` and `plan`, the issue should NOT move to "In Progress" — it stays in its current column (Backlog or Refined).

**Files:**
- Modify: `dark-factory/entrypoint.sh:43-68`

- [ ] **Step 1: Update intent parsing to recognize refine and plan**

In `dark-factory/entrypoint.sh`, replace line 44:

```bash
INTENT=$(echo "$ARGUMENTS" | grep -oiP '^\s*\K(fix|continue|close)' | head -1 | tr '[:upper:]' '[:lower:]')
```

with:

```bash
INTENT=$(echo "$ARGUMENTS" | grep -oiP '^\s*\K(fix|continue|close|refine|plan)' | head -1 | tr '[:upper:]' '[:lower:]')
```

- [ ] **Step 2: Update the "move to In Progress" guard**

Replace line 65-68:

```bash
if [ -n "$ISSUE_NUM" ] && [ "$INTENT" != "close" ]; then
  echo "Moving issue #$ISSUE_NUM to In Progress..."
  set_board_status "$STATUS_IN_PROGRESS" || echo "WARNING: Could not update project board"
fi
```

with:

```bash
if [ -n "$ISSUE_NUM" ] && [ "$INTENT" != "close" ] && [ "$INTENT" != "refine" ] && [ "$INTENT" != "plan" ]; then
  echo "Moving issue #$ISSUE_NUM to In Progress..."
  set_board_status "$STATUS_IN_PROGRESS" || echo "WARNING: Could not update project board"
fi
```

- [ ] **Step 3: Update the failure handler to handle refine/plan differently**

Replace the `on_failure` function (lines 71-89):

```bash
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
```

- [ ] **Step 4: Commit**

```bash
git add dark-factory/entrypoint.sh
git commit -m "feat(refinement): handle refine/plan intents in entrypoint.sh (issue #52)

Skip In Progress move for refine/plan. Separate failure handler for
refinement pipeline errors (no Blocked move, different report signature)."
```

---

### Task 5: Add Backlog and Refined Tiers to Scheduler

Add the two new waterfall tiers to `scheduler.sh` — Backlog items trigger refinement, Refined items trigger plan generation.

**Files:**
- Modify: `dark-factory/scheduler.sh:1-19` (add constants)
- Modify: `dark-factory/scheduler.sh:59-64` (extend `is_issue_running`)
- Modify: `dark-factory/scheduler.sh:80-95` (extend `has_skip_label`)
- Modify: `dark-factory/scheduler.sh:213-300` (add waterfall tiers)

- [ ] **Step 1: Add board constants for Backlog and Refined**

In `dark-factory/scheduler.sh`, after line 19 (`STATUS_DONE="98236657"`), add:

```bash
STATUS_BACKLOG="f75ad846"
STATUS_REFINED="0c79ebe5"

# Refinement pipeline configuration
REFINE_WIP_LIMIT="${REFINE_WIP_LIMIT:-2}"
REFINE_SKIP_LABELS="needs-discussion,epic,spec-pending-review"
```

- [ ] **Step 2: Add a function to count running refinement containers**

After the `is_issue_running` function (after line 64), add:

```bash
count_refine_running() {
  docker ps --format '{{.Command}}' 2>/dev/null | grep -c '"Refine issue\|"Plan issue' || echo "0"
}

has_refine_skip_label() {
  local item="$1"
  local labels
  labels=$(echo "$item" | jq -r '.labels[]?' 2>/dev/null)
  IFS=',' read -ra SKIP_ARRAY <<< "$REFINE_SKIP_LABELS"
  for skip in "${SKIP_ARRAY[@]}"; do
    if echo "$labels" | grep -qi "$skip"; then
      return 0
    fi
  done
  return 1
}

has_new_comment_after_report() {
  local issue_num="$1"
  local report_marker="$2"
  local comments
  comments=$(gh issue view "$issue_num" --json comments -q '.comments' 2>/dev/null) || { echo "no"; return; }

  local report_idx
  report_idx=$(echo "$comments" | jq "map(.body) | to_entries | map(select(.value | test(\"$report_marker\"))) | last | .key // -1")

  if [ "$report_idx" = "-1" ]; then
    echo "no"
    return
  fi

  local total
  total=$(echo "$comments" | jq 'length')
  local next_idx=$((report_idx + 1))
  if [ "$next_idx" -lt "$total" ]; then
    echo "yes"
  else
    echo "no"
  fi
}
```

- [ ] **Step 3: Add Backlog and Refined item fetching in the main loop**

In the main loop, after line 224 (`IN_PROGRESS=$(get_items_by_status "$BOARD_ITEMS" "In Progress")`), add:

```bash
  BACKLOG=$(get_items_by_status "$BOARD_ITEMS" "Backlog")
  REFINED=$(get_items_by_status "$BOARD_ITEMS" "Refined")

  BACKLOG_COUNT=$(echo "$BACKLOG" | jq 'length')
  REFINED_COUNT=$(echo "$REFINED" | jq 'length')
  REFINE_RUNNING=$(count_refine_running)
```

- [ ] **Step 4: Add Priority 0 — Backlog items (refinement)**

Insert BEFORE the existing "Priority 1: In Review" block (before line 235). The new block:

```bash
  # --- Priority 0: Backlog items (refinement) ---
  while IFS= read -r item; do
    [ -n "$DISPATCHED" ] && break
    ISSUE=$(get_issue_number "$item")
    if has_refine_skip_label "$item"; then continue; fi
    if is_issue_running "$ISSUE"; then continue; fi
    if [ "$REFINE_RUNNING" -ge "$REFINE_WIP_LIMIT" ]; then break; fi

    # Check for spec-pending-review items with new human comments (re-run refinement)
    ITEM_LABELS=$(echo "$item" | jq -r '.labels[]?' 2>/dev/null)
    if echo "$ITEM_LABELS" | grep -qi "spec-pending-review"; then
      HAS_NEW=$(has_new_comment_after_report "$ISSUE" "Posted by MarketHawk Refinement Pipeline")
      if [ "$HAS_NEW" = "yes" ]; then
        gh issue edit "$ISSUE" --remove-label "spec-pending-review" 2>/dev/null || true
        dispatch "Refine issue #${ISSUE}"
        DISPATCHED="Refine issue #${ISSUE}"
        REFINE_RUNNING=$((REFINE_RUNNING + 1))
      fi
      continue
    fi

    dispatch "Refine issue #${ISSUE}"
    DISPATCHED="Refine issue #${ISSUE}"
    REFINE_RUNNING=$((REFINE_RUNNING + 1))
  done < <(echo "$BACKLOG" | jq -c '.[]')

  # --- Priority 0.5: Refined items (plan generation) ---
  while IFS= read -r item; do
    [ -n "$DISPATCHED" ] && break
    ISSUE=$(get_issue_number "$item")
    if has_skip_label "$item"; then continue; fi
    if is_issue_running "$ISSUE"; then continue; fi
    if [ "$REFINE_RUNNING" -ge "$REFINE_WIP_LIMIT" ]; then break; fi

    dispatch "Plan issue #${ISSUE}"
    DISPATCHED="Plan issue #${ISSUE}"
    REFINE_RUNNING=$((REFINE_RUNNING + 1))
  done < <(echo "$REFINED" | jq -c '.[]')
```

- [ ] **Step 5: Update the log line to include refinement counts**

Replace the log lines at the end of the loop (lines 293-297):

```bash
  if [ -n "$DISPATCHED" ]; then
    echo "[$(date -u +%FT%TZ)] backlog=${BACKLOG_COUNT} refined=${REFINED_COUNT} in_progress=${IN_PROGRESS_COUNT}/${MAX_IN_PROGRESS} in_review=${IN_REVIEW_COUNT}/${MAX_IN_REVIEW} refine_running=${REFINE_RUNNING}/${REFINE_WIP_LIMIT} dispatched=\"${DISPATCHED}\""
  else
    echo "[$(date -u +%FT%TZ)] backlog=${BACKLOG_COUNT} refined=${REFINED_COUNT} in_progress=${IN_PROGRESS_COUNT}/${MAX_IN_PROGRESS} in_review=${IN_REVIEW_COUNT}/${MAX_IN_REVIEW} refine_running=${REFINE_RUNNING}/${REFINE_WIP_LIMIT} skip=nothing_to_do"
  fi
```

- [ ] **Step 6: Commit**

```bash
git add dark-factory/scheduler.sh
git commit -m "feat(refinement): add Backlog and Refined tiers to scheduler waterfall (issue #52)

Backlog items dispatch 'Refine issue #N' for spec generation.
Refined items dispatch 'Plan issue #N' for implementation planning.
Separate WIP limit for refinement containers (default 2).
Detects human comments on spec-pending-review items for re-runs."
```

---

### Task 6: Update Dockerfile to Copy Skill Files

The dark factory Dockerfile needs to copy the refinement skill files into the container image so the Archon commands can read them.

**Files:**
- Modify: `dark-factory/Dockerfile:66-71`

- [ ] **Step 1: Add COPY for refinement skill files**

In `dark-factory/Dockerfile`, after line 69 (`COPY seed_preview.sql /opt/dark-factory/seed_preview.sql`), add:

```dockerfile
COPY ../claude/skills/refinement/ /opt/refinement-skills/
```

Wait — the Dockerfile build context is `./dark-factory`, so it can't reach `../.claude/`. We need to either change the build context or copy the files into `dark-factory/` during build. The cleaner approach: add a `pre-build` step in docker-compose that copies, or change the build context.

Actually, looking at the existing Dockerfile, the build context is `./dark-factory`. The simplest approach is to copy the skill files into the dark factory directory as part of the build context. But that creates duplication.

Better approach: change the Dockerfile build context to the project root and adjust paths:

In `docker-compose.yml`, the `dark-factory` service has:
```yaml
    build:
      context: ./dark-factory
      dockerfile: Dockerfile
```

Change to:
```yaml
    build:
      context: .
      dockerfile: dark-factory/Dockerfile
```

Then in the Dockerfile, update all COPY commands to use `dark-factory/` prefix, and add the skill files copy.

Replace lines 67-70 of `dark-factory/Dockerfile`:

```dockerfile
COPY dark-factory/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY dark-factory/scheduler.sh /opt/dark-factory/scheduler.sh
COPY dark-factory/docker-compose.preview.yml /opt/dark-factory/docker-compose.preview.yml
COPY dark-factory/seed_preview.sql /opt/dark-factory/seed_preview.sql
COPY .claude/skills/refinement/ /opt/refinement-skills/
RUN chmod +x /usr/local/bin/entrypoint.sh /opt/dark-factory/scheduler.sh
```

And update both services in `docker-compose.yml`:

For `dark-factory`:
```yaml
  dark-factory:
    build:
      context: .
      dockerfile: dark-factory/Dockerfile
```

For `backlog-scheduler`:
```yaml
  backlog-scheduler:
    build:
      context: .
      dockerfile: dark-factory/Dockerfile
```

- [ ] **Step 2: Update the refine and plan Archon commands to reference the correct path**

The commands reference `.claude/skills/refinement/*.md` — inside the container these will be at `/opt/refinement-skills/`. Update the paths in `.archon/commands/dark-factory-refine.md`:

Replace:
```
4. Read `.claude/skills/refinement/orchestrator-prompt.md` for your process instructions
5. Read `.claude/skills/refinement/product-owner-prompt.md` — you will pass this to subagents
6. Read `.claude/skills/refinement/config.yaml` for pipeline configuration
```

with:
```
4. Read `/opt/refinement-skills/orchestrator-prompt.md` for your process instructions
5. Read `/opt/refinement-skills/product-owner-prompt.md` — you will pass this to subagents
6. Read `/opt/refinement-skills/config.yaml` for pipeline configuration
```

And in `.archon/commands/dark-factory-plan.md`, replace:
```
3. Read `.claude/skills/refinement/architect-prompt.md` — you will pass this to the review subagent
```

with:
```
3. Read `/opt/refinement-skills/architect-prompt.md` — you will pass this to the review subagent
```

- [ ] **Step 3: Commit**

```bash
git add dark-factory/Dockerfile docker-compose.yml .archon/commands/dark-factory-refine.md .archon/commands/dark-factory-plan.md
git commit -m "feat(refinement): update Dockerfile and build context for skill files (issue #52)

Change build context from ./dark-factory to project root so we can COPY
.claude/skills/refinement/ into the image at /opt/refinement-skills/.
Update Archon command paths to match container layout."
```

---

### Task 7: Smoke Test — Manual Refine Invocation

Verify the full pipeline works end-to-end by manually refining a test issue.

**Files:**
- No new files

- [ ] **Step 1: Rebuild the dark factory image**

```bash
docker compose --profile factory build dark-factory
```

Expected: Build completes without errors. The output should show the COPY step for refinement skills.

- [ ] **Step 2: Create a test issue (or use an existing Backlog item)**

```bash
gh issue create --repo omniscient/markethawk \
  --title "Test: auto-refinement smoke test" \
  --body "Add a simple health check endpoint that returns the current server timestamp and version number. This should be accessible without authentication."
```

Note the issue number.

- [ ] **Step 3: Run the refine intent manually**

```bash
docker compose --profile factory run --rm dark-factory "Refine issue #<NUMBER>"
```

Expected:
- Container starts and clones the repo
- Orchestrator reads issue and starts asking questions
- Product-owner subagent answers each question
- Spec is written and committed
- Issue gets a "Refinement Pipeline — Spec Generated" comment
- Issue gets `spec-pending-review` label

- [ ] **Step 4: Verify the outputs**

```bash
# Check the label was added
gh issue view <NUMBER> --json labels --jq '.labels[].name'
# Expected: spec-pending-review

# Check the comment was posted
gh issue view <NUMBER> --json comments --jq '.comments[-1].body' | head -20
# Expected: starts with "## Refinement Pipeline — Spec Generated"

# Check the branch exists
git fetch origin
git branch -r | grep "refine/issue-<NUMBER>"
# Expected: shows the refine branch
```

- [ ] **Step 5: Test the plan intent**

Simulate approval by moving the issue to Refined:
```bash
# Move to Refined on the board
ITEM_ID=$(gh project item-list 1 --owner omniscient --format json --limit 200 \
  | jq -r ".items[] | select(.content.number == <NUMBER> and .content.type == \"Issue\") | .id")
gh project item-edit --project-id PVT_kwHOAAFds84BWh4w --id "$ITEM_ID" \
  --field-id PVTSSF_lAHOAAFds84BWh4wzhR1VaA \
  --single-select-option-id 0c79ebe5

# Run the plan intent
docker compose --profile factory run --rm dark-factory "Plan issue #<NUMBER>"
```

Expected:
- Orchestrator reads the spec
- Plan is written following TDD conventions
- Architect subagent reviews and approves
- Issue moves to Ready
- Comment posted with plan summary

- [ ] **Step 6: Clean up test issue**

```bash
gh issue close <NUMBER> --comment "Smoke test complete — closing."
```

- [ ] **Step 7: Commit any fixes discovered during smoke test**

If the smoke test revealed issues, fix them and commit:

```bash
git add -A
git commit -m "fix(refinement): address issues found during smoke test (issue #52)"
```
