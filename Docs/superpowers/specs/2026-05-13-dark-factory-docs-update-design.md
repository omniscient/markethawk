# Dark Factory — Project Documentation Updates

**Date:** 2026-05-13
**Status:** Pending Review
**Scope:** `.archon/commands/dark-factory-implement.md` — new Phase 4 DOCUMENT step

## Problem

The Dark Factory implements features autonomously, but it never updates the project's structural documentation. After a feature lands, files like `ARCHITECTURE.md` and `PROJECT_STRUCTURE.md` silently drift from reality: new models appear without a row in the Database Models table, new routers ship without an entry in the Routers table, and new environment variables go undocumented. Reviewers and future agents read stale docs.

## Requirements

1. After every successful implementation (new and continue intents), the pipeline must update all documentation files affected by the committed code changes.
2. Documentation changes must be in a separate `docs:` commit immediately following the `feat:` commit — not mixed into the feature commit.
3. The set of files to update must be determined from the actual git diff, not from memory or planning artifacts alone.
4. The agent authors the documentation content; it does not regenerate or overwrite entire files.
5. Only files explicitly listed in the classification mapping below are candidates for update. No free-form doc edits beyond those targets.
6. `Docs/database-schema.md` is auto-generated — it must never be edited by this step.

## Architecture

### Change Classification Mapping

After Phase 3 completes, read the file list from `$ARTIFACTS_DIR/implementation.md` (written by Phase 3's checkpoint). This is the primary input — it already enumerates every file created or modified during the TDD loop across all commits. As a cross-check, `git diff main...HEAD --name-only` gives the same set for new intents; for continue intents it covers the full branch diff, which is also correct because docs should reflect the final state of the feature.

Classify each path against these rules to produce a list of `(doc_file, section)` pairs:

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
| `CLAUDE.md`-affecting changes (new port, new command, new pattern) | `CLAUDE.md` | Relevant section |

Rules:
- If a path matches no pattern, skip it.
- If a file is modified but nothing was added or removed (e.g., only an existing model's fields changed), still read the current doc row and update it if the description is now inaccurate.
- If a file was deleted, remove the corresponding doc row.
- `CLAUDE.md` is only touched if the change adds/removes a developer-facing command, port, or architectural pattern described there. This is rare and requires explicit judgment.

### New Phase 4 in dark-factory-implement.md

Insert between the current Phase 3 (IMPLEMENT) and Phase 4 (REPORT):

```
## Phase 4: DOCUMENT

1. Read the file list from $ARTIFACTS_DIR/implementation.md (all files created/modified in Phase 3).
   Cross-check: git diff main...HEAD --name-only for completeness.
2. Classify each path against the mapping above to produce the list of (doc_file, section) pairs to update.
3. If no pairs matched, skip this phase entirely (no docs commit needed).
4. For each (doc_file, section) pair:
   a. Read the current section in full
   b. Read the changed source file(s) that triggered this pair
   c. Write the updated section content: add a new row, update an existing row, or remove a deleted entry
5. Commit all doc changes: git commit -m "docs: update architecture map for <feature-slug>"

### PHASE_4_CHECKPOINT
- [ ] git diff HEAD~1 HEAD --name-only run and classified
- [ ] All matched doc sections updated
- [ ] docs: commit created (or phase explicitly skipped — no matches)
```

### Hybrid Detection Rationale

The git diff provides a deterministic, auditable input: the agent cannot misremember which files were touched. The LLM then authors the actual doc row content (description text, type annotations, purpose summary) from the changed source file — something a pure path classifier cannot do. Together these produce correct, focused updates with no hallucinated entries.

## Alternatives Considered

### A: Update docs in the same feat commit
Simpler — no second commit. Rejected because it mixes structural doc changes with code changes, making `git blame` and `git revert` harder. PR reviewers cannot skip or focus on docs separately.

### B: Run doc update inside the validate step
`dark-factory-validate.md` is a runtime check against the preview stack (curl tests, pytest, tsc). Rejected because docs are static and should be committed before validation, not patched as a side effect of endpoint tests.

### C: Full-file regeneration
Regenerate ARCHITECTURE.md from scratch from the codebase on every run. Rejected because the existing docs contain prose, diagrams, and context that cannot be reconstructed from code alone. Row-level updates are safer and cheaper.

## Open Questions

- Should the `docs:` commit be squashed with the `feat:` commit before merge, or kept separate? This is a merge strategy preference — the pipeline does not enforce either. Leave for the human reviewer.
- Should PROJECT_STRUCTURE.md entries include inline comments (matching the existing annotation style)? Yes — read surrounding entries and match the style.

## Assumptions

- `implementation.md` (written at the end of Phase 3) is the primary input for the changed-file list. The git diff (`main...HEAD`) is a cross-check, not the authoritative source, because Phase 3 may produce multiple commits and `HEAD~1` would only capture the last one.
- `git diff main...HEAD --name-only` is used as the cross-check. This assumes the feature branch diverged from `main`; for branches diverged from another base, adjust accordingly.
- Both new and continue intents run Phase 4. On continue, the diff reflects only the changes in the most recent feat commit on the branch, which is the correct scope.
