# Direct-to-PR Autonomous Flow Design

**Date:** 2026-06-03

## Overview

An opt-in, per-ticket mode that lets the dark factory carry a GitHub issue all the
way from `Backlog` to a draft PR with **a single required human review gate at the
end** — the PR itself. Today the pipeline already does spec → plan → implement →
draft-PR autonomously, but it stops for a human **board-move after the spec** and
**after the plan**, and the final merge requires an explicit `Close issue #N`
command. This design collapses those mid-flight human gates into
**grace-windowed auto-advances** and makes **PR approval the merge trigger** — but
only for tickets explicitly flagged with a new `direct-to-pr` label. Every ticket
without the flag keeps today's fully-gated behavior unchanged. The change is purely
additive.

## Motivation

The refinement pipeline was originally built with auto-advance (spec → plan → Ready
ran straight through; see `Docs/superpowers/specs/2026-05-13-auto-refinement-pipeline-design.md`).
Two human approval gates (`spec-pending-review`, `plan-pending-review` + manual
board moves) were later added deliberately, and the auto-advance code was removed
(`auto_advance_to_ready` in `.claude/skills/refinement/config.yaml` is now
vestigial — nothing reads it). Those gates make the pipeline *fail cheap*: a wrong
spec is caught before any code is written.

For trusted, well-scoped tickets that tradeoff is not worth the babysitting. This
design reintroduces straight-through flow as an **opt-in per-ticket choice**, while
preserving the gated path as the default and keeping all *automated* quality gates
as hard stops.

## Design Decisions

These were settled during brainstorming and define the behavior:

1. **Spec & plan checkpoints become async, non-blocking.** The spec and plan are
   still generated and posted to the ticket, but the pipeline auto-advances without
   waiting for a board move. A human *can* comment during a grace window to
   interrupt/redirect before code is written; nothing blocks indefinitely.
2. **The opt-in flag is a single label that implies entry.** A ticket carrying
   `direct-to-pr` is both admitted to the pipeline *and* run straight-through. It
   does **not** also need `ready-for-agent`. `ready-for-agent` continues to mean
   "enter the pipeline under the gated flow."
3. **Interrupt window = a configurable grace period per stage.** After the spec
   posts, the scheduler waits `SPEC_GRACE_MINUTES` before advancing to plan; after
   the plan posts, it waits `PLAN_GRACE_MINUTES` before advancing to implement. A
   human comment during the window reroutes (re-refine / re-plan) instead of
   advancing. A window of `0` means pure auto-flow with no pause.
4. **PR approval is the single end gate.** Approving the draft PR triggers the
   existing `Close` path (merge → delete branch → teardown preview → Done). A
   changes-requested review or comment reroutes to `Continue` (iterate on the same
   branch).
5. **Automated quality-check failures still block.** Architect plan-review,
   code-vs-spec conformance (`block_on_material`), and the 3-strike implementation
   retry continue to route genuine failures to `Blocked` + `needs-discussion`,
   exactly as today — for flagged tickets too. These are the safety net; the single
   end-gate applies to the *happy path*.
6. **Default behavior is untouched.** Every new behavior fires *only* when the
   ticket carries `direct-to-pr`. Tickets without it follow today's exact path.

## The New Lifecycle

State machine for a `direct-to-pr` ticket (board column + label). Anything not in
**bold** is existing behavior.

| Stage | Trigger / state | Action |
|-------|-----------------|--------|
| Entry | `Backlog`, label `direct-to-pr`, no spec yet | Scheduler dispatches `Refine issue #N` (label treated as an entry trigger alongside `ready-for-agent`) |
| Spec posted | `Backlog` + `spec-pending-review` + `direct-to-pr` | **Human comment since the pipeline marker → re-refine (existing feedback path). Else elapsed ≥ `SPEC_GRACE_MINUTES` → remove `spec-pending-review`, move to `Refined`. Else wait this cycle.** |
| Plan generation | `Refined` (no `plan-pending-review`) | Scheduler dispatches `Plan issue #N` (existing). Architect review still blocks on failure. |
| Plan posted | `Refined` + `plan-pending-review` + `direct-to-pr` | **Human comment since marker → re-plan. Else elapsed ≥ `PLAN_GRACE_MINUTES` → remove `plan-pending-review`, move to `Ready`. Else wait this cycle.** |
| Implementation | `Ready` | Scheduler dispatches `Fix issue #N` (existing). Conformance + 3-strike retry still block on failure. |
| Draft PR | `In Review` | Factory opened a draft PR (existing). |
| **End gate** | `In Review` + `direct-to-pr` | **Approved PR review → dispatch `Close issue #N` (merge + teardown + Done). Changes-requested / comment → `Continue issue #N`.** |

The grace logic keys off `(column, label)` pairs and reuses the timestamp of the
pipeline's marker comment (`"Posted by MarketHawk Refinement Pipeline"`) — the same
marker the scheduler already reads for feedback detection — to measure elapsed time
against `now` (UTC).

## Component Changes

### `dark-factory/scheduler.sh` (all new logic lives here)

The scheduler already polls every 60s, detects human comments after the marker
comment, and has board-column-move helpers — the new behavior is additive tiers and
guards, not new infrastructure.

- **`has_direct_to_pr_label`** helper — checks an item's labels for the flag.
- **Entry trigger** — the opt-in check that gates Backlog dispatch treats
  `direct-to-pr` as an admitting label alongside `ready-for-agent`.
- **Elapsed-minutes helper** — compute minutes since the marker comment's
  `createdAt` (ISO-8601, UTC) relative to `date -u`.
- **Spec auto-advance** (Backlog + `spec-pending-review` + flag): comment-since-marker
  → existing re-refine path; elapsed ≥ `SPEC_GRACE_MINUTES` → remove label + move to
  `Refined`; otherwise skip this cycle (still within window).
- **Plan auto-advance** (Refined + `plan-pending-review` + flag): symmetric —
  comment → re-plan; elapsed ≥ `PLAN_GRACE_MINUTES` → remove label + move to `Ready`;
  otherwise skip. (`plan-pending-review` is already a skip label, so the plan-dispatch
  tier will not re-plan while it waits.)
- **End-gate auto-merge** (In Review + flag): in addition to the existing
  comment-classify tier, read `gh pr view --json reviews`. An `APPROVED` review →
  dispatch `Close issue #N`. A changes-requested review → dispatch `Continue issue #N`.

### Configuration

New scheduler environment variables (defined near the existing `POLL_INTERVAL` /
`SKIP_LABELS` block in `scheduler.sh`), with defaults; mirrored in
`.claude/skills/refinement/config.yaml` for documentation:

- `DIRECT_TO_PR_LABEL` — default `direct-to-pr`.
- `SPEC_GRACE_MINUTES` — default `30`. `0` = advance on the next poll (pure auto-flow).
- `PLAN_GRACE_MINUTES` — default `30`. `0` = advance on the next poll.

The vestigial `plan.auto_advance_to_ready` key is superseded by this mechanism and
should be removed to avoid confusion.

### Commands (`.archon/commands/dark-factory-refine.md`, `dark-factory-plan.md`)

No control-flow change. One cosmetic addition: when the ticket carries
`direct-to-pr`, the posted spec/plan comment notes
"⏩ Auto-advancing in ~N min unless you comment" so the grace window is visible to
the human.

### Labels & Docs

- Create the `direct-to-pr` GitHub label on `omniscient/markethawk`.
- Document the flag and the straight-through mode in `docs/agents/triage-labels.md`
  (it is a workflow flag, not a triage role) and in the dark-factory docs.

## What Stays the Same

These fire for `direct-to-pr` tickets too — they are the retained safety net:

- **Architect plan-review** — unapprovable plan after 3 cycles → `Blocked` +
  `needs-discussion`.
- **Code-vs-spec conformance** — material divergence after `max_reconcile_cycles`
  with `block_on_material: true` → `Blocked` + `needs-discussion`.
- **3-strike implementation retry** circuit-breaker → `Blocked` + `needs-discussion`.
- **Red-CI guard** — an `In Review` ticket with failing CI is moved to `Blocked`
  before it can be approved, so an approval can never merge a red branch.
- **`needs-discussion` / `epic` skip labels** and **WIP limits** still suppress all
  dispatch, including for flagged tickets.

## Edge Cases

- **`SPEC_GRACE_MINUTES=0` / `PLAN_GRACE_MINUTES=0`** — flagged tickets advance on
  the next poll (~60s) with no deliberate pause. Valid "full trust" configuration.
- **Comment arrives during the grace window** — treated as feedback: the pending
  label is removed and the stage is re-dispatched (re-refine / re-plan); the window
  restarts when the new spec/plan is posted.
- **Comment arrives after auto-advance** — handled by the existing post-advance
  feedback/classify paths (re-plan if still in Refined, or `Continue` once in
  Review). The grace window only governs the pre-advance pause.
- **Flag added mid-flight** (e.g. a ticket already in `Refined` with
  `plan-pending-review`) — the next poll picks it up under the auto-advance rules
  from its current state; no special migration needed.
- **Both `direct-to-pr` and `ready-for-agent` present** — `direct-to-pr` wins
  (straight-through); the ticket is not double-dispatched.
- **Quality gate sends a flagged ticket to `Blocked`** — it stops there like any
  other ticket; resuming is the normal `needs-discussion` human path. The single
  end-gate is a happy-path guarantee, not a promise to never block on broken work.

## Testing

- **Scheduler unit/behavior tests** (bash-level, matching existing scheduler test
  patterns): elapsed-minutes calculation; spec auto-advance fires only after the
  window and only with the flag; plan auto-advance symmetric; comment-in-window
  reroutes instead of advancing; approved-review triggers `Close`;
  changes-requested triggers `Continue`.
- **Guard tests:** a non-flagged ticket never auto-advances (regression guard for
  default behavior); a flagged ticket with `needs-discussion` is still suppressed.
- **Manual end-to-end:** create a throwaway issue labelled `direct-to-pr` with
  `SPEC_GRACE_MINUTES=0`/`PLAN_GRACE_MINUTES=0` and confirm it flows Backlog →
  Refined → Ready → In Review → (approve) → Done without a human board move.

## Out of Scope (YAGNI)

- No per-stage *different* flags (one `direct-to-pr` label governs the whole flow).
- No change to the brainstorm/spec/plan/implement *content* generation — only how
  tickets advance between stages and how the PR resolves.
- No new UI; the flag is applied via GitHub labels like every other workflow label.
- No making the automated quality gates fail-open — they remain hard stops by
  explicit decision.
