# Read-Through Memory Retrieval Adapter

**Status:** design  
**Date:** 2026-06-27 (re-spec)  
**Issue:** #646  
**Epic:** #643 — Improve Dark Factory memory system using agent-native memory architecture  
**Component:** `dark-factory/scripts/memory_retrieve.py`

## Problem

Dark Factory agents load memory by running a bash `load_memory()` function defined inline in each
`.archon/commands/*.md` prompt file. This function reads `.archon/memory/*.md`, applies path-tag
filtering, and emits plain-text lines that the agent injects into its prompt context.

The limitations: (1) each command file carries a copy of the same bash logic; (2) the function
loads the entire corpus without role-based segregation — a refine run sees implement entries and
vice versa; (3) there is no hook for the `index.jsonl` scoring substrate from #649 to improve
relevance ordering.

Issue #646 is Phase 2 of the parent epic (#643): replace `load_memory()` with a single Python CLI
that applies role-segregated, path-aware filtering and, when `index.jsonl` is present, ranks
surviving entries by relevance score. The script is **flat-file only** — no `agentmemory` library,
no HTTP service, no vector database.

## Requirements

Derived from the issue acceptance criteria, user feedback, and Q&A:

1. **CLI invocation** — `dark-factory/scripts/memory_retrieve.py` is a runnable Python script.
   Its stdout is a markdown block that can be substituted for the current `load_memory()` output
   without other changes to `.archon/commands/*.md` files.

2. **Inputs**
   - `--phase <refine|plan|implement|validate|review>` — drives Layer 2 source-filter and area selection.
   - `--files <newline-separated paths>` — drives Layer 1 area selection and Layer 2 path-tag filtering.
   - `--issue <n>` (optional) — informational; may be included in output header.
   - `--labels <comma-list>` (optional) — reserved; not used in filtering this spec.

3. **Primary path — `index.jsonl`** — when `.archon/memory/index.jsonl` exists (produced by #649):
   - Load all records from the index as a single JSON-lines scan (no `.md` file reads needed).
   - Apply two-layer filtering (see §Architecture) and score/rank survivors.
   - Emit the ranked block as markdown.

4. **Fallback path — `.md` file scan** — when `index.jsonl` is absent or produces zero survivors
   after filtering:
   - Read the selected `.archon/memory/*.md` files (Layer 1 area selection).
   - Apply the same two-layer filter logic line-by-line (same logic as today's `load_memory()`
     plus the new `source:`/`agent_id` filter).
   - Emit in file-declaration order (no ranking — index absent means no scoring metadata).

5. **Layer 1 — area file selection** (applies to both paths):
   - Always include: `codebase-patterns.md`, `architecture.md`
   - Any `--files` path starting with `backend/`: add `backend-patterns.md`
   - Any `--files` path starting with `frontend/`: add `frontend-patterns.md`
   - Any `--files` path starting with `dark-factory/`, `docker-compose`, or `Dockerfile`:
     add `dark-factory-ops.md`
   - No `--files` given: include all five files (backward-compatible with empty `AFFECTED`).

6. **Layer 2 — entry-level filtering** (applies inside both paths):
   - **Status filter:** exclude entries with `[PROVISIONAL]` or `[INVALID]` anywhere in the line
     (markdown path) or `status` ∈ {provisional, invalid} (index path).
   - **Source/agent_id filter:** map `--phase` to the `source:` vocabulary and keep only matching
     entries. Entries from globally-shared files (`codebase-patterns.md`, `architecture.md`) are
     kept unconditionally (all phases).

     | `--phase`  | Keep entries where `source:` equals |
     |------------|--------------------------------------|
     | `refine`   | `refine`                             |
     | `plan`     | `refine`                             |
     | `implement`| `implement`                          |
     | `validate` | `conformance`                        |
     | `review`   | `code-review`                        |

     **Exception:** entries in `codebase-patterns.md` and `architecture.md` are always included
     regardless of `source:`, because they are global shared memory. Area-specific files
     (`backend-patterns.md`, `frontend-patterns.md`, `dark-factory-ops.md`) apply the source
     filter fully.

   - **Path-tag filter:** entries containing a `path:` tag are included only when the tag
     value is a prefix of at least one file in `--files`. Entries without a `path:` tag are
     always included. When `--files` is empty, all entries pass.

7. **Ranking (index path only)** — sort survivors within each area section by:
   1. Path specificity: a `path_scope` that is a longer prefix match scores higher than a
      shallow or absent path tag.
   2. Status confidence: `active` ranks above `provisional` (though `provisional` is excluded by
      the status filter — this matters if the filter is relaxed in future).
   3. Recency: break ties by `created_at`/`updated_at` descending (newest first).
   Never drop entries below a score threshold — all survivors after filtering are emitted.

8. **Expiry** — exclude entries whose `expires:` date (markdown) or `expires_at` field (index)
   is strictly in the past relative to today's date.

9. **Output format** — identical to current `load_memory()` concatenation:
   ```markdown
   ### Memory: codebase-patterns.md
   - [PATTERN] ...
   - [AVOID] ...

   ### Memory: architecture.md
   - [PATTERN] ...

   ### Memory: dark-factory-ops.md
   - [AVOID] ...
   ```
   The `### Memory: <filename>` heading matches the `$MEMORY_CONTEXT` builder in
   `dark-factory-plan.md` (Phase 3, lines 87–104) — this makes the output a drop-in replacement.

10. **No new services or dependencies** — stdlib Python only. No `agentmemory`, no HTTP client,
    no vector database, no embedding model, no new Docker container.

11. **Tests** — Python pytest at `dark-factory/tests/test_memory_retrieve.py`. Must cover:
    - Index-present path: records filtered by phase, path, status, expiry; ranked by path
      specificity then recency.
    - Index-absent path: `.md` file scan with same two-layer logic (monkeypatch the file layer).
    - Global-file exception: `codebase-patterns.md` / `architecture.md` entries pass regardless
      of source filter.
    - Area selection: correct files opened for backend/frontend/infra/empty `--files`.
    - Expiry exclusion: expired entries excluded from both paths.
    - PROVISIONAL/INVALID exclusion.
    - Empty-files fallback (all five files loaded).

## Architecture

### Component map

```
.archon/commands/dark-factory-plan.md
.archon/commands/dark-factory-implement.md
  (currently inline bash load_memory() — will be replaced by #652)
        │
        ▼
dark-factory/scripts/memory_retrieve.py   <── this spec
        │
        ├── index.jsonl present?
        │   ├── YES → load index, two-layer filter, rank, emit
        │   └── NO  → scan .archon/memory/*.md, two-layer filter, emit
        │
        └── output: "### Memory: <file>\n- [TAG] ...\n..."
```

### CLI contract

```bash
python3 dark-factory/scripts/memory_retrieve.py \
  --phase implement \
  --files "dark-factory/scripts/memory_retrieve.py
dark-factory/tests/test_memory_retrieve.py" \
  [--issue 646] \
  [--labels "Dark Factory,foundation"]
```

stdout (example):
```markdown
### Memory: codebase-patterns.md
- [PATTERN] ...
- [AVOID] ...

### Memory: architecture.md
- [PATTERN] ...

### Memory: dark-factory-ops.md
- [AVOID] ...
```

### Phase → source mapping

```python
PHASE_SOURCE_MAP = {
    "refine":    "refine",
    "plan":      "refine",
    "implement": "implement",
    "validate":  "conformance",
    "review":    "code-review",
}
GLOBAL_FILES = {"codebase-patterns.md", "architecture.md"}
```

### Index path (index.jsonl present)

```python
# index.jsonl line example:
# {"id":"abc123","type":"pattern","status":"active","scope":"backend-patterns.md",
#  "agent_id":"implement","path_scope":"backend/app/","content":"...",
#  "expires_at":"2026-12-01","created_at":"2026-06-04"}

with open(index_path) as f:
    records = [json.loads(line) for line in f if line.strip()]

# Layer 1: keep only records from selected area files
records = [r for r in records if r["scope"] in selected_files]

# Layer 2: two-layer filter
def passes(r, phase, affected_files, today):
    if r.get("status") in ("provisional", "invalid"):
        return False
    if r.get("expires_at") and r["expires_at"] < today:
        return False
    # source filter (global files exempt)
    if r["scope"] not in GLOBAL_FILES:
        if r.get("agent_id") != PHASE_SOURCE_MAP[phase]:
            return False
    # path filter
    path_scope = r.get("path_scope", "")
    if path_scope and affected_files:
        if not any(f.startswith(path_scope) for f in affected_files):
            return False
    return True

survivors = [r for r in records if passes(r, phase, affected_files, today)]

# Rank: path specificity > recency
survivors.sort(key=lambda r: (
    -len(r.get("path_scope", "")),   # deeper prefix = higher rank
    -(r.get("created_at", "") or ""),  # newer = higher rank (str compare, ISO dates)
))
```

### Fallback path (.md file scan)

Replicates the bash `load_memory()` logic in Python, with the additional `source:` filter:

```python
import re

def passes_line(line, phase, affected_files, global_file):
    if "[PROVISIONAL]" in line or "[INVALID]" in line:
        return False
    # expiry
    m = re.search(r"expires:(\d{4}-\d{2}-\d{2})", line)
    if m and m.group(1) < today:
        return False
    # source filter (global files exempt)
    if not global_file:
        m = re.search(r"source:([^ >]*)", line)
        src = m.group(1) if m else ""
        if src and src != PHASE_SOURCE_MAP[phase]:
            return False
    # path filter
    m = re.search(r"path:([^ >]*)", line)
    if m:
        path_tag = m.group(1)
        if affected_files and not any(f.startswith(path_tag) for f in affected_files):
            return False
    return True
```

### Scope note: command-file integration

Updating `.archon/commands/*.md` to call the CLI instead of inline `load_memory()` is **not
in scope** for this ticket. This spec ships `memory_retrieve.py` and its tests only. The
command-file integration is tracked as a separate follow-on (issue #652).

## Alternatives Considered

### A. agentmemory library (original spec)

The previous spec used `try: import agentmemory` as the primary path. This was the design
before the #644 spike revealed that no `agentmemory` backend exists or is planned. Dropped
entirely per user feedback.

### B. Scoring threshold (drop entries below a score)

Hard-dropping entries below a relevance threshold risks silently hiding a directly-applicable
lesson. At the corpus size (~130 entries across five files), filtering is sufficient to reduce
noise; ranking orders the survivors. No threshold.

### C. Separate retriever per phase (five separate scripts)

A dedicated retriever per phase would make the source-filter trivial but create five copies of
the same file-read and path-filter logic. A single parameterised script with `--phase` is the
established pattern in `dark-factory/scripts/` (see `gate_blast_radius.py`, `dedupe_oos.py`).

## Open Questions (non-blocking)

1. **#645 contract finalization** — the role × file scoping matrix in this spec is derived from
   the de-facto contract in `.archon/commands/*.md`. When #645 ships its formal spec, align
   the `PHASE_SOURCE_MAP` and `GLOBAL_FILES` constants with whatever it documents.

2. **`--labels` filtering** — labels are accepted as an input but not used in filtering this
   spec. If #645 defines label-based scoping, add it in a follow-on.

3. **index.jsonl full-record path** — the spec uses `index.jsonl` only (no `.archon/memory/records/`).
   If the index is ever truncated (e.g., missing `content`), fall back to opening the
   corresponding `.json` record file. Treat as implementation-time decision.

## Assumptions

- `[ASSUMPTION]` `index.jsonl` does not yet exist in the repo. It will be produced by
  `dark-factory/scripts/memory_import.py` from #649. Until #649 ships, `memory_retrieve.py`
  always takes the fallback path — which is behaviorally equivalent to today's `load_memory()`,
  plus the new source-filter.

- `[ASSUMPTION]` Python stdlib only. The dark-factory image already has Python 3 (confirmed by
  all existing `dark-factory/scripts/*.py`).

- `[ASSUMPTION]` `.archon/memory/*.md` files remain the canonical markdown surface throughout
  Phase 2. No new memory file format is introduced by this ticket.

- `[ASSUMPTION]` The `source:` tag vocabulary (`refine`, `implement`, `conformance`, `code-review`)
  is stable. Entries without a `source:` tag are treated as unscoped and pass the source filter
  unconditionally (backward-compatible with pre-scoping entries).
