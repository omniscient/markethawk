# PageLoader Test Scope Correction — Design

**Date:** 2026-06-12
**Issue:** #311 (scope spillover from #250)
**Status:** Spec ready for review

## Overview

`PageLoader` (`frontend/src/components/ui/PageLoader.tsx`) is a static, propless full-screen spinner used as the `<Suspense>` fallback for all lazy-loaded routes in `App.tsx`. `PageLoader.test.tsx` was added during issue #250's coverage ratchet as an out-of-scope file not listed in the spec's priority list. It was retained at scope-enforcement time because removing it would drop coverage below the gate thresholds.

This spec formally legitimises the existing test file so that it is explicitly in scope — no modifications to the component or the tests are required.

## Requirements

1. `PageLoader.test.tsx` must contain exactly two tests:
   - **Smoke test** — render the component without asserting on any DOM output; confirms no render-time error.
   - **Spinner presence test** — assert that a DOM element with the class `animate-spin` exists in the rendered output; confirms the animated spinner is mounted.

2. Both tests must use `@testing-library/react` (`render`) and `vitest` (`describe`, `it`, `expect`), consistent with the existing test suite pattern.

3. No modifications to the `PageLoader.tsx` production component are required or permitted by this spec.

4. No `data-testid` attributes are added; the `.animate-spin` Tailwind class is the selector (consistent with zero `getByTestId` calls elsewhere in the test suite).

5. Coverage contribution: the two tests fully cover `PageLoader.tsx`'s single rendering code-path, contributing to the `statements`, `functions`, and `lines` thresholds defined in `frontend/vitest.config.ts`.

## Architecture / Approach

No code changes needed. The tests already exist and match the requirements above. The implementation task is to:

1. Verify the current `PageLoader.test.tsx` content matches the spec (it does — see below for the authoritative content).
2. Commit the spec; the conformance gate will treat the file as formally in-scope on the next run.

### Authoritative test content (frozen by this spec)

```tsx
import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { PageLoader } from './PageLoader';

describe('PageLoader', () => {
  it('renders without crashing', () => {
    render(<PageLoader />);
  });

  it('renders a spinning element', () => {
    const { container } = render(<PageLoader />);
    const spinner = container.querySelector('.animate-spin');
    expect(spinner).toBeInTheDocument();
  });
});
```

## Alternatives Considered

### A — Add accessibility attributes and assert them

`role="status"` and `aria-label="Loading"` on the spinner `<div>` would improve screen-reader UX and align with RTL best practices for asserting on interactive elements. Rejected: modifying the production component is out of scope for a test-correction ticket. An accessibility enhancement should be filed as a separate issue.

### B — Replace `.animate-spin` with `data-testid="spinner"`

RTL guidance prefers `data-testid` for non-semantic elements. Rejected: the codebase has zero `getByTestId` calls in production test files, and adding `data-testid` to the component means modifying production code — same scope-expansion problem as Alternative A.

### C — Delete the tests and accept a coverage drop, then re-set the threshold

The tests could be excised and the coverage threshold lowered to compensate. Rejected: the tests are correctly scoped for a static presentational spinner, they provide genuine value (smoke test + structural assertion), and they are already passing. Deleting them introduces churn with no benefit.

## Open Questions

None. The component is stable; no future prop additions are anticipated under this spec.

## Assumptions

- `PageLoader` remains a no-prop, no-state presentational component for the lifetime of this spec.
- The `animate-spin` Tailwind utility class is not renamed or removed from the spinner `<div>`.
- Coverage thresholds in `frontend/vitest.config.ts` remain at or below their current values (`statements: 30`, `branches: 27`, `functions: 22`, `lines: 30`).
