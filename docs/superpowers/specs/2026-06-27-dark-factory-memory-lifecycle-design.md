# Dark Factory Memory Lifecycle Maintenance

**Status:** design
**Date:** 2026-06-27
**Issue:** #650
**Epic:** #643 (Improve Dark Factory memory system using agent-native memory architecture)
**Phase:** 4 of 4 in epic #643 — earlier phases (structured records, retrieve, write) not yet landed.

## Problem

The five `.archon/memory/*.md` files accumulate entries across every refine and implement
run. Today, the only lifecycle enforcement happens inline — scattered awk expiry-cleanup
blocks inside the refine skill and `gate_lib.sh`. There is no consolidated tool to:

- Prune entries whose `expires:` date has passed
- Promote `[PROVISIONAL]` entries that have been independently confirmed by a second issue
- Surface near-identical duplicate entries and mark the older one superseded
- Give an operator a dry-run-safe, auditable way to invalidate a specific entry

As the corpus grows (currently ~115 authoritative + 12 provisional entries across 5 files),
unreviewed stale entries erode signal quality and the per-file cap warnings become routine
noise.

## Decision

Add `dark-factory/scripts/memory_maintain.py` — a standalone `argparse` CLI that
implements four discrete lifecycle operations against the markdown memory files, with
full dry-run support so every change is reviewable before it lands.

## Requirements

1. **Dry-run mode** — `--dry-run` flag prints a unified diff of every change the script
   *would* make without touching any file. This is the default for the `run` subcommand.
2. **Expire** — entries whose `expires:YYYY-MM-DD` metadata date is in the past are removed
   from the authoritative section. `[PROVISIONAL]` entries that expire without ever gaining
   a second `issue:#N` are also removed.
3. **Promote** — a `[PROVISIONAL]` entry that carries 2+ distinct `issue:#N` values in its
   inline HTML comment is promoted to `[PATTERN]` (or `[AVOID]`/`[FIX]` if explicitly
   tagged by the inline comment metadata). The `[PROVISIONAL]` tag is rewritten in-place;
   the entry moves from the provisional section to the authoritative section.
4. **Dedup-invalidate** — when two entries share body text that is ≥90% identical after
   stripping inline `<!-- ... -->` metadata comments, the older entry (by `date:YYYY-MM-DD`)
   is retagged `[INVALID: superseded by identical entry added <date>]`. High threshold (90%)
   to avoid false positives; gated behind `--dry-run` review.
5. **CLI invalidate** — `python memory_maintain.py invalidate --file <file.md>
   --match "<substring of entry body>" --reason "<why>"` rewrites the matching entry's
   leading tag to `[INVALID: <reason>]` in place, preserving the inline metadata comment.
6. **Output** — after `run`, print a structured change summary: counts of expired,
   promoted, dedup-invalidated entries per file, and the file paths modified.
   In `--dry-run`, print the unified diff instead.
7. **Scope filter** — `--scope <path-prefix>` restricts operation to entries whose inline
   `path:` tag matches the prefix (mirrors the Phase 1 LOAD path-tag filtering already used
   in the refine skill). Without `--scope`, all five files are processed.
8. **Tests** — `dark-factory/tests/test_memory_maintain.py` with pytest fixtures covering:
   promote, expire (authoritative and provisional), dedup-invalidate, and CLI invalidate.
   Tests operate on in-memory strings (no file-system writes).

## Out of scope (v1)

- Usage-based decay (`last_used`, `retrieval_count` tracking) — requires Phase 1 of epic #643
  (structured `index.jsonl` records + `memory_retrieve.py`) which is not yet landed.
- LLM-assisted semantic contradiction detection — remains a human-triggered `invalidate` call.
- Pipeline auto-wiring (invoking `memory_maintain.py` as a post-run step in `entrypoint.sh`)
  — the standalone CLI is built here; integration into the factory lifecycle is a follow-up.

## Architecture

### Entry format (existing)

Each memory entry is one line matching:

```
- [TAG] <body text> <!-- key:val key2:val2 -->
```

Where `TAG` ∈ `{PATTERN, AVOID, FIX, PROVISIONAL, INVALID: <reason>}` and the inline
comment contains space-separated `key:value` pairs (no quotes; values end at the next
space or `-->`). Known keys: `issue`, `date`, `expires`, `source`, `path`, `evidence`,
`evidence2`.

Sections in each file are delimited by:
```
---
<!-- PROVISIONAL — entries below are from a single observed run; ... -->
```

Authoritative entries live before the `---` line; provisional entries live after it.

### Module structure (`dark-factory/scripts/memory_maintain.py`)

```
memory_maintain.py
  ├── parse_file(path) → MemoryFile          # returns header, auth entries, provisional entries
  ├── parse_entry(line) → MemoryEntry        # tag, body, metadata dict
  ├── render_file(MemoryFile) → str          # back to markdown
  │
  ├── op_expire(entries, today) → changes    # remove entries with expires < today
  ├── op_promote(prov_entries) → changes     # move 2+-issue provisionals to auth
  ├── op_dedup(entries) → changes            # tag older near-identical pairs as INVALID
  │
  ├── cmd_run(args)                          # expire + promote + dedup
  └── cmd_invalidate(args)                   # single-entry retag by body substring
```

All `op_*` functions are **pure** — they accept lists of `MemoryEntry` dataclasses and
return a `ChangeList` without touching the filesystem. The `cmd_*` functions handle I/O,
dry-run diff rendering, and file writing.

### Dry-run output

`--dry-run` uses `difflib.unified_diff` on the before/after `render_file()` output.
Example:
```
--- .archon/memory/dark-factory-ops.md
+++ .archon/memory/dark-factory-ops.md (dry-run)
@@ -87,2 +87,2 @@
-  - [PROVISIONAL] When .env is absent, ...  <!-- issue:#287 ... -->
+  *(removed — expired 2026-12-11, no second evidence)*
```

### Parsing approach

Regex-based, no new dependencies. The entry regex:

```python
ENTRY_RE = re.compile(
    r'^(?P<indent>\s*)-\s+\[(?P<tag>[^\]]+)\]\s+(?P<body>.*?)(?:\s*<!--(?P<meta>[^>]*)-->)?\s*$'
)
```

Metadata is extracted by splitting the `meta` group on whitespace and parsing `key:value`
pairs, stopping at the next whitespace boundary.

### Issue-number deduplication for promotion

A `[PROVISIONAL]` entry is eligible for promotion when its `meta` group contains 2+
distinct tokens matching `issue:#\d+`. Example:

```
- [PROVISIONAL] ... <!-- evidence:docker-exec issue:#287 evidence2:ci-log issue:#295 date:... -->
```

The two distinct issue values `#287` and `#295` trigger promotion. When only one issue is
present, the entry stays provisional until it expires.

### Structural deduplication

Body text comparison strips `<!--...-->` metadata and normalises whitespace. If
`SequenceMatcher(None, a_body, b_body).ratio() >= 0.90`, the entry with the earlier
`date:` is tagged `[INVALID: superseded by identical entry added <newer_date>]`.

## Alternatives considered

### A: Pure expiry-only (no promote/dedup)

Simplest possible v1 — just prune expired entries. Rejected because the accept criteria
explicitly require promote and invalidate flows, and they are achievable from the current
markdown format without scope creep.

### B: JSON shadow index

Parse markdown into an intermediate JSON, apply operations in JSON, re-render to markdown.
Rejected as YAGNI — introduces a state file requiring its own lifecycle management, and
the markdown format is regular enough for direct regex parsing.

### C: LLM-based contradiction detection

Route each pair of entries through Claude for semantic similarity. Rejected for v1 because:
(a) it requires a network call from the standalone maintenance script, (b) the cost is
unbounded relative to corpus size, and (c) existing `[INVALID]` entries were all authored
by operators with precise human judgment. The `invalidate` subcommand preserves this pattern.

## Open questions (non-blocking)

- Should `memory_maintain.py` emit a machine-readable JSON change log (alongside the
  markdown diff) for future automation (e.g., posting lifecycle events to Seq)? Not needed
  for v1.
- When promoting a `[PROVISIONAL]` entry, should the script preserve or extend the `expires:`
  date? The spec assumes extension by 6 months (matching the existing `refine` rule for new
  PATTERN entries), but a pass-through of the original date is also defensible.

## Assumptions

- **[ASSUMED]** The metadata `<!-- ... -->` comment is always the **last** portion of the
  line. Entries with comments in the middle of the body text will not parse correctly.
- **[ASSUMED]** Phase 1–3 of epic #643 (structured records, retrieve, write) are not
  yet landed and are not prerequisites for this script to be useful.
- **[ASSUMED]** `dark-factory/tests/` uses standard pytest conventions; no containerised
  database or external services are required for the maintenance script tests.
