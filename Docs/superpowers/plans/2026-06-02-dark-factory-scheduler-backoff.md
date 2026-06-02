# Dark Factory Scheduler — Back-off and Comment Dedup Implementation Plan

**Date:** 2026-06-02
**Issue:** #144
**Spec:** `Docs/superpowers/specs/2026-06-01-dark-factory-scheduler-backoff-design.md`
**Branch:** `refine/issue-144-dark-factory-scheduler--back-off-and-sto`

## Goal

Stop the dark factory scheduler from (a) posting a new failure comment on every retry attempt and (b) retrying refinement/plan dispatches indefinitely. When a refine or plan run fails deterministically, produce at most one updated failure comment and stop dispatching after `REFINE_MAX_RETRIES` attempts, adding `needs-discussion` and a distinct exhaustion comment.

## Architecture

Two bash scripts are affected — no database changes, no Python/TypeScript changes:

| Component | Change |
|-----------|--------|
| `dark-factory/entrypoint.sh` | Add `REFINE_FAILURE_MARKER`/`FACTORY_FAILURE_MARKER` constants + `post_or_update_comment` helper; rewrite `on_failure()` to call it |
| `dark-factory/scheduler.sh` | Add `REFINE_MAX_RETRIES`; add per-intent retry guard + exhaustion action to Priority 4 (Plan) and Priority 5 (fresh Refine); add `reset_retry` on spec-pending-review re-dispatch |

The HTML-marker find-and-patch pattern for failure comments mirrors the existing `post_cost_report` / `COST_MARKER` pattern already in `entrypoint.sh`. The composite-key retry tracking (`"123:refine"`, `"123:plan"`) reuses the existing `get_retry_count` / `increment_retry` / `reset_retry` helpers with no changes to those functions.

## Tech Stack

Bash + GitHub CLI (`gh api`, `gh issue comment`, `gh issue edit`). No additional dependencies.

## File Structure

| File | Lines Changed | Purpose |
|------|---------------|---------|
| `dark-factory/entrypoint.sh` | ~207–244 | `on_failure()` rewrite + new helper |
| `dark-factory/scheduler.sh` | ~7–27, ~541–556, ~558–593 | Config constant + Priority 4 guard + Priority 5 guard + reset |

---

## Tasks

### Task 1 — `entrypoint.sh`: Add failure markers and `post_or_update_comment` helper

**Files:** `dark-factory/entrypoint.sh`

**Current behavior:** `on_failure()` calls `gh issue comment` unconditionally, appending a new comment every time.

**Before change (verify):**
```bash
grep -n 'REFINE_FAILURE_MARKER\|post_or_update_comment' dark-factory/entrypoint.sh
# Expected: no output (function does not exist yet)
```

**Change:** After the `COST_MARKER` constant on line 85, insert the two failure marker constants and the `post_or_update_comment` helper:

```bash
# After:
COST_MARKER="<!-- dark-factory-cost-report -->"

# Insert immediately after (before the post_cost_report function):
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

**Verify after:**
```bash
bash -n dark-factory/entrypoint.sh
# Expected: no output (syntax OK)

grep -c 'post_or_update_comment' dark-factory/entrypoint.sh
# Expected: 1 (definition only; call sites are added in Task 2)
```

**Commit:**
```bash
git add dark-factory/entrypoint.sh
git commit -m "feat(#144): add post_or_update_comment helper to entrypoint.sh

Adds REFINE_FAILURE_MARKER / FACTORY_FAILURE_MARKER constants and a
post_or_update_comment() helper using the same HTML-marker find-and-patch
pattern as post_cost_report. Subsequent on_failure() rewrite will call it."
```

---

### Task 2 — `entrypoint.sh`: Rewrite `on_failure()` to use the helper

**Files:** `dark-factory/entrypoint.sh`

**Scope:** Replace only the inner conditional block (lines 210–238) inside `on_failure()`. The outer guard (`if [ -n "${ISSUE_NUM:-}" ] && [ "$INTENT" != "close" ]; then`) and the final `post_cost_report || true` line are **kept unchanged**. Do not remove or modify lines outside the inner `if`/`else`/`fi` shown below.

**Current inner block — replace only this:**

```bash
# REPLACE only this inner block (the two gh issue comment calls plus their surrounding if/else/fi):
    if [ "$INTENT" = "refine" ] || [ "$INTENT" = "plan" ]; then
      echo "Refinement pipeline failed (exit $EXIT_CODE) for issue #$ISSUE_NUM"
      gh issue comment "$ISSUE_NUM" --body "## Refinement Pipeline — Failed

The refinement pipeline encountered an error (exit code $EXIT_CODE) and could not complete.

\`\`\`bash
# Retry
docker compose --profile factory run --rm dark-factory \"$ARGUMENTS\"
\`\`\`

---
*Posted by MarketHawk Refinement Pipeline*" 2>/dev/null || true
    else
      echo "Dark factory failed (exit $EXIT_CODE). Moving issue #$ISSUE_NUM back to Ready..."
      set_board_status "$STATUS_BLOCKED" 2>/dev/null || true
      gh issue comment "$ISSUE_NUM" --body "## Dark Factory Run — Failed

The dark factory encountered an error (exit code $EXIT_CODE) and could not complete.
Issue has been moved to **Blocked**.

\`\`\`bash
# Retry
docker compose --profile factory run --rm dark-factory \"$ARGUMENTS\"
\`\`\`

---
*Posted by MarketHawk Dark Factory*" 2>/dev/null || true
    fi
```

**Replace with:**
```bash
    if [ "$INTENT" = "refine" ] || [ "$INTENT" = "plan" ]; then
      echo "Refinement pipeline failed (exit $EXIT_CODE) for issue #$ISSUE_NUM"
      post_or_update_comment "$REFINE_FAILURE_MARKER" \
        "${REFINE_FAILURE_MARKER}
## Refinement Pipeline — Failed

The refinement pipeline encountered an error (exit code $EXIT_CODE) and could not complete.

\`\`\`bash
# Retry
docker compose --profile factory run --rm dark-factory \"$ARGUMENTS\"
\`\`\`

---
*Posted by MarketHawk Refinement Pipeline*"
    else
      echo "Dark factory failed (exit $EXIT_CODE). Moving issue #$ISSUE_NUM back to Ready..."
      set_board_status "$STATUS_BLOCKED" 2>/dev/null || true
      post_or_update_comment "$FACTORY_FAILURE_MARKER" \
        "${FACTORY_FAILURE_MARKER}
## Dark Factory Run — Failed

The dark factory encountered an error (exit code $EXIT_CODE) and could not complete.
Issue has been moved to **Blocked**.

\`\`\`bash
# Retry
docker compose --profile factory run --rm dark-factory \"$ARGUMENTS\"
\`\`\`

---
*Posted by MarketHawk Dark Factory*"
    fi
```

**Verify after:**
```bash
bash -n dark-factory/entrypoint.sh
# Expected: no output (syntax OK)

grep -c 'post_or_update_comment' dark-factory/entrypoint.sh
# Expected: 3 (definition + 2 call sites — the refine/plan branch and the else branch)

# Confirm unconditional gh issue comment is gone from on_failure():
sed -n '/^on_failure/,/^trap on_failure/p' dark-factory/entrypoint.sh | grep 'gh issue comment'
# Expected: no output
```

**Commit:**
```bash
git add dark-factory/entrypoint.sh
git commit -m "feat(#144): rewrite on_failure() to update failure comment in place

Uses post_or_update_comment() instead of unconditional gh issue comment.
First failure posts a new comment with the HTML marker embedded; subsequent
failures for the same intent PATCH the existing comment in place, producing
at most one failure comment per issue per run type."
```

---

### Task 3 — `scheduler.sh`: Add `REFINE_MAX_RETRIES` constant

**Files:** `dark-factory/scheduler.sh`

**Before change (verify):**
```bash
grep 'REFINE_MAX_RETRIES' dark-factory/scheduler.sh
# Expected: no output (not yet defined)
```

**Change:** After line 26 (`REFINE_WIP_LIMIT="${REFINE_WIP_LIMIT:-2}"`), add:

```bash
# After:
REFINE_WIP_LIMIT="${REFINE_WIP_LIMIT:-2}"
REFINE_SKIP_LABELS="needs-discussion,epic,spec-pending-review,plan-pending-review"

# Insert:
REFINE_MAX_RETRIES="${REFINE_MAX_RETRIES:-3}"
```

The full Refinement pipeline configuration block becomes:
```bash
# Refinement pipeline configuration
REFINE_WIP_LIMIT="${REFINE_WIP_LIMIT:-2}"
REFINE_SKIP_LABELS="needs-discussion,epic,spec-pending-review,plan-pending-review"
REFINE_MAX_RETRIES="${REFINE_MAX_RETRIES:-3}"
```

**Verify after:**
```bash
bash -n dark-factory/scheduler.sh
# Expected: no output

grep 'REFINE_MAX_RETRIES' dark-factory/scheduler.sh
# Expected: 1 line (definition only; guard call sites added in Tasks 4 and 5)
```

**Commit (standalone — do not defer to Task 4):**
```bash
git add dark-factory/scheduler.sh
git commit -m "feat(#144): add REFINE_MAX_RETRIES config constant to scheduler.sh

Adds REFINE_MAX_RETRIES=3 alongside MAX_RETRIES in the Configuration block.
Env-configurable independently from implementation retry threshold."
```

---

### Task 4 — `scheduler.sh`: Add retry guard + exhaustion to Priority 4 (Plan dispatch)

**Files:** `dark-factory/scheduler.sh`

**Current Priority 4 block (lines 541–556) — replace:**

```bash
  # --- Priority 4: Refined items (plan generation — advance refined work before pulling new backlog) ---
  while IFS= read -r item; do
    [ -n "$DISPATCHED" ] && break
    ISSUE=$(get_issue_number "$item")
    if has_refine_skip_label "$item"; then continue; fi
    if is_issue_running "$ISSUE"; then continue; fi
    if [ "$REFINE_RUNNING" -ge "$REFINE_WIP_LIMIT" ]; then break; fi

    gh issue comment "$ISSUE" --repo "${OWNER}/markethawk" --body "📋 **Refinement Pipeline** — Starting plan generation and architect validation.

---
*Posted by MarketHawk Backlog Scheduler*" 2>/dev/null || true
    dispatch "Plan issue #${ISSUE}"
    DISPATCHED="Plan issue #${ISSUE}"
    REFINE_RUNNING=$((REFINE_RUNNING + 1))
  done < <(echo "$REFINED" | jq -c '.[]')
```

**Replace with:**
```bash
  # --- Priority 4: Refined items (plan generation — advance refined work before pulling new backlog) ---
  while IFS= read -r item; do
    [ -n "$DISPATCHED" ] && break
    ISSUE=$(get_issue_number "$item")
    if has_refine_skip_label "$item"; then continue; fi
    if is_issue_running "$ISSUE"; then continue; fi
    if [ "$REFINE_RUNNING" -ge "$REFINE_WIP_LIMIT" ]; then break; fi

    RETRIES=$(get_retry_count "${ISSUE}:plan")
    if [ "$RETRIES" -ge "$REFINE_MAX_RETRIES" ]; then
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

**Verify after:**
```bash
bash -n dark-factory/scheduler.sh
# Expected: no output

grep -c 'ISSUE}:plan' dark-factory/scheduler.sh
# Expected: 2 (get_retry_count and increment_retry calls)
```

**Commit:**
```bash
git add dark-factory/scheduler.sh
git commit -m "feat(#144): add retry guard to Priority 4 (Plan)

Adds REFINE_MAX_RETRIES=3 config constant. Priority 4 now tracks attempts
via composite key '\"N:plan\"' and exhausts to needs-discussion + a distinct
exhaustion comment after REFINE_MAX_RETRIES failures, rather than looping
indefinitely."
```

---

### Task 5 — `scheduler.sh`: Add retry guard to Priority 5 fresh Refine dispatch + reset on re-run

**Files:** `dark-factory/scheduler.sh`

Two insertion points within the Priority 5 block:

#### 5a — Fresh refinement dispatch (after the `spec-pending-review` block, before dispatch)

**Current lines 582–594 (fresh dispatch, inside Priority 5):**
```bash
    if has_refine_skip_label "$item"; then continue; fi
    if is_issue_running "$ISSUE"; then continue; fi
    if [ "$REFINE_RUNNING" -ge "$REFINE_WIP_LIMIT" ]; then break; fi

    gh issue comment "$ISSUE" --repo "${OWNER}/markethawk" --body "🧠 **Refinement Pipeline** — Starting brainstorming and spec generation.

---
*Posted by MarketHawk Backlog Scheduler*" 2>/dev/null || true
    dispatch "Refine issue #${ISSUE}"
    DISPATCHED="Refine issue #${ISSUE}"
    REFINE_RUNNING=$((REFINE_RUNNING + 1))
  done < <(echo "$BACKLOG" | jq -c '.[]')
```

**Replace with:**
```bash
    if has_refine_skip_label "$item"; then continue; fi
    if is_issue_running "$ISSUE"; then continue; fi
    if [ "$REFINE_RUNNING" -ge "$REFINE_WIP_LIMIT" ]; then break; fi

    RETRIES=$(get_retry_count "${ISSUE}:refine")
    if [ "$RETRIES" -ge "$REFINE_MAX_RETRIES" ]; then
      gh issue edit "$ISSUE" --repo "${OWNER}/markethawk" --add-label needs-discussion 2>/dev/null || true
      gh issue comment "$ISSUE" --repo "${OWNER}/markethawk" --body "## Refinement Pipeline — Retries Exhausted

The scheduler has attempted refinement **${RETRIES} time(s)** and cannot recover automatically. The issue has been labelled \`needs-discussion\` to pause automation.

**To resume automation:**
1. Investigate the failure comments above.
2. Fix the root cause (update the issue body, fix a dependency, or resolve the blocking error).
3. Remove the \`needs-discussion\` label — the scheduler will resume automatically.

\`\`\`bash
# Or retry manually:
docker compose --profile factory run --rm dark-factory \"Refine issue #${ISSUE}\"
\`\`\`

---
*Posted by MarketHawk Backlog Scheduler*" 2>/dev/null || true
      continue
    fi

    increment_retry "${ISSUE}:refine"
    gh issue comment "$ISSUE" --repo "${OWNER}/markethawk" --body "🧠 **Refinement Pipeline** — Starting brainstorming and spec generation.

---
*Posted by MarketHawk Backlog Scheduler*" 2>/dev/null || true
    dispatch "Refine issue #${ISSUE}"
    DISPATCHED="Refine issue #${ISSUE}"
    REFINE_RUNNING=$((REFINE_RUNNING + 1))
  done < <(echo "$BACKLOG" | jq -c '.[]')
```

#### 5b — spec-pending-review re-dispatch: add `reset_retry` before dispatch

**Current spec-pending-review block (lines 565–580, inside Priority 5):**
```bash
        HAS_NEW=$(has_new_comment_after_report "$ISSUE" "Posted by MarketHawk Refinement Pipeline")
        if [ "$HAS_NEW" = "yes" ]; then
          gh issue edit "$ISSUE" --repo "${OWNER}/markethawk" --remove-label "spec-pending-review" 2>/dev/null || true
          gh issue comment "$ISSUE" --repo "${OWNER}/markethawk" --body "🔄 **Refinement Pipeline** — Re-running with new feedback.

---
*Posted by MarketHawk Backlog Scheduler*" 2>/dev/null || true
          dispatch "Refine issue #${ISSUE}"
          DISPATCHED="Refine issue #${ISSUE}"
          REFINE_RUNNING=$((REFINE_RUNNING + 1))
        fi
```

**Replace with (add `reset_retry` as first line of the `if` body):**
```bash
        HAS_NEW=$(has_new_comment_after_report "$ISSUE" "Posted by MarketHawk Refinement Pipeline")
        if [ "$HAS_NEW" = "yes" ]; then
          reset_retry "${ISSUE}:refine"
          gh issue edit "$ISSUE" --repo "${OWNER}/markethawk" --remove-label "spec-pending-review" 2>/dev/null || true
          gh issue comment "$ISSUE" --repo "${OWNER}/markethawk" --body "🔄 **Refinement Pipeline** — Re-running with new feedback.

---
*Posted by MarketHawk Backlog Scheduler*" 2>/dev/null || true
          dispatch "Refine issue #${ISSUE}"
          DISPATCHED="Refine issue #${ISSUE}"
          REFINE_RUNNING=$((REFINE_RUNNING + 1))
        fi
```

**Verify after:**
```bash
bash -n dark-factory/scheduler.sh
# Expected: no output

grep -c 'ISSUE}:refine' dark-factory/scheduler.sh
# Expected: 3 (get_retry_count, increment_retry, reset_retry calls)
```

**Commit:**
```bash
git add dark-factory/scheduler.sh
git commit -m "feat(#144): add retry guard to Priority 5 (Refine) + reset on re-run

Priority 5 fresh Refine dispatch now tracks attempts via composite key
'\"N:refine\"' and exhausts to needs-discussion after REFINE_MAX_RETRIES
failures. The spec-pending-review re-dispatch path calls reset_retry to
give the new run a full retry budget after human feedback."
```

---

### Task 6 — Syntax validation and manual test checklist

**Files:** (read-only verification)

#### Syntax check (automated)
```bash
bash -n dark-factory/entrypoint.sh && echo "entrypoint.sh OK"
bash -n dark-factory/scheduler.sh  && echo "scheduler.sh OK"
# Expected:
# entrypoint.sh OK
# scheduler.sh OK
```

#### Structure check
```bash
# Confirm helper is present
grep -n 'post_or_update_comment\|REFINE_FAILURE_MARKER\|FACTORY_FAILURE_MARKER' dark-factory/entrypoint.sh
# Expected: 5+ lines (2 marker consts, function def, 2 call sites)

# Confirm no unconditional gh issue comment remains in on_failure()
# sed range: from the on_failure function definition to the trap line that follows it
sed -n '/^on_failure/,/^trap on_failure/p' dark-factory/entrypoint.sh | grep 'gh issue comment'
# Expected: no output

# Confirm composite keys in scheduler
grep 'ISSUE}:plan\|ISSUE}:refine' dark-factory/scheduler.sh
# Expected: 5 lines (get×2, increment×2, reset×1)

# Confirm REFINE_MAX_RETRIES constant and guards
grep 'REFINE_MAX_RETRIES' dark-factory/scheduler.sh
# Expected: 3 lines (definition + 2 guards in Priority 4 and Priority 5)

# Confirm Priority 3 (Blocked) retry tracking uses plain issue-number key (unchanged)
grep 'get_retry_count "\$ISSUE"\|increment_retry "\$ISSUE"\|reset_retry "\$ISSUE"' dark-factory/scheduler.sh
# Expected: 3 lines — the existing Priority 3 plain-key calls must still be present
```

#### Manual validation checklist

| Scenario | How to test | Expected result |
|----------|-------------|-----------------|
| Comment dedup | Trigger a failing refine run twice | 2nd failure PATCHes the same comment; issue still has 1 failure comment |
| Retry exhaustion | `REFINE_MAX_RETRIES=1`, trigger failing refine | After 1 attempt: `needs-discussion` label added, "retries exhausted" comment posted, scheduler stops dispatching |
| Human re-run reset | After exhaustion, remove `needs-discussion`; inspect `STATE_FILE` inside scheduler container | `"N:refine"` key absent (reset) or = 0; full 3-attempt budget restored |
| Plan exhaustion | `REFINE_MAX_RETRIES=1`, move issue to Refined, trigger failing plan | Same as refine exhaustion but for `"N:plan"` composite key |
| Factory impl failure dedup | Trigger failing Fix/Continue run twice | 2nd failure PATCHes existing factory failure comment |

**No commit needed for this task** (verification only).

---

## Commit Summary

| Task | Commit message |
|------|---------------|
| 1 | `feat(#144): add post_or_update_comment helper to entrypoint.sh` |
| 2 | `feat(#144): rewrite on_failure() to update failure comment in place` |
| 3 | `feat(#144): add REFINE_MAX_RETRIES config constant to scheduler.sh` |
| 4 | `feat(#144): add retry guard to Priority 4 (Plan)` |
| 5 | `feat(#144): add retry guard to Priority 5 (Refine) + reset on re-run` |

## Not in Scope

- Changes to `archon-dark-factory.yaml` or any implement/validate Archon commands
- Resetting `"N:plan"` counter automatically when a human moves an exhausted Plan issue back to Refined
- Email/Slack notifications on exhaustion
- Distinguishing transient vs. deterministic failures automatically
