# Dark Factory — Project Documentation Updates — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Phase 4 DOCUMENT step to `.archon/commands/dark-factory-implement.md` so that after every successful feature implementation the pipeline automatically updates `ARCHITECTURE.md`, `PROJECT_STRUCTURE.md`, `ENV_VARIABLES.md`, and `CLAUDE.md` to reflect the committed changes, then commits those doc updates separately from the feature code.

**Architecture:** Single-file edit to `.archon/commands/dark-factory-implement.md`. The new Phase 4 DOCUMENT is inserted between Phase 3 IMPLEMENT and the existing Phase 4 REPORT (which becomes Phase 5). No backend or frontend code changes; no migrations; no tests beyond grep/file-structure verification.

**Tech Stack:** Markdown (command file), Bash snippets embedded in the command document.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `.archon/commands/dark-factory-implement.md` | Modify | Insert Phase 4 DOCUMENT section; renumber old Phase 4 REPORT → Phase 5 |

---

## Task 1: Insert Phase 4 DOCUMENT and renumber Phase 5 REPORT

**Files:**
- Modify: `.archon/commands/dark-factory-implement.md`

> **Note on `implementation.md` timing:** The PHASE_3_CHECKPOINT already requires writing `$ARTIFACTS_DIR/implementation.md`. Phase 4 DOCUMENT reads this file as its primary input. Phase 5 REPORT (formerly Phase 4) may overwrite it with a final summary — that is fine because Phase 4 reads before Phase 5 writes. No structural change to Phase 3 or Phase 5 is needed.

### TDD Steps

- [ ] **Step 1: Write failing test — verify Phase 4 DOCUMENT does not yet exist**

```bash
grep -c "Phase 4: DOCUMENT" .archon/commands/dark-factory-implement.md
```

Expected: `grep` returns exit code 1 and prints `0`. This confirms the section is absent before the change.

- [ ] **Step 2: Verify the test fails**

Confirm the command exits non-zero (no match). Proceed.

- [ ] **Step 3: Read the target file before editing**

Use the Read tool on `.archon/commands/dark-factory-implement.md` to confirm its exact current contents (especially the whitespace and newlines at the end of the file before constructing the `old_string`).

- [ ] **Step 4: Implement — edit `.archon/commands/dark-factory-implement.md`**

Use the Edit tool with the following exact strings.

**`old_string`** (the exact text currently at the end of the file — 7 lines, no trailing newline after the last bullet):

```
## Phase 4: REPORT

Write a summary of what was implemented to `$ARTIFACTS_DIR/implementation.md`:
- Files created/modified
- Tests added
- Migrations created (if any)
- Any decisions or trade-offs made
```

**`new_string`** (Phase 4 DOCUMENT inserted before, old block renamed Phase 5):

```
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
```

- [ ] **Step 5: Verify Phase 4 DOCUMENT is present**

```bash
grep -c "Phase 4: DOCUMENT" .archon/commands/dark-factory-implement.md
```

Expected output: `1`

- [ ] **Step 6: Verify Phase 5 REPORT exists (old Phase 4 renamed)**

```bash
grep -c "Phase 5: REPORT" .archon/commands/dark-factory-implement.md
```

Expected output: `1`

- [ ] **Step 7: Verify PHASE_4_CHECKPOINT block is present**

```bash
grep -c "PHASE_4_CHECKPOINT" .archon/commands/dark-factory-implement.md
```

Expected output: `1`

- [ ] **Step 8: Verify the classification table is present**

```bash
grep -c "ARCHITECTURE.md" .archon/commands/dark-factory-implement.md
```

Expected output: `2` or more (the mapping table references `ARCHITECTURE.md` in multiple rows).

- [ ] **Step 9: Commit**

```bash
git add .archon/commands/dark-factory-implement.md
git commit -m "feat(factory): add Phase 4 DOCUMENT step to dark factory implement (issue #46)"
```

Expected: a commit hash is printed confirming the change.

---

## Task 2: Post plan summary to GitHub issue

**Files:** none (GitHub API call only)

- [ ] **Step 1: Post implementation summary to issue #46**

```bash
gh issue comment 46 --body "## Refinement Pipeline — Plan Generated

**Plan:** \`Docs/superpowers/plans/2026-05-14-dark-factory-docs-update.md\`
**Branch:** \`refine/issue-46-dark-factory-shjould-include-project-rel\`
**Tasks:** 2 tasks, 9 steps

### Task Overview
1. Insert Phase 4 DOCUMENT section and renumber Phase 5 REPORT in \`.archon/commands/dark-factory-implement.md\`
2. Post plan summary to GitHub issue

---
*Posted by MarketHawk Refinement Pipeline*"
```

- [ ] **Step 2: Verify the comment was posted**

```bash
gh issue view 46 --comments | tail -20
```

Expected: the last comment body contains "Refinement Pipeline — Plan Generated".
