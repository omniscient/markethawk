# Gate Seam — Design (issue #334)

**Date**: 2026-06-12
**Issue**: [#334](https://github.com/omniscient/markethawk/issues/334) — Deepen the Gate seam: layered gate policy, judge calibration audit, blast-radius human gate

## Problem

The two LLM gates are shallow and miscalibrated in opposite directions:

- **Conformance over-blocks**: 9 "excise out-of-scope" reverts in 42 days (including one double-revert at 2948fb0), producing 42 scope-spillover tickets. Root cause partially addressed in #275/#276; the gate seam itself is untracked.
- **Code-review under-blocks**: 0 blocking findings across every sampled PR. `fail_open: true` plus auto-advance means the gate is a rubber stamp.

Both commands carry near-identical inline `route_memory_file()` / `write_memory_entry()` implementations (95% duplicate), separate verdict formats, and no shared policy. PR #278 passed both gates and re-reverted a settled migration decision (resolved in #281) — a seed/migration contradiction that neither gate was structurally equipped to catch.

## Requirements

1. One shared `dark-factory/scripts/gate_lib.sh` sourced by both command files; duplication of `route_memory_file()` and `write_memory_entry()` removed.
2. Common 4-field verdict header (`STATUS`, `GATE_TYPE`, `FINDINGS_COUNT`, `SEVERITY`) emitted by all gates via a shared `emit_verdict()` helper in `gate_lib.sh`.
3. Deterministic `dark-factory/scripts/gate_blast_radius.py` that classifies changed files into trigger categories and writes a blast-radius verdict.
4. `dark-factory-validate.md` gains **Phase 0** (before pytest/tsc) that runs the blast-radius check and blocks the pipeline with `STATUS: HUMAN_REQUIRED` when triggered.
5. `close-preview` node in `archon-dark-factory.yaml` checks for `needs-discussion` label before calling `gh pr ready` / `gh pr merge` — refuses to auto-merge if the label is present.
6. `config.yaml` gains a `blast_radius` block with tunable knobs.
7. Calibration audit runbook documented (no new code — manual process, outputs `config.yaml` edits and a `docs/gate-calibration.md` record).
8. `dark-factory/tests/test_conformance_memory_write.sh` updated to source `gate_lib.sh` instead of inline-defining `route_memory_file()`.

## Architecture

### Shared library: `dark-factory/scripts/gate_lib.sh`

This file is sourced by both `dark-factory-conformance.md` and `dark-factory-code-review.md` at Phase 1 load time:

```bash
source "$(git rev-parse --show-toplevel)/dark-factory/scripts/gate_lib.sh"
```

It exports three functions:

**`route_memory_file(FILE)`** — maps a changed file path to the appropriate memory file. Identical to the current inline implementation in both commands:

```bash
route_memory_file() {
  local FILE="$1"
  case "$FILE" in
    backend/app/*)            echo ".archon/memory/backend-patterns.md" ;;
    frontend/src/*)           echo ".archon/memory/frontend-patterns.md" ;;
    .archon/*|dark-factory/*) echo ".archon/memory/dark-factory-ops.md" ;;
    ARCHITECTURE.md)          echo ".archon/memory/architecture.md" ;;
    *)                        echo ".archon/memory/codebase-patterns.md" ;;
  esac
}
```

**`write_memory_entry(TARGET PATH_PREFIX TEXT SOURCE ISSUE_NUM)`** — dedup-checked, cap-guarded, expiry-cleaned memory writer. Identical to the current inline implementation in both commands. The single canonical definition removes the 95% duplication that the issue flags.

**`emit_verdict(GATE_TYPE STATUS FINDINGS_COUNT SEVERITY)`** — writes the 4-field common header to stdout; caller redirects to the artifact file:

```bash
emit_verdict() {
  local GATE="$1" STATUS="$2" COUNT="$3" SEV="$4"
  printf "STATUS: %s\nGATE_TYPE: %s\nFINDINGS_COUNT: %s\nSEVERITY: %s\n" \
    "$STATUS" "$GATE" "$COUNT" "$SEV"
}
```

Conformance uses: `emit_verdict conformance PASS|BLOCKED|SKIPPED|HUMAN_REQUIRED 0 none|high`
Code-review uses: `emit_verdict code-review PASS|BLOCKED|SKIPPED|ERROR "$BLOCKERS" "$SEVERITY"`
Blast gate uses:  `emit_verdict blast PASS|HUMAN_REQUIRED "$HIT_COUNT" none|critical`

Each gate file appends its gate-specific fields below the common header (existing `VERDICT:`, `CYCLES:`, `NO_SPEC:`, `BLOCKERS:`, `ADVISORY:`, `THRESHOLD:` fields remain unchanged — the `report` node continues to grep for them).

### Blast-radius gate: `dark-factory/scripts/gate_blast_radius.py`

A deterministic Python script (mirroring the role of `code_review_payload.py`) that reads the changed file list and classifies against three trigger categories. Output is written to `$ARTIFACTS_DIR/blast.md`.

**Input:**
```bash
python3 dark-factory/scripts/gate_blast_radius.py \
  --changed-files-stdin \           # reads newline-separated file list from stdin
  --hotspots docs/codeindex-hotspots.md \
  --config .claude/skills/refinement/config.yaml
```

**Trigger categories:**

| Category | Trigger condition | Blocking? |
|----------|-----------------|-----------|
| A — hotspot | File appears in `docs/codeindex-hotspots.md` at blast score ≥ `blast_radius.hotspot_score_floor` (default 5.0) | Always mandatory |
| B — migration/seed/auth | Path matches `alembic/versions/**`, `dark-factory/seed/**`, `*seed*.sql`, or `backend/app/routers/auth.py` | Always mandatory |
| C — PR size | Total changed lines > `blast_radius.size_budget_lines` (default 400) | Configurable via `blast_radius.size_budget_blocks` (default: false = advisory only) |

Category B is what would have caught the #278 seed/migration contradiction: migrations and seed SQL appear together in the changed-file list and are individually low blast-score, but both carry semantic coupling that the LLM gates cannot verify.

**Output artifact** (`$ARTIFACTS_DIR/blast.md`):
```
STATUS: PASS | HUMAN_REQUIRED
GATE_TYPE: blast
FINDINGS_COUNT: <N>
SEVERITY: none | critical
---
TRIGGER: hotspot | migration-seed | size | none
TRIGGERED_FILES:
  - alembic/versions/abc123_foo.py (category: migration-seed)
  - backend/app/routers/auth.py (category: hotspot, score: 55.5)
LINES_CHANGED: 312
```

### validate Phase 0 (new)

Inserted at the top of `dark-factory-validate.md`, before Phase 1 LOAD:

```
## Phase 0: BLAST-RADIUS HARD GATE

Read `blast_radius.enabled` from `.claude/skills/refinement/config.yaml` (default: true).
If false, skip this phase entirely (write `STATUS: SKIPPED` to blast.md and continue).

1. Get changed files:
   CHANGED=$(git diff main...HEAD --name-only 2>/dev/null)
   LINES=$(git diff main...HEAD --shortstat 2>/dev/null | grep -oP '\d+ insertion' | grep -oP '\d+' || echo 0)
   LINES=$((LINES + $(git diff main...HEAD --shortstat 2>/dev/null | grep -oP '\d+ deletion' | grep -oP '\d+' || echo 0)))

2. Run the blast-radius checker:
   echo "$CHANGED" | python3 dark-factory/scripts/gate_blast_radius.py \
     --changed-files-stdin \
     --hotspots docs/codeindex-hotspots.md \
     --config .claude/skills/refinement/config.yaml \
     > "$ARTIFACTS_DIR/blast.md"

3. Read verdict:
   BLAST_STATUS=$(grep '^STATUS:' "$ARTIFACTS_DIR/blast.md" | cut -d' ' -f2)
   BLAST_TRIGGER=$(grep '^TRIGGER:' "$ARTIFACTS_DIR/blast.md" | cut -d' ' -f2-)

4. If BLAST_STATUS = HUMAN_REQUIRED:
   a. Post an issue comment explaining which trigger fired and which files triggered it
   b. Add `needs-discussion` label: gh issue edit $ISSUE_NUM --add-label needs-discussion
   c. Move issue to Blocked on the project board (same board/field IDs as conformance Phase 5)
   d. Exit 1 — halts the pipeline
```

This phase covers all three intent paths (new/continue/resolve) because `validate` is the single choke point all merge-bound intents pass through.

### close-preview enforcement

In `archon-dark-factory.yaml`, the `close-preview` node currently calls `gh pr ready "$PR_NUM"` then `gh pr merge`. Add a label check immediately before the `gh pr ready` call:

```bash
# Refuse auto-merge if a blast-radius block (or any other gate block) is still active
HAS_NEEDS_DISCUSSION=$(gh issue view "$ISSUE_NUM" \
  --repo omniscient/markethawk \
  --json labels --jq '.labels[].name' \
  | grep -c 'needs-discussion' || true)
if [ "$HAS_NEEDS_DISCUSSION" -gt 0 ]; then
  echo "close-preview: BLOCKED — needs-discussion label present on issue #$ISSUE_NUM"
  echo "Remove the label after human review, then re-run: docker compose --profile factory run --rm dark-factory \"Close issue #$ISSUE_NUM\""
  exit 1
fi
```

This is the correct mechanism because: (a) the label survives across separate invocations (a `close` run is a different invocation from the `new`/`continue` run that fired the gate); (b) `needs-discussion` is already the idiomatic block signal used by conformance and code-review; (c) it remains in a consistent state until a human explicitly removes it after review. The `--draft` PR state remains as defense-in-depth, since `gh pr ready` is gated by the label check.

### config.yaml additions

New block added to `.claude/skills/refinement/config.yaml`:

```yaml
blast_radius:
  enabled: true
  hotspot_score_floor: 5.0      # files at or above this codeindex blast score trigger HUMAN_REQUIRED
  size_budget_lines: 400        # total added+deleted lines threshold (0 = disabled)
  size_budget_blocks: false     # true = size alone is blocking; false = advisory only
```

### Test file update

`dark-factory/tests/test_conformance_memory_write.sh` currently defines `route_memory_file()` inline to test it in isolation. After extraction it must source the real function:

```bash
# Replace inline definition with:
source "$(git rev-parse --show-toplevel)/dark-factory/scripts/gate_lib.sh"
```

The test cases themselves are unchanged — they test the same routing logic.

### report node (no changes needed)

The `report` node in the DAG already reads gate artifacts via `grep '^FIELD:'`. Adding the common 4-field header does not break existing field reads (they grep for specific fields like `VERDICT:`, `CYCLES:` which remain present). The blast gate adds a new artifact `blast.md` — the report node should surface it in the run summary. A new `BLAST_STATUS` read (mirroring `CONFORMANCE_STATUS`) should be added:

```bash
if [ -f "$ARTIFACTS_DIR/blast.md" ]; then
  BLAST_STATUS=$(grep '^STATUS:' "$ARTIFACTS_DIR/blast.md" | cut -d' ' -f2)
  BLAST_TRIGGER=$(grep '^TRIGGER:' "$ARTIFACTS_DIR/blast.md" | cut -d' ' -f2-)
fi
```

## Calibration Audit Runbook

The LLM judges (conformance and code-review) must complete this audit before their blocking power is changed. The audit is a one-time manual process — no new code is required.

### 5-Step Process

**Step 1 — Sample** (20–30 verdicts per gate):
- Conformance: search GitHub issues for comments containing "Spec Conformance — Blocked" and the 9 documented excise reverts (the root set for #334). Use `gh issue list --label scope-spillover --limit 50` to enumerate spillover tickets.
- Code-review: search PRs for "Code Review" reviews posted by the factory. Use `gh pr list --state merged --limit 50 --json reviews`.

**Step 2 — Label** each verdict `correct` (gate was right to block/pass) or `incorrect`:
- For a conformance block: was the flagged deviation genuinely out-of-scope or material? Check the spec.
- For a code-review block: was the flagged finding a real bug/security issue?
- For passes (the gate did not block): spot-check that the change was clean.

**Step 3 — Score**:

```
agreement_rate = correct_count / total_count
```

≥75% agreement = gate is calibrated for blocking power. <75% = gate needs further tuning first.

**Step 4 — Calibrate** (update `config.yaml` per the result):

| Gate | Under-agreement signal | Config lever |
|------|----------------------|--------------|
| Conformance | Over-blocks (excise FPs) | Set `conformance.excise_out_of_scope: false` (backlog only); or raise `block_on_material` threshold |
| Code-review | Under-blocks (0 findings = rubber stamp) | Set `code_review.fail_open: false` once agreement ≥75% confirms the judge is calibrated |

**Step 5 — Document** in `docs/gate-calibration.md` (created in this issue):
- Date of audit
- Sample size per gate
- Agreement rate per gate
- Resulting config.yaml changes and their rationale

This file is the permanent record that "calibration audit performed and documented" is satisfied.

## Alternatives Considered

**Alt 1: Python Gate class hierarchy (formal OOP interface)**
Formal Python abstract `Gate` class with `ConformanceGate` / `CodeReviewGate` subclasses. Rejected: the "adapter" boundary in this architecture is the LLM reviewer prompt + parse loop, which is markdown/shell orchestrated. Forcing conformance's reconcile loop and scope-excision logic into Python subclasses would require rewriting the full command orchestration — a scope far beyond this issue. The existing `code_review_payload.py` and `fmt_hunk_filter.py` establish the correct line: deterministic post-processing goes to Python; orchestration stays in the command.

**Alt 2: JSON artifact format for all gates**
All gate artifacts written as JSON instead of `KEY: value` text headers. Rejected: the `report` node (25+ `grep '^FIELD:' | cut` lines) would need a full rewrite. The common 4-field header achieves the "common schema" goal with zero disruption to existing artifact parsing.

**Alt 3: Blast gate as a standalone DAG node (between validate and conformance)**
A new `blast-radius-gate` node with its own `depends_on` and `trigger_rule`. Rejected: (a) `validate` already carries the OR-join `trigger_rule: none_failed_min_one_success` that joins `preview-up` and `preview-up-resolve`; a standalone node would need identical plumbing; (b) `conformance` only runs on `new`/`continue` intents — a node dependent on `validate` alone would not cover `resolve` runs, the exact path that reintroduces settled migration decisions.

**Alt 4: Calibration as an automated script (`calibrate_gate.py`)**
A script fetching past verdicts from GitHub, prompting for labels, and computing agreement. Rejected: gate verdict artifacts are not durably aggregated anywhere queryable — they exist as text comments on GitHub issues and PRs. The labeling set is tiny (20–30 items, one-time). The manual process is faster and the script would not be reused.

## Assumptions

1. `docs/codeindex-hotspots.md` is always current — the `update-codeindex` DAG step regenerates it before `implement`, so it is fresh by the time `validate` runs.
2. The `codeindex` binary is available on PATH in the factory container (confirmed by `dark-factory-ops.md` pattern).
3. `needs-discussion` is the correct label for blast-gate blocks — it is the idiomatic gate-block signal and is already applied by conformance and code-review on block. The human removes it after approving the high-risk change.
4. The calibration audit is run once by the human owner after this issue ships; the result drives config updates, not automated enforcement.
5. `dark-factory/seed/**` glob covers both `dark-factory/seed/*.sql` (the seeded root files) and `dark-factory/seed/seed/` (the nested subdirectory visible in git status).

## Open Questions (non-blocking)

- Should `gate_blast_radius.py` re-run `codeindex impact` live (always fresh) or read the committed `docs/codeindex-hotspots.md`? The spec assumes committed doc (deterministic, no binary dependency in the check); live recompute is a future enhancement.
- Should the `GATE_TYPE: blast` field in `blast.md` trigger a new board section in the `report` node comment? The spec says yes (surface blast trigger in the run summary) but leaves the exact wording to implementation.
