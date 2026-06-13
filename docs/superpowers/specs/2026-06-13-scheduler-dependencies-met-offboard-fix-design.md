# Scheduler — Fix dependencies_met() Stranding on Closed Off-Board Deps

**Date:** 2026-06-13
**Issue:** #389
**Status:** Draft

## Problem

`dependencies_met()` in `dark-factory/scheduler.sh` resolves a `Depends on: #N` line by
looking up the dependency's board status via `board_items` (fetched as the first 50 project
board items). When the dependency is **closed but no longer visible on the board** — either
archived as routine hygiene or pushed outside the 50-item fetch window — `dep_status` comes
back empty, which `!= "Done"`, so the dependent issue is permanently stranded in Ready and
silently skipped every poll cycle.

Confirmed incident: issue #339 (Ready, `direct-to-pr`) was never dispatched. Its body
contained `Depends on: #331`; #331 was CLOSED but absent from the board. The scheduler
logged `skip=nothing_to_do` every cycle while #339 sat eligible.

This will recur for every issue whose dependency completes and is later archived — a routine
board hygiene action that the scheduler cannot avoid.

## Decision

Two-part fix, both in `dark-factory/scheduler.sh`:

### Part 1 — Off-board fallback in `dependencies_met()`

When a dependency is not found on the board (`dep_status` is empty), fall back to the
GitHub issue state via `gh issue view`:

```bash
if [ -z "$dep_status" ]; then
  local dep_state
  dep_state=$(gh issue view "$dep_num" --repo "${OWNER}/markethawk" --json state -q '.state' 2>/dev/null)
  if [ "$dep_state" = "CLOSED" ]; then
    echo "[$(date -u +%FT%TZ)] dep_gate issue=#${issue_num} dep=#${dep_num} resolved=closed_off_board"
    continue  # treat closed-off-board dep as met; advance to next dep
  fi
  echo "[$(date -u +%FT%TZ)] dep_gate issue=#${issue_num} blocked_by=#${dep_num} dep_status=off_board"
  return 1
fi
```

CLOSED (archived or manually closed) → met.  
OPEN, empty (gh failure), or any other state → unmet.

### Part 2 — Log line for on-board but non-Done deps

The existing `[ "$dep_status" != "Done" ]` branch currently returns 1 silently. Add a
log line before the return to satisfy the "unmet dependencies produce a log line" acceptance
criterion:

```bash
if [ "$dep_status" != "Done" ]; then
  echo "[$(date -u +%FT%TZ)] dep_gate issue=#${issue_num} blocked_by=#${dep_num} dep_status=${dep_status}"
  return 1
fi
```

**Log verbosity**: one line per blocking or fallback-resolved dep only. Normal on-board-Done
deps are silent (matches current zero-logging-on-success behavior).

## Changes

1. `dark-factory/scheduler.sh` — `dependencies_met()` function (lines 645–663):
   - After `dep_status=$(...)`, insert the off-board fallback block (Part 1) as an `if [ -z
     "$dep_status" ]` branch before the existing `!= "Done"` check.
   - Add a log line to the existing `!= "Done"` return-1 branch (Part 2).
   - The `OWNER` variable is already in scope (used at line 649 for the body fetch).

2. `dark-factory/tests/test_scheduler.sh` — new section **K: dependencies_met()**:
   - The `gh()` stub must branch on `--json body` vs `--json state` (and on issue number
     vs dep number) to return the correct payload per call.
   - Required test cases:
     - K1: No `Depends on:` in body → passes (return 0)
     - K2: Single dep on board as `Done` → passes
     - K3: Single dep on board as non-Done (`Ready`) → blocked (return 1); log contains `blocked_by=#<dep>`
     - K4: Dep off-board + CLOSED → passes via fallback; log contains `resolved=closed_off_board`
     - K5: Dep off-board + OPEN → blocked (return 1); log contains `blocked_by=#<dep>`
     - K6: Dep off-board + gh failure (empty state) → blocked (return 1)
     - K7: Two deps — first on-board Done, second off-board OPEN → blocked on second dep
     - K8: Two deps — one on-board Done, one off-board CLOSED → passes (both met)
     - K9: Body fetch fails → passes (return 0; pre-existing behaviour at line 649)

## Alternatives Considered

**A: Expand the board fetch window** (increase `items(first: 50)` to 100 or 200)  
→ Rejected. Doesn't solve the archival case and burns GraphQL rate-limit budget on every
poll cycle. The root cause is the off-board assumption, not the fetch size.

**B: Require deps to stay on the board until the downstream is dispatched**  
→ Rejected. Requires process enforcement on humans doing routine board hygiene.
Not reliable; the bug already happened once.

**C: Fall back to the GitHub issue state for all deps (skip board entirely)**  
→ Rejected. The board "Done" status is a deliberate gate — an issue can be OPEN and in
state "Done" on the board, or CLOSED without ever being moved to "Done". The board check
is the primary signal; the GH state fallback should only activate when the board has no
data.

## Assumptions

- `OWNER` is exported and in scope when `dependencies_met()` is called (confirmed — used at
  line 649 for the body fetch today).
- `gh issue view` for a dep issue number is reliable enough to use as a fallback (single
  API call, low failure rate; failures default to unmet which is the safe direction).
- The `dep_gate` log key is novel (not already emitted elsewhere in scheduler.sh) — grep
  confirms no existing uses.

## Open Questions

None blocking. The fix is self-contained to one function and its test section.

## Rebuild Note

`scheduler.sh` is baked into the dark-factory image. After merging:
```bash
docker compose build backlog-scheduler
docker compose --profile scheduler up -d --force-recreate backlog-scheduler
```
