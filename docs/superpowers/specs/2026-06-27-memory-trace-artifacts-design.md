# Memory Trace Artifacts for Dark Factory Runs

**Date:** 2026-06-27 (revised 2026-06-30)
**Issue:** #647
**Parent Epic:** #643 (Improve Dark Factory memory system)
**Status:** Spec — pending review

---

## Overview

Every Dark Factory run that loads memory should emit a `memory-trace.json` artifact to `$ARTIFACTS_DIR`. This makes memory retrieval auditable: a reviewer can open the artifact and see exactly which memory files were considered, how many entries survived the path-tag filter, and what changed-file set drove the filtering decision.

**Revision note (2026-06-30):** PRs #678 and #681 merged `memory_retrieve.py` and wired it into all four gates (refine, plan, implement, validate), replacing the inline `load_memory()` bash function. This spec is updated to emit the trace from `memory_retrieve.py` itself rather than from an agent-written bash block.

---

## Requirements

1. **Every phase that calls `memory_retrieve.py` emits the trace.** Currently that is refine, plan, implement, and validate. If a future phase adds a `memory_retrieve.py` call, it should follow the same pattern.
2. **The trace is emitted from `memory_retrieve.py` itself.** A new `--emit-trace-to <path>` CLI argument causes the script to write `memory-trace.json` as a side-effect of the retrieval call that already populates the memory context. This guarantees the trace matches exactly what entered context (single source of truth — no second pass).
3. **Schema is file-level, mechanism-honest.** No `id`, `score`, or `source: "agentmemory"` — those belong to a future semantic retrieval system (deferred to epic #643). The v1 schema uses `schema_version: 1` and `retrieval_mechanism: "flatfile-pathtag"` so consumers can branch on version when the semantic upgrade arrives. Entry counts are always derived from the `.archon/memory/*.md` files regardless of whether the index path or markdown fallback ran — the index is still flat-file content with identical path-tag filtering, just pre-indexed.
4. **Best-effort, non-blocking.** A run must never fail or stall because the trace could not be written. Any failure inside the `--emit-trace-to` code path is silently swallowed; the markdown output on stdout is unaffected. The existing gate invocation already wraps the call in `2>/dev/null || true`.
5. **`fallback_used: true`** means the trace could not be fully derived (file read or count failed). It does not indicate which retrieval path inside `memory_retrieve.py` ran (index vs. markdown) — that distinction belongs to a `schema_version: 2` upgrade.
6. **`run_record.py` picks it up.** At end-of-run assembly, `memory-trace.json` (if present) is read into `run-record.json` under a top-level `"memory_trace"` key. Absent or malformed file is tolerated silently.

---

## Schema

`$ARTIFACTS_DIR/memory-trace.json`:

```json
{
  "schema_version": 1,
  "retrieval_mechanism": "flatfile-pathtag",
  "issue": 647,
  "phase": "implement",
  "agent_id": "implementation-agent",
  "project": "markethawk",
  "affected_files": [
    "dark-factory/scripts/memory_retrieve.py"
  ],
  "files_loaded": [
    {
      "path": ".archon/memory/codebase-patterns.md",
      "entries_total": 12,
      "entries_included": 12,
      "entries_filtered_out": 0
    },
    {
      "path": ".archon/memory/dark-factory-ops.md",
      "entries_total": 20,
      "entries_included": 15,
      "entries_filtered_out": 5
    }
  ],
  "fallback_used": false
}
```

**Field definitions:**

| Field | Type | Description |
|---|---|---|
| `schema_version` | int | Always `1` for this implementation. Bump when the schema changes. |
| `retrieval_mechanism` | string | Always `"flatfile-pathtag"`. A future semantic retrieval system sets this to `"semantic"`. |
| `issue` | int | GitHub issue number passed via `--issue` |
| `phase` | string | `"refine"`, `"plan"`, `"implement"`, or `"validate"` |
| `agent_id` | string | `"refine-agent"`, `"plan-agent"`, `"implementation-agent"`, or `"validate-agent"` |
| `project` | string | Always `"markethawk"` |
| `affected_files` | string[] | The `$AFFECTED` list (`git diff --name-only origin/main...HEAD`). Empty array if nothing changed (new branch). |
| `files_loaded` | object[] | One entry per area memory file considered (derived from `area_files` in `select_area_files()`) |
| `files_loaded[].path` | string | Relative path, e.g. `.archon/memory/backend-patterns.md` |
| `files_loaded[].entries_total` | int | Lines matching `^\- \[` in the `.md` file |
| `files_loaded[].entries_included` | int | Lines that passed all filters (expiry, source, path-tag) |
| `files_loaded[].entries_filtered_out` | int | `entries_total - entries_included` |
| `fallback_used` | bool | `true` when the trace could not be fully derived (file read or counting failed) |

**Note:** `queries` and `selected_memories[].id/score` from the issue's proposed shape are intentionally absent from v1 — they belong to the epic #643 semantic retrieval upgrade. `affected_files` is the path-scoping equivalent of `queries`.

---

## Architecture / Approach

### `memory_retrieve.py` changes

Add a `--emit-trace-to <path>` argument. After `retrieve_memory()` runs and before writing to stdout, compute the trace and write it to the given path. The trace write is entirely wrapped in a try/except so it can never affect the main retrieval output or exit code.

**New CLI argument:**
```python
parser.add_argument(
    "--emit-trace-to",
    default=None,
    help="If set, write memory-trace.json to this path as a side-effect (best-effort).",
)
```

**Per-phase agent IDs** (constant map inside `memory_retrieve.py`):
```python
PHASE_AGENT_ID = {
    "refine":    "refine-agent",
    "plan":      "plan-agent",
    "implement": "implementation-agent",
    "validate":  "validate-agent",
    "review":    "review-agent",
}
```

**Trace-writing block** (called at the end of `main()`, after output is printed, when `args.emit_trace_to` is set):

```python
if args.emit_trace_to:
    try:
        import json as _json
        from pathlib import Path as _Path

        today = date.today().isoformat()
        area_files = select_area_files(files)
        allowed_sources = PHASE_SOURCE_MAP.get(args.phase, set())
        files_loaded = []
        fallback = False
        memory_dir_path = Path(args.memory_dir)

        for fname in area_files:
            fpath = memory_dir_path / fname
            if not fpath.exists():
                continue
            try:
                raw_lines = fpath.read_text(encoding="utf-8").splitlines()
            except OSError:
                fallback = True
                continue
            total = sum(1 for l in raw_lines if l.startswith("- ["))
            # Count included entries using the same filter logic as scan_markdown_files
            included = 0
            for line in raw_lines:
                m = _ENTRY_RE.match(line)
                if not m:
                    continue
                meta = parse_meta(m.group("meta"))
                if passes_line_filters(m.group("tag"), meta, fname, files, allowed_sources):
                    included += 1
            files_loaded.append({
                "path": str(fpath.relative_to(_Path(".").resolve()) if fpath.is_absolute() else fpath),
                "entries_total": total,
                "entries_included": included,
                "entries_filtered_out": total - included,
            })

        affected_list = [f for f in args.files.splitlines() if f.strip()] if args.files else []
        trace = {
            "schema_version": 1,
            "retrieval_mechanism": "flatfile-pathtag",
            "issue": args.issue or 0,
            "phase": args.phase,
            "agent_id": PHASE_AGENT_ID.get(args.phase, args.phase + "-agent"),
            "project": "markethawk",
            "affected_files": affected_list,
            "files_loaded": files_loaded,
            "fallback_used": fallback,
        }
        out = _Path(args.emit_trace_to)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(_json.dumps(trace, indent=2), encoding="utf-8")
    except Exception:
        pass  # best-effort: never affect the main retrieval
```

### Command file additions (refine, plan, implement, validate)

**Files to update:**
- `.archon/commands/dark-factory-refine.md`
- `.archon/commands/dark-factory-plan.md`
- `.archon/commands/dark-factory-implement.md`
- `.archon/commands/dark-factory-validate.md`

In each file, the existing `memory_retrieve.py` invocation already looks like:

```bash
MEMORY_CONTEXT=$(python3 "${REPO_ROOT}/dark-factory/scripts/memory_retrieve.py" \
  --phase <PHASE> \
  --files "$AFFECTED" \
  $ISSUE_ARG \
  --memory-dir "${REPO_ROOT}/.archon/memory" 2>/dev/null || true)
```

Add one argument to each invocation (identical change across all four gates):

```bash
MEMORY_CONTEXT=$(python3 "${REPO_ROOT}/dark-factory/scripts/memory_retrieve.py" \
  --phase <PHASE> \
  --files "$AFFECTED" \
  $ISSUE_ARG \
  --memory-dir "${REPO_ROOT}/.archon/memory" \
  --emit-trace-to "$ARTIFACTS_DIR/memory-trace.json" 2>/dev/null || true)
```

The `2>/dev/null || true` wrapper already present on each call ensures any failure (including a trace write failure) is non-fatal. No other change to the command files is required.

### `run_record.py` changes

In `cmd_assemble()`, after the existing artifact loop, pick up `memory-trace.json`:

```python
# Existing loop handles: validation, conformance, review, conflict_resolution
# New: pick up memory-trace.json if present
memory_trace_path = artifacts_dir / "memory-trace.json"
if memory_trace_path.exists():
    try:
        run_record["memory_trace"] = json.loads(
            memory_trace_path.read_text(encoding="utf-8")
        )
    except Exception:
        pass  # non-fatal: trace absent or malformed
```

The `memory_trace` key is added at the top level of `run-record.json`. It does not contribute to `stages[]` (no verdict) and does not affect cost totals.

---

## Alternatives Considered

### Alt 1: Agent-written bash block in each command file (previous spec)

The previous spec had each gate agent write the trace via a large bash block that re-invoked `load_memory()` for counts. Superseded: PRs #678 and #681 replaced `load_memory()` with `memory_retrieve.py`, so the bash block would need to re-read `.md` files separately anyway — the same re-read that `--emit-trace-to` does, but without the benefit of being co-located with the retrieval logic. The bash block approach also duplicated identical ~30-line blocks across four command files.

### Alt 2: Gate writes trace via a second `memory_retrieve.py` call

Each gate keeps the existing retrieval call unchanged and adds a second invocation that outputs JSON instead of markdown. Rejected: two invocations create a possible count mismatch (between what entered context and what the trace records) — the opposite of auditability. Also doubles I/O per gate.

### Alt 3: Entry-level schema with pseudo-IDs

Enumerate each entry with `id` (e.g. `"backend-patterns.md#L42"`), `score: 1.0` or `0.0`. Rejected in the prior run and again here: line-anchored IDs are brittle (churn on any memory edit), and a binary score dressed as a floating-point score misleads reviewers into thinking semantic retrieval ran. Schema honesty wins.

---

## Open Questions

1. **Trace path collision when two gates run sequentially.** The four gates run as separate containers with the same `$ARTIFACTS_DIR`. Currently refine and plan run before implement, so the implement gate overwrites the refine/plan trace. For v1 this is acceptable (auditors care most about the implement trace). A future improvement could name the file `memory-trace-<phase>.json` — track in epic #643.

---

## Assumptions

- `memory_retrieve.py` is available at `dark-factory/scripts/memory_retrieve.py` (introduced by PR #678, merged 2026-06-30). This spec modifies that script.
- `$ARTIFACTS_DIR` is set and writable by the time each gate runs its `memory_retrieve.py` call (confirmed: set and `mkdir -p`'d in `entrypoint.sh` before archon launches). The `--emit-trace-to` path uses `$ARTIFACTS_DIR/memory-trace.json`.
- All four phases (refine, plan, implement, validate) call `memory_retrieve.py` as their memory-load step (confirmed by PR #681).
- `ISSUE_NUM` is passed via `$ISSUE_ARG` in all four gate invocations (confirmed: existing pattern in all four command files).
- The validate phase uses `--phase validate` with `allowed_sources = {"conformance"}` — the trace correctly reflects the narrower source filter for that phase.
