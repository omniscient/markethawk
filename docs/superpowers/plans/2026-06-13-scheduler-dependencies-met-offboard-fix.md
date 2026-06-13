# Plan: Fix dependencies_met() Off-Board Fallback

**Date:** 2026-06-13
**Issue:** #389
**Spec:** docs/superpowers/specs/2026-06-13-scheduler-dependencies-met-offboard-fix-design.md

## Goal

Patch `dependencies_met()` in `dark-factory/scheduler.sh` to treat a dependency that is closed
but no longer on the project board (archived or outside the 50-item fetch window) as met. Add a
`dep_gate` log line whenever a dependency is unmet — whether on-board non-Done or off-board
non-CLOSED — making the stranding condition diagnosable from scheduler logs.

Confirmed incident: issue #339 was permanently stranded because its dependency (#331) was CLOSED
but archived off the board. The scheduler logged `skip=nothing_to_do` every cycle with no
per-item diagnostic.

## Architecture

Two-part patch to `dependencies_met()` in one file:

1. **Part 1 — Off-board fallback**: when `dep_status` is empty (dep not found on board), fall
   back to `gh issue view $dep_num --json state`. CLOSED → met (log `resolved=closed_off_board`);
   OPEN / empty (gh failure) → unmet (log `dep_status=off_board`).
2. **Part 2 — On-board log line**: the existing silent `return 1` for non-Done deps gains a
   `dep_gate` log line.

No new functions, no new config variables, no compose or Docker changes needed until post-merge
image rebuild.

## Tech Stack

- Shell: `dark-factory/scheduler.sh` (bash, `set -euo pipefail`)
- Test harness: `dark-factory/tests/test_scheduler.sh` (bash, `SCHEDULER_SOURCE_ONLY=1` source
  pattern, `set -uo pipefail` — no `-e` in test file)

## File Structure

| File | Change |
|------|--------|
| `dark-factory/scheduler.sh` | Modify `dependencies_met()` — insert fallback block + log line |
| `dark-factory/tests/test_scheduler.sh` | Add section N (9 test cases) before cleanup block |

> **Section letter conflict**: The spec designates the new test section "K: dependencies_met()".
> Section K is already used by "Priority 1.5 — conflict gate" (line 458). Sections A–M are all
> occupied. This plan uses **N** for the new section. Test names are N1–N9.

---

## Task 1 — Write failing tests: section N in test_scheduler.sh

**Files:** `dark-factory/tests/test_scheduler.sh`

### Step 1.1 — Add section N before the cleanup block

Insert the following block immediately before the `# ==========================================`
`# Cleanup` comment at line 744 of `dark-factory/tests/test_scheduler.sh`:

```bash
# ==========================================
# N: dependencies_met()
# ==========================================
echo ""
echo "--- N: dependencies_met ---"
> "$STUB_LOG"

_BOARD_EMPTY='{"items":[]}'
_BOARD_DEP100_DONE='{"items":[{"content":{"number":100},"status":"Done"}]}'
_BOARD_DEP100_READY='{"items":[{"content":{"number":100},"status":"Ready"}]}'
_BOARD_DEP101_DONE='{"items":[{"content":{"number":101},"status":"Done"}]}'

_NDEP_LOG=$(mktemp)

# N1: No "Depends on:" in body → passes (return 0)
gh() {
  case "$*" in
    *"--json body"*) echo "No dependencies here" ;;
    *) echo "" ;;
  esac
}
export -f gh
dependencies_met "339" "$_BOARD_EMPTY" >"$_NDEP_LOG" \
  && assert_eq "N1: no Depends on → passes" "0" "0" \
  || assert_eq "N1: no Depends on → passes" "0" "1"

# N2: Single dep on board as Done → passes
gh() {
  case "$*" in
    *"--json body"*) echo "Depends on: #100" ;;
    *) echo "" ;;
  esac
}
export -f gh
dependencies_met "339" "$_BOARD_DEP100_DONE" >"$_NDEP_LOG" \
  && assert_eq "N2: on-board Done → passes" "0" "0" \
  || assert_eq "N2: on-board Done → passes" "0" "1"

# N3: Single dep on board as non-Done (Ready) → blocked (return 1);
#     log contains dep_gate blocked_by=#100
gh() {
  case "$*" in
    *"--json body"*) echo "Depends on: #100" ;;
    *) echo "" ;;
  esac
}
export -f gh
dependencies_met "339" "$_BOARD_DEP100_READY" >"$_NDEP_LOG" \
  && assert_eq "N3: on-board Ready → blocked" "0" "1" \
  || assert_eq "N3: on-board Ready → blocked" "0" "0"
assert_eq "N3: dep_gate log present" "1" \
  "$(grep -c 'blocked_by=#100' "$_NDEP_LOG" || echo 0)"

# N4: Dep off-board + CLOSED → passes via fallback;
#     log contains resolved=closed_off_board
gh() {
  case "$*" in
    *"--json body"*)  echo "Depends on: #100" ;;
    *"--json state"*) echo "CLOSED" ;;
    *) echo "" ;;
  esac
}
export -f gh
dependencies_met "339" "$_BOARD_EMPTY" >"$_NDEP_LOG" \
  && assert_eq "N4: off-board CLOSED → passes" "0" "0" \
  || assert_eq "N4: off-board CLOSED → passes" "0" "1"
assert_eq "N4: closed_off_board log present" "1" \
  "$(grep -c 'resolved=closed_off_board' "$_NDEP_LOG" || echo 0)"

# N5: Dep off-board + OPEN → blocked (return 1);
#     log contains dep_gate blocked_by=#100
gh() {
  case "$*" in
    *"--json body"*)  echo "Depends on: #100" ;;
    *"--json state"*) echo "OPEN" ;;
    *) echo "" ;;
  esac
}
export -f gh
dependencies_met "339" "$_BOARD_EMPTY" >"$_NDEP_LOG" \
  && assert_eq "N5: off-board OPEN → blocked" "0" "1" \
  || assert_eq "N5: off-board OPEN → blocked" "0" "0"
assert_eq "N5: dep_gate log present" "1" \
  "$(grep -c 'blocked_by=#100' "$_NDEP_LOG" || echo 0)"

# N6: Dep off-board + gh state failure (empty) → blocked (return 1)
gh() {
  case "$*" in
    *"--json body"*)  echo "Depends on: #100"; return 0 ;;
    *"--json state"*) return 1 ;;
    *) echo "" ;;
  esac
}
export -f gh
dependencies_met "339" "$_BOARD_EMPTY" >"$_NDEP_LOG" \
  && assert_eq "N6: off-board gh-failure → blocked" "0" "1" \
  || assert_eq "N6: off-board gh-failure → blocked" "0" "0"

# N7: Two deps — first on-board Done (#101), second off-board OPEN (#102) → blocked
gh() {
  case "$*" in
    *"--json body"*)               printf 'Depends on: #101\nDepends on: #102\n' ;;
    *"view 102 "*"--json state"*)  echo "OPEN" ;;
    *) echo "" ;;
  esac
}
export -f gh
dependencies_met "339" "$_BOARD_DEP101_DONE" >"$_NDEP_LOG" \
  && assert_eq "N7: two deps, #102 off-board OPEN → blocked" "0" "1" \
  || assert_eq "N7: two deps, #102 off-board OPEN → blocked" "0" "0"

# N8: Two deps — first on-board Done (#101), second off-board CLOSED (#102) → passes
gh() {
  case "$*" in
    *"--json body"*)               printf 'Depends on: #101\nDepends on: #102\n' ;;
    *"view 102 "*"--json state"*)  echo "CLOSED" ;;
    *) echo "" ;;
  esac
}
export -f gh
dependencies_met "339" "$_BOARD_DEP101_DONE" >"$_NDEP_LOG" \
  && assert_eq "N8: two deps, #102 off-board CLOSED → passes" "0" "0" \
  || assert_eq "N8: two deps, #102 off-board CLOSED → passes" "0" "1"

# N9: Body fetch fails → passes (return 0; pre-existing behaviour)
gh() { return 1; }
export -f gh
dependencies_met "339" "$_BOARD_EMPTY" >/dev/null \
  && assert_eq "N9: body fetch fails → passes" "0" "0" \
  || assert_eq "N9: body fetch fails → passes" "0" "1"

rm -f "$_NDEP_LOG"

# Restore general gh stub
gh() { echo "gh $*" >> "$STUB_LOG"; return 0; }
export -f gh
```

### Step 1.2 — Run tests, verify failures

```bash
bash dark-factory/tests/test_scheduler.sh 2>&1 | grep -E "^  (PASS|FAIL): N"
```

Expected failures **before** the implementation (Task 2):

| Test | Status before fix | Why |
|------|-------------------|-----|
| N3: dep_gate log present | FAIL | No log line in current code |
| N4: off-board CLOSED → passes | FAIL | Empty dep_status → `!= "Done"` → return 1 |
| N4: closed_off_board log present | FAIL | Fallback block absent |
| N5: dep_gate log present | FAIL | No log line in current code |
| N8: two deps, #102 off-board CLOSED → passes | FAIL | Empty dep_status → return 1 for #102 |

Tests N1, N2, N6, N7, N9 should already pass (existing behavior matches their expectations).

### Step 1.3 — Commit failing tests

```bash
cd /workspace/markethawk
git add dark-factory/tests/test_scheduler.sh
git commit -m "test: add section N — dependencies_met() 9 cases (#389)"
```

Expected output: `[refine/... <hash>] test: add section N — dependencies_met() 9 cases (#389)`

---

## Task 2 — Implement off-board fallback + dep_gate log lines

**Files:** `dark-factory/scheduler.sh`

### Step 2.1 — Replace the dependencies_met function body

The current function (lines 645–663):

```bash
# --- Dependency checking ---
dependencies_met() {
  local issue_num="$1"
  local board_items="$2"
  local body
  body=$(gh issue view "$issue_num" --repo "${OWNER}/markethawk" --json body -q '.body' 2>/dev/null) || return 0
  local deps
  deps=$(echo "$body" | grep -oP 'Depends on:\s*#\K\d+' || true)
  if [ -z "$deps" ]; then
    return 0
  fi
  while IFS= read -r dep_num; do
    local dep_status
    dep_status=$(echo "$board_items" | jq -r ".items[] | select(.content.number == $dep_num) | .status" 2>/dev/null)
    if [ "$dep_status" != "Done" ]; then
      return 1
    fi
  done <<< "$deps"
  return 0
}
```

Replace with:

```bash
# --- Dependency checking ---
dependencies_met() {
  local issue_num="$1"
  local board_items="$2"
  local body
  body=$(gh issue view "$issue_num" --repo "${OWNER}/markethawk" --json body -q '.body' 2>/dev/null) || return 0
  local deps
  deps=$(echo "$body" | grep -oP 'Depends on:\s*#\K\d+' || true)
  if [ -z "$deps" ]; then
    return 0
  fi
  while IFS= read -r dep_num; do
    local dep_status
    dep_status=$(echo "$board_items" | jq -r ".items[] | select(.content.number == $dep_num) | .status" 2>/dev/null)
    if [ -z "$dep_status" ]; then
      local dep_state
      dep_state=$(gh issue view "$dep_num" --repo "${OWNER}/markethawk" --json state -q '.state' 2>/dev/null || true)
      if [ "$dep_state" = "CLOSED" ]; then
        echo "[$(date -u +%FT%TZ)] dep_gate issue=#${issue_num} dep=#${dep_num} resolved=closed_off_board"
        continue
      fi
      echo "[$(date -u +%FT%TZ)] dep_gate issue=#${issue_num} blocked_by=#${dep_num} dep_status=off_board"
      return 1
    fi
    if [ "$dep_status" != "Done" ]; then
      echo "[$(date -u +%FT%TZ)] dep_gate issue=#${issue_num} blocked_by=#${dep_num} dep_status=${dep_status}"
      return 1
    fi
  done <<< "$deps"
  return 0
}
```

> **Note on `|| true`**: `dep_state=$(gh ... || true)` ensures `set -euo pipefail` does not abort
> the scheduler daemon when `gh` returns non-zero. The `|| true` outputs nothing (dep_state=""),
> which the subsequent `[ "$dep_state" = "CLOSED" ]` correctly treats as unmet.

### Step 2.2 — Run the full test suite

```bash
cd /workspace/markethawk
bash dark-factory/tests/test_scheduler.sh 2>&1
```

Expected:
```
Results: <N> passed, 0 failed
```

Verify section N specifically:
```bash
bash dark-factory/tests/test_scheduler.sh 2>&1 | grep -E "^  (PASS|FAIL): N"
```

Expected — all 12 assertions pass:
```
  PASS: N1: no Depends on → passes
  PASS: N2: on-board Done → passes
  PASS: N3: on-board Ready → blocked
  PASS: N3: dep_gate log present
  PASS: N4: off-board CLOSED → passes
  PASS: N4: closed_off_board log present
  PASS: N5: off-board OPEN → blocked
  PASS: N5: dep_gate log present
  PASS: N6: off-board gh-failure → blocked
  PASS: N7: two deps, #102 off-board OPEN → blocked
  PASS: N8: two deps, #102 off-board CLOSED → passes
  PASS: N9: body fetch fails → passes
```

### Step 2.3 — Commit the fix

```bash
cd /workspace/markethawk
git add dark-factory/scheduler.sh
git commit -m "fix: dependencies_met() off-board fallback + dep_gate log (#389)"
```

Expected: `[refine/... <hash>] fix: dependencies_met() off-board fallback + dep_gate log (#389)`

---

## Post-Merge Rebuild

`scheduler.sh` is baked into the dark-factory image. After this branch is merged to main:

```bash
docker compose build backlog-scheduler
docker compose --profile scheduler up -d --force-recreate backlog-scheduler
```
