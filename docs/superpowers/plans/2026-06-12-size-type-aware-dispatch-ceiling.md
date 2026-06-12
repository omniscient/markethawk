# Plan: Size/Type-Aware Dispatch Ceiling in the Scheduler

**Date:** 2026-06-12
**Issue:** #339
**Spec:** docs/superpowers/specs/2026-06-12-size-type-aware-dispatch-ceiling-design.md
**Branch:** refine/issue-339-size-type-aware-dispatch-ceiling-in-the-

---

## Goal

Extend `dark-factory/scheduler.sh` with a dispatch ceiling that classifies every Ready ticket as
below-ceiling (S), at-ceiling (M), or above-ceiling (L / keyword-escalated M) before dispatching.
Above-ceiling tickets are parked in Blocked with a new `above-ceiling` label and a human-pairing
comment; at-ceiling M tickets lose the `plan-pending-review` grace-window auto-advance.

## Architecture

All changes are confined to two files:
- `dark-factory/scheduler.sh` — three new env-var constants, four new bash helpers, and three
  insertion points (Priority 2 ceiling gate, Priority 3 guard, `plan_advance_check` suppression).
- `.claude/skills/refinement/config.yaml` — doc-only mirror of the three new constants, matching
  the existing pattern for `PLAN_GRACE_MINUTES`, `FACTORY_WIP_LIMIT`, etc.

No new services, Docker containers, database models, or migrations are required.
`ABOVE_CEILING_LABEL` is intentionally NOT added to `SKIP_LABELS` so refinement and plan dispatch
remain unaffected for above-ceiling tickets.

## Tech Stack

Bash (`scheduler.sh`), YAML (`config.yaml`). Tested with a standalone bash test script at
`dark-factory/test_dispatch_ceiling.sh`.

---

## File Structure

| File | Change |
|------|--------|
| `dark-factory/scheduler.sh` | +3 constants, +4 helpers, +P2 gate, +P3 guard, +`plan_advance_check` suppression, +inline comment |
| `.claude/skills/refinement/config.yaml` | +`dispatch_ceiling` doc-only section |
| `dark-factory/test_dispatch_ceiling.sh` | new — bash test harness for the 4 helpers and gate logic |

---

## Tasks

### Task 1 — Constants, helper functions, and inline comment

**Files:** `dark-factory/scheduler.sh`, `dark-factory/test_dispatch_ceiling.sh`

#### TDD steps

**Step 1.1 — Write test harness (failing baseline)**

Create `dark-factory/test_dispatch_ceiling.sh`:

```bash
#!/usr/bin/env bash
# Test harness for dispatch ceiling helpers (issue #339)
set -euo pipefail
PASS=0; FAIL=0

assert_eq() {
  local label="$1" got="$2" expected="$3"
  if [ "$got" = "$expected" ]; then
    echo "PASS: $label"; PASS=$((PASS+1))
  else
    echo "FAIL: $label — got='$got' expected='$expected'"; FAIL=$((FAIL+1))
  fi
}
assert_rc() {
  local label="$1" expected_rc="$2"; shift 2
  local rc=0; "$@" || rc=$?
  if [ "$rc" = "$expected_rc" ]; then
    echo "PASS: $label"; PASS=$((PASS+1))
  else
    echo "FAIL: $label — got rc=$rc expected rc=$expected_rc"; FAIL=$((FAIL+1))
  fi
}

# --- Env defaults required by helpers ---
DISPATCH_CEILING_ENABLED="true"
ABOVE_CEILING_LABEL="above-ceiling"
ABOVE_CEILING_KEYWORDS="migration|migrate|performance|perf|architectur|refactor"

# --- Helpers under test (sourced inline for isolation) ---
get_size_label() {
  echo "$1" | jq -r '.labels[]?' 2>/dev/null | grep -oi 'size: [SML]' | awk '{print $2}' | head -1
}
is_above_ceiling() {
  local item="$1" title size
  title=$(echo "$item" | jq -r '.content.title // ""' 2>/dev/null)
  size=$(get_size_label "$item")
  case "$size" in
    L) return 0 ;;
    M) echo "$title" | grep -qiE "${ABOVE_CEILING_KEYWORDS}" && return 0 || return 1 ;;
    *) return 1 ;;
  esac
}
has_above_ceiling_label() {
  echo "$1" | jq -r '.labels[]?' 2>/dev/null | grep -qi "^${ABOVE_CEILING_LABEL}$"
}
is_below_ceiling() {
  local size; size=$(get_size_label "$1")
  case "$size" in S|"") return 0 ;; *) return 1 ;; esac
}

# --- Mock items ---
ITEM_S='{"labels":["size: S","priority: must-have"],"content":{"title":"Fix login bug"}}'
ITEM_M='{"labels":["size: M","priority: must-have"],"content":{"title":"Add new chart"}}'
ITEM_M_MIGRATION='{"labels":["size: M"],"content":{"title":"Run database migration for users table"}}'
ITEM_M_PERF='{"labels":["size: M"],"content":{"title":"Improve performance of scanner query"}}'
ITEM_M_ARCH='{"labels":["size: M"],"content":{"title":"Architectural refactor of provider layer"}}'
ITEM_L='{"labels":["size: L"],"content":{"title":"Big architectural feature"}}'
ITEM_NO_SIZE='{"labels":["priority: must-have"],"content":{"title":"No size label here"}}'
ITEM_ABOVE_LABELED='{"labels":["above-ceiling","size: L"],"content":{"title":"Perf work"}}'

# --- get_size_label ---
assert_eq "get_size_label: S"    "$(get_size_label "$ITEM_S")" "S"
assert_eq "get_size_label: M"    "$(get_size_label "$ITEM_M")" "M"
assert_eq "get_size_label: L"    "$(get_size_label "$ITEM_L")" "L"
assert_eq "get_size_label: none" "$(get_size_label "$ITEM_NO_SIZE")" ""

# --- is_above_ceiling ---
assert_rc "is_above_ceiling: S → false"              1 is_above_ceiling "$ITEM_S"
assert_rc "is_above_ceiling: M no keyword → false"   1 is_above_ceiling "$ITEM_M"
assert_rc "is_above_ceiling: M+migration → true"     0 is_above_ceiling "$ITEM_M_MIGRATION"
assert_rc "is_above_ceiling: M+perf → true"          0 is_above_ceiling "$ITEM_M_PERF"
assert_rc "is_above_ceiling: M+architectur → true"   0 is_above_ceiling "$ITEM_M_ARCH"
assert_rc "is_above_ceiling: L → true"               0 is_above_ceiling "$ITEM_L"
assert_rc "is_above_ceiling: no size → false"        1 is_above_ceiling "$ITEM_NO_SIZE"

# --- has_above_ceiling_label ---
assert_rc "has_above_ceiling_label: absent → false"  1 has_above_ceiling_label "$ITEM_M"
assert_rc "has_above_ceiling_label: present → true"  0 has_above_ceiling_label "$ITEM_ABOVE_LABELED"

# --- is_below_ceiling ---
assert_rc "is_below_ceiling: S → true"               0 is_below_ceiling "$ITEM_S"
assert_rc "is_below_ceiling: no size → true"         0 is_below_ceiling "$ITEM_NO_SIZE"
assert_rc "is_below_ceiling: M → false"              1 is_below_ceiling "$ITEM_M"
assert_rc "is_below_ceiling: L → false"              1 is_below_ceiling "$ITEM_L"

# --- P2 gate simulation ---
p2_gate_outcome() {
  local item="$1"
  if [ "${DISPATCH_CEILING_ENABLED:-true}" = "true" ] && is_above_ceiling "$item"; then
    has_above_ceiling_label "$item" && echo "already_labeled_skip" || echo "block_and_label"
  else
    echo "dispatch"
  fi
}
assert_eq "P2 gate: S → dispatch"            "$(p2_gate_outcome "$ITEM_S")"            "dispatch"
assert_eq "P2 gate: M no kw → dispatch"      "$(p2_gate_outcome "$ITEM_M")"            "dispatch"
assert_eq "P2 gate: M+migration → block"     "$(p2_gate_outcome "$ITEM_M_MIGRATION")"  "block_and_label"
assert_eq "P2 gate: L → block"               "$(p2_gate_outcome "$ITEM_L")"            "block_and_label"
assert_eq "P2 gate: L already labeled → skip" "$(p2_gate_outcome "$ITEM_ABOVE_LABELED")" "already_labeled_skip"

# --- P3 guard simulation ---
p3_guard_outcome() {
  has_above_ceiling_label "$1" && echo "skip" || echo "retry"
}
assert_eq "P3 guard: normal blocked → retry"         "$(p3_guard_outcome "$ITEM_M")"           "retry"
assert_eq "P3 guard: above-ceiling labeled → skip"   "$(p3_guard_outcome "$ITEM_ABOVE_LABELED")" "skip"

# --- plan_advance_check suppression ---
plan_advance_ceiling_outcome() {
  local item="$1"
  if [ "${DISPATCH_CEILING_ENABLED:-true}" = "true" ] && ! is_below_ceiling "$item"; then
    echo "suppressed"
  else
    echo "allowed"
  fi
}
assert_eq "plan_advance: S → allowed"       "$(plan_advance_ceiling_outcome "$ITEM_S")"          "allowed"
assert_eq "plan_advance: no size → allowed" "$(plan_advance_ceiling_outcome "$ITEM_NO_SIZE")"    "allowed"
assert_eq "plan_advance: M → suppressed"    "$(plan_advance_ceiling_outcome "$ITEM_M")"          "suppressed"
assert_eq "plan_advance: M+kw → suppressed" "$(plan_advance_ceiling_outcome "$ITEM_M_MIGRATION")" "suppressed"
assert_eq "plan_advance: L → suppressed"    "$(plan_advance_ceiling_outcome "$ITEM_L")"          "suppressed"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" = "0" ] || exit 1
```

**Step 1.2 — Verify test passes (baseline logic confirmed)**

```bash
bash dark-factory/test_dispatch_ceiling.sh
```

Expected output:
```
PASS: get_size_label: S
...
Results: 27 passed, 0 failed
```

**Step 1.3 — Add constants to `scheduler.sh`**

In `dark-factory/scheduler.sh`, insert after line 17 (`FACTORY_WIP_LIMIT` line),
immediately before the blank line before `# Board constants`:

```bash
# Dispatch ceiling policy (see docs/superpowers/specs/2026-06-12-size-type-aware-dispatch-ceiling-design.md; revisit 2026-09-12)
DISPATCH_CEILING_ENABLED="${DISPATCH_CEILING_ENABLED:-true}"
ABOVE_CEILING_LABEL="${ABOVE_CEILING_LABEL:-above-ceiling}"
ABOVE_CEILING_KEYWORDS="${ABOVE_CEILING_KEYWORDS:-migration|migrate|performance|perf|architectur|refactor}"
```

**Step 1.4 — Add the four helper functions to `scheduler.sh`**

Insert after the closing `}` of `has_direct_to_pr_label()` (line 153),
before `# Returns minutes elapsed since...` / `elapsed_minutes_since_marker`:

```bash
# Returns "S", "M", "L", or "" from the item's labels
get_size_label() {
  echo "$1" | jq -r '.labels[]?' 2>/dev/null | grep -oi 'size: [SML]' | awk '{print $2}' | head -1
}

# True (returns 0) if item is at or above the dispatch ceiling
is_above_ceiling() {
  local item="$1" title size
  title=$(echo "$item" | jq -r '.content.title // ""' 2>/dev/null)
  size=$(get_size_label "$item")
  case "$size" in
    L) return 0 ;;
    M) echo "$title" | grep -qiE "${ABOVE_CEILING_KEYWORDS}" && return 0 || return 1 ;;
    *) return 1 ;;
  esac
}

# True if item carries the above-ceiling label (board-fetch snapshot)
has_above_ceiling_label() {
  echo "$1" | jq -r '.labels[]?' 2>/dev/null | grep -qi "^${ABOVE_CEILING_LABEL}$"
}

# True if item is S-size or has no size label (treated as S per spec)
is_below_ceiling() {
  local size
  size=$(get_size_label "$1")
  case "$size" in S|"") return 0 ;; *) return 1 ;; esac
}
```

**Step 1.5 — Verify syntax**

```bash
bash -n dark-factory/scheduler.sh && echo "syntax OK"
```

Expected: `syntax OK`

**Step 1.6 — Commit Task 1**

```bash
git add dark-factory/scheduler.sh dark-factory/test_dispatch_ceiling.sh
git commit -m "feat(scheduler): add dispatch ceiling constants and helper functions (#339)

- DISPATCH_CEILING_ENABLED / ABOVE_CEILING_LABEL / ABOVE_CEILING_KEYWORDS constants
- get_size_label / is_above_ceiling / has_above_ceiling_label / is_below_ceiling helpers
- test_dispatch_ceiling.sh harness (27 assertions)"
```

---

### Task 2 — Priority 2 ceiling gate (above-ceiling → Blocked + label + comment)

**Files:** `dark-factory/scheduler.sh`

#### TDD steps

**Step 2.1 — Confirm test already covers P2 gate logic**

The `p2_gate_outcome` assertions added in Task 1's test script cover this. Run to confirm:

```bash
bash dark-factory/test_dispatch_ceiling.sh
```

Expected: `Results: 27 passed, 0 failed` (all pass, including the 5 P2 gate tests).

**Step 2.2 — Insert ceiling gate in Priority 2 loop**

In `dark-factory/scheduler.sh`, locate the Priority 2 loop (around line 832+).
Find the line `if is_issue_running "$ISSUE"; then continue; fi` inside the Ready loop.
Insert the ceiling gate immediately after that line, before `if dispatch "Fix issue #${ISSUE}"; then`:

```bash
    if [ "${DISPATCH_CEILING_ENABLED:-true}" = "true" ] && is_above_ceiling "$item"; then
      if ! has_above_ceiling_label "$item"; then
        echo "[$(date -u +%FT%TZ)] ceiling_gate issue=#${ISSUE} action=above_ceiling_blocked"
        gh issue edit "$ISSUE" --repo "${OWNER}/markethawk" \
          --add-label "$ABOVE_CEILING_LABEL" 2>/dev/null || true
        set_board_status "$ISSUE" "$STATUS_BLOCKED" || true
        gh issue comment "$ISSUE" --repo "${OWNER}/markethawk" --body \
"## Scheduler — Above Dispatch Ceiling

This ticket has been classified as **above the autonomous dispatch ceiling** \
(size: L, or size: M with a perf/architectural/migration title keyword).

Spec and plan are complete. **A human must pair on implementation.**

To proceed:
1. Remove the \`$ABOVE_CEILING_LABEL\` label.
2. Dispatch manually:
   \`\`\`bash
   docker compose --profile factory run --rm dark-factory \"Fix issue #${ISSUE}\"
   \`\`\`
   Or implement directly in a local worktree.

---
*Posted by MarketHawk Backlog Scheduler*" 2>/dev/null || true
      fi
      continue
    fi
```

The final `continue` after the `fi` block ensures the loop moves on regardless of whether
the label was just added or was already present — no dispatch happens.

**Step 2.3 — Verify syntax**

```bash
bash -n dark-factory/scheduler.sh && echo "syntax OK"
```

**Step 2.4 — Commit Task 2**

```bash
git add dark-factory/scheduler.sh
git commit -m "feat(scheduler): Priority 2 ceiling gate — block L/M+keyword tickets (#339)

Above-ceiling items: add above-ceiling label, move to Blocked, post
human-pairing comment, and skip dispatch. Guard against re-posting
on every cycle via has_above_ceiling_label check."
```

---

### Task 3 — Priority 3 guard (skip above-ceiling blocked items)

**Files:** `dark-factory/scheduler.sh`

#### TDD steps

**Step 3.1 — Confirm test already covers P3 guard logic**

```bash
bash dark-factory/test_dispatch_ceiling.sh
```

Expected: `Results: 27 passed, 0 failed` (including the 2 P3 guard tests).

**Step 3.2 — Insert guard in Priority 3 loop**

In `dark-factory/scheduler.sh`, locate the Priority 3 loop (around line 847+).
Find the line `if has_skip_label "$item"; then continue; fi` inside the Blocked loop.
Insert the above-ceiling guard on the very next line after it:

```bash
    if has_above_ceiling_label "$item"; then continue; fi
```

This single line prevents the retry loop from dispatching a "Continue" or "Fix" run on any
Blocked item that carries the `above-ceiling` label — whether placed there by the P2 gate
or by a human who manually moved the ticket.

**Step 3.3 — Verify syntax**

```bash
bash -n dark-factory/scheduler.sh && echo "syntax OK"
```

**Step 3.4 — Commit Task 3**

```bash
git add dark-factory/scheduler.sh
git commit -m "feat(scheduler): Priority 3 guard — skip above-ceiling blocked items (#339)"
```

---

### Task 4 — Suppress plan_advance_check grace-advance for M and L

**Files:** `dark-factory/scheduler.sh`

#### TDD steps

**Step 4.1 — Confirm test already covers plan_advance suppression**

```bash
bash dark-factory/test_dispatch_ceiling.sh
```

Expected: `Results: 27 passed, 0 failed` (including the 5 plan_advance tests).

**Step 4.2 — Insert suppression block in `plan_advance_check()`**

In `dark-factory/scheduler.sh`, locate `plan_advance_check()` (around line 208).
Find the line `if has_direct_to_pr_label "$item"; then` (the grace-window branch).
Insert the suppression block immediately before that line:

```bash
  # Suppress timer-based advance for at/above-ceiling items: M and L require
  # explicit human plan approval; the grace window applies only to S-size.
  if [ "${DISPATCH_CEILING_ENABLED:-true}" = "true" ] && ! is_below_ceiling "$item"; then
    return 0
  fi
```

The "new human feedback re-runs plan" path (the `has_new` block above this point) is NOT
suppressed — human feedback always triggers a re-run regardless of size.

**Step 4.3 — Verify syntax**

```bash
bash -n dark-factory/scheduler.sh && echo "syntax OK"
```

**Step 4.4 — Run full test suite**

```bash
bash dark-factory/test_dispatch_ceiling.sh
```

Expected: `Results: 27 passed, 0 failed`

**Step 4.5 — Commit Task 4**

```bash
git add dark-factory/scheduler.sh
git commit -m "feat(scheduler): suppress plan grace-advance for M/L tickets (#339)

plan_advance_check() now returns early for M and L items before
reaching the has_direct_to_pr grace-window branch. Human feedback
path is unaffected."
```

---

### Task 5 — Mirror constants in config.yaml and verify YAML validity

**Files:** `.claude/skills/refinement/config.yaml`

#### TDD steps

**Step 5.1 — Confirm the mirror gap**

```bash
grep -c "dispatch_ceiling" .claude/skills/refinement/config.yaml || echo "0 (expected)"
```

Expected: `0 (expected)` — section does not yet exist.

**Step 5.2 — Append the `dispatch_ceiling` section**

At the end of `.claude/skills/refinement/config.yaml`, append:

```yaml

dispatch_ceiling:
  enabled: true                # mirror of $DISPATCH_CEILING_ENABLED (set false in .archon/.env to disable)
  label: above-ceiling         # mirror of $ABOVE_CEILING_LABEL
  keywords: "migration|migrate|performance|perf|architectur|refactor"  # mirror of $ABOVE_CEILING_KEYWORDS
  # Doc-only: the scheduler reads env-var defaults in scheduler.sh, not this file.
  # To override without a code change, set these vars in .archon/.env.
  # See docs/superpowers/specs/2026-06-12-size-type-aware-dispatch-ceiling-design.md for rationale.
  # Revisit: 2026-09-12
```

**Step 5.3 — Verify YAML validity**

```bash
python3 -c "import yaml; yaml.safe_load(open('.claude/skills/refinement/config.yaml'))" \
  && echo "config.yaml: YAML valid"
```

Expected: `config.yaml: YAML valid`

**Step 5.4 — Commit Task 5**

```bash
git add .claude/skills/refinement/config.yaml
git commit -m "chore(config): mirror dispatch ceiling constants in config.yaml (#339)"
```

---

### Task 6 — File the revisit GitHub issue

**Files:** (no file changes — GitHub issue creation only)

#### Steps

**Step 6.1 — Check revisit issue does not already exist**

```bash
gh issue list --repo omniscient/markethawk \
  --search "Revisit dispatch ceiling" \
  --json number,title \
  --jq '.[] | "\(.number): \(.title)"'
```

Expected: no output (issue does not exist yet).

**Step 6.2 — Create the revisit issue**

```bash
gh issue create \
  --repo omniscient/markethawk \
  --title "Revisit dispatch ceiling (C9) — re-measure success-by-size/type" \
  --body "$(cat <<'EOF'
## Purpose

Quarterly revisit of the dispatch ceiling policy introduced in #339.

## What to review

1. Pull Factory Scorecard (#331) success-by-S/M/L numbers from the last quarter.
2. Compare against the initial thresholds (L = always above-ceiling; M + keyword = above-ceiling).
3. Assess keyword false-positive rate — especially for "refactor". If high, narrow the list.
4. Adjust \`ABOVE_CEILING_KEYWORDS\` in \`.archon/.env\` if data warrants, without a code change.

## References

- Spec: \`docs/superpowers/specs/2026-06-12-size-type-aware-dispatch-ceiling-design.md\`
- Architecture review candidate C9: \`docs/dark-factory-architecture-review-2026-06-11.html\`
- Factory Scorecard: #331

## Target date

**2026-09-12** (quarterly from 2026-06-12 policy introduction).
The primary trigger is #331 producing per-bucket success rates over a full quarter;
2026-09-12 is the time-boxed backstop if the data hasn't converged.

---
*Filed automatically by issue #339 plan generation*
EOF
)" \
  --label "priority: should-have" \
  --label "Dark Factory"
```

**Step 6.3 — Verify issue was created**

```bash
gh issue list --repo omniscient/markethawk \
  --search "Revisit dispatch ceiling" \
  --json number,title \
  --jq '.[] | "\(.number): \(.title)"'
```

Expected: one line like `350: Revisit dispatch ceiling (C9) — re-measure success-by-size/type`

**Step 6.4 — Final integration check**

```bash
# Syntax check
bash -n dark-factory/scheduler.sh && echo "scheduler.sh: syntax OK"

# Full test suite
bash dark-factory/test_dispatch_ceiling.sh

# YAML validity
python3 -c "import yaml; yaml.safe_load(open('.claude/skills/refinement/config.yaml'))" \
  && echo "config.yaml: valid"

# Spec checklist coverage
echo "Constants defined:"
grep -c "DISPATCH_CEILING_ENABLED\|ABOVE_CEILING_LABEL\|ABOVE_CEILING_KEYWORDS" \
  dark-factory/scheduler.sh

echo "Helpers defined:"
grep -c "^get_size_label\|^is_above_ceiling\|^has_above_ceiling_label\|^is_below_ceiling" \
  dark-factory/scheduler.sh

echo "P2 ceiling gate present:"
grep -c "ceiling_gate" dark-factory/scheduler.sh

echo "P3 guard present:"
grep -c "has_above_ceiling_label.*continue" dark-factory/scheduler.sh

echo "plan_advance_check suppression present:"
grep -c "is_below_ceiling" dark-factory/scheduler.sh

echo "config.yaml mirror present:"
grep -c "dispatch_ceiling" .claude/skills/refinement/config.yaml
```

Expected output:
```
scheduler.sh: syntax OK
Results: 27 passed, 0 failed
config.yaml: valid
Constants defined: 3
Helpers defined: 4
P2 ceiling gate present: 1
P3 guard present: 1
plan_advance_check suppression present: 1
config.yaml mirror present: 1
```

---

*Plan generated by MarketHawk Refinement Pipeline — 2026-06-12*
