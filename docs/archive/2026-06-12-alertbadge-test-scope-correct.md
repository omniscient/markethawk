# AlertBadge Tests — Scope Correction Plan (issue #313)

**Date**: 2026-06-12
**Issue**: [#313](https://github.com/omniscient/markethawk/issues/313) — test(frontend): scope-correct AlertBadges tests (not in spec #250)
**Spec**: `docs/superpowers/specs/2026-06-12-alertbadge-test-scope-correct-design.md`

## Goal

Formally accept `AlertBadges.test.tsx` as a legitimate, in-scope deliverable. The file was added out-of-scope during the #250 coverage ratchet and retained because excision would break coverage thresholds. This plan executes a **validate-and-retain** pass: verify the existing 7 test cases are correct per spec, run the test suite, confirm coverage and TypeScript gates hold, and commit a scope-acceptance record.

**No code modifications are required.** The test file is already committed on this branch with all 7 test cases covering all four decision branches of `AlertBadge`. The production component `AlertBadges.tsx` is not touched.

## Architecture

Scope is limited to `frontend/src/pages/ActiveWatchlist/AlertBadges.test.tsx`. No backend, no production component, no new tests.

## Tech Stack

Vitest + React Testing Library, TypeScript (`tsc --noEmit` gate), Vitest coverage (`v8` provider).

## File Structure

| File | Action |
|------|--------|
| `frontend/src/pages/ActiveWatchlist/AlertBadges.test.tsx` | Verify — no modifications |
| `frontend/src/pages/ActiveWatchlist/AlertBadges.tsx` | Read-only — not modified |
| `frontend/vitest.config.ts` | Read-only — thresholds verified, not changed |

---

## Task 1 — Verify test file completeness against spec

**Files**: `frontend/src/pages/ActiveWatchlist/AlertBadges.test.tsx`

**Note**: This is a validate-and-retain task. There is no failing-test phase — the tests already exist and are expected to pass. The steps confirm spec fidelity before running.

**Steps**:

1. Confirm the file exists at the correct path:

```bash
test -f frontend/src/pages/ActiveWatchlist/AlertBadges.test.tsx && echo "EXISTS" || echo "MISSING"
# expected: EXISTS
```

2. Confirm exactly 7 `it(...)` test cases:

```bash
grep -c "^\s*it(" frontend/src/pages/ActiveWatchlist/AlertBadges.test.tsx
# expected: 7
```

3. Confirm all 7 spec-named descriptions are present:

```bash
grep -E \
  "renders null when alert is null|\
renders null when alert is older than 1 hour|\
shows .VOL. badge for live_volume_spike|\
shows .MOVE. badge for other scanner types|\
applies red color classes for high severity|\
applies yellow color classes for medium severity|\
applies gray color classes for low severity" \
  frontend/src/pages/ActiveWatchlist/AlertBadges.test.tsx
# expected: 7 matching lines
```

4. Confirm `className.toContain(...)` assertion pattern (repo convention — not `data-testid`):

```bash
grep "className.*toContain" frontend/src/pages/ActiveWatchlist/AlertBadges.test.tsx
# expected: 3 lines (red, yellow, gray assertions)
```

5. Confirm `AlertBadges.tsx` is unmodified relative to `origin/main`:

```bash
git diff origin/main...HEAD -- frontend/src/pages/ActiveWatchlist/AlertBadges.tsx
# expected: empty output (no diff)
```

**Commit**: No code commit for this task — it is read-only verification.

---

## Task 2 — Run the isolated test suite

**Files**: `frontend/src/pages/ActiveWatchlist/AlertBadges.test.tsx`

**Steps**:

1. Run the 7 AlertBadge tests in isolation:

```bash
cd frontend && npx vitest run src/pages/ActiveWatchlist/AlertBadges.test.tsx
```

Expected output (excerpt):

```
 ✓ src/pages/ActiveWatchlist/AlertBadges.test.tsx (7)
   ✓ AlertBadge > renders null when alert is null
   ✓ AlertBadge > renders null when alert is older than 1 hour
   ✓ AlertBadge > shows "VOL" badge for live_volume_spike scanner type
   ✓ AlertBadge > shows "MOVE" badge for other scanner types
   ✓ AlertBadge > applies red color classes for high severity
   ✓ AlertBadge > applies yellow color classes for medium severity
   ✓ AlertBadge > applies gray color classes for low severity

 Test Files  1 passed (1)
 Tests       7 passed (7)
```

2. Run the full frontend test suite to confirm no regressions:

```bash
cd frontend && npx vitest run
```

Expected: all tests pass, exit code 0.

**Commit**: No code commit for this task — it is read-only verification.

---

## Task 3 — Verify TypeScript compiles clean

**Files**: `frontend/tsconfig.json` (read-only)

**Steps**:

1. Run the TypeScript production check:

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors, exit code 0.

2. If `tsconfig.test.json` exists, optionally run the test-file check:

```bash
cd frontend && npx tsc -p tsconfig.test.json --noEmit
```

Expected: no errors.

**Commit**: No code commit for this task — it is read-only verification.

---

## Task 4 — Verify coverage thresholds are met

**Files**: `frontend/vitest.config.ts` (read-only)

**Steps**:

1. Run coverage:

```bash
cd frontend && npx vitest run --coverage
```

2. Confirm thresholds (set during the #250 ratchet) are met with `AlertBadges.test.tsx` contributing:
   - Statements ≥ 30%
   - Lines ≥ 30%
   - Branches ≥ 22%
   - Functions ≥ 22%

Expected: coverage run exits with code 0 (thresholds not violated).

3. Check the current threshold values in the config for reference:

```bash
grep -A 10 "thresholds" frontend/vitest.config.ts
```

**Commit**: No code commit for this task — it is read-only verification.

---

## Task 5 — Commit scope acceptance record

**Files**: `docs/superpowers/plans/2026-06-12-alertbadge-test-scope-correct.md` (this file, committed by the plan workflow)

**Steps**:

The plan file itself serves as the scope-acceptance record and is committed by the plan workflow in Phase 4. No further code changes are needed.

1. Confirm the plan file is committed:

```bash
git log --oneline -3
# Should show the plan commit at the top
```

2. Verify no uncommitted modifications to the test or component files:

```bash
git status --short frontend/src/pages/ActiveWatchlist/
# expected: empty (no staged or unstaged changes)
```

3. Close the issue via commit message reference. If any final housekeeping is needed (e.g., the branch needs a closing commit after the plan commit), use:

```bash
git commit --allow-empty -m "$(cat <<'EOF'
close(#313): scope-accept AlertBadges.test.tsx — validate-and-retain

Formally scopes AlertBadges.test.tsx as a legitimate deliverable.
File was added OOS during #250 coverage ratchet and retained by the
conformance gate. All 7 tests verified, coverage thresholds confirmed.
EOF
)"
```

Only emit this empty commit if the branch has no other pending commit that closes the issue.
