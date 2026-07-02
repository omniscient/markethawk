"""Tests for context_budget.py CLI (build_budget function)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import context_budget as cb


# ── helpers ──────────────────────────────────────────────────────────────────

def make_issue_json(tmp_path, with_pr=False):
    data = {
        "resolved_number": 664,
        "intent": "continue" if with_pr else "new",
        "title": "Test issue",
        "body": "Issue body text for estimation",
        "comments": [{"body": "comment one"}, {"body": "comment two"}],
    }
    if with_pr:
        data["pr_reviews"] = {"reviews": [{"body": "looks good"}], "comments": []}
        data["pr_inline_comments"] = []
    p = tmp_path / "issue.json"
    p.write_text(json.dumps(data))
    return str(p)


def make_spec_file(tmp_path):
    p = tmp_path / "spec.md"
    p.write_text("# Spec\n\n" + "word " * 100)
    return str(p)


def make_impl_file(tmp_path):
    p = tmp_path / "implementation.md"
    p.write_text("## Changes\n\n" + "line " * 50)
    return str(p)


def make_diff_file(tmp_path, lines=10):
    p = tmp_path / "review_diff.txt"
    p.write_text("\n".join(f"+line {i}" for i in range(lines)))
    return str(p)


def run_budget(tmp_path, scenario, **kwargs):
    out_path = str(tmp_path / "context-budget.json")
    cb.build_budget(
        scenario=scenario,
        issue_num=664,
        run_id="test-run-abc123",
        artifacts_dir=str(tmp_path),
        clone_dir=str(tmp_path),
        out=out_path,
        **kwargs,
    )
    return json.loads(Path(out_path).read_text())


# ── schema tests ─────────────────────────────────────────────────────────────

def test_required_fields_present(tmp_path):
    result = run_budget(tmp_path, "refine", issue_json=make_issue_json(tmp_path))
    for field in (
        "schema_version", "scenario", "run_id", "issue_number",
        "generated_at", "budget_tokens", "estimated_input_tokens",
        "utilization_pct", "sections", "included_sections",
        "dropped_sections", "source_file_hashes",
    ):
        assert field in result, f"Missing required field: {field}"


def test_schema_version_is_2(tmp_path):
    result = run_budget(tmp_path, "refine", issue_json=make_issue_json(tmp_path))
    assert result["schema_version"] == 2


def test_budget_tokens_is_200000(tmp_path):
    result = run_budget(tmp_path, "refine", issue_json=make_issue_json(tmp_path))
    assert result["budget_tokens"] == 200_000


def test_utilization_pct_matches_tokens(tmp_path):
    result = run_budget(tmp_path, "refine", issue_json=make_issue_json(tmp_path))
    expected = round(result["estimated_input_tokens"] / 200_000 * 100, 1)
    assert result["utilization_pct"] == expected


def test_scenario_and_run_id_round_trip(tmp_path):
    result = run_budget(tmp_path, "plan", issue_json=make_issue_json(tmp_path))
    assert result["scenario"] == "plan"
    assert result["run_id"] == "test-run-abc123"
    assert result["issue_number"] == 664


# ── section status tests ──────────────────────────────────────────────────────

def test_plan_spec_present_is_included(tmp_path):
    spec = make_spec_file(tmp_path)
    result = run_budget(tmp_path, "plan",
                        issue_json=make_issue_json(tmp_path),
                        spec_file=spec)
    assert result["sections"]["spec"]["status"] == "included"
    assert result["sections"]["spec"]["tokens"] > 0
    assert "file_hash" in result["sections"]["spec"]
    assert len(result["sections"]["spec"]["file_hash"]) == 12


def test_plan_spec_missing_is_dropped(tmp_path):
    result = run_budget(tmp_path, "plan",
                        issue_json=make_issue_json(tmp_path))
    assert result["sections"]["spec"]["status"] == "dropped"
    assert result["sections"]["spec"]["tokens"] == 0
    assert "reason" in result["sections"]["spec"]


def test_conformance_diff_over_1000_lines_is_partial(tmp_path):
    diff = make_diff_file(tmp_path, lines=1500)
    spec = make_spec_file(tmp_path)
    impl = make_impl_file(tmp_path)
    result = run_budget(tmp_path, "conformance",
                        spec_file=spec, impl_file=impl, diff_file=diff)
    sec = result["sections"]["diff"]
    assert sec["status"] == "included_partial"
    assert sec["truncated_at_lines"] == 1000
    assert sec["tokens"] > 0


def test_conformance_diff_under_1000_lines_is_included(tmp_path):
    diff = make_diff_file(tmp_path, lines=50)
    spec = make_spec_file(tmp_path)
    impl = make_impl_file(tmp_path)
    result = run_budget(tmp_path, "conformance",
                        spec_file=spec, impl_file=impl, diff_file=diff)
    assert result["sections"]["diff"]["status"] == "included"


def test_included_dropped_lists_consistent(tmp_path):
    result = run_budget(tmp_path, "plan",
                        issue_json=make_issue_json(tmp_path))
    # spec is absent → dropped
    assert "spec" in result["dropped_sections"]
    assert "spec" not in result["included_sections"]
    # issue_context provided via issue_json → included
    assert "issue_context" in result["included_sections"]
    assert "issue_context" not in result["dropped_sections"]


def test_source_file_hashes_populated_when_file_exists(tmp_path):
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text("# CLAUDE.md content for test")
    result = run_budget(tmp_path, "refine",
                        issue_json=make_issue_json(tmp_path))
    assert "CLAUDE.md" in result["source_file_hashes"]
    assert len(result["source_file_hashes"]["CLAUDE.md"]) == 12


def test_conformance_excludes_inapplicable_sections(tmp_path):
    spec = make_spec_file(tmp_path)
    impl = make_impl_file(tmp_path)
    result = run_budget(tmp_path, "conformance",
                        spec_file=spec, impl_file=impl)
    # conformance does not load claude_md, architecture_md, issue_context, comments
    for sec in ("claude_md", "architecture_md", "issue_context", "comments", "memory_context"):
        assert sec not in result["sections"], f"Section {sec!r} should be absent for conformance"


def test_continue_scenario_includes_comment_digest(tmp_path):
    """continue scenario uses comment_digest instead of comments/pr_reviews."""
    digest_file = tmp_path / "comment-digest.md"
    digest_file.write_text("# Comment Digest\n\n## Issue Comments\n\nsome feedback\n")
    result = run_budget(tmp_path, "continue",
                        issue_json=make_issue_json(tmp_path, with_pr=True),
                        comment_digest_file=str(digest_file))
    assert "comment_digest" in result["sections"]
    assert result["sections"]["comment_digest"]["status"] == "included"
    assert "pr_reviews" not in result["sections"]
    assert "comments" not in result["sections"]


def test_continue_scenario_comment_digest_absent_is_dropped(tmp_path):
    """continue scenario reports comment_digest as dropped when file is absent."""
    result = run_budget(tmp_path, "continue", issue_json=make_issue_json(tmp_path))
    sec = result["sections"].get("comment_digest", {})
    assert sec["status"] == "dropped"
    assert sec.get("reason") == "empty_or_missing"


def test_implement_scenario_excludes_pr_reviews(tmp_path):
    result = run_budget(tmp_path, "implement",
                        issue_json=make_issue_json(tmp_path))
    assert "pr_reviews" not in result["sections"]


def test_estimated_tokens_is_sum_of_section_tokens(tmp_path):
    result = run_budget(tmp_path, "plan",
                        issue_json=make_issue_json(tmp_path))
    total = sum(v.get("tokens", 0) for v in result["sections"].values())
    assert result["estimated_input_tokens"] == total


def test_memory_context_absent_is_dropped(tmp_path):
    # memory-context.md doesn't exist pre-command (written inside command session);
    # reports "empty_or_missing" matching spec vocabulary.
    result = run_budget(tmp_path, "refine",
                        issue_json=make_issue_json(tmp_path))
    sec = result["sections"].get("memory_context", {})
    assert sec["status"] == "dropped"
    assert sec.get("reason") == "empty_or_missing"


# ── Integration: architecture_slice wired into context_budget ─────────────────

def make_arch_file(tmp_path):
    p = tmp_path / "ARCHITECTURE.md"
    p.write_text(
        "# Architecture\n\n"
        "## Backend Module Map\n\nBackend content.\n\n"
        "## Frontend Architecture\n\nFrontend content.\n\n"
        "## Service Topology\n\nTopology content.\n\n"
        "## Scan Execution Flow\n\nScan flow content.\n\n"
        "## Error Tracking System\n\nError tracking content.\n\n"
        "## IB Gateway Integration\n\nIBKR content.\n\n"
        "## Live Scanner\n\nLive scanner content.\n\n"
        "## Celery Task Architecture\n\nCelery content.\n\n"
        "## Catch Up Feature (Universe Aggregate Backfill)\n\nCatch up content.\n\n"
        "## Metrics and Observability\n\nMetrics content.\n\n"
        "## Test Architecture\n\nTest content.\n\n"
    )
    return str(p)


def run_budget_with_arch(tmp_path, scenario, spec_component=None, changed_files=None, **kwargs):
    make_arch_file(tmp_path)
    out_path = str(tmp_path / "context-budget.json")
    cb.build_budget(
        scenario=scenario,
        issue_num=664,
        run_id="test-run-arch",
        artifacts_dir=str(tmp_path),
        clone_dir=str(tmp_path),
        out=out_path,
        spec_component=spec_component,
        changed_files=changed_files,
        **kwargs,
    )
    import json
    return json.loads(Path(out_path).read_text())


def test_architecture_md_slice_status_when_component_known(tmp_path):
    result = run_budget_with_arch(tmp_path, "implement", spec_component="backend")
    sec = result["sections"]["architecture_md"]
    assert sec["status"] == "included_slice"
    assert sec["component"] == "backend"
    assert "included_sections" in sec
    assert "omitted_sections" in sec
    assert sec["fallback"] is False
    assert "Backend Module Map" in sec["included_sections"]
    assert "Frontend Architecture" in sec["omitted_sections"]


def test_architecture_md_fallback_status_when_component_unknown(tmp_path):
    result = run_budget_with_arch(tmp_path, "refine",
                                  spec_component=None, changed_files=[])
    sec = result["sections"]["architecture_md"]
    assert sec["status"] == "included"
    assert sec["fallback"] is True
    assert sec["fallback_reason"] == "component_unresolved"


# ── memory_context cap counts from trace ─────────────────────────────────────

import json as _json
from pathlib import Path as _Path


def write_memory_trace(artifacts_dir, entries_selected, entries_dropped):
    """Write a minimal memory-trace.json with run-level cap totals."""
    trace = {
        "schema_version": 1,
        "entries_selected_total": entries_selected,
        "entries_dropped_by_cap_total": entries_dropped,
    }
    (_Path(artifacts_dir) / "memory-trace.json").write_text(
        _json.dumps(trace), encoding="utf-8"
    )


def make_memory_file(tmp_path, content="Memory block content here.\n"):
    p = tmp_path / "memory-context.md"
    p.write_text(content)
    return str(p)


class TestMemoryContextCapCounts:
    def test_entries_selected_from_trace(self, tmp_path):
        issue_json = make_issue_json(tmp_path)
        mem_file = make_memory_file(tmp_path)
        write_memory_trace(str(tmp_path), entries_selected=6, entries_dropped=10)
        result = run_budget(tmp_path, "plan", issue_json=issue_json, memory_file=mem_file)
        mc = result["sections"]["memory_context"]
        assert mc.get("entries_selected") == 6

    def test_entries_dropped_from_trace(self, tmp_path):
        issue_json = make_issue_json(tmp_path)
        mem_file = make_memory_file(tmp_path)
        write_memory_trace(str(tmp_path), entries_selected=3, entries_dropped=25)
        result = run_budget(tmp_path, "plan", issue_json=issue_json, memory_file=mem_file)
        mc = result["sections"]["memory_context"]
        assert mc.get("entries_dropped") == 25

    def test_no_trace_no_cap_fields(self, tmp_path):
        """When trace is absent, cap fields are absent (not 0)."""
        issue_json = make_issue_json(tmp_path)
        mem_file = make_memory_file(tmp_path)
        result = run_budget(tmp_path, "plan", issue_json=issue_json, memory_file=mem_file)
        mc = result["sections"]["memory_context"]
        assert "entries_selected" not in mc
        assert "entries_dropped" not in mc

    def test_corrupt_trace_does_not_raise(self, tmp_path):
        """Corrupt trace JSON → fail-open, no exception."""
        issue_json = make_issue_json(tmp_path)
        mem_file = make_memory_file(tmp_path)
        (_Path(tmp_path) / "memory-trace.json").write_text("not valid json", encoding="utf-8")
        result = run_budget(tmp_path, "plan", issue_json=issue_json, memory_file=mem_file)
        assert "memory_context" in result["sections"]

    def test_dropped_memory_file_no_trace_no_crash(self, tmp_path):
        """When memory_file is None, the memory_context section is dropped (status=dropped)."""
        issue_json = make_issue_json(tmp_path)
        write_memory_trace(str(tmp_path), entries_selected=5, entries_dropped=3)
        result = run_budget(tmp_path, "plan", issue_json=issue_json, memory_file=None)
        mc = result["sections"]["memory_context"]
        assert mc["status"] == "dropped"


# ── schema v2 savings tests ───────────────────────────────────────────────────

class TestSchemaV2Savings:
    """Schema v2 adds savings_tokens, savings_pct, and fallback_events at the top level."""

    def test_savings_fields_present(self, tmp_path):
        result = run_budget(tmp_path, "refine", issue_json=make_issue_json(tmp_path))
        assert "savings_tokens" in result
        assert "savings_pct" in result
        assert "fallback_events" in result

    def test_savings_tokens_is_non_negative(self, tmp_path):
        result = run_budget(tmp_path, "refine", issue_json=make_issue_json(tmp_path))
        assert result["savings_tokens"] >= 0

    def test_fallback_events_is_list(self, tmp_path):
        result = run_budget(tmp_path, "refine", issue_json=make_issue_json(tmp_path))
        assert isinstance(result["fallback_events"], list)

    def test_diff_section_has_baseline_tokens_from_ranking_sidecar(self, tmp_path):
        """When diff-ranking.json has raw_diff_tokens, it should appear as baseline_tokens in diff section."""
        import json as _json
        diff_file = make_diff_file(tmp_path, lines=50)
        ranking_path = tmp_path / "diff-ranking.json"
        ranking_path.write_text(_json.dumps({"raw_diff_tokens": 999, "files": []}), encoding="utf-8")
        result = run_budget(tmp_path, "code-review",
                            issue_json=make_issue_json(tmp_path),
                            diff_file=diff_file)
        diff_sec = result["sections"].get("diff", {})
        if diff_sec.get("status") in ("included", "included_partial"):
            assert diff_sec.get("baseline_tokens") == 999

    def test_memory_uncapped_tokens_feeds_baseline(self, tmp_path):
        """uncapped_tokens in memory-trace.json → baseline_tokens in memory_context section."""
        import json as _json
        from pathlib import Path as _Path
        issue_json = make_issue_json(tmp_path)
        mem_file = make_memory_file(tmp_path)
        trace = {
            "schema_version": 1,
            "entries_selected_total": 3,
            "entries_dropped_by_cap_total": 2,
            "uncapped_tokens": 2500,
        }
        (_Path(tmp_path) / "memory-trace.json").write_text(_json.dumps(trace), encoding="utf-8")
        result = run_budget(tmp_path, "plan", issue_json=issue_json, memory_file=mem_file)
        mc = result["sections"]["memory_context"]
        assert mc.get("baseline_tokens") == 2500

    def test_architecture_section_has_baseline_tokens(self, tmp_path):
        """architecture_md section always has baseline_tokens (full doc size)."""
        arch_path = tmp_path / "ARCHITECTURE.md"
        arch_path.write_text("## Section A\ncontent\n" * 10)
        result = run_budget(tmp_path, "refine", issue_json=make_issue_json(tmp_path))
        arch_sec = result["sections"].get("architecture_md", {})
        if arch_sec.get("status") not in ("dropped",):
            assert "baseline_tokens" in arch_sec


# ── architecture slice feature-disabled tests ─────────────────────────────────

class TestArchitectureFeatureDisabled:
    """When TOKEN_OPTIMIZATION_ARCHITECTURE_ENABLED=false, slice_architecture returns full doc."""

    def test_feature_disabled_env_returns_full_doc(self, tmp_path, monkeypatch):
        import architecture_slice as aslice
        arch_path = tmp_path / "ARCHITECTURE.md"
        arch_path.write_text("## Section A\ncontent\n## Section B\nmore\n")
        monkeypatch.setenv("TOKEN_OPTIMIZATION_ARCHITECTURE_ENABLED", "false")
        result = aslice.slice_architecture(
            arch_path=str(arch_path),
            scenario="implement",
            changed_files=["backend/app/routers/health.py"],
        )
        assert result.fallback is True
        assert result.fallback_reason == "feature_disabled"

    def test_feature_enabled_env_still_slices(self, tmp_path, monkeypatch):
        import architecture_slice as aslice
        arch_path = tmp_path / "ARCHITECTURE.md"
        arch_path.write_text("## Section A\ncontent\n")
        monkeypatch.setenv("TOKEN_OPTIMIZATION_ARCHITECTURE_ENABLED", "true")
        result = aslice.slice_architecture(
            arch_path=str(arch_path),
            scenario="implement",
            changed_files=["backend/app/routers/health.py"],
        )
        # Should not be feature_disabled (may be other fallback reasons)
        assert result.fallback_reason != "feature_disabled"


# ── diff rank feature-disabled tests ─────────────────────────────────────────

class TestDiffRankFeatureDisabled:
    """When diff_enabled=False, build_ranked_diff returns full diff without truncation."""

    def test_disabled_returns_full_diff(self):
        import diff_rank as dr
        diff_text = "diff --git a/foo.py b/foo.py\n+++ b/foo.py\n+line\n"
        result, info = dr.build_ranked_diff(
            diff_text, token_cap=10, hotspot_paths=set(), hotspot_scores={},
            spec_names=set(), score_floor=5.0, diff_enabled=False,
        )
        assert result == diff_text
        assert info["diff_enabled"] is False

    def test_disabled_records_raw_diff_tokens(self):
        import diff_rank as dr
        diff_text = "diff --git a/foo.py b/foo.py\n+++ b/foo.py\n+line\n"
        _, info = dr.build_ranked_diff(
            diff_text, token_cap=10, hotspot_paths=set(), hotspot_scores={},
            spec_names=set(), score_floor=5.0, diff_enabled=False,
        )
        expected = dr.estimate_tokens(diff_text)
        assert info["raw_diff_tokens"] == expected
        assert info["estimated_tokens_emitted"] == expected

    def test_enabled_produces_ranking_header(self):
        import diff_rank as dr
        diff_text = "diff --git a/foo.py b/foo.py\n+++ b/foo.py\n+line\n"
        result, _ = dr.build_ranked_diff(
            diff_text, token_cap=9999, hotspot_paths=set(), hotspot_scores={},
            spec_names=set(), score_floor=5.0, diff_enabled=True,
        )
        assert result.startswith("# [diff-rank:")

    def test_load_config_returns_3_tuple(self, tmp_path):
        import diff_rank as dr
        cfg = tmp_path / "config.yaml"
        cfg.write_text("token_optimization:\n  diff:\n    enabled: true\n    max_review_tokens: 4000\nblast_radius:\n  hotspot_score_floor: 3.0\n")
        result = dr.load_config(str(cfg))
        assert len(result) == 3
        token_cap, score_floor, diff_enabled = result
        assert token_cap == 4000
        assert score_floor == 3.0
        assert diff_enabled is True

    def test_load_config_diff_disabled_flag(self, tmp_path):
        import diff_rank as dr
        cfg = tmp_path / "config.yaml"
        cfg.write_text("token_optimization:\n  diff:\n    enabled: false\n    max_review_tokens: 6000\nblast_radius:\n  hotspot_score_floor: 5.0\n")
        _, _, diff_enabled = dr.load_config(str(cfg))
        assert diff_enabled is False
