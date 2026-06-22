# Plan: dark-factory-ops.md BuildKit/Preview Memory Verification

**Date:** 2026-06-22
**Issue:** #517 — docs(memory): dark-factory-ops.md BuildKit/preview patterns not spec-listed in #436
**Spec:** [docs/superpowers/specs/2026-06-20-dark-factory-ops-memory-buildkit-preview-design.md](../specs/2026-06-20-dark-factory-ops-memory-buildkit-preview-design.md)

## Goal

Retroactively verify the three BuildKit/preview `[PATTERN]` entries added to `.archon/memory/dark-factory-ops.md` during issue #436 are correct and present, and confirm three stale entries were properly removed. This is a **verification-only** task — the work is already merged to `main` (PR #519, commit `92207ab`). No code or memory file modifications are made.

## Architecture

- **Memory file**: `.archon/memory/dark-factory-ops.md` — maintained by implement agents through the standard memory phase. The header marks it "Do not edit manually"; direct hand-editing during a separate ticket is not the correct mechanism.
- **No commits**: All verification passes → close the issue. Any failed check → investigate divergence from `main` before acting.

## Tech Stack

Shell (`bash`, `grep`, `awk`, `git log`) for verification; `gh` CLI for issue closure.

## File Structure

| File | Action |
|------|--------|
| `.archon/memory/dark-factory-ops.md` | Read-only (verify content, do not modify) |

---

## Task 1: Verify the Three [PATTERN] Entries Are Present

**Files:** `.archon/memory/dark-factory-ops.md`

### Steps

**Step 1 — Count metadata occurrences** (should be exactly 3 from #436):

```bash
grep -c "issue:#436 date:2026-06-14 expires:2026-12-14 source:implement" \
  .archon/memory/dark-factory-ops.md
# Expected output: 3
```

**Step 2 — Verify BuildKit build path entry** (must contain `moby/buildkit` and `--load`):

```bash
grep -n "moby/buildkit\|buildx build.*buildkit" .archon/memory/dark-factory-ops.md
# Expected: one line under ## Preview Stack, tagged [PATTERN], with issue:#436 metadata
```

**Step 3 — Verify migrate service entrypoint override entry**:

```bash
grep -n "alembic.*upgrade.*head\|migrate.*service must override" \
  .archon/memory/dark-factory-ops.md
# Expected: one [PATTERN] line with depends_on/service_completed_successfully and issue:#436 metadata
```

**Step 4 — Verify health polling via docker inspect entry**:

```bash
grep -n "docker inspect.*Health.Status\|EXEC:0.*socket proxy" \
  .archon/memory/dark-factory-ops.md
# Expected: one [PATTERN] line with issue:#436 metadata (not the [INVALID] EXEC:0 line)
```

**Step 5 — Confirm all three appear under `## Preview Stack` heading**:

```bash
awk '/^## Preview Stack/,/^## [^P]/' .archon/memory/dark-factory-ops.md | \
  grep "issue:#436" | wc -l
# Expected output: 3
```

**Accept criteria:** All three `[PATTERN]` entries with `issue:#436 date:2026-06-14 expires:2026-12-14 source:implement` are present under `## Preview Stack`. No commit needed — proceed to Task 2.

---

## Task 2: Verify the Three Stale Entries Are Absent

**Files:** `.archon/memory/dark-factory-ops.md`

The three dropped entries are: (1) bootstrap `[AVOID]` about embedding data in Alembic migrations (expired 2026-06-02); (2) `[PATTERN]` from issue #206 about writing out-of-scope defects to `$ARTIFACTS_DIR/out-of-scope.md` under the now-removed `## Scope Enforcement` heading; (3) `[PATTERN]` from issue #171 about exact line numbers in refinement plans under the now-removed `## Plan Drift` heading.

### Steps

**Step 1 — Confirm Alembic embed-data bootstrap entry is gone**:

```bash
grep -c "embed data directly in Alembic migration" .archon/memory/dark-factory-ops.md
# Expected output: 0
```

**Step 2 — Confirm Scope Enforcement / out-of-scope.md entry is gone**:

```bash
grep -c "out-of-scope defect.*out-of-scope\.md\|ARTIFACTS_DIR.*out-of-scope" \
  .archon/memory/dark-factory-ops.md
# Expected output: 0
```

**Step 3 — Confirm Plan Drift / exact line numbers entry is gone**:

```bash
grep -c "refinement plan specifies exact line numbers\|Plan Drift" \
  .archon/memory/dark-factory-ops.md
# Expected output: 0
```

**Step 4 — Confirm the `## Scope Enforcement` and `## Plan Drift` section headings are gone**:

```bash
grep -c "^## Scope Enforcement\|^## Plan Drift" .archon/memory/dark-factory-ops.md
# Expected output: 0
```

**Accept criteria:** All four searches return 0. No commit needed — proceed to Task 3.

---

## Task 3: Confirm the [INVALID] Entry (#379) Is Untouched

**Files:** `.archon/memory/dark-factory-ops.md`

The `[INVALID]` entry at the bottom of the file (factory proxy / `EXEC=1` note) predates #436 and must not have been modified by the #436 memory commit.

### Steps

**Step 1 — Confirm the [INVALID] #379 entry is present**:

```bash
grep -n "INVALID: factory proxy now has EXEC=1 as of issue #379" \
  .archon/memory/dark-factory-ops.md
# Expected: one line — e.g., line 87: "- [INVALID: factory proxy now has EXEC=1 as of issue #379] ..."
```

**Step 2 — Confirm it was not introduced or last modified by the #436 commit**:

```bash
git log --all --oneline --diff-filter=M -- .archon/memory/dark-factory-ops.md | head -5
# The most recent commit touching this file should be the #436 memory commit (92207ab).
# To verify the [INVALID] #379 line existed before #436, check the parent commit:
COMMIT=$(git log --oneline --grep="#436" --all -- .archon/memory/dark-factory-ops.md \
  | head -1 | awk '{print $1}')
git show "${COMMIT}^:.archon/memory/dark-factory-ops.md" 2>/dev/null | \
  grep "INVALID: factory proxy now has EXEC=1 as of issue #379" | wc -l
# Expected output: 1 (entry existed in the parent commit before #436 touched the file)
```

**Accept criteria:** `[INVALID: factory proxy now has EXEC=1 as of issue #379]` is present and pre-dates the #436 memory commit. No commit needed — proceed to Task 4.

---

## Task 4: Close the Issue

**Files:** None (GitHub CLI only)

All four spec conditions pass. Per the spec: "If all four checks pass, close the ticket with no commits."

### Steps

**Step 1 — Close issue #517 with a verification summary**:

```bash
gh issue close 517 --repo omniscient/markethawk \
  --comment "All four verification checks passed — no modifications made.

✅ **Check 1:** 3 BuildKit/preview \`[PATTERN]\` entries present under \`## Preview Stack\` with \`issue:#436 date:2026-06-14 expires:2026-12-14 source:implement\` metadata.
✅ **Check 2:** 3 stale entries absent — Alembic bootstrap \`[AVOID]\`, Scope Enforcement \`[PATTERN]\` (#206), Plan Drift \`[PATTERN]\` (#171).
✅ **Check 3:** \`[INVALID]\` entry for issue #379 (\`EXEC=1\`) present and untouched.
✅ **Check 4:** No modifications made to \`.archon/memory/dark-factory-ops.md\`.

Implementation complete — verification-only, zero commits."
```

**Accept criteria:** Issue #517 is closed with the verification summary comment attached.
