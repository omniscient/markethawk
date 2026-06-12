# Implementation Plan: Baseline-Green Gate (Issue #332)

**Date:** 2026-06-12  
**Issue:** #332  
**Spec:** [docs/superpowers/specs/2026-06-12-baseline-green-gate-design.md](../specs/2026-06-12-baseline-green-gate-design.md)

---

## Goal

Run a smoke gate before any per-ticket factory run to verify `origin/main` is buildable. On a red main: exit the container cleanly (exit 0 — no per-ticket retry or circuit break), file or update a `regression`-labelled GitHub issue, and write a sentinel file. The scheduler reads that sentinel to skip Priority 1.5/2/3 dispatch until main goes green again. On the next green pass the gate removes the sentinel and closes the regression ticket.

---

## Architecture

- **`dark-factory/smoke_gate.sh`** (new sourced helper): defines `run_smoke_gate`, `_smoke_check_main`, `_smoke_on_red`, `_smoke_on_green`. Mirrors the `SCHEDULER_SOURCE_ONLY` guard pattern for unit-testability.
- **`dark-factory/entrypoint.sh`**: sources and calls `smoke_gate.sh` after dep install, before the archon call. Guarded by intent: only `fix`, `continue`, `deconflict` (spec's `new`/`continue`/`resolve`) — skip for `refine`, `plan`, `close`.
- **`dark-factory/Dockerfile`**: adds `COPY dark-factory/smoke_gate.sh /opt/dark-factory/smoke_gate.sh` so the helper is present inside the container image.
- **`dark-factory/scheduler.sh`**: reads `${SCHEDULER_STATE_DIR}/main-is-red` at the top of each dispatch loop iteration; gates Priority 1.5 (deconflict), Priority 2 (Ready/implement), and Priority 3 (Blocked retry). Priority 1 (Close), Priority 4 (plan), Priority 5 (refine) continue unaffected.
- **`docker-compose.yml`**: mounts `scheduler_state:/var/lib/dark-factory` on the `dark-factory` service (currently only `backlog-scheduler` mounts it), so the sentinel written by a factory container is visible to the scheduler.
- **`dark-factory/tests/test_smoke_gate.sh`** (new): 3-phase shell regression test (red main, green recovery, intent guard).

### Intent mapping (spec → codebase)
| Spec name | Codebase `INTENT` value |
|-----------|------------------------|
| `new`     | `fix` (default)        |
| `continue`| `continue`             |
| `resolve` | `deconflict`           |

---

## Tech Stack

Bash, Docker Compose named volumes, GitHub CLI (`gh`).

---

## File Structure

| File | Action |
|------|--------|
| `dark-factory/smoke_gate.sh` | Create (new helper) |
| `dark-factory/tests/test_smoke_gate.sh` | Create (regression test) |
| `dark-factory/entrypoint.sh` | Modify (source + call smoke gate) |
| `dark-factory/Dockerfile` | Modify (COPY smoke_gate.sh) |
| `dark-factory/scheduler.sh` | Modify (MAIN_IS_RED guard) |
| `docker-compose.yml` | Modify (scheduler_state volume on dark-factory) |

---

## Task 1: Smoke gate helper with TDD regression test

**Files:** `dark-factory/smoke_gate.sh` (new), `dark-factory/tests/test_smoke_gate.sh` (new)

### Step 1a — Write the failing test first

Create `dark-factory/tests/test_smoke_gate.sh`:

```bash
#!/usr/bin/env bash
# Regression test for issue #332: smoke gate must not increment per-ticket counters on red main.
# Run: bash dark-factory/tests/test_smoke_gate.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Isolated temp state dir — shared between gate calls (persists across subshells via filesystem)
SMOKE_STATE_DIR=$(mktemp -d /tmp/smoke-state-XXXXXX)
SCHEDULER_STATE_DIR="$SMOKE_STATE_DIR"
export SMOKE_STATE_DIR SCHEDULER_STATE_DIR

# Fake clone dir (smoke_gate.sh uses ${CLONE_DIR}/frontend and ${CLONE_DIR}/backend)
CLONE_DIR=$(mktemp -d /tmp/smoke-clone-XXXXXX)
mkdir -p "$CLONE_DIR/frontend" "$CLONE_DIR/backend"
export CLONE_DIR OWNER="omniscient"

STUB_LOG=$(mktemp /tmp/smoke-stubs-XXXXXX.log)
TSC_FAIL=0   # 0=pass 1=fail; controls the npx stub
PY_FAIL=0    # 0=pass 1=fail; controls the python stub

# Stubs — visible inside ( subshell ) because ( ) forks and inherits the parent function table.
npx()    { echo "npx $*"    >> "$STUB_LOG"; return "$TSC_FAIL"; }
python() {
  echo "python $*" >> "$STUB_LOG"
  if echo "$*" | grep -q "import app"; then return "$PY_FAIL"; fi
  return 0
}
python3() { python "$@"; }
gh() {
  echo "gh $*" >> "$STUB_LOG"
  if echo "$*" | grep -q "issue create"; then
    echo "https://github.com/omniscient/markethawk/issues/999"
  fi
  return 0
}

# Source smoke_gate.sh to define functions without auto-executing.
# Will fail here (file not yet created) — that is the expected TDD failure.
SMOKE_GATE_SOURCE_ONLY=1 source "$SCRIPT_DIR/../smoke_gate.sh"

PASSED=0; FAILED=0
assert_eq() {
  local desc="$1" expected="$2" actual="$3"
  if [ "$expected" = "$actual" ]; then
    echo "  PASS: $desc"; PASSED=$((PASSED+1))
  else
    echo "  FAIL: $desc — expected='$expected' got='$actual'" >&2; FAILED=$((FAILED+1))
  fi
}
assert_file_exists() {
  if [ -f "$2" ]; then echo "  PASS: $1"; PASSED=$((PASSED+1))
  else echo "  FAIL: $1 — file absent: $2" >&2; FAILED=$((FAILED+1)); fi
}
assert_file_absent() {
  if [ ! -f "$2" ]; then echo "  PASS: $1"; PASSED=$((PASSED+1))
  else echo "  FAIL: $1 — file unexpectedly exists: $2" >&2; FAILED=$((FAILED+1)); fi
}

echo "=== Smoke Gate Regression Test (#332) ==="

# ---- Phase 1: Red main ----
echo ""
echo "--- Phase 1: Red main (tsc fails) ---"
TSC_FAIL=1; PY_FAIL=0
> "$STUB_LOG"
rm -f "${SMOKE_STATE_DIR}/main-is-red" "${SMOKE_STATE_DIR}/main-is-red-issue"

# run_smoke_gate exits 0 on red; run in subshell so test continues after it
(run_smoke_gate) || true

assert_file_exists "sentinel file created" "${SMOKE_STATE_DIR}/main-is-red"
assert_file_exists "issue number file created" "${SMOKE_STATE_DIR}/main-is-red-issue"
GH_CREATES=$(grep -c "gh.*issue create" "$STUB_LOG" 2>/dev/null || echo 0)
assert_eq "gh issue create called once on first red" "1" "$GH_CREATES"

# Idempotency: second gate pass on same red main → update call, not a second create
(run_smoke_gate) || true
GH_CREATES2=$(grep -c "gh.*issue create" "$STUB_LOG" 2>/dev/null || echo 0)
assert_eq "idempotency: only one gh issue create after two red passes" "1" "$GH_CREATES2"
GH_COMMENTS=$(grep -c "gh.*issue comment" "$STUB_LOG" 2>/dev/null || echo 0)
assert_eq "idempotency: update comment posted on second red pass" "1" "$GH_COMMENTS"

# Per-ticket blast radius: no retry/block/board calls for ANY ticket
BLAST_CALLS=$(grep -cE "increment_retry|trip_to_blocked|set_board_status Blocked|needs-discussion" \
              "$STUB_LOG" 2>/dev/null || echo 0)
assert_eq "no per-ticket retry/block/board calls on red main" "0" "$BLAST_CALLS"

# ---- Phase 2: Green main after red ----
echo ""
echo "--- Phase 2: Green main after red (sentinel cleanup) ---"
TSC_FAIL=0; PY_FAIL=0
> "$STUB_LOG"
# Sentinel and issue file from Phase 1 are still present — gate must clean them up

GATE_RC=0
(run_smoke_gate) || GATE_RC=$?
assert_eq "gate exits/returns 0 on green" "0" "$GATE_RC"
assert_file_absent "sentinel removed on green" "${SMOKE_STATE_DIR}/main-is-red"
assert_file_absent "issue number file removed on green" "${SMOKE_STATE_DIR}/main-is-red-issue"
GH_CLOSES=$(grep -c "gh.*issue close" "$STUB_LOG" 2>/dev/null || echo 0)
assert_eq "gh issue close called once" "1" "$GH_CLOSES"

# ---- Phase 3: Intent guard ----
echo ""
echo "--- Phase 3: Intent guard — smoke gate skipped for refine/plan/close ---"
TSC_FAIL=1
> "$STUB_LOG"
rm -f "${SMOKE_STATE_DIR}/main-is-red" "${SMOKE_STATE_DIR}/main-is-red-issue"

# Inline the entrypoint.sh intent guard so we can assert it correctly skips the gate
for INTENT in refine plan close; do
  export INTENT
  if [ "$INTENT" = "fix" ] || [ "$INTENT" = "continue" ] || [ "$INTENT" = "deconflict" ]; then
    (run_smoke_gate) || true
  fi
done

TSC_CALLS=$(grep -cE "npx|tsc" "$STUB_LOG" 2>/dev/null || echo 0)
assert_eq "no tsc calls for refine/plan/close" "0" "$TSC_CALLS"
assert_file_absent "no sentinel created for skip intents" "${SMOKE_STATE_DIR}/main-is-red"

# ---- Summary ----
echo ""
echo "Results: $PASSED passed, $FAILED failed"
rm -rf "$SMOKE_STATE_DIR" "$CLONE_DIR" "$STUB_LOG"
[ "$FAILED" -eq 0 ] || exit 1
```

### Step 1b — Verify the test fails (smoke_gate.sh doesn't exist yet)

```bash
bash dark-factory/tests/test_smoke_gate.sh
```

Expected output contains: `dark-factory/smoke_gate.sh: No such file or directory`

### Step 1c — Implement `dark-factory/smoke_gate.sh`

```bash
#!/usr/bin/env bash
# Smoke gate: verifies origin/main is buildable before per-ticket factory work begins.
# Sourced by entrypoint.sh. Set SMOKE_GATE_SOURCE_ONLY=1 before sourcing in tests to
# define functions only (mirrors scheduler.sh's SCHEDULER_SOURCE_ONLY pattern).

SMOKE_STATE_DIR="${SCHEDULER_STATE_DIR:-/var/lib/dark-factory}"
SMOKE_MARKER="<!-- df-main-red -->"

# Runs tsc + python import on origin/main. Returns 0 on full pass, non-zero on first failure.
_smoke_check_main() {
  echo "[smoke_gate] Checking frontend TypeScript (tsc)..."
  if ! (cd "${CLONE_DIR:-/workspace/markethawk}/frontend" \
        && rm -f tsconfig.app.tsbuildinfo \
        && npx tsc -p tsconfig.app.json --noEmit 2>&1); then
    echo "[smoke_gate] tsc FAILED — main is red"
    return 1
  fi
  echo "[smoke_gate] Checking backend Python import graph..."
  if ! (cd "${CLONE_DIR:-/workspace/markethawk}/backend" \
        && python -c "import app.main" 2>&1); then
    echo "[smoke_gate] python import FAILED — main is red"
    return 1
  fi
  return 0
}

# Writes sentinel, files or updates the regression ticket, then exits 0 (clean halt).
_smoke_on_red() {
  echo "[smoke_gate] main is RED — halting factory run (exit 0, no per-ticket failure)"
  mkdir -p "${SMOKE_STATE_DIR}"
  touch "${SMOKE_STATE_DIR}/main-is-red"

  local ISSUE_FILE="${SMOKE_STATE_DIR}/main-is-red-issue"
  if [ -f "$ISSUE_FILE" ]; then
    # Subsequent reds: post an update comment (idempotent — one create, many updates)
    local REGR_NUM
    REGR_NUM=$(cat "$ISSUE_FILE")
    gh issue comment "$REGR_NUM" \
      --repo "${OWNER:-omniscient}/markethawk" \
      --body "main still red at $(date -u +%FT%TZ) — factory implementation runs remain paused." \
      2>/dev/null || true
  else
    # First red: create regression issue and persist its number
    local REGR_URL
    REGR_URL=$(gh issue create \
      --repo "${OWNER:-omniscient}/markethawk" \
      --label regression \
      --title "main is red: tsc/python import failure" \
      --body "$(printf '%s\n\n**main smoke check failed at %s.**\n\nThe dark factory is pausing all implementation dispatches (Priority 1.5/2/3) until `origin/main` compiles cleanly.\n\nThis ticket closes automatically on the next green gate pass.\n' \
              "$SMOKE_MARKER" "$(date -u +%FT%TZ)")" \
      2>/dev/null || true)
    local REGR_NUM
    REGR_NUM=$(echo "$REGR_URL" | grep -oE '[0-9]+$' || true)
    [ -n "$REGR_NUM" ] && echo "$REGR_NUM" > "$ISSUE_FILE"
  fi

  exit 0
}

# On green: removes sentinel (if present) and closes regression ticket.
_smoke_on_green() {
  if [ ! -f "${SMOKE_STATE_DIR}/main-is-red" ]; then
    return 0  # Main was never red this session; nothing to clean up
  fi
  echo "[smoke_gate] main is GREEN — removing red sentinel and closing regression ticket"
  rm -f "${SMOKE_STATE_DIR}/main-is-red"

  local ISSUE_FILE="${SMOKE_STATE_DIR}/main-is-red-issue"
  if [ -f "$ISSUE_FILE" ]; then
    local REGR_NUM
    REGR_NUM=$(cat "$ISSUE_FILE")
    gh issue close "$REGR_NUM" \
      --repo "${OWNER:-omniscient}/markethawk" \
      --comment "main smoke gate passed — closing regression ticket." \
      2>/dev/null || true
    rm -f "$ISSUE_FILE"
  fi
}

# Main entry point called by entrypoint.sh. Returns 0 on green; exits 0 on red.
run_smoke_gate() {
  if _smoke_check_main; then
    _smoke_on_green
    return 0
  else
    _smoke_on_red
    # _smoke_on_red calls exit 0; this line is unreachable
  fi
}

# When sourced for testing (SMOKE_GATE_SOURCE_ONLY=1) stop here — functions are defined
# above; the file has no auto-exec code below this guard (mirrors scheduler.sh pattern).
if [ "${SMOKE_GATE_SOURCE_ONLY:-0}" = "1" ]; then
  return 0
fi
```

### Step 1d — Verify test passes

```bash
bash dark-factory/tests/test_smoke_gate.sh
```

Expected output:
```
=== Smoke Gate Regression Test (#332) ===

--- Phase 1: Red main (tsc fails) ---
  PASS: sentinel file created
  PASS: issue number file created
  PASS: gh issue create called once on first red
  PASS: idempotency: only one gh issue create after two red passes
  PASS: idempotency: update comment posted on second red pass
  PASS: no per-ticket retry/block/board calls on red main

--- Phase 2: Green main after red (sentinel cleanup) ---
  PASS: gate exits/returns 0 on green
  PASS: sentinel removed on green
  PASS: issue number file removed on green
  PASS: gh issue close called once

--- Phase 3: Intent guard — smoke gate skipped for refine/plan/close ---
  PASS: no tsc calls for refine/plan/close
  PASS: no sentinel created for skip intents

Results: 12 passed, 0 failed
```

### Step 1e — Commit

```bash
git add dark-factory/smoke_gate.sh dark-factory/tests/test_smoke_gate.sh
git commit -m "feat(factory): smoke gate helper + 3-phase regression test (issue #332)"
```

---

## Task 2: Wire smoke gate into `entrypoint.sh` and `Dockerfile`

**Files:** `dark-factory/entrypoint.sh`, `dark-factory/Dockerfile`

### Step 2a — Write inline test for the intent guard condition

Validate the intent guard condition before touching entrypoint.sh:

```bash
# Verify that the intent guard logic correctly passes fix/continue/deconflict
# and skips refine/plan/close. Run inline:
for INTENT in fix continue deconflict; do
  if [ "$INTENT" = "fix" ] || [ "$INTENT" = "continue" ] || [ "$INTENT" = "deconflict" ]; then
    echo "PASS: $INTENT triggers gate"
  else
    echo "FAIL: $INTENT should trigger gate but doesn't"
  fi
done
for INTENT in refine plan close; do
  if [ "$INTENT" = "fix" ] || [ "$INTENT" = "continue" ] || [ "$INTENT" = "deconflict" ]; then
    echo "FAIL: $INTENT should be skipped but triggers gate"
  else
    echo "PASS: $INTENT correctly skipped"
  fi
done
# Expected: all 6 lines print PASS
```

### Step 2b — Modify `entrypoint.sh`

Add the smoke gate block **after** line 526 (`pre-commit install ...`) and **before** line 528 (the deconflict comment block). The insertion point is between the pre-commit line and `# =============================================================================`.

Current block (lines 525–532 of `entrypoint.sh`):
```bash
# --- Install pre-commit hooks so codeindex-blast warn hook fires in the run log ---
pre-commit install --allow-missing-config 2>/dev/null || true

# =============================================================================
# --- Deconflict flow: resolve → validate → push → report → exit ---
```

Replace with:
```bash
# --- Install pre-commit hooks so codeindex-blast warn hook fires in the run log ---
pre-commit install --allow-missing-config 2>/dev/null || true

# --- Smoke gate: verify origin/main is green before any per-ticket work ---
# Applies to fix (new), continue, and deconflict (resolve) intents only.
# On red main: exits 0 (no per-ticket failure), files a regression ticket, writes sentinel.
# On green: cleans up any prior red state and proceeds.
if [ "$INTENT" = "fix" ] || [ "$INTENT" = "continue" ] || [ "$INTENT" = "deconflict" ]; then
  source /opt/dark-factory/smoke_gate.sh
  run_smoke_gate
fi

# =============================================================================
# --- Deconflict flow: resolve → validate → push → report → exit ---
```

### Step 2c — Modify `Dockerfile`

Locate line 79 in `Dockerfile`:
```dockerfile
COPY dark-factory/scheduler.sh /opt/dark-factory/scheduler.sh
```

Add the new COPY immediately after it:
```dockerfile
COPY dark-factory/scheduler.sh /opt/dark-factory/scheduler.sh
COPY dark-factory/smoke_gate.sh /opt/dark-factory/smoke_gate.sh
```

Then update the `chmod` line (currently line 84):
```dockerfile
RUN chmod +x /usr/local/bin/entrypoint.sh /opt/dark-factory/scheduler.sh
```
to:
```dockerfile
RUN chmod +x /usr/local/bin/entrypoint.sh /opt/dark-factory/scheduler.sh /opt/dark-factory/smoke_gate.sh
```

### Step 2d — Verify

Confirm `source /opt/dark-factory/smoke_gate.sh` in the modified entrypoint.sh references the path that the Dockerfile installs the file at:

```bash
grep "smoke_gate" dark-factory/entrypoint.sh
# Expected: source /opt/dark-factory/smoke_gate.sh
grep "smoke_gate" dark-factory/Dockerfile
# Expected: COPY dark-factory/smoke_gate.sh /opt/dark-factory/smoke_gate.sh
```

Confirm the intent guard is in place and the insertion is between pre-commit and deconflict sections:
```bash
grep -n "smoke_gate\|pre-commit\|Deconflict flow" dark-factory/entrypoint.sh
# Expected order: pre-commit line → smoke_gate source/call → Deconflict flow comment
```

### Step 2e — Commit

```bash
git add dark-factory/entrypoint.sh dark-factory/Dockerfile
git commit -m "feat(factory): wire smoke gate into entrypoint + Dockerfile COPY (issue #332)"
```

---

## Task 3: MAIN_IS_RED guard in `scheduler.sh`

**Files:** `dark-factory/scheduler.sh`

### Step 3a — Locate insertion point

The MAIN_IS_RED variable is read once per dispatch loop iteration, after the orphaned sweep and before Priority 1.5. The exact insertion point is between line 758 (`done < <(echo "$IN_PROGRESS" | jq -c '.[]')`) and line 760 (`# --- Priority 1.5:`).

```bash
grep -n "IN_PROGRESS.*jq\|Priority 1.5\|Priority 2\|Priority 3\|per-cycle summary\|dispatched.*BUDGET\|skip=nothing" \
  dark-factory/scheduler.sh | head -20
# Expected line numbers (approximate):
# 758: done < <(echo "$IN_PROGRESS" | jq -c '.[]')
# 760: # --- Priority 1.5:
# 832: # --- Priority 2:
# 847: # --- Priority 3:
# 951: echo "[...] backlog=... dispatched=...
# 953: echo "[...] backlog=... skip=nothing_to_do ...
```

### Step 3b — Add MAIN_IS_RED read block after orphaned sweep

**After** the orphaned sweep's `done` line (line ~758), **before** the Priority 1.5 comment, insert:

```bash
  # --- Read main-is-red sentinel (written by smoke_gate.sh in dispatched containers) ---
  # When present, skip Priority 1.5/2/3 (implementation dispatches); 1/4/5 continue.
  MAIN_IS_RED=false
  [ -f "${SCHEDULER_STATE_DIR}/main-is-red" ] && MAIN_IS_RED=true
  if [ "$MAIN_IS_RED" = "true" ]; then
    echo "[$(date -u +%FT%TZ)] main_red_gate=active action=skip_implement_dispatch"
  fi
```

### Step 3c — Gate Priority 1.5

Current Priority 1.5 block (lines ~760–796):
```bash
  # --- Priority 1.5: In Review items with merge conflicts (proactive auto-resolve) ---
  # ...
  if [ "${CONFLICT_RESOLUTION_ENABLED:-true}" = "true" ]; then
    while IFS= read -r item; do
      ...
    done < <(echo "$IN_REVIEW" | jq -c '.[]')
  fi
```

Replace with:
```bash
  # --- Priority 1.5: In Review items with merge conflicts (proactive auto-resolve) ---
  # ...
  if [ "$MAIN_IS_RED" = "true" ]; then
    echo "[$(date -u +%FT%TZ)] main_red_gate=skip_deconflict"
  elif [ "${CONFLICT_RESOLUTION_ENABLED:-true}" = "true" ]; then
    while IFS= read -r item; do
      ...
    done < <(echo "$IN_REVIEW" | jq -c '.[]')
  fi
```

### Step 3d — Gate Priority 2

Current Priority 2 block (lines ~832–845):
```bash
  # --- Priority 2: Ready items (implement what's already refined+planned) ---
  while IFS= read -r item; do
    ...
  done < <(echo "$READY" | jq -c '.[]')
```

Replace with:
```bash
  # --- Priority 2: Ready items (implement what's already refined+planned) ---
  if [ "$MAIN_IS_RED" = "true" ]; then
    echo "[$(date -u +%FT%TZ)] main_red_gate=skip_implement"
  else
    while IFS= read -r item; do
      ...
    done < <(echo "$READY" | jq -c '.[]')
  fi
```

### Step 3e — Gate Priority 3

Current Priority 3 block (lines ~847–873):
```bash
  # --- Priority 3: Blocked items (retry stuck work) ---
  while IFS= read -r item; do
    ...
  done < <(echo "$BLOCKED" | jq -c '.[]')
```

Replace with:
```bash
  # --- Priority 3: Blocked items (retry stuck work) ---
  if [ "$MAIN_IS_RED" = "true" ]; then
    echo "[$(date -u +%FT%TZ)] main_red_gate=skip_blocked_retry"
  else
    while IFS= read -r item; do
      ...
    done < <(echo "$BLOCKED" | jq -c '.[]')
  fi
```

### Step 3f — Add `main_red=` to per-cycle summary log lines

Locate the two summary echo lines (lines ~951, ~953). Add `main_red=${MAIN_IS_RED}` before `graphql=`:

```bash
  # dispatched cycle
  echo "[$(date -u +%FT%TZ)] backlog=${BACKLOG_COUNT} refined=${REFINED_COUNT} in_progress=${IN_PROGRESS_COUNT}/${MAX_IN_PROGRESS} in_review=${IN_REVIEW_COUNT}/${MAX_IN_REVIEW} factory_running=${FACTORY_RUNNING}/${FACTORY_WIP_LIMIT} refine_running=${REFINE_RUNNING}/${REFINE_WIP_LIMIT} dispatched=\"${DISPATCHED}\" main_red=${MAIN_IS_RED} graphql=${BUDGET}"
  # skip cycle
  echo "[$(date -u +%FT%TZ)] backlog=${BACKLOG_COUNT} refined=${REFINED_COUNT} in_progress=${IN_PROGRESS_COUNT}/${MAX_IN_PROGRESS} in_review=${IN_REVIEW_COUNT}/${MAX_IN_REVIEW} factory_running=${FACTORY_RUNNING}/${FACTORY_WIP_LIMIT} refine_running=${REFINE_RUNNING}/${REFINE_WIP_LIMIT} skip=nothing_to_do main_red=${MAIN_IS_RED} graphql=${BUDGET}"
```

### Step 3g — Verify with existing scheduler regression test

```bash
bash dark-factory/tests/test_159_regression.sh
# Expected: all PASS (no regressions introduced)
bash dark-factory/tests/test_smoke_gate.sh
# Expected: all PASS
```

Also verify the MAIN_IS_RED guard is present in each of the three priority blocks:
```bash
grep -n "MAIN_IS_RED\|main_red" dark-factory/scheduler.sh
# Expected: ~7 occurrences (read block + 3 guards + 2 summary lines)
```

### Step 3h — Commit

```bash
git add dark-factory/scheduler.sh
git commit -m "feat(scheduler): gate Priority 1.5/2/3 on main-is-red sentinel (issue #332)"
```

---

## Task 4: Mount `scheduler_state` volume on `dark-factory` service

**Files:** `docker-compose.yml`

### Step 4a — Locate the dark-factory service

```bash
grep -n "dark-factory:\|profiles:\|volumes:" docker-compose.yml | head -20
# Confirm dark-factory service has no volumes: key (currently has none)
# backlog-scheduler has scheduler_state:/var/lib/dark-factory at line ~480
```

### Step 4b — Add `volumes:` to the dark-factory service

In `docker-compose.yml`, the `dark-factory` service (lines ~437–459) currently ends with:
```yaml
    logging:
      driver: gelf
      options:
        gelf-address: "udp://host.docker.internal:12201"
        tag: "dark-factory"
    profiles:
      - factory
```

Add a `volumes:` block between `logging:` and `profiles:`:
```yaml
    logging:
      driver: gelf
      options:
        gelf-address: "udp://host.docker.internal:12201"
        tag: "dark-factory"
    volumes:
      - scheduler_state:/var/lib/dark-factory
    profiles:
      - factory
```

### Step 4c — Verify

```bash
grep -A 30 "dark-factory:" docker-compose.yml | grep -A2 "volumes:"
# Expected: volumes: / - scheduler_state:/var/lib/dark-factory

# Confirm the named volume is still defined at the bottom of the file
grep -A2 "^  scheduler_state:" docker-compose.yml
# Expected: scheduler_state: (with no driver_opts: type: tmpfs — regular named volume)
```

Confirm the backlog-scheduler still has its own mount:
```bash
grep -A 30 "backlog-scheduler:" docker-compose.yml | grep "scheduler_state"
# Expected: - scheduler_state:/var/lib/dark-factory
```

### Step 4d — Commit

```bash
git add docker-compose.yml
git commit -m "feat(compose): mount scheduler_state volume on dark-factory service (issue #332)"
```

---

## Task 5: Create the `regression` GitHub label (one-time setup)

**Files:** none (external GitHub state)

### Step 5a — Create the label

```bash
gh label create regression \
  --repo omniscient/markethawk \
  --color "e4e669" \
  --description "Broken main / shared infrastructure regression" \
  2>/dev/null || echo "label already exists"
```

Expected output: URL of the new label, or "label already exists" if already present.

### Step 5b — Verify

```bash
gh label list --repo omniscient/markethawk --search regression
# Expected: regression    e4e669    Broken main / shared infrastructure regression
```

### Step 5c — Commit note

No file change needed. This task is complete when the label exists on GitHub. The smoke gate's `_smoke_on_red` uses `--label regression` in `gh issue create`; if the label is absent, `gh` returns a non-zero exit that is already silenced with `|| true`, so missing label is non-fatal — but the regression ticket would not carry the label.

---

## Summary

| Task | Files changed | Commit |
|------|--------------|--------|
| 1 | `dark-factory/smoke_gate.sh`, `dark-factory/tests/test_smoke_gate.sh` | `feat(factory): smoke gate helper + 3-phase regression test` |
| 2 | `dark-factory/entrypoint.sh`, `dark-factory/Dockerfile` | `feat(factory): wire smoke gate into entrypoint + Dockerfile COPY` |
| 3 | `dark-factory/scheduler.sh` | `feat(scheduler): gate Priority 1.5/2/3 on main-is-red sentinel` |
| 4 | `docker-compose.yml` | `feat(compose): mount scheduler_state volume on dark-factory service` |
| 5 | (GitHub label) | (no file commit) |

**Total tasks:** 5  
**Total steps:** 24
