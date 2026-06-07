# Scheduler P1.5 Tests — Design Spec

**Date:** 2026-06-07
**Issue:** #215
**Status:** Ready for implementation
**Author:** MarketHawk Refinement Pipeline (brainstorming session)

## Overview

Issue #210 introduced Priority 1.5 (P1.5) in `scheduler.sh` — a proactive conflict-resolution gate that scans In Review PRs for `CONFLICTING` mergeability and dispatches a Deconflict run. Scope spillover filed as #215: two spec-required test scenarios were not added to `dark-factory/tests/test_scheduler.sh` Section K when the P1.5 implementation landed.

This spec covers the two missing tests: **P1.5-1** (retry counter incremented on CONFLICTING dispatch) and **P1.5-5** (circuit-breaker trips to Blocked at MAX_RETRIES).

## Production Code Being Tested

`dark-factory/scheduler.sh`, Priority 1.5 block (~lines 752–785):

```bash
RETRIES=$(get_retry_count "${ISSUE}:resolve")
if [ "$RETRIES" -ge "$MAX_RETRIES" ]; then
    trip_to_blocked "$ISSUE" "resolve" "retry limit of ${MAX_RETRIES} reached for conflict resolution"
    continue
fi
# ...
MERGEABLE=$(check_pr_mergeable "$PR_NUM")
case "$MERGEABLE" in
  CONFLICTING)
    increment_retry "${ISSUE}:resolve" || true   # ← P1.5-1 target
    if dispatch "Deconflict issue #${ISSUE}"; then
      DISPATCHED="Deconflict issue #${ISSUE}"
    fi
    ;;
esac
```

And the MAX_RETRIES guard (above the mergeability check) — that is the **P1.5-5** path.

## Requirements

1. **P1.5-1** — After a CONFLICTING dispatch, `get_retry_count "${ISSUE}:resolve"` must equal `1` in STATE_FILE (increment_retry was called before dispatch in the production code).
2. **P1.5-5** — When the retry counter for `"${ISSUE}:resolve"` is already at `$MAX_RETRIES`, the scheduler calls `trip_to_blocked` and does **not** dispatch. The test must assert:
   - `set_board_status` logged with the Blocked status (`$STATUS_BLOCKED`).
   - No `dispatch` call in STUB_LOG.
   - Retry counter reset to `0` after trip (trip_to_blocked calls `reset_retry`).

## Approach

Add two new test cases — **K8** and **K9** — appended immediately before the Section K cleanup block in `test_scheduler.sh`. Both follow the existing Section K inline-simulation pattern: stub dependencies, drive the logic directly (not via the full scheduler loop), and assert with `assert_eq`.

### K8 — P1.5-1: increment_retry recorded after CONFLICTING dispatch

- Reset STATE_FILE to `{}`.
- Re-stub `check_pr_mergeable` to return `CONFLICTING` and `is_issue_running` to return `1` (false).
- Simulate the CONFLICTING case inline (mirroring lines 776–779 of scheduler.sh), including `increment_retry "${ISSUE}:resolve" || true`.
- Assert `get_retry_count "60:resolve"` equals `1`.

Key naming: issue number is `60` (from `_ITEM_REVIEW_A` defined at line 440), and the resolve phase key is `"${ISSUE}:resolve"` matching the production code.

### K9 — P1.5-5: trip_to_blocked called at MAX_RETRIES

- Reset `> "$STUB_LOG"` and seed STATE_FILE with `{"60:resolve": $MAX_RETRIES}`.
- Simulate the MAX_RETRIES guard inline: read `RETRIES=$(get_retry_count "60:resolve")`, then call `trip_to_blocked "60" "resolve" "retry limit..."` if retries >= MAX_RETRIES.
- Assert three things:
  1. `set_board_status 60 $STATUS_BLOCKED` present in STUB_LOG — confirms board moved to Blocked.
  2. No `dispatch` in STUB_LOG — confirms no Deconflict was queued.
  3. `get_retry_count "60:resolve"` equals `0` — confirms reset_retry was called by trip_to_blocked.

## Alternatives Considered

**K8 as a new standalone assert instead of inline simulation** — Section K uses inline simulation throughout; a separate test helper would be inconsistent and harder to read against the production P1.5 block. Inline simulation chosen.

**Assert on `gh issue edit ... needs-discussion` in K9** — valid but redundant: trip_to_blocked is already fully covered by Section B (lines 56–86). K9 only needs to confirm the P1.5 guard *invokes* trip_to_blocked (via set_board_status) and suppresses dispatch. Full trip_to_blocked behavior is B's concern.

**Test numbering K8/K9 vs. K8/K8** — Section K uses sequential single-letter suffixes. K8 for P1.5-1 and K9 for P1.5-5 maintains that convention.

## Assumptions

- `STATUS_BLOCKED` is already exported by scheduler.sh (sourced in the test suite preamble) — confirmed at line 23 of test_scheduler.sh: `SCHEDULER_SOURCE_ONLY=1 source "$SCHED"`.
- `MAX_RETRIES` resolves to `3` by default (scheduler.sh line 7); the test references the variable, not the literal, for env-override robustness.
- The `set_board_status` stub logs `set_board_status $*` to STUB_LOG (re-stubbed at line 26 of the test file after sourcing).

## Open Questions

None — all decisions resolved via codebase inspection and product-owner Q&A.
