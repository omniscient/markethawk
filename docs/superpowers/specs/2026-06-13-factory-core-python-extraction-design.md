# Factory Core Python Extraction

**Date:** 2026-06-13
**Issue:** #337
**Status:** Spec

---

## Problem

Board updates, retry/circuit-breaker logic, and the three-tier de-conflict strategy live as
duplicated, untestable bash across three files:

| File | Scope | Line count |
|------|-------|-----------|
| `dark-factory/entrypoint.sh` | `find_board_item`, `set_board_status`, `_conflict_tier1/2/3`, `_resolve_merge_conflicts`, `post_or_update_comment` | ~808 total; ~220 lines of duplicated/complex logic |
| `dark-factory/scheduler.sh` | `set_board_status`, `trip_to_blocked`, `get/increment/reset_retry` | ~1102 total; ~100 lines of duplicated/complex logic |
| `.archon/workflows/archon-dark-factory.yaml` (`de-conflict` node) | Tier 1/2/3 inline bash, ~200 lines | ~200 lines of de-conflict logic |

`find_board_item()` / `set_board_status()` are defined twice with different signatures. Board
constants (`PROJECT_ID`, `STATUS_FIELD`, status option IDs) are duplicated verbatim. No unit
tests exist for any of these functions, so bugs (the trigger_rule regression, the conformance
double-revert, the #207 Tier 2 prose-corruption) are caught in production runs only.

---

## Requirements

1. A Python package `dark-factory/scripts/factory_core/` containing board ops, breaker state,
   de-conflict tiers 1–3, and run-record emission. Shared helpers exist exactly once.
2. A single argparse CLI entry point (`cli.py`) callable from shell as
   `python3 "$CLONE_DIR/dark-factory/scripts/factory_core/cli.py" <subcommand>`.
3. De-conflict tiers covered by pytest unit tests, including the Tier 1 per-file allowlist,
   Tier 2 sentinel parsing, and the Tier 3 hard-grep escalation path (both positive case and
   the `.git`/`node_modules` exclusion rules).
4. `entrypoint.sh` and `scheduler.sh` become thin adapters: all duplicated functions replaced
   by `python3 .../factory_core/cli.py <subcommand>` calls. Line counts drop substantially.
5. The DAG `de-conflict` node body replaced by a thin `python3 factory_core/cli.py deconflict`
   call (same as entrypoint.sh Tier 3 escalation path).
6. Board constants (`PROJECT_ID`, `STATUS_FIELD`, status option IDs) unified in
   `factory_core/board.py`; no longer duplicated between entrypoint and scheduler.
7. `run_record.py` moved into the package as `factory_core/run_record.py`;
   `test_run_record.py` import path updated accordingly.
8. A new `factory-tests` CI job in `.github/workflows/ci.yml` runs `pytest dark-factory/tests/`
   (currently no CI job covers dark-factory Python tests).
9. No behavior change for the board-status machine, retry state, or the
   `conflict_resolution.md` artifact format consumed by `report` DAG node and `run_record.py`.

---

## Architecture / Approach

### Package structure

```
dark-factory/scripts/factory_core/
  __init__.py            # re-exports top-level symbols for import convenience
  board.py               # find_board_item, set_board_status, post_or_update_comment
                         # + all board/project constants (PROJECT_ID, STATUS_FIELD, STATUS_*)
  deconflict.py          # tier1(), tier2(), hard_grep_survivors(), resolve_merge_conflicts()
  breaker.py             # get_retry_count, increment_retry, reset_retry, trip_to_blocked
  run_record.py          # moved from dark-factory/scripts/run_record.py (unchanged logic)
  cli.py                 # argparse entry point; delegates to board/deconflict/breaker/run_record
```

The existing `dark-factory/scripts/run_record.py` is moved (not copied) into the package;
`dark-factory/tests/test_run_record.py` updates its `sys.path.insert` / import line to
`from factory_core import run_record as rr`. No other caller changes needed — `entrypoint.sh`
already calls it as `python3 "$CLONE_DIR/dark-factory/scripts/run_record.py"`, which becomes
`python3 "$CLONE_DIR/dark-factory/scripts/factory_core/run_record.py"` (or via `cli.py`
`run-record` subcommand).

### CLI subcommands

```
factory-core board-move   --issue <N> --status <option_id>
factory-core deconflict   --issue <N> [--repo <owner/repo>] [--no-ai-tier]
factory-core breaker-get  --key <key>
factory-core breaker-incr --key <key>
factory-core breaker-reset --key <key>
factory-core breaker-trip  --issue <N> --phase <implement|refine|plan|resolve> --reason <str>
factory-core run-record record  <existing args>   # passthrough to run_record.cmd_record
factory-core run-record assemble <existing args>  # passthrough to run_record.cmd_assemble
```

Shell adapters in `entrypoint.sh`:

```bash
# Replaces the inline _resolve_merge_conflicts() body
_resolve_merge_conflicts() {
  python3 "$CLONE_DIR/dark-factory/scripts/factory_core/cli.py" \
    deconflict --issue "$ISSUE_NUM" || return $?
}
```

Shell adapters in `scheduler.sh`:

```bash
set_board_status() {
  local issue_num="$1" option_id="$2"
  python3 "$CLONE_DIR/dark-factory/scripts/factory_core/cli.py" \
    board-move --issue "$issue_num" --status "$option_id" || true
}
trip_to_blocked() {
  python3 "$CLONE_DIR/dark-factory/scripts/factory_core/cli.py" \
    breaker-trip --issue "$1" --phase "$2" --reason "$3" || true
}
get_retry_count() {
  python3 "$CLONE_DIR/dark-factory/scripts/factory_core/cli.py" \
    breaker-get --key "$1"
}
increment_retry() {
  python3 "$CLONE_DIR/dark-factory/scripts/factory_core/cli.py" \
    breaker-incr --key "$1"
}
reset_retry() {
  python3 "$CLONE_DIR/dark-factory/scripts/factory_core/cli.py" \
    breaker-reset --key "$1"
}
```

DAG `de-conflict` node body (`.archon/workflows/archon-dark-factory.yaml`):

```bash
# Replaces the ~200-line inline bash with a single Python call.
# The Python module writes $ARTIFACTS_DIR/conflict_resolution.md in the same
# key=value format the `report` node already reads.
ISSUE=$(jq -r '.resolved_number' "$ARTIFACTS_DIR/issue.json")
python3 "$CLONE_DIR/dark-factory/scripts/factory_core/cli.py" \
  deconflict --issue "$ISSUE"
```

Note: `$CLONE_DIR` is available in the DAG node via `entrypoint.sh`'s env export. The DAG
node runs after `entrypoint.sh` sets `CLONE_DIR="/workspace/markethawk"`.

### Tier 2 sentinel contract

`entrypoint.sh`'s Tier 2 uses `===BEGIN_RESOLVED_FILE===` / `===END_RESOLVED_FILE===`
sentinels and discards Claude's preamble prose before writing the file. The DAG node's Tier 2
writes raw stdout. The Python implementation adopts the sentinel approach (same as
entrypoint.sh), fixing the DAG behavior. This is a safe behavior change: without sentinels, any
Claude preamble prose is silently written into the source file — the #207 incident traced to
exactly this class of bug.

### Test strategy

All new tests land in `dark-factory/tests/test_factory_core_*.py`:

| Test file | Coverage | Method |
|-----------|----------|--------|
| `test_factory_core_board.py` | `find_board_item`, `set_board_status`, `post_or_update_comment` | Mock `subprocess.run` (gh CLI calls); assert command args |
| `test_factory_core_deconflict.py` | Tier 1 (per-file allowlist), Tier 2 (sentinel parsing), Tier 3 (hard-grep + exclusions), orchestrator | Tier 1/3: real `tmp_path` git repos with actual conflict markers. Tier 2: `subprocess.run` mock returning sentinel-wrapped content; separate tests for malformed/no-sentinel response (escalate path) |
| `test_factory_core_breaker.py` | get/increment/reset/trip cycle, state file JSON format | Real `tmp_path` state files; mock gh/board calls |
| `test_run_record.py` | Existing suite | Update import: `from factory_core import run_record as rr` |

Tier 1 test fixture: `git init` → commit two divergent histories on a branch → `git merge --no-commit` to force conflict → call `tier1(filepath)` → assert file content + `git status`.

Tier 3 hard-grep test: create `tmp_path/foo.py` containing `<<<<<<< HEAD` → assert `hard_grep_survivors()` returns `["foo.py"]`; create `tmp_path/node_modules/bar.py` with same marker → assert not returned (excluded).

### CI job

Add to `.github/workflows/ci.yml` (no DB required; lightweight):

```yaml
factory-tests:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with:
        python-version: "3.12"
    - name: Install test deps
      run: pip install pytest pytest-mock
    - name: Run factory tests
      run: python -m pytest dark-factory/tests/ -v
      env:
        PYTHONPATH: dark-factory/scripts
```

`PYTHONPATH: dark-factory/scripts` makes `import factory_core` resolve without a pip install,
matching how `test_run_record.py` currently does `sys.path.insert(0, '.../scripts')`. The
existing `sys.path.insert` calls in test files are kept for local `python test_xxx.py` runs;
the CI env var takes precedence when running via `python -m pytest`.

---

## Alternatives Considered

### A: Per-operation standalone scripts

`deconflict.py`, `board_ops.py`, `breaker.py` as sibling scripts under `dark-factory/scripts/`
(flat, no package). Simpler initial structure but: no natural home for shared constants; cross-
module imports require sys.path manipulation; the fragmentation problem re-emerges as scripts
multiply. Rejected: the package pattern is well-established (the test files already do
`sys.path.insert(0, 'dark-factory/scripts')`).

### B: Leave the DAG `de-conflict` node as-is

Extract from entrypoint.sh / scheduler.sh only; leave the DAG node's ~200 lines of inline
bash. Reduces blast radius at the cost of keeping two de-conflict implementations (entrypoint.sh
adapter vs DAG node). The issue's acceptance criterion "delete any one file scatters complexity
to others" specifically names DAG yaml as one of the three files. The issue explicitly says "DAG
stages become thin adapters." Rejected per issue intent.

### C: Pip-install `factory_core` into the Docker image

Allows `python -m factory_core` without PYTHONPATH gymnastics. But any Python logic change
requires `docker compose build` (the baked-image constraint). The established pattern
(`run_record.py`, `code_review_payload.py`) is clone-side invocation — `python3 "$CLONE_DIR/..."`
— so changes ride the clone without a rebuild. Rejected: maintains the clone-side pattern.

---

## Open Questions (non-blocking)

1. **`classify_comments()` in scheduler.sh** — also untestable (calls `claude -p --model haiku`),
   but not listed in the issue's four areas and defined only once (not duplicated). Natural v2
   target once `factory_core` is established.
2. **`post_cost_report()` in entrypoint.sh** — a heavy jq+bash cost-report builder consuming the
   run-record JSON. A strong candidate for factory_core v2 given the "line counts drop" criterion,
   but out of scope for v1.
3. **Breaker state file path** — currently `$STATE_FILE` env var (scheduler.sh:9). The Python
   breaker must read the same path. Default should match scheduler.sh's
   `SCHEDULER_STATE_DIR=/var/lib/dark-factory`. Factory-scoped (implement) runs use bare issue
   keys; pipeline phases (refine/plan/resolve) use `issue:phase` keys — this contract must be
   preserved exactly.

---

## Assumptions

1. `CLONE_DIR` is exported in `entrypoint.sh` before the archon workflow starts (line 4-6 of
   entrypoint.sh sets it), so DAG node bash bodies can reference it.
2. The Tier 2 sentinel behavior change (DAG node now uses sentinels like entrypoint.sh) is
   acceptable — it is a safety improvement, not a regression.
3. The board constants in entrypoint.sh and scheduler.sh are identical (cross-verified during
   spec: `PROJECT_ID=PVT_kwHOAAFds84BWh4w`, `STATUS_FIELD=PVTSSF_lAHOAAFds84BWh4wzhR1VaA`,
   status IDs match across both files).
4. Tests that require real git operations (`git init`, `git merge`) assume git is available in
   the CI runner (ubuntu-latest; git is pre-installed).

---

## Implementation Checklist

- [ ] Create `dark-factory/scripts/factory_core/__init__.py`
- [ ] Create `dark-factory/scripts/factory_core/board.py` — constants + `find_board_item`, `set_board_status`, `post_or_update_comment`
- [ ] Create `dark-factory/scripts/factory_core/deconflict.py` — `tier1`, `tier2` (sentinel contract), `hard_grep_survivors`, `resolve_merge_conflicts`
- [ ] Create `dark-factory/scripts/factory_core/breaker.py` — retry state + `trip_to_blocked`
- [ ] Move `dark-factory/scripts/run_record.py` → `dark-factory/scripts/factory_core/run_record.py`
- [ ] Create `dark-factory/scripts/factory_core/cli.py` — argparse dispatch for all subcommands
- [ ] Update `dark-factory/tests/test_run_record.py` import path
- [ ] Create `dark-factory/tests/test_factory_core_board.py`
- [ ] Create `dark-factory/tests/test_factory_core_deconflict.py` (Tier 1/2/3 + orchestrator)
- [ ] Create `dark-factory/tests/test_factory_core_breaker.py`
- [ ] Replace duplicated functions in `entrypoint.sh` with thin adapter calls
- [ ] Replace duplicated functions in `scheduler.sh` with thin adapter calls
- [ ] Replace DAG `de-conflict` node body with `python3 factory_core/cli.py deconflict`
- [ ] Add `factory-tests` job to `.github/workflows/ci.yml`

---

*Spec generated by MarketHawk Refinement Pipeline — 2026-06-13*
