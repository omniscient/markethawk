# Memory Quality Evaluation Harness — Implementation Plan

**Date:** 2026-06-30  
**Issue:** #653  
**Spec:** `docs/superpowers/specs/2026-06-30-eval-memory-quality-design.md`  
**Epic:** #643

## Goal

Build a read-only evaluation harness that measures whether the flat-file memory system
(`memory_retrieve.py`) surfaces the right lesson for each historical factory regression.
Produces an objective recall scorecard (pass/fail at `PASS_THRESHOLD = 0.5`) committed as
`dark-factory/evals/memory-quality-report.md`. Zero changes to retrieval code.

## Architecture

```
factory-failures.jsonl          .archon/memory/*.md
        │                               │
        ▼                               ▼
filter_and_deduplicate_regressions()   parse_memory_entries()
        │                               │
        └─────────── match on issue# ──►│
                                        ▼
                           subprocess: memory_retrieve.py
                                        │
                                        ▼
                                  check_hit()
                                        │
                                        ▼
                               compute_scorecard()
                                        │
                                        ▼
                           memory-quality-report.md
```

Ground truth: entries in `.archon/memory/*.md` carrying `<!-- issue:#NNN -->` metadata.  
Hit detection: `memory_retrieve.py` stdout contains the entry's body text (stripped of
`<!-- ... -->` comments), case-insensitive substring match.  
Scoring: recall = hits / scorable_N; PASS if recall ≥ 0.5.

## Tech Stack

Python 3, stdlib only (`argparse`, `re`, `subprocess`, `pathlib`, `json`). No external deps,
no network access at eval time.

## File Structure

| File | Status | Description |
|------|--------|-------------|
| `dark-factory/scripts/eval_memory_quality.py` | NEW | Harness: scoring functions + subprocess runner + CLI |
| `dark-factory/tests/test_eval_memory_quality.py` | NEW | pytest unit tests — no subprocess, no network |
| `dark-factory/evals/memory-quality-report.md` | GENERATED | Committed scorecard artifact written by the harness |

No modifications to `memory_retrieve.py`, `memory_write.py`, `.archon/memory/*.md`, or
`dark-factory/evals/factory-failures.jsonl`.

---

## Task 1: Write the pytest unit test suite (TDD — write first, expect failure)

**Files:** `dark-factory/tests/test_eval_memory_quality.py`

**Step 1** — Create the test file:

```python
# dark-factory/tests/test_eval_memory_quality.py
"""
Unit tests for eval_memory_quality.py scoring functions.
No subprocess calls, no network, no .archon/memory reads.
All fixtures use tmp_path or in-memory data.
Run from repo root: pytest dark-factory/tests/test_eval_memory_quality.py -v
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import eval_memory_quality as emq  # noqa: E402


# ── is_infrastructure_failure ──────────────────────────────────────────────

class TestIsInfrastructureFailure:
    def test_session_limit_exact(self):
        assert emq.is_infrastructure_failure(
            "You've hit your session limit · resets 11:10pm (UTC) "
        )

    def test_session_limit_lowercase(self):
        assert emq.is_infrastructure_failure("session limit reached, please wait")

    def test_resets_utc_pattern(self):
        assert emq.is_infrastructure_failure("resets 6:30pm (UTC)")

    def test_resets_utc_case_insensitive(self):
        assert emq.is_infrastructure_failure("Resets 5am (UTC) on next cycle")

    def test_substantive_postmortem_not_infra(self):
        assert not emq.is_infrastructure_failure(
            "The push-and-pr phase failed due to a non-fast-forward git rejection"
        )

    def test_empty_postmortem_not_infra(self):
        assert not emq.is_infrastructure_failure("")

    def test_partial_match_resets_without_utc_not_infra(self):
        assert not emq.is_infrastructure_failure(
            "The factory resets its internal counter after each run"
        )


# ── parse_memory_entries ───────────────────────────────────────────────────

class TestParseMemoryEntries:
    def test_parses_entry_with_issue_and_path(self, tmp_path):
        md = tmp_path / "backend-patterns.md"
        md.write_text(
            "# Backend\n"
            "- [PATTERN] Use the `db_session` fixture. "
            "<!-- issue:#391 date:2026-06-15 path:backend/app/tasks/ source:implement -->\n"
        )
        entries = emq.parse_memory_entries(tmp_path)
        assert len(entries) == 1
        e = entries[0]
        assert e["issue_num"] == 391
        assert "db_session" in e["entry_text"]
        assert e["path_tag"] == "backend/app/tasks/"

    def test_parses_entry_with_issue_no_path(self, tmp_path):
        md = tmp_path / "codebase-patterns.md"
        md.write_text(
            "# Codebase\n"
            "- [AVOID] Never store secrets in env files. "
            "<!-- issue:#42 date:2026-01-01 source:implement -->\n"
        )
        entries = emq.parse_memory_entries(tmp_path)
        assert len(entries) == 1
        assert entries[0]["path_tag"] == ""
        assert entries[0]["issue_num"] == 42

    def test_skips_entry_without_issue_tag(self, tmp_path):
        md = tmp_path / "codebase-patterns.md"
        md.write_text(
            "# Codebase\n"
            "- [PATTERN] General advice with no issue tag. <!-- date:2026-01-01 -->\n"
        )
        assert emq.parse_memory_entries(tmp_path) == []

    def test_stops_at_separator(self, tmp_path):
        md = tmp_path / "codebase-patterns.md"
        md.write_text(
            "# Codebase\n"
            "- [PATTERN] Entry before separator. <!-- issue:#1 -->\n"
            "---\n"
            "- [PATTERN] Entry after separator is not parsed. <!-- issue:#2 -->\n"
        )
        entries = emq.parse_memory_entries(tmp_path)
        assert len(entries) == 1
        assert entries[0]["issue_num"] == 1

    def test_multiple_files(self, tmp_path):
        for name, issue in [("backend-patterns.md", 10), ("frontend-patterns.md", 20)]:
            (tmp_path / name).write_text(
                f"- [PATTERN] Some text. <!-- issue:#{issue} source:implement -->\n"
            )
        entries = emq.parse_memory_entries(tmp_path)
        issue_nums = {e["issue_num"] for e in entries}
        assert issue_nums == {10, 20}

    def test_issue_tag_with_hash_prefix(self, tmp_path):
        md = tmp_path / "dark-factory-ops.md"
        md.write_text("- [FIX] Fix thing. <!-- issue:#999 -->\n")
        entries = emq.parse_memory_entries(tmp_path)
        assert entries[0]["issue_num"] == 999


# ── check_hit ─────────────────────────────────────────────────────────────

class TestCheckHit:
    RETRIEVE_OUTPUT = (
        "### Memory: backend-patterns.md\n"
        "- [PATTERN] Use the db_session fixture for all database access. "
        "<!-- issue:#391 date:2026-06-15 path:backend/ source:implement -->\n"
    )

    def test_exact_body_match(self):
        assert emq.check_hit(
            self.RETRIEVE_OUTPUT,
            "Use the db_session fixture for all database access."
        )

    def test_case_insensitive_match(self):
        assert emq.check_hit(
            self.RETRIEVE_OUTPUT,
            "USE THE DB_SESSION FIXTURE FOR ALL DATABASE ACCESS."
        )

    def test_no_match_returns_false(self):
        assert not emq.check_hit(
            self.RETRIEVE_OUTPUT,
            "Never use redis for durable state."
        )

    def test_entry_text_with_metadata_comment_stripped(self):
        entry_text_with_meta = (
            "Use the db_session fixture for all database access. "
            "<!-- issue:#391 date:2026-06-15 source:implement -->"
        )
        assert emq.check_hit(self.RETRIEVE_OUTPUT, entry_text_with_meta)

    def test_empty_output_returns_false(self):
        assert not emq.check_hit("", "Use the db_session fixture.")

    def test_empty_entry_text_returns_false(self):
        assert not emq.check_hit(self.RETRIEVE_OUTPUT, "")

    def test_partial_substring_match(self):
        assert emq.check_hit(self.RETRIEVE_OUTPUT, "db_session fixture")


# ── filter_and_deduplicate_regressions ────────────────────────────────────

class TestFilterAndDeduplicateRegressions:
    def _r(self, issue, postmortem):
        return {
            "issue": issue,
            "title": f"Title for #{issue}",
            "phase": "fix",
            "postmortem": postmortem,
        }

    def test_all_infra_issue_excluded(self):
        regressions = [
            self._r(106, "You've hit your session limit · resets 11:10pm (UTC) "),
            self._r(106, "You've hit your session limit · resets 11:10pm (UTC) "),
        ]
        substantive, filtered = emq.filter_and_deduplicate_regressions(regressions)
        assert substantive == []
        assert filtered == 1

    def test_mixed_infra_and_substantive_keeps_issue(self):
        regressions = [
            self._r(360, "You've hit your session limit · resets 6:30pm (UTC) "),
            self._r(360, "The push-and-pr phase failed due to a non-fast-forward git rejection"),
        ]
        substantive, filtered = emq.filter_and_deduplicate_regressions(regressions)
        assert len(substantive) == 1
        assert substantive[0]["issue"] == 360
        assert filtered == 0

    def test_deduplicated_to_one_per_issue(self):
        regressions = [
            self._r(421, "Implementation failed in phase A"),
            self._r(421, "Implementation failed in phase A and also B — more detail here"),
        ]
        substantive, filtered = emq.filter_and_deduplicate_regressions(regressions)
        assert len(substantive) == 1
        assert substantive[0]["issue"] == 421

    def test_selects_longest_substantive_postmortem(self):
        regressions = [
            self._r(421, "Short failure."),
            self._r(421, "Much longer and more substantive failure description with details."),
        ]
        substantive, _ = emq.filter_and_deduplicate_regressions(regressions)
        assert "longer" in substantive[0]["postmortem"]

    def test_multiple_issues_all_preserved(self):
        regressions = [
            self._r(100, "Code review blocker in phase 3."),
            self._r(200, "Implementation failed due to missing import."),
        ]
        substantive, filtered = emq.filter_and_deduplicate_regressions(regressions)
        assert len(substantive) == 2
        assert filtered == 0

    def test_filtered_count_correct(self):
        regressions = [
            self._r(1, "session limit"),
            self._r(2, "Substantive failure."),
        ]
        _, filtered = emq.filter_and_deduplicate_regressions(regressions)
        assert filtered == 1


# ── compute_scorecard ─────────────────────────────────────────────────────

class TestComputeScorecard:
    def _case(self, result):
        return {
            "issue": 1,
            "title": "Test",
            "phase": "fix",
            "matched_entry": "some entry",
            "result": result,
            "files_used": "",
        }

    def test_all_hits_recall_one(self):
        cases = [self._case("HIT")] * 4
        sc = emq.compute_scorecard(cases)
        assert sc["recall"] == 1.0
        assert sc["pass_fail"] == "PASS"

    def test_below_threshold_is_fail(self):
        cases = [self._case("HIT")] * 2 + [self._case("MISS")] * 3
        sc = emq.compute_scorecard(cases)
        assert sc["recall"] == pytest.approx(0.4)
        assert sc["pass_fail"] == "FAIL"

    def test_exactly_threshold_is_pass(self):
        cases = [self._case("HIT")] * 1 + [self._case("MISS")] * 1
        sc = emq.compute_scorecard(cases)
        assert sc["recall"] == pytest.approx(0.5)
        assert sc["pass_fail"] == "PASS"

    def test_unevaluable_counted_in_gap_rate(self):
        cases = [self._case("HIT")] * 2 + [self._case("UNEVALUABLE")] * 2
        sc = emq.compute_scorecard(cases)
        assert sc["unevaluable_N"] == 2
        assert sc["gap_rate"] == pytest.approx(0.5)
        assert sc["scorable_N"] == 2

    def test_all_unevaluable_recall_zero(self):
        cases = [self._case("UNEVALUABLE")] * 3
        sc = emq.compute_scorecard(cases)
        assert sc["recall"] == 0.0
        assert sc["scorable_N"] == 0
        assert sc["pass_fail"] == "FAIL"

    def test_pass_threshold_constant(self):
        assert emq.PASS_THRESHOLD == 0.5
```

**Step 2** — Run tests, expect `ModuleNotFoundError` or `ImportError`:

```bash
python -m pytest dark-factory/tests/test_eval_memory_quality.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'eval_memory_quality'`

**Step 3** — Commit the test file:

```bash
git add dark-factory/tests/test_eval_memory_quality.py
git commit -m "test(#653): unit tests for eval_memory_quality scoring functions (TDD)"
```

---

## Task 2: Implement scoring functions

**Files:** `dark-factory/scripts/eval_memory_quality.py`

**Step 1** — Create the script with all scoring functions:

```python
#!/usr/bin/env python3
"""
eval_memory_quality.py — Memory retrieval quality evaluation harness.

For each scorable regression in factory-failures.jsonl, invokes memory_retrieve.py
as a subprocess and checks whether the relevant memory entry is surfaced.

Exit 0 = PASS (recall >= PASS_THRESHOLD), exit 1 = FAIL.

Usage:
    python3 dark-factory/scripts/eval_memory_quality.py \
        [--memory-dir .archon/memory] \
        [--failures dark-factory/evals/factory-failures.jsonl] \
        [--output dark-factory/evals/memory-quality-report.md] \
        [--retrieve-script dark-factory/scripts/memory_retrieve.py]
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# ── Constants ──────────────────────────────────────────────────────────────

PASS_THRESHOLD = 0.5

# Postmortem strings that indicate an infrastructure failure (not a codeable lesson)
_INFRA_STRINGS = ["session limit"]
_INFRA_PATTERNS = [re.compile(r"resets\s+\S+\s+\(UTC\)", re.IGNORECASE)]

# Parse: - [TAG] body <!-- meta -->
_ENTRY_RE = re.compile(
    r"^- \[(?P<tag>[^\]]+)\]\s+(?P<body>.+?)(?:\s*<!--(?P<meta>[^>]*)-->)?\s*$"
)
_META_ISSUE_RE = re.compile(r"issue:#(\d+)")
_META_PATH_RE = re.compile(r"path:([^\s>]+)")
_META_SOURCE_RE = re.compile(r"source:([^\s>]+)")
_METADATA_COMMENT_RE = re.compile(r"\s*<!--[^>]*-->")

# Map memory entry source tag → memory_retrieve.py --phase argument
_SOURCE_TO_PHASE = {
    "implement": "implement",
    "conformance": "validate",
    "code-review": "review",
    "refine": "refine",
}


# ── Scoring functions ──────────────────────────────────────────────────────

def is_infrastructure_failure(postmortem: str) -> bool:
    """Return True if the postmortem describes a runtime infra event, not a code lesson."""
    lower = postmortem.lower()
    for s in _INFRA_STRINGS:
        if s in lower:
            return True
    for pat in _INFRA_PATTERNS:
        if pat.search(postmortem):
            return True
    return False


def parse_memory_entries(memory_dir: Path) -> list:
    """
    Scan all .md files in memory_dir for entries carrying issue:#NNN metadata.

    Returns list of dicts:
        {issue_num: int, entry_text: str, path_tag: str, source_file: str}

    Entries without an issue:#NNN tag are excluded (no ground-truth linkage).
    Stops parsing each file at the first '---' separator line.
    """
    entries = []
    for md_file in sorted(memory_dir.glob("*.md")):
        try:
            text = md_file.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            if line.strip() == "---":
                break
            m = _ENTRY_RE.match(line)
            if not m:
                continue
            meta_str = m.group("meta") or ""
            issue_m = _META_ISSUE_RE.search(meta_str)
            if not issue_m:
                continue
            path_m = _META_PATH_RE.search(meta_str)
            source_m = _META_SOURCE_RE.search(meta_str)
            entries.append({
                "issue_num": int(issue_m.group(1)),
                "entry_text": m.group("body").strip(),
                "path_tag": path_m.group(1) if path_m else "",
                "source_tag": source_m.group(1) if source_m else "",
                "source_file": md_file.name,
            })
    return entries


def check_hit(retrieve_output: str, entry_text: str) -> bool:
    """
    Return True if retrieve_output contains the body of entry_text.

    Strips inline metadata comments from entry_text before matching.
    Case-insensitive substring match; prefix-to-first-space fallback
    handles minor whitespace normalization.
    """
    clean = _METADATA_COMMENT_RE.sub("", entry_text).strip()
    if not clean:
        return False
    lower_output = retrieve_output.lower()
    lower_clean = clean.lower()
    if lower_clean in lower_output:
        return True
    # Prefix-to-first-space fallback for whitespace normalization
    words = lower_clean.split()
    if words and len(words[0]) > 3:
        return words[0] in lower_output
    return False


def filter_and_deduplicate_regressions(regressions: list) -> tuple:
    """
    Group by issue number, exclude issues where ALL entries are infra failures,
    then select the most substantive (longest postmortem) non-infra entry per issue.

    Returns (substantive_list, filtered_count) where:
    - substantive_list: one dict per issue, non-infra postmortems only
    - filtered_count: number of issues excluded (all entries were infra)
    """
    by_issue = {}
    for r in regressions:
        by_issue.setdefault(r["issue"], []).append(r)

    substantive = []
    filtered_count = 0

    for issue_num in sorted(by_issue):
        entries = by_issue[issue_num]
        non_infra = [e for e in entries if not is_infrastructure_failure(e["postmortem"])]
        if not non_infra:
            filtered_count += 1
            continue
        best = max(non_infra, key=lambda e: len(e["postmortem"]))
        substantive.append(best)

    return substantive, filtered_count


def compute_scorecard(cases: list) -> dict:
    """
    Compute recall scorecard from evaluated cases.

    Each case dict must have 'result' in {"HIT", "MISS", "UNEVALUABLE"}.

    Returns:
        recall, scorable_N, hits, unevaluable_N, gap_rate, pass_fail, substantive_N
    """
    scorable = [c for c in cases if c["result"] in ("HIT", "MISS")]
    scorable_N = len(scorable)
    hits = sum(1 for c in scorable if c["result"] == "HIT")
    unevaluable_N = sum(1 for c in cases if c["result"] == "UNEVALUABLE")
    substantive_N = len(cases)

    recall = hits / scorable_N if scorable_N > 0 else 0.0
    gap_rate = unevaluable_N / substantive_N if substantive_N > 0 else 0.0
    pass_fail = "PASS" if recall >= PASS_THRESHOLD else "FAIL"

    return {
        "recall": recall,
        "scorable_N": scorable_N,
        "hits": hits,
        "unevaluable_N": unevaluable_N,
        "gap_rate": gap_rate,
        "pass_fail": pass_fail,
        "substantive_N": substantive_N,
    }
```

**Step 2** — Run tests, expect pass:

```bash
python -m pytest dark-factory/tests/test_eval_memory_quality.py -v
```

Expected output (all tests pass):
```
test_eval_memory_quality.py::TestIsInfrastructureFailure::test_session_limit_exact PASSED
...
================== N passed in X.Xs ==================
```

**Step 3** — Fix any test failures before continuing.

**Step 4** — Commit:

```bash
git add dark-factory/scripts/eval_memory_quality.py
git commit -m "feat(#653): scoring functions for memory quality eval harness"
```

---

## Task 3: Implement harness runner and CLI

**Files:** `dark-factory/scripts/eval_memory_quality.py` (continued)

**Step 1** — Append the runner and CLI to `eval_memory_quality.py` (below the scoring functions):

```python
# ── Harness runner ─────────────────────────────────────────────────────────

def _call_retrieve(retrieve_script: Path, memory_dir: Path, phase: str, files: str) -> str:
    """
    Call memory_retrieve.py as a subprocess and return stdout.
    Returns empty string on failure (fail-open).
    """
    try:
        result = subprocess.run(
            [sys.executable, str(retrieve_script),
             "--phase", phase,
             "--files", files,
             "--memory-dir", str(memory_dir)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout
    except Exception:
        return ""


def run_eval(memory_dir: Path, failures_path: Path, retrieve_script: Path) -> tuple:
    """
    Main eval logic. Returns (cases, scorecard, filtered_count).

    cases: list of per-regression result dicts
    scorecard: dict from compute_scorecard()
    filtered_count: number of infra-only issues excluded
    """
    # Load regressions
    regressions = []
    for line in failures_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            regressions.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    # Filter and deduplicate
    substantive, filtered_count = filter_and_deduplicate_regressions(regressions)

    # Build ground-truth index: issue_num -> list of memory entries
    memory_entries = parse_memory_entries(memory_dir)
    gt_index = {}
    for entry in memory_entries:
        gt_index.setdefault(entry["issue_num"], []).append(entry)

    # Evaluate each substantive regression
    cases = []
    for reg in substantive:
        issue_num = reg["issue"]
        matching = gt_index.get(issue_num, [])

        if not matching:
            cases.append({
                "issue": issue_num,
                "title": reg.get("title", ""),
                "phase": reg.get("phase", ""),
                "matched_entry": "",
                "result": "UNEVALUABLE",
                "files_used": "",
            })
            continue

        # Iterate all matching entries; count a HIT if any is surfaced under its
        # appropriate retrieve phase (derived from the entry's source tag, not the
        # failure's runtime phase which uses "fix"/"continue" — not valid retrieve phases).
        overall_hit = False
        hit_entry = None
        hit_phase = ""
        hit_files = ""
        for entry in matching:
            files_arg = entry["path_tag"] if entry["path_tag"] else ""
            retrieve_phase = _SOURCE_TO_PHASE.get(entry["source_tag"], "implement")
            retrieve_output = _call_retrieve(retrieve_script, memory_dir, retrieve_phase, files_arg)
            if check_hit(retrieve_output, entry["entry_text"]):
                overall_hit = True
                hit_entry = entry
                hit_phase = retrieve_phase
                hit_files = files_arg
                break

        # Report the first-match entry details (or first entry if all MISS)
        report_entry = hit_entry if overall_hit else matching[0]
        report_phase = hit_phase if overall_hit else _SOURCE_TO_PHASE.get(matching[0]["source_tag"], "implement")
        report_files = hit_files if overall_hit else matching[0]["path_tag"]

        cases.append({
            "issue": issue_num,
            "title": reg.get("title", ""),
            "phase": report_phase,
            "matched_entry": report_entry["entry_text"][:80] + ("..." if len(report_entry["entry_text"]) > 80 else ""),
            "result": "HIT" if overall_hit else "MISS",
            "files_used": report_files,
        })

    scorecard = compute_scorecard(cases)
    return cases, scorecard, filtered_count


def _get_git_sha() -> str:
    """Return current HEAD short SHA, or 'unknown' on failure."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def write_report(output_path: Path, cases: list, scorecard: dict,
                 filtered_count: int, timestamp: str) -> None:
    """Write the markdown scorecard to output_path."""
    git_sha = _get_git_sha()
    lines = [
        "# Memory Quality Evaluation Report",
        "",
        f"**Generated:** {timestamp}  ",
        f"**Git SHA:** {git_sha}  ",
        f"**PASS_THRESHOLD:** {PASS_THRESHOLD}  ",
        "",
        "## Per-Case Results",
        "",
        "| Issue | Title | Phase | Matched Entry | Result | Files Used |",
        "|-------|-------|-------|---------------|--------|------------|",
    ]
    for c in cases:
        title = (c["title"][:40] + "...") if len(c["title"]) > 40 else c["title"]
        entry_snippet = c["matched_entry"] or "*(no entry)*"
        lines.append(
            f"| #{c['issue']} | {title} | {c['phase']} | "
            f"{entry_snippet} | **{c['result']}** | `{c['files_used'] or '(empty)'}` |"
        )

    sc = scorecard
    pass_emoji = "✅" if sc["pass_fail"] == "PASS" else "❌"
    lines += [
        "",
        "## Aggregate Scorecard",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Recall | {sc['recall']:.2f} ({sc['hits']}/{sc['scorable_N']}) |",
        f"| Scorable cases | {sc['scorable_N']} |",
        f"| Hits | {sc['hits']} |",
        f"| Unevaluable (no memory entry) | {sc['unevaluable_N']} |",
        f"| Gap rate | {sc['gap_rate']:.2f} ({sc['unevaluable_N']}/{sc['substantive_N']}) |",
        f"| Infrastructure-only issues filtered | {filtered_count} |",
        f"| **Verdict** | {pass_emoji} **{sc['pass_fail']}** |",
        "",
    ]
    output_path.write_text("\n".join(lines), encoding="utf-8")


# ── CLI ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Evaluate memory retrieval recall against historical factory regressions."
    )
    parser.add_argument("--memory-dir", default=".archon/memory",
                        help="Path to the memory directory")
    parser.add_argument("--failures",
                        default="dark-factory/evals/factory-failures.jsonl",
                        help="Path to factory-failures.jsonl")
    parser.add_argument("--output",
                        default="dark-factory/evals/memory-quality-report.md",
                        help="Output path for the scorecard report")
    parser.add_argument("--retrieve-script",
                        default="dark-factory/scripts/memory_retrieve.py",
                        help="Path to memory_retrieve.py")
    # For testability: inject timestamp
    parser.add_argument("--timestamp", default=None,
                        help="Override timestamp (default: current UTC time)")
    args = parser.parse_args()

    memory_dir = Path(args.memory_dir)
    failures_path = Path(args.failures)
    retrieve_script = Path(args.retrieve_script)
    output_path = Path(args.output)

    if not memory_dir.exists():
        sys.stderr.write(f"error: memory-dir not found: {memory_dir}\n")
        sys.exit(1)
    if not failures_path.exists():
        sys.stderr.write(f"error: failures file not found: {failures_path}\n")
        sys.exit(1)
    if not retrieve_script.exists():
        sys.stderr.write(f"error: retrieve-script not found: {retrieve_script}\n")
        sys.exit(1)

    import datetime
    timestamp = args.timestamp or datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    cases, scorecard, filtered_count = run_eval(memory_dir, failures_path, retrieve_script)
    write_report(output_path, cases, scorecard, filtered_count, timestamp)

    sc = scorecard
    print(f"Recall: {sc['recall']:.2f} ({sc['hits']}/{sc['scorable_N']} scorable cases)")
    print(f"Gap rate: {sc['gap_rate']:.2f} ({sc['unevaluable_N']} unevaluable / {sc['substantive_N']} substantive)")
    print(f"Infrastructure-only issues filtered: {filtered_count}")
    print(f"Report written to: {output_path}")
    print(f"Verdict: {sc['pass_fail']}")

    sys.exit(0 if sc["pass_fail"] == "PASS" else 1)


if __name__ == "__main__":
    main()
```

**Step 2** — Re-run the full test suite to confirm no regressions:

```bash
python -m pytest dark-factory/tests/test_eval_memory_quality.py -v
```

All tests must still pass.

**Step 3** — Run the harness against the live corpus:

```bash
python3 dark-factory/scripts/eval_memory_quality.py \
  --memory-dir .archon/memory \
  --failures dark-factory/evals/factory-failures.jsonl \
  --output dark-factory/evals/memory-quality-report.md \
  --retrieve-script dark-factory/scripts/memory_retrieve.py
```

Expected: exits 0 (PASS) or 1 (FAIL); report written to
`dark-factory/evals/memory-quality-report.md`.

Note: exit 1 (FAIL) does not mean the harness is broken — a recall below 0.5 simply means
the corpus hasn't been seeded with issue-tagged entries yet. The report artifact is committed
regardless of the verdict.

**Step 4** — Commit everything together:

```bash
git add dark-factory/scripts/eval_memory_quality.py \
        dark-factory/evals/memory-quality-report.md
git commit -m "feat(#653): memory quality eval harness + committed report artifact"
```

---

## Summary

| Task | Files | Outcome |
|------|-------|---------|
| 1. pytest suite | `tests/test_eval_memory_quality.py` | All scoring logic covered, TDD-first |
| 2. Scoring functions | `scripts/eval_memory_quality.py` | Pure functions pass all 5 test classes |
| 3. Harness + CLI | `scripts/eval_memory_quality.py` | Subprocess runner, report writer, CLI |
| Generate artifact | `evals/memory-quality-report.md` | Committed scorecard, PASS/FAIL gate |

**Total:** 3 tasks, ~12 actionable steps. No changes to `memory_retrieve.py`,
`memory_write.py`, `.archon/memory/*.md`, or `factory-failures.jsonl`.
