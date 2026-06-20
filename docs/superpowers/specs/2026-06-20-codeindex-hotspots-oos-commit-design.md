# Codeindex Hotspots — Stop OOS Commits on Feature Branches

**Date:** 2026-06-20
**Issue:** #561 (scope spillover from #329)
**Status:** Spec

## Problem

The `regen-codeindex` node in `.archon/workflows/archon-dark-factory.yaml` regenerates
`docs/codeindex-hotspots.md` after every `implement` run and commits it to the feature
branch. This file reflects whole-codebase blast scores (line counts + dependency counts
across all files), not just the current issue's changes. Every implement run produces a
spurious commit that changes line counts or scores for files untouched by the issue,
polluting the PR diff and triggering the OOS scope gate — which then has to excise the
file by restoring it to `main`. Issue #329 demonstrated the excision working correctly;
this spec prevents the problem from recurring.

## Requirements

1. `docs/codeindex-hotspots.md` must not be committed to feature branches by the factory.
2. The `regen-codeindex` node's codeindex regen (for MCP freshness) must continue unchanged.
3. `docs/codeindex-hotspots.md` on `main` must be kept up to date after each merge.
4. The hotspot update must be non-blocking: a codeindex failure or push failure must not
   undo a completed merge or fail the close run.

## Approach

Two changes to `.archon/workflows/archon-dark-factory.yaml`:

### Change 1: Remove the git commit from `regen-codeindex`

In the `regen-codeindex` node body, remove the `git add` + `git commit` block:

```bash
# REMOVE these lines:
git add docs/codeindex-hotspots.md 2>/dev/null || true
if ! git diff --staged --quiet 2>/dev/null; then
  git commit -m "chore: update codeindex hotspots (post-implement)"
  echo "codeindex hotspots committed"
else
  echo "codeindex hotspots unchanged — no commit needed"
fi
```

Keep the `codeindex high-blast > docs/codeindex-hotspots.md` generation line. The file is
still written to disk for local/in-run use (cheap to generate, useful if the implement
agent or a validate step reads it). Since the factory never does `git add -A` or
`git add .` (all staging is path-explicit), the unstaged modification will not be picked up
by any subsequent commit in the run.

Update the node's comment to reflect that the hotspot file is generated locally but not
committed; post-merge updates happen in `post-merge-update-codeindex`.

### Change 2: New `post-merge-update-codeindex` node

Add a new DAG node after `close-preview` in the close flow:

```yaml
- id: post-merge-update-codeindex
  bash: |
    if ! command -v codeindex &>/dev/null; then
      echo "WARNING: codeindex not available — skipping post-merge hotspot update"
      exit 0
    fi
    ISSUE=$(jq -r '.resolved_number' "$ARTIFACTS_DIR/issue.json")
    echo "Refreshing codeindex hotspots on main (post-merge for issue #${ISSUE})..."
    git fetch origin main
    git checkout main
    git reset --hard origin/main
    codeindex analyze . 2>/dev/null || echo "WARNING: codeindex analyze failed"
    codeindex symbols . --inline 2>/dev/null || echo "WARNING: codeindex symbols failed"
    mkdir -p docs
    codeindex high-blast 2>/dev/null > docs/codeindex-hotspots.md || true
    git add docs/codeindex-hotspots.md
    if ! git diff --staged --quiet; then
      git commit -m "chore: refresh codeindex hotspots (post-merge #${ISSUE})"
      git push origin main \
        || echo "WARNING: push to main failed — hotspots will be stale until next manual refresh"
    else
      echo "codeindex hotspots unchanged post-merge — no commit needed"
    fi
  depends_on: [close-preview]
  when: "$parse-intent.output.intent == 'close'"
  timeout: 120000
```

Key design decisions:
- `git fetch + checkout main + reset --hard origin/main` — ensures a clean checkout of the
  merged state, not the feature branch, before regenerating
- `codeindex analyze` + `codeindex symbols` — fresh index so `high-blast` scores reflect the
  merged code (not the pre-merge state)
- Non-blocking: codeindex unavailability exits 0 (warning only); push failure also exits 0
  (warning only). The merge and Done-move in `close-preview` have already completed before
  this node runs.
- Idempotent: only commits when `git diff --staged` is non-empty (same check as the removed
  `regen-codeindex` block)

## Alternatives Considered

**Skip generating the file locally in `regen-codeindex` (Option B)**
Not adopted. The file is cheap to generate and useful for local inspection during the run.
The risk of accidental staging is zero because all factory `git add` calls are path-explicit.
Keeping the generation preserves the "on-disk artifact is consistent with the JSON indexes"
invariant noted by the product owner.

**Scheduled nightly refresh via cron**
Not adopted. Adds operational complexity, doesn't match the issue's stated direction of
"running the codeindex update pass only on `main` after merge," and would leave the file
stale for up to 24h.

**Embedding the update inside `close-preview`**
Not adopted. `close-preview` already handles preview teardown, PR merge, board move, and
comment. Adding git/push operations to an already-complex node increases blast radius on a
high-stakes step. An isolated DAG node is cleaner and independently timeout-able.

## Files Changed

| File | Change |
|------|--------|
| `.archon/workflows/archon-dark-factory.yaml` | Remove `git add + git commit` from `regen-codeindex`; add `post-merge-update-codeindex` node; update node comment |

No other files need changes. `dark-factory/tests/test_codeindex_config.sh` is not affected:
it checks for the existence of `regen-codeindex` (still present) and `docs/codeindex-hotspots.md`
(still committed on `main`), but does not assert that `regen-codeindex` commits the file.

## Assumptions

- The factory never runs `git add -A` or `git add .` — only explicit `git add <path>` calls
  (confirmed: only `git add .archon/memory/` in `dark-factory-implement.md`). An unstaged
  `docs/codeindex-hotspots.md` will not be accidentally swept into a feature-branch commit.
- `close-preview` always runs `gh pr merge --merge --delete-branch` before this node fires,
  so `git checkout main && git reset --hard origin/main` will find the merged commit.
- The factory container has push access to `main` (same token used for `close-preview` merge).

## Open Questions

- If `git push origin main` fails in `post-merge-update-codeindex` (e.g. branch protection),
  a subsequent `close` run on the same issue would retry. Is silent staleness acceptable for
  the window between merge and a successful hotspot push, or should the warning be escalated
  to an issue comment? (Non-blocking for this spec.)
