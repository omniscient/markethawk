# Epic Autopilot — broaden reach (drain the backlog, start the next epic)

**Status:** design
**Date:** 2026-06-21
**Epic:** #548 (Dark Factory platform — maintenance, telemetry)
**Builds on:** `2026-06-20-epic-autopilot-design.md` (the starved-only self-unlock reviewer)
**Sibling spec:** `2026-06-21-main-red-autofix-design.md` (separate feature; implement A first)
**Build constraint:** Modifies the scheduler/factory itself (a "factory self-edit"), so it
must be **human-implemented**, never auto-refined/implemented by the factory. Edits to
`scheduler.sh` / `factory_core/` are **baked** — they need
`docker compose build backlog-scheduler` + `up --force-recreate` to take effect.

## Problem

Epic Autopilot shipped (#571) but in practice advances nothing. Observed 2026-06-21:
`backlog=87 refined=4 in_progress=4 in_review=1`, free slots everywhere, yet every cycle
logs `autopilot=no_candidates`. Tracing the funnel against the live board:

1. **Candidate source is too narrow.** `fetch_candidates()` only returns OPEN sub-issues of
   *in-progress* epics that carry a `spec-pending-review` / `plan-pending-review` label. It
   cannot see Backlog, Ready, or Refined work. The 6 "Ready" items are all **epics**
   (#373, #483, #438, #448, #449, #450), which nobody dispatches — so there is committed,
   prioritised work sitting idle that autopilot structurally cannot reach.
2. **Within its pool, every candidate is dropped** by one of: size-L above-ceiling
   (the meaty data-quality children #492/#494/#495/#499/#500), `needs-discussion`,
   trading/auth hard-exclude (correct), factory-self hard-exclude (correct),
   **undeclared-scope fail-closed** (over-aggressive), or a permanent cached `HOLD`.

Three of those drops are *accidental* (size-L, undeclared-scope, stale-HOLD); the rest are
intentional safety. We want autopilot to (a) stop the accidental drops, (b) advance size-L
children, and (c) when its existing pool is dry, **start the next epic** itself.

## Decision

Three changes to the existing module + scheduler + factory ceiling. The starved-only
trigger, main-green-only guard, Opus low-risk+confidence gate, `no-autopilot` opt-out,
daily cap, kill-switch, reversibility, and comment+notify-every-action invariants are all
**unchanged**.

### 1. Soft over-drops (Stage B, `epic_autopilot.py`)

- **Undeclared scope is no longer a hard drop.** Today `hard_excluded()` returns
  `(True, "undeclared-scope")` whenever `extract_target_paths()` finds no path-like tokens.
  Change: undeclared scope passes through to Opus as an explicit **concern** in the review
  prompt ("declared file scope: none — treat trading/auth/factory risk as possible"). The
  fail-closed hard-drop is retained **only** when trading/auth keywords actually appear in
  the title/body (`trading|order|ibkr|auth|login|jwt|session|rbac|token`), or when a
  declared path matches `exclude_paths`. Opus still defaults to HOLD when uncertain, so the
  envelope holds; we just stop discarding safe-but-pathless specs before review.
- **Cached HOLD gets a TTL.** `record_verdict()` stamps a `ts`; `cached_verdict()` returns
  the cached HOLD only if `now - ts < hold_ttl_hours` (default 24h) **and** the spec hash
  still matches. After the TTL, the ticket is re-reviewed (spec may have been edited, or the
  earlier HOLD was a one-off). ADVANCE remains terminal (label present ⇒ not a candidate).

### 2. Size ceiling → L (autopilot + factory)

- **Autopilot:** `is_eligible()` currently drops `size in (L, XL)`. Change to drop `XL` only
  (L becomes eligible). The M+keyword ceiling check is removed for autopilot — Opus weighs
  blast radius directly.
- **Factory implement ceiling (#339, global):** raise the dispatch ceiling so **L is below
  ceiling**. `is_above_ceiling()` in `scheduler.sh` classifies `size: L` as above-ceiling
  today; the change makes only `XL` (and M-with-keyword, if we keep that) above-ceiling, via
  the `.dispatch_ceiling.*` config. This is a **global** behaviour change: it affects the
  Priority-2 park gate (`scheduler.sh:957`) and the timer-based advance (`:341`) for **all**
  tickets, human-created included — not just autopilot's. Called out explicitly as an
  accepted factory-self change.

### 3. Broaden candidate source + epic-starter (`epic_autopilot.py`)

`fetch_candidates()` keeps returning gated children of in-progress epics (advance those
first — finish what's started). When that pool yields no candidate, a new
**`pick_next_epic()`** stage runs:

- Enumerate epics whose board Status is **Ready** (unstarted).
- **Skip hard-excluded epics**: security/auth/trading/factory-self by label or title
  keyword (e.g. #373 security is skipped; the next eligible epic is chosen).
- **Order by priority:** `priority:` label (`must-have` before `should-have`), then board
  order / issue age as a tiebreak.
- **Promote & delegate** the chosen epic (one per starved cycle):
  - move its board Status `Ready → In progress`,
  - add `ready-for-agent` to its OPEN children (so the normal Priority-5 refiner picks them
    up), and
  - post a comment + notification ("🤖 Epic Autopilot — starting epic #N «title»").
- Autopilot then **sleeps**: promoting fills the pipeline, so the next cycle isn't starved.
  No Opus review is needed to *start* an epic (promotion is fully reversible — demote +
  remove labels); Opus review still gates each **child** advance as today.

### Control flow (`scheduler.sh`, Priority 6)

Unchanged trigger — still `[ -z "$DISPATCHED" ] && [ "$MAIN_IS_RED" = "false" ] &&
[ "$EPIC_AUTOPILOT_ENABLED" = "true" ]`. The module now has two internal outcomes beyond
today's: `autopilot=epic_started epic=#N`. The scheduler maps `advanced`/`epic_started` to a
non-empty `DISPATCHED`.

## Module shape (`dark-factory/scripts/factory_core/epic_autopilot.py`)

Pure-core + injected-IO pattern is preserved. New/changed pure functions (all unit-tested,
no IO):

- `hard_excluded(c, exclude_paths)` → drop only on keyword/path match; undeclared scope
  returns `(False, "undeclared-scope")` and sets a `scope_undeclared` flag on the candidate.
- `is_eligible(...)` → `XL` ceiling only.
- `cached_verdict(state, issue, hash, now, ttl)` / `record_verdict(..., now)` → TTL-aware.
- `pick_next_epic(epics)` → pure selector: takes `[{number, title, labels, priority,
  board_order, status}]`, returns the chosen epic number or `None` (skips hard-excluded,
  orders by priority then board_order).
- `run_once(cfg, io, state, today, now)` → after the child-candidate pass yields nothing,
  call `io.fetch_ready_epics()` → `pick_next_epic()` → `io.promote_epic(n)` →
  comment/notify/record. New outcome dict `{"outcome": "epic_started", "issue": n}`.

New `LiveIO` adapters: `fetch_ready_epics()` (GraphQL: board items Status=Ready + `epic`
label + priority label + order), `promote_epic(n)` (set Status field → In progress; add
`ready-for-agent` to OPEN children via the existing sub-issue query).

## Config (`.claude/skills/refinement/config.yaml`, `epic_autopilot:` section)

```yaml
epic_autopilot:
  enabled: false                 # unchanged kill-switch (env EPIC_AUTOPILOT_ENABLED overrides)
  model: claude-opus-4-8
  daily_cap: 5                   # caps advances AND epic-starts combined per UTC day
  confidence_floor: 0.7
  hold_ttl_hours: 24             # NEW — re-review a cached HOLD after this long
  size_ceiling: XL               # NEW — drop only at/above this size (was effectively L)
  start_epics: true              # NEW — enable the epic-starter stage
  opt_out_label: no-autopilot
  hard_exclude_paths: [ ... ]    # unchanged
dispatch_ceiling:                # GLOBAL factory ceiling (#339) — raise to allow L
  enabled: true
  # size L is now below ceiling; only XL (and M+keyword, if retained) park
```

## Error handling / safety

- Fail-closed unchanged: parse errors → HOLD; trading/auth keyword hits → hard drop;
  declared exclude-path hits → hard drop.
- Epic promotion is reversible (demote Status + remove `ready-for-agent`); it triggers no
  code change and no PR by itself.
- Daily cap covers advances **and** epic-starts so the combined autonomous rate is bounded.
- Notifications fail-soft (logged, never block).

## Validation

- **Python unit tests** (mocked, alongside `test_epic_autopilot.py`): undeclared-scope now
  passes through + sets the concern flag; trading/auth keyword still hard-drops;
  HOLD-TTL expiry re-enables review; `size: L` eligible, `XL` dropped; `pick_next_epic`
  ordering + hard-exclude skip (security epic skipped, next chosen); `epic_started` outcome
  shape; daily-cap counts starts + advances.
- **Scheduler bash test** (`SCHEDULER_SOURCE_ONLY`): `is_above_ceiling` treats L as below
  ceiling under the new config; Priority-6 maps `epic_started` to a non-empty DISPATCHED.
- **Manual:** enable on the live scheduler (env already `true`); confirm it advances a size-L
  data-quality child end-to-end; empty the gated-child pool and confirm it promotes the
  highest-priority non-security Ready epic (skipping #373) and marks its children
  `ready-for-agent`; confirm comment + notification on both paths; force the daily cap.

## Accepted trade-offs

- Raising the **global** dispatch ceiling to L means human-created L tickets also dispatch
  autonomously — a deliberate throughput-for-oversight trade.
- Softening undeclared-scope leans harder on Opus's judgement (mitigated by the keyword
  fail-closed backstop + default-HOLD).
- Epic-starter advances board state without a heavyweight review; justified because
  promotion is fully reversible and every child still passes the Opus gate before any PR.
