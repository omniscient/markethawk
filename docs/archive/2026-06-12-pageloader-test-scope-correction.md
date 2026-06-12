# PageLoader Test Scope Correction — Implementation Plan

**Goal:** Formally legitimise `PageLoader.test.tsx` as in-scope by verifying its content matches the authoritative spec, confirming the tests pass, and confirming coverage thresholds remain satisfied. No code changes to the production component or the tests are required.

**Issue:** #311 (scope spillover from #250)
**Spec:** `docs/superpowers/specs/2026-06-12-pageloader-test-scope-correction-design.md`
**Date:** 2026-06-12

---

## Architecture

`PageLoader` (`frontend/src/components/ui/PageLoader.tsx`) is a static, propless full-screen spinner used as the `<Suspense>` fallback for all lazy-loaded routes in `App.tsx`. It has a single rendering code-path: a `div` containing an inner spinner `div` with the Tailwind class `animate-spin`.

`PageLoader.test.tsx` was added during issue #250's coverage ratchet as an out-of-spec file. It was retained because removing it would drop coverage below the gate. This plan formalises it as in-scope without modifying the component or the tests.

## Tech Stack

- **Testing:** Vitest + `@testing-library/react` + jsdom
- **Coverage:** V8 provider via `npx vitest run --coverage`
- **TypeScript gate:** `npx tsc --noEmit`

---

## File Structure

| File | Action |
|---|---|
| `frontend/src/components/ui/PageLoader.test.tsx` | Verify only — no changes |
| `frontend/src/components/ui/PageLoader.tsx` | Verify only — no changes |
| `frontend/vitest.config.ts` | Verify only — confirm thresholds still pass |
| `docs/superpowers/specs/2026-06-12-pageloader-test-scope-correction-design.md` | Create (spec) |
| `docs/superpowers/plans/2026-06-12-pageloader-test-scope-correction.md` | Create (this file) |

---

## Tasks

### Task 1 — Verify `PageLoader.test.tsx` matches the authoritative spec content

**Files:** `frontend/src/components/ui/PageLoader.test.tsx`

**Steps:**

1. Read the current file content and diff it against the spec's frozen test block.

```bash
cat frontend/src/components/ui/PageLoader.test.tsx
```

Expected output (verbatim from spec):
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

2. Verify `PageLoader.tsx` has the `animate-spin` class on the spinner element:

```bash
grep -n 'animate-spin' frontend/src/components/ui/PageLoader.tsx
```

Expected: at least one line containing `animate-spin`.

3. If the file content matches exactly: proceed to Task 2. If it differs: note the deviation but do not modify — the spec frozen content is the source of truth.

**Commit step:** No commit — this is a read-only verification task.

---

### Task 2 — Run the test suite and confirm both PageLoader tests pass

**Files:** `frontend/src/components/ui/PageLoader.test.tsx` (run, not modified)

**Steps:**

1. Run Vitest in CI mode for the PageLoader test file only:

```bash
cd frontend && npx vitest run PageLoader
```

Expected output:
```
 ✓ src/components/ui/PageLoader.test.tsx > PageLoader > renders without crashing
 ✓ src/components/ui/PageLoader.test.tsx > PageLoader > renders a spinning element

 Test Files  1 passed (1)
 Tests       2 passed (2)
```

2. Confirm that both tests pass with exit code 0.

**Commit step:** No commit — this is a verification task.

---

### Task 3 — Run full coverage suite and confirm thresholds are met

**Files:** `frontend/vitest.config.ts` (read only to confirm thresholds)

**Steps:**

1. Run the full Vitest coverage suite:

```bash
cd frontend && npx vitest run --coverage
```

2. Confirm coverage output meets or exceeds the thresholds defined in `frontend/vitest.config.ts`:

```
statements : ≥ 30%
branches   : ≥ 27%
functions  : ≥ 22%
lines      : ≥ 30%
```

3. If thresholds are met: proceed to Task 4. If any threshold fails: do not modify thresholds or add tests — record and flag.

**Commit step:** No commit — this is a verification task.

---

### Task 4 — Run TypeScript gate and commit the plan

**Files:** `docs/superpowers/specs/2026-06-12-pageloader-test-scope-correction-design.md`, `docs/superpowers/plans/2026-06-12-pageloader-test-scope-correction.md`

**Steps:**

1. Run the TypeScript gate to confirm the frontend compiles cleanly:

```bash
cd frontend && npx tsc --noEmit
```

Expected: zero errors, exit code 0.

2. Stage and commit the spec + plan files:

```bash
git add docs/superpowers/specs/2026-06-12-pageloader-test-scope-correction-design.md
git add docs/superpowers/plans/2026-06-12-pageloader-test-scope-correction.md
git commit -m "test(frontend): scope-correct PageLoader tests (#311)"
```

---

## Summary

| Task | Description | Files Changed | Commit |
|---|---|---|---|
| 1 | Verify test file matches spec | none | no |
| 2 | Run PageLoader tests | none | no |
| 3 | Run full coverage suite | none | no |
| 4 | TypeScript gate + commit spec + plan docs | spec + plan docs | yes |

**Total:** 4 tasks, 10 steps. No production code changes. No test changes. One commit (docs only).
