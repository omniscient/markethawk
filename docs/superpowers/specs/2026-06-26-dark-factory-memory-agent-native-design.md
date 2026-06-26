# Dark Factory — Agent-Native Memory Layer (Phase 1, 2, 5)

**Status:** design
**Date:** 2026-06-26
**Issue:** #643
**Labels:** Dark Factory, foundation, enhancement, priority: should-have, size: M

## Problem

The current Dark Factory memory system stores lessons as plain markdown bullets in five
`.archon/memory/*.md` files. The read path is a POSIX shell function (`load_memory()`)
that filters entries by `path:` prefix and injects the full filtered text into every agent
prompt. This approach has two compounding problems:

1. **No ranking** — every surviving entry is injected at equal weight, regardless of
   recency, entry kind, or how closely the path prefix matches the files actually being
   changed. Low-signal or near-stale entries crowd out high-signal ones at the same prompt
   cost.
2. **No observability** — there is no per-run record of which entries were selected, why
   they were selected, or whether they influenced the agent's output. It is impossible to
   determine whether memory is helping, hurting, or simply burning tokens.

The arXiv paper cited in the issue (2606.24775) frames agent memory as a data-management
system with four modules: representation, extraction, retrieval/routing, and maintenance.
The current system handles representation (markdown + HTML-comment tags) and maintenance
(expiry, cap, PROVISIONAL promotion) adequately. The gaps are **retrieval** (ranking, not
just filtering) and **evaluation** (observability artifacts).

## Scope

**In this ticket (Phases 1, 2, 5):**

- Phase 1 — Non-invasive index: parse `.archon/memory/*.md` into `.archon/memory/index.jsonl`
- Phase 2 — Read-path replacement: `dark-factory/scripts/memory_retrieve.py` + update
  `dark-factory-plan.md` and `dark-factory-implement.md` memory-loading to call the retriever
- Phase 5 — Evaluation trace: emit `$ARTIFACTS_DIR/memory-trace.json` per run listing which
  records were selected and why

**Explicitly deferred:**

- Phase 3 (write-path replacement: `memory_write.py` + rework `gate_lib.sh::write_memory_entry()`) — requires the index schema to be settled first; the write path is load-bearing for conformance and code-review gates
- Phase 4 (maintenance job: `memory_maintain.py`) — depends on Phase 3 output; no global rewrites during normal runs

**Permanently out of scope (per issue AVOID constraint):**

No vector database, embedding model, or semantic search. Ranking is deterministic, scoring
only over metadata already present in the HTML-comment tags.

## Requirements

1. A Python parser reads all five `.archon/memory/*.md` files and emits
   `.archon/memory/index.jsonl` — one JSON record per entry, containing all structured
   metadata currently encoded in HTML comments.

2. The index is gitignored and regenerated deterministically at Phase 1 LOAD (same pattern
   as `codeindex.json`/`symbolindex.json`). A stale or missing index is never a correctness
   risk; it only affects ranking freshness.

3. `memory_retrieve.py` accepts a query context (affected file paths, workflow phase, optional
   scope hint) and returns a ranked, filtered list of memory entries suitable for injecting
   into a prompt, excluding `[PROVISIONAL]` and `[INVALID]` entries by default.

4. Ranking uses only signals present in the existing metadata tags (no new write-path state):
   - **Expiry exclusion** — entries past their `expires:` date are dropped.
   - **Kind weighting** — `[PATTERN]` and `[AVOID]` outrank `[FIX]`; `[PROVISIONAL]` is
     excluded from default output.
   - **Path/scope match strength** — graded score: exact directory match > parent-prefix
     match > untagged (global). Extends today's binary prefix match.
   - **Recency decay** — entries with a newer `date:` tag score higher; smooth decay, not
     a hard cutoff.

5. The retriever preserves the existing prompt-injection format (rendered markdown bullets,
   not raw JSON) so all consuming command files require minimal changes.

6. Every factory run that uses the retriever emits
   `$ARTIFACTS_DIR/memory-trace.json` containing: selected entry IDs, their scores, the
   query context (affected files, phase), and a `total_entries_considered` count.

7. `dark-factory-plan.md` and `dark-factory-implement.md` replace their `load_memory()`
   shell function invocations with a call to `memory_retrieve.py`. The gate commands
   (`dark-factory-conformance.md`, `dark-factory-code-review.md`) are out of scope for
   this ticket; they continue using `gate_lib.sh`.

8. Tests cover: parse round-trip (all existing entry kinds), retrieval ranking (score
   ordering for known inputs), expiry exclusion, PROVISIONAL exclusion, markdown rendering
   of retriever output, and memory-trace JSON schema validation.

9. Existing Dark Factory tests (including `test_conformance_memory_write.sh`) continue to
   pass unchanged — the write path (`gate_lib.sh::write_memory_entry()`) is not modified.

## Architecture

### Record schema (`index.jsonl`)

Each line is a JSON object:

```json
{
  "id": "<sha256 of source_file + line_content, first 12 hex chars>",
  "kind": "PATTERN | AVOID | FIX | PROVISIONAL | INVALID",
  "scope": "backend | frontend | dark-factory | architecture | codebase",
  "path_prefixes": ["dark-factory/scripts/"],
  "summary": "the text of the bullet point (plain text, no markdown tags)",
  "raw_line": "- [AVOID] original line text <!-- ... -->",
  "source_file": ".archon/memory/dark-factory-ops.md",
  "issue": 194,
  "source_agent": "implement",
  "date": "2026-06-05",
  "expires_at": "2026-12-05"
}
```

Fields not present in a tag are `null`. `scope` is inferred from `source_file`
(e.g. `dark-factory-ops.md` → `"dark-factory"`; `architecture.md` → `"architecture"`).

The parser is idempotent and deterministic — same source files always produce the same
`index.jsonl` (stable IDs allow trace files to reference records across runs).

### Retriever (`memory_retrieve.py`)

CLI interface:
```sh
python3 dark-factory/scripts/memory_retrieve.py \
  --affected-files "backend/app/services/scanner.py backend/app/models/scanner.py" \
  --phase implement \
  --scope backend \
  --top-k 20 \
  --trace-output "$ARTIFACTS_DIR/memory-trace.json"
```

Outputs rendered markdown bullets to stdout (same format as current `load_memory()`), so
callers substitute the script call for the shell function with no downstream format change.

**Scoring function (per entry):**

```
score = kind_weight * path_score * recency_factor
```

- `kind_weight`: PATTERN/AVOID = 1.0, FIX = 0.8, (PROVISIONAL excluded = 0.0)
- `path_score`: exact dir match = 1.0, parent-prefix = 0.7, untagged global = 0.4;
  if entry has multiple path prefixes, uses the highest match score
- `recency_factor`: `1.0 - 0.3 * min(days_since_date / 180, 1.0)` — linear decay from 1.0
  to 0.7 over 6 months, then clamped at 0.7 (never drops below 30% weight from recency alone)

Entries that have passed their `expires_at` date are hard-excluded before scoring.

Top-K results are returned sorted descending by score. Ties broken by `date` descending.

### Memory-trace artifact

`$ARTIFACTS_DIR/memory-trace.json`:

```json
{
  "run_id": "...",
  "phase": "implement",
  "query_context": {
    "affected_files": ["backend/app/services/scanner.py"],
    "scope": "backend"
  },
  "total_entries_in_index": 87,
  "total_after_expiry_filter": 82,
  "total_after_kind_filter": 78,
  "selected": [
    {
      "id": "a1b2c3d4e5f6",
      "kind": "PATTERN",
      "summary": "...",
      "score": 0.94,
      "path_score": 1.0,
      "kind_weight": 1.0,
      "recency_factor": 0.94
    }
  ]
}
```

### Integration with command files

In `dark-factory-plan.md` and `dark-factory-implement.md`, the current Phase 1 LOAD block:

```bash
# Current (shell)
load_memory() { ... }
load_memory codebase-patterns.md
load_memory architecture.md
...
```

becomes:

```bash
# New (Python retriever)
python3 dark-factory/scripts/memory_parse.py  # regenerate index.jsonl
MEMORY_CONTEXT=$(python3 dark-factory/scripts/memory_retrieve.py \
  --affected-files "$AFFECTED" \
  --phase plan \
  --scope "$COMPONENT_SCOPE" \
  --top-k 25 \
  --trace-output "$ARTIFACTS_DIR/memory-trace.json")
```

The retriever handles the cross-file query that previously required four separate `load_memory`
calls. The markdown output format is identical, so the downstream template substitution for
`$MEMORY_CONTEXT` is unchanged.

## Alternatives Considered

### Alternative A: Keep the shell function, add only ranking in shell

Extend `load_memory()` to score entries using `awk`. This is feasible for simple
path scoring but rapidly becomes unmaintainable for multi-factor scoring (recency math,
structured JSON tags). Python is already used for all other Dark Factory scripts
(`dedupe_oos.py`, `check_workflow_dag.py`, `gate_blast_radius.py`). Rejected.

### Alternative B: Committed `index.jsonl`

Commit `index.jsonl` to git alongside the markdown files. Rejected because: (1) the index
is a generated projection of the markdown files, which are already committed and
version-controlled, (2) factory runs that modify memory would need to also rebuild and
commit the index, adding noise to every PR diff, and (3) parallel factory worktrees would
collide on `index.jsonl` — reproducing the merge-conflict issue that drove `codeindex.json`
into `.gitignore` (see CLAUDE.md).

### Alternative C: Retrieval scoring over all 5 issue-specified factors (full-as-specified)

Include issue-label matching, workflow-phase matching, evidence-count scoring, and
prior-retrieval-usefulness weighting. Rejected because: factors like "prior retrieval
usefulness" and "evidence count" require new write-path state that Phase 3 (deferred) would
provide. Building partial wiring for these now would produce scoring inputs that are always
`null`, which would silently produce lower-quality ranking than the simpler 3-factor formula.
Defer to Phase 3+4.

## Open Questions (Non-Blocking)

- **`--top-k` tuning**: 25 is a reasonable default but the right number depends on measured
  prompt-token cost vs. retrieval precision. The memory-trace artifact makes this measurable;
  the default can be adjusted after Phase 5 data is collected.
- **Scope hint inference**: The current plan requires the command file to pass `--scope` explicitly.
  Automatically inferring scope from `--affected-files` paths would remove a manual parameter.
  Straightforward to add to the retriever but left as a follow-on to keep this ticket small.

## Assumptions

- **[A1]** All five `.archon/memory/*.md` files follow the current entry format
  (`- [KIND] text <!-- key:value ... -->`) consistently enough for a regex parser to extract
  them. Minor malformed entries (missing closing `-->`) are skipped with a warning, not fatal.
- **[A2]** The `$ARTIFACTS_DIR` environment variable is set in the factory environment
  (per existing `dark-factory-implement.md` conventions). If absent, the retriever writes
  the trace to `/tmp/memory-trace.json`.
- **[A3]** The Python environment in the dark-factory container (Python 3.11) is the
  runtime target; no third-party library dependencies beyond the standard library are
  introduced by this ticket.
- **[A4]** `dark-factory-conformance.md` and `dark-factory-code-review.md` continue using
  `gate_lib.sh` for memory writes and reads. They are out of scope until Phase 3.

## Implementation Notes

- Two scripts: `dark-factory/scripts/memory_parse.py` (Phase 1, parse → index.jsonl) and
  `dark-factory/scripts/memory_retrieve.py` (Phase 2, rank → markdown output).
- Tests live in `dark-factory/tests/test_memory_retrieve.py` (pytest).
- Add `.archon/memory/index.jsonl` to `.gitignore`.
- Update `dark-factory-plan.md` and `dark-factory-implement.md` Phase 1 LOAD sections.
- The `memory_retrieve.py` `--trace-output` flag is optional; if omitted no trace file is written (safe for command files not yet Phase-5-aware).
