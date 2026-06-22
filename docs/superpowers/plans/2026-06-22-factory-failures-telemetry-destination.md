# Plan: factory-failures.jsonl Telemetry Destination Fix

**Date:** 2026-06-22  
**Issue:** [#521](https://github.com/omniscient/markethawk/issues/521)  
**Spec:** `docs/superpowers/specs/2026-06-20-factory-failures-telemetry-destination-design.md`  
**Goal:** Redirect `run_post_mortem()` failure telemetry writes from a git worktree on `main` to the per-run `ARTIFACTS_DIR`. Drop all git operations from the function. Add `.gitignore` entry to permanently block future commits.

## Architecture

`run_post_mortem()` in `dark-factory/entrypoint.sh` (line 160) currently:
1. Builds a JSONL record for the factory failure
2. Fetches `origin/main`, creates a temporary detached worktree, appends the record to `dark-factory/evals/factory-failures.jsonl`, commits, pushes `HEAD:main`, and removes the worktree

After this fix:
1. Builds the same JSONL record
2. Appends it to `${ARTIFACTS_DIR}/factory-failures.jsonl` (non-git, per-run directory)
3. Does no git operations

**Two files changed total:** `dark-factory/entrypoint.sh`, `.gitignore`  
**One test file updated:** `dark-factory/tests/test_431_telemetry_isolation.sh`

## Tech Stack

- Shell (bash): `dark-factory/entrypoint.sh`, `dark-factory/tests/test_431_telemetry_isolation.sh`
- `.gitignore`: simple text append

## File Structure

| File | Change |
|------|--------|
| `dark-factory/entrypoint.sh` | Rename local `ARTIFACTS_DIR` shadow → `ARTIFACTS_BASE_DIR` (lines ~178–183); replace worktree block (lines ~233–259) with ARTIFACTS_DIR write |
| `.gitignore` | Add `dark-factory/evals/factory-failures.jsonl` entry |
| `dark-factory/tests/test_431_telemetry_isolation.sh` | Update assertions: no git ops, ARTIFACTS_DIR file written |

---

## Task 1: Update `run_post_mortem()` — redirect write to ARTIFACTS_DIR, drop git ops

**Files:**
- `dark-factory/tests/test_431_telemetry_isolation.sh` (test first)
- `dark-factory/entrypoint.sh` (implementation)

### TDD Steps

#### Step 1.1 — Write failing test

Replace the body of `dark-factory/tests/test_431_telemetry_isolation.sh` with the new test that asserts the ARTIFACTS_DIR approach:

```bash
#!/usr/bin/env bash
# Test: run_post_mortem() writes failure telemetry to ARTIFACTS_DIR,
# with zero git operations — no worktree, no push, no commit.
# Issue #521
# Run: bash dark-factory/tests/test_431_telemetry_isolation.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── Stubs ────────────────────────────────────────────────────────────────────
export GH_TOKEN="stub-token"
export CLAUDE_CODE_OAUTH_TOKEN="stub-token"

GIT_LOG=$(mktemp /tmp/521-git-XXXXXX.log)

git() {
  echo "git $*" >> "$GIT_LOG"
  return 0
}
export -f git

gh() { echo "stub-title"; return 0; }
export -f gh

docker() { return 0; }
export -f docker

claude() { echo "Stub post-mortem text for test."; return 0; }
export -f claude

# ── Source entrypoint (guard prevents clone + main execution) ─────────────
ENTRYPOINT_SOURCE_ONLY=1 source "$SCRIPT_DIR/../entrypoint.sh"

# Reset strict error handling from entrypoint — test context manages its own flow
trap - ERR
set +e
set +u
set +o pipefail

# ── Test fixture ──────────────────────────────────────────────────────────
CLONE_DIR=$(mktemp -d /tmp/521-clone-XXXXXX)

# Set ARTIFACTS_DIR to a temp directory (simulates the global per-run dir)
ARTIFACTS_DIR=$(mktemp -d /tmp/521-artifacts-XXXXXX)
export ARTIFACTS_DIR

JSONL_IN_ARTIFACTS="${ARTIFACTS_DIR}/factory-failures.jsonl"

ISSUE_NUM=521
INTENT=fix

# ── Run ───────────────────────────────────────────────────────────────────
run_post_mortem 1 ""

# ── Assertions ────────────────────────────────────────────────────────────
PASSED=0; FAILED=0
assert_eq() {
  local desc="$1" expected="$2" actual="$3"
  if [ "$expected" = "$actual" ]; then
    echo "  PASS: $desc"; PASSED=$((PASSED + 1))
  else
    echo "  FAIL: $desc — expected='$expected' got='$actual'" >&2
    FAILED=$((FAILED + 1))
  fi
}
assert_true() {
  local desc="$1" condition="$2"
  if eval "$condition"; then
    echo "  PASS: $desc"; PASSED=$((PASSED + 1))
  else
    echo "  FAIL: $desc — condition false: $condition" >&2
    FAILED=$((FAILED + 1))
  fi
}

echo "=== #521: Telemetry isolation — ARTIFACTS_DIR write, zero git operations ==="
echo ""

GIT_CALL_COUNT=$(wc -l < "$GIT_LOG" 2>/dev/null || echo "0")
assert_eq "no git operations called" "0" "$GIT_CALL_COUNT"

assert_true "factory-failures.jsonl exists in ARTIFACTS_DIR" "[ -f '$JSONL_IN_ARTIFACTS' ]"

LINE_COUNT=$(wc -l < "$JSONL_IN_ARTIFACTS" 2>/dev/null || echo "0")
assert_eq "exactly one JSONL line written" "1" "$LINE_COUNT"

VALID_JSON=$(python3 -c "import json,sys; json.load(open('$JSONL_IN_ARTIFACTS'))" 2>/dev/null && echo "ok" || echo "invalid")
assert_eq "JSONL line is valid JSON" "ok" "$VALID_JSON"

ISSUE_FIELD=$(python3 -c "import json; d=json.load(open('$JSONL_IN_ARTIFACTS')); print(d.get('issue','missing'))" 2>/dev/null || echo "missing")
assert_eq "issue field matches ISSUE_NUM" "521" "$ISSUE_FIELD"

# ── Cleanup ───────────────────────────────────────────────────────────────
rm -f "$GIT_LOG"
rm -rf "$CLONE_DIR" "$ARTIFACTS_DIR"

echo ""
echo "Results: ${PASSED} passed, ${FAILED} failed"
[ "$FAILED" -eq 0 ]
```

#### Step 1.2 — Verify test fails (expected)

```bash
bash dark-factory/tests/test_431_telemetry_isolation.sh
# Expected: multiple FAIL lines because:
# - git operations are still called (worktree approach)
# - factory-failures.jsonl does NOT exist in ARTIFACTS_DIR
```

Expected output includes failures like:
```
  FAIL: no git operations called — expected='0' got='7'
  FAIL: factory-failures.jsonl exists in ARTIFACTS_DIR — condition false
```

#### Step 1.3 — Implement: fix `run_post_mortem()` in `entrypoint.sh`

**Change 1 of 2**: Rename the local `ARTIFACTS_DIR` shadow at line ~178 to `ARTIFACTS_BASE_DIR`.

Find this block (lines 178–183):
```bash
  local ARTIFACTS_DIR="${HOME}/.archon/workspaces/omniscient/markethawk/artifacts/runs"
  # Find the most recent run artifacts directory for this issue
  local run_dir
  run_dir=$(ls -dt "${ARTIFACTS_DIR}"/*/issue.json 2>/dev/null \
    | xargs grep -l "\"resolved_number\": ${ISSUE_NUM}" 2>/dev/null \
    | head -1 | xargs dirname 2>/dev/null || true)
```

Replace with:
```bash
  local ARTIFACTS_BASE_DIR="${HOME}/.archon/workspaces/omniscient/markethawk/artifacts/runs"
  # Find the most recent run artifacts directory for this issue
  local run_dir
  run_dir=$(ls -dt "${ARTIFACTS_BASE_DIR}"/*/issue.json 2>/dev/null \
    | xargs grep -l "\"resolved_number\": ${ISSUE_NUM}" 2>/dev/null \
    | head -1 | xargs dirname 2>/dev/null || true)
```

**Change 2 of 2**: Replace the worktree block (lines ~233–259) with an ARTIFACTS_DIR write.

Find this block:
```bash
  # Write failure telemetry to main via a temporary detached worktree.
  # The feature-branch CLONE_DIR working tree and index are never touched,
  # so factory-failures.jsonl can never appear in the feature-branch diff.
  if [ -d "${CLONE_DIR}" ]; then
    local JSONL_PATH="dark-factory/evals/factory-failures.jsonl"
    local excerpt
    excerpt=$(echo "$post_mortem_text" | head -c 500 | tr '\n' ' ')
    local record
    record=$(printf '{"issue":%s,"title":"%s","phase":"%s","exit_code":%s,"postmortem":"%s","promoted_at":"%s"}\n' \
      "${ISSUE_NUM}" \
      "$(gh issue view "${ISSUE_NUM}" --repo "omniscient/markethawk" --json title --jq '.title' 2>/dev/null | sed 's/"/\\"/g' || echo "unknown")" \
      "${INTENT:-fix}" \
      "${exit_code}" \
      "$(echo "$excerpt" | sed 's/"/\\"/g')" \
      "$PROMOTED_AT")
    (
      git -C "${CLONE_DIR}" fetch origin main 2>/dev/null || true
      WT=$(mktemp -d)
      git -C "${CLONE_DIR}" worktree add --detach "$WT" origin/main 2>/dev/null
      echo "$record" >> "${WT}/${JSONL_PATH}"
      git -C "$WT" add "${JSONL_PATH}"
      git -C "$WT" commit -m "eval: record factory failure for issue #${ISSUE_NUM}"
      git -C "$WT" push origin HEAD:main 2>/dev/null
      git -C "${CLONE_DIR}" worktree remove --force "$WT" 2>/dev/null || true
      rm -rf "$WT" 2>/dev/null || true
    ) 2>/dev/null || true
  fi
}
```

Replace with:
```bash
  # Write failure telemetry to per-run ARTIFACTS_DIR (no git operations).
  if [ -n "${ARTIFACTS_DIR:-}" ]; then
    local JSONL_PATH="${ARTIFACTS_DIR}/factory-failures.jsonl"
    local excerpt
    excerpt=$(echo "$post_mortem_text" | head -c 500 | tr '\n' ' ')
    local record
    record=$(printf '{"issue":%s,"title":"%s","phase":"%s","exit_code":%s,"postmortem":"%s","promoted_at":"%s"}\n' \
      "${ISSUE_NUM}" \
      "$(gh issue view "${ISSUE_NUM}" --repo "omniscient/markethawk" --json title --jq '.title' 2>/dev/null | sed 's/"/\\"/g' || echo "unknown")" \
      "${INTENT:-fix}" \
      "${exit_code}" \
      "$(echo "$excerpt" | sed 's/"/\\"/g')" \
      "$PROMOTED_AT")
    echo "$record" >> "$JSONL_PATH" 2>/dev/null || true
  fi
}
```

#### Step 1.4 — Verify test passes

```bash
bash dark-factory/tests/test_431_telemetry_isolation.sh
```

Expected output:
```
=== #521: Telemetry isolation — ARTIFACTS_DIR write, zero git operations ===

  PASS: no git operations called
  PASS: factory-failures.jsonl exists in ARTIFACTS_DIR
  PASS: exactly one JSONL line written
  PASS: JSONL line is valid JSON
  PASS: issue field matches ISSUE_NUM

Results: 5 passed, 0 failed
```

Exit code: `0`

#### Step 1.5 — Commit

```bash
git add dark-factory/entrypoint.sh dark-factory/tests/test_431_telemetry_isolation.sh
git commit -m "fix(dark-factory): redirect failure telemetry to ARTIFACTS_DIR, drop git worktree (#521)"
```

Expected output: `[feat/issue-521-... <hash>] fix(dark-factory): redirect failure telemetry to ARTIFACTS_DIR, drop git worktree (#521)`

---

## Task 2: Add `.gitignore` entry for `factory-failures.jsonl`

**Files:**
- `.gitignore`

### TDD Steps

#### Step 2.1 — Write failing check

```bash
grep -q "dark-factory/evals/factory-failures.jsonl" .gitignore && echo "PRESENT" || echo "MISSING"
# Expected: MISSING
```

#### Step 2.2 — Implement: add `.gitignore` entry

Find the `# Dark factory runtime` block in `.gitignore`:
```
# Dark factory runtime
dark-factory/tmp/
```

Append the new entry immediately after `dark-factory/tmp/`:
```
# Dark factory runtime
dark-factory/tmp/
dark-factory/evals/factory-failures.jsonl
```

#### Step 2.3 — Verify check passes

```bash
grep -q "dark-factory/evals/factory-failures.jsonl" .gitignore && echo "PRESENT" || echo "MISSING"
# Expected: PRESENT

git check-ignore -v dark-factory/evals/factory-failures.jsonl
# Expected: .gitignore:<N>:dark-factory/evals/factory-failures.jsonl  dark-factory/evals/factory-failures.jsonl
```

Note: `dark-factory/evals/factory-failures.jsonl` remains **git-tracked** per requirement 4 (no `git rm`).
The `.gitignore` entry is a forward guard for future untracked copies. The write path redirect in
Task 1 is what prevents the file from ever being modified on feature branches — not gitignore alone.

#### Step 2.4 — Commit

```bash
git add .gitignore
git commit -m "chore: gitignore dark-factory/evals/factory-failures.jsonl (#521)"
```

Expected output: `[feat/issue-521-... <hash>] chore: gitignore dark-factory/evals/factory-failures.jsonl (#521)`

---

## Summary

| Task | Files | Steps |
|------|-------|-------|
| 1. Redirect telemetry write | `entrypoint.sh`, `tests/test_431_telemetry_isolation.sh` | 5 |
| 2. Add .gitignore entry | `.gitignore` | 4 |

**Total: 2 tasks, 9 steps**
