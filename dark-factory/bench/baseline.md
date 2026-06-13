# Replay Benchmark — Baseline

**Committed**: 2026-06-12  
**Suite version**: 1  
**Run parameters**: n=3 runs/task, k=3, BENCH_MODE=stub  
**Status**: Stub baseline — pass^k tables show 0 (no runs executed yet).  
             Run `dark-factory/bench/run_suite.sh --baseline` to populate with real results.

---

## pass^k by Size Bucket

_Formula_: `pass^k = (c/n)^k` where c = runs with all oracle tests passing, n = 3, k = 3.  
_Interpretation_: 70% single-run success → only 34% chance of 3 clean runs.

| Size | Tasks | pass^k (n=3, k=3) |
|------|-------|-------------------|
| S    | 9     | — (not yet run)   |
| M    | 1     | — (not yet run)   |

---

## Task Manifest (10 tasks)

| Issue | Size | pre_pr_sha | Oracle test(s) |
|-------|------|-----------|----------------|
| [#224](https://github.com/omniscient/markethawk/issues/224) | S | `a662669` | `test_workflow_or_join.py` |
| [#332](https://github.com/omniscient/markethawk/issues/332) | S | `34d160c` | `test_smoke_gate.sh` |
| [#289](https://github.com/omniscient/markethawk/issues/289) | S | `26f0f35` | `test_health_ready.py` |
| [#299](https://github.com/omniscient/markethawk/issues/299) | M | `fe7bba4` | `test_trend_pullback_scan.py` |
| [#286](https://github.com/omniscient/markethawk/issues/286) | S | `8b4e37d` | `test_time_utils.py`, `test_db_utils.py` |
| [#276](https://github.com/omniscient/markethawk/issues/276) | S | `424a34d` | `test_fmt_hunk_filter.py` |
| [#287](https://github.com/omniscient/markethawk/issues/287) | S | `9634dea` | `test_stock_screener.py`, `test_futures_screener.py` |
| [#215](https://github.com/omniscient/markethawk/issues/215) | S | `b7664f0` | `test_scheduler.sh` |
| [#285](https://github.com/omniscient/markethawk/issues/285) | S | `69e5421` | `test_alerts.py`, `test_cache.py` |
| [#249](https://github.com/omniscient/markethawk/issues/249) | S | `e54e19a` | `indicators.test.ts` (jest) |

---

## Running the Suite

```bash
# Single command — runs n=3 per task, emits pass^k per size bucket
docker compose --profile factory run --rm dark-factory \
  bash /workspace/markethawk/dark-factory/bench/run_suite.sh

# With explicit parameters
BENCH_TOKEN_BUDGET=10.00 \
  docker compose --profile factory run --rm dark-factory \
  bash /workspace/markethawk/dark-factory/bench/run_suite.sh --n 3 --k 3

# Dry run — shows plan without executing
docker compose --profile factory run --rm dark-factory \
  bash /workspace/markethawk/dark-factory/bench/run_suite.sh --dry-run

# Subset of issues
docker compose --profile factory run --rm dark-factory \
  bash /workspace/markethawk/dark-factory/bench/run_suite.sh --issues 224,299

# Generate baseline.md prose summaries (runs Haiku judge, requires ANTHROPIC_API_KEY)
docker compose --profile factory run --rm dark-factory \
  bash /workspace/markethawk/dark-factory/bench/run_suite.sh --baseline
```

Results are written to `dark-factory/bench/results/YYYY-MM-DD-HH-run.json`. These files are gitignored — only this `baseline.md` is committed.

---

## BENCH_MODE

The suite runs with `BENCH_MODE=stub` by default:

| Node | Stub behavior |
|------|---------------|
| `preview-up` | Writes `preview_env.sh` with `PREVIEW_SKIPPED=true`, exits 0. No Docker stack. |
| `push-and-pr` | Exits 0 without pushing branch or creating a PR. |
| `classify-preview` | Runs unchanged (Haiku, ~$0.001/run). |
| `validate` (OR-join) | Runs unchanged — exercises `none_failed_min_one_success` trigger rule. |
| `conformance` | Runs unchanged. |
| `code-review` | Runs unchanged (reads `git diff main...HEAD`). |
| `status-in-review` (OR-join) | Runs unchanged. |
| `report` (OR-join) | Runs unchanged — posts to the real GitHub issue. |

Set `BENCH_MODE=full` to skip only `push-and-pr` (runs a real preview stack). Use this when changes specifically touch `preview-up` or preview infrastructure.

---

## Adding Tasks

1. Run `python3 dark-factory/bench/find_eligible.py --verify` to identify new candidates.
2. Manually verify the fail→pass transition is genuine (not a fixture-dependent fluke).
3. Add the task to `suite.json` and re-run the suite to establish its baseline.
4. Update this file with the new task and its pass^k.

---

## Token Cost

Budget is controlled via `BENCH_TOKEN_BUDGET` (default: `$5.00`). The runner logs a warning when the budget is exceeded. Per-task costs are recorded in the results JSON.

Rough cost estimate for the 10-task / n=3 suite:
- Each archon run: ~2,000 tokens in + ~15,000 tokens out ≈ $0.25–$0.40 per run
- 30 runs total: ~$7.50–$12.00 (use `BENCH_TOKEN_BUDGET=12.00` for a full run)
