# Frontend tsconfig Split — Fix Production Build Gate

> Tracking issue: [#193](https://github.com/omniscient/markethawk/issues/193)

## Overview

`frontend/tsconfig.json` includes the entire `src/` directory with no exclusion for test files. When `tsc --noEmit` runs (gating `npm run build` and the CI frontend job), it type-checks test files that import from `vitest` and `@testing-library/react` as if they were production code. This causes module resolution failures and surfaces a genuine TS7006 implicit-`any` in `useScannerWs.test.ts:19`. The build gate is currently red (exit 2).

## Requirements

1. `npx tsc --noEmit` exits 0 with zero errors or warnings.
2. The CI frontend job (`ci.yml`) becomes genuinely green.
3. `npm run build` (`tsc && vite build`) succeeds.
4. Test files are no longer included in the production typecheck scope.
5. The TS7006 implicit-`any` on `updater` in `useScannerWs.test.ts:19` is fixed.
6. No production source file loses type coverage.
7. Vitest test runs are unaffected (vitest uses esbuild, not tsc, to transpile).

## Architecture / Approach

**Split the tsconfig into a composite project following the canonical Vite scaffold layout.**

```
frontend/
  tsconfig.json        ← references-only root (no compilerOptions, no include)
  tsconfig.app.json    ← NEW: production code, excludes test files
  tsconfig.node.json   ← existing: vite.config.ts only (unchanged)
```

### Changes

**1. `frontend/tsconfig.app.json` (new)**

Move all production `compilerOptions` from `tsconfig.json` here. Add `"composite": true` (required by TypeScript project references). Add an `exclude` array to prevent test files from entering the production typecheck:

```json
{
  "compilerOptions": {
    "composite": true,
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true
  },
  "include": ["src"],
  "exclude": [
    "src/**/*.test.ts",
    "src/**/*.test.tsx",
    "src/**/*.spec.ts",
    "src/**/*.spec.tsx",
    "src/test-utils",
    "src/test-setup.ts"
  ]
}
```

**2. `frontend/tsconfig.json` (updated)**

Reduce to a references-only root. `"files": []` prevents TypeScript from accidentally picking up files directly:

```json
{
  "files": [],
  "references": [
    { "path": "./tsconfig.app.json" },
    { "path": "./tsconfig.node.json" }
  ]
}
```

**3. `frontend/package.json` build script (updated)**

```json
"build": "tsc -p tsconfig.app.json && vite build"
```

The `-p tsconfig.app.json` flag is explicit: it type-checks production code only. `tsc -b` (composite build mode) would also work but is less readable in a build script.

**4. Fix TS7006 in `frontend/src/hooks/useScannerWs.test.ts:19`**

The `updater` parameter in the mock `setLiveProgress` mirrors `React.Dispatch<React.SetStateAction<LiveProgress>>`. Add an explicit type annotation:

```typescript
const setLiveProgress = vi.fn((updater: LiveProgress | ((prev: LiveProgress) => LiveProgress)) => {
  if (typeof updater === 'function') progress = updater(progress);
  else progress = updater;
});
```

## Alternatives Considered

### B — Add test types to the existing tsconfig

Add `"types": ["vitest/globals", "@testing-library/jest-dom"]` and `"exclude"` globs to the existing `tsconfig.json`. Simpler (two-field diff vs. a new file), but injects test-runner globals (`describe`, `it`, `vi`, etc.) into the production type environment — a production source file could accidentally call `vi.fn()` and tsc would not error. Also contradicts the project's existing direction of splitting configs (the `tsconfig.node.json` reference pattern already implies multi-config).

**Rejected**: pollutes production type environment; contradicts existing project direction.

### C — Exclude in existing tsconfig, fix nothing else

Add only the `"exclude"` array to `tsconfig.json`. This makes tsc skip test files without adding test types. Simpler than A, but leaves the TS7006 in the test file latent (vitest still transpiles it without type errors since vitest uses esbuild with `strict: false` by default, but the bug will re-surface if a `tsconfig.vitest.json` is ever added).

**Rejected**: doesn't satisfy acceptance criterion "Fix the TS7006 implicit-any".

## Open Questions

- Should a `tsconfig.vitest.json` be added now to also type-check test files via `tsc -p tsconfig.vitest.json`? Not required for this issue (CI gate is the target, and vitest uses esbuild), but a natural follow-on once the gate is green.
- The other test files (`useScannerState.test.ts`, `useScanTask.test.ts`, etc.) may have similar untyped callback parameters. Out of scope for this bug fix but should be audited once the gate is green.

## Assumptions

- `vitest.config.ts` does not need to be modified — vitest's esbuild transpiler runs tests without invoking `tsc`, so test execution is independent of the tsconfig split.
- The CI `ci.yml` frontend job runs `npx tsc --noEmit` (or `npm run build`) from the `frontend/` directory — the `-p tsconfig.app.json` flag propagates automatically once the build script is updated.
- `skipLibCheck: true` is kept to avoid noise from third-party `@types` — this is the existing setting and is safe to preserve.
- `composite: true` on `tsconfig.app.json` is required by TypeScript's project references protocol (it enables declaration emit needed for cross-project type resolution). Since `noEmit: true` is also set, TypeScript suppresses actual `.d.ts` output while still validating.
