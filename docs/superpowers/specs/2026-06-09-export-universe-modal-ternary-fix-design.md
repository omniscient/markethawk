# ExportUniverseModal — Fix no-unused-expressions Ternary (Design)

**Date:** 2026-06-09
**Status:** Approved — implement phase is verification only
**Issue:** #240 (scope-spillover from #197)
**Author:** Brainstormed with Claude (Opus 4.8)

## Problem

`frontend/src/components/ExportUniverseModal.tsx` line 81 originally contained a
ternary used as a void statement:

```ts
next.has(ticker) ? next.delete(ticker) : next.add(ticker);
```

ESLint's `no-unused-expressions` rule (inherited at error level from
`@typescript-eslint/flat/recommended`, enabled by issue #197) flags this pattern
because the ternary's result is discarded — only the side-effects matter.  The rule
requires an explicit `if/else` when a branch is used solely for side-effects.

The dark factory detected this during the #197 implementation and attempted to excise
the incidental fix, but excision was skipped because reverting to the ternary form
would immediately fail the newly-honest ESLint gate.  The fix therefore shipped with
#197 and the issue was filed to close the tracking loop.

## Goal

Confirm the fix is present and the lint gate is clean; close issue #240 with evidence.
No net code change is expected.

## Requirements

1. `ExportUniverseModal.tsx:81` must read `if (next.has(ticker)) { next.delete(ticker); } else { next.add(ticker); }` (or functionally equivalent `if/else`).
2. `npx eslint src` run from `frontend/` must report zero `no-unused-expressions` violations across the entire `src/` tree.
3. `npx tsc --noEmit` must pass (no type regressions).
4. No other ternary-as-statement instances exist in `frontend/src/` that would violate the same rule (verified by grepping for the pattern).

## Approach

**Verification-only (no code changes).**

1. Confirm requirement 1 by reading the file.
2. Run `npx eslint src --ext .ts,.tsx` from `frontend/`; assert exit 0.
3. Run `npx tsc --noEmit` from `frontend/`; assert exit 0.
4. Grep `frontend/src/` for unassigned ternary statements to confirm no new instances.
5. Post results as evidence in the issue comment and close.

## Alternatives Considered

**Fix + close in this PR.** Not applicable — there is nothing to fix.  The defect was
already eliminated as a side-effect of #197 and cannot be introduced again without
breaking ESLint.

**Broader ternary-as-statement sweep.** Considered and rejected: a full grep sweep of
the frontend finds zero other instances of ternaries used as void statements.  The ESLint
gate would catch any future regressions automatically.

## Open Questions

None — all questions resolved during brainstorming.

## Assumptions

- The `no-unused-expressions` rule is enabled at error level via
  `@typescript-eslint/flat/recommended` in `frontend/eslint.config.js` (confirmed by
  issue #197 implementation).
- The fix at line 81 was committed to `main` as part of PR #197 and is therefore present
  on all branches that descend from main after that merge.
