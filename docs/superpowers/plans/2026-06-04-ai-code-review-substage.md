# AI Code-Review Sub-Stage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `code-review` node to the dark-factory pipeline that reviews `git diff main...HEAD` with an Opus-4.8 subagent, blocks the PR on critical/high findings, and posts the rest as inline PR review comments.

**Architecture:** A new clone-read command (`dark-factory-code-review`) runs as a workflow node after `push-and-pr` and before `status-in-review`. It spawns a reviewer subagent (markdown-driven, like `conformance`), then hands the reviewer's output + the diff to a small pure-stdlib helper (`code_review_payload.py`) that deterministically parses findings, anchors them to diff lines, applies the block threshold, and builds the GitHub review payload. The command posts the review via `gh api` and, on blockers, diverts the issue to Blocked (mirroring conformance Phase 5). Config + kill-switch live in `config.yaml`.

**Tech Stack:** Archon workflow YAML + markdown command files, Python 3 (stdlib only) for the helper, pytest for its tests, `gh` CLI for GitHub, the GitHub Pulls Reviews API.

**Spec:** `docs/superpowers/specs/2026-06-04-ai-code-review-substage-design.md`

**Reference precedent (read before starting):**
- `.archon/commands/dark-factory-conformance.md` — the subagent + gate + Blocked pattern to mirror.
- `.claude/skills/refinement/conformance-reviewer-prompt.md` — the reviewer-prompt + output-format pattern.
- `.archon/workflows/archon-dark-factory.yaml` — `validate` (716), `conformance` (723), `push-and-pr` (752), `status-in-review` (860), `report` (886) nodes.

**Board IDs (from conformance Phase 5 / status-in-review):** project `PVT_kwHOAAFds84BWh4w`, status field `PVTSSF_lAHOAAFds84BWh4wzhR1VaA`, option `Blocked = 93d87b2f`, option `In Review = df73e18b`.

**Note on the helper (intentional spec refinement):** the spec described the parse/anchor/payload logic as inline command steps. This plan extracts the deterministic, error-prone parts (diff-line anchoring + JSON payload construction) into a tested helper script so off-by-one anchoring bugs that would 422 the GitHub API are caught by tests, not in production. The helper is clone-read (run via `python3`), so it preserves the spec's "no image rebuild" property.

---

## File Structure

| File | Responsibility |
|---|---|
| `dark-factory/scripts/code_review_payload.py` | **NEW** Pure-stdlib: parse reviewer findings → anchor to diff lines → apply block threshold → emit GitHub review payload JSON + gate status. |
| `dark-factory/tests/test_code_review_payload.py` | **NEW** pytest unit tests for the helper. |
| `.claude/skills/refinement/code-review-reviewer-prompt.md` | **NEW** Reviewer subagent prompt + machine-parseable output format. |
| `.archon/commands/dark-factory-code-review.md` | **NEW** The command: LOAD → DIFF → REVIEW → helper → POST → BLOCK/PASS. |
| `.claude/skills/refinement/config.yaml` | **MODIFY** add the `code_review` block. |
| `.archon/workflows/archon-dark-factory.yaml` | **MODIFY** add `code-review` node; wire `status-in-review`/`report` `depends_on`; add Code Review section to `report` body. |

**Finding wire format (used by the prompt and the parser — keep them in sync):**
Each machine-readable finding is one bullet:
`- [severity] category | path:line | description`
Example: `- [high] security | backend/app/routers/x.py:42 | SQL built via f-string; use bound params`
Fields are pipe-delimited (`|`) to avoid em-dash/hyphen ambiguity. `severity ∈ {critical, high, medium, low}`.

---

## Task 1: Config block (`code_review`)

**Files:**
- Modify: `.claude/skills/refinement/config.yaml`
- Test: `dark-factory/tests/test_config_code_review.py` (create)

- [ ] **Step 1: Write the failing test**

Create `dark-factory/tests/test_config_code_review.py`:

```python
from pathlib import Path
import yaml

CONFIG = Path(__file__).resolve().parents[2] / ".claude" / "skills" / "refinement" / "config.yaml"

def test_code_review_block_present_with_defaults():
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    cr = cfg.get("code_review")
    assert cr is not None, "config.yaml is missing the code_review block"
    assert cr["enabled"] is True
    assert cr["block_threshold"] == "high"
    assert cr["fail_open"] is True
    assert cr["max_findings"] == 50
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest dark-factory/tests/test_config_code_review.py -v`
Expected: FAIL — `cr is None` (block not yet added).

- [ ] **Step 3: Add the block**

Append to `.claude/skills/refinement/config.yaml` (after the `conformance:` block, before `preview:`), matching the file's existing 2-space indentation and comment style:

```yaml
code_review:
  enabled: true
  block_threshold: high     # findings at this severity or above block (critical|high|medium|low)
  fail_open: true           # reviewer error / unparseable output → advisory, never block
  max_findings: 50          # cap inline comments to avoid spam (log if exceeded)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest dark-factory/tests/test_config_code_review.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/refinement/config.yaml dark-factory/tests/test_config_code_review.py
git commit -m "feat(dark-factory): add code_review config block [#218]"
```

---

## Task 2: Helper — `parse_findings`

**Files:**
- Create: `dark-factory/scripts/code_review_payload.py`
- Test: `dark-factory/tests/test_code_review_payload.py` (create)

- [ ] **Step 1: Write the failing test**

Create `dark-factory/tests/test_code_review_payload.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest dark-factory/tests/test_code_review_payload.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'code_review_payload'`.

- [ ] **Step 3: Create the helper with `parse_findings`**

Create `dark-factory/scripts/code_review_payload.py`:

```python
"""Build a GitHub PR review payload from a code-reviewer subagent's findings.

Pure stdlib. Given the reviewer's markdown output and the unified diff that was
reviewed, this parses severity-tagged findings, anchors each to a changed line on
the RIGHT side of the diff, demotes off-diff findings into the review body, decides
the review event (REQUEST_CHANGES if any finding >= block_threshold else COMMENT),
and caps inline comments at max_findings (highest severity kept).

Used by .archon/commands/dark-factory-code-review.md (clone-read; no image rebuild).

Finding wire format (one bullet per finding):
    - [severity] category | path:line | description
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from typing import Optional

SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}

_FINDING_RE = re.compile(r"\s*-\s*\[(critical|high|medium|low)\]\s*(.+)$", re.IGNORECASE)
_LOC_RE = re.compile(r"^(?P<path>.+?):(?P<line>\d+)\s*$")


@dataclass
class Finding:
    severity: str
    category: str
    path: Optional[str]
    line: Optional[int]
    description: str


def _split_loc(loc: str):
    m = _LOC_RE.match((loc or "").strip())
    if m:
        return m.group("path").strip(), int(m.group("line"))
    cleaned = (loc or "").strip()
    return (cleaned or None), None


def parse_findings(text: str):
    """Parse `- [sev] category | path:line | desc` bullets anywhere in the text."""
    findings = []
    for raw in (text or "").splitlines():
        m = _FINDING_RE.match(raw)
        if not m:
            continue
        severity = m.group(1).lower()
        fields = [p.strip() for p in m.group(2).split("|")]
        if len(fields) >= 3:
            category, loc, description = fields[0], fields[1], " | ".join(fields[2:])
        elif len(fields) == 2:
            category, loc, description = "", fields[0], fields[1]
        else:
            category, loc, description = "", "", fields[0]
        path, line = _split_loc(loc)
        findings.append(Finding(severity, category, path, line, description.strip()))
    return findings
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest dark-factory/tests/test_code_review_payload.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add dark-factory/scripts/code_review_payload.py dark-factory/tests/test_code_review_payload.py
git commit -m "feat(dark-factory): code-review helper — parse_findings [#218]"
```

---

## Task 3: Helper — `changed_lines` (diff hunk parser)

**Files:**
- Modify: `dark-factory/scripts/code_review_payload.py`
- Test: `dark-factory/tests/test_code_review_payload.py`

- [ ] **Step 1: Write the failing test**

Append to `dark-factory/tests/test_code_review_payload.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest dark-factory/tests/test_code_review_payload.py -k changed_lines -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'changed_lines'`.

- [ ] **Step 3: Add `changed_lines`**

Append to `dark-factory/scripts/code_review_payload.py` (after `parse_findings`):

```python
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def changed_lines(diff_text: str):
    """Map each changed file -> set of RIGHT-side (new) line numbers present in the diff.

    Added ('+') and context (' ') lines advance the new-file counter and are anchorable;
    removed ('-') lines do not. Deleted files (+++ /dev/null) are skipped.
    """
    result = {}
    current = None
    new_ln = 0
    for line in (diff_text or "").splitlines():
        if line.startswith("diff --git"):
            current = None
            continue
        if line.startswith("+++ "):
            path = line[4:].strip()
            if path.startswith("b/"):
                path = path[2:]
            current = None if path == "/dev/null" else path
            if current:
                result.setdefault(current, set())
            continue
        if line.startswith("--- "):
            continue
        m = _HUNK_RE.match(line)
        if m:
            new_ln = int(m.group(1))
            continue
        if current is None:
            continue
        if line.startswith("+"):
            result.setdefault(current, set()).add(new_ln)
            new_ln += 1
        elif line.startswith("-"):
            continue  # left side only
        else:  # context line (leading space) or blank
            result.setdefault(current, set()).add(new_ln)
            new_ln += 1
    return result
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest dark-factory/tests/test_code_review_payload.py -k changed_lines -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add dark-factory/scripts/code_review_payload.py dark-factory/tests/test_code_review_payload.py
git commit -m "feat(dark-factory): code-review helper — changed_lines diff parser [#218]"
```

---

## Task 4: Helper — `build_review` (gate + anchor + cap + payload)

**Files:**
- Modify: `dark-factory/scripts/code_review_payload.py`
- Test: `dark-factory/tests/test_code_review_payload.py`

- [ ] **Step 1: Write the failing test**

Append to `dark-factory/tests/test_code_review_payload.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest dark-factory/tests/test_code_review_payload.py -k build_review -v`
Expected: FAIL — `AttributeError: ... 'build_review'`.

- [ ] **Step 3: Add `build_review` and its body/comment formatters**

Append to `dark-factory/scripts/code_review_payload.py` (after `changed_lines`):

```python
def _comment_body(f: Finding) -> str:
    cat = f"**{f.category}** · " if f.category else ""
    return f"{cat}**{f.severity}** — {f.description}"


def _review_body(header, blockers, advisory, offdiff, dropped_count):
    lines = [f"## {header}", ""]
    lines.append(
        f"**{len(blockers)}** blocking · **{len(advisory)}** advisory finding(s)."
    )
    if blockers:
        lines += ["", "### ⛔ Blocking"]
        for f in blockers:
            loc = f"`{f.path}:{f.line}`" if f.path and f.line else (f"`{f.path}`" if f.path else "_(no location)_")
            lines.append(f"- **[{f.severity}] {f.category}** {loc} — {f.description}")
    if offdiff:
        lines += ["", "### Findings not anchorable to the diff"]
        for f in offdiff:
            loc = f"`{f.path}:{f.line}`" if f.path and f.line else (f"`{f.path}`" if f.path else "_(no location)_")
            lines.append(f"- [{f.severity}] {f.category} {loc} — {f.description}")
    if dropped_count:
        lines += ["", f"_Note: {dropped_count} additional inline comment(s) dropped (max_findings cap)._"]
    return "\n".join(lines)


def build_review(findings, changed, block_threshold="high", max_findings=50,
                 header="🏭 Dark Factory Code Review"):
    thr = SEVERITY_ORDER[block_threshold.lower()]
    blockers = [f for f in findings if SEVERITY_ORDER[f.severity] >= thr]
    advisory = [f for f in findings if SEVERITY_ORDER[f.severity] < thr]

    def anchorable(f):
        return f.path is not None and f.line is not None and f.line in changed.get(f.path, set())

    anchored = sorted(
        (f for f in findings if anchorable(f)),
        key=lambda f: (-SEVERITY_ORDER[f.severity], f.path, f.line),
    )
    offdiff = [f for f in findings if not anchorable(f)]
    kept = anchored[:max_findings]
    dropped = anchored[max_findings:]
    offdiff_for_body = offdiff + dropped

    comments = [{"path": f.path, "line": f.line, "side": "RIGHT", "body": _comment_body(f)} for f in kept]
    event = "REQUEST_CHANGES" if blockers else "COMMENT"
    body = _review_body(header, blockers, advisory, offdiff_for_body, len(dropped))
    status = "BLOCKED" if blockers else "PASS"
    return {
        "status": status,
        "event": event,
        "payload": {"event": event, "body": body, "comments": comments},
        "blockers": [f.__dict__ for f in blockers],
        "advisory": [f.__dict__ for f in advisory],
        "inline_count": len(comments),
        "offdiff_count": len(offdiff_for_body),
    }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest dark-factory/tests/test_code_review_payload.py -k build_review -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add dark-factory/scripts/code_review_payload.py dark-factory/tests/test_code_review_payload.py
git commit -m "feat(dark-factory): code-review helper — build_review gate+anchor+cap [#218]"
```

---

## Task 5: Helper — CLI entrypoint

**Files:**
- Modify: `dark-factory/scripts/code_review_payload.py`
- Test: `dark-factory/tests/test_code_review_payload.py`

- [ ] **Step 1: Write the failing test**

Append to `dark-factory/tests/test_code_review_payload.py`:

```python
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
         "--block-threshold", "high", "--max-findings", "50"],
        text=True,
    )
    result = json.loads(out)
    assert result["status"] == "BLOCKED"
    assert result["event"] == "REQUEST_CHANGES"
    assert result["payload"]["comments"][0]["path"] == "a.py"
    assert result["payload"]["comments"][0]["line"] == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest dark-factory/tests/test_code_review_payload.py -k cli -v`
Expected: FAIL — script has no `__main__`, so `subprocess` output is empty and `json.loads` raises.

- [ ] **Step 3: Add the CLI entrypoint**

Append to `dark-factory/scripts/code_review_payload.py`:

```python
def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build a GitHub PR review payload from reviewer findings.")
    ap.add_argument("--review", required=True, help="path to the reviewer subagent's markdown output")
    ap.add_argument("--diff", required=True, help="path to the unified diff that was reviewed")
    ap.add_argument("--block-threshold", default="high", choices=list(SEVERITY_ORDER))
    ap.add_argument("--max-findings", type=int, default=50)
    args = ap.parse_args(argv)
    findings = parse_findings(_read(args.review))
    changed = changed_lines(_read(args.diff))
    result = build_review(findings, changed, args.block_threshold, args.max_findings)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the full helper test suite to verify all pass**

Run: `python -m pytest dark-factory/tests/test_code_review_payload.py -v`
Expected: PASS (all tests from Tasks 2–5).

- [ ] **Step 5: Commit**

```bash
git add dark-factory/scripts/code_review_payload.py dark-factory/tests/test_code_review_payload.py
git commit -m "feat(dark-factory): code-review helper — CLI entrypoint [#218]"
```

---

## Task 6: Reviewer prompt

**Files:**
- Create: `.claude/skills/refinement/code-review-reviewer-prompt.md`
- Test: `dark-factory/tests/test_code_review_prompt.py` (create)

- [ ] **Step 1: Write the failing test**

Create `dark-factory/tests/test_code_review_prompt.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest dark-factory/tests/test_code_review_prompt.py -v`
Expected: FAIL — `FileNotFoundError` (prompt not created yet).

- [ ] **Step 3: Create the prompt**

Create `.claude/skills/refinement/code-review-reviewer-prompt.md`:

````markdown
# Code Reviewer — MarketHawk

You are a senior code reviewer for the MarketHawk dark factory pipeline. You review a code
diff for **correctness, edge cases, naming, and security** and produce a structured,
severity-tagged finding list. You are not judging spec conformance (that is the conformance
reviewer's job) — you judge whether the code is correct, safe, and maintainable.

## Input

- `$ISSUE_CONTEXT`: the GitHub issue title and body (what this change is meant to do).
- `$DIFF_CONTENT`: the unified diff of the implementation (`git diff main...HEAD`, pre-triaged,
  possibly truncated to 1000 lines).

## What to judge

For the changed code, look for:

1. **Security** — injection (SQL/command/path), auth/authorization bypass, secret leakage,
   unsafe deserialization, SSRF, missing input validation on a trust boundary.
2. **Correctness** — logic that produces wrong results, crashes, unhandled error paths,
   race conditions, resource leaks, off-by-one, incorrect async/await usage.
3. **Edge cases** — empty/None inputs, boundary values, timezone/session-window handling,
   pagination, partial failures.
4. **Naming & maintainability** — misleading names, dead code, duplicated logic, missing or
   wrong types, overly broad excepts.

Only report issues in the **changed** lines (or directly caused by them). Do not review
pre-existing code that the diff merely moves or leaves untouched.

## Severity

- **critical** — exploitable security hole, data loss/corruption, or a bug that breaks the
  feature's core path for all users.
- **high** — a real correctness or security bug that produces wrong results, crashes, or
  unsafe behavior under realistic input.
- **medium** — a recoverable edge case, a missing guard, or a bug with limited blast radius.
- **low** — naming, readability, dead code, or a test-coverage suggestion.

`critical` and `high` block the PR; `medium` and `low` become advisory inline comments.

## Categories

`security`, `correctness`, `edge-case`, `naming`, `maintainability`.

## Output format

Respond with exactly this structure and nothing outside it. The `### Findings` bullets are
machine-parsed — they MUST use the pipe-delimited format shown, with a real `path:line` taken
from the diff:

```
## Code Review

| # | Severity | Category | Location | Finding |
|---|----------|----------|----------|---------|
| 1 | high | security | backend/app/routers/x.py:42 | SQL built via f-string |
| 2 | low | naming | frontend/src/foo.ts:88 | rename tmp to parsedRow |

### Findings
- [severity] category | path:line | description
- [high] security | backend/app/routers/x.py:42 | SQL built via f-string; use bound params
- [low] naming | frontend/src/foo.ts:88 | rename `tmp` to `parsedRow`

(If there are no findings, write exactly: No findings.)
```

Rules:
- Every `### Findings` bullet MUST be `- [severity] category | path:line | description`.
- `severity` is one of `critical|high|medium|low`. `path:line` must be a file and line that
  appear on the new side of `$DIFF_CONTENT`. If you cannot tie a finding to a specific changed
  line, still report it with the closest `path:line` you can, or `path` alone — it will be
  surfaced in the review body rather than inline.
- Keep each description to one or two sentences with a concrete suggested fix.

## Context

### Issue
$ISSUE_CONTEXT

### Diff
$DIFF_CONTENT
````

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest dark-factory/tests/test_code_review_prompt.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/refinement/code-review-reviewer-prompt.md dark-factory/tests/test_code_review_prompt.py
git commit -m "feat(dark-factory): add code-review reviewer prompt [#218]"
```

---

## Task 7: The command file (`dark-factory-code-review`)

**Files:**
- Create: `.archon/commands/dark-factory-code-review.md`
- Test: `dark-factory/tests/test_code_review_command.py` (create)

- [ ] **Step 1: Write the failing test**

Create `dark-factory/tests/test_code_review_command.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest dark-factory/tests/test_code_review_command.py -v`
Expected: FAIL — `FileNotFoundError` (command not created yet).

- [ ] **Step 3: Create the command**

Create `.archon/commands/dark-factory-code-review.md`:

````markdown
---
description: AI code review of the implementation diff — blocks the PR on critical/high findings, inline-comments the rest (Gate 3)
argument-hint: (no arguments - reads issue/PR context from the workflow)
---

# Dark Factory — Code Review

**Workflow ID**: $WORKFLOW_ID

---

## Phase 1: LOAD

1. Read the `code_review` block from `.claude/skills/refinement/config.yaml`.
2. If `code_review.enabled` is `false`:
   - Write `$ARTIFACTS_DIR/review.md` with content: `STATUS: SKIPPED\nREASON: code_review.enabled=false`
   - Exit cleanly (`exit 0`) — `status-in-review` and `report` proceed.
3. Extract `BLOCK_THRESHOLD` from `code_review.block_threshold` (default: `high`).
4. Extract `FAIL_OPEN` from `code_review.fail_open` (default: `true`).
5. Extract `MAX_FINDINGS` from `code_review.max_findings` (default: `50`).
6. Determine `ISSUE_NUM` (from workflow context, or `git branch --show-current | grep -oP 'issue-\K\d+'`).
7. Determine `PR_NUM`:
   ```bash
   BRANCH=$(git branch --show-current)
   PR_NUM=$(gh pr list --repo omniscient/markethawk --head "$BRANCH" --json number --jq '.[0].number // empty')
   ```
   If `PR_NUM` is empty, write `STATUS: ERROR\nREASON: no PR found` to `$ARTIFACTS_DIR/review.md` and exit `0` (fail-open — never block the board on missing PR).

## Phase 2: DIFF

Build the review diff with the SAME pre-triage exclusions the conformance gate uses, and save it:

```bash
git diff main...HEAD \
  -- ':!*.lock' ':!*.md' \
  ':!.archon/memory/**' \
  ':!codeindex.json' ':!symbolindex.json' \
  ':!docs/codeindex-hotspots.md' \
  ':!docs/database-schema.md' \
  2>/dev/null | head -1000 > "$ARTIFACTS_DIR/review_diff.txt"
```

- If the diff was truncated at 1000 lines (`wc -l` reports exactly 1000), log: "code-review: diff truncated to 1000 lines — some lines may not be anchorable."
- If `$ARTIFACTS_DIR/review_diff.txt` is empty, write `STATUS: PASS\nBLOCKERS: 0\nADVISORY: 0` to `$ARTIFACTS_DIR/review.md` and exit `0` (nothing to review).

## Phase 3: REVIEW

1. Build `$ISSUE_CONTEXT` = issue title + body:
   ```bash
   gh issue view "$ISSUE_NUM" --repo omniscient/markethawk --json title,body \
     --jq '"Title: \(.title)\n\n\(.body)"'
   ```
2. Read `.claude/skills/refinement/code-review-reviewer-prompt.md`.
3. Spawn a code-reviewer subagent using the Agent tool:
   - `description`: "Code review: diff vs correctness/security"
   - `model`: `claude-opus-4-8` — **always** pin this subagent to Opus 4.8; do not let it inherit the orchestrator's model.
   - `prompt`: the reviewer-prompt content with `$ISSUE_CONTEXT` replaced by the issue context from step 1 and `$DIFF_CONTENT` replaced by the contents of `$ARTIFACTS_DIR/review_diff.txt`.
4. Save the subagent's full output to `$ARTIFACTS_DIR/review_findings.md`.
   - If the subagent errored, timed out, or returned empty/unparseable output:
     - If `FAIL_OPEN=true` → write `STATUS: ERROR\nBLOCKERS: 0\nADVISORY: 0` to `$ARTIFACTS_DIR/review.md`, skip Phases 4–6, exit `0`.
     - If `FAIL_OPEN=false` → treat as a single blocker: skip to Phase 6 BLOCK with a generic "code review could not complete" message.

## Phase 4: BUILD PAYLOAD

Run the deterministic helper to parse findings, anchor them to the diff, apply the threshold, and build the GitHub review payload:

```bash
python3 dark-factory/scripts/code_review_payload.py \
  --review "$ARTIFACTS_DIR/review_findings.md" \
  --diff "$ARTIFACTS_DIR/review_diff.txt" \
  --block-threshold "$BLOCK_THRESHOLD" \
  --max-findings "$MAX_FINDINGS" \
  > "$ARTIFACTS_DIR/review_result.json"
```

Read fields from `$ARTIFACTS_DIR/review_result.json`:
- `STATUS = .status` (PASS | BLOCKED)
- `BLOCKERS = (.blockers | length)`
- `ADVISORY = (.advisory | length)`
- The `.payload` object is the body to POST.

If `BLOCKERS == 0` and `ADVISORY == 0` (no findings), write `STATUS: PASS\nBLOCKERS: 0\nADVISORY: 0` to `$ARTIFACTS_DIR/review.md` and exit `0` without posting an empty review.

## Phase 5: POST the review

Post a single GitHub review carrying the inline comments + body:

```bash
jq '.payload' "$ARTIFACTS_DIR/review_result.json" > "$ARTIFACTS_DIR/review_payload.json"
gh api "repos/omniscient/markethawk/pulls/$PR_NUM/reviews" \
  --method POST --input "$ARTIFACTS_DIR/review_payload.json" || \
  echo "code-review: WARNING — posting the PR review failed (continuing to gate decision)"
```

A failed POST is non-fatal — the gate decision below still applies.

## Phase 6: BLOCK or PASS

### If `STATUS` is `PASS` (no blockers)

Write to `$ARTIFACTS_DIR/review.md`:
```
STATUS: PASS
BLOCKERS: 0
ADVISORY: <ADVISORY>
THRESHOLD: <BLOCK_THRESHOLD>

---

<contents of $ARTIFACTS_DIR/review_findings.md>
```
Exit `0`. `status-in-review` and `report` proceed.

### If `STATUS` is `BLOCKED`

1. Post a "Code Review — Blocked" comment on the issue, listing the blocking findings (from `.blockers` in the result JSON):
   ```bash
   gh issue comment "$ISSUE_NUM" --repo omniscient/markethawk --body "## Code Review — Blocked

   The AI code reviewer found ${BLOCKERS} blocking issue(s) (severity ≥ ${BLOCK_THRESHOLD}). See the inline comments on PR #${PR_NUM}.

   $(jq -r '.blockers[] | \"- **[\(.severity)] \(.category)** \(.path):\(.line) — \(.description)\"' \"$ARTIFACTS_DIR/review_result.json\")

   ### Next Steps
   Fix the issues and re-run: \`docker compose --profile factory run --rm dark-factory \\\"Continue issue #${ISSUE_NUM}\\\"\`, or add \`needs-discussion\` if a finding is a false positive.

   ---
   *Posted by MarketHawk Dark Factory*"
   ```
2. Move the issue to **Blocked** on the project board:
   ```bash
   ITEM_ID=$(gh project item-list 1 --owner omniscient --format json --limit 200 \
     | jq -r ".items[] | select(.content.number == $ISSUE_NUM and .content.type == \"Issue\") | .id")
   if [ -n "$ITEM_ID" ]; then
     gh project item-edit \
       --project-id PVT_kwHOAAFds84BWh4w \
       --id "$ITEM_ID" \
       --field-id PVTSSF_lAHOAAFds84BWh4wzhR1VaA \
       --single-select-option-id 93d87b2f
   fi
   ```
3. Add the `needs-discussion` label:
   ```bash
   gh issue edit "$ISSUE_NUM" --repo omniscient/markethawk --add-label needs-discussion
   ```
4. Write to `$ARTIFACTS_DIR/review.md`:
   ```
   STATUS: BLOCKED
   BLOCKERS: <BLOCKERS>
   ADVISORY: <ADVISORY>
   THRESHOLD: <BLOCK_THRESHOLD>

   ---

   <contents of $ARTIFACTS_DIR/review_findings.md>
   ```
5. Exit non-zero (`exit 1`) — this halts `status-in-review` (the issue stays Blocked instead of moving to In Review).
````

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest dark-factory/tests/test_code_review_command.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add .archon/commands/dark-factory-code-review.md dark-factory/tests/test_code_review_command.py
git commit -m "feat(dark-factory): add dark-factory-code-review command [#218]"
```

---

## Task 8: Wire the workflow node

**Files:**
- Modify: `.archon/workflows/archon-dark-factory.yaml`
- Test: `dark-factory/tests/test_workflow_code_review.py` (create)

- [ ] **Step 1: Write the failing test**

Create `dark-factory/tests/test_workflow_code_review.py`:

```python
from pathlib import Path
import yaml

WF = Path(__file__).resolve().parents[2] / ".archon" / "workflows" / "archon-dark-factory.yaml"


def _nodes():
    data = yaml.safe_load(WF.read_text(encoding="utf-8"))
    return {n["id"]: n for n in data["nodes"]}


def test_code_review_node_exists_and_is_wired():
    nodes = _nodes()
    assert "code-review" in nodes, "workflow is missing the code-review node"
    cr = nodes["code-review"]
    assert cr["command"] == "dark-factory-code-review"
    assert "push-and-pr" in cr["depends_on"]
    assert "new" in cr["when"] and "continue" in cr["when"]


def test_status_in_review_depends_on_code_review():
    nodes = _nodes()
    assert "code-review" in nodes["status-in-review"]["depends_on"]


def test_report_depends_on_code_review():
    nodes = _nodes()
    assert "code-review" in nodes["report"]["depends_on"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest dark-factory/tests/test_workflow_code_review.py -v`
Expected: FAIL — `code-review` not in nodes.

- [ ] **Step 3: Add the node and rewire dependents**

In `.archon/workflows/archon-dark-factory.yaml`, insert this node immediately after the `push-and-pr` node (after its closing `timeout: 30000` at ~line 857), before the `status-in-review` node:

```yaml
  # Layer 4.5: AI code review of the diff (Gate 3 — correctness/security)
  - id: code-review
    command: dark-factory-code-review
    depends_on: [push-and-pr]
    when: "$parse-intent.output.intent == 'new' || $parse-intent.output.intent == 'continue'"
    idle_timeout: 600000
```

Then update the `status-in-review` node's `depends_on` (currently `[push-and-pr, push-resolve]`) to add `code-review`:

```yaml
    depends_on: [push-and-pr, push-resolve, code-review]
```

And update the `report` node's `depends_on` (currently `[status-in-review]`) to add `code-review`:

```yaml
    depends_on: [status-in-review, code-review]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest dark-factory/tests/test_workflow_code_review.py -v`
Expected: PASS (3 tests). Also confirm the YAML still parses:
Run: `python -c "import yaml; yaml.safe_load(open('.archon/workflows/archon-dark-factory.yaml', encoding='utf-8')); print('yaml ok')"`
Expected: `yaml ok`.

- [ ] **Step 5: Commit**

```bash
git add .archon/workflows/archon-dark-factory.yaml dark-factory/tests/test_workflow_code_review.py
git commit -m "feat(dark-factory): add code-review workflow node and wiring [#218]"
```

---

## Task 9: Report-node Code Review section

**Files:**
- Modify: `.archon/workflows/archon-dark-factory.yaml` (the `report` node bash body)
- Test: `dark-factory/tests/test_report_code_review_section.py` (create)

- [ ] **Step 1: Write the failing test**

Create `dark-factory/tests/test_report_code_review_section.py`:

```python
from pathlib import Path

WF = Path(__file__).resolve().parents[2] / ".archon" / "workflows" / "archon-dark-factory.yaml"


def test_report_node_renders_code_review_section():
    text = WF.read_text(encoding="utf-8")
    assert "review.md" in text, "report node must read the code-review artifact"
    assert "### Code Review" in text, "report node must render a Code Review section"
    assert "CODE_REVIEW_SECTION" in text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest dark-factory/tests/test_report_code_review_section.py -v`
Expected: FAIL — no `### Code Review` / `CODE_REVIEW_SECTION` in the workflow yet.

- [ ] **Step 3: Add the section to the `report` node**

In the `report` node bash body, after the `CONFORMANCE_SECTION` block ends (after its `fi`, ~line 944) and before the `# --- Build the Preview Environment section ---` comment, insert:

```bash
      CODE_REVIEW_SECTION=""
      if [ -f "$ARTIFACTS_DIR/review.md" ]; then
        CR_STATUS=$(grep '^STATUS:' "$ARTIFACTS_DIR/review.md" | cut -d' ' -f2)
        CR_BLOCKERS=$(grep '^BLOCKERS:' "$ARTIFACTS_DIR/review.md" | cut -d' ' -f2)
        CR_ADVISORY=$(grep '^ADVISORY:' "$ARTIFACTS_DIR/review.md" | cut -d' ' -f2)
        case "$CR_STATUS" in
          PASS)
            CODE_REVIEW_SECTION=$(printf "### Code Review\n\n✅ Passed — %s advisory finding(s), 0 blocking. See PR review comments." "${CR_ADVISORY:-0}")
            ;;
          BLOCKED)
            CODE_REVIEW_SECTION=$(printf "### Code Review\n\n⛔ Blocked — %s blocking finding(s). Issue moved to Blocked; see PR review comments." "${CR_BLOCKERS:-0}")
            ;;
          SKIPPED)
            CODE_REVIEW_SECTION=$(printf "### Code Review\n\n_Code review disabled (code_review.enabled=false)._")
            ;;
          ERROR)
            CODE_REVIEW_SECTION=$(printf "### Code Review\n\n_Code review could not complete (advisory; did not block)._")
            ;;
          *)
            CODE_REVIEW_SECTION=""
            ;;
        esac
      fi
```

Then add `${CODE_REVIEW_SECTION}` to the `gh issue comment` body, immediately after the `${CONFORMANCE_SECTION}` line:

```bash
      ${CONFORMANCE_SECTION}
      ${CODE_REVIEW_SECTION}
      ${CONFLICT_SECTION}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest dark-factory/tests/test_report_code_review_section.py -v`
Expected: PASS. Confirm YAML still parses:
Run: `python -c "import yaml; yaml.safe_load(open('.archon/workflows/archon-dark-factory.yaml', encoding='utf-8')); print('yaml ok')"`
Expected: `yaml ok`.

- [ ] **Step 5: Commit**

```bash
git add .archon/workflows/archon-dark-factory.yaml dark-factory/tests/test_report_code_review_section.py
git commit -m "feat(dark-factory): surface code-review status in the run report [#218]"
```

---

## Task 10: Full-suite check and plan-level verification

**Files:**
- (no new files — verification only)

- [ ] **Step 1: Run the entire code-review test suite**

Run: `python -m pytest dark-factory/tests/ -v`
Expected: PASS — all tests from Tasks 1–9.

- [ ] **Step 2: Verify the helper runs end-to-end against the real workflow diff**

Smoke-test the helper with a tiny hand-made diff + findings file (no network needed):

```bash
printf '### Findings\n- [high] security | a.py:1 | bug\n' > /tmp/cr_review.md
printf 'diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1,0 +1,1 @@\n+x = 1\n' > /tmp/cr_diff.txt
python3 dark-factory/scripts/code_review_payload.py --review /tmp/cr_review.md --diff /tmp/cr_diff.txt --block-threshold high --max-findings 50 | python -m json.tool
```
Expected: JSON with `"status": "BLOCKED"`, `"event": "REQUEST_CHANGES"`, one comment on `a.py:1`.

- [ ] **Step 3: Confirm both edited YAML/config files still parse**

```bash
python -c "import yaml; yaml.safe_load(open('.archon/workflows/archon-dark-factory.yaml', encoding='utf-8')); yaml.safe_load(open('.claude/skills/refinement/config.yaml', encoding='utf-8')); print('all yaml ok')"
```
Expected: `all yaml ok`.

- [ ] **Step 4: Confirm the conformance precedent is unbroken**

Confirm we only ADDED to `status-in-review`/`report` `depends_on` and did not remove `push-resolve` or `status-in-review`:

```bash
git diff main -- .archon/workflows/archon-dark-factory.yaml | grep -E "depends_on" | grep -E "code-review|push-resolve|status-in-review"
```
Expected: shows `code-review` added alongside the existing dependencies (no deletions of existing deps).

- [ ] **Step 5: Final commit (if anything was adjusted during verification)**

```bash
git add -A
git commit -m "test(dark-factory): full-suite verification for code-review sub-stage [#218]" || echo "nothing to commit"
```

---

## Done criteria

- `python -m pytest dark-factory/tests/ -v` is green.
- `.archon/workflows/archon-dark-factory.yaml` parses and contains a `code-review` node wired between `push-and-pr` and `status-in-review`, with `status-in-review` and `report` depending on it.
- `code_review` config block present with the four keys.
- Reviewer prompt, command, and helper exist; the command references the helper, the clone-path prompt, the conformance diff exclusions, the Blocked board IDs, and the Pulls Reviews API.
- No dark-factory image rebuild required — all artifacts are clone-read.
- The PR opened by this work will itself be reviewed by the existing conformance gate (and, once merged, by this new gate on subsequent runs).
