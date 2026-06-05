from pathlib import Path

PROMPT = Path(__file__).resolve().parents[2] / ".claude" / "skills" / "refinement" / "code-review-reviewer-prompt.md"


def test_prompt_exists_and_has_contract():
    text = PROMPT.read_text(encoding="utf-8")
    assert "$DIFF_CONTENT" in text, "prompt must declare the $DIFF_CONTENT placeholder"
    assert "$ISSUE_CONTEXT" in text, "prompt must declare the $ISSUE_CONTEXT placeholder"
    # the machine-readable finding format the parser depends on
    assert "[severity] category | path:line | description" in text
    for sev in ("critical", "high", "medium", "low"):
        assert sev in text
    assert "### Findings" in text
