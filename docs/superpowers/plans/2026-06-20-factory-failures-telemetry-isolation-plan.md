# Plan: Factory Failures Telemetry Isolation from Feature Branches

**Date:** 2026-06-20  
**Issue:** #431  
**Spec:** [docs/superpowers/specs/2026-06-14-factory-failures-telemetry-isolation-design.md](../specs/2026-06-14-factory-failures-telemetry-isolation-design.md)  
**Branch:** `refine/issue-431-cleanup-dark-factory---factory-failures-`

---

## Goal

Fix `run_post_mortem()` in `dark-factory/entrypoint.sh` so failure telemetry
(`dark-factory/evals/factory-failures.jsonl`) is written to `origin/main` via a
temporary git worktree instead of being committed to the current feature branch.
This eliminates the repeated `scope-spillover` tickets triggered by the existing
direct-append-then-push-to-feature-branch pattern.

---

## Architecture

Single-file change in the dark factory entrypoint shell script. No model changes,
no migrations, no frontend changes. A new test file is added to
`dark-factory/tests/`. Because `entrypoint.sh` is **baked into the dark-factory
image** (not mounted at runtime), the fix requires an image rebuild after merge.

The worktree approach (Approach B in the spec) pushes the JSONL record directly to
`main` from a temporary detached worktree, leaving the feature-branch working tree
and index completely untouched.

---

## Tech Stack

- Bash / git worktree (git ≥ 2.5, available in the dark-factory image)
- Dark Factory image baked from `dark-factory/Dockerfile`
- Shell-based test suite in `dark-factory/tests/`

---

## File Structure

| File | Change |
|------|--------|
| `dark-factory/entrypoint.sh` | (1) Add `ENTRYPOINT_SOURCE_ONLY` sourcing guard before the clone block; (2) Replace append+commit+push block in `run_post_mortem()` with worktree pattern |
| `dark-factory/tests/test_431_telemetry_isolation.sh` | New: behavioral test verifying the worktree approach |

No other files are touched. The JSONL schema is unchanged (spec requirement 4). No removal of existing records from `main` (spec requirement 5; that is scope of #507).

---

## Task 1: Add ENTRYPOINT_SOURCE_ONLY guard and write the failing test

**Files:** `dark-factory/entrypoint.sh`, `dark-factory/tests/test_431_telemetry_isolation.sh`

**Purpose:** Prove the test catches the bug before implementing the fix. The guard
enables sourcing `entrypoint.sh` in test context without triggering the actual git
clone and main execution flow.

### TDD Steps

**Step 1.1 — Add the sourcing guard to `entrypoint.sh`**

In `dark-factory/entrypoint.sh`, locate the `# --- Clone the repo ---` comment
block (after all function definitions, around line 429). Insert the guard immediately
before it:

```bash
# Guard: allow sourcing for unit tests without running the main execution block.
# Set ENTRYPOINT_SOURCE_ONLY=1 before sourcing. External commands (git, gh, docker,
# claude) must be stubbed by the test to prevent real side effects.
[ "${ENTRYPOINT_SOURCE_ONLY:-0}" = "1" ] && return 0

# --- Clone the repo ---
```

This guard makes all function definitions (including `run_post_mortem`) accessible
to tests while preventing `git clone`, `pip install`, `archon workflow run`, etc.
from executing.

**Step 1.2 — Write the failing test**

Create `dark-factory/tests/test_431_telemetry_isolation.sh`:

```bash
#!/usr/bin/env bash
# Test: run_post_mortem() writes failure telemetry via a git worktree on main,
# never touching the feature-branch CLONE_DIR.
# Issue #431
# Run: bash dark-factory/tests/test_431_telemetry_isolation.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── Stubs ────────────────────────────────────────────────────────────────────
# Set before sourcing so they're active during the module-level setup code in
# entrypoint.sh (git config, gh auth, docker ps concurrency check).

export GH_TOKEN="stub-token"
export CLAUDE_CODE_OAUTH_TOKEN="stub-token"

# git stub: log every call; when a worktree is added, create the expected JSONL
# directory inside the worktree dir so the subsequent append succeeds.
GIT_LOG=$(mktemp /tmp/431-git-XXXXXX.log)

git() {
  echo "git $*" >> "$GIT_LOG"
  local prev=""
  for arg in "$@"; do
    if [ "$prev" = "--detach" ]; then
      # $arg is the worktree directory path passed by the implementation
      mkdir -p "${arg}/dark-factory/evals"
      # Seed with existing record (simulates origin/main content)
      echo '{"issue":1,"title":"prior","phase":"fix","exit_code":1,"postmortem":"prior","promoted_at":"2026-01-01T00:00:00Z"}' \
        > "${arg}/dark-factory/evals/factory-failures.jsonl"
      break
    fi
    prev="$arg"
  done
  return 0
}
export -f git

# gh stub: return stub JSON / text; covers issue view, api, issue comment calls
gh() { echo "stub-title"; return 0; }
export -f gh

# docker stub: return empty output so the WIP-limit check sees RUNNING=0
docker() { return 0; }
export -f docker

# claude stub: return canned post-mortem text
claude() { echo "Stub post-mortem text for test."; return 0; }
export -f claude

# ── Source entrypoint (guard prevents clone + main execution) ─────────────
ENTRYPOINT_SOURCE_ONLY=1 source "$SCRIPT_DIR/../entrypoint.sh"

# ── Test fixture ──────────────────────────────────────────────────────────
# Override CLONE_DIR with a temp directory that has the JSONL file in place.
CLONE_DIR=$(mktemp -d /tmp/431-clone-XXXXXX)
JSONL_IN_CLONE="${CLONE_DIR}/dark-factory/evals/factory-failures.jsonl"
mkdir -p "$(dirname "$JSONL_IN_CLONE")"
echo '{"issue":1,"title":"prior","phase":"fix","exit_code":1,"postmortem":"prior","promoted_at":"2026-01-01T00:00:00Z"}' \
  > "$JSONL_IN_CLONE"

INITIAL_LINES=$(wc -l < "$JSONL_IN_CLONE")
INITIAL_MD5=$(md5sum "$JSONL_IN_CLONE" | awk '{print $1}')

# Set globals that run_post_mortem() reads
ISSUE_NUM=431
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

echo "=== #431: Telemetry isolation — worktree on main, never touches CLONE_DIR ==="
echo ""

# AC1: CLONE_DIR jsonl must not be modified (same content as before the call)
FINAL_MD5=$(md5sum "$JSONL_IN_CLONE" | awk '{print $1}')
assert_eq "CLONE_DIR jsonl not modified (md5)" "$INITIAL_MD5" "$FINAL_MD5"

FINAL_LINES=$(wc -l < "$JSONL_IN_CLONE")
assert_eq "CLONE_DIR jsonl line count unchanged" "$INITIAL_LINES" "$FINAL_LINES"

# AC2 / Approach B: push must target HEAD:main (worktree approach)
PUSH_TO_MAIN=$(grep -c 'push origin HEAD:main' "$GIT_LOG" || echo 0)
assert_eq "push targets HEAD:main exactly once" "1" "$PUSH_TO_MAIN"

# AC1 (negative): no push directly to the feature branch
PUSH_TO_BRANCH=$(grep 'push origin' "$GIT_LOG" | grep -cv 'HEAD:main' || echo 0)
assert_eq "no direct push to feature branch" "0" "$PUSH_TO_BRANCH"

# Approach B structural checks
WORKTREE_ADD=$(grep -c 'worktree add' "$GIT_LOG" || echo 0)
assert_eq "worktree add called" "1" "$WORKTREE_ADD"

WORKTREE_REMOVE=$(grep -c 'worktree remove' "$GIT_LOG" || echo 0)
assert_eq "worktree remove called" "1" "$WORKTREE_REMOVE"

FETCH_MAIN=$(grep -c 'fetch origin main' "$GIT_LOG" || echo 0)
assert_eq "git fetch origin main called" "1" "$FETCH_MAIN"

# ── Cleanup ───────────────────────────────────────────────────────────────
rm -f "$GIT_LOG"
rm -rf "$CLONE_DIR"

echo ""
echo "Results: ${PASSED} passed, ${FAILED} failed"
[ "$FAILED" -eq 0 ]
```

**Step 1.3 — Run the test (expect failure)**

```bash
bash dark-factory/tests/test_431_telemetry_isolation.sh
```

Expected output (before implementation):
```
=== #431: Telemetry isolation — worktree on main, never touches CLONE_DIR ===

  FAIL: CLONE_DIR jsonl not modified (md5) — expected='<hash>' got='<different-hash>'
  FAIL: CLONE_DIR jsonl line count unchanged — expected='1' got='2'
  FAIL: push targets HEAD:main exactly once — expected='1' got='0'
  PASS: no direct push to feature branch
  FAIL: worktree add called — expected='1' got='0'
  FAIL: worktree remove called — expected='1' got='0'
  FAIL: git fetch origin main called — expected='1' got='0'

Results: 1 passed, 6 failed
```

The old code appends directly to `$JSONL_IN_CLONE` and pushes to `$(git branch --show-current)` — exactly what the test catches.

**Step 1.4 — Commit the failing test and the guard**

```bash
git add dark-factory/entrypoint.sh dark-factory/tests/test_431_telemetry_isolation.sh
git commit -m "test(dark-factory): failing test for #431 telemetry isolation + ENTRYPOINT_SOURCE_ONLY guard"
```

Expected: commit with two files, no failures (the test file is new, the guard is a no-op to existing behavior).

---

## Task 2: Implement the worktree-based telemetry isolation

**Files:** `dark-factory/entrypoint.sh`

**Purpose:** Replace the direct-append+push-to-current-branch block with the
temporary-worktree approach from the spec. After this task the failing test passes.

### TDD Steps

**Step 2.1 — Locate the existing telemetry block**

In `dark-factory/entrypoint.sh`, inside `run_post_mortem()`, find and remove this
block (lines ~233–250):

```bash
  # Append to eval corpus and commit
  local JSONL_PATH="${CLONE_DIR}/dark-factory/evals/factory-failures.jsonl"
  if [ -d "${CLONE_DIR}" ] && [ -f "$JSONL_PATH" ]; then
    local excerpt
    excerpt=$(echo "$post_mortem_text" | head -c 500 | tr '\n' ' ')
    printf '{"issue":%s,"title":"%s","phase":"%s","exit_code":%s,"postmortem":"%s","promoted_at":"%s"}\n' \
      "${ISSUE_NUM}" \
      "$(gh issue view "${ISSUE_NUM}" --repo "omniscient/markethawk" --json title --jq '.title' 2>/dev/null | sed 's/"/\\"/g' || echo "unknown")" \
      "${INTENT:-fix}" \
      "${exit_code}" \
      "$(echo "$excerpt" | sed 's/"/\\"/g')" \
      "$PROMOTED_AT" \
      >> "$JSONL_PATH" 2>/dev/null || true

    (cd "${CLONE_DIR}" && git add dark-factory/evals/factory-failures.jsonl \
      && git commit -m "eval: record factory failure for issue #${ISSUE_NUM}" \
      && git push origin "$(git branch --show-current)" 2>/dev/null) 2>/dev/null || true
  fi
```

**Step 2.2 — Replace with the worktree approach**

In its place insert the following block (directly after the `post_or_update_comment`
call and the `|| true`, still inside `run_post_mortem()`):

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
```

Key differences from the old block:
- `JSONL_PATH` is now relative (used as a path under both `$WT` and the worktree), not absolute into `$CLONE_DIR`
- The outer `if` only checks `[ -d "${CLONE_DIR}" ]` — the JSONL file does not need to pre-exist in `CLONE_DIR` (the worktree checks out `origin/main` where the file already lives)
- `record` is built before the subshell (single `printf` instead of inline command substitution within the append)
- `git fetch origin main` runs first so `origin/main` is as fresh as possible at worktree creation
- Push is `git -C "$WT" push origin HEAD:main` (HEAD of the detached worktree → `main` on remote), not `git push origin $(git branch --show-current)` (which was the feature branch)
- The entire subshell is wrapped in `2>/dev/null || true` (same best-effort posture as before)

**Step 2.3 — Verify the test passes**

```bash
bash dark-factory/tests/test_431_telemetry_isolation.sh
```

Expected output:
```
=== #431: Telemetry isolation — worktree on main, never touches CLONE_DIR ===

  PASS: CLONE_DIR jsonl not modified (md5)
  PASS: CLONE_DIR jsonl line count unchanged
  PASS: push targets HEAD:main exactly once
  PASS: no direct push to feature branch
  PASS: worktree add called
  PASS: worktree remove called
  PASS: git fetch origin main called

Results: 7 passed, 0 failed
```

**Step 2.4 — Confirm no OOS changes**

```bash
git diff --name-only
```
Expected: Only `dark-factory/entrypoint.sh` is modified.

```bash
git diff dark-factory/entrypoint.sh | grep '^[+-]' | grep -v '^---\|^+++' | wc -l
```
Expected: Approximately 20–30 changed lines (the two blocks replacing one another).

**Step 2.5 — Commit the implementation**

```bash
git add dark-factory/entrypoint.sh
git commit -m "fix(dark-factory): write failure telemetry to main via git worktree (#431)

Replaces the direct-append+push-to-current-branch pattern in run_post_mortem()
with a temporary detached worktree on origin/main. The JSONL record is now
appended inside the worktree, committed, and pushed to main directly — the
feature-branch CLONE_DIR is never touched. Eliminates repeated scope-spillover
tickets for factory-failures.jsonl across issues #292 #360 #370 #403.

Deployment: requires image rebuild —
  docker compose --profile factory build dark-factory
  docker compose --profile factory up -d --force-recreate dark-factory"
```

---

## Deployment (post-merge)

Because `entrypoint.sh` is **baked into the dark-factory image** at build time
(not mounted from the repo at runtime), the fix takes effect only after an image
rebuild:

```bash
docker compose --profile factory build dark-factory
docker compose --profile factory up -d --force-recreate dark-factory
```

Verify the new image is running:
```bash
docker inspect markethawk-dark-factory-run-1 --format '{{.Config.Labels}}' 2>/dev/null \
  || docker compose --profile factory images dark-factory
```

---

## Acceptance Criteria Mapping

| Spec AC | Task | Verification |
|---------|------|-------------|
| AC1: feature branch diff never contains factory-failures.jsonl | Task 2 | Test assertion: CLONE_DIR jsonl not modified |
| AC2: telemetry still captured on main | Task 2 | Test assertion: push targets HEAD:main |
| AC3: no future scope-spillover ticket | Task 2 | No write to CLONE_DIR means no diff on feature branch |
| AC4: JSONL schema unchanged | Task 2 | Same `printf` format, same fields |
| AC5: no removal of stale records from main history | N/A (out of scope, #507) | Not touched |
