# Fix prefer-const Violation in StockChart.tsx — Design Spec

**Date:** 2026-06-10
**Issue:** #241
**Status:** Ready for implementation
**Labels:** scope-spillover, direct-to-pr

## Overview

During the implementation of issue #197 (ESLint @typescript-eslint v8 flat-config fix), the dark factory identified a pre-existing `prefer-const` ESLint violation in `frontend/src/components/ui/StockChart.tsx`. The variable `allMarkers` was declared with `let` but never reassigned — a trivial one-character fix required to satisfy the now-active error-level `prefer-const` rule.

Scope enforcement blocked an inline fix during #197. This issue tracks that fix as a standalone backlog item.

## Analysis: Fix Already Applied

Subsequent review shows that commit `881f1fe` ("fix(eslint): spread flat/recommended array in @typescript-eslint v8", part of #197) included this fix as a side-effect. The file currently reads:

```typescript
// Line 370 — frontend/src/components/ui/StockChart.tsx
const allMarkers: SeriesMarker<Time>[] = [];  // was `let`
```

The fix is live. Other `let` declarations in the same function (`let timeValue`, `let ts`) are legitimately reassigned across conditional branches and are not `prefer-const` violations.

## Requirements

1. `allMarkers` at line 370 of `frontend/src/components/ui/StockChart.tsx` must be declared with `const`.
2. `npm run lint` (or `npx eslint frontend/src/components/ui/StockChart.tsx`) must pass with zero `prefer-const` errors for this file.
3. `npx tsc --noEmit` must continue to pass.
4. No other changes to the file are required or in scope.

## Approach

Since the fix is already applied, the implementation step is purely **verification and closure**:

1. Confirm `const allMarkers` is present at line 370.
2. Run ESLint against the file and confirm no `prefer-const` findings.
3. Run `npx tsc --noEmit` to confirm no regressions.
4. Close the issue referencing commit `881f1fe` as the fix.

No new commit or PR is required unless verification reveals a regression or the fix was not included in the merge.

## Alternatives Considered

**Option A (chosen): Verify-and-close** — confirm the fix exists, validate lint passes, close as resolved-by-#197.

**Option B: New standalone PR** — redundant if the fix is already on `main`. Only warranted if, on verification, the fix is absent (e.g. was reverted or never merged).

## Open Questions

None. The fix is unambiguous and already present.

## Assumptions

- Commit `881f1fe` was merged to `main` before this refine run. If the branch history shows the fix is absent, the implementation agent must apply `let → const` at line 370 and commit.
- No other `prefer-const` violations exist in `StockChart.tsx` (verified during context assembly — the remaining `let` declarations are legitimately reassigned).
