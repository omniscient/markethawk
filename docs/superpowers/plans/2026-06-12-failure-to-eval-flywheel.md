# Failure-to-Eval Flywheel — Implementation Plan (issue #336)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Reflexion-style post-mortem loop to the dark factory circuit-break path. When a non-rate-limit run fails, a haiku agent reads the failure artefacts and archon transcript, posts a root-cause comment (idempotent, marker-based), applies a `factory-regression` label, and appends a JSONL line to the eval corpus — building a durable benchmark feed and feeding future retries with context.

**Architecture:** Two existing shell scripts are extended; one new file is created:
- `dark-factory/entrypoint.sh`: new `run_post_mortem()` function called from (a) the main loop's non-rate-limit failure branch and (b) the `on_failure()` ERR trap
- `dark-factory/scheduler.sh`: `trip_to_blocked()` gains one additional `gh issue edit --add-label factory-regression` call
- `dark-factory/evals/factory-failures.jsonl`: new empty corpus file committed to the branch

**Tech Stack:** Bash, `claude` CLI (`claude-haiku-4-5-20251001` model), `jq`, `gh` CLI, `git`

**Spec:** `docs/superpowers/specs/2026-06-12-failure-to-eval-flywheel-design.md` · **Ticket:** #336

---

## File Structure

| File | Change |
|------|--------|
| `dark-factory/entrypoint.sh` | Add `DF_POST_MORTEM_MARKER` constant + `run_post_mortem()` function; wire into failure paths |
| `dark-factory/scheduler.sh` | Add `factory-regression` label in `trip_to_blocked()` after `needs-discussion` |
| `dark-factory/evals/factory-failures.jsonl` | New empty file — eval corpus |
| `dark-factory/tests/test_scheduler.sh` | Add `factory-regression` assertion to section B (TDD) |
| `DEVELOPMENT.md` | Add "Eval Flywheel" section before Security Notes |

---

## Task 1: Bootstrap `dark-factory/evals/factory-failures.jsonl` and `factory-regression` GitHub label

**Files:**
- New: `dark-factory/evals/factory-failures.jsonl`

- [ ] **Step 1: Create the directory and empty corpus file**

```bash
mkdir -p dark-factory/evals
touch dark-factory/evals/factory-failures.jsonl
```

- [ ] **Step 2: Create the `factory-regression` GitHub label** (idempotent — `|| true` if already exists)

```bash
gh label create "factory-regression" \
  --repo omniscient/markethawk \
  --description "Failed dark factory run promoted to eval corpus" \
  --color "B60205" || true
```

Expected: `Label 'factory-regression' created` (or silently succeeds if already present).

- [ ] **Step 3: Commit**

```bash
git add dark-factory/evals/factory-failures.jsonl
git commit -m "feat(evals): bootstrap factory-failures.jsonl eval corpus"
```

Expected: `1 file changed, 0 insertions(+), 0 deletions(-)`

---

## Task 2: Add `DF_POST_MORTEM_MARKER` constant to `entrypoint.sh`

**Files:**
- Modify: `dark-factory/entrypoint.sh`

- [ ] **Step 1: Add constant alongside existing markers** (after lines 95-97)

Find the marker block:
```bash
COST_MARKER="<!-- dark-factory-cost-report -->"
REFINE_FAILURE_MARKER="<!-- df-refine-failure -->"
FACTORY_FAILURE_MARKER="<!-- df-factory-failure -->"
```

Add immediately after:
```bash
DF_POST_MORTEM_MARKER="<!-- df-post-mortem -->"
```

- [ ] **Step 2: Verify syntax**

```bash
bash -n dark-factory/entrypoint.sh
```

Expected: no output (clean parse).

- [ ] **Step 3: Commit**

```bash
git add dark-factory/entrypoint.sh
git commit -m "feat(entrypoint): add DF_POST_MORTEM_MARKER constant"
```

---

## Task 3: Add `run_post_mortem()` function to `entrypoint.sh`

**Files:**
- Modify: `dark-factory/entrypoint.sh`

- [ ] **Step 1: Insert function** immediately before the `# --- Error handler: move ticket back to Ready and post comment ---` comment (around line 236)

```bash
# --- Post-mortem generator: diagnoses a failed factory run and posts a marker comment ---
# $1: path to archon transcript temp file (pass empty string if not available)
# $2: exit code of the failed run (defaults to $EXIT_CODE global if omitted)
# Call sites always use: run_post_mortem "$TMP_OUT" "$EXIT_CODE" || true
run_post_mortem() {
  [ -z "${ISSUE_NUM:-}" ] && return 0
  [ "$INTENT" = "refine" ]     && return 0
  [ "$INTENT" = "plan" ]       && return 0
  [ "$INTENT" = "deconflict" ] && return 0

  local transcript_file="${1:-}"
  local run_exit_code="${2:-${EXIT_CODE:-1}}"
  local ARTIFACTS_DIR="/tmp/artifacts/${ISSUE_NUM}"

  # Read issue title from artifacts (may not exist on very early failures)
  local ISSUE_TITLE
  ISSUE_TITLE=$(jq -r '.title // "unknown"' "$ARTIFACTS_DIR/issue.json" 2>/dev/null || echo "unknown")

  # Assemble transcript tail (last 200 lines; empty string if file not available)
  local TRANSCRIPT_TAIL="(no transcript available)"
  if [ -n "$transcript_file" ] && [ -f "$transcript_file" ]; then
    TRANSCRIPT_TAIL=$(tail -200 "$transcript_file" 2>/dev/null || echo "(transcript unreadable)")
  fi

  # Assemble artifact summaries (head -50 of each artifact present in ARTIFACTS_DIR)
  local ARTIFACTS_SUMMARY=""
  for artifact in implementation.md conformance.md review.md; do
    local apath="$ARTIFACTS_DIR/$artifact"
    if [ -f "$apath" ]; then
      ARTIFACTS_SUMMARY="${ARTIFACTS_SUMMARY}
### ${artifact}
$(head -50 "$apath" 2>/dev/null || true)"
    fi
  done
  [ -z "$ARTIFACTS_SUMMARY" ] && ARTIFACTS_SUMMARY="(no artifacts written before failure)"

  # Build haiku prompt
  local PROMPT_FILE
  PROMPT_FILE=$(mktemp /tmp/postmortem-prompt-XXXXXX.txt) || return 0
  cat > "$PROMPT_FILE" << 'HAIKU_PROMPT_EOF'
You are diagnosing a failed AI coding factory run.
HAIKU_PROMPT_EOF

  # Append variable content separately to avoid heredoc quoting issues
  cat >> "$PROMPT_FILE" << HAIKU_PROMPT_EOF
Issue: #${ISSUE_NUM} — ${ISSUE_TITLE}
Phase: ${INTENT:-unknown}
Exit code: ${run_exit_code}

Archon transcript tail (last 200 lines):
${TRANSCRIPT_TAIL}

Artifacts produced before failure:
${ARTIFACTS_SUMMARY}

Write ONE paragraph (3-5 sentences) explaining the most likely root cause of this failure.
Focus on: what the agent tried to do, what went wrong, and what a retry should do differently.
Do not repeat the transcript verbatim. Be concrete and actionable.
HAIKU_PROMPT_EOF

  local POSTMORTEM
  POSTMORTEM=$(claude -p --model claude-haiku-4-5-20251001 < "$PROMPT_FILE" 2>/dev/null || true)
  rm -f "$PROMPT_FILE"
  [ -z "$POSTMORTEM" ] && return 0

  # Post comment (idempotent — post_or_update_comment replaces existing marker comment)
  post_or_update_comment "$DF_POST_MORTEM_MARKER" \
"${DF_POST_MORTEM_MARKER}
## Dark Factory — Post-Mortem

**Issue:** #${ISSUE_NUM} · **Phase:** ${INTENT:-unknown} · **Exit code:** ${run_exit_code}

${POSTMORTEM}

---
*Posted by MarketHawk Dark Factory*"

  # Append JSONL entry to eval corpus and commit
  if [ -d "${CLONE_DIR:-}/.git" ]; then
    local JSONL_FILE="$CLONE_DIR/dark-factory/evals/factory-failures.jsonl"
    jq -cn \
      --arg i "$ISSUE_NUM" \
      --arg t "$ISSUE_TITLE" \
      --arg p "${INTENT:-unknown}" \
      --arg r "$run_exit_code" \
      --arg m "$POSTMORTEM" \
      --arg ts "$(date -u +%FT%TZ)" \
      '{issue: ($i|tonumber), title: $t, phase: $p, exit_code: ($r|tonumber), postmortem: $m, promoted_at: $ts}' \
      >> "$JSONL_FILE" 2>/dev/null || true
    if [ -n "$(git -C "$CLONE_DIR" diff --name-only "$JSONL_FILE" 2>/dev/null)" ]; then
      git -C "$CLONE_DIR" add "$JSONL_FILE" \
      && git -C "$CLONE_DIR" commit --no-verify \
           -m "eval: promote failure of issue #${ISSUE_NUM} to benchmark corpus" || true
    fi
  fi
}
```

- [ ] **Step 2: Verify syntax**

```bash
bash -n dark-factory/entrypoint.sh
```

Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add dark-factory/entrypoint.sh
git commit -m "feat(entrypoint): add run_post_mortem() function with JSONL corpus promotion"
```

---

## Task 4: Wire `run_post_mortem()` into the two failure paths

**Files:**
- Modify: `dark-factory/entrypoint.sh`

There are two wiring points:

### 4a — Main loop non-rate-limit failure path (primary; full transcript available)

- [ ] **Step 1: Find the non-rate-limit tail of the `while true` failure block** (around lines 664-666)

The current end of the non-rate-limit path is:
```bash
    rm -f "$TMP_OUT"
    exit "$EXIT_CODE"
```

(These two lines appear right after `fi` that closes the rate-limit `if grep -qiE "usage limit|..."` block.)

- [ ] **Step 2: Insert `run_post_mortem` call BEFORE `rm -f "$TMP_OUT"`**

Replace:
```bash
    rm -f "$TMP_OUT"
    exit "$EXIT_CODE"
```

With:
```bash
    run_post_mortem "$TMP_OUT" "$EXIT_CODE" || true
    rm -f "$TMP_OUT"
    exit "$EXIT_CODE"
```

### 4b — ERR trap `on_failure()` (secondary; no transcript, degraded post-mortem)

- [ ] **Step 3: Insert `run_post_mortem` call in `on_failure()`** BEFORE the `set_board_status "$STATUS_BLOCKED"` call in the `else` branch

Find in `on_failure()`:
```bash
    else
      echo "Dark factory failed (exit $EXIT_CODE). Moving issue #$ISSUE_NUM back to Ready..."
      set_board_status "$STATUS_BLOCKED" 2>/dev/null || true
      post_or_update_comment "$FACTORY_FAILURE_MARKER" \
```

Replace with:
```bash
    else
      echo "Dark factory failed (exit $EXIT_CODE). Moving issue #$ISSUE_NUM back to Ready..."
      run_post_mortem "" "$EXIT_CODE" || true
      set_board_status "$STATUS_BLOCKED" 2>/dev/null || true
      post_or_update_comment "$FACTORY_FAILURE_MARKER" \
```

- [ ] **Step 4: Verify syntax**

```bash
bash -n dark-factory/entrypoint.sh
```

Expected: no output.

- [ ] **Step 5: Smoke-check the wiring**

```bash
grep -n "run_post_mortem" dark-factory/entrypoint.sh
```

Expected: exactly 2 lines matching — one in the `while true` non-rate-limit path, one in `on_failure()`.

- [ ] **Step 6: Commit**

```bash
git add dark-factory/entrypoint.sh
git commit -m "feat(entrypoint): wire run_post_mortem() into non-rate-limit failure paths"
```

---

## Task 5: `factory-regression` label in `trip_to_blocked()` — TDD

**Files:**
- Modify: `dark-factory/tests/test_scheduler.sh` (failing test first)
- Modify: `dark-factory/scheduler.sh` (implementation)

### 5a — Write the failing test

- [ ] **Step 1: Add `factory-regression` assertion to section B**

In `dark-factory/tests/test_scheduler.sh`, find the existing assertion in section B:
```bash
assert_eq "gh issue edit adds needs-discussion" \
  "1" "$(grep -c 'issue edit 99.*needs-discussion' "$STUB_LOG" || echo 0)"
```

Insert immediately after:
```bash
assert_eq "gh issue edit adds factory-regression label" \
  "1" "$(grep -c 'issue edit 99.*factory-regression' "$STUB_LOG" || echo 0)"
```

- [ ] **Step 2: Run tests to verify the new assertion fails**

```bash
bash dark-factory/tests/test_scheduler.sh
```

Expected output contains:
```
  FAIL: gh issue edit adds factory-regression label — expected='1' got='0'
```

### 5b — Implement

- [ ] **Step 3: Add `factory-regression` label in `trip_to_blocked()`**

In `dark-factory/scheduler.sh`, find (lines ~357-359):
```bash
  # 2. needs-discussion is in SKIP_LABELS — filters this issue from every dispatch loop
  gh issue edit "$issue_num" --repo "${OWNER}/markethawk" \
    --add-label needs-discussion 2>/dev/null || true
```

Add immediately after:
```bash
  gh issue edit "$issue_num" --repo "${OWNER}/markethawk" \
    --add-label factory-regression 2>/dev/null || true
```

- [ ] **Step 4: Run tests to verify all pass**

```bash
bash dark-factory/tests/test_scheduler.sh
```

Expected:
```
Results: N passed, 0 failed
```

(Where N is the total count of previously-passing tests plus the new assertion.)

- [ ] **Step 5: Commit**

```bash
git add dark-factory/scheduler.sh dark-factory/tests/test_scheduler.sh
git commit -m "feat(scheduler): apply factory-regression label in trip_to_blocked()"
```

---

## Task 6: Document the eval flywheel in DEVELOPMENT.md

**Files:**
- Modify: `DEVELOPMENT.md`

- [ ] **Step 1: Add section** immediately before `## Security Notes` (around line 400)

```markdown
## Dark Factory Eval Flywheel

When a dark factory run fails with a non-rate-limit exit code, the circuit-break path automatically promotes the failure into the eval corpus:

1. **Post-mortem comment** — a haiku agent reads the archon transcript tail and any artefacts from `$ARTIFACTS_DIR` (`implementation.md`, `conformance.md`, `review.md`), then posts a `<!-- df-post-mortem -->` marker comment on the issue explaining the root cause. The comment is idempotent (reruns replace it, not append). Retry/continue runs include this comment automatically via the existing `gh issue view --json comments` fetch — no retry-context changes needed.

2. **`factory-regression` label** — `trip_to_blocked()` in the scheduler applies this label alongside `needs-discussion` whenever the circuit breaker trips. The label is the human-queryable index of all machine-confirmed failures.

3. **JSONL corpus** — `dark-factory/evals/factory-failures.jsonl` accumulates one line per circuit-break trip. Each line is valid JSON committed to the issue branch:
   ```json
   {"issue": 123, "title": "Add feature X", "phase": "implement", "exit_code": 1, "postmortem": "The agent failed because...", "promoted_at": "2026-06-12T04:00:00Z"}
   ```
   The file persists failures even after GitHub labels are triaged off.

### Querying the eval corpus

```bash
# All machine-promoted failures (label is the human-facing index)
gh issue list --repo omniscient/markethawk --label factory-regression

# Full JSONL corpus (survives label removal)
cat dark-factory/evals/factory-failures.jsonl | jq .

# Manually promote a failure (add the label from the issue UI or CLI)
gh issue edit <number> --repo omniscient/markethawk --add-label factory-regression
```

### C3 replay harness (future work)

The JSONL corpus feeds the planned replay harness (architecture review candidate C3). When built, C3 will replay failures against new model/workflow versions to measure improvement over time. See `docs/dark-factory-architecture-review-2026-06-11.html` for the C3 candidate spec.
```

- [ ] **Step 2: Commit**

```bash
git add DEVELOPMENT.md
git commit -m "docs: add eval flywheel section to DEVELOPMENT.md"
```

---

## Task Summary

| Task | Files | Steps |
|------|-------|-------|
| 1: Bootstrap JSONL corpus + GitHub label | `dark-factory/evals/factory-failures.jsonl` | 3 |
| 2: `DF_POST_MORTEM_MARKER` constant | `dark-factory/entrypoint.sh` | 3 |
| 3: `run_post_mortem()` function | `dark-factory/entrypoint.sh` | 3 |
| 4: Wire failure paths | `dark-factory/entrypoint.sh` | 6 |
| 5: `factory-regression` label (TDD) | `dark-factory/scheduler.sh`, `dark-factory/tests/test_scheduler.sh` | 5 |
| 6: DEVELOPMENT.md docs | `DEVELOPMENT.md` | 2 |

**Total: 6 tasks, 22 steps**
