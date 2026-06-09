# Add vite-env.d.ts Scaffold File to Frontend — Design

**Date:** 2026-06-09
**Status:** Spec generated — pending implementation plan
**Issue:** #226 (scope spillover from #193)
**Author:** Brainstormed with Claude (Opus 4.8)

## Problem

`frontend/src/vite-env.d.ts` is missing from the project. This is the standard Vite
scaffold file that includes the `vite/client` type declarations via a triple-slash reference
directive. Its absence means `import.meta.env` is untyped in IDE type checks and in any
TypeScript compilation pass that resolves types through `tsconfig.app.json` rather than
through Vite's runtime transform. Two files already use `import.meta.env`:

- `frontend/src/api/client.ts`
- `frontend/src/components/ui/GlobalErrorToast.tsx`

`vitest.config.ts` already lists `src/vite-env.d.ts` in its coverage exclusion array,
anticipating the file's existence. The file was identified during the implementation of
issue #193 but was not added inline due to scope enforcement.

## Requirements

1. Create `frontend/src/vite-env.d.ts` containing exactly one line:
   ```ts
   /// <reference types="vite/client" />
   ```
2. No other files need to change — `tsconfig.app.json` already includes the `src/` directory
   and relies on triple-slash reference directives for type augmentation.
3. No `tsconfig.test.json` is in scope for this issue (see Alternatives Considered).

## Architecture / Approach

**Approach chosen: Add the single file.**

`frontend/src/vite-env.d.ts` with `/// <reference types="vite/client" />` is the canonical
Vite project pattern. Once present and included via `tsconfig.app.json`'s `"include": ["src"]`,
it makes `import.meta.env` and all Vite-specific global types available project-wide without
per-file triple-slash references or changes to compiler options.

This is a one-file, zero-risk change. `vitest.config.ts` already accounts for the file; no
other config changes are required.

## Alternatives Considered

### A. Add `"types": ["vite/client"]` to `tsconfig.app.json`

Redundant if `vite-env.d.ts` exists. The triple-slash reference directive in the `.d.ts` file
achieves the same inclusion. Adding it to `compilerOptions.types` would suppress automatic
`@types/*` resolution — a broader change with higher blast radius. Rejected.

### B. Add `vite-env.d.ts` + `tsconfig.test.json`

`tsconfig.test.json` (types: `["vite/client", "vitest/globals"]`, relaxed unused-locals,
include limited to test files) was also identified during #193. Rejected for this issue
because:

- Vitest resolves test types through `vitest.config.ts` (`globals: true`), not a separate TS
  project; `tsconfig.test.json` has no active consumer today.
- Creating unused scaffolding here would be speculative. If a CI `tsc` pass over test files
  is added in the future, `tsconfig.test.json` should be filed as its own issue then.

## Open Questions

None — the change is fully specified by the issue and confirmed by codebase inspection.

## Assumptions

- `tsconfig.app.json`'s `"include": ["src"]` is sufficient to pick up `src/vite-env.d.ts`
  automatically. ✓ Confirmed: `src/` is listed as the include glob and the file will be
  matched as a `.d.ts` within it.
- No change to `vitest.config.ts` is needed; it already excludes `src/vite-env.d.ts` from
  coverage. ✓ Confirmed.
