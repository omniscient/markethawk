# Auto-Refinement Pipeline Design

**Date:** 2026-05-13

## Overview

A multi-agent pipeline that automatically refines raw GitHub issues into reviewed specs and implementation plans. Two AI agents collaborate — a brainstormer orchestrator that drives requirements discovery, and a product-owner subagent that answers clarifying questions using issue context, codebase patterns, and domain documentation. The pipeline integrates into the existing backlog scheduler as a new tier in the priority waterfall.

## Architecture

### Agent Model: Orchestrator + Stateless Subagents

The pipeline uses a single orchestrator (brainstormer role) that maintains conversational state across the refinement session. For each clarifying question, it spawns a stateless product-owner subagent via the Claude Code Agent tool. This asymmetry — stateful orchestrator, stateless responders — maps naturally to the problem: the brainstormer needs an evolving understanding of the feature, but each product-owner answer is independent.

```
Orchestrator (brainstormer):
  ├─ Reads issue, codebase, docs
  ├─ Formulates question 1
  │   └─ Agent("product-owner") → answer 1
  ├─ Formulates question 2
  │   └─ Agent("product-owner") → answer 2
  ├─ ... (until converged)
  ├─ Proposes 2-3 approaches, selects best
  ├─ Writes spec
  ├─ Self-reviews spec
  └─ Posts to issue, labels spec-pending-review
```

After spec approval, a second stage triggers:

```
Orchestrator (plan writer):
  ├─ Reads approved spec
  ├─ Writes implementation plan (writing-plans skill logic)
  ├─ Spawns architect subagent for validation
  │   └─ Agent("architect") → approval or issues
  ├─ Fixes issues if any, re-submits
  └─ Commits plan, moves issue to Ready
```

### Trigger Mechanisms

**Manual:** Direct invocation via the dark factory container:
```bash
docker compose --profile factory run --rm dark-factory "Refine issue #12"
```

**Scheduled:** A new tier in the existing `scheduler.sh` priority waterfall. Scans for Backlog items that qualify for refinement on each polling cycle.

### Pipeline Phases

The pipeline has two distinct phases, separated by a human approval gate:

**Phase 1: Spec Generation (Backlog → spec-pending-review)**

Triggered when an issue is in the Backlog column without exclusion labels.

1. **Parse & fetch** — Extract issue number and intent. Fetch issue data via `gh issue view`.

2. **Pre-flight checks** — Skip if:
   - Issue has `spec-pending-review` label (already processed)
   - Issue has `needs-discussion` label (waiting for human input)
   - Issue has `epic` label (needs manual decomposition)
   - Issue body is empty or trivially short (< 20 chars) — add `needs-discussion` label with a comment requesting more detail

3. **Context assembly** — Build a context package (assembled once, passed to every subagent):
   - Issue content: title, body, labels, comments
   - CLAUDE.md: tech stack, architecture, conventions
   - ARCHITECTURE.md: service topology, module map
   - Relevant existing code discovered by exploring the area the issue touches

4. **Question loop** — The orchestrator formulates clarifying questions one at a time. For each question, it spawns a product-owner subagent with:
   - The product-owner prompt (read from `product-owner-prompt.md`)
   - The context package
   - The full Q&A history so far
   - The current question

   The product-owner subagent reads the codebase and docs as needed. It returns either a concrete answer or `UNCERTAIN: <reason>`.

   If `UNCERTAIN` is returned, the orchestrator:
   - Posts a comment on the issue with the specific question and context gathered so far
   - Adds `needs-discussion` label
   - Exits the pipeline

   The orchestrator decides when it has enough information to proceed — no fixed question cap.

5. **Approach selection** — The orchestrator proposes 2-3 approaches internally, evaluates trade-offs against the Q&A answers and codebase patterns, and selects the best. Reasoning is captured in an "Alternatives Considered" section of the spec.

6. **Spec writing** — Output follows the existing spec format in `Docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`. Contents:
   - Problem statement (from issue)
   - Requirements (distilled from Q&A)
   - Architecture / approach
   - Alternatives considered
   - Open questions (non-blocking)
   - Assumptions made (flagged explicitly)

7. **Self-review** — Placeholder scan, internal consistency check, scope check, ambiguity check. Fixes inline.

8. **Publish** — Commits the spec to a `refine/issue-<N>` branch. Posts a summary comment on the issue with the spec content. Adds `spec-pending-review` label. Issue stays in Backlog.

**Human Approval Gate**

The issue sits in Backlog with `spec-pending-review` until the user acts:

- **Approve:** Remove `spec-pending-review` label and move issue to Refined. The scheduler detects the column change on the next cycle and triggers Phase 2.
- **Request changes:** Post a comment with feedback on the issue. The scheduler detects a new human comment (after the pipeline's report) on a `spec-pending-review` issue, removes the label via `gh issue edit --remove-label`, and re-dispatches the refinement pipeline with the feedback included in the context.
- **Reject:** Close the issue or add `needs-discussion`. No further automation.

For `needs-discussion` issues: when the user answers the question and removes the label, the scheduler picks the issue up again on the next cycle.

**Phase 2: Plan Generation (Refined → Ready)**

Triggered when the scheduler detects an issue in the Refined column.

1. **Plan writing** — The orchestrator reads the approved spec and produces a full implementation plan following writing-plans skill conventions. Output: `Docs/superpowers/plans/YYYY-MM-DD-<feature>.md` with bite-sized TDD tasks, exact file paths, and code blocks.

2. **Architect review** — A subagent with an architect persona validates the plan:
   - Does every spec requirement map to a task?
   - Are file paths and interfaces consistent across tasks?
   - Is the task decomposition appropriately scoped?
   - Does the plan follow codebase conventions?

   The architect prompt is loaded from `architect-prompt.md` (adjustable).

3. **Fix loop** — If the architect flags issues, the orchestrator fixes them and re-submits. Repeat until approved.

4. **Publish** — Commits the plan to the same `refine/issue-<N>` branch. Posts a summary comment on the issue. Moves the issue to Ready. The dark factory can now pick it up with a complete spec + plan.

## Scheduler Integration

### Updated Priority Waterfall

```
┌──────────────────────────────────────────────────┐
│                 Every 60 seconds                  │
├──────────────────────────────────────────────────┤
│ 0. BACKLOG items (NEW)                            │
│    For each (board order):                        │
│    - No skip labels? Not already running?         │
│    - Refine WIP < limit?                          │
│    → dispatch "Refine issue #N"                   │
│                                                   │
│ 1. REFINED items (NEW)                            │
│    For each (board order):                        │
│    - Not already running?                         │
│    → dispatch "Plan issue #N"                     │
│                                                   │
│ 2. IN REVIEW items                                │
│    (existing logic — classify comments)           │
│                                                   │
│ 3. BLOCKED items                                  │
│    (existing logic — retry failed issues)         │
│                                                   │
│ 4. READY items                                    │
│    (existing logic — dispatch dark factory)       │
│                                                   │
│ 5. Nothing to do → sleep 60s                      │
└──────────────────────────────────────────────────┘
```

### Concurrency

- Refinement containers count toward a separate WIP limit (configurable, default 2) so they don't starve the dark factory
- Each refinement run is checked via `docker ps` to prevent duplicate dispatches per issue
- Refinement is lightweight (no preview stack, no Docker-in-Docker) — safe to run as first priority

### Intent Routing

The dark factory's `parse-intent` node gains two new intents alongside `new`/`continue`/`close`:

| Intent | Trigger | Action |
|--------|---------|--------|
| `refine` | `"Refine issue #N"` | Run Phase 1 (spec generation) |
| `plan` | `"Plan issue #N"` | Run Phase 2 (plan generation) |
| `new` | `"Fix issue #N"` | Existing: implement from spec+plan |
| `continue` | `"Continue issue #N"` | Existing: iterate on feedback |
| `close` | `"Close issue #N"` | Existing: merge and tear down |

## File Layout

```
.claude/skills/refinement/
├── SKILL.md                    # Skill definition for manual invocation
├── product-owner-prompt.md     # Product owner persona (adjustable)
├── architect-prompt.md         # Architect reviewer persona (adjustable)
├── orchestrator-prompt.md      # Brainstormer/orchestrator instructions
└── config.yaml                 # Tunable parameters
```

### config.yaml

```yaml
refine:
  wip_limit: 2
  skip_labels:
    - needs-discussion
    - epic
    - spec-pending-review
  min_issue_body_length: 20

plan:
  auto_advance_to_ready: true
```

### Modified Existing Files

| File | Change |
|------|--------|
| `dark-factory/scheduler.sh` | Add Backlog and Refined tiers to waterfall |
| `dark-factory/Dockerfile` | Copy skill files into container image |
| `docker-compose.yml` | No changes needed (scheduler service already exists) |

### Output Locations

| Artifact | Path |
|----------|------|
| Specs | `Docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md` |
| Plans | `Docs/superpowers/plans/YYYY-MM-DD-<topic>.md` |
| Branch | `refine/issue-<N>` |

## Board Constants

| Constant | Value |
|----------|-------|
| Project ID | `PVT_kwHOAAFds84BWh4w` |
| Status Field ID | `PVTSSF_lAHOAAFds84BWh4wzhR1VaA` |
| Backlog | `f75ad846` |
| Refined | `0c79ebe5` |
| Ready | `61e4505c` |
| In Progress | `47fc9ee4` |
| In Review | `df73e18b` |
| Blocked | `93d87b2f` |
| Done | `98236657` |

## Failure Handling

### Refinement pipeline fails
The container exits with an error. The scheduler logs it and retries on the next cycle, up to `MAX_RETRIES` (3). After that, the issue is skipped and a warning is logged. Retry counter resets when the issue gets new human comments.

### Product owner returns UNCERTAIN
Not a failure — this is the designed abort path. The question is posted to the issue, `needs-discussion` is added, and the pipeline exits cleanly. The scheduler skips the issue until the label is removed.

### Architect rejects plan repeatedly
After 3 rejection cycles, the pipeline posts the latest plan + architect feedback as an issue comment, adds `needs-discussion`, and exits. Human intervention needed.

### Scheduler crashes
`restart: unless-stopped` handles recovery. The scheduler is stateless — reads board state fresh each cycle. Only retry counters are lost on restart.

## Assumptions

- The dark factory Docker image will be extended to support `refine` and `plan` intents (same image, new code paths)
- The product-owner subagent runs inside the same Claude Code session as the orchestrator (Agent tool, not a separate container)
- Issue bodies contain enough seed information (at minimum a title and a few sentences) for the brainstormer to start meaningful questions
- The existing `refine/issue-<N>` branch naming won't conflict with `feat/issue-<N>` branches used by the dark factory
