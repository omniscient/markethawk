# Frontend tsconfig Split — Fix Production Build Gate

> Issue: [#193](https://github.com/omniscient/markethawk/issues/193)
> Spec: [docs/superpowers/specs/2026-06-05-frontend-tsconfig-split-design.md](../specs/2026-06-05-frontend-tsconfig-split-design.md)

## Goal

Fix the red build/CI gate: `frontend/tsconfig.json` includes all of `src/` with no test exclusion, so `tsc --noEmit` type-checks test files that cannot resolve `vitest`/`@testing-library` modules, producing module-resolution failures and a TS7006 implicit-any. Split the tsconfig into a composite project layout matching the canonical Vite scaffold, update the build script, and fix the latent TS7006.

## Architecture

Canonical Vite composite project layout:

```
frontend/
  tsconfig.json        ← references-only root (files: [], no compilerOptions)
  tsconfig.app.json    ← NEW: production code, excludes test globs, composite: true
  tsconfig.node.json   ← unchanged: vite.config.ts only
```

The build script changes from `tsc && vite build` to `tsc -p tsconfig.app.json && vite build`. The CI `TypeScript type check` step (`npx tsc --noEmit`) exits 0 because `tsconfig.json` now has `files: []` — the explicit production check gate is `npm run build`.

## Tech Stack

TypeScript 5 / Vite 8 / Vitest 4 / React 18

## File Structure

| File | Action |
|------|--------|
| `frontend/tsconfig.app.json` | **CREATE** — production compiler options, excludes test globs, `composite: true` |
| `frontend/tsconfig.json` | **MODIFY** — reduce to `files: []` + `references` only (remove all compilerOptions/include) |
| `frontend/package.json` | **MODIFY** — build script: `tsc && vite build` → `tsc -p tsconfig.app.json && vite build` |
| `frontend/src/hooks/useScannerWs.test.ts` | **MODIFY** — add explicit type annotation to `updater` parameter (line 19) |

---

## Task 1 — Create `tsconfig.app.json` and reduce `tsconfig.json` to references-only root

**Files:** `frontend/tsconfig.app.json` (new), `frontend/tsconfig.json`

Tasks 1a and 1b are done atomically: TypeScript project references require the referenced file to exist before the root can resolve it.

### TDD Steps

**1a. Verify baseline failure** (write failing test):

```bash
cd /workspace/markethawk/frontend
npx tsc --noEmit 2>&1 | head -10; echo "Exit: $?"
```

Expected: errors including `Cannot find module 'vitest'` and `useScannerWs.test.ts(19,…): error TS7006`, `Exit: 2`.

**1b. Create `frontend/tsconfig.app.json`:**

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

**1c. Replace `frontend/tsconfig.json`** with the references-only root:

```json
{
  "files": [],
  "references": [
    { "path": "./tsconfig.app.json" },
    { "path": "./tsconfig.node.json" }
  ]
}
```

**1d. Verify pass — production typecheck clean:**

```bash
cd /workspace/markethawk/frontend
npx tsc -p tsconfig.app.json --noEmit; echo "Exit: $?"
```

Expected: no output, `Exit: 0`. (Test files excluded; no TS7006 in scope.)

**1e. Verify CI `tsc --noEmit` step passes:**

```bash
cd /workspace/markethawk/frontend
npx tsc --noEmit; echo "Exit: $?"
```

Expected: no output, `Exit: 0`. (`files: []` means TypeScript checks nothing at the root level.)

**1f. Commit:**

```bash
cd /workspace/markethawk
git add frontend/tsconfig.app.json frontend/tsconfig.json
git commit -m "$(cat <<'EOF'
feat(#193): split frontend tsconfig into composite project layout

Creates tsconfig.app.json for production code (excludes test globs,
composite: true). Reduces tsconfig.json to a references-only root
(files: []). Matches canonical Vite scaffold; keeps test-runner globals
out of production type scope.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2 — Update `package.json` build script

**Files:** `frontend/package.json`

### TDD Steps

**2a. Verify current build script:**

```bash
grep '"build"' /workspace/markethawk/frontend/package.json
```

Expected: `"build": "tsc && vite build"`.

**2b. Update the `build` script in `frontend/package.json`:**

Change:
```json
"build": "tsc && vite build",
```
To:
```json
"build": "tsc -p tsconfig.app.json && vite build",
```

**2c. Verify pass — production build exits 0:**

```bash
cd /workspace/markethawk/frontend
npm run build 2>&1 | tail -8; echo "Exit: ${PIPESTATUS[0]}"
```

Expected: Vite output ending with asset bundle sizes, `Exit: 0`.

**2d. Commit:**

```bash
cd /workspace/markethawk
git add frontend/package.json
git commit -m "$(cat <<'EOF'
fix(#193): update build script to tsc -p tsconfig.app.json

Explicit -p flag ensures only the production tsconfig is used for the
type-check gate in npm run build and CI. Bare tsc would fall back to the
new references-only tsconfig.json and check nothing.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3 — Fix TS7006 implicit-any in `useScannerWs.test.ts`

**Files:** `frontend/src/hooks/useScannerWs.test.ts`

The `updater` parameter is excluded from production typecheck scope (test files are excluded by `tsconfig.app.json`), but the implicit-any is a latent bug: if a `tsconfig.vitest.json` is ever added to also type-check tests, TS7006 will re-surface. Requirement 5 of the spec requires fixing it now.

### TDD Steps

**3a. Confirm the untyped parameter at line 19:**

```bash
sed -n '19p' /workspace/markethawk/frontend/src/hooks/useScannerWs.test.ts
```

Expected: `  const setLiveProgress = vi.fn((updater) => {`

**3b. Add the explicit type annotation:**

In `frontend/src/hooks/useScannerWs.test.ts`, line 19 — replace:

```typescript
  const setLiveProgress = vi.fn((updater) => {
```

With:

```typescript
  const setLiveProgress = vi.fn((updater: LiveProgress | ((prev: LiveProgress) => LiveProgress)) => {
```

The `LiveProgress` type is already imported at line 6 (`import { EMPTY_PROGRESS, type LiveProgress } from './useScannerState';`), so no new import is required.

**3c. Verify pass — vitest suite unaffected:**

```bash
cd /workspace/markethawk/frontend
npm test 2>&1 | tail -10; echo "Exit: ${PIPESTATUS[0]}"
```

Expected: `✓ src/hooks/useScannerWs.test.ts` (all tests pass), `Exit: 0`.

**3d. Commit:**

```bash
cd /workspace/markethawk
git add frontend/src/hooks/useScannerWs.test.ts
git commit -m "$(cat <<'EOF'
fix(#193): type updater param in useScannerWs.test.ts (TS7006)

Adds explicit LiveProgress | ((prev: LiveProgress) => LiveProgress)
annotation. File is excluded from tsconfig.app.json but fixing the latent
implicit-any avoids a re-surface if tsconfig.vitest.json is ever added.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4 — Full gate verification

**Files:** none (read-only verification)

All four requirements below must pass before the branch is considered green.

**4a. CI "TypeScript type check" step** (`npx tsc --noEmit`):

```bash
cd /workspace/markethawk/frontend
npx tsc --noEmit; echo "Exit: $?"
```

Expected: `Exit: 0`.

**4b. CI "Production build" step** (`npm run build`):

```bash
cd /workspace/markethawk/frontend
npm run build 2>&1 | tail -5; echo "Exit: ${PIPESTATUS[0]}"
```

Expected: `Exit: 0`.

**4c. Production-only typecheck** (explicit):

```bash
cd /workspace/markethawk/frontend
npx tsc -p tsconfig.app.json --noEmit; echo "Exit: $?"
```

Expected: `Exit: 0`.

**4d. Vitest test suite** (unaffected):

```bash
cd /workspace/markethawk/frontend
npm test 2>&1 | tail -10; echo "Exit: ${PIPESTATUS[0]}"
```

Expected: all tests pass, `Exit: 0`.

**4e. Confirm no production source loses type coverage** (spot check):

```bash
# Edit a production file to introduce a deliberate error and confirm tsc catches it
echo 'const x: string = 123;' >> /workspace/markethawk/frontend/src/main.tsx
cd /workspace/markethawk/frontend
npx tsc -p tsconfig.app.json --noEmit 2>&1 | grep "error TS"; echo "Exit: $?"
git checkout -- /workspace/markethawk/frontend/src/main.tsx
```

Expected: `error TS2322` on the injected line, `Exit: 2`. (Confirms production files are still in scope.)
