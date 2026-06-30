# Memory Retrieval Gate Integration — Dark Factory

**Status:** design
**Date:** 2026-06-30
**Issue:** #652
**Epic:** #643 (Dark Factory memory system)

## Problem

The four Dark Factory pipeline gates (refine, plan, implement, validate) each contain a
hand-rolled inline `load_memory()` bash function that reads `.archon/memory/*.md` files
line-by-line, applies project and path filtering, and returns matching entries. This
inline function is ~20 lines of shell, duplicated four times, and is now superseded by
the centralized `dark-factory/scripts/memory_retrieve.py` adapter (merged in #646 and #678).
Additionally, the validate gate has no memory load step at all, even though the adapter
supports `--phase validate` and filters to `conformance`-tagged entries.

The inline `load_memory()` approach also misses index-backed retrieval: `memory_retrieve.py`
uses `index.jsonl` when present for fast lookup and falls back to scanning the markdown
files directly, while the bash function only scans markdown.

## Decision

Replace all inline `load_memory()` bash functions and the `_filter_memory()` helper in
the plan gate with a single `python3 dark-factory/scripts/memory_retrieve.py --phase <role>`
call per gate. Add a memory load step to the validate gate. Write a smoke-test script.

## Requirements

### Read path (primary)

1. **Refine gate** (`dark-factory-refine.md`): Remove the `load_memory()` bash function
   definition and the three separate `load_memory X.md` calls (steps 7–10 of Phase 1 LOAD).
   Replace with one call:
   ```bash
   MEMORY_CONTEXT=$(python3 "${REPO_ROOT}/dark-factory/scripts/memory_retrieve.py" \
       --phase refine --files "$AFFECTED" --issue "$ISSUE_NUM")
   ```
   Include `$MEMORY_CONTEXT` in the agent context (analogous to current pattern).

2. **Plan gate** (`dark-factory-plan.md`): Remove the `load_memory()` function and its
   three call steps, AND remove the `_filter_memory()` helper block that builds
   `$MEMORY_CONTEXT` for the architect subagent. Replace both with a single call whose
   output is reused for both the planning agent and the architect subagent prompt:
   ```bash
   MEMORY_CONTEXT=$(python3 "${REPO_ROOT}/dark-factory/scripts/memory_retrieve.py" \
       --phase plan --files "$AFFECTED" --issue "$ISSUE_NUM")
   ```
   The plan gate currently passes `$MEMORY_CONTEXT` to the architect subagent — this
   variable name is kept; only its source changes.

3. **Implement gate** (`dark-factory-implement.md`): Remove the `load_memory()` function
   and its call steps (steps 6–10 of Phase 1 LOAD). Replace with:
   ```bash
   MEMORY_CONTEXT=$(python3 "${REPO_ROOT}/dark-factory/scripts/memory_retrieve.py" \
       --phase implement --files "$AFFECTED" --issue "$ISSUE_NUM")
   ```

4. **Validate gate** (`dark-factory-validate.md`): Add a new memory load step to
   Phase 1 LOAD (currently only reads `implementation.md` and `CLAUDE.md`):
   ```bash
   CHANGED=$(git diff main...HEAD --name-only 2>/dev/null || echo "")
   MEMORY_CONTEXT=$(python3 "${REPO_ROOT}/dark-factory/scripts/memory_retrieve.py" \
       --phase validate --files "$CHANGED" --issue "$ISSUE_NUM")
   ```
   By design, `PHASE_SOURCE_MAP["validate"] == {"conformance"}` in `memory_retrieve.py`,
   so only conformance-tagged entries are returned. Implementation-phase reasoning is
   excluded automatically — no additional filtering is needed.

### Dry-run artifact (observability)

5. Each gate must write the retrieved memory block to a run artifact **before** using it.
   This makes the injected context visible without blocking:
   ```bash
   mkdir -p "$ARTIFACTS_DIR"
   printf '%s\n' "$MEMORY_CONTEXT" > "$ARTIFACTS_DIR/memory-context.md"
   ```
   Empty `$MEMORY_CONTEXT` → the file is created but empty; the gate continues normally.

### Write path (secondary)

6. The write path in the **implement** and **validate** gates already goes through
   `gate_lib.sh::write_memory_entry()`, which delegates to `memory_write.py` (merged in
   #648 / #679). No changes needed there.

7. The **refine gate** write path currently uses direct shell appends (`echo '...' >>
   .archon/memory/architecture.md`) with inline awk expiry cleanup, grep-based dedup, and
   a post-write verification backstop. Replace these with `memory_write.py` calls:
   ```bash
   python3 "${REPO_ROOT}/dark-factory/scripts/memory_write.py" \
       --target ".archon/memory/architecture.md" \
       --path-prefix ".archon/commands/" \
       --text "<lesson text>" \
       --source refine \
       --issue "$ISSUE_NUM"
   ```
   `memory_write.py` handles normalized dedup, the 30-entry cap, expiry cleanup, and
   index.jsonl stub writes. Remove the inline awk expiry block, grep dedup check, R4 cap
   warning, and post-write verification backstop from the refine gate command — they are
   superseded by the script.

### Tests

8. Create `dark-factory/tests/test_memory_integration.sh` — a bash smoke test that:
   - Calls `memory_retrieve.py --phase <role>` for each of refine, plan, implement, validate
   - Asserts exit code 0 for all four (passes even on an empty memory directory)
   - For the validate phase: asserts that any returned entries have `source:conformance`
     in their inline comment (or that the output is empty) — validates the source filter
   - Follows the existing pattern in `test_load_memory.sh` and `test_conformance_memory_write.sh`

## Files Changed

| File | Change |
|---|---|
| `.archon/commands/dark-factory-refine.md` | Remove `load_memory()` + 3 calls; add single `memory_retrieve.py` call; replace write-path bash block with `memory_write.py` calls; add `memory-context.md` artifact step |
| `.archon/commands/dark-factory-plan.md` | Remove `load_memory()` + 3 calls + `_filter_memory()` block; add single `memory_retrieve.py` call feeding `$MEMORY_CONTEXT`; add artifact step |
| `.archon/commands/dark-factory-implement.md` | Remove `load_memory()` + calls; add single `memory_retrieve.py` call; add artifact step |
| `.archon/commands/dark-factory-validate.md` | Add memory load step in Phase 1 LOAD; add artifact step |
| `dark-factory/tests/test_memory_integration.sh` | New — smoke tests for all 4 phases |
| `dark-factory/scripts/gate_lib.sh` | No changes needed — `write_memory_entry()` already delegates to `memory_write.py` |

## Approach

**Single call per gate** (chosen over per-file calls): `memory_retrieve.py` owns the
area-file routing internally via `select_area_files()` and `AREA_PREFIX_MAP`. Calling it
once with `--files "$AFFECTED"` produces the same filtered output that the old
`load_memory codebase-patterns.md; load_memory architecture.md; load_memory dark-factory-ops.md`
chain produced, without duplicating the routing logic in the command files.

The same `$MEMORY_CONTEXT` variable name is kept for backward compatibility with the plan
gate's architect subagent prompt block, which already splices `$MEMORY_CONTEXT` into the
subagent prompt.

## Alternatives Considered

**Per-file `memory_retrieve.py` calls** (rejected): Would keep the `load_memory X; load_memory Y`
structure but replace the bash function with script calls. This re-implements the
area-selection routing that `memory_retrieve.py` already owns and risks drifting from
`AREA_PREFIX_MAP`. Single call is simpler and the canonical interface.

**Keep `load_memory()` as fallback alongside `memory_retrieve.py`** (rejected): Creates two
code paths to maintain. The adapter's fallback path (scanning markdown directly when
`index.jsonl` is absent or empty) already handles the case where the index isn't built.

**No validate gate memory load** (rejected): The acceptance criteria explicitly requires it,
and `PHASE_SOURCE_MAP["validate"]` in `memory_retrieve.py` was built for this purpose. The
phase is otherwise a dead codepath.

## Assumptions

- `dark-factory/scripts/memory_retrieve.py` is accessible from `$REPO_ROOT` in the factory
  container at runtime (confirmed: `dark-factory/scripts/` is bind-mounted or baked in).
- `$ARTIFACTS_DIR` is set by the time Phase 1 LOAD runs in all gates (confirmed: it is
  set by the workflow harness before any gate command runs).
- Empty `$MEMORY_CONTEXT` is a valid no-op — all gates already handle the empty-context
  case (memory is advisory; no memory → agent uses CLAUDE.md + codebase only).
- The refine gate's architectural write entries (PATTERN+AVOID pairs to `architecture.md`)
  are straightforward enough for `memory_write.py` to handle without the elaborate
  multi-step shell protocol currently specified. The script's dedup and cap logic replaces
  the manual shell equivalent.

## Open Questions

- Should the plan gate's memory call use `--phase plan` (source filter: `refine`) or
  `--phase implement` to also see implement-phase lessons? Currently `PHASE_SOURCE_MAP["plan"]
  == {"refine"}` — plan agents see only refine-authored entries. This matches intent
  (plan builds on spec decisions, not runtime lessons), so no change is proposed.
- The `--issue` argument in `memory_retrieve.py` is listed as "informational" in the help.
  Future runs could use it to de-weight same-issue entries and avoid circular reasoning
  (issue #652 refine run including its own entries). Out of scope for this issue.
