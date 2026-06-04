# Archive Write-Once Specs/Plans — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move 31 shipped specs/plans out of the active docs tree into `docs/archive/`, fix two
active-docs cross-references, and add a self-maintaining archive-on-PR step to the dark factory
`push-and-pr` node so no future implementation run leaves historical residue in the active tree.

**Architecture:** Initial bulk `git mv` + cross-reference fix → YAML edit that prepends an
archive bash block before `git push` in `push-and-pr`.

**Tech Stack:** Bash, YAML (Archon workflow), Markdown

**Spec:** [`docs/superpowers/specs/2026-06-04-archive-write-once-docs-design.md`](../specs/2026-06-04-archive-write-once-docs-design.md)
**Issue:** [#173](https://github.com/omniscient/markethawk/issues/173)

---

## File Structure

| Path | Change |
|------|--------|
| `docs/archive/` | New directory (created by first `git mv`) |
| `docs/superpowers/specs/*.md` | Moved to `docs/archive/` (all 18 files) |
| `docs/superpowers/plans/*.md` | Moved to `docs/archive/` (all 13 files) |
| `docs/ai-development.md` | Fix link: `superpowers/specs/…` → `archive/…` |
| `docs/agents/domain.md` | Update description of `docs/superpowers/specs/` |
| `.archon/workflows/archon-dark-factory.yaml` | Add archive block to `push-and-pr` node |

---

## Task 1 — Move all shipped specs/plans to docs/archive/

**Files:** `docs/superpowers/specs/*.md`, `docs/superpowers/plans/*.md`, `docs/archive/` (new)

### Steps

- [ ] 1.1 Verify there are no in-flight files (confirms all can be safely archived):

  ```bash
  ls docs/superpowers/specs/ | wc -l   # expect 18
  ls docs/superpowers/plans/ | wc -l   # expect 13
  ```

- [ ] 1.2 Create the archive directory and move all specs:

  ```bash
  mkdir -p docs/archive
  git mv docs/superpowers/specs/*.md docs/archive/
  ```

  Expected: `git status` shows 18 renames from `docs/superpowers/specs/` to `docs/archive/`.

- [ ] 1.3 Move all plans:

  ```bash
  git mv docs/superpowers/plans/*.md docs/archive/
  ```

  Expected: `git status` shows 13 additional renames.

- [ ] 1.4 Verify the active directories are now empty:

  ```bash
  ls docs/superpowers/specs/   # should be empty
  ls docs/superpowers/plans/   # should be empty
  ```

- [ ] 1.5 Commit:

  ```bash
  git add docs/archive/ docs/superpowers/
  git commit -m "docs(#173): move 31 shipped specs/plans to docs/archive/"
  ```

---

## Task 2 — Fix cross-references in active docs

**Files:** `docs/ai-development.md`, `docs/agents/domain.md`

### Steps

- [ ] 2.1 Read the current line in `docs/ai-development.md`:

  ```bash
  grep -n "superpowers/specs" docs/ai-development.md
  ```

  Expected output:

  ```
  168:See [dark factory design spec](superpowers/specs/2026-05-02-dark-factory-design.md) for the full architecture, security model, and container topology.
  ```

- [ ] 2.2 Update the link to point to the archive:

  In `docs/ai-development.md`, find the line and change:

  ```
  superpowers/specs/2026-05-02-dark-factory-design.md
  ```

  to:

  ```
  archive/2026-05-02-dark-factory-design.md
  ```

- [ ] 2.3 Read the current line in `docs/agents/domain.md`:

  ```bash
  grep -n "superpowers/specs" docs/agents/domain.md
  ```

  Expected output:

  ```
  27:Note: `docs/superpowers/specs/` contains feature specifications and implementation plans — these are *not* ADRs. ADRs record architectural decisions and their rationale; specs describe what to build.
  ```

- [ ] 2.4 Update the description to reflect the in-flight-only convention. Replace the line with:

  ```
  Note: `docs/superpowers/specs/` holds **in-flight** feature specifications; `docs/superpowers/plans/` holds **in-flight** implementation plans. Both are write-once artifacts — shipped specs/plans are archived to `docs/archive/` automatically when an implementation PR is created. These are *not* ADRs; ADRs record architectural decisions and their rationale.
  ```

- [ ] 2.5 Verify no other active docs reference the old spec path:

  ```bash
  grep -rn "superpowers/specs/\|superpowers/plans/" docs/ \
    --include="*.md" \
    | grep -v "^docs/superpowers/\|^docs/archive/"
  ```

  Expected: no output (all cross-references fixed).

- [ ] 2.6 Commit:

  ```bash
  git add docs/ai-development.md docs/agents/domain.md
  git commit -m "docs(#173): fix cross-references to archived spec files"
  ```

---

## Task 3 — Add archive-on-PR step to archon-dark-factory.yaml

**Files:** `.archon/workflows/archon-dark-factory.yaml`

### Steps

- [ ] 3.1 Locate the `push-and-pr` bash block in the YAML. Confirm the block begins with:

  ```bash
  ISSUE=$(echo $fetch-issue.output | jq -r '.resolved_number')
  ```

  and contains the `git push` call approximately 10 lines later:

  ```bash
  if ! git push -u origin "$BRANCH"; then
  ```

- [ ] 3.2 Insert the following archive block into the `push-and-pr` bash section, immediately
  before the `if ! git push -u origin "$BRANCH"; then` line:

  ```bash
  # Archive spec/plan for this issue before pushing
  SPEC_FILE=$(grep -rl "#${ISSUE}" docs/superpowers/specs/ 2>/dev/null | head -1)
  PLAN_FILE=$(grep -rl "#${ISSUE}" docs/superpowers/plans/ 2>/dev/null | head -1)

  ARCHIVED=0
  if [ -n "$SPEC_FILE" ]; then
    mkdir -p docs/archive
    git mv "$SPEC_FILE" docs/archive/
    ARCHIVED=$((ARCHIVED + 1))
    echo "Archived spec: $SPEC_FILE -> docs/archive/"
  fi
  if [ -n "$PLAN_FILE" ]; then
    mkdir -p docs/archive
    git mv "$PLAN_FILE" docs/archive/
    ARCHIVED=$((ARCHIVED + 1))
    echo "Archived plan: $PLAN_FILE -> docs/archive/"
  fi

  if [ "$ARCHIVED" -gt 0 ]; then
    git commit -m "docs: archive spec/plan for issue #${ISSUE}"
  fi

  ```

- [ ] 3.3 Verify the YAML is syntactically valid after the edit:

  ```bash
  python3 -c "import yaml, sys; yaml.safe_load(open('.archon/workflows/archon-dark-factory.yaml'))" \
    && echo "YAML OK"
  ```

  Expected: `YAML OK`

- [ ] 3.4 Smoke-test the detection logic with the in-flight spec for issue #173:

  ```bash
  ISSUE=173
  SPEC_FILE=$(grep -rl "#${ISSUE}" docs/superpowers/specs/ 2>/dev/null | head -1)
  PLAN_FILE=$(grep -rl "#${ISSUE}" docs/superpowers/plans/ 2>/dev/null | head -1)
  echo "SPEC: $SPEC_FILE"
  echo "PLAN: $PLAN_FILE"
  ```

  Expected:

  ```
  SPEC: docs/superpowers/specs/2026-06-04-archive-write-once-docs-design.md
  PLAN: docs/superpowers/plans/2026-06-04-archive-write-once-docs.md
  ```

  (These are the spec/plan for the current issue — they will be auto-archived when the implementation PR for #173 is created.)

- [ ] 3.5 Smoke-test the no-op path (an issue with no spec/plan in the active tree):

  ```bash
  ISSUE=99999
  SPEC_FILE=$(grep -rl "#${ISSUE}" docs/superpowers/specs/ 2>/dev/null | head -1)
  PLAN_FILE=$(grep -rl "#${ISSUE}" docs/superpowers/plans/ 2>/dev/null | head -1)
  echo "SPEC: '${SPEC_FILE}'"
  echo "PLAN: '${PLAN_FILE}'"
  ```

  Expected:

  ```
  SPEC: ''
  PLAN: ''
  ```

  The `if [ -n "" ]` guards ensure `git mv` is never called with an empty path.

- [ ] 3.6 Commit:

  ```bash
  git add .archon/workflows/archon-dark-factory.yaml
  git commit -m "feat(#173): archive spec/plan in push-and-pr before git push"
  ```

---

## Validation

- [ ] Run the YAML validity check from Task 3.3 one final time.
- [ ] Confirm `docs/superpowers/specs/` and `docs/superpowers/plans/` now contain only the
  spec and plan for issue #173 (written by the refine/plan phases of this run):

  ```bash
  ls docs/superpowers/specs/
  ls docs/superpowers/plans/
  ```

  Expected: one file each (the #173 spec and plan).

- [ ] Confirm `docs/archive/` contains 31 files:

  ```bash
  ls docs/archive/ | wc -l   # expect 31
  ```

- [ ] No active docs link is broken:

  ```bash
  grep -rn "superpowers/specs/\|superpowers/plans/" docs/ \
    --include="*.md" \
    | grep -v "^docs/superpowers/\|^docs/archive/"
  ```

  Expected: no output.
