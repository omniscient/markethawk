# Archive Write-Once Specs/Plans

> Tracking issue: [#173](https://github.com/omniscient/markethawk/issues/173)

## Goal

`docs/superpowers/specs/` holds 18 specs and `docs/superpowers/plans/` holds 13 plans. These
files are write-once: the refinement pipeline creates them, they are committed to the feature
branch, reviewed, and never written again after the feature ships. Parking them in the active
docs tree creates three problems:

1. **Agent grep noise** — ~13K lines of dead plans appear in every codebase search.
2. **False "current" signal** — files dated months ago look like living documentation.
3. **Pairing rot** — 8 specs have no paired plan; 3 plans reference non-existent specs; date
   mismatches and `-v2` suffixes hint at inconsistent editing.

This change keeps only in-flight specs/plans in the active tree. Shipped ones move to
`docs/archive/`. A self-maintaining hook in `archon-dark-factory.yaml` ensures no future
implementation PR can leak a new spec/plan into the active tree.

## Scope

**In scope:**
- `docs/archive/` — new home for shipped specs/plans.
- Initial cleanup: `git mv` all 31 current files to `docs/archive/` in one commit.
- Cross-reference update: fix the one active-docs link (`docs/ai-development.md`) that points
  to a spec being moved, and update the description in `docs/agents/domain.md`.
- Archive-on-PR step in `archon-dark-factory.yaml` `push-and-pr` node: detects and archives
  the spec and plan for the current issue before `git push`.

**Out of scope (YAGNI):**
- Changing the write paths in `.archon/commands/dark-factory-refine.md` or
  `dark-factory-plan.md` — they continue writing to `docs/superpowers/specs|plans/` (correct
  during in-flight work; the archive step handles cleanup at PR time).
- An `docs/archive/README.md` index — git log and the closed issues serve as the catalogue.
- Archiving at plan-branch-push time — the plan is still useful for human review at that stage.
- Retroactively fixing orphaned specs (8 specs without plans) — cleanup moves them all.

## Architecture

### Archive step placement

The archive step runs **inside `push-and-pr`**, immediately before `git push`. This means:

- The archived files are included in the implementation PR diff — reviewers see the spec/plan
  move alongside the code.
- The commit is atomic with the push — no orphaned spec if the push fails.
- `docs/superpowers/specs|plans/` is clean after merge, ready for the next in-flight feature.

### Detection mechanism

Spec and plan files for a given issue are found by grepping for the issue number:

```bash
SPEC_FILE=$(grep -rl "#${ISSUE}" docs/superpowers/specs/ 2>/dev/null | head -1)
PLAN_FILE=$(grep -rl "#${ISSUE}" docs/superpowers/plans/ 2>/dev/null | head -1)
```

This works because:
- **Spec files** (post-pipeline): contain `> Tracking issue: [#NNN](...)` on line 3.
- **Plan files**: contain `**Issue:** [#NNN](...)` in the header block.

The search is a no-op when either directory is empty or has no matching file (old-style
implementations, `2>/dev/null` suppresses the empty-directory warning).

### Initial cleanup: all 31 files

All current contents of both directories are shipped (the most recent spec belongs to issue
#178, merged as PR #180). There are no in-flight features at the time issue #173 ships. A
single `git mv` sweep moves all 31 files in one atomic commit.

### Cross-reference audit

Two active docs reference a spec path:

| File | Reference | Resolution |
|------|-----------|------------|
| `docs/ai-development.md:168` | Links to `superpowers/specs/2026-05-02-dark-factory-design.md` | Update link to `archive/2026-05-02-dark-factory-design.md` |
| `docs/agents/domain.md:27` | States the directory "contains feature specifications" | Update to describe the in-flight convention |

All other cross-references are inside the specs/plans themselves and move with the files.

## Requirements

- **R1** After any implementation PR merges, `docs/superpowers/specs/` and
  `docs/superpowers/plans/` contain only specs/plans whose issue is still in-flight.
- **R2** Shipped specs/plans are reachable at `docs/archive/<original-filename>`.
- **R3** The archive step is a no-op when no spec or plan file contains the issue number
  (old-style run, or already archived).
- **R4** The archive commit is distinct from the implementation commits (separate
  `git commit` step).
- **R5** No active docs file outside `docs/superpowers/specs|plans/` contains a broken
  link to a moved file after the cleanup.

## Alternatives Considered

### Rely solely on git history (delete, no archive dir)
Simpler: just `git rm` shipped files. Git history and closed issues are the record. Rejected
because browsing `docs/archive/` is lower friction than `git show` or `git log --diff-filter=D`.

### Archive after merge (post-merge GitHub Action)
Clean separation: active tree stays clean during review. Rejected because adding a GitHub Action
for this is disproportionate overhead. Pre-push archiving in `push-and-pr` achieves the same end
state with a single bash block edit.

### Change write path to docs/archive/ directly
Have the refine/plan commands write to `docs/archive/` from the start. Simpler long-term but
reduces visibility during review (spec buried in archive before anyone reads it). Current flow
(active tree during in-flight → archived at PR time) is more legible.

## Assumptions

- All 31 current files in `docs/superpowers/specs/` and `docs/superpowers/plans/` are shipped.
- The `push-and-pr` node's `when` guard already limits execution to `new`/`continue` intents.
- `git mv` preserves history; `git log --follow` will trace a moved file back through its origin.
