# AlertBadge Tests — Scope Correction Design (issue #313)

**Date**: 2026-06-12
**Issue**: [#313](https://github.com/omniscient/markethawk/issues/313) — test(frontend): scope-correct AlertBadges tests (not in spec #250)

## Problem

During the #250 coverage ratchet, `AlertBadges.test.tsx` was written and committed as an out-of-scope (OOS) addition — the file was not on the spec's priority list. The conformance gate retained it rather than reverting it because excision would have broken the newly-established coverage thresholds. This issue exists to formally scope that work and declare the test file legitimate.

## Component being tested

`frontend/src/pages/ActiveWatchlist/AlertBadges.tsx` — a 21-line presentational component that renders a colored `<span>` badge for a `LiveAlert`. It has exactly four decision branches:

| Branch | Condition | Result |
|---|---|---|
| No alert | `!alert` | return null |
| Stale alert | `age > 3_600_000` ms (1 hour) | return null |
| Label | `scanner_type === 'live_volume_spike'` | "VOL" / "MOVE" |
| Color | `severity === 'high'/'medium'/other` | red / yellow / gray Tailwind classes |

## Requirements

1. `AlertBadges.test.tsx` is the sole deliverable — no other files are created or modified.
2. The file contains exactly 7 test cases covering all four branches above.
3. No new test cases are required: all branches are already exercised.
4. Severity-state color assertions use `className.toContain(...)`, conforming to the established repo pattern used in `IntervalTable.test.tsx`, `HeroMetrics.test.tsx`, and `OrdersPanel.test.tsx`.
5. The production component (`AlertBadges.tsx`) is not modified — the scope is tests only.

## Test case inventory

| # | Description | Branch covered |
|---|---|---|
| 1 | `renders null when alert is null` | `!alert` |
| 2 | `renders null when alert is older than 1 hour` | `age > 3_600_000` |
| 3 | `shows "VOL" badge for live_volume_spike scanner type` | label — VOL arm |
| 4 | `shows "MOVE" badge for other scanner types` | label — MOVE arm |
| 5 | `applies red color classes for high severity` | color — high |
| 6 | `applies yellow color classes for medium severity` | color — medium |
| 7 | `applies gray color classes for low severity` | color — low (fallthrough) |

## Approach

**Validate-and-retain**: Accept the existing 7 test cases as correct and complete. No additions, no rewrites. The spec documents the legitimacy of the already-present file within scope governance.

## Alternatives considered

**Audit-and-complete** — Audit the component for uncovered branches and add test cases. Rejected: the branch inventory above shows every decision point is covered. Adding tests (e.g., `title` attribute assertion, boundary test at exactly 3,600,000 ms) would be gold-plating, and this ticket is a bookkeeping issue, not a coverage-expansion issue.

**Rewrite to data-testid assertions** — Replace `className.toContain(...)` with `data-testid` lookups for robustness. Rejected: (a) it would require editing `AlertBadges.tsx` which is out of scope, (b) className assertions are the established repo convention for severity/state color, and (c) the component is a pure presentational span whose primary job is distinct visual severity — the class assertions verify the correct behavior.

**Excise and file stub** — Revert `AlertBadges.test.tsx` and leave coverage to recover naturally. Rejected by the conformance gate at PR #250 merge: excision breaks coverage thresholds.

## Assumptions

- The coverage threshold in `frontend/vitest.config.ts` was set with `AlertBadges.test.tsx` contributing to the measurement; removing the file would push statements/lines below the gated threshold.
- `AlertBadges.tsx` itself is stable and not under active change; no test updates are needed due to component drift.

## Open questions

None — the deliverable is fully defined by the existing file.
