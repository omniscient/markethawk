# Dispatch Ceiling Weekly Revisit — Week 2 Design

**Date:** 2026-06-20
**Issue:** [#574](https://github.com/omniscient/markethawk/issues/574) — Revisit dispatch ceiling (C9) — re-measure success-by-size/type
**Depends on:** [#339](https://github.com/omniscient/markethawk/issues/339) (ceiling policy), [#331](https://github.com/omniscient/markethawk/issues/331) (Factory Scorecard)
**Status:** Spec
**Analysis window:** 2026-06-12 → 2026-06-27
**Next revisit filing date:** 2026-07-04

---

## Problem

The dispatch ceiling policy (introduced in #339) is a heuristic that must be reassessed regularly to avoid keyword list drift — either false-positives (blocking useful factory work) or false-negatives (failing to block work that routinely fails). This spec defines the week-2 analysis run, using the cumulative window from policy introduction (2026-06-12) through 2026-06-27.

This is a recurring analysis run, not a tooling-build issue. The tooling infrastructure for durable Archon commands is out of scope; the analysis runs inline against the existing `scripts/fetch_scorecard.py` script.

---

## Requirements

1. Pull Factory Scorecard success-by-size (S/M/L) data for the cumulative window 2026-06-12 → 2026-06-27 using `scripts/fetch_scorecard.py`.
2. Apply deterministic keyword decision rules (n ≥ 5 guard, ≥ M-baseline-minus-15pt threshold) against the current `ABOVE_CEILING_KEYWORDS` list.
3. Post the full per-bucket triad table and per-keyword analysis as a comment on issue #574.
4. Open a PR modifying only the `dispatch_ceiling.keywords` field in `.claude/skills/refinement/config.yaml` if any keyword change is warranted. The agent does NOT modify this file directly on the live branch.
5. Check whether code-change issue #573 ("Revisit L=always-above-ceiling rule") already exists before filing a duplicate; if it exists, reference it in the comment rather than re-filing.
6. File the next weekly revisit issue for 2026-07-04 unconditionally.

---

## Architecture / Approach

### Step 1 — Pull scorecard data

```bash
python3 scripts/fetch_scorecard.py \
  --since 2026-06-12 \
  --until 2026-06-27 \
  --output /tmp/scorecard-w2.json
```

The output JSON carries:
- `by_size.{S,M,L,XL}.{merged_clean, merged_with_edits, closed, open}` — per-bucket triad.
- `prs[]` — one entry per factory PR with `{number, title, size, classification}`.

Treat XL as L-equivalent — add `by_size.XL` counts to `by_size.L` before analysis.

**Success rate formula:**
```
success_rate(bucket) = (merged_clean + merged_with_edits) / (merged_clean + merged_with_edits + closed)
# open is excluded from the denominator — in-flight PRs are undecided
```

### Step 2 — Compute overall M baseline

```
M_baseline = success_rate(M)
```

This is the reference point for all keyword decisions.

### Step 3 — Assess each keyword in ABOVE_CEILING_KEYWORDS

Current keywords: `migration|migrate|performance|perf|architectur|refactor`
Source: `.claude/skills/refinement/config.yaml` → `dispatch_ceiling.keywords`

For each keyword `kw`:
1. Filter `prs[]` where `size == "M"` AND `title` matches `kw` (case-insensitive regex, matching `scheduler.sh` behavior).
2. Count cohort `n_kw`.
3. If `n_kw < 5`: record "insufficient data — no change."
4. If `n_kw >= 5`: compute `rate_kw = (merged_clean + merged_with_edits) / (merged_clean + merged_with_edits + closed)` for the cohort.
5. Decision:
   - **Remove** if `rate_kw >= M_baseline` — no discriminative value.
   - **Keep** if `rate_kw < M_baseline - 0.15` — keyword identifies work that fails meaningfully more.
   - **Ambiguous** if `M_baseline - 0.15 ≤ rate_kw < M_baseline` — leave unchanged; note in report.

**Adding a keyword** requires ≥5 M-size `closed` PRs with a recurring title pattern not in the current list AND ≥15 points below M_baseline.

### Step 4 — L-bucket observation

Compute `success_rate(L + XL)`.

Check whether issue #573 ("Revisit L=always-above-ceiling rule in is_above_ceiling() — scheduler.sh") already exists:
```bash
gh issue list --repo omniscient/markethawk --search "is_above_ceiling" --json number,title,state
```

- If #573 exists (expected — filed by week-1 analysis): reference it in the report. Note whether the week-2 L+XL rate still clears the 70%/n≥5 bar. Do NOT file a duplicate.
- If no issue exists: if `rate(L+XL) > 0.70` and `n ≥ 5`, file a code-change issue targeting `is_above_ceiling()` in `dark-factory/scheduler.sh`.

### Step 5 — Produce recommendation comment

Post a Markdown comment on issue #574 containing:
- Per-bucket triad table (S/M/L+XL counts and success rates).
- M_baseline value.
- Per-keyword analysis table (cohort n, success rate, decision: remove / keep / ambiguous / insufficient data).
- Current vs. proposed `ABOVE_CEILING_KEYWORDS` string.
- If #573 is open: `> L-bucket observation: Rate {rate}% (n={n}) still clears the 70%/n≥5 threshold. See #573 (already open) for the code-change review.`
- Whether a PR for keyword changes was opened or "no changes warranted this week."
- Link to next-week revisit issue once filed.

### Step 6 — Open PR if changes warranted

If any keywords are flagged for removal or addition:
1. Branch off main: `git checkout -b fix/ceiling-keywords-week2-574`.
2. Edit `.claude/skills/refinement/config.yaml` — update only the `dispatch_ceiling.keywords` value.

**Important**: The canonical source for `ABOVE_CEILING_KEYWORDS` is `.claude/skills/refinement/config.yaml` (`dispatch_ceiling.keywords`). `.archon/.env` is gitignored and cannot carry a PR change. The scheduler reads `config.yaml` at startup and only falls back to an env-var override if one is explicitly set.

3. Open PR:
```bash
gh pr create \
  --title "fix(config): update dispatch ceiling keywords — week-2 analysis (#574)" \
  --body "..."
```

If no changes: comment "No keyword changes warranted this week (all keywords n<5 or within ambiguous band)."

### Step 7 — File next weekly revisit issue

File unconditionally:
```bash
gh issue create \
  --repo omniscient/markethawk \
  --title "Revisit dispatch ceiling (C9) — re-measure success-by-size/type" \
  --label "enhancement,priority: should-have,size: M,Dark Factory,ready-for-agent" \
  --body "..."
```

Body must include:
- `SINCE = 2026-06-12` (always fixed at policy introduction date)
- `UNTIL = 2026-07-04`
- `NEXT_DATE = 2026-07-11`
- Reference: Prior revisit: #574

---

## Alternatives Considered

### A: Build durable tooling (ceiling_revisit.py + ceiling-revisit.md Archon command) as part of this issue

This would match the intent in the #355 plan but was out of scope when that plan's PR wasn't merged. The issue is size:M and labeled for a single analysis run; creating new infrastructure expands scope and adds conformance risk. Rejected for #574; could be raised as a separate follow-up if weekly recurrence makes inline analysis burdensome.

### B: Block on #355 PR being merged first

No #355 PR exists. The implementation wasn't delivered. Blocking would stall the analysis indefinitely. Rejected.

### C: Directly mutate config.yaml on the live branch without a PR

Takes effect immediately with no human review gate, contradicting the original design decision from #355's spec. Rejected.

---

## Assumptions

- `scripts/fetch_scorecard.py` accepts `--since`/`--until` and is functional on main (confirmed).
- Week-1 data (from issue #355 comment, 2026-06-20): S=100%, M=100%, L+XL=100% at n=6/15/5 respectively. Week-2 will likely add similar counts, keeping all per-keyword cohorts below n=5.
- Issue #573 exists (confirmed) — the L-bucket code-change issue filed by week-1.
- `.archon/.env` is gitignored; the correct PR target for keyword changes is `.claude/skills/refinement/config.yaml`.
- `ABOVE_CEILING_KEYWORDS` env var override in `.archon/.env` takes precedence over config.yaml when set — verify no override exists before modifying config.yaml.

---

## Open Questions (non-blocking)

1. **Cumulative n too small to be statistically meaningful**: With only ~2 weeks of data, all keyword cohorts are expected to remain n<5. The analysis will likely return "insufficient data — no change" for all keywords. This is acceptable and expected; the value is in accumulating the data over time, not in making premature decisions.

2. **Config.yaml vs .archon/.env as PR target**: The original #355 spec referenced `.archon/.env` as the PR target, but that file is gitignored. This spec corrects that assumption. If there is ever a need for a runtime override without a code change (e.g., live environment tuning), an env var in `.archon/.env` can still be used — but PRs must target `config.yaml`.

---

*Spec generated by MarketHawk Refinement Pipeline — 2026-06-20*
