# Dark Factory Memory Quality Report

Generated: 2026-06-30T00:00:00Z

## Scorecard

| Metric | Value |
|--------|-------|
| Total substantive regressions | 19 |
| Scorable (memory entry exists) | 7 |
| Hits (entry surfaced by retrieval) | 7 |
| Recall | 100.0% (PASS) |
| Corpus gap (no memory entry) | 12 (63.2%) |
| Pass threshold | 50% |
| Filtered (session-limit infra noise) | 133 |

## Per-Case Results

| Issue | Title | Has Memory Entry | Hit |
|-------|-------|-----------------|-----|
| #360 | test-infra: add postgres discovery fallback when testcontain | YES | YES |
| #386 | ops: weekly restore drill — verify #90 backups by restoring  | NO | - |
| #387 | data-quality: gap/staleness detection on aggregates + corpor | NO | - |
| #391 | observability: pre-market scan latency SLO — metrics + misse | YES | YES |
| #392 | scanner: nightly replay-diff — re-run yesterday's scans and  | YES | YES |
| #394 | Revisit dispatch ceiling (C9) - re-measure success-by-size/t | NO | - |
| #403 | ci: lint .archon/workflows when: expressions against Archon  | YES | YES |
| #421 | Update dark-factory-ops.md scope enforcement entry to reflec | YES | YES |
| #494 | Apply advisory data quality gate to scanner runs | YES | YES |
| #495 | Show data quality trust status in scanner and quality UI | YES | YES |
| #496 | Apply strict data quality gate to automated trading | NO | - |
| #498 | Generate missing bars and insufficient lookback gate issues | NO | - |
| #499 | Generate stale quote and provider gap gate issues | NO | - |
| #517 | docs(memory): dark-factory-ops.md BuildKit/preview patterns  | NO | - |
| #518 | cleanup(dark-factory): orphaned seed files in dark-factory/s | NO | - |
| #521 | cleanup(dark-factory): factory-failures.jsonl accumulates OO | NO | - |
| #570 | feat(notifications): generic system-notification path (email | NO | - |
| #646 | Build read-through memory retrieval adapter for Dark Factory | NO | - |
| #648 | Build write-through memory adapter for agentmemory and .arch | NO | - |
