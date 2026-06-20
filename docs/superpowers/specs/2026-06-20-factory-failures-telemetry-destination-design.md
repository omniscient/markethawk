# factory-failures.jsonl — Telemetry Destination Fix

**Date:** 2026-06-20  
**Status:** Spec complete — pending implementation plan  
**Author:** Brainstormed with Claude (Opus 4.8)  
**Issue:** [#521](https://github.com/omniscient/markethawk/issues/521)

## Problem

`dark-factory/entrypoint.sh`'s `promote_failure()` function appends a postmortem JSON line
to `dark-factory/evals/factory-failures.jsonl` and commits it to whatever branch the factory
is currently running on. On feature branches (the typical case), this produces an
out-of-scope (OOS) change that the scope-enforcement gate detects and excises. The excision
works, but it creates noise and has now fired twice (#431 from #370, #521 from #391),
signalling the inline-excision workaround isn't sufficient — the root cause must be fixed.

## Goal

Redirect postmortem writes to the factory container's per-run `ARTIFACTS_DIR` and drop the
`git add`/`commit`/`push` block. The file `dark-factory/evals/factory-failures.jsonl` is
frozen as a historical snapshot and added to `.gitignore` so no future write can re-enter the
working tree.

## Requirements

1. `promote_failure()` writes the JSONL entry to `${ARTIFACTS_DIR}/factory-failures.jsonl`
   rather than `${CLONE_DIR}/dark-factory/evals/factory-failures.jsonl`.
2. The `git add`/`commit`/`push` block in `promote_failure()` is removed entirely.
3. `dark-factory/evals/factory-failures.jsonl` is added to `.gitignore`.
4. The existing 11 entries in `dark-factory/evals/factory-failures.jsonl` are left in place
   as a frozen historical record (no `git rm`). The `.gitignore` entry ensures no future
   modifications to this file can be committed.
5. Feature branches must never see a `dark-factory/evals/factory-failures.jsonl` change from
   a factory run after this fix.

## Non-Goals (v1)

- Aggregating or analyzing the ARTIFACTS_DIR-resident postmortem files across runs.
- Building a structured failure dashboard or report from the corpus.
- Moving or deleting the 11 historical entries already on `main`.

## Architecture / Approach

**Single change to `entrypoint.sh` (lines ~233-250) and one `.gitignore` entry.**

Current `promote_failure()` (simplified):
```bash
local JSONL_PATH="${CLONE_DIR}/dark-factory/evals/factory-failures.jsonl"
if [ -d "${CLONE_DIR}" ] && [ -f "$JSONL_PATH" ]; then
  printf '{"issue":...}\n' ... >> "$JSONL_PATH" 2>/dev/null || true
  (cd "${CLONE_DIR}" && git add dark-factory/evals/factory-failures.jsonl \
    && git commit -m "eval: record factory failure for issue #${ISSUE_NUM}" \
    && git push origin "$(git branch --show-current)" 2>/dev/null) 2>/dev/null || true
fi
```

After fix:
```bash
local JSONL_PATH="${ARTIFACTS_DIR}/factory-failures.jsonl"
if [ -n "${ARTIFACTS_DIR:-}" ]; then
  printf '{"issue":...}\n' ... >> "$JSONL_PATH" 2>/dev/null || true
  # no git add/commit/push — writes stay in ARTIFACTS_DIR only
fi
```

The guard changes from testing whether the repo path and file exist (`[ -d "${CLONE_DIR}" ] && [ -f "$JSONL_PATH" ]`) to testing whether `ARTIFACTS_DIR` is set — which is always true when the factory runs normally (set at line 92 of entrypoint.sh). The JSONL format and fields are unchanged.

`.gitignore` entry to add:
```
dark-factory/evals/factory-failures.jsonl
```

## Alternatives Considered

### A — Commit to `main` via a separate git worktree

Keep the postmortem data in git but target `main` instead of the feature branch: create a
temporary worktree at `origin/main`, append there, commit, push to `main`, remove worktree.

**Rejected**: Preserving the corpus in git is not worth the complexity — a cross-branch
write, potential push races, and a new push-to-main permission surface — when there is no
active downstream consumer of the data. YAGNI; if a future consumer is built, the destination
can be reconsidered with a real requirement driving it.

### B — Remove the file from git (`git rm`)

Delete `dark-factory/evals/factory-failures.jsonl` from the tree and gitignore it.

**Rejected**: The 11 existing entries are legitimate historical data that landed on `main`
properly. Removing the file gains nothing — `.gitignore` already prevents future commits.
Freezing in place (chosen approach) avoids an unnecessary destructive operation.

## Open Questions

None blocking this change.

## Assumptions

- `ARTIFACTS_DIR` is always set by the time `promote_failure()` is called (it is exported at
  line 92 of entrypoint.sh and `mkdir -p`'d immediately, before any downstream code runs).
- Branch protection on `main` does not need to be considered; the chosen approach (ARTIFACTS_DIR)
  performs no git writes at all.
- The 11 historical entries in `dark-factory/evals/factory-failures.jsonl` have no active
  readers or downstream consumers (confirmed by codebase search: the file path appears only in
  `entrypoint.sh` as a write target, nowhere else).
