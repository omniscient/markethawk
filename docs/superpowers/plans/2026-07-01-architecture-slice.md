# Implementation Plan — Architecture Slice (#666)

**Goal:** Replace the monolithic `ARCHITECTURE.md` load in Dark Factory context packs with a targeted `architecture_slice.py` library+CLI that emits only the sections relevant to the current component (backend / frontend / dark-factory / infrastructure). Fallbacks to the full document when component inference fails or safety-sensitive signals are present. Integrates with `context_budget.py` as a drop-in for the existing `architecture_md` section handler.

**Issue:** #666  
**Spec:** `docs/superpowers/specs/2026-07-01-architecture-slice-design.md`  
**Date:** 2026-07-01

---

## Architecture

New `dark-factory/scripts/architecture_slice.py` library module, imported by `context_budget.py` (matching the `token_estimate.py` library-import precedent). No subprocess, no new Docker service, no entrypoint.sh change.

`build_budget()` gains three optional kwargs (`spec_component`, `changed_files`, `labels`) and the `architecture_md` section handler is replaced with a `slice_architecture()` call. Existing call sites pass `None` for all three — behaviour is unchanged until the caller wires them up.

The `plan` scenario in `_SECTION_REGISTRY` gains `architecture_md` so plan-phase agents receive the relevant architecture context.

---

## Tech Stack

- **Language/runtime:** Python 3.11, stdlib only in the core library (`dataclasses`, `hashlib`, `re`, `os`); `yaml` loaded via lazy import for config parsing (same pattern as `gate_blast_radius.py`)
- **Tests:** `pytest` with `tmp_path` fixture; no mocking required — the library works on filesystem fixtures

---

## File Structure

| File | Status | Purpose |
|------|--------|---------|
| `dark-factory/scripts/architecture_slice.py` | New | Library + CLI: `SliceResult`, `COMPONENT_SECTION_MAP`, `infer_component()`, `slice_architecture()` |
| `dark-factory/tests/test_architecture_slice.py` | New | 14 unit tests (12 for the slicer, 2 for context_budget integration) |
| `dark-factory/scripts/context_budget.py` | Modified | Import slicer; add 3 new kwargs; wire `architecture_md` handler; add `architecture_md` to `plan` scenario |

---

## Task 1 — `architecture_slice.py` library + 12 slicer tests (TDD)

**Files:** `dark-factory/scripts/architecture_slice.py`, `dark-factory/tests/test_architecture_slice.py`

### 1.1 — Write 12 failing slicer tests

Create `dark-factory/tests/test_architecture_slice.py` with the fixture helpers and the first 12 tests:

```python
"""Tests for architecture_slice.py — library and CLI for targeted ARCHITECTURE.md slices."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import architecture_slice as aslice
from architecture_slice import SliceResult, COMPONENT_SECTION_MAP, infer_component, slice_architecture


# ── Fixtures ──────────────────────────────────────────────────────────────────

SECTION_NAMES = [
    "Service Topology",
    "Scan Execution Flow",
    "Backend Module Map",
    "Frontend Architecture",
    "Error Tracking System",
    "IB Gateway Integration",
    "Live Scanner",
    "Celery Task Architecture",
    "Catch Up Feature (Universe Aggregate Backfill)",
    "Metrics and Observability",
    "Test Architecture",
]


def make_arch_md(tmp_path) -> str:
    lines = ["# Architecture\n\n"]
    for name in SECTION_NAMES:
        lines.append(f"## {name}\n\nContent for {name}.\n\n")
    p = tmp_path / "ARCHITECTURE.md"
    p.write_text("".join(lines))
    return str(p)


def make_config(tmp_path) -> None:
    skill_dir = tmp_path / ".claude" / "skills" / "refinement"
    skill_dir.mkdir(parents=True)
    (skill_dir / "config.yaml").write_text(
        "dispatch_ceiling:\n"
        "  keywords: 'migration|migrate|performance|perf|architectur|refactor'\n"
        "epic_autopilot:\n"
        "  sensitive_keywords: 'trading|ibkr|live order|notional|authentication'\n"
        "  hard_exclude_paths:\n"
        "    - app/services/trading\n"
        "    - app/tasks/trading.py\n"
        "    - app/core/auth\n"
        "    - app/routers/auth\n"
    )


# ── Component slice tests ─────────────────────────────────────────────────────

def test_backend_slice(tmp_path):
    make_arch_md(tmp_path)
    make_config(tmp_path)
    result = slice_architecture(
        str(tmp_path / "ARCHITECTURE.md"), "implement",
        spec_component="backend", clone_dir=str(tmp_path)
    )
    assert not result.fallback
    assert "Backend Module Map" in result.included_sections
    assert "Frontend Architecture" not in result.included_sections
    assert "Frontend Architecture" in result.omitted_sections


def test_frontend_slice(tmp_path):
    make_arch_md(tmp_path)
    make_config(tmp_path)
    result = slice_architecture(
        str(tmp_path / "ARCHITECTURE.md"), "implement",
        spec_component="frontend", clone_dir=str(tmp_path)
    )
    assert not result.fallback
    assert "Frontend Architecture" in result.included_sections
    assert "Live Scanner" not in result.included_sections
    assert "Live Scanner" in result.omitted_sections


def test_dark_factory_slice(tmp_path):
    make_arch_md(tmp_path)
    make_config(tmp_path)
    result = slice_architecture(
        str(tmp_path / "ARCHITECTURE.md"), "refine",
        spec_component="dark-factory", clone_dir=str(tmp_path)
    )
    assert not result.fallback
    assert "Service Topology" in result.included_sections
    assert "Test Architecture" not in result.included_sections
    assert "Test Architecture" in result.omitted_sections


def test_infrastructure_slice(tmp_path):
    make_arch_md(tmp_path)
    make_config(tmp_path)
    result = slice_architecture(
        str(tmp_path / "ARCHITECTURE.md"), "refine",
        spec_component="infrastructure", clone_dir=str(tmp_path)
    )
    assert not result.fallback
    assert "IB Gateway Integration" in result.included_sections
    assert "Backend Module Map" not in result.included_sections
    assert "Backend Module Map" in result.omitted_sections


# ── Inference tests ───────────────────────────────────────────────────────────

def test_infer_backend_from_changed_files():
    component = infer_component(None, ["backend/app/services/scanner.py"], None)
    assert component == "backend"


def test_infer_frontend_from_changed_files():
    component = infer_component(None, ["frontend/src/pages/Scanner/index.tsx"], None)
    assert component == "frontend"


def test_infer_dark_factory_from_changed_files():
    component = infer_component(None, ["dark-factory/scripts/context_budget.py"], None)
    assert component == "dark-factory"


# ── Fallback tests ────────────────────────────────────────────────────────────

def test_fallback_no_signals(tmp_path):
    make_arch_md(tmp_path)
    make_config(tmp_path)
    result = slice_architecture(
        str(tmp_path / "ARCHITECTURE.md"), "refine",
        clone_dir=str(tmp_path)
    )
    assert result.fallback
    assert result.fallback_reason == "component_unresolved"


def test_fallback_safety_keyword_label(tmp_path):
    make_arch_md(tmp_path)
    make_config(tmp_path)
    result = slice_architecture(
        str(tmp_path / "ARCHITECTURE.md"), "refine",
        spec_component="backend",
        labels=["trading"],
        clone_dir=str(tmp_path),
    )
    assert result.fallback
    assert "safety_keyword:trading" in result.fallback_reason


def test_fallback_safety_file(tmp_path):
    make_arch_md(tmp_path)
    make_config(tmp_path)
    result = slice_architecture(
        str(tmp_path / "ARCHITECTURE.md"), "implement",
        spec_component="backend",
        changed_files=["backend/app/core/config.py"],
        clone_dir=str(tmp_path),
    )
    assert result.fallback
    assert "safety_file" in result.fallback_reason


# ── Metadata tests ────────────────────────────────────────────────────────────

def test_omitted_comment_in_slice(tmp_path):
    make_arch_md(tmp_path)
    make_config(tmp_path)
    result = slice_architecture(
        str(tmp_path / "ARCHITECTURE.md"), "implement",
        spec_component="backend", clone_dir=str(tmp_path)
    )
    assert result.text.startswith("<!-- architecture-slice:")


def test_explicit_component_overrides_inference(tmp_path):
    make_arch_md(tmp_path)
    make_config(tmp_path)
    result = slice_architecture(
        str(tmp_path / "ARCHITECTURE.md"), "implement",
        spec_component="frontend",
        changed_files=["backend/app/services/scanner.py"],
        clone_dir=str(tmp_path),
    )
    assert not result.fallback
    assert result.component == "frontend"
    assert "Frontend Architecture" in result.included_sections
```

### 1.2 — Verify tests fail

```bash
cd /workspace/markethawk
python -m pytest dark-factory/tests/test_architecture_slice.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'architecture_slice'` (or similar import failure for all 12 tests).

### 1.3 — Implement `dark-factory/scripts/architecture_slice.py`

Create the file:

```python
"""Library + CLI: produce targeted ARCHITECTURE.md slices for Dark Factory agents.

Parses ARCHITECTURE.md by ##-level headings and returns a component-scoped
slice (backend / frontend / dark-factory / infrastructure). Falls back to the
full document when component inference fails or safety-sensitive signals are
present.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field


# ── Component → section map ───────────────────────────────────────────────────

COMPONENT_SECTION_MAP: dict[str, list[str]] = {
    "backend": [
        "Scan Execution Flow",
        "Backend Module Map",
        "Error Tracking System",
        "Celery Task Architecture",
        "Test Architecture",
    ],
    "frontend": [
        "Frontend Architecture",
        "Backend Module Map",
        "Error Tracking System",
    ],
    "dark-factory": [
        "Service Topology",
        "Celery Task Architecture",
        "Metrics and Observability",
    ],
    "infrastructure": [
        "Service Topology",
        "IB Gateway Integration",
        "Live Scanner",
        "Celery Task Architecture",
        "Catch Up Feature (Universe Aggregate Backfill)",
        "Metrics and Observability",
    ],
}

_DEFAULT_DISPATCH_KEYWORDS = "migration|migrate|performance|perf|architectur|refactor"
_DEFAULT_SENSITIVE_KEYWORDS = (
    "trading|ibkr|live order|notional|authentication|authorization"
    "|authn|authz|jwt|oauth|rbac|/auth"
)
_DEFAULT_HARD_EXCLUDE_PATHS: list[str] = [
    "app/services/trading",
    "app/tasks/trading.py",
    "app/core/auth",
    "app/routers/auth",
]
_CROSS_CUTTING_INFRA_PREFIXES = [
    "ARCHITECTURE.md",
    "backend/app/core/",
    "backend/app/main.py",
]


# ── SliceResult dataclass ─────────────────────────────────────────────────────

@dataclass
class SliceResult:
    text: str
    component: str | None
    scenario: str
    included_sections: list[str]
    omitted_sections: list[str]
    section_hashes: dict[str, str]
    fallback: bool
    fallback_reason: str | None


# ── Internal helpers ──────────────────────────────────────────────────────────

def _parse_sections(arch_path: str) -> dict[str, str]:
    """Read ARCHITECTURE.md; return {heading_title: content} for ## headings."""
    try:
        with open(arch_path, encoding="utf-8") as f:
            raw = f.read()
    except (FileNotFoundError, OSError):
        return {}
    sections: dict[str, str] = {}
    current_title: str | None = None
    current_lines: list[str] = []
    for line in raw.splitlines(keepends=True):
        if line.startswith("## "):
            if current_title is not None:
                sections[current_title] = "".join(current_lines)
            current_title = line[3:].rstrip("\n").strip()
            current_lines = [line]
        elif current_title is not None:
            current_lines.append(line)
    if current_title is not None:
        sections[current_title] = "".join(current_lines)
    return sections


def _load_config(clone_dir: str) -> dict:
    config_path = os.path.join(
        clone_dir, ".claude", "skills", "refinement", "config.yaml"
    )
    try:
        import yaml  # type: ignore
        with open(config_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _check_safety_fallback(
    labels: list[str] | None,
    title: str | None,
    changed_files: list[str] | None,
    config: dict,
) -> str | None:
    dispatch_kws = config.get("dispatch_ceiling", {}).get(
        "keywords", _DEFAULT_DISPATCH_KEYWORDS
    )
    sensitive_kws = config.get("epic_autopilot", {}).get(
        "sensitive_keywords", _DEFAULT_SENSITIVE_KEYWORDS
    )
    hard_excludes: list[str] = config.get("epic_autopilot", {}).get(
        "hard_exclude_paths", _DEFAULT_HARD_EXCLUDE_PATHS
    )

    text_lower = (" ".join(labels or []) + " " + (title or "")).lower()

    for kw in dispatch_kws.split("|"):
        kw = kw.strip()
        if kw and kw in text_lower:
            return f"safety_keyword:{kw}"

    for kw in sensitive_kws.split("|"):
        kw = kw.strip()
        if kw and kw in text_lower:
            return f"safety_keyword:{kw}"

    for f in changed_files or []:
        for exclude in hard_excludes:
            if exclude in f:
                return f"safety_file:{f}"
        for prefix in _CROSS_CUTTING_INFRA_PREFIXES:
            if f == prefix or f.startswith(prefix):
                return f"safety_file:{f}"
        basename = os.path.basename(f)
        if basename.startswith("docker-compose") and basename.endswith((".yml", ".yaml")):
            return f"safety_file:{f}"

    return None


def _slice_comment(
    component: str,
    scenario: str,
    included: list[str],
    omitted: list[str],
) -> str:
    return (
        f"<!-- architecture-slice: component={component} scenario={scenario}\n"
        f"     included: {', '.join(included)}\n"
        f"     omitted: {', '.join(omitted)}\n"
        f"     (load full ARCHITECTURE.md if your change touches an omitted area) -->\n"
    )


def _fallback_comment(
    component: str | None,
    scenario: str,
    reason: str,
) -> str:
    return (
        f"<!-- architecture-slice: component={component} scenario={scenario}"
        f" fallback=true reason={reason}\n"
        f"     full ARCHITECTURE.md loaded -->\n"
    )


# ── Public API ────────────────────────────────────────────────────────────────

def infer_component(
    spec_file: str | None,
    changed_files: list[str] | None,
    labels: list[str] | None,
) -> str | None:
    """Infer component from changed files, spec filename keywords, or issue labels."""
    for f in changed_files or []:
        if f.startswith("backend/app/"):
            return "backend"
        if f.startswith("frontend/src/"):
            return "frontend"
        if f.startswith("dark-factory/"):
            return "dark-factory"
        if f.startswith("docker-compose"):
            return "infrastructure"

    if spec_file:
        slug = os.path.basename(spec_file)
        slug = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", slug)
        slug = re.sub(r"\.md$", "", slug)
        tokens = set(slug.replace("-", " ").replace("_", " ").lower().split())
        if tokens & {"backend", "scanner", "api", "celery", "database", "migration"}:
            return "backend"
        if tokens & {"frontend", "ui", "react", "page", "component"}:
            return "frontend"
        if tokens & {"factory", "archon", "scheduler", "dark", "refine", "plan", "pipeline"}:
            return "dark-factory"
        if tokens & {"infrastructure", "docker", "ibkr", "gateway", "prometheus", "grafana"}:
            return "infrastructure"

    for label in labels or []:
        ll = label.lower()
        if "dark factory" in ll or ll == "dark-factory":
            return "dark-factory"
        if "frontend" in ll:
            return "frontend"
        if "backend" in ll:
            return "backend"
        if "infrastructure" in ll:
            return "infrastructure"

    return None


def slice_architecture(
    arch_path: str,
    scenario: str,
    spec_component: str | None = None,
    spec_file: str | None = None,
    changed_files: list[str] | None = None,
    labels: list[str] | None = None,
    title: str | None = None,
    clone_dir: str | None = None,
) -> SliceResult:
    """Return a SliceResult for the given context signals."""
    effective_clone_dir = clone_dir or os.path.dirname(arch_path)
    config = _load_config(effective_clone_dir)
    all_sections = _parse_sections(arch_path)
    all_titles = list(all_sections.keys())

    def full_doc(reason: str) -> SliceResult:
        text = _fallback_comment(None, scenario, reason) + "".join(
            all_sections.values()
        )
        return SliceResult(
            text=text,
            component=None,
            scenario=scenario,
            included_sections=all_titles,
            omitted_sections=[],
            section_hashes={},
            fallback=True,
            fallback_reason=reason,
        )

    safety_reason = _check_safety_fallback(labels, title, changed_files, config)
    if safety_reason:
        return full_doc(safety_reason)

    component = spec_component or infer_component(spec_file, changed_files, labels)
    if not component or component not in COMPONENT_SECTION_MAP:
        return full_doc("component_unresolved")

    wanted = set(COMPONENT_SECTION_MAP[component])
    included = [t for t in all_titles if t in wanted]
    omitted = [t for t in all_titles if t not in wanted]

    if not included:
        return full_doc("component_unresolved")

    hashes = {
        t: hashlib.sha256(all_sections[t].encode()).hexdigest()[:12]
        for t in included
    }
    body = "".join(all_sections[t] for t in included)
    text = _slice_comment(component, scenario, included, omitted) + body

    return SliceResult(
        text=text,
        component=component,
        scenario=scenario,
        included_sections=included,
        omitted_sections=omitted,
        section_hashes=hashes,
        fallback=False,
        fallback_reason=None,
    )


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Emit a targeted ARCHITECTURE.md slice."
    )
    parser.add_argument("--clone-dir", required=True)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--spec-component")
    parser.add_argument("--spec-file")
    parser.add_argument("--changed-files", nargs="*", default=[])
    parser.add_argument("--labels", nargs="*", default=[])
    parser.add_argument("--title")
    parser.add_argument("--out")
    args = parser.parse_args()

    arch_path = os.path.join(args.clone_dir, "ARCHITECTURE.md")
    result = slice_architecture(
        arch_path=arch_path,
        scenario=args.scenario,
        spec_component=args.spec_component,
        spec_file=args.spec_file,
        changed_files=args.changed_files or [],
        labels=args.labels or [],
        title=args.title,
        clone_dir=args.clone_dir,
    )

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(result.text)
        with open(args.out + ".json", "w", encoding="utf-8") as f:
            json.dump(
                {
                    "component": result.component,
                    "scenario": result.scenario,
                    "included_sections": result.included_sections,
                    "omitted_sections": result.omitted_sections,
                    "section_hashes": result.section_hashes,
                    "fallback": result.fallback,
                    "fallback_reason": result.fallback_reason,
                },
                f,
                indent=2,
            )
    else:
        print(result.text, end="")

    sys.exit(0)


if __name__ == "__main__":
    main()
```

### 1.4 — Verify 12 slicer tests pass (2 context_budget tests are not in this file yet)

```bash
cd /workspace/markethawk
python -m pytest dark-factory/tests/test_architecture_slice.py -v 2>&1
```

Expected output:
```
test_backend_slice PASSED
test_frontend_slice PASSED
test_dark_factory_slice PASSED
test_infrastructure_slice PASSED
test_infer_backend_from_changed_files PASSED
test_infer_frontend_from_changed_files PASSED
test_infer_dark_factory_from_changed_files PASSED
test_fallback_no_signals PASSED
test_fallback_safety_keyword_label PASSED
test_fallback_safety_file PASSED
test_omitted_comment_in_slice PASSED
test_explicit_component_overrides_inference PASSED
12 passed in <1s
```

### 1.5 — Commit

```bash
cd /workspace/markethawk
git add dark-factory/scripts/architecture_slice.py dark-factory/tests/test_architecture_slice.py
git commit -m "feat(#666): add architecture_slice.py — targeted ARCHITECTURE.md slices"
```

Expected: commit succeeds with the two new files.

---

## Task 2 — Wire `architecture_slice` into `context_budget.py` (TDD)

**Files:** `dark-factory/scripts/context_budget.py`, `dark-factory/tests/test_architecture_slice.py`

### 2.1 — Append 2 context_budget integration tests to `test_architecture_slice.py`

Add at the bottom of `dark-factory/tests/test_architecture_slice.py`:

```python
# ── context_budget integration tests ─────────────────────────────────────────

def test_context_budget_included_slice_status(tmp_path):
    import context_budget as cb
    make_arch_md(tmp_path)
    make_config(tmp_path)
    out = str(tmp_path / "budget.json")
    cb.build_budget(
        scenario="refine",
        issue_num=666,
        run_id="test-666",
        artifacts_dir=str(tmp_path),
        clone_dir=str(tmp_path),
        out=out,
        spec_component="backend",
    )
    import json as _json
    result = _json.loads(Path(out).read_text())
    assert result["sections"]["architecture_md"]["status"] == "included_slice"


def test_context_budget_fallback_status(tmp_path):
    import context_budget as cb
    make_arch_md(tmp_path)
    make_config(tmp_path)
    out = str(tmp_path / "budget.json")
    cb.build_budget(
        scenario="refine",
        issue_num=666,
        run_id="test-666",
        artifacts_dir=str(tmp_path),
        clone_dir=str(tmp_path),
        out=out,
        labels=["trading"],
    )
    import json as _json
    result = _json.loads(Path(out).read_text())
    assert result["sections"]["architecture_md"]["status"] == "included"
    assert result["sections"]["architecture_md"]["fallback"] is True
```

### 2.2 — Verify 2 new tests fail

```bash
cd /workspace/markethawk
python -m pytest dark-factory/tests/test_architecture_slice.py::test_context_budget_included_slice_status \
                 dark-factory/tests/test_architecture_slice.py::test_context_budget_fallback_status -v 2>&1
```

Expected: `TypeError: build_budget() got an unexpected keyword argument 'spec_component'` (or similar) for both tests.

### 2.3 — Update `dark-factory/scripts/context_budget.py`

**Change 1:** Add import at the top of the file (after `import token_estimate as te`):

```python
import architecture_slice as aslice
```

**Change 2:** Add `architecture_md` to the `plan` scenario in `_SECTION_REGISTRY`:

```python
_SECTION_REGISTRY: dict[str, list[str]] = {
    "refine":      ["claude_md", "architecture_md", "skill_prompts", "issue_context", "comments", "memory_context"],
    "plan":        ["claude_md", "architecture_md", "skill_prompts", "issue_context", "comments", "memory_context", "spec"],
    "implement":   ["claude_md", "architecture_md", "issue_context", "comments", "memory_context"],
    "continue":    ["claude_md", "architecture_md", "issue_context", "comments", "memory_context", "pr_reviews"],
    "conformance": ["skill_prompts", "spec", "implementation_md", "diff"],
    "code-review": ["skill_prompts", "issue_context", "diff"],
}
```

**Change 3:** Add three new optional kwargs to `build_budget()`:

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
) -> None:
```

**Change 4:** Replace the `architecture_md` section handler (currently lines 163–168 in `context_budget.py`):

```python
        elif sec == "architecture_md":
            arch_path = os.path.join(clone_dir, "ARCHITECTURE.md")
            if not os.path.exists(arch_path):
                sections[sec] = _dropped("empty_or_missing")
            else:
                slice_result = aslice.slice_architecture(
                    arch_path=arch_path,
                    scenario=scenario,
                    spec_component=spec_component,
                    spec_file=spec_file,
                    changed_files=changed_files,
                    labels=labels,
                    clone_dir=clone_dir,
                )
                status = "included" if slice_result.fallback else "included_slice"
                sections[sec] = {
                    "status": status,
                    "tokens": te.estimate_tokens(slice_result.text),
                    "component": slice_result.component,
                    "included_sections": slice_result.included_sections,
                    "omitted_sections": slice_result.omitted_sections,
                    "section_hashes": slice_result.section_hashes,
                    "fallback": slice_result.fallback,
                    "fallback_reason": slice_result.fallback_reason,
                }
                h = te.hash_file(arch_path)
                if h:
                    source_hashes["ARCHITECTURE.md"] = h
```

**Change 5:** Add CLI args for the three new kwargs to `main()` in `context_budget.py` (add after `--diff-file`):

```python
    parser.add_argument("--spec-component",
                        help="Explicit component key (backend|frontend|dark-factory|infrastructure)")
    parser.add_argument("--changed-files", nargs="*", default=[],
                        help="Changed file paths for component inference")
    parser.add_argument("--labels", nargs="*", default=[],
                        help="Issue label strings for safety and component inference")
```

And pass them to `build_budget()`:

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
        changed_files=args.changed_files or [],
        labels=args.labels or [],
    )
```

### 2.4 — Verify all 14 tests pass

```bash
cd /workspace/markethawk
python -m pytest dark-factory/tests/test_architecture_slice.py -v 2>&1
```

Expected:
```
test_backend_slice PASSED
test_frontend_slice PASSED
test_dark_factory_slice PASSED
test_infrastructure_slice PASSED
test_infer_backend_from_changed_files PASSED
test_infer_frontend_from_changed_files PASSED
test_infer_dark_factory_from_changed_files PASSED
test_fallback_no_signals PASSED
test_fallback_safety_keyword_label PASSED
test_fallback_safety_file PASSED
test_omitted_comment_in_slice PASSED
test_explicit_component_overrides_inference PASSED
test_context_budget_included_slice_status PASSED
test_context_budget_fallback_status PASSED
14 passed in <1s
```

### 2.5 — Verify existing context_budget tests are unaffected

```bash
cd /workspace/markethawk
python -m pytest dark-factory/tests/test_context_budget.py -v 2>&1
```

Expected: all existing tests pass (the `architecture_md` section now returns `_dropped("empty_or_missing")` in tmp_path-based tests where no real ARCHITECTURE.md is present — same behaviour as the original handler for missing files).

### 2.6 — Smoke-test the CLI

```bash
python3 dark-factory/scripts/architecture_slice.py \
  --clone-dir /workspace/markethawk \
  --scenario implement \
  --spec-component dark-factory 2>&1 | head -10
```

Expected: output starts with `<!-- architecture-slice: component=dark-factory scenario=implement`.

### 2.7 — Commit

```bash
cd /workspace/markethawk
git add dark-factory/scripts/context_budget.py dark-factory/tests/test_architecture_slice.py
git commit -m "feat(#666): wire architecture_slice into context_budget — plan scenario + included_slice status"
```

---

## Summary

| Task | Files | Tests |
|------|-------|-------|
| 1 — architecture_slice.py | `scripts/architecture_slice.py`, `tests/test_architecture_slice.py` | 12 new |
| 2 — context_budget.py wire-in | `scripts/context_budget.py`, `tests/test_architecture_slice.py` | +2 new |

**Total:** 2 tasks, 14 new tests, 3 files (2 new, 1 modified).
