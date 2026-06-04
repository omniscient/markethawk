# Implementation Plan: Direct-to-PR Autonomous Flow

**Date:** 2026-06-04
**Issue:** #183
**Spec:** `docs/superpowers/specs/2026-06-03-direct-to-pr-autonomous-flow-design.md`

---

## Goal

Add an opt-in per-ticket "direct-to-pr" mode to the backlog scheduler. Tickets labelled
`direct-to-pr` flow Backlog → Refined → Ready → In Review → Done with **no human board
move**, gated only by configurable grace windows and a final PR review. Every ticket
without the label keeps today's fully-gated behavior unchanged.

---

## Architecture

All new logic lives in `dark-factory/scheduler.sh`. The scheduler already polls every 60s,
detects human comments after a pipeline marker, and has board-column-move helpers — the new
behavior adds tiers and guards, not new infrastructure.

New pieces (all in scheduler.sh):
- Two helper functions: `has_direct_to_pr_label` and `elapsed_minutes_since_marker`
- Spec auto-advance: extended `spec-pending-review` handler in Priority 5 Backlog loop
- Entry trigger: extended opt-in check in Priority 5 Backlog loop
- Plan auto-advance: new handler before `has_refine_skip_label` in Priority 4 Refined loop
- End-gate auto-merge: new PR review check at the top of Priority 1 In Review loop

Supporting changes:
- `.claude/skills/refinement/config.yaml` — remove vestigial `auto_advance_to_ready`, add `direct_to_pr` section
- `ENV_VARIABLES.md` — document three new env vars
- `docs/agents/triage-labels.md` — document the new workflow flag
- `.archon/commands/dark-factory-refine.md` + `dark-factory-plan.md` — cosmetic auto-advance note
- `dark-factory/tests/test_scheduler.sh` — tests for each behavior

---

## Tech Stack

- **Scheduler**: `bash` + `gh` CLI + `docker compose` + `jq`
- **Tests**: bash unit tests, `SCHEDULER_SOURCE_ONLY=1` pattern
- **CI**: `bash dark-factory/tests/test_scheduler.sh`

---

## File Structure

| File | Change |
|------|--------|
| `dark-factory/scheduler.sh` | Add env vars, two helpers, four logic changes |
| `dark-factory/tests/test_scheduler.sh` | Add test sections E–J |
| `.claude/skills/refinement/config.yaml` | Remove vestigial key, add `direct_to_pr` block |
| `ENV_VARIABLES.md` | Document three new scheduler env vars |
| `docs/agents/triage-labels.md` | Document `direct-to-pr` as workflow flag |
| `.archon/commands/dark-factory-refine.md` | Cosmetic auto-advance note in Phase 6 (PUBLISH) |
| `.archon/commands/dark-factory-plan.md` | Cosmetic auto-advance note in Phase 4 |

---

## Tasks

---

### Task 1: Create `direct-to-pr` GitHub label + update triage docs

**Files:** `docs/agents/triage-labels.md`

#### Step 1.1 — Create the label on GitHub

```bash
gh label create "direct-to-pr" \
  --repo omniscient/markethawk \
  --color "0075ca" \
  --description "Opt-in: autonomous spec→plan→implement→PR→merge with grace windows"
```

Expected output: `✓ Label "direct-to-pr" created`

#### Step 1.2 — Update `docs/agents/triage-labels.md`

After the existing "Opt-in refinement gate" section, add a new "Workflow flags" section:

```markdown
## Workflow flags

These labels change scheduler *behavior* for a ticket already past triage. They are not
triage roles — apply them after the issue is `ready-for-agent` or `direct-to-pr` (which
implies entry and straight-through flow).

| Label | Meaning |
|-------|---------|
| `spec-pending-review` | Spec posted, waiting for human board-move or `SPEC_GRACE_MINUTES` auto-advance |
| `plan-pending-review` | Plan posted, waiting for human board-move or `PLAN_GRACE_MINUTES` auto-advance |
| `direct-to-pr` | **Opt-in**: ticket is admitted to the pipeline _and_ runs straight-through. Spec and plan checkpoints become async (grace-windowed); PR approval is the single end gate. Combine with `SPEC_GRACE_MINUTES=0` / `PLAN_GRACE_MINUTES=0` for pure auto-flow. |
```

#### Step 1.3 — Commit

```bash
git add docs/agents/triage-labels.md
git commit -m "docs(#183): document direct-to-pr label and workflow flags in triage-labels.md"
```

---

### Task 2: Add env vars to scheduler.sh + update config.yaml + ENV_VARIABLES.md

**Files:** `dark-factory/scheduler.sh`, `.claude/skills/refinement/config.yaml`, `ENV_VARIABLES.md`

#### Step 2.1 — Add three env vars to scheduler.sh config block

In `dark-factory/scheduler.sh`, after the `RATE_LIMIT_FLOOR` line (~line 8), add:

```bash
DIRECT_TO_PR_LABEL="${DIRECT_TO_PR_LABEL:-direct-to-pr}"
SPEC_GRACE_MINUTES="${SPEC_GRACE_MINUTES:-30}"
PLAN_GRACE_MINUTES="${PLAN_GRACE_MINUTES:-30}"
```

#### Step 2.2 — Update `.claude/skills/refinement/config.yaml`

Remove the vestigial `plan.auto_advance_to_ready: false` key (nothing reads it since the
auto-advance code was previously removed). Add a `direct_to_pr` section for documentation:

Before:
```yaml
plan:
  auto_advance_to_ready: false
  skip_labels:
    - needs-discussion
    - epic
    - plan-pending-review
```

After:
```yaml
plan:
  skip_labels:
    - needs-discussion
    - epic
    - plan-pending-review

direct_to_pr:
  label: direct-to-pr          # mirror of $DIRECT_TO_PR_LABEL (set in .archon/.env to override)
  spec_grace_minutes: 30       # mirror of $SPEC_GRACE_MINUTES — 0 = advance on next poll
  plan_grace_minutes: 30       # mirror of $PLAN_GRACE_MINUTES — 0 = advance on next poll
```

#### Step 2.3 — Update `ENV_VARIABLES.md`

In the `## Dark Factory / Backlog Scheduler` section, after the existing rows, add:

```markdown
| `DIRECT_TO_PR_LABEL` | `direct-to-pr` | Label name that opts a ticket into straight-through autonomous flow. Change only if your repo uses a different label string. |
| `SPEC_GRACE_MINUTES` | `30` | Minutes the scheduler waits after posting the spec before auto-advancing a `direct-to-pr` ticket from Backlog to Refined. `0` = advance on the next poll. |
| `PLAN_GRACE_MINUTES` | `30` | Minutes the scheduler waits after posting the plan before auto-advancing a `direct-to-pr` ticket from Refined to Ready. `0` = advance on the next poll. |
```

#### Step 2.4 — Verify config change is valid YAML

```bash
python3 -c "import yaml; yaml.safe_load(open('.claude/skills/refinement/config.yaml'))"
```

Expected: no output (valid).

#### Step 2.5 — Commit

```bash
git add dark-factory/scheduler.sh .claude/skills/refinement/config.yaml ENV_VARIABLES.md
git commit -m "feat(#183): add DIRECT_TO_PR_LABEL / SPEC_GRACE_MINUTES / PLAN_GRACE_MINUTES env vars"
```

---

### Task 3: Add `has_direct_to_pr_label` + `elapsed_minutes_since_marker` helpers (TDD)

**Files:** `dark-factory/tests/test_scheduler.sh`, `dark-factory/scheduler.sh`

#### Step 3.1 — Write failing tests (section E + F)

Append to `dark-factory/tests/test_scheduler.sh` (before the cleanup block at the bottom):

```bash
# ==========================================
# E: has_direct_to_pr_label
# ==========================================
echo ""
echo "--- E: has_direct_to_pr_label ---"

ITEM_DTP='{"content":{"number":10},"labels":["enhancement","direct-to-pr"],"status":"Backlog"}'
ITEM_NO_DTP='{"content":{"number":11},"labels":["enhancement","ready-for-agent"],"status":"Backlog"}'

has_direct_to_pr_label "$ITEM_DTP" \
  && assert_eq "item WITH direct-to-pr returns true" "0" "0" \
  || assert_eq "item WITH direct-to-pr returns true" "0" "1"

has_direct_to_pr_label "$ITEM_NO_DTP" \
  && assert_eq "item WITHOUT direct-to-pr returns false" "0" "1" \
  || assert_eq "item WITHOUT direct-to-pr returns false" "0" "0"

# ==========================================
# F: elapsed_minutes_since_marker
# ==========================================
echo ""
echo "--- F: elapsed_minutes_since_marker ---"

# Compute a timestamp 35 minutes in the past
_MARKER_EPOCH=$(( $(date -u +%s) - 35*60 ))
_MARKER_TS=$(date -u -d "@${_MARKER_EPOCH}" +%Y-%m-%dT%H:%M:%SZ)

gh() {
  printf '[{"body":"Refinement Pipeline — Plan Generated","createdAt":"%s"}]\n' "$_MARKER_TS"
}
export -f gh

_ELAPSED=$(elapsed_minutes_since_marker "55" "Refinement Pipeline")
[ -n "$_ELAPSED" ] && [ "$_ELAPSED" -ge 34 ] \
  && assert_eq "elapsed ≥ 34 for 35-min-old marker" "0" "0" \
  || assert_eq "elapsed ≥ 34 for 35-min-old marker" "0" "1"

# No matching comment → returns ""
gh() { printf '[{"body":"some other comment","createdAt":"%s"}]\n' "$_MARKER_TS"; }
export -f gh
_ELAPSED2=$(elapsed_minutes_since_marker "55" "Refinement Pipeline")
assert_eq "no matching marker returns empty" "" "$_ELAPSED2"

# Restore original gh stub
gh() { echo "gh $*" >> "$STUB_LOG"; return 0; }
export -f gh
```

#### Step 3.2 — Run tests to confirm they fail

```bash
bash dark-factory/tests/test_scheduler.sh 2>&1 | tail -20
```

Expected: `has_direct_to_pr_label` and `elapsed_minutes_since_marker` sections fail because
the functions are not yet defined.

#### Step 3.3 — Add helpers to `dark-factory/scheduler.sh`

Place these two functions immediately after the `has_opt_in_refine_label` function (~line 127):

```bash
has_direct_to_pr_label() {
  local item="$1"
  echo "$item" | jq -r '.labels[]?' 2>/dev/null | grep -qi "$DIRECT_TO_PR_LABEL"
}

# Returns minutes elapsed since the last comment matching $marker_re on the given issue.
# Returns "" if no matching comment exists or if the timestamp cannot be parsed.
elapsed_minutes_since_marker() {
  local issue_num="$1"
  local marker_re="$2"
  local comments
  comments=$(gh issue view "$issue_num" --repo "${OWNER}/markethawk" \
    --json comments -q '.comments' 2>/dev/null) || { echo ""; return; }
  local created_at
  created_at=$(echo "$comments" | jq -r --arg m "$marker_re" \
    '[.[] | select(.body | test($m))] | last | .createdAt // ""')
  [ -z "$created_at" ] && { echo ""; return; }
  local marker_epoch now_epoch
  marker_epoch=$(date -u -d "$created_at" +%s 2>/dev/null) || { echo ""; return; }
  now_epoch=$(date -u +%s)
  echo $(( (now_epoch - marker_epoch) / 60 ))
}
```

#### Step 3.4 — Run tests to confirm they pass

```bash
bash dark-factory/tests/test_scheduler.sh 2>&1 | grep -E "^(--|  PASS|  FAIL|Results)"
```

Expected: `Results: N passed, 0 failed`

#### Step 3.5 — Commit

```bash
git add dark-factory/scheduler.sh dark-factory/tests/test_scheduler.sh
git commit -m "feat(#183): add has_direct_to_pr_label and elapsed_minutes_since_marker helpers"
```

---

### Task 4: Spec auto-advance in Priority 5 (TDD)

**Files:** `dark-factory/tests/test_scheduler.sh`, `dark-factory/scheduler.sh`

#### Step 4.1 — Write failing tests (section G)

The tests exercise the three paths in the spec-advance handler:
1. Flag present + human comment → re-refine dispatched
2. Flag present + no comment + elapsed ≥ grace → advance to Refined
3. Flag present + no comment + elapsed < grace → no action
4. Flag absent → no auto-advance (regression guard)

Append to test_scheduler.sh before cleanup:

```bash
# ==========================================
# G: Spec auto-advance (direct-to-pr)
# ==========================================
echo ""
echo "--- G: Spec auto-advance ---"
echo '{}' > "$STATE_FILE"; > "$STUB_LOG"

# Shared test helpers
_ITEM_DTP_SPR='{"content":{"number":20},"labels":["direct-to-pr","spec-pending-review"],"status":"Backlog"}'
_ITEM_NODTP_SPR='{"content":{"number":21},"labels":["spec-pending-review"],"status":"Backlog"}'

# G1: flag + human comment → re-refine path (remove-label + dispatch Refine)
has_new_comment_after_report() { echo "yes"; }
elapsed_minutes_since_marker() { echo "99"; }
dispatch() { echo "dispatch $*" >> "$STUB_LOG"; return 0; }
export -f has_new_comment_after_report elapsed_minutes_since_marker dispatch

spec_advance_check 20 "$_ITEM_DTP_SPR"
assert_eq "G1: re-refine: remove-label called" \
  "1" "$(grep -c -- '--remove-label spec-pending-review' "$STUB_LOG" || echo 0)"
assert_eq "G1: re-refine: Refine dispatched" \
  "1" "$(grep -c 'dispatch Refine issue #20' "$STUB_LOG" || echo 0)"

> "$STUB_LOG"
# G2: flag + no comment + elapsed ≥ grace → advance (remove-label + set_board_status REFINED)
has_new_comment_after_report() { echo "no"; }
export SPEC_GRACE_MINUTES=30
elapsed_minutes_since_marker() { echo "35"; }   # 35 ≥ 30 → advance
export -f has_new_comment_after_report elapsed_minutes_since_marker

spec_advance_check 20 "$_ITEM_DTP_SPR"
assert_eq "G2: advance: remove-label called" \
  "1" "$(grep -c -- '--remove-label spec-pending-review' "$STUB_LOG" || echo 0)"
assert_eq "G2: advance: set_board_status REFINED" \
  "1" "$(grep -c "set_board_status 20 ${STATUS_REFINED}" "$STUB_LOG" || echo 0)"

> "$STUB_LOG"
# G3: flag + no comment + elapsed < grace → no action
elapsed_minutes_since_marker() { echo "10"; }   # 10 < 30 → wait
export -f elapsed_minutes_since_marker

spec_advance_check 20 "$_ITEM_DTP_SPR"
assert_eq "G3: within-window: no set_board_status" \
  "0" "$(grep -c 'set_board_status' "$STUB_LOG" || echo 0)"
assert_eq "G3: within-window: no dispatch" \
  "0" "$(grep -c 'dispatch' "$STUB_LOG" || echo 0)"

> "$STUB_LOG"
# G4: no flag → no auto-advance (regression guard)
elapsed_minutes_since_marker() { echo "99"; }  # would advance if flag were present
export -f elapsed_minutes_since_marker

spec_advance_check 21 "$_ITEM_NODTP_SPR"
assert_eq "G4: no-flag regression: no advance" \
  "0" "$(grep -c 'set_board_status' "$STUB_LOG" || echo 0)"

> "$STUB_LOG"
# G5: flag + needs-discussion → suppressed (no advance, even with elapsed ≥ grace)
_ITEM_DTP_SPR_ND='{"content":{"number":22},"labels":["direct-to-pr","spec-pending-review","needs-discussion"],"status":"Backlog"}'
elapsed_minutes_since_marker() { echo "99"; }
export -f elapsed_minutes_since_marker

spec_advance_check 22 "$_ITEM_DTP_SPR_ND"
assert_eq "G5: needs-discussion suppresses spec advance" \
  "0" "$(grep -c 'set_board_status' "$STUB_LOG" || echo 0)"
assert_eq "G5: needs-discussion suppresses spec dispatch" \
  "0" "$(grep -c 'dispatch' "$STUB_LOG" || echo 0)"

# Restore stubs
has_new_comment_after_report() { echo "no"; }
elapsed_minutes_since_marker() { echo ""; }
dispatch() { echo "dispatch $*" >> "$STUB_LOG"; return 0; }
export -f has_new_comment_after_report elapsed_minutes_since_marker dispatch
```

#### Step 4.2 — Run tests to confirm section G fails

```bash
bash dark-factory/tests/test_scheduler.sh 2>&1 | grep -E "G[0-9]|Results"
```

Expected: G1–G5 fail (`spec_advance_check` not yet defined).

#### Step 4.3 — Extract `spec_advance_check` function and wire into Priority 5

Add to `dark-factory/scheduler.sh` after `elapsed_minutes_since_marker`:

```bash
# Handle spec-pending-review for any item (gated or direct-to-pr).
# Assumes: caller already verified the item has spec-pending-review.
# Side-effects: may set DISPATCHED, increment REFINE_RUNNING, call dispatch/set_board_status.
spec_advance_check() {
  local issue_num="$1"
  local item="$2"
  # needs-discussion and epic suppress all automation — even for direct-to-pr items.
  has_skip_label "$item" && return 0
  local has_new
  has_new=$(has_new_comment_after_report "$issue_num" "Posted by MarketHawk Refinement Pipeline")
  if [ "$has_new" = "yes" ]; then
    reset_retry "${issue_num}:refine"
    gh issue edit "$issue_num" --repo "${OWNER}/markethawk" \
      --remove-label "spec-pending-review" 2>/dev/null || true
    gh issue comment "$issue_num" --repo "${OWNER}/markethawk" --body \
"🔄 **Refinement Pipeline** — Re-running with new feedback.

---
*Posted by MarketHawk Backlog Scheduler*" 2>/dev/null || true
    if dispatch "Refine issue #${issue_num}"; then
      DISPATCHED="Refine issue #${issue_num}"
      REFINE_RUNNING=$((REFINE_RUNNING + 1))
    fi
    return 0
  fi
  if has_direct_to_pr_label "$item"; then
    local elapsed
    elapsed=$(elapsed_minutes_since_marker "$issue_num" "Posted by MarketHawk Refinement Pipeline")
    if [ -n "$elapsed" ] && [ "$elapsed" -ge "$SPEC_GRACE_MINUTES" ]; then
      echo "[$(date -u +%FT%TZ)] spec_auto_advance issue=#${issue_num} elapsed=${elapsed}m grace=${SPEC_GRACE_MINUTES}m action=advance_to_refined"
      gh issue edit "$issue_num" --repo "${OWNER}/markethawk" \
        --remove-label "spec-pending-review" 2>/dev/null || true
      set_board_status "$issue_num" "$STATUS_REFINED" || true
    else
      echo "[$(date -u +%FT%TZ)] spec_grace_window issue=#${issue_num} elapsed=${elapsed:-unknown}m grace=${SPEC_GRACE_MINUTES}m action=waiting"
    fi
  fi
}
```

In the Priority 5 Backlog loop, replace the `spec-pending-review` handler block. The
replacement must include the `ITEM_LABELS` assignment that was in the original block — do
not omit it, as downstream code in the same loop iteration reads `$ITEM_LABELS`.

**Before (full block including ITEM_LABELS assignment):**
```bash
    ITEM_LABELS=$(echo "$item" | jq -r '.labels[]?' 2>/dev/null)
    if echo "$ITEM_LABELS" | grep -qi "spec-pending-review"; then
      if ! is_issue_running "$ISSUE" && [ "$REFINE_RUNNING" -lt "$REFINE_WIP_LIMIT" ]; then
        HAS_NEW=$(has_new_comment_after_report "$ISSUE" "Posted by MarketHawk Refinement Pipeline")
        if [ "$HAS_NEW" = "yes" ]; then
          reset_retry "${ISSUE}:refine"
          gh issue edit "$ISSUE" --repo "${OWNER}/markethawk" --remove-label "spec-pending-review" 2>/dev/null || true
          gh issue comment "$ISSUE" --repo "${OWNER}/markethawk" --body "🔄 **Refinement Pipeline** — Re-running with new feedback.

---
*Posted by MarketHawk Backlog Scheduler*" 2>/dev/null || true
          if dispatch "Refine issue #${ISSUE}"; then
            DISPATCHED="Refine issue #${ISSUE}"
            REFINE_RUNNING=$((REFINE_RUNNING + 1))
          fi
        fi
      fi
      continue
    fi
```

**After (ITEM_LABELS assignment preserved):**
```bash
    ITEM_LABELS=$(echo "$item" | jq -r '.labels[]?' 2>/dev/null)
    if echo "$ITEM_LABELS" | grep -qi "spec-pending-review"; then
      if ! is_issue_running "$ISSUE" && [ "$REFINE_RUNNING" -lt "$REFINE_WIP_LIMIT" ]; then
        spec_advance_check "$ISSUE" "$item"
      fi
      continue
    fi
```

#### Step 4.4 — Re-stub `spec_advance_check` in test after source (memory-safety pattern)

Since `scheduler.sh` now defines `spec_advance_check`, re-stubs in the test file must be
placed **after** `SCHEDULER_SOURCE_ONLY=1 source "$SCHED"`. Re-define `set_board_status`
after source (already done in the test preamble). The stubs for `has_new_comment_after_report`,
`elapsed_minutes_since_marker`, and `dispatch` are re-defined inside each test section — that
is the correct pattern per the `[FIX]` memory entry from issue #160.

#### Step 4.5 — Run tests to confirm section G passes

```bash
bash dark-factory/tests/test_scheduler.sh 2>&1 | grep -E "G[0-9]|Results"
```

Expected: G1–G5 all PASS.

#### Step 4.6 — Commit

```bash
git add dark-factory/scheduler.sh dark-factory/tests/test_scheduler.sh
git commit -m "feat(#183): spec auto-advance — grace window + direct-to-pr entry advance to Refined"
```

---

### Task 5: Direct-to-PR entry trigger in Priority 5 (TDD)

**Files:** `dark-factory/tests/test_scheduler.sh`, `dark-factory/scheduler.sh`

#### Step 5.1 — Write failing tests (section H)

The entry trigger extends the opt-in check so that `direct-to-pr` admits a Backlog item
alongside `ready-for-agent`. Tests:
1. Item with `direct-to-pr` (no `ready-for-agent`) → passes the entry gate
2. Item with `ready-for-agent` (no `direct-to-pr`) → still passes (existing behavior unchanged)
3. Item with neither → still blocked (regression guard)

Append to test_scheduler.sh:

```bash
# ==========================================
# H: Entry trigger — direct-to-pr admits Backlog items
# ==========================================
echo ""
echo "--- H: Entry trigger ---"

ITEM_DTP_ONLY='{"content":{"number":30},"labels":["direct-to-pr"],"status":"Backlog"}'
ITEM_RFA_ONLY='{"content":{"number":31},"labels":["ready-for-agent"],"status":"Backlog"}'
ITEM_NEITHER='{"content":{"number":32},"labels":["needs-triage"],"status":"Backlog"}'
ITEM_BOTH='{"content":{"number":33},"labels":["direct-to-pr","ready-for-agent"],"status":"Backlog"}'

# H1: direct-to-pr alone → passes entry gate
(has_opt_in_refine_label "$ITEM_DTP_ONLY" || has_direct_to_pr_label "$ITEM_DTP_ONLY") \
  && assert_eq "H1: direct-to-pr admits item" "0" "0" \
  || assert_eq "H1: direct-to-pr admits item" "0" "1"

# H2: ready-for-agent alone → still passes (unchanged)
(has_opt_in_refine_label "$ITEM_RFA_ONLY" || has_direct_to_pr_label "$ITEM_RFA_ONLY") \
  && assert_eq "H2: ready-for-agent still admits item" "0" "0" \
  || assert_eq "H2: ready-for-agent still admits item" "0" "1"

# H3: neither → blocked
(has_opt_in_refine_label "$ITEM_NEITHER" || has_direct_to_pr_label "$ITEM_NEITHER") \
  && assert_eq "H3: neither label is blocked" "0" "1" \
  || assert_eq "H3: neither label is blocked" "0" "0"

# H4: both labels → passes (direct-to-pr wins, no double-dispatch risk)
(has_opt_in_refine_label "$ITEM_BOTH" || has_direct_to_pr_label "$ITEM_BOTH") \
  && assert_eq "H4: both labels passes gate once" "0" "0" \
  || assert_eq "H4: both labels passes gate once" "0" "1"
```

#### Step 5.2 — Run tests to confirm section H fails

```bash
bash dark-factory/tests/test_scheduler.sh 2>&1 | grep -E "H[0-9]|Results"
```

Expected: H tests fail because `has_direct_to_pr_label` is not yet defined (it was added in
Task 3, so if Task 3 is done, H tests should already pass — if so, proceed to commit).

#### Step 5.3 — Extend opt-in entry gate in `dark-factory/scheduler.sh`

In Priority 5 Backlog loop, locate the existing gate:

```bash
    if ! has_opt_in_refine_label "$item"; then continue; fi
```

Replace with:

```bash
    if ! has_opt_in_refine_label "$item" && ! has_direct_to_pr_label "$item"; then continue; fi
```

#### Step 5.4 — Run tests to confirm section H passes

```bash
bash dark-factory/tests/test_scheduler.sh 2>&1 | grep -E "H[0-9]|Results"
```

Expected: H1–H4 all PASS.

#### Step 5.5 — Commit

```bash
git add dark-factory/scheduler.sh dark-factory/tests/test_scheduler.sh
git commit -m "feat(#183): direct-to-pr entry trigger — Backlog items with flag admitted to pipeline"
```

---

### Task 6: Plan auto-advance in Priority 4 (TDD)

**Files:** `dark-factory/tests/test_scheduler.sh`, `dark-factory/scheduler.sh`

#### Step 6.1 — Write failing tests (section I)

Symmetric to Task 4 but for `plan-pending-review` → advance to `Ready`. Tests:
1. Flag + human comment → re-plan dispatched
2. Flag + no comment + elapsed ≥ grace → advance to Ready (remove label + STATUS_READY)
3. Flag + no comment + elapsed < grace → no action
4. No flag → no auto-advance (regression guard)

Append to test_scheduler.sh:

```bash
# ==========================================
# I: Plan auto-advance (direct-to-pr)
# ==========================================
echo ""
echo "--- I: Plan auto-advance ---"
echo '{}' > "$STATE_FILE"; > "$STUB_LOG"

_ITEM_DTP_PPR='{"content":{"number":40},"labels":["direct-to-pr","plan-pending-review"],"status":"Refined"}'
_ITEM_NODTP_PPR='{"content":{"number":41},"labels":["plan-pending-review"],"status":"Refined"}'

# I1: flag + human comment → re-plan
has_new_comment_after_report() { echo "yes"; }
dispatch() { echo "dispatch $*" >> "$STUB_LOG"; return 0; }
export -f has_new_comment_after_report dispatch

plan_advance_check 40 "$_ITEM_DTP_PPR"
assert_eq "I1: re-plan: remove-label called" \
  "1" "$(grep -c -- '--remove-label plan-pending-review' "$STUB_LOG" || echo 0)"
assert_eq "I1: re-plan: Plan dispatched" \
  "1" "$(grep -c 'dispatch Plan issue #40' "$STUB_LOG" || echo 0)"

> "$STUB_LOG"
# I2: flag + no comment + elapsed ≥ grace → advance to Ready
has_new_comment_after_report() { echo "no"; }
export PLAN_GRACE_MINUTES=30
elapsed_minutes_since_marker() { echo "35"; }
export -f has_new_comment_after_report elapsed_minutes_since_marker

plan_advance_check 40 "$_ITEM_DTP_PPR"
assert_eq "I2: advance: remove-label called" \
  "1" "$(grep -c -- '--remove-label plan-pending-review' "$STUB_LOG" || echo 0)"
assert_eq "I2: advance: set_board_status READY" \
  "1" "$(grep -c "set_board_status 40 ${STATUS_READY}" "$STUB_LOG" || echo 0)"

> "$STUB_LOG"
# I3: flag + no comment + elapsed < grace → no action
elapsed_minutes_since_marker() { echo "10"; }
export -f elapsed_minutes_since_marker

plan_advance_check 40 "$_ITEM_DTP_PPR"
assert_eq "I3: within-window: no set_board_status" \
  "0" "$(grep -c 'set_board_status' "$STUB_LOG" || echo 0)"
assert_eq "I3: within-window: no dispatch" \
  "0" "$(grep -c 'dispatch' "$STUB_LOG" || echo 0)"

> "$STUB_LOG"
# I4: no flag → no auto-advance (regression guard)
elapsed_minutes_since_marker() { echo "99"; }
export -f elapsed_minutes_since_marker

plan_advance_check 41 "$_ITEM_NODTP_PPR"
assert_eq "I4: no-flag regression: no advance" \
  "0" "$(grep -c 'set_board_status' "$STUB_LOG" || echo 0)"

> "$STUB_LOG"
# I5: flag + needs-discussion → suppressed (no advance, even with elapsed ≥ grace)
_ITEM_DTP_PPR_ND='{"content":{"number":42},"labels":["direct-to-pr","plan-pending-review","needs-discussion"],"status":"Refined"}'
elapsed_minutes_since_marker() { echo "99"; }
export -f elapsed_minutes_since_marker

plan_advance_check 42 "$_ITEM_DTP_PPR_ND"
assert_eq "I5: needs-discussion suppresses plan advance" \
  "0" "$(grep -c 'set_board_status' "$STUB_LOG" || echo 0)"
assert_eq "I5: needs-discussion suppresses plan dispatch" \
  "0" "$(grep -c 'dispatch' "$STUB_LOG" || echo 0)"

# Restore
has_new_comment_after_report() { echo "no"; }
elapsed_minutes_since_marker() { echo ""; }
dispatch() { echo "dispatch $*" >> "$STUB_LOG"; return 0; }
export -f has_new_comment_after_report elapsed_minutes_since_marker dispatch
```

#### Step 6.2 — Run tests to confirm section I fails

```bash
bash dark-factory/tests/test_scheduler.sh 2>&1 | grep -E "I[0-9]|Results"
```

Expected: I tests fail (`plan_advance_check` not defined).

#### Step 6.3 — Add `plan_advance_check` function and wire into Priority 4

Add to `dark-factory/scheduler.sh` after `spec_advance_check`:

```bash
# Handle plan-pending-review for a direct-to-pr ticket.
# Assumes: caller already verified the item has plan-pending-review AND direct-to-pr.
# Side-effects: may set DISPATCHED, increment REFINE_RUNNING, call dispatch/set_board_status.
plan_advance_check() {
  local issue_num="$1"
  local item="$2"
  # needs-discussion and epic suppress all automation — even for direct-to-pr items.
  has_skip_label "$item" && return 0
  local has_new
  has_new=$(has_new_comment_after_report "$issue_num" "Posted by MarketHawk Refinement Pipeline")
  if [ "$has_new" = "yes" ]; then
    reset_retry "${issue_num}:plan"
    gh issue edit "$issue_num" --repo "${OWNER}/markethawk" \
      --remove-label "plan-pending-review" 2>/dev/null || true
    gh issue comment "$issue_num" --repo "${OWNER}/markethawk" --body \
"🔄 **Refinement Pipeline** — Re-running plan with new feedback.

---
*Posted by MarketHawk Backlog Scheduler*" 2>/dev/null || true
    if dispatch "Plan issue #${issue_num}"; then
      DISPATCHED="Plan issue #${issue_num}"
      REFINE_RUNNING=$((REFINE_RUNNING + 1))
    fi
    return 0
  fi
  local elapsed
  elapsed=$(elapsed_minutes_since_marker "$issue_num" "Posted by MarketHawk Refinement Pipeline")
  if [ -n "$elapsed" ] && [ "$elapsed" -ge "$PLAN_GRACE_MINUTES" ]; then
    echo "[$(date -u +%FT%TZ)] plan_auto_advance issue=#${issue_num} elapsed=${elapsed}m grace=${PLAN_GRACE_MINUTES}m action=advance_to_ready"
    gh issue edit "$issue_num" --repo "${OWNER}/markethawk" \
      --remove-label "plan-pending-review" 2>/dev/null || true
    set_board_status "$issue_num" "$STATUS_READY" || true
  else
    echo "[$(date -u +%FT%TZ)] plan_grace_window issue=#${issue_num} elapsed=${elapsed:-unknown}m grace=${PLAN_GRACE_MINUTES}m action=waiting"
  fi
}
```

In the Priority 4 Refined loop, add the plan-advance tier **before** the existing
`has_refine_skip_label` check:

**Before:**
```bash
  while IFS= read -r item; do
    [ -n "$DISPATCHED" ] && break
    ISSUE=$(get_issue_number "$item")
    if has_refine_skip_label "$item"; then continue; fi
    ...
```

**After:**
```bash
  while IFS= read -r item; do
    [ -n "$DISPATCHED" ] && break
    ISSUE=$(get_issue_number "$item")

    # Direct-to-PR plan auto-advance: handle before refine_skip_label blocks plan-pending-review
    if echo "$item" | jq -r '.labels[]?' 2>/dev/null | grep -qi "plan-pending-review" \
       && has_direct_to_pr_label "$item"; then
      if ! is_issue_running "$ISSUE" && [ "$REFINE_RUNNING" -lt "$REFINE_WIP_LIMIT" ]; then
        plan_advance_check "$ISSUE" "$item"
      fi
      continue
    fi

    if has_refine_skip_label "$item"; then continue; fi
    ...
```

#### Step 6.4 — Run tests to confirm section I passes

```bash
bash dark-factory/tests/test_scheduler.sh 2>&1 | grep -E "I[0-9]|Results"
```

Expected: I1–I5 all PASS.

#### Step 6.5 — Commit

```bash
git add dark-factory/scheduler.sh dark-factory/tests/test_scheduler.sh
git commit -m "feat(#183): plan auto-advance — grace window + direct-to-pr advance to Ready"
```

---

### Task 7: End-gate auto-merge in Priority 1 (TDD)

**Files:** `dark-factory/tests/test_scheduler.sh`, `dark-factory/scheduler.sh`

#### Step 7.1 — Write failing tests (section J)

Tests:
1. Flag + APPROVED PR review → dispatch `Close issue #N`
2. Flag + CHANGES_REQUESTED PR review → dispatch `Continue issue #N`
3. Flag + no actionable review (PENDING/COMMENTED/no reviews) → no dispatch (fall through)
4. No flag + APPROVED review → no end-gate dispatch (regression guard)

Append to test_scheduler.sh:

```bash
# ==========================================
# J: End-gate auto-merge (direct-to-pr)
# ==========================================
echo ""
echo "--- J: End-gate auto-merge ---"
echo '{}' > "$STATE_FILE"; > "$STUB_LOG"

_ITEM_DTP_REVIEW='{"content":{"number":50},"labels":["direct-to-pr"],"status":"In review"}'
_ITEM_NODTP_REVIEW='{"content":{"number":51},"labels":[],"status":"In review"}'

# J1: flag + APPROVED → Close dispatched
# Stubs return what `gh pr view --json reviews --jq '...'` returns after filtering:
# just the state string (not a JSON object). The case statement in end_gate_check
# matches against this string directly.
get_pr_for_issue() { echo "99"; }
gh() {
  case "$*" in
    *"pr view"*) echo "APPROVED" ;;
    *) echo "gh $*" >> "$STUB_LOG" ;;
  esac
  return 0
}
dispatch() { echo "dispatch $*" >> "$STUB_LOG"; return 0; }
export -f get_pr_for_issue gh dispatch

end_gate_check 50 "$_ITEM_DTP_REVIEW"
assert_eq "J1: APPROVED → Close dispatched" \
  "1" "$(grep -c 'dispatch Close issue #50' "$STUB_LOG" || echo 0)"

> "$STUB_LOG"
# J2: flag + CHANGES_REQUESTED → Continue dispatched
gh() {
  case "$*" in
    *"pr view"*) echo "CHANGES_REQUESTED" ;;
    *) echo "gh $*" >> "$STUB_LOG" ;;
  esac
  return 0
}
export -f gh

end_gate_check 50 "$_ITEM_DTP_REVIEW"
assert_eq "J2: CHANGES_REQUESTED → Continue dispatched" \
  "1" "$(grep -c 'dispatch Continue issue #50' "$STUB_LOG" || echo 0)"

> "$STUB_LOG"
# J3: flag + no actionable review → no dispatch (fall through)
# Stub returns empty string: no APPROVED/CHANGES_REQUESTED reviews exist
gh() {
  case "$*" in
    *"pr view"*) echo "" ;;
    *) echo "gh $*" >> "$STUB_LOG" ;;
  esac
  return 0
}
export -f gh

end_gate_check 50 "$_ITEM_DTP_REVIEW"
assert_eq "J3: no review → no dispatch" \
  "0" "$(grep -c 'dispatch' "$STUB_LOG" || echo 0)"

> "$STUB_LOG"
# J4: no flag → no end-gate dispatch (regression guard)
gh() {
  case "$*" in
    *"pr view"*) echo "APPROVED" ;;
    *) echo "gh $*" >> "$STUB_LOG" ;;
  esac
  return 0
}
export -f gh

end_gate_check 51 "$_ITEM_NODTP_REVIEW"
assert_eq "J4: no-flag: no end-gate dispatch" \
  "0" "$(grep -c 'dispatch Close' "$STUB_LOG" || echo 0)"

# Restore
gh() { echo "gh $*" >> "$STUB_LOG"; return 0; }
get_pr_for_issue() { echo ""; }
dispatch() { echo "dispatch $*" >> "$STUB_LOG"; return 0; }
export -f gh get_pr_for_issue dispatch
```

#### Step 7.2 — Run tests to confirm section J fails

```bash
bash dark-factory/tests/test_scheduler.sh 2>&1 | grep -E "J[0-9]|Results"
```

Expected: J tests fail (`end_gate_check` not defined).

#### Step 7.3 — Add `end_gate_check` function to `dark-factory/scheduler.sh`

Add after `plan_advance_check`:

```bash
# Check PR review state for a direct-to-pr In Review ticket and dispatch accordingly.
# Returns 0 if action was taken (APPROVED or CHANGES_REQUESTED) — caller should continue.
# Returns 1 if no actionable review — caller should fall through to comment classification.
# No-op (returns 1) if the item does not have the direct-to-pr label.
end_gate_check() {
  local issue_num="$1"
  local item="$2"
  has_direct_to_pr_label "$item" || return 1
  local pr_num
  pr_num=$(get_pr_for_issue "$issue_num")
  [ -z "$pr_num" ] && return 1
  local review_state
  review_state=$(gh pr view "$pr_num" --repo "${OWNER}/markethawk" --json reviews \
    --jq '[.reviews[] | select(.state == "APPROVED" or .state == "CHANGES_REQUESTED")] | last | .state // ""' \
    2>/dev/null) || review_state=""
  case "$review_state" in
    APPROVED)
      echo "[$(date -u +%FT%TZ)] end_gate issue=#${issue_num} pr=#${pr_num} state=APPROVED action=Close"
      if dispatch "Close issue #${issue_num}"; then
        DISPATCHED="Close issue #${issue_num}"
      fi
      return 0
      ;;
    CHANGES_REQUESTED)
      echo "[$(date -u +%FT%TZ)] end_gate issue=#${issue_num} pr=#${pr_num} state=CHANGES_REQUESTED action=Continue"
      if ! is_issue_running "$issue_num"; then
        if dispatch "Continue issue #${issue_num}"; then
          DISPATCHED="Continue issue #${issue_num}"
          reset_retry "$issue_num"
        fi
      fi
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}
```

In the Priority 1 In Review loop, add the end-gate check **after** the skip-label/CI-blocked
guards and **before** `get_new_comments`:

**Before:**
```bash
    NEW_COMMENTS=$(get_new_comments "$ISSUE")
    COMMENT_COUNT=$(echo "$NEW_COMMENTS" | jq 'length')
    if [ "$COMMENT_COUNT" -eq 0 ]; then continue; fi
```

**After:**
```bash
    if end_gate_check "$ISSUE" "$item"; then continue; fi

    NEW_COMMENTS=$(get_new_comments "$ISSUE")
    COMMENT_COUNT=$(echo "$NEW_COMMENTS" | jq 'length')
    if [ "$COMMENT_COUNT" -eq 0 ]; then continue; fi
```

#### Step 7.4 — Run tests to confirm section J passes

```bash
bash dark-factory/tests/test_scheduler.sh 2>&1 | grep -E "J[0-9]|Results"
```

Expected: J1–J4 all PASS.

#### Step 7.5 — Run full test suite

```bash
bash dark-factory/tests/test_scheduler.sh
```

Expected: all sections A–J pass with 0 failures.

#### Step 7.6 — Commit

```bash
git add dark-factory/scheduler.sh dark-factory/tests/test_scheduler.sh
git commit -m "feat(#183): end-gate auto-merge — approved PR triggers Close, changes-requested triggers Continue"
```

---

### Task 8: Cosmetic auto-advance note in refine/plan command files

**Files:** `.archon/commands/dark-factory-refine.md`, `.archon/commands/dark-factory-plan.md`

#### Step 8.1 — Update Phase 6 PUBLISH in `dark-factory-refine.md`

In Phase 6 (PUBLISH — **note: PUBLISH is Phase 6 in `dark-factory-refine.md`, not Phase 4**),
step 3 posts the spec summary comment. Before posting, add a step to detect the `direct-to-pr`
label and adjust the "Next Steps" section.

Replace the "Next Steps" block in the spec comment template:

**Before:**
```
   ### Next Steps

   - ✅ **Approve spec** — move the issue to the **Refined** column on the project board. The scheduler will automatically trigger plan generation.
   - ✏️ **Request changes** — leave a comment on this issue with your feedback, then re-run:
     ```bash
     docker compose --profile factory run --rm dark-factory "Refine issue #$ISSUE_NUM"
     ```
   - ❓ **Need to discuss** — add the `needs-discussion` label to pause automation.
```

**After:**
```
   ### Next Steps

   <!-- If the issue has the direct-to-pr label, prepend this line: -->
   ⏩ **Auto-advancing in ~`$SPEC_GRACE_MINUTES` min** unless you comment — the scheduler will move this to **Refined** automatically once the grace window elapses. Leave a comment to re-run the spec or override the direction.

   - ✅ **Approve spec** — move the issue to the **Refined** column on the project board. The scheduler will automatically trigger plan generation.
   - ✏️ **Request changes** — leave a comment on this issue with your feedback, then re-run:
     ```bash
     docker compose --profile factory run --rm dark-factory "Refine issue #$ISSUE_NUM"
     ```
   - ❓ **Need to discuss** — add the `needs-discussion` label to pause automation.
```

Then add an instruction step in Phase 4, before step 3 (the comment post):

```
3a. Check if the issue carries the `direct-to-pr` label:
    ```bash
    IS_DIRECT_TO_PR=$(gh issue view $ISSUE_NUM --repo omniscient/markethawk \
      --json labels --jq '.labels[].name' | grep -q "direct-to-pr" && echo "yes" || echo "no")
    ```
    If `IS_DIRECT_TO_PR=yes`, prepend the auto-advance note (with the actual `SPEC_GRACE_MINUTES`
    value, read from `.claude/skills/refinement/config.yaml` or defaulting to `30`) to the
    "### Next Steps" section of the posted comment.
```

#### Step 8.2 — Update Phase 4 PUBLISH in `dark-factory-plan.md`

Apply the same change symmetrically — check for `direct-to-pr`, and if present, prepend:

```
⏩ **Auto-advancing in ~`$PLAN_GRACE_MINUTES` min** unless you comment — the scheduler will move this to **Ready** automatically. Leave a comment to re-run the plan or redirect.
```

Add the same step 5a (label-check before the comment post) to the plan command's Phase 4.

#### Step 8.3 — Commit

```bash
git add .archon/commands/dark-factory-refine.md .archon/commands/dark-factory-plan.md
git commit -m "feat(#183): cosmetic auto-advance note in spec/plan posted comments for direct-to-pr tickets"
```

---

## Verification Commands

```bash
# Run all scheduler tests
bash dark-factory/tests/test_scheduler.sh

# Spot-check env vars are set and readable
SCHEDULER_SOURCE_ONLY=1 GH_TOKEN=stub CLAUDE_CODE_OAUTH_TOKEN=stub \
  source dark-factory/scheduler.sh && \
  echo "DIRECT_TO_PR_LABEL=${DIRECT_TO_PR_LABEL}" && \
  echo "SPEC_GRACE_MINUTES=${SPEC_GRACE_MINUTES}" && \
  echo "PLAN_GRACE_MINUTES=${PLAN_GRACE_MINUTES}"

# Validate config YAML
python3 -c "import yaml; yaml.safe_load(open('.claude/skills/refinement/config.yaml')); print('OK')"

# Confirm label exists on GitHub
gh label list --repo omniscient/markethawk | grep direct-to-pr
```

---

## Summary

| Task | Files | Key Change |
|------|-------|------------|
| 1 | `docs/agents/triage-labels.md` | Create label, document workflow flag |
| 2 | `scheduler.sh`, `config.yaml`, `ENV_VARIABLES.md` | Env vars, remove vestigial key |
| 3 | `scheduler.sh`, `test_scheduler.sh` | `has_direct_to_pr_label`, `elapsed_minutes_since_marker` |
| 4 | `scheduler.sh`, `test_scheduler.sh` | `spec_advance_check` + Priority 5 wiring |
| 5 | `scheduler.sh`, `test_scheduler.sh` | Entry trigger opt-in gate extension |
| 6 | `scheduler.sh`, `test_scheduler.sh` | `plan_advance_check` + Priority 4 wiring |
| 7 | `scheduler.sh`, `test_scheduler.sh` | `end_gate_check` + Priority 1 wiring |
| 8 | `dark-factory-refine.md`, `dark-factory-plan.md` | Cosmetic auto-advance note |
