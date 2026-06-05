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


def test_parse_findings_two_field_category_and_desc():
    f = crp.parse_findings("- [high] security | SQL via f-string")
    assert len(f) == 1
    assert f[0].category == "security"
    assert f[0].path is None and f[0].line is None
    assert f[0].description == "SQL via f-string"


def test_parse_findings_two_field_location_and_desc():
    f = crp.parse_findings("- [high] backend/app/x.py:42 | SQL via f-string")
    assert len(f) == 1
    assert f[0].category == ""
    assert f[0].path == "backend/app/x.py" and f[0].line == 42
    assert f[0].description == "SQL via f-string"


def test_parse_findings_line_zero_is_not_anchorable():
    f = crp.parse_findings("- [low] naming | foo.py:0 | rename x")
    assert len(f) == 1
    assert f[0].path == "foo.py" and f[0].line is None


DIFF = """diff --git a/backend/app/x.py b/backend/app/x.py
index 1111111..2222222 100644
--- a/backend/app/x.py
+++ b/backend/app/x.py
@@ -40,3 +40,5 @@ def handler():
 context_line
+added_line_41
+added_line_42
 trailing_context
+added_line_44
diff --git a/gone.py b/gone.py
deleted file mode 100644
--- a/gone.py
+++ /dev/null
@@ -1,2 +0,0 @@
-was_here
-also_here
"""


def test_changed_lines_tracks_right_side_only():
    changed = crp.changed_lines(DIFF)
    # @@ +40,5 -> new file lines start at 40
    # 40 context, 41 added, 42 added, 43 context, 44 added
    assert changed["backend/app/x.py"] == {40, 41, 42, 43, 44}


def test_changed_lines_ignores_deleted_file():
    changed = crp.changed_lines(DIFF)
    assert "/dev/null" not in changed
    assert "gone.py" not in changed
