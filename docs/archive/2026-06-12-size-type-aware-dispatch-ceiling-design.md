# Size/Type-Aware Dispatch Ceiling in the Scheduler

**Date:** 2026-06-12
**Issue:** #339
**Depends on:** #331 (Factory Scorecard — closed)
**Status:** Spec

---

## Problem

The scheduler dispatches every Ready ticket identically regardless of size or
task type. Published research shows agent success rates vary ~30 points by task
type (chores merge at 84%, perf work at 55% — MSR '26 / arXiv 2602.08915) and
collapse above a size threshold (METR time-horizon data). Dispatching L-size or
architectural/migration/perf tickets to autonomous implement burns 5-hour Max
windows on work the factory predictably fails.

---

## Requirements

1. The scheduler classifies every Ready ticket before dispatch: **below ceiling**
   (S), **at ceiling** (M), or **above ceiling** (L / keyword-escalated M).
2. Above-ceiling tickets are moved to Blocked with a new `above-ceiling` label,
   never auto-dispatched to implement.
3. At-ceiling (M) tickets with `direct-to-pr` lose the `plan-pending-review`
   grace-window auto-advance; they require explicit human plan approval.
4. Below-ceiling (S) tickets: no change to current behaviour (both spec and plan
   grace-windows apply, `direct-to-pr` fully autonomous).
5. Policy constants live in `scheduler.sh` as env-var defaults (consistent with
   `SKIP_LABELS`, `FACTORY_WIP_LIMIT`, etc.); #338 consolidates them later.
6. Ceiling rationale and revisit date documented; a quarterly revisit issue filed.

---

## Architecture / Approach

### Classification

Two signals combine, with escalation only (the heuristic never demotes):

| Size label | + keyword match? | Tier |
|------------|-----------------|------|
| `size: S` or absent | — | Below ceiling |
| `size: M` | No | At ceiling |
| `size: M` | Yes (title contains keyword) | Above ceiling |
| `size: L` | — | Above ceiling (always) |

**Keywords** (`ABOVE_CEILING_KEYWORDS` env var):
`migration|migrate|performance|perf|architectur|refactor`

These are the three task types the issue names — perf, architectural, migrations
— expressed as grep-able title substrings. A keyword match on an M-size ticket
is the only escalation path; L is unconditionally above-ceiling.

### New constants in `scheduler.sh`

```bash
# Dispatch ceiling policy (see docs/superpowers/specs/2026-06-12-*.md; revisit 2026-09-12)
DISPATCH_CEILING_ENABLED="${DISPATCH_CEILING_ENABLED:-true}"
ABOVE_CEILING_LABEL="${ABOVE_CEILING_LABEL:-above-ceiling}"
ABOVE_CEILING_KEYWORDS="${ABOVE_CEILING_KEYWORDS:-migration|migrate|performance|perf|architectur|refactor}"
```

`DISPATCH_CEILING_ENABLED` is a kill-switch: set to `false` in `.archon/.env` to
restore the old flat-dispatch behaviour without code changes.

### New helper functions

```bash
# Returns "S", "M", "L", or "" from the item's labels
get_size_label() {
  echo "$1" | jq -r '.labels[]?' 2>/dev/null | grep -oi 'size: [SML]' | awk '{print $2}' | head -1
}

# True (returns 0) if item is at or above the dispatch ceiling
is_above_ceiling() {
  local item="$1" title size
  title=$(echo "$item" | jq -r '.content.title // ""' 2>/dev/null)
  size=$(get_size_label "$item")
  case "$size" in
    L) return 0 ;;
    M) echo "$title" | grep -qiE "${ABOVE_CEILING_KEYWORDS}" && return 0 || return 1 ;;
    *) return 1 ;;
  esac
}

# True if item carries the above-ceiling label (board-fetch snapshot)
has_above_ceiling_label() {
  echo "$1" | jq -r '.labels[]?' 2>/dev/null | grep -qi "^${ABOVE_CEILING_LABEL}$"
}

# True if item is S-size or has no size label
is_below_ceiling() {
  local size
  size=$(get_size_label "$1")
  case "$size" in S|"") return 0 ;; *) return 1 ;; esac
}
```

### Changes to the dispatch loops

**Priority 2 — Ready items**

Before the `dispatch "Fix issue #${ISSUE}"` call, insert a ceiling gate:

```bash
if [ "${DISPATCH_CEILING_ENABLED:-true}" = "true" ] && is_above_ceiling "$item"; then
  if ! has_above_ceiling_label "$item"; then
    echo "[...] ceiling_gate issue=#${ISSUE} action=above_ceiling_blocked"
    gh issue edit "$ISSUE" --repo "${OWNER}/markethawk" \
      --add-label "$ABOVE_CEILING_LABEL" 2>/dev/null || true
    set_board_status "$ISSUE" "$STATUS_BLOCKED" || true
    gh issue comment "$ISSUE" --repo "${OWNER}/markethawk" --body \
"## Scheduler — Above Dispatch Ceiling

This ticket has been classified as **above the autonomous dispatch ceiling** \
(size: L, or size: M with a perf/architectural/migration title keyword).

Spec and plan are complete. **A human must pair on implementation.**

To proceed:
1. Remove the \`$ABOVE_CEILING_LABEL\` label.
2. Dispatch manually:
   \`\`\`bash
   docker compose --profile factory run --rm dark-factory \"Fix issue #${ISSUE}\"
   \`\`\`
   Or implement directly in a local worktree.

---
*Posted by MarketHawk Backlog Scheduler*" 2>/dev/null || true
  fi
  continue
fi
```

`has_above_ceiling_label` guards against re-posting the comment and re-moving
the board on every cycle (the label persists across cycles via GitHub issue
labels returned by the next `fetch_board_items` call).

**Priority 3 — Blocked items**

Add a single guard at the top of the per-item block, immediately after the
`has_skip_label` check:

```bash
if has_above_ceiling_label "$item"; then continue; fi
```

This prevents the retry loop from auto-dispatching a "Fix" or "Continue" run
on an above-ceiling ticket that was moved to Blocked by the gate above, or by a
human who manually moved it there.

**`plan_advance_check()` — suppress grace-advance for M and L**

Inside `plan_advance_check`, immediately before the `has_direct_to_pr_label`
grace-window branch, add:

```bash
# Suppress timer-based advance for at/above-ceiling items: M and L require
# explicit human plan approval; the grace window applies only to S-size.
if [ "${DISPATCH_CEILING_ENABLED:-true}" = "true" ] && ! is_below_ceiling "$item"; then
  return 0
fi
```

The existing "new human feedback re-runs plan" path (the `has_new` block) is
NOT suppressed — human feedback always re-runs. Only the timer-based
auto-advance is blocked.

### What is NOT changed

- `spec_advance_check()` — spec grace-advance is unaffected for M tickets. The
  ceiling gates *implement dispatch*, not spec or plan generation. An M ticket's
  spec auto-advances to Refined; it then hits the human gate at `plan-pending-review`.
- Refine and plan dispatch (Priorities 4 and 5) — above-ceiling tickets are still
  refined and planned normally. `ABOVE_CEILING_LABEL` is NOT added to `SKIP_LABELS`.
- Circuit-breaker (`trip_to_blocked` / `needs-discussion`) — semantics unchanged.
  `above-ceiling` is a deliberate routing decision, not a failure state; the two
  label types must remain distinct.
- Board WIP limits and all other scheduler machinery — no changes.

---

## Alternatives Considered

### A: Size-only, no type heuristic

Drop the keyword escalation and enforce ceiling on size label alone. Simpler,
but fails the acceptance criterion ("policy keyed on existing `size:` labels
*plus* a small task-type heuristic"). Also misses the concrete failure mode the
issue names: an M-size db-migration ticket that is really above-ceiling.
Rejected.

### B: Introduce `task-type:` label taxonomy

Create `task-type: perf`, `task-type: architectural`, `task-type: migration`
labels and enforce ceiling from those. More precise but requires label tooling
changes and manual tagging discipline not currently in place. The issue says use
"existing" labels; new taxonomy is out of scope. Rejected for now; the keyword
heuristic is the lightweight proxy the issue describes, and a full taxonomy is a
natural future upgrade once the policy matures.

### C: Parse `config.yaml` for ceiling policy

Pre-empt #338 by making `scheduler.sh` read `config.yaml` with `yq`. Adds a
YAML-parsing dependency to a `set -euo pipefail` bash daemon; #338 owns that
consolidation. Env-var constants in `scheduler.sh` is the established pattern
and is what `config.yaml` already mirrors for other scheduler settings. Rejected.

### D: Move above-ceiling tickets back to Backlog

Would re-trigger refinement (`Refine issue #N`) on items that already have a
complete spec + plan, wasting a Max window and looping forever (size never
changes). Rejected; Blocked with `above-ceiling` label is the correct park state.

---

## Evidence

Threshold rationale drawn from:

- **MSR '26** (arXiv 2602.08915): task-stratified PR acceptance — chores 84%,
  perf/architectural work 55%. The ~30-point gap makes type-aware gating
  worthwhile.
- **METR time-horizon data**: success rate collapses above a task-size threshold;
  L-size tickets are in the regime where autonomous completion is below break-even.
- **Dark Factory Architecture Review 2026-06-11** (`docs/dark-factory-architecture-review-2026-06-11.html`),
  candidate **C9**: specifically recommends this ceiling as a measurable,
  revisitable policy rather than a guessed constant.

---

## Revisit

**First revisit:** 2026-09-12 (quarterly).
**Filed as:** GitHub issue "Revisit dispatch ceiling (C9) — re-measure success-by-size/type".
**Primary trigger:** Factory Scorecard (#331) producing success-by-S/M/L numbers
over a full quarter — that data drives any threshold adjustment. The date is a
time-boxed backstop if the scorecard data doesn't converge.

To adjust the ceiling without a code change, update `.archon/.env`:
```bash
ABOVE_CEILING_KEYWORDS="migration|migrate|performance|perf|architectur|refactor"
DISPATCH_CEILING_ENABLED=false   # kill-switch
```

---

## Open Questions (non-blocking)

1. **Keyword false-positive rate** — "refactor" may catch reasonable M-size
   cleanups that the factory handles fine. If false positives accumulate, narrow
   the keyword list (e.g. remove "refactor") in `.archon/.env` before the revisit.
2. **Unsize-labelled tickets** — treated as S (below ceiling). If unlabelled
   L-size tickets accumulate, triage policy should require the `size:` label on
   every ticket before it reaches Ready.
3. **Scorecard integration** — once #331 produces per-bucket success rates, the
   ceiling thresholds can be moved from keyword heuristics to data-driven cutoffs.
   At that point, #338's config consolidation and this revisit should land together.

---

## Implementation Checklist

- [ ] Add `DISPATCH_CEILING_ENABLED`, `ABOVE_CEILING_LABEL`, `ABOVE_CEILING_KEYWORDS` constants to `scheduler.sh`
- [ ] Add `get_size_label`, `is_above_ceiling`, `has_above_ceiling_label`, `is_below_ceiling` helpers
- [ ] Priority 2 (Ready) ceiling gate: move above-ceiling → Blocked + label + comment
- [ ] Priority 3 (Blocked-retry): skip `has_above_ceiling_label` items
- [ ] `plan_advance_check()`: suppress grace-advance for non-below-ceiling items
- [ ] Mirror new constants in `config.yaml` as doc-only entries (matching existing pattern)
- [ ] File revisit issue for 2026-09-12
- [ ] Inline comment in `scheduler.sh` constants block citing spec path and revisit date

---

*Spec generated by MarketHawk Refinement Pipeline — 2026-06-12*
