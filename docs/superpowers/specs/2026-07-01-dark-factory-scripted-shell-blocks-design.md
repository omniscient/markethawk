# Dark Factory — Extract Repeated Shell Blocks into Deterministic Scripts

**Date:** 2026-07-01
**Status:** Approved (design) — pending implementation plan
**Author:** Brainstormed with Claude (Sonnet 4.6 + Opus 4.8 product-owner)
**Issue:** #670
**Epic:** #663

## Problem

Three of the five dark-factory command files (`.archon/commands/dark-factory-refine.md`,
`dark-factory-plan.md`, `dark-factory-implement.md`) contain an identical ~16-line memory-load
shell block. Two of those commands also contain a near-identical ~20-line OOS excision block.
Duplicated inline shell code in markdown command files is fragile: a fix or behavioral change
must be applied in each copy, and the blocks are not unit-tested — they are only exercised
through full end-to-end factory runs.

## Goal

Extract the two most-duplicated shell blocks into standalone, tested scripts in
`dark-factory/scripts/` and update the command files to call these scripts instead of embedding
the full blocks. Behavior must be byte-for-byte equivalent to the original inline code.

## Non-Goals (v1)

- Extracting the expiry-cleanup `awk` block from `dark-factory-implement.md` (single copy;
  already scripted in `memory_write.py` / `memory_maintain.py`).
- Modifying `context_pack.py` or `context_budget.py` call sites — those are already standalone
  scripts; this ticket is "verify doc references" only.
- Changing any gate behavior, OOS guard semantics, memory guard invariants, epic guard, or
  conformance behavior.
- Adding new features to either extracted script.

## Candidate Blocks and Duplication Count

| Block | Command files | Line ranges |
|---|---|---|
| Memory-load | refine.md (39–55), plan.md (31–47), implement.md (31–47) | 3 copies, only `--phase` differs |
| OOS gate | refine.md (111–137), plan.md (158–192) | 2 copies, only `ALLOWED_PREFIXES` and commit noun differ |

## Requirements

1. **`load_memory_context.sh <phase>`** — a bash script in `dark-factory/scripts/` that encodes
   the memory-load block logic. Accepts phase as its sole positional argument
   (`refine`/`plan`/`implement`). Reads `$ARTIFACTS_DIR`, `$ISSUE_NUM`, and `$REPO_ROOT` from
   the environment (already exported by all calling commands). Outputs `$MEMORY_CONTEXT` to
   stdout and writes `$ARTIFACTS_DIR/memory-context.md` and
   `$ARTIFACTS_DIR/memory-trace.json` as side effects. Preserves the `2>/dev/null || true`
   fail-soft behavior of the original block.

2. **`oos_excise.sh <allowed-prefixes> <commit-noun>`** — a bash script in
   `dark-factory/scripts/` that encodes the OOS excision block. Accepts allowed-prefixes as a
   space-separated string (e.g. `"docs/superpowers/specs/ .archon/memory/"`) and a commit noun
   (e.g. `refine` or `plan`). Reads `$ARTIFACTS_DIR` and `$ISSUE_NUM` from the environment.
   Outputs the list of excised files (one per line) to stdout, so callers can capture
   `OOS_FILES=$(oos_excise.sh ...)` for use in Phase 6 comments. Writes entries to
   `$ARTIFACTS_DIR/out-of-scope.md` as a side effect. Preserves `--allow-empty` commit
   behavior.

3. **Pytest tests** — one pytest file per script (`test_load_memory_context.py`,
   `test_oos_excise.py`) in `dark-factory/tests/`. Tests invoke the bash scripts via
   `subprocess.run` in `tmp_path`-based git fixtures (following the subprocess pattern in
   `test_memory_retrieve.py`). At minimum, each test file must cover: correct output on the
   happy path, correct side-effect files written, graceful behavior when inputs are missing or
   the command fails. Tests must pass in the `factory-tests` CI job (`pytest
   dark-factory/tests/`).

4. **Command file updates** — replace the inlined blocks in all three commands with one-liner
   calls to the new scripts:
   - `dark-factory-refine.md`: replace memory-load block (lines 39–55) and OOS block
     (lines 111–137).
   - `dark-factory-plan.md`: replace memory-load block (lines 31–47) and OOS block
     (lines 158–192).
   - `dark-factory-implement.md`: replace memory-load block (lines 31–47) only (no OOS block
     in implement).

5. **No behavioral regression** — the OOS guard, append-only memory guard, epic guard, and
   conformance behavior must remain identical. A dedicated behavior-parity test must assert
   that `oos_excise.sh` produces the same set of excised files and commit message as the
   original inline block for a given input set.

## Architecture / Approach

### Chosen Approach — standalone bash scripts + pytest subprocess wrappers

Both scripts are bash scripts in `dark-factory/scripts/`, invoked with `bash
"${REPO_ROOT}/dark-factory/scripts/<script>.sh"` from the command files. Using bash (not Python)
is appropriate because the blocks are pure shell orchestration around git and
`memory_retrieve.py` — no new logic is needed, and rewriting to Python would add subprocess
overhead for no benefit. Standalone scripts (not functions in `gate_lib.sh`) follow the
precedent of `check_preview_creds.sh` and `eval_agentmemory.sh` and avoid violating the
`gate_lib.sh` contract comment ("only the three shared primitives").

Tests are written as pytest files (not bash-only) to ensure they run in the `factory-tests` CI
job. Each test uses `tmp_path` to create a minimal git repo with fixture files, sets the
required env vars (`ARTIFACTS_DIR`, `ISSUE_NUM`, `REPO_ROOT`), calls the script via
`subprocess.run`, and asserts on exit code, stdout, and written files.

### Script call-site patterns in command files

**Memory-load block replacement (refine, plan, implement):**
```bash
MEMORY_CONTEXT=$(bash "${REPO_ROOT}/dark-factory/scripts/load_memory_context.sh" refine)
```
The script writes the trace file and `memory-context.md`; the calling command captures the
context string and continues exactly as before.

**OOS gate replacement (refine, plan):**
```bash
OOS_FILES=$(bash "${REPO_ROOT}/dark-factory/scripts/oos_excise.sh" \
  "docs/superpowers/specs/ .archon/memory/" refine)
```
The script writes entries to `$ARTIFACTS_DIR/out-of-scope.md`, creates the excision commit if
needed, and prints excised filenames to stdout. `$OOS_FILES` is available for Phase 6 comments.

## Alternatives Considered

### Option B — Extract memory-load only (narrower scope)

Satisfy the "at least one" acceptance criterion with only `load_memory_context.sh`. Lower risk,
but leaves the OOS gate — the next most-duplicated block — as inline copy-paste. Rejected:
the M-size budget accommodates both extractions, and the OOS gate is a higher-risk block
(guards against spec-scope drift) that deserves the same testability as the memory-load block.

### Option C — Rewrite extracted blocks as Python scripts

More testable in isolation (no subprocess needed), but the blocks are pure shell orchestration.
Wrapping git commands in Python subprocess calls adds verbosity and complexity compared to a
thin bash wrapper. The existing test-over-subprocess pattern (`test_memory_retrieve.py`,
`test_dedupe_oos.py`) already handles bash scripts through pytest. Rejected in favor of bash.

### Option D — Add functions to `gate_lib.sh`

`gate_lib.sh` explicitly restricts itself to three primitives (`route_memory_file`,
`write_memory_entry`, `emit_verdict`) and is only sourced by conformance and code-review.
Memory-load and OOS blocks live in commands that do not source `gate_lib.sh`. Adding to it
would violate the contract comment and couple unrelated commands to a gate-centric library.
Rejected.

## Implementation Plan (sketch for the implement agent)

1. Write `dark-factory/scripts/load_memory_context.sh` — paste the Phase 1 memory block from
   `dark-factory-implement.md` lines 31–47, parameterise `--phase` on `$1`, make executable
   (`chmod +x`).
2. Write `dark-factory/scripts/oos_excise.sh` — paste the OOS gate from
   `dark-factory-refine.md` lines 111–137, accept `$1=ALLOWED_PREFIXES` and `$2=COMMIT_NOUN`,
   print excised files to stdout. Make executable.
3. Write `dark-factory/tests/test_load_memory_context.py` — pytest with subprocess fixture.
4. Write `dark-factory/tests/test_oos_excise.py` — pytest with subprocess + git fixture.
5. Update `dark-factory-refine.md`, `dark-factory-plan.md`, `dark-factory-implement.md` with
   one-liner call-sites (see above).
6. Run `pytest dark-factory/tests/test_load_memory_context.py
   dark-factory/tests/test_oos_excise.py -v` — confirm pass.

## Open Questions (non-blocking)

- Should `load_memory_context.sh` also accept `--issue` and `--artifacts-dir` as explicit CLI
  flags (for testability) rather than reading env vars? The current plan uses env vars (matching
  the calling context), but explicit flags would simplify fixture setup in tests. Either is fine;
  the implement agent can choose based on the test friction observed when writing the fixtures.
- Should `oos_excise.sh` also support a `--dry-run` flag that prints the would-be excised files
  without committing, to aid testing? Optional ergonomic addition; not required for v1.

## Assumptions

- `$ARTIFACTS_DIR`, `$ISSUE_NUM`, and `$REPO_ROOT` are already set in the calling command
  context (all three are used throughout the existing commands, confirmed by reading the files).
- The `factory-tests` CI job (`pytest dark-factory/tests/`) will discover and run
  `test_load_memory_context.py` and `test_oos_excise.py` without any CI config change.
- `bash` is available in the command execution environment (it is, based on all existing
  `gate_lib.sh` and `agent_roles.sh` usage).
- The memory-load block in refine, plan, and implement is identical except for the `--phase`
  argument — verified by the product-owner subagent against the actual file line ranges.
- The OOS gate in refine and plan is identical except for `ALLOWED_PREFIXES` and the commit
  noun — verified by the product-owner subagent against the actual file line ranges.
