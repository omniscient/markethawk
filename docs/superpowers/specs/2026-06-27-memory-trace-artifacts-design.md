# Memory Trace Artifacts for Dark Factory Runs

**Date:** 2026-06-27
**Issue:** #647
**Parent Epic:** #643 (Improve Dark Factory memory system)
**Status:** Spec — pending review

---

## Overview

Every Dark Factory run that loads memory files should emit a `memory-trace.json` artifact to `$ARTIFACTS_DIR`. This makes memory retrieval auditable: a reviewer can open the artifact and see exactly which memory files were loaded, how many entries survived the path-tag filter, and what changed-file set drove the filtering decision.

---

## Requirements

1. **Every phase that calls `load_memory()` emits the trace.** Currently that is refine, plan, and implement (conformance and code-review do not load memory and are out of scope for v1). If a future phase adds `load_memory()`, it should follow the same pattern.
2. **The trace uses the same filter logic and `$AFFECTED` set as the primary `load_memory()` invocations.** The bash block re-invokes `load_memory()` once per file to get counts, but applies identical inputs (`$AFFECTED`, same file), so the result reflects exactly what entered context. `load_memory()` is idempotent (read-only, no side effects).
3. **Schema is file-level, mechanism-honest.** No `id`, `score`, or `source: "agentmemory"` — those belong to a future semantic retrieval system (deferred to epic #643). The v1 schema uses `schema_version: 1` and `retrieval_mechanism: "flatfile-pathtag"` so consumers can branch on version when the semantic upgrade arrives.
4. **Best-effort, non-blocking.** A run must never fail or stall because the trace could not be written. If `load_memory()` produced no output or counting fails, emit a fallback form with `fallback_used: true` and empty `files_loaded`.
5. **`run_record.py` picks it up.** At end-of-run assembly, `memory-trace.json` (if present) is read into `run-record.json` under a top-level `"memory_trace"` key. Absent file is tolerated silently.

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
    "dark-factory/scripts/factory_core/run_record.py"
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
| `issue` | int | GitHub issue number from workflow context |
| `phase` | string | `"refine"`, `"plan"`, or `"implement"` |
| `agent_id` | string | `"refine-agent"`, `"plan-agent"`, or `"implementation-agent"` per phase |
| `project` | string | Always `"markethawk"` |
| `affected_files` | string[] | The `$AFFECTED` list (`git diff --name-only origin/main...HEAD`). Empty array if nothing changed (new branch). |
| `files_loaded` | object[] | One entry per memory file passed to `load_memory()` |
| `files_loaded[].path` | string | Relative path, e.g. `.archon/memory/backend-patterns.md` |
| `files_loaded[].entries_total` | int | Lines matching `^\- \[` in the file |
| `files_loaded[].entries_included` | int | Lines matching `^\- \[` in `load_memory()` output |
| `files_loaded[].entries_filtered_out` | int | `entries_total - entries_included` |
| `fallback_used` | bool | `true` when the trace could not be fully derived (load_memory returned nothing or counting failed) |

**Note:** `queries` (from the issue's proposed shape) is intentionally absent — there is no query in a path-tag filter; `affected_files` is its equivalent. `id`, `score`, and `source: "agentmemory"` are deferred to epic #643's semantic retrieval upgrade.

---

## Architecture / Approach

### Command file additions (refine, plan, implement)

**Files to update:**
- `.archon/commands/dark-factory-refine.md`
- `.archon/commands/dark-factory-plan.md`
- `.archon/commands/dark-factory-implement.md`

After the Phase 1 LOAD section (after all `load_memory()` calls), insert the following instruction block. The text between the horizontal rules is what goes into the command file.

---

**Memory Trace (Phase 1 LOAD — after all `load_memory()` calls)**

After all `load_memory()` calls above, emit `$ARTIFACTS_DIR/memory-trace.json` using the bash block below. This is best-effort — any failure silently continues.

Set `PHASE_NAME` and `AGENT_ID` to the per-phase values:
- refine: `PHASE_NAME=refine`, `AGENT_ID=refine-agent`
- plan: `PHASE_NAME=plan`, `AGENT_ID=plan-agent`
- implement: `PHASE_NAME=implement`, `AGENT_ID=implementation-agent`

```bash
{
  TRACE_FILES_LOADED='[]'

  _count_entries() { grep -c '^\- \[' "$1" 2>/dev/null || echo 0; }

  for MEMFILE in \
    ".archon/memory/codebase-patterns.md" \
    ".archon/memory/architecture.md" \
    ".archon/memory/backend-patterns.md" \
    ".archon/memory/frontend-patterns.md" \
    ".archon/memory/dark-factory-ops.md"
  do
    [ -f "$MEMFILE" ] || continue
    MEM_TOTAL=$(_count_entries "$MEMFILE")
    MEM_INCLUDED=$(load_memory "$(basename "$MEMFILE")" | grep -c '^\- \[' 2>/dev/null || echo 0)
    TRACE_FILES_LOADED=$(printf '%s' "$TRACE_FILES_LOADED" | python3 -c "
import json, sys
arr = json.load(sys.stdin)
arr.append({'path': '$MEMFILE', 'entries_total': $MEM_TOTAL, 'entries_included': $MEM_INCLUDED, 'entries_filtered_out': $((MEM_TOTAL - MEM_INCLUDED))})
print(json.dumps(arr))" 2>/dev/null || printf '%s' "$TRACE_FILES_LOADED")
  done

  AFFECTED_JSON=$(printf '%s' "${AFFECTED:-}" | python3 -c "
import json, sys; lines=[l for l in sys.stdin.read().splitlines() if l.strip()]; print(json.dumps(lines))" 2>/dev/null || echo '[]')

  python3 -c "
import json, os
trace = {
  'schema_version': 1, 'retrieval_mechanism': 'flatfile-pathtag',
  'issue': int('${ISSUE_NUM:-0}' or 0), 'phase': '${PHASE_NAME}',
  'agent_id': '${AGENT_ID}', 'project': 'markethawk',
  'affected_files': ${AFFECTED_JSON}, 'files_loaded': ${TRACE_FILES_LOADED},
  'fallback_used': False
}
out = os.environ.get('ARTIFACTS_DIR','') + '/memory-trace.json'
out.startswith('/') and open(out,'w').write(json.dumps(trace, indent=2))
" 2>/dev/null || true
} 2>/dev/null || true
```

---

**Design notes:**
- `load_memory()` is re-invoked once per file to get counts; it is idempotent (read-only, no side effects) and uses the same `$AFFECTED` set, so results match what entered context.
- `python3` is available in the factory container (used throughout `entrypoint.sh` and `scripts/`).
- The entire block is wrapped in `2>/dev/null || true` — any failure is silently swallowed and the run continues.
- If `$ARTIFACTS_DIR` is unset, the `out.startswith('/')` guard prevents writes and the trace is absent; `run_record.py` tolerates that.

### `run_record.py` changes

In `cmd_assemble()`, after the existing artifact loop:

```python
# Existing loop handles: validation, conformance, review, conflict_resolution
# New: pick up memory-trace.json if present
memory_trace_path = artifacts_dir / "memory-trace.json"
if memory_trace_path.exists():
    try:
        run_record["memory_trace"] = json.loads(memory_trace_path.read_text(encoding="utf-8"))
    except Exception:
        pass  # non-fatal: trace absent or malformed
```

The `memory_trace` key is added at the top level of `run-record.json`. It does not contribute to `stages[]` (no verdict) and does not affect cost totals.

---

## Alternatives Considered

### Alt 1: External Python wrapper script

A new `dark-factory/scripts/emit_memory_trace.py` re-implements the path-tag filter logic from `load_memory()` and writes the trace independently. Rejected: creates two sources of truth for "which entries get included." If `load_memory()` and the script's filter logic diverge, the trace would misrepresent what actually entered the agent's context — the opposite of auditability.

### Alt 2: Entry-level schema with pseudo-IDs

Enumerate each entry with a derived `id` (e.g., `"backend-patterns.md#L42"`), `score: 1.0` or `0.0`, and `source: "archon-memory"`. Rejected: line-anchored IDs are brittle (churn on any memory file edit), and a binary score dressed as a floating-point retrieval score would mislead reviewers into thinking semantic retrieval ran. Schema honesty wins on the stated goal of auditability.

### Alt 3: Instrument `load_memory()` with side-channel temp files

Modify `load_memory()` to write running counts to temp files as a side effect, then assemble the trace at the end. Rejected: more moving parts than option A for identical output, and the side-channel adds fragility (temp file left behind if the run aborts mid-load).

---

## Open Questions

1. **Fallback behavior when `$ARTIFACTS_DIR` is unset.** Currently the block silently does nothing (the `out.startswith('/')` guard prevents writes to relative paths). Should we also detect this case and set `TRACE_FALLBACK=true`? Low priority for v1 — the `$ARTIFACTS_DIR` is always set by `entrypoint.sh` before archon launches, so the unset case only occurs in manual/test invocations.

---

## Assumptions

- `python3` is available in the factory container at the point `load_memory()` is called (confirmed: used extensively in entrypoint.sh and scripts/).
- `$ARTIFACTS_DIR` is set and writable by the time Phase 1 LOAD completes (confirmed: set and `mkdir -p`'d in entrypoint.sh before archon launches).
- The "every run" acceptance criterion applies to "every run that retrieves memory" — phases that don't call `load_memory()` (conformance, code-review, validate) are out of scope for v1.
- `ISSUE_NUM` is available in the agent's environment when the trace is written (confirmed: always set by the workflow or extractable from the branch name).
