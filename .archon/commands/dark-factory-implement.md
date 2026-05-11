---
description: Implement a feature or fix from a GitHub issue inside the dark factory
argument-hint: (no arguments - reads issue context from workflow)
---

# Dark Factory — Implement

**Workflow ID**: $WORKFLOW_ID

---

## CRITICAL: Epic Guard

**NEVER implement an epic (issue with the `epic` label) as a monolithic change.** Each sub-issue
gets its own branch, PR, and preview stack. The workflow resolves epics to individual sub-issues
before reaching this command. If the issue context still has the `epic` label, STOP immediately
and exit with an error — the resolution should have happened upstream.

**NEVER work on multiple sub-issues in the same branch.** If the issue body references sibling
sub-issues, ignore them. Focus exclusively on the single resolved issue you were given.

## Phase 1: LOAD

Read the project rules:
- Read `CLAUDE.md` for all development rules, architecture, and validation requirements.
- The issue context has been fetched by the workflow. It is available in the conversation.
- **Check the `intent` field** in the issue context: `"new"` or `"continue"`.

### If intent is "continue"

This is an iteration on existing work. **The latest comments on the issue and PR contain feedback that must drive your changes.** Do NOT re-implement from scratch. Instead:
1. Read the latest issue comments (bottom of the `comments` array) — these are the user's feedback
2. Read `pr_reviews` if present — top-level PR conversation and review summaries
3. Read `pr_inline_comments` if present — these are line-level code review comments with `path` and `line` pointing to exact locations
3. Review what was already implemented on this branch (`git log --oneline main..HEAD`, read changed files)
4. Focus exclusively on addressing the feedback

### If intent is "new"

This is a fresh implementation. Follow the issue description.

## Phase 2: PLAN

Based on the issue description (new) or feedback (continue) and codebase analysis:
1. Identify which files need to change (backend models, routers, services, frontend components, etc.)
2. Determine if database migrations are needed
3. Write a brief plan (10-20 lines) as a checklist in `$ARTIFACTS_DIR/plan.md`

### PHASE_2_CHECKPOINT
- [ ] Plan written to `$ARTIFACTS_DIR/plan.md`
- [ ] All affected files identified

## Phase 3: IMPLEMENT (TDD)

For each change in the plan:

1. **Write the failing test first** — pytest for backend, type-check for frontend
2. **Run the test to confirm it fails** — `cd backend && python -m pytest tests/ -x -v` or `cd frontend && npx tsc --noEmit`
3. **Implement the minimal code to pass** — follow existing patterns in the codebase
4. **Run the test to confirm it passes**
5. **Commit** — small, focused commits with descriptive messages

If the change requires a new SQLAlchemy model:
1. Create the model file in `backend/app/models/`
2. Import it in `backend/app/models/__init__.py`
3. Generate migration: `cd backend && python -m alembic revision --autogenerate -m "description"`
4. Apply migration: `cd backend && python -m alembic upgrade head`

### PHASE_3_CHECKPOINT
- [ ] All tests pass: `cd backend && python -m pytest`
- [ ] Frontend type-checks: `cd frontend && npx tsc --noEmit` (if frontend changed)
- [ ] All changes committed
- [ ] Implementation summary written to `$ARTIFACTS_DIR/implementation.md`

## Phase 4: REPORT

Write a summary of what was implemented to `$ARTIFACTS_DIR/implementation.md`:
- Files created/modified
- Tests added
- Migrations created (if any)
- Any decisions or trade-offs made
