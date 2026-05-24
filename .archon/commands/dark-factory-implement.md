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

### Seed Data Awareness

Before implementing, check if the feature requires data that isn't in the baseline seed modules (`dark-factory/seed/`). The baseline covers: tickers, universes, scanner configs, scanner runs/events, stock aggregates (minute bars), watchlist, and system config.

If the feature touches pages or endpoints that need data not in the baseline:
1. Create `dark-factory/seed/99_feature.sql` with idempotent INSERT statements (`ON CONFLICT DO NOTHING`) for the missing data
2. If that data would benefit future features (not just this one), also add it to a new numbered baseline module (e.g. `05_trades.sql`, `06_journal.sql`) so it persists for future previews
3. Include the seed file(s) in your commits

Tables NOT in baseline that commonly need seed data: `trades`, `trade_executions`, `journal_entries`, `tags`, `trading_strategies`, `news_articles`, `alert_rules`, `futures_aggregates`, `stock_metrics`.

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

## Phase 4: DOCUMENT

1. Read the file list from `$ARTIFACTS_DIR/implementation.md` (all files created/modified in Phase 3).
   Cross-check: `git diff main...HEAD --name-only` for completeness.
2. Classify each path against this mapping to produce the list of `(doc_file, section)` pairs to update:

   | Changed file pattern | Documentation target | Section |
   |---|---|---|
   | `backend/app/models/*.py` | `ARCHITECTURE.md` | Database Models table |
   | `backend/app/models/*.py` | `PROJECT_STRUCTURE.md` | `models/` directory entry |
   | `backend/app/routers/*.py` | `ARCHITECTURE.md` | Routers table |
   | `backend/app/routers/*.py` | `PROJECT_STRUCTURE.md` | `routers/` directory entry |
   | `backend/app/services/*.py` | `ARCHITECTURE.md` | Services table |
   | `backend/app/services/*.py` | `PROJECT_STRUCTURE.md` | `services/` directory entry |
   | `frontend/src/pages/*.tsx` | `ARCHITECTURE.md` | Pages table |
   | `.env.example` | `ENV_VARIABLES.md` | Relevant section |
   | `docker-compose.yml` (new service added/removed) | `ARCHITECTURE.md` | Service Topology section |
   | `CLAUDE.md`-affecting changes (new port, command, pattern) | `CLAUDE.md` | Relevant section |

   Rules:
   - If a path matches no pattern, skip it.
   - If a file was modified but nothing added/removed (e.g. only existing model fields changed), still read the current doc row and update it if the description is now inaccurate.
   - If a file was deleted, remove the corresponding doc row.
   - `CLAUDE.md` is only touched if the change adds/removes a developer-facing command, port, or architectural pattern. This is rare and requires explicit judgment.
   - `Docs/database-schema.md` is auto-generated — never edit it.

3. If no pairs matched, skip this phase entirely (no docs commit needed).
4. For each `(doc_file, section)` pair:
   a. Read the current section in full
   b. Read the changed source file(s) that triggered this pair
   c. Write the updated section content: add a new row, update an existing row, or remove a deleted entry. Read surrounding entries and match their style (inline comments, column widths, etc.)
5. Commit all doc changes: `git commit -m "docs: update architecture map for <feature-slug>"` — derive `<feature-slug>` from the branch name (e.g. `feat/issue-12-new-router` → `new-router`).

### PHASE_4_CHECKPOINT
- [ ] `git diff main...HEAD --name-only` run and classified against the mapping table
- [ ] All matched doc sections updated
- [ ] `docs:` commit created (or phase explicitly skipped — no matches)

## Phase 5: REPORT

Write a summary of what was implemented to `$ARTIFACTS_DIR/implementation.md`:
- Files created/modified
- Tests added
- Migrations created (if any)
- Any decisions or trade-offs made
