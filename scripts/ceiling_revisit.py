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
from collections import Counter
from pathlib import Path

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
    triad: dict[str, int] = {"merged_clean": 0, "merged_with_edits": 0, "closed": 0, "open": 0}
    for p in cohort:
        cls = p.get("classification", "open")
        if cls in triad:
            triad[cls] += 1
    n = _decided(triad)
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
    """Find recurring word tokens in closed M-PRs not already covered by current_keywords
    with >=5 occurrences — all closed implies rate=0.0, which is >=15pt below any positive
    m_baseline. Returns list of {keyword, n, decision} dicts."""
    existing = [kw.strip() for kw in current_keywords.split("|") if kw.strip()]
    closed_m = [p for p in prs if p.get("size") == "M" and p.get("classification") == "closed"]
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
        rate = 0.0
        if rate < m_baseline - 0.15:
            candidates.append({"keyword": token, "n": n, "decision": "add candidate"})
    return candidates


def _decided(triad: dict) -> int:
    return triad["merged_clean"] + triad["merged_with_edits"] + triad["closed"]


def build_bucket_table(by_size: dict) -> dict:
    """Compute per-bucket success rates; merge XL into L+XL for reporting.

    n = decided count (excludes open PRs — in-flight are not yet determined).
    """
    result = {}
    for bucket in ("S", "M"):
        triad = by_size.get(
            bucket, {"merged_clean": 0, "merged_with_edits": 0, "closed": 0, "open": 0}
        )
        rate = success_rate(triad)
        result[bucket] = {"rate": rate, "n": _decided(triad), **triad}
    l_triad: dict[str, int] = {"merged_clean": 0, "merged_with_edits": 0, "closed": 0, "open": 0}
    for b in ("L", "XL"):
        t = by_size.get(b, {})
        for k in l_triad:
            l_triad[k] += t.get(k, 0)
    result["L+XL"] = {"rate": success_rate(l_triad), "n": _decided(l_triad), **l_triad}
    return result


def _fmt_rate(rate: float | None) -> str:
    return f"{rate:.1%}" if rate is not None else "N/A"


def generate_report(
    since: str,
    until: str,
    scorecard_path: str,
    keywords: str = DEFAULT_KEYWORDS,
) -> tuple[str, list[str], list[dict], bool]:
    """Return (markdown_report, keywords_to_remove, new_keyword_candidates, l_bucket_needs_issue)."""
    with open(scorecard_path) as f:
        data = json.load(f)

    by_size = data.get("by_size", {})
    prs = data.get("prs", [])

    bucket_table = build_bucket_table(by_size)
    m_baseline = bucket_table["M"]["rate"]

    kw_list = [kw.strip() for kw in keywords.split("|") if kw.strip()]
    kw_rows = [build_keyword_analysis(prs, kw, m_baseline or 0.0) for kw in kw_list]

    keywords_to_remove = [r["keyword"] for r in kw_rows if r["decision"] == "remove"]
    new_keyword_candidates = find_new_keyword_candidates(prs, keywords, m_baseline or 0.0)

    l_data = bucket_table["L+XL"]
    l_rate = l_data["rate"]
    l_n = l_data["n"]
    l_bucket_needs_issue = bool(l_rate is not None and l_rate > 0.70 and l_n >= 5)

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

    lines += [
        "### L-Bucket Observation",
        "",
    ]
    if l_rate is not None:
        lines.append(f"L+XL success rate: {_fmt_rate(l_rate)} (n={l_n}). ")
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

    rec = {
        "keywords_to_remove": to_remove,
        "new_keyword_candidates": [c["keyword"] for c in new_candidates],
        "l_bucket_needs_issue": l_needs_issue,
    }
    print("\n<!-- CEILING_REVISIT_JSON", json.dumps(rec), "-->", file=sys.stderr)


if __name__ == "__main__":
    main()
