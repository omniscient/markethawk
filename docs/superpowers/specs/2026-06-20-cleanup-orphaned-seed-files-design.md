# Cleanup: Orphaned Seed Files in dark-factory/seed/seed/

Date: 2026-06-20  
Issue: #518 (scope spillover from #436)

## Overview

A prior factory run (implementing issue #436) died before completing and left untracked duplicate
SQL files in `dark-factory/seed/seed/`. The orphaned directory contains exact copies of the
seed files at `dark-factory/seed/` plus a further-nested `seed/seed/` directory. These files
are never executed (the preview stack only globs `/seed/*.sql` at the root) and should not be
committed.

## Root Cause

`dark-factory/entrypoint.sh` seeds the factory clone via:

```bash
cp -r /opt/dark-factory/seed/ "$CLONE_DIR/dark-factory/seed/"
```

When `$CLONE_DIR/dark-factory/seed/` already exists, `cp -r` with a trailing slash on the
source copies the source directory *into* the existing destination, producing
`$CLONE_DIR/dark-factory/seed/seed/`. In a healthy run these files stay inside the throwaway
clone; the dead run's partial work leaked them back into the working tree of the real repo.

## Requirements

1. Remove `dark-factory/seed/seed/` and all of its contents (the orphaned SQL files and the
   nested `seed/seed/` subdirectory inside it).
2. Do not add a `.gitignore` inside `dark-factory/seed/` — it would mask symptoms rather than
   eliminate the source and risks silently hiding legitimately-tracked files in the future.
3. Do not fix `entrypoint.sh` in this ticket — that is a distinct root-cause hardening concern
   and should be tracked separately.

## Selected Approach

**Simple deletion.** Run `git rm -rf --cached dark-factory/seed/seed/ && rm -rf dark-factory/seed/seed/`
to remove all untracked orphaned files and commit the result. Because these files were never
committed, a plain `rm -rf` is sufficient; `git rm` is used as a guard in case any were staged.

No model changes. No migration. No frontend changes.

## Alternatives Considered

### Add a `.gitignore` entry

Rejected. A `.gitignore` of `seed/` inside `dark-factory/seed/` treats the symptom
(the files appear in `git status`) rather than the cause, and silently swallows future
seed subdirectory files that might legitimately be tracked. The product owner explicitly
ruled this out.

### Fix `entrypoint.sh` to use `cp -rT` (Linux) or `rsync`

Correct root-cause fix but out of scope for this cleanup ticket. The issue frames this as
deleting the untracked duplicates; `entrypoint.sh` hardening is a separate concern. A
follow-up ticket should use `cp -rT "$SRC" "$DEST"` or `rsync -a --delete "$SRC/" "$DEST/"`
to make the copy operation idempotent regardless of whether the destination directory exists.

## Assumptions

- The files in `dark-factory/seed/seed/` are confirmed exact duplicates of `dark-factory/seed/`
  and carry no unique content; verified by `diff` before deletion.
- `docker-compose.preview.yml` only executes `for f in /seed/*.sql` at the mount root, so no
  functional behavior changes from removing the subdirectory.

## Open Questions

- None blocking. The `entrypoint.sh` root-cause fix is advisory; file as a follow-up if recurrence
  is observed.
