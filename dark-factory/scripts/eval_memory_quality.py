#!/usr/bin/env python3
"""
eval_memory_quality.py — Read-only harness for evaluating Dark Factory memory retrieval quality.

Measures whether memory_retrieve.py surfaces the right lessons for historical factory
regressions recorded in dark-factory/evals/factory-failures.jsonl.

Usage:
    python eval_memory_quality.py \\
        [--failures dark-factory/evals/factory-failures.jsonl] \\
        [--memory-dir .archon/memory] \\
        [--retrieve-script dark-factory/scripts/memory_retrieve.py] \\
        [--output dark-factory/evals/memory-quality-report.md] \\
        [--timestamp 2026-06-30T15:00:00Z]
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# ── Constants ──────────────────────────────────────────────────────────────

PASS_THRESHOLD = 0.5

# Inverse of memory_retrieve.PHASE_SOURCE_MAP
_SOURCE_TO_PHASE = {
    "implement": "implement",
    "conformance": "validate",
    "code-review": "review",
    "refine": "refine",
}

_MEMORY_FILES = [
    "codebase-patterns.md",
    "architecture.md",
    "backend-patterns.md",
    "frontend-patterns.md",
    "dark-factory-ops.md",
]

# Parse: - [TAG] body <!-- meta -->
_ENTRY_RE = re.compile(
    r"^- \[(?P<tag>[^\]]+)\]\s+(?P<body>.+?)(?:\s*<!--(?P<meta>[^>]*)-->)?\s*$"
)
_META_TAG_RE = re.compile(r"(\w+\d*):([^\s>]+)")


# ── Helpers ────────────────────────────────────────────────────────────────

def _parse_meta(meta_str):
    if not meta_str:
        return {}
    return dict(_META_TAG_RE.findall(meta_str))


# ── Scoring functions ─────────────────────────────────────────────────────

def is_infrastructure_failure(postmortem: str) -> bool:
    """True when the postmortem is a session-limit/infra-noise event with no lesson."""
    lower = postmortem.lower()
    return "session limit" in lower and "resets" in lower


def parse_memory_entries(memory_dir: Path) -> list:
    """
    Scan memory .md files for authoritative entries tagged with issue:#NNN.

    Returns list of dicts: {issue_num, body, source_tag, path_tag, source_file}.
    Excludes PROVISIONAL, INVALID, and untagged entries.
    Stops scanning each file at the first '---' separator line.
    """
    entries = []
    for fname in _MEMORY_FILES:
        fpath = Path(memory_dir) / fname
        if not fpath.exists():
            continue
        try:
            text = fpath.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            if line.strip() == "---":
                break
            m = _ENTRY_RE.match(line)
            if not m:
                continue
            tag = m.group("tag").upper()
            if tag.startswith("INVALID") or tag == "PROVISIONAL":
                continue
            meta = _parse_meta(m.group("meta") or "")
            issue_tag = meta.get("issue", "")
            if not issue_tag.startswith("#"):
                continue
            try:
                issue_num = int(issue_tag[1:])
            except ValueError:
                continue
            entries.append({
                "issue_num": issue_num,
                "body": m.group("body").strip(),
                "source_tag": meta.get("source", ""),
                "path_tag": meta.get("path", ""),
                "source_file": fname,
            })
    return entries


def check_hit(entry: dict, output: str) -> bool:
    """True if the entry's body text appears as a substring in the retrieval output."""
    body = entry["body"].strip()
    if not body:
        return False
    return body in output


def filter_and_deduplicate_regressions(regressions: list) -> list:
    """
    Deduplicate by issue_num; drop issues where every postmortem is an infra failure.

    For each issue: keeps the first substantive record encountered.
    Issues where all postmortems are infrastructure failures are excluded.
    """
    by_issue = {}
    for reg in regressions:
        iss = reg["issue"]
        if iss not in by_issue:
            by_issue[iss] = {"has_substantive": False, "record": reg}
        if not is_infrastructure_failure(reg["postmortem"]):
            if not by_issue[iss]["has_substantive"]:
                by_issue[iss]["has_substantive"] = True
                by_issue[iss]["record"] = reg
    return [info["record"] for info in by_issue.values() if info["has_substantive"]]


def compute_scorecard(cases: list) -> dict:
    """
    Compute recall-based scorecard over evaluated cases.

    Each case must have: has_memory_entry (bool), hit (bool|None).
    Returns: {total_n, scorable_n, hits_n, recall, passed, corpus_gap_n, corpus_gap_pct}.
    """
    total_n = len(cases)
    scorable = [c for c in cases if c.get("has_memory_entry")]
    gap = [c for c in cases if not c.get("has_memory_entry")]
    scorable_n = len(scorable)
    hits_n = sum(1 for c in scorable if c.get("hit"))
    recall = hits_n / scorable_n if scorable_n > 0 else 0.0
    corpus_gap_n = len(gap)
    corpus_gap_pct = corpus_gap_n / total_n if total_n > 0 else 0.0
    return {
        "total_n": total_n,
        "scorable_n": scorable_n,
        "hits_n": hits_n,
        "recall": recall,
        "passed": recall >= PASS_THRESHOLD,
        "corpus_gap_n": corpus_gap_n,
        "corpus_gap_pct": corpus_gap_pct,
    }


# ── Harness runner ─────────────────────────────────────────────────────────

def run_eval(failures_path: Path, memory_dir: Path, retrieve_script: Path) -> tuple:
    """
    Run full eval: load regressions, find ground truth, call memory_retrieve.py.

    Returns (cases, filtered_count, scorecard).
    For each unique substantive regression, HIT if ANY matching memory entry is surfaced.
    """
    regressions = []
    with open(failures_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                regressions.append(json.loads(line))

    total_raw = len(regressions)
    substantive = filter_and_deduplicate_regressions(regressions)
    filtered_count = total_raw - len(substantive)

    memory_entries = parse_memory_entries(memory_dir)
    gt_by_issue = {}
    for e in memory_entries:
        gt_by_issue.setdefault(e["issue_num"], []).append(e)

    cases = []
    for reg in substantive:
        issue_num = reg["issue"]
        matching = gt_by_issue.get(issue_num, [])
        has_memory_entry = len(matching) > 0

        hit = None
        if has_memory_entry:
            hit = False
            for entry in matching:
                phase = _SOURCE_TO_PHASE.get(entry["source_tag"])
                if phase is None:
                    continue
                try:
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(retrieve_script),
                            "--phase", phase,
                            "--files", entry["path_tag"] or "",
                            "--memory-dir", str(memory_dir),
                        ],
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    if check_hit(entry, result.stdout):
                        hit = True
                        break
                except (subprocess.TimeoutExpired, OSError):
                    continue

        cases.append({
            "issue_num": issue_num,
            "title": reg.get("title", ""),
            "has_memory_entry": has_memory_entry,
            "hit": hit,
            "memory_entries_count": len(matching),
        })

    scorecard = compute_scorecard(cases)
    return cases, filtered_count, scorecard


# ── Report writer ─────────────────────────────────────────────────────────

def write_report(
    cases: list,
    filtered_count: int,
    scorecard: dict,
    output_path: Path,
    timestamp: str = "",
) -> None:
    """Write the memory quality scorecard report to output_path."""
    recall_pct = f"{scorecard['recall']:.1%}"
    verdict = "PASS" if scorecard["passed"] else "FAIL"
    gap_pct = f"{scorecard['corpus_gap_pct']:.1%}"

    lines = [
        "# Dark Factory Memory Quality Report",
        "",
        f"Generated: {timestamp}",
        "",
        "## Scorecard",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total substantive regressions | {scorecard['total_n']} |",
        f"| Scorable (memory entry exists) | {scorecard['scorable_n']} |",
        f"| Hits (entry surfaced by retrieval) | {scorecard['hits_n']} |",
        f"| Recall | {recall_pct} ({verdict}) |",
        f"| Corpus gap (no memory entry) | {scorecard['corpus_gap_n']} ({gap_pct}) |",
        f"| Pass threshold | {PASS_THRESHOLD:.0%} |",
        f"| Filtered (session-limit infra noise) | {filtered_count} |",
        "",
        "## Per-Case Results",
        "",
        "| Issue | Title | Has Memory Entry | Hit |",
        "|-------|-------|-----------------|-----|",
    ]

    for c in sorted(cases, key=lambda x: x["issue_num"]):
        has = "YES" if c["has_memory_entry"] else "NO"
        if c["hit"] is True:
            hit_str = "YES"
        elif c["hit"] is False:
            hit_str = "NO"
        else:
            hit_str = "-"
        title = c["title"][:60]
        lines.append(f"| #{c['issue_num']} | {title} | {has} | {hit_str} |")

    lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-8")


# ── CLI ────────────────────────────────────────────────────────────────────

def main():
    repo_root = Path(__file__).parent.parent.parent

    parser = argparse.ArgumentParser(
        description="Evaluate Dark Factory memory retrieval quality."
    )
    parser.add_argument(
        "--failures",
        default=str(repo_root / "dark-factory/evals/factory-failures.jsonl"),
        help="Path to factory-failures.jsonl",
    )
    parser.add_argument(
        "--memory-dir",
        default=str(repo_root / ".archon/memory"),
        help="Path to the memory directory",
    )
    parser.add_argument(
        "--retrieve-script",
        default=str(Path(__file__).parent / "memory_retrieve.py"),
        help="Path to memory_retrieve.py",
    )
    parser.add_argument(
        "--output",
        default=str(repo_root / "dark-factory/evals/memory-quality-report.md"),
        help="Output path for the report",
    )
    parser.add_argument(
        "--timestamp",
        default="",
        help="Timestamp string for the report header (default: current UTC time)",
    )
    args = parser.parse_args()

    if not args.timestamp:
        from datetime import datetime, timezone
        args.timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    failures_path = Path(args.failures)
    memory_dir = Path(args.memory_dir)
    retrieve_script = Path(args.retrieve_script)
    output_path = Path(args.output)

    if not failures_path.exists():
        sys.stderr.write(f"error: failures file not found: {failures_path}\n")
        sys.exit(1)
    if not memory_dir.exists():
        sys.stderr.write(f"error: memory directory not found: {memory_dir}\n")
        sys.exit(1)
    if not retrieve_script.exists():
        sys.stderr.write(f"error: retrieve script not found: {retrieve_script}\n")
        sys.exit(1)

    print(f"Loading regressions from: {failures_path}", file=sys.stderr)
    print(f"Memory dir: {memory_dir}", file=sys.stderr)

    cases, filtered_count, scorecard = run_eval(failures_path, memory_dir, retrieve_script)

    print(f"Evaluated {scorecard['total_n']} substantive regressions", file=sys.stderr)
    print(
        f"Recall: {scorecard['recall']:.1%} over {scorecard['scorable_n']} scorable "
        f"({'PASS' if scorecard['passed'] else 'FAIL'})",
        file=sys.stderr,
    )
    print(
        f"Corpus gap: {scorecard['corpus_gap_n']}/{scorecard['total_n']} issues "
        f"have no memory entry",
        file=sys.stderr,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_report(cases, filtered_count, scorecard, output_path, args.timestamp)
    print(f"Report written to: {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
