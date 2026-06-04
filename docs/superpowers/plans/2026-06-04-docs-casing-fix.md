# Implementation Plan: Docs/ → docs/ Casing Fix

**Goal**: Rename `Docs/` to `docs/` so lowercase links in CLAUDE.md and domain.md resolve on Linux (dark-factory). Fix all remaining capital-D `Docs/` references in operational files.

**Issue**: #171  
**Spec**: [`Docs/superpowers/specs/2026-06-04-docs-casing-fix-design.md`](../specs/2026-06-04-docs-casing-fix-design.md)  
**Date**: 2026-06-04  
**Architecture**: Pure docs/config rename — no backend, no frontend, no migrations.  
**Tech Stack**: git, bash

## File Structure

| Before | After |
|--------|-------|
| `Docs/adr/` | `docs/adr/` |
| `Docs/agents/` | `docs/agents/` |
| `Docs/superpowers/` | `docs/superpowers/` |
| `Docs/scanner-validation/` | `docs/scanner-validation/` |
| `Docs/presentations/` | `docs/presentations/` |
| `Docs/database-schema.md` | `docs/database-schema.md` |
| `Docs/database-schema.html` | `docs/database-schema.html` |
| `Docs/Diagram.md` | `docs/Diagram.md` |
| `docs/codeindex-hotspots.md` | `docs/codeindex-hotspots.md` (unchanged) |

**Files modified (reference fixes):**
- `CLAUDE.md`
- `.archon/commands/dark-factory-conformance.md`
- `.archon/commands/dark-factory-implement.md`
- `.archon/commands/dark-factory-plan.md`
- `.archon/commands/dark-factory-refine.md`
- `.claude/skills/refinement/orchestrator-prompt.md`
- `.claude/skills/validate-scanner/SKILL.md`

---

## Task 1 — Pre-flight: verify broken state

**Files**: none (read-only checks)  
**Purpose**: Confirm the problem exists before changing anything.

### Steps

1. **Confirm both directories exist**
   ```bash
   ls -d /workspace/markethawk/Docs /workspace/markethawk/docs
   # Expected: both paths printed, no error
   ```

2. **Confirm `docs/` already has one file**
   ```bash
   find /workspace/markethawk/docs -type f
   # Expected: docs/codeindex-hotspots.md
   ```

3. **Confirm the 6 broken lowercase refs in CLAUDE.md do not resolve**
   ```bash
   cd /workspace/markethawk
   test -f docs/superpowers/specs/2026-05-02-dark-factory-design.md && echo "EXISTS" || echo "BROKEN"
   test -f docs/agents/issue-tracker.md && echo "EXISTS" || echo "BROKEN"
   test -f docs/agents/triage-labels.md && echo "EXISTS" || echo "BROKEN"
   test -f docs/agents/domain.md          && echo "EXISTS" || echo "BROKEN"
   # Expected: all 4 print "BROKEN"
   ```

4. **Record the capital-D `Docs/` reference count** (should be >0 before fix)
   ```bash
   grep -rn "Docs/" /workspace/markethawk --include="*.md" --include="*.yml" --include="*.yaml" \
     | grep -v "^Binary\|/.git/\|/Docs/" | wc -l
   # Expected: ≥ 9 (the known references outside Docs/)
   ```

---

## Task 2 — git mv: rename Docs/ contents into docs/

**Files**: all files under `Docs/`, all moved to `docs/`  
**Constraint**: `docs/` already has `codeindex-hotspots.md` — do NOT delete it. Move subdirectories and loose files individually.

### Steps

1. **Verify working tree is clean** (git mv requires a clean state)
   ```bash
   cd /workspace/markethawk
   git status --short
   # Expected: only the untracked seed files (dark-factory seed work); no modified tracked files
   ```

2. **Move subdirectories**
   ```bash
   cd /workspace/markethawk
   git mv Docs/adr            docs/adr
   git mv Docs/agents         docs/agents
   git mv Docs/superpowers    docs/superpowers
   git mv Docs/scanner-validation docs/scanner-validation
   git mv Docs/presentations  docs/presentations
   ```

3. **Move loose files from Docs/**
   ```bash
   cd /workspace/markethawk
   git mv Docs/database-schema.md   docs/database-schema.md
   git mv Docs/database-schema.html docs/database-schema.html
   git mv Docs/Diagram.md           docs/Diagram.md
   ```

4. **Verify Docs/ is now empty and gone**
   ```bash
   ls /workspace/markethawk/Docs 2>&1
   # Expected: "ls: cannot access '/workspace/markethawk/Docs': No such file or directory"
   # (git mv of the last file removes the empty directory automatically)
   ```

5. **Verify docs/ now contains all expected subdirectories**
   ```bash
   ls /workspace/markethawk/docs/
   # Expected: adr  agents  codeindex-hotspots.md  database-schema.html  database-schema.md  Diagram.md  presentations  scanner-validation  superpowers
   ```

6. **Verify the 4 previously-broken CLAUDE.md lowercase refs now resolve**
   ```bash
   cd /workspace/markethawk
   test -f docs/superpowers/specs/2026-05-02-dark-factory-design.md && echo "OK" || echo "FAIL"
   test -f docs/agents/issue-tracker.md && echo "OK" || echo "FAIL"
   test -f docs/agents/triage-labels.md && echo "OK" || echo "FAIL"
   test -f docs/agents/domain.md        && echo "OK" || echo "FAIL"
   # Expected: all 4 print "OK"
   ```

7. **Commit the rename**
   ```bash
   cd /workspace/markethawk
   git add -A
   git commit -m "$(cat <<'EOF'
   docs(#171): git mv Docs/ → docs/ — unify casing for Linux compatibility

   Moves all 48 files from capital-D Docs/ into lowercase docs/ so that
   the six lowercase docs/ references already present in CLAUDE.md and
   domain.md resolve correctly inside Linux dark-factory containers.

   docs/codeindex-hotspots.md (the pre-existing file) is untouched.

   Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
   EOF
   )"
   ```

   Expected output: `[refine/issue-171-...] docs(#171): git mv Docs/ → docs/...` with `48 files changed`.

---

## Task 3 — Fix capital-D Docs/ references in CLAUDE.md

**Files**: `CLAUDE.md`  
**Why**: After the rename, the one remaining `Docs/` reference in CLAUDE.md (line 305) is now broken. The 6 lowercase refs already work.

### Steps

1. **Verify the broken reference**
   ```bash
   grep -n "Docs/" /workspace/markethawk/CLAUDE.md
   # Expected: line 305: - [Docs/database-schema.md](Docs/database-schema.md)
   ```

2. **Fix it**

   In `CLAUDE.md`, line 305 — change:
   ```
   - [Docs/database-schema.md](Docs/database-schema.md) — auto-generated database schema ERD and indices
   ```
   to:
   ```
   - [docs/database-schema.md](docs/database-schema.md) — auto-generated database schema ERD and indices
   ```

3. **Verify no more Docs/ in CLAUDE.md**
   ```bash
   grep "Docs/" /workspace/markethawk/CLAUDE.md
   # Expected: no output
   ```

4. **Commit**
   ```bash
   cd /workspace/markethawk
   git add CLAUDE.md
   git commit -m "$(cat <<'EOF'
   docs(#171): fix capital-D Docs/ reference in CLAUDE.md

   Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
   EOF
   )"
   ```

---

## Task 4 — Fix capital-D Docs/ references in operational agent files

**Files**: `.archon/commands/dark-factory-conformance.md`, `.archon/commands/dark-factory-implement.md`, `.archon/commands/dark-factory-plan.md`, `.archon/commands/dark-factory-refine.md`, `.claude/skills/refinement/orchestrator-prompt.md`, `.claude/skills/validate-scanner/SKILL.md`

**Why**: These files are actively read by dark-factory agents. A capital-D `Docs/` reference in an agent command will cause the agent to look for a path that no longer exists on Linux.

### Steps

1. **Audit all remaining Docs/ references outside docs/**
   ```bash
   grep -rn "Docs/" /workspace/markethawk --include="*.md" --include="*.yml" --include="*.yaml" \
     | grep -v "^Binary\|/.git/\|/docs/" | grep -v "superpowers/plans/\|superpowers/specs/"
   # Expected: hits in .archon/commands/ and .claude/skills/ only
   ```

2. **Fix `.archon/commands/dark-factory-conformance.md`**

   Three occurrences — change each `Docs/superpowers/` to `docs/superpowers/`:
   - Line containing: `look for any linked file under \`Docs/superpowers/specs/\``  
     → `look for any linked file under \`docs/superpowers/specs/\``
   - Line containing: `### 2c. Scan Docs/superpowers/specs/`  
     → `### 2c. Scan docs/superpowers/specs/`
   - Line containing: `ls Docs/superpowers/specs/ 2>/dev/null | sort -r | head -10`  
     → `ls docs/superpowers/specs/ 2>/dev/null | sort -r | head -10`

3. **Fix `.archon/commands/dark-factory-implement.md`**

   One occurrence:
   - Line containing: `\`Docs/database-schema.md\` is auto-generated`  
     → `\`docs/database-schema.md\` is auto-generated`

4. **Fix `.archon/commands/dark-factory-plan.md`**

   Two occurrences:
   - Line containing: `look in \`Docs/superpowers/specs/\``  
     → `look in \`docs/superpowers/specs/\``
   - Line containing: `Save to \`Docs/superpowers/plans/YYYY-MM-DD-<feature>.md\``  
     → `Save to \`docs/superpowers/plans/YYYY-MM-DD-<feature>.md\``

5. **Fix `.archon/commands/dark-factory-refine.md`**

   Two occurrences:
   - Line containing: `Write the spec to \`Docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md\``  
     → `Write the spec to \`docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md\``
   - Line containing: `Spec link: \`https://github.com/omniscient/markethawk/blob/$BRANCH/<spec-file-path>\` (e.g. \`Docs/superpowers/specs/...`  
     → `(e.g. \`docs/superpowers/specs/...`

6. **Fix `.claude/skills/refinement/orchestrator-prompt.md`**

   One occurrence:
   - Line containing: `Write the spec to \`Docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md\``  
     → `Write the spec to \`docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md\``

7. **Fix `.claude/skills/validate-scanner/SKILL.md`**

   Four occurrences — change each `Docs/scanner-validation/` to `docs/scanner-validation/`:
   - Line 65: cursor file path
   - Line 287: read cursor from path
   - Line 288: list available *.json files
   - Line 328: mkdir -p line

8. **Verify no more Docs/ references in operational files**
   ```bash
   grep -rn "Docs/" /workspace/markethawk --include="*.md" --include="*.yml" --include="*.yaml" \
     | grep -v "^Binary\|/.git/\|/docs/" | grep -v "superpowers/plans/\|superpowers/specs/"
   # Expected: no output
   ```

9. **Commit**
   ```bash
   cd /workspace/markethawk
   git add .archon/commands/dark-factory-conformance.md \
           .archon/commands/dark-factory-implement.md \
           .archon/commands/dark-factory-plan.md \
           .archon/commands/dark-factory-refine.md \
           .claude/skills/refinement/orchestrator-prompt.md \
           .claude/skills/validate-scanner/SKILL.md
   git commit -m "$(cat <<'EOF'
   docs(#171): fix Docs/ → docs/ in agent commands and skill files

   Updates all hard-coded Docs/ references in .archon/commands/ and
   .claude/skills/ so dark-factory agents find the correct paths after
   the directory rename.

   Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
   EOF
   )"
   ```

---

## Task 5 — Final verification

**Files**: none (read-only)

### Steps

1. **Full Docs/ scan — should be zero hits in non-historical files**
   ```bash
   grep -rn "Docs/" /workspace/markethawk --include="*.md" --include="*.yml" --include="*.yaml" \
     | grep -v "^Binary\|/.git/\|/docs/" | grep -v "superpowers/plans/\|superpowers/specs/"
   # Expected: no output
   ```

2. **All CLAUDE.md docs/ links resolve**
   ```bash
   cd /workspace/markethawk
   for f in \
     "docs/superpowers/specs/2026-05-02-dark-factory-design.md" \
     "docs/codeindex-hotspots.md" \
     "docs/agents/issue-tracker.md" \
     "docs/agents/triage-labels.md" \
     "docs/agents/domain.md" \
     "docs/database-schema.md"; do
     test -f "$f" && echo "OK: $f" || echo "FAIL: $f"
   done
   # Expected: all 6 print "OK: ..."
   ```

3. **domain.md links resolve** (it references `docs/adr/` and `docs/agents/`)
   ```bash
   cd /workspace/markethawk
   test -d docs/adr     && echo "OK: docs/adr"     || echo "FAIL: docs/adr"
   test -d docs/agents  && echo "OK: docs/agents"  || echo "FAIL: docs/agents"
   test -d docs/superpowers && echo "OK: docs/superpowers" || echo "FAIL: docs/superpowers"
   # Expected: all 3 print "OK"
   ```

4. **codeindex-hotspots.md still exists**
   ```bash
   test -f /workspace/markethawk/docs/codeindex-hotspots.md && echo "OK" || echo "FAIL"
   # Expected: OK
   ```

5. **Docs/ is gone**
   ```bash
   ls /workspace/markethawk/Docs 2>&1
   # Expected: "No such file or directory"
   ```
