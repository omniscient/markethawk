# Replay Benchmark: pass^k Suite — Design (issue #335)

**Date**: 2026-06-12
**Issue**: [#335](https://github.com/omniscient/markethawk/issues/335) — Replay benchmark: pass^k suite of replayed closed issues to regression-test the harness

## Problem

Every change to the factory DAG, a command prompt, or a gate threshold ships unmeasured. The OR-join `trigger_rule` self-regression (ce9e4a3) proved the harness can silently break itself; there is no fixed suite to catch the next one. Pass^k also quantifies the honest unattended-reliability ceiling (70% single-run success → only 34% chance of 3 clean runs).

## Solution Overview

A replay benchmark suite in `dark-factory/bench/` — fixed tasks sourced from closed issues, the harness is the variable:

```
dark-factory/bench/
  find_eligible.py           # eligibility detection: diff pre-filter + pytest verification
  run_suite.sh               # suite runner: n=3 replays per task, emits pass^k per size bucket
  suite.json                 # committed manifest: pinned pre-PR commits + oracle test IDs
  baseline.md                # committed baseline run documentation (prose + tables)
  results/                   # per-run JSON output (gitignored except baseline)
    YYYY-MM-DD-HH-run.json
```

The suite runner invokes the factory's Archon workflow directly (`archon workflow run archon-dark-factory "Fix issue #N"`) with `BENCH_MODE=stub` set. This exercises the DAG's gate/OR-join logic — the class of regression the benchmark exists to catch — without spinning up preview Docker stacks or creating real GitHub PRs.

## Requirements (from Q&A)

1. **Eligibility script** (`find_eligible.py`) identifies replayable issues from closed-PR history using executable fail→pass verification, not a diff heuristic alone.
2. **Suite manifest** (`suite.json`) pins each task to its pre-PR commit SHA and the specific oracle test IDs that confirm eligibility.
3. **Suite runner** (`run_suite.sh`) dispatches n=3 Archon runs per task, collects test results, computes `pass^k = (c/n)^k` per size bucket, writes per-run JSON, and emits a summary table to stdout.
4. **Scoring** is two-track: (a) deterministic test passage (0/1) for all runs — the regression gate; (b) Haiku prose summary per task added to the committed `baseline.md` once, not on every run.
5. **Token budget** is an explicit input to `run_suite.sh` (env var `BENCH_TOKEN_BUDGET`); the runner logs cost per task and warns when approaching the budget.
6. **Trigger** is manual — the `CONTRIBUTING.md`/harness change workflow references "run the bench suite before merging changes to factory prompts/DAG/gates."

## Acceptance Criteria Mapping

| Criterion | Implementation |
|-----------|---------------|
| Eligibility script identifies replayable issues | `find_eligible.py` — diff pre-filter + `pytest` fail→pass at pre/post commit |
| 10+ task suite with pinned pre-PR commits | `suite.json` manifest, committed |
| One command runs the suite, emits pass^k per size bucket | `dark-factory/bench/run_suite.sh` |
| Documented baseline run committed | `dark-factory/bench/baseline.md` |
| Factory-harness changes reference a suite run | CONTRIBUTING note added to harness PR template |

## Architecture

### 1. Eligibility Detection (`find_eligible.py`)

**Inputs**: GitHub repo history, closed issues with merged PRs.

**Algorithm**:

```
for each closed issue with a merged PR:
  1. Diff the golden PR to find added/modified test files
     (backend/tests/**, dark-factory/tests/**) — these are oracle candidates
  2. If no test files changed → not eligible (skip)
  3. Checkout pre-PR commit → run `pytest <oracle_candidates>` → record failures
  4. Checkout post-PR commit → run the same set → record passes
  5. Eligible iff ≥1 test transitions fail→pass
  6. If auto-verification fails (live Polygon/IBKR fixture required, build error) →
     emit as "needs-review candidate" for human review
```

Tests self-provision Postgres via testcontainers (`PostgresContainer("postgres:15-alpine")` in `backend/tests/conftest.py`) — no separately running DB is needed.

**Output**: a candidate list with verified oracle test IDs, pre-PR SHA, size label, and eligibility status. A human reviews and pins the final 10–20 tasks into `suite.json`.

**`suite.json` schema**:
```json
{
  "tasks": [
    {
      "issue": 156,
      "title": "...",
      "size": "S",
      "pre_pr_sha": "abc1234",
      "golden_pr": 158,
      "oracle_tests": ["backend/tests/tasks/test_scanning.py::test_run_logic"],
      "notes": ""
    }
  ]
}
```

### 2. Archon Workflow Modifications (`BENCH_MODE`)

Two nodes in `archon-dark-factory.yaml` are modified to check `BENCH_MODE`:

**`classify-preview`** — when `BENCH_MODE` is set, force `needs_preview=false` unconditionally (no LLM call needed; write canned output to the artifact file). This removes classify-preview's LLM cost and prevents it from varying run-to-run, stabilizing the pass^k signal.

**`preview-up`** — when `BENCH_MODE` is set, write the preview artifact file with `preview_active=false` and exit cleanly. No Docker compose invocation. The validate node reads this file and runs the pytest/tsc-only path (which already exists — this is the same path used by `preview-up-resolve` for the `resolve` intent).

**`push-and-pr`** — when `BENCH_MODE` is set, write the push artifact file with `pr_url=""`, `branch=<current>` and exit cleanly. No `gh pr create`. Code-review still runs against the local diff (same as today; code-review reads `git diff main...HEAD`, not the PR URL).

The gate nodes — `validate` (OR-join: `none_failed_min_one_success`), `conformance`, `code-review`, `status-in-review` (OR-join), and `report` (OR-join) — run **unchanged** in all BENCH_MODE paths. These are the nodes whose `trigger_rule` logic the benchmark is designed to exercise.

**`BENCH_MODE=full`** escape hatch: when set, the bench runner uses `BENCH_MODE=full` which skips only `push-and-pr` (no junk PRs) but runs a real preview stack. Reserved for changes that specifically touch `preview-up` or `push-and-pr` — not the default.

### 3. Suite Runner (`run_suite.sh`)

```bash
# Invocation
BENCH_MODE=stub \
BENCH_ISSUE_SHA=<pre_pr_sha> \
dark-factory/bench/run_suite.sh [--tasks suite.json] [--n 3] [--k 3]
```

**Per-task loop** (pseudocode):
```
for task in suite.json:
  git checkout <task.pre_pr_sha>              # pin to pre-PR state
  for run in 1..N:
    archon workflow run archon-dark-factory "Fix issue #${task.issue}"
    git checkout <result_branch>
    pytest <task.oracle_tests> → pass (1) or fail (0)
    log token cost from archon workflow cost --last --json
    record (task, run, passed, tokens)
  compute c = count of passed runs
  compute pass_k = (c/n)^k
  write to results/YYYY-MM-DD-run.json
emit pass^k table per size bucket to stdout
```

**`BENCH_ISSUE_SHA`**: ensures the Archon `branch-and-checkout` node starts from the pinned pre-PR commit rather than `main`, so the oracle tests actually fail before the factory applies the fix.

**Pass^k formula** — per the issue's cited reference:
```
pass^k(task) = (c/n)^k   where c = number of runs that pass all oracle tests
```
The report aggregates per `size` bucket (S/M/L) matching the `suite.json` `size` field.

### 4. Baseline Run Documentation (`baseline.md`)

The baseline run adds a per-task prose summary (run once, committed):

```
dark-factory/bench/run_suite.sh --baseline
```

When `--baseline` is set, after collecting test results the runner spawns a Haiku judge subagent (via the Anthropic Batches API for 50% cost reduction) per task:

- **Input**: golden PR diff + replay run diff
- **Output**: short prose (3-5 sentences) — correctness, completeness, notable divergences from the golden solution

The prose is appended to `baseline.md` and committed. It is documentation, not a blocking score, and not re-generated on subsequent regression runs.

### 5. Token Budget Tracking

Each run records token cost via `archon workflow cost --last --json`. The runner accumulates total cost and logs a warning when `BENCH_TOKEN_BUDGET` (default: `$5.00`) is exceeded. The per-run JSON includes token costs per task, enabling cost-per-size-bucket analysis.

## Alternatives Considered

### Alt 1: Full Docker-in-Docker pipeline (rejected)

Run each replay as `docker compose --profile factory run --rm dark-factory "Fix issue #N"` from the host, giving 100% entrypoint coverage. Rejected because: 30–60 container startups (n=3 × 10–20 tasks) each clone the repo and reinstall deps — pure cost with no additional harness coverage. The entrypoint/container path is not the subject of regression. Docker-in-Docker also requires socket mounting and is fragile in CI.

### Alt 2: Implement-only (lean) replay (rejected)

Skip the full Archon workflow — run only the `dark-factory-implement.md` command via `claude -p`. Cheaper (~50% of stub-gated cost), but structurally blind to the DAG's OR-join gate logic: the ce9e4a3 regression that motivated this issue lives entirely in the gate nodes (`none_failed_min_one_success` trigger rules). An implement-only run never executes those nodes.

### Alt 3: Diff-overlap quality grade (rejected)

Score quality as the fraction of golden-PR lines reproduced in the replay diff. Rejected because it penalizes semantically correct solutions that differ textually from the golden PR — exactly what METR's calibration note warns against. Replaced by the optional Haiku prose summary (baseline only).

### Alt 4: Integrate with pipeline-report (rejected)

Add a `fetch_bench.py` stage to `scripts/generate.sh`. Rejected because the bench is a developer/CI gate tool, not an observability dashboard, and coupling it to the report-render pipeline adds failure surfaces unrelated to its purpose. A lightweight static link from `pipeline-report.html` to `baseline.md` is fine, but the bench tooling stays self-contained.

## Open Questions (non-blocking)

1. **BENCH_ISSUE_SHA mechanism**: how exactly does `BENCH_ISSUE_SHA` override `branch-and-checkout`'s starting commit? The node currently branches from `origin/main`. The simplest approach is a new `when: "$env.BENCH_ISSUE_SHA != ''"` guard that substitutes the SHA; a cleaner alternative is a new `bench-checkout` node that precedes `branch-and-checkout` in the DAG. To be resolved during implementation.

2. **Frontend oracle tests**: some issues may only have TypeScript test oracles (`npx jest` or `npx tsc --noEmit`). The runner should support both `pytest` and `jest` oracle commands; `suite.json` should carry an `oracle_cmd` field.

3. **Parallelism**: n=3 runs per task are sequential in the current design to avoid Claude Max subscription limit collisions. A future opt-in flag (`--parallel`) could parallelize across tasks (not within a task) with `FACTORY_WIP_LIMIT` awareness.

## Assumptions

- `[A1]` The Archon workflow supports reading `BENCH_MODE` from env vars passed to `archon workflow run`. Verified by inspection of `.archon/workflows/archon-dark-factory.yaml` (nodes use bash `${ENV_VAR:-default}` expansion).
- `[A2]` The `preview-up-resolve` path (validate runs pytest/tsc only without a live stack) is a stable, tested path that the bench stub can reuse. Verified by inspection of the workflow's `validate` node.
- `[A3]` `archon workflow cost --last --json` returns valid JSON after each run. To be confirmed during implementation — fallback is parsing the cost report comment from the issue.
- `[A4]` The Anthropic Batches API is available in the dark-factory container's `ANTHROPIC_API_KEY` credentials. Fallback: run the Haiku judge inline (non-batch) for the baseline.
