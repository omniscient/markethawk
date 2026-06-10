# Fix prefer-const Violation in StockChart.tsx — Verify and Close Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verify that the `prefer-const` lint fix for `allMarkers` in `StockChart.tsx` (applied as a side-effect of commit `881f1fe` in #197) is live and passes all validation gates, then close issue #241. No code change is expected — this is a verify-and-close workflow. A contingency task is included in case verification reveals the fix is absent.

**Architecture:** Pure verification — confirm `const allMarkers` exists at line 370, run ESLint and TypeScript compiler gates against the file, then close the issue. If verification reveals the fix is absent (e.g., `881f1fe` was not merged to this branch), Task 3 applies the one-character `let → const` correction before re-running the gates.

**Tech Stack:** ESLint (v8 flat-config, `@typescript-eslint` v8), TypeScript compiler (`npx tsc --noEmit`), `gh` CLI for issue closure.

**Spec:** `docs/superpowers/specs/2026-06-10-fix-prefer-const-allmarkers-stockchart-design.md`

**Component:** `frontend/src/components/ui/StockChart.tsx`

---

## File Structure

| File | Action |
|---|---|
| `frontend/src/components/ui/StockChart.tsx` | VERIFY only (or MODIFY line 370 if contingency Task 3 triggers) |

---

## Task 1: Verify `const allMarkers` declaration at line 370

**Files:**
- Read-only: `frontend/src/components/ui/StockChart.tsx`

- [ ] **Step 1: Confirm `const` declaration exists**

Run:
```bash
grep -n "allMarkers" frontend/src/components/ui/StockChart.tsx
```

Expected output — line 370 reads `const`:
```
370:      const allMarkers: SeriesMarker<Time>[] = [];
384:          allMarkers.push(...)
400:        allMarkers.push(...)
411:        if (allMarkers.length > 0) {
412:          allMarkers.sort(...)
417:          const validMarkers = allMarkers.filter(...)
```

- [ ] **Step 2: Confirm no `let allMarkers` remains**

Run:
```bash
grep -n "let allMarkers" frontend/src/components/ui/StockChart.tsx
```

Expected: **no output** (empty — the `let` form has been replaced).

If this command produces output (the fix is absent), **skip to Task 3** before proceeding. Otherwise continue to Task 2.

- [ ] **Step 3: Confirm remaining `let` declarations are legitimately reassigned**

Run:
```bash
grep -n "^\s*let " frontend/src/components/ui/StockChart.tsx
```

Expected: only `let timeValue` and `let ts` declarations, both of which are reassigned inside conditional branches. No `let allMarkers`.

---

## Task 2: Run ESLint and TypeScript gates

**Files:**
- Command-line verification only

- [ ] **Step 1: Run ESLint against the specific file**

From the repo root:
```bash
cd frontend && npx eslint src/components/ui/StockChart.tsx
```

Expected: **no output** (zero errors, zero warnings). Exit code 0.

If a `prefer-const` error appears on line 370, skip to Task 3. If other unrelated errors appear, document them and proceed (they are pre-existing and out of scope for this issue).

- [ ] **Step 2: Run `tsc --noEmit` to confirm no regressions**

From the repo root:
```bash
cd frontend && npx tsc --noEmit
```

Expected: **no output**. Exit code 0.

If TypeScript errors appear on lines unrelated to this issue, they are pre-existing regressions and out of scope — document them and continue.

- [ ] **Step 3: Commit (no-op)**

No file changes were made. No commit needed. Proceed to Task 4.

---

## Task 3 (CONTINGENCY): Apply `let → const` fix at line 370

**Execute only if Task 1 Step 2 found `let allMarkers` still present.**

**Files:**
- Modify: `frontend/src/components/ui/StockChart.tsx`

- [ ] **Step 1: Verify the violation exists (failing lint check)**

```bash
cd frontend && npx eslint src/components/ui/StockChart.tsx
```

Expected output includes:
```
/path/to/frontend/src/components/ui/StockChart.tsx
  370:7  error  'allMarkers' is never reassigned. Use 'const' instead  prefer-const
```

- [ ] **Step 2: Apply the one-character fix**

In `frontend/src/components/ui/StockChart.tsx`, line 370, change:

```typescript
      let allMarkers: SeriesMarker<Time>[] = [];
```

to:

```typescript
      const allMarkers: SeriesMarker<Time>[] = [];
```

This is the only change. Do not modify any other declarations (`let timeValue`, `let ts` are legitimately reassigned and must remain `let`).

- [ ] **Step 3: Verify ESLint now passes**

```bash
cd frontend && npx eslint src/components/ui/StockChart.tsx
```

Expected: **no output**. Exit code 0.

- [ ] **Step 4: Verify `tsc --noEmit` passes**

```bash
cd frontend && npx tsc --noEmit
```

Expected: **no output**. Exit code 0.

- [ ] **Step 5: Commit the fix**

```bash
git add frontend/src/components/ui/StockChart.tsx
git commit -m "$(cat <<'EOF'
fix(eslint): use const for allMarkers in StockChart.tsx (prefer-const)

Variable is never reassigned; let → const satisfies the error-level
prefer-const ESLint rule.

Closes #241.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

Expected output:
```
[refine/issue-241-fix-prefer-const-violation-in-stockchart <hash>] fix(eslint): use const for allMarkers in StockChart.tsx (prefer-const)
 1 file changed, 1 insertion(+), 1 deletion(-)
```

Return to Task 2 to re-run the gates before closing.

---

## Task 4: Close issue #241

**Files:**
- Command-line only (`gh` CLI)

- [ ] **Step 1: Determine the resolution commit**

If Task 3 was NOT executed (fix was already present):
- Resolution commit = `881f1fe` (applied as part of #197)

If Task 3 WAS executed:
- Run `git log --oneline -1` and record the new commit hash.

- [ ] **Step 2: Post close comment and close the issue**

If fix was already present (happy path):
```bash
gh issue close 241 --repo omniscient/markethawk \
  --comment "Verified: \`const allMarkers\` is present at line 370 of \`frontend/src/components/ui/StockChart.tsx\`. ESLint (\`npx eslint src/components/ui/StockChart.tsx\`) and \`npx tsc --noEmit\` both pass with zero errors. Fix was applied by commit 881f1fe as a side-effect of #197. Closing as resolved."
```

If Task 3 fix was applied (contingency path):
```bash
HASH=$(git log --oneline -1 --format="%h")
gh issue close 241 --repo omniscient/markethawk \
  --comment "Fix applied in commit ${HASH}: changed \`let allMarkers\` to \`const allMarkers\` at line 370 of \`frontend/src/components/ui/StockChart.tsx\`. ESLint and \`npx tsc --noEmit\` both pass with zero errors. Closes #241."
```

Expected output:
```
Closed issue #241 (Fix prefer-const violation in StockChart.tsx (allMarkers never reassigned))
```

- [ ] **Step 3: Verify closure**

```bash
gh issue view 241 --repo omniscient/markethawk --json state --jq '.state'
```

Expected: `"CLOSED"`
