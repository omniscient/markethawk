"""Tests for context_pack.py — scenario content assembler."""
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import context_pack as cp


# ── helpers ──────────────────────────────────────────────────────────────────

def make_issue_json(tmp_path, with_pr=False):
    data = {
        "resolved_number": 665,
        "intent": "continue" if with_pr else "new",
        "title": "Test issue",
        "body": "Issue body text for pack assembly",
        "comments": [{"body": "comment alpha"}, {"body": "comment beta"}],
    }
    if with_pr:
        data["pr_reviews"] = {"reviews": [{"body": "lgtm"}], "comments": []}
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


def run_pack(tmp_path, scenario, **kwargs):
    out_md = str(tmp_path / "context-pack.md")
    out_json = str(tmp_path / "context-pack.json")
    cp.assemble_pack(
        scenario=scenario,
        issue_num=665,
        run_id="test-run-cp-abc",
        artifacts_dir=str(tmp_path),
        clone_dir=str(tmp_path),
        out_md=out_md,
        out_json=out_json,
        **kwargs,
    )
    manifest = json.loads(Path(out_json).read_text())
    md_content = Path(out_md).read_text()
    return manifest, md_content


# ── JSON schema tests (refine scenario) ──────────────────────────────────────

def test_required_json_fields_present(tmp_path):
    manifest, _ = run_pack(tmp_path, "refine", issue_json=make_issue_json(tmp_path))
    for field in (
        "schema_version", "scenario", "run_id", "issue_number",
        "generated_at", "budget_tokens", "estimated_input_tokens",
        "utilization_pct", "over_budget", "sections", "included_sections",
        "dropped_sections", "source_file_hashes",
    ):
        assert field in manifest, f"Missing required JSON field: {field}"


def test_schema_version_is_1(tmp_path):
    manifest, _ = run_pack(tmp_path, "refine", issue_json=make_issue_json(tmp_path))
    assert manifest["schema_version"] == 1


def test_budget_tokens_is_200000(tmp_path):
    manifest, _ = run_pack(tmp_path, "refine", issue_json=make_issue_json(tmp_path))
    assert manifest["budget_tokens"] == 200_000


def test_over_budget_false_for_small_input(tmp_path):
    manifest, _ = run_pack(tmp_path, "refine", issue_json=make_issue_json(tmp_path))
    assert manifest["over_budget"] is False


def test_refine_md_has_section_headers(tmp_path):
    _, md = run_pack(tmp_path, "refine", issue_json=make_issue_json(tmp_path))
    assert "## issue_context" in md
    assert "## comments" in md


def test_refine_md_contains_issue_body(tmp_path):
    _, md = run_pack(tmp_path, "refine", issue_json=make_issue_json(tmp_path))
    assert "Issue body text for pack assembly" in md


# ── plan scenario — spec section included / dropped ───────────────────────────
# The plan scenario includes spec; this verifies the content assembler handles
# the include/drop distinction correctly.

def test_plan_spec_included_when_file_supplied(tmp_path):
    spec = make_spec_file(tmp_path)
    manifest, md = run_pack(tmp_path, "plan",
                            issue_json=make_issue_json(tmp_path),
                            spec_file=spec)
    assert manifest["sections"]["spec"]["status"] == "included"
    assert manifest["sections"]["spec"]["tokens"] > 0
    assert "## spec" in md


def test_plan_spec_dropped_when_absent(tmp_path):
    manifest, md = run_pack(tmp_path, "plan",
                            issue_json=make_issue_json(tmp_path))
    assert manifest["sections"]["spec"]["status"] == "dropped"
    assert "## spec" not in md


# ── code-review scenario — diff section with truncation ──────────────────────

def test_code_review_diff_included_when_under_cap(tmp_path):
    diff = make_diff_file(tmp_path, lines=50)
    spec = make_spec_file(tmp_path)
    manifest, md = run_pack(tmp_path, "code-review",
                            issue_json=make_issue_json(tmp_path),
                            spec_file=spec,
                            diff_file=diff)
    sec = manifest["sections"]["diff"]
    assert sec["status"] == "included"
    assert "truncated_at_lines" not in sec
    assert "## diff" in md
    assert "<!-- truncated" not in md


def test_code_review_diff_partial_when_over_cap(tmp_path):
    diff = make_diff_file(tmp_path, lines=1500)
    spec = make_spec_file(tmp_path)
    manifest, md = run_pack(tmp_path, "code-review",
                            issue_json=make_issue_json(tmp_path),
                            spec_file=spec,
                            diff_file=diff)
    sec = manifest["sections"]["diff"]
    assert sec["status"] == "included_partial"
    assert sec["truncated_at_lines"] == 1000
    assert sec["tokens"] > 0
    assert "<!-- truncated at 1000 lines -->" in md


# ── over_budget flag ──────────────────────────────────────────────────────────

def test_over_budget_true_and_stderr_warning_when_exceeds(tmp_path, monkeypatch):
    # Temporarily reduce BUDGET_TOKENS so small content exceeds it
    original = cp.BUDGET_TOKENS
    monkeypatch.setattr(cp, "BUDGET_TOKENS", 1)
    try:
        captured = io.StringIO()
        monkeypatch.setattr(sys, "stderr", captured)
        manifest, _ = run_pack(tmp_path, "refine", issue_json=make_issue_json(tmp_path))
    finally:
        monkeypatch.setattr(cp, "BUDGET_TOKENS", original)

    assert manifest["over_budget"] is True
    warning = captured.getvalue()
    assert "WARNING" in warning
    assert "exceeds budget" in warning


# ── graceful missing-file drop ────────────────────────────────────────────────

def test_missing_source_files_drop_gracefully(tmp_path):
    # No file-backed sources provided — spec, implementation_md, diff must all be dropped.
    # skill_prompts is container-mounted (/opt/refinement-skills) so its status is env-dependent;
    # we only assert on the file-path-backed sections.
    manifest, _ = run_pack(tmp_path, "conformance",
                           spec_file=None, impl_file=None, diff_file=None)
    for sec_name in ("spec", "implementation_md", "diff"):
        sec = manifest["sections"][sec_name]
        assert sec["status"] == "dropped", (
            f"Expected dropped for {sec_name!r}, got {sec['status']!r}"
        )
        assert "reason" in sec, f"Missing 'reason' for dropped section {sec_name!r}"


def test_nonexistent_files_produce_dropped_with_reason(tmp_path):
    manifest, _ = run_pack(tmp_path, "implement",
                           issue_json="/nonexistent/issue.json",
                           memory_file="/nonexistent/memory.md")
    assert manifest["sections"]["issue_context"]["status"] == "dropped"
    assert "reason" in manifest["sections"]["issue_context"]
    assert manifest["sections"]["memory_context"]["status"] == "dropped"
    assert "reason" in manifest["sections"]["memory_context"]
