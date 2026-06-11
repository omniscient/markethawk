# Factory Scorecard — Design (issue #331)

**Date**: 2026-06-11
**Issue**: [#331](https://github.com/omniscient/markethawk/issues/331) — Factory Scorecard: merge-rate triad, rework rate, 2-week churn, success-by-size
**Implemented**: interactively (this session), not via the dark factory.

## Problem

The platform measures its scanners with Outcomes and a Scorecard, but the factory — itself a signal generator whose signals are PRs — has no outcome tracking. "Is the factory good?" is currently unanswerable without manual excavation (as done for the 2026-06-11 architecture review).

## Solution overview

A third script in the existing dashboard pipeline (`scripts/` from PR #217):

```
scripts/fetch_metrics.py    → metrics.json      (existing, unchanged)
scripts/fetch_scorecard.py  → scorecard.json    (NEW)
scripts/render_report.py    → docs/pipeline-report.html
                              (merges scorecard.json under a "scorecard" key
                               in the injected data blob)
scripts/generate.sh           gains the scorecard stage
```

`fetch_metrics.py` stays issue-centric; the scorecard is PR/git-centric with different data sources (GitHub PR data + git history), so it gets its own module.

**Data transport (amended during implementation):** REST v3 via `gh api
--paginate`, not `gh pr list --json commits` — fetching `commits.authors`
inline for hundreds of PRs exceeds GraphQL node limits and exhausts the
hourly GraphQL quota. Commit authors come from a per-PR REST call returning
the *primary* author only; co-authors (`Co-Authored-By:` trailers such as
`noreply@anthropic.com`) never appear in REST payloads and need no filtering.
The factory fingerprint is unaffected: factory commits are always
primary-authored `factory@markethawk`.

## Key design decisions

1. **`merged-with-edits` is derived from commit authorship, not manual labeling.**
   Every factory commit is authored `MarketHawk Factory <factory@markethawk>`,
   while all PRs (factory and human) share one GitHub login. So:
   - A PR is a **factory PR** iff ≥1 of its commits is factory-authored.
   - A merged factory PR is **merged-with-edits** iff it contains ≥1
     non-factory-authored commit, **or** carries the `merged-with-edits` label
     (manual override for cases git can't see, e.g. a human fix-up pushed
     directly to main after merge).
   This works retroactively for the baseline window with zero label discipline.
2. **The script is read-only** — it never applies labels or mutates GitHub state.
3. **Four metrics only.** Cost-per-merged-clean-PR was considered and deferred
   (decided 2026-06-11): get the baseline first, let it drive what's next.
4. **Renders into the existing dashboard**, not a separate page.

## Metrics (computed for a `--since/--until` window, defaults 2026-05-01 → today)

A PR is "in window" by its `createdAt`. A commit is "in window" by its commit date.

### 1. Merge-rate triad (Cognition top-line)

Each factory PR in window classified as exactly one of:
- `closed` — closed without merging
- `merged_with_edits` — merged, with ≥1 human commit or the `merged-with-edits` label
- `merged_clean` — merged, all commits factory-authored
- (still-open PRs are reported as `open` but excluded from rate denominators)

Top-line: `merge_rate_pct = (merged_clean + merged_with_edits) / (all resolved factory PRs)`.

### 2. Rework rate (DORA 2025 fifth metric)

`rework_rate_pct = (issues + PRs labeled `factory-regression` created in window) / (factory PRs merged in window)`.

Note the denominator uses `mergedAt` (DORA counts deployments in the period),
unlike the triad which buckets PRs by `createdAt`.

### 3. 2-week churn (GitClear slop signal)

For each factory-authored, non-merge commit on `main` whose commit date is ≥14
days before `--until`:
- **added lines** per file from `git show --numstat`
- **surviving lines** = lines attributed to that commit by `git blame` run at
  the latest main rev ≤ (commit date + 14 days) (`git rev-list -1 --before`)
- `churn_pct = 1 − Σsurvived / Σadded`

Documented approximations: renames/moves count as churn; binary files skipped;
merge commits skipped; commits younger than 14 days excluded (not yet measurable).

### 4. Success-by-size (METR ceiling feed)

The triad from (1) segmented by the linked issue's `size:` label. Linkage:
parse `issue-(\d+)` from the PR head branch name (factory convention
`feat/issue-N-…`). PRs with no parseable issue or unlabeled issues fall into
an `unknown` bucket.

## Output contract (`scorecard.json`)

```json
{
  "generated_at": "...",
  "window": {"since": "2026-05-01", "until": "2026-06-11"},
  "triad": {"merged_clean": 0, "merged_with_edits": 0, "closed": 0, "open": 0,
             "merge_rate_pct": 0.0},
  "rework": {"regression_count": 0, "merged_factory_prs": 0, "rework_rate_pct": 0.0},
  "churn": {"added_lines": 0, "surviving_lines": 0, "churn_pct": 0.0,
             "commits_analyzed": 0, "commits_too_young": 0},
  "by_size": {"S": {"merged_clean": 0, "merged_with_edits": 0, "closed": 0, "open": 0},
               "M": {}, "L": {}, "unknown": {}},
  "prs": [{"number": 0, "title": "", "classification": "merged_clean",
            "issue": 0, "size": "S", "merged_at": null}]
}
```

`render_report.py` reads `scorecard.json` if present and merges it into the
injected data blob as `metrics["scorecard"]`; the template renders the section
only when the key exists (older `metrics.json` snapshots keep working).

## Dashboard section

New "Factory Scorecard" section in `scripts/template.html`:
- Triad stacked bar (merged-clean / merged-with-edits / closed)
- Success-by-size grouped bars (S/M/L/unknown)
- Stat cards: merge rate %, rework rate %, 2-week churn %, factory PRs in window
- Window dates shown in the section header

Verified with the real-ECharts headless smoke test
(`node tests/scripts/render_smoke.cjs`) — one `setOption` throw blanks all
later charts, so stub tests are insufficient.

## Labels (acceptance criterion #1)

Created once via `gh label create`:
- `factory-regression` — "Fixes something a factory PR broke (feeds rework rate)"
- `merged-with-edits` — "Factory PR needed human commits before merge (manual override; normally derived from commit authorship)"

## Testing

`tests/scripts/test_fetch_scorecard.py`, mirroring the existing fixture style:
- PR classification (factory detection, triad, label override, open exclusion)
- Issue/size linkage from branch names (incl. no-match → unknown)
- Churn arithmetic from synthetic numstat/blame output (no live git needed)
- Window filtering edge cases
Live `gh`/git calls isolated in thin fetch functions, excluded from unit tests
(same pattern as `fetch_metrics.py`).

## Acceptance criteria mapping (#331)

| Criterion | How |
|---|---|
| Labels exist with descriptions | `gh label create` × 2 |
| Script computes four metrics for arbitrary window | `scripts/fetch_scorecard.py --since --until` |
| Baseline 2026-05-01 → 2026-06-11 posted on ticket | run script, `gh issue comment 331 --body-file` |
| Metrics visible on dashboard | new template section, regenerated `docs/pipeline-report.html` |
