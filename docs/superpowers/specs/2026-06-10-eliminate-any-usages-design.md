# Eliminate `any` Usages & Re-enable `no-explicit-any: error` — Design Spec

**Date:** 2026-06-10
**Issue:** #239
**Status:** Spec generated — pending review
**Author:** Refinement Pipeline (brainstorming session)

## Overview

PR #197 fixed the `@typescript-eslint` v8 ESLint config but deliberately downgraded
`no-explicit-any` to `warn` to avoid blocking CI on ~131 pre-existing `any` usages.
CI now runs `npx eslint . --report-unused-disable-directives-severity error`, which
tolerates warnings. This spec covers eliminating all `any` usages so the rule can be
promoted back to `error` and CI restored to the strict `npm run lint` gate.

## Goals

1. Eliminate all `any` usages in `frontend/src/` (currently ~130 across ~27 files).
2. Promote `@typescript-eslint/no-explicit-any` to `error` in `eslint.config.js`.
3. Restore CI lint step to `npm run lint` (`--max-warnings 0` — strict gate).
4. Restore pre-commit hook to `npm run lint` (was temporarily relaxed by #197).

## Non-Goals

- Backend changes — purely a frontend TypeScript quality issue.
- Adding new API types not already implied by the codebase.
- Refactoring component interfaces beyond what is required for type safety.
- Changing `tsconfig.json` strictness settings.

## Affected Files

~27 files in `frontend/src/`, grouped by pattern:

| Pattern | File count | Fix |
|---------|-----------|-----|
| `icon={X as any}` (Lucide icon casts) | ~15 | Remove `as any` — icons are already `LucideIcon` |
| `(e: any)` callback params | ~10 | Drop annotation; infer from array type |
| `as any` on typed arrays/objects | ~5 | Import real type from `api/` layer |
| `MockWebSocket.ts` `globalThis` casts | 1 | `(globalThis as { WebSocket: typeof WebSocket })` |
| `useScorecard.test.ts` fixtures | 1 | Import real `Scorecard` type from `api/outcomes` |
| `eslint.config.js` rule + CI/pre-commit | 3 | Promote rule; restore scripts |

## Approach

### Pattern 1 — Icon `as any` casts (highest volume)

All `icon={X as any}` usages are Lucide icons passed to `Card` or `MetricCard`,
both of which already declare `icon?: LucideIcon`. The casts are stale — a leftover
from an earlier lucide-react major version. **Remove them mechanically.** Confirmed:
`npx tsc --noEmit` passes after removal. No interface change needed.

Affected files include `Dashboard.tsx`, `EdgeExplorer.tsx`, `Scanner/ScanConfigPanel.tsx`,
`Journal.tsx`, `StockDetailPage/ChartPanel.tsx`, `StockDetailPage/MetadataPanel.tsx`,
`Scanner/ScanStatusCard.tsx`, `AutoTrading/AccountPanel.tsx`, `Scanner/index.tsx`,
`components/ScannerConfig.tsx`, `components/QualityReportModal.tsx`, and others.

### Pattern 2 — Callback parameter `any` annotations

For `.map()` / `.reduce()` callbacks on arrays already typed by React Query return values,
**remove the explicit annotation** — TypeScript infers the parameter type from the array
element type (e.g., `ScannerEvent[]` from `useQuery(...getScannerResults)`).

For arrays whose element type is genuinely ambiguous (e.g., `EdgeExplorer.tsx` where
`events` comes from `api/outcomes`), **import the named type** from `frontend/src/api/*.ts`
and annotate explicitly. Do not define a duplicate local interface — follow the established
pattern of `api/` as the single source of truth.

If an API client function returns `Promise<any>` or `Promise<unknown>`, fix the return type
there so all downstream call sites benefit automatically.

### Pattern 3 — Test utilities

**`src/test-utils/MockWebSocket.ts`** — replace `(globalThis as any).WebSocket` casts with:
```ts
(globalThis as { WebSocket: typeof WebSocket }).WebSocket = MockWebSocket as unknown as typeof WebSocket;
```
This removes `any` while keeping the mock installation correct.

**`src/hooks/useScorecard.test.ts`** — replace `{} as any` / `mockScorecard as any` with
proper type imports from `frontend/src/api/outcomes.ts`. Use the real `Scorecard` type;
complete or cast partial fixtures via `as Partial<Scorecard> as Scorecard` if needed.

No `eslint-disable` comments. No per-directory ESLint overrides. All five test-file
usages are mechanically fixable and the fully-strict gate is the explicit goal.

### Pattern 4 — ESLint config, CI, and pre-commit

Once all `any` usages are eliminated:

1. **`frontend/eslint.config.js`**: Change `'@typescript-eslint/no-explicit-any': 'warn'` to `'error'`.
2. **`.github/workflows/ci.yml`**: Replace `npx eslint . --report-unused-disable-directives-severity error` with `npm run lint` (or `npx eslint . --report-unused-disable-directives --max-warnings 0`).
3. **`.pre-commit-config.yaml`**: Replace `npx eslint . --report-unused-disable-directives-severity error` with `npm run lint` (consistent with CI).

## Alternatives Considered

### A. ESLint override block for test files
Add a separate config block in `eslint.config.js` allowing `any` in `**/*.test.ts` and
`src/test-utils/**`. **Rejected** — the test-file usages are trivially fixable and adding
an escape hatch sets a precedent that erodes the gate.

### B. Per-line `eslint-disable-next-line` comments
Add targeted disable comments on lines where `any` is "hard to avoid."
**Rejected** — none of the ~130 usages are genuinely hard to avoid; all are fixable with
proper types. Per-line suppression obscures real future violations.

### C. Phased promotion (files in batches across multiple PRs)
Fix one area at a time and keep `no-explicit-any: warn` until the last batch.
**Rejected** — the issue is size:M (1–4 hours), the fix is mechanical, and a single PR is
simpler to review. The patterns repeat and a single pass is less error-prone than tracking
partial progress across PRs.

## Acceptance Criteria

- `npm run lint` exits 0 (no `any` violations, no warnings)
- CI lint step uses `npm run lint` (or equivalent with `--max-warnings 0`)
- `npx tsc --noEmit` exits 0
- `@typescript-eslint/no-explicit-any` is `'error'` in `eslint.config.js`
- Pre-commit hook uses `npm run lint`

## Assumptions

- **[ASSUMPTION]** All `any` usages identified by `grep` / ESLint are the full set (~130);
  no hidden usages in generated files or `public/`.
- **[ASSUMPTION]** `lucide-react` icons used in pages are already typed as `LucideIcon`
  (confirmed by product owner subagent: lucide-react v1.8.0 installed).
- **[ASSUMPTION]** `api/outcomes.ts` exports a `Scorecard` type that backs
  `fetchScorecard`'s return; if it does not, that type must be added there first.

## Open Questions (non-blocking)

- Should Recharts-specific data shapes (e.g., `BarChart` `data` props) be typed with
  local component interfaces (acceptable as view-model shapes) or with `Record<string, unknown>`?
  Either is valid given the product owner guidance; implementer may choose.
- The `Chart.tsx` component (`src/components/ui/Chart.tsx`) has 4 `any` usages — these
  may require a local interface for chart data if the shape isn't covered by an api/ type.
