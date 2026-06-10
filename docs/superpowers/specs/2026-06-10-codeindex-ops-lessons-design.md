# Codeindex Ops Lessons — Factory Memory Entries (Spillover from #200)

**Date:** 2026-06-10
**Status:** Approved (design) — pending implementation plan
**Author:** Brainstormed with Claude (Opus 4.8)
**Issue:** #264

## Problem

During implementation of issue #200, the dark factory discovered two codeindex CLI behavioral pitfalls and wrote memory entries for them. The conformance gate excised those entries via scope enforcement (correct behavior) and filed this spillover ticket. The lessons are not currently recorded anywhere, and the workflow at `.archon/workflows/archon-dark-factory.yaml` actively uses both anti-patterns.

## Goal

Add two entries to `.archon/memory/dark-factory-ops.md` under the "Codeindex / MCP Integration" section so future implement agents do not repeat the mistakes observed during #200.

## Non-Goals (v1)

- Fixing the live anti-patterns in `.archon/workflows/archon-dark-factory.yaml` (three call sites: startup `symbols --inline`, post-implement `symbols --inline`, and the direct `>` redirect for `high-blast`). That is a separate bug fix with its own validation requirements; file a follow-up issue.
- Adding entries to any other memory file.
- Documenting codeindex MCP server or pre-commit hook behavior (already covered by existing entries).

## Requirements

1. Add an `[AVOID]` entry documenting that `codeindex symbols . --inline` embeds symbols into `codeindex.json` rather than producing a standalone `symbolindex.json`; the correct invocation is `codeindex symbols . --output symbolindex.json`.
2. Add a `[PATTERN]` entry documenting that `codeindex high-blast` output must be written via a temp file + atomic `mv` rather than a direct `>` redirect, to preserve the clean-on-failure guarantee (direct `>` truncates the target before the command runs).
3. Both entries go under the existing `## Codeindex / MCP Integration` section in `.archon/memory/dark-factory-ops.md`.
4. Both entries carry `source:implement`, `issue:#264`, `date:2026-06-10`, and `expires:2026-12-10` inline comments — matching the established entry format.
5. No other files are modified.

## Approach

Direct edit to `.archon/memory/dark-factory-ops.md`. Append the two entries at the end of the "Codeindex / MCP Integration" section, before the `---` PROVISIONAL delimiter.

### Entry text

```markdown
- [AVOID] `codeindex symbols . --inline` embeds symbols into `codeindex.json` rather than producing a standalone file. Use `codeindex symbols . --output symbolindex.json` to generate the committed standalone symbol index. <!-- issue:#264 date:2026-06-10 expires:2026-12-10 source:implement -->

- [PATTERN] Write `codeindex high-blast` output via a temp file + `mv` (`codeindex high-blast > /tmp/hotspots.md && mv /tmp/hotspots.md docs/codeindex-hotspots.md`) rather than redirecting straight to the target. A direct `>` redirect truncates the target before the command runs, so a codeindex failure leaves an empty/corrupt committed file — the temp-file + atomic `mv` preserves the clean-on-failure guarantee. <!-- issue:#264 date:2026-06-10 expires:2026-12-10 source:implement -->
```

## Alternatives Considered

**Option B — New "Codeindex CLI Invocation" subsection:** Rejected. The existing file uses coarse-grained single-topic section headers (e.g. "Seed Files" spans three distinct lessons). Introducing a finer-grained sub-header breaks the file's established convention. Co-location under "Codeindex / MCP Integration" keeps all codeindex guidance in one place.

**Include workflow fix in scope:** Rejected. The issue title and File/area field explicitly scope this to `.archon/memory/dark-factory-ops.md`. The workflow fix is a separable change requiring a real workflow run for validation — heavier than a docs-only change and deserving its own issue. An `[AVOID]` entry that the current workflow has not yet adopted is the intended signal that drives the follow-up fix.

## Open Questions

- None. Scope and content are fully specified by the issue body.

## Assumptions

- `codeindex symbols . --inline` behavior (embeds into `codeindex.json`, does not produce `symbolindex.json`) was observed during #200 and is accurately described in the issue body.
- `codeindex high-blast 2>/dev/null > target || true` is the current pattern and has the silent-truncation risk described.
- The follow-up issue to fix the workflow will be filed separately (not part of this implementation).

## Follow-up Required

The workflow at `.archon/workflows/archon-dark-factory.yaml` violates both lessons added here:
- Lines using `codeindex symbols . --inline` (startup and post-implement passes) should be changed to `codeindex symbols . --output symbolindex.json`.
- `codeindex high-blast 2>/dev/null > docs/codeindex-hotspots.md || true` should be changed to the temp-file + `mv` pattern.

A follow-up issue should be filed to apply these fixes.
