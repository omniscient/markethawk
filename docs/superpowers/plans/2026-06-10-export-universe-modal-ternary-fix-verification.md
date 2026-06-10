# ExportUniverseModal — Verify no-unused-expressions Fix (Issue #240)

**Date:** 2026-06-10
**Issue:** [#240](https://github.com/omniscient/markethawk/issues/240)
**Spec:** [docs/superpowers/specs/2026-06-09-export-universe-modal-ternary-fix-design.md](../specs/2026-06-09-export-universe-modal-ternary-fix-design.md)
**Branch:** `refine/issue-240-fix-no-unused-expressions-in-exportunive`

## Goal

Confirm that the `no-unused-expressions` ternary fix at `ExportUniverseModal.tsx:81` is present,
that ESLint and TypeScript gates pass clean, and that no other ternary-as-statement instances exist
in `frontend/src/`. Close issue #240 with evidence. **No code changes are expected.**

## Architecture

No architectural changes. The defect was already corrected as a side-effect of PR #197, which wired
`@typescript-eslint/flat/recommended` (including `no-unused-expressions` at error level) into
`frontend/eslint.config.js`. Reverting to the ternary form would immediately fail the ESLint gate,
so the fix is permanent.

## Tech Stack

- **Frontend**: React 18 + TypeScript + ESLint (flat-config, `@typescript-eslint/flat/recommended`)
- **Tooling**: `npx eslint src --ext .ts,.tsx`, `npx tsc --noEmit`, `grep`

## File Structure

| File | Action |
|------|--------|
| `frontend/src/components/ExportUniverseModal.tsx` | Read-only — verify `if/else` form at line 81 |
| `frontend/eslint.config.js` | Read-only — confirm rule is active (advisory) |

---

## Task 1: Verify if/else form at ExportUniverseModal.tsx:81

**Files:** `frontend/src/components/ExportUniverseModal.tsx`

This requirement would fail if the file still contained `next.has(ticker) ? next.delete(ticker) : next.add(ticker);`.

### Steps

1. **Read the relevant line:**
   ```bash
   grep -n "has(ticker)" frontend/src/components/ExportUniverseModal.tsx
   ```
   **Expected output (success):**
   ```
   81:      if (next.has(ticker)) { next.delete(ticker); } else { next.add(ticker); }
   ```
   Any output containing `? next.delete` or `? next.add` (ternary form) means the requirement is
   **not met** — escalate before proceeding.

2. **Confirm no ternary-as-statement form survives anywhere in the file:**
   ```bash
   grep -n "has(ticker).*?" frontend/src/components/ExportUniverseModal.tsx
   ```
   **Expected output:** *(empty)*

3. No code change needed — fix is already present.

4. No commit — read-only verification.

---

## Task 2: Run ESLint gate — zero `no-unused-expressions` violations

**Files:** None (command-only)

This requirement would fail if ESLint exited non-zero or printed any `no-unused-expressions` diagnostic.

### Steps

1. **Run ESLint across the entire `src/` tree:**
   ```bash
   cd frontend && npx eslint src --ext .ts,.tsx
   echo "ESLint exit: $?"
   ```
   **Expected output (success):**
   ```
   ESLint exit: 0
   ```
   Any printed diagnostic lines (errors or warnings that cause non-zero exit) mean the requirement
   is **not met** — report the full output before proceeding.

2. **Specifically isolate `no-unused-expressions` violations to confirm zero:**
   ```bash
   cd frontend && npx eslint src --ext .ts,.tsx 2>&1 | grep "no-unused-expressions" | wc -l
   ```
   **Expected output:**
   ```
   0
   ```

3. No code change needed.

4. No commit.

---

## Task 3: Run TypeScript gate — tsc --noEmit passes

**Files:** None (command-only)

This requirement would fail if any type errors were introduced. While no code changes are expected,
confirming tsc is clean is a hard requirement per the spec.

### Steps

1. **Run tsc from `frontend/`:**
   ```bash
   cd frontend && npx tsc --noEmit
   echo "tsc exit: $?"
   ```
   **Expected output (success):**
   ```
   tsc exit: 0
   ```
   Any TypeScript error output means the requirement is **not met** — report verbatim before
   proceeding.

2. No code change needed.

3. No commit.

---

## Task 4: Grep for other ternary-as-statement instances in frontend/src/

**Files:** `frontend/src/` (read-only)

The authoritative gate for this requirement is the ESLint run in Task 2 (exit 0 = zero
`no-unused-expressions` violations across all of `src/`). This task supplements that with a
targeted grep for human audit.

### Steps

1. **Search for unassigned ternary statements** — lines where a standalone expression is a
   ternary (not a type annotation or optional property, which also contain `?:`):
   ```bash
   grep -rEn "^\s+[a-zA-Z_\$][a-zA-Z0-9_.\$]*\s*\?[^.:]" frontend/src/ \
     --include="*.ts" --include="*.tsx" \
     | grep -v "//\|return\b\|const \|let \|var \|=\|interface\|type " \
     | head -30
   ```
   **Expected output:** *(empty)*

   If the output is non-empty, each match is a candidate — confirm manually whether it is a
   ternary-as-statement or a false positive (JSX expression, optional chaining, etc.). The
   ESLint exit from Task 2 is authoritative; a non-empty grep result here does not fail the
   requirement if ESLint already exited 0.

2. **Authoritative confirmation (already completed by Task 2):**
   ESLint exit 0 with zero `no-unused-expressions` violations covers this requirement fully.

3. No code change needed.

4. No commit.

---

## Task 5: Post evidence comment and close issue #240

**Files:** None (GitHub CLI only)

### Steps

1. **Assemble evidence output** from Tasks 1–4 (actual command output, not placeholders).

2. **Post evidence comment:**
   ```bash
   gh issue comment 240 --repo omniscient/markethawk --body "$(cat <<'BODY'
   ## Issue #240 — Verification Complete ✅

   The \`no-unused-expressions\` ternary fix at \`ExportUniverseModal.tsx:81\` has been verified as
   present and correct. No code changes were made — the fix shipped with PR #197.

   ### Requirement 1: if/else form at line 81
   \`\`\`
   $ grep -n "has(ticker)" frontend/src/components/ExportUniverseModal.tsx
   81:      if (next.has(ticker)) { next.delete(ticker); } else { next.add(ticker); }
   \`\`\`
   ✅ Confirmed — \`if/else\` form present; ternary-as-statement is gone.

   ### Requirement 2: ESLint clean (zero no-unused-expressions violations)
   \`\`\`
   $ cd frontend && npx eslint src --ext .ts,.tsx; echo "exit: $?"
   exit: 0
   \`\`\`
   ✅ Confirmed — ESLint exits 0; zero \`no-unused-expressions\` violations in \`src/\`.

   ### Requirement 3: TypeScript clean (tsc --noEmit)
   \`\`\`
   $ cd frontend && npx tsc --noEmit; echo "exit: $?"
   exit: 0
   \`\`\`
   ✅ Confirmed — No TypeScript errors.

   ### Requirement 4: No other ternary-as-statement instances
   \`\`\`
   $ grep -rEn "^\s+[a-zA-Z_\$\(].*\?.*:.*;" frontend/src/ --include="*.ts" --include="*.tsx" | ...
   (empty)
   \`\`\`
   ✅ Confirmed — No other ternary-as-statement instances found in \`frontend/src/\`.

   ---
   *Posted by MarketHawk Refinement Pipeline*
   BODY
   )"
   ```
   Replace the placeholder output lines above with actual captured output from Tasks 1–4 before
   posting.

3. **Close the issue as completed:**
   ```bash
   gh issue close 240 --repo omniscient/markethawk --reason completed
   ```
   **Expected output:**
   ```
   ✓ Closed issue #240 (Fix no-unused-expressions in ExportUniverseModal.tsx)
   ```

4. No commit — verification-only; no source files changed.
