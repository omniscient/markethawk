# Write-Through Memory Adapter for agentmemory and .archon Markdown

**Status:** design
**Date:** 2026-06-27
**Issue:** #648
**Epic:** #643 (Improve Dark Factory memory system using agent-native memory architecture)
**Phase:** 3 of 5 (write-path replacement)
**Related:** #645 (schema), #646 (read-through retrieval), #649 (import existing memory)

## Problem

The Dark Factory's memory write path lives entirely in `gate_lib.sh::write_memory_entry()`.
It appends `[AVOID]` entries to `.archon/memory/*.md` files with dedup, expiry cleanup, and a
30-entry cap — but the logic is bash-only, difficult to test, and tightly coupled to markdown.

Epic #643 introduces `agentmemory` (`rohitg00/agentmemory`) as a structured/indexed backend.
Phase 3 is the write-path replacement: every memory write must now fan out to both the
agentmemory backend (structured/indexed) and the `.archon/memory/*.md` files (human-readable
contract), while keeping the existing bash callers unchanged.

## Requirements

Distilled from issue #648 acceptance criteria and Q&A:

1. **Dual write**: every validated memory event is written to `agentmemory` (structured) and
   rendered into the appropriate `.archon/memory/*.md` file.
2. **Write seam preserved**: existing callers of `gate_lib.sh::write_memory_entry()` (conformance
   and code-review commands) work without code-path changes beyond the `gate_lib.sh` update.
3. **Markdown-first ordering**: markdown is written unconditionally before the agentmemory call.
   Markdown is the source of truth.
4. **Best-effort agentmemory**: agentmemory failures (connection refused, timeout, HTTP 5xx) are
   logged at WARNING and are non-fatal; the write returns success.
5. **Symmetric skip**: when markdown is skipped (dedup match or cap reached), agentmemory is also
   skipped. The two stores stay consistent.
6. **Normalized dedup**: duplicate detection uses normalized substring match (lowercase, collapse
   whitespace, strip trailing punctuation). On match, update the existing entry's `date:` and
   `expires:` in place rather than appending a new line.
7. **Configurable backend URL**: `AGENTMEMORY_BASE_URL` env var (default `http://agentmemory:8000`).
8. **Tested**: unit tests cover markdown write, normalized dedup, cap enforcement, expiry cleanup,
   reinforcement (in-place date/expires update), and all agentmemory failure modes.
9. **Stable diffs**: markdown output is append-only (new entries) or single-line changes
   (in-place reinforcement), never a full-file rewrite.

## Approach Selection

### Approach A — Full Python ownership, bash delegation (selected)

`memory_write.py` owns all write logic: routing, normalized dedup, expiry cleanup, cap,
markdown insertion, and the agentmemory POST. `gate_lib.sh::write_memory_entry()` becomes a
5-line bash wrapper that shells out to `memory_write.py` with the same 5-argument signature.

Advantages:
- All write logic centralized and testable with pytest.
- The no-op/skip signal (dedup hit, cap reached) is naturally available to the agentmemory
  step in the same process — no bash-to-bash handshake needed.
- Matches the established pattern: conformance and code-review already shell out to
  `code_review_payload.py`, `fmt_hunk_filter.py`, `dedupe_oos.py`.
- The AC "routes through the adapter" is literally satisfied — every markdown write goes
  through the Python adapter.

### Approach B — Additive (rejected)

Keep the existing bash markdown logic intact, call Python only for the agentmemory step.
Rejected: splits the dedup/cap/skip decision across bash and Python, requiring bash to
re-derive the markdown outcome for the agentmemory skip signal. Contradicts the AC
("routes through the adapter" means the adapter is the write path, not a supplemental step).

### Approach C — Full markdown re-render (rejected)

Python re-renders the entire markdown file from scratch on each write.
Rejected: violates the "stable diffs" requirement; produces large, unreadable diffs when a
single entry is added or updated.

## Architecture

### File layout

```
dark-factory/scripts/
  memory_write.py         # new — full write adapter (this issue)
  gate_lib.sh             # modified — write_memory_entry() delegates to memory_write.py
dark-factory/tests/
  test_memory_write.py    # new — pytest unit tests
```

### `memory_write.py` — command-line interface

```
python3 memory_write.py \
  --target    <abs-or-rel path to .archon/memory/*.md>   \
  --path-prefix <e.g. backend/app/>                       \
  --text       <core lesson text without tag prefix>      \
  --source     <refine|implement|conformance|code-review> \
  --issue      <issue number>
```

Exit codes:
- `0`: markdown write succeeded or was intentionally skipped (dedup/cap).
- `1`: markdown write failed (file I/O error). agentmemory failures do **not** set exit 1.

### `memory_write.py` — write pipeline

```
1. Validate args (target file path, non-empty text).
2. Normalize candidate: lowercase, collapse whitespace, strip trailing punctuation.
3. Load target markdown, scan for existing [PATTERN]/[AVOID]/[FIX] lines.
4. Normalize each existing entry body the same way.
5. Dedup check:
   a. If normalized candidate ∈ normalized existing bodies → REINFORCE:
      update the matching line's date: and expires: in-place; set skip_agentmemory=True.
   b. Else continue.
6. Cap check: count [PATTERN]/[AVOID]/[FIX] lines. If ≥ 30 → log WARNING, skip write; set skip_agentmemory=True.
7. Expiry cleanup: remove lines where expires: date < today (existing awk logic, ported to Python).
8. Write entry as [AVOID] line with metadata before --- PROVISIONAL delimiter (or append).
9. If skip_agentmemory → return 0.
10. Best-effort agentmemory POST:
    - Read AGENTMEMORY_BASE_URL (default http://agentmemory:8000).
    - Health-check optional (can skip to save latency, failure already handled below).
    - POST /agentmemory/memories with structured payload (see below).
    - On success: log INFO "agentmemory: saved".
    - On connection error, timeout, HTTP 5xx: log WARNING "agentmemory: unavailable (<reason>)".
    - On HTTP 4xx (bad payload): log WARNING "agentmemory: rejected (<status>)".
11. Return 0.
```

### agentmemory write payload

The exact agentmemory create-endpoint path and schema are not yet confirmed in this repo — they
depend on the `rohitg00/agentmemory` service evaluated in spike #644.
**Assumption**: `POST /agentmemory/memories` with the following shape (based on epic #643):

```json
{
  "project": "markethawk",
  "kind": "AVOID",
  "scope": "<derived from target filename>",
  "path_prefixes": ["<path_prefix>"],
  "summary": "<text>",
  "evidence": [{"issue": <issue>, "source": "<source>", "date": "<today>"}],
  "expires_at": "<today + 6 months>"
}
```

**Design contract**: if the actual endpoint or payload shape differs from the spike findings,
only `memory_write.py` needs updating. The bash gate commands and markdown files are unaffected.

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

Note: `${BASH_SOURCE[0]}` (not `$0`) is required because `gate_lib.sh` is sourced, not executed.
`route_memory_file()` and `emit_verdict()` remain as bash — they are not write logic.

### agentmemory service (out of scope for this issue)

Adding the `agentmemory` Docker service to `docker-compose.yml` or a compose profile is tracked
as a dependency but is **not in scope here**. `memory_write.py` handles the unavailable case
(best-effort, non-fatal) so it ships and works before the sidecar is wired up.

## Alternatives Considered

### Keep expiry cleanup in bash (awk)

The existing awk block in `gate_lib.sh` (lines 29-35) handles expiry cleanup. Porting to Python
keeps all write logic in one file and enables proper unit testing; the behavior is identical.

### Use agentmemory query to drive dedup

Query agentmemory for semantic matches before writing. Rejected per architecture memory:
"Do not introduce a vector database, embedding model, or semantic search service."
Also makes dedup depend on the optional/unavailable sidecar, violating Requirement 5.

### Exact substring match (existing behavior)

The current `grep -qF` is the floor. The spec extends to normalized substring match
(lowercase, whitespace collapse, punctuation strip) to handle minor rewordings that
carry the same lesson, producing one changed line instead of a duplicate entry.

## Open Questions (non-blocking)

1. **Exact agentmemory endpoint paths**: the spike (#644) documents the health probe
   (`GET /agentmemory/health`) but not the create-memory route. The adapter should read the
   endpoint from a second env var (`AGENTMEMORY_MEMORIES_PATH`, default `/agentmemory/memories`)
   so it can be adjusted without a code change once the spike findings are confirmed.

2. **agentmemory auth**: the spike may reveal an API key requirement. Add `AGENTMEMORY_API_KEY`
   env var support as a `Bearer` token header; omit the header when unset.

3. **Reinforcement on agentmemory side**: when a normalized dedup match triggers an in-place
   date/expires update in markdown, the adapter should also PATCH or re-POST the corresponding
   agentmemory record. This requires knowing the record ID from a prior write. Deferred to the
   lifecycle maintenance ticket (#650) — for now, a reinforced markdown entry is not reflected in
   agentmemory (the next import/sync ticket #649 will reconcile).

## Assumptions

- **[A1]** Python 3 is available in the dark-factory container at runtime (confirmed by existing
  `code_review_payload.py`, `fmt_hunk_filter.py`, `dedupe_oos.py` patterns).
- **[A2]** `gate_lib.sh` is always sourced from within the dark-factory repo tree, so
  `${BASH_SOURCE[0]}` reliably points to `dark-factory/scripts/gate_lib.sh`.
- **[A3]** The agentmemory sidecar is not yet deployed; `memory_write.py` must work correctly
  in its absence (best-effort, non-fatal).
- **[A4]** The create-memory endpoint follows the pattern `POST /agentmemory/memories` with a
  JSON body; this will be confirmed against spike #644 findings before implementation.
- **[A5]** Normalised dedup (B from Q3) is sufficient for "highly similar" detection at
  current memory scale (<200 entries). Edit-distance or semantic similarity is explicitly out
  of scope.
