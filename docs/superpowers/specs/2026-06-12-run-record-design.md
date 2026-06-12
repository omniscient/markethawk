# Run Record Module — Design (issue #333)

**Date**: 2026-06-12
**Issue**: [#333](https://github.com/omniscient/markethawk/issues/333) — Run Record: one structured per-run record of every stage verdict
**Branch**: `refine/issue-333-run-record--one-structured-per-run-recor`

## Problem

Factory run state is scattered across five lossy sinks:

| Sink | Problem |
|------|---------|
| Cost comment on issue (jq-formatted) | Parse-hostile; no structured properties |
| `/tmp/artifacts/*.md` (validation, conformance, review, conflict_resolution) | Die with the `--rm` container |
| `scheduler-state.json` | Retry counts only — no verdicts |
| GitHub labels | Current state only; no history |
| Seq GELF lines | Unstructured strings; properties unindexed |

Gate-effectiveness questions ("how often does conformance block?", "what does code-review find?") require manual excavation. This is the seam every other measurement ticket (Scorecard automation, judge calibration, replay benchmarks) plugs into.

## Requirements

Derived from the issue body and the Q&A session during this refinement:

1. **One module**: `dark-factory/scripts/run_record.py` — Python CLI consistent with existing helpers (`check_workflow_dag.py`, `code_review_payload.py`, `fmt_hunk_filter.py`).
2. **Two durable sinks**:
   - `/var/lib/dark-factory/runs.jsonl` — append-only, one JSON line per event, on the existing named Docker volume that also holds `scheduler-state.json`.
   - Seq raw events API (`POST http://seq:5341/api/events/raw`) — structured `gen_ai.*` properties, same contract as `backend/app/core/error_tracking.py`.
3. **Per-run working file**: `$ARTIFACTS_DIR/run-record.json` — assembled during the run, used as the data source for `post_cost_report()` (replaces `archon workflow cost --last --json`).
4. **Token/cost fields use OTel `gen_ai.*` names** (`gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`) — future-proof for Seq dashboards and GenAI semantic-convention consumers.
5. **Verdict artifacts survive the container**: content of `validation.md`, `conformance.md`, `review.md`, `conflict_resolution.md` is folded into the run record before the container exits.
6. **`ARTIFACTS_DIR` hoisted**: single canonical export near the top of `entrypoint.sh` so `run_record.py`, `post_cost_report()`, and DAG nodes all agree on the path.
7. **Non-fatal**: Seq POST is best-effort (`timeout=5`, `|| true`). The `runs.jsonl` append (local capture) happens first, always.
8. **Atomic appends**: `fcntl.flock(fd, fcntl.LOCK_EX)` before appending to `runs.jsonl` (WIP_LIMIT > 1 is configurable).
9. **No new dependencies**: use `stdlib` only (`json`, `urllib.request`, `fcntl`, `pathlib`).

## Architecture

### Module: `dark-factory/scripts/run_record.py`

**CLI commands:**

```
run_record.py record  --run-id RUN_ID --issue N --intent INTENT
                      --stage STAGE --verdict VERDICT
                      [--tokens-in N] [--tokens-out N] [--cost-usd F]
                      [--duration-ms N] [--detail KEY=VAL ...]

run_record.py assemble --run-id RUN_ID --issue N --intent INTENT
                       --artifacts-dir PATH [--archon-cost-json PATH]
                       --out-file PATH
```

- **`record`**: writes one event line to `runs.jsonl` + POSTs to Seq. Can be called incrementally (e.g., from the `on_failure` trap to capture partial runs).
- **`assemble`**: reads all verdict artifact `.md` files from `$ARTIFACTS_DIR`, captures archon cost data (if provided), and writes `run-record.json` to `--out-file`. Also calls `record` internally for each stage found. Called once at the end of a successful run from `entrypoint.sh`.

**Data model — `runs.jsonl` line / Seq event Properties:**

```json
{
  "run_id": "736c05b0c0feba47f4e0379331853061",
  "issue_number": 333,
  "intent": "new",
  "stage": "conformance",
  "verdict": "PASS",
  "gen_ai.system": "dark-factory",
  "gen_ai.operation.name": "stage.conformance",
  "gen_ai.usage.input_tokens": 45000,
  "gen_ai.usage.output_tokens": 8000,
  "cost_usd": 0.061,
  "duration_ms": 180000,
  "timestamp": "2026-06-12T03:51:41Z",
  "detail": {
    "cycles": 2,
    "no_spec": false,
    "oos_excised": 0
  }
}
```

**Data model — `run-record.json` (per-run working file):**

```json
{
  "run_id": "...",
  "issue_number": 333,
  "intent": "new",
  "started_at": "...",
  "completed_at": "...",
  "stages": [
    { "stage": "validate", "verdict": "PASS", ... },
    { "stage": "conformance", "verdict": "PASS", "cycles": 2, ... },
    { "stage": "code_review", "verdict": "PASS", "blockers": 0, "advisory": 3, ... },
    { "stage": "conflict", "verdict": "none", ... }
  ],
  "nodes": [
    { "node_id": "implement", "gen_ai.usage.input_tokens": 120000, ... }
  ],
  "totals": {
    "gen_ai.usage.input_tokens": 245000,
    "gen_ai.usage.output_tokens": 52000,
    "cost_usd": 0.34
  }
}
```

The `nodes[]` array mirrors what `archon workflow cost --last --json` currently provides, so `post_cost_report()`'s existing `jq`-based table-row formatting can read from `run-record.json` with minimal changes.

### Seq event format

Follows `backend/app/core/error_tracking.py`'s envelope:

```json
{
  "Events": [{
    "Timestamp": "2026-06-12T03:51:41.000Z",
    "Level": "Information",
    "MessageTemplate": "factory.stage.{Stage} verdict={Verdict} issue=#{IssueNumber}",
    "Properties": {
      "gen_ai.system": "dark-factory",
      "gen_ai.operation.name": "stage.conformance",
      "gen_ai.usage.input_tokens": 45000,
      "gen_ai.usage.output_tokens": 8000,
      "Stage": "conformance",
      "Verdict": "PASS",
      "IssueNumber": 333,
      "Intent": "new",
      "RunId": "...",
      "CostUsd": 0.061,
      "DurationMs": 180000
    }
  }]
}
```

Queryable in Seq by: `Stage = "conformance"`, `Verdict = "BLOCKED"`, `IssueNumber = 333`.

### Changes to `entrypoint.sh`

1. **Hoist `ARTIFACTS_DIR`**: define early as:
   ```bash
   ARTIFACTS_DIR="${HOME}/.archon/workspaces/omniscient/markethawk/artifacts/runs/${ARCHON_RUN_ID:-${ISSUE_NUM}}"
   export ARTIFACTS_DIR
   mkdir -p "$ARTIFACTS_DIR"
   ```
   (Uses the Archon workflow run ID when available, falls back to issue number.)

2. **Capture Archon cost data**: after `archon workflow run` returns:
   ```bash
   ARCHON_COST_JSON=$(mktemp)
   archon workflow cost --last --json --quiet > "$ARCHON_COST_JSON" 2>/dev/null || true
   ```

3. **Assemble run record**: call `assemble` to build `run-record.json` from all artifact files:
   ```bash
   python3 "$CLONE_DIR/dark-factory/scripts/run_record.py" assemble \
     --run-id "${ARCHON_RUN_ID:-unknown}" \
     --issue "$ISSUE_NUM" \
     --intent "$INTENT" \
     --artifacts-dir "$ARTIFACTS_DIR" \
     --archon-cost-json "$ARCHON_COST_JSON" \
     --out-file "$ARTIFACTS_DIR/run-record.json" || true
   rm -f "$ARCHON_COST_JSON"
   ```

4. **Rewrite `post_cost_report()`**: read token/cost data from `$ARTIFACTS_DIR/run-record.json` instead of `archon workflow cost --last --json`. The comment format (cumulative totals, hidden HTML markers, per-run markdown table) stays unchanged — only the data source changes.

5. **Partial-failure record** (in `on_failure` trap): call `record` with `--stage failed --verdict failed` before the existing failure comment logic:
   ```bash
   python3 "$CLONE_DIR/dark-factory/scripts/run_record.py" record \
     --run-id "${ARCHON_RUN_ID:-unknown}" \
     --issue "$ISSUE_NUM" \
     --intent "$INTENT" \
     --stage "failed" \
     --verdict "failed" || true
   ```

### `SEQ_URL` env var

Add `SEQ_URL: http://seq:5341` to the `dark-factory` service env in `docker-compose.yml`, following the existing pattern (already present for `backend`, `celery-worker`, etc.). `run_record.py` reads `os.environ.get("SEQ_URL", "http://seq:5341")`.

### Verdict artifacts survive the container

The `assemble` command reads verdict file content from the four `.md` artifact files and stores it under a `"artifacts"` key in `run-record.json` and in the `runs.jsonl` event:

```json
"artifacts": {
  "validation": "STATUS: PASS\n...",
  "conformance": "STATUS: PASS\nVERDICT: Approved\n...",
  "review": "STATUS: PASS\nBLOCKERS: 0\n...",
  "conflict_resolution": "CONFLICT_VERDICT=none\n..."
}
```

This is the mechanism by which "verdict artifacts no longer die with /tmp."

## Alternatives Considered

### Option B: Pure bash with `jq` + `curl`

A shell function defined in `entrypoint.sh` that uses `printf`/`jq` to build JSON and `curl` to POST to Seq.

**Rejected** because:
- JSON assembly with bash string escaping is fragile (special characters in verdict text break `printf '%s'` args).
- The `scripts/` directory already establishes Python as the language for non-trivial bash helper work. Consistency matters for maintainability.
- Testing bash functions is harder than testing a Python module.

### Option C: Single end-of-run record with no `runs.jsonl`

One large record emitted only at the end of the run, stored in `$ARTIFACTS_DIR` (ephemeral).

**Rejected** because:
- Crashes after conformance but before code-review produce no record — partial runs remain invisible.
- `$ARTIFACTS_DIR` dies with the `--rm` container, so the record is lost on the next query. The acceptance criterion "accumulates history across runs" requires a durable sink.

### Option D: Emit via GELF/stdout

Echo CLEF-formatted JSON lines to stderr, captured by the existing Docker GELF driver.

**Rejected** because (per ADR-0011): the GELF driver wraps each line as the opaque `short_message` field — it does not parse JSON bodies, so `gen_ai.*` properties would not be indexed as queryable Seq fields. Direct HTTP POST to the raw events API is the only mechanism that produces structured, queryable properties.

## Open Questions (Non-Blocking)

1. **Scheduler dispatch events**: The issue mentions "every DAG stage and the scheduler write to" the run record. This spec covers factory-container records only. Scheduler dispatch events (circuit-breaker trips, dispatch decisions) are a natural Phase 2 addition to `runs.jsonl` — the scheduler already mounts `/var/lib/dark-factory` and has Python available.

2. **`ARCHON_RUN_ID` availability**: The Archon CLI may or may not expose the current workflow run ID as an env var. If not, a UUID generated at the start of `entrypoint.sh` is an acceptable substitute for the `run_id` field.

3. **`runs.jsonl` rotation**: There's no max-size policy. With one run per issue per day, growth is slow. A `logrotate`-style cap (e.g., keep last 1000 lines) is deferred.

## Assumptions

- `fcntl.flock` (exclusive) is sufficient for atomic append when WIP_LIMIT ≤ 10. POSIX guarantees for larger write sizes require the lock regardless.
- The factory Docker image has Python 3.9+ available (confirmed: `entrypoint.sh` already calls `python3` multiple times, e.g. lines 302-325).
- `SEQ_URL` addition to `docker-compose.yml` is a non-breaking change (services that don't use it ignore the variable).
- The `assemble` command treats missing artifact files as absent stages (no error), so runs that skip conformance (e.g., refine flows) produce a partial but valid record.
- This spec does not change the `archon-dark-factory.yaml` DAG — all changes are in `entrypoint.sh` and the new `run_record.py` script.
