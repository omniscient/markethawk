# Dark Factory — Configurable Concurrent Run Limit

**Date:** 2026-06-11
**Status:** Approved

## Problem

The backlog scheduler serializes all dark-factory work: the guard in
`dark-factory/scheduler.sh` skips every dispatch cycle whenever *any*
`markethawk-dark-factory-run-*` container is running. Throughput is capped at
one ticket at a time, and the only way to change that is to edit a baked-in
script and rebuild the image. The existing `REFINE_WIP_LIMIT=2` is unreachable
in practice because this guard blocks at 1 total container first.

## Decision

Replace the hardcoded "any running container → skip" guard with an env-driven
limit on **total concurrent factory containers** (all run types: implement,
refine, plan, deconflict, close).

- New config var in `scheduler.sh`: `FACTORY_WIP_LIMIT="${FACTORY_WIP_LIMIT:-1}"`
- Guard becomes: `if [ "$FACTORY_RUNNING" -ge "$FACTORY_WIP_LIMIT" ]; then skip cycle`
- Committed default stays **1** (safe for the Claude Max 5h window).
- Local value **2** set in `.archon/.env` (gitignored), which is already the
  scheduler's `env_file` — no compose change needed.

## How to change the limit later

1. Edit `FACTORY_WIP_LIMIT` in `.archon/.env`
2. `docker compose --profile scheduler up -d backlog-scheduler`
   (compose recreates the container on env change; no image rebuild)

## Changes

1. `dark-factory/scheduler.sh`
   - Add `FACTORY_WIP_LIMIT` to the configuration block.
   - Change the factory-concurrency guard to compare against the limit; update
     its comment (it currently cites "only one factory container at a time").
   - Update the orphaned-in-progress sweep comment: its claim "we only reach
     here when no factory container is running" no longer holds. The sweep
     remains correct because it already checks `is_issue_running` per issue.
   - Add `factory_running=${FACTORY_RUNNING}/${FACTORY_WIP_LIMIT}` to the
     per-cycle summary log line for observability.
2. `dark-factory/entrypoint.sh` *(discovered during live validation)* — the
   entrypoint has its own single-run mutex ("Another dark factory container is
   already running") that vetoed scheduler dispatches into the second slot.
   It now reads `FACTORY_WIP_LIMIT` (same default 1) and aborts only when the
   count of *other* run containers is `>= limit`. The var reaches dispatched
   containers via the service `env_file` (the scheduler's startup-provisioned
   copy of `.archon/.env`).
3. `.archon/.env` (local only, not committed): `FACTORY_WIP_LIMIT=2`

No changes to `docker-compose.yml`, retry/circuit-breaker state, or board
WIP-limit parsing.

## Behaviour under concurrency 2

- One dispatch per poll cycle is unchanged, so the second run starts on the
  next 60s poll — a natural stagger.
- `REFINE_WIP_LIMIT=2` becomes reachable (e.g. 1 implement + 1 refine, or
  2 refines).
- Per-issue duplicate-dispatch prevention (`is_issue_running`) is unchanged and
  still prevents two runs on the same ticket.

## Accepted trade-offs

- **Claude Max burn rate roughly doubles** while two runs are active; past runs
  have exhausted the 5h window. Mitigation: dial `.archon/.env` back to 1.
- **Host load**: two per-issue preview stacks may run simultaneously.
- **More deconflict runs**: two PRs branched off the same main conflict more
  often; the existing conflict-resolution pipeline handles this.

## Validation

1. Rebuild + recreate: `docker compose --profile scheduler build backlog-scheduler`
   then `docker compose --profile scheduler up -d backlog-scheduler`.
2. Startup log shows the scheduler running; cycle summary lines include
   `factory_running=N/2`.
3. With two Ready/Backlog-eligible tickets, observe two
   `markethawk-dark-factory-run-*` containers within two poll cycles, and a
   `skip=factory_running` line only once both slots are full.
