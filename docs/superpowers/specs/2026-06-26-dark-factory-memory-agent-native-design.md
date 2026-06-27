# Dark Factory — Agent-Native Memory Layer (All 5 Phases)

**Status:** design  
**Date:** 2026-06-27 (revised from 2026-06-26; expanded to all 5 phases)  
**Issue:** #643  
**Labels:** Dark Factory, foundation, enhancement, priority: should-have, size: M

## Problem

The current Dark Factory memory system stores lessons as plain markdown bullets in five
`.archon/memory/*.md` files. The read path is a POSIX shell function (`load_memory()`)
that filters entries by `path:` prefix and injects the full filtered text into every agent
prompt. The write path is `gate_lib.sh::write_memory_entry()`, which does basic expiry
cleanup and a 30-entry cap but no schema validation, semantic dedup, or confidence tracking.
This approach has four compounding problems:

1. **No ranking** — every surviving entry is injected at equal weight, regardless of
   recency, entry kind, or how closely the path prefix matches the files actually being
   changed.
2. **No semantic dedup** — near-duplicate entries accumulate as different runs independently
   learn the same lesson with slightly different wording.
3. **No observability** — there is no per-run record of which entries were selected, why
   they were selected, or whether they influenced the agent's output.
4. **No lifecycle management** — `[PROVISIONAL]` entries have no automated promotion path;
   stale entries degrade signal quality for all future runs.

The arXiv paper cited in the issue (2606.24775) frames agent memory as a data-management
system with four modules: representation, extraction, retrieval/routing, and maintenance.
This spec covers all five proposed implementation phases.

## Scope

**All 5 phases are in scope for this ticket:**

- **Phase 1** — Non-invasive index: parse `.archon/memory/*.md` into `.archon/memory/index.jsonl`
- **Phase 2** — Read-path replacement: `memory_retrieve.py` replaces `load_memory()` in
  `dark-factory-plan.md` and `dark-factory-implement.md`, adding ranked + semantic retrieval
- **Phase 3** — Write-path replacement: `memory_write.py` handles schema-validated, semantically-
  deduped writes; `gate_lib.sh::write_memory_entry()` becomes a thin shell wrapper
- **Phase 4** — Maintenance job: `memory_maintain.py` runs as a post-run Archon DAG terminal
  node, scoped to the files/clusters modified in that run
- **Phase 5** — Evaluation trace: per-run `$ARTIFACTS_DIR/memory-trace.json` listing selected
  entries, scores, and query context

**Explicitly out of scope:**

- No new Docker services — the entire system runs as pip-installed Python tooling inside
  the existing dark-factory container
- No new application database tables or migrations — vectors are stored locally in `.archon/`
- No global memory rewrite passes during normal runs

## Requirements

1. A Python parser (`memory_parse.py`) reads all five `.archon/memory/*.md` files and emits
   `.archon/memory/index.jsonl` — one JSON record per entry.

2. Both `.archon/memory/index.jsonl` and `.archon/memory/vectors.db` are gitignored and
   regenerated deterministically at Phase 1 LOAD (same pattern as `codeindex.json`).

3. `memory_retrieve.py` accepts a query context (affected file paths, workflow phase,
   optional scope hint) and returns a ranked, filtered list of memory entries, excluding
   `[PROVISIONAL]` and `[INVALID]` entries by default.

4. Retrieval uses a **hybrid scoring model**:
   - **First-pass filter**: deterministic 3-factor scoring (kind × path-match × recency)
     as a fast first-pass and graceful-degradation fallback when offline or lacking an API key.
   - **Semantic re-rank** (when vectors available): sqlite-vec ANN query over pre-computed
     entry embeddings, blended with the deterministic score to produce a final rank.

5. Embeddings are generated at index time (Phase 1) via an API call (e.g., Anthropic), cached
   by entry content-hash in `vectors.db`. Unchanged entries are never re-embedded. When the
   embedding API is unavailable, the system falls back to deterministic-only scoring without error.

6. `memory_write.py` is the canonical write path. It accepts the same 5-arg contract as
   `write_memory_entry()` (`TARGET PATH_PREFIX VIOLATION_TEXT SOURCE ISSUE_NUM`) and, on
   each write, atomically: validates the entry against the structured schema, performs exact-
   match dedup, enforces the 30-entry cap, runs expiry cleanup, appends to the markdown file,
   and updates `index.jsonl`. Expensive operations (semantic dedup, PROVISIONAL promotion)
   are deferred to the maintenance step.

7. `gate_lib.sh::write_memory_entry()` and `route_memory_file()` become thin shell wrappers
   delegating to `memory_write.py`. Gate command files (`dark-factory-conformance.md`,
   `dark-factory-code-review.md`) are **not modified** — they continue to call the same shell
   functions by name.

8. `memory_maintain.py` runs as a terminal node in `archon-dark-factory.yaml`, once per
   factory run, scoped to the set of memory files/path-clusters modified during that run.
   It performs: semantic similarity dedup (sqlite-vec ANN, ≥0.92 cosine threshold),
   `[PROVISIONAL]`→`[PATTERN]` promotion (requires second evidence from a different issue),
   and superseded/invalidation marking. It never rewrites memory files outside the touched scope.

9. Every factory run that invokes `memory_retrieve.py` emits `$ARTIFACTS_DIR/memory-trace.json`
   containing: selected entry IDs, scores (deterministic + semantic), query context, and counts
   at each filter stage.

10. `dark-factory-plan.md` and `dark-factory-implement.md` replace their `load_memory()` shell
    function blocks with a two-step call: regenerate the index, then invoke `memory_retrieve.py`.

11. Tests cover: parse round-trip (all entry kinds), retrieval ranking (score ordering for known
    inputs), expiry exclusion, PROVISIONAL exclusion, markdown rendering, memory-trace JSON schema,
    write dedup/cap/expiry, shell wrapper contract, and maintenance promotion/dedup logic.

12. Existing Dark Factory tests continue to pass, including `test_conformance_memory_write.sh`
    (shell routing assertions preserved; depth of coverage migrated to Python tests).

## Architecture

### Record schema (`index.jsonl`)

Each line is a JSON object:

```json
{
  "id": "<sha256 of source_file + normalized_line, first 12 hex chars>",
  "kind": "PATTERN | AVOID | FIX | PROVISIONAL | INVALID",
  "scope": "backend | frontend | dark-factory | architecture | codebase",
  "path_prefixes": ["dark-factory/scripts/"],
  "summary": "the text of the bullet (plain text, HTML comment stripped)",
  "raw_line": "- [AVOID] original line text <!-- ... -->",
  "source_file": ".archon/memory/dark-factory-ops.md",
  "issue": 194,
  "source_agent": "implement",
  "date": "2026-06-05",
  "expires_at": "2026-12-05",
  "content_hash": "<sha256 of summary, stable for embedding cache key>"
}
```

Fields not present in a tag are `null`. `scope` is inferred from `source_file`.

### Vector store (`vectors.db`)

SQLite database managed by the `sqlite-vec` pip package. Schema:

```sql
CREATE VIRTUAL TABLE memory_vectors USING vec0(
  id TEXT PRIMARY KEY,
  embedding FLOAT[384]   -- dimension matches chosen embedding model
);
```

`vectors.db` is regenerated alongside `index.jsonl` at Phase 1 LOAD. New entries not yet
in `vectors.db` are embedded in a single batch call; existing content-hashes are skipped.

### Retriever (`memory_retrieve.py`)

CLI interface:
```sh
python3 dark-factory/scripts/memory_retrieve.py \
  --affected-files "backend/app/services/scanner.py" \
  --phase implement \
  --scope backend \
  --query "sqlalchemy async session pattern" \
  --top-k 20 \
  --trace-output "$ARTIFACTS_DIR/memory-trace.json"
```

**Scoring function:**

```
deterministic_score = kind_weight × path_score × recency_factor

final_score = α × deterministic_score + (1 − α) × semantic_similarity
```

Where:
- `kind_weight`: PATTERN/AVOID = 1.0, FIX = 0.8 (PROVISIONAL = excluded)
- `path_score`: exact dir = 1.0, parent-prefix = 0.7, untagged global = 0.4
- `recency_factor`: linear decay 1.0→0.7 over 6 months (clamped at 0.7)
- `semantic_similarity`: cosine similarity from sqlite-vec ANN query, in [0.0, 1.0]
- `α`: 0.5 when vectors available; 1.0 (deterministic only) when vectors absent

Output: rendered markdown bullets (same format as current `load_memory()`).

### Writer (`memory_write.py`)

Invoked by the shell wrapper in `gate_lib.sh` with the same 5 positional args:

```bash
# gate_lib.sh (thin wrapper)
write_memory_entry() {
  python3 "$(git rev-parse --show-toplevel)/dark-factory/scripts/memory_write.py" \
    "$1" "$2" "$3" "$4" "$5"
}
```

Write sequence (all inline, fast):
1. Parse and validate the entry against the structured schema
2. Exact-match dedup against `index.jsonl` (same scope + normalized summary + same path cluster)
3. Expiry cleanup on the target markdown file (awk one-pass, same as current behavior)
4. 30-entry cap enforcement (warn + drop oldest if exceeded)
5. Append to markdown file and append to `index.jsonl` (no PROVISIONAL-section re-sort)
6. Record the write in `$ARTIFACTS_DIR/write-log.jsonl` for the maintenance step

### Maintenance (`memory_maintain.py`)

Archon DAG terminal node in `archon-dark-factory.yaml`:

```yaml
- id: memory-maintain
  task: "Run memory maintenance on touched scope clusters"
  depends_on: [report]
  trigger_rule: none_failed_min_one_success
```

Operations (localized to touched scope only, in order):
1. **Semantic dedup**: for each new entry written this run, query sqlite-vec ANN with cosine
   threshold ≥ 0.92; if a near-duplicate exists, mark the lower-confidence entry
   `[INVALID: superseded by <id>]` in the markdown file and remove it from `index.jsonl`.
2. **PROVISIONAL promotion**: for each `[PROVISIONAL]` entry, check `index.jsonl` for a
   confirming entry from a different issue number with overlapping summary embedding
   (cosine ≥ 0.85); if found, rewrite as `[PATTERN]` in the markdown file and update the record.
3. **Superseded marking**: if an entry's `expires_at` is within 14 days, emit a warning in
   the trace; if past expiry, mark `[INVALID: expired]` and remove from index.
4. Emit `$ARTIFACTS_DIR/maintenance-report.json` listing all changes made.

### Integration with command files

In `dark-factory-plan.md` and `dark-factory-implement.md`, the current Phase 1 LOAD block:

```bash
# Current (shell)
load_memory() { ... }
load_memory codebase-patterns.md
load_memory architecture.md
```

becomes:

```bash
# New (Python)
python3 dark-factory/scripts/memory_parse.py  # regenerate index.jsonl + vectors.db
MEMORY_CONTEXT=$(python3 dark-factory/scripts/memory_retrieve.py \
  --affected-files "$AFFECTED" \
  --phase plan \
  --scope "$COMPONENT_SCOPE" \
  --query "$ISSUE_TITLE" \
  --top-k 25 \
  --trace-output "$ARTIFACTS_DIR/memory-trace.json")
```

The markdown output format is identical, so the downstream `$MEMORY_CONTEXT` substitution
in prompt templates is unchanged.

### Memory-trace artifact

`$ARTIFACTS_DIR/memory-trace.json`:

```json
{
  "run_id": "...",
  "phase": "implement",
  "query_context": {
    "affected_files": ["backend/app/services/scanner.py"],
    "scope": "backend",
    "query": "sqlalchemy async session"
  },
  "total_entries_in_index": 87,
  "total_after_expiry_filter": 82,
  "total_after_kind_filter": 78,
  "embedding_available": true,
  "selected": [
    {
      "id": "a1b2c3d4e5f6",
      "kind": "PATTERN",
      "summary": "...",
      "final_score": 0.91,
      "deterministic_score": 0.88,
      "semantic_similarity": 0.94,
      "path_score": 1.0,
      "kind_weight": 1.0,
      "recency_factor": 0.94
    }
  ]
}
```

## Alternatives Considered

### Alternative A: Keep shell function, add only deterministic ranking in shell

Extend `load_memory()` to score entries using `awk`. Feasible for path scoring but
unmaintainable for multi-factor scoring (recency math, structured JSON tags, semantic
similarity). Python is already the standard for Dark Factory scripts. Rejected.

### Alternative B: Committed `index.jsonl`

Commit `index.jsonl` to git alongside the markdown files. Rejected because: the index is
a generated projection of committed markdown files; parallel factory worktrees would collide
on `index.jsonl` (the same root cause that drove `codeindex.json` into `.gitignore`).

### Alternative C: pgvector for vector storage

Use the `pgvector` PostgreSQL extension with embeddings in a `memory_embeddings` table.
Rejected because: the Dark Factory container must work during startup passes before any
application stack is up; coupling memory retrieval to a live DB connection makes the factory
brittle in the exact isolation contexts where it's most needed. sqlite-vec has zero service
dependencies.

### Alternative D: sentence-transformers local model

Install `sentence-transformers` + a small model locally. Adds ~500MB to the container image
for a 200-entry corpus. The existing Dockerfile is deliberately lean (only `codeindex` +
`pre-commit`). API-generated embeddings cached by content-hash achieve the same result
without image bloat.

### Alternative E: Parallel write paths (old + new)

Keep `gate_lib.sh` write path unchanged; add `memory_write.py` as a new path for Phase 3+
consumers only. Rejected because entries written by the old path would miss `index.jsonl`
and `vectors.db` until the next full reindex, creating consistency gaps that this issue
specifically exists to close.

### Alternative F: Option B (Python called directly from gate commands)

Remove shell functions; gate command files call `python3 memory_write.py` directly.
Increases the blast radius of Phase 3 (gate command prompts must be edited) with no
benefit over the thin-wrapper approach. Rejected.

### Alternative G: `rohitg00/agentmemory` as primary backend

The Hermes Agent (research, gpt-5.5) reviewed the `rohitg00/agentmemory` library
(commit `f6f9e3c`) and recommended it as the structured memory backend: BM25+vector+graph
hybrid retrieval, a Lessons API with confidence/reinforcement/decay, and multi-agent
coordination primitives (leases, actions) via a REST API on port 3111 or an NPX shim.

**Rejected as the primary backend for this ticket.** Two hard constraints rule it out:

1. **New runtime service dependency.** The Dark Factory container must be fully functional
   during startup isolation passes — before the application stack (postgres, redis, backend)
   is up — and in per-issue preview worktrees where no auxiliary services are running.
   agentmemory's REST API on port 3111 (or an `npx`-launched Node process) reintroduces
   exactly the service-coupling fragility this architecture avoids. sqlite-vec has zero
   runtime dependencies beyond the Python standard library.

2. **Over-engineered for a ~200-entry, single-writer-per-worktree corpus.** BM25+vector+graph
   retrieval, graph stores, and lease/action coordination solve problems (corpus scale,
   concurrent multi-agent writes to a shared store) that do not yet exist here. The hybrid
   sqlite-vec + 3-factor deterministic model specified in Phase 2 covers the same retrieval
   needs without a Node toolchain or a new container.

**Future option — revisit when:**
- The memory corpus exceeds ~2,000 entries and graph-structure retrieval starts paying off, or
- A future ticket introduces genuinely concurrent multi-agent writes to a *shared*
  (non-per-worktree) memory store, at which point agentmemory's lease/action primitives
  become relevant.

**If adopted in the future:** integrate as a read-through (then write-through) adapter behind
the `memory_retrieve.py` / `memory_write.py` interfaces already defined here, preserving
`.archon/memory/*.md` as the git-committed human-readable surface — which is exactly the
staged adapter approach the Hermes Agent recommends.

## Open Questions (Non-Blocking)

- **`--top-k` tuning**: 25 is a reasonable default. The memory-trace artifact makes this
  measurable after the first production runs; the default can be adjusted based on data.
- **Embedding model selection**: Specific model to use for embeddings (e.g., `text-embedding-3-small`
  via OpenAI, or Anthropic equivalent). The spec is agnostic; the implementation should
  read the model from an environment variable (`MEMORY_EMBED_MODEL`) to allow future swaps.
- **Semantic similarity threshold calibration**: The 0.92 (dedup) and 0.85 (PROVISIONAL
  promotion) thresholds are educated guesses. Both should be configurable and tuned after
  the first batch of production runs.
- **`--scope` inference**: The current plan requires callers to pass `--scope` explicitly.
  Automatic inference from `--affected-files` paths is straightforward and can be added
  as a follow-on without changing the spec.

## Assumptions

- **[A1]** All five `.archon/memory/*.md` files follow the current entry format
  (`- [KIND] text <!-- key:value ... -->`) consistently enough for a regex parser to extract
  them. Minor malformed entries are skipped with a warning, not fatal.
- **[A2]** `$ARTIFACTS_DIR` is set in the factory environment; falls back to `/tmp/` if absent.
- **[A3]** The Python environment in the dark-factory container (Python 3.14, Ubuntu 26.04)
  is the runtime target. `sqlite-vec` is a pip-installable package with no native library
  beyond the bundled SQLite extension. No PyTorch or heavy ML frameworks.
- **[A4]** An embedding API is available in the factory environment (read from
  `ANTHROPIC_API_KEY` or similar). When absent, the system falls back to deterministic-only
  scoring with a warning, not an error.
- **[A5]** `dark-factory-conformance.md` and `dark-factory-code-review.md` source
  `gate_lib.sh` and call `write_memory_entry()` by the existing 5-arg contract, which is
  preserved verbatim by the shell wrapper.
- **[A6]** The `memory-maintain` Archon DAG node is an OR-join consumer of the `report`
  node; it must declare `trigger_rule: none_failed_min_one_success` per the existing DAG
  conventions (see `REQUIRED_OR_JOIN_NODES` in `check_workflow_dag.py`).

## Implementation Notes

**Scripts to add:**
- `dark-factory/scripts/memory_parse.py` — Phase 1 (parse markdown → `index.jsonl` + seed `vectors.db`)
- `dark-factory/scripts/memory_retrieve.py` — Phase 2 (ranked + semantic retrieval → markdown output)
- `dark-factory/scripts/memory_write.py` — Phase 3 (schema-validated write, inline dedup/cap/expiry)
- `dark-factory/scripts/memory_maintain.py` — Phase 4 (post-run semantic dedup, PROVISIONAL promotion)

**Files to modify:**
- `dark-factory/scripts/gate_lib.sh` — `write_memory_entry()` and `route_memory_file()` become thin wrappers
- `.archon/commands/dark-factory-plan.md` — replace `load_memory()` block
- `.archon/commands/dark-factory-implement.md` — replace `load_memory()` block
- `.archon/archon-dark-factory.yaml` — add `memory-maintain` terminal node
- `dark-factory/Dockerfile` — add `sqlite-vec` to pip install layer
- `.gitignore` — add `.archon/memory/index.jsonl` and `.archon/memory/vectors.db`

**Tests:**
- `dark-factory/tests/test_memory_parse.py` — parse round-trip, all entry kinds
- `dark-factory/tests/test_memory_retrieve.py` — ranking, expiry exclusion, PROVISIONAL exclusion,
  markdown output, trace JSON schema, offline fallback (no vectors)
- `dark-factory/tests/test_memory_write.py` — dedup, cap, expiry, schema validation, shell wrapper contract
- `dark-factory/tests/test_memory_maintain.py` — semantic dedup (mocked ANN), PROVISIONAL promotion,
  invalidation, touched-scope isolation (files outside scope not modified)
- `dark-factory/tests/test_conformance_memory_write.sh` — shell routing assertions preserved as
  regression guard; depth of coverage for write logic migrated to Python
