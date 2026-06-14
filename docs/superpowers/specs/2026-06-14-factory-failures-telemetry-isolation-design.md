# Dark Factory — Isolate Failure Telemetry from Feature Branches

**Date:** 2026-06-14  
**Status:** Draft  
**Issue:** #431

## Problem

`run_post_mortem()` in `dark-factory/entrypoint.sh` appends a JSONL record to
`dark-factory/evals/factory-failures.jsonl` and then commits and pushes to
**whatever branch the factory is currently on**. Since factory runs almost always
operate on feature/implementation branches, failure records land on those branches
rather than on `main`. Scope enforcement excises the file from each feature-branch
diff and files a `scope-spillover` ticket — but the leak recurs on every subsequent
factory run. This has been re-observed on issues #292, #360, #370, and #403.

## Requirements

1. A factory run that fails on a feature/implementation branch must not commit or
   push `factory-failures.jsonl` to that branch.
2. Failure telemetry must still be captured in the eval corpus on `main` (intent
   preserved — records do not vanish).
3. Subsequent feature-branch runs must not generate a `scope-spillover` ticket for
   `factory-failures.jsonl`.
4. No change to the schema or content of the JSONL records themselves.
5. No removal of already-committed stale records from `main`'s history (that is
   scope of #507).

## Approach: Temporary Git Worktree on `origin/main`

Instead of appending to the file inside `CLONE_DIR` (the feature-branch working
tree), write the JSONL record via a short-lived detached worktree rooted at a fresh
copy of `origin/main`. The worktree never touches the feature-branch index or
working tree, so the file can never appear in the feature-branch diff or trigger
scope-spillover.

Implementation sketch (replaces the existing append+commit block inside
`run_post_mortem()`):

```bash
# Write failure telemetry to main, not the feature branch
local JSONL_PATH="dark-factory/evals/factory-failures.jsonl"
local excerpt
excerpt=$(echo "$post_mortem_text" | head -c 500 | tr '\n' ' ')
local record
record=$(printf '{"issue":%s,"title":"%s","phase":"%s","exit_code":%s,"postmortem":"%s","promoted_at":"%s"}\n' \
  "${ISSUE_NUM}" \
  "$(gh issue view "${ISSUE_NUM}" --repo "omniscient/markethawk" --json title --jq '.title' 2>/dev/null | sed 's/"/\\"/g' || echo "unknown")" \
  "${INTENT:-fix}" \
  "${exit_code}" \
  "$(echo "$excerpt" | sed 's/"/\\"/g')" \
  "$PROMOTED_AT")

(
  # Fetch the latest main so the worktree is as fresh as possible.
  git -C "${CLONE_DIR}" fetch origin main 2>/dev/null || true

  WT=$(mktemp -d)
  git -C "${CLONE_DIR}" worktree add --detach "$WT" origin/main 2>/dev/null

  echo "$record" >> "${WT}/${JSONL_PATH}"

  git -C "$WT" add "${JSONL_PATH}"
  git -C "$WT" commit -m "eval: record factory failure for issue #${ISSUE_NUM}"
  git -C "$WT" push origin HEAD:main 2>/dev/null

  git -C "${CLONE_DIR}" worktree remove --force "$WT" 2>/dev/null || true
  rm -rf "$WT" 2>/dev/null || true
) 2>/dev/null || true
```

The entire block is wrapped in `|| true`, consistent with the existing telemetry
code. A push failure (e.g. non-fast-forward due to a concurrent update) silently
drops the record — the same acceptable loss mode as today.

## Alternatives Considered

### A — Gate the commit/push on `main`

Check `git branch --show-current`. If on `main`, do the existing append + commit +
push. If not, skip entirely.

**Rejected:** Almost all factory failures happen on feature branches, never on
`main`. Gating on `main` would lose effectively all telemetry and violate AC2.

### C — Write to `$ARTIFACTS_DIR`, aggregate later

Write the JSON record to `$ARTIFACTS_DIR/factory-failure-record.jsonl`
(container-local, ephemeral). A separate job aggregates onto `main` later.

**Rejected:** No aggregation mechanism exists. The separate job would itself
require implementing the worktree approach above, adding scope. Artifacts are
container-local and ephemeral; records do not land in the shared corpus. Violates
AC2 without additional work.

## Implementation Notes

### Concurrency and races

`FACTORY_WIP_LIMIT=1` means only one factory container runs at a time under normal
conditions, so concurrent pushes to `main` are rare. On the rare concurrent push
(two containers failing near-simultaneously), one push will be rejected as
non-fast-forward. That record is silently dropped — acceptable given the
best-effort posture of the entire telemetry path.

No `--force-with-lease` or other force flags are used. Force-push semantics near
`main` (the default branch all PRs merge into) carry too much risk of clobbering
commits, even with a lease. The `|| true` swallow is the correct failure mode.

### Stale `origin/main` at run start

The factory clones at startup, which may be many minutes before `run_post_mortem`
fires. A `git fetch origin main` immediately before creating the worktree refreshes
`origin/main` to the latest tip, maximizing the chance the append-and-push
fast-forwards cleanly. This fetch is also best-effort; if it fails, the worktree
falls back to the clone-time `origin/main` ref.

### Deployment

The entrypoint is baked into the dark-factory image. After merging:

```bash
docker compose --profile factory build dark-factory
docker compose --profile factory up -d --force-recreate dark-factory
```

## Assumptions

- The factory's `GH_TOKEN` has permission to push directly to `main` (the current
  code already does `git push origin <current-branch>` with the same credentials).
- `main` is not protected against direct pushes for the factory user. If it were,
  the entire telemetry flow would silently drop (already the behavior for any push
  failure); this change does not make that situation worse.
- `git worktree add --detach` is available in the dark-factory image's git version
  (git ≥ 2.5, widely available).

## Open Questions (non-blocking)

- Should a failed worktree push emit a stderr warning to the run log (rather than
  being silently swallowed), so operators can tell if telemetry is consistently
  failing? This could be added with a simple `|| echo "WARNING: eval push failed"`
  before the outer `|| true`, but would add noise for the common/benign
  non-fast-forward case.
