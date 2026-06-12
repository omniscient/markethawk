# ActiveWatchlist Test Coverage — Design (issue #312)

**Date**: 2026-06-12
**Issue**: [#312](https://github.com/omniscient/markethawk/issues/312) — test(frontend): scope-correct ActiveWatchlist tests (not in spec #250)

## Problem

During the issue #250 coverage ratchet, `ActiveWatchlist.test.tsx` was added out-of-scope (not in the spec's priority list) because the spec's listed files alone were insufficient to clear the 30%/22% coverage gate. The file was retained rather than excised because removing it breaks thresholds. `WatchlistTable.tsx` — the most behaviorally rich component in the directory — has no test file at all.

Issue #312 exists to replace the accidental, gate-driven tests with an intentional, spec-driven suite covering the full `ActiveWatchlist/` directory.

## Requirements

1. **`ActiveWatchlist.test.tsx`** — extend the existing 7 tests with:
   - Loading state: spinner visible when `isLoading: true`
   - At-limit state (50 items): count banner shows red, "Add Symbol" form is hidden, at-limit warning message is visible
   - `AddSymbolForm` behavior:
     - Submit calls `useAddToWatchlist().mutate` with trimmed+uppercased symbol and correct payload
     - Changing security type to `FUT` auto-sets exchange field to `CME`
     - API error message renders when the mocked mutation returns an error

2. **`WatchlistTable.test.tsx`** — new file covering:
   - Render-state assertions with populated `items` and `liveData`:
     - Price formatted to 2 decimal places; stale data (>15s) dims the price
     - `priceChangePct` coloring: green for positive, red for negative, gray for zero/null
     - Session label: `PRE` (yellow), `REG` (green), `POST` (blue)
     - Session volume formatted as `M` (≥1 000 000), `K` (≥1 000), or raw
     - Security-type badge: `STK` (blue) vs `FUT` (purple)
     - Notes display: shows text when present, dash when absent
   - Shallow interaction tests (all via `fireEvent`, no `userEvent`):
     - Clicking the edit-notes button switches the row to inline-edit mode (input appears)
     - `keyDown Enter` on the notes input calls `useUpdateWatchlistNotes().mutate`
     - `keyDown Escape` on the notes input returns to display mode (input removed)
     - Clicking the remove button calls `useRemoveFromWatchlist().mutate` with the symbol

3. **`AlertBadges.test.tsx`** — no changes (already comprehensive per issue #250 implementation).

4. **Coverage**: tests must keep the existing `vitest.config.ts` thresholds green (30% stmts, 27% branches, 22% functions, 30% lines). The new `WatchlistTable.test.tsx` is the primary coverage contributor for the directory; the expanded `ActiveWatchlist.test.tsx` tests are secondary.

## Architecture / Approach

### Tooling

- `fireEvent` from `@testing-library/react` for all interactions — consistent with every existing test file in the repo (`ScanConfigPanel.test.tsx`, `ConfigPanel.test.tsx`, `Scanner.test.tsx`, etc.). No `userEvent` — it is not used anywhere in the project.
- `renderWithQuery` from `../../test-utils/renderWithQuery` for components that use React Query or routing (same wrapper as `ActiveWatchlist.test.tsx`).
- Plain `render` from `@testing-library/react` for `WatchlistTable` (no React Query dependency).

### Mock pattern

Follow the established `vi.fn()` module-scope spy with `vi.mock` factory pattern from `ActiveWatchlist.test.tsx` and `frontend-patterns.md`:

```ts
const mockMutate = vi.hoisted(() => vi.fn());
vi.mock('../../api/watchlist', () => ({
  useRemoveFromWatchlist: () => ({ mutate: mockMutate, isPending: false }),
  useUpdateWatchlistNotes: () => ({ mutate: vi.fn(), isPending: false }),
}));
```

Use `vi.hoisted` for any spy that needs to be referenced in both the mock factory and test assertions (per `frontend-patterns.md` issue #250 entry).

### AddSymbolForm testing

`AddSymbolForm` is not exported — test it through the `ActiveWatchlist` page render (visible when `useWatchlist` returns `data: []`, which is the existing default mock). Use `fireEvent.change` to set field values and `fireEvent.submit` to trigger the form handler.

### `WatchlistTable.test.tsx` fixture

A minimal `WatchlistItem` and `SymbolLiveData` factory produces the test data. Import from `../../api/watchlist` and `../../hooks/useWatchlistLive` for the types.

## Alternatives Considered

**A. Keep `ActiveWatchlist.test.tsx` as-is, only add `WatchlistTable.test.tsx`.**
Rejected: the existing tests lack loading state, at-limit state, and AddSymbolForm coverage. A proper spec should claim these intentionally.

**B. Extract `AddSymbolForm` to its own file and test file.**
Rejected: it is a private sub-component of `index.tsx` with no reuse. Extracting it is a refactor beyond the scope of #312. Test it through the page render.

**C. Use `userEvent` for interaction tests.**
Rejected: no existing test in the repo uses `userEvent`. Introducing it creates a convention split and requires a new dev dependency. `fireEvent` covers the needed assertions.

## Assumptions

- The coverage thresholds in `vitest.config.ts` will remain at 30/27/22/30 (unchanged from issue #250 outcome) unless actuals drop below them after this issue's changes.
- `WatchlistTable.tsx` will not be refactored or split during implementation; it is tested as a single module.
- The `MemoryRouter` in `renderWithQuery` satisfies the `Link` component inside `WatchlistRow` (requires a router context).

## Open Questions

- None blocking. The "Live" vs "Connecting" status indicator in `ActiveWatchlist.test.tsx` already covers the `connected=false` path; a `connected=true` test would add coverage of the `Wifi` icon branch but is non-critical for this issue.
