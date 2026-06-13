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


def test_changed_lines_ignores_no_newline_marker():
    diff = (
        "diff --git a/a.py b/a.py\n"
        "--- a/a.py\n"
        "+++ b/a.py\n"
        "@@ -1,2 +1,2 @@\n"
        " context\n"
        "-old\n"
        "+new\n"
        "\\ No newline at end of file\n"
    )
    changed = crp.changed_lines(diff)
    # new side has exactly line 1 (context) and line 2 (added 'new'); no phantom line 3
    assert changed["a.py"] == {1, 2}


def _f(sev, path, line, desc="d", cat="c"):
    return crp.Finding(sev, cat, path, line, desc)


def test_build_review_blocks_on_high_and_anchors_inline():
    changed = {"a.py": {10, 11}}
    findings = [_f("high", "a.py", 10), _f("low", "a.py", 11)]
    r = crp.build_review(findings, changed, block_threshold="high", max_findings=50)
    assert r["status"] == "BLOCKED"
    assert r["event"] == "REQUEST_CHANGES"
    assert len(r["payload"]["comments"]) == 2
    assert r["payload"]["comments"][0]["side"] == "RIGHT"
    assert {c["line"] for c in r["payload"]["comments"]} == {10, 11}
    assert len(r["blockers"]) == 1 and len(r["advisory"]) == 1


def test_build_review_comment_event_when_no_blockers():
    changed = {"a.py": {5}}
    r = crp.build_review([_f("low", "a.py", 5)], changed, block_threshold="high")
    assert r["status"] == "PASS"
    assert r["event"] == "COMMENT"


def test_build_review_offdiff_findings_demoted_to_body():
    changed = {"a.py": {5}}
    # line 999 is not in the diff -> must not be an inline comment
    findings = [_f("high", "a.py", 999, desc="off-diff bug")]
    r = crp.build_review(findings, changed, block_threshold="high")
    assert r["payload"]["comments"] == []
    assert r["status"] == "BLOCKED"  # still a blocker even if not anchorable
    assert "off-diff bug" in r["payload"]["body"]
    assert r["offdiff_count"] == 1


def test_build_review_caps_inline_keeping_highest_severity():
    changed = {"a.py": set(range(1, 11))}
    findings = [_f("low", "a.py", i) for i in range(1, 6)] + [_f("high", "a.py", i) for i in range(6, 11)]
    r = crp.build_review(findings, changed, block_threshold="high", max_findings=5)
    assert len(r["payload"]["comments"]) == 5
    # all kept comments should be the high-severity ones (lines 6..10)
    assert all(c["line"] >= 6 for c in r["payload"]["comments"])


def test_build_review_threshold_critical_only():
    changed = {"a.py": {1, 2}}
    findings = [_f("high", "a.py", 1), _f("critical", "a.py", 2)]
    r = crp.build_review(findings, changed, block_threshold="critical")
    assert len(r["blockers"]) == 1  # only the critical one blocks
    assert r["status"] == "BLOCKED"


import json
import subprocess

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "code_review_payload.py"


def test_cli_emits_json(tmp_path):
    review = tmp_path / "review.md"
    review.write_text("### Findings\n- [high] security | a.py:1 | bug\n", encoding="utf-8")
    diff = tmp_path / "diff.txt"
    diff.write_text(
        "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1,0 +1,1 @@\n+x = 1\n",
        encoding="utf-8",
    )
    out = subprocess.check_output(
        [sys.executable, str(SCRIPT), "--review", str(review), "--diff", str(diff),
         "--block-threshold", "high", "--severity-order", "low,medium,high,critical",
         "--max-findings", "50"],
        text=True,
    )
    result = json.loads(out)
    assert result["status"] == "BLOCKED"
    assert result["event"] == "REQUEST_CHANGES"
    assert result["payload"]["comments"][0]["path"] == "a.py"
    assert result["payload"]["comments"][0]["line"] == 1


def test_missing_severity_order_exits_nonzero(tmp_path):
    review = tmp_path / "review.md"
    review.write_text("### Findings\nNo findings.\n", encoding="utf-8")
    diff = tmp_path / "diff.txt"
    diff.write_text("", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--review", str(review), "--diff", str(diff),
         "--block-threshold", "high"],
        capture_output=True, text=True,
    )
    assert proc.returncode != 0, "script must exit non-zero when --severity-order is omitted"
