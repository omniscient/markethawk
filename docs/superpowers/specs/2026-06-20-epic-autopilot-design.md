# Epic Autopilot — bounded self-unlock for a starved scheduler

**Status:** design
**Date:** 2026-06-20
**Epic:** #548 (Dark Factory platform — maintenance, telemetry)
**Depends on:** System Notifications Enabler (`2026-06-20-system-notifications-enabler-design.md`)
**Build constraint:** This modifies the scheduler/factory itself (a "factory self-edit"),
so it must be **human-implemented**, never auto-refined/implemented by the factory.

## Problem

The backlog scheduler dispatches nothing when the only Ready items are epics
(never dispatched, by design) and every refined child sits behind a human-review
gate (`spec-pending-review` / `plan-pending-review`). Observed 2026-06-20: 5 Ready
epics, 53 opted-in backlog specs all `spec-pending-review`, factory idle for hours
with free slots — every cycle `skip=nothing_to_do`. Unblocking required a human to
review a ticket and advance it (we did this for #402 by hand).

We want the scheduler to **self-unlock** when starved: review the safest refined
children of *in-progress* epics with a strong model and advance them autonomously,
within hard guardrails, with full transparency and escalation.

## Decision

A new **Priority 6: Epic Autopilot** runs at the tail of the poll loop, **only when
starved**, backed by a testable Python module. It reviews **one** candidate per cycle
with **Opus 4.8** and, on a low-risk verdict, adds `direct-to-pr` so the existing
grace-timer machinery carries the ticket spec→plan→implement→PR.

### Control flow (`scheduler.sh`)

```sh
# After Priority 5, at the loop tail:
if [ -z "$DISPATCHED" ] && [ "$MAIN_IS_RED" = "false" ] && [ "$EPIC_AUTOPILOT_ENABLED" = "true" ]; then
  python3 "$FACTORY_CORE_CLI" epic-autopilot --once
fi
```

`DISPATCHED` empty ⇒ no priority dispatched this cycle (and the capacity guard already
`continue`d if at capacity), so the autopilot only ever fills genuine idle time and
never runs while main is red. The scheduler logs the module's structured outcome:
`autopilot=advanced issue=#N` / `autopilot=hold issue=#N reason=…` /
`autopilot=no_candidates` / `autopilot=daily_cap_reached`.

### Module (`dark-factory/scripts/factory_core/epic_autopilot.py`)

Thin-adapter pattern (like `breaker.py` / `board.py`), invoked via `cli.py epic-autopilot`.

**Stage A — structural eligibility** (all must hold):
- OPEN `subIssue` of an **in-progress** epic (GraphQL `subIssues`)
- board status `spec-pending-review` or `plan-pending-review`
- not already `direct-to-pr`, `no-autopilot`, `needs-discussion`, or `epic`
- **below the dispatch ceiling** (size S, or M without a `dispatch_ceiling` keyword) —
  above-ceiling can't reach a PR autonomously, so skipping avoids wasted Opus calls
- no cached HOLD verdict for the current spec hash

**Stage B — hard exclusions** (any match ⇒ drop before Opus sees it; **fail-closed**):
- **Factory self-edits** — target paths under `dark-factory/`, `.archon/`, `scheduler.sh`,
  `factory_core/`, refinement skills
- **Automated trading** — live order/trading path (`app/services/trading*`,
  `app/tasks/trading.py`, IBKR order methods) or `trading` label + order keywords
- **AuthN/AuthZ** — `app/core/auth*`, `app/routers/auth*`, JWT/login/session/RBAC
  keywords. **Plain `security` label is allowed** (normal security fixes are fine);
  only auth-specific changes are excluded.

Detection reads the **declared target files** in the generated spec/plan plus
title/body keywords. If the spec does not clearly declare its file scope, the sensitive
categories (trading/auth) are treated as **possibly matched → excluded**. Size,
migrations, and blast-radius are **soft** inputs to Opus (not hard blocks), except
where `dispatch_ceiling` already parks them.

**Candidate pick:** one eligible candidate per cycle (oldest / highest `priority:` first).

**Context for the reviewer:** ticket #/title/body/labels/size, parent epic title, the
full generated spec (and plan if present), declared target files, and — *best-effort,
when codeindex data is available to the scheduler* — their blast scores. Blast scores
are a soft input; if absent, Opus judges from the spec/plan text alone.

**Reviewer call:** `claude -p --model claude-opus-4-8` (mirrors the existing
`classify_comments` `claude -p` pattern). Structured JSON output:
```json
{ "decision": "ADVANCE|HOLD", "risk": "low|medium|high",
  "confidence": 0.0-1.0, "reasons": [...], "concerns": [...] }
```
The prompt asks Opus to weigh spec completeness, test coverage, reversibility, blast
radius, and empty-branch/no-op risk; to re-check trading/auth/factory-self as a
redundant catch; and to **default to HOLD when uncertain**.

**Decision rule (belt-and-suspenders):** ADVANCE only if
`decision == ADVANCE` **and** `risk == low` **and** `confidence >= confidence_floor`.
Anything else, or any parse error, → **HOLD** (fail-closed, mirroring
`classify_comments`→SKIP and `code_review.fail_open`).

**Actions:**
- **ADVANCE** → add `direct-to-pr`; post a verdict comment (reasons + concerns,
  footer `Posted by MarketHawk Epic Autopilot`); send the advance notification.
  *No new dispatch logic* — the existing P4/P5 grace-timer path carries it onward.
  (Uses the `direct-to-pr` grace path, **not** a manual remove-label-then-board-move,
  which avoids the re-plan race seen when advancing #402 by hand.)
- **HOLD** → post a one-time "parked by autopilot" comment; cache the verdict.

**Idempotency / cost:** verdict cache on the `scheduler_state` volume keyed by
`issue → {spec_hash, verdict}`. HOLD is not re-reviewed until the spec is regenerated
(hash changes); ADVANCE is terminal (label present → no longer a candidate). ≤1 Opus
call per cycle; ≤1 per ticket per spec revision.

**Pacing & backstop:** one advance per starved cycle (advancing fills a slot → next
cycle isn't starved → autopilot sleeps). A **daily cap** (`daily_cap`, default 5) hard-
limits autonomous advances per UTC day, tracked in the state file, reset at midnight.

### Notifications (via the System Notifications Enabler endpoint)

The module POSTs to `http://backend:8000/api/alerts/system` (scheduler is on
`stockscanner-network`) with `X-Internal-Token`. All three go to **email + browser
push**. Notification failure is fail-soft (logged, never blocks autopilot):

1. **Advancing** *(info, per advance)* — "🤖 Autopilot advancing #N «title» — risk=low:
   `<reason>`."
2. **Daily cap reached** *(warning)* — "⚠️ Autopilot hit its daily cap (N); autonomous
   advancement paused until UTC reset — review the backlog."
3. **Starved but stuck** *(warning, throttled 1×/day via `dedupe_key`)* — factory idle
   **and** zero eligible candidates: "⚠️ Factory idle and autopilot has nothing safe to
   advance — human input needed."

### Config (new `epic_autopilot:` section in `.claude/skills/refinement/config.yaml`)

```yaml
epic_autopilot:
  enabled: false              # kill-switch — ship OFF, enable after validation. env: EPIC_AUTOPILOT_ENABLED
  model: claude-opus-4-8
  daily_cap: 5                # max autonomous advances / UTC day
  confidence_floor: 0.7       # min Opus confidence to ADVANCE
  opt_out_label: no-autopilot
  hard_exclude_paths:         # factory-self / trading / auth — fail-closed
    - "dark-factory/"
    - ".archon/"
    - "app/services/trading"
    - "app/tasks/trading.py"
    - "app/core/auth"
    - "app/routers/auth"
```
Loaded via the existing `read_config` knob pattern (env overrides logged).

## Guardrails summary

Starved-only trigger · hard-rule envelope (fail-closed) · Opus low-risk + confidence
threshold · `no-autopilot` opt-out · daily cap · kill-switch (ships OFF) · full
reversibility (remove `direct-to-pr`) · every action commented + notified · the
autopilot excludes edits to itself.

## Validation

- **Python unit tests** (alongside `test_breaker`/`test_board`, fully mocked — no live
  API): eligibility filter; each hard-exclusion category incl. fail-closed on undeclared
  scope and `security`-passes-through; decision rule (ADVANCE only on
  `ADVANCE`+`low`+`≥floor`); malformed Opus output → HOLD; verdict-cache invalidation by
  `spec_hash`; daily-cap enforcement + UTC reset; notification payload shape.
- **Scheduler bash test** (`SCHEDULER_SOURCE_ONLY`): P6 guard fires only when
  `DISPATCHED` empty + main not red + enabled.
- **Manual:** enable; watch it advance exactly one low-risk ticket end-to-end to a PR;
  verify ticket comment + `direct-to-pr` label + cache entry + advance email/push;
  force `daily_cap` and confirm the cap notification; empty the candidate pool and
  confirm the stuck notification.

## Accepted trade-offs

- One advance per cycle (throughput traded for caution + self-pacing).
- Opus per review is costly, but bounded by starved-only + daily cap + verdict cache.
- Reviews from spec/plan text (not a full agent reading the codebase) — cheaper and
  sufficient given the hard-rule envelope; a full-agent reviewer (factory intent) is a
  possible future upgrade.
- Human-implemented (factory self-edit) — cannot be dogfooded through the pipeline.
