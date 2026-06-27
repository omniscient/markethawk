# Read-Through Memory Retrieval Adapter

**Status:** design  
**Date:** 2026-06-27  
**Issue:** #646  
**Epic:** #643 — Improve Dark Factory memory system using agent-native memory architecture  
**Component:** `dark-factory/scripts/memory_retrieve.py`

## Problem

Dark Factory agents load memory by running a bash `load_memory()` function defined inline in each
`.archon/commands/*.md` prompt file. This function reads `.archon/memory/*.md`, applies path-tag
filtering, and emits plain-text lines that the agent injects into its prompt context.

The limitation: each command file carries a copy of the same bash logic; the function has no
awareness of structured metadata (confidence, evidence count, role-specific relevance); and there
is no hook for a future structured memory store to replace the flat-file reads.

Issue #646 is Phase 2 of the parent epic (#643): add a single Python CLI that the command files
call instead of `load_memory()`. The CLI tries a structured `agentmemory` store first and falls
back to reading `.archon/memory/*.md` when the library is unavailable or returns no results —
preserving today's exact behavior as the resilience floor.

## Requirements

Derived from the issue acceptance criteria and Q&A:

1. **CLI invocation** — `dark-factory/scripts/memory_retrieve.py` is a runnable Python script.
   Its stdout is a markdown block that can be substituted for the current `load_memory()` output
   in `.archon/commands/*.md` prompts without other changes to those files.

2. **Inputs** — `--phase <phase>` (one of `refine|plan|implement|validate|review`), `--files
   <newline-separated paths>` (affected or anticipated files), optional `--issue <n>`, optional
   `--labels <comma-list>`.

3. **Primary path (agentmemory)** — attempt `import agentmemory`; query with
   `project="markethawk"` and `agentId=<phase>`; filter by path prefixes derived from `--files`;
   exclude `PROVISIONAL` and `INVALID` entries. On `ImportError` or any query exception, proceed
   to the fallback path.

4. **Fallback path (markdown)** — read the same `.archon/memory/*.md` files the bash function
   reads, apply the same path-tag prefix filtering, exclude `[PROVISIONAL]` and `[INVALID]`
   entries. This is the live path today (agentmemory is not installed).

5. **Empty-store fallback** — if agentmemory is importable but returns zero records for the
   query, treat it as unavailable and fall back to markdown. Until Phase 1 of the epic populates
   the store, the adapter always uses markdown.

6. **Area selection** — both paths must select the same memory files:
   - Always: `codebase-patterns.md`, `architecture.md`
   - If any `--files` path starts with `backend/`: add `backend-patterns.md`
   - If any `--files` path starts with `frontend/`: add `frontend-patterns.md`
   - If any `--files` path starts with `dark-factory/` or matches `docker-compose` or
     `Dockerfile`: add `dark-factory-ops.md`
   - If no `--files` given (empty): load all five files (same "include all" behavior as
     the bash function with empty `AFFECTED`).

7. **Path-tag filtering in fallback** — replicates the bash `load_memory()` logic exactly:
   entries without a `path:` tag are always included; path-tagged entries are included only
   if their `path:` prefix is a prefix of at least one file in `--files`; with no `--files`,
   all entries are included.

8. **No new services or dependencies** — no new Docker container, no HTTP endpoint, no vector
   database or embedding model. The `agentmemory` library is used with metadata-only filtering
   (no embeddings). If the library's backing store requires Chroma in embedding mode, the
   agentmemory path must either configure it with `embedding_function=None` or be treated as
   unavailable (falling back to markdown).

9. **Tests** — Python pytest at `dark-factory/tests/test_memory_retrieve.py`. Must cover:
   agentmemory-available path (mocked), ImportError fallback, query-exception fallback,
   empty-result fallback, path-tag filtering (match / no-match / empty-affected), area
   selection, and PROVISIONAL/INVALID exclusion.

10. **`project=markethawk`** — this constant namespace is passed to every agentmemory call so
    the store is project-scoped and reusable if other repos adopt the library.

## Architecture

### Component map

```
.archon/commands/dark-factory-plan.md
.archon/commands/dark-factory-implement.md
  (currently inline bash load_memory() — replaced by:)
        │
        ▼
dark-factory/scripts/memory_retrieve.py   <── this spec
        │
        ├── try: import agentmemory
        │   ├── available + records found → emit agentmemory results
        │   └── unavailable / empty / error → fallback
        │
        └── fallback: read .archon/memory/*.md
            ├── area selection (based on --files + --phase)
            ├── path-tag prefix filtering
            └── PROVISIONAL/INVALID exclusion
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

stdout:

```markdown
### Memory: codebase-patterns.md
- [PATTERN] ...
- [AVOID] ...

### Memory: architecture.md
- [PATTERN] ...

### Memory: dark-factory-ops.md
- [AVOID] ...
```

The heading format `### Memory: <filename>` matches the section headers already used by the
`$MEMORY_CONTEXT` builder in `dark-factory-plan.md` (Phase 3, lines 87–104), so the output
is a drop-in replacement.

### agentmemory query (primary path)

```python
try:
    import agentmemory
    records = agentmemory.get_memories(
        project="markethawk",
        agentId=phase,     # "refine" | "plan" | "implement" | "validate" | "review"
        n=100,
    )
    if not records:
        raise ValueError("empty store")
    # filter by path prefix and kind
    ...
except Exception:
    records = None  # trigger fallback
```

`agentmemory` must be configured without embeddings (metadata-only store). If the library
requires a Chroma embedding function and cannot be made metadata-only, the primary path is
treated as permanently unavailable until a compatible version is confirmed.

### Markdown fallback path

Replicates the bash `load_memory()` logic line-for-line in Python:

```python
for line in memory_file.read_text().splitlines():
    if "path:" in line:
        path_tag = re.search(r"path:([^ >]*)", line).group(1)
        if not affected_files or any(f.startswith(path_tag) for f in affected_files):
            yield line
    else:
        yield line
```

Entries whose line contains `[PROVISIONAL]` or `[INVALID]` are excluded from the authoritative
output (same rule as the `_filter_memory` helper in `dark-factory-plan.md:82`).

### Integration change in `.archon/commands/`

Replace the inline bash `load_memory()` block (Steps 6-10 / Steps 7-10) in each command file
with a single call:

```bash
MEMORY_BLOCK=$(python3 "$CLONE_DIR/dark-factory/scripts/memory_retrieve.py" \
  --phase "$INTENT" \
  --files "$AFFECTED")
```

Then inject `$MEMORY_BLOCK` into the prompt context where the concatenated `load_memory` outputs
went. This is a one-line replacement per command file.

**Scope note:** Updating `.archon/commands/*.md` files is NOT in scope for this ticket. This
spec defines only `memory_retrieve.py` and its tests. The command-file integration is a
follow-on task within the parent epic (issue #643).

## Alternatives Considered

### A. Protocol/backend classes (`MemoryBackend` protocol)

Define a `MemoryBackend` protocol with two implementations: `AgentMemoryBackend` and
`MarkdownBackend`. The retriever dispatches based on availability.

Rejected: over-engineered for an M-size ticket. The try/except import guard achieves the
same dispatch with less code and no extra abstractions that the conformance agent would need
to validate.

### B. HTTP microservice for memory queries

"agentmemory available" means an external HTTP service is reachable. `project=markethawk` and
`agentId` are HTTP headers.

Rejected: contradicts the `[AVOID]` architecture entry ("no new Docker containers") and the
`[AVOID]` for Redis durable state. There is no existing HTTP memory service in the stack.
"Server outage" language in the issue is loose — it means library/store unavailability, not
a real network failure.

### C. On-the-fly markdown → agentmemory population at retrieval time

`memory_retrieve.py` parses `.archon/memory/*.md` into records, loads them into agentmemory,
then queries. No separate population step.

Rejected: blurs the Phase 1 / Phase 2 boundary from the parent epic. The spec for Phase 1
produces an `index.jsonl` that populates the store as a separate pre-step. Loading on every
retrieval call defeats the purpose of having a queryable store and adds unnecessary write
overhead to each factory run.

## Open Questions (non-blocking)

1. **agentmemory embedding mode** — whether the library can be configured with
   `embedding_function=None` (pure metadata store, no Chroma/vector overhead) is an
   implementation-time question. If it cannot, the primary path is deferred until Phase 1 of
   the epic produces a compatible adapter. The fallback path is unaffected.

2. **`--labels` filtering** — the issue lists labels as an input. In the agentmemory path,
   labels could be passed as an additional metadata filter to narrow results (e.g., a `backend`
   label narrows to backend-scoped records). In the markdown fallback path, labels have no
   filtering role (area selection is driven by `--files` alone). The spec treats labels as
   advisory: pass them to agentmemory if supported; ignore them in the fallback path.

3. **Command-file integration timing** — updating `.archon/commands/*.md` to call the CLI
   instead of inline `load_memory()` is a separate change. This ticket ships the retriever
   script; the integration change is tracked under the parent epic #643.

## Assumptions

- `[ASSUMPTION]` The `agentmemory` Python library is pip-installable into the dark-factory
  image when needed. Today it is absent, so the fallback path is always active. The primary path
  activates automatically once the library is installed.

- `[ASSUMPTION]` The dark-factory image already has Python 3 available (confirmed: all existing
  scripts in `dark-factory/scripts/*.py` run under Python 3).

- `[ASSUMPTION]` The five existing `.archon/memory/*.md` files remain the canonical markdown
  surface throughout Phase 2. No new file format or location is introduced by this ticket.

- `[ASSUMPTION]` The agentmemory store is populated by a Phase 1 pre-step (out of scope here).
  Until that step runs, the retriever correctly treats an empty store as unavailable and returns
  the markdown-based block instead.
