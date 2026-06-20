# Dispatch Ceiling Weekly Revisit — Process Design

**Date:** 2026-06-13
**Issue:** [#355](https://github.com/omniscient/markethawk/issues/355) — Revisit dispatch ceiling (C9) — re-measure success-by-size/type
**Depends on:** [#339](https://github.com/omniscient/markethawk/issues/339) (ceiling policy, implemented 2026-06-12), [#331](https://github.com/omniscient/markethawk/issues/331) (Factory Scorecard, implemented)
**Status:** Spec
**Next revisit:** 2026-06-27

---

## Problem

The dispatch ceiling policy (introduced #339) classifies tickets by size and keyword to determine
whether they are dispatched autonomously or parked for human pairing. The initial policy is a
heuristic, not a data-driven constant. Without a scheduled reassessment, the keyword list will
grow stale — either blocking useful factory work (false positives) or failing to block work that
routinely fails (false negatives). This spec defines the process for the first weekly
reassessment, which runs each week from 2026-06-20.

**Cadence note:** Originally drafted as quarterly; spec owner approved changing to weekly cadence
on 2026-06-20 (issue #355 comment). All scheduling parameters use 7-day intervals.

---

## Requirements

1. Pull Factory Scorecard success-by-size (S/M/L) numbers for the cumulative window
   2026-06-12 → <run date> (policy introduction date is always the fixed start).
2. Apply deterministic decision rules to decide whether any keyword should be removed or added.
3. Report the L-bucket success rate as an observation; if it exceeds 70% at n ≥ 5, file a separate
   code-change issue (not an env-var change — the L rule is hardcoded in `scheduler.sh`).
4. Produce a recommended `.archon/.env` diff as a PR for human review — the agent does NOT mutate
   `.archon/.env` directly.
5. File the next weekly revisit issue (~7 days from run date) unconditionally, to keep the cadence
   self-perpetuating even when no keyword change is warranted.

---

## Architecture / Approach

### Step 1 — Pull scorecard data

```bash
python3 scripts/fetch_scorecard.py \
  --since 2026-06-12 \
  --until <today> \
  --output /tmp/scorecard.json
```

The output JSON carries:
- `by_size.{S,M,L,unknown}.{merged_clean, merged_with_edits, closed, open}` — per-bucket triad.
- `prs[]` — one entry per factory PR with `{number, title, size, classification}` (where `classification`
  is `merged_clean | merged_with_edits | closed | open`).

**Note:** XL-labelled tickets are returned under `by_size.XL` by the current script. Treat XL as
L-equivalent (above ceiling) for all bucketing purposes — add `by_size.XL` counts to `by_size.L`.

**Success definition:**

```
success_rate(bucket) = (merged_clean + merged_with_edits) / (merged_clean + merged_with_edits + closed)
# `open` is excluded from the denominator — in-flight PRs are not yet decided.
```

### Step 2 — Compute overall M baseline

```
M_baseline = success_rate(M)   # computed from by_size.M
```

This is the reference point for all keyword decisions.

### Step 3 — Assess each keyword in ABOVE_CEILING_KEYWORDS

For each keyword `kw` in `ABOVE_CEILING_KEYWORDS` (currently: `migration|migrate|performance|perf|architectur|refactor`):

1. Filter `prs[]` where `size == "M"` AND `title` matches `kw` (case-insensitive regex, same as `scheduler.sh`).
2. Count the cohort `n_kw`.
3. If `n_kw < 5`: record "insufficient data — no change." This keyword is not yet evaluable.
4. If `n_kw >= 5`: compute `rate_kw = (merged_clean + merged_with_edits) / (merged_clean + merged_with_edits + closed)` for the cohort.
5. Decision:
   - **Remove** keyword if `rate_kw >= M_baseline` (the keyword has no discriminative value).
   - **Keep** keyword if `rate_kw < M_baseline - 0.15` (the keyword identifies work that fails meaningfully more than average).
   - **Ambiguous** (M_baseline - 0.15 ≤ rate_kw < M_baseline): leave unchanged; note in report.

**Adding a new keyword** (OR ADDED) requires the inverse evidence: ≥5 M-size `closed` PRs whose titles share
a recurring substring not in the current list AND whose success rate is ≥15 points below M_baseline.
This is rare — only act if the pattern is unambiguous and n ≥ 5.

### Step 4 — Report L-bucket observation (out of scope for env-var change)

Compute `success_rate(L + XL)`. If `> 0.70` and `n ≥ 5`, add to the report:
> L-bucket success rate is {rate}% (n={n}). The L=always-above-ceiling rule may be overly conservative.
> A separate code-change issue should be filed to revisit `is_above_ceiling()` in `scheduler.sh`.

If below 0.70 or n < 5: note the observation but take no action.

### Step 5 — Produce recommendation

Generate a report as a Markdown comment on the current revisit issue containing:
- Per-bucket triad table (S/M/L counts and success rates).
- Per-keyword analysis table (cohort n, success rate, decision: remove / keep / insufficient data).
- Current vs. proposed `ABOVE_CEILING_KEYWORDS` value.
- If any changes are warranted: open a PR that modifies only the `ABOVE_CEILING_KEYWORDS` line in
  `.archon/.env`. The PR description references the issue and the decision data.
- If no changes: note "no changes warranted this week" and close with that comment.

### Step 6 — File the next weekly revisit issue

Unconditionally file the following issue via `gh issue create`:

```
Title: Revisit dispatch ceiling (C9) — re-measure success-by-size/type
Body:
## Purpose

Weekly revisit of the dispatch ceiling policy introduced in #339.

## What to review

1. Pull Factory Scorecard (#331) success-by-S/M/L numbers for the cumulative window
   since 2026-06-12 (policy introduction date).
2. Compare against current ABOVE_CEILING_KEYWORDS thresholds.
3. Assess keyword false-positive rate. If high, narrow the list.
4. Recommend `ABOVE_CEILING_KEYWORDS` update in `.archon/.env` via PR if data warrants.

## References

- Spec: `docs/superpowers/specs/2026-06-13-dispatch-ceiling-quarterly-revisit-design.md`
- Archon command: `.archon/commands/ceiling-revisit.md`
- Architecture review candidate C9: `docs/dark-factory-architecture-review-2026-06-11.html`
- Prior revisit: #355 (comment with latest results)

## Target date

**<NEXT_DATE>** (weekly from <UNTIL>).

---
*Filed automatically by MarketHawk weekly ceiling revisit agent*

Labels: enhancement, priority: should-have, size: M, Dark Factory, ready-for-agent
```

---

## Alternatives Considered

### A: Agent directly modifies `.archon/.env`

Simpler (no PR overhead), but `.archon/.env` edits take effect on the live scheduler immediately
with no audit trail or rollback path. Rejected: a heuristic decision based on n ≥ 5 thresholds
warrants human review before mutating production dispatch behavior.

### B: Fully human checklist (no agent automation)

Issue is `ready-for-agent` and the work (running a script, applying decision rules, drafting a
PR) is mechanical enough for the factory. Rejected as too conservative — the value of the factory
is precisely to automate this kind of data-driven policy review.

### C: Inline the decision logic into `scheduler.sh`

Have the scheduler compute success rates at runtime and auto-adjust keywords. This would require
the scheduler to access GitHub PR data (net-new dependency), adds significant complexity to a
critical bash daemon, and changes the ceiling semantics on every scheduler cycle rather than
weekly. Rejected. The CLI-script + weekly-issue pattern is the correct separation.

---

## Assumptions

- `scripts/fetch_scorecard.py` is available in the repo at revisit time and accepts `--since`/`--until`
  date arguments. (Currently confirmed: file exists at `scripts/fetch_scorecard.py`.)
- Factory PRs continue to use the `feat/issue-<N>-...` branch naming convention so `fetch_scorecard.py`
  can resolve `size:` labels from issue numbers.
- `ABOVE_CEILING_KEYWORDS` in `.archon/.env` is a simple `|`-delimited regex string, one variable per
  line — the PR can edit it with a one-line sed or manual edit.
- n ≥ 5 may not be met in early weeks; the guard handles this case by recording "insufficient data
  — no change." The analysis window is cumulative from 2026-06-12 so data accumulates across weeks.

---

## Open Questions (non-blocking)

1. **Minimum total window PRs** — if the factory dispatched very few M tickets in the window
   (say < 10 total), is the analysis meaningful? The n ≥ 5 per-keyword guard handles the worst
   case; overall M_baseline is still usable as a reference even at small n.
2. **Keyword overlap** — `migration` and `migrate` are overlapping patterns; if both have n < 5
   individually but their union has n ≥ 5, should they be evaluated jointly? Current spec
   evaluates individually (they're separate pipe-delimited tokens). Revisit if n is too small.
3. **DISPATCH_CEILING_ENABLED kill-switch** — if the ceiling was disabled at any point, blocked
   tickets may have been dispatched, changing the cohort composition. The revisit agent should
   check `gh issue list --label above-ceiling` to estimate how much the ceiling actually ran.

---

## Implementation Checklist

- [ ] Run `python3 scripts/fetch_scorecard.py --since 2026-06-12 --until <today> --output /tmp/scorecard.json`
- [ ] Compute `M_baseline`, `success_rate(L+XL)`
- [ ] For each keyword: compute cohort n and success rate, apply decision rules
- [ ] Build per-bucket triad table and per-keyword analysis table
- [ ] If changes warranted: open PR modifying `ABOVE_CEILING_KEYWORDS` in `.archon/.env`
- [ ] Post analysis comment on current revisit issue
- [ ] If L-bucket >70% at n≥5: file separate code-change issue for `is_above_ceiling()` in `scheduler.sh`
- [ ] File next weekly revisit issue (~7 days from run date)

---

*Spec generated by MarketHawk Refinement Pipeline — 2026-06-13*
*Cadence updated to weekly per spec owner approval — 2026-06-20*
