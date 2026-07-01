# Dark Factory Context Budget Telemetry — Design Spec

**Date:** 2026-07-01
**Status:** Spec pending review
**Issue:** #664 (parent epic: #663)
**Author:** MarketHawk Refinement Pipeline

---

## Overview

The Dark Factory pipeline can load large volumes of static and dynamic context before invoking Claude: governance docs, architecture files, memory, issue context, specs, plans, and diffs. Before the parent epic (#663) can optimize or enforce token budgets, the "observe" phase must produce a machine-readable artifact for every run.

This spec defines two pure-stdlib Python scripts and a workflow integration that emit `$ARTIFACTS_DIR/context-budget.json` at the start of each measured Dark Factory phase (refine, plan, implement, continue, conformance, code-review). No prompt contents are changed. The existing cost report behavior in `entrypoint.sh` is preserved unchanged.

---

## Requirements

1. **Measurement-only.** No prompt content changes in this issue. The artifact is observation data for the #663 epic's later "compare → optimize → enforce" phases.
2. **Emit `context-budget.json`** to `$ARTIFACTS_DIR/` for refine, plan, implement, continue, conformance, and code-review runs.
3. **Token estimation** uses a pure-stdlib character-count heuristic (`len(text) / CHARS_PER_TOKEN`) — no `tiktoken` or API calls. The Dark Factory container has no token-counting packages installed.
4. **Budget reference ceiling** is the model context window (200,000 tokens for the Sonnet/Opus family used across all phases). The `budget_tokens` field makes `estimated_input_tokens` immediately interpretable as a utilization percentage without enforcing anything.
5. **Included/dropped sections** reflect which context sources existed and were loaded vs. which were conditionally absent for this run (e.g., no spec during refine, no PR comments on a new implement run, empty memory context).
6. **Source file hashes** (SHA-256, first 12 hex chars) are recorded for deterministic on-disk sources: `CLAUDE.md`, `ARCHITECTURE.md`, spec, `memory-context.md`, `implementation.md`, and diff. Agent-chosen opportunistic reads (Phase 3 codebase exploration) are not captured; the artifact under-counts those by design and the field name reflects this.
7. **Preserve** `entrypoint.sh`'s `post_cost_report()` and `run-record assemble` paths — no edits to `entrypoint.sh`.
8. **Non-fatal.** The bash nodes that call `context_budget.py` must end with `|| true` so a script error never aborts the workflow phase.

---

## Architecture

### Two new scripts in `dark-factory/scripts/`

#### `token_estimate.py`

Pure-stdlib library module — no CLI, no side effects. Provides:

```python
CHARS_PER_TOKEN = 4.0  # tunable in the epic's optimize phase

def estimate_tokens(text: str) -> int:
    """Rough token estimate: chars / CHARS_PER_TOKEN."""
    return int(len(text) / CHARS_PER_TOKEN)

def hash_file(path: str) -> str | None:
    """SHA-256 of file contents, first 12 hex chars. Returns None if file missing."""

def hash_text(text: str) -> str:
    """SHA-256 of a string, first 12 hex chars."""
```

Follows the pure-stdlib, no-side-effect pattern established by `code_review_payload.py` and `gate_lib.sh`.

#### `context_budget.py`

CLI entry point. Probes on-disk context sources, estimates token counts per section, and writes `context-budget.json`. Invoked by pre-phase bash nodes in `archon-dark-factory.yaml`.

**CLI signature:**

```bash
python3 context_budget.py \
  --scenario        refine|plan|implement|continue|conformance|code-review \
  --issue-num       <int> \
  --run-id          <uuid-hex> \
  --artifacts-dir   <path> \
  --clone-dir       <path>           # repo root (for CLAUDE.md, ARCHITECTURE.md) \
  [--spec-file      <path>]          # located by caller when known \
  [--plan-file      <path>]          # located by caller when known \
  [--memory-file    <path>]          # $ARTIFACTS_DIR/memory-context.md \
  [--issue-json     <path>]          # $ARTIFACTS_DIR/issue.json \
  [--impl-file      <path>]          # $ARTIFACTS_DIR/implementation.md \
  [--diff-file      <path>]          # $ARTIFACTS_DIR/review_diff.txt or git diff output \
  --out             <path>           # output path (default: $ARTIFACTS_DIR/context-budget.json)
```

**Section registry per scenario** (derived from the command files):

| Section | refine | plan | implement/continue | conformance | code-review |
|---|---|---|---|---|---|
| `claude_md` | ✓ | ✓ | ✓ | — | — |
| `architecture_md` | ✓ | — | ✓ | — | — |
| `skill_prompts` | ✓ | ✓ | — | ✓ | ✓ |
| `issue_context` | ✓ | ✓ | ✓ | — | ✓ |
| `comments` | ✓ | ✓ | ✓ | — | — |
| `memory_context` | ✓ | ✓ | ✓ | — | — |
| `spec` | — | ✓ | — | ✓ | — |
| `plan` | — | — | — | — | — |
| `implementation_md` | — | — | — | ✓ | — |
| `diff` | — | — | — | ✓ (1000-line cap) | ✓ (1000-line cap) |
| `pr_reviews` | — | — | continue only | — | — |

Sections that a scenario does not load at all are omitted from the JSON. Sections that a scenario would load but whose source file is absent are listed as `"status": "dropped"` with a `"reason"` field.

### JSON output schema

```json
{
  "schema_version": 1,
  "scenario": "refine",
  "run_id": "a3f9...",
  "issue_number": 664,
  "generated_at": "2026-07-01T03:17:00Z",
  "budget_tokens": 200000,
  "estimated_input_tokens": 42500,
  "utilization_pct": 21.3,
  "sections": {
    "claude_md": {
      "status": "included",
      "tokens": 18200,
      "file_hash": "a1b2c3d4e5f6"
    },
    "architecture_md": {
      "status": "included",
      "tokens": 14800,
      "file_hash": "f6e5d4c3b2a1"
    },
    "issue_context": {
      "status": "included",
      "tokens": 1800
    },
    "comments": {
      "status": "included",
      "tokens": 600
    },
    "memory_context": {
      "status": "dropped",
      "tokens": 0,
      "reason": "empty_or_missing"
    },
    "spec": {
      "status": "dropped",
      "tokens": 0,
      "reason": "not_yet_written"
    },
    "diff": {
      "status": "dropped",
      "tokens": 0,
      "reason": "not_applicable_for_scenario"
    }
  },
  "included_sections": ["claude_md", "architecture_md", "issue_context", "comments"],
  "dropped_sections": ["memory_context", "spec", "diff"],
  "source_file_hashes": {
    "CLAUDE.md": "a1b2c3d4e5f6",
    "ARCHITECTURE.md": "f6e5d4c3b2a1"
  }
}
```

Truncated sections (conformance and code-review diffs capped at 1000 lines) are represented as `"status": "included_partial"` with an additional `"truncated_at_lines": 1000` field.

### Integration in `archon-dark-factory.yaml`

One `bash:` telemetry node is inserted immediately before each measured `command:` node. Each node:
- inherits `$ARTIFACTS_DIR`, `$RUN_ID`, `$ISSUE` from the workflow environment (set in `entrypoint.sh` before the workflow runs)
- calls `context_budget.py` with the paths appropriate for that phase
- ends with `|| true` (non-fatal)
- carries `depends_on` matching the `command:` node it precedes

Example for the `refine` phase (inserted before node `refine`):

```yaml
- id: budget-refine
  bash: |
    python3 "$CLONE_DIR/dark-factory/scripts/context_budget.py" \
      --scenario refine \
      --issue-num "$ISSUE" \
      --run-id "$RUN_ID" \
      --artifacts-dir "$ARTIFACTS_DIR" \
      --clone-dir "$CLONE_DIR" \
      --issue-json "$ARTIFACTS_DIR/issue.json" \
      --memory-file "$ARTIFACTS_DIR/memory-context.md" \
      --out "$ARTIFACTS_DIR/context-budget.json" || true
  depends_on: [setup-refine-branch, fetch-issue]
  when: "$parse-intent.output.intent == 'refine'"

- id: refine
  command: dark-factory-refine
  depends_on: [budget-refine, setup-refine-branch, fetch-issue]
  when: "$parse-intent.output.intent == 'refine'"
```

The same pattern applies for `plan`, `implement`, `conformance`, and `code-review`, each with scenario-specific `--spec-file`, `--diff-file`, etc. arguments resolved using the same path conventions already used by those phases' bash scaffolding.

---

## Approaches Considered

### Approach A (chosen): Two scripts + pre-phase bash nodes in workflow YAML

`token_estimate.py` provides pure functions; `context_budget.py` provides the CLI. Pre-phase bash nodes in `archon-dark-factory.yaml` call `context_budget.py` before Claude runs the corresponding command phase.

**Pros:** Deterministic — runs before the LLM session, can hash files and count context before it changes; matches the existing bash-node scaffolding pattern (`setup-refine-branch`, `update-codeindex`); no `entrypoint.sh` edits needed; non-fatal by design.

**Cons:** The YAML edit touches 5 phase blocks; agent-opportunistic reads (Phase 3 codebase exploration) can't be captured pre-prompt.

### Approach B (rejected): Hook in `entrypoint.sh`, post-run reconstruction

Call `context_budget.py` at the end of the run alongside `run-record assemble`, reconstructing context from artifact files that were produced.

**Why rejected:** `entrypoint.sh` has a single `archon workflow run` call with no per-phase hooks. Post-run reconstruction can't capture which sections were loaded before Claude ran; it infers from output artifacts, not input context. Also risks entangling with `post_cost_report()` logic (the AC explicitly says to preserve that path).

### Approach C (rejected): Call from inside Claude's skill prompt scripts

Have the refine/plan/etc. command markdown files invoke `context_budget.py` as part of their Phase 1 load.

**Why rejected:** Skill prompts are LLM instructions, not deterministic bash. The AC says "Do not change prompt contents yet." Adding bash invocations to skill prompts is a prompt change. Emission would be non-deterministic.

---

## File Layout

```
dark-factory/scripts/
  token_estimate.py        # NEW: pure stdlib token estimation helpers
  context_budget.py        # NEW: CLI — probes sections, emits context-budget.json

.archon/workflows/
  archon-dark-factory.yaml  # MODIFIED: 5 new bash: telemetry nodes (budget-refine,
                            #   budget-plan, budget-implement, budget-conformance,
                            #   budget-code-review)
```

All output goes to `$ARTIFACTS_DIR/context-budget.json` alongside existing `run-record.json`, `issue.json`, and `memory-trace.json`.

---

## Open Questions (non-blocking)

1. **Skill prompt sizes** — `/opt/refinement-skills/orchestrator-prompt.md`, `product-owner-prompt.md`, and `conformance-reviewer-prompt.md` are container-mounted at a known path. Their sizes are stable within a container version. Should they be included in the telemetry? They are predictable but not in the git repo; hashing them is possible but lower-value.

2. **`continue` vs `new`** — Both intents use the `dark-factory-implement` command node. The `pr_reviews` / `pr_inline_comments` sections are only present for `continue` runs where a PR exists. The script can detect this by checking whether `pr_reviews` keys exist in `issue.json`. No separate `--intent` flag is needed if `issue.json` is passed.

3. **Aggregated view** — The artifact is per-phase. A future step in the epic could aggregate across phases (refine → plan → implement chain) to show total context loaded per issue, not just per phase.

---

## Assumptions

- `CHARS_PER_TOKEN = 4.0` is a reasonable approximation for Claude Sonnet/Opus (proven close enough for rough measurement; the constant is tunable).
- `budget_tokens = 200_000` represents the effective context window for all models used in Dark Factory phases (Sonnet 4.6, Opus 4.8). This is accurate as of 2026-07-01.
- The `$RUN_ID`, `$ARTIFACTS_DIR`, `$CLONE_DIR`, and `$ISSUE` environment variables are available in all workflow bash nodes (they are exported in `entrypoint.sh` before `archon workflow run` is called).
- Archon `bash:` nodes support `when:` and `depends_on:` fields (confirmed by existing nodes `setup-refine-branch`, `update-codeindex`, `regen-codeindex`).
