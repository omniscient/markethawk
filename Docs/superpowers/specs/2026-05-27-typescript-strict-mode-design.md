# TypeScript Strict Mode — Incremental Rollout Design Spec

**Issue**: [#92 — Enable TypeScript strict mode incrementally](https://github.com/omniscient/markethawk/issues/92)
**Date**: 2026-05-27
**Status**: Pending Review

## Overview

TypeScript `strict` mode is disabled in `frontend/tsconfig.json`. There are 76 explicit `: any` type annotations across 27 source files and 67 `as any` cast patterns. With strict off, implicit `any` types are also permitted, allowing type errors to pass silently through the compiler.

This spec defines a four-phase incremental rollout. Each phase is a separate PR that enables one or more `tsconfig` flags and replaces the highest-risk `any` patterns uncovered by those flags. The end state is `"strict": true` in `tsconfig.json` with all implicit `any` eliminated and the majority of explicit `any` replaced by proper domain types.

## Current State (baseline, 2026-05-27)

Running `tsc --noEmit` with specific flags against the unmodified codebase:

| Flag(s) | Compiler errors |
|---|---|
| `--noImplicitAny` | 1 (api/watchlist.ts — function expression missing return type) |
| `--strictNullChecks` | 16 (StockChart.tsx + utils/indicators.ts — type narrowing on empty-array inference) |
| `--strict` (all flags) | 2 (Recharts formatter type mismatch in DistributionChart.tsx and EdgeExplorer.tsx) |

The low compiler-error count is misleading: the 76 explicit `: any` and 67 `as any` casts are already syntactically valid — they suppress the errors the compiler would otherwise emit. The real work is replacing those explicit annotations with domain types as part of each phase.

## Requirements

1. Each phase produces a separate, reviewable PR.
2. `npx tsc --noEmit` must pass (zero errors) before any phase PR is merged.
3. The api/ layer (`src/api/scanner.ts`, `src/api/journal.ts`, `src/api/stocks.ts`, `src/api/watchlist.ts`) must have all `any` annotations replaced with proper types — no suppressions permitted in these files.
4. Component-level `any` in files already being edited for a phase must be replaced in that same PR.
5. UI-local `as any` casts where replacement requires non-trivial component refactoring may use `// @ts-expect-error` with a one-line explanation of why the cast is safe. Limit: ≤ 5 per phase PR. A PR reviewer must push back on any `@ts-expect-error` that looks like laziness rather than genuine complexity.
6. `noUnusedLocals` and `noUnusedParameters` remain `false` through Phase 3; they are enabled in Phase 4 to avoid unrelated cleanup scope in earlier PRs.
7. Third-party library type errors that cannot be fixed in our own code are resolved with a targeted cast (`as unknown as TargetType`) at the call site, accompanied by a one-line comment citing the library deficiency. These casts do not count against the `@ts-expect-error` budget. If the same library accumulates more than 3 cast sites, escalate to a vendor patch in `src/types/vendor/`.
8. New types introduced to replace `any` are defined in the same api/ file that owns them — no new `src/types/` directory.

## Phases

### Phase 1 — `noImplicitAny`

**tsconfig.json change:**
```json
"noImplicitAny": true
```

**Compiler errors to fix (1):**
- `src/api/watchlist.ts` — function expression missing explicit return type annotation. Add `: ReturnType` annotation.

**api/ layer `any` to replace in this PR (highest priority):**

| File | Line(s) | Current | Replacement |
|---|---|---|---|
| `src/api/scanner.ts` | 758 | `(error: any): string` | `(error: unknown): string` — use `instanceof Error` guard in body |
| `src/api/journal.ts` | 76 | `createTrade(trade: any)` | `createTrade(trade: CreateTradeRequest)` — new interface |
| `src/api/journal.ts` | 81 | `updateTrade(id, data: any)` | `updateTrade(id, data: Partial<CreateTradeRequest>)` |
| `src/api/journal.ts` | 106 | `createEntry(data: any)` | `createEntry(data: CreateJournalEntryRequest)` — new interface |
| `src/api/journal.ts` | 116 | `createTag(data: any)` | `createTag(data: CreateTagRequest)` — new interface |
| `src/api/journal.ts` | 91 | `importTrades(): Promise<any>` | `importTrades(): Promise<ImportTradesResponse>` — new interface |

**New interfaces for `src/api/journal.ts`:**
```typescript
export interface CreateTradeRequest {
  symbol: string;
  side?: string;
  open_date?: string;
  quantity?: number;
  avg_entry_price?: number;
  notes?: string;
}

export interface CreateJournalEntryRequest {
  entry_date: string;
  content: string;
  sentiment?: string;
}

export interface CreateTagRequest {
  name: string;
  color?: string;
}

export interface ImportTradesResponse {
  imported: number;
  skipped: number;
  errors: string[];
}
```

**Acceptance criteria:**
- `npx tsc --noEmit --noImplicitAny` passes with zero errors.
- No new `@ts-expect-error` comments.
- api/journal.ts has zero `any` annotations.

---

### Phase 2 — `strictNullChecks`

**tsconfig.json change:**
```json
"noImplicitAny": true,
"strictNullChecks": true
```

**Compiler errors to fix (up to 16):**

Errors are concentrated in two files:

1. **`src/utils/indicators.ts`** — `utils/indicators.ts:77` attempts to push into a typed array that TypeScript infers as `never[]` when initialized as `[]`. Fix: provide an explicit array type annotation on initialization.

2. **`src/components/ui/StockChart.tsx`** — Multiple `Property 'X' does not exist on type 'never'` errors caused by the same pattern: typed array narrowed to `never[]`. Fix: annotate array initialization types explicitly.

**api/ layer `any` to replace in this PR:**

| File | Line(s) | Current | Replacement |
|---|---|---|---|
| `src/api/scanner.ts` | 246 | `[k: string]: any` (index sig in `ScannerRunStatus`) | `[k: string]: string \| number \| boolean \| null \| undefined` |
| `src/api/scanner.ts` | 614 | `data: any[]` in `fetchStockHistory` return type | `data: OHLCVRow[]` — new interface |
| `src/api/scanner.ts` | 637, 662 | `const row: any = {}` | `const row: OHLCVRow = {} as OHLCVRow` — valid because keys are added immediately |

**New interface for `src/api/scanner.ts`:**
```typescript
export interface OHLCVRow {
  Date: string;
  Open: number;
  High: number;
  Low: number;
  Close: number;
  Volume: number;
  vwap?: number;
  transactions?: number;
  vwap_intraday?: number;
  marker_type?: string;
  contract_month?: string;
  [k: string]: string | number | undefined;
}
```

**Acceptance criteria:**
- `npx tsc --noEmit --noImplicitAny --strictNullChecks` passes with zero errors.
- `@ts-expect-error` count introduced: ≤ 5.
- api/scanner.ts OHLCV path has typed rows.

---

### Phase 3 — Remaining strict flags (excluding `noUnusedLocals`/`noUnusedParameters`)

**tsconfig.json change:**
```json
"noImplicitAny": true,
"strictNullChecks": true,
"strictFunctionTypes": true,
"strictBindCallApply": true,
"strictPropertyInitialization": true,
"noImplicitThis": true,
"alwaysStrict": true,
"useUnknownInCatchVariables": true
```

**Compiler errors to fix:**

Based on the baseline measurement, enabling all strict flags together produces only the 2 Recharts errors (addressed in Phase 4). With phases 1 and 2 already merged, Phase 3 is expected to have zero new compiler errors. Run `npx tsc --noEmit` with the above flags to confirm before submitting the PR.

**`useUnknownInCatchVariables` consequence:** any `catch (e)` block that accesses `e.message` or `e.response` will now require narrowing (`e instanceof Error`). Audit all `catch` blocks in `src/` and add guards where needed.

**api/ layer `any` to replace in this PR:**

Any remaining `any` in api/ files not covered by Phases 1 or 2, including any `catch (e: any)` patterns that were previously valid but are now surfaced by `useUnknownInCatchVariables`.

**Acceptance criteria:**
- `npx tsc --noEmit` with all flags above passes with zero errors.
- No `catch (e: any)` patterns remain in `src/api/`.
- `@ts-expect-error` count introduced: ≤ 5.

---

### Phase 4 — `strict: true` + `noUnusedLocals` + `noUnusedParameters`

**tsconfig.json change (final state):**
```json
"strict": true,
"noUnusedLocals": true,
"noUnusedParameters": true
```

**Compiler errors to fix (2 Recharts formatter mismatches):**

Both errors are in third-party formatter callbacks. Fix with a targeted cast per the library policy (Requirement 7):

```typescript
// src/components/scorecard/DistributionChart.tsx:103
// Recharts Formatter union type is too broad to satisfy with a concrete return type — cast is safe.
formatter={myFn as unknown as Formatter<ValueType, NameType>}

// src/pages/EdgeExplorer.tsx:381
// Same Recharts Formatter limitation.
formatter={myFn as unknown as Formatter<ValueType, NameType>}
```

These casts do not count against the `@ts-expect-error` budget.

**`noUnusedLocals` / `noUnusedParameters`:** Run `npx tsc --noEmit` with the full config to surface unused variables and parameters. Remove unused locals. For unused parameters that are required by a callback signature, prefix with `_` (e.g., `_index`).

**Remaining explicit `any` cleanup:**

By Phase 4 all api/ layer `any` is already gone. The remaining `any` patterns are in UI files. Apply the tiered policy:

- **Replace if straightforward:** component props typed inline, local state initialization, event handler parameters.
- **`@ts-expect-error` if non-trivial:** deep Recharts/chart library integration, dynamic data shapes where the correct type requires understanding runtime behavior. Include a dated comment and reference to a follow-up issue.

Track `@ts-expect-error` count in the PR description. If Phase 4 introduces more than 5, file a follow-up issue for the deferred items before merging.

**Acceptance criteria:**
- `npx tsc --noEmit` passes with zero errors against final `tsconfig.json`.
- `"strict": true`, `"noUnusedLocals": true`, `"noUnusedParameters": true` all present in `tsconfig.json`.
- api/ layer has zero `any` annotations.
- All `@ts-expect-error` comments include a one-line explanation.
- `@ts-expect-error` count introduced in Phase 4: ≤ 5 (file follow-up if exceeded).

## Approach

The phased flag-by-flag approach is preferred over enabling `strict: true` in one commit because:

1. **Smaller, reviewable PRs.** Each phase touches a bounded set of files and introduces a specific class of type improvements.
2. **Incremental any cleanup.** The api/ layer gets properly typed across phases 1–3, reducing the risk that Phase 4 is overloaded.
3. **Clear rollback points.** If a phase PR reveals unexpected issues, only that phase needs to be reverted.

## Alternatives Considered

### Enable `strict: true` immediately

Technically feasible — only 2 compiler errors exist today. However, it does not address the 76 explicit `: any` annotations or 67 `as any` casts, which remain silently valid even with `strict: true`. Enabling the flag in one commit provides no momentum for the actual type-safety work and produces a large, hard-to-review PR.

### Type suppression strategy (convert all `any` to `unknown`)

Converting every `any` to `unknown` eliminates the `any` count but defers the actual domain modeling work. `unknown` is better than `any` but still requires a type guard at every use site — it makes the problem visible without solving it. The tiered replacement policy (api/ layer must be properly typed; UI deferred only where non-trivial) gives better signal-to-noise.

### Monorepo-level strict enforcement via ESLint `@typescript-eslint/no-explicit-any`

Would catch all explicit `any` usages at lint time, independent of the compiler. Reasonable addition after Phase 4 lands as a lint rule to prevent regression. Out of scope for this spec — track as a follow-up.

## Open Questions

- Are there backend Pydantic schema changes needed to match the new `CreateTradeRequest` / `OHLCVRow` interfaces, or do the current API response shapes already match? (Non-blocking — the interfaces can be derived from actual API responses during implementation.)
- Should `@typescript-eslint/no-explicit-any` be added to ESLint as a regression guard after Phase 4? (Follow-up issue recommended.)

## Assumptions

- `skipLibCheck: true` remains in `tsconfig.json` — third-party library type errors do not affect this effort.
- The Recharts version in use will not be upgraded during this rollout (an upgrade could introduce new formatter type issues).
- Each phase is implemented sequentially; Phase 2 does not begin until Phase 1 is merged.
- `npx tsc --noEmit` run from `frontend/` is the canonical validation command for each PR.
