# Implementation Plan: Agent Role and Project Scoping for Dark Factory Memory Calls

**Issue:** #651
**Date:** 2026-06-27
**Branch:** refine/issue-651-add-agent-role-and-project-scoping-to-da
**Spec:** `docs/superpowers/specs/2026-06-27-agent-role-project-scoping-design.md`

---

## Goal

Prevent cross-project and cross-role contamination in the Dark Factory flat-file memory system by:
1. Adding `project:markethawk` and `agentId:<role>` to every memory entry written after this change.
2. Filtering out entries with a mismatched `project:` tag in `load_memory()`.
3. Defining the 13 stable role-ID constants in a new `agent_roles.sh` include, sourced by `gate_lib.sh` and each reader command.

## Architecture

- `gate_lib.sh` sources `agent_roles.sh` at load time, making `MEMORY_PROJECT` and the 13 constants available to all gate commands.
- Reader commands (refine, plan, implement) source `agent_roles.sh` directly before defining `load_memory()`, so `MEMORY_PROJECT` is in scope for the project filter.
- `write_memory_entry()` accepts an optional 6th parameter `ROLE`; if omitted it falls back to the `$AGENT_ID` env var; if that is unset it falls back to `"unknown"`. Each command sets `AGENT_ID` from the new constants in Phase 1 LOAD.
- No Python files, structured backend, Docker services, or backfilling of existing entries.

## Tech Stack

Shell (bash), dark-factory markdown command files, existing test harness (`dark-factory/tests/`).

---

## File Structure

| File | Action | Purpose |
|---|---|---|
| `dark-factory/scripts/agent_roles.sh` | **Create** | 13 role-ID constants + `MEMORY_PROJECT` |
| `dark-factory/scripts/gate_lib.sh` | **Update** | Source `agent_roles.sh`; add optional 6th param to `write_memory_entry()` |
| `.archon/commands/dark-factory-refine.md` | **Update** | Source `agent_roles.sh`; project filter in `load_memory()`; set `AGENT_ID`; update Phase 5 shell-appends |
| `.archon/commands/dark-factory-plan.md` | **Update** | Source `agent_roles.sh`; project filter in `load_memory()`; set `AGENT_ID` |
| `.archon/commands/dark-factory-implement.md` | **Update** | Source `agent_roles.sh`; project filter in `load_memory()`; set `AGENT_ID` |
| `.archon/commands/dark-factory-conformance.md` | **Update** | Set `AGENT_ID` default after `gate_lib.sh` source |
| `.archon/commands/dark-factory-code-review.md` | **Update** | Set `AGENT_ID` default after `gate_lib.sh` source |
| `docs/agents/domain.md` | **Update** | Document cross-agent read convention |
| `dark-factory/tests/test_agent_roles.sh` | **Create** | Verify all 13 constants + `MEMORY_PROJECT` in `agent_roles.sh` |
| `dark-factory/tests/test_conformance_memory_write.sh` | **Update** | Verify `project:` and `agentId:` tags in `write_memory_entry()` output |
| `dark-factory/tests/test_load_memory.sh` | **Update** | Verify project-filter behavior in `load_memory()` |

---

## Tasks

### Task 1 — Create `dark-factory/scripts/agent_roles.sh`

**Files:** `dark-factory/scripts/agent_roles.sh`, `dark-factory/tests/test_agent_roles.sh`

#### 1a. Write failing test

Create `dark-factory/tests/test_agent_roles.sh`:

```bash
#!/usr/bin/env bash
# Unit tests for agent_roles.sh — verifies all 13 constants and MEMORY_PROJECT.
set -euo pipefail

REPO_ROOT=$(git rev-parse --show-toplevel)
source "${REPO_ROOT}/dark-factory/scripts/agent_roles.sh"

PASS=0; FAIL=0

assert() {
  local desc="$1" result="$2"
  if [ "$result" = "0" ]; then
    echo "PASS: $desc"; PASS=$((PASS+1))
  else
    echo "FAIL: $desc"; FAIL=$((FAIL+1))
  fi
}

assert "MEMORY_PROJECT=markethawk" \
  "$([ "${MEMORY_PROJECT:-}" = 'markethawk' ] && echo 0 || echo 1)"

assert "AGENT_ID_FACTORY_DIRECTOR=factory-director" \
  "$([ "${AGENT_ID_FACTORY_DIRECTOR:-}" = 'factory-director' ] && echo 0 || echo 1)"

assert "AGENT_ID_INTAKE_TRIAGE=intake-triage-agent" \
  "$([ "${AGENT_ID_INTAKE_TRIAGE:-}" = 'intake-triage-agent' ] && echo 0 || echo 1)"

assert "AGENT_ID_REFINEMENT=refinement-agent" \
  "$([ "${AGENT_ID_REFINEMENT:-}" = 'refinement-agent' ] && echo 0 || echo 1)"

assert "AGENT_ID_PLANNING=planning-agent" \
  "$([ "${AGENT_ID_PLANNING:-}" = 'planning-agent' ] && echo 0 || echo 1)"

assert "AGENT_ID_IMPLEMENTATION=implementation-agent" \
  "$([ "${AGENT_ID_IMPLEMENTATION:-}" = 'implementation-agent' ] && echo 0 || echo 1)"

assert "AGENT_ID_VALIDATION=validation-agent" \
  "$([ "${AGENT_ID_VALIDATION:-}" = 'validation-agent' ] && echo 0 || echo 1)"

assert "AGENT_ID_CODE_REVIEW=code-review-agent" \
  "$([ "${AGENT_ID_CODE_REVIEW:-}" = 'code-review-agent' ] && echo 0 || echo 1)"

assert "AGENT_ID_SECURITY=security-agent" \
  "$([ "${AGENT_ID_SECURITY:-}" = 'security-agent' ] && echo 0 || echo 1)"

assert "AGENT_ID_DECONFLICT=deconflict-agent" \
  "$([ "${AGENT_ID_DECONFLICT:-}" = 'deconflict-agent' ] && echo 0 || echo 1)"

assert "AGENT_ID_CI_RESCUE=ci-rescue-agent" \
  "$([ "${AGENT_ID_CI_RESCUE:-}" = 'ci-rescue-agent' ] && echo 0 || echo 1)"

assert "AGENT_ID_MERGE_GATE=merge-gate-agent" \
  "$([ "${AGENT_ID_MERGE_GATE:-}" = 'merge-gate-agent' ] && echo 0 || echo 1)"

assert "AGENT_ID_COST_TELEMETRY=cost-telemetry-agent" \
  "$([ "${AGENT_ID_COST_TELEMETRY:-}" = 'cost-telemetry-agent' ] && echo 0 || echo 1)"

assert "AGENT_ID_HUMAN_LIAISON=human-liaison-agent" \
  "$([ "${AGENT_ID_HUMAN_LIAISON:-}" = 'human-liaison-agent' ] && echo 0 || echo 1)"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
```

#### 1b. Verify test fails

```bash
bash dark-factory/tests/test_agent_roles.sh
# Expected: error — cannot source dark-factory/scripts/agent_roles.sh (file not found)
```

#### 1c. Create `dark-factory/scripts/agent_roles.sh`

```bash
#!/usr/bin/env bash
# Agent role-ID constants for Dark Factory memory scoping.
# Sourced by gate_lib.sh and by each phase command that writes or reads memory.
# Do NOT add set -euo pipefail — this file is sourced and must not alter caller shell options.

MEMORY_PROJECT="markethawk"

AGENT_ID_FACTORY_DIRECTOR="factory-director"
AGENT_ID_INTAKE_TRIAGE="intake-triage-agent"
AGENT_ID_REFINEMENT="refinement-agent"
AGENT_ID_PLANNING="planning-agent"
AGENT_ID_IMPLEMENTATION="implementation-agent"
AGENT_ID_VALIDATION="validation-agent"
AGENT_ID_CODE_REVIEW="code-review-agent"
AGENT_ID_SECURITY="security-agent"
AGENT_ID_DECONFLICT="deconflict-agent"
AGENT_ID_CI_RESCUE="ci-rescue-agent"
AGENT_ID_MERGE_GATE="merge-gate-agent"
AGENT_ID_COST_TELEMETRY="cost-telemetry-agent"
AGENT_ID_HUMAN_LIAISON="human-liaison-agent"
```

#### 1d. Verify test passes

```bash
bash dark-factory/tests/test_agent_roles.sh
# Expected: 14 passed, 0 failed
```

#### 1e. Commit

```bash
git add dark-factory/scripts/agent_roles.sh dark-factory/tests/test_agent_roles.sh
git commit -m "feat(#651): add agent_roles.sh with 13 role-ID constants and MEMORY_PROJECT"
```

---

### Task 2 — Extend `write_memory_entry()` in `gate_lib.sh`

**Files:** `dark-factory/scripts/gate_lib.sh`, `dark-factory/tests/test_conformance_memory_write.sh`

#### 2a. Add failing tests to `test_conformance_memory_write.sh`

Append at the end of `dark-factory/tests/test_conformance_memory_write.sh` (before the final results block):

```bash
# ---- write_memory_entry() tag tests (R1/R2) ----

# Test: written entry includes project:markethawk and agentId: from explicit 6th param
TMPWM1=$(mktemp /tmp/test_write_memory_XXXXXX.md)
printf '# Test\n' > "$TMPWM1"
AGENT_ID="" write_memory_entry "$TMPWM1" "dark-factory/scripts/" "Test avoidance text" "test" "651" "planning-agent"

assert "written entry includes project:markethawk (explicit 6th param)" \
  "$(grep -q 'project:markethawk' "$TMPWM1" && echo 0 || echo 1)"

assert "written entry includes agentId:planning-agent (explicit 6th param)" \
  "$(grep -q 'agentId:planning-agent' "$TMPWM1" && echo 0 || echo 1)"

rm -f "$TMPWM1"

# Test: falls back to AGENT_ID env var when no 6th param
TMPWM2=$(mktemp /tmp/test_write_memory_XXXXXX.md)
printf '# Test\n' > "$TMPWM2"
AGENT_ID="refinement-agent" write_memory_entry "$TMPWM2" "dark-factory/" "Another avoidance text" "test" "651"

assert "written entry uses AGENT_ID env var when 6th param omitted" \
  "$(grep -q 'agentId:refinement-agent' "$TMPWM2" && echo 0 || echo 1)"

rm -f "$TMPWM2"

# Test: falls back to "unknown" when neither 6th param nor AGENT_ID is set
TMPWM3=$(mktemp /tmp/test_write_memory_XXXXXX.md)
printf '# Test\n' > "$TMPWM3"
AGENT_ID="" write_memory_entry "$TMPWM3" "docs/" "Yet another text" "test" "651"

assert "written entry uses 'unknown' fallback when no 6th param and AGENT_ID unset" \
  "$(grep -q 'agentId:unknown' "$TMPWM3" && echo 0 || echo 1)"

rm -f "$TMPWM3"
```

#### 2b. Verify tests fail

```bash
bash dark-factory/tests/test_conformance_memory_write.sh
# Expected: the 3 new write_memory_entry tag asserts fail (project: and agentId: not yet in output)
```

#### 2c. Update `dark-factory/scripts/gate_lib.sh`

Replace the top of the file (before `route_memory_file`) to source `agent_roles.sh`, and update `write_memory_entry()` to accept the optional 6th parameter:

Full updated `gate_lib.sh`:

```bash
#!/usr/bin/env bash
# Shared gate functions sourced by dark-factory-conformance.md and dark-factory-code-review.md.
# Do not add gate-specific logic here — only the three shared primitives.
# Do NOT add set -euo pipefail: this file is sourced and must not alter caller shell options.

GATE_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=dark-factory/scripts/agent_roles.sh
source "${GATE_LIB_DIR}/agent_roles.sh"

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

write_memory_entry() {
  # Usage: write_memory_entry TARGET PATH_PREFIX VIOLATION_TEXT SOURCE ISSUE_NUM [AGENT_ID]
  local TARGET="$1" PATH_PREFIX="$2" TEXT="$3" SOURCE="$4" ISSUE="$5"
  local ROLE="${6:-${AGENT_ID:-unknown}}"

  # Dedup: skip if core sentence already present
  if grep -qF "$TEXT" "$TARGET" 2>/dev/null; then
    echo "memory-write: duplicate entry skipped — already in $TARGET"
    return 0
  fi

  # Expiry cleanup (mawk-compatible two-argument match form)
  TODAY=$(date +%Y-%m-%d)
  awk -v today="$TODAY" '
    /expires:[0-9]{4}-[0-9]{2}-[0-9]{2}/ {
      found=match($0, /expires:[0-9]{4}-[0-9]{2}-[0-9]{2}/)
      if (found) { expiry_date=substr($0, RSTART+8, 10); if (expiry_date < today) next }
    }
    { print }
  ' "$TARGET" > "$TARGET.tmp" && mv "$TARGET.tmp" "$TARGET"

  # Cap check (30 authoritative entries per file)
  COUNT=$(grep -c '^\- \[PATTERN\]\|^\- \[AVOID\]\|^\- \[FIX\]' "$TARGET" 2>/dev/null || echo 0)
  if [ "$COUNT" -ge 30 ]; then
    echo "memory-write: cap reached ($COUNT entries) in $TARGET — skipping write"
    return 0
  fi

  EXPIRES=$(date -d '+6 months' +%Y-%m-%d 2>/dev/null || date -v+6m +%Y-%m-%d)
  ENTRY="- [AVOID] $TEXT <!-- project:${MEMORY_PROJECT} agentId:${ROLE} issue:#$ISSUE date:$(date +%Y-%m-%d) expires:$EXPIRES source:$SOURCE path:$PATH_PREFIX -->"

  # Insert before the PROVISIONAL section delimiter (or append if no delimiter)
  if grep -q '^---$' "$TARGET" 2>/dev/null; then
    sed -i "/^---$/i $ENTRY" "$TARGET"
  else
    echo "$ENTRY" >> "$TARGET"
  fi
}

emit_verdict() {
  # Usage: emit_verdict GATE_TYPE STATUS FINDINGS_COUNT SEVERITY
  local GATE="$1" STATUS="$2" COUNT="$3" SEV="$4"
  printf "STATUS: %s\nGATE_TYPE: %s\nFINDINGS_COUNT: %s\nSEVERITY: %s\n" \
    "$STATUS" "$GATE" "$COUNT" "$SEV"
}
```

#### 2d. Verify tests pass

```bash
bash dark-factory/tests/test_conformance_memory_write.sh
# Expected: all asserts pass (including the 3 new tag asserts)
```

#### 2e. Commit

```bash
git add dark-factory/scripts/gate_lib.sh dark-factory/tests/test_conformance_memory_write.sh
git commit -m "feat(#651): source agent_roles.sh in gate_lib.sh; add project/agentId tags to write_memory_entry"
```

---

### Task 3 — Add project filter to `load_memory()` in the three reader commands

**Files:** `.archon/commands/dark-factory-refine.md`, `.archon/commands/dark-factory-plan.md`, `.archon/commands/dark-factory-implement.md`, `dark-factory/tests/test_load_memory.sh`

#### 3a. Update `test_load_memory.sh` to source `agent_roles.sh` and add project-filter tests

At the top of `dark-factory/tests/test_load_memory.sh`, after `set -euo pipefail`, add:

```bash
REPO_ROOT=$(git rev-parse --show-toplevel)
source "${REPO_ROOT}/dark-factory/scripts/agent_roles.sh"
```

Update the inline `load_memory()` definition (replacing the existing one after the `AFFECTED` assignment) to include the project filter:

```bash
load_memory() {
  local MEMFILE="$1"
  [ -f "$MEMFILE" ] || return
  while IFS= read -r line; do
    # Project filter: skip entries tagged for a different project.
    # Entries without any project: tag are always included (legacy backward compat).
    if echo "$line" | grep -q 'project:'; then
      if ! echo "$line" | grep -q "project:${MEMORY_PROJECT}"; then
        continue
      fi
    fi
    # Path filter: existing behavior unchanged.
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

Append new project-filter test cases before the final results block:

```bash
# ---- Project filter tests (R3) ----
AFFECTED=""

TMPPROJ=$(mktemp /tmp/test_load_memory_XXXXXX.md)
cat > "$TMPPROJ" << 'MEMEOF'
- [PATTERN] No project tag — always included
- [PATTERN] Wrong project <!-- project:otherproject issue:#1 date:2026-01-01 expires:2026-12-01 source:refine -->
- [PATTERN] Matching project <!-- project:markethawk issue:#2 date:2026-01-01 expires:2026-12-01 source:refine -->
MEMEOF

OUTPUT_PROJ=$(load_memory "$TMPPROJ")
rm -f "$TMPPROJ"

assert "entry without project: tag passes through" \
  "$(echo "$OUTPUT_PROJ" | grep -q 'No project tag' && echo 0 || echo 1)"

assert "entry with wrong project: is excluded" \
  "$(echo "$OUTPUT_PROJ" | grep -q 'Wrong project' && echo 1 || echo 0)"

assert "entry with project:markethawk is included" \
  "$(echo "$OUTPUT_PROJ" | grep -q 'Matching project' && echo 0 || echo 1)"

# Combined: project filter AND path filter interact correctly
AFFECTED="backend/app/routers/scanner.py"

TMPCOMB=$(mktemp /tmp/test_load_memory_XXXXXX.md)
cat > "$TMPCOMB" << 'MEMEOF'
- [PATTERN] Matching project, matching path <!-- project:markethawk path:backend/app/ issue:#3 date:2026-01-01 expires:2026-12-01 source:refine -->
- [PATTERN] Matching project, non-matching path <!-- project:markethawk path:frontend/src/ issue:#4 date:2026-01-01 expires:2026-12-01 source:refine -->
- [PATTERN] Wrong project, matching path <!-- project:otherproject path:backend/app/ issue:#5 date:2026-01-01 expires:2026-12-01 source:refine -->
MEMEOF

OUTPUT_COMB=$(load_memory "$TMPCOMB")
rm -f "$TMPCOMB"

assert "matching project + matching path: included" \
  "$(echo "$OUTPUT_COMB" | grep -q 'Matching project, matching path' && echo 0 || echo 1)"

assert "matching project + non-matching path: excluded" \
  "$(echo "$OUTPUT_COMB" | grep -q 'Matching project, non-matching path' && echo 1 || echo 0)"

assert "wrong project + matching path: excluded by project filter" \
  "$(echo "$OUTPUT_COMB" | grep -q 'Wrong project, matching path' && echo 1 || echo 0)"
```

#### 3b. Verify updated test passes

```bash
bash dark-factory/tests/test_load_memory.sh
# Expected: all existing tests pass + 6 new project-filter tests pass
```

#### 3c. Update Phase 1 LOAD in each reader command

In each of the three files, in the Phase 1 LOAD section, immediately before the `load_memory()` function definition block, insert the `agent_roles.sh` source instruction and update the `load_memory()` code block.

**`.archon/commands/dark-factory-refine.md`** — find the existing `load_memory` definition block and replace it:

Old block (approximately):
```bash
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

New block (preceded by source instruction). **Retain the existing `AFFECTED=` assignment above the function:**
```bash
AFFECTED=$(git diff --name-only origin/main...HEAD 2>/dev/null || echo "")

REPO_ROOT=$(git rev-parse --show-toplevel)
source "${REPO_ROOT}/dark-factory/scripts/agent_roles.sh"

# load_memory: reads a memory file; project-tagged entries for other projects are excluded;
# path-tagged entries are filtered against AFFECTED; entries with neither tag are always included.
# When AFFECTED is empty (new branch, pre-impl), all path-tagged entries are included.
load_memory() {
  local MEMFILE=".archon/memory/$1"
  [ -f "$MEMFILE" ] || return
  while IFS= read -r line; do
    # Project filter: skip entries tagged for a different project.
    # Entries without any project: tag are always included (legacy backward compat).
    if echo "$line" | grep -q 'project:'; then
      if ! echo "$line" | grep -q "project:${MEMORY_PROJECT}"; then
        continue
      fi
    fi
    # Path filter: existing behavior unchanged.
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

Apply the same replacement to **`.archon/commands/dark-factory-plan.md`** and **`.archon/commands/dark-factory-implement.md`** (the `load_memory()` definition in each is identical in structure; only the surrounding prose differs). In each file, keep the pre-existing `AFFECTED=` line — only the function body and the new source + comment lines are new.

#### 3d. Commit

```bash
git add .archon/commands/dark-factory-refine.md \
        .archon/commands/dark-factory-plan.md \
        .archon/commands/dark-factory-implement.md \
        dark-factory/tests/test_load_memory.sh
git commit -m "feat(#651): add project-tag filter to load_memory() in reader commands; update test"
```

---

### Task 4 — Set AGENT_ID defaults in all 5 command files + update Phase 5 shell-appends

**Files:** `.archon/commands/dark-factory-refine.md`, `.archon/commands/dark-factory-plan.md`, `.archon/commands/dark-factory-implement.md`, `.archon/commands/dark-factory-conformance.md`, `.archon/commands/dark-factory-code-review.md`

#### 4a. Set AGENT_ID in the three reader commands

In each reader command file, directly after the `source "${REPO_ROOT}/dark-factory/scripts/agent_roles.sh"` line **that was inserted by Task 3c**, add one line setting the default AGENT_ID. The full block after Task 3c's edit looks like:

**`.archon/commands/dark-factory-refine.md`:**
```bash
REPO_ROOT=$(git rev-parse --show-toplevel)
source "${REPO_ROOT}/dark-factory/scripts/agent_roles.sh"
AGENT_ID="${AGENT_ID_REFINEMENT}"    # ← add this line
```

**`.archon/commands/dark-factory-plan.md`:**
```bash
REPO_ROOT=$(git rev-parse --show-toplevel)
source "${REPO_ROOT}/dark-factory/scripts/agent_roles.sh"
AGENT_ID="${AGENT_ID_PLANNING}"      # ← add this line
```

**`.archon/commands/dark-factory-implement.md`:**
```bash
REPO_ROOT=$(git rev-parse --show-toplevel)
source "${REPO_ROOT}/dark-factory/scripts/agent_roles.sh"
AGENT_ID="${AGENT_ID_IMPLEMENTATION}" # ← add this line
```

#### 4b. Set AGENT_ID in the two gate commands

Both conformance and code-review already source `gate_lib.sh` at Phase 1 LOAD (which now sources `agent_roles.sh`, making the constants available). Add one line after their existing `source "${REPO_ROOT}/dark-factory/scripts/gate_lib.sh"` call:

**`.archon/commands/dark-factory-conformance.md`** — find:
```bash
REPO_ROOT=$(git rev-parse --show-toplevel)
source "${REPO_ROOT}/dark-factory/scripts/gate_lib.sh"
```
Replace with:
```bash
REPO_ROOT=$(git rev-parse --show-toplevel)
source "${REPO_ROOT}/dark-factory/scripts/gate_lib.sh"
AGENT_ID="${AGENT_ID_DECONFLICT}"
```

**`.archon/commands/dark-factory-code-review.md`** — find:
```bash
REPO_ROOT=$(git rev-parse --show-toplevel)
source "${REPO_ROOT}/dark-factory/scripts/gate_lib.sh"
```
Replace with:
```bash
REPO_ROOT=$(git rev-parse --show-toplevel)
source "${REPO_ROOT}/dark-factory/scripts/gate_lib.sh"
AGENT_ID="${AGENT_ID_CODE_REVIEW}"
```

#### 4c. Update Phase 5 shell-append format in `dark-factory-refine.md`

In `.archon/commands/dark-factory-refine.md`, Phase 5 Step 7a contains a literal PATTERN/AVOID template block with inline HTML comments. Find this block:

```
- [PATTERN] <the chosen approach and why it is correct> <!-- issue:#$ISSUE_NUM date:$(date +%Y-%m-%d) expires:$(date -d '+6 months' +%Y-%m-%d 2>/dev/null || date -v+6m +%Y-%m-%d) source:refine -->
- [AVOID] <the rejected approach and the concrete reason it was rejected> <!-- issue:#$ISSUE_NUM date:$(date +%Y-%m-%d) expires:$(date -d '+6 months' +%Y-%m-%d 2>/dev/null || date -v+6m +%Y-%m-%d) source:refine -->
```

Replace with (adding `project:${MEMORY_PROJECT} agentId:${AGENT_ID}` before the closing `-->`):
```
- [PATTERN] <the chosen approach and why it is correct> <!-- issue:#$ISSUE_NUM date:$(date +%Y-%m-%d) expires:$(date -d '+6 months' +%Y-%m-%d 2>/dev/null || date -v+6m +%Y-%m-%d) source:refine project:${MEMORY_PROJECT} agentId:${AGENT_ID} -->
- [AVOID] <the rejected approach and the concrete reason it was rejected> <!-- issue:#$ISSUE_NUM date:$(date +%Y-%m-%d) expires:$(date -d '+6 months' +%Y-%m-%d 2>/dev/null || date -v+6m +%Y-%m-%d) source:refine project:${MEMORY_PROJECT} agentId:${AGENT_ID} -->
```

Step 7b is prose (no literal template block). Update the prose sentence in Step 7b that currently says `with \`source:refine\`` to instead say `with \`source:refine\`, \`project:${MEMORY_PROJECT}\`, and \`agentId:${AGENT_ID}\`` so shell-appended entries for `backend-patterns.md`, `frontend-patterns.md`, and `dark-factory-ops.md` also carry the new tags.

#### 4d. Commit

```bash
git add .archon/commands/dark-factory-refine.md \
        .archon/commands/dark-factory-plan.md \
        .archon/commands/dark-factory-implement.md \
        .archon/commands/dark-factory-conformance.md \
        .archon/commands/dark-factory-code-review.md
git commit -m "feat(#651): set AGENT_ID defaults in all command files; update Phase 5 shell-append format"
```

---

### Task 5 — Document cross-agent read convention in `docs/agents/domain.md`

**Files:** `docs/agents/domain.md`

#### 5a. Append new section to `docs/agents/domain.md`

Add the following section at the end of the file:

```markdown
## Memory Isolation and Agent Role Scoping

Dark Factory memory entries carry `project:` and `agentId:` tags:

- `project:markethawk` — all entries in this repo belong to this project; a future multi-project deployment can filter by project without modifying the files.
- `agentId:<role>` — the role identity that wrote the entry (e.g. `planning-agent`, `implementation-agent`). Distinct from `source:` which records the pipeline phase.

### Cross-agent read convention

**Validation, security, and gate agents MUST NOT call `load_memory()` for entries written by `implementation-agent` or `planning-agent` unless the caller explicitly declares the need.**

Today, `dark-factory-validate.md` and `dark-factory-conformance.md` do not read memory at all, so no leak is possible. When a validation or security agent begins reading memory, a follow-up ticket must add an `allow_agent_ids=` parameter to `load_memory()` that filters by `agentId:` at load time. Until that ticket is implemented, validation/security agents must not call `load_memory()`.

Role ID constants are defined in `dark-factory/scripts/agent_roles.sh`. The current 13 stable roles are:

| Constant | Value |
|---|---|
| `AGENT_ID_FACTORY_DIRECTOR` | `factory-director` |
| `AGENT_ID_INTAKE_TRIAGE` | `intake-triage-agent` |
| `AGENT_ID_REFINEMENT` | `refinement-agent` |
| `AGENT_ID_PLANNING` | `planning-agent` |
| `AGENT_ID_IMPLEMENTATION` | `implementation-agent` |
| `AGENT_ID_VALIDATION` | `validation-agent` |
| `AGENT_ID_CODE_REVIEW` | `code-review-agent` |
| `AGENT_ID_SECURITY` | `security-agent` |
| `AGENT_ID_DECONFLICT` | `deconflict-agent` |
| `AGENT_ID_CI_RESCUE` | `ci-rescue-agent` |
| `AGENT_ID_MERGE_GATE` | `merge-gate-agent` |
| `AGENT_ID_COST_TELEMETRY` | `cost-telemetry-agent` |
| `AGENT_ID_HUMAN_LIAISON` | `human-liaison-agent` |

Adding a new role requires a code change to `agent_roles.sh`; there is no dynamic registration.
```

#### 5b. Commit

```bash
git add docs/agents/domain.md
git commit -m "docs(#651): document agent role scoping and cross-agent read convention"
```

---

## Verification

After all tasks are complete, run the full test suite to confirm no regressions:

```bash
bash dark-factory/tests/test_agent_roles.sh
bash dark-factory/tests/test_conformance_memory_write.sh
bash dark-factory/tests/test_load_memory.sh
# Expected: all three suites report 0 failed
```

Confirm `write_memory_entry()` now emits the correct tags end-to-end:

```bash
# Quick smoke test
TMPSMOKE=$(mktemp /tmp/smoke_XXXXXX.md)
printf '# Smoke\n' > "$TMPSMOKE"
AGENT_ID="planning-agent" bash -c "
  source dark-factory/scripts/gate_lib.sh
  write_memory_entry '$TMPSMOKE' 'dark-factory/' 'Smoke test avoidance' 'plan' '651'
"
grep 'project:markethawk' "$TMPSMOKE" && grep 'agentId:planning-agent' "$TMPSMOKE" && echo 'OK'
rm -f "$TMPSMOKE"
```

---

## Task Summary

| # | Task | Files | Steps |
|---|---|---|---|
| 1 | Create `agent_roles.sh` | 2 files | 5 |
| 2 | Extend `write_memory_entry()` in `gate_lib.sh` | 2 files | 5 |
| 3 | Add project filter to `load_memory()` in reader commands | 4 files | 4 |
| 4 | Set `AGENT_ID` defaults in all 5 command files | 5 files | 4 |
| 5 | Document cross-agent read convention | 1 file | 2 |

**5 tasks, 20 implementation steps**
