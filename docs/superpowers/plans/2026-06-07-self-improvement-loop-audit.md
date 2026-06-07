# Self-Improvement Loop Audit & Optimization — Implementation Plan

**Date:** 2026-06-07
**Issue:** #213
**Epic:** #262 — Harden the Dark Factory self-improvement loop
**Spec:** `docs/superpowers/specs/2026-06-05-self-improvement-loop-audit-design.md`
**Branch:** `refine/issue-213-review-all-the-self-improvement-made-and`

## Goal

Deliver a self-contained HTML audit report comparing the Dark Factory against the Addy Osmani
self-improving agent framework (Phase 1, independent), then close the two highest-priority
structural gaps: gate-failure → memory write (Phase 2) and path-tag filtering for scoped memory
relevance (Phase 2). Phase 2 is gated on #254's memory write contract — the scheduler will not
dispatch the implement stage until #254 is Done. When implementing Phase 2, read #254's finalized
spec first and adopt its write function; do not use the raw `>>` append pattern.

## Architecture

- **Phase 1 (HTML report):** fetch-and-render; no backend code changes, no DB migrations,
  no image rebuild. Single `.html` file with inline CSS — portable, no external dependencies.
  Precedent: `docs/dark-factory-agyn-comparison.html` (issue #184).
- **Phase 2 (memory write hooks):** append new bash phases to existing
  `.archon/commands/dark-factory-conformance.md` and `dark-factory-code-review.md`. All memory
  writes MUST be routed through #254's gated write function — never a raw `>>` append.
- **Phase 2 (path-tag filtering):** add a `load_memory()` shell function to the Phase 1 LOAD
  section of implement/refine/plan commands. POSIX-compatible: `sed` for extraction, string-prefix
  `grep -q "^${PATH_TAG}"` for matching. No `grep -oP` (PCRE), no gawk three-arg `match()`.

## Tech Stack

- Dark Factory commands: bash within YAML `|` blocks in markdown files
- HTML: self-contained, inline CSS, no external dependencies
- Shell: `mawk` (not gawk), POSIX grep (not PCRE), cross-platform `date`

## File Structure

| File | Change | Phase |
|---|---|---|
| `docs/dark-factory-self-improvement-audit.html` | **NEW** — self-contained HTML audit report | 1 |
| `.archon/commands/dark-factory-conformance.md` | Add Phase 6: Memory Write on MATERIAL verdict | 2 |
| `.archon/commands/dark-factory-code-review.md` | Add Phase 7: Memory Write on BLOCKED status | 2 |
| `.archon/commands/dark-factory-implement.md` | Add `load_memory()` path-tag filtering to Phase 1 | 2 |
| `.archon/commands/dark-factory-refine.md` | Add `load_memory()` path-tag filtering to Phase 1 | 2 |
| `.archon/commands/dark-factory-plan.md` | Add `load_memory()` path-tag filtering to Phase 1 | 2 |
| `dark-factory/tests/test_conformance_memory_write.sh` | **NEW** — routing table unit test | 2 |
| `dark-factory/tests/test_load_memory.sh` | **NEW** — path-tag filtering unit test | 2 |

---

## PHASE 1 — HTML AUDIT REPORT

### Task 1: Create the self-improvement loop audit HTML report

**Files:** `docs/dark-factory-self-improvement-audit.html`

This task has no traditional TDD cycle (it is a document, not code). Validation steps confirm
structure and self-containment instead of test pass/fail.

---

**Step 1.1 — Fetch the article**

Use the `WebFetch` tool to retrieve `https://addyosmani.com/blog/self-improving-agents/`.

Parse the article for:
- The article's named self-improving agent patterns (feedback loops, episodic memory, reflection,
  tool improvement, performance metrics, etc.)
- Any evaluation checklist or framework structure
- Key definitions or criteria for each pattern

If the URL is unreachable, note the failure in the report header, skip the comparison table, and
write a fallback section that lists the patterns known from the spec instead. Do not abort the task.

---

**Step 1.2 — Inventory the current Dark Factory**

Read the following files to map current mechanisms to each article pattern:

```bash
cat .archon/commands/dark-factory-implement.md
cat .archon/commands/dark-factory-conformance.md
cat .archon/commands/dark-factory-code-review.md
cat .archon/commands/dark-factory-refine.md
cat .archon/commands/dark-factory-plan.md
cat .archon/memory/codebase-patterns.md
cat .archon/memory/architecture.md
cat .archon/memory/dark-factory-ops.md
cat .claude/skills/refinement/config.yaml
```

For each article pattern, identify the corresponding Dark Factory mechanism or note its absence.

---

**Step 1.3 — Build the comparison table**

Use these status values:
- ✅ Implemented — mechanism exists and is functional
- ⚠️ Partial — mechanism exists but incomplete
- ❌ Missing — no mechanism
- 🔄 In Progress — being addressed (include issue ref)

Rows to include at minimum (expand based on the full article content):

| Article Pattern | Dark Factory Mechanism | Status |
|---|---|---|
| Feedback loops (errors → lessons) | Conformance/code-review gate-failure → `[AVOID]` (this issue, Phase 2) | 🔄 #213 |
| Episodic memory | `.archon/memory/*.md` `[PATTERN]`/`[AVOID]` entries with 6-month TTL | ✅ |
| Reflection / self-assessment | Conformance reviewer subagent: compares implementation vs spec | ✅ |
| Tool / process improvement | Pipeline commands updated based on lessons (e.g. awk fix via #149) | ✅ |
| Performance metrics | Pipeline metrics report (#212) | 🔄 #212 |
| Scoped memory loading | `path:` tag filtering in load step (this issue, Phase 2) | 🔄 #213 |
| Memory write correctness gate | #254's gated write function (dedup, caps, invalidation) | 🔄 #254 |
| Memory effectiveness tracking | Detecting `[AVOID]` recurrence — unspecified | ❌ |

Add additional rows for any other patterns the article names that are not listed here.

---

**Step 1.4 — Identify the gap analysis**

For each ❌ Missing or ⚠️ Partial row, write a one-paragraph explanation ordered by impact:
1. What the gap is
2. What happens without it (concrete failure mode)
3. Current disposition (whether this issue or a future issue addresses it)

---

**Step 1.5 — Write `docs/dark-factory-self-improvement-audit.html`**

Write the file as a single self-contained HTML document with inline CSS. No external scripts,
no external fonts, no CDN dependencies. All styles must be in a `<style>` block in `<head>`.

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Dark Factory — Self-Improvement Loop Audit</title>
  <style>
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      max-width: 1100px; margin: 40px auto; padding: 0 24px;
      color: #1a1a2e; line-height: 1.6;
    }
    h1 { font-size: 1.8rem; border-bottom: 3px solid #4361ee; padding-bottom: 10px; }
    h2 { font-size: 1.3rem; color: #3a0ca3; border-bottom: 1px solid #e0e0e0;
         padding-bottom: 6px; margin-top: 2rem; }
    h3 { font-size: 1.1rem; color: #480ca8; }
    table { width: 100%; border-collapse: collapse; margin: 1rem 0; font-size: 0.9rem; }
    th { background: #4361ee; color: white; padding: 10px 14px; text-align: left; }
    td { padding: 9px 14px; border-bottom: 1px solid #e0e0e0; vertical-align: top; }
    tr:nth-child(even) { background: #f8f9ff; }
    .badge { display: inline-block; padding: 2px 8px; border-radius: 12px;
             font-size: 0.82rem; font-weight: 600; white-space: nowrap; }
    .badge-ok       { background: #d1fae5; color: #065f46; }
    .badge-partial  { background: #fef3c7; color: #92400e; }
    .badge-missing  { background: #fee2e2; color: #991b1b; }
    .badge-progress { background: #dbeafe; color: #1e40af; }
    .gap-card { border: 1px solid #e0e0e0; border-radius: 8px; padding: 16px; margin: 12px 0; }
    .gap-high   { border-left: 4px solid #ef4444; }
    .gap-medium { border-left: 4px solid #f59e0b; }
    .gap-low    { border-left: 4px solid #6b7280; }
    .meta { color: #6b7280; font-size: 0.85rem; margin-bottom: 2rem; }
    code { background: #f1f5f9; padding: 2px 6px; border-radius: 4px; font-size: 0.85em; }
    .note { background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 6px;
            padding: 12px 16px; margin: 12px 0; font-size: 0.9rem; }
    a { color: #4361ee; }
  </style>
</head>
<body>

<h1>Dark Factory — Self-Improvement Loop Audit</h1>
<p class="meta">
  Issue: <a href="https://github.com/omniscient/markethawk/issues/213">#213</a> &nbsp;|&nbsp;
  Epic: <a href="https://github.com/omniscient/markethawk/issues/262">#262 — Harden the self-improvement loop</a>
  &nbsp;|&nbsp; Date: 2026-06-07 &nbsp;|&nbsp;
  Reference: <a href="https://addyosmani.com/blog/self-improving-agents/">Addy Osmani — Self-Improving Agents</a>
</p>

<!-- If article was unreachable, insert a .note block here explaining the failure -->

<h2>1. Framework Comparison</h2>
<p>Each row maps a self-improving agent pattern from the article to the current Dark Factory
mechanism. Status: ✅ Implemented · ⚠️ Partial · ❌ Missing · 🔄 In Progress.</p>

<table>
  <thead>
    <tr>
      <th style="width:22%">Article Pattern</th>
      <th style="width:40%">Current Dark Factory Mechanism</th>
      <th style="width:12%">Status</th>
      <th>Notes / Issue Ref</th>
    </tr>
  </thead>
  <tbody>
    <!-- One <tr> per article pattern.
         Status cell: <span class="badge badge-ok">✅ Implemented</span>
                      <span class="badge badge-partial">⚠️ Partial</span>
                      <span class="badge badge-missing">❌ Missing</span>
                      <span class="badge badge-progress">🔄 In Progress</span>
         Fill in all rows based on Step 1.3 above. -->
  </tbody>
</table>

<h2>2. Gap Analysis</h2>
<p>Gaps ordered by impact. Only ❌ Missing and ⚠️ Partial rows generate cards here.</p>

<!-- One .gap-card per gap:
  <div class="gap-card gap-high">
    <h3>[Pattern Name]</h3>
    <p><strong>Gap:</strong> ...</p>
    <p><strong>Failure mode without it:</strong> ...</p>
    <p><strong>Disposition:</strong> Addressed by this issue / deferred to #NNN / no issue yet.</p>
  </div>
-->

<h2>3. What This Issue Addresses</h2>
<div class="note">
  <strong>Phase 1 (ships with this PR):</strong>
  <ul>
    <li>This HTML audit report</li>
    <!-- list concrete deliverables -->
  </ul>
  <strong>Phase 2 (ships after #254 is Done):</strong>
  <ul>
    <li>Conformance gate → <code>[AVOID]</code> memory write on MATERIAL verdict</li>
    <li>Code-review gate → <code>[AVOID]</code> memory write on BLOCKED status</li>
    <li><code>path:</code> tag filtering in implement/refine/plan load phases</li>
  </ul>
</div>

<h2>4. Deferred / Non-Goals</h2>
<div class="note">
  <ul>
    <li>Memory effectiveness tracking (detecting <code>[AVOID]</code> recurrence) — no issue yet</li>
    <li>Pipeline metrics dashboards — issue #212 covers this</li>
    <li>Retroactively path-tagging existing memory entries — deferred</li>
    <li>Auto-fixing conformance violations via additional reconcile loops — deferred</li>
  </ul>
</div>

<h2>5. In-Flight Improvements</h2>
<table>
  <thead><tr><th>Issue</th><th>Title</th><th>Status</th></tr></thead>
  <tbody>
    <tr><td><a href="https://github.com/omniscient/markethawk/issues/213">#213</a></td>
        <td>Self-improvement loop audit &amp; optimization</td>
        <td><span class="badge badge-progress">🔄 This issue</span></td></tr>
    <tr><td><a href="https://github.com/omniscient/markethawk/issues/254">#254</a></td>
        <td>Memory write contract (correctness gate, caps, invalidation)</td>
        <td><span class="badge badge-progress">🔄 Pending</span></td></tr>
    <tr><td><a href="https://github.com/omniscient/markethawk/issues/212">#212</a></td>
        <td>Pipeline metrics report</td>
        <td><span class="badge badge-progress">🔄 In Progress</span></td></tr>
    <!-- Add any other relevant in-flight issues from Step 1.2 inventory -->
  </tbody>
</table>

</body>
</html>
```

Fill in all `<!-- ... -->` comment placeholders with actual content from Steps 1.3 and 1.4.
Do not leave any placeholder comments in the final file.

---

**Step 1.6 — Validate self-containment**

```bash
# File must exist and be non-empty
ls -lh docs/dark-factory-self-improvement-audit.html

# No external CSS/JS/font references (GitHub and article links are OK)
grep -n 'src=\|@import\|url(' docs/dark-factory-self-improvement-audit.html \
  | grep -v 'href=' || true
# Expected: zero output (all styles are inline; no external src= or @import)

# No placeholder comments in the final file
grep -c '<!-- .*\.\.\.' docs/dark-factory-self-improvement-audit.html || true
# Expected: 0
```

---

**Step 1.7 — Commit**

```bash
git add docs/dark-factory-self-improvement-audit.html
git commit -m "docs: add self-improvement loop audit HTML report (#213)"
```

Expected:
```
[refine/issue-213-...] docs: add self-improvement loop audit HTML report (#213)
 1 file changed, N insertions(+)
 create mode 100644 docs/dark-factory-self-improvement-audit.html
```

---

## PHASE 2 — GATE → MEMORY WRITE HOOKS

> ⚠️ **Phase 2 is blocked on #254.** The scheduler `Depends on: #254` gate prevents the
> implement stage from dispatching until #254 is Done. When implementing these tasks:
> 1. Read #254's finalized spec first.
> 2. Replace every `TODO: Once #254 lands` comment below with #254's actual write function call.
> 3. Do NOT implement the raw `>>` append — that bypasses #254's correctness gate, dedup, and caps.

---

### Task 2: Add Memory Write Phase to Conformance Command

**Files:** `.archon/commands/dark-factory-conformance.md`,
`dark-factory/tests/test_conformance_memory_write.sh`

**Trigger condition:** Only when `VERDICT = MATERIAL`. Advisory findings
(`CONFORMS` or `MINOR`) do not write memory — only proven blocking mistakes do.

**Memory lesson: AVOID patterns to check before editing:**
- Do NOT use `grep -oP` (PCRE) — factory container ships POSIX grep. Use `sed 's/.*path:\([^ >]*\).*/\1/'`.
- Do NOT use three-argument `match(arr)` in awk — this is a gawk extension. Use two-argument
  `match($0, /regex/)` and extract with `substr($0, RSTART+N, LEN)`.
- Do NOT use multiline string assignments with literal newlines inside a YAML `|` block —
  use `printf "line1\n\nline2"` or `printf "%s\n%s" ...` instead.
- Do NOT use raw `>>` to append to memory files — this re-introduces the unverified write
  problem that #254 exists to fix. Leave the `TODO` comment and implement via #254's function.

---

**Step 2.1 — Write and run the routing-table test first (failing → passing)**

Create `dark-factory/tests/test_conformance_memory_write.sh` and run it — it will fail
initially because the `route_memory_file` function does not exist in the conformance command yet.
The test doubles as a reference implementation you will copy into the command.

```bash
#!/usr/bin/env bash
# Unit test for route_memory_file() — the path routing table for gate-stage memory writes.
# This test is self-contained: it defines and tests the function in isolation.
set -euo pipefail

PASS=0; FAIL=0

assert() {
  local desc="$1" result="$2"
  if [ "$result" = "0" ]; then
    echo "PASS: $desc"; PASS=$((PASS+1))
  else
    echo "FAIL: $desc"; FAIL=$((FAIL+1))
  fi
}

route_memory_file() {
  local FILE="$1"
  case "$FILE" in
    backend/app/*)           echo ".archon/memory/backend-patterns.md" ;;
    frontend/src/*)          echo ".archon/memory/frontend-patterns.md" ;;
    .archon/*|dark-factory/*) echo ".archon/memory/dark-factory-ops.md" ;;
    ARCHITECTURE.md)         echo ".archon/memory/architecture.md" ;;
    *)                       echo ".archon/memory/codebase-patterns.md" ;;
  esac
}

assert "backend/ routes to backend-patterns.md" \
  "$([ "$(route_memory_file 'backend/app/routers/scanner.py')" = '.archon/memory/backend-patterns.md' ] && echo 0 || echo 1)"

assert "frontend/ routes to frontend-patterns.md" \
  "$([ "$(route_memory_file 'frontend/src/components/Foo.tsx')" = '.archon/memory/frontend-patterns.md' ] && echo 0 || echo 1)"

assert ".archon/ routes to dark-factory-ops.md" \
  "$([ "$(route_memory_file '.archon/commands/dark-factory-plan.md')" = '.archon/memory/dark-factory-ops.md' ] && echo 0 || echo 1)"

assert "dark-factory/ routes to dark-factory-ops.md" \
  "$([ "$(route_memory_file 'dark-factory/scripts/foo.sh')" = '.archon/memory/dark-factory-ops.md' ] && echo 0 || echo 1)"

assert "ARCHITECTURE.md routes to architecture.md" \
  "$([ "$(route_memory_file 'ARCHITECTURE.md')" = '.archon/memory/architecture.md' ] && echo 0 || echo 1)"

assert "catch-all routes to codebase-patterns.md" \
  "$([ "$(route_memory_file 'docs/some/file.md')" = '.archon/memory/codebase-patterns.md' ] && echo 0 || echo 1)"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
```

Run to confirm it passes (the test is self-contained — it does not read the command file):
```bash
chmod +x dark-factory/tests/test_conformance_memory_write.sh
bash dark-factory/tests/test_conformance_memory_write.sh
```

Expected output:
```
PASS: backend/ routes to backend-patterns.md
PASS: frontend/ routes to frontend-patterns.md
PASS: .archon/ routes to dark-factory-ops.md
PASS: dark-factory/ routes to dark-factory-ops.md
PASS: ARCHITECTURE.md routes to architecture.md
PASS: catch-all routes to codebase-patterns.md

Results: 6 passed, 0 failed
```

---

**Step 2.2 — Read `/opt/refinement-skills/conformance-reviewer-prompt.md` and `.archon/commands/dark-factory-conformance.md`**

Read both files before editing. The conformance reviewer prompt defines the output format —
identify the section structure used for MATERIAL deviations (e.g., what headers, labels, or
list formats the reviewer uses for blocking findings). You will use this format in the
extraction logic below.

In the command file, confirm the structure:
- Phase 3.5 RECONCILE LOOP: fixes MATERIAL violations and loops until PASS or MAX_CYCLES
- Phase 4 PASS: writes attestation to `$ARTIFACTS_DIR/conformance.md`, then `exit 0`
- Phase 5 BLOCKED: fires only when `CONFORMANCE_CYCLE > MAX_CYCLES` — ends in `exit 1`

The memory write must be inserted inside **Phase 4 PASS**, immediately after the attestation
write and before the `exit 0`. It is conditional on `CONFORMANCE_CYCLE > 0` (at least one
MATERIAL cycle occurred and was resolved). This is the only execution path where MATERIAL
violations exist AND the run ends successfully.

---

**Step 2.3 — Insert memory write block inside Phase 4 PASS**

Read `.archon/commands/dark-factory-conformance.md`. Find the Phase 4 PASS section. It ends with:

```bash
Exit `0`. The `push-and-pr` and `report` nodes will proceed normally.
```

Insert the following markdown block IMMEDIATELY BEFORE that final "Exit `0`" line:

````markdown
If `CONFORMANCE_CYCLE > 0` (MATERIAL violations were found and resolved in this run), extract
violation data from `$CONFORMANCE_DIALOGUE` and write memory entries via #254's write function:

```bash
# Memory write: only when MATERIAL violations were found and resolved (CONFORMANCE_CYCLE > 0)
if [ "${CONFORMANCE_CYCLE:-0}" -gt 0 ]; then

  # Guard: #254's write function must be available. Skip silently until it ships.
  if ! command -v write_memory_entry > /dev/null 2>&1; then
    echo "memory-write: write_memory_entry not yet available — Phase 4 memory write skipped until #254 lands"
  else

    route_memory_file() {
      local FILE="$1"
      case "$FILE" in
        backend/app/*)            echo ".archon/memory/backend-patterns.md" ;;
        frontend/src/*)           echo ".archon/memory/frontend-patterns.md" ;;
        .archon/*|dark-factory/*) echo ".archon/memory/dark-factory-ops.md" ;;
        ARCHITECTURE.md)          echo ".archon/memory/architecture.md" ;;
        *)                        echo ".archon/memory/codebase-patterns.md" ;;
      esac
    }

    # Extract (VIOLATION_FILE, VIOLATION_TEXT) pairs from $CONFORMANCE_DIALOGUE.
    # $CONFORMANCE_DIALOGUE is the free-form output of the conformance reviewer subagent.
    # Parse it using the reviewer's output format (read from conformance-reviewer-prompt.md):
    # — Identify the section containing MATERIAL deviation descriptions
    # — For each MATERIAL finding, extract the file path and a one-sentence lesson
    # — Build BLOCKING_VIOLATIONS as newline-separated "FILE|TEXT" pairs
    # The implement agent must read /opt/refinement-skills/conformance-reviewer-prompt.md
    # to determine the reviewer's exact output format and write the extraction here.
    # If #254 provides an extraction helper, use it; otherwise implement inline parsing.
    BLOCKING_VIOLATIONS="${BLOCKING_VIOLATIONS:-}"  # set by extraction logic above

    MEMORY_WRITTEN=0

    while IFS='|' read -r VIOLATION_FILE VIOLATION_TEXT; do
      [ -z "$VIOLATION_FILE" ] || [ -z "$VIOLATION_TEXT" ] && continue

      TARGET=$(route_memory_file "$VIOLATION_FILE")
      PATH_PREFIX=$(dirname "$VIOLATION_FILE")/

      # write_memory_entry is #254's gated function: enforces correctness gate, dedup, caps.
      # The >> append pattern is NOT used — routing all writes through this boundary.
      write_memory_entry \
        --target  "$TARGET" \
        --path    "$PATH_PREFIX" \
        --text    "$VIOLATION_TEXT" \
        --source  conformance \
        --issue   "$ISSUE_NUM"
      MEMORY_WRITTEN=$((MEMORY_WRITTEN + 1))
      echo "memory-write: wrote [AVOID] to $TARGET (path:$PATH_PREFIX)"

    done << EOF
$BLOCKING_VIOLATIONS
EOF

    if [ "$MEMORY_WRITTEN" -gt 0 ]; then
      git add .archon/memory/
      git commit -m "memory: conformance lesson from #${ISSUE_NUM}"
      echo "memory-write: committed $MEMORY_WRITTEN new [AVOID] entr(ies)"
    else
      echo "memory-write: no novel entries — skipping commit"
    fi
  fi
fi
```
````

---

**Step 2.4 — Validate no POSIX-incompatible patterns and no raw appends**

```bash
# No grep -oP (PCRE) in the conformance command
grep -n 'grep -oP' .archon/commands/dark-factory-conformance.md
# Expected: no output

# No raw >> appends to memory files (all writes go through write_memory_entry)
grep -n '>> .archon/memory' .archon/commands/dark-factory-conformance.md
# Expected: no output

# Confirm write_memory_entry call is present in the Phase 4 PASS section
grep -n 'write_memory_entry' .archon/commands/dark-factory-conformance.md
# Expected: one or more matches in the Phase 4 memory-write block
```

---

**Step 2.5 — Commit**

```bash
git add .archon/commands/dark-factory-conformance.md \
        dark-factory/tests/test_conformance_memory_write.sh
git commit -m "feat: add memory write phase to conformance gate (#213)"
```

Expected:
```
[refine/issue-213-...] feat: add memory write phase to conformance gate (#213)
 2 files changed, N insertions(+)
```

---

### Task 3: Add Memory Write Phase to Code-Review Command

**Files:** `.archon/commands/dark-factory-code-review.md`

**Trigger condition:** Only when `STATUS = BLOCKED` (blocking findings from Phase 6 of the
code-review command). `STATUS = PASS` with advisory count does not write memory.

The same AVOID patterns apply as Task 2 — no `grep -oP`, no three-arg awk `match()`, no raw `>>`.

---

**Step 3.1 — Read `.archon/commands/dark-factory-code-review.md`**

Read the full file before editing. Confirm Phase 6 is the last section with two branches:
- `PASS` branch: writes attestation to `$ARTIFACTS_DIR/review.md`, then `exit 0`
- `BLOCKED` branch: posts comment, moves board, writes attestation, then `exit 1`

The memory write must be inserted inside the **BLOCKED branch of Phase 6**, immediately after
the `$ARTIFACTS_DIR/review.md` write (step 4) and before the `exit 1` (step 5). This is the
only execution path where `STATUS = BLOCKED` and the write is unconditionally reachable.

---

**Step 3.2 — Insert Phase 7 memory write inside the Phase 6 BLOCKED branch**

Read `.archon/commands/dark-factory-code-review.md` in full. In the Phase 6 BLOCKED section,
find the line:

```
5. Exit non-zero (`exit 1`) — this halts `status-in-review`...
```

Insert the following markdown block IMMEDIATELY BEFORE step 5:

````markdown
5. Write blocking findings back to memory via #254's write function:

```bash
# Memory write: only when STATUS=BLOCKED (blocking findings confirmed)
# Guard: #254's write function must be available. Skip silently until it ships.
if ! command -v write_memory_entry > /dev/null 2>&1; then
  echo "memory-write: write_memory_entry not yet available — Phase 6 memory write skipped until #254 lands"
else

  route_memory_file() {
    local FILE="$1"
    case "$FILE" in
      backend/app/*)            echo ".archon/memory/backend-patterns.md" ;;
      frontend/src/*)           echo ".archon/memory/frontend-patterns.md" ;;
      .archon/*|dark-factory/*) echo ".archon/memory/dark-factory-ops.md" ;;
      ARCHITECTURE.md)          echo ".archon/memory/architecture.md" ;;
      *)                        echo ".archon/memory/codebase-patterns.md" ;;
    esac
  }

  MEMORY_WRITTEN=0

  # Parse blocker file paths and descriptions from the structured review result JSON.
  # review_result.json is produced by code_review_payload.py with .blockers[].path
  # and .blockers[].description fields.
  BLOCKER_FILES=$(jq -r '.blockers[].path // empty' "$ARTIFACTS_DIR/review_result.json" 2>/dev/null || true)

  for BLOCKER_FILE in $BLOCKER_FILES; do
    # head -1 guards against multi-line description output
    FINDING_TEXT=$(jq -r --arg p "$BLOCKER_FILE" \
      '.blockers[] | select(.path == $p) | .description' \
      "$ARTIFACTS_DIR/review_result.json" 2>/dev/null | head -1)

    [ -z "$FINDING_TEXT" ] && continue

    TARGET=$(route_memory_file "$BLOCKER_FILE")
    PATH_PREFIX=$(dirname "$BLOCKER_FILE")/

    # write_memory_entry is #254's gated function: enforces correctness gate, dedup, caps.
    # The >> append pattern is NOT used — routing all writes through this boundary.
    write_memory_entry \
      --target  "$TARGET" \
      --path    "$PATH_PREFIX" \
      --text    "$FINDING_TEXT" \
      --source  code-review \
      --issue   "$ISSUE_NUM"
    MEMORY_WRITTEN=$((MEMORY_WRITTEN + 1))
    echo "memory-write: wrote [AVOID] to $TARGET"
  done

  if [ "$MEMORY_WRITTEN" -gt 0 ]; then
    git add .archon/memory/
    git commit -m "memory: code-review lesson from #${ISSUE_NUM}"
  else
    echo "memory-write: no novel entries — skipping commit"
  fi
fi
```

Renumber the existing step 5 (`exit 1`) to step 6.
````

---

**Step 3.3 — Validate no raw appends and no POSIX-incompatible patterns**

```bash
grep -n 'grep -oP' .archon/commands/dark-factory-code-review.md
# Expected: no output

# No raw >> appends to memory files
grep -n '>> .archon/memory' .archon/commands/dark-factory-code-review.md
# Expected: no output

# Confirm write_memory_entry call is present
grep -n 'write_memory_entry' .archon/commands/dark-factory-code-review.md
# Expected: one or more matches in the Phase 6 BLOCKED branch
```

---

**Step 3.4 — Commit**

```bash
git add .archon/commands/dark-factory-code-review.md
git commit -m "feat: add memory write phase to code-review gate (#213)"
```

---

### Task 4: Add Path-Tag Filtering to Implement, Refine, and Plan Commands

**Files:** `.archon/commands/dark-factory-implement.md`,
`.archon/commands/dark-factory-refine.md`,
`.archon/commands/dark-factory-plan.md`,
`dark-factory/tests/test_load_memory.sh`

**Context:** New memory entries written by the gate stages will carry a `path:` glob tag. The
Phase 1 LOAD step in each command should filter path-tagged entries to only those relevant to the
current issue's affected file set. Entries without a `path:` tag are always included (backward
compatible — all existing entries have no `path:` tag).

**AVOID patterns:**
- Do NOT use `grep -oP` for path-tag extraction — use `sed 's/.*path:\([^ >]*\).*/\1/'`.
- Do NOT use `[[ $FILE == $PATTERN* ]]` for prefix matching — requires Bash 4+; factory uses
  POSIX sh compatibility. Use `echo "$AFFECTED" | grep -q "^${PATH_TAG}"` instead.

---

**Step 4.1 — Write and run the `load_memory` test first**

Create `dark-factory/tests/test_load_memory.sh`:

```bash
#!/usr/bin/env bash
# Unit test for load_memory() — path-tag filtering in Phase 1 LOAD.
set -euo pipefail

PASS=0; FAIL=0

assert() {
  local desc="$1" result="$2"
  if [ "$result" = "0" ]; then
    echo "PASS: $desc"; PASS=$((PASS+1))
  else
    echo "FAIL: $desc"; FAIL=$((FAIL+1))
  fi
}

AFFECTED="backend/app/routers/scanner.py"

load_memory() {
  local MEMFILE="$1"
  [ -f "$MEMFILE" ] || return
  while IFS= read -r line; do
    if echo "$line" | grep -q 'path:'; then
      # sed extraction — POSIX compatible (not grep -oP)
      PATH_TAG=$(echo "$line" | sed 's/.*path:\([^ >]*\).*/\1/')
      # String-prefix match — grep -q "^PREFIX" against affected file list
      if [ -z "$AFFECTED" ] || echo "$AFFECTED" | grep -q "^${PATH_TAG}"; then
        echo "$line"
      fi
    else
      echo "$line"
    fi
  done < "$MEMFILE"
}

TMPFILE=$(mktemp /tmp/test_load_memory_XXXXXX.md)
cat > "$TMPFILE" << 'MEMEOF'
- [PATTERN] Always included — no path tag
- [AVOID] Backend only <!-- issue:#1 date:2026-01-01 expires:2026-12-01 source:conformance path:backend/app/ -->
- [AVOID] Frontend only <!-- issue:#2 date:2026-01-01 expires:2026-12-01 source:conformance path:frontend/src/ -->
MEMEOF

OUTPUT=$(load_memory "$TMPFILE")
rm -f "$TMPFILE"

assert "entry without path: tag is always included" \
  "$(echo "$OUTPUT" | grep -q 'Always included' && echo 0 || echo 1)"

assert "backend-path entry included when affected file matches" \
  "$(echo "$OUTPUT" | grep -q 'Backend only' && echo 0 || echo 1)"

assert "frontend-path entry excluded when no affected file matches" \
  "$(echo "$OUTPUT" | grep -q 'Frontend only' && echo 1 || echo 0)"

# Test: empty AFFECTED → include all entries (new branch fallback)
AFFECTED=""
TMPFILE2=$(mktemp /tmp/test_load_memory_XXXXXX.md)
printf -- "- [AVOID] Path-tagged entry <!-- path:frontend/src/ -->\n" > "$TMPFILE2"
OUTPUT2=$(load_memory "$TMPFILE2")
rm -f "$TMPFILE2"

assert "empty AFFECTED includes all path-tagged entries (new branch)" \
  "$(echo "$OUTPUT2" | grep -q 'Path-tagged entry' && echo 0 || echo 1)"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
```

Run to confirm it passes:
```bash
chmod +x dark-factory/tests/test_load_memory.sh
bash dark-factory/tests/test_load_memory.sh
```

Expected output:
```
PASS: entry without path: tag is always included
PASS: backend-path entry included when affected file matches
PASS: frontend-path entry excluded when no affected file matches
PASS: empty AFFECTED includes all path-tagged entries (new branch)

Results: 4 passed, 0 failed
```

---

**Step 4.2 — Read each command file before editing**

```bash
# Read all three command files to locate their Phase 1 memory-load instructions
grep -n 'archon/memory' .archon/commands/dark-factory-implement.md
grep -n 'archon/memory' .archon/commands/dark-factory-refine.md
grep -n 'archon/memory' .archon/commands/dark-factory-plan.md
```

Note the line numbers where each file reads memory. The `load_memory` function block and
`AFFECTED` computation will be inserted immediately before the first memory-read step in each
command's Phase 1 section.

---

**Step 4.3 — Insert `load_memory` into `dark-factory-implement.md`**

Read `.archon/commands/dark-factory-implement.md` in full. Find Phase 1 step 5
("Read `.archon/memory/codebase-patterns.md`"). Insert the following markdown block
immediately BEFORE step 5 (renumber steps 5–9 to 6–10 after insertion):

````markdown
5. Compute the affected file set and define `load_memory` for path-tag filtering:

```bash
AFFECTED=$(git diff --name-only origin/main...HEAD 2>/dev/null || echo "")

# load_memory: reads a memory file, including entries without a path: tag unconditionally,
# and path-tagged entries only when their prefix matches an affected file.
# Uses sed (POSIX) for tag extraction and grep -q "^PREFIX" for prefix matching.
load_memory() {
  local MEMFILE=".archon/memory/$1"
  [ -f "$MEMFILE" ] || return
  while IFS= read -r line; do
    if echo "$line" | grep -q 'path:'; then
      PATH_TAG=$(echo "$line" | sed 's/.*path:\([^ >]*\).*/\1/')
      if [ -z "$AFFECTED" ] || echo "$AFFECTED" | grep -q "^${PATH_TAG}"; then
        echo "$line"
      fi
    else
      echo "$line"
    fi
  done < "$MEMFILE"
}
```
````

Then update steps 6–10 (previously 5–9) to use `load_memory` instead of `cat`/direct reads:
- Replace "Read `.archon/memory/codebase-patterns.md`" →
  "Run `load_memory codebase-patterns.md` and include its filtered output in context."
- Replace "Read `.archon/memory/architecture.md`" →
  "Run `load_memory architecture.md` and include its filtered output in context."
- Replace "read `.archon/memory/backend-patterns.md`" →
  "run `load_memory backend-patterns.md` and include its filtered output in context."
- Replace "read `.archon/memory/frontend-patterns.md`" →
  "run `load_memory frontend-patterns.md` and include its filtered output in context."
- Replace "read `.archon/memory/dark-factory-ops.md`" →
  "run `load_memory dark-factory-ops.md` and include its filtered output in context."

Use exact phrasing from the file — read the file first to match the wording precisely.

---

**Step 4.4 — Insert `load_memory` into `dark-factory-refine.md`**

Read `.archon/commands/dark-factory-refine.md` in full. Find Phase 1 step 7
("Read `.archon/memory/codebase-patterns.md`"). Insert the same `AFFECTED` + `load_memory`
block immediately before step 7 (renumber steps 7–9 to 8–10). Update the memory-read steps
in the same way as Step 4.3.

---

**Step 4.5 — Insert `load_memory` into `dark-factory-plan.md`**

Read `.archon/commands/dark-factory-plan.md` in full. Find Phase 1 step 6
("Read `.archon/memory/codebase-patterns.md`"). Insert the same block immediately before
step 6 (renumber steps 6–8 to 7–9). Update the memory-read steps in the same way.

---

**Step 4.6 — Validate no POSIX-incompatible patterns in the new blocks**

```bash
for f in .archon/commands/dark-factory-implement.md \
          .archon/commands/dark-factory-refine.md \
          .archon/commands/dark-factory-plan.md; do
  echo "=== $f ==="
  grep -n 'grep -oP' "$f" && echo "  ERROR: PCRE grep found" || echo "  OK: no grep -oP"
  # Bash 4+ glob check — [[ ]] with * glob for path comparison
  grep -n '\[\[ \$.*==.*\*' "$f" && echo "  ERROR: Bash 4+ glob found" || echo "  OK: no Bash glob"
done
```

Expected: all "OK" lines, no "ERROR" lines.

---

**Step 4.7 — Commit**

```bash
git add .archon/commands/dark-factory-implement.md \
        .archon/commands/dark-factory-refine.md \
        .archon/commands/dark-factory-plan.md \
        dark-factory/tests/test_load_memory.sh
git commit -m "feat: add path-tag memory filtering to implement/refine/plan commands (#213)"
```

Expected:
```
[refine/issue-213-...] feat: add path-tag memory filtering to implement/refine/plan commands (#213)
 4 files changed, N insertions(+)
```

---

## Task Summary

| # | Phase | Files Changed | Deliverable |
|---|---|---|---|
| 1 | 1 | `docs/dark-factory-self-improvement-audit.html` | HTML audit report comparing Dark Factory vs Addy Osmani framework |
| 2 | 2* | `.archon/commands/dark-factory-conformance.md`, `dark-factory/tests/test_conformance_memory_write.sh` | Memory write on MATERIAL verdict (routing table + awk-compatible cleanup) |
| 3 | 2* | `.archon/commands/dark-factory-code-review.md` | Memory write on BLOCKED status |
| 4 | 2* | `.archon/commands/dark-factory-implement.md`, `dark-factory-refine.md`, `dark-factory-plan.md`, `dark-factory/tests/test_load_memory.sh` | Path-tag filtering in Phase 1 LOAD of all three commands |

*Phase 2 tasks are blocked on #254. When implementing, read #254's finalized spec and adopt its
write function — the `TODO` markers in Tasks 2 and 3 must be replaced with #254's actual API call.
Do not merge Phase 2 changes before #254's write contract is finalized.
