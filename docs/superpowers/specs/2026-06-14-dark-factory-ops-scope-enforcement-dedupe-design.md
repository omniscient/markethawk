# dark-factory-ops.md Scope Enforcement Entry — dedupe_oos.py Update

**Date**: 2026-06-14
**Issue**: [#421](https://github.com/omniscient/markethawk/issues/421) — Update dark-factory-ops.md scope enforcement entry to reflect dedupe_oos.py behavior

## Overview

The "Scope Enforcement" entry in `.archon/memory/dark-factory-ops.md` describes the pre-dedup behavior: the conformance gate "converts each entry into a `scope-spillover`-labelled backlog ticket automatically." Since issue #384 introduced `dedupe_oos.py`, the actual mechanism routes each OOS entry through a three-action classifier (create / comment / suppress) rather than unconditionally filing a new ticket. The memory entry must be updated so future implement agents do not assume a ticket is always created.

## Requirements

1. The "Scope Enforcement" `[PATTERN]` entry in `.archon/memory/dark-factory-ops.md` is updated to describe the `dedupe_oos.py` create / comment / suppress classification.
2. The updated entry no longer implies a ticket is created unconditionally per finding.
3. The entry mentions the dedup-key mechanism (`<!-- dedup-key: <file/area>|<finding-type> -->` embedded in existing issue bodies) as the matching mechanism.
4. The entry carries a provenance marker in the format used by all other entries in the file: `<!-- issue:#421 date:2026-06-14 expires:2026-12-14 source:implement -->`.
5. No other sections of `.archon/memory/dark-factory-ops.md` are modified.
6. No code changes — `dedupe_oos.py` behavior is unchanged.

## Approach

**Single updated [PATTERN] bullet** — replace the existing Scope Enforcement `[PATTERN]` entry in-place with a new one that names all three actions and adds a half-clause for the dedup-key mechanism. The entry stays one self-contained bullet matching the file's one-lesson-per-bullet rhythm.

The updated bullet will:
- Retain the existing instruction ("write to `$ARTIFACTS_DIR/out-of-scope.md` … and leave the defect unfixed")
- Replace "converts each entry into a `scope-spillover`-labelled backlog ticket automatically" with the three-action description
- Add a path-tag (`path:dark-factory/scripts/dedupe_oos.py`) for future path-tag filtering
- Update the provenance marker to `issue:#421 date:2026-06-14 expires:2026-12-14 source:implement`

Concrete replacement text:

```
- [PATTERN] When an out-of-scope defect is noticed during implementation, write it to `$ARTIFACTS_DIR/out-of-scope.md` with `- <file>: <one-sentence description>` and leave the defect unfixed. The conformance gate routes each entry through `dedupe_oos.py` (`dark-factory/scripts/`), which classifies it as **create** (file a new `scope-spillover` ticket), **comment:\<n\>** (a matching open ticket exists — post a comment instead), or **suppress** (ruff-reformat class or within-run duplicate — drop silently). Matching uses an embedded `<!-- dedup-key: <file/area>|<finding-type> -->` marker in existing ticket bodies, so re-observed findings no longer spawn duplicate tickets. path:dark-factory/scripts/dedupe_oos.py <!-- issue:#421 date:2026-06-14 expires:2026-12-14 source:implement -->
```

## Alternatives Considered

**Option B: Expand to full detail** — include the suppression keyword list, within-run vs. cross-run dedup distinction, and keyless fallback logic. Rejected: the memory file is advisory; the source of truth is `dedupe_oos.py`. Over-specifying risks the entry going stale as the classifier evolves.

**Option C: Two bullets** — split the "write to out-of-scope.md" instruction from the "classify via dedupe_oos.py" description. Rejected: every other section in the file uses one bullet per topic; a two-bullet Scope Enforcement section would be the only exception and adds no clarity.

## Open Questions

None — the acceptance criteria are fully specified in the issue brief.

## Assumptions

- The `expires` date follows the 6-month convention used by all other `source:implement` entries added in 2026.
- The existing `<!-- issue:#206 date:2026-06-04 expires:2026-12-04 source:implement -->` provenance marker on the current entry is replaced (not kept alongside) since the entry body is being superseded, not extended.
- No second `[AVOID]` entry is needed; the old behavior is covered by the updated `[PATTERN]` (which makes clear that unconditional ticket creation no longer happens).

## Implementation Checklist

- [ ] Replace the Scope Enforcement `[PATTERN]` entry in `.archon/memory/dark-factory-ops.md` with the updated text above
- [ ] Verify no other lines in the file were modified (`git diff .archon/memory/dark-factory-ops.md`)
- [ ] Commit with message: `docs(memory): update scope-enforcement entry for dedupe_oos.py (#421)`
