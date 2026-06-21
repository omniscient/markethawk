# Dispatch Ceiling — Week-1 Revisit

**Date:** 2026-06-21
**Issue:** [#394](https://github.com/omniscient/markethawk/issues/394) — Revisit dispatch ceiling (C9) — re-measure success-by-size/type
**Depends on:** [#339](https://github.com/omniscient/markethawk/issues/339) (ceiling policy), [#331](https://github.com/omniscient/markethawk/issues/331) (Factory Scorecard), [#355](https://github.com/omniscient/markethawk/issues/355) (first revisit issue, cadence change approved 2026-06-20)
**Status:** Spec

---

## Overview

Issue #394 was originally filed as a "quarterly revisit" of the dispatch ceiling policy (#339) with a target date of 2026-09-12. Since then, the spec owner approved changing the cadence from quarterly to **weekly** on 2026-06-20 (see `docs/archive/2026-06-13-dispatch-ceiling-quarterly-revisit-design.md`, Cadence note). The `.archon/commands/ceiling-revisit.md` Archon command encodes the weekly process; its Phase 5 unconditionally files the next weekly issue to keep the cadence self-perpetuating.

Issue #394 therefore runs as **week 1** of the weekly cadence (analysis window: 2026-06-12 → 2026-06-21). With only 9 days of data since policy introduction, all keywords are expected to report "insufficient data — no change" (the `n ≥ 5` per-keyword guard in `scripts/ceiling_revisit.py`). No `.archon/.env` change and no PR are anticipated. The terminal outcome for week 1 is: analysis comment posted, next weekly issue filed.

---

## Requirements

1. Fetch Factory Scorecard data for the cumulative window **2026-06-12 → 2026-06-21** (policy introduction date is the fixed start).
2. Apply the deterministic decision rules from `scripts/ceiling_revisit.py`: n ≥ 5 per keyword; rate ≥ M_baseline → remove; rate < M_baseline − 0.15 → keep; otherwise insufficient data.
3. Post the analysis report as a comment on issue #394.
4. Open a PR to modify `ABOVE_CEILING_KEYWORDS` in `.archon/.env` only if keywords_to_remove is non-empty (not expected in week 1).
5. File a code-change issue for `is_above_ceiling()` in `scheduler.sh` only if L-bucket success rate > 70% at n ≥ 5 (not expected in week 1).
6. Unconditionally file the next weekly revisit issue with `NEXT_DATE = 2026-06-28`, labeled `size: S` (see Approach below for the stale-label fix).
7. "No PR opened" is a valid, expected terminal state for week 1. The `direct-to-pr` label on issue #394 refers to the automated refinement → plan → implement pipeline, not to the ceiling analysis itself.

---

## Architecture / Approach

### Existing machinery (all in place — no new code needed)

| Artifact | Location | Role |
|---|---|---|
| Analysis script | `scripts/ceiling_revisit.py` | Decision rules; generates Markdown report |
| Data fetcher | `scripts/fetch_scorecard.py` | Pulls per-bucket triad from GitHub PR history |
| Archon command | `.archon/commands/ceiling-revisit.md` | Five-phase execution plan (fetch → comment → PR → L-issue → next issue) |
| Archived design | `docs/archive/2026-06-13-dispatch-ceiling-quarterly-revisit-design.md` | Full spec, decision rules, alternatives |

### Run parameters for this instance

```bash
ISSUE_NUM=394
SINCE=2026-06-12      # policy introduction date — always fixed
UNTIL=2026-06-21      # today
NEXT_DATE=2026-06-28  # UNTIL + 7 days
```

### Expected week-1 outcome

- Every keyword (`migration|migrate|performance|perf|architectur|refactor`) will report "insufficient data — no change" because no keyword cohort will reach n ≥ 5 decided M-size PRs in 9 days.
- `KEYWORDS_TO_REMOVE` will be empty → Phase 3 (PR) does not execute.
- L-bucket success rate will be either N/A (no L PRs) or below the 70% / n ≥ 5 trigger → Phase 4 (code-change issue) does not execute.
- Phase 5 (next weekly issue) executes unconditionally.

### Stale-label fix: `size: M` → `size: S` in Phase 5 template

The Phase 5 issue template in `.archon/commands/ceiling-revisit.md` (line 190) hardcodes `--label "size: M"`. The correct size is `size: S` — the revisit task is mechanical (run a script, apply deterministic rules, post a comment, file the next issue) and #394 itself is correctly labeled `size: S`. When executing Phase 5, the implementation must use `--label "size: S"`. The stale `size: M` line in the command file should be corrected to `size: S` as part of this implementation.

### `.archon/.env` format (for future reference)

When a keyword change is eventually warranted (future weeks), `.archon/.env` should contain **only the override lines actually in effect** — one variable per line, no template, no commented defaults. Defaults are canonical in `dark-factory/scheduler.sh`. Example (minimal):

```
ABOVE_CEILING_KEYWORDS=migration|migrate|performance|perf|architectur
```

The `>>` append in `ceiling-revisit.md` Phase 3 handles creation correctly when the file doesn't exist.

---

## Alternatives Considered

### A: Defer to September 2026 (original quarterly target)

The quarterly target date (2026-09-12) in the issue body would be honored; the analysis would run with a full quarter of data. Rejected: the cadence change to weekly was approved on 2026-06-20 and is encoded in the Archon command. Deferring contradicts the approved cadence and breaks the self-perpetuating chain (Phase 5 files the next issue unconditionally).

### B: Skip week 1 because all keywords will show "insufficient data"

Skip running the analysis since no decision can be made yet. Rejected: Phase 5 must still file the next weekly issue to perpetuate the cadence, and the analysis comment establishes a traceable week-1 baseline. "Insufficient data" is the correct, expected result — not a reason to skip.

---

## Assumptions

- `scripts/fetch_scorecard.py` is available and accepts `--since`/`--until` (confirmed: file exists).
- Factory PRs continue to use the `feat/issue-<N>-...` branch naming convention.
- The `n ≥ 5` guard in `ceiling_revisit.py` handles zero-data weeks gracefully (confirmed: the guard returns "insufficient data — no change" for any keyword with decided < 5).
- `DISPATCH_CEILING_ENABLED` is `true` in the running scheduler (the default in `config.yaml`; no override in `.archon/.env` since it doesn't exist yet).

---

## Open Questions (non-blocking)

1. **`direct-to-pr` interaction:** Issue #394 carries the `direct-to-pr` label, which auto-advances the issue after the spec grace window. Since week-1 produces no PR (only a comment + next-issue), the scheduler should treat the analysis-comment-only outcome as completion. This behavior is inherent to the weekly revisit design and requires no spec change.

2. **`size: M` in the archived design doc:** `docs/archive/2026-06-13-dispatch-ceiling-quarterly-revisit-design.md` line 141 also lists `size: M` in its filed-issue template. This is a documentation inconsistency but does not affect the live command; it can be corrected in a follow-up if desired.

---

## Implementation Checklist

- [ ] Run `python3 scripts/fetch_scorecard.py --since 2026-06-12 --until 2026-06-21 --output /tmp/scorecard.json`
- [ ] Run `python3 scripts/ceiling_revisit.py --since 2026-06-12 --until 2026-06-21 --scorecard /tmp/scorecard.json --output /tmp/report.md`
- [ ] Post `/tmp/report.md` contents as a comment on issue #394
- [ ] If `keywords_to_remove` is non-empty: open PR modifying `ABOVE_CEILING_KEYWORDS` in `.archon/.env` (not expected in week 1)
- [ ] If L-bucket success > 70% at n ≥ 5: file code-change issue for `is_above_ceiling()` (not expected)
- [ ] Fix `--label "size: M"` → `--label "size: S"` in `.archon/commands/ceiling-revisit.md` Phase 5
- [ ] File next weekly revisit issue: NEXT_DATE=2026-06-28, label `size: S`

---

*Spec generated by MarketHawk Refinement Pipeline — 2026-06-21*
