# ScorecardOverview — Test Scope Specification

**Date:** 2026-06-12
**Issue:** [#315](https://github.com/omniscient/markethawk/issues/315) — test(frontend): scope-correct ScorecardOverview tests (not in spec #250)
**Status:** Spec Generated

## Problem

`ScorecardOverview.test.tsx` was added out-of-scope during issue #250's frontend coverage ratchet. It was not on the priority list but was retained because excising it would drop coverage below the current threshold. This spec formally defines the intended test scope for the `ScorecardOverview` page component, enabling the tests to be implemented deliberately rather than as coverage padding.

## Requirements

1. **Heading renders** — The page title "SCANNER SCORECARD" is visible.
2. **Period selectors present** — All four period buttons (7D, 30D, 90D, ALL) are rendered.
3. **Empty state (no configs)** — When `useScannerConfigs` returns `data: []`, the "No scanner configurations found." message is shown.
4. **Empty state (all inactive)** — When all returned configs have `is_active: false`, the same empty-state message is shown; the `is_active` filter is exercised.
5. **Active-config filtering (exact count)** — Given a mix of active and inactive configs, only the active ones produce rendered `ScannerSummaryCard` instances (assert exact count, not just `> 0`).
6. **Loading state** — When `loadingConfigs=true`, two loading-skeleton `ScannerSummaryCard` instances are rendered (both with `isLoading=true`).
7. **Period → `useScorecard` params** — Clicking a period button passes the correct `{ start_date, end_date }` window to `useScorecard`. Use `vi.setSystemTime()` to fix the clock; assert `useScorecard` mock call args after clicking 7D.
8. **`periodToDates` unit tests** — Export `periodToDates` from `ScorecardOverview.tsx` and test all four branches with a fixed clock: `'all'` → `{}`, and `'7d'`/`'30d'`/`'90d'` → `{ start_date, end_date }` in `YYYY-MM-DD` format with the correct day offset.

### Optional (not required for acceptance)

- **Smoke test** — "renders without crashing" is redundant since every other test mounts the component. Keep for documentation value but it is not part of the behavioral surface.
- **Active period button styling** — asserting the Tailwind class `bg-financial-blue` is implementation-specific and brittle to class renames. Acceptable to keep as a CSS-level sanity check; it is not the primary way to verify period selection behavior.

## Architecture / Approach

### File changes

1. **`frontend/src/pages/ScorecardOverview.tsx`** — Export the `periodToDates` function so it can be unit-tested directly:
   ```ts
   export const periodToDates = (period: Period): { start_date?: string; end_date?: string } => { … }
   ```
   No behavioral change — the function body is unchanged.

2. **`frontend/src/pages/ScorecardOverview.test.tsx`** — Revise and extend the existing test file:

   **Mock fix (prerequisite for requirement 7):** The current `useScorecard` mock factory drops arguments:
   ```ts
   // BEFORE — args not forwarded
   useScorecard: () => mockUseScorecard(),
   // AFTER — args forwarded so call assertions work
   useScorecard: (...args) => mockUseScorecard(...args),
   ```

   **Test additions/revisions:**
   - Revise the "renders scanner summary cards when configs are present" test to include an inactive config and assert an exact count (e.g., 1 card for 1 active + 1 inactive input).
   - Add: "shows empty state when all configs are inactive" — pass two configs with `is_active: false`; assert the "No scanner configurations found." message.
   - Add: "passes 7D date window to useScorecard on period click" — set system time to a known date, render with one active config, click 7D, assert `mockUseScorecard.mock.calls` contain the expected `start_date`/`end_date`.
   - Add: a `describe('periodToDates', …)` block with one test per branch using `vi.setSystemTime()`.

### Test infrastructure

- `vi.setSystemTime()` is used in a `beforeEach`/`afterEach` pair with `vi.useFakeTimers()` for all date-sensitive tests. Existing non-date tests are unaffected.
- No new packages or configuration changes are required. `vi.setSystemTime` is available in the existing Vitest setup.

## Alternatives Considered

### A — Keep the CSS-class assertion as the behavioral period test
Asserting `bg-financial-blue` verifies UI state, not the data flow. It breaks on any cosmetic rename and does not confirm `useScorecard` receives the right dates. **Rejected as the primary behavioral test** (demoted to optional).

### B — Test period → dates through rendered content (ScannerSummaryCard props)
`ScannerSummaryCard` is already stubbed to render only `scannerName` — dates never surface in the rendered DOM. Asserting downstream DOM content for a date-window change has no anchoring surface. **Rejected**; collapses into approach C with extra indirection.

### C — Direct `useScorecard` call-arg assertion (chosen)
Forward mock args, use `vi.setSystemTime()`, assert call args on `mockUseScorecard`. This matches the pattern in `useScorecard.test.ts` (`vi.mocked(fetchScorecard)` call-arg assertions) and is the most direct proof that the period-to-dates pipeline is wired correctly. **Selected.**

## Open Questions

- None blocking.

## Assumptions

- [ASSUMPTION] `periodToDates` export does not require a re-export barrel update — the function is used only within this module and by its own tests.
- [ASSUMPTION] Coverage thresholds will remain satisfied after this test revision. If the exact-count refactor drops a branch, a follow-up coverage check is needed.
- [ASSUMPTION] The mock-arg-forwarding fix (`...args`) is backward-compatible with existing tests — existing tests pass `mockUseScorecard()` with no assertions on call args, so forwarding arguments to a `vi.fn()` that ignores them is a no-op for those tests.
