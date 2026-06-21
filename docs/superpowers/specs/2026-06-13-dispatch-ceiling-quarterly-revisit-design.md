# Dispatch Ceiling Revisit — Design (issue #394 / recurring)

**Date**: 2026-06-13  
**Issue**: [#588](https://github.com/omniscient/markethawk/issues/588) — Revisit dispatch ceiling (C9) — re-measure success-by-size/type  
**Prior run**: [#394](https://github.com/omniscient/markethawk/issues/394) — Revisit dispatch ceiling (C9) — re-measure success-by-size/type

> **Note on naming:** this spec file is referenced by `.archon/commands/ceiling-revisit.md`
> and `scripts/ceiling_revisit.py` under the `dispatch-ceiling-quarterly-revisit` slug.
> The issue body cites a different nonexistent name (`2026-06-12-size-type-aware-dispatch-ceiling-design.md`).
> This file is canonical; the issue reference is stale. The cadence is now **weekly**
> (UNTIL + 7 days), not quarterly — see § Cadence below.

---

## Problem

The `is_above_ceiling()` gate in `dark-factory/scheduler.sh` blocks autonomous dispatch of
issues whose titles match `ABOVE_CEILING_KEYWORDS` (a pipe-delimited regex) plus an
unconditional L-size block. The policy was introduced in issue #339 to prevent the factory
from autonomously attempting scope classes with historically low merge rates.

Without periodic review, the keyword list can become either:
- **Too permissive**: missing emerging low-success patterns → wasted autonomous runs
- **Too restrictive**: keeping keywords whose matched PRs now succeed as well as the M baseline
  → unnecessarily blocking automatable work

This revisit closes the feedback loop: pull actual merge-rate data, apply evidence-based
decision rules, and update the keyword list (or L-bucket logic) if warranted.

---

## Dispatch Ceiling Policy (C9)

Defined in `dark-factory/scheduler.sh`, function `is_above_ceiling()` (~line 242):

| Size | Rule |
|------|------|
| S    | Never above ceiling (always dispatched) |
| M    | Above ceiling **iff** title matches `ABOVE_CEILING_KEYWORDS` regex |
| L    | Always above ceiling (parked for human pairing) |
| XL   | Always above ceiling (same as L) |

Above-ceiling items in the Refine/Plan stages receive an `above-ceiling` label and a
comment asking for human review. They do NOT advance autonomously.

Current default `ABOVE_CEILING_KEYWORDS` (from `config.yaml`):
```
migration|migrate|performance|perf|architectur|refactor
```

An `.archon/.env` override takes precedence over the scheduler's default when present.

---

## Decision Rules

Implemented in `scripts/ceiling_revisit.py`. The spec is authoritative; the script implements these rules.

### 1. Per-bucket triad

For each size bucket (S, M, L+XL — XL is merged into L for reporting):

```
n          = merged_clean + merged_with_edits + closed    # decided PRs only (open excluded)
rate       = (merged_clean + merged_with_edits) / n       # None if n=0
```

`n` excludes open/in-flight PRs because their outcome is not yet determined.

### 2. Keyword removal rule (M-size cohort)

For each keyword in `ABOVE_CEILING_KEYWORDS`:

```
cohort = M-size factory PRs whose title matches the keyword (case-insensitive)
n      = decided count in cohort
rate   = keyword cohort success rate
```

| Condition | Decision |
|-----------|----------|
| n < 5 | insufficient data — no change |
| rate ≥ M\_baseline | **remove** — keyword no longer discriminates from M average |
| rate < M\_baseline − 0.15 | **keep** — keyword identifies materially lower-success work |
| otherwise | ambiguous — leave unchanged |

**Why removal means "non-discriminative":** the ceiling is intended to block work
that succeeds *worse* than typical M work. When a keyword cohort succeeds *at least
as well* as the M baseline, the keyword provides no useful signal — it only blocks.

**Why only M-size PRs for keyword analysis:** S-size tickets are never blocked
(ceiling never fires for S), and L+XL are unconditionally above-ceiling. Keyword
discrimination is only relevant for the M bucket where the ceiling can fire.

### 3. Add-keyword candidates (inverse evidence)

Token-scan closed M-size PRs for word tokens (≥4 chars, n≥5 occurrences) not
already covered by existing keywords. Any qualifying token with `rate = 0.0`
(all closed) is flagged as an "add candidate." These are advisory — human review
required before adding to `ABOVE_CEILING_KEYWORDS`.

### 4. L-bucket rule

If `L+XL success rate > 70% at n≥5`: file a new code-change issue to revisit the
unconditional `L = always-above-ceiling` rule in `is_above_ceiling()`. This is a
scheduler code change (not just an env-var change) and requires human review.

---

## Implementation Procedure

All phases are implemented in `.archon/commands/ceiling-revisit.md`. The spec does
not duplicate them. A high-level summary:

1. **Fetch** — run `scripts/fetch_scorecard.py` to pull PR/commit data from GitHub
   into a `scorecard.json` file (by-size triads + PR list)
2. **Analyze** — run `scripts/ceiling_revisit.py` to apply §Decision Rules above
3. **Post** — comment the analysis report on the issue
4. **Keyword PR** — if `keywords_to_remove` is non-empty, write `.archon/.env` with
   the updated keyword list and open a PR (reviewer must merge to apply)
5. **L-bucket issue** — if L+XL triggers the >70% rule, file a code-change issue
6. **Next revisit** — unconditionally file the next weekly revisit issue
   (NEXT\_DATE = UNTIL + 7 days)

---

## Cadence

**Current cadence: weekly.** Each revisit issues files the next at `UNTIL + 7 days`.

The original design targeted quarterly (2026-09-12 backstop). Weekly was adopted
after the first revisit (#394) to keep the keyword list responsive to current data
rather than waiting a quarter for evidence to accumulate. The `SINCE` date is always
fixed at `2026-06-12` (policy introduction date) so the cumulative window grows each
week — this is intentional: small-n M-keyword cohorts need time to reach n≥5.

---

## Per-Run Parameters (issue #588)

| Parameter | Value |
|-----------|-------|
| `ISSUE_NUM` | 588 |
| `SINCE` | 2026-06-12 (fixed — policy introduction date) |
| `UNTIL` | 2026-06-28 |
| `NEXT_DATE` | 2026-07-05 |

---

## Outputs / Success Criteria

| Outcome | Artifact |
|---------|----------|
| Analysis comment posted | GitHub comment on issue #588 with per-bucket triad table, per-keyword table, and recommendation |
| No keyword change needed | "No keyword changes warranted this week." in comment; no PR opened |
| Keyword change warranted | PR opened against `main` modifying `.archon/.env`; comment includes PR link |
| L-bucket fires | New GitHub issue filed; comment notes it |
| Next revisit filed | New issue with title "Revisit dispatch ceiling (C9) — re-measure success-by-size/type", target date 2026-07-05 |

---

## Alternatives Considered

**A. Single cumulative doc with live data inline** — the revisit produces a comment
(ephemeral, issue-attached) rather than a persistent doc update. Chosen because the
data changes weekly; a doc would go stale instantly. The comment is the record.

**B. Keyword changes applied directly (no PR)** — rejected. A PR gives a human
review step before the keyword list changes affect the live scheduler. The ceiling
policy affects all future dispatch decisions, so a merge gate is appropriate.

**C. Evaluate each keyword in isolation (not vs. M baseline)** — rejected. An
absolute success-rate threshold would require calibrating the threshold value manually
and re-calibrating as overall factory success evolves. Using M baseline as the
reference makes the rule self-calibrating: a keyword is "good enough" iff it performs
no worse than the median M-size ticket.

---

## Open Questions (non-blocking)

1. **Minimum cumulative window before keyword decisions are reliable.** The n≥5 gate
   helps, but with a short history some keywords may flip between "remove" and "keep"
   across consecutive weekly runs. Consider adding a stability check (n≥5 in at least
   2 consecutive runs) before removing a keyword.
2. **L-bucket relaxation path.** If the L-bucket fires, what precisely should
   `is_above_ceiling()` change to? Current candidate: `L + keyword` (same logic as M).
   Spec for that code change would be filed on the auto-created issue.

---

## Assumptions

- Factory PRs are identified by `factory@markethawk` commit authorship (not GitHub login).
- "Decided" means merged (clean or with edits) or closed; open PRs are excluded from
  denominators because their outcome is unknown.
- The cumulative window (`SINCE=2026-06-12` fixed) is the intended data range — not
  a rolling 7-day window. This allows keyword cohorts to reach n≥5 even for infrequent
  keywords.
