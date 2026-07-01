# Plan: Dark Factory Context Budget Telemetry

**Issue:** #664
**Parent Epic:** #663
**Spec:** `docs/superpowers/specs/2026-07-01-dark-factory-context-budget-telemetry-design.md`
**Date:** 2026-07-01
**Size:** S

## Goal

Emit a machine-readable `context-budget.json` artifact at the start of each Dark Factory phase (refine, plan, implement, continue, conformance, code-review) by adding two pure-stdlib Python scripts and five pre-phase bash nodes to the Archon workflow YAML. No prompt contents change; no edits to `entrypoint.sh`.

## Architecture

Two pure-stdlib scripts in `dark-factory/scripts/`:
- `token_estimate.py` — pure library module with estimation helpers (no CLI, no side effects), following the pattern of `code_review_payload.py`
- `context_budget.py` — CLI that probes on-disk context sources per scenario, estimates token counts, and writes `context-budget.json`

Five new `bash:` telemetry nodes in `.archon/workflows/archon-dark-factory.yaml`, each inserted immediately before the corresponding `command:` node and ending with `|| true` (non-fatal). Each `command:` node's `depends_on` is extended to include its budget node, following the `update-codeindex` → `implement` scaffolding pattern.

The artifact is written to `$ARTIFACTS_DIR/context-budget.json` alongside `run-record.json`, `issue.json`, and `memory-trace.json`. `entrypoint.sh` is not modified.

> **Memory note:** The existing `[AVOID]` entries in `.archon/memory/architecture.md` concern Redis for durable state and vector databases — neither applies here. The `[PATTERN]` about git diff two-dot form applies to OOS gate verification if needed, not to this implementation.

### Environment variable availability in bash nodes

`$CLONE_DIR` and `$RUN_ID` are **not exported** to Archon DAG bash nodes (documented in the de-conflict node comment at line ~418 of `archon-dark-factory.yaml`, citing failures #403/#391/#570/#394/#648). All five budget bash nodes use `_CLONE="${CLONE_DIR:-.}"` (CWD is the clone root in bash nodes) and `_RUN="${RUN_ID:-$(basename "${ARTIFACTS_DIR:-/tmp/budget}")}"`  (ARTIFACTS_DIR ends in `.../runs/<run-id>`). `$ARTIFACTS_DIR` IS exported and available.

### Pre-command artifact timing

Budget nodes run before the command node in the DAG, so some artifacts don't exist yet:

- **`memory-context.md`**: Written by Claude's Phase 1 load (inside the command session via `memory_retrieve.py`). This applies to **all three** relevant scenarios: `dark-factory-refine.md`, `dark-factory-plan.md`, and `dark-factory-implement.md` all run `memory_retrieve.py` at Phase 1 start — after the budget node has already finished. The `memory_context` section will report `"status": "dropped", "reason": "empty_or_missing"` for all refine, plan, new, and continue runs. This is a permanent pre-command limitation; the parent epic (#663) can address memory context sizing separately.

- **`review_diff.txt` (conformance / code-review)**: Not an artifact written before the command. `budget-conformance` and `budget-code-review` generate the diff inline via `git diff main...HEAD` (three-dot, matching what `dark-factory-conformance.md` and `dark-factory-code-review.md` actually pass to Claude) piped to a temp file, so the `diff` section measures what the command actually loads. Note: three-dot form is used here intentionally to match the commands — do NOT confuse with OOS detection which uses two-dot (per `.archon/memory/codebase-patterns.md`).

- **`implementation.md` (conformance)**: Written during the `implement` command session. By the time `budget-conformance` runs (it depends on `validate`, which runs after `implement`), `implementation.md` exists — this probe works correctly.

## Tech Stack

- **Python**: stdlib only (`hashlib`, `argparse`, `json`, `os`, `sys`, `datetime`) — no pip installs; matches existing `dark-factory/scripts/` pattern
- **Shell**: bash, `jq` (already in container)
- **YAML**: edit `.archon/workflows/archon-dark-factory.yaml` — 5 new `bash:` nodes, 5 `depends_on` extensions
- **Tests**: `pytest` in `dark-factory/tests/`

## File Structure

| File | Action | Purpose |
|------|--------|---------|
| `dark-factory/scripts/token_estimate.py` | Create | Pure-stdlib estimation helpers (`CHARS_PER_TOKEN`, `estimate_tokens`, `hash_file`, `hash_text`) |
| `dark-factory/scripts/context_budget.py` | Create | CLI — probes sections per scenario, emits `context-budget.json` with the spec schema |
| `dark-factory/tests/test_token_estimate.py` | Create | Unit tests for estimation helpers |
| `dark-factory/tests/test_context_budget.py` | Create | Unit tests for CLI (schema, section status, truncation at 1000 lines, scenario registry) |
| `.archon/workflows/archon-dark-factory.yaml` | Edit | 5 new `bash:` telemetry nodes (`budget-refine`, `budget-plan`, `budget-implement`, `budget-conformance`, `budget-code-review`); `refine`, `plan`, `implement`, `conformance`, `code-review` nodes each gain a `depends_on` entry on their budget node |

---

## Task 1: Create `token_estimate.py` — pure-stdlib estimation helpers

**Files:** `dark-factory/scripts/token_estimate.py`, `dark-factory/tests/test_token_estimate.py`
**Time:** ~5 min

### Steps

**1a. Write failing tests**

Create `dark-factory/tests/test_token_estimate.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import token_estimate as te


def test_chars_per_token_constant():
    assert te.CHARS_PER_TOKEN == 4.0


def test_estimate_tokens_empty():
    assert te.estimate_tokens("") == 0


def test_estimate_tokens_basic():
    # "hello" = 5 chars → int(5 / 4.0) = 1
    assert te.estimate_tokens("hello") == 1


def test_estimate_tokens_exact_multiple():
    assert te.estimate_tokens("a" * 400) == 100


def test_hash_file_missing_returns_none():
    assert te.hash_file("/nonexistent/path/file.txt") is None


def test_hash_file_returns_12_hex_chars(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("hello world")
    result = te.hash_file(str(f))
    assert result is not None
    assert len(result) == 12
    assert all(c in "0123456789abcdef" for c in result)


def test_hash_file_same_content_same_hash(tmp_path):
    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.txt"
    f1.write_text("identical content")
    f2.write_text("identical content")
    assert te.hash_file(str(f1)) == te.hash_file(str(f2))


def test_hash_text_returns_12_hex_chars():
    result = te.hash_text("hello")
    assert len(result) == 12
    assert all(c in "0123456789abcdef" for c in result)


def test_hash_text_deterministic():
    assert te.hash_text("hello") == te.hash_text("hello")
```

**1b. Run tests — expect failure**

```bash
python -m pytest dark-factory/tests/test_token_estimate.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'token_estimate'`

**1c. Create `dark-factory/scripts/token_estimate.py`**

```python
"""Pure-stdlib token estimation helpers for Dark Factory context budget telemetry."""
import hashlib

CHARS_PER_TOKEN = 4.0


def estimate_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN)


def hash_file(path: str) -> "str | None":
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:12]
    except (FileNotFoundError, OSError):
        return None


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
```

**1d. Run tests — expect pass**

```bash
python -m pytest dark-factory/tests/test_token_estimate.py -v
```

Expected:
```
PASSED test_chars_per_token_constant
PASSED test_estimate_tokens_empty
PASSED test_estimate_tokens_basic
PASSED test_estimate_tokens_exact_multiple
PASSED test_hash_file_missing_returns_none
PASSED test_hash_file_returns_12_hex_chars
PASSED test_hash_file_same_content_same_hash
PASSED test_hash_text_returns_12_hex_chars
PASSED test_hash_text_deterministic
9 passed in 0.XXs
```

**1e. Commit**

```bash
git add dark-factory/scripts/token_estimate.py dark-factory/tests/test_token_estimate.py
git commit -m "feat: add token_estimate.py — pure-stdlib estimation helpers (#664)"
```

---

## Task 2: Create `context_budget.py` — CLI entry point

**Files:** `dark-factory/scripts/context_budget.py`, `dark-factory/tests/test_context_budget.py`
**Time:** ~20 min

### Steps

**2a. Write failing tests**

Create `dark-factory/tests/test_context_budget.py`:

```python
"""Tests for context_budget.py CLI (build_budget function)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import context_budget as cb


# ── helpers ──────────────────────────────────────────────────────────────────

def make_issue_json(tmp_path, with_pr=False):
    data = {
        "resolved_number": 664,
        "intent": "continue" if with_pr else "new",
        "title": "Test issue",
        "body": "Issue body text for estimation",
        "comments": [{"body": "comment one"}, {"body": "comment two"}],
    }
    if with_pr:
        data["pr_reviews"] = {"reviews": [{"body": "looks good"}], "comments": []}
        data["pr_inline_comments"] = []
    p = tmp_path / "issue.json"
    p.write_text(json.dumps(data))
    return str(p)


def make_spec_file(tmp_path):
    p = tmp_path / "spec.md"
    p.write_text("# Spec\n\n" + "word " * 100)
    return str(p)


def make_impl_file(tmp_path):
    p = tmp_path / "implementation.md"
    p.write_text("## Changes\n\n" + "line " * 50)
    return str(p)


def make_diff_file(tmp_path, lines=10):
    p = tmp_path / "review_diff.txt"
    p.write_text("\n".join(f"+line {i}" for i in range(lines)))
    return str(p)


def run_budget(tmp_path, scenario, **kwargs):
    out_path = str(tmp_path / "context-budget.json")
    cb.build_budget(
        scenario=scenario,
        issue_num=664,
        run_id="test-run-abc123",
        artifacts_dir=str(tmp_path),
        clone_dir=str(tmp_path),
        out=out_path,
        **kwargs,
    )
    return json.loads(Path(out_path).read_text())


# ── schema tests ─────────────────────────────────────────────────────────────

def test_required_fields_present(tmp_path):
    result = run_budget(tmp_path, "refine", issue_json=make_issue_json(tmp_path))
    for field in (
        "schema_version", "scenario", "run_id", "issue_number",
        "generated_at", "budget_tokens", "estimated_input_tokens",
        "utilization_pct", "sections", "included_sections",
        "dropped_sections", "source_file_hashes",
    ):
        assert field in result, f"Missing required field: {field}"


def test_schema_version_is_1(tmp_path):
    result = run_budget(tmp_path, "refine", issue_json=make_issue_json(tmp_path))
    assert result["schema_version"] == 1


def test_budget_tokens_is_200000(tmp_path):
    result = run_budget(tmp_path, "refine", issue_json=make_issue_json(tmp_path))
    assert result["budget_tokens"] == 200_000


def test_utilization_pct_matches_tokens(tmp_path):
    result = run_budget(tmp_path, "refine", issue_json=make_issue_json(tmp_path))
    expected = round(result["estimated_input_tokens"] / 200_000 * 100, 1)
    assert result["utilization_pct"] == expected


def test_scenario_and_run_id_round_trip(tmp_path):
    result = run_budget(tmp_path, "plan", issue_json=make_issue_json(tmp_path))
    assert result["scenario"] == "plan"
    assert result["run_id"] == "test-run-abc123"
    assert result["issue_number"] == 664


# ── section status tests ──────────────────────────────────────────────────────

def test_plan_spec_present_is_included(tmp_path):
    spec = make_spec_file(tmp_path)
    result = run_budget(tmp_path, "plan",
                        issue_json=make_issue_json(tmp_path),
                        spec_file=spec)
    assert result["sections"]["spec"]["status"] == "included"
    assert result["sections"]["spec"]["tokens"] > 0
    assert "file_hash" in result["sections"]["spec"]
    assert len(result["sections"]["spec"]["file_hash"]) == 12


def test_plan_spec_missing_is_dropped(tmp_path):
    result = run_budget(tmp_path, "plan",
                        issue_json=make_issue_json(tmp_path))
    assert result["sections"]["spec"]["status"] == "dropped"
    assert result["sections"]["spec"]["tokens"] == 0
    assert "reason" in result["sections"]["spec"]


def test_conformance_diff_over_1000_lines_is_partial(tmp_path):
    diff = make_diff_file(tmp_path, lines=1500)
    spec = make_spec_file(tmp_path)
    impl = make_impl_file(tmp_path)
    result = run_budget(tmp_path, "conformance",
                        spec_file=spec, impl_file=impl, diff_file=diff)
    sec = result["sections"]["diff"]
    assert sec["status"] == "included_partial"
    assert sec["truncated_at_lines"] == 1000
    assert sec["tokens"] > 0


def test_conformance_diff_under_1000_lines_is_included(tmp_path):
    diff = make_diff_file(tmp_path, lines=50)
    spec = make_spec_file(tmp_path)
    impl = make_impl_file(tmp_path)
    result = run_budget(tmp_path, "conformance",
                        spec_file=spec, impl_file=impl, diff_file=diff)
    assert result["sections"]["diff"]["status"] == "included"


def test_included_dropped_lists_consistent(tmp_path):
    result = run_budget(tmp_path, "plan",
                        issue_json=make_issue_json(tmp_path))
    # spec is absent → dropped
    assert "spec" in result["dropped_sections"]
    assert "spec" not in result["included_sections"]
    # issue_context provided via issue_json → included
    assert "issue_context" in result["included_sections"]
    assert "issue_context" not in result["dropped_sections"]


def test_source_file_hashes_populated_when_file_exists(tmp_path):
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text("# CLAUDE.md content for test")
    result = run_budget(tmp_path, "refine",
                        issue_json=make_issue_json(tmp_path))
    assert "CLAUDE.md" in result["source_file_hashes"]
    assert len(result["source_file_hashes"]["CLAUDE.md"]) == 12


def test_conformance_excludes_inapplicable_sections(tmp_path):
    spec = make_spec_file(tmp_path)
    impl = make_impl_file(tmp_path)
    result = run_budget(tmp_path, "conformance",
                        spec_file=spec, impl_file=impl)
    # conformance does not load claude_md, architecture_md, issue_context, comments
    for sec in ("claude_md", "architecture_md", "issue_context", "comments", "memory_context"):
        assert sec not in result["sections"], f"Section {sec!r} should be absent for conformance"


def test_continue_scenario_includes_pr_reviews(tmp_path):
    issue_json = make_issue_json(tmp_path, with_pr=True)
    result = run_budget(tmp_path, "continue", issue_json=issue_json)
    assert "pr_reviews" in result["sections"]


def test_implement_scenario_excludes_pr_reviews(tmp_path):
    result = run_budget(tmp_path, "implement",
                        issue_json=make_issue_json(tmp_path))
    assert "pr_reviews" not in result["sections"]


def test_estimated_tokens_is_sum_of_section_tokens(tmp_path):
    result = run_budget(tmp_path, "plan",
                        issue_json=make_issue_json(tmp_path))
    total = sum(v.get("tokens", 0) for v in result["sections"].values())
    assert result["estimated_input_tokens"] == total


def test_memory_context_absent_is_dropped(tmp_path):
    # memory-context.md doesn't exist pre-command (written inside command session);
    # reports "empty_or_missing" matching spec vocabulary.
    result = run_budget(tmp_path, "refine",
                        issue_json=make_issue_json(tmp_path))
    sec = result["sections"].get("memory_context", {})
    assert sec["status"] == "dropped"
    assert sec.get("reason") == "empty_or_missing"
```

**2b. Run tests — expect failure**

```bash
python -m pytest dark-factory/tests/test_context_budget.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'context_budget'`

**2c. Create `dark-factory/scripts/context_budget.py`**

```python
"""CLI: probe Dark Factory context sources and emit context-budget.json.

Usage:
  python3 context_budget.py --scenario refine --issue-num 42 --run-id abc123 \
    --artifacts-dir /tmp/artifacts/42 --clone-dir /workspace/markethawk \
    --issue-json /tmp/artifacts/42/issue.json \
    --memory-file /tmp/artifacts/42/memory-context.md \
    --out /tmp/artifacts/42/context-budget.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
import token_estimate as te

BUDGET_TOKENS = 200_000
DIFF_LINE_CAP = 1000

# Sections active per scenario; order determines iteration order in JSON output.
_SECTION_REGISTRY: dict[str, list[str]] = {
    "refine":      ["claude_md", "architecture_md", "skill_prompts", "issue_context", "comments", "memory_context"],
    "plan":        ["claude_md", "skill_prompts", "issue_context", "comments", "memory_context", "spec"],
    "implement":   ["claude_md", "architecture_md", "issue_context", "comments", "memory_context"],
    "continue":    ["claude_md", "architecture_md", "issue_context", "comments", "memory_context", "pr_reviews"],
    "conformance": ["skill_prompts", "spec", "implementation_md", "diff"],
    "code-review": ["skill_prompts", "issue_context", "diff"],
}

_SKILL_PROMPT_DIR = "/opt/refinement-skills"
_SKILL_PROMPT_FILES = [
    "orchestrator-prompt.md",
    "product-owner-prompt.md",
    "architect-prompt.md",
    "conformance-reviewer-prompt.md",
    "code-review-reviewer-prompt.md",
]


def _read_text(path: str | None) -> str | None:
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except (FileNotFoundError, OSError):
        return None


def _included(text: str | None, file_path: str | None = None) -> dict:
    if not text or not text.strip():
        return {"status": "dropped", "tokens": 0, "reason": "empty_or_missing"}
    entry: dict = {"status": "included", "tokens": te.estimate_tokens(text)}
    if file_path:
        h = te.hash_file(file_path)
        if h:
            entry["file_hash"] = h
    return entry


def _dropped(reason: str) -> dict:
    return {"status": "dropped", "tokens": 0, "reason": reason}


def _probe_skill_prompts() -> dict:
    parts = []
    for name in _SKILL_PROMPT_FILES:
        txt = _read_text(os.path.join(_SKILL_PROMPT_DIR, name))
        if txt:
            parts.append(txt)
    if not parts:
        return _dropped("container_mounted_not_found")
    return {"status": "included", "tokens": te.estimate_tokens("\n".join(parts))}


def _probe_issue_context(issue_json: str | None) -> dict:
    raw = _read_text(issue_json)
    if not raw:
        return _dropped("empty_or_missing")
    try:
        body = json.loads(raw).get("body") or ""
        return _included(body) if body.strip() else _dropped("empty_body")
    except (json.JSONDecodeError, AttributeError):
        return _dropped("invalid_json")


def _probe_comments(issue_json: str | None) -> dict:
    raw = _read_text(issue_json)
    if not raw:
        return _dropped("empty_or_missing")
    try:
        comments = json.loads(raw).get("comments") or []
        combined = "\n".join(c.get("body", "") for c in comments if isinstance(c, dict))
        return _included(combined) if combined.strip() else _dropped("no_comments")
    except (json.JSONDecodeError, AttributeError):
        return _dropped("invalid_json")


def _probe_pr_reviews(issue_json: str | None) -> dict:
    raw = _read_text(issue_json)
    if not raw:
        return _dropped("empty_or_missing")
    try:
        data = json.loads(raw)
        pr = data.get("pr_reviews") or {}
        inline = data.get("pr_inline_comments") or []
        text = json.dumps(pr) + "\n" + json.dumps(inline)
        return _included(text) if text.strip() else _dropped("no_pr_reviews")
    except (json.JSONDecodeError, AttributeError):
        return _dropped("invalid_json")


def _probe_diff(diff_file: str | None) -> dict:
    text = _read_text(diff_file)
    if not text or not text.strip():
        return _dropped("empty_or_missing")
    lines = text.splitlines()
    truncated = len(lines) > DIFF_LINE_CAP
    effective = "\n".join(lines[:DIFF_LINE_CAP]) if truncated else text
    entry: dict = {"tokens": te.estimate_tokens(effective)}
    if truncated:
        entry["status"] = "included_partial"
        entry["truncated_at_lines"] = DIFF_LINE_CAP
    else:
        entry["status"] = "included"
    if diff_file:
        h = te.hash_file(diff_file)
        if h:
            entry["file_hash"] = h
    return entry


def build_budget(
    scenario: str,
    issue_num: int,
    run_id: str,
    artifacts_dir: str,
    clone_dir: str,
    out: str,
    spec_file: str | None = None,
    plan_file: str | None = None,
    memory_file: str | None = None,
    issue_json: str | None = None,
    impl_file: str | None = None,
    diff_file: str | None = None,
) -> None:
    active = _SECTION_REGISTRY.get(scenario, [])
    sections: dict[str, dict] = {}
    source_hashes: dict[str, str] = {}

    for sec in active:
        if sec == "claude_md":
            path = os.path.join(clone_dir, "CLAUDE.md")
            sections[sec] = _included(_read_text(path), path)
            h = te.hash_file(path)
            if h:
                source_hashes["CLAUDE.md"] = h

        elif sec == "architecture_md":
            path = os.path.join(clone_dir, "ARCHITECTURE.md")
            sections[sec] = _included(_read_text(path), path)
            h = te.hash_file(path)
            if h:
                source_hashes["ARCHITECTURE.md"] = h

        elif sec == "skill_prompts":
            sections[sec] = _probe_skill_prompts()

        elif sec == "issue_context":
            sections[sec] = _probe_issue_context(issue_json)

        elif sec == "comments":
            sections[sec] = _probe_comments(issue_json)

        elif sec == "memory_context":
            sections[sec] = _included(_read_text(memory_file), memory_file)
            if memory_file:
                h = te.hash_file(memory_file)
                if h:
                    source_hashes["memory-context.md"] = h
            # Note: memory-context.md is written inside the command session by memory_retrieve.py.
            # The budget node runs before the command so the file won't exist yet — sections[sec]
            # correctly shows status="dropped", reason="empty_or_missing" (matching spec vocabulary).

        elif sec == "spec":
            sections[sec] = _included(_read_text(spec_file), spec_file)
            if spec_file and sections[sec]["status"] == "included":
                h = te.hash_file(spec_file)
                if h:
                    source_hashes["spec"] = h

        elif sec == "plan":
            sections[sec] = _included(_read_text(plan_file), plan_file)

        elif sec == "implementation_md":
            sections[sec] = _included(_read_text(impl_file), impl_file)
            if impl_file:
                h = te.hash_file(impl_file)
                if h:
                    source_hashes["implementation.md"] = h

        elif sec == "diff":
            sections[sec] = _probe_diff(diff_file)
            if diff_file:
                h = te.hash_file(diff_file)
                if h:
                    source_hashes["diff"] = h

        elif sec == "pr_reviews":
            sections[sec] = _probe_pr_reviews(issue_json)

    included = [s for s, v in sections.items() if v["status"] in ("included", "included_partial")]
    dropped = [s for s, v in sections.items() if v["status"] == "dropped"]
    estimated = sum(v.get("tokens", 0) for v in sections.values())
    utilization = round(estimated / BUDGET_TOKENS * 100, 1)

    artifact = {
        "schema_version": 1,
        "scenario": scenario,
        "run_id": run_id,
        "issue_number": issue_num,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "budget_tokens": BUDGET_TOKENS,
        "estimated_input_tokens": estimated,
        "utilization_pct": utilization,
        "sections": sections,
        "included_sections": included,
        "dropped_sections": dropped,
        "source_file_hashes": source_hashes,
    }

    out_dir = os.path.dirname(out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Emit context-budget.json for a Dark Factory phase.")
    p.add_argument("--scenario", required=True, choices=list(_SECTION_REGISTRY))
    p.add_argument("--issue-num", required=True, type=int)
    p.add_argument("--run-id", required=True)
    p.add_argument("--artifacts-dir", required=True)
    p.add_argument("--clone-dir", required=True)
    p.add_argument("--spec-file")
    p.add_argument("--plan-file")
    p.add_argument("--memory-file")
    p.add_argument("--issue-json")
    p.add_argument("--impl-file")
    p.add_argument("--diff-file")
    p.add_argument("--out")
    args = p.parse_args(argv)

    out = args.out or os.path.join(args.artifacts_dir, "context-budget.json")
    build_budget(
        scenario=args.scenario,
        issue_num=args.issue_num,
        run_id=args.run_id,
        artifacts_dir=args.artifacts_dir,
        clone_dir=args.clone_dir,
        out=out,
        spec_file=args.spec_file,
        plan_file=args.plan_file,
        memory_file=args.memory_file,
        issue_json=args.issue_json,
        impl_file=args.impl_file,
        diff_file=args.diff_file,
    )
    print(f"context-budget.json written to {out}")


if __name__ == "__main__":
    main()
```

**2d. Run tests — expect pass**

```bash
python -m pytest dark-factory/tests/test_context_budget.py -v
```

Expected:
```
PASSED test_required_fields_present
PASSED test_schema_version_is_1
PASSED test_budget_tokens_is_200000
PASSED test_utilization_pct_matches_tokens
PASSED test_scenario_and_run_id_round_trip
PASSED test_plan_spec_present_is_included
PASSED test_plan_spec_missing_is_dropped
PASSED test_conformance_diff_over_1000_lines_is_partial
PASSED test_conformance_diff_under_1000_lines_is_included
PASSED test_included_dropped_lists_consistent
PASSED test_source_file_hashes_populated_when_file_exists
PASSED test_conformance_excludes_inapplicable_sections
PASSED test_continue_scenario_includes_pr_reviews
PASSED test_implement_scenario_excludes_pr_reviews
PASSED test_estimated_tokens_is_sum_of_section_tokens
PASSED test_memory_context_absent_is_dropped
16 passed in 0.XXs
```

**2e. Smoke-test CLI directly**

```bash
mkdir -p /tmp/test-budget-664
python3 dark-factory/scripts/context_budget.py \
  --scenario plan \
  --issue-num 664 \
  --run-id test-run-001 \
  --artifacts-dir /tmp/test-budget-664 \
  --clone-dir . \
  --out /tmp/test-budget-664/context-budget.json && \
python3 -m json.tool /tmp/test-budget-664/context-budget.json | head -30
```

Expected: valid JSON with `"schema_version": 1`, `"scenario": "plan"`, sections for `claude_md`, `skill_prompts`, `issue_context`, `comments`, `memory_context`, `spec` (all with a status field).

**2f. Commit**

```bash
git add dark-factory/scripts/context_budget.py dark-factory/tests/test_context_budget.py
git commit -m "feat: add context_budget.py CLI — probe sections and emit context-budget.json (#664)"
```

---

## Task 3: Add 5 pre-phase bash nodes to `archon-dark-factory.yaml`

**Files:** `.archon/workflows/archon-dark-factory.yaml`
**Time:** ~15 min

### Steps

**3a. Verify target node line numbers**

```bash
grep -n "^  - id:" .archon/workflows/archon-dark-factory.yaml | grep -E "refine$|^.*plan$|^.*implement$|^.*conformance$|^.*code-review$"
```

Expected (line numbers will vary):
```
NNN:  - id: refine
NNN:  - id: plan
NNN:  - id: implement
NNN:  - id: conformance
NNN:  - id: code-review
```

**3b. Insert `budget-refine` before `refine`, extend `refine.depends_on`**

In `.archon/workflows/archon-dark-factory.yaml`, immediately before the `# Layer 2a: Refine` comment block, insert:

```yaml
  # Context budget telemetry — captures pre-prompt token estimate for refine phase
  - id: budget-refine
    bash: |
      ISSUE=$(jq -r '.resolved_number' "$ARTIFACTS_DIR/issue.json")
      # $CLONE_DIR and $RUN_ID are NOT exported to bash nodes (see de-conflict node comment).
      # Fall back to "." for CLONE_DIR (CWD is the clone root in bash nodes) and derive
      # RUN_ID from the ARTIFACTS_DIR basename (e.g. .../runs/<run-id>).
      _CLONE="${CLONE_DIR:-.}"
      _RUN="${RUN_ID:-$(basename "${ARTIFACTS_DIR:-/tmp/budget}")}"
      python3 "$_CLONE/dark-factory/scripts/context_budget.py" \
        --scenario refine \
        --issue-num "$ISSUE" \
        --run-id "$_RUN" \
        --artifacts-dir "$ARTIFACTS_DIR" \
        --clone-dir "$_CLONE" \
        --issue-json "$ARTIFACTS_DIR/issue.json" \
        --memory-file "$ARTIFACTS_DIR/memory-context.md" \
        --out "$ARTIFACTS_DIR/context-budget.json" || true
    depends_on: [setup-refine-branch, fetch-issue]
    when: "$parse-intent.output.intent == 'refine'"
    timeout: 30000

```

Change the `refine` node:
```yaml
  # Layer 2a: Refine — generate spec via multi-agent brainstorming
  - id: refine
    command: dark-factory-refine
    depends_on: [budget-refine, setup-refine-branch, fetch-issue]
    when: "$parse-intent.output.intent == 'refine'"
    idle_timeout: 600000
```

**3c. Insert `budget-plan` before `plan`, extend `plan.depends_on`**

Immediately before the `# Layer 2b: Plan` comment, insert:

```yaml
  # Context budget telemetry — captures pre-prompt token estimate for plan phase
  - id: budget-plan
    bash: |
      ISSUE=$(jq -r '.resolved_number' "$ARTIFACTS_DIR/issue.json")
      _CLONE="${CLONE_DIR:-.}"
      _RUN="${RUN_ID:-$(basename "${ARTIFACTS_DIR:-/tmp/budget}")}"
      SPEC_FILE=$(grep -rl "#${ISSUE}" "$_CLONE/docs/superpowers/specs/" 2>/dev/null | head -1 || true)
      python3 "$_CLONE/dark-factory/scripts/context_budget.py" \
        --scenario plan \
        --issue-num "$ISSUE" \
        --run-id "$_RUN" \
        --artifacts-dir "$ARTIFACTS_DIR" \
        --clone-dir "$_CLONE" \
        --issue-json "$ARTIFACTS_DIR/issue.json" \
        --memory-file "$ARTIFACTS_DIR/memory-context.md" \
        ${SPEC_FILE:+--spec-file "$SPEC_FILE"} \
        --out "$ARTIFACTS_DIR/context-budget.json" || true
    depends_on: [setup-refine-branch, fetch-issue]
    when: "$parse-intent.output.intent == 'plan'"
    timeout: 30000

```

Change the `plan` node:
```yaml
  # Layer 2b: Plan — generate implementation plan with architect review
  - id: plan
    command: dark-factory-plan
    depends_on: [budget-plan, setup-refine-branch, fetch-issue]
    when: "$parse-intent.output.intent == 'plan'"
    idle_timeout: 600000
```

**3d. Insert `budget-implement` before `implement`, extend `implement.depends_on`**

Immediately before the `# Layer 2: Implement` comment, insert:

```yaml
  # Context budget telemetry — captures pre-prompt token estimate for implement/continue phase.
  # INTENT is read from issue.json (new|continue); context_budget.py uses the distinct registry
  # entries for each: "continue" includes pr_reviews, "new" does not (per _SECTION_REGISTRY).
  - id: budget-implement
    bash: |
      ISSUE=$(jq -r '.resolved_number' "$ARTIFACTS_DIR/issue.json")
      INTENT=$(jq -r '.intent' "$ARTIFACTS_DIR/issue.json")
      _CLONE="${CLONE_DIR:-.}"
      _RUN="${RUN_ID:-$(basename "${ARTIFACTS_DIR:-/tmp/budget}")}"
      # memory-context.md is written inside the command session by memory_retrieve.py (Phase 1
      # load). This applies to all of refine, plan, implement, continue — budget nodes always
      # run before the command. Reported as dropped/empty_or_missing; this is expected.
      python3 "$_CLONE/dark-factory/scripts/context_budget.py" \
        --scenario "$INTENT" \
        --issue-num "$ISSUE" \
        --run-id "$_RUN" \
        --artifacts-dir "$ARTIFACTS_DIR" \
        --clone-dir "$_CLONE" \
        --issue-json "$ARTIFACTS_DIR/issue.json" \
        --memory-file "$ARTIFACTS_DIR/memory-context.md" \
        --out "$ARTIFACTS_DIR/context-budget.json" || true
    depends_on: [update-codeindex, fetch-issue]
    when: "$parse-intent.output.intent == 'new' || $parse-intent.output.intent == 'continue'"
    timeout: 30000

```

Change the `implement` node:
```yaml
  # Layer 2: Implement the feature (status set to "In Progress" by entrypoint or epic resolver)
  - id: implement
    command: dark-factory-implement
    depends_on: [budget-implement, update-codeindex, fetch-issue]
    when: "$parse-intent.output.intent == 'new' || $parse-intent.output.intent == 'continue'"
    idle_timeout: 600000
```

**3e. Insert `budget-conformance` before `conformance`, extend `conformance.depends_on`**

Immediately before the `# Layer 3.5: Verify implementation` comment, insert:

```yaml
  # Context budget telemetry — captures pre-prompt token estimate for conformance phase
  - id: budget-conformance
    bash: |
      ISSUE=$(jq -r '.resolved_number' "$ARTIFACTS_DIR/issue.json")
      _CLONE="${CLONE_DIR:-.}"
      _RUN="${RUN_ID:-$(basename "${ARTIFACTS_DIR:-/tmp/budget}")}"
      SPEC_FILE=$(grep -rl "#${ISSUE}" "$_CLONE/docs/superpowers/specs/" 2>/dev/null | head -1 || true)
      # review_diff.txt is written inside the conformance command session, not before it.
      # Use three-dot (matches what dark-factory-conformance.md sends to Claude) for telemetry
      # fidelity. Note: three-dot is intentional here (measure what command loads), NOT for
      # OOS detection (which uses two-dot per codebase-patterns.md).
      DIFF_TMP=$(mktemp)
      git diff main...HEAD > "$DIFF_TMP" 2>/dev/null || true
      python3 "$_CLONE/dark-factory/scripts/context_budget.py" \
        --scenario conformance \
        --issue-num "$ISSUE" \
        --run-id "$_RUN" \
        --artifacts-dir "$ARTIFACTS_DIR" \
        --clone-dir "$_CLONE" \
        ${SPEC_FILE:+--spec-file "$SPEC_FILE"} \
        --impl-file "$ARTIFACTS_DIR/implementation.md" \
        --diff-file "$DIFF_TMP" \
        --out "$ARTIFACTS_DIR/context-budget.json" || true
      rm -f "$DIFF_TMP"
    depends_on: [validate]
    when: "$parse-intent.output.intent == 'new' || $parse-intent.output.intent == 'continue'"
    timeout: 30000

```

Change the `conformance` node:
```yaml
  # Layer 3.5: Verify implementation conforms to spec (Gate 2 — code vs spec)
  - id: conformance
    command: dark-factory-conformance
    depends_on: [budget-conformance, validate]
    when: "$parse-intent.output.intent == 'new' || $parse-intent.output.intent == 'continue'"
    idle_timeout: 600000
```

**3f. Insert `budget-code-review` before `code-review`, extend `code-review.depends_on`**

Immediately before the `# Layer 4.5: AI code review` comment, insert:

```yaml
  # Context budget telemetry — captures pre-prompt token estimate for code-review phase
  - id: budget-code-review
    bash: |
      ISSUE=$(jq -r '.resolved_number' "$ARTIFACTS_DIR/issue.json")
      _CLONE="${CLONE_DIR:-.}"
      _RUN="${RUN_ID:-$(basename "${ARTIFACTS_DIR:-/tmp/budget}")}"
      # The code-review diff is produced inside the command session (branch is already pushed
      # at this point — push-and-pr ran). Use three-dot to match what dark-factory-code-review.md
      # sends to Claude (telemetry fidelity). Not for OOS detection (which uses two-dot).
      DIFF_TMP=$(mktemp)
      git diff main...HEAD > "$DIFF_TMP" 2>/dev/null || true
      python3 "$_CLONE/dark-factory/scripts/context_budget.py" \
        --scenario code-review \
        --issue-num "$ISSUE" \
        --run-id "$_RUN" \
        --artifacts-dir "$ARTIFACTS_DIR" \
        --clone-dir "$_CLONE" \
        --issue-json "$ARTIFACTS_DIR/issue.json" \
        --diff-file "$DIFF_TMP" \
        --out "$ARTIFACTS_DIR/context-budget.json" || true
      rm -f "$DIFF_TMP"
    depends_on: [push-and-pr]
    when: "$parse-intent.output.intent == 'new' || $parse-intent.output.intent == 'continue'"
    timeout: 30000

```

Change the `code-review` node:
```yaml
  # Layer 4.5: AI code review of the diff (Gate 3 — correctness/security)
  - id: code-review
    command: dark-factory-code-review
    depends_on: [budget-code-review, push-and-pr]
    when: "$parse-intent.output.intent == 'new' || $parse-intent.output.intent == 'continue'"
    idle_timeout: 600000
```

**3g. Validate YAML syntax**

```bash
python3 -c "import yaml; yaml.safe_load(open('.archon/workflows/archon-dark-factory.yaml'))" && echo "YAML valid"
```

Expected: `YAML valid`

**3h. Validate DAG and `when:` expressions**

```bash
python3 dark-factory/scripts/check_workflow_dag.py .archon/workflows/archon-dark-factory.yaml && echo "DAG OK"
python3 dark-factory/scripts/check_workflow_when.py .archon/workflows/archon-dark-factory.yaml && echo "WHEN OK"
```

Expected: `DAG OK` and `WHEN OK` (no cycle errors, no mixed-operator `when:` expressions).

**3i. Confirm budget nodes appear and command nodes have extended depends_on**

```bash
grep -A3 "id: budget-" .archon/workflows/archon-dark-factory.yaml | grep "id:"
grep -A3 "id: refine$\|id: plan$\|id: implement$\|id: conformance$\|id: code-review$" \
  .archon/workflows/archon-dark-factory.yaml | grep "depends_on:" | grep budget
```

Expected: 5 `id: budget-*` lines and 5 `depends_on:` lines each containing a `budget-*` entry.

**3j. Commit**

```bash
git add .archon/workflows/archon-dark-factory.yaml
git commit -m "feat: add 5 context-budget telemetry nodes to dark factory workflow (#664)"
```

---

## Final Verification

Run all new tests together to confirm nothing regressed:

```bash
python -m pytest dark-factory/tests/test_token_estimate.py dark-factory/tests/test_context_budget.py -v
```

Expected: 25 tests pass, 0 failures.

---

*Generated by MarketHawk Refinement Pipeline*
