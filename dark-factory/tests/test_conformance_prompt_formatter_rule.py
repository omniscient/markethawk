from pathlib import Path

PROMPT = (
    Path(__file__).resolve().parents[2]
    / ".claude" / "skills" / "refinement" / "conformance-reviewer-prompt.md"
)


def test_formatter_exception_rule_present():
    text = PROMPT.read_text(encoding="utf-8")
    assert "## Out-of-Scope Changes" in text, "section anchor missing"
    assert "Formatter / import-ordering exception" in text, "formatter rule not inserted"
    assert "ruff" in text, "rule must name ruff"
    assert "Do NOT emit an `[OOS]` bullet" in text, "rule must contain the exact prohibition"


def test_formatter_rule_precedes_oos_bullet_format():
    text = PROMPT.read_text(encoding="utf-8")
    fmt_pos = text.find("Formatter / import-ordering exception")
    oos_pos = text.find("- [OOS] <file or area>")
    assert fmt_pos != -1, "formatter rule not found"
    assert oos_pos != -1, "[OOS] example bullet not found"
    assert fmt_pos < oos_pos, "formatter rule must appear before the [OOS] bullet example"
