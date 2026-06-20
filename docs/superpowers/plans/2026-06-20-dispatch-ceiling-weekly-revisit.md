# Plan: Weekly Dispatch Ceiling Revisit Process

**Date:** 2026-06-20
**Issue:** #355
**Spec:** docs/superpowers/specs/2026-06-13-dispatch-ceiling-quarterly-revisit-design.md
**Cadence note:** Spec calls for quarterly revisits; user feedback on 2026-06-20 requested
**weekly** cadence. All scheduling parameters below use 7-day intervals.

**Spec update required:** The approved spec uses quarterly cadence (window → 2026-09-12, next issue
~2026-12-12). Per the spec owner's comment on issue #355 (2026-06-20): *"Fine with this one but
quarterly is an eternity. Weekly best here. Adjust the plan to weekly when planning."* This is a
spec owner–approved deviation. Task 0 below updates the spec itself to reflect weekly cadence before
implementation proceeds, making the rest of the plan spec-conformant.

---

## Goal

Create a self-perpetuating weekly review process for the dispatch ceiling keyword list
introduced in #339. Each weekly run:
1. Pulls cumulative Factory Scorecard data (from 2026-06-12 to run date).
2. Applies deterministic decision rules (n≥5 guard, ≥M-baseline-15pt threshold).
3. Posts an analysis comment on the current revisit issue.
4. Opens a PR modifying `.archon/.env` only if keyword changes are warranted.
5. Files the next weekly revisit issue unconditionally (~7 days out).

The implementation produces two deliverables: `scripts/ceiling_revisit.py` (reusable analysis
script) and `.archon/commands/ceiling-revisit.md` (the Archon command for all future weekly runs).

---

## Architecture

All changes are confined to:
- `scripts/ceiling_revisit.py` — new analysis script wrapping `fetch_scorecard.py` output
  with decision logic, markdown report generation, and GitHub actions (PR + issue creation).
- `.archon/commands/ceiling-revisit.md` — new Archon command file; the agent prompt that
  drives each weekly revisit run.
- First analysis execution: runs `ceiling_revisit.py` for the 2026-06-12 → 2026-06-20 window,
  posts the week-1 report to issue #355, and files the next issue (~2026-06-27).

No new Docker containers, models, migrations, or scheduler changes required.

---

## Tech Stack

Python 3 (`scripts/ceiling_revisit.py`), Bash (invocation), `gh` CLI (GitHub actions),
Markdown (`.archon/commands/ceiling-revisit.md`).

---

## File Structure

| File | Change |
|------|--------|
| `scripts/ceiling_revisit.py` | New — analysis script with decision logic |
| `.archon/commands/ceiling-revisit.md` | New — Archon command for weekly agent runs |

---

## Tasks

### Task 0 — Update spec to reflect weekly cadence

**Files:** `docs/superpowers/specs/2026-06-13-dispatch-ceiling-quarterly-revisit-design.md`

The spec was written before the spec owner requested weekly cadence (issue #355 comment, 2026-06-20).
This task updates the spec in-place so all downstream conformance checks compare against the correct cadence.

#### Steps

**Step 0.1 — Apply cadence changes to the spec file**

In `docs/superpowers/specs/2026-06-13-dispatch-ceiling-quarterly-revisit-design.md`, make the following
targeted replacements:

1. Change the title from `Dispatch Ceiling **Quarterly** Revisit` to `Dispatch Ceiling **Weekly** Revisit`
2. Change "first **quarterly** reassessment, which runs at or after 2026-09-12" to
   "first **weekly** reassessment, which runs each week from 2026-06-20"
3. In Requirements section: Change Requirement 1 window `2026-06-12 → 2026-09-12` to
   `2026-06-12 → <run date>` (cumulative window, updated each weekly run)
4. Change Requirement 5 "File the next **quarterly** revisit issue (~2026-12-12)" to
   "File the next **weekly** revisit issue (~7 days from run date)"
5. In Architecture Step 1, change the example command to use `--until <today>` pattern:
   `python3 scripts/fetch_scorecard.py --since 2026-06-12 --until <today> --output /tmp/scorecard.json`
6. In Step 6 (file next issue), change the body to use the weekly body and target date (~7 days out)
7. Update `**Next revisit:**` header field from `2026-12-12` to `2026-06-27` (first weekly cadence)
8. Update the assumption "M-bucket will have n ≥ 5 PRs by 2026-09-12 (3 months)" to
   "n ≥ 5 may not be met in early weeks; the guard handles this case by recording 'insufficient data — no change'"

**Step 0.2 — Verify spec still parses as valid Markdown**

```bash
python3 -c "
import re
text = open('docs/superpowers/specs/2026-06-13-dispatch-ceiling-quarterly-revisit-design.md').read()
assert 'Weekly' in text, 'cadence not updated'
assert 'quarterly' not in text.lower() or 'quarterly' in text.lower()[:500], 'old cadence language remains'
assert 'weekly' in text.lower(), 'weekly cadence not added'
print('Spec update: OK')
"
```

**Step 0.3 — Commit the spec update**

```bash
git add docs/superpowers/specs/2026-06-13-dispatch-ceiling-quarterly-revisit-design.md
git commit -m "docs(spec): update dispatch ceiling revisit cadence from quarterly to weekly (#355)

Per spec owner feedback on 2026-06-20: weekly cadence preferred.
Adjusts window, next-issue target, and data-sufficiency assumptions."
```

---

### Task 1 — Create `scripts/ceiling_revisit.py`

**Files:** `scripts/ceiling_revisit.py`

This script wraps `fetch_scorecard.py`, applies the keyword decision rules from the spec,
and produces a markdown analysis report. It does NOT post to GitHub or open PRs — those actions
are performed by the Archon command in Task 2 so the script remains testable in isolation.

#### TDD steps

**Step 1.1 — Write the failing smoke test first**

Create `scripts/test_ceiling_revisit.py`:

```python
#!/usr/bin/env python3
"""Smoke tests for ceiling_revisit.py decision logic (issue #355)."""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from ceiling_revisit import (
    success_rate,
    classify_keyword,
    build_keyword_analysis,
    build_bucket_table,
    find_new_keyword_candidates,
)

PASS = 0
FAIL = 0

def assert_eq(label, got, expected):
    global PASS, FAIL
    if got == expected:
        print(f"PASS: {label}")
        PASS += 1
    else:
        print(f"FAIL: {label} — got={got!r} expected={expected!r}")
        FAIL += 1

# --- success_rate ---
assert_eq("success_rate: normal",   success_rate({"merged_clean": 3, "merged_with_edits": 1, "closed": 1, "open": 2}), 0.8)
assert_eq("success_rate: all open", success_rate({"merged_clean": 0, "merged_with_edits": 0, "closed": 0, "open": 5}), None)
assert_eq("success_rate: zeros",    success_rate({"merged_clean": 0, "merged_with_edits": 0, "closed": 0, "open": 0}), None)

# --- classify_keyword ---
# (m_baseline=0.70)
assert_eq("classify: n<5 → insufficient",   classify_keyword(n=3, rate=0.40, m_baseline=0.70), "insufficient data — no change")
assert_eq("classify: rate>=baseline → remove", classify_keyword(n=6, rate=0.75, m_baseline=0.70), "remove")
assert_eq("classify: rate>=baseline-0 → remove", classify_keyword(n=5, rate=0.70, m_baseline=0.70), "remove")
assert_eq("classify: ambiguous band",        classify_keyword(n=5, rate=0.58, m_baseline=0.70), "ambiguous — leave unchanged")
assert_eq("classify: rate<baseline-0.15 → keep", classify_keyword(n=5, rate=0.54, m_baseline=0.70), "keep")
assert_eq("classify: n=0 → insufficient",   classify_keyword(n=0, rate=None, m_baseline=0.70), "insufficient data — no change")

# --- build_keyword_analysis ---
prs = [
    {"title": "Run database migration for users", "size": "M", "classification": "merged_clean"},
    {"title": "Another migration task", "size": "M", "classification": "closed"},
    {"title": "Add chart feature", "size": "M", "classification": "merged_clean"},
    {"title": "Migration cleanup work", "size": "M", "classification": "merged_clean"},
    {"title": "Big migration project", "size": "M", "classification": "merged_with_edits"},
    {"title": "MIGRATION: remove old table", "size": "M", "classification": "merged_clean"},
]
m_baseline = 0.70
rows = build_keyword_analysis(prs, "migration", m_baseline)
assert_eq("kw analysis: n=6", rows["n"], 6)
assert_eq("kw analysis: rate", rows["rate"], 5/6)
assert_eq("kw analysis: decision → remove", rows["decision"], "remove")

# --- build_bucket_table (spot check) ---
by_size = {
    "S": {"merged_clean": 5, "merged_with_edits": 1, "closed": 0, "open": 1},
    "M": {"merged_clean": 3, "merged_with_edits": 1, "closed": 2, "open": 0},
    "L": {"merged_clean": 0, "merged_with_edits": 0, "closed": 2, "open": 1},
    "XL": {"merged_clean": 0, "merged_with_edits": 1, "closed": 1, "open": 0},
}
table = build_bucket_table(by_size)
# M: (3+1)/(3+1+2) = 0.667
assert_eq("bucket table: M rate", round(table["M"]["rate"], 3), 0.667)
# L+XL combined: (0+0+0+1)/(0+0+0+1+2+1) = 1/4 = 0.25
assert_eq("bucket table: L+XL combined n", table["L+XL"]["n"], 4)
assert_eq("bucket table: L+XL rate", table["L+XL"]["rate"], 0.25)

# --- find_new_keyword_candidates ---
# Needs >=5 M-size *closed* PRs with recurring substring AND >=15pt below M_baseline
prs_new_kw = [
    {"title": "Add rollback logic for deploy", "size": "M", "classification": "closed"},
    {"title": "Improve rollback on failed deploy", "size": "M", "classification": "closed"},
    {"title": "Rollback safety for scanner restart", "size": "M", "classification": "closed"},
    {"title": "Rollback mechanism after DB upgrade", "size": "M", "classification": "closed"},
    {"title": "Add rollback to migration flow", "size": "M", "classification": "closed"},
    # Not enough for "deploy" alone but "rollback" has n=5
]
candidates = find_new_keyword_candidates(prs_new_kw, "migration|migrate|performance|perf|architectur|refactor", m_baseline=0.70)
# "rollback" appears 5 times, all closed → rate=0.0, well below M_baseline-0.15=0.55 → candidate
assert_eq("find_new_kw: rollback is candidate", any("rollback" in c["keyword"] for c in candidates), True)
# "deploy" appears only 2 times → n<5 → not a candidate
assert_eq("find_new_kw: deploy not candidate (n<5)", any("deploy" == c["keyword"] for c in candidates), False)

print(f"\nResults: {PASS} passed, {FAIL} failed")
sys.exit(0 if FAIL == 0 else 1)
```

**Step 1.2 — Verify test fails (functions not yet defined)**

```bash
cd /workspace/markethawk
python3 scripts/test_ceiling_revisit.py 2>&1 | head -5
```

Expected: `ModuleNotFoundError: No module named 'ceiling_revisit'` (or ImportError)

**Step 1.3 — Implement `scripts/ceiling_revisit.py`**

```python
#!/usr/bin/env python3
"""Dispatch ceiling keyword revisit analysis (issue #355).

Wraps scripts/fetch_scorecard.py and applies the decision rules from
docs/superpowers/specs/2026-06-13-dispatch-ceiling-quarterly-revisit-design.md.

Outputs a Markdown report to stdout (or --output file). Does NOT post to
GitHub — that is handled by the Archon command (.archon/commands/ceiling-revisit.md).
"""
from __future__ import annotations
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


# Keyword list mirrors ABOVE_CEILING_KEYWORDS default in scheduler.sh:32
DEFAULT_KEYWORDS = "migration|migrate|performance|perf|architectur|refactor"


def success_rate(triad: dict) -> float | None:
    """(merged_clean + merged_with_edits) / decided; None if no decided PRs."""
    decided = triad["merged_clean"] + triad["merged_with_edits"] + triad["closed"]
    if decided == 0:
        return None
    return (triad["merged_clean"] + triad["merged_with_edits"]) / decided


def classify_keyword(n: int, rate: float | None, m_baseline: float) -> str:
    if n < 5 or rate is None:
        return "insufficient data — no change"
    if rate >= m_baseline:
        return "remove"
    if rate < m_baseline - 0.15:
        return "keep"
    return "ambiguous — leave unchanged"


def build_keyword_analysis(prs: list[dict], keyword: str, m_baseline: float) -> dict:
    cohort = [
        p for p in prs
        if p.get("size") == "M"
        and re.search(keyword, p.get("title", ""), re.IGNORECASE)
    ]
    n = len(cohort)
    triad: dict[str, int] = {"merged_clean": 0, "merged_with_edits": 0, "closed": 0, "open": 0}
    for p in cohort:
        cls = p.get("classification", "open")
        if cls in triad:
            triad[cls] += 1
    rate = success_rate(triad)
    return {
        "keyword": keyword,
        "n": n,
        "rate": rate,
        "decision": classify_keyword(n, rate, m_baseline),
    }


def find_new_keyword_candidates(
    prs: list[dict], current_keywords: str, m_baseline: float
) -> list[dict]:
    """Find recurring substrings in closed M-PRs that are not in current_keywords and
    have >=5 closed PRs with success rate >=15pt below m_baseline.

    Returns list of {keyword, n, decision} dicts — empty if none qualify.
    Note: XL is never emitted by fetch_scorecard.py's size label regex ([SML]); XL merging
    in build_bucket_table is spec-correct but will be dead code for the current data source.
    """
    existing = set(kw.strip() for kw in current_keywords.split("|") if kw.strip())
    closed_m = [p for p in prs if p.get("size") == "M" and p.get("classification") == "closed"]
    # Extract single-word tokens (\w{4,}) from closed-M titles; skip existing keywords
    from collections import Counter
    token_counts: Counter = Counter()
    for p in closed_m:
        words = re.findall(r'\b\w{4,}\b', p.get("title", "").lower())
        for w in set(words):
            if not any(re.search(kw, w, re.IGNORECASE) for kw in existing):
                token_counts[w] += 1
    candidates = []
    for token, n in token_counts.items():
        if n < 5:
            continue
        # All closed (by filter above) → rate = 0.0
        rate = 0.0
        if rate < m_baseline - 0.15:
            candidates.append({"keyword": token, "n": n, "decision": "add candidate"})
    return candidates


def build_bucket_table(by_size: dict) -> dict:
    """Compute per-bucket success rates; merge XL into L for reporting."""
    result = {}
    for bucket in ("S", "M"):
        triad = by_size.get(bucket, {"merged_clean": 0, "merged_with_edits": 0, "closed": 0, "open": 0})
        rate = success_rate(triad)
        decided = triad["merged_clean"] + triad["merged_with_edits"] + triad["closed"]
        result[bucket] = {"rate": rate, "n": decided + triad.get("open", 0), **triad}
    # Merge L + XL
    l_triad: dict[str, int] = {"merged_clean": 0, "merged_with_edits": 0, "closed": 0, "open": 0}
    for b in ("L", "XL"):
        t = by_size.get(b, {})
        for k in l_triad:
            l_triad[k] += t.get(k, 0)
    l_rate = success_rate(l_triad)
    l_n = sum(l_triad.values())
    result["L+XL"] = {"rate": l_rate, "n": l_n, **l_triad}
    return result


def _fmt_rate(rate: float | None) -> str:
    return f"{rate:.1%}" if rate is not None else "N/A"


def generate_report(
    since: str,
    until: str,
    scorecard_path: str,
    keywords: str = DEFAULT_KEYWORDS,
) -> tuple[str, list[str], list[dict], bool]:
    """Return (markdown_report, keywords_to_remove, new_keyword_candidates, l_bucket_needs_issue).

    keywords_to_remove: list of keyword tokens the analysis recommends removing.
    new_keyword_candidates: list of {keyword, n, decision} for add candidates (spec Step 3).
    l_bucket_needs_issue: True if L-bucket >70% at n≥5.
    """
    with open(scorecard_path) as f:
        data = json.load(f)

    by_size = data.get("by_size", {})
    prs = data.get("prs", [])

    bucket_table = build_bucket_table(by_size)
    m_baseline = bucket_table["M"]["rate"]

    kw_list = [kw.strip() for kw in keywords.split("|") if kw.strip()]
    kw_rows = [build_keyword_analysis(prs, kw, m_baseline or 0.0) for kw in kw_list]

    keywords_to_remove = [r["keyword"] for r in kw_rows if r["decision"] == "remove"]

    # Add-keyword candidates (spec Step 3 — inverse evidence)
    new_keyword_candidates = find_new_keyword_candidates(prs, keywords, m_baseline or 0.0)

    # L-bucket observation
    l_data = bucket_table["L+XL"]
    l_rate = l_data["rate"]
    l_n = l_data["n"]
    l_bucket_needs_issue = bool(l_rate is not None and l_rate > 0.70 and l_n >= 5)

    # Build markdown report
    lines = [
        f"## Dispatch Ceiling Weekly Revisit — {since} → {until}",
        "",
        "### Per-Bucket Triad",
        "",
        "| Bucket | n (total) | merged_clean | merged_with_edits | closed | open | Success Rate |",
        "|--------|-----------|--------------|-------------------|--------|------|--------------|",
    ]
    for bucket in ("S", "M", "L+XL"):
        d = bucket_table[bucket]
        lines.append(
            f"| {bucket} | {d['n']} | {d['merged_clean']} | {d['merged_with_edits']}"
            f" | {d['closed']} | {d['open']} | {_fmt_rate(d['rate'])} |"
        )

    lines += [
        "",
        f"**M baseline:** {_fmt_rate(m_baseline)}",
        "",
        "### Per-Keyword Analysis",
        "",
        "| Keyword | M-cohort n | Success Rate | vs M baseline | Decision |",
        "|---------|-----------|--------------|---------------|----------|",
    ]
    for r in kw_rows:
        vs = (
            f"{r['rate'] - (m_baseline or 0.0):+.1%}"
            if r["rate"] is not None and m_baseline is not None
            else "N/A"
        )
        lines.append(
            f"| `{r['keyword']}` | {r['n']} | {_fmt_rate(r['rate'])}"
            f" | {vs} | {r['decision']} |"
        )

    # Current vs proposed keyword string
    current_kws = keywords
    if keywords_to_remove:
        remaining = [kw for kw in kw_list if kw not in keywords_to_remove]
        proposed_kws = "|".join(remaining) if remaining else "(empty)"
    else:
        proposed_kws = current_kws

    lines += [
        "",
        "### Keyword Change Recommendation",
        "",
        f"**Current:** `{current_kws}`",
        f"**Proposed:** `{proposed_kws}`",
        "",
    ]

    if keywords_to_remove:
        lines += [
            f"Keywords recommended for removal: {', '.join(f'`{k}`' for k in keywords_to_remove)}",
            "",
            "A PR has been opened with the exact `.archon/.env` diff. Review and merge to apply.",
            "",
        ]
    if new_keyword_candidates:
        lines += [
            "### Add-Keyword Candidates (spec Step 3 — inverse evidence)",
            "",
            "| Candidate keyword | closed-M n | Decision |",
            "|-------------------|-----------|----------|",
        ]
        for c in new_keyword_candidates:
            lines.append(f"| `{c['keyword']}` | {c['n']} | {c['decision']} |")
        lines += [
            "",
            "Review these candidates manually — add to ABOVE_CEILING_KEYWORDS only if the "
            "pattern is unambiguous and recurring across distinct issues.",
            "",
        ]
    if not keywords_to_remove and not new_keyword_candidates:
        lines.append("No keyword changes warranted this week.\n")

    # L-bucket observation
    lines += [
        "### L-Bucket Observation",
        "",
    ]
    if l_rate is not None:
        lines.append(
            f"L+XL success rate: {_fmt_rate(l_rate)} (n={l_n}). "
        )
        if l_bucket_needs_issue:
            lines += [
                "**The L=always-above-ceiling rule may be overly conservative.**",
                "A separate code-change issue should be filed to revisit `is_above_ceiling()`"
                " in `scheduler.sh`.",
                "",
            ]
        else:
            lines.append("Below 70% threshold or n<5 — no action required.\n")
    else:
        lines.append("No L/XL-size PRs in this window yet.\n")

    lines += [
        "---",
        "*Posted by MarketHawk Weekly Ceiling Revisit — issue #355*",
    ]

    return "\n".join(lines), keywords_to_remove, new_keyword_candidates, l_bucket_needs_issue


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", required=True, help="YYYY-MM-DD window start")
    parser.add_argument("--until", required=True, help="YYYY-MM-DD window end")
    parser.add_argument("--scorecard", default=None,
                        help="Path to pre-fetched scorecard JSON (skips fetch step)")
    parser.add_argument("--keywords", default=DEFAULT_KEYWORDS,
                        help="Pipe-delimited keyword list (default: scheduler.sh default)")
    parser.add_argument("--output", default=None, help="Write report to file instead of stdout")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print report only; do not post or open PRs")
    args = parser.parse_args()

    # Fetch scorecard if not provided
    scorecard_path = args.scorecard
    if not scorecard_path:
        scorecard_path = "/tmp/ceiling-revisit-scorecard.json"
        print(f"[ceiling_revisit] Fetching scorecard {args.since} → {args.until}...",
              file=sys.stderr)
        subprocess.run(
            [
                sys.executable,
                str(Path(__file__).parent / "fetch_scorecard.py"),
                f"--since={args.since}",
                f"--until={args.until}",
                f"--output={scorecard_path}",
            ],
            check=True,
        )

    report, to_remove, new_candidates, l_needs_issue = generate_report(
        args.since, args.until, scorecard_path, args.keywords
    )

    if args.output:
        Path(args.output).write_text(report)
        print(f"[ceiling_revisit] Report written to {args.output}", file=sys.stderr)
    else:
        print(report)

    if args.dry_run:
        print("[ceiling_revisit] --dry-run: no GitHub actions taken.", file=sys.stderr)
        return

    # Emit machine-readable recommendation for the Archon command to consume
    rec = {
        "keywords_to_remove": to_remove,
        "new_keyword_candidates": [c["keyword"] for c in new_candidates],
        "l_bucket_needs_issue": l_needs_issue,
    }
    print("\n<!-- CEILING_REVISIT_JSON", json.dumps(rec), "-->", file=sys.stderr)


if __name__ == "__main__":
    main()
```

**Step 1.4 — Run tests (should pass now)**

```bash
cd /workspace/markethawk
python3 scripts/test_ceiling_revisit.py
```

Expected:
```
PASS: success_rate: normal
PASS: success_rate: all open
...
Results: 16 passed, 0 failed
```

**Step 1.5 — Smoke-test with `--dry-run` (requires scorecard fetch)**

```bash
python3 scripts/ceiling_revisit.py \
  --since 2026-06-12 \
  --until 2026-06-20 \
  --dry-run 2>&1 | head -20
```

Expected: report header line `## Dispatch Ceiling Weekly Revisit — 2026-06-12 → 2026-06-20`
(may show `No L/XL-size PRs` and `insufficient data — no change` for all keywords given the
short window — that is correct and expected for week 1).

**Step 1.6 — Commit Task 1**

```bash
git add scripts/ceiling_revisit.py scripts/test_ceiling_revisit.py
git commit -m "feat(scripts): ceiling_revisit.py — weekly dispatch ceiling analysis script (#355)

Wraps fetch_scorecard.py output with n>=5/M-baseline-15pt decision rules.
Outputs markdown report. Does not post to GitHub (Archon command handles that).
Unit tests in scripts/test_ceiling_revisit.py — 14 assertions."
```

---

### Task 2 — Create `.archon/commands/ceiling-revisit.md`

**Files:** `.archon/commands/ceiling-revisit.md`

This Archon command drives each weekly revisit run. The agent reads it to know what to do:
fetch, analyze, post, optionally PR, and file the next issue.

#### TDD steps

**Step 2.1 — Verify no command file exists yet**

```bash
ls .archon/commands/ceiling-revisit.md 2>/dev/null || echo "not found (expected)"
```

Expected: `not found (expected)`

**Step 2.2 — Create `.archon/commands/ceiling-revisit.md`**

```markdown
---
description: Weekly dispatch ceiling keyword revisit — analyze success-by-size/keyword and recommend changes
argument-hint: "ceiling-revisit <issue-number> <since-date> <until-date>"
---

# Weekly Dispatch Ceiling Revisit

## Purpose

Runs the weekly dispatch ceiling keyword review for the MarketHawk factory scheduler.
Reads Factory Scorecard data, applies deterministic decision rules, posts an analysis
comment on the given GitHub issue, optionally opens a PR for keyword changes, and
unconditionally files the next weekly revisit issue.

## Inputs (from workflow args)

- `$ISSUE_NUM` — GitHub issue number receiving the analysis comment (e.g. 355)
- `$SINCE` — analysis window start (YYYY-MM-DD, always 2026-06-12 — policy introduction date)
- `$UNTIL` — analysis window end (YYYY-MM-DD, today's date when the agent runs)
- `$NEXT_DATE` — target date for the next weekly revisit issue (UNTIL + 7 days)

## Phase 1 — Fetch and Analyze

```bash
REPO=omniscient/markethawk
SCORECARD=/tmp/ceiling-revisit-scorecard.json

# Fetch scorecard data for cumulative window since policy introduction
python3 scripts/fetch_scorecard.py \
  --since "$SINCE" \
  --until "$UNTIL" \
  --output "$SCORECARD"

# Generate analysis report and machine-readable recommendation
REPORT_FILE=/tmp/ceiling-revisit-report.md
python3 scripts/ceiling_revisit.py \
  --since "$SINCE" \
  --until "$UNTIL" \
  --scorecard "$SCORECARD" \
  --output "$REPORT_FILE" \
  2>/tmp/ceiling-revisit-meta.txt

# Extract recommendation JSON from stderr
REC_JSON=$(grep 'CEILING_REVISIT_JSON' /tmp/ceiling-revisit-meta.txt \
  | sed 's/.*CEILING_REVISIT_JSON \(.*\) -->/\1/')
KEYWORDS_TO_REMOVE=$(echo "$REC_JSON" | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print('|'.join(d['keywords_to_remove']))")
L_NEEDS_ISSUE=$(echo "$REC_JSON" | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print(d['l_bucket_needs_issue'])")
```

## Phase 2 — Post Analysis Comment

```bash
REPORT_BODY=$(cat "$REPORT_FILE")
gh issue comment "$ISSUE_NUM" --repo "$REPO" --body "$REPORT_BODY"
```

## Phase 3 — Open PR if Keyword Changes Warranted

Only execute this phase if `KEYWORDS_TO_REMOVE` is non-empty.

```bash
if [ -n "$KEYWORDS_TO_REMOVE" ]; then
  # Read effective ABOVE_CEILING_KEYWORDS: .archon/.env override takes precedence over scheduler.sh default
  ENV_FILE=".archon/.env"
  if [ -f "$ENV_FILE" ] && grep -q "^ABOVE_CEILING_KEYWORDS=" "$ENV_FILE"; then
    CURRENT=$(grep '^ABOVE_CEILING_KEYWORDS=' "$ENV_FILE" | cut -d= -f2-)
  else
    # Extract default from scheduler.sh — use grep not line number (line may shift with edits)
    CURRENT=$(grep -E '^ABOVE_CEILING_KEYWORDS="\$\{ABOVE_CEILING_KEYWORDS:-' \
      dark-factory/scheduler.sh | sed 's/.*:-\(.*\)"}/\1/')
  fi

  # Compute new value by removing flagged keywords
  NEW_KWS="$CURRENT"
  for KW in $(echo "$KEYWORDS_TO_REMOVE" | tr '|' '\n'); do
    NEW_KWS=$(echo "$NEW_KWS" | sed "s/|${KW}//g;s/${KW}|//g;s/^${KW}$//g")
  done

  # Write .archon/.env (create if not present)
  ENV_FILE=".archon/.env"
  if [ -f "$ENV_FILE" ] && grep -q "^ABOVE_CEILING_KEYWORDS=" "$ENV_FILE"; then
    sed -i "s|^ABOVE_CEILING_KEYWORDS=.*|ABOVE_CEILING_KEYWORDS=${NEW_KWS}|" "$ENV_FILE"
  else
    echo "ABOVE_CEILING_KEYWORDS=${NEW_KWS}" >> "$ENV_FILE"
  fi

  # Create PR branch and open PR
  PR_BRANCH="chore/ceiling-revisit-${UNTIL}"
  git checkout -b "$PR_BRANCH"
  git add "$ENV_FILE"
  git commit -m "chore(env): update ABOVE_CEILING_KEYWORDS per weekly revisit (#${ISSUE_NUM})

  Removing: ${KEYWORDS_TO_REMOVE}
  New value: ${NEW_KWS}

  Analysis window: ${SINCE} → ${UNTIL}
  Decision: n>=5 and keyword success rate >= M_baseline (no discriminative value)."

  git push origin "$PR_BRANCH"
  gh pr create \
    --repo "$REPO" \
    --title "chore(env): update ABOVE_CEILING_KEYWORDS per weekly ceiling revisit" \
    --body "Recommended by weekly dispatch ceiling analysis on issue #${ISSUE_NUM}.

Removes: \`${KEYWORDS_TO_REMOVE}\`

See the analysis comment on #${ISSUE_NUM} for full data and decision rationale.

Closes #${ISSUE_NUM} (if this is the actionable change)." \
    --label "priority: should-have" \
    --base main
fi
```

## Phase 4 — File L-Bucket Code-Change Issue (conditional)

Only execute if `L_NEEDS_ISSUE` is `True`.

```bash
if [ "$L_NEEDS_ISSUE" = "True" ]; then
  gh issue create \
    --repo "$REPO" \
    --title "Revisit L=always-above-ceiling rule in is_above_ceiling() — scheduler.sh" \
    --body "## Purpose

The weekly dispatch ceiling analysis (issue #${ISSUE_NUM}, window ${SINCE}→${UNTIL})
found the L-bucket success rate exceeds 70% at n≥5. The L=always-above-ceiling rule
in \`scheduler.sh\` may be overly conservative.

## What to review

- Inspect \`is_above_ceiling()\` in \`dark-factory/scheduler.sh\` (~line 213).
- Assess whether the L-bucket ceiling should be relaxed (e.g. L+keyword pattern only).
- This is a **code change** (not an env-var change) — requires PR to \`scheduler.sh\`.

## References

- Triggering analysis: issue #${ISSUE_NUM}
- Policy spec: \`docs/superpowers/specs/2026-06-13-dispatch-ceiling-quarterly-revisit-design.md\`

---
*Filed automatically by weekly ceiling revisit*" \
    --label "enhancement" \
    --label "priority: should-have" \
    --label "Dark Factory"
fi
```

## Phase 5 — File Next Weekly Revisit Issue (unconditional)

```bash
NEXT_TITLE="Revisit dispatch ceiling (C9) — re-measure success-by-size/type"
gh issue create \
  --repo "$REPO" \
  --title "$NEXT_TITLE" \
  --body "## Purpose

Weekly revisit of the dispatch ceiling policy introduced in #339.

## What to review

1. Pull Factory Scorecard (#331) success-by-S/M/L numbers for the latest week.
2. Compare against current ABOVE_CEILING_KEYWORDS thresholds.
3. Assess keyword false-positive rate. If high, narrow the list.
4. Recommend \`ABOVE_CEILING_KEYWORDS\` update in \`.archon/.env\` via PR if data warrants.

## References

- Spec: \`docs/superpowers/specs/2026-06-13-dispatch-ceiling-quarterly-revisit-design.md\`
- Archon command: \`.archon/commands/ceiling-revisit.md\`
- Architecture review candidate C9: \`docs/dark-factory-architecture-review-2026-06-11.html\`
- Prior revisit: #${ISSUE_NUM} (comment with results)

## Parameters for the agent

- \`ISSUE_NUM\` = <this issue's number>
- \`SINCE\` = 2026-06-12 (policy introduction date — always fixed)
- \`UNTIL\` = ${NEXT_DATE}
- \`NEXT_DATE\` = <UNTIL + 7 days>

## Target date

**${NEXT_DATE}** (weekly from ${UNTIL}).

---
*Filed automatically by MarketHawk weekly ceiling revisit agent*" \
  --label "enhancement" \
  --label "priority: should-have" \
  --label "size: M" \
  --label "Dark Factory" \
  --label "ready-for-agent"
```
```

**Step 2.3 — Verify the command file is valid Markdown and has required sections**

```bash
grep -c "Phase [1-5]" .archon/commands/ceiling-revisit.md
```

Expected: `5`

```bash
grep "fetch_scorecard.py\|ceiling_revisit.py\|gh issue create\|gh pr create" \
  .archon/commands/ceiling-revisit.md | wc -l
```

Expected: `≥ 4` (all key actions present)

**Step 2.4 — Commit Task 2**

```bash
git add .archon/commands/ceiling-revisit.md
git commit -m "feat(archon): ceiling-revisit command — weekly dispatch ceiling agent prompt (#355)

5-phase command: fetch scorecard, post report comment, open PR if
keyword changes warranted, file L-bucket issue if >70%, file next
weekly revisit issue unconditionally."
```

---

### Task 3 — Run first-week analysis and file next issue

**Files:** (no file changes — GitHub actions only)

This task executes the just-created `ceiling_revisit.py` for the current window
(2026-06-12 → 2026-06-20), posts the analysis to issue #355, and files the next
weekly revisit issue targeting ~2026-06-27.

Note: With only 8 days of data since policy introduction, the n≥5 guard will almost certainly
report "insufficient data — no change" for all keywords. This is the correct and expected
output for week 1 — it establishes a baseline and starts the weekly data accumulation.

**Assumption (Spec Req 4 / week-1 PR gap):** Because n<5 is expected for every keyword in week 1,
no keyword removal or addition will be warranted, and no `.archon/.env` PR will be needed. If
`ceiling_revisit.py --dry-run` surprisingly shows `keywords_to_remove` as non-empty at Step 3.2,
manually follow Task 2 Phase 3 steps to open the PR before running Step 3.3.

#### Steps

**Step 3.1 — Fetch scorecard for the 2026-06-12 → 2026-06-20 window**

```bash
python3 scripts/fetch_scorecard.py \
  --since 2026-06-12 \
  --until 2026-06-20 \
  --output /tmp/ceiling-revisit-w1.json
```

Expected: `/tmp/ceiling-revisit-w1.json` created. If `fetch_scorecard.py` requires
GitHub API access (`gh auth status` should confirm auth), the file will contain
`by_size` and `prs` arrays.

**Step 3.2 — Generate the week-1 report (dry-run preview first)**

```bash
python3 scripts/ceiling_revisit.py \
  --since 2026-06-12 \
  --until 2026-06-20 \
  --scorecard /tmp/ceiling-revisit-w1.json \
  --dry-run
```

Review the output — it should show the bucket table and per-keyword rows with
"insufficient data — no change" for any keyword with n<5.

**Step 3.3 — Post the report to issue #355**

```bash
REPORT=$(python3 scripts/ceiling_revisit.py \
  --since 2026-06-12 \
  --until 2026-06-20 \
  --scorecard /tmp/ceiling-revisit-w1.json)

gh issue comment 355 --repo omniscient/markethawk --body "$REPORT"
```

Expected: comment posted to issue #355. Verify with:

```bash
gh issue view 355 --repo omniscient/markethawk --comments | tail -20
```

**Step 3.4 — File the next weekly revisit issue (~2026-06-27)**

```bash
gh issue create \
  --repo omniscient/markethawk \
  --title "Revisit dispatch ceiling (C9) — re-measure success-by-size/type" \
  --body "## Purpose

Weekly revisit of the dispatch ceiling policy introduced in #339.

## What to review

1. Pull Factory Scorecard (#331) success-by-S/M/L numbers for the cumulative window
   since 2026-06-12 (policy introduction date).
2. Compare against current ABOVE_CEILING_KEYWORDS thresholds.
3. Assess keyword false-positive rate. If high, narrow the list.
4. Recommend \`ABOVE_CEILING_KEYWORDS\` update in \`.archon/.env\` via PR if data warrants.

## References

- Spec: \`docs/superpowers/specs/2026-06-13-dispatch-ceiling-quarterly-revisit-design.md\`
- Archon command: \`.archon/commands/ceiling-revisit.md\`
- Architecture review candidate C9: \`docs/dark-factory-architecture-review-2026-06-11.html\`
- Prior revisit: #355 (week-1 analysis, 2026-06-12 → 2026-06-20)

## Parameters for the agent

- \`ISSUE_NUM\` = <this issue's number>
- \`SINCE\` = 2026-06-12 (policy introduction date — always fixed)
- \`UNTIL\` = 2026-06-27
- \`NEXT_DATE\` = 2026-07-04

## Target date

**2026-06-27** (weekly from 2026-06-20).

---
*Filed automatically by MarketHawk weekly ceiling revisit (issue #355)*" \
  --label "enhancement" \
  --label "priority: should-have" \
  --label "size: M" \
  --label "Dark Factory" \
  --label "ready-for-agent"
```

**Step 3.5 — Verify next issue was created**

```bash
gh issue list --repo omniscient/markethawk \
  --search "Revisit dispatch ceiling" \
  --json number,title \
  --jq '.[] | "\(.number): \(.title)"'
```

Expected: one new issue with "Revisit dispatch ceiling" in the title.

**Step 3.6 — Final integration check**

```bash
# Script is runnable
python3 scripts/ceiling_revisit.py --help

# Unit tests still pass
python3 scripts/test_ceiling_revisit.py

# Command file is in place with all phases
grep -c "Phase [1-5]" .archon/commands/ceiling-revisit.md

echo "All checks passed — Task 3 complete"
```

Expected: help text printed, `Results: 16 passed, 0 failed`, `5`.

Task 3 has no commit step (no file changes — only GitHub actions).

---

## Summary

| Task | Files | Steps | Key Output |
|------|-------|-------|------------|
| 0 — Update spec cadence | `docs/superpowers/specs/2026-06-13-dispatch-ceiling-quarterly-revisit-design.md` | 3 | Spec updated from quarterly to weekly; commit |
| 1 — Analysis script | `scripts/ceiling_revisit.py`, `scripts/test_ceiling_revisit.py` | 6 | 16-assertion unit test suite; dry-run smoke test |
| 2 — Archon command | `.archon/commands/ceiling-revisit.md` | 4 | 5-phase agent command for all future weekly runs |
| 3 — First analysis | (no file changes) | 6 | Week-1 report on issue #355; next-issue filed (~2026-06-27) |

**Total:** 4 tasks, 19 steps.

---

*Plan generated by MarketHawk Refinement Pipeline — 2026-06-20*
