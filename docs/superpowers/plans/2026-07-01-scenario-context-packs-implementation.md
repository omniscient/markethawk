# Plan: Scenario-Specific Context Packs for Dark Factory Phases

**Issue:** #665  
**Spec:** `docs/superpowers/specs/2026-07-01-scenario-context-packs-design.md`  
**Date:** 2026-07-01  
**Size:** M  

## Goal

Add `dark-factory/scripts/context_pack.py` — a content-assembly companion to `context_budget.py`
that produces `context-pack.md` (assembled prompt-ready Markdown) and `context-pack.json`
(manifest with per-section token counts, source hashes, and an `over_budget` flag) for six
Dark Factory scenarios. No other files are created or modified.

## Architecture

`context_pack.py` imports shared constants and helpers from `context_budget.py` to guarantee a
single source of truth for the section registry. It calls `architecture_slice.slice_architecture()`
for architecture content and `token_estimate` for counting. Both output artifacts are produced in
a single `assemble_pack()` pass — no separate telemetry and assembly passes.

```
dark-factory/scripts/
  context_budget.py          — existing: imports via cb.*  (unchanged)
  context_pack.py            — NEW: content assembler
  architecture_slice.py      — existing: called for arch content  (unchanged)
  token_estimate.py          — existing: estimate_tokens + hash_file  (unchanged)

dark-factory/tests/
  test_context_pack.py       — NEW: 5 test scenarios (refine, implement, code-review,
                                    over_budget, missing files)
```

## Tech Stack

- Python 3.10+ stdlib only
- pytest for tests (same `sys.path.insert` pattern as `test_context_budget.py`)

## File Structure

| File | Action | Purpose |
|------|--------|---------|
| `dark-factory/scripts/context_pack.py` | Create | Content assembler (imports from context_budget) |
| `dark-factory/tests/test_context_pack.py` | Create | 5-scenario unit tests |

---

## Task 1: Create `context_pack.py` (full implementation) + refine scenario tests

**Files:** `dark-factory/tests/test_context_pack.py`, `dark-factory/scripts/context_pack.py`  
**Time:** ~5 min

### Steps

**1a. Write failing refine tests**

Create `dark-factory/tests/test_context_pack.py`:

```python
"""Tests for context_pack.py — scenario content assembly."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import context_pack as cp


def _make_issue_json(tmp_path, body="issue body text", comments=None):
    data = {
        "body": body,
        "comments": comments or [{"body": "a comment"}],
    }
    p = tmp_path / "issue.json"
    p.write_text(json.dumps(data))
    return str(p)


def _run_pack(tmp_path, scenario, **kwargs):
    out_md = str(tmp_path / "context-pack.md")
    out_json = str(tmp_path / "context-pack.json")
    (tmp_path / "CLAUDE.md").write_text("# Claude Config\n\nproject instructions here.\n")
    cp.assemble_pack(
        scenario=scenario,
        issue_num=42,
        run_id="test-run-abc123",
        clone_dir=str(tmp_path),
        artifacts_dir=str(tmp_path),
        out_md=out_md,
        out_json=out_json,
        **kwargs,
    )
    md = Path(out_md).read_text()
    manifest = json.loads(Path(out_json).read_text())
    return md, manifest


# ── Task 1: refine scenario ───────────────────────────────────────────────────

def test_refine_produces_md_with_section_headers(tmp_path):
    md, manifest = _run_pack(
        tmp_path, "refine",
        issue_json=_make_issue_json(tmp_path),
    )
    assert "## claude_md" in md
    assert "## issue_context" in md
    assert "## comments" in md
    assert manifest["scenario"] == "refine"
    assert manifest["estimated_input_tokens"] > 0
    assert "claude_md" in manifest["included_sections"]


def test_refine_json_has_required_fields(tmp_path):
    _, manifest = _run_pack(
        tmp_path, "refine",
        issue_json=_make_issue_json(tmp_path),
    )
    for field in (
        "schema_version", "scenario", "run_id", "issue_number",
        "generated_at", "budget_tokens", "estimated_input_tokens",
        "utilization_pct", "over_budget", "sections",
        "included_sections", "dropped_sections", "source_file_hashes",
    ):
        assert field in manifest, f"Missing required field: {field}"
    assert manifest["schema_version"] == 1
    assert manifest["budget_tokens"] == 200_000
    assert manifest["over_budget"] is False
    assert manifest["run_id"] == "test-run-abc123"
    assert manifest["issue_number"] == 42
```

**1b. Verify tests fail**

```bash
cd /workspace/markethawk && python -m pytest dark-factory/tests/test_context_pack.py -v 2>&1 | head -15
```

Expected: `ModuleNotFoundError: No module named 'context_pack'`

**1c. Create `dark-factory/scripts/context_pack.py`**

```python
"""CLI: assemble Dark Factory context pack (context-pack.md + context-pack.json).

Usage:
  python3 context_pack.py --scenario refine --issue-num 42 --run-id abc123 \
    --artifacts-dir /tmp/artifacts/42 --clone-dir /workspace/markethawk \
    --issue-json /tmp/artifacts/42/issue.json \
    --memory-file /tmp/artifacts/42/memory-context.md \
    [--out-md /tmp/artifacts/42/context-pack.md] \
    [--out-json /tmp/artifacts/42/context-pack.json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
import token_estimate as te
import architecture_slice as aslice
import context_budget as cb

_SECTION_REGISTRY = cb._SECTION_REGISTRY
BUDGET_TOKENS = cb.BUDGET_TOKENS
DIFF_LINE_CAP = cb.DIFF_LINE_CAP
_read_text = cb._read_text
_SKILL_PROMPT_DIR = cb._SKILL_PROMPT_DIR
_SKILL_PROMPT_FILES = cb._SKILL_PROMPT_FILES


def _read_skill_prompts() -> str | None:
    parts = []
    for name in _SKILL_PROMPT_FILES:
        txt = _read_text(os.path.join(_SKILL_PROMPT_DIR, name))
        if txt:
            parts.append(txt)
    return "\n".join(parts) if parts else None


def _read_issue_context(issue_json: str | None) -> str | None:
    raw = _read_text(issue_json)
    if not raw:
        return None
    try:
        body = json.loads(raw).get("body") or ""
        return body.strip() or None
    except (json.JSONDecodeError, AttributeError):
        return None


def _read_comments(issue_json: str | None) -> str | None:
    raw = _read_text(issue_json)
    if not raw:
        return None
    try:
        comments = json.loads(raw).get("comments") or []
        combined = "\n".join(c.get("body", "") for c in comments if isinstance(c, dict))
        return combined.strip() or None
    except (json.JSONDecodeError, AttributeError):
        return None


def _read_pr_reviews(issue_json: str | None) -> str | None:
    raw = _read_text(issue_json)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        pr = data.get("pr_reviews") or {}
        inline = data.get("pr_inline_comments") or []
        text = json.dumps(pr) + "\n" + json.dumps(inline)
        return text.strip() or None
    except (json.JSONDecodeError, AttributeError):
        return None


def _read_diff(diff_file: str | None) -> tuple[str | None, dict]:
    """Return (content, extra_manifest_fields)."""
    text = _read_text(diff_file)
    if not text or not text.strip():
        return None, {}
    lines = text.splitlines()
    truncated = len(lines) > DIFF_LINE_CAP
    if truncated:
        effective = "\n".join(lines[:DIFF_LINE_CAP]) + "\n<!-- truncated at 1000 lines -->"
        extra: dict = {"status": "included_partial", "truncated_at_lines": DIFF_LINE_CAP}
    else:
        effective = text
        extra = {"status": "included"}
    return effective, extra


def assemble_pack(
    scenario: str,
    issue_num: int,
    run_id: str,
    clone_dir: str,
    artifacts_dir: str,
    out_md: str | None = None,
    out_json: str | None = None,
    spec_file: str | None = None,
    memory_file: str | None = None,
    issue_json: str | None = None,
    impl_file: str | None = None,
    diff_file: str | None = None,
    spec_component: str | None = None,
    changed_files: list[str] | None = None,
    labels: list[str] | None = None,
) -> None:
    if out_md is None:
        out_md = os.path.join(artifacts_dir, "context-pack.md")
    if out_json is None:
        out_json = os.path.join(artifacts_dir, "context-pack.json")

    active = _SECTION_REGISTRY.get(scenario, [])
    parts: list[str] = []
    sections: dict[str, dict] = {}
    source_hashes: dict[str, str] = {}

    for sec in active:
        content: str | None = None
        file_path: str | None = None
        extra_fields: dict = {}

        if sec == "claude_md":
            file_path = os.path.join(clone_dir, "CLAUDE.md")
            content = _read_text(file_path)

        elif sec == "architecture_md":
            arch_path = os.path.join(clone_dir, "ARCHITECTURE.md")
            result = aslice.slice_architecture(
                arch_path=arch_path,
                scenario=scenario,
                spec_component=spec_component,
                spec_file=spec_file,
                changed_files=changed_files,
                labels=labels,
                clone_dir=clone_dir,
            )
            content = result.text if result.text and result.text.strip() else None
            file_path = arch_path
            extra_fields = {
                "status": "included" if result.fallback else "included_slice",
                "component": result.component,
                "included_sections": result.included_sections,
                "omitted_sections": result.omitted_sections,
                "section_hashes": result.section_hashes,
                "fallback": result.fallback,
                "fallback_reason": result.fallback_reason,
            }

        elif sec == "skill_prompts":
            content = _read_skill_prompts()

        elif sec == "issue_context":
            content = _read_issue_context(issue_json)

        elif sec == "comments":
            content = _read_comments(issue_json)

        elif sec == "memory_context":
            file_path = memory_file
            content = _read_text(memory_file)

        elif sec == "pr_reviews":
            content = _read_pr_reviews(issue_json)

        elif sec == "spec":
            file_path = spec_file
            content = _read_text(spec_file)

        elif sec == "implementation_md":
            file_path = impl_file
            content = _read_text(impl_file)

        elif sec == "diff":
            content, extra_fields = _read_diff(diff_file)
            if content:
                tokens = te.estimate_tokens(content)
                entry: dict = {"tokens": tokens}
                entry.update(extra_fields)
                if diff_file:
                    h = te.hash_file(diff_file)
                    if h:
                        entry["file_hash"] = h
                        source_hashes["diff"] = h
                sections[sec] = entry
                parts.append(f"## {sec}\n\n{content}\n")
            else:
                sections[sec] = {"status": "dropped", "tokens": 0, "reason": "empty_or_missing"}
            continue

        if content and content.strip():
            tokens = te.estimate_tokens(content)
            entry = {"tokens": tokens}
            if "status" in extra_fields:
                entry["status"] = extra_fields.pop("status")
            else:
                entry["status"] = "included"
            entry.update(extra_fields)
            if file_path:
                h = te.hash_file(file_path)
                if h:
                    entry["file_hash"] = h
                    source_hashes[os.path.basename(file_path)] = h
            sections[sec] = entry
            parts.append(f"## {sec}\n\n{content}\n")
        else:
            reason = extra_fields.get("fallback_reason") or "empty_or_missing"
            sections[sec] = {"status": "dropped", "tokens": 0, "reason": reason}

    md_content = "\n".join(parts)
    total_tokens = sum(v.get("tokens", 0) for v in sections.values())
    utilization = round(total_tokens / BUDGET_TOKENS * 100, 1)
    over_budget = total_tokens > BUDGET_TOKENS

    if over_budget:
        print(
            f"WARNING: context pack {total_tokens} tokens exceeds budget {BUDGET_TOKENS}",
            file=sys.stderr,
        )

    included_sections = [
        k for k, v in sections.items()
        if v.get("status") in ("included", "included_slice", "included_partial")
    ]
    dropped_sections = [k for k, v in sections.items() if v.get("status") == "dropped"]

    manifest = {
        "schema_version": 1,
        "scenario": scenario,
        "run_id": run_id,
        "issue_number": issue_num,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "budget_tokens": BUDGET_TOKENS,
        "estimated_input_tokens": total_tokens,
        "utilization_pct": utilization,
        "over_budget": over_budget,
        "sections": sections,
        "included_sections": included_sections,
        "dropped_sections": dropped_sections,
        "source_file_hashes": source_hashes,
    }

    os.makedirs(os.path.dirname(os.path.abspath(out_md)), exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(out_json)), exist_ok=True)
    with open(out_md, "w", encoding="utf-8") as f:
        f.write(md_content)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Assemble Dark Factory context pack.")
    parser.add_argument("--scenario", required=True, choices=list(_SECTION_REGISTRY.keys()))
    parser.add_argument("--issue-num", required=True, type=int)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--artifacts-dir", required=True)
    parser.add_argument("--clone-dir", required=True)
    parser.add_argument("--spec-file")
    parser.add_argument("--memory-file")
    parser.add_argument("--issue-json")
    parser.add_argument("--impl-file")
    parser.add_argument("--diff-file")
    parser.add_argument("--spec-component")
    parser.add_argument("--changed-files", nargs="*", default=None)
    parser.add_argument("--labels", nargs="*", default=None)
    parser.add_argument("--out-md")
    parser.add_argument("--out-json")
    args = parser.parse_args()

    assemble_pack(
        scenario=args.scenario,
        issue_num=args.issue_num,
        run_id=args.run_id,
        clone_dir=args.clone_dir,
        artifacts_dir=args.artifacts_dir,
        spec_file=args.spec_file,
        memory_file=args.memory_file,
        issue_json=args.issue_json,
        impl_file=args.impl_file,
        diff_file=args.diff_file,
        spec_component=args.spec_component,
        changed_files=args.changed_files,
        labels=args.labels,
        out_md=args.out_md,
        out_json=args.out_json,
    )
    print(f"context-pack.md and context-pack.json written to {args.artifacts_dir}", file=sys.stderr)


if __name__ == "__main__":
    main()
```

**1d. Verify refine tests pass**

```bash
cd /workspace/markethawk && python -m pytest dark-factory/tests/test_context_pack.py::test_refine_produces_md_with_section_headers dark-factory/tests/test_context_pack.py::test_refine_json_has_required_fields -v
```

Expected:

```
PASSED dark-factory/tests/test_context_pack.py::test_refine_produces_md_with_section_headers
PASSED dark-factory/tests/test_context_pack.py::test_refine_json_has_required_fields
```

**1e. Commit**

```bash
cd /workspace/markethawk && git add dark-factory/scripts/context_pack.py dark-factory/tests/test_context_pack.py && git commit -m "feat: add context_pack.py scaffold + refine scenario (#665)"
```

---

## Task 2: `implement` scenario — spec section included/dropped

**Files:** `dark-factory/tests/test_context_pack.py`  
**Time:** ~3 min

The `implement` scenario in `_SECTION_REGISTRY` includes `spec`. Task 1's implementation already
handles the `spec` section. This task adds the tests that confirm that behaviour.

### Steps

**2a. Add failing tests**

Append to `dark-factory/tests/test_context_pack.py`:

```python
# ── Task 2: implement scenario ────────────────────────────────────────────────

def test_implement_spec_included_when_spec_file_supplied(tmp_path):
    spec = tmp_path / "spec.md"
    spec.write_text("# Spec\n\n" + "word " * 100)
    md, manifest = _run_pack(
        tmp_path, "implement",
        issue_json=_make_issue_json(tmp_path),
        spec_file=str(spec),
    )
    assert "## spec" in md
    assert "spec" in manifest["included_sections"]
    assert manifest["sections"]["spec"]["status"] == "included"
    assert manifest["sections"]["spec"]["tokens"] > 0


def test_implement_spec_dropped_when_spec_file_absent(tmp_path):
    md, manifest = _run_pack(
        tmp_path, "implement",
        issue_json=_make_issue_json(tmp_path),
    )
    assert "## spec" not in md
    assert "spec" in manifest["dropped_sections"]
    assert manifest["sections"]["spec"]["status"] == "dropped"
    assert manifest["sections"]["spec"]["tokens"] == 0
```

**2b. Verify tests pass**

```bash
cd /workspace/markethawk && python -m pytest dark-factory/tests/test_context_pack.py::test_implement_spec_included_when_spec_file_supplied dark-factory/tests/test_context_pack.py::test_implement_spec_dropped_when_spec_file_absent -v
```

Expected:

```
PASSED dark-factory/tests/test_context_pack.py::test_implement_spec_included_when_spec_file_supplied
PASSED dark-factory/tests/test_context_pack.py::test_implement_spec_dropped_when_spec_file_absent
```

**2c. Commit**

```bash
cd /workspace/markethawk && git add dark-factory/tests/test_context_pack.py && git commit -m "test: implement scenario — spec section included/dropped (#665)"
```

---

## Task 3: `code-review` scenario — diff section with truncation

**Files:** `dark-factory/tests/test_context_pack.py`  
**Time:** ~3 min

The `code-review` scenario in `_SECTION_REGISTRY` includes `diff`. Task 1's `_read_diff()`
truncates at `DIFF_LINE_CAP = 1000` lines and appends a `<!-- truncated at 1000 lines -->`
comment. This task verifies both the truncated and non-truncated cases.

### Steps

**3a. Add failing tests**

Append to `dark-factory/tests/test_context_pack.py`:

```python
# ── Task 3: code-review scenario + diff truncation ────────────────────────────

def test_code_review_diff_short_included_as_is(tmp_path):
    diff_file = tmp_path / "review.diff"
    diff_file.write_text("\n".join(f"+line {i}" for i in range(10)))
    md, manifest = _run_pack(
        tmp_path, "code-review",
        issue_json=_make_issue_json(tmp_path),
        diff_file=str(diff_file),
    )
    assert "## diff" in md
    assert "diff" in manifest["included_sections"]
    assert manifest["sections"]["diff"]["status"] == "included"
    assert "<!-- truncated" not in md


def test_code_review_diff_truncated_at_1000_lines(tmp_path):
    diff_file = tmp_path / "review.diff"
    diff_file.write_text("\n".join(f"+line {i}" for i in range(1500)))
    md, manifest = _run_pack(
        tmp_path, "code-review",
        issue_json=_make_issue_json(tmp_path),
        diff_file=str(diff_file),
    )
    assert "## diff" in md
    assert "diff" in manifest["included_sections"]
    assert manifest["sections"]["diff"]["status"] == "included_partial"
    assert manifest["sections"]["diff"]["truncated_at_lines"] == 1000
    assert "<!-- truncated at 1000 lines -->" in md
    lines_in_diff = md.split("## diff\n\n")[1].splitlines()
    non_comment_lines = [l for l in lines_in_diff if not l.startswith("<!--")]
    assert len(non_comment_lines) == 1000
```

**3b. Verify tests pass**

```bash
cd /workspace/markethawk && python -m pytest dark-factory/tests/test_context_pack.py::test_code_review_diff_short_included_as_is dark-factory/tests/test_context_pack.py::test_code_review_diff_truncated_at_1000_lines -v
```

Expected:

```
PASSED dark-factory/tests/test_context_pack.py::test_code_review_diff_short_included_as_is
PASSED dark-factory/tests/test_context_pack.py::test_code_review_diff_truncated_at_1000_lines
```

**3c. Commit**

```bash
cd /workspace/markethawk && git add dark-factory/tests/test_context_pack.py && git commit -m "test: code-review scenario + diff truncation (#665)"
```

---

## Task 4: `over_budget` flag + graceful missing-file drop

**Files:** `dark-factory/tests/test_context_pack.py`  
**Time:** ~3 min

`BUDGET_TOKENS = 200_000`. When total estimated tokens exceed the budget, `assemble_pack()` sets
`over_budget: true` in the JSON and emits a WARNING to stderr. Sections whose source files
cannot be read are silently dropped with `status: dropped, reason: empty_or_missing`.

### Steps

**4a. Add failing tests**

Append to `dark-factory/tests/test_context_pack.py`:

```python
# ── Task 4: over_budget flag + missing files ──────────────────────────────────

def test_over_budget_flag_set_and_stderr_emitted(tmp_path, capsys):
    # Force over-budget by patching BUDGET_TOKENS to 1
    original = cp.BUDGET_TOKENS
    cp.BUDGET_TOKENS = 1
    try:
        _, manifest = _run_pack(
            tmp_path, "refine",
            issue_json=_make_issue_json(tmp_path),
        )
    finally:
        cp.BUDGET_TOKENS = original

    assert manifest["over_budget"] is True
    captured = capsys.readouterr()
    assert "WARNING" in captured.err
    assert "exceeds budget" in captured.err


def test_missing_source_files_graceful_drop(tmp_path):
    # Run implement scenario with no issue_json, spec_file, or memory_file
    md, manifest = _run_pack(tmp_path, "implement")
    # Pack still produced (no crash)
    assert Path(tmp_path / "context-pack.md").exists()
    # Dropped sections have correct shape
    for sec in manifest["dropped_sections"]:
        assert manifest["sections"][sec]["status"] == "dropped"
        assert manifest["sections"][sec]["tokens"] == 0
        assert "reason" in manifest["sections"][sec]
    # claude_md was present (written by _run_pack helper) so it must be included
    assert "claude_md" in manifest["included_sections"]
```

**4b. Verify tests pass**

```bash
cd /workspace/markethawk && python -m pytest dark-factory/tests/test_context_pack.py::test_over_budget_flag_set_and_stderr_emitted dark-factory/tests/test_context_pack.py::test_missing_source_files_graceful_drop -v
```

Expected:

```
PASSED dark-factory/tests/test_context_pack.py::test_over_budget_flag_set_and_stderr_emitted
PASSED dark-factory/tests/test_context_pack.py::test_missing_source_files_graceful_drop
```

**4c. Run full test suite to confirm no regressions**

```bash
cd /workspace/markethawk && python -m pytest dark-factory/tests/test_context_pack.py -v
```

Expected: all 9 tests pass.

**4d. Commit**

```bash
cd /workspace/markethawk && git add dark-factory/tests/test_context_pack.py && git commit -m "test: over_budget flag + graceful missing-file drop (#665)"
```
