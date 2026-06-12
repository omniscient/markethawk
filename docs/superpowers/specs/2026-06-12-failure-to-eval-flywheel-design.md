# Failure-to-Eval Flywheel — Design (issue #336)

**Date**: 2026-06-12
**Issue**: [#336](https://github.com/omniscient/markethawk/issues/336) — Failure-to-eval flywheel: post-mortem stage on circuit-break, failures become eval tasks

## Problem

When the circuit breaker trips, the failure's cause evaporates: the human reconstructs it from Seq, the retry run starts blind, and nothing accumulates. The factory's most valuable data — its own failures — is discarded. Two consequences:

1. **Blind retries** — the next dispatch has no context about what broke last time, so it repeats the same mistake.
2. **Wasted signal** — every circuit-break is a concrete test case ("the factory failed to implement X") that could be replayed to measure improvement. Today that data is thrown away.

## Solution Overview

Three composable additions:

1. **Post-mortem comment**: when a factory run fails, a haiku agent reads the failure artefacts and posts a one-paragraph "why this failed" comment on the ticket using the existing marker-comment pattern.
2. **Retry reads it back**: no new code needed — the existing `gh issue view --json comments` fetch in `archon-dark-factory.yaml` already includes all comments in every dispatch's context.
3. **Eval promotion**: the circuit-break path applies a `factory-regression` label and appends a line to `dark-factory/evals/factory-failures.jsonl`. This is the benchmark corpus feed. The replay harness (candidate C3 from the architecture review) consumes it when built.

## Requirements

- When a dark factory run exits non-zero (non-rate-limit failure), a haiku agent generates a post-mortem paragraph and posts it as a distinct marker comment (`<!-- df-post-mortem -->`) on the issue *before* the status moves to Blocked.
- The post-mortem comment uses the "Posted by MarketHawk Dark Factory" footer so the bot-comment filter in `scheduler.sh:has_new_comment_after_report` already excludes it from "human feedback" detection — no filter changes needed.
- The comment is idempotent: `post_or_update_comment` replaces an existing `df-post-mortem` comment rather than appending duplicates.
- When `trip_to_blocked()` fires in `scheduler.sh`, it applies a `factory-regression` label alongside the existing `needs-discussion` label.
- `dark-factory/evals/factory-failures.jsonl` accumulates one JSONL line per promoted failure: `{issue, title, phase, failure_reason, postmortem_excerpt, promoted_at}`. The line is written and committed by the dark factory container during the failure path (git commit to the current branch; the commit is part of the run's history).
- Manually-labelled `factory-regression` issues are included in the corpus by label query — no further automation required for the manual path.
- No direct `.archon/memory` writes from the post-mortem step.

## Architecture / Approach

### A. Post-mortem generation (`dark-factory/entrypoint.sh`)

The archon process failure is detected in the explicit `if [ "$EXIT_CODE" -ne 0 ]` block (lines 631-666) inside the `while true` loop. The `$TMP_OUT` variable (mktemp holding the archon stdout) is available there before the `rm -f "$TMP_OUT"` call. The `$ARTIFACTS_DIR` (per `archon-dark-factory.yaml` node `fetch-issue`, default `/tmp/artifacts/${ISSUE}`) may have `implementation.md`, `conformance.md`, and `review.md` from the partial run.

**Implementation steps:**

1. Add a `DF_POST_MORTEM_MARKER="<!-- df-post-mortem -->"` constant alongside the existing markers (lines 95-97).
2. Add a `run_post_mortem()` function that:
   - Assembles evidence: tail of `$TMP_OUT` (last 200 lines of archon transcript), plus any `implementation.md` / `conformance.md` / `review.md` in `$ARTIFACTS_DIR`.
   - Calls `claude -p --model claude-haiku-4-5-20251001` with a prompt asking for a one-paragraph root-cause diagnosis. This mirrors the existing Tier 2 conflict-resolution pattern (line 353: `raw=$(claude -p --model sonnet < "$tmpfile" 2>/dev/null)`).
   - Calls `post_or_update_comment "$DF_POST_MORTEM_MARKER" "..."` to post the result on the issue.
   - Non-fatal: wrapped in `|| true` so a post-mortem failure never masks the real failure.
3. In the non-rate-limit failure branch, call `run_post_mortem` **before** `rm -f "$TMP_OUT"` and `exit "$EXIT_CODE"`.
4. For unexpected ERR-trap failures (`on_failure`), call `run_post_mortem` there as well, using an empty transcript (since `$TMP_OUT` is out of scope). Unexpected failures are rarer and have less artifact evidence, so a degraded post-mortem is acceptable.

**Haiku prompt (template):**
```
You are diagnosing a failed AI coding factory run.
Issue: #$ISSUE_NUM — $ISSUE_TITLE
Phase: $INTENT
Exit code: $EXIT_CODE

Archon transcript tail (last 200 lines):
$TRANSCRIPT_TAIL

Artifacts produced before failure:
$ARTIFACTS_SUMMARY

Write ONE paragraph (3-5 sentences) explaining the most likely root cause of this failure.
Focus on: what the agent tried to do, what went wrong, and what a retry should do differently.
Do not repeat the transcript verbatim. Be concrete and actionable.
```

**Commit the JSONL entry:** After generating the post-mortem, if `$CLONE_DIR` is a valid git repo and `$ISSUE_NUM` is set, append to `dark-factory/evals/factory-failures.jsonl` and commit:
```bash
JSONL_FILE="$CLONE_DIR/dark-factory/evals/factory-failures.jsonl"
jq -n --arg i "$ISSUE_NUM" --arg t "$ISSUE_TITLE" --arg p "$INTENT" \
       --arg r "$EXIT_CODE" --arg m "$POSTMORTEM" --arg ts "$(date -u +%FT%TZ)" \
  '{issue: ($i|tonumber), title: $t, phase: $p, exit_code: ($r|tonumber), postmortem: $m, promoted_at: $ts}' \
  >> "$JSONL_FILE" || true
# Guard: only commit if file changed and we're on a branch
if [ -n "$(git -C "$CLONE_DIR" diff --name-only "$JSONL_FILE" 2>/dev/null)" ]; then
  git -C "$CLONE_DIR" add "$JSONL_FILE"
  git -C "$CLONE_DIR" commit --no-verify -m "eval: promote failure of issue #${ISSUE_NUM} to benchmark corpus" || true
fi
```

### B. Label application (`dark-factory/scheduler.sh`)

In `trip_to_blocked()`, add `factory-regression` label application alongside the existing `needs-discussion` label:

```bash
# Existing (line 358-359):
gh issue edit "$issue_num" --repo "${OWNER}/markethawk" \
  --add-label needs-discussion 2>/dev/null || true

# Add:
gh issue edit "$issue_num" --repo "${OWNER}/markethawk" \
  --add-label factory-regression 2>/dev/null || true
```

The `factory-regression` label must be created in the repo once (can be done in the implementation):
```bash
gh label create "factory-regression" --repo omniscient/markethawk \
  --description "Failed dark factory run promoted to eval corpus" --color "B60205" || true
```

### C. JSONL corpus file

Create `dark-factory/evals/factory-failures.jsonl` as an empty file committed to main. The file grows one line per circuit-break trip. Each line is valid JSON:
```json
{"issue": 123, "title": "Add feature X", "phase": "implement", "exit_code": 1, "postmortem": "The agent failed because...", "promoted_at": "2026-06-12T04:00:00Z"}
```

To query the corpus:
```bash
# List all promoted failures
gh issue list --repo omniscient/markethawk --label factory-regression

# View the JSONL corpus
cat dark-factory/evals/factory-failures.jsonl | jq .
```

### D. Documentation (`DEVELOPMENT.md`)

Add a section describing the eval flywheel:
- How failures are promoted (automatic via circuit-break, or manual via `factory-regression` label)
- How to query the corpus
- Reference to C3 (replay harness, future work)

## Alternatives Considered

### Alt 1: Post-mortem in `trip_to_blocked()` (scheduler-side only)
The scheduler has no access to `$TMP_OUT` or `$ARTIFACTS_DIR` — it runs in a separate container. It can only read GitHub comments. A post-mortem based solely on the existing failure comment would be thin and redundant. Rejected.

### Alt 2: Both `on_failure` + `trip_to_blocked()` (two post-mortems)
A scheduler-side "summary" post-mortem over N runs' worth of comments adds complexity for marginal gain. The per-run post-mortem (Option A) already covers the Reflexion feedback loop. The circuit-break can use the latest per-run post-mortem rather than generating a new one. Rejected.

### Alt 3: JSONL only (no GitHub label)
The label is the primary human-facing and query interface. Without it, discovering the eval corpus requires reading a committed file rather than a `gh issue list` query. The label also lets humans promote failures manually. Rejected in favor of both.

### Alt 4: No JSONL, label only
The label is removed when a ticket is retried/resolved. A JSONL file persists the corpus even after successful resolution. Given the negligible implementation cost of appending a JSONL line, both are included. Rejected as too minimal.

## Open Questions (non-blocking)

- **C3 replay harness format**: when C3 is built, the JSONL may need additional fields (e.g., the issue body at time of failure, the git branch state). These can be added by cherry-picking commits from this issue's branch at C3 implementation time; the JSONL is intentionally minimal for now.
- **`factory-regression` vs `needs-discussion` label coexistence**: both are SKIP_LABELS; applying both is redundant but harmless. If `factory-regression` is added to `SKIP_LABELS`, `needs-discussion` can be dropped from the circuit-break path in a follow-up.

## Assumptions

- `claude` binary available in the dark factory container at `/usr/bin/claude` (confirmed by `entrypoint.sh:620`).
- `claude-haiku-4-5-20251001` is the correct Haiku model ID (matches the project's Claude API usage; verify against `.claude/` config or via `claude --version` before implementing).
- `$ARTIFACTS_DIR` resolves to `/tmp/artifacts/${ISSUE}` or similar at failure time; the post-mortem must handle the case where none of the artifact files exist (partial run that failed before any artefacts were written).
- `ISSUE_NUM` and `ISSUE_TITLE` are available in the `on_failure` scope; `ISSUE_TITLE` may need to be set from `$ARTIFACTS_DIR/issue.json` rather than from a bare env var.
- The `dark-factory/evals/` directory does not exist yet; it must be created and the empty `factory-failures.jsonl` committed as part of this implementation.
