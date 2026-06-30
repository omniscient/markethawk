# Write-Through Memory Adapter — Flat-File Only

**Status:** design (re-spec 2026-06-30 — supersedes agentmemory version)
**Date:** 2026-06-27 (re-spec: 2026-06-30)
**Issue:** #648
**Epic:** #643 (Improve Dark Factory memory system using agent-native memory architecture)
**Phase:** 3 of 5 (write-path replacement)
**Related:** #645 (schema), #646 (read-through retrieval), #649 (index substrate / import)

> **Re-spec note (2026-06-30):** Per #644 spike verdict and epic #643 direction, this spec
> drops all `agentmemory` REST sidecar fan-out. `memory_write.py` is **flat-file only**.
> The earlier dual-write / best-effort-agentmemory design is superseded.

## Problem

The Dark Factory's memory write path lives entirely in `gate_lib.sh::write_memory_entry()`.
It appends `[AVOID]` entries to `.archon/memory/*.md` files with dedup, expiry cleanup, and a
30-entry cap — but the logic is bash-only, difficult to test, and carries no structured metadata
(`agent_id`, `scope`) that the future role-scoped read adapter (#646) and records substrate
(#649) need for filtering.

Issue #648 (Phase 3 of epic #643) replaces this path with a Python adapter that:

1. Preserves all existing cap/expiry/dedup behaviour (the markdown files remain the source of
   truth and continue to be human-readable diffs).
2. Tags every written entry with `agent:`, `scope:`, and `path:` per the #645 contract.
3. Optionally appends a record to `.archon/memory/index.jsonl` (best-effort; schema stub
   deferring full field semantics to #649).
4. Makes the entire write path testable via pytest.
5. Eliminates all external HTTP / REST / vector-DB dependencies.

## Requirements

Distilled from issue #648 acceptance criteria and re-spec Q&A:

1. **Markdown is the source of truth**: every validated memory event is written to the
   appropriate `.archon/memory/*.md` file (dedup, cap, expiry cleanup, and in-place
   reinforcement all preserved from the existing bash implementation).
2. **Write seam preserved**: existing callers of `gate_lib.sh::write_memory_entry()` —
   conformance and code-review gate commands — work without any code-path changes beyond the
   `gate_lib.sh` wrapper body itself.
3. **agentId/scope/path tagging**: each markdown entry's inline comment is extended with
   `agent:<source>` and `scope:<derived>` tags so the #646 read adapter and #649 import
   can filter by role and domain without touching the markdown files.
4. **index.jsonl stub**: after a successful markdown write, append a JSON record to
   `.archon/memory/index.jsonl` using available #645 schema fields. Write is best-effort
   and non-fatal. Skip when markdown write is a no-op (dedup/cap), keeping the two stores
   consistent.
5. **Normalized dedup**: duplicate detection uses normalized substring match (lowercase,
   collapse whitespace, strip trailing punctuation). On match, update the existing entry's
   `date:` and `expires:` in place rather than appending a new line.
6. **Stable diffs**: markdown output is append-only (new entries) or single-line changes
   (in-place reinforcement) — never a full-file rewrite.
7. **Tested**: pytest covers markdown write, normalized dedup, cap enforcement, expiry cleanup,
   reinforcement (in-place date/expires update), `index.jsonl` write success, and
   `index.jsonl` I/O error (must be non-fatal).
8. **No external HTTP**: no REST sidecar, no vector database, no embedding model, no network
   I/O. All writes are local file operations.

## Approach Selection

### Approach A — Full Python ownership, bash delegation (selected)

`memory_write.py` owns all write logic: routing, normalized dedup, expiry cleanup, cap,
markdown insertion, agentId/scope tagging, and the `index.jsonl` stub write.
`gate_lib.sh::write_memory_entry()` becomes a 5-line bash wrapper that shells out to
`memory_write.py` with the same 5-argument signature.

Advantages:
- All write logic is centralized and testable with pytest.
- The no-op/skip signal (dedup hit, cap reached) is naturally available to the `index.jsonl`
  step in the same process — no bash-to-bash handshake needed.
- Matches the established pattern: conformance and code-review already shell out to
  `code_review_payload.py`, `fmt_hunk_filter.py`, `dedupe_oos.py`.
- Existing callers need zero changes.

### Approach B — Additive (rejected)

Keep the existing bash markdown logic intact, call Python only for tagging and `index.jsonl`.
Rejected: splits the dedup/cap/skip decision across bash and Python. Tagging and the
`index.jsonl` write must know whether the markdown write was a no-op to apply the
symmetric-skip rule — this requires re-deriving the bash outcome in Python, defeating the
purpose of the adapter.

### Approach C — Full markdown re-render (rejected)

Python re-renders the entire markdown file from scratch on each write.
Rejected: violates Requirement 6 (stable diffs) and produces large, unreadable diffs when a
single entry is added or updated.

## Architecture

### File layout

```
dark-factory/scripts/
  memory_write.py         # new — full write adapter (this issue)
  gate_lib.sh             # modified — write_memory_entry() body replaced with 5-line stub
dark-factory/tests/
  test_memory_write.py    # new — pytest unit tests
.archon/memory/
  index.jsonl             # new — records substrate (appended by memory_write.py, read by #649)
  *.md                    # existing — source of truth, extended with agent:/scope: tags
```

### `memory_write.py` — command-line interface

```
python3 memory_write.py \
  --target      <abs-or-rel path to .archon/memory/*.md>    \
  --path-prefix <e.g. dark-factory/scripts/>                \
  --text        <core lesson text without tag prefix>        \
  --source      <conformance|code-review|refine|implement>   \
  --issue       <issue number>
```

Exit codes:
- `0`: markdown write succeeded or was intentionally skipped (dedup/cap).
- `1`: markdown write failed (file I/O error). `index.jsonl` failures do **not** set exit 1.

### `memory_write.py` — write pipeline

```
1. Validate args (target file path, non-empty text).
2. Derive metadata:
   - agent_id = source argument verbatim (e.g. "conformance", "code-review")
   - scope    = stem of target filename, stripping "-patterns" / "-ops" suffixes:
                  "dark-factory-ops.md"  → "dark-factory"
                  "backend-patterns.md"  → "backend"
                  "frontend-patterns.md" → "frontend"
                  "architecture.md"      → "architecture"
                  "codebase-patterns.md" → "codebase"
3. Normalize candidate: lowercase, collapse whitespace, strip trailing punctuation.
4. Load target markdown, scan for existing [PATTERN]/[AVOID]/[FIX] lines.
5. Normalize each existing entry body the same way.
6. Dedup check:
   a. If normalized candidate ∈ normalized existing bodies → REINFORCE:
      update the matching line's date: and expires: in-place; set skip_index=True.
   b. Else continue.
7. Cap check: count [PATTERN]/[AVOID]/[FIX] lines. If ≥ 30 → log WARNING, skip; set skip_index=True.
8. Expiry cleanup: remove lines where expires: date < today (port of existing awk logic).
9. Write entry as [AVOID] line before --- PROVISIONAL delimiter (or append if no delimiter):
   "- [AVOID] <text> <!-- issue:#<N> date:<today> expires:<+6m> source:<source>
    agent:<agent_id> scope:<scope> path:<path_prefix> -->"
10. If skip_index → return 0.
11. Best-effort index.jsonl write:
    - Build a JSON record from available #645 fields (see schema below).
    - Append to .archon/memory/index.jsonl (one line, newline-terminated).
    - On I/O error: log WARNING "index.jsonl: write failed (<reason>)".  Do not set exit 1.
12. Return 0.
```

### agentId / scope derivation

SOURCE is passed by the caller; it serves as both `source` and `agent_id` (they are the same
value). No signature change to `write_memory_entry()` is required.

| SOURCE caller passes | `agent_id`   | `scope` (from target filename)                       |
|----------------------|--------------|------------------------------------------------------|
| `conformance`        | conformance  | backend / frontend / dark-factory / architecture / codebase |
| `code-review`        | code-review  | (same — derived from `--target` argument)            |
| `refine`             | refine       | (same)                                               |
| `implement`          | implement    | (same)                                               |

### Markdown entry format (extended)

New format adds `agent:` and `scope:` inline comment tags. The existing `path:` tag and
`source:` tag are preserved unchanged for backward compatibility with the `load_memory`
shell function that filters on `path:`.

```
- [AVOID] <text> <!-- issue:#648 date:2026-06-30 expires:2026-12-30 source:conformance agent:conformance scope:dark-factory path:dark-factory/scripts/ -->
```

### index.jsonl record schema

Fields populated by `memory_write.py` from the 5 arguments it receives. Fields from the #645
schema that cannot be determined here (`id`, `supersedes`, `confidence`, `concepts`,
`rationale`, `pr_number`, `updated_at`) are omitted; #649 (`memory_import.py`) will
reconcile them during the import/sync pass.

```json
{
  "project":       "markethawk",
  "type":          "avoidance",
  "status":        "active",
  "source":        "<source>",
  "agent_id":      "<agent_id>",
  "phase":         "<source>",
  "issue_number":  <issue>,
  "files":         ["<path_prefix>"],
  "scope":         "<scope>",
  "content":       "<text>",
  "created_at":    "<today ISO-8601>",
  "expires_at":    "<today + 6 months ISO-8601>"
}
```

### `gate_lib.sh` — updated `write_memory_entry()`

```bash
write_memory_entry() {
  # Usage: write_memory_entry TARGET PATH_PREFIX VIOLATION_TEXT SOURCE ISSUE_NUM
  local TARGET="$1" PATH_PREFIX="$2" TEXT="$3" SOURCE="$4" ISSUE="$5"
  python3 "$(dirname "${BASH_SOURCE[0]}")/memory_write.py" \
    --target "$TARGET" --path-prefix "$PATH_PREFIX" --text "$TEXT" \
    --source "$SOURCE" --issue "$ISSUE"
}
```

`${BASH_SOURCE[0]}` (not `$0`) is required because `gate_lib.sh` is sourced, not executed.
`route_memory_file()` and `emit_verdict()` remain in bash — they are not write logic.

## Alternatives Considered

### Keep expiry cleanup in bash (awk)

The existing awk block in `gate_lib.sh` (lines 29–35) handles expiry cleanup. Porting to
Python keeps all write logic in one file and enables proper unit testing; behaviour is
identical.

### Add a 6th `AGENT_ID` argument to `write_memory_entry()`

Rejected because SOURCE already encodes the caller's identity (`conformance`, `code-review`),
and no current caller requires a different `agent_id` value. Adding an argument would force
edits to both gate command files for no current benefit.

### Add agentmemory REST fan-out

Dropped per #644 spike verdict and the `architecture.md` AVOID entry: "Do not introduce a
vector database, embedding model, or semantic search service for memory retrieval."
`index.jsonl` is the local flat-file substitute — no network I/O required.

### Exact substring match (existing `grep -qF` behaviour)

The current bash implementation is the floor. This spec extends to normalized substring match
(lowercase, whitespace collapse, punctuation strip) to handle minor rewordings carrying the
same lesson, producing one changed line instead of a duplicate entry.

## Open Questions (non-blocking)

1. **index.jsonl field reconciliation**: fields the write adapter cannot populate (`id`,
   `supersedes`, `confidence`, `concepts`, `rationale`, `pr_number`, `updated_at`) are
   omitted. #649 defines whether these are generated at import time or remain optional.

2. **Reinforcement in index.jsonl**: when normalized dedup triggers an in-place
   `date:`/`expires:` update in markdown, the matching `index.jsonl` record should also have
   its `expires_at` updated. Requires reading back the record's position. Deferred to #649;
   a reinforced markdown entry is not reflected in `index.jsonl` until the next import.

3. **index.jsonl gitignore status**: whether `.archon/memory/index.jsonl` is committed
   alongside the markdown files or gitignored (rebuilt by #649 import from markdown) is
   deferred to #649, which owns the import/sync contract.

4. **Read-path adoption**: the #646 read adapter (`memory_retrieve.py`) currently reads
   `.archon/memory/*.md` directly. `index.jsonl` enables structured filtering by role/scope
   but `memory_retrieve.py` does not yet consume it. Deferred to #646 implementation.

## Assumptions

- **[A1]** Python 3 is available in the dark-factory container at runtime (confirmed by
  existing `code_review_payload.py`, `fmt_hunk_filter.py`, `dedupe_oos.py` patterns).
- **[A2]** `gate_lib.sh` is always sourced from within the dark-factory repo tree, so
  `${BASH_SOURCE[0]}` reliably points to `dark-factory/scripts/gate_lib.sh`.
- **[A3]** Normalized substring match is sufficient for "highly similar" detection at
  current memory scale (<200 entries). Edit-distance or semantic similarity is out of scope.
- **[A4]** SOURCE values (`conformance`, `code-review`, `refine`, `implement`) are stable
  enough to serve as `agent_id` identifiers in `index.jsonl` records and markdown tags.
- **[A5]** `.archon/memory/index.jsonl` location is correct; gitignore decision deferred
  to #649.
