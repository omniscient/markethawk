# Dark Factory Scheduler — Back-off and Comment Dedup on Repeated Failures

**Date:** 2026-06-01
**Issue:** #144
**Component:** `dark-factory/entrypoint.sh`, `dark-factory/scheduler.sh`
**Approach:** HTML-marker find-and-patch for failure comments + per-intent retry cap with `needs-discussion` exhaustion on refinement paths

## Problem

When a dark-factory dispatch fails deterministically (e.g. the workflow-load regression in #140, root-caused in #142), the backlog scheduler retried the same step roughly every 60–90 s for hours and posted a new "Refinement Pipeline — Failed" comment on **every attempt**. Issue #140 accumulated 28 identical failure comments.

Two separate problems compound each other:

1. **Comment spam** — `on_failure()` in `entrypoint.sh` calls `gh issue comment` unconditionally, appending a new comment each time rather than updating an existing one.
2. **No retry cap on refinement dispatches** — The Priority 3 (Blocked) path already has `MAX_RETRIES=3` tracked in `STATE_FILE`. The Priority 4 (Plan) and Priority 5 (Refine/Backlog) paths have no retry tracking at all; a failing refine or plan dispatch loops forever.

A deterministic failure never recovers on blind retry — the tight loop just burns cycles and pollutes the issue thread.

## Requirements

1. **Comment dedup (both paths):** Each issue produces at most one failure comment per run type (refinement vs. implementation). Subsequent failures from the same intent update that comment in place.
2. **Retry cap — refinement path:** "Refine issue #N" and "Plan issue #N" dispatches are bounded by `REFINE_MAX_RETRIES` (default 3). Attempts are tracked per `issue+intent` key so Refine and Plan exhaust independently.
3. **Exhaustion action — refinement path:** When a refinement or plan dispatch exhausts its retries, the scheduler adds the `needs-discussion` label (which is already in `REFINE_SKIP_LABELS`, so future dispatches stop) and posts a distinct "retries exhausted" comment explaining the situation and what the human should do next.
4. **No true time-based backoff:** The 60-second poll cycle is already a natural pacing mechanism. Simple attempt counting (same pattern as `MAX_RETRIES` on implementation items) is sufficient and avoids STATE_FILE timestamp complexity.
5. **Retry counter reset on human re-dispatch:** When a human leaves feedback on a `spec-pending-review` item and the scheduler re-dispatches it, the retry counter resets to give the new run a full budget.
6. **Existing implementation retry path unchanged:** Priority 3 (Blocked) already has `MAX_RETRIES=3` and correct retry tracking. No changes there except the comment dedup fix in `entrypoint.sh`.

## Architecture

### Change 1 — `dark-factory/entrypoint.sh`: HTML-marker find-and-patch for `on_failure()`

The cost report already demonstrates the exact pattern needed:
1. Embed a hidden HTML marker in the comment body.
2. On failure, list comments on the issue and find the one containing the marker.
3. `PATCH` the existing comment; `POST` a new one only if none exists yet.

Add a shared `post_or_update_comment` helper:

```bash
REFINE_FAILURE_MARKER="<!-- df-refine-failure -->"
FACTORY_FAILURE_MARKER="<!-- df-factory-failure -->"

post_or_update_comment() {
  local marker="$1"
  local body="$2"
  local COMMENT_ID
  COMMENT_ID=$(gh api "repos/omniscient/markethawk/issues/${ISSUE_NUM}/comments" \
    --jq "[.[] | select(.body | contains(\"$marker\"))] | last | .id // empty" 2>/dev/null || true)
  local TMPFILE
  TMPFILE=$(mktemp /tmp/failure-comment-XXXXXX.md)
  echo "$body" > "$TMPFILE"
  if [ -n "$COMMENT_ID" ]; then
    gh api "repos/omniscient/markethawk/issues/comments/${COMMENT_ID}" \
      --method PATCH -F "body=@${TMPFILE}" >/dev/null 2>&1 || true
  else
    gh issue comment "$ISSUE_NUM" --body-file "$TMPFILE" 2>/dev/null || true
  fi
  rm -f "$TMPFILE"
}
```

Then rewrite `on_failure()` to call this helper, with the marker prepended to each comment body:

```bash
if [ "$INTENT" = "refine" ] || [ "$INTENT" = "plan" ]; then
  post_or_update_comment "$REFINE_FAILURE_MARKER" \
    "${REFINE_FAILURE_MARKER}
## Refinement Pipeline — Failed

The refinement pipeline encountered an error (exit code $EXIT_CODE) and could not complete.
...
*Posted by MarketHawk Refinement Pipeline*"
else
  post_or_update_comment "$FACTORY_FAILURE_MARKER" \
    "${FACTORY_FAILURE_MARKER}
## Dark Factory Run — Failed
...
*Posted by MarketHawk Dark Factory*"
fi
```

The marker is a hidden HTML comment at the very start of the body — invisible in GitHub's rendered view, findable via `jq`'s `contains()`.

### Change 2 — `dark-factory/scheduler.sh`: Per-intent retry tracking for refinement paths

#### New configuration constant

```bash
REFINE_MAX_RETRIES="${REFINE_MAX_RETRIES:-3}"
```

Add alongside the existing `MAX_RETRIES` in the Configuration section.

#### Composite-key retry functions

The existing `get_retry_count` / `increment_retry` / `reset_retry` functions already accept an arbitrary string key. Use composite keys for refinement to keep them independent from the implementation path's bare issue-number keys:

| Path | STATE_FILE key |
|------|----------------|
| Implementation (Fix/Continue, Priority 3) | `"123"` (unchanged) |
| Refinement — Refine (Priority 5) | `"123:refine"` |
| Refinement — Plan (Priority 4) | `"123:plan"` |

No changes to the helper functions themselves — only the key string passed by callers changes.

#### Priority 4 (Plan) — add retry guard

```bash
# --- Priority 4: Refined items (plan generation) ---
while IFS= read -r item; do
  [ -n "$DISPATCHED" ] && break
  ISSUE=$(get_issue_number "$item")
  if has_refine_skip_label "$item"; then continue; fi
  if is_issue_running "$ISSUE"; then continue; fi
  if [ "$REFINE_RUNNING" -ge "$REFINE_WIP_LIMIT" ]; then break; fi

  RETRIES=$(get_retry_count "${ISSUE}:plan")
  if [ "$RETRIES" -ge "$REFINE_MAX_RETRIES" ]; then
    # Exhausted — hand off to human
    gh issue edit "$ISSUE" --repo "${OWNER}/markethawk" --add-label needs-discussion 2>/dev/null || true
    gh issue comment "$ISSUE" --repo "${OWNER}/markethawk" --body "## Refinement Pipeline — Retries Exhausted

The scheduler has attempted plan generation **${RETRIES} time(s)** and cannot recover automatically. The issue has been labelled \`needs-discussion\` to pause automation.

**To resume automation:**
1. Investigate the failure comments above.
2. Fix the root cause (update the issue body, fix a dependency, or resolve the blocking error).
3. Remove the \`needs-discussion\` label — the scheduler will resume automatically.

\`\`\`bash
# Or retry manually:
docker compose --profile factory run --rm dark-factory \"Plan issue #${ISSUE}\"
\`\`\`

---
*Posted by MarketHawk Backlog Scheduler*" 2>/dev/null || true
    continue
  fi

  increment_retry "${ISSUE}:plan"
  gh issue comment "$ISSUE" --repo "${OWNER}/markethawk" --body "📋 **Refinement Pipeline** — Starting plan generation and architect validation.

---
*Posted by MarketHawk Backlog Scheduler*" 2>/dev/null || true
  dispatch "Plan issue #${ISSUE}"
  DISPATCHED="Plan issue #${ISSUE}"
  REFINE_RUNNING=$((REFINE_RUNNING + 1))
done < <(echo "$REFINED" | jq -c '.[]')
```

#### Priority 5 (Refine/Backlog) — add retry guard and reset on re-run

Two insertion points:

**A) Fresh refinement dispatch** (currently no retry guard):

```bash
RETRIES=$(get_retry_count "${ISSUE}:refine")
if [ "$RETRIES" -ge "$REFINE_MAX_RETRIES" ]; then
  gh issue edit "$ISSUE" --repo "${OWNER}/markethawk" --add-label needs-discussion 2>/dev/null || true
  gh issue comment "$ISSUE" --repo "${OWNER}/markethawk" --body "## Refinement Pipeline — Retries Exhausted
...
*Posted by MarketHawk Backlog Scheduler*" 2>/dev/null || true
  continue
fi
increment_retry "${ISSUE}:refine"
# (existing dispatch code follows)
```

**B) Re-run after human feedback** (the `spec-pending-review` branch) — add `reset_retry`:

```bash
if [ "$HAS_NEW" = "yes" ]; then
  reset_retry "${ISSUE}:refine"    # ← NEW: give fresh budget
  gh issue edit "$ISSUE" --repo "${OWNER}/markethawk" --remove-label "spec-pending-review" ...
  dispatch "Refine issue #${ISSUE}"
  ...
fi
```

## Failure / Success Flow After This Change

### Deterministic refinement failure (the issue-#140 scenario)

```
Cycle 1  retry_count=0 → increment to 1 → dispatch "Refine #140"
         factory fails → on_failure posts NEW failure comment (marker embedded)
Cycle 2  retry_count=1 → increment to 2 → dispatch "Refine #140"
         factory fails → on_failure finds marker → PATCHES comment in place (no new comment)
Cycle 3  retry_count=2 → increment to 3 → dispatch "Refine #140"
         factory fails → on_failure finds marker → PATCHES comment in place
Cycle 4  retry_count=3 ≥ REFINE_MAX_RETRIES(3) → add needs-discussion label
                                                 → post "retries exhausted" comment
                                                 → stop dispatching
```

Result: 2 comments total (1 failure + 1 exhaustion). Compared to 28 before this change.

### Human re-runs after investigating

1. Human reads the exhaustion comment, fixes root cause, removes `needs-discussion`.
2. Scheduler sees issue in Backlog without skip labels, `reset_retry("N:refine")` → counter=0.
3. Full 3-attempt budget restored.

## Alternatives Considered

### A — True exponential backoff (timestamp-based)

Store last-dispatch timestamp in STATE_FILE, skip the issue if `now - last_dispatch < 2^retries * POLL_INTERVAL`. Gives longer gaps between retries automatically.

**Rejected:** Adds STATE_FILE complexity (timestamps) and time arithmetic in bash. The 60-second poll cycle already provides natural pacing. The primary problem is unbounded retry *count*, not *interval* — 3 fast retries then stop is the right fix for deterministic failures.

### B — STATE_FILE comment-ID cache for find-and-patch

Store the failure comment ID in STATE_FILE on first post, PATCH by ID on subsequent failures. Faster (no comments list API call).

**Rejected:** STATE_FILE is ephemeral (`/tmp/`). A scheduler restart wipes the cached ID, causing the next failure to post a new comment — exactly the problem we're fixing. The HTML-marker approach (same as cost report) is stateless and survives restarts.

### C — Separate state file for refinement retries

Keep refinement retry counters in a `/tmp/scheduler-refine-state.json` separate from the implementation `STATE_FILE`.

**Rejected:** Unnecessary. The existing `get_retry_count` / `increment_retry` / `reset_retry` helpers already accept arbitrary string keys. Using composite keys (`"123:refine"`) achieves the same separation within the same file with no code changes to the helpers.

## Open Questions

1. **Plan retry counter reset:** If a Plan dispatch exhausts (`123:plan` counter = 3), the human removes `needs-discussion`, and the issue is manually moved back to Refined, the counter starts at 3 and immediately exhausts again. There's no automated path to reset `123:plan` after human intervention. Operators would need to either restart the scheduler (STATE_FILE wipe resets all counters) or add a manual step to the runbook. This is an acceptable edge case for now — Plan exhaustion is rarer than Refine exhaustion.

2. **REFINE_MAX_RETRIES vs MAX_RETRIES separate tuning:** Both default to 3. If operators want different thresholds for refinement vs. implementation, they can set each env var independently. Document this in the scheduler's comment block.

## Assumptions

- The `needs-discussion` label already exists in the `omniscient/markethawk` repo (it is referenced throughout the scheduler and skip-label config).
- STATE_FILE JSON is small enough that the cost-neutral operations (`jq` reads and writes on each cycle) remain negligible even with composite keys.
- Three retry attempts (same as implementation default) is sufficient for refinement failures. Deterministic failures won't recover on retry regardless; transient failures (network, Claude rate limit) are expected to recover within 1–2 retries.

## Files Modified

| File | Change |
|------|--------|
| `dark-factory/entrypoint.sh` | Add `REFINE_FAILURE_MARKER` / `FACTORY_FAILURE_MARKER` constants + `post_or_update_comment` helper; rewrite `on_failure()` to call it instead of unconditional `gh issue comment` |
| `dark-factory/scheduler.sh` | Add `REFINE_MAX_RETRIES` constant; add per-intent retry guard + exhaustion action to Priority 4 (Plan) and Priority 5 (Refine/Backlog) dispatch paths; add `reset_retry` call when re-dispatching after human feedback |

## Testing / Validation

1. **Syntax check:** `bash -n dark-factory/entrypoint.sh && bash -n dark-factory/scheduler.sh`
2. **Comment dedup:** Trigger a failing refine run; confirm the second failure patches the existing comment (check comment count on the issue is still 1 failure comment, not 2).
3. **Retry exhaustion:** Set `REFINE_MAX_RETRIES=1` and trigger a failing refine; confirm:
   - Exactly 1 dispatch attempt
   - The `needs-discussion` label is added after 1 failure
   - The "retries exhausted" comment appears
   - The scheduler stops dispatching that issue
4. **Human re-run:** After exhaustion, remove `needs-discussion`; confirm `reset_retry` fires and the counter resets to 0 (visible in `cat /tmp/scheduler-state.json` inside the container).

## Not in Scope

- Changes to the Archon workflow (`archon-dark-factory.yaml`) or any implement/validate commands.
- Resetting the `123:plan` counter automatically when a human moves an exhausted Plan issue back to Refined (open question above — defer).
- Sending notifications (email, Slack) on exhaustion — the `needs-discussion` label and exhaustion comment are the only signals.
- Distinguishing transient vs. deterministic failures automatically — all failures are treated the same; the count cap is the only circuit breaker.
