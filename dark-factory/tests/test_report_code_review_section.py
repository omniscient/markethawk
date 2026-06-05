from pathlib import Path

WF = Path(__file__).resolve().parents[2] / ".archon" / "workflows" / "archon-dark-factory.yaml"


def test_report_node_renders_code_review_section():
    text = WF.read_text(encoding="utf-8")
    assert "review.md" in text, "report node must read the code-review artifact"
    assert "### Code Review" in text, "report node must render a Code Review section"
    assert "CODE_REVIEW_SECTION" in text
