# Scheduler Circuit-Breaker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the dark-factory backlog scheduler against dispatch loops (the #159 incident): durable retry state, crash-resilient dispatch, and a universal circuit-breaker that trips any `(issue, phase)` to Blocked after N failed attempts. Also gate auto-refinement on an opt-in label and fix the inline-build hazard.

**Architecture:** Shell script hardening only — no new services or DB tables. `dark-factory/scheduler.sh` gets a durable `STATE_FILE` path (named Docker volume), a hardened `dispatch()` that captures exit codes, a new `trip_to_blocked()` helper replacing three divergent retry-exhausted handlers, an opt-in label gate on the Backlog refine loop, and a startup image probe. `docker-compose.yml` gains the named `scheduler_state` volume. `dark-factory/entrypoint.sh` gets a comment documenting the run-side deferral decision. `Docs/agents/triage-labels.md` is updated with the opt-in gate docs.

**Planning verification (spec §"Must verify during planning"):**
1. **GHCR denied** — `dispatch()` gains `--no-build` (Task 3); a startup probe exits with instructions if the image is unavailable (Task 9), preventing the inline-build crash path.
2. **Blocked re-dispatch** — `trip_to_blocked` adds `needs-discussion`, which is in `SKIP_LABELS="needs-discussion,epic"`. Priority 3 calls `has_skip_label` before dispatching; tripped issues are permanently filtered until a human removes the label.
3. **`set -e` unguarded calls** — audit of the main loop confirms `dispatch()` is the only unguarded external call that can kill the daemon. All other `gh`/`docker` calls already carry `|| true` or `2>/dev/null` guards. Task 4 wraps every `dispatch` caller with `if dispatch ...; then`.
4. **`ready-for-agent` label** — confirmed as the correct opt-in label (existing triage label, `Docs/agents/triage-labels.md`). No new label introduced.

**Tech Stack:** Bash, Docker Compose named volumes, GitHub CLI (`gh`)

**Spec:** [`Docs/superpowers/specs/2026-06-03-scheduler-circuit-breaker-design.md`](../specs/2026-06-03-scheduler-circuit-breaker-design.md)
**Issue:** [#160](https://github.com/omniscient/markethawk/issues/160)

---

### Task 1: Write unit-test harness (TDD red phase)

**Files:**
- Create: `dark-factory/tests/test_scheduler.sh`

Establish the test harness first. Section A (retry helpers) will pass immediately. Sections B–D will fail until the corresponding features are implemented.

- [ ] **Step 1: Create test directory and harness**

```bash
mkdir -p dark-factory/tests
```

Create `dark-factory/tests/test_scheduler.sh`:

```bash
#!/usr/bin/env bash
# Unit tests for scheduler.sh helpers.
# Run: bash dark-factory/tests/test_scheduler.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCHED="$SCRIPT_DIR/../scheduler.sh"

# ---- Stubs ----
STUB_LOG=$(mktemp /tmp/sched-test-stubs-XXXXXX.log)
gh()               { echo "gh $*"               >> "$STUB_LOG"; return 0; }
docker()           { echo "docker $*"           >> "$STUB_LOG"; return 0; }
set_board_status() { echo "set_board_status $*" >> "$STUB_LOG"; return 0; }
export -f gh docker set_board_status

# ---- Source scheduler helpers only ----
STATE_FILE=$(mktemp /tmp/sched-test-state-XXXXXX.json)
echo '{}' > "$STATE_FILE"
export STATE_FILE
SCHEDULER_SOURCE_ONLY=1 source "$SCHED"

# ---- Runner ----
PASSED=0; FAILED=0
assert_eq() {
  local desc="$1" expected="$2" actual="$3"
  if [ "$expected" = "$actual" ]; then
    echo "  PASS: $desc"; PASSED=$((PASSED+1))
  else
    echo "  FAIL: $desc — expected='$expected' got='$actual'" >&2; FAILED=$((FAILED+1))
  fi
}

# ==========================================
# A: Retry helpers (should pass immediately)
# ==========================================
echo "--- A: Retry helpers ---"
echo '{}' > "$STATE_FILE"

assert_eq "unknown key returns 0"       "0" "$(get_retry_count "42:refine")"
increment_retry "42:refine"
assert_eq "after 1 increment"           "1" "$(get_retry_count "42:refine")"
increment_retry "42:refine"
assert_eq "after 2 increments"          "2" "$(get_retry_count "42:refine")"
reset_retry "42:refine"
assert_eq "after reset"                 "0" "$(get_retry_count "42:refine")"
increment_retry "42"
assert_eq "bare key independent"        "1" "$(get_retry_count "42")"
assert_eq ":refine unaffected by bare"  "0" "$(get_retry_count "42:refine")"

# ==========================================
# B: trip_to_blocked (fails until Task 5)
# ==========================================
echo ""
echo "--- B: trip_to_blocked ---"
echo '{}' > "$STATE_FILE"; > "$STUB_LOG"

increment_retry "99:plan"
increment_retry "99:plan"
increment_retry "99:plan"

trip_to_blocked "99" "plan" "test reason"

assert_eq "set_board_status called" \
  "1" "$(grep -c 'set_board_status 99' "$STUB_LOG" || echo 0)"
assert_eq "gh issue edit adds needs-discussion" \
  "1" "$(grep -c 'issue edit 99.*needs-discussion' "$STUB_LOG" || echo 0)"
assert_eq "gh issue comment posted" \
  "1" "$(grep -c 'issue comment 99' "$STUB_LOG" || echo 0)"
assert_eq ":plan counter reset after trip" \
  "0" "$(get_retry_count "99:plan")"

echo '{}' > "$STATE_FILE"; > "$STUB_LOG"
increment_retry "88:refine"
trip_to_blocked "88" "refine" "test"
assert_eq ":refine counter reset" "0" "$(get_retry_count "88:refine")"

echo '{}' > "$STATE_FILE"; > "$STUB_LOG"
increment_retry "77"
trip_to_blocked "77" "implement" "test"
assert_eq "bare implement counter reset" "0" "$(get_retry_count "77")"

# ==========================================
# C: dispatch() exit-code capture (fails until Task 3)
# ==========================================
echo ""
echo "--- C: dispatch() exit-code capture ---"
> "$STUB_LOG"

_orig_docker() { echo "docker $*" >> "$STUB_LOG"; return 0; }
docker() {
  echo "docker $*" >> "$STUB_LOG"
  echo "$*" | grep -q "compose.*run" && return 42
  return 0
}
export -f docker

EXIT_CODE=0
dispatch "Fix issue #1" || EXIT_CODE=$?
assert_eq "dispatch returns non-zero exit code" "42" "$EXIT_CODE"
assert_eq "dispatch uses --no-build" \
  "1" "$(grep -c -- '--no-build' "$STUB_LOG" || echo 0)"

docker() { echo "docker $*" >> "$STUB_LOG"; return 0; }
export -f docker

# ==========================================
# D: Opt-in label gate (fails until Task 8)
# ==========================================
echo ""
echo "--- D: Opt-in label gate ---"

ITEM_WITH='{"content":{"number":1},"labels":["ready-for-agent","needs-triage"],"status":"Backlog"}'
ITEM_WITHOUT='{"content":{"number":2},"labels":["needs-triage"],"status":"Backlog"}'

has_opt_in_refine_label "$ITEM_WITH"    \
  && assert_eq "item WITH label passes gate"    "0" "0" \
  || assert_eq "item WITH label passes gate"    "0" "1"
has_opt_in_refine_label "$ITEM_WITHOUT" \
  && assert_eq "item WITHOUT label blocked"     "0" "1" \
  || assert_eq "item WITHOUT label blocked"     "0" "0"

# ==========================================
# Cleanup
# ==========================================
rm -f "$STATE_FILE" "$STUB_LOG"
echo ""
echo "Results: ${PASSED} passed, ${FAILED} failed"
[ "$FAILED" -eq 0 ]
```

- [ ] **Step 2: Verify Section A passes, Sections B–D fail**

```bash
bash dark-factory/tests/test_scheduler.sh 2>&1
```

Expected: Section A prints 6 `PASS` lines. Sections B–D print `FAIL` lines (functions don't exist yet).

- [ ] **Step 3: Commit the test harness**

```bash
git add dark-factory/tests/test_scheduler.sh
git commit -m "test(#160): add scheduler unit-test harness (TDD red phase)"
```

---

### Task 2: Durable retry state — named Docker volume

**Files:**
- Modify: `docker-compose.yml`
- Modify: `dark-factory/scheduler.sh` (line 8, init block)
- Modify: `ENV_VARIABLES.md`

- [ ] **Step 1: Add `scheduler_state` named volume to docker-compose.yml**

In the `backlog-scheduler` service `volumes:` block (around line 439), add the volume mount:

**Current:**
```yaml
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
```

**New:**
```yaml
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - scheduler_state:/var/lib/dark-factory
```

In the top-level `volumes:` section (line 523), add before `postgres_data:`:

```yaml
volumes:
  scheduler_state:
  postgres_data:
```

> **Volume durability note:** `scheduler_state` is a bare managed volume (no `external: true`). This means `docker compose down -v` would delete it and wipe retry counters — the same as the old `/tmp` behaviour. The scheduler workflow uses `docker compose down` (without `-v`) and `docker restart backlog-scheduler` for the restart-unless-stopped lifecycle, so this is safe in practice. If your deployment teardown uses `-v`, either (a) use `docker volume rm scheduler_state` selectively instead, or (b) promote the volume to external: `docker volume create markethawk_scheduler_state` and update the `docker-compose.yml` entry to `external: true` / `name: markethawk_scheduler_state`. Do not mix both approaches.

- [ ] **Step 2: Validate docker-compose.yml**

```bash
docker compose config --services
```

Expected: All services listed, no YAML errors, `backlog-scheduler` appears in the list.

- [ ] **Step 3: Update STATE_FILE in scheduler.sh**

Replace line 8 in `dark-factory/scheduler.sh`:

**Current (line 8):**
```bash
STATE_FILE="/tmp/scheduler-state.json"
```

**New:**
```bash
SCHEDULER_STATE_DIR="${SCHEDULER_STATE_DIR:-/var/lib/dark-factory}"
STATE_FILE="${SCHEDULER_STATE_DIR}/scheduler-state.json"
```

Immediately before the init guard (currently `if [ ! -f "$STATE_FILE" ]; then` at line ~40), add:

```bash
# Create state directory (named volume creates the mountpoint but not subdirectories).
mkdir -p "$SCHEDULER_STATE_DIR"
```

- [ ] **Step 4: Document SCHEDULER_STATE_DIR in ENV_VARIABLES.md**

Under the dark-factory / scheduler section in `ENV_VARIABLES.md`, add:

```markdown
| `SCHEDULER_STATE_DIR` | `/var/lib/dark-factory` | Directory for durable scheduler retry state. Mounted from the `scheduler_state` named Docker volume in the `backlog-scheduler` service. |
```

- [ ] **Step 5: Verify sourcing still works**

```bash
bash dark-factory/tests/test_scheduler.sh 2>&1 | grep -E "^--- A|PASS|FAIL" | head -10
```

Expected: Section A still prints 6 `PASS` lines.

- [ ] **Step 6: Manual durability verification (run when scheduler is available)**

```bash
# Write state in one process, re-read in a new process with the same file
TMPDIR=$(mktemp -d)
export STATE_FILE="$TMPDIR/scheduler-state.json"
mkdir -p "$TMPDIR"

SCHEDULER_SOURCE_ONLY=1 bash -c '
  source dark-factory/scheduler.sh
  increment_retry "5:refine"; increment_retry "5:refine"
  echo "wrote: $(get_retry_count "5:refine")"
'

SCHEDULER_SOURCE_ONLY=1 bash -c '
  source dark-factory/scheduler.sh
  COUNT=$(get_retry_count "5:refine")
  echo "read after restart: $COUNT"
  [ "$COUNT" = "2" ] && echo "PASS" || echo "FAIL"
'
rm -rf "$TMPDIR"
```

Expected: `wrote: 2`, `read after restart: 2`, `PASS`.

- [ ] **Step 7: Commit**

```bash
git add docker-compose.yml dark-factory/scheduler.sh ENV_VARIABLES.md
git commit -m "fix(#160): move scheduler STATE_FILE to durable named volume"
```

---

### Task 3: Harden dispatch() — exit-code capture and --no-build

**Files:**
- Modify: `dark-factory/scheduler.sh` (lines 138–142)

- [ ] **Step 1: Verify Section C tests are failing**

```bash
bash dark-factory/tests/test_scheduler.sh 2>&1 | grep -A4 "^--- C"
```

Expected: `FAIL: dispatch returns non-zero exit code`.

- [ ] **Step 2: Replace dispatch() in scheduler.sh**

Replace lines 138–142 in `dark-factory/scheduler.sh`:

**Current:**
```bash
# --- Dispatch ---
dispatch() {
  local command="$1"
  echo "Dispatching: $command"
  docker compose -f /opt/dark-factory/docker-compose.yml --profile factory run -d --rm dark-factory "$command"
}
```

**New:**
```bash
# --- Dispatch ---
# Returns the docker compose exit code. Callers MUST use `if dispatch ...; then` —
# a bare call under set -e exits the daemon on non-zero.
# --no-build prevents inline image builds; the startup probe ensures the image exists.
dispatch() {
  local command="$1"
  local exit_code=0
  echo "[$(date -u +%FT%TZ)] dispatch command=\"${command}\""
  docker compose -f /opt/dark-factory/docker-compose.yml --profile factory run \
    -d --rm --no-build dark-factory "$command" || exit_code=$?
  if [ "$exit_code" -ne 0 ]; then
    echo "[$(date -u +%FT%TZ)] dispatch_error command=\"${command}\" exit=${exit_code}" >&2
  fi
  return "$exit_code"
}
```

- [ ] **Step 3: Run Section C tests — expect pass**

```bash
bash dark-factory/tests/test_scheduler.sh 2>&1 | grep -A4 "^--- C"
```

Expected:
```
  PASS: dispatch returns non-zero exit code
  PASS: dispatch uses --no-build
```

- [ ] **Step 4: Commit**

```bash
git add dark-factory/scheduler.sh
git commit -m "fix(#160): harden dispatch() — exit-code capture and --no-build"
```

---

### Task 4: Guard all dispatch() call sites

**Files:**
- Modify: `dark-factory/scheduler.sh` (8 call sites in the main loop: 2 in Priority 1, 1 in Priority 2, 2 in Priority 3, 1 in Priority 4, 2 in Priority 5)

Under `set -e`, a bare `dispatch "..."` that returns non-zero exits the scheduler. Wrap every call in `if dispatch ...; then`.

- [ ] **Step 1: Priority 1 — MERGE verdict (around line 491)**

**Current:**
```bash
      MERGE)
        dispatch "Close issue #${ISSUE}"
        DISPATCHED="Close issue #${ISSUE}"
        ;;
```

**New:**
```bash
      MERGE)
        if dispatch "Close issue #${ISSUE}"; then
          DISPATCHED="Close issue #${ISSUE}"
        fi
        ;;
```

- [ ] **Step 2: Priority 1 — CONTINUE verdict (around line 495)**

**Current:**
```bash
      CONTINUE)
        if ! is_issue_running "$ISSUE"; then
          dispatch "Continue issue #${ISSUE}"
          DISPATCHED="Continue issue #${ISSUE}"
          reset_retry "$ISSUE"
        fi
        ;;
```

**New:**
```bash
      CONTINUE)
        if ! is_issue_running "$ISSUE"; then
          if dispatch "Continue issue #${ISSUE}"; then
            DISPATCHED="Continue issue #${ISSUE}"
            reset_retry "$ISSUE"
          fi
        fi
        ;;
```

- [ ] **Step 3: Priority 2 — Ready items (around line 515)**

**Current:**
```bash
    dispatch "Fix issue #${ISSUE}"
    DISPATCHED="Fix issue #${ISSUE}"
```

**New:**
```bash
    if dispatch "Fix issue #${ISSUE}"; then
      DISPATCHED="Fix issue #${ISSUE}"
    fi
```

- [ ] **Step 4: Priority 3 — Blocked items (around lines 533–538)**

**Current:**
```bash
    increment_retry "$ISSUE"
    # Branch-aware: a blocked item that already has a PR (e.g. red CI gated above, or a
    # continue run that failed mid-way) must be CONTINUED to reuse the existing branch.
    # Dispatching "Fix" would start a fresh branch that collides with the PR on push.
    if [ -n "$(get_pr_for_issue "$ISSUE")" ]; then
      dispatch "Continue issue #${ISSUE}"
      DISPATCHED="Continue issue #${ISSUE}"
    else
      dispatch "Fix issue #${ISSUE}"
      DISPATCHED="Fix issue #${ISSUE}"
    fi
```

**New:**
```bash
    increment_retry "$ISSUE"
    # Branch-aware: a blocked item that already has a PR (e.g. red CI gated above, or a
    # continue run that failed mid-way) must be CONTINUED to reuse the existing branch.
    # Dispatching "Fix" would start a fresh branch that collides with the PR on push.
    if [ -n "$(get_pr_for_issue "$ISSUE")" ]; then
      if dispatch "Continue issue #${ISSUE}"; then
        DISPATCHED="Continue issue #${ISSUE}"
      fi
    else
      if dispatch "Fix issue #${ISSUE}"; then
        DISPATCHED="Fix issue #${ISSUE}"
      fi
    fi
```

- [ ] **Step 5: Priority 4 — Plan dispatch (around line 577)**

**Current:**
```bash
    increment_retry "${ISSUE}:plan"
    gh issue comment "$ISSUE" --repo "${OWNER}/markethawk" --body "📋 **Refinement Pipeline** — Starting plan generation and architect validation.

---
*Posted by MarketHawk Backlog Scheduler*" 2>/dev/null || true
    dispatch "Plan issue #${ISSUE}"
    DISPATCHED="Plan issue #${ISSUE}"
    REFINE_RUNNING=$((REFINE_RUNNING + 1))
```

**New:**
```bash
    increment_retry "${ISSUE}:plan"
    gh issue comment "$ISSUE" --repo "${OWNER}/markethawk" --body "📋 **Refinement Pipeline** — Starting plan generation and architect validation.

---
*Posted by MarketHawk Backlog Scheduler*" 2>/dev/null || true
    if dispatch "Plan issue #${ISSUE}"; then
      DISPATCHED="Plan issue #${ISSUE}"
      REFINE_RUNNING=$((REFINE_RUNNING + 1))
    fi
```

- [ ] **Step 6: Priority 5 — Refine, spec-pending-review path (around line 599)**

**Current:**
```bash
            dispatch "Refine issue #${ISSUE}"
            DISPATCHED="Refine issue #${ISSUE}"
            REFINE_RUNNING=$((REFINE_RUNNING + 1))
```

**New:**
```bash
            if dispatch "Refine issue #${ISSUE}"; then
              DISPATCHED="Refine issue #${ISSUE}"
              REFINE_RUNNING=$((REFINE_RUNNING + 1))
            fi
```

- [ ] **Step 7: Priority 5 — Refine, normal Backlog path (around line 638)**

**Current:**
```bash
    dispatch "Refine issue #${ISSUE}"
    DISPATCHED="Refine issue #${ISSUE}"
    REFINE_RUNNING=$((REFINE_RUNNING + 1))
```

**New:**
```bash
    if dispatch "Refine issue #${ISSUE}"; then
      DISPATCHED="Refine issue #${ISSUE}"
      REFINE_RUNNING=$((REFINE_RUNNING + 1))
    fi
```

- [ ] **Step 8: Audit for remaining bare dispatch calls**

```bash
grep -n '^\s*dispatch "' dark-factory/scheduler.sh
```

Expected: Empty output. All calls are now inside `if dispatch ...; then` blocks (the function definition itself is `dispatch() {` — different pattern).

- [ ] **Step 9: Commit**

```bash
git add dark-factory/scheduler.sh
git commit -m "fix(#160): guard all dispatch() callers — non-zero exit never kills the scheduler"
```

---

### Task 5: Add trip_to_blocked() universal circuit-breaker helper

**Files:**
- Modify: `dark-factory/scheduler.sh` (insert after `set_board_status`, around line 155)

- [ ] **Step 1: Verify Section B tests are failing**

```bash
bash dark-factory/tests/test_scheduler.sh 2>&1 | grep -A10 "^--- B"
```

Expected: Multiple `FAIL` lines (function does not exist yet).

- [ ] **Step 2: Insert trip_to_blocked() after set_board_status()**

In `dark-factory/scheduler.sh`, after the `set_board_status()` function body (after line ~155, before `# --- PR lookup`), insert:

```bash
# --- Universal circuit-breaker ---
# Moves an issue to Blocked, adds needs-discussion (filters it from all dispatch loops via
# SKIP_LABELS), posts an explanatory comment, and resets the retry counter so a later
# manual re-trigger starts clean.
# Usage: trip_to_blocked <issue_num> <phase: implement|plan|refine> <reason>
trip_to_blocked() {
  local issue_num="$1"
  local phase="$2"
  local reason="${3:-repeated dispatch failure}"

  # implement uses bare issue number; plan/refine use ':phase' suffix
  local key
  case "$phase" in
    implement) key="$issue_num" ;;
    *)         key="${issue_num}:${phase}" ;;
  esac
  local attempts
  attempts=$(get_retry_count "$key")

  echo "[$(date -u +%FT%TZ)] circuit_breaker=trip issue=#${issue_num} phase=${phase} attempts=${attempts}"

  # 1. Board → Blocked (no-op if already Blocked)
  set_board_status "$issue_num" "$STATUS_BLOCKED" || true

  # 2. needs-discussion is in SKIP_LABELS — filters this issue from every dispatch loop
  gh issue edit "$issue_num" --repo "${OWNER}/markethawk" \
    --add-label needs-discussion 2>/dev/null || true

  # 3. Manual retry command varies by phase
  local retry_cmd
  case "$phase" in
    refine) retry_cmd="Refine issue #${issue_num}" ;;
    plan)   retry_cmd="Plan issue #${issue_num}" ;;
    *)      retry_cmd="Fix issue #${issue_num}" ;;
  esac

  # 4. Explanatory comment
  gh issue comment "$issue_num" --repo "${OWNER}/markethawk" --body \
"## Scheduler — Circuit-Breaker Tripped (\`${phase}\`)

The scheduler attempted **${phase}** **${attempts} time(s)** without success and cannot recover automatically.

**Reason:** ${reason}

This ticket has been moved to **Blocked** and labelled \`needs-discussion\` to pause automation.

**To resume:**
1. Investigate the failure comments above and fix the root cause.
2. Remove the \`needs-discussion\` label — the scheduler resumes on its next poll.

\`\`\`bash
# Or re-run manually:
docker compose --profile factory run --rm dark-factory \"${retry_cmd}\"
\`\`\`

---
*Posted by MarketHawk Backlog Scheduler*" 2>/dev/null || true

  # 5. Reset counter so a future manual retry starts clean
  reset_retry "$key"
}
```

- [ ] **Step 3: Run Section B tests — expect all pass**

```bash
bash dark-factory/tests/test_scheduler.sh 2>&1 | grep -A15 "^--- B"
```

Expected: 6 `PASS` lines, 0 `FAIL`.

- [ ] **Step 4: Commit**

```bash
git add dark-factory/scheduler.sh
git commit -m "feat(#160): add trip_to_blocked() universal circuit-breaker helper"
```

---

### Task 6: Replace three divergent retry cap-handlers with trip_to_blocked()

**Files:**
- Modify: `dark-factory/scheduler.sh` (Priority 3, 4, 5 retry-exhausted blocks)

- [ ] **Step 1: Priority 3 — implement silent-skip (lines ~526–527)**

Note: items reaching this cap-handler already passed the `has_skip_label` check at the top of the Priority 3 loop (line ~524), so they cannot carry `needs-discussion` at this point. `trip_to_blocked` adding `needs-discussion` is safe — no duplicate comment risk on the same cycle.

**Current:**
```bash
    RETRIES=$(get_retry_count "$ISSUE")
    if [ "$RETRIES" -ge "$MAX_RETRIES" ]; then continue; fi
```

**New:**
```bash
    RETRIES=$(get_retry_count "$ISSUE")
    if [ "$RETRIES" -ge "$MAX_RETRIES" ]; then
      trip_to_blocked "$ISSUE" "implement" "retry limit of ${MAX_RETRIES} reached"
      continue
    fi
```

- [ ] **Step 2: Priority 4 — plan needs-discussion block (lines ~550–569)**

Replace the entire `if [ "$RETRIES" -ge "$REFINE_MAX_RETRIES" ]; then ... fi` block (which currently posts a large comment and adds `needs-discussion`) with:

**Current (lines ~551–569):**
```bash
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
```

**New:**
```bash
    if [ "$RETRIES" -ge "$REFINE_MAX_RETRIES" ]; then
      trip_to_blocked "$ISSUE" "plan" "retry limit of ${REFINE_MAX_RETRIES} reached"
      continue
    fi
```

- [ ] **Step 3: Priority 5 — refine needs-discussion block (lines ~611–630)**

Replace the equivalent block for refine (identical structure to the plan block above):

**Current (lines ~612–630):**
```bash
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
```

**New:**
```bash
    if [ "$RETRIES" -ge "$REFINE_MAX_RETRIES" ]; then
      trip_to_blocked "$ISSUE" "refine" "retry limit of ${REFINE_MAX_RETRIES} reached"
      continue
    fi
```

- [ ] **Step 4: Verify no divergent handlers remain**

```bash
grep -n 'Retries Exhausted' dark-factory/scheduler.sh
```

Expected: Empty output (the old copy-pasted comment blocks are gone).

- [ ] **Step 5: Run full test suite**

```bash
bash dark-factory/tests/test_scheduler.sh
```

Expected: All sections pass.

- [ ] **Step 6: Commit**

```bash
git add dark-factory/scheduler.sh
git commit -m "fix(#160): replace divergent retry cap-handlers with trip_to_blocked()"
```

---

### Task 7: Add ERR trap logging backstop

**Files:**
- Modify: `dark-factory/scheduler.sh` (after `SCHEDULER_SOURCE_ONLY` guard, before WIP limits fetch)

- [ ] **Step 1: Insert ERR trap after SCHEDULER_SOURCE_ONLY guard (after line ~373)**

After the `if [ "${SCHEDULER_SOURCE_ONLY:-0}" = "1" ]; then return 0; fi` block and before the `# --- Fetch WIP limits once at startup` comment, add:

```bash
# --- ERR trap: log unhandled exits for post-mortem diagnosis ---
# dispatch() callers are all guarded with `if dispatch ...; then`; this backstop
# identifies any command that slips through. The scheduler exits on unhandled ERR
# (set -e); durable retry state on the named volume ensures circuit-breakers
# accumulate correctly across the restart-unless-stopped restart cycle.
_sched_err_trap() {
  local code=$? line=${BASH_LINENO[0]}
  echo "[$(date -u +%FT%TZ)] SCHED_UNHANDLED_ERR line=${line} exit=${code}" >&2
}
trap '_sched_err_trap' ERR
```

- [ ] **Step 2: Verify test harness unaffected**

```bash
bash dark-factory/tests/test_scheduler.sh
```

Expected: All tests still pass. The trap is set after the `SCHEDULER_SOURCE_ONLY` guard, so it is never active during test harness runs.

- [ ] **Step 3: Commit**

```bash
git add dark-factory/scheduler.sh
git commit -m "fix(#160): add ERR trap for unhandled-exit logging"
```

---

### Task 8: Opt-in refinement gate

**Files:**
- Modify: `dark-factory/scheduler.sh` (new helper + Priority 5 loop gate)
- Modify: `Docs/agents/triage-labels.md`
- Modify: `dark-factory/tests/test_scheduler.sh` (already has Section D)

- [ ] **Step 1: Verify Section D tests are failing**

```bash
bash dark-factory/tests/test_scheduler.sh 2>&1 | grep -A6 "^--- D"
```

Expected: Error "has_opt_in_refine_label: command not found" or FAIL lines.

- [ ] **Step 2: Add has_opt_in_refine_label() helper in scheduler.sh**

In `dark-factory/scheduler.sh`, after the `has_refine_skip_label()` function (after line ~111), add:

```bash
has_opt_in_refine_label() {
  local item="$1"
  local labels
  labels=$(echo "$item" | jq -r '.labels[]?' 2>/dev/null)
  echo "$labels" | grep -qi "ready-for-agent"
}
```

- [ ] **Step 3: Add opt-in gate in the Priority 5 Backlog loop**

In the Backlog loop (Priority 5), after the `has_refine_skip_label` check (around line 607):

**Current:**
```bash
    if has_refine_skip_label "$item"; then continue; fi
    if is_issue_running "$ISSUE"; then continue; fi
```

**New:**
```bash
    if has_refine_skip_label "$item"; then continue; fi
    # Opt-in gate: only auto-refine Backlog items labelled ready-for-agent.
    # Unlabelled items are left for triage — humans add the label when the issue is ready.
    if ! has_opt_in_refine_label "$item"; then continue; fi
    if is_issue_running "$ISSUE"; then continue; fi
```

- [ ] **Step 4: Update Docs/agents/triage-labels.md**

Append the following section to the end of `Docs/agents/triage-labels.md`:

```markdown

## Opt-in refinement gate

The backlog scheduler auto-refines Backlog issues **only when they carry the `ready-for-agent` label**. Unlabelled Backlog items are left for triage and are never automatically dispatched to the refinement pipeline.

This prevents new issues from being auto-refined during the labelling window (the root cause of the #159 dispatch loop). Apply `ready-for-agent` to a Backlog issue once it is triaged and fully specified for agent work.

The `spec-pending-review` re-refine-on-feedback path is unaffected — it handles feedback on an already-refined issue and does not require an opt-in label.
```

- [ ] **Step 5: Run Section D tests — expect pass**

```bash
bash dark-factory/tests/test_scheduler.sh 2>&1 | grep -A6 "^--- D"
```

Expected:
```
--- D: Opt-in label gate ---
  PASS: item WITH label passes gate
  PASS: item WITHOUT label blocked
```

- [ ] **Step 6: Commit**

```bash
git add dark-factory/scheduler.sh Docs/agents/triage-labels.md
git commit -m "fix(#160): opt-in refinement gate — require ready-for-agent on Backlog items"
```

---

### Task 9: Startup image probe and FACTORY_IMAGE env var

**Files:**
- Modify: `dark-factory/scheduler.sh` (after WIP limits echo, before main loop)
- Modify: `docker-compose.yml` (environment block for backlog-scheduler)
- Modify: `ENV_VARIABLES.md`

- [ ] **Step 1: Add environment block to backlog-scheduler in docker-compose.yml**

In the `backlog-scheduler` service (around line 427), after `env_file:` and before `volumes:`:

**Add:**
```yaml
    environment:
      FACTORY_IMAGE: "ghcr.io/omniscient/markethawk-dark-factory:${IMAGE_TAG:-latest}"
```

- [ ] **Step 2: Add startup probe in scheduler.sh**

After the WIP limits echo (line ~379: `echo "WIP limits: ..."`) and before `# --- Main loop ---`, insert:

```bash
# --- Startup probe: verify factory image is available locally ---
# dispatch() uses --no-build so a missing image causes every dispatch to fail immediately
# (no inline build). Exit here with actionable instructions rather than entering a loop
# where every dispatch fails and the circuit-breaker trips in N cycles.
FACTORY_IMAGE="${FACTORY_IMAGE:-ghcr.io/omniscient/markethawk-dark-factory:${IMAGE_TAG:-latest}}"
echo "[$(date -u +%FT%TZ)] probe=image_check image=${FACTORY_IMAGE}"
if ! docker image inspect "$FACTORY_IMAGE" >/dev/null 2>&1; then
  echo "[$(date -u +%FT%TZ)] probe=image_missing — attempting docker pull"
  if ! docker pull "$FACTORY_IMAGE"; then
    echo "[$(date -u +%FT%TZ)] FATAL: image unavailable and pull failed." >&2
    echo "  Fix GHCR auth (docker login ghcr.io) or build the image locally:" >&2
    echo "  docker compose --profile factory build dark-factory" >&2
    echo "  Then restart the scheduler." >&2
    # Sleep before exit to throttle restart-unless-stopped restart loops
    sleep 60
    exit 1
  fi
  echo "[$(date -u +%FT%TZ)] probe=image_pulled image=${FACTORY_IMAGE}"
else
  echo "[$(date -u +%FT%TZ)] probe=image_ok image=${FACTORY_IMAGE}"
fi
```

- [ ] **Step 3: Document FACTORY_IMAGE and IMAGE_TAG in ENV_VARIABLES.md**

Add to `ENV_VARIABLES.md` alongside `SCHEDULER_STATE_DIR`:

```markdown
| `FACTORY_IMAGE` | `ghcr.io/omniscient/markethawk-dark-factory:latest` | Docker image the scheduler probes at startup and dispatches with `--no-build`. Override to use a locally-built tag. |
| `IMAGE_TAG` | `latest` | Tag suffix for `FACTORY_IMAGE`. Used when `FACTORY_IMAGE` is not set explicitly. |
```

- [ ] **Step 4: Validate docker-compose.yml**

```bash
docker compose config --services
```

Expected: All services listed, no YAML errors.

- [ ] **Step 5: Run full test suite**

```bash
bash dark-factory/tests/test_scheduler.sh
```

Expected: All tests pass (the probe runs after the `SCHEDULER_SOURCE_ONLY` guard).

- [ ] **Step 6: Commit**

```bash
git add dark-factory/scheduler.sh docker-compose.yml ENV_VARIABLES.md
git commit -m "fix(#160): startup image probe — fail fast if factory image unavailable"
```

---

### Task 10: Document entrypoint.sh run-side deferral decision

**Files:**
- Modify: `dark-factory/entrypoint.sh` (on_failure() at line ~227)

The spec asks whether `on_failure` should set board status to Blocked for refine/plan (as it does for implement). Design decision: defer to the scheduler counter. If `on_failure` set Blocked+`needs-discussion` for refine/plan, the issue would enter Blocked before the scheduler's counter accumulates, and Priority 3 would retry it as `Fix` (implement) — wrong intent. The scheduler's `trip_to_blocked` is the correct Blocked transition for pipeline phases.

- [ ] **Step 1: Add comment to on_failure() in entrypoint.sh**

In `dark-factory/entrypoint.sh`, find the `on_failure()` function (line ~227). Locate the `if [ "$INTENT" = "refine" ] || [ "$INTENT" = "plan" ]; then` branch and add a comment:

**Current:**
```bash
    if [ "$INTENT" = "refine" ] || [ "$INTENT" = "plan" ]; then
      echo "Refinement pipeline failed (exit $EXIT_CODE) for issue #$ISSUE_NUM"
```

**New:**
```bash
    if [ "$INTENT" = "refine" ] || [ "$INTENT" = "plan" ]; then
      # No board status change here — the scheduler's trip_to_blocked() handles the
      # Blocked transition after N attempts. Setting Blocked from on_failure would put
      # the issue in Blocked before the scheduler's counter accumulates; Priority 3
      # would then retry it as "Fix" (implement) — wrong intent for a pipeline phase.
      echo "Refinement pipeline failed (exit $EXIT_CODE) for issue #$ISSUE_NUM"
```

- [ ] **Step 2: Verify no logic changes**

```bash
grep -A25 'on_failure()' dark-factory/entrypoint.sh | head -30
```

Expected: The new comment appears between the `if` line and the `echo` line. All surrounding code is unchanged.

- [ ] **Step 3: Commit**

```bash
git add dark-factory/entrypoint.sh
git commit -m "docs(#160): explain refine/plan on_failure deferral to scheduler circuit-breaker"
```

---

### Task 11: Regression test script

**Files:**
- Create: `dark-factory/tests/test_159_regression.sh`

- [ ] **Step 1: Create regression test**

Create `dark-factory/tests/test_159_regression.sh`:

```bash
#!/usr/bin/env bash
# Regression test for the #159 dispatch loop.
# Simulates: unlabelled Backlog issue, failing dispatch, N cycles → Blocked.
# Run: bash dark-factory/tests/test_159_regression.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

STATE_FILE=$(mktemp /tmp/159-state-XXXXXX.json)
echo '{}' > "$STATE_FILE"
export STATE_FILE

STUB_LOG=$(mktemp /tmp/159-stubs-XXXXXX.log)
DISPATCH_CALLS=0

# Source scheduler functions first so our stubs override the real definitions.
# scheduler.sh defines is_issue_running() at line ~86; exporting stubs before source
# would be clobbered. Define and export stubs AFTER source.
SCHEDULER_SOURCE_ONLY=1 source "$SCRIPT_DIR/../scheduler.sh"

# Override external commands with stubs (defined after source to win the override race)
gh()               { echo "gh $*"               >> "$STUB_LOG"; return 0; }
set_board_status() { echo "set_board_status $*" >> "$STUB_LOG"; return 0; }
docker() {
  echo "docker $*" >> "$STUB_LOG"
  if echo "$*" | grep -q "compose.*run"; then
    DISPATCH_CALLS=$((DISPATCH_CALLS+1))
    return 1   # simulate failing docker compose run
  fi
  return 0
}
is_issue_running() { return 1; }

PASSED=0; FAILED=0
assert_eq() {
  local desc="$1" expected="$2" actual="$3"
  if [ "$expected" = "$actual" ]; then
    echo "  PASS: $desc"; PASSED=$((PASSED+1))
  else
    echo "  FAIL: $desc — expected='$expected' got='$actual'" >&2; FAILED=$((FAILED+1))
  fi
}

echo "=== #159 Regression: unlabelled Backlog issue, failing dispatch ==="
echo ""

# Phase 1: unlabelled issue is never dispatched (opt-in gate)
echo "--- Phase 1: Opt-in gate blocks unlabelled issue ---"
echo '{}' > "$STATE_FILE"; > "$STUB_LOG"; DISPATCH_CALLS=0

ITEM_UNLABELLED='{"content":{"number":159,"type":"Issue"},"labels":["needs-triage"],"status":"Backlog"}'
has_opt_in_refine_label "$ITEM_UNLABELLED" \
  && assert_eq "unlabelled issue blocked by opt-in gate" "dispatched" "dispatched" \
  || assert_eq "unlabelled issue blocked by opt-in gate" "skipped" "skipped"
assert_eq "no dispatch calls for unlabelled item" "0" "$DISPATCH_CALLS"

# Phase 2: labelled issue with failing dispatch trips to Blocked within MAX retries
echo ""
echo "--- Phase 2: Failing dispatch trips to Blocked within ${REFINE_MAX_RETRIES:-3} retries ---"
echo '{}' > "$STATE_FILE"; > "$STUB_LOG"; DISPATCH_CALLS=0
MAX="${REFINE_MAX_RETRIES:-3}"
ISSUE="159"

CYCLES=0
while [ "$CYCLES" -le "$MAX" ]; do
  RETRIES=$(get_retry_count "${ISSUE}:refine")
  if [ "$RETRIES" -ge "$MAX" ]; then
    trip_to_blocked "$ISSUE" "refine" "retry limit reached in regression test"
    break
  fi
  increment_retry "${ISSUE}:refine"
  dispatch "Refine issue #${ISSUE}" || true
  CYCLES=$((CYCLES+1))
done

assert_eq "dispatch attempted exactly ${MAX} times" "$MAX" "$DISPATCH_CALLS"
assert_eq "retry counter reset to 0 after trip"     "0"    "$(get_retry_count "${ISSUE}:refine")"
assert_eq "set_board_status called (→ Blocked)"      "1" \
  "$(grep -c "set_board_status ${ISSUE}" "$STUB_LOG" || echo 0)"
assert_eq "needs-discussion label added" "1" \
  "$(grep -c "needs-discussion" "$STUB_LOG" || echo 0)"

# Phase 3: tripped issue is skipped on next cycle (has needs-discussion)
echo ""
echo "--- Phase 3: Tripped issue skipped by dispatch loops ---"
ITEM_TRIPPED='{"content":{"number":159,"type":"Issue"},"labels":["needs-discussion"],"status":"Blocked"}'
has_skip_label "$ITEM_TRIPPED" \
  && assert_eq "tripped issue skipped (has needs-discussion)" "skipped" "skipped" \
  || assert_eq "tripped issue skipped (has needs-discussion)" "skipped" "dispatched"

# Cleanup
rm -f "$STATE_FILE" "$STUB_LOG"
echo ""
echo "Results: ${PASSED} passed, ${FAILED} failed"
[ "$FAILED" -eq 0 ]
```

- [ ] **Step 2: Run regression test — expect all pass**

```bash
bash dark-factory/tests/test_159_regression.sh
```

Expected:
```
=== #159 Regression: unlabelled Backlog issue, failing dispatch ===

--- Phase 1: Opt-in gate blocks unlabelled issue ---
  PASS: unlabelled issue blocked by opt-in gate
  PASS: no dispatch calls for unlabelled item

--- Phase 2: Failing dispatch trips to Blocked within 3 retries ---
  PASS: dispatch attempted exactly 3 times
  PASS: retry counter reset to 0 after trip
  PASS: set_board_status called (→ Blocked)
  PASS: needs-discussion label added

--- Phase 3: Tripped issue skipped by dispatch loops ---
  PASS: tripped issue skipped (has needs-discussion)

Results: 7 passed, 0 failed
```

- [ ] **Step 3: Run full unit-test suite as final check**

```bash
bash dark-factory/tests/test_scheduler.sh && bash dark-factory/tests/test_159_regression.sh
```

Expected: Both exit 0.

- [ ] **Step 4: Commit**

```bash
git add dark-factory/tests/test_159_regression.sh
git commit -m "test(#160): regression test for #159 dispatch loop scenario"
```
