# Dispatch Ceiling Week-1 Revisit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute the week-1 dispatch ceiling keyword analysis (2026-06-12 → 2026-06-21), post the analysis report on issue #394, fix the stale `size: M` → `size: S` label bug in the ceiling-revisit command, and file the next weekly revisit issue (NEXT_DATE=2026-06-28).

**Architecture:** All analysis machinery is in place — `scripts/fetch_scorecard.py` pulls PR data, `scripts/ceiling_revisit.py` applies decision rules and emits a Markdown report. The Archon command template is `.archon/commands/ceiling-revisit.md`. The only code change is a one-line label fix in that command file. All analysis phases are executed directly via the scripts.

**Tech Stack:** Python 3 (`scripts/ceiling_revisit.py`, `scripts/fetch_scorecard.py`), `gh` CLI (comments, issue creation), bash.

**Spec:** `docs/superpowers/specs/2026-06-21-dispatch-ceiling-week1-revisit-design.md`
**Depends on:** Issue #339 (ceiling policy), Issue #331 (Factory Scorecard scripts).

## Global Constraints

- `scripts/fetch_scorecard.py` and `scripts/ceiling_revisit.py` are the sole data sources — do not manually construct the report.
- `SINCE` is always `2026-06-12` (policy introduction date — never changes). `UNTIL` is `2026-06-21`. `NEXT_DATE` is `2026-06-28`.
- Phase 3 (PR) and Phase 4 (L-bucket issue) are **conditional** — expected to be no-ops in week 1. Implement the conditional checks; do not hard-code a skip.
- `.archon/commands/` files are read from the live repo (no image rebuild needed after editing).
- The `direct-to-pr` label on issue #394 governs the refinement → plan pipeline, not the ceiling analysis itself. No PR for the ceiling analysis is expected in week 1.

---

### Task 1: Fix stale `size: M` → `size: S` label in `.archon/commands/ceiling-revisit.md`

**Files:**
- Modify: `.archon/commands/ceiling-revisit.md` (line 190, Phase 5 `gh issue create`)

**Context:** The Phase 5 template hardcodes `--label "size: M"` but the correct size is `size: S` — the weekly revisit is a mechanical `< 1 hour` task. Issue #394 itself is correctly labeled `size: S`. This bug would propagate to every subsequent weekly issue unless fixed here.

- [ ] **Step 1: Write a failing smoke test**
```bash
# Verify the bug exists before fixing
grep -n '"size: M"' .archon/commands/ceiling-revisit.md | grep -q 'label' \
  && echo "BUG CONFIRMED: size: M present on line $(grep -n '"size: M"' .archon/commands/ceiling-revisit.md | head -1 | cut -d: -f1)" \
  || echo "FAIL: expected to find size: M label bug — already fixed or file changed"
```
Expected: `BUG CONFIRMED: size: M present on line 190`

- [ ] **Step 2: Apply the fix**

In `.archon/commands/ceiling-revisit.md` at line 190, change:
```
  --label "size: M" \
```
to:
```
  --label "size: S" \
```

- [ ] **Step 3: Verify the fix**
```bash
# Confirm size: M is gone from the Phase 5 issue create call
grep '"size: M"' .archon/commands/ceiling-revisit.md && echo "FAIL: size: M still present" || echo "PASS: size: M removed"
# Confirm size: S is present
grep '"size: S"' .archon/commands/ceiling-revisit.md | grep -q 'label' \
  && echo "PASS: size: S label confirmed" || echo "FAIL: size: S label not found"
```
Expected output:
```
PASS: size: M removed
PASS: size: S label confirmed
```

- [ ] **Step 4: Commit**
```bash
git add .archon/commands/ceiling-revisit.md
git commit -m "fix(ceiling-revisit): correct Phase 5 label size: M → size: S (#394)

Weekly revisit issues are size: S (< 1 hour). The size: M label in the
Phase 5 gh issue create template was stale from the original quarterly design."
```

---

### Task 2: Fetch Factory Scorecard data for the week-1 analysis window

**Files:** (no code changes — script execution only)

**Context:** `scripts/fetch_scorecard.py` pulls per-bucket PR triads from GitHub history. The output JSON at `/tmp/ceiling-revisit-scorecard.json` is the input to Task 3. Week 1 has 9 days of data so all keyword cohorts are expected to report `n < 5`.

- [ ] **Step 1: Confirm the script accepts required flags**
```bash
python3 scripts/fetch_scorecard.py --help 2>&1 | grep -E '\-\-since|\-\-until|\-\-output' \
  && echo "PASS: required flags present" || echo "FAIL: missing flags"
```
Expected: Lines showing `--since`, `--until`, `--output` flags.

- [ ] **Step 2: Run the fetch**
```bash
python3 scripts/fetch_scorecard.py \
  --since 2026-06-12 \
  --until 2026-06-21 \
  --output /tmp/ceiling-revisit-scorecard.json
```
Expected: exits 0; `/tmp/ceiling-revisit-scorecard.json` is created.

- [ ] **Step 3: Verify output**
```bash
python3 -c "import json; d=json.load(open('/tmp/ceiling-revisit-scorecard.json')); print('PASS: scorecard loaded, keys:', list(d.keys())[:5])"
```
Expected: `PASS: scorecard loaded` with key list.

---

### Task 3: Run the ceiling revisit analysis

**Files:** (no code changes — script execution only)

**Context:** `scripts/ceiling_revisit.py` applies the decision rules (n ≥ 5 guard, rate comparison against M_baseline). It writes a Markdown report to `--output` and emits `CEILING_REVISIT_JSON ...` on stderr for machine consumption. In week 1, every keyword is expected to report "insufficient data — no change" and `keywords_to_remove` will be empty.

- [ ] **Step 1: Run the analysis**
```bash
python3 scripts/ceiling_revisit.py \
  --since 2026-06-12 \
  --until 2026-06-21 \
  --scorecard /tmp/ceiling-revisit-scorecard.json \
  --output /tmp/ceiling-revisit-report.md \
  2>/tmp/ceiling-revisit-meta.txt
```
Expected: exits 0; `/tmp/ceiling-revisit-report.md` is created.

- [ ] **Step 2: Extract machine-readable recommendation**
```bash
REC_JSON=$(grep 'CEILING_REVISIT_JSON' /tmp/ceiling-revisit-meta.txt \
  | sed 's/.*CEILING_REVISIT_JSON \(.*\) -->/\1/')
KEYWORDS_TO_REMOVE=$(echo "$REC_JSON" | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print('|'.join(d['keywords_to_remove']))" 2>/dev/null || echo "")
L_NEEDS_ISSUE=$(echo "$REC_JSON" | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print(d['l_bucket_needs_issue'])" 2>/dev/null || echo "False")
echo "KEYWORDS_TO_REMOVE: '$KEYWORDS_TO_REMOVE'"
echo "L_NEEDS_ISSUE: '$L_NEEDS_ISSUE'"
```
Expected in week 1:
```
KEYWORDS_TO_REMOVE: ''
L_NEEDS_ISSUE: 'False'
```

- [ ] **Step 3: Spot-check the report**
```bash
wc -l /tmp/ceiling-revisit-report.md
grep -c 'insufficient data' /tmp/ceiling-revisit-report.md
```
Expected: non-zero line count; "insufficient data" appears for each keyword (6 keywords → count ≥ 6).

---

### Task 4: Post the analysis report as a comment on issue #394

**Files:** (no code changes — GitHub CLI operation)

**Context:** The full Markdown from `/tmp/ceiling-revisit-report.md` is posted verbatim as a GitHub issue comment. This satisfies requirement 3 of the spec and creates the week-1 traceable baseline.

- [ ] **Step 1: Verify the report file is non-empty**
```bash
[ -s /tmp/ceiling-revisit-report.md ] \
  && echo "PASS: report file has content" \
  || echo "FAIL: report file is empty or missing"
```
Expected: `PASS: report file has content`

- [ ] **Step 2: Post the comment**
```bash
gh issue comment 394 \
  --repo omniscient/markethawk \
  --body-file /tmp/ceiling-revisit-report.md
```
Expected: `https://github.com/omniscient/markethawk/issues/394#issuecomment-...` printed.

- [ ] **Step 3: Verify comment was posted**
```bash
gh issue view 394 --repo omniscient/markethawk --json comments \
  --jq '.comments[-1].body' | head -5
```
Expected: First lines of the report content appear.

---

### Task 5: Conditional — Open PR if keywords_to_remove is non-empty

**Files:** `.archon/.env` (conditionally created/modified), new PR branch (conditional)

**Context:** This phase is not expected to execute in week 1 (all keywords will have `n < 5`). The plan implements the conditional check faithfully — if `KEYWORDS_TO_REMOVE` is non-empty, follow Phase 3 of `.archon/commands/ceiling-revisit.md` exactly. Document and skip if empty.

- [ ] **Step 1: Check the condition**
```bash
if [ -z "$KEYWORDS_TO_REMOVE" ]; then
  echo "PASS (expected): KEYWORDS_TO_REMOVE is empty — Phase 3 (PR) not executed. Week 1 no-op as expected by spec."
else
  echo "UNEXPECTED: KEYWORDS_TO_REMOVE='$KEYWORDS_TO_REMOVE' — executing Phase 3"
fi
```
Expected: `PASS (expected): KEYWORDS_TO_REMOVE is empty`

- [ ] **Step 2: Execute PR phase only if non-empty**

If (unexpectedly) `KEYWORDS_TO_REMOVE` is non-empty, execute the full Phase 3 block from `.archon/commands/ceiling-revisit.md`:

```bash
# Only run this block if KEYWORDS_TO_REMOVE is non-empty
if [ -n "$KEYWORDS_TO_REMOVE" ]; then
  ENV_FILE=".archon/.env"
  if [ -f "$ENV_FILE" ] && grep -q "^ABOVE_CEILING_KEYWORDS=" "$ENV_FILE"; then
    CURRENT=$(grep '^ABOVE_CEILING_KEYWORDS=' "$ENV_FILE" | cut -d= -f2-)
  else
    CURRENT=$(grep -E '^ABOVE_CEILING_KEYWORDS="\$\{ABOVE_CEILING_KEYWORDS:-' \
      dark-factory/scheduler.sh | sed 's/.*:-\(.*\)"}/\1/')
  fi

  NEW_KWS="$CURRENT"
  for KW in $(echo "$KEYWORDS_TO_REMOVE" | tr '|' '\n'); do
    NEW_KWS=$(echo "$NEW_KWS" | sed "s/|${KW}//g;s/${KW}|//g;s/^${KW}$//g")
  done

  if [ -f "$ENV_FILE" ] && grep -q "^ABOVE_CEILING_KEYWORDS=" "$ENV_FILE"; then
    sed -i "s|^ABOVE_CEILING_KEYWORDS=.*|ABOVE_CEILING_KEYWORDS=${NEW_KWS}|" "$ENV_FILE"
  else
    echo "ABOVE_CEILING_KEYWORDS=${NEW_KWS}" >> "$ENV_FILE"
  fi

  PR_BRANCH="chore/ceiling-revisit-2026-06-21"
  git checkout -b "$PR_BRANCH"
  git add "$ENV_FILE"
  git commit -m "chore(env): update ABOVE_CEILING_KEYWORDS per weekly revisit (#394)

Removing: ${KEYWORDS_TO_REMOVE}
New value: ${NEW_KWS}

Analysis window: 2026-06-12 → 2026-06-21"

  git push origin "$PR_BRANCH"
  gh pr create \
    --repo omniscient/markethawk \
    --title "chore(env): update ABOVE_CEILING_KEYWORDS per weekly ceiling revisit" \
    --body "Recommended by weekly dispatch ceiling analysis on issue #394.

Removes: \`${KEYWORDS_TO_REMOVE}\`

See the analysis comment on #394 for full data and decision rationale." \
    --label "priority: should-have" \
    --base main
fi
```

---

### Task 6: Conditional — File L-bucket code-change issue

**Files:** (no code changes — GitHub CLI operation, conditional)

**Context:** Fires only if `L_NEEDS_ISSUE=True` (L-bucket success > 70% at n ≥ 5). Not expected in week 1. Implement the conditional check faithfully.

- [ ] **Step 1: Check the condition**
```bash
if [ "$L_NEEDS_ISSUE" != "True" ]; then
  echo "PASS (expected): L_NEEDS_ISSUE='$L_NEEDS_ISSUE' — Phase 4 (L-bucket issue) not executed. Week 1 no-op as expected by spec."
else
  echo "UNEXPECTED: L_NEEDS_ISSUE=True — executing Phase 4"
fi
```
Expected: `PASS (expected): L_NEEDS_ISSUE='False'`

- [ ] **Step 2: File issue only if triggered**

If (unexpectedly) `L_NEEDS_ISSUE=True`:

```bash
if [ "$L_NEEDS_ISSUE" = "True" ]; then
  gh issue create \
    --repo omniscient/markethawk \
    --title "Revisit L=always-above-ceiling rule in is_above_ceiling() — scheduler.sh" \
    --body "## Purpose

The weekly dispatch ceiling analysis (issue #394, window 2026-06-12 → 2026-06-21)
found the L-bucket success rate exceeds 70% at n≥5. The L=always-above-ceiling rule
in \`scheduler.sh\` may be overly conservative.

## What to review

- Inspect \`is_above_ceiling()\` in \`dark-factory/scheduler.sh\`.
- Assess whether the L-bucket ceiling should be relaxed (e.g. L+keyword pattern only).
- This is a **code change** (not an env-var change) — requires PR to \`scheduler.sh\`.

## References

- Triggering analysis: issue #394
- Policy spec: \`docs/superpowers/specs/2026-06-13-dispatch-ceiling-quarterly-revisit-design.md\`

---
*Filed automatically by weekly ceiling revisit*" \
    --label "enhancement" \
    --label "priority: should-have" \
    --label "Dark Factory"
fi
```

---

### Task 7: File the next weekly revisit issue (unconditional)

**Files:** (no code changes — GitHub CLI operation)

**Context:** Phase 5 executes unconditionally regardless of analysis outcome, keeping the weekly cadence self-perpetuating. `NEXT_DATE=2026-06-28` (`UNTIL + 7 days`). The label must be `size: S` — this matches the fix applied in Task 1.

- [ ] **Step 1: Create the next weekly revisit issue**
```bash
gh issue create \
  --repo omniscient/markethawk \
  --title "Revisit dispatch ceiling (C9) — re-measure success-by-size/type" \
  --body "## Purpose

Weekly revisit of the dispatch ceiling policy introduced in #339.

## What to review

1. Pull Factory Scorecard (#331) success-by-S/M/L numbers for the latest week.
2. Compare against current ABOVE_CEILING_KEYWORDS thresholds.
3. Assess keyword false-positive rate. If high, narrow the list.
4. Recommend \`ABOVE_CEILING_KEYWORDS\` update in \`.archon/.env\` via PR if data warrants.

## References

- Spec: \`docs/superpowers/specs/2026-06-13-dispatch-ceiling-quarterly-revisit-design.md\`
- Archon command: \`.archon/commands/ceiling-revisit.md\`
- Prior revisit: #394 (comment with results)

## Parameters for the agent

- \`ISSUE_NUM\` = <this issue's number>
- \`SINCE\` = 2026-06-12 (policy introduction date — always fixed)
- \`UNTIL\` = 2026-06-28
- \`NEXT_DATE\` = 2026-07-05

## Target date

**2026-06-28** (weekly from 2026-06-21).

---
*Filed automatically by MarketHawk weekly ceiling revisit agent*" \
  --label "enhancement" \
  --label "priority: should-have" \
  --label "size: S" \
  --label "Dark Factory" \
  --label "ready-for-agent"
```
Expected: `https://github.com/omniscient/markethawk/issues/<new-number>` printed.

- [ ] **Step 2: Verify the issue was filed**
```bash
# Confirm the new issue was created and has size: S
gh issue list --repo omniscient/markethawk \
  --label "Dark Factory" \
  --label "size: S" \
  --limit 3 \
  --json number,title,labels \
  --jq '.[] | {number, title, labels: [.labels[].name]}'
```
Expected: The new issue appears in the list with `size: S`.

- [ ] **Step 3: Commit the plan and close out**
```bash
# Only the Task 1 change has a tracked commit.
# Tasks 2-7 are execution-only (no file modifications beyond Task 1).
# Verify git status is clean:
git status --short
```
Expected: Only the `.archon/commands/ceiling-revisit.md` fix is committed (from Task 1); working tree is clean.
