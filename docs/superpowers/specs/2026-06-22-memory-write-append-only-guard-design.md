# Memory Write — Append-Only Guard

**Status:** design
**Date:** 2026-06-22
**Issue:** #522 (scope-spillover from #391)

## Problem

During issue #391 the implement agent deleted three valid, non-expired memory entries from
`.archon/memory/backend-patterns.md` while adding new SLO-related patterns. The conformance
gate detected and restored the missing entries, but only after the fact — the root cause
remains live in the implement and refine agents.

The failure mode: the agent used the `Write` or `Edit` tool to regenerate a memory file from
its in-context view of the file. Because LLM context is lossy (the agent may not have re-read
the full file immediately before writing), it reconstructed a subset of the original content
and silently dropped entries that were not directly relevant to the current issue.

The constraint: not all writes to memory files are pure appends. Three operations legitimately
modify or remove existing lines:

- **Expiry cleanup** — the `awk` block removes entries whose `expires:` date has passed.
- **R4 cap-drop** — when a file exceeds 30 authoritative entries, the oldest/lowest-signal
  entries are removed to stay under the cap.
- **R5 invalidation** — an existing `[PATTERN]` tag is rewritten to `[INVALID: reason]` when
  this run proves the pattern wrong.

The fix must preserve all three legitimate operations while preventing accidental deletion of
everything else.

## Requirements

1. New memory entries must be written using shell `echo '...' >> file` appends — never via
   `Write` or `Edit` tools on the memory file as a whole.
2. Only the three documented operations (expiry cleanup, R4 cap-drop, R5 invalidation) may
   remove or rewrite existing lines. Every other line in the file must survive the Phase 5
   memory write unchanged.
3. A deterministic verification step runs after all writes and before the memory commit. It
   uses `git diff .archon/memory/<file>` to detect any deleted authoritative lines that fall
   outside the expected categories. If unexpected deletions are found, the file is restored and
   only the intended entries are re-applied.
4. The fix applies to both:
   - `dark-factory-implement.md` Phase 5 MEMORY UPDATE
   - `dark-factory-refine.md` step 7 (memory append)
5. The `.claude/skills/refinement/` skill is read-only — no changes needed there.

## Architecture

### Instruction hardening (prevention)

In the "Writing authoritative entries" section of Phase 5 (`dark-factory-implement.md`) and
the equivalent section of `dark-factory-refine.md`, add an explicit constraint block:

```
**Append-only rule:** New memory entries must be written with shell appends:
  echo '- [PATTERN] ...' >> .archon/memory/backend-patterns.md
NEVER use the Write or Edit tool on a memory file to add new entries — doing so risks
regenerating the file from a stale in-context copy and silently dropping existing entries.

The ONLY operations permitted to remove or modify existing lines are:
  (a) the awk expiry-cleanup block (entries with a past `expires:` date)
  (b) R4 cap-drop (explicit drop of the oldest/lowest-signal entries when COUNT > 30)
  (c) R5 invalidation (rewrite `[PATTERN]` → `[INVALID: reason]` for a single entry)
Each of these operations must touch ONLY the targeted lines and leave all other lines verbatim.
```

### Post-write verification backstop (detection + recovery)

Insert this verification block in both commands, immediately before the `git add .archon/memory/` commit:

```bash
# Memory write guard — detect unexpected deletions and restore
for MEM_FILE in .archon/memory/*.md; do
  [ -f "$MEM_FILE" ] || continue
  # Lines starting with '-' that are not file-header markers
  DELETED=$(git diff "$MEM_FILE" | grep '^-' | grep -v '^---' | grep -v '^-#' | grep -v '^-<!--' || true)
  if [ -n "$DELETED" ]; then
    # Filter out expected deletions: expiry-cleaned lines (expired dates),
    # R4 drops (oldest-date lines), R5 rewrites (tag-only change, body unchanged)
    TODAY=$(date +%Y-%m-%d)
    UNEXPECTED=$(echo "$DELETED" | while IFS= read -r line; do
      # Skip lines whose expires: date is in the past (legitimate expiry cleanup)
      if echo "$line" | grep -q 'expires:'; then
        EXPIRY=$(echo "$line" | sed 's/.*expires:\([0-9-]*\).*/\1/')
        [ "$EXPIRY" \< "$TODAY" ] && continue
      fi
      # Skip R5 invalidations: deleted line body matches an added line body (tag change only)
      BODY=$(echo "$line" | sed 's/^\- \[PATTERN\]//' | sed 's/^\- \[AVOID\]//' | sed 's/^\- \[FIX\]//')
      if git diff "$MEM_FILE" | grep '^+' | grep -v '^+++' | grep -qF "$BODY"; then
        continue
      fi
      echo "$line"
    done)
    if [ -n "$UNEXPECTED" ]; then
      echo "MEMORY GUARD: unexpected deletions detected in $MEM_FILE — restoring"
      echo "$UNEXPECTED"
      git checkout HEAD -- "$MEM_FILE"
      # Re-apply only the intended new entries by echoing them back
      # (The agent must re-append them after the restore.)
      echo "MEMORY GUARD: re-append your new entries to $MEM_FILE now"
    fi
  fi
done
```

When the guard fires, the agent restores the file from HEAD and re-appends only the intended
new entries using shell `echo >>` appends. It does not attempt to reconstruct the full file.

### Placement in each command

**`dark-factory-implement.md` Phase 5:**
- Add the append-only rule to the "Writing authoritative entries" section (after the Format block, before the Per-file cap block).
- Add the verification block after the R5 invalidation section and before the "### Commit" block.

**`dark-factory-refine.md` step 7:**
- Add the append-only rule to the "What to write and where" subsection (after the PATTERN+AVOID pair format block).
- Add the verification block after the per-file entry cap check and before the "If any entries were added, commit" block.

## Alternatives Considered

### (a) Instruction-only (prompt hardening, no verification)

Add the append-only rule but skip the `git diff` backstop.

**Rejected**: The current Phase 5 already relies on shell appends and the `awk` expiry block,
yet #391 still deleted entries. The agent sometimes reaches for `Write`/`Edit` for legitimate
sub-tasks (cap-drop, invalidation) and regenerates the file incorrectly. A non-deterministic
LLM cannot be constrained by prompts alone for a correctness-critical operation.

### (b) Verification-only (no instruction change)

Add the `git diff` backstop without changing the append-only instruction.

**Rejected**: The backstop is a safety net, not a teaching tool. Without the instruction
change, the agent continues producing files with unexpected deletions on every run (they just
get caught and restored). This adds noise and recovery overhead. Both controls together are
cheap and complementary.

### (d) Atomic write helper script

Write a shell script `scripts/memory_append.sh` that the agent calls instead of `echo >>`.

**Rejected**: Adds a new artifact to maintain; the existing `echo >>` pattern is already in
Phase 5 documentation and works correctly when followed. A helper script adds indirection
without changing the fundamental guarantee (the agent could still bypass it). The verification
backstop provides the same safety without a new dependency.

## Assumptions

- `git diff <file>` (against the working-tree HEAD) correctly surfaces all lines modified
  since the last commit on the current branch. This is true for the dark factory's single-
  branch-per-issue workflow where the memory file was committed in a prior step.
- The `awk` expiry cleanup correctly identifies and removes only expired entries (entries
  whose `expires:` date is strictly less than today). This was verified by inspection of the
  existing awk block in both commands.
- R4 cap-drops are rare (the 30-entry cap is well above current file sizes) and R5
  invalidations are explicit human-driven corrections — neither will fire on a typical run,
  so the verification overhead is negligible in practice.

## Open Questions

- Should the verification block also check `architecture.md` and `codebase-patterns.md`
  (not just the area files)? Both are written by the refine and implement agents respectively.
  This is non-blocking: the requirement as written ("for each memory file written in this
  phase") covers all files and does not require them to be listed explicitly.
