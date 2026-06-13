# Plan: Plan/Refine Scope Enforcement — issue #390

**Date**: 2026-06-13
**Issue**: [#390](https://github.com/omniscient/markethawk/issues/390) — Plan stage implemented the full feature on the refine branch (#339) instead of stopping at the plan
**Spec**: [`docs/superpowers/specs/2026-06-13-plan-refine-scope-enforcement-design.md`](docs/superpowers/specs/2026-06-13-plan-refine-scope-enforcement-design.md)

## Goal

Add two-layer scope enforcement to `dark-factory-plan.md` and `dark-factory-refine.md` so agents operating in the plan/refine stages cannot accidentally implement code on the refinement branch:

- **Layer 1 (prompt prohibition)**: A `## SCOPE BOUNDARY` notice at the top of each command file, before Phase 1, giving the agent its scope constraint before it reads anything else.
- **Layer 2 (mechanical gate)**: A pre-commit shell block that scans `git diff --name-only origin/main HEAD` (two-dot, per `codebase-patterns.md`), reverts any files outside the allowlist, writes them to `$ARTIFACTS_DIR/out-of-scope.md`, and continues publishing — matching `conformance.excise_out_of_scope: true`.

## Architecture

Changes are confined to two command prompt files in `.archon/commands/`. No new services, models, packages, or image rebuilds required — `.archon/commands/` files are read from the cloned repo at runtime (per `dark-factory-ops.md` Container Root and Mounts pattern).

The OOS gate follows the established Scope Enforcement pattern from `dark-factory-ops.md`: write to `$ARTIFACTS_DIR/out-of-scope.md` with `- <file>: <description>` format so the scheduler's scope-spillover mechanism can auto-file backlog tickets.

## Tech Stack

Bash shell embedded in markdown command files. `git diff --name-only origin/main HEAD` (two-dot form), `git checkout origin/main -- <file>`, `git rm -f --cached`, `git commit --allow-empty`. No Python, no new dependencies.

## File Structure

| File | Change |
|---|---|
| `.archon/commands/dark-factory-plan.md` | Add SCOPE BOUNDARY before Phase 1 + OOS gate in Phase 4 (before commit) |
| `.archon/commands/dark-factory-refine.md` | Add SCOPE BOUNDARY before Phase 1 + OOS gate in Phase 5 (before spec commit) |

---

## Task 1: Add SCOPE BOUNDARY notice to dark-factory-plan.md

**Files**: `.archon/commands/dark-factory-plan.md`

### Step 1 — Write failing test

```bash
grep -c 'SCOPE BOUNDARY' .archon/commands/dark-factory-plan.md
# Expected: 0
```

### Step 2 — Verify fail

Run the command and confirm output is `0`.

### Step 3 — Implement

Edit `.archon/commands/dark-factory-plan.md`. Find this exact block (the `---` separator before Phase 1):

```
---

## Phase 1: LOAD
```

Replace it with:

```
---

## SCOPE BOUNDARY

This command's only authorized file outputs are:
- Documents under `docs/superpowers/plans/` (the plan file)

Do NOT create or modify any other files. Do NOT implement code, write tests, or edit configuration.
Implementation belongs to the `Fix issue #N` workflow on a `feat/issue-N-*` branch.

---

## Phase 1: LOAD
```

### Step 4 — Verify pass

```bash
grep -c 'SCOPE BOUNDARY' .archon/commands/dark-factory-plan.md
# Expected: 1

grep -c 'docs/superpowers/plans/' .archon/commands/dark-factory-plan.md
# Expected: ≥1 (appears in SCOPE BOUNDARY section)
```

### Step 5 — Commit

```bash
git add .archon/commands/dark-factory-plan.md
git commit -m "feat: add SCOPE BOUNDARY notice to dark-factory-plan.md (#390)"
# Expected: [branch <hash>] feat: add SCOPE BOUNDARY notice to dark-factory-plan.md (#390)
```

---

## Task 2: Add OOS gate + comment note to dark-factory-plan.md Phase 4

**Files**: `.archon/commands/dark-factory-plan.md`

### Step 1 — Write failing test

```bash
grep -c 'OOS gate' .archon/commands/dark-factory-plan.md
# Expected: 0

grep -c 'OOS excision' .archon/commands/dark-factory-plan.md
# Expected: 0

grep -c 'out-of-scope.md' .archon/commands/dark-factory-plan.md
# Expected: 0
```

### Step 2 — Verify fail

Run all three; confirm each outputs `0`.

### Step 3 — Implement

Edit `.archon/commands/dark-factory-plan.md`, Phase 4: PUBLISH. Two sub-edits:

**a) Insert OOS gate step before "Commit the plan".**

Find (in Phase 4):

```
4. Commit the plan
5. Post a summary comment on the issue:
```

Replace with:

```
4. Run the OOS gate — detect and revert any files committed outside the plan allowlist:
   ```bash
   ALLOWED_PREFIXES="docs/superpowers/plans/"
   OOS_FILES=$(git diff --name-only origin/main HEAD 2>/dev/null | while read -r f; do
     ALLOWED=false
     for prefix in $ALLOWED_PREFIXES; do
       case "$f" in "$prefix"*) ALLOWED=true; break;; esac
     done
     $ALLOWED || echo "$f"
   done)
   if [ -n "$OOS_FILES" ]; then
     echo "OOS gate: excising out-of-scope files: $OOS_FILES"
     for f in $OOS_FILES; do
       if git show origin/main:"$f" > /dev/null 2>&1; then
         git checkout origin/main -- "$f"
       else
         git rm -f --cached "$f" 2>/dev/null; rm -f "$f"
       fi
     done
     git commit -m "chore: excise out-of-scope files from plan run (#$ISSUE_NUM)" --allow-empty
     mkdir -p "$ARTIFACTS_DIR"
     echo "$OOS_FILES" | while read -r f; do
       echo "- $f: removed by plan OOS gate (should not have been created/modified)" >> "$ARTIFACTS_DIR/out-of-scope.md"
     done
   fi
   ```
5. Commit the plan
6. Post a summary comment on the issue:
```

**b) Update the Phase 4 comment template to note OOS excision.**

Find (inside the Phase 4 comment template, after the `**Branch:**` line):

```
   **Branch:** [`<BRANCH>`](https://github.com/omniscient/markethawk/tree/<BRANCH>)
   **Tasks:** <count> tasks, <total-steps> steps
```

Replace with:

```
   **Branch:** [`<BRANCH>`](https://github.com/omniscient/markethawk/tree/<BRANCH>)
   <!-- If OOS_FILES is non-empty, include this line: -->
   > ⚠️ **OOS excision**: The following files were created outside the plan scope and were reverted before publishing: `$OOS_FILES`. Scope-spillover tickets may be filed automatically.
   **Tasks:** <count> tasks, <total-steps> steps
```

**c) Renumber the final status step** from `7.` to `8.`:

Find:

```
7. Write status to `$ARTIFACTS_DIR/refinement-status.md`:
```

Replace with:

```
8. Write status to `$ARTIFACTS_DIR/refinement-status.md`:
```

### Step 4 — Verify pass

```bash
grep -c 'OOS gate' .archon/commands/dark-factory-plan.md
# Expected: 1

grep -c 'ALLOWED_PREFIXES' .archon/commands/dark-factory-plan.md
# Expected: 1

grep -c 'OOS excision' .archon/commands/dark-factory-plan.md
# Expected: 1

grep -c 'out-of-scope.md' .archon/commands/dark-factory-plan.md
# Expected: 1
```

### Step 5 — Commit

```bash
git add .archon/commands/dark-factory-plan.md
git commit -m "feat: add OOS gate to dark-factory-plan.md Phase 4 (#390)"
# Expected: [branch <hash>] feat: add OOS gate to dark-factory-plan.md Phase 4 (#390)
```

---

## Task 3: Add SCOPE BOUNDARY notice to dark-factory-refine.md

**Files**: `.archon/commands/dark-factory-refine.md`

### Step 1 — Write failing test

```bash
grep -c 'SCOPE BOUNDARY' .archon/commands/dark-factory-refine.md
# Expected: 0
```

### Step 2 — Verify fail

Run the command; confirm output is `0`.

### Step 3 — Implement

Edit `.archon/commands/dark-factory-refine.md`. The file has a `## CRITICAL: Skip Guard` section before Phase 1. Insert the SCOPE BOUNDARY between the Skip Guard block and Phase 1. Find:

```
## Phase 1: LOAD
```

Replace with:

```
## SCOPE BOUNDARY

This command's only authorized file outputs are:
- Documents under `docs/superpowers/specs/` (the spec file)
- Entries under `.archon/memory/` (optional architecture memory)

Do NOT create or modify any other files. Do NOT implement code, write tests, or edit configuration.

---

## Phase 1: LOAD
```

### Step 4 — Verify pass

```bash
grep -c 'SCOPE BOUNDARY' .archon/commands/dark-factory-refine.md
# Expected: 1

grep -c 'docs/superpowers/specs/' .archon/commands/dark-factory-refine.md
# Expected: ≥1

grep -c '.archon/memory/' .archon/commands/dark-factory-refine.md
# Expected: ≥1
```

### Step 5 — Commit

```bash
git add .archon/commands/dark-factory-refine.md
git commit -m "feat: add SCOPE BOUNDARY notice to dark-factory-refine.md (#390)"
# Expected: [branch <hash>] feat: add SCOPE BOUNDARY notice to dark-factory-refine.md (#390)
```

---

## Task 4: Add OOS gate + comment note to dark-factory-refine.md Phase 5

**Files**: `.archon/commands/dark-factory-refine.md`

The OOS gate runs in Phase 5 SPEC WRITING, immediately before the spec commit (step 5). At that point no legitimate commits have been made yet (spec and memory commits come after), so the gate catches any rogue commits from Phases 1-4. The existing step 5 (Commit the spec) becomes step 6; existing step 6 (Append memory entries) becomes step 7.

### Step 1 — Write failing test

```bash
grep -c 'OOS gate' .archon/commands/dark-factory-refine.md
# Expected: 0

grep -c 'OOS excision' .archon/commands/dark-factory-refine.md
# Expected: 0

grep -c 'out-of-scope.md' .archon/commands/dark-factory-refine.md
# Expected: 0
```

### Step 2 — Verify fail

Run all three; confirm each outputs `0`.

### Step 3 — Implement

Edit `.archon/commands/dark-factory-refine.md`. Two sub-edits:

**a) Insert OOS gate step before "Commit the spec" in Phase 5.**

Find (in Phase 5: SPEC WRITING):

```
4. Self-review: placeholder scan, consistency check, scope check, ambiguity check. Fix inline.
5. Commit the spec

6. Append memory entries to `.archon/memory/`:
```

Replace with:

```
4. Self-review: placeholder scan, consistency check, scope check, ambiguity check. Fix inline.
5. Run the OOS gate — detect and revert any files committed outside the refine allowlist:
   ```bash
   ALLOWED_PREFIXES="docs/superpowers/specs/ .archon/memory/"
   OOS_FILES=$(git diff --name-only origin/main HEAD 2>/dev/null | while read -r f; do
     ALLOWED=false
     for prefix in $ALLOWED_PREFIXES; do
       case "$f" in "$prefix"*) ALLOWED=true; break;; esac
     done
     $ALLOWED || echo "$f"
   done)
   if [ -n "$OOS_FILES" ]; then
     echo "OOS gate: excising out-of-scope files: $OOS_FILES"
     for f in $OOS_FILES; do
       if git show origin/main:"$f" > /dev/null 2>&1; then
         git checkout origin/main -- "$f"
       else
         git rm -f --cached "$f" 2>/dev/null; rm -f "$f"
       fi
     done
     git commit -m "chore: excise out-of-scope files from refine run (#$ISSUE_NUM)" --allow-empty
     mkdir -p "$ARTIFACTS_DIR"
     echo "$OOS_FILES" | while read -r f; do
       echo "- $f: removed by refine OOS gate (should not have been created/modified)" >> "$ARTIFACTS_DIR/out-of-scope.md"
     done
   fi
   ```
   Retain `$OOS_FILES` for use in the Phase 6 comment.
6. Commit the spec

7. Append memory entries to `.archon/memory/`:
```

**b) Update the Phase 6 comment template to note OOS excision.**

Find (inside the Phase 6 comment template, after the `**Branch:**` line):

```
   **Branch:** [`<BRANCH>`](https://github.com/omniscient/markethawk/tree/<BRANCH>)

   ### Summary
```

Replace with:

```
   **Branch:** [`<BRANCH>`](https://github.com/omniscient/markethawk/tree/<BRANCH>)
   <!-- If OOS_FILES is non-empty, include this line: -->
   > ⚠️ **OOS excision**: The following files were created outside the refine scope and were reverted before publishing: `$OOS_FILES`. Scope-spillover tickets may be filed automatically.

   ### Summary
```

**c) Renumber the final status step** in Phase 6 from `6.` to `6.` (no change needed — Phase 6 numbering is independent).

### Step 4 — Verify pass

```bash
grep -c 'OOS gate' .archon/commands/dark-factory-refine.md
# Expected: 1

grep -c 'ALLOWED_PREFIXES' .archon/commands/dark-factory-refine.md
# Expected: 1

grep -c 'OOS excision' .archon/commands/dark-factory-refine.md
# Expected: 1

grep -c 'out-of-scope.md' .archon/commands/dark-factory-refine.md
# Expected: 1
```

### Step 5 — Commit

```bash
git add .archon/commands/dark-factory-refine.md
git commit -m "feat: add OOS gate to dark-factory-refine.md Phase 5 (#390)"
# Expected: [branch <hash>] feat: add OOS gate to dark-factory-refine.md Phase 5 (#390)
```

---

## Summary

| Task | Files | Changes |
|---|---|---|
| 1 | `dark-factory-plan.md` | SCOPE BOUNDARY notice before Phase 1 |
| 2 | `dark-factory-plan.md` | OOS gate in Phase 4 + comment excision note |
| 3 | `dark-factory-refine.md` | SCOPE BOUNDARY notice before Phase 1 |
| 4 | `dark-factory-refine.md` | OOS gate in Phase 5 + comment excision note |

**Total**: 4 tasks, 20 steps. Defense-in-depth: Layer 1 (prompt) reduces probability of agent going out-of-scope; Layer 2 (gate) catches and reverts any OOS commits regardless, matching the established `conformance.excise_out_of_scope: true` philosophy.
