# Self-Improvement Loop Audit & Optimization — Design

**Date:** 2026-06-05
**Status:** Approved (design) — pending implementation plan
**Issue:** #213
**Author:** Brainstormed with Claude (Opus 4.8)

## Problem

The Dark Factory pipeline has accumulated self-improvement mechanisms across many issues
(#149, #162, #178, #206, #210, #212, #218) but has never been audited systematically
against an established self-improving agent framework. Two structural gaps also exist in the
current memory loop:

1. **One-directional writes** — the conformance and code-review stages catch mistakes and
   violations, but that signal never flows back into `.archon/memory/`. Future runs repeat
   the same class of error until a human happens to write the lesson manually.

2. **Flat memory loading** — all entries within a memory file are loaded without filtering.
   As the pipeline auto-generates more entries (from fixing gap 1), signal-to-noise will
   degrade unless entries can be scoped by file path.

## Goal

1. Produce a self-contained HTML audit report (`docs/dark-factory-self-improvement-audit.html`)
   comparing the current Dark Factory memory/feedback loop against the patterns described in
   https://addyosmani.com/blog/self-improving-agents/

2. Close the highest-priority structural gap: wire conformance-stage violations and
   code-review blocking findings back into `.archon/memory/` as `[AVOID]` entries with
   `source:conformance` / `source:code-review` attribution.

3. Improve future memory relevance by tagging new auto-written entries with a `path:` glob
   so downstream Phase 1 loads can filter within-file by the issue's affected paths.

## Non-Goals (v1)

- Memory effectiveness tracking (detecting recurrence of `[AVOID]` scenarios uncaught)
- Pipeline metrics dashboards (issue #212 in progress — do not duplicate)
- Scanner signal quality ML loop (out of scope per Q&A)
- Retroactively path-tagging existing memory entries
- Auto-fixing conformance violations via additional reconcile loops

## Components

### 1. HTML Audit Report

**File:** `docs/dark-factory-self-improvement-audit.html`

Self-contained HTML with inline CSS (no external dependencies), consistent with the
`docs/dark-factory-agyn-comparison.html` precedent from issue #184.

**Process:**
1. Fetch and parse https://addyosmani.com/blog/self-improving-agents/ using the `WebFetch`
   tool to extract the article's self-improving agent framework and checklist.
   If the URL is unreachable, note the failure in the report and skip the comparison table.
2. For each pattern the article identifies (e.g. feedback loops, episodic memory, reflection,
   tool improvement, performance metrics), map it to the current Dark Factory mechanism:

   | Article Pattern | Current Mechanism | Status |
   |---|---|---|
   | Feedback loop | Conformance gate → `[AVOID]` entries (after this issue) | ✅ |
   | Episodic memory | `.archon/memory/*.md` `[PATTERN]`/`[AVOID]` entries, 6-month TTL | ✅ |
   | _... one row per article pattern ..._ | | |

3. Status values: ✅ Implemented, ⚠️ Partial, ❌ Missing, 🔄 In Progress (with issue ref).
4. Gap analysis section: ordered by impact, each gap with a one-paragraph explanation.
5. Recommendations section: what this issue addresses vs. what is deferred.

Deliver as a single `.html` file with colored tables and status badges. No Markdown.

### 2. Memory Feedback from Conformance Stage

**File modified:** `.archon/commands/dark-factory-conformance.md`

Add a **Memory Write phase** that executes after the conformance verdict is determined
(after Phase 5 / the existing block-or-pass logic) and before `exit`.

**Trigger:** Only when `VERDICT = MATERIAL` (blocking). Advisory-only (`CONFORMS` or
`MINOR`) does not write memory — advisory findings are not proven mistakes.

**Logic:**

```bash
# The conformance reviewer subagent already produces a structured finding list.
# For each blocking violation, the conformance COMMAND (not the subagent) extracts:
#   VIOLATION_FILE  — the file path of the violation (e.g. backend/app/routers/scanner.py)
#   VIOLATION_TEXT  — the one-sentence lesson (paraphrased from the violation description)
# Then:
for each (VIOLATION_FILE, VIOLATION_TEXT) in $BLOCKING_VIOLATIONS:
  TARGET=$(route_memory_file "$VIOLATION_FILE")   # see routing table below
  PATH_PREFIX=$(dirname "$VIOLATION_FILE")/       # e.g. backend/app/routers/
  run_expiry_cleanup "$TARGET"                    # mawk two-argument match() form
  ENTRY="- [AVOID] $VIOLATION_TEXT <!-- issue:#$ISSUE date=$(date +%Y-%m-%d) expires:$(date -d '+6 months' +%Y-%m-%d 2>/dev/null || date -v+6m +%Y-%m-%d) source:conformance path:$PATH_PREFIX -->"
  if ! grep -qF "$VIOLATION_TEXT" "$TARGET"; then
    echo "$ENTRY" >> "$TARGET"
  fi
done
# Commit only if new entries were written:
if ! git diff --quiet .archon/memory/; then
  git add .archon/memory/ && git commit -m "memory: conformance lesson from #$ISSUE"
fi
```

**Path routing table:**

| File path prefix | Target memory file |
|---|---|
| `backend/app/**` | `.archon/memory/backend-patterns.md` |
| `frontend/src/**` | `.archon/memory/frontend-patterns.md` |
| `.archon/**`, `dark-factory/**` | `.archon/memory/dark-factory-ops.md` |
| `ARCHITECTURE.md`, service-topology decisions | `.archon/memory/architecture.md` |
| Any other / ambiguous | `.archon/memory/codebase-patterns.md` |

**Important constraints:**
- Use `date -d '+6 months' +%Y-%m-%d 2>/dev/null || date -v+6m +%Y-%m-%d` for cross-platform
  expiry (GNU/BSD date).
- The awk cleanup must use the two-argument `match()` form (not three-argument — `mawk`
  incompatibility; see `dark-factory-ops.md` `[AVOID]`).
- Duplicate check via `grep -qF` on the core sentence before appending.
- If no violations produce a novel entry (all duplicates or ambiguous path), skip the commit.

### 3. Memory Feedback from Code-Review Stage

**File modified:** `.archon/commands/dark-factory-code-review.md`

Add the same **Memory Write phase** after Phase 6 (block-or-pass), using the same path
routing and format.

**Trigger:** Only when `STATUS = BLOCKED` (blocking findings). Advisory findings (`STATUS:
PASS` with advisory count) do not write memory.

**Entry format:**
```
- [AVOID] <one-sentence lesson from the blocking finding> <!-- issue:#NNN date:YYYY-MM-DD expires:YYYY-MM-DD source:code-review path:backend/app/routers/ -->
```

The `source:code-review` attribution distinguishes auto-generated entries from
`source:implement` (runtime-proven) and `source:refine` (design-time decisions).

### 4. Memory Path Tagging

All new memory entries written by the pipeline (conformance and code-review phases above)
carry a `path:<glob>` tag in their inline comment. Entries written by human-operated
runs (implement agent, refine agent) should also adopt this tag going forward, but
existing entries are not retroactively changed.

**Format:**
```
- [AVOID] Never do X <!-- issue:#213 date:2026-06-05 expires:2026-12-05 source:conformance path:backend/app/routers/ -->
```

**Phase 1 filtering in implement/refine/plan commands:**

After loading a memory file, filter entries for the current context:
- Entries **without** a `path:` tag: always included (backward-compatible with all existing entries).
- Entries **with** a `path:` tag: included only if the tag is a **prefix** of at least one
  file in the current issue's affected set.

Affected files come from `git diff --name-only origin/main...HEAD 2>/dev/null` on existing
branches; for new branches (no commits yet) fall back to unconditional load.

```bash
# Pseudo-bash (adapt to the actual shell in each command file):
AFFECTED=$(git diff --name-only origin/main...HEAD 2>/dev/null || echo "")

# Load a memory file with path-tag filtering
# Usage: load_memory backend-patterns.md
load_memory() {
  local MEMFILE=".archon/memory/$1"
  [ -f "$MEMFILE" ] || return
  while IFS= read -r line; do
    if echo "$line" | grep -q 'path:'; then
      # Extract path prefix (between 'path:' and the next space or '>')
      PATH_TAG=$(echo "$line" | sed 's/.*path:\([^ >]*\).*/\1/')
      if [ -z "$AFFECTED" ] || echo "$AFFECTED" | grep -q "^$PATH_TAG"; then
        echo "$line"
      fi
    else
      echo "$line"   # no path tag — always include
    fi
  done < "$MEMFILE"
}
```

Note: `grep -oP` (PCRE) is avoided above — the dark factory container ships `mawk`-compatible
grep; use `sed` or POSIX `grep` for extraction. The `path:` match is a string prefix check,
not a shell glob expansion.

## Approach Selection

Three approaches were considered:

**Approach A — HTML report only:**
- Pro: Low risk, fast delivery.
- Con: Leaves both structural gaps open; "must-have" priority implies concrete action.
- Rejected.

**Approach B (selected) — HTML report + B + D:**
- Audit, then close the two highest-confidence gaps identified by Q&A.
- Conformance→memory and code-review→memory feedback closes the one-directional-write gap.
- Path tagging prepares memory for growth from auto-writes and tightens relevance.
- Doesn't duplicate issue #212 (metrics) or introduce speculative complexity (A).

**Approach C — Code changes only, no report:**
- Skips the "compare against the article" requirement in the issue body.
- Rejected.

## Data Flow (After This Issue)

```
run_scanner → conformance gate
                  │ MATERIAL violation found
                  ▼
          conformance memory write
          path → backend-patterns.md / frontend-patterns.md / ...
          [AVOID] entry with source:conformance path:<prefix>
                  │
                  ▼
          git commit "memory: conformance lesson from #N"

push-and-pr → code-review gate
                  │ BLOCKED (critical/high finding)
                  ▼
          code-review memory write (same routing)
          [AVOID] entry with source:code-review path:<prefix>
                  │
                  ▼
          git commit "memory: code-review lesson from #N"

next run Phase 1 (implement/refine/plan):
  load memory files → filter by path: tags → only relevant entries in context
```

## Files Touched

| File | Change |
|---|---|
| `docs/dark-factory-self-improvement-audit.html` | **NEW** — HTML audit report |
| `.archon/commands/dark-factory-conformance.md` | Add Memory Write phase (MATERIAL violations → `[AVOID]`) |
| `.archon/commands/dark-factory-code-review.md` | Add Memory Write phase (BLOCKED findings → `[AVOID]`) |

No dark-factory image rebuild required (commands are clone-read). No new workflow nodes.
No database migrations.

## Assumptions

- The implement agent can access the article URL with the `WebFetch` tool to extract the
  framework (the report will fail gracefully if the URL is unreachable — omit the
  comparison section and note the failure).
- `dark-factory-conformance.md` and `dark-factory-code-review.md` already exist (confirmed
  in `.archon/commands/`).
- The path routing table covers the common cases; files outside all prefixes fall through
  to `codebase-patterns.md` as the catch-all.
- Memory commits from this phase do not interfere with the main feature branch commit
  because memory files are in `.archon/memory/`, which is committed on the same branch
  and merged to main with the PR.

## Open Questions (Non-Blocking)

- Should advisory code-review findings (medium/low) also write memory? Currently excluded
  to avoid noise — revisit after observing auto-generated entry volume.
- Should the path-filtering logic in Phase 1 be centralized into a shared shell function
  loaded by all commands, or stay inline in each command? (Inline is simpler for now.)
- Memory effectiveness tracking (detecting `[AVOID]` recurrence) remains unspecified —
  could be tackled as a follow-up once enough auto-generated entries exist to test against.
