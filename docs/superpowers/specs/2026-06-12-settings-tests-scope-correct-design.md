# Settings Tests — Scope Correction Design (issue #316)

**Date**: 2026-06-12
**Issue**: [#316](https://github.com/omniscient/markethawk/issues/316) — test(frontend): scope-correct Settings tests (not in spec #250)

## Problem

`Settings.test.tsx` was added out-of-scope during the issue #250 coverage ratchet ("stop once actuals clear ~32%/24%"). It was retained because excising it would drop coverage below the gate. This ticket legitimizes the retained file and corrects a defect in it: the `fetchStorageStats` mock returns `{ total_rows, db_size_mb }` which does not match the actual `StorageStats` interface, making the existing tests pass while silently hiding the display path.

## Requirements

1. Fix the `fetchStorageStats` mock to match `StorageStats`: `{ scanner: { bytes, formatted }, historical: { bytes, formatted }, settings: { bytes, formatted }, total: { bytes, formatted } }`.
2. Add one async display assertion that makes the mock-shape fix load-bearing — assert that a `total.formatted` value from the corrected mock renders on screen after the `useEffect` resolves.
3. Keep the 5 existing test cases intact; do not add sync-button behavior tests (scope boundary).
4. Coverage thresholds in `vitest.config.ts` must not regress (statements: 30, branches: 27, functions: 22, lines: 30).

## Approach

**Fix mock shape + add one `findByText` assertion.**

The `fetchStorageStats` mock is corrected to:

```ts
fetchStorageStats: vi.fn().mockResolvedValue({
  scanner:    { bytes: 1024,  formatted: '1.0 KB'  },
  historical: { bytes: 2048,  formatted: '2.0 KB'  },
  settings:   { bytes: 512,   formatted: '512 B'   },
  total:      { bytes: 3584,  formatted: '3.5 KB'  },
}),
```

A new test asserts the async-rendered total:

```ts
it('shows storage stats from fetchStorageStats', async () => {
  renderWithQuery(<Settings />);
  expect(await screen.findByText('3.5 KB')).toBeInTheDocument();
});
```

`findByText` is the codebase-standard pattern for async rendering (matches `Dashboard.test.tsx:34`). No `act()` wrapping is needed or used anywhere in this project.

The `stopSync` mock is also corrected to return `{ message: 'Sync stopped' }` (matching `TaskEnqueueResponse`) to prevent future confusion, though the existing tests do not exercise that path.

## Alternatives Considered

**Fix mock only, no new assertion** — a corrected mock with no assertion exercising it is dead code. The existing "renders without crashing" test still passes whether the mock is correct or wrong because the storage display falls back to `'0.0 B'` when stats are null. Rejected: the fix would not be verifiable.

**Fix mock + add all 4 storage-label assertions** — asserting scanner, historical, settings, and total individually is thorough but excessive for a scope-correction ticket. One total assertion exercises the render path. Rejected: disproportionate scope for a scope-spillover cleanup.

**Add sync-button behavior tests** — re-commits the scope-expansion the ticket exists to remediate. Rejected.

## Scope Boundary

The following are explicitly out of scope:
- Behavior tests for Sync Fundamentals, Sync Ticker Details, Update Metrics, Stop buttons
- NewsSettings tab content beyond the existing tab-switch smoke test
- API Speed selector mutation assertion

## Assumptions

- `[ASSUMPTION]` The corrected `fetchStorageStats` mock keeps per-file coverage stable or improves it (the `useEffect` storage-display branch is now exercised by the async assertion).
- `[ASSUMPTION]` No other test file mocks `fetchStorageStats` with the wrong shape; the fix is isolated to `Settings.test.tsx`.

## Acceptance Criteria

1. `fetchStorageStats` mock matches `StorageStats` interface.
2. `npx vitest run --coverage` passes all four thresholds (30/27/22/30).
3. `npx tsc --noEmit` passes.
4. All 6 tests (5 existing + 1 new) pass.
