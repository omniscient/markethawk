from pathlib import Path

CMD = Path(__file__).resolve().parents[2] / ".archon" / "commands" / "dark-factory-code-review.md"


def test_command_wires_the_contract():
    text = CMD.read_text(encoding="utf-8")
    # reads config + kill-switch
    assert "code_review" in text and "enabled" in text
    # calls the helper
    assert "code_review_payload.py" in text
    # reads the clone-path reviewer prompt (not the baked /opt path)
    assert ".claude/skills/refinement/code-review-reviewer-prompt.md" in text
    # mirrors conformance's pre-triage diff exclusions
    assert "':!*.lock'" in text and "':!.archon/memory/**'" in text
    # blocking path uses the real Blocked board option id
    assert "93d87b2f" in text
    assert "PVTSSF_lAHOAAFds84BWh4wzhR1VaA" in text
    # posts the review via the Pulls Reviews API
    assert "/pulls/" in text and "/reviews" in text
    # writes the artifact the report node reads
    assert "review.md" in text
