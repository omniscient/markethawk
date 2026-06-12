# Settings Tests — Scope Correction Plan (issue #316)

**Date**: 2026-06-12
**Issue**: [#316](https://github.com/omniscient/markethawk/issues/316)
**Spec**: [docs/superpowers/specs/2026-06-12-settings-tests-scope-correct-design.md](../specs/2026-06-12-settings-tests-scope-correct-design.md)

## Goal

Correct the `fetchStorageStats` mock shape in `Settings.test.tsx` from the wrong flat shape (`{ total_rows, db_size_mb }`) to the real `StorageStats` interface (`{ scanner, historical, settings, total }` each with `{ bytes, formatted }`). Fix the `stopSync` mock to return `{ message: 'Sync stopped' }`. Add one async assertion that makes the fix load-bearing: `await screen.findByText('3.5 KB')`. Keep all 5 existing tests intact. No app-code changes.

## Architecture

Test-only change. `Settings.tsx` uses `fetchStorageStats` from `frontend/src/api/scanner.ts` (where `StorageStats` is also defined at line 166). The component sets storage state in a `useEffect`, then renders `storageStats?.total.formatted`. The test mocks the module at `../api/scanner`; correcting the mock shape + adding a `findByText` assertion exercises the async render path end-to-end.

## Tech Stack

- **Frontend test framework**: Vitest + React Testing Library
- **Key files**: `frontend/src/pages/Settings.test.tsx` (only file modified)
- **Async pattern**: `findByText` (codebase standard — see `Dashboard.test.tsx:34`)

## File Structure

| File | Change |
|------|--------|
| `frontend/src/pages/Settings.test.tsx` | Fix `fetchStorageStats` mock shape, fix `stopSync` mock, add async test |

---

## Task 1 — Fix mock shapes and add async storage-stats assertion

**Files**: `frontend/src/pages/Settings.test.tsx`

### TDD Steps

**Step 1: Verify the tests currently pass with the wrong mock (baseline)**

```bash
cd /workspace/markethawk/frontend
npx vitest run src/pages/Settings.test.tsx --reporter=verbose 2>&1 | tail -20
```

Expected: 5 tests pass. The "renders without crashing" passes because `storageStats?.total.formatted` falls back to `'0.0 B'` when the mock resolves with the wrong shape (the optional chain returns `undefined`).

**Step 2: Add a failing test that will only pass with the correct mock shape**

Add the `findByText` test to `Settings.test.tsx` _before_ fixing the mock, so we can confirm it fails with the old mock:

```diff
# In frontend/src/pages/Settings.test.tsx — add after the last existing it() block:

+  it('shows storage stats from fetchStorageStats', async () => {
+    renderWithQuery(<Settings />);
+    expect(await screen.findByText('3.5 KB')).toBeInTheDocument();
+  });
```

Run and confirm failure:
```bash
npx vitest run src/pages/Settings.test.tsx --reporter=verbose 2>&1 | tail -20
```
Expected: the new test fails (times out on `findByText('3.5 KB')`) because the mock returns `total_rows`/`db_size_mb`, so `storageStats?.total.formatted` is `undefined` and the component renders `'0.0 B'`.

**Step 3: Fix both mock shapes**

Replace the two incorrect mock return values. The full updated mock block at the top of `Settings.test.tsx`:

```ts
vi.mock('../api/scanner', () => ({
  syncFundamentals: vi.fn().mockResolvedValue({}),
  syncMetrics: vi.fn().mockResolvedValue({}),
  syncTickerDetails: vi.fn().mockResolvedValue({}),
  stopSync: vi.fn().mockResolvedValue({ message: 'Sync stopped' }),
  fetchStorageStats: vi.fn().mockResolvedValue({
    scanner:    { bytes: 1024,  formatted: '1.0 KB' },
    historical: { bytes: 2048,  formatted: '2.0 KB' },
    settings:   { bytes: 512,   formatted: '512 B'  },
    total:      { bytes: 3584,  formatted: '3.5 KB' },
  }),
}));
```

**Step 4: Verify all 6 tests pass**

```bash
npx vitest run src/pages/Settings.test.tsx --reporter=verbose 2>&1
```

Expected output:
```
✓ Settings page > renders without crashing
✓ Settings page > shows Market Data Sync section by default
✓ Settings page > shows News tab button
✓ Settings page > shows News tab content when News tab is clicked
✓ Settings page > shows Global API Speed selector in Data tab
✓ Settings page > shows storage stats from fetchStorageStats

Test Files  1 passed (1)
Tests       6 passed (6)
```

**Step 5: Run full coverage gate**

```bash
npx vitest run --coverage 2>&1 | tail -30
```

Expected: all four thresholds pass — statements ≥ 30, branches ≥ 27, functions ≥ 22, lines ≥ 30.

**Step 6: Run TypeScript check**

```bash
npx tsc --noEmit 2>&1
```

Expected: no output (zero errors).

**Step 7: Commit**

```bash
git add frontend/src/pages/Settings.test.tsx
git commit -m "test(frontend): scope-correct Settings.test.tsx mock shape and add async assertion (#316)

Fix fetchStorageStats mock to match StorageStats interface (scanner/historical/settings/total with bytes+formatted).
Fix stopSync mock to return { message: 'Sync stopped' } matching TaskEnqueueResponse.
Add findByText async assertion so the corrected mock shape is load-bearing.
"
```

---

## Acceptance Checklist

- [ ] `fetchStorageStats` mock matches `StorageStats` interface (4 keys, each with `bytes` + `formatted`)
- [ ] `stopSync` mock returns `{ message: 'Sync stopped' }`
- [ ] 6 tests pass (5 existing + 1 new async assertion)
- [ ] `npx vitest run --coverage` passes all four thresholds (30/27/22/30)
- [ ] `npx tsc --noEmit` exits zero
