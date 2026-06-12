# Baseline-Green Gate: Smoke origin/main Before Any Factory Run

**Date:** 2026-06-12
**Issue:** #332
**Status:** Draft

## Problem

The factory pipeline assumes `origin/main` is green. When it isn't — e.g. a
TypeScript compile error merged by another contributor — every implement run fails
at `preview-up` or `validate` for a reason unrelated to the ticket being worked.
The `on_failure` trap moves each ticket to Blocked, the scheduler's per-ticket
retry counter increments, and the circuit breaker eventually trips. Runs burn and
the backlog stalls until a human notices the shared root cause.

**Measured incident:** Issue #250 (Chart.tsx tsc break) blocked the entire backlog
for ~48 hours and tripped circuit breakers across unrelated tickets.

## Requirements

Derived from Q&A with the product owner:

1. A smoke gate runs **before** any per-ticket work begins (before `setup-branch` / archon call).
2. The smoke check executes:
   - `rm -f frontend/tsconfig.app.tsbuildinfo && npx tsc -p tsconfig.app.json --noEmit` on the freshly-cloned `origin/main`
   - `python -c "import app.main"` on the freshly-cloned `origin/main`
3. **Red main → clean halt**: the container exits 0 (not triggering the `on_failure` ERR trap). The in-flight ticket's board status, retry counter, and circuit breaker are untouched.
4. **Red main → single regression ticket**: the gate files or updates exactly one GitHub issue labelled `regression` with an idempotent `<!-- df-main-red -->` marker-comment (same pattern as the cost report).
5. **Red main → sentinel file**: the gate writes `${SCHEDULER_STATE_DIR}/main-is-red` to signal the scheduler.
6. **Green main → lifecycle cleanup**: on the next successful (green) gate pass, before proceeding with normal work, the gate removes the sentinel file and closes any open regression ticket.
7. **Scheduler selective pause**: while `main-is-red` sentinel exists, the scheduler skips Priority 1.5 (deconflict), Priority 2 (Fix/Ready), and Priority 3 (Blocked retries) dispatch. Priority 1 (Close/MERGE), Priority 4 (plan), and Priority 5 (refine) continue unaffected.
8. **Intent selectivity**: the smoke gate applies only to `new`, `continue`, and `resolve` intents. It is skipped entirely for `refine`, `plan`, and `close`.
9. **Regression test** (`dark-factory/tests/test_smoke_gate.sh`): verifies that a simulated red main does not increment any per-ticket retry counter or trip any per-ticket circuit breaker.

## Architecture

### Placement: `entrypoint.sh`, pre-archon

The smoke gate runs in `entrypoint.sh` after dependency installation (`pip install` + `npm install`) but **before** the `archon workflow run` call. At that point the repo is already cloned to a clean `origin/main` checkout — no extra fetch or branch setup needed.

The `on_failure` trap is armed at `entrypoint.sh:283`; a clean `exit 0` from the gate never fires it, satisfying the "no per-ticket retry / circuit break" requirement without any changes to the trap logic itself.

This placement also avoids modifying the Archon DAG or `REQUIRED_OR_JOIN_NODES` in `check_workflow_dag.py`.

### Smoke gate helper: `dark-factory/smoke_gate.sh`

The gate logic is extracted into a sourced helper (pattern: `scheduler.sh`'s `SCHEDULER_SOURCE_ONLY` guard) so it can be unit-tested independently.

```
dark-factory/smoke_gate.sh
```

`entrypoint.sh` sources and calls it:

```bash
# After dep install, before archon:
if [ "$INTENT" = "new" ] || [ "$INTENT" = "continue" ] || [ "$INTENT" = "resolve" ]; then
  source /opt/dark-factory/smoke_gate.sh
  run_smoke_gate   # exits 0 on red; returns 0 on green (proceed)
fi
```

The helper defines:
- `run_smoke_gate` — main entry point; returns 0 on green, exits 0 on red
- `_smoke_check_main` — runs the two checks; returns 0 on pass, non-zero on fail
- `_smoke_on_red` — writes sentinel + files/updates regression ticket + exits 0
- `_smoke_on_green` — removes sentinel (if present) + closes regression ticket (if open)

### Regression ticket pattern

```
SMOKE_MARKER="<!-- df-main-red -->"
```

On red: `post_or_update_comment` (already defined in `entrypoint.sh`) creates or
updates the regression issue body with the `<!-- df-main-red -->` marker. The issue
is created with `gh issue create --label regression --title "main is red"` on first
occurrence, or the existing open ticket is updated on subsequent reds. The issue
number is written to `${SCHEDULER_STATE_DIR}/main-is-red-issue` alongside the
sentinel so the green-path cleanup can close it without an API search.

On green: `gh issue close <number>` on the stored issue, then `rm -f` both files.

### Scheduler selective pause

At the top of each dispatch loop iteration in `scheduler.sh` (before Priority 1.5),
add:

```bash
MAIN_IS_RED=false
[ -f "${SCHEDULER_STATE_DIR}/main-is-red" ] && MAIN_IS_RED=true
```

Gate Priority 1.5, 2, and 3 loops:

```bash
# Priority 1.5: deconflict
if [ "$MAIN_IS_RED" = "true" ]; then
  echo "[$(date -u +%FT%TZ)] main_red_gate=skip_deconflict"
else
  ...
fi

# Priority 2: Ready/Fix
if [ "$MAIN_IS_RED" = "true" ]; then
  echo "[$(date -u +%FT%TZ)] main_red_gate=skip_implement"
else
  ...
fi

# Priority 3: Blocked retry
if [ "$MAIN_IS_RED" = "true" ]; then
  echo "[$(date -u +%FT%TZ)] main_red_gate=skip_blocked_retry"
else
  ...
fi
```

Priority 1 (Close), Priority 4 (plan), and Priority 5 (refine) are unchanged —
they continue even while main is red. This keeps the pipeline flowing: specs and
plans accumulate, and already-approved PRs (including the fix for main) can merge.

The `MAIN_IS_RED` check is a local file read — free, survives rate-limit exhaustion.

### Regression test: `dark-factory/tests/test_smoke_gate.sh`

Structure mirrors `test_159_regression.sh` (source helper, stub external commands, assert).

**Phase 1 — Red main:**
- Stub `tsc` to return exit 1
- Call `run_smoke_gate` (INTENT=new)
- Assert: sentinel file created ✓
- Assert: `gh issue create` called with `regression` label ✓
- Assert: exit code from gate = 0 ✓ (no per-ticket failure)
- Assert: `trip_to_blocked` / `increment_retry` / `set_board_status Blocked` / `needs-discussion` label NOT called for any ticket (grep stub log, count == 0)
- Assert: idempotency — running the gate twice still results in ONE `gh issue create` and ONE update call, not two creates

**Phase 2 — Green main after red:**
- Sentinel file present (from phase 1)
- Stub `tsc` to return exit 0, `python -c "import app.main"` to return exit 0
- Call `run_smoke_gate` (INTENT=new)
- Assert: sentinel file removed ✓
- Assert: `gh issue close <N>` called ✓
- Assert: returns 0 (proceed) ✓

**Phase 3 — Intent guard:**
- Call `run_smoke_gate` (INTENT=refine or plan or close)
- Assert: neither `tsc` nor `python -c "import app.main"` called
- Assert: no sentinel or ticket activity

## Changes

1. **`dark-factory/smoke_gate.sh`** (new file): `run_smoke_gate` + helpers. Sourced by `entrypoint.sh`. Has a `SMOKE_GATE_SOURCE_ONLY` early-return guard for testing.

2. **`dark-factory/entrypoint.sh`**: Source and call `smoke_gate.sh` for `new`/`continue`/`resolve` after dep install, before `archon workflow run`. `post_or_update_comment` is already defined before the archon call so it's in scope.

3. **`dark-factory/scheduler.sh`**: Add `MAIN_IS_RED` read at loop top; gate Priority 1.5, 2, 3 loops; log `main_red=true/false` in the per-cycle summary line.

4. **`docker-compose.yml`**: Add `scheduler_state:/var/lib/dark-factory` to the `dark-factory` service's `volumes` list. Currently only `backlog-scheduler` mounts this volume; dispatched factory run containers do not. Without this mount, the sentinel file written by the factory container would be invisible to the scheduler.

5. **`dark-factory/tests/test_smoke_gate.sh`** (new file): 3-phase shell regression test.

6. **GitHub label**: Create the `regression` label in the `omniscient/markethawk` repo (`gh label create regression --color "e4e669" --description "Broken main / shared infrastructure regression"`) — it does not exist yet.

No changes to `archon-dark-factory.yaml` or `check_workflow_dag.py`.

## Alternatives Considered

### A: Archon DAG node

Adding a `smoke-check` node to `archon-dark-factory.yaml` depending on `fetch-issue` and gating `setup-branch`. Rejected because:
- Modifying the DAG would require OR-join handling on every dependent node — `setup-branch`, `setup-refine-branch`, `setup-branch-resolve` — or adding `smoke-check` to `REQUIRED_OR_JOIN_NODES` (which it isn't: it's a linear gate, not an OR-join).
- A red-main DAG node exit is a node failure, which the Archon harness reports as an error and still potentially triggers `on_failure` trap.
- The production code for dep install, `post_or_update_comment`, and fresh-main checkout already lives in `entrypoint.sh`. The DAG node would have to re-derive this context.

### B: Scheduler-side smoke check (polling)

Having the scheduler run the smoke check itself. Rejected because:
- The scheduler runs outside a git checkout (lines 407-416 all use `--repo` flag); it has no `frontend/` or `backend/` tree to run `tsc`/`import app.main` against.
- Would require duplicating the dep-install setup.
- Adds a Docker-exec or subprocess call every 60s poll cycle.

## Open Questions (non-blocking)

- Should the smoke gate include a `pytest -x --co -q` (fast collection) as a third check? Not in scope for v1; the issue only names tsc and import app.main.
- Should the regression ticket auto-close when the `regression` label is removed by a human? Not specified; v1 only closes on gate's next green pass.

## Assumptions

- [A1] `tsc` is available in the factory container after `npm install` in `frontend/`. **Confirmed** by the existing `deconflict` validation step in `entrypoint.sh` (line 612: `npx tsc --noEmit`).
- [A2] `python -c "import app.main"` is sufficient to detect a broken backend import graph. This matches the issue's stated check and existing `preview-up` health probe pattern.
- [A3] The `scheduler_state` named Docker volume (mounted at `/var/lib/dark-factory` in `backlog-scheduler`) must also be mounted by the `dark-factory` service for the sentinel to be visible to the scheduler. This is a required `docker-compose.yml` change — see Changes item 4.
- [A4] The `regression` label does not yet exist in the `omniscient/markethawk` repo. The smoke gate's first run on a red main must create it (or the implementer creates it once in setup). See Changes item 6.
