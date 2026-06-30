"""
Tests for eval_memory_quality.py scoring functions.
No subprocess, no network — all fixtures are in-memory or tmp_path.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from eval_memory_quality import (
    PASS_THRESHOLD,
    check_hit,
    compute_scorecard,
    filter_and_deduplicate_regressions,
    is_infrastructure_failure,
    parse_memory_entries,
)


# ── is_infrastructure_failure ─────────────────────────────────────────────


class TestIsInfrastructureFailure:
    def test_session_limit_with_resets_is_infra(self):
        pm = "You've hit your session limit · resets 11:10pm (UTC) "
        assert is_infrastructure_failure(pm) is True

    def test_session_limit_with_resets_variant(self):
        pm = "You've hit your session limit · resets 7am (UTC) "
        assert is_infrastructure_failure(pm) is True

    def test_session_limit_lowercase_is_infra(self):
        pm = "you've hit your session limit · resets 5am (UTC) "
        assert is_infrastructure_failure(pm) is True

    def test_substantive_postmortem_is_not_infra(self):
        pm = (
            "The code-review gate failed on a high-severity correctness issue: "
            "the cleanup trap in scripts/restore-drill.sh uses kill without wait."
        )
        assert is_infrastructure_failure(pm) is False

    def test_empty_string_is_not_infra(self):
        assert is_infrastructure_failure("") is False

    def test_session_limit_without_resets_is_not_infra(self):
        pm = "You've hit your session limit."
        assert is_infrastructure_failure(pm) is False

    def test_resets_without_session_limit_is_not_infra(self):
        pm = "The scheduler resets at midnight UTC."
        assert is_infrastructure_failure(pm) is False

    def test_long_postmortem_mentioning_session_context_is_not_infra(self):
        # Has "session" and "resets" but not "session limit"
        pm = "The session token resets after 24 hours. The fix required updating the auth flow."
        assert is_infrastructure_failure(pm) is False


# ── parse_memory_entries ──────────────────────────────────────────────────


def _write_memory_file(tmp_path: Path, filename: str, lines: list) -> None:
    content = "\n".join(lines) + "\n"
    (tmp_path / filename).write_text(content, encoding="utf-8")


class TestParseMemoryEntries:
    def test_empty_dir_returns_empty(self, tmp_path):
        result = parse_memory_entries(tmp_path)
        assert result == []

    def test_single_entry_extracted(self, tmp_path):
        _write_memory_file(tmp_path, "dark-factory-ops.md", [
            "- [PATTERN] Use foo pattern here <!-- issue:#123 date:2026-06-01 expires:2026-12-01 source:implement -->",
        ])
        result = parse_memory_entries(tmp_path)
        assert len(result) == 1
        e = result[0]
        assert e["issue_num"] == 123
        assert e["body"] == "Use foo pattern here"
        assert e["source_tag"] == "implement"
        assert e["path_tag"] == ""
        assert e["source_file"] == "dark-factory-ops.md"

    def test_provisional_excluded(self, tmp_path):
        _write_memory_file(tmp_path, "dark-factory-ops.md", [
            "- [PROVISIONAL] Some provisional claim <!-- issue:#456 date:2026-06-01 expires:2026-12-01 source:implement -->",
        ])
        result = parse_memory_entries(tmp_path)
        assert result == []

    def test_invalid_excluded(self, tmp_path):
        _write_memory_file(tmp_path, "dark-factory-ops.md", [
            "- [INVALID: reason here] Some old pattern <!-- issue:#789 date:2026-06-01 expires:2026-12-01 source:implement -->",
        ])
        result = parse_memory_entries(tmp_path)
        assert result == []

    def test_entry_without_issue_tag_excluded(self, tmp_path):
        _write_memory_file(tmp_path, "dark-factory-ops.md", [
            "- [PATTERN] No issue tag here <!-- date:2026-06-01 expires:2026-12-01 source:implement -->",
        ])
        result = parse_memory_entries(tmp_path)
        assert result == []

    def test_entry_without_hash_prefix_excluded(self, tmp_path):
        _write_memory_file(tmp_path, "dark-factory-ops.md", [
            "- [PATTERN] Missing hash <!-- issue:123 date:2026-06-01 source:implement -->",
        ])
        result = parse_memory_entries(tmp_path)
        assert result == []

    def test_path_tag_extracted(self, tmp_path):
        _write_memory_file(tmp_path, "codebase-patterns.md", [
            "- [AVOID] Some avoid thing <!-- issue:#360 date:2026-06-13 expires:2026-12-13 source:conformance path:backend/tests/ -->",
        ])
        result = parse_memory_entries(tmp_path)
        assert len(result) == 1
        assert result[0]["path_tag"] == "backend/tests/"

    def test_multiple_files_scanned(self, tmp_path):
        _write_memory_file(tmp_path, "dark-factory-ops.md", [
            "- [PATTERN] Factory ops entry <!-- issue:#100 date:2026-06-01 source:implement -->",
        ])
        _write_memory_file(tmp_path, "backend-patterns.md", [
            "- [AVOID] Backend avoid <!-- issue:#200 date:2026-06-01 source:implement -->",
        ])
        result = parse_memory_entries(tmp_path)
        issue_nums = {e["issue_num"] for e in result}
        assert 100 in issue_nums
        assert 200 in issue_nums

    def test_multiple_entries_same_issue(self, tmp_path):
        _write_memory_file(tmp_path, "backend-patterns.md", [
            "- [PATTERN] First pattern <!-- issue:#391 date:2026-06-01 source:implement -->",
            "- [AVOID] Second pattern <!-- issue:#391 date:2026-06-02 source:implement -->",
        ])
        result = parse_memory_entries(tmp_path)
        nums = [e["issue_num"] for e in result]
        assert nums.count(391) == 2

    def test_source_tag_conformance(self, tmp_path):
        _write_memory_file(tmp_path, "codebase-patterns.md", [
            "- [AVOID] Conformance entry <!-- issue:#494 date:2026-06-22 source:conformance path:backend/app/tasks/ -->",
        ])
        result = parse_memory_entries(tmp_path)
        assert len(result) == 1
        assert result[0]["source_tag"] == "conformance"

    def test_entry_without_source_tag_included(self, tmp_path):
        _write_memory_file(tmp_path, "dark-factory-ops.md", [
            "- [PATTERN] Old entry no source <!-- issue:#50 date:2026-01-01 -->",
        ])
        result = parse_memory_entries(tmp_path)
        assert len(result) == 1
        assert result[0]["source_tag"] == ""

    def test_stops_at_separator_line(self, tmp_path):
        _write_memory_file(tmp_path, "dark-factory-ops.md", [
            "- [PATTERN] Before separator <!-- issue:#10 date:2026-06-01 source:implement -->",
            "---",
            "- [PATTERN] After separator <!-- issue:#20 date:2026-06-01 source:implement -->",
        ])
        result = parse_memory_entries(tmp_path)
        issue_nums = {e["issue_num"] for e in result}
        assert 10 in issue_nums
        assert 20 not in issue_nums


# ── check_hit ────────────────────────────────────────────────────────────


class TestCheckHit:
    def _make_entry(self, body: str, source_tag: str = "implement", path_tag: str = "") -> dict:
        return {
            "issue_num": 100,
            "body": body,
            "source_tag": source_tag,
            "path_tag": path_tag,
            "source_file": "dark-factory-ops.md",
        }

    def test_body_in_output_is_hit(self):
        entry = self._make_entry("Use foo pattern here")
        output = "### Memory: dark-factory-ops.md\n- [PATTERN] Use foo pattern here <!-- metadata -->\n"
        assert check_hit(entry, output) is True

    def test_body_not_in_output_is_miss(self):
        entry = self._make_entry("Use foo pattern here")
        output = "### Memory: dark-factory-ops.md\n- [PATTERN] Some other thing\n"
        assert check_hit(entry, output) is False

    def test_empty_body_is_miss(self):
        entry = self._make_entry("")
        output = "### Memory: dark-factory-ops.md\n- [PATTERN] Some text\n"
        assert check_hit(entry, output) is False

    def test_empty_output_is_miss(self):
        entry = self._make_entry("Use foo pattern here")
        assert check_hit(entry, "") is False

    def test_body_substring_of_longer_line(self):
        entry = self._make_entry("Use foo pattern")
        output = "- [PATTERN] Use foo pattern for bar baz <!-- issue:#100 -->\n"
        assert check_hit(entry, output) is True

    def test_body_with_backticks(self):
        entry = self._make_entry("Use `docker exec` for health checks")
        output = "- [PATTERN] Use `docker exec` for health checks <!-- meta -->\n"
        assert check_hit(entry, output) is True

    def test_exact_match_only(self):
        entry = self._make_entry("Use foo pattern")
        output = "- [PATTERN] Usefoopattern <!-- meta -->\n"
        assert check_hit(entry, output) is False


# ── filter_and_deduplicate_regressions ───────────────────────────────────


def _make_regression(issue: int, postmortem: str, title: str = "title", phase: str = "fix") -> dict:
    return {"issue": issue, "title": title, "phase": phase, "exit_code": 1, "postmortem": postmortem}


INFRA_PM = "You've hit your session limit · resets 5am (UTC) "
SUBST_PM = "The code-review gate failed with a high-severity blocker in the implementation."


class TestFilterAndDeduplicateRegressions:
    def test_empty_list_returns_empty(self):
        assert filter_and_deduplicate_regressions([]) == []

    def test_pure_infra_issue_excluded(self):
        regressions = [
            _make_regression(100, INFRA_PM),
            _make_regression(100, INFRA_PM),
        ]
        result = filter_and_deduplicate_regressions(regressions)
        assert result == []

    def test_substantive_issue_kept(self):
        regressions = [_make_regression(200, SUBST_PM)]
        result = filter_and_deduplicate_regressions(regressions)
        assert len(result) == 1
        assert result[0]["issue"] == 200

    def test_duplicates_deduped_to_one_record(self):
        regressions = [
            _make_regression(300, SUBST_PM),
            _make_regression(300, SUBST_PM),
            _make_regression(300, SUBST_PM),
        ]
        result = filter_and_deduplicate_regressions(regressions)
        assert len(result) == 1

    def test_mixed_infra_and_substantive_kept(self):
        regressions = [
            _make_regression(400, INFRA_PM),
            _make_regression(400, INFRA_PM),
            _make_regression(400, SUBST_PM),
        ]
        result = filter_and_deduplicate_regressions(regressions)
        assert len(result) == 1
        assert result[0]["issue"] == 400

    def test_multiple_distinct_issues(self):
        regressions = [
            _make_regression(500, SUBST_PM),
            _make_regression(600, SUBST_PM),
        ]
        result = filter_and_deduplicate_regressions(regressions)
        issue_nums = {r["issue"] for r in result}
        assert issue_nums == {500, 600}

    def test_first_substantive_record_kept(self):
        pm1 = "First substantive postmortem describing the code review failure."
        pm2 = "Second substantive postmortem with different content."
        regressions = [
            _make_regression(700, pm1),
            _make_regression(700, pm2),
        ]
        result = filter_and_deduplicate_regressions(regressions)
        assert len(result) == 1
        assert result[0]["postmortem"] == pm1

    def test_infra_before_substantive_picks_substantive(self):
        regressions = [
            _make_regression(800, INFRA_PM),
            _make_regression(800, SUBST_PM),
        ]
        result = filter_and_deduplicate_regressions(regressions)
        assert len(result) == 1
        assert result[0]["postmortem"] == SUBST_PM


# ── compute_scorecard ─────────────────────────────────────────────────────


def _make_case(issue_num: int, has_entry: bool, hit) -> dict:
    return {
        "issue_num": issue_num,
        "title": f"Issue #{issue_num}",
        "has_memory_entry": has_entry,
        "hit": hit,
        "memory_entries_count": 1 if has_entry else 0,
    }


class TestComputeScorecard:
    def test_all_hits_recall_one(self):
        cases = [
            _make_case(1, True, True),
            _make_case(2, True, True),
        ]
        sc = compute_scorecard(cases)
        assert sc["recall"] == 1.0
        assert sc["passed"] is True
        assert sc["hits_n"] == 2
        assert sc["scorable_n"] == 2

    def test_all_misses_recall_zero(self):
        cases = [
            _make_case(1, True, False),
            _make_case(2, True, False),
        ]
        sc = compute_scorecard(cases)
        assert sc["recall"] == 0.0
        assert sc["passed"] is False

    def test_half_hits_passes_threshold(self):
        cases = [
            _make_case(1, True, True),
            _make_case(2, True, False),
        ]
        sc = compute_scorecard(cases)
        assert sc["recall"] == 0.5
        assert sc["passed"] is True  # >= PASS_THRESHOLD

    def test_below_threshold_fails(self):
        cases = [
            _make_case(1, True, True),
            _make_case(2, True, False),
            _make_case(3, True, False),
        ]
        sc = compute_scorecard(cases)
        assert sc["recall"] == pytest.approx(1 / 3)
        assert sc["passed"] is False

    def test_empty_cases_zero_recall(self):
        sc = compute_scorecard([])
        assert sc["recall"] == 0.0
        assert sc["passed"] is False
        assert sc["total_n"] == 0

    def test_no_memory_entries_all_gap(self):
        cases = [
            _make_case(1, False, None),
            _make_case(2, False, None),
        ]
        sc = compute_scorecard(cases)
        assert sc["scorable_n"] == 0
        assert sc["recall"] == 0.0
        assert sc["corpus_gap_n"] == 2
        assert sc["corpus_gap_pct"] == 1.0

    def test_mixed_gap_and_scorable(self):
        cases = [
            _make_case(1, True, True),
            _make_case(2, False, None),
            _make_case(3, True, True),
            _make_case(4, False, None),
        ]
        sc = compute_scorecard(cases)
        assert sc["total_n"] == 4
        assert sc["scorable_n"] == 2
        assert sc["hits_n"] == 2
        assert sc["corpus_gap_n"] == 2
        assert sc["corpus_gap_pct"] == 0.5

    def test_pass_threshold_constant(self):
        assert PASS_THRESHOLD == 0.5

    def test_exactly_at_threshold_passes(self):
        cases = [_make_case(i, True, i % 2 == 0) for i in range(1, 11)]
        sc = compute_scorecard(cases)
        assert sc["recall"] == 0.5
        assert sc["passed"] is True
