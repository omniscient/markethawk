# Frontend Test Quality Pass — Design (issue #396)

**Date**: 2026-06-13
**Issue**: [#396](https://github.com/omniscient/markethawk/issues/396) — test(frontend): quality-pass the 7 OOS test files from #250 (executes epic #383 decision)

## Problem

Seven test files were added out-of-scope during issue #250's coverage ratchet and retained because removing them would drop coverage below the 30%/22% gates. Epic #383 decided that rather than excising them, they should be quality-passed (option 3: quality-pass, then bless). The current files have three categories of quality issues:

1. **Pure smoke tests** — `it('renders without crashing', ...)` tests with no assertion, or a bare `render()` call.
2. **Implementation-detail class assertions** — `expect(el.className).toContain('text-red-300')` etc. These couple tests to Tailwind class names and break on cosmetic refactors.
3. **Redundant tests** — smoke tests that duplicate coverage already provided by behavioral sibling tests in the same file.

## Requirements

Derived from issue body and Q&A:

1. **Remove** pure smoke tests from ScorecardDetail, ScorecardOverview, ActiveWatchlist, PreMarketMovers — existing behavioral tests (loading/error/data) cover the same render path.
2. **PageLoader** — add `role="status"` and `aria-label="Loading"` to `PageLoader.tsx` source; replace the two existing tests (smoke + `.animate-spin` class check) with a single behavioral test using `getByRole('status', { name: /loading/i })`.
3. **AlertBadges severity assertions** — add an `aria-label` attribute to the severity indicator span in `AlertBadges.tsx` (e.g., `aria-label="high severity"`). Replace `className.toContain('text-red-300')` assertions with `getByRole('img', { name: /high severity/i })` or `getByLabelText(/high severity/i)`.
4. **ActiveWatchlist count-at-limit assertion** — no source change needed. Replace `getByText('50').className.toContain('text-red-400')` with `getByText(/Watchlist is full/)` (already rendered by the component at limit).
5. **Period selector button active state** — add `aria-pressed={period === p.value}` to the period buttons in `ScorecardOverview.tsx` and `ScorecardDetail.tsx`. Replace `button.className.toContain('bg-financial-blue')` assertions with `expect(button).toHaveAttribute('aria-pressed', 'true')`.
6. **Settings.test.tsx** — already quality-grade (behavioral assertions, tab interaction, async data). No changes needed.
7. **Coverage gates must stay green** — `npx vitest run --coverage` must report ≥ 30% statements/lines and ≥ 22% branches/functions after changes.
8. **TypeScript gate** — `npx tsc --noEmit` must pass.
9. **Sub-issues closed** — PR closes #309, #311, #312, #313, #314, #315, #316. Epic #383 closes when all sub-issues close.

## Architecture / Approach

**Approach: Minimal source changes with semantic ARIA improvements**

Three source files receive small ARIA additions (PageLoader, AlertBadges, period-selector components). These are not test scaffolding — they are genuine accessibility improvements: `role="status"` announces loading state to screen readers; `aria-label` on severity badges conveys severity to users who cannot distinguish color; `aria-pressed` on toggle buttons correctly identifies their state to assistive technology. The changes are minimal and non-breaking (ARIA attributes are additive).

Test changes follow a consistent pattern: any assertion that reaches into CSS implementation details is replaced with a WCAG-semantics assertion (`getByRole`, `getByLabelText`, `toHaveAttribute('aria-pressed')`).

## Per-File Change Map

| File | Source change | Test change |
|------|--------------|-------------|
| `PageLoader.tsx` | Add `role="status"` + `aria-label="Loading"` to spinner element | Remove 2 tests; add 1 `getByRole('status', { name: /loading/i })` test |
| `AlertBadges.tsx` | Add `aria-label={`${alert.severity} severity`}` to badge span | Replace 3 className assertions with `getByLabelText(/severity/i)` assertions |
| `ActiveWatchlist/index.tsx` | None | Replace `className.toContain('text-red-400')` with `getByText(/Watchlist is full/i)` |
| `ScorecardOverview.tsx` | Add `aria-pressed={activePeriod === p.value}` to period buttons | Replace `className.toContain('bg-financial-blue')` with `toHaveAttribute('aria-pressed', 'true')` |
| `ScorecardDetail.tsx` | Add `aria-pressed={period === p.value}` to period buttons | Replace `className.toContain('bg-financial-blue')` with `toHaveAttribute('aria-pressed', 'true')` |
| `ScorecardDetail.test.tsx` | — | Remove `it('renders without crashing')` |
| `ActiveWatchlist.test.tsx` | — | Remove `it('renders without crashing')` |
| `PreMarketMovers.test.tsx` | — | Remove `it('renders without crashing')` |
| `ScorecardOverview.test.tsx` | — | Remove `it('renders without crashing')` |
| `Settings.test.tsx` | — | No changes |

## Alternatives Considered

**A. Accept all class assertions (no source changes)** — The issue explicitly calls class-name assertions out as implementation-detail coupling to remove. Accepting them violates the issue's criteria.

**B. Add `data-testid` instead of ARIA** — `data-testid` is production code with no semantic value. ARIA attributes provide the same test hook and simultaneously fix real accessibility gaps (color-only severity indication fails WCAG 1.4.1; status regions should use `role="status"`). ARIA is strictly better.

**C. Add full accessibility audit beyond the 3 source files** — Out of scope for this issue. Only the minimum changes needed to decouple tests from implementation details.

## Open Questions (non-blocking)

- The `ScorecardDetail` loading state test uses `container.querySelectorAll('.animate-pulse').length > 0` — this is also a class assertion. It should be evaluated during implementation: if a skeleton loader has a visible label (e.g., ARIA live region) prefer that; otherwise `.animate-pulse` is arguably closer to behavior (Tailwind's loading skeleton convention) than a layout class. Defer to implementation judgement with PR justification if kept.

## Assumptions

- The 30%/22% coverage thresholds from the #250 ratchet are still the current gates (not raised since). If they have been raised, run `npx vitest run --coverage` first to confirm actuals before any deletions.
- `ScorecardOverview.tsx` and `ScorecardDetail.tsx` use a `periodButtons` array rendered with `.map()` — period-selector buttons share the same JSX structure and the `aria-pressed` addition applies identically to both.
- `AlertBadge.tsx` renders a single `<span>` per badge; `aria-label` on that span is the correct attachment point.
