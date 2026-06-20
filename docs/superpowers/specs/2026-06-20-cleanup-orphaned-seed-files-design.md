# Cleanup: Orphaned Seed Files in dark-factory/seed/seed/

Date: 2026-06-20  
Issue: #518 (scope spillover from #436)

## Overview

A prior factory run (implementing issue #436) died before completing and left untracked duplicate
SQL files in `dark-factory/seed/seed/`. The orphaned directory contains exact copies of the
seed files at `dark-factory/seed/` plus a further-nested `seed/seed/seed/` directory. These files
are never executed (the preview stack only globs `/seed/*.sql` at the root) and should not be
committed.

## Scope Boundary

**Files modified by this ticket:**
- `dark-factory/seed/seed/` — deleted (working-tree only; files were never tracked in git)

**Files NOT modified by this ticket:**
- `dark-factory/entrypoint.sh` — mentioned below for root-cause context only; no changes in this ticket
- `docker-compose.preview.yml` — referenced in Assumptions for context only; no changes in this ticket
- No model, migration, or frontend changes

## Root Cause (context only — not fixed here)

`dark-factory/entrypoint.sh` seeds the factory clone at line 443:

```bash
cp -r /opt/dark-factory/seed/ "$CLONE_DIR/dark-factory/seed/"
```

When `$CLONE_DIR/dark-factory/seed/` already exists, `cp -r` with a trailing slash on the
source copies the source directory *into* the existing destination, producing
`$CLONE_DIR/dark-factory/seed/seed/`. In a healthy run these files stay inside the throwaway
clone; the dead run's partial work leaked them back into the working tree of the real repo.

The `entrypoint.sh` fix (`cp -rT` / `rsync`) is the correct root-cause remedy but is **out of
scope here** — it touches `dark-factory/` infrastructure and warrants its own issue and human
review. File a follow-up if recurrence is observed.

## Requirements

1. Delete `dark-factory/seed/seed/` and all of its contents from the local working tree.
2. Do not add a `.gitignore` inside `dark-factory/seed/`.
3. Do not modify `entrypoint.sh` in this ticket.

## Selected Approach

**Working-tree deletion only.** Run `rm -rf dark-factory/seed/seed/` to remove the orphaned
files from the local working tree.

### Expected PR content

The orphaned files were **never committed to git**, so deleting them produces no git-tracked
diff. The resulting PR will contain only this spec documentation file
(`docs/superpowers/specs/2026-06-20-cleanup-orphaned-seed-files-design.md`). This is expected
and correct — the cleanup is real (the junk disappears from `git status`), but untracked files
cannot appear as "deleted" in a PR diff. A "documentation-only PR" is the honest representation
of "delete untracked files."

### Note on autonomous advancement

Because the fix touches `dark-factory/`, it falls within the epic autopilot's hard-exclude
path list and cannot be advanced autonomously. **Human review and merge are required.**

### Test coverage

No test coverage is applicable or necessary for a working-tree deletion of untracked duplicate
files. There is nothing in git to regress against.

## Alternatives Considered

### Add a `.gitignore` entry

Rejected. A `.gitignore` of `seed/` inside `dark-factory/seed/` treats the symptom
(the files appear in `git status`) rather than the cause, and silently swallows future
seed subdirectory files that might legitimately be tracked.

### Fix `entrypoint.sh` to use `cp -rT` (Linux) or `rsync`

Correct root-cause fix but out of scope for this cleanup ticket. A follow-up ticket should
use `cp -rT "$SRC" "$DEST"` or `rsync -a --delete "$SRC/" "$DEST/"` to make the copy
idempotent regardless of whether the destination directory exists.

### Expand scope to include `entrypoint.sh` fix in this PR

Rejected. Folding the entrypoint change here contradicts the prior Q&A scoping decision and
re-introduces the very `dark-factory/` path that the autopilot identified as excluded from
autonomous advancement. Manufacturing a non-empty code diff to satisfy a heuristic is
scope-creep, not a spec improvement.

## Assumptions

- The files in `dark-factory/seed/seed/` are confirmed exact duplicates of `dark-factory/seed/`
  and carry no unique content (verified with `diff`).
- `docker-compose.preview.yml` only executes `for f in /seed/*.sql` at the mount root (confirmed
  in `dark-factory-ops.md` memory), so removal has zero functional impact.

## Open Questions

- None blocking. The `entrypoint.sh` root-cause fix (`cp -r` → `cp -rT`) should be filed as a
  separate follow-up issue to prevent recurrence.
