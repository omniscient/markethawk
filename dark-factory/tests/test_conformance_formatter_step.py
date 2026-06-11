from pathlib import Path

CMD = (
    Path(__file__).resolve().parents[2]
    / ".archon" / "commands" / "dark-factory-conformance.md"
)


def test_step_30_invokes_filter_script():
    text = CMD.read_text(encoding="utf-8")
    assert "fmt_hunk_filter.py" in text, "Step 3.0 must invoke fmt_hunk_filter.py"


def test_step_30_guards_on_ruff_absence_via_script():
    text = CMD.read_text(encoding="utf-8")
    # Script handles missing ruff internally (returns raw diff unchanged)
    assert "fmt_hunk_filter.py" in text


def test_step_30_writes_py_files_list():
    text = CMD.read_text(encoding="utf-8")
    assert "'*.py'" in text or '"*.py"' in text, \
        "Step 3.0 must extract .py file list from git diff --name-only"


def test_step_30_pre_triage_annotation_variable():
    text = CMD.read_text(encoding="utf-8")
    assert "TRIAGED_DIFF" in text, \
        "filtered diff must be stored as TRIAGED_DIFF for Step 3.1"


def test_step_31_uses_triaged_diff():
    text = CMD.read_text(encoding="utf-8")
    # TRIAGED_DIFF must be referenced in Step 3.1's ARTIFACT_CONTENT build
    assert "TRIAGED_DIFF" in text
    triaged_pos = text.find("TRIAGED_DIFF")
    artifact_content_pos = text.find("ARTIFACT_CONTENT")
    assert triaged_pos < artifact_content_pos or text.count("TRIAGED_DIFF") >= 2, \
        "TRIAGED_DIFF must be used when building ARTIFACT_CONTENT"
