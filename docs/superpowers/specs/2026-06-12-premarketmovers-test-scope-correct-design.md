# PreMarketMovers Test Scope-Correction — Design (issue #314)

**Date**: 2026-06-12
**Issue**: [#314](https://github.com/omniscient/markethawk/issues/314) — test(frontend): scope-correct PreMarketMovers tests (not in spec #250)

## Problem

`PreMarketMovers.test.tsx` was added out-of-scope during the coverage ratchet for issue #250. It was retained because removing it drops coverage below the CI thresholds, but it was never specced: it contains only 2 trivial smoke tests and includes a spurious `fetchStorageStats` mock that the component does not import. The test file exists for coverage accounting but provides no real behavioral signal.

## Requirements

1. **Remove the spurious mock** — `fetchStorageStats` is not imported by `PreMarketMovers.tsx`; it must not appear in the `vi.mock('../api/scanner', ...)` factory.
2. **Correct the mock response shape** — the existing mock omits the `status` field required by `PreMarketMoversResponse`; add `status: 'ok'` to match the TypeScript interface.
3. **Retain and fix existing smoke tests** — "renders without crashing" and "shows loading state initially" remain; verify they pass after the mock cleanup.
4. **Add error state test** — when `fetchPreMarketMovers` rejects, the component must render an error message and a Retry button.
5. **Add empty state after fetch test** — when the API returns `movers: []`, the component must render the "No movers found" empty-state row.
6. **Add ticker filter test** — when the user types a partial ticker into the search input, the table filters to matching rows only and hides non-matching ones.
7. **No component changes** — `PreMarketMovers.tsx` is out of scope; the React Query refactor is deferred to a separate issue.

Optional (implement if low-effort and stable, skip if they require timer mocking):
- Column sort: clicking a sortable header changes the sort key.
- MetricCard computed values: when movers are loaded, the top gainer/loser/volume MetricCard values derive correctly from the data.

## Approach

**Test-only fix against the existing useState+useEffect component.**

The component is functional and user-facing; its pattern violation (useState+useEffect instead of React Query) is real but does not block a test-quality fix. Scope stays narrow: the test file is changed, the source file is not.

Key implementation notes:
- Use `waitFor` from `@testing-library/react` for async assertions (error state, empty state after fetch, ticker filter — all require the initial fetch to complete or reject before asserting UI state).
- The ticker filter test must call `fireEvent.change` on the search `<input type="text">` and then assert rows — the component filters `filteredMovers` synchronously in the render on `filterTicker` state, so no extra async wait is needed after the input change.
- Error test: use `vi.fn().mockRejectedValueOnce(new Error('Network error'))` on `fetchPreMarketMovers`, then `waitFor` that the error text and Retry button appear.
- For tests that need populated data (filter, MetricCard), use two mover objects with distinct tickers, sectors, and numeric values.

## Alternatives Considered

**A: Minimal fix only** — Remove spurious mock, confirm existing 2 tests pass. No new tests.
- Rejected: leaves the file as thin smoke coverage. "Scope-correct" implies the test earns its place, not just avoids breaking things.

**B: Moderate fix (chosen)** — Fix mock + 3 new behavioral tests (error, empty, filter).
- The right balance for a `scope-spillover` / `direct-to-pr` ticket: adds genuine regression value without over-engineering a file that exists primarily for coverage accounting.

**C: Comprehensive** — Add all optional tests (sort, MetricCard, refresh timer).
- Sort and MetricCard tests are acceptable if low-effort; auto-refresh tests require `vi.useFakeTimers()` and carry flakiness risk, so they are explicitly excluded.

## Open Questions

None. The component API and test infrastructure are well-established.

## Assumptions

- `[ASSUMPTION]` Coverage thresholds in `frontend/vitest.config.ts` (statements 30, branches 27, functions 22, lines 30) hold after the mock cleanup; the test count stays the same or increases, so no regression is expected.
- `[ASSUMPTION]` `renderWithQuery` from `src/test-utils/renderWithQuery` wraps with React Query client and MemoryRouter, which is sufficient for `PreMarketMovers` (it uses no route params).
- `[ASSUMPTION]` `vi.mock('../api/scanner', ...)` must list every named export imported by the file under test; since `PreMarketMovers.tsx` only imports `fetchPreMarketMovers` and the `PreMarketMover` type, the mock factory needs only `fetchPreMarketMovers`.
