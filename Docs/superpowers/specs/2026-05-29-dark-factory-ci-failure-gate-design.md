# Dark Factory — CI-Failure Gate on In-Review Tickets

**Date:** 2026-05-29
**Component:** `dark-factory/scheduler.sh` (backlog scheduler poll loop)
**Approach:** New "Priority 0" CI gate in the In-Review section + branch-aware Blocked retry

## Problem

When the dark factory finishes implementing an issue, it opens a PR and moves the
ticket to **In review**. The repo's CI (`.github/workflows/ci.yml` → `Backend CI`
→ `pytest`) runs on every PR to `main`.

Today the scheduler has **no reaction to a red PR**. A ticket whose CI is failing
just sits in "In review" waiting for a human, and a reviewer could even approve and
merge it. The only In-review automation (Priority 1) reacts solely to *new human
review comments* — a CI failure is not a comment, so nothing happens.

We want: when an in-review ticket's PR has failing CI, move the ticket to **Blocked**,
post a comment explaining why, and let the factory automatically attempt to fix it.

## Why this can't be driven by the existing comment path

The comment-driven auto-fix (Priority 1) has two hard constraints that rule it out:

1. **It only watches the "In review" column.** Honoring the "move to Blocked"
   requirement removes the ticket from that column, so the comment handler stops
   watching it.
2. **It deliberately ignores bot/automated comments** (`classify_comments` prompt:
   *"SKIP — the comment is purely from a bot or automated system"*). A CI-failure
   comment we post is a bot comment → classified SKIP → no action. Driving a fix off
   our own bot comment would be circular.

So once a ticket is Blocked, the fix must be kicked off by the **Blocked retry path**,
not the comment path. The *fixing itself* needs no new logic: the existing
`Continue issue #N` command reuses the PR branch, and `dark-factory-validate` re-runs
`python -m pytest` (the same command CI runs) and loops "fix → re-run → re-validate
until all pass." The validate phase is the real safety net — it repairs the failing
tests regardless of whether the bot comment is read.

## Changes

All changes are in `dark-factory/scheduler.sh`.

### 1. New helpers

```bash
# Open PR number for an issue's feature branch ("" if none).
# Matches the branch convention used throughout the workflow: feat/issue-<N>-<slug>.
get_pr_for_issue() {
  gh pr list --search "head:feat/issue-${1}-" --json number --jq '.[0].number // empty' 2>/dev/null
}

# JSON array of definitively-failing checks for a PR (bucket == "fail").
# Robust to gh's non-zero exit on failing/pending checks and to "no checks reported".
failing_checks_for_pr() {
  local pr_num="$1"
  local checks
  checks=$(gh pr checks "$pr_num" --json name,bucket,link 2>/dev/null) || true
  echo "$checks" | jq empty >/dev/null 2>&1 || checks='[]'
  echo "$checks" | jq -c '[.[] | select(.bucket == "fail")]'
}
```

**Why `bucket == "fail"`:** `gh pr checks --json` buckets each check into
`pass | fail | pending | skipping | cancel`. We act only on `fail` — a definitive,
concluded failure. Pending/queued checks (a freshly-opened PR whose CI hasn't finished)
produce no `fail` entries, so the gate correctly waits instead of blocking prematurely.
A single failure is enough to pull the PR from review even if other checks are still
pending — a failed check won't un-fail.

**gh exit-code gotcha:** `gh pr checks` exits non-zero when checks are failing (1) or
pending (8), and errors when a PR has no checks. We capture stdout into a variable with
`$(...) || true` (so `set -e` / `pipefail` don't abort and so a non-zero exit's JSON is
still captured), then validate the JSON with `jq empty`, falling back to `[]`. We do
**not** use `$(cmd || echo '[]')` — on a non-zero exit that appends `[]` after the real
JSON and corrupts it.

### 2. New "Priority 0" CI gate (In-Review section)

Inserted in the main loop **before** the existing Priority 1 comment handler, so a red
PR is pulled from review before any "looks good → merge" comment can be acted on.

The gate (and the board-state fetch it needs) runs **above the single-factory
concurrency guard**, so it executes on every poll even while a factory run is in
progress. This is safe because the gate only sets board status + posts a comment — it
never dispatches a factory container. Everything that *does* dispatch (the orphaned
sweep and Priorities 1–5) stays below the guard. Without this, a red in-review PR would
wait for the current (possibly long) factory run to finish before being gated.

```bash
# --- Priority 0: In Review items with failing CI (gate red PRs out of review) ---
CI_BLOCKED=""   # space-padded list of issues blocked this cycle (so Priority 1 skips them)
while IFS= read -r item; do
  ISSUE=$(get_issue_number "$item")
  if has_skip_label "$item"; then continue; fi

  PR_NUM=$(get_pr_for_issue "$ISSUE")
  [ -z "$PR_NUM" ] && continue

  FAILED=$(failing_checks_for_pr "$PR_NUM")
  FAIL_COUNT=$(echo "$FAILED" | jq 'length')
  [ "$FAIL_COUNT" -eq 0 ] && continue

  echo "[$(date -u +%FT%TZ)] ci_gate issue=#${ISSUE} pr=#${PR_NUM} failing=${FAIL_COUNT} action=move_to_blocked"
  set_board_status "$ISSUE" "$STATUS_BLOCKED"

  FAIL_LIST=$(echo "$FAILED" | jq -r '.[] | "- [\(.name)](\(.link))"')
  gh issue comment "$ISSUE" --repo "${OWNER}/markethawk" --body "## Dark Factory — CI Failing, Moved to Blocked

PR #${PR_NUM} has failing CI checks, so this ticket has been moved out of **In review** to **Blocked**. The factory will retry automatically, continue the existing PR branch, and attempt to fix the failures.

**Failing checks:**
${FAIL_LIST}

---
*Posted by MarketHawk Backlog Scheduler*" 2>/dev/null || true

  CI_BLOCKED="${CI_BLOCKED} ${ISSUE} "
done < <(echo "$IN_REVIEW" | jq -c '.[]')
```

Notes:
- The gate **does not** set `DISPATCHED` and does **not** `break` — blocking is cheap
  (one status mutation + one comment), so every red in-review ticket is gated in the
  same cycle.
- It uses the existing `set_board_status` helper and `STATUS_BLOCKED` constant.
- The comment uses the **Backlog Scheduler** marker (not the Dark Factory marker), so it
  does not interfere with `get_new_comments`' "last Dark Factory comment" cursor.

### 3. Priority 1 skips tickets blocked this cycle

`$IN_REVIEW` is a stale snapshot taken at the top of the cycle, so a just-gated ticket is
still in that list. Add a guard at the top of the existing Priority 1 loop so we don't
also try to classify its comments:

```bash
    ISSUE=$(get_issue_number "$item")
    if has_skip_label "$item"; then continue; fi
    case "$CI_BLOCKED" in *" $ISSUE "*) continue ;; esac   # gated to Blocked this cycle
```

### 4. Branch-aware Blocked retry (Priority 3)

Today the Blocked retry always dispatches `Fix issue #N`, which the workflow classifies
as a *new* run and creates a fresh branch (`git checkout -b`). For a ticket that already
has a pushed PR, that fresh branch collides with the existing remote branch on push and
the run fails — so "block + auto-fix" would never actually fix the CI. Make the dispatch
branch-aware:

```bash
    increment_retry "$ISSUE"
    if [ -n "$(get_pr_for_issue "$ISSUE")" ]; then
      dispatch "Continue issue #${ISSUE}"        # reuse the PR branch, re-run validate, fix CI
      DISPATCHED="Continue issue #${ISSUE}"
    else
      dispatch "Fix issue #${ISSUE}"             # no PR yet — start fresh (unchanged behaviour)
      DISPATCHED="Fix issue #${ISSUE}"
    fi
```

This is what makes CI auto-fix work, and it also fixes the latent fresh-branch-collision
bug for **any** blocked item that already has a PR (e.g. a `continue` run that failed
mid-way and was moved to Blocked by `on_failure`).

## Control flow & termination

1. In-review ticket, CI red → **Priority 0** moves it to Blocked + comments. It leaves
   "In review", so the gate won't re-fire on it this cycle (Priority 1 skips it) or next
   cycle (it's no longer in `IN_REVIEW`).
2. Next cycle, **Priority 3** sees it in `BLOCKED`, increments its retry counter, and —
   because it has a PR — dispatches `Continue issue #N`.
3. The Continue run re-runs `pytest` in validate, fixes failures, pushes, and returns the
   ticket to "In review". CI re-runs on the new push.
4. If CI passes → ticket waits for human review (success). If CI fails again → back to
   step 1.

**Termination:** the retry counter (`get_retry_count` / `increment_retry`,
`MAX_RETRIES=3`) bounds the loop. After 3 fix attempts the Blocked retry skips the ticket
and it stays Blocked for a human. We intentionally do **not** reset the counter on the
gate transition.

## Idempotency & cost

- One comment per failed-CI cycle (moving to Blocked removes it from review, so no
  re-commenting until a Continue run brings it back red). Bounded by `MAX_RETRIES`.
- Extra API calls per cycle: one `gh pr list` + one `gh pr checks` per in-review ticket
  (`MAX_IN_REVIEW` is small), plus one `gh pr list` per blocked ticket evaluated until
  the first dispatch. The existing GraphQL rate-limit guard (`check_rate_limit`) already
  protects the loop.

## Files Modified

| File | Change |
|------|--------|
| `dark-factory/scheduler.sh` | Add `get_pr_for_issue` + `failing_checks_for_pr` helpers; add Priority 0 CI gate before Priority 1; add `CI_BLOCKED` skip guard in Priority 1; make Priority 3 Blocked retry branch-aware (Continue vs Fix) |

## Testing / Validation

The scheduler is bash with no unit-test harness. Validate by:
1. `bash -n dark-factory/scheduler.sh` — syntax check.
2. Dry-run the helpers against a real PR with a known-failing check, e.g.
   `failing_checks_for_pr <pr#>` returns the failing check; against a green PR it returns
   `[]`; against a PR with only pending checks it returns `[]`.
3. End-to-end: point the scheduler at a board with an in-review ticket whose PR has red
   CI; confirm it moves to Blocked with the comment, then is retried via `Continue`.

## Not in Scope

- Changes to the Archon workflow (`archon-dark-factory.yaml`) or the implement/validate
  commands — the existing `Continue` + `validate` path already re-runs and fixes pytest.
- Reacting to CI that is merely *pending* (we wait for a definitive failure).
- Distinguishing CI-failure blocks from other blocks in the retry path — branch-aware
  routing (Continue when a PR exists) is correct for every blocked item, so no marker is
  needed.
- Resetting / raising `MAX_RETRIES` for CI-blocked tickets — the existing bound is the
  intended backstop.
