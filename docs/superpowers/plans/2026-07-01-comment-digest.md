# Comment Digest for Continue Runs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce token usage for `Continue issue #N` by extracting only human-authored feedback that appears after the latest factory-boundary comment from `issue.json`, replacing the current unfiltered `comments` + `pr_reviews` sections in the `continue` context scenario with a new deterministic `comment_digest` section.

**Architecture:** A new pure-Python script `comment_digest.py` does body-footer string matching (reusing the same `bot_re` pattern as `scheduler.sh`) to find the factory boundary, then extracts human issue comments, PR review bodies, and inline comments after the boundary — deterministically, no LLM. A new `digest-comments` bash DAG node runs this script for `continue` intent. Both `context_budget.py` and `context_pack.py` add a `comment_digest` section key to their `_SECTION_REGISTRY["continue"]` entry (replacing `comments` and `pr_reviews`). The `summarize-feedback` Haiku node is updated to consume `$digest-comments.output` (the digest content) instead of the raw `$fetch-issue.output`.

**Critical DAG note:** `digest-comments` is `when: continue` only. `budget-implement` and `implement` run for `new || continue`. Adding a `when`-gated upstream to their `depends_on` under the default `all_success` rule would skip them for `new` runs. Both nodes must be given `trigger_rule: none_failed_min_one_success`. This also requires adding them to `REQUIRED_OR_JOIN_NODES` in `check_workflow_dag.py` and updating `test_workflow_or_join.py`'s baseline fixture — the DAG linter's sync tripwire enforces this.

**Tech Stack:** Python 3 stdlib (no LLM, no external dependencies), pytest for tests, Archon YAML DAG.

**Spec:** `docs/superpowers/specs/2026-07-01-comment-digest-design.md`

**Reference precedent (read before starting):**
- `dark-factory/scripts/context_budget.py` — `_SECTION_REGISTRY`, `_probe_memory_context` pattern to mirror for `_probe_comment_digest`.
- `dark-factory/scripts/context_pack.py` — `assemble_pack()` + `_read_comments()` / `memory_context` handler patterns.
- `dark-factory/scheduler.sh:443` — canonical `bot_re` alternation to replicate exactly.
- `.archon/workflows/archon-dark-factory.yaml` — `summarize-feedback` (line 129), `budget-implement` (line 426), `implement` (line 455) nodes to update.
- `dark-factory/scripts/check_workflow_dag.py` — `REQUIRED_OR_JOIN_NODES` frozenset; the sync tripwire at lines 81–91.
- `dark-factory/tests/test_workflow_or_join.py` — `_KNOWN_OR_JOINS` baseline fixture used by multiple tests.
- `dark-factory/tests/test_context_budget.py` — `test_continue_scenario_includes_pr_reviews` to replace.
- `dark-factory/tests/test_context_pack.py` — `test_refine_md_has_section_headers` pattern to follow.

---

## File Structure

| File | Responsibility |
|---|---|
| `dark-factory/scripts/comment_digest.py` | **NEW** Pure-stdlib: read `issue.json`, find factory boundary, extract human feedback, emit `comment-digest.md`. |
| `dark-factory/tests/test_comment_digest.py` | **NEW** pytest unit tests (4 cases per spec: no-feedback, issue-comment, PR-review, inline-comment). |
| `dark-factory/scripts/context_budget.py` | **MODIFY** `_SECTION_REGISTRY["continue"]` removes `comments`/`pr_reviews`, adds `comment_digest`; new `_probe_comment_digest()`; `--comment-digest-file` CLI arg. |
| `dark-factory/scripts/context_pack.py` | **MODIFY** new `_read_comment_digest()` handler in `assemble_pack()`; `--comment-digest-file` CLI arg. |
| `.archon/workflows/archon-dark-factory.yaml` | **MODIFY** add `digest-comments` node; update `summarize-feedback` deps + prompt; update `budget-implement`/`implement` with `trigger_rule` + new dep. |
| `dark-factory/scripts/check_workflow_dag.py` | **MODIFY** add `budget-implement` and `implement` to `REQUIRED_OR_JOIN_NODES`. |
| `dark-factory/tests/test_workflow_or_join.py` | **MODIFY** update `_KNOWN_OR_JOINS` baseline fixture to include the two new OR-join nodes. |
| `dark-factory/tests/test_context_budget.py` | **MODIFY** replace `test_continue_scenario_includes_pr_reviews`; add `comment_digest` assertions. |
| `dark-factory/tests/test_context_pack.py` | **MODIFY** add `continue` scenario `comment_digest` assertions. |

---

## Task 1: `comment_digest.py` — TDD

**Files:**
- Create: `dark-factory/tests/test_comment_digest.py`
- Create: `dark-factory/scripts/comment_digest.py`

- [ ] **Step 1.1: Write failing tests**

Create `dark-factory/tests/test_comment_digest.py`:

```python
"""Tests for comment_digest.py — deterministic comment digest builder."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import comment_digest as cd


BOT_BODY = "Posted by MarketHawk Dark Factory\nRun complete."
HUMAN_BODY = "Please fix the null pointer bug."

FACTORY_TS = "2026-06-01T10:00:00Z"
HUMAN_TS = "2026-06-01T12:00:00Z"


def make_comment(body, ts):
    return {"body": body, "createdAt": ts}


# ── Case 1: no-feedback (all comments are factory-authored) ───────────────────

def test_no_feedback_all_factory():
    data = {
        "comments": [make_comment(BOT_BODY, FACTORY_TS)],
        "pr_reviews": {},
        "pr_inline_comments": [],
    }
    result = cd.build_digest(data)
    assert "<!-- no-feedback: true -->" in result
    assert "No human feedback found" in result
    assert HUMAN_BODY not in result


def test_no_feedback_human_before_boundary():
    """Human comment that precedes the last factory marker is excluded."""
    data = {
        "comments": [
            make_comment(HUMAN_BODY, "2026-05-01T09:00:00Z"),
            make_comment(BOT_BODY, FACTORY_TS),
        ],
        "pr_reviews": {},
        "pr_inline_comments": [],
    }
    result = cd.build_digest(data)
    assert "<!-- no-feedback: true -->" in result
    assert HUMAN_BODY not in result


# ── Case 2: issue-comment feedback ────────────────────────────────────────────

def test_issue_comment_after_boundary():
    data = {
        "comments": [
            make_comment(BOT_BODY, FACTORY_TS),
            make_comment(HUMAN_BODY, HUMAN_TS),
        ],
        "pr_reviews": {},
        "pr_inline_comments": [],
    }
    result = cd.build_digest(data)
    assert "<!-- no-feedback" not in result
    assert HUMAN_BODY in result
    assert "### Issue comments" in result


def test_bot_comment_after_boundary_excluded():
    """A second bot comment after the boundary must not appear as human feedback."""
    second_bot = "Updated by MarketHawk Dark Factory\nNew run."
    data = {
        "comments": [
            make_comment(BOT_BODY, FACTORY_TS),
            make_comment(second_bot, HUMAN_TS),
        ],
        "pr_reviews": {},
        "pr_inline_comments": [],
    }
    result = cd.build_digest(data)
    assert "<!-- no-feedback: true -->" in result


# ── Case 3: PR-review feedback ────────────────────────────────────────────────

def test_pr_review_body_after_boundary():
    pr_review_body = "LGTM but please update the README."
    data = {
        "comments": [make_comment(BOT_BODY, FACTORY_TS)],
        "pr_reviews": {
            "reviews": [{"body": pr_review_body, "submittedAt": HUMAN_TS}],
            "comments": [],
        },
        "pr_inline_comments": [],
    }
    result = cd.build_digest(data)
    assert pr_review_body in result
    assert "### PR review comments" in result


def test_pr_review_before_boundary_excluded():
    pr_review_body = "Old review before marker."
    data = {
        "comments": [make_comment(BOT_BODY, FACTORY_TS)],
        "pr_reviews": {
            "reviews": [{"body": pr_review_body, "submittedAt": "2026-05-01T08:00:00Z"}],
            "comments": [],
        },
        "pr_inline_comments": [],
    }
    result = cd.build_digest(data)
    assert pr_review_body not in result


# ── Case 4: inline-comment feedback ───────────────────────────────────────────

def test_inline_comments_grouped_by_path():
    data = {
        "comments": [make_comment(BOT_BODY, FACTORY_TS)],
        "pr_reviews": {},
        "pr_inline_comments": [
            {"path": "backend/app/models/user.py", "line": 42, "body": "Typo here.", "created_at": HUMAN_TS},
            {"path": "backend/app/models/user.py", "line": 77, "body": "Use f-string.", "created_at": HUMAN_TS},
            {"path": "frontend/src/App.tsx", "line": 5, "body": "Import order.", "created_at": HUMAN_TS},
        ],
    }
    result = cd.build_digest(data)
    assert "#### backend/app/models/user.py" in result
    assert "Line 42: Typo here." in result
    assert "Line 77: Use f-string." in result
    assert "#### frontend/src/App.tsx" in result
    assert "Line 5: Import order." in result
    assert "### Inline review comments by file" in result


def test_inline_before_boundary_excluded():
    data = {
        "comments": [make_comment(BOT_BODY, FACTORY_TS)],
        "pr_reviews": {},
        "pr_inline_comments": [
            {"path": "backend/app/routers/scanner.py", "line": 10,
             "body": "Old inline.", "created_at": "2026-05-01T08:00:00Z"},
        ],
    }
    result = cd.build_digest(data)
    assert "Old inline." not in result


# ── Edge: no factory marker at all ────────────────────────────────────────────

def test_no_boundary_includes_all_comments():
    data = {
        "comments": [make_comment(HUMAN_BODY, HUMAN_TS)],
        "pr_reviews": {},
        "pr_inline_comments": [],
    }
    result = cd.build_digest(data)
    assert "<!-- no-boundary: true" in result
    assert HUMAN_BODY in result


# ── Output format: HTML comment header ────────────────────────────────────────

def test_output_starts_with_comment_header():
    data = {
        "comments": [
            make_comment(BOT_BODY, FACTORY_TS),
            make_comment(HUMAN_BODY, HUMAN_TS),
        ],
        "pr_reviews": {},
        "pr_inline_comments": [],
    }
    result = cd.build_digest(data)
    assert result.startswith("<!-- comment-digest:")


# ── CLI: --issue-json / --out round-trip ─────────────────────────────────────

def test_cli_writes_file(tmp_path):
    import json
    issue_json = tmp_path / "issue.json"
    data = {
        "comments": [
            make_comment(BOT_BODY, FACTORY_TS),
            make_comment(HUMAN_BODY, HUMAN_TS),
        ],
        "pr_reviews": {},
        "pr_inline_comments": [],
    }
    issue_json.write_text(json.dumps(data))
    out = tmp_path / "comment-digest.md"

    import subprocess, sys as _sys
    script = Path(__file__).resolve().parents[1] / "scripts" / "comment_digest.py"
    result = subprocess.run(
        [_sys.executable, str(script), "--issue-json", str(issue_json), "--out", str(out)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert out.exists()
    content = out.read_text()
    assert HUMAN_BODY in content
```

- [ ] **Step 1.2: Verify tests fail**
```bash
cd /workspace/markethawk
python -m pytest dark-factory/tests/test_comment_digest.py -x 2>&1 | head -20
# Expected: ModuleNotFoundError: No module named 'comment_digest'
```

- [ ] **Step 1.3: Implement `comment_digest.py`**

Create `dark-factory/scripts/comment_digest.py`:

```python
"""Deterministic comment digest: filter issue.json to human feedback after last factory marker.

Reads issue.json (produced by fetch-issue DAG node) and emits comment-digest.md containing
only human-authored comments/reviews that appear after the latest factory-boundary comment.
No LLM calls — deterministic filter only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

# Mirrors scheduler.sh:443 bot_re exactly — match against footer strings, not author login.
# All factory comments are posted via the same GitHub PAT as humans, so author login is unreliable.
BOT_MARKERS = [
    "Posted by MarketHawk Refinement Pipeline",
    "Posted by MarketHawk Backlog Scheduler",
    "Posted by MarketHawk Dark Factory",
    "Updated by MarketHawk Dark Factory",
    "dark-factory-cost-report",
    "Posted by MarketHawk Epic Autopilot",
]

_BOT_RE = re.compile("|".join(re.escape(m) for m in BOT_MARKERS))


def _is_bot(body: str) -> bool:
    return bool(_BOT_RE.search(body or ""))


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def build_digest(issue_data: dict) -> str:
    """Build the digest string from the parsed issue.json dict. No I/O."""
    comments = issue_data.get("comments") or []
    pr_reviews = issue_data.get("pr_reviews") or {}
    pr_inline = issue_data.get("pr_inline_comments") or []

    # Find the latest factory boundary (last bot comment in the list)
    boundary_idx = -1
    boundary_ts: datetime | None = None
    boundary_body = ""
    for i, c in enumerate(comments):
        if isinstance(c, dict) and _is_bot(c.get("body", "")):
            boundary_idx = i
            boundary_body = c.get("body", "")
            boundary_ts = _parse_ts(c.get("createdAt") or c.get("created_at"))

    cutoff_str = boundary_ts.isoformat() if boundary_ts else "unknown"
    marker_preview = boundary_body[:80].replace("\n", " ") if boundary_body else "none"

    # No factory marker found — include everything (first run)
    if boundary_idx == -1:
        lines = [
            "<!-- comment-digest: cutoff=none marker=none -->",
            "<!-- no-boundary: true — no prior factory comments found; including all comments verbatim -->",
            "",
            "## Marker",
            "",
            "No factory boundary found (first run or no prior factory comments).",
            "",
            "## Human feedback since last factory run",
            "",
            "### Issue comments",
            "",
        ]
        for c in comments:
            if isinstance(c, dict):
                ts = c.get("createdAt") or c.get("created_at") or "unknown"
                lines.append(f"- [{ts}] {c.get('body', '')}")
        if not any(line.startswith("- [") for line in lines):
            lines.append("_(none)_")
        return "\n".join(lines)

    # Collect human issue comments after the boundary
    human_comments = [
        c for i, c in enumerate(comments)
        if i > boundary_idx and isinstance(c, dict) and not _is_bot(c.get("body", ""))
    ]

    # Collect human PR review bodies after the boundary
    review_list: list[dict] = []
    reviews_source: list = []
    if isinstance(pr_reviews, dict):
        reviews_source = pr_reviews.get("reviews") or []
    elif isinstance(pr_reviews, list):
        reviews_source = pr_reviews
    for r in reviews_source:
        if not isinstance(r, dict):
            continue
        if _is_bot(r.get("body", "")):
            continue
        r_ts = _parse_ts(r.get("submittedAt") or r.get("created_at"))
        if boundary_ts is not None and r_ts is not None and r_ts <= boundary_ts:
            continue
        review_list.append(r)

    # Collect inline comments after boundary, grouped by path
    inline_by_path: dict[str, list[dict]] = {}
    for ic in pr_inline:
        if not isinstance(ic, dict):
            continue
        ic_ts = _parse_ts(ic.get("created_at"))
        if boundary_ts is not None and ic_ts is not None and ic_ts <= boundary_ts:
            continue
        path = ic.get("path") or "unknown"
        inline_by_path.setdefault(path, []).append(ic)

    # No human feedback found after boundary
    if not human_comments and not review_list and not inline_by_path:
        return (
            f'<!-- comment-digest: cutoff={cutoff_str} marker="{marker_preview}" -->\n'
            "<!-- no-feedback: true -->\n"
            "No human feedback found after last factory marker."
        )

    lines = [
        f'<!-- comment-digest: cutoff={cutoff_str} marker="{marker_preview}" -->',
        "## Marker",
        "",
        f'Latest factory comment at {cutoff_str}: "{marker_preview}…"',
        "",
        "## Human feedback since last factory run",
        "",
        "### Issue comments",
        "",
    ]
    if human_comments:
        for c in human_comments:
            ts = c.get("createdAt") or c.get("created_at") or "unknown"
            lines.append(f"- [{ts}] {c.get('body', '')}")
    else:
        lines.append("_(none)_")

    lines += ["", "### PR review comments", ""]
    if review_list:
        for r in review_list:
            ts = r.get("submittedAt") or r.get("created_at") or "unknown"
            lines.append(f"- [{ts}] {r.get('body', '')}")
    else:
        lines.append("_(none)_")

    lines += ["", "### Inline review comments by file", ""]
    if inline_by_path:
        for path in sorted(inline_by_path):
            lines.append(f"#### {path}")
            for ic in inline_by_path[path]:
                line_num = ic.get("line") or "?"
                lines.append(f"- Line {line_num}: {ic.get('body', '')}")
            lines.append("")
    else:
        lines.append("_(none)_")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Produce comment-digest.md from issue.json (deterministic, no LLM)."
    )
    parser.add_argument("--issue-json", required=True,
                        help="Path to issue.json produced by fetch-issue DAG node")
    parser.add_argument("--out", required=True,
                        help="Output path for comment-digest.md")
    args = parser.parse_args()

    try:
        with open(args.issue_json, encoding="utf-8") as f:
            issue_data = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: {args.issue_json} not found", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"ERROR: cannot parse {args.issue_json}: {e}", file=sys.stderr)
        sys.exit(1)

    digest = build_digest(issue_data)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(digest)
        if not digest.endswith("\n"):
            f.write("\n")

    print(f"comment-digest.md written to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
```

- [ ] **Step 1.4: Verify tests pass**
```bash
python -m pytest dark-factory/tests/test_comment_digest.py -v 2>&1 | tail -20
# Expected: all tests pass
```

- [ ] **Step 1.5: Commit**
```bash
git add dark-factory/scripts/comment_digest.py dark-factory/tests/test_comment_digest.py
git commit -m "feat(dark-factory): add comment_digest.py — deterministic human-feedback filter (#668)"
```

---

## Task 2: Update `context_budget.py` (TDD)

**Files:**
- Modify: `dark-factory/scripts/context_budget.py`
- Modify: `dark-factory/tests/test_context_budget.py`

The `_SECTION_REGISTRY` lives in `context_budget.py` and is imported by `context_pack.py`, so updating it here changes both files' registry.

- [ ] **Step 2.1: Write failing tests**

Add to the end of `dark-factory/tests/test_context_budget.py`:

```python
# ── comment_digest section — continue scenario ────────────────────────────────

def make_digest_file(tmp_path, content="## Human feedback\n\n- [2026-06-01] Fix the bug."):
    p = tmp_path / "comment-digest.md"
    p.write_text(content)
    return str(p)


def test_continue_scenario_uses_comment_digest_not_comments(tmp_path):
    """After #668: continue registry has comment_digest, not comments or pr_reviews."""
    result = run_budget(tmp_path, "continue",
                        issue_json=make_issue_json(tmp_path, with_pr=True))
    assert "comment_digest" in result["sections"]
    assert "comments" not in result["sections"]
    assert "pr_reviews" not in result["sections"]


def test_continue_comment_digest_included_when_file_present(tmp_path):
    digest = make_digest_file(tmp_path)
    result = run_budget(tmp_path, "continue",
                        issue_json=make_issue_json(tmp_path, with_pr=True),
                        comment_digest_file=digest)
    sec = result["sections"]["comment_digest"]
    assert sec["status"] == "included"
    assert sec["tokens"] > 0
    assert "file_hash" in sec


def test_continue_comment_digest_dropped_when_absent(tmp_path):
    result = run_budget(tmp_path, "continue",
                        issue_json=make_issue_json(tmp_path, with_pr=True))
    sec = result["sections"]["comment_digest"]
    assert sec["status"] == "dropped"
    assert "reason" in sec


def test_implement_scenario_unchanged_no_comment_digest(tmp_path):
    """implement scenario must NOT have comment_digest (unchanged by this PR)."""
    result = run_budget(tmp_path, "implement",
                        issue_json=make_issue_json(tmp_path))
    assert "comment_digest" not in result["sections"]
    assert "comments" in result["sections"]
```

Also **remove** the now-outdated `test_continue_scenario_includes_pr_reviews` test — it asserts the old behavior that `pr_reviews` is in the `continue` sections, which is no longer true:

```python
# REMOVE this existing test (it validates the old behavior):
def test_continue_scenario_includes_pr_reviews(tmp_path):
    issue_json = make_issue_json(tmp_path, with_pr=True)
    result = run_budget(tmp_path, "continue", issue_json=issue_json)
    assert "pr_reviews" in result["sections"]
```

- [ ] **Step 2.2: Verify new tests fail**
```bash
python -m pytest dark-factory/tests/test_context_budget.py::test_continue_scenario_uses_comment_digest_not_comments -x 2>&1 | tail -10
# Expected: AssertionError — 'comment_digest' not in sections (registry not updated yet)
```

- [ ] **Step 2.3: Update `_SECTION_REGISTRY` and add `_probe_comment_digest`**

In `dark-factory/scripts/context_budget.py`, update the registry line:

```python
# Change from:
"continue":    ["claude_md", "architecture_md", "issue_context", "comments", "memory_context", "pr_reviews"],
# To:
"continue":    ["claude_md", "architecture_md", "issue_context", "memory_context", "comment_digest"],
```

Add the probe function after `_probe_pr_reviews`:

```python
def _probe_comment_digest(digest_file: str | None) -> dict:
    return _included(_read_text(digest_file), digest_file)
```

Update `build_budget` signature to accept `comment_digest_file`:

```python
def build_budget(
    scenario: str,
    issue_num: int,
    run_id: str,
    clone_dir: str,
    out: str,
    artifacts_dir: str | None = None,
    spec_file: str | None = None,
    plan_file: str | None = None,
    memory_file: str | None = None,
    issue_json: str | None = None,
    impl_file: str | None = None,
    diff_file: str | None = None,
    spec_component: str | None = None,
    changed_files: list[str] | None = None,
    labels: list[str] | None = None,
    comment_digest_file: str | None = None,
) -> None:
```

Add the `comment_digest` handler in `build_budget`'s `for sec in active:` loop, after the `pr_reviews` handler:

```python
        elif sec == "comment_digest":
            sections[sec] = _probe_comment_digest(comment_digest_file)
            if comment_digest_file and sections[sec]["status"] == "included":
                h = te.hash_file(comment_digest_file)
                if h:
                    source_hashes["comment-digest.md"] = h
```

Add `--comment-digest-file` to `main()` argument parser (after `--diff-file`):

```python
    parser.add_argument("--comment-digest-file",
                        help="Path to comment-digest.md (continue scenario only)")
```

Pass it in the `build_budget()` call in `main()`:

```python
    build_budget(
        scenario=args.scenario,
        issue_num=args.issue_num,
        run_id=args.run_id,
        clone_dir=args.clone_dir,
        out=args.out,
        artifacts_dir=args.artifacts_dir,
        spec_file=args.spec_file,
        plan_file=args.plan_file,
        memory_file=args.memory_file,
        issue_json=args.issue_json,
        impl_file=args.impl_file,
        diff_file=args.diff_file,
        spec_component=args.spec_component,
        changed_files=args.changed_files,
        labels=args.labels,
        comment_digest_file=args.comment_digest_file,
    )
```

- [ ] **Step 2.4: Verify all tests pass**
```bash
python -m pytest dark-factory/tests/test_context_budget.py -v 2>&1 | tail -30
# Expected: all tests pass
```

- [ ] **Step 2.5: Commit**
```bash
git add dark-factory/scripts/context_budget.py dark-factory/tests/test_context_budget.py
git commit -m "feat(dark-factory): add comment_digest section to context_budget continue registry (#668)"
```

---

## Task 3: Update `context_pack.py` (TDD)

**Files:**
- Modify: `dark-factory/scripts/context_pack.py`
- Modify: `dark-factory/tests/test_context_pack.py`

`context_pack.py` imports `_SECTION_REGISTRY` from `context_budget`, so the registry change in Task 2 already propagates here. This task adds the read handler and CLI arg.

- [ ] **Step 3.1: Write failing tests**

Add to the end of `dark-factory/tests/test_context_pack.py`:

```python
# ── comment_digest section — continue scenario ────────────────────────────────

def make_digest_file(tmp_path, content="## Human feedback\n\n- [2026-06-01] Fix the bug."):
    p = tmp_path / "comment-digest.md"
    p.write_text(content)
    return str(p)


def test_continue_emits_comment_digest_not_comments(tmp_path):
    """After #668: continue scenario MD has comment_digest header, not comments or pr_reviews."""
    digest = make_digest_file(tmp_path)
    manifest, md = run_pack(tmp_path, "continue",
                            issue_json=make_issue_json(tmp_path, with_pr=True),
                            comment_digest_file=digest)
    assert "## comment_digest" in md
    assert "## comments" not in md
    assert "## pr_reviews" not in md
    assert manifest["sections"]["comment_digest"]["status"] == "included"


def test_continue_comment_digest_content_included_in_md(tmp_path):
    unique_content = "UNIQUE_HUMAN_FEEDBACK_XYZ"
    digest = make_digest_file(tmp_path, content=f"## Human feedback\n\n{unique_content}")
    _, md = run_pack(tmp_path, "continue",
                     issue_json=make_issue_json(tmp_path, with_pr=True),
                     comment_digest_file=digest)
    assert unique_content in md


def test_continue_comment_digest_dropped_when_absent(tmp_path):
    manifest, md = run_pack(tmp_path, "continue",
                            issue_json=make_issue_json(tmp_path, with_pr=True))
    assert manifest["sections"]["comment_digest"]["status"] == "dropped"
    assert "## comment_digest" not in md


def test_implement_scenario_still_has_comments(tmp_path):
    """implement scenario is unchanged — must still use comments section."""
    _, md = run_pack(tmp_path, "implement",
                     issue_json=make_issue_json(tmp_path))
    assert "## comments" in md
    assert "## comment_digest" not in md
```

- [ ] **Step 3.2: Verify tests fail**
```bash
python -m pytest dark-factory/tests/test_context_pack.py::test_continue_emits_comment_digest_not_comments -x 2>&1 | tail -10
# Expected: TypeError or AssertionError — assemble_pack doesn't accept comment_digest_file yet
```

- [ ] **Step 3.3: Add `_read_comment_digest` and update `assemble_pack`**

Add after `_read_pr_reviews` in `dark-factory/scripts/context_pack.py`:

```python
def _read_comment_digest(digest_file: str | None) -> tuple[dict, str | None]:
    return _included(_read_text(digest_file), digest_file)
```

Update `assemble_pack` signature to accept `comment_digest_file`:

```python
def assemble_pack(
    scenario: str,
    issue_num: int,
    run_id: str,
    clone_dir: str,
    out_md: str,
    out_json: str,
    artifacts_dir: str | None = None,
    spec_file: str | None = None,
    memory_file: str | None = None,
    issue_json: str | None = None,
    impl_file: str | None = None,
    diff_file: str | None = None,
    spec_component: str | None = None,
    changed_files: list[str] | None = None,
    labels: list[str] | None = None,
    comment_digest_file: str | None = None,
) -> None:
```

Add the `comment_digest` handler in `assemble_pack`'s `for sec in active:` loop, after the `pr_reviews` elif:

```python
        elif sec == "comment_digest":
            status_entry, content = _read_comment_digest(comment_digest_file)
            if comment_digest_file and status_entry["status"] == "included":
                h = te.hash_file(comment_digest_file)
                if h:
                    source_hashes["comment-digest.md"] = h
```

Add `--comment-digest-file` to `main()` argument parser (after `--diff-file`):

```python
    parser.add_argument("--comment-digest-file",
                        help="Path to comment-digest.md (continue scenario only)")
```

Update the `assemble_pack()` call in `main()`:

```python
    assemble_pack(
        scenario=args.scenario,
        issue_num=args.issue_num,
        run_id=args.run_id,
        clone_dir=args.clone_dir,
        out_md=out_md,
        out_json=out_json,
        artifacts_dir=args.artifacts_dir,
        spec_file=args.spec_file,
        memory_file=args.memory_file,
        issue_json=args.issue_json,
        impl_file=args.impl_file,
        diff_file=args.diff_file,
        spec_component=args.spec_component,
        changed_files=args.changed_files,
        labels=args.labels,
        comment_digest_file=args.comment_digest_file,
    )
```

- [ ] **Step 3.4: Verify new and old tests pass**
```bash
python -m pytest dark-factory/tests/test_context_pack.py -v 2>&1 | tail -30
# Expected: all tests pass
```

- [ ] **Step 3.5: Commit**
```bash
git add dark-factory/scripts/context_pack.py dark-factory/tests/test_context_pack.py
git commit -m "feat(dark-factory): add comment_digest handler to context_pack continue scenario (#668)"
```

---

## Task 4: Update DAG linter and `check_workflow_dag.py` (TDD)

**Files:**
- Modify: `dark-factory/scripts/check_workflow_dag.py`
- Modify: `dark-factory/tests/test_workflow_or_join.py`

This task must happen **before** the YAML changes in Task 5, because Task 5's YAML edits will add `trigger_rule` to `budget-implement` and `implement`, which would immediately fail the sync tripwire unless `REQUIRED_OR_JOIN_NODES` is expanded first.

- [ ] **Step 4.1: Write failing test for the linter update**

Verify the current state: the linter passes with 4 OR-join nodes. After the YAML changes in Task 5, it will fail because two more `trigger_rule` nodes will exist without being in `REQUIRED_OR_JOIN_NODES`. Add a test to `test_workflow_or_join.py` that asserts `budget-implement` and `implement` will be valid OR-join members once the linter allowlist is updated:

```python
# Add after the existing _KNOWN_OR_JOINS definition in test_workflow_or_join.py:

def test_budget_implement_and_implement_are_in_allowlist():
    """After #668, budget-implement and implement become OR-join nodes and must be in REQUIRED_OR_JOIN_NODES."""
    from check_workflow_dag import REQUIRED_OR_JOIN_NODES
    assert "budget-implement" in REQUIRED_OR_JOIN_NODES, (
        "budget-implement must be in REQUIRED_OR_JOIN_NODES after #668 DAG wiring"
    )
    assert "implement" in REQUIRED_OR_JOIN_NODES, (
        "implement must be in REQUIRED_OR_JOIN_NODES after #668 DAG wiring"
    )
```

- [ ] **Step 4.2: Verify test fails**
```bash
python -m pytest dark-factory/tests/test_workflow_or_join.py::test_budget_implement_and_implement_are_in_allowlist -x 2>&1 | tail -10
# Expected: AssertionError — budget-implement not in REQUIRED_OR_JOIN_NODES
```

- [ ] **Step 4.3: Update `check_workflow_dag.py`**

In `dark-factory/scripts/check_workflow_dag.py`, update `REQUIRED_OR_JOIN_NODES`:

```python
REQUIRED_OR_JOIN_NODES: frozenset[str] = frozenset(
    {"validate", "de-conflict", "status-in-review", "report", "budget-implement", "implement"}
)
```

- [ ] **Step 4.4: Update `_KNOWN_OR_JOINS` baseline fixture in `test_workflow_or_join.py`**

The `_KNOWN_OR_JOINS` baseline is used by `test_sync_tripwire_catches_extra_trigger_rule_node` and other tests. With `REQUIRED_OR_JOIN_NODES` now having 6 members, the fixture must include all 6:

```python
# Update _KNOWN_OR_JOINS from 4 entries to 6:
_KNOWN_OR_JOINS = [
    {"id": "validate",         "trigger_rule": "none_failed_min_one_success", "depends_on": ["a", "b"]},
    {"id": "de-conflict",      "trigger_rule": "none_failed_min_one_success", "depends_on": ["c", "d"]},
    {"id": "status-in-review", "trigger_rule": "none_failed_min_one_success", "depends_on": ["e", "f"]},
    {"id": "report",           "trigger_rule": "none_failed_min_one_success", "depends_on": ["g", "h"]},
    {"id": "budget-implement", "trigger_rule": "none_failed_min_one_success", "depends_on": ["i", "j"]},
    {"id": "implement",        "trigger_rule": "none_failed_min_one_success", "depends_on": ["k", "l"]},
]
```

Also update `test_sync_tripwire_catches_extra_trigger_rule_node` if it hardcodes a 5-node list (it should now use 7 nodes — 6 known + 1 extra — to trigger the tripwire):

```python
def test_sync_tripwire_catches_extra_trigger_rule_node(tmp_path):
    """A seventh node with trigger_rule (beyond the 6 known OR-joins) must trigger the
    sync tripwire, prompting the developer to update REQUIRED_OR_JOIN_NODES."""
    nodes = _KNOWN_OR_JOINS + [
        # Seventh node with trigger_rule, not in the allowlist:
        {"id": "new-node", "trigger_rule": "none_failed_min_one_success"},
    ]
    path = _write_tmp(tmp_path, _make_workflow(nodes))
    errors = check(path)
    assert errors, "Expected sync-tripwire error but got none"
    assert any("trigger_rule" in e or "allowlist" in e or "update" in e.lower() or "new-node" in e for e in errors), (
        f"Expected a tripwire/allowlist error but got: {errors}"
    )
```

- [ ] **Step 4.5: Verify all linter tests pass (live YAML will fail until Task 5)**
```bash
python -m pytest dark-factory/tests/test_workflow_or_join.py -v -k "not test_current_workflow_passes" 2>&1 | tail -20
# Expected: all non-live-workflow tests pass
# test_current_workflow_passes will FAIL until Task 5 adds trigger_rule to the YAML — that is expected
```

- [ ] **Step 4.6: Commit**
```bash
git add dark-factory/scripts/check_workflow_dag.py dark-factory/tests/test_workflow_or_join.py
git commit -m "feat(dark-factory): expand OR-join allowlist to include budget-implement and implement (#668)"
```

---

## Task 5: Update `archon-dark-factory.yaml`

**Files:**
- Modify: `.archon/workflows/archon-dark-factory.yaml`

Four changes: (a) add `digest-comments` node, (b) update `summarize-feedback` deps + prompt, (c) update `budget-implement` with `trigger_rule` + new dep + fix stale comment, (d) update `implement` with `trigger_rule` + new dep.

- [ ] **Step 5.1: Add `digest-comments` node**

Insert immediately after `acknowledge-continue` (the `when: continue` acknowledgement node, around line 161) and before `close-announce`. The node `cat`s the digest to stdout so `$digest-comments.output` carries the file content:

```yaml
  - id: digest-comments
    bash: |
      ISSUE=$(jq -r '.resolved_number' "$ARTIFACTS_DIR/issue.json")
      _CLONE="${CLONE_DIR:-.}"
      python3 "$_CLONE/dark-factory/scripts/comment_digest.py" \
        --issue-json "$ARTIFACTS_DIR/issue.json" \
        --out "$ARTIFACTS_DIR/comment-digest.md"
      cat "$ARTIFACTS_DIR/comment-digest.md"
    depends_on: [fetch-issue]
    when: "$parse-intent.output.intent == 'continue'"
    timeout: 15000
```

- [ ] **Step 5.2: Update `summarize-feedback` node**

Change `summarize-feedback` to depend on `digest-comments` and read from its output (the file content piped via stdout):

```yaml
  - id: summarize-feedback
    prompt: |
      You are reviewing feedback on a code implementation.
      Below is a pre-filtered digest of human-authored feedback since the last factory run.
      Summarize the feedback in 2-3 sentences covering what changes the reviewer wants made.
      If there is no meaningful human feedback, respond with: {"summary": "No specific feedback found."}

      Comment digest:
      $digest-comments.output

      Output ONLY valid JSON, nothing else:
      {"summary": "<2-3 sentence summary>"}
    allowed_tools: []
    model: haiku
    depends_on: [digest-comments]
    when: "$parse-intent.output.intent == 'continue'"
    output_format:
      type: object
      properties:
        summary:
          type: string
      required: [summary]
```

- [ ] **Step 5.3: Update `budget-implement` node**

Three changes: add `digest-comments` to `depends_on`, add `trigger_rule: none_failed_min_one_success` (so `new`-intent runs are not blocked when `digest-comments` is skipped), pass `--comment-digest-file` conditionally, and remove the stale `pr_reviews` comment:

```yaml
  - id: budget-implement
    bash: |
      ISSUE=$(jq -r '.resolved_number' "$ARTIFACTS_DIR/issue.json")
      INTENT=$(jq -r '.intent' "$ARTIFACTS_DIR/issue.json")
      _CLONE="${CLONE_DIR:-.}"
      _RUN="${RUN_ID:-$(basename "${ARTIFACTS_DIR:-/tmp/budget}")}"
      # Assert INTENT is a known scenario before invoking context_budget.py so that
      # an unexpected value produces a visible error rather than a silent no-op.
      case "$INTENT" in
        new|continue) ;;
        *) echo "budget-implement: unexpected INTENT='$INTENT'; expected new or continue" >&2; exit 1 ;;
      esac
      # memory-context.md is written inside the command session by memory_retrieve.py (Phase 1
      # load). This applies to all of refine, plan, implement, continue — budget nodes always
      # run before the command. Reported as dropped/empty_or_missing; this is expected.
      _DIGEST_FILE=""
      if [ "$INTENT" = "continue" ]; then
        _DIGEST_FILE="$ARTIFACTS_DIR/comment-digest.md"
      fi
      python3 "$_CLONE/dark-factory/scripts/context_budget.py" \
        --scenario "$INTENT" \
        --issue-num "$ISSUE" \
        --run-id "$_RUN" \
        --artifacts-dir "$ARTIFACTS_DIR" \
        --clone-dir "$_CLONE" \
        --issue-json "$ARTIFACTS_DIR/issue.json" \
        --memory-file "$ARTIFACTS_DIR/memory-context.md" \
        ${_DIGEST_FILE:+--comment-digest-file "$_DIGEST_FILE"} \
        --out "$ARTIFACTS_DIR/context-budget.json" || true
    depends_on: [update-codeindex, fetch-issue, digest-comments]
    trigger_rule: none_failed_min_one_success
    when: "$parse-intent.output.intent == 'new' || $parse-intent.output.intent == 'continue'"
    timeout: 30000
```

- [ ] **Step 5.4: Update `implement` node**

Add `digest-comments` to `depends_on` and add `trigger_rule: none_failed_min_one_success`:

```yaml
  - id: implement
    command: dark-factory-implement
    depends_on: [budget-implement, update-codeindex, fetch-issue, digest-comments]
    trigger_rule: none_failed_min_one_success
    when: "$parse-intent.output.intent == 'new' || $parse-intent.output.intent == 'continue'"
    idle_timeout: 600000
```

- [ ] **Step 5.5: Verify YAML is valid**
```bash
python3 -c "import yaml; yaml.safe_load(open('.archon/workflows/archon-dark-factory.yaml'))" && echo "YAML valid"
# Expected: YAML valid
```

- [ ] **Step 5.6: Run the full workflow OR-join test suite including the live-YAML test**
```bash
python -m pytest dark-factory/tests/test_workflow_or_join.py dark-factory/tests/test_workflow_when.py -v 2>&1 | tail -30
# Expected: all tests pass — including test_current_workflow_passes (which now validates the updated YAML)
```

- [ ] **Step 5.7: Commit**
```bash
git add .archon/workflows/archon-dark-factory.yaml
git commit -m "feat(dark-factory): add digest-comments DAG node; wire summarize-feedback to digest (#668)"
```

---

## Task 6: Full test suite

- [ ] **Step 6.1: Run the complete dark-factory test suite**
```bash
python -m pytest dark-factory/tests/ -v --tb=short 2>&1 | tail -50
# Expected: all tests pass, no regressions
```

- [ ] **Step 6.2: Spot-check the DAG linter directly**
```bash
python3 dark-factory/scripts/check_workflow_dag.py .archon/workflows/archon-dark-factory.yaml
# Expected: "DAG trigger_rule check passed for 1 workflow file(s)."
```
