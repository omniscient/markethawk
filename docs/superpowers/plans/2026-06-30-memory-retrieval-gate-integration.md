# Plan: Memory Retrieval Gate Integration — Dark Factory

**Date:** 2026-06-30
**Issue:** #652
**Epic:** #643
**Spec:** `docs/superpowers/specs/2026-06-30-memory-retrieval-gate-integration-design.md`
**Branch:** `feat/issue-652-*`

---

## Goal

Replace the inline `load_memory()` bash function (duplicated across three gates) and the `_filter_memory()` helper (plan gate only) with a single `python3 dark-factory/scripts/memory_retrieve.py --phase <role>` call per gate. Add a memory-load step to the validate gate (currently has none). Upgrade the refine gate's write path to use `memory_write.py` (replacing awk expiry, echo appends, grep dedup, and the post-write backstop). Deliver a bash smoke test covering all four phases.

---

## Architecture

`memory_retrieve.py` (merged in #646/#678) owns all retrieval logic: it selects area files via `AREA_PREFIX_MAP`, applies `PHASE_SOURCE_MAP` source filters, handles index.jsonl fast path and markdown fallback, and strips `[PROVISIONAL]`/`[INVALID]` entries. Calling it once per gate replaces the current 20-line bash function.

`memory_write.py` (merged in #648/#679) owns write logic: normalized dedup, 30-entry cap, expiry cleanup, and `index.jsonl` stub writes. It replaces the awk/echo/grep/backstop block in the refine gate.

`.archon/commands/` files are live-read from the cloned repo at runtime — no image rebuild is needed for changes to these files.

---

## Tech Stack

- **Bash** — gate command files (markdown), smoke test
- **Python 3** — `memory_retrieve.py`, `memory_write.py` (already in `dark-factory/scripts/`)
- **pytest / tsc** — unchanged (not touched by this issue)

---

## File Structure

| File | Change |
|------|--------|
| `dark-factory/tests/test_memory_integration.sh` | **New** — smoke test calling `memory_retrieve.py` for all 4 phases |
| `.archon/commands/dark-factory-refine.md` | Remove `load_memory()` + 3 calls; add `memory_retrieve.py` call; replace awk/echo write path with `memory_write.py`; add artifact step |
| `.archon/commands/dark-factory-plan.md` | Remove `load_memory()` + 3 calls + `_filter_memory()` block; add single `memory_retrieve.py` call setting `$MEMORY_CONTEXT`; add artifact step |
| `.archon/commands/dark-factory-implement.md` | Remove `load_memory()` + 5 calls; add `memory_retrieve.py` call; add artifact step |
| `.archon/commands/dark-factory-validate.md` | Add memory load step (REPO_ROOT + CHANGED + `memory_retrieve.py`) and artifact step to Phase 1 LOAD |

`dark-factory/scripts/gate_lib.sh` — no changes (write path already delegates to `memory_write.py`).

---

## Task 1: Write smoke test for memory_retrieve.py across all phases

**Files:** `dark-factory/tests/test_memory_integration.sh`

### Steps

1. **Write test** — create `dark-factory/tests/test_memory_integration.sh`:

```bash
#!/usr/bin/env bash
# Smoke test: memory_retrieve.py returns exit 0 for each gate phase.
# Validates the validate-phase source filter (conformance-only or empty output).
# Validates that --issue accepts a valid integer (gates always pass --issue "$ISSUE_NUM").
# Follows the pattern in test_load_memory.sh and test_conformance_memory_write.sh.
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

REPO_ROOT=$(git rev-parse --show-toplevel)
SCRIPT="$REPO_ROOT/dark-factory/scripts/memory_retrieve.py"

# ── Phase exit-code assertions (no --issue) ──────────────────────────────
# Tests that each phase exits 0 when no --issue is supplied (optional arg).
# Use || true to prevent set -e from aborting before $? is captured.
for phase in refine plan implement validate; do
  python3 "$SCRIPT" --phase "$phase" > /dev/null 2>&1 && rc=0 || rc=$?
  assert "phase '$phase' exits 0 (no --issue, default memory dir)" "$rc"
done

# ── Phase exit-code assertions (with --issue) ────────────────────────────
# Gates always call --issue "$ISSUE_NUM" (a valid integer); verify exit 0.
# argparse type=int rejects empty/non-integer; this confirms a valid integer passes.
for phase in refine plan implement validate; do
  python3 "$SCRIPT" --phase "$phase" --issue 652 > /dev/null 2>&1 && rc=0 || rc=$?
  assert "phase '$phase' exits 0 with --issue 652" "$rc"
done

# ── Validate phase source filter ─────────────────────────────────────────
# Create a temp memory dir with one conformance entry and one implement entry.
TMPDIR_MEM=$(mktemp -d /tmp/test_mem_integration_XXXXXX)
trap "rm -rf $TMPDIR_MEM" EXIT

cat > "$TMPDIR_MEM/dark-factory-ops.md" << 'MEMEOF'
# Test

- [PATTERN] Conformance entry <!-- source:conformance issue:#1 date:2026-01-01 expires:2026-12-31 -->
- [AVOID] Implement entry <!-- source:implement issue:#2 date:2026-01-01 expires:2026-12-31 -->
MEMEOF

cat > "$TMPDIR_MEM/codebase-patterns.md" << 'MEMEOF'
# Test Codebase
MEMEOF

cat > "$TMPDIR_MEM/architecture.md" << 'MEMEOF'
# Test Architecture
MEMEOF

OUTPUT=$(python3 "$SCRIPT" --phase validate --memory-dir "$TMPDIR_MEM" 2>/dev/null || true)

# Either the output is empty, or every source: tag in the output is source:conformance
if [ -z "$OUTPUT" ]; then
  assert "validate phase: empty output is valid (no conformance entries matched)" "0"
else
  NON_CONFORMANCE=$(printf '%s\n' "$OUTPUT" | grep 'source:' | grep -v 'source:conformance' || true)
  assert "validate phase: no non-conformance source: tags in output" \
    "$([ -z "$NON_CONFORMANCE" ] && echo 0 || echo 1)"
  CONFORMANCE=$(printf '%s\n' "$OUTPUT" | grep 'source:conformance' || true)
  assert "validate phase: conformance entry appears in output" \
    "$([ -n "$CONFORMANCE" ] && echo 0 || echo 1)"
fi

# Implement entry must NOT appear in validate output
assert "validate phase: implement entry excluded from output" \
  "$(printf '%s\n' "$OUTPUT" | grep -q 'Implement entry' && echo 1 || echo 0)"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
```

2. **Make executable:**
```bash
chmod +x dark-factory/tests/test_memory_integration.sh
```

3. **Run test — expect all assertions to pass:**
```bash
bash dark-factory/tests/test_memory_integration.sh
```

Expected output:
```
PASS: phase 'refine' exits 0 (no --issue, default memory dir)
PASS: phase 'plan' exits 0 (no --issue, default memory dir)
PASS: phase 'implement' exits 0 (no --issue, default memory dir)
PASS: phase 'validate' exits 0 (no --issue, default memory dir)
PASS: phase 'refine' exits 0 with --issue 652
PASS: phase 'plan' exits 0 with --issue 652
PASS: phase 'implement' exits 0 with --issue 652
PASS: phase 'validate' exits 0 with --issue 652
PASS: validate phase: conformance entry appears in output
PASS: validate phase: no non-conformance source: tags in output
PASS: validate phase: implement entry excluded from output

Results: 11 passed, 0 failed
```

4. **Commit:**
```bash
git add dark-factory/tests/test_memory_integration.sh
git commit -m "test: smoke test for memory_retrieve.py across all 4 gate phases (#652)"
```

---

## Task 2: Update refine gate — replace read path

**Files:** `.archon/commands/dark-factory-refine.md`

### Steps

1. **Verify old pattern exists:**
```bash
grep -c "load_memory" .archon/commands/dark-factory-refine.md
# Expected: ≥1 (the function definition is present)
```

2. **Apply edit** — replace step 7 (the load_memory() function definition block) and steps 8–10 (the three `load_memory X.md` calls plus the note about PROVISIONAL/INVALID) with:

   **Remove** step 7's bash code block (everything from the opening bash fence through the closing fence after the `load_memory()` function) and replace with the `memory_retrieve.py` call. Keep `AFFECTED` and `REPO_ROOT` / `source agent_roles.sh`. Drop `AGENT_ID="${AGENT_ID_REFINEMENT}"` — `memory_write.py` (Task 3) takes `--source`/`--issue`, not `agentId:`, so the assignment becomes orphaned after the write-path refactor. The revised step 7 becomes:

   ```
   7. Compute the affected file set and retrieve memory context:

   ```bash
   AFFECTED=$(git diff --name-only origin/main...HEAD 2>/dev/null || echo "")

   REPO_ROOT=$(git rev-parse --show-toplevel)
   source "${REPO_ROOT}/dark-factory/scripts/agent_roles.sh"

   MEMORY_CONTEXT=$(python3 "${REPO_ROOT}/dark-factory/scripts/memory_retrieve.py" \
       --phase refine --files "$AFFECTED" --issue "$ISSUE_NUM")
   ```

   8. Write the memory block to the run artifact for observability:

   ```bash
   mkdir -p "$ARTIFACTS_DIR"
   printf '%s\n' "$MEMORY_CONTEXT" > "$ARTIFACTS_DIR/memory-context.md"
   ```

   Include `$MEMORY_CONTEXT` in the agent context — treat it as the merged set of applicable memory entries (global lessons + area-specific patterns + AVOID entries for this phase). Skip entries tagged `[PROVISIONAL]` and `[INVALID]` — they are excluded by `memory_retrieve.py` automatically.
   ```

   **Remove** original steps 8, 9, and 10 (the `load_memory codebase-patterns.md`, `load_memory architecture.md`, and `load_memory <area>.md` call lines, plus the paragraph beginning "When reading memory files, skip entries tagged...").

   The original "AVOID entries are especially relevant to spec decisions" paragraph and the "If this is a re-run" section remain unchanged.

3. **Verify old pattern removed and new pattern present:**
```bash
grep -c "load_memory" .archon/commands/dark-factory-refine.md
# Expected: 0

grep -q "memory_retrieve.py" .archon/commands/dark-factory-refine.md && echo "PRESENT" || echo "MISSING"
# Expected: PRESENT

grep -q "memory-context.md" .archon/commands/dark-factory-refine.md && echo "PRESENT" || echo "MISSING"
# Expected: PRESENT
```

4. **Run smoke test:**
```bash
bash dark-factory/tests/test_memory_integration.sh
# Expected: all pass (unchanged — this validates the script still works)
```

5. **Commit:**
```bash
git add .archon/commands/dark-factory-refine.md
git commit -m "refactor(refine): replace load_memory() with memory_retrieve.py --phase refine (#652)"
```

---

## Task 3: Update refine gate — replace write path

**Files:** `.archon/commands/dark-factory-refine.md`

The refine gate's Phase 5 currently uses raw shell appends with awk expiry cleanup, grep dedup, R4 cap warning, and a ~40-line post-write verification backstop. All are superseded by `memory_write.py`.

### Steps

1. **Verify old write patterns exist:**
```bash
grep -c "awk.*expires" .archon/commands/dark-factory-refine.md
# Expected: ≥ 1 (the expiry awk block)
grep -c "echo '- \[PATTERN\]'" .archon/commands/dark-factory-refine.md
# Expected: ≥ 1 (the direct append)
grep -c "MEMORY GUARD" .archon/commands/dark-factory-refine.md
# Expected: ≥ 1 (the backstop)
```

2. **Apply edit** — in Phase 5 step 7, remove the following named blocks in their entirety:
   - **Expiry cleanup** bash block (the `awk -v today` block, lines beginning "For each target memory file you are about to write, remove expired entries first")
   - **Sub-step a** (`PATTERN+AVOID` entry templates) — the code fence showing inline `<!-- ... -->` comments
   - **Sub-step b** (area-file convention writes: "For any codebase convention discovered during Phase 3 … append a `[PATTERN]` entry") — this sub-step references `${AGENT_ID}` and `${MEMORY_PROJECT}` which are removed in Task 2; replacing it avoids orphaned variable references
   - **Sub-step c** (dedup check: "Before appending any entry, check for duplicates: `grep -F`")
   - **Sub-step d** ("Do NOT write to `codebase-patterns.md` from the refine agent") — KEEP this as a prose guideline; it has no shell dependency
   - **Append-only rule** paragraph
   - **ONLY operations permitted** paragraph
   - **Per-file entry cap (R4)** bash block
   - **Post-write verification backstop** (`for MEM_FILE in .archon/memory/*.md` loop)

   Keep: "Write bar — default to nothing" instruction, provisional tier (R2) section, sub-step d (the prose prohibition on codebase-patterns.md), commit step (e).

   Replace sub-steps a–c and all surrounding helper blocks with:

   ```
   **For each architectural decision (a pair of chosen approach + rejected approach)**, call `memory_write.py` twice. Note: `memory_write.py` writes every entry as `[AVOID]` regardless of which entry is the "chosen" vs "rejected" approach — both calls produce `[AVOID]` lines in the file. This is the intended behavior per spec; the comments below are for human readability only:

   ```bash
   # Chosen-approach entry (written as [AVOID] by memory_write.py — tool limitation, per spec)
   python3 "${REPO_ROOT}/dark-factory/scripts/memory_write.py" \
       --target ".archon/memory/architecture.md" \
       --path-prefix ".archon/commands/" \
       --text "<the chosen approach and why it is correct>" \
       --source refine \
       --issue "$ISSUE_NUM"

   # Rejected-approach entry
   python3 "${REPO_ROOT}/dark-factory/scripts/memory_write.py" \
       --target ".archon/memory/architecture.md" \
       --path-prefix ".archon/commands/" \
       --text "<the rejected approach and the concrete reason it was rejected>" \
       --source refine \
       --issue "$ISSUE_NUM"
   ```

   For codebase convention discoveries (formerly sub-step b), target the relevant area file and adjust `--path-prefix` to the affected code area (e.g. `dark-factory/scripts/`):

   ```bash
   python3 "${REPO_ROOT}/dark-factory/scripts/memory_write.py" \
       --target ".archon/memory/dark-factory-ops.md" \
       --path-prefix "dark-factory/scripts/" \
       --text "<convention text>" \
       --source refine \
       --issue "$ISSUE_NUM"
   ```

   `memory_write.py` handles dedup, the 30-entry cap, expiry cleanup, and `index.jsonl` stub writes. No inline awk, grep, or counter logic is needed.
   ```

3. **Verify all removed blocks and orphaned variables are gone:**
```bash
grep -c "MEMORY GUARD" .archon/commands/dark-factory-refine.md
# Expected: 0
grep -c "awk.*expires" .archon/commands/dark-factory-refine.md
# Expected: 0
grep -c 'AGENT_ID\|MEMORY_PROJECT\|agentId:\|grep -F' .archon/commands/dark-factory-refine.md
# Expected: 0 (all orphaned variable references removed)
grep -q "memory_write.py" .archon/commands/dark-factory-refine.md && echo "PRESENT" || echo "MISSING"
# Expected: PRESENT
```

4. **Run smoke test:**
```bash
bash dark-factory/tests/test_memory_integration.sh
```

5. **Commit:**
```bash
git add .archon/commands/dark-factory-refine.md
git commit -m "refactor(refine): replace write-path awk/echo/backstop with memory_write.py (#652)"
```

---

## Task 4: Update plan gate

**Files:** `.archon/commands/dark-factory-plan.md`

The plan gate has `load_memory()` in Phase 1 LOAD (steps 6–9) AND a separate `_filter_memory()` helper block in Phase 3 (before the architect subagent). Both are replaced by a single `memory_retrieve.py` call in Phase 1; the `$MEMORY_CONTEXT` variable name is kept so Phase 3's architect prompt block needs no changes.

### Steps

1. **Verify old patterns exist:**
```bash
grep -c "load_memory\|_filter_memory" .archon/commands/dark-factory-plan.md
# Expected: ≥ 6 (one load_memory definition, 3 calls, one _filter_memory definition, multiple uses)
```

2. **Apply Phase 1 LOAD edit** — replace step 6 (the AFFECTED + `load_memory()` function definition block) and steps 7–9 (the three `load_memory X.md` call lines and the PROVISIONAL note) with:

   ```
   6. Compute the affected file set and retrieve memory context:

   ```bash
   AFFECTED=$(git diff --name-only origin/main...HEAD 2>/dev/null || echo "")

   REPO_ROOT=$(git rev-parse --show-toplevel)
   source "${REPO_ROOT}/dark-factory/scripts/agent_roles.sh"
   AGENT_ID="${AGENT_ID_PLANNING}"

   MEMORY_CONTEXT=$(python3 "${REPO_ROOT}/dark-factory/scripts/memory_retrieve.py" \
       --phase plan --files "$AFFECTED" --issue "$ISSUE_NUM")
   ```

   7. Write the memory block to the run artifact for observability:

   ```bash
   mkdir -p "$ARTIFACTS_DIR"
   printf '%s\n' "$MEMORY_CONTEXT" > "$ARTIFACTS_DIR/memory-context.md"
   ```

   Include `$MEMORY_CONTEXT` in the agent context as accumulated patterns and prior architectural decisions. Bake relevant memory lessons directly into the plan task steps. If a memory entry marks an approach as `AVOID`, do not plan steps that use that approach.
   ```

3. **Apply Phase 3 edit** — remove the entire `_filter_memory()` helper block and the `$MEMORY_CONTEXT`-building code (the `MEMORY_CONTEXT=""`, `_filter_memory()` function, and all the `if echo "$SPEC_COMPONENT" ...` branches). Keep the `Prepend $MEMORY_CONTEXT to the architect prompt` instruction and everything that follows it unchanged — `$MEMORY_CONTEXT` is now already populated from Phase 1.

   The removed block starts at:
   ```bash
   MEMORY_CONTEXT=""

   # Filter out [PROVISIONAL] and [INVALID] lines ...
   _filter_memory() {
   ```
   and ends after the last `fi` of the `if echo "$SPEC_COMPONENT" ...` chain.

   **Note on Phase-1/Phase-3 handoff:** `$MEMORY_CONTEXT` is now set in Phase 1 LOAD and consumed in Phase 3 by the architect subagent prompt. Because these are agent instruction phases (not one continuous shell script), the variable persists in the agent's execution context between phases. There is no shell-variable export needed; the agent holds the retrieved content and splices it into the architect prompt at Phase 3's `Prepend $MEMORY_CONTEXT` step.

4. **Verify:**
```bash
grep -c "load_memory\|_filter_memory" .archon/commands/dark-factory-plan.md
# Expected: 0

grep -q "memory_retrieve.py" .archon/commands/dark-factory-plan.md && echo "PRESENT" || echo "MISSING"
# Expected: PRESENT

grep -q "memory-context.md" .archon/commands/dark-factory-plan.md && echo "PRESENT" || echo "MISSING"
# Expected: PRESENT

# Confirm MEMORY_CONTEXT is still referenced for the architect subagent (must not be removed)
grep -q 'MEMORY_CONTEXT' .archon/commands/dark-factory-plan.md && echo "PRESENT" || echo "MISSING"
# Expected: PRESENT
```

5. **Run smoke test:**
```bash
bash dark-factory/tests/test_memory_integration.sh
```

6. **Commit:**
```bash
git add .archon/commands/dark-factory-plan.md
git commit -m "refactor(plan): replace load_memory() + _filter_memory() with memory_retrieve.py --phase plan (#652)"
```

---

## Task 5: Update implement gate

**Files:** `.archon/commands/dark-factory-implement.md`

### Steps

1. **Verify old pattern:**
```bash
grep -c "load_memory" .archon/commands/dark-factory-implement.md
# Expected: ≥1 (the function definition is present)
```

2. **Apply edit** — replace step 5 (AFFECTED + `load_memory()` function definition block) and steps 6–10 (five `load_memory X.md` call lines plus the PROVISIONAL note) with:

   ```
   5. Compute the affected file set and retrieve memory context:

   ```bash
   AFFECTED=$(git diff --name-only origin/main...HEAD 2>/dev/null || echo "")

   REPO_ROOT=$(git rev-parse --show-toplevel)
   source "${REPO_ROOT}/dark-factory/scripts/agent_roles.sh"
   AGENT_ID="${AGENT_ID_IMPLEMENTATION}"

   MEMORY_CONTEXT=$(python3 "${REPO_ROOT}/dark-factory/scripts/memory_retrieve.py" \
       --phase implement --files "$AFFECTED" --issue "$ISSUE_NUM")
   ```

   6. Write the memory block to the run artifact for observability:

   ```bash
   mkdir -p "$ARTIFACTS_DIR"
   printf '%s\n' "$MEMORY_CONTEXT" > "$ARTIFACTS_DIR/memory-context.md"
   ```

   Apply `$MEMORY_CONTEXT` as strong hints throughout implementation. Entries tagged `[PROVISIONAL]` and `[INVALID]` are excluded automatically by `memory_retrieve.py` — treat the retrieved context as authoritative. If a lesson conflicts with `CLAUDE.md` or `ARCHITECTURE.md`, follow those documents instead and note the conflict in `$ARTIFACTS_DIR/implementation.md`.
   ```

   The `### If intent is "continue"` section and everything after step 10 remain unchanged.

3. **Verify:**
```bash
grep -c "load_memory" .archon/commands/dark-factory-implement.md
# Expected: 0

grep -q "memory_retrieve.py" .archon/commands/dark-factory-implement.md && echo "PRESENT" || echo "MISSING"
# Expected: PRESENT

grep -q "memory-context.md" .archon/commands/dark-factory-implement.md && echo "PRESENT" || echo "MISSING"
# Expected: PRESENT
```

4. **Run smoke test:**
```bash
bash dark-factory/tests/test_memory_integration.sh
```

5. **Commit:**
```bash
git add .archon/commands/dark-factory-implement.md
git commit -m "refactor(implement): replace load_memory() with memory_retrieve.py --phase implement (#652)"
```

---

## Task 6: Update validate gate — add memory load step

**Files:** `.archon/commands/dark-factory-validate.md`

The validate gate's Phase 1 LOAD currently only reads `implementation.md` and `CLAUDE.md`. Add a memory retrieval step. `PHASE_SOURCE_MAP["validate"] == {"conformance"}` so only conformance-tagged entries are returned — no filtering needed beyond the `--phase validate` argument.

### Steps

1. **Verify no memory load exists:**
```bash
grep -c "memory_retrieve\|load_memory\|MEMORY_CONTEXT" .archon/commands/dark-factory-validate.md
# Expected: 0
```

2. **Apply edit** — expand Phase 1 LOAD from:

   ```
   ## Phase 1: LOAD

   Read the implementation context:
   - Read `$ARTIFACTS_DIR/implementation.md` for what was implemented
   - Read `CLAUDE.md` for validation rules
   ```

   To:

   ```
   ## Phase 1: LOAD

   Read the implementation context:
   - Read `$ARTIFACTS_DIR/implementation.md` for what was implemented
   - Read `CLAUDE.md` for validation rules

   Retrieve conformance memory entries for this gate:

   ```bash
   REPO_ROOT=$(git rev-parse --show-toplevel)
   CHANGED=$(git diff main...HEAD --name-only 2>/dev/null || echo "")
   MEMORY_CONTEXT=$(python3 "${REPO_ROOT}/dark-factory/scripts/memory_retrieve.py" \
       --phase validate --files "$CHANGED" --issue "$ISSUE_NUM")
   mkdir -p "$ARTIFACTS_DIR"
   printf '%s\n' "$MEMORY_CONTEXT" > "$ARTIFACTS_DIR/memory-context.md"
   ```

   `$MEMORY_CONTEXT` contains only `source:conformance`-tagged entries (filtered by `memory_retrieve.py` automatically). Use these as the conformance checklist during Phase 2 validation — if an entry flags a known failure mode, check explicitly for that pattern in the preview results.
   ```

3. **Verify:**
```bash
grep -q "memory_retrieve.py" .archon/commands/dark-factory-validate.md && echo "PRESENT" || echo "MISSING"
# Expected: PRESENT

grep -q "memory-context.md" .archon/commands/dark-factory-validate.md && echo "PRESENT" || echo "MISSING"
# Expected: PRESENT

grep -q "phase validate" .archon/commands/dark-factory-validate.md && echo "PRESENT" || echo "MISSING"
# Expected: PRESENT
```

4. **Run full smoke test:**
```bash
bash dark-factory/tests/test_memory_integration.sh
# Expected: all 7 assertions pass
```

5. **Commit:**
```bash
git add .archon/commands/dark-factory-validate.md
git commit -m "feat(validate): add memory_retrieve.py --phase validate to Phase 1 LOAD (#652)"
```

---

## Final Verification

After all 6 tasks, confirm no `load_memory` function definitions remain in any gate:

```bash
grep -rn "load_memory\(\)\|_filter_memory\(\)" .archon/commands/
# Expected: no output
```

Confirm `memory_retrieve.py` is wired into all four gates:

```bash
for gate in dark-factory-refine dark-factory-plan dark-factory-implement dark-factory-validate; do
  echo -n "$gate: "
  grep -q "memory_retrieve.py" ".archon/commands/$gate.md" && echo "✓" || echo "MISSING"
done
```

Confirm all four artifact writes are present:

```bash
grep -rn "memory-context.md" .archon/commands/
# Expected: 4 lines (one per gate)
```

Run smoke test one final time:

```bash
bash dark-factory/tests/test_memory_integration.sh
```
