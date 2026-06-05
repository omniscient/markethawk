import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import code_review_payload as crp  # noqa: E402


def test_parse_findings_basic():
    text = """
## Code Review

### Findings
- [high] security | backend/app/x.py:42 | SQL via f-string; use bound params
- [low] naming | frontend/src/foo.ts:88 | rename tmp to parsedRow
""".strip()
    findings = crp.parse_findings(text)
    assert len(findings) == 2
    assert findings[0].severity == "high"
    assert findings[0].category == "security"
    assert findings[0].path == "backend/app/x.py"
    assert findings[0].line == 42
    assert "bound params" in findings[0].description
    assert findings[1].severity == "low"
    assert findings[1].path == "frontend/src/foo.ts"
    assert findings[1].line == 88


def test_parse_findings_no_findings_marker():
    assert crp.parse_findings("### Findings\nNo findings.") == []


def test_parse_findings_location_without_line_goes_to_path_only():
    findings = crp.parse_findings("- [medium] maintainability | backend/app/x.py | broad except")
    assert len(findings) == 1
    assert findings[0].path == "backend/app/x.py"
    assert findings[0].line is None
