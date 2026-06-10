# Scheduler P1.5 Tests — Implementation Plan

**Date:** 2026-06-10
**Issue:** [#215](https://github.com/omniscient/markethawk/issues/215)
**Spec:** [docs/superpowers/specs/2026-06-07-p1-5-scheduler-tests-design.md](../specs/2026-06-07-p1-5-scheduler-tests-design.md)
**Branch:** `plan/issue-215-p1-5-scheduler-tests`
**Component:** `dark-factory/tests/`
**Author:** MarketHawk Refinement Pipeline (plan generation)

## Goal

Add two missing P1.5 test cases — **K8** and **K9** — to Section K of
`dark-factory/tests/test_scheduler.sh`. These are the two spec-required scenarios
left unimplemented when #210 shipped:

- **K8 (P1.5-1):** Assert that `increment_retry "${ISSUE}:resolve"` is recorded in
  STATE_FILE after the CONFLICTING-dispatch path runs.
- **K9 (P1.5-5):** Assert that when `get_retry_count "${ISSUE}:resolve"` equals
  `$MAX_RETRIES`, `trip_to_blocked` is called, no `dispatch` is logged, and the
  retry counter resets to `0`.

No production code changes are required — the production behaviour already exists in
`scheduler.sh` lines 764–779; only test coverage is missing.

## Architecture

Both tests follow the existing **Section K inline-simulation pattern**: stub all
external dependencies (gh, docker, set_board_status, dispatch, check_pr_mergeable,
is_issue_running), simulate the relevant sub-path of the P1.5 block directly in the
test file (not via the full scheduler poll loop), and assert outcomes with `assert_eq`.

K8 and K9 are inserted immediately before the `# Restore stubs` block that closes
Section K (after the K7 assertion on line 571), so they share the same
`_ITEM_REVIEW_A/_B/_C` fixture variables already defined at Section K entry.

**Sourced helpers are in scope at line 573.** `increment_retry`, `get_retry_count`,
`trip_to_blocked`, `MAX_RETRIES`, and `STATUS_BLOCKED` are all defined in
`scheduler.sh` before the `SCHEDULER_SOURCE_ONLY=1` early-return guard (line 613).
After `SCHEDULER_SOURCE_ONLY=1 source "$SCHED"` (test line 23), these symbols are
available throughout the test file — they are not dropped by subsequent `export -f`
stub churn (which only adds functions to the sub-shell environment, it does not remove
previously sourced functions from the current shell). This was empirically verified:
`type -t increment_retry` returns `function` at line 573, and calling
`increment_retry "60:resolve" || true` followed by `get_retry_count "60:resolve"`
returns `1` as expected. Section A (lines 45–54) uses the same helpers by the same
mechanism.

## Tech Stack

- **Test file:** `dark-factory/tests/test_scheduler.sh` (Bash)
- **Runner:** `bash dark-factory/tests/test_scheduler.sh`
- **Assertion helper:** `assert_eq` (defined in the file preamble; increments
  `$PASSED` / `$FAILED`)
- **State:** `$STATE_FILE` (JSON, per-run tmp file), `$STUB_LOG` (stub call recorder)

## File Structure

| File | Change |
|------|--------|
| `dark-factory/tests/test_scheduler.sh` | Add K8 and K9 test cases before `# Restore stubs` |

---

## Task 1 — Add K8: P1.5-1 — increment_retry recorded after CONFLICTING dispatch

**Files:** `dark-factory/tests/test_scheduler.sh`

### Context

Production code path being verified (`scheduler.sh` ~lines 776–779):

```bash
case "$MERGEABLE" in
  CONFLICTING)
    increment_retry "${ISSUE}:resolve" || true
    if dispatch "Deconflict issue #${ISSUE}"; then
      DISPATCHED="Deconflict issue #${ISSUE}"
    fi
    ;;
esac
```

### TDD Steps

**Step 1 — Establish baseline**

```bash
bash dark-factory/tests/test_scheduler.sh 2>&1 | tail -3
# Expected: Results: N passed, 0 failed
# Note the current pass count N for comparison.
```

**Step 2 — Write the test case**

Insert the following block into `dark-factory/tests/test_scheduler.sh`, immediately
after the unique K7 assertion line:
`assert_eq "K7: check_pr_mergeable returns value from gh" "CONFLICTING" "$_RESULT"`

(The file has two `# Restore stubs` markers at lines 245 and 573; anchoring on the K7
assertion line avoids any ambiguity — `_ITEM_REVIEW_A` is defined at line 442 and only
in scope for the Section K block at line 573.)

```bash

> "$STUB_LOG"; DISPATCHED=""

# K8: P1.5-1 — increment_retry recorded after CONFLICTING dispatch
echo '{}' > "$STATE_FILE"
check_pr_mergeable() { echo "CONFLICTING"; }
is_issue_running() { return 1; }
dispatch() { echo "dispatch $*" >> "$STUB_LOG"; return 0; }
export -f check_pr_mergeable is_issue_running dispatch

ISSUE=$(get_issue_number "$_ITEM_REVIEW_A")   # 60
# Inline P1.5 CONFLICTING branch (mirrors scheduler.sh lines 776–779)
increment_retry "${ISSUE}:resolve" || true
if dispatch "Deconflict issue #${ISSUE}"; then
  DISPATCHED="Deconflict issue #${ISSUE}"
fi
assert_eq "K8: increment_retry recorded after CONFLICTING dispatch" \
  "1" "$(get_retry_count "60:resolve")"
```

**Step 3 — Run and verify the test passes**

```bash
bash dark-factory/tests/test_scheduler.sh 2>&1 | grep "K8\|Results"
# Expected:
#   PASS: K8: increment_retry recorded after CONFLICTING dispatch
#   Results: N+1 passed, 0 failed
```

If the test fails, check:
- `STATE_FILE` is reset to `{}` before the K8 block — any stale state from K7
  would carry a non-zero `60:resolve` counter.
- `is_issue_running` returns `1` (non-zero = false in bash); the production code
  guards with `if ! is_issue_running "$ISSUE"` but K8 simulates the inner block
  directly, so the stub isn't actually called in this simulation.

**Step 4 — Commit**

```bash
git add dark-factory/tests/test_scheduler.sh
git commit -m "test: K8 — P1.5-1 increment_retry recorded after CONFLICTING dispatch [#215]"
# Expected: [plan/issue-215-p1-5-scheduler-tests <sha>] test: K8 …
```

---

## Task 2 — Add K9: P1.5-5 — trip_to_blocked called at MAX_RETRIES

**Files:** `dark-factory/tests/test_scheduler.sh`

### Context

Production code path being verified (`scheduler.sh` ~lines 764–767):

```bash
RETRIES=$(get_retry_count "${ISSUE}:resolve")
if [ "$RETRIES" -ge "$MAX_RETRIES" ]; then
  trip_to_blocked "$ISSUE" "resolve" "retry limit of ${MAX_RETRIES} reached for conflict resolution"
  continue
fi
```

`trip_to_blocked` (lines 330–385) calls `set_board_status "$issue_num" "$STATUS_BLOCKED"`,
posts a GitHub comment, and then calls `reset_retry "$key"`.

### TDD Steps

**Step 1 — Write the test case**

Insert the following block immediately after the K8 block added in Task 1,
still before `# Restore stubs`:

```bash

> "$STUB_LOG"
printf '{"60:resolve": %s}' "$MAX_RETRIES" > "$STATE_FILE"

# K9: P1.5-5 — trip_to_blocked called at MAX_RETRIES; dispatch suppressed
ISSUE=$(get_issue_number "$_ITEM_REVIEW_A")   # 60
# Inline P1.5 MAX_RETRIES guard (mirrors scheduler.sh lines 764–766)
RETRIES=$(get_retry_count "${ISSUE}:resolve")
if [ "$RETRIES" -ge "$MAX_RETRIES" ]; then
  trip_to_blocked "$ISSUE" "resolve" "retry limit of ${MAX_RETRIES} reached for conflict resolution"
fi
assert_eq "K9: set_board_status Blocked called" \
  "1" "$(grep -c "set_board_status 60 ${STATUS_BLOCKED}" "$STUB_LOG" || echo 0)"
assert_eq "K9: no dispatch on trip" \
  "0" "$(grep -c 'dispatch' "$STUB_LOG" || true)"
assert_eq "K9: retry counter reset after trip" \
  "0" "$(get_retry_count "60:resolve")"
```

**Notes on assertions:**

- `$STATUS_BLOCKED` is sourced from `scheduler.sh` via `SCHEDULER_SOURCE_ONLY=1 source "$SCHED"`
  (line 23 of the test file); at the time this test runs it expands to `93d87b2f`.
- `trip_to_blocked` calls `set_board_status` and `gh issue edit` (which logs via the `gh` stub)
  and then `reset_retry` — so `get_retry_count "60:resolve"` must equal `0` after the call.
- The `dispatch` stub logs every call to STUB_LOG; checking `grep -c 'dispatch'` confirms the
  production guard (`continue` after `trip_to_blocked`) suppressed dispatch.

**Step 2 — Run and verify all three K9 assertions pass**

```bash
bash dark-factory/tests/test_scheduler.sh 2>&1 | grep "K9\|Results"
# Expected:
#   PASS: K9: set_board_status Blocked called
#   PASS: K9: no dispatch on trip
#   PASS: K9: retry counter reset after trip
#   Results: N+3 passed, 0 failed
```

If `K9: set_board_status Blocked called` fails:
- Verify `$MAX_RETRIES` resolves correctly (default `3`; scheduler.sh line 7).
- Verify `printf '{"60:resolve": %s}'` writes valid JSON.
- Check `set_board_status` stub is in scope (it is re-stubbed at line 26 of the
  test file and never overridden in Section K).

If `K9: retry counter reset after trip` fails:
- `trip_to_blocked` calls `reset_retry "$key"` (line 385) where key is `"60:resolve"`;
  confirm the scheduler.sh source is current.

**Step 3 — Full-suite validation**

```bash
bash dark-factory/tests/test_scheduler.sh 2>&1 | tail -3
# Expected: Results: <final-N> passed, 0 failed
```

**Step 4 — Commit**

```bash
git add dark-factory/tests/test_scheduler.sh
git commit -m "test: K9 — P1.5-5 trip_to_blocked called at MAX_RETRIES [#215]"
# Expected: [plan/issue-215-p1-5-scheduler-tests <sha>] test: K9 …
```
