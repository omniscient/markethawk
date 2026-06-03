# Dark Factory Scheduler — Universal Loop Circuit-Breaker — Design Spec

**Issue:** #160
**Date:** 2026-06-03
**Size:** M
**Status:** spec-pending-review

---

## Summary

Harden the dark-factory `backlog-scheduler` (`dark-factory/scheduler.sh`) so a stuck or failing dispatch can never spam the pipeline. Replace today's fragile, inconsistent safeguards with three changes:

1. **Durable retry state** — survives scheduler restarts.
2. **Crash-resilient dispatch** — a failed `docker compose run` is logged and skipped, never kills the daemon.
3. **One universal circuit-breaker** — after N attempts of the same `(issue, phase)`, the ticket moves to **Blocked**, consistently for refine / plan / implement.

Plus a trigger fix: refinement becomes **opt-in** (a label gates entry to refinement) rather than auto-refining every unlabelled Backlog issue.

## Background — the #159 incident

Creating issue #159 produced ~10 "Starting brainstorming and spec generation" dispatch comments in ~2 minutes. The retry circuit-breaker that *does* exist (`REFINE_MAX_RETRIES=3` → `needs-discussion`, `scheduler.sh:611`) never tripped. Diagnosis found three compounding root causes, each individually sufficient to cause the loop:

1. **Broken image pull.** `dispatch()` runs `docker compose run -d --rm dark-factory …`. Docker tried to pull `ghcr.io/omniscient/markethawk-dark-factory:latest`, the registry returned `denied`, and compose fell back to building the `ubuntu:24.04`-based image **inline inside the scheduler process**.
2. **Crash-prone dispatch.** `dispatch()` (`scheduler.sh:138-142`) is unguarded, and the script runs under `set -e`. A non-zero `docker compose run` exits the whole scheduler. `RestartPolicy=unless-stopped` restarts it — observed `RestartCount=10`, current `StartedAt=2026-06-03T12:59:44Z`, matching the ~10 dispatches.
3. **Non-durable retry state.** `STATE_FILE=/tmp/scheduler-state.json` (`scheduler.sh:8`) is in ephemeral `/tmp` and re-initialized to `{}` on each start (`scheduler.sh:40-41`). Every crash-restart reset the `${issue}:refine` counter to 0, so it never reached 3.

Net: dispatch → build/run fails → `set -e` kills scheduler → restart wipes counter → re-poll → re-dispatch, until a human applied a skip label that filtered #159 out *before* the crashing dispatch path.

## Current safeguard landscape (the inconsistency we're fixing)

| Dispatch path | Code | On repeated trouble |
|---|---|---|
| implement (`fix`/`continue`) | scheduler `:526`; run `on_failure` in `entrypoint.sh:246` | run failure → **Blocked** (board status) |
| refine | scheduler `:611` | retry-cap(3) → **`needs-discussion`** label |
| plan | scheduler `:550` | retry-cap(3) → **`needs-discussion`** label |
| *all* | `get_retry_count`/`increment_retry` on `STATE_FILE` | gated on the ephemeral `/tmp` counter + crash-prone dispatch |

Three different outcomes; all sitting on the same fragile foundation.

## Design decisions

| Decision | Choice | Rationale |
|---|---|---|
| Retry-state durability | Dedicated **named docker volume** mounted into the scheduler (not `/tmp`, not the repo bind) | Survives restarts; keeps scheduler state out of the source tree. |
| Daemon resilience | Per-iteration **error isolation**: guard `dispatch` + every `gh`/`docker` call so a failure logs, counts as an attempt, and `continue`s | A single failed dispatch must never exit the daemon. |
| Circuit-breaker | **One** `trip_to_blocked(issue, phase, reason)` helper, keyed on a durable `(issue:phase)` attempt counter, default threshold reusing `MAX_RETRIES`/`REFINE_MAX_RETRIES=3` | Uniform behaviour; Blocked is the single "human, look at this" signal you asked for. |
| Refinement entry | **Opt-in** label gate — only auto-refine Backlog items carrying `ready-for-agent` (existing triage label) | Removes the "new issue auto-refined during the labelling window" trigger entirely. |
| Image availability | Pull/build the image **once** (scheduler startup or a build step); dispatch with `--no-build` | A missing image fails fast and visibly instead of a multi-minute inline build that can crash the loop. |

## Components

### A. Durable retry state
- Move `STATE_FILE` to a path on a **named volume** (e.g. `scheduler-state:/var/lib/dark-factory`), set via env in the scheduler's compose service.
- Keep the `if [ ! -f "$STATE_FILE" ]` init guard (`scheduler.sh:40`) — with a durable store it now only initializes once, not on every restart.
- Counter keys stay `${issue}` (implement), `${issue}:refine`, `${issue}:plan` — see C for unification.

### B. Crash-resilient dispatch loop
- `dispatch()` (`scheduler.sh:138`) returns the `docker compose run` exit code; callers must handle non-zero: log, `increment_retry`, `continue` — never let it propagate to `set -e`.
- Audit the loop body for other unguarded `gh`/`jq`/`docker` calls that can exit the daemon under `set -e`; wrap each so a transient failure is logged and skipped (the board-fetch path at `:391` already models this).
- Consider a top-level `trap … ERR` that logs and resumes the poll loop rather than exiting, as a backstop.

### C. Universal circuit-breaker → Blocked
- New helper `trip_to_blocked(issue, phase, reason)`:
  1. set board status to **Blocked** (`STATUS_BLOCKED=93d87b2f`),
  2. add a skip label so the scheduler also filters it (`needs-discussion`),
  3. post one explanatory comment (which phase, attempt count, retry command),
  4. `reset_retry` for that key so a later manual re-trigger starts clean.
- Replace the three divergent cap-handlers (`:527` implement silent-skip, `:550` plan→needs-discussion, `:611` refine→needs-discussion) with calls to `trip_to_blocked` once `attempts >= THRESHOLD`.
- Align the **run side**: `entrypoint.sh on_failure` (`:226-268`) already Blocks on implement failure; extend it so refine/plan failures are consistent with the scheduler's circuit-breaker (Blocked, not just a comment), or document why the run side defers to the scheduler counter.

### D. Opt-in refinement gate
- In the Backlog loop (`scheduler.sh:583` onward), require an opt-in label (`ready-for-agent`) before dispatching `Refine issue #N`. Backlog items without it are left for triage.
- Preserve the existing `spec-pending-review` re-refine-on-feedback path (`:587-605`).
- Document the new gate in the triage docs (`docs/agents/triage-labels.md`).

### E. Image availability
- Investigate the GHCR `denied` pull (auth/scope on the scheduler's Docker context). Either fix the pull, or build the image once and dispatch with `--no-build`.
- This is the trigger that turned a recoverable failure into a crash loop; fixing it removes the inline-build-in-scheduler behaviour.

## Files touched

- `dark-factory/scheduler.sh` — durable `STATE_FILE`; guarded dispatch; `trip_to_blocked` helper; replace the three cap-handlers; opt-in Backlog gate.
- `dark-factory/entrypoint.sh` — align refine/plan `on_failure` with the unified Blocked behaviour.
- `docker-compose.yml` (factory/scheduler service) — named volume for scheduler state; `--no-build`/pre-pull wiring.
- `docs/agents/triage-labels.md` — document the `ready-for-agent` refine gate.

## Testing

- **Durable state:** write a counter, `docker restart backlog-scheduler`, confirm the counter persists.
- **Crash resilience:** force a dispatch to fail (e.g. bad image ref) and confirm the scheduler logs it, increments the counter, and keeps polling (no restart).
- **Circuit-breaker:** drive `(issue, phase)` attempts to the threshold and assert the ticket lands in **Blocked** with the comment — for each of refine, plan, implement.
- **Opt-in gate:** a Backlog issue without `ready-for-agent` is never dispatched; adding the label starts refinement.
- **#159 regression:** simulate an unlabelled new issue with a failing dispatch and confirm it trips to Blocked within N attempts instead of looping.

## Must verify during planning

1. The scheduler's Docker context auth for GHCR (`denied`) — is it a missing token/scope, and does `--no-build` need a guaranteed local image first?
2. Whether `Blocked` board items are ever re-dispatched by any loop (they should be terminal until a human acts) — confirm no priority section pulls from Blocked.
3. Exact `set -e` failure points in the loop body beyond `dispatch` (audit every unguarded external call).
4. That `ready-for-agent` is the right opt-in label vs introducing a dedicated `ready-to-refine` (check current triage-label usage).

## Out of scope

- Workflow DAG (`archon-dark-factory.yaml`) restructuring.
- Changes to how implement/preview/validate execute.
- The codeindex integration (#159) — independent.

## Next steps

- ✅ **Approve spec** — remove `spec-pending-review` (optionally add `spec-approved`). The issue is already in **Refined**, so the scheduler dispatches plan generation on its next tick.
- ✏️ **Request changes** — comment with feedback, then re-run `docker compose --profile factory run --rm dark-factory "Refine issue #160"`.
- ❓ **Pause** — add `needs-discussion`.
