# Add vite-env.d.ts Scaffold File to Frontend — Implementation Plan

**Date:** 2026-06-10
**Issue:** #226 (scope spillover from #193)
**Spec:** [docs/superpowers/specs/2026-06-09-vite-env-d-ts-scaffold-design.md](../specs/2026-06-09-vite-env-d-ts-scaffold-design.md)
**Goal:** Create the missing `frontend/src/vite-env.d.ts` file so `import.meta.env` resolves correctly under `tsconfig.app.json` type checks and IDE inspections.

## Architecture

Single-file addition. `frontend/src/vite-env.d.ts` containing one triple-slash reference directive is the standard Vite scaffold pattern. `tsconfig.app.json`'s `"include": ["src"]` picks it up automatically; no tsconfig changes are needed.

Two existing files benefit immediately: `frontend/src/api/client.ts` and `frontend/src/components/ui/GlobalErrorToast.tsx` both reference `import.meta.env` and are now properly typed without per-file workarounds.

## Tech Stack

TypeScript 5 · Vite · `tsconfig.app.json` (strict, `noEmit: true`)

## File Structure

| File | Action | Purpose |
|------|--------|---------|
| `frontend/src/vite-env.d.ts` | **Create** | Adds `/// <reference types="vite/client" />` so `import.meta.env` and Vite-specific globals are typed project-wide |

---

## Task 1 — Create `vite-env.d.ts`

**Files:** `frontend/src/vite-env.d.ts`

### Step 1 — Confirm pre-condition (no existing file)

```bash
ls frontend/src/vite-env.d.ts 2>/dev/null && echo "EXISTS — stop" || echo "MISSING — proceed"
```

Expected output: `MISSING — proceed`

### Step 2 — Record baseline TypeScript check

```bash
cd frontend && npx tsc -p tsconfig.app.json --noEmit 2>&1 | tail -20
```

Record any existing errors. The root `tsconfig.json` is a solution-file with `"files": []` and project references, so bare `tsc` resolves zero source files. The app-scoped project (`tsconfig.app.json`) is the correct gate — it includes `src/` and exercises the `import.meta.env` references in `src/api/client.ts` and `src/components/ui/GlobalErrorToast.tsx`. Either pass or fail is a valid baseline; the goal is to confirm the check exits 0 after Step 3.

### Step 3 — Create the file

`frontend/src/vite-env.d.ts`:

```ts
/// <reference types="vite/client" />
```

The file contains exactly this one line — no blank line before or after. This is the canonical Vite scaffold pattern confirmed in `frontend-patterns.md` (`[PATTERN] frontend/src/vite-env.d.ts … must exist in src/`).

### Step 4 — Verify TypeScript check passes

```bash
cd frontend && npx tsc -p tsconfig.app.json --noEmit 2>&1
```

Expected output: no output (exit code 0). Any new errors introduced by this step indicate a tsconfig misconfiguration unrelated to the file's content.

### Step 5 — Confirm the file is included

```bash
cd frontend && npx tsc -p tsconfig.app.json --noEmit --listFiles 2>/dev/null | grep vite-env
```

Expected output: `.../frontend/src/vite-env.d.ts`

This confirms `tsconfig.app.json`'s `"include": ["src"]` picked up the new file. Note: bare `tsc --listFiles` (no `-p`) resolves zero files due to the solution-style root `tsconfig.json` (`"files": []` + project references); the `-p tsconfig.app.json` flag is required.

### Step 6 — Commit

```bash
git add frontend/src/vite-env.d.ts
git commit -m "feat(frontend): add vite-env.d.ts scaffold (issue #226)"
```

Expected output: `[refine/issue-226-add-vite-env-d-ts-scaffold-file-to-front <hash>] feat(frontend): add vite-env.d.ts scaffold (issue #226)`

---

## Out-of-scope (do not touch)

- `frontend/tsconfig.app.json` — no changes needed; `"include": ["src"]` already covers the new file
- `frontend/tsconfig.json` — no changes needed
- `frontend/vitest.config.ts` — already excludes `src/vite-env.d.ts` from coverage
- `frontend/tsconfig.test.json` — explicitly out of scope per spec §Alternatives Considered B
