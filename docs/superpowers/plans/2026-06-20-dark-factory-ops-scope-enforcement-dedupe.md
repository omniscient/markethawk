# Plan: Update dark-factory-ops.md Scope Enforcement Entry (Issue #421)

**Date**: 2026-06-20
**Issue**: [#421](https://github.com/omniscient/markethawk/issues/421)
**Goal**: Replace the outdated "Scope Enforcement" `[PATTERN]` entry in `.archon/memory/dark-factory-ops.md` to describe the current `dedupe_oos.py` create / comment / suppress classification introduced in #384. No code changes.

---

## Architecture

This is a pure documentation change. The single target file is `.archon/memory/dark-factory-ops.md` — a machine-maintained advisory memory file read by implement agents at Phase 1 LOAD. The update replaces one bullet point in-place; every other entry in the file is untouched.

**Why this matters**: Implement agents that read the old entry believe a new `scope-spillover` ticket is always filed per OOS finding. Since #384 introduced `dedupe_oos.py`, the actual flow classifies findings as create / comment / suppress — so re-observed findings no longer spawn duplicate tickets. The stale entry could cause future agents to mis-describe behavior or over-create tickets.

## Tech Stack

No code changes. No migrations. No frontend or backend changes.

## Component

`.archon/memory/dark-factory-ops.md`

---

## File Structure

| File | Change |
|------|--------|
| `.archon/memory/dark-factory-ops.md` | Replace Scope Enforcement `[PATTERN]` bullet in-place |

---

## Memory: Applicable Patterns

From `dark-factory-ops.md`:

- **Scope Enforcement** (current): The target entry to replace is the sole `[PATTERN]` bullet under `## Scope Enforcement`. Its provenance marker is `<!-- issue:#206 date:2026-06-04 expires:2026-12-04 source:implement -->`. The replacement carries `issue:#421 date:2026-06-14 expires:2026-12-14 source:implement`.
- **Path-tag filtering**: Include `path:dark-factory/scripts/dedupe_oos.py` in the new entry so future path-tag filtering correctly scopes this lesson to changes in that script.

---

## Task 1 — Replace the Scope Enforcement entry

**Files**: `.archon/memory/dark-factory-ops.md`

### Verify current state (pre-condition check)

Confirm the existing entry matches the expected text before replacing:

```bash
grep -n "scope-spillover.*backlog ticket automatically" .archon/memory/dark-factory-ops.md
```

Expected output (exact line content):
```
<n>:- [PATTERN] When an out-of-scope defect is noticed during implementation, write it to `$ARTIFACTS_DIR/out-of-scope.md` with `- <file>: <one-sentence description>` and leave the defect unfixed. The conformance gate reads this file and converts each entry into a `scope-spillover`-labelled backlog ticket automatically. <!-- issue:#206 date:2026-06-04 expires:2026-12-04 source:implement -->
```

If this grep returns nothing, the file has already been updated or the entry was moved — stop and investigate before proceeding.

### Apply the replacement

Using the Edit tool (or equivalent), replace the entire Scope Enforcement `[PATTERN]` bullet. Old string (exact):

```
- [PATTERN] When an out-of-scope defect is noticed during implementation, write it to `$ARTIFACTS_DIR/out-of-scope.md` with `- <file>: <one-sentence description>` and leave the defect unfixed. The conformance gate reads this file and converts each entry into a `scope-spillover`-labelled backlog ticket automatically. <!-- issue:#206 date:2026-06-04 expires:2026-12-04 source:implement -->
```

New string (exact):

```
- [PATTERN] When an out-of-scope defect is noticed during implementation, write it to `$ARTIFACTS_DIR/out-of-scope.md` with `- <file>: <one-sentence description>` and leave the defect unfixed. The conformance gate routes each entry through `dedupe_oos.py` (`dark-factory/scripts/`), which classifies it as **create** (file a new `scope-spillover` ticket), **comment:\<n\>** (a matching open ticket exists — post a comment instead), or **suppress** (ruff-reformat class or within-run duplicate — drop silently). Matching uses an embedded `<!-- dedup-key: <file/area>|<finding-type> -->` marker in existing ticket bodies, so re-observed findings no longer spawn duplicate tickets. path:dark-factory/scripts/dedupe_oos.py <!-- issue:#421 date:2026-06-14 expires:2026-12-14 source:implement -->
```

### Verify only the targeted line changed

```bash
git diff .archon/memory/dark-factory-ops.md
```

Expected: diff shows exactly two changed lines (old bullet removed, new bullet added) under `## Scope Enforcement`. All other sections show no diff. Confirm the diff contains:
- `-` line: the old `issue:#206` entry
- `+` line: the new `issue:#421` entry

If any other lines appear in the diff, revert and investigate.

```bash
# Confirm no other sections modified
git diff .archon/memory/dark-factory-ops.md | grep "^@@" | wc -l
```

Expected output: `1` (a single hunk — one contiguous change region).

### Commit

```bash
git add .archon/memory/dark-factory-ops.md
git commit -m "docs(memory): update scope-enforcement entry for dedupe_oos.py (#421)"
```

Expected output:
```
[<branch> <sha>] docs(memory): update scope-enforcement entry for dedupe_oos.py (#421)
 1 file changed, 1 insertion(+), 1 deletion(-)
```
