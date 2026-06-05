# AI Code-Review Sub-Stage (Dark Factory) — Design

**Date:** 2026-06-04
**Status:** Approved (design) — pending implementation plan
**Author:** Brainstormed with Claude (Opus 4.8)

## Problem

The dark-factory pipeline validates an implementation (pytest, tsc, endpoint smoke
tests) and verifies spec conformance, but nothing performs a **code-quality / correctness
review** of the diff before the PR goes to a human. Bugs, edge cases, naming problems, and
security issues that pass the tests still reach review unflagged. We want an autonomous AI
reviewer that inspects `git diff main...HEAD`, blocks the PR on serious findings, and leaves
inline review comments for the rest — reusing the existing `conformance-reviewer` subagent
pattern.

## Goal

Add a `code-review` node to the dark-factory workflow that, on every `new`/`continue` run:

1. Spawns a **code-reviewer subagent** (Agent tool, pinned to `claude-opus-4-8`) against the
   implementation diff.
2. Produces a structured, severity-tagged finding list.
3. **Blocks** the PR when any finding is `critical` or `high` (mirroring the conformance
   gate: blocked comment, issue → Blocked, `needs-discussion`, non-zero exit).
4. Posts all findings as **inline review comments** on the PR (a single GitHub review).

This extends the conformance subagent pattern and requires **no new external services** —
only a new workflow node, a new command file, a new reviewer prompt, and a config block.

## Non-Goals (v1)

- Auto-fixing findings (no reconcile loop — block-and-hand-back only).
- Reviewing `resolve`-intent runs (conflict-resolution branches).
- Dismissing / superseding stale reviews across `continue` re-runs.
- Reviewing documentation prose or migration SQL content.

## Pipeline Placement

The reviewer runs as a dedicated node **after the PR is created** so inline comments can
anchor to real diff lines, and **before** `status-in-review` so a block diverts the issue to
Blocked instead of letting it reach In Review:

```
validate → conformance → push-and-pr (PR created) → code-review → status-in-review → report
```

- `when: "$parse-intent.output.intent == 'new' || $parse-intent.output.intent == 'continue'"`
  (same guard as `conformance` / `push-and-pr`).
- `depends_on: [push-and-pr]`.
- `status-in-review` and `report` gain `code-review` to their `depends_on` so a non-zero exit
  from `code-review` halts the board move (consistent with how `conformance` Phase 5 halts
  `push-and-pr`).

Rationale for a dedicated post-PR node (vs. running inside `validate`): `validate` runs two
nodes before the PR exists, so neither inline comments nor a PR-level block are possible there.
The conformance gate already centralizes blocking, but it too runs pre-PR; putting code review
after `push-and-pr` is the only placement that gives native inline-comment support.

## Components

### 1. Workflow node (`.archon/workflows/archon-dark-factory.yaml`)

New node `code-review` of `command: dark-factory-code-review`, inserted between
`push-and-pr` and `status-in-review`. Clone-read — no image rebuild. `idle_timeout: 600000`.

### 2. Command (`.archon/commands/dark-factory-code-review.md`) — NEW

Phases mirror `dark-factory-conformance.md`:

- **Phase 1 — LOAD.** Read the `code_review` block from
  `.claude/skills/refinement/config.yaml`. If `enabled: false`, write
  `$ARTIFACTS_DIR/review.md` with `STATUS: SKIPPED` and exit 0. Extract `BLOCK_THRESHOLD`
  (default `high`), `FAIL_OPEN` (default `true`), `MAX_FINDINGS` (default 50). Determine
  `ISSUE_NUM` and `PR_NUM` (`gh pr list --head "$(git branch --show-current)" --json number`).

- **Phase 2 — DIFF.** Build the review diff with the *same* pre-triage exclusions
  conformance uses:
  ```bash
  git diff main...HEAD \
    -- ':!*.lock' ':!*.md' ':!.archon/memory/**' \
    ':!codeindex.json' ':!symbolindex.json' \
    ':!docs/codeindex-hotspots.md' ':!docs/database-schema.md' \
    2>/dev/null | head -1000
  ```
  If the diff is truncated at 1000 lines, `log()` it (no silent cap). If the diff is empty,
  write `STATUS: PASS` (nothing to review) and exit 0.

- **Phase 3 — REVIEW.** Spawn one reviewer subagent via the Agent tool:
  - `description`: "Code review: diff vs correctness/security"
  - `model`: `claude-opus-4-8` (always pinned, like the conformance reviewer)
  - `prompt`: contents of `.claude/skills/refinement/code-review-reviewer-prompt.md` with
    `$DIFF_CONTENT` and `$ISSUE_CONTEXT` (issue title + body) substituted.
  - The subagent returns the structured finding block (see §4).

- **Phase 4 — PARSE & GATE.** Parse the findings table. Split by severity against
  `BLOCK_THRESHOLD`: `critical`/`high` → **blockers**; `medium`/`low` → **advisory**.
  If the subagent errored / timed out / returned unparseable output:
  - `FAIL_OPEN=true` → write `STATUS: ERROR` (advisory), do **not** block, continue to Phase 5.
  - `FAIL_OPEN=false` → treat as a blocker.

- **Phase 5 — POST.** Build one GitHub review payload and post it:
  ```bash
  gh api repos/omniscient/markethawk/pulls/$PR_NUM/reviews --input payload.json
  ```
  - `event`: `REQUEST_CHANGES` if any blocker exists, else `COMMENT`.
  - `body`: a `🏭 Dark Factory Code Review` header + a summary table + any findings that
    could **not** be anchored to a changed line (fail-soft demotion).
  - `comments[]`: one entry `{path, line, side:"RIGHT", body}` per finding whose `path:line`
    falls inside the diff's changed hunks. Cap inline comments at `MAX_FINDINGS`; if exceeded,
    keep the highest-severity ones and note the count dropped in the review body.
  - Validate each `path:line` against the changed hunks before including it; lines outside the
    diff are demoted to the review body (GitHub rejects review comments off-diff).

- **Phase 6 — BLOCK or PASS.**
  - **Blockers present** → post a "Code Review — Blocked" issue comment listing the blocking
    findings, move the issue to **Blocked** (project board, same field/option IDs as
    conformance Phase 5), add `needs-discussion`, write `STATUS: BLOCKED` to `review.md`,
    `exit 1` (halts `status-in-review`).
  - **No blockers** → write `STATUS: PASS` to `review.md`, `exit 0`.

`review.md` schema:
```
STATUS: PASS | BLOCKED | SKIPPED | ERROR
BLOCKERS: <count>
ADVISORY: <count>
THRESHOLD: <critical|high|medium|low>
---
<full reviewer dialogue / findings table>
```

### 3. Reviewer prompt (`.claude/skills/refinement/code-review-reviewer-prompt.md`) — NEW

Derived from the philosophy of the existing `/code-review` and `/security-review` skills.
Read from the **clone path** (not the baked `/opt/refinement-skills/`) so it goes live on
commit+push without a `docker compose build`. (It is *also* baked via the existing
`COPY .claude/skills/refinement/ /opt/refinement-skills/` Dockerfile line, so parity is
preserved; the command simply prefers the clone copy.)

Output format (parseable markdown, like the conformance reviewer — the command parses it, not
JSON schema):

```
## Code Review

| # | Severity | Category | Location | Finding |
|---|----------|----------|----------|---------|
| 1 | high | security | backend/app/routers/x.py:42 | <one-line> |
| 2 | low | naming | frontend/src/foo.ts:88 | <one-line> |

### Findings
- [critical|high|medium|low] <category> — <path>:<line> — <description + suggested fix>

(If there are no findings, write: No findings.)
```

- **Severities:** `critical`, `high`, `medium`, `low`.
- **Categories:** `security`, `correctness`, `edge-case`, `naming`, `maintainability`.
- **Blocking rubric (guidance to the reviewer):** `critical`/`high` = security
  vulnerabilities, auth bypass, data loss, injection, or correctness bugs that produce wrong
  results / crashes / corrupted state. `medium`/`low` = recoverable edge cases, naming,
  readability, missing-test suggestions.
- Each finding **must** include `path:line` so the command can anchor it. Findings without a
  reliable location go to the review-body summary.

### 4. Config block (`.claude/skills/refinement/config.yaml`) — NEW

```yaml
code_review:
  enabled: true
  block_threshold: high     # findings at this severity or above block (critical|high|medium|low)
  fail_open: true           # reviewer error / unparseable output → advisory, never block
  max_findings: 50          # cap inline comments to avoid spam (log if exceeded)
```

`block_threshold: high` means `critical` + `high` block; lowering to `critical` later makes
only `critical` block. `enabled: false` is the kill-switch (skips the whole stage).

### 5. `report` node edit (`.archon/workflows/archon-dark-factory.yaml`)

Add a `### Code Review` section to the existing `report` issue-comment, reading `review.md`
(status + blocker/advisory counts + a link to the PR review). This is the only edit to an
existing node body besides the graph wiring.

## Data Flow

```
push-and-pr ──(PR_NUM)──▶ code-review
                              │
            git diff main...HEAD (pre-triaged, ≤1000 lines)
                              │
                              ▼
                 code-reviewer subagent (Opus 4.8)
                              │  structured findings (severity, category, path:line)
                              ▼
                   parse + split by block_threshold
                    ┌─────────┴──────────┐
            blockers (crit/high)     advisory (med/low)
                    │                     │
        block path (Phase 6)     single PR review, inline comments (Phase 5)
        - blocked issue comment   - REQUEST_CHANGES if blockers, else COMMENT
        - issue → Blocked         - off-diff findings → review body
        - needs-discussion
        - review.md BLOCKED
        - exit 1 (halts board)
```

## Failure Modes

| Condition | Behavior |
|---|---|
| `code_review.enabled: false` | Stage skipped; `review.md` STATUS: SKIPPED; exit 0. |
| Empty diff after exclusions | Nothing to review; STATUS: PASS; exit 0. |
| Subagent error / timeout / unparseable | `fail_open: true` → advisory (STATUS: ERROR), never blocks. `fail_open: false` → blocker. |
| Finding line not in diff hunks | Demoted from inline comment to the review-body summary (fail-soft). |
| `> max_findings` findings | Keep highest-severity inline; note dropped count in review body. |
| `continue` re-run | Fresh review posted each run, prefixed `🏭 Dark Factory Code Review`; no stale-review dismissal in v1. |

## Files Touched

| File | Change |
|---|---|
| `.archon/commands/dark-factory-code-review.md` | **NEW** — the command (Phases 1–6). |
| `.claude/skills/refinement/code-review-reviewer-prompt.md` | **NEW** — reviewer prompt + output format. |
| `.archon/workflows/archon-dark-factory.yaml` | New `code-review` node; `status-in-review` + `report` `depends_on` add `code-review`; `report` body gains a Code Review section. |
| `.claude/skills/refinement/config.yaml` | **NEW** `code_review` block. |

No dark-factory image rebuild required (workflow, command, config, and the prompt are all
clone-read).

## Open Questions / Future Work

- Auto-fix reconcile loop for high-severity findings (deferred — would re-push to the PR
  branch, mirroring conformance Phase 3.5).
- Reviewing `resolve` runs.
- Dismissing prior factory reviews on `continue` to avoid stacked reviews.
- Tuning `block_threshold` after observing real false-positive rates.
