# Read-Through Memory Retrieval Adapter (#646)

**Goal:** Create `dark-factory/scripts/memory_retrieve.py` — a Python CLI that reads Dark Factory memory from flat files with role-segregated two-layer filtering, emitting a `### Memory: <filename>` markdown block compatible with the existing inline `load_memory()` bash function.

**Architecture:** Single Python file + pytest suite. When `.archon/memory/index.jsonl` is present (produced by #649), reads it for two-layer filtering and ranking by path specificity then recency. When absent, scans `.archon/memory/*.md` with identical filter logic. Fallback also triggers when the index produces zero survivors. Integration of the script into `.archon/commands/*.md` files is **out of scope** (issue #652).

```
dark-factory/scripts/memory_retrieve.py
  │
  ├── PHASE_SOURCE_MAP, GLOBAL_FILES     # constants
  ├── select_area_files()                # Layer 1: file selection by --files prefixes
  ├── passes_line()                      # Layer 2 filter: markdown fallback path
  ├── passes_record()                    # Layer 2 filter: index primary path
  ├── scan_markdown_files()              # Fallback: read .archon/memory/*.md
  ├── scan_index()                       # Primary: read index.jsonl, filter, rank
  ├── retrieve_memory()                  # Dispatch: index vs fallback; testable helper
  ├── format_output()                    # ### Memory: <file>\n- ...\n
  └── main()                             # argparse + wires everything
```

**Tech Stack:** Python 3 stdlib only — `argparse`, `json`, `pathlib`, `re`, `datetime`. pytest for tests.

**Spec:** `docs/superpowers/specs/2026-06-27-read-through-memory-retrieval-adapter-design.md`  
**Epic:** #643

## Global Constraints

- **Stdlib only** — no `agentmemory`, no HTTP client, no vector DB, no new Docker containers.
- **Flat-file only** — primary path reads `index.jsonl` via stdlib `json`; fallback reads `.archon/memory/*.md` via `open()`.
- **Backward-compatible output** — `### Memory: <file>` heading format matches the `$MEMORY_CONTEXT` builder in `dark-factory-plan.md` Phase 3.
- **Source filter is additive** — entries without a `source:` tag pass the filter unconditionally (backward-compat with pre-scoping entries).
- **Global files exempt** — `codebase-patterns.md` and `architecture.md` entries skip the source/agent_id filter entirely; area-specific files apply it fully.
- **Expiry** — entries with `expires:` (markdown) or `expires_at` (index) strictly in the past are excluded.
- Tests cover: index-present path, index-absent path, both Layer 2 filters, area selection, global-file exception, expiry exclusion, PROVISIONAL/INVALID exclusion, empty-files fallback.

## File Structure

| File | Action |
|------|--------|
| `dark-factory/scripts/memory_retrieve.py` | CREATE |
| `dark-factory/tests/test_memory_retrieve.py` | CREATE |

---

## Task 1 — CLI skeleton, constants, area selection (TDD)

**Files:** `dark-factory/scripts/memory_retrieve.py` (CREATE), `dark-factory/tests/test_memory_retrieve.py` (CREATE)

### Interfaces produced
- `PHASE_SOURCE_MAP: dict[str, str]` — maps phase names to `source:` vocabulary
- `GLOBAL_FILES: set[str]` — files that bypass the source filter
- `select_area_files(files: list) -> list` — returns ordered list of area filenames to include

---

- [ ] **Step 1.1 — Write failing tests**

Create `dark-factory/tests/test_memory_retrieve.py`:

```python
"""Tests for dark-factory/scripts/memory_retrieve.py."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import memory_retrieve as mr  # noqa: E402


class TestConstants:
    def test_phase_source_map_all_phases(self):
        assert mr.PHASE_SOURCE_MAP["refine"] == "refine"
        assert mr.PHASE_SOURCE_MAP["plan"] == "refine"
        assert mr.PHASE_SOURCE_MAP["implement"] == "implement"
        assert mr.PHASE_SOURCE_MAP["validate"] == "conformance"
        assert mr.PHASE_SOURCE_MAP["review"] == "code-review"

    def test_global_files_contains_shared_files(self):
        assert "codebase-patterns.md" in mr.GLOBAL_FILES
        assert "architecture.md" in mr.GLOBAL_FILES
        assert "backend-patterns.md" not in mr.GLOBAL_FILES
        assert "frontend-patterns.md" not in mr.GLOBAL_FILES
        assert "dark-factory-ops.md" not in mr.GLOBAL_FILES


class TestSelectAreaFiles:
    def test_empty_files_returns_all_five(self):
        result = mr.select_area_files([])
        assert set(result) == {
            "codebase-patterns.md", "architecture.md",
            "backend-patterns.md", "frontend-patterns.md", "dark-factory-ops.md",
        }

    def test_global_files_always_first(self):
        result = mr.select_area_files(["backend/app/models/foo.py"])
        assert result[0] == "codebase-patterns.md"
        assert result[1] == "architecture.md"

    def test_backend_path_adds_backend_patterns(self):
        result = mr.select_area_files(["backend/app/services/scanner.py"])
        assert "backend-patterns.md" in result
        assert "frontend-patterns.md" not in result
        assert "dark-factory-ops.md" not in result

    def test_frontend_path_adds_frontend_patterns(self):
        result = mr.select_area_files(["frontend/src/components/Chart.tsx"])
        assert "frontend-patterns.md" in result
        assert "backend-patterns.md" not in result

    def test_dark_factory_path_adds_ops(self):
        result = mr.select_area_files(["dark-factory/scripts/scheduler.sh"])
        assert "dark-factory-ops.md" in result
        assert "backend-patterns.md" not in result

    def test_docker_compose_adds_ops(self):
        result = mr.select_area_files(["docker-compose.yml"])
        assert "dark-factory-ops.md" in result

    def test_dockerfile_adds_ops(self):
        result = mr.select_area_files(["Dockerfile"])
        assert "dark-factory-ops.md" in result

    def test_mixed_backend_and_frontend(self):
        result = mr.select_area_files(["backend/app/foo.py", "frontend/src/bar.tsx"])
        assert "backend-patterns.md" in result
        assert "frontend-patterns.md" in result
        assert "dark-factory-ops.md" not in result

    def test_non_matching_path_only_global(self):
        result = mr.select_area_files(["scripts/run.sh"])
        assert result == ["codebase-patterns.md", "architecture.md"]

    def test_global_files_always_included_with_area_files(self):
        result = mr.select_area_files(["dark-factory/scripts/memory_retrieve.py"])
        assert "codebase-patterns.md" in result
        assert "architecture.md" in result
```

- [ ] **Step 1.2 — Verify tests fail**

```bash
cd /workspace/markethawk && python -m pytest dark-factory/tests/test_memory_retrieve.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'memory_retrieve'`

- [ ] **Step 1.3 — Create `dark-factory/scripts/memory_retrieve.py`**

```python
"""
Read-through memory retrieval CLI for Dark Factory agents.

Usage:
    python3 dark-factory/scripts/memory_retrieve.py \
        --phase implement \
        --files "dark-factory/scripts/memory_retrieve.py
dark-factory/tests/test_memory_retrieve.py" \
        [--issue 646] \
        [--labels "Dark Factory,foundation"]

Stdout: markdown memory block (### Memory: <file>\\n- ...) for prompt injection.
Flat-file only — no agentmemory, no HTTP, no vector DB (stdlib only).
"""
import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

PHASE_SOURCE_MAP = {
    "refine": "refine",
    "plan": "refine",
    "implement": "implement",
    "validate": "conformance",
    "review": "code-review",
}

GLOBAL_FILES = {"codebase-patterns.md", "architecture.md"}

_ALL_AREA_FILES = [
    "codebase-patterns.md",
    "architecture.md",
    "backend-patterns.md",
    "frontend-patterns.md",
    "dark-factory-ops.md",
]


def select_area_files(files: list) -> list:
    """Layer 1: return ordered list of memory filenames for the given changed file paths."""
    if not files:
        return list(_ALL_AREA_FILES)
    selected = ["codebase-patterns.md", "architecture.md"]
    if any(f.startswith("backend/") for f in files):
        selected.append("backend-patterns.md")
    if any(f.startswith("frontend/") for f in files):
        selected.append("frontend-patterns.md")
    if any(
        f.startswith("dark-factory/")
        or f.startswith("docker-compose")
        or f.lower().startswith("dockerfile")
        for f in files
    ):
        selected.append("dark-factory-ops.md")
    return selected


def passes_line(line: str, phase: str, affected_files: list, global_file: bool, today: str) -> bool:
    """Layer 2 filter for one markdown entry line."""
    if "[PROVISIONAL]" in line or "[INVALID]" in line:
        return False
    m = re.search(r"expires:(\d{4}-\d{2}-\d{2})", line)
    if m and m.group(1) < today:
        return False
    if not global_file:
        m = re.search(r"source:([^ >]*)", line)
        src = m.group(1) if m else ""
        if src and src != PHASE_SOURCE_MAP[phase]:
            return False
    m = re.search(r"path:([^ >]*)", line)
    if m:
        path_tag = m.group(1)
        if affected_files and not any(f.startswith(path_tag) for f in affected_files):
            return False
    return True


def passes_record(r: dict, phase: str, selected_set: set, affected_files: list, today: str) -> bool:
    """Layer 2 filter for one index.jsonl record."""
    if r.get("status") in ("provisional", "invalid"):
        return False
    if r.get("expires_at") and r["expires_at"] < today:
        return False
    if r.get("scope") not in GLOBAL_FILES:
        if r.get("agent_id") != PHASE_SOURCE_MAP[phase]:
            return False
    path_scope = r.get("path_scope", "")
    if path_scope and affected_files:
        if not any(f.startswith(path_scope) for f in affected_files):
            return False
    return True


def scan_markdown_files(
    selected_files: list, memory_dir: Path, phase: str, affected_files: list, today: str
) -> dict:
    """Fallback path: scan .archon/memory/*.md with two-layer filtering."""
    sections = {}
    for filename in selected_files:
        path = memory_dir / filename
        if not path.exists():
            continue
        global_file = filename in GLOBAL_FILES
        lines = []
        with open(path) as f:
            for raw in f:
                line = raw.rstrip("\n")
                if line.startswith("- ") and passes_line(
                    line, phase, affected_files, global_file, today
                ):
                    lines.append(line)
        if lines:
            sections[filename] = lines
    return sections


def scan_index(
    index_path: Path, selected_files: list, phase: str, affected_files: list, today: str
) -> dict:
    """Primary path: read index.jsonl, apply two-layer filter, rank, return sections."""
    selected_set = set(selected_files)
    with open(index_path) as f:
        records = [json.loads(line) for line in f if line.strip()]
    records = [r for r in records if r.get("scope") in selected_set]
    survivors = [
        r for r in records
        if passes_record(r, phase, selected_set, affected_files, today)
    ]
    # Rank: path specificity (longer prefix = higher) then recency (newer = higher)
    survivors.sort(
        key=lambda r: (
            len(r.get("path_scope", "")),
            r.get("updated_at") or r.get("created_at") or "",
        ),
        reverse=True,
    )
    sections = {}
    for filename in selected_files:
        file_records = [r for r in survivors if r.get("scope") == filename]
        if file_records:
            sections[filename] = [r.get("content", "") for r in file_records]
    return sections


def retrieve_memory(
    selected_files: list, memory_dir: Path, phase: str, affected_files: list, today: str
) -> dict:
    """Dispatch between primary (index.jsonl) and fallback (.md scan) paths."""
    index_path = memory_dir / "index.jsonl"
    if index_path.exists():
        sections = scan_index(index_path, selected_files, phase, affected_files, today)
        if not any(sections.values()):
            sections = scan_markdown_files(selected_files, memory_dir, phase, affected_files, today)
    else:
        sections = scan_markdown_files(selected_files, memory_dir, phase, affected_files, today)
    return sections


def format_output(sections: dict, selected_files: list) -> str:
    """Emit ### Memory: <filename> blocks in selected_files order."""
    parts = []
    for filename in selected_files:
        if not sections.get(filename):
            continue
        parts.append(f"### Memory: {filename}")
        parts.extend(sections[filename])
        parts.append("")
    return "\n".join(parts).strip()


def main():
    parser = argparse.ArgumentParser(
        description="Retrieve role-segregated memory for Dark Factory agents."
    )
    parser.add_argument(
        "--phase", required=True, choices=list(PHASE_SOURCE_MAP),
        help="Workflow phase: drives source filter and area selection",
    )
    parser.add_argument(
        "--files", default="",
        help="Newline-separated list of affected file paths",
    )
    parser.add_argument("--issue", type=int, help="Issue number (informational)")
    parser.add_argument("--labels", default="", help="Comma-separated labels (reserved)")
    args = parser.parse_args()

    affected_files = [f for f in args.files.splitlines() if f.strip()]
    today = date.today().isoformat()
    repo_root = Path(__file__).resolve().parents[2]
    memory_dir = repo_root / ".archon" / "memory"
    selected_files = select_area_files(affected_files)
    sections = retrieve_memory(selected_files, memory_dir, args.phase, affected_files, today)
    output = format_output(sections, selected_files)
    if output:
        print(output)


if __name__ == "__main__":
    main()
```

- [ ] **Step 1.4 — Verify Task 1 tests pass**

```bash
cd /workspace/markethawk && python -m pytest dark-factory/tests/test_memory_retrieve.py::TestConstants dark-factory/tests/test_memory_retrieve.py::TestSelectAreaFiles -v
```

Expected:
```
PASSED TestConstants::test_phase_source_map_all_phases
PASSED TestConstants::test_global_files_contains_shared_files
PASSED TestSelectAreaFiles::test_empty_files_returns_all_five
... (10 tests total, all PASSED)
```

- [ ] **Step 1.5 — Commit**

```bash
git add dark-factory/scripts/memory_retrieve.py dark-factory/tests/test_memory_retrieve.py
git commit -m "feat(#646): add memory_retrieve.py with constants, area selection, and full implementation skeleton"
```

---

## Task 2 — Layer 2 entry filters (TDD)

**Files:** `dark-factory/tests/test_memory_retrieve.py` (ADD test classes), `dark-factory/scripts/memory_retrieve.py` (already has implementations — verify coverage)

### Interfaces tested
- `passes_line(line, phase, affected_files, global_file, today) -> bool`
- `passes_record(r, phase, selected_set, affected_files, today) -> bool`

---

- [ ] **Step 2.1 — Add failing tests to `test_memory_retrieve.py`**

Append to `dark-factory/tests/test_memory_retrieve.py`:

```python

class TestPassesLine:
    """Layer 2 filter for the markdown fallback path."""

    TODAY = "2026-06-29"

    def test_normal_line_passes(self):
        line = "- [PATTERN] something <!-- source:implement -->"
        assert mr.passes_line(line, "implement", [], False, self.TODAY) is True

    def test_excludes_provisional(self):
        line = "- [PROVISIONAL] entry <!-- source:implement -->"
        assert mr.passes_line(line, "implement", [], False, self.TODAY) is False

    def test_excludes_invalid(self):
        line = "- [INVALID: superseded] entry <!-- source:implement -->"
        assert mr.passes_line(line, "implement", [], False, self.TODAY) is False

    def test_excludes_expired(self):
        line = "- [PATTERN] old <!-- source:implement expires:2026-01-01 -->"
        assert mr.passes_line(line, "implement", [], False, self.TODAY) is False

    def test_includes_future_expiry(self):
        line = "- [PATTERN] fresh <!-- source:implement expires:2026-12-31 -->"
        assert mr.passes_line(line, "implement", [], False, self.TODAY) is True

    def test_source_filter_matching_phase(self):
        line = "- [PATTERN] entry <!-- source:implement -->"
        assert mr.passes_line(line, "implement", [], False, self.TODAY) is True

    def test_source_filter_non_matching_phase(self):
        line = "- [PATTERN] entry <!-- source:refine -->"
        assert mr.passes_line(line, "implement", [], False, self.TODAY) is False

    def test_no_source_tag_passes_unconditionally(self):
        """Backward-compat: entries without source tag are unscoped and always pass."""
        line = "- [PATTERN] entry without source"
        assert mr.passes_line(line, "implement", [], False, self.TODAY) is True

    def test_global_file_exempt_from_source_filter(self):
        """global_file=True: source filter skipped regardless of source value."""
        line = "- [PATTERN] entry <!-- source:refine -->"
        assert mr.passes_line(line, "implement", [], True, self.TODAY) is True

    def test_path_tag_matches_affected_file(self):
        line = "- [PATTERN] entry <!-- source:implement path:backend/app/services/ -->"
        assert mr.passes_line(
            line, "implement", ["backend/app/services/scanner.py"], False, self.TODAY
        ) is True

    def test_path_tag_no_match_excluded(self):
        line = "- [PATTERN] entry <!-- source:implement path:frontend/ -->"
        assert mr.passes_line(
            line, "implement", ["backend/app/services/scanner.py"], False, self.TODAY
        ) is False

    def test_path_tag_empty_affected_files_passes(self):
        """Empty affected_files = include-all fallback; path-tagged entries pass."""
        line = "- [PATTERN] entry <!-- source:implement path:backend/ -->"
        assert mr.passes_line(line, "implement", [], False, self.TODAY) is True

    def test_no_path_tag_always_passes(self):
        line = "- [PATTERN] global lesson <!-- source:implement -->"
        assert mr.passes_line(
            line, "implement", ["frontend/src/foo.tsx"], False, self.TODAY
        ) is True

    def test_plan_phase_uses_refine_source(self):
        """plan phase maps to source:refine."""
        line = "- [PATTERN] design decision <!-- source:refine -->"
        assert mr.passes_line(line, "plan", [], False, self.TODAY) is True

    def test_validate_phase_uses_conformance_source(self):
        line = "- [AVOID] deviation pattern <!-- source:conformance -->"
        assert mr.passes_line(line, "validate", [], False, self.TODAY) is True

    def test_review_phase_uses_code_review_source(self):
        line = "- [AVOID] security issue <!-- source:code-review -->"
        assert mr.passes_line(line, "review", [], False, self.TODAY) is True


class TestPassesRecord:
    """Layer 2 filter for the index.jsonl primary path."""

    TODAY = "2026-06-29"
    SELECTED = {"codebase-patterns.md", "architecture.md", "dark-factory-ops.md"}

    def _r(self, **kwargs):
        base = {
            "id": "abc",
            "type": "pattern",
            "status": "active",
            "scope": "dark-factory-ops.md",
            "agent_id": "implement",
            "path_scope": "",
            "content": "- [PATTERN] something",
            "expires_at": None,
            "created_at": "2026-06-15",
        }
        base.update(kwargs)
        return base

    def test_active_record_passes(self):
        assert mr.passes_record(self._r(), "implement", self.SELECTED, [], self.TODAY) is True

    def test_provisional_status_excluded(self):
        assert mr.passes_record(self._r(status="provisional"), "implement", self.SELECTED, [], self.TODAY) is False

    def test_invalid_status_excluded(self):
        assert mr.passes_record(self._r(status="invalid"), "implement", self.SELECTED, [], self.TODAY) is False

    def test_expired_excluded(self):
        assert mr.passes_record(self._r(expires_at="2026-01-01"), "implement", self.SELECTED, [], self.TODAY) is False

    def test_future_expiry_passes(self):
        assert mr.passes_record(self._r(expires_at="2026-12-31"), "implement", self.SELECTED, [], self.TODAY) is True

    def test_null_expiry_passes(self):
        assert mr.passes_record(self._r(expires_at=None), "implement", self.SELECTED, [], self.TODAY) is True

    def test_agent_id_matching_phase(self):
        assert mr.passes_record(self._r(agent_id="implement"), "implement", self.SELECTED, [], self.TODAY) is True

    def test_agent_id_non_matching_phase(self):
        assert mr.passes_record(self._r(agent_id="refine"), "implement", self.SELECTED, [], self.TODAY) is False

    def test_global_file_exempt_from_agent_id(self):
        r = self._r(scope="codebase-patterns.md", agent_id="refine")
        assert mr.passes_record(r, "implement", self.SELECTED, [], self.TODAY) is True

    def test_architecture_md_global_exempt(self):
        r = self._r(scope="architecture.md", agent_id="code-review")
        assert mr.passes_record(r, "implement", self.SELECTED, [], self.TODAY) is True

    def test_path_scope_match(self):
        r = self._r(path_scope="dark-factory/scripts/")
        files = ["dark-factory/scripts/memory_retrieve.py"]
        assert mr.passes_record(r, "implement", self.SELECTED, files, self.TODAY) is True

    def test_path_scope_no_match(self):
        r = self._r(path_scope="frontend/")
        files = ["dark-factory/scripts/memory_retrieve.py"]
        assert mr.passes_record(r, "implement", self.SELECTED, files, self.TODAY) is False

    def test_path_scope_empty_affected_passes(self):
        r = self._r(path_scope="dark-factory/")
        assert mr.passes_record(r, "implement", self.SELECTED, [], self.TODAY) is True

    def test_empty_path_scope_always_passes(self):
        r = self._r(path_scope="")
        assert mr.passes_record(r, "implement", self.SELECTED, ["backend/app/foo.py"], self.TODAY) is True
```

- [ ] **Step 2.2 — Verify new tests pass** (implementation is already in the file from Task 1)

```bash
cd /workspace/markethawk && python -m pytest dark-factory/tests/test_memory_retrieve.py::TestPassesLine dark-factory/tests/test_memory_retrieve.py::TestPassesRecord -v
```

Expected: all 30 tests pass.

- [ ] **Step 2.3 — Run the full suite to confirm no regressions**

```bash
cd /workspace/markethawk && python -m pytest dark-factory/tests/test_memory_retrieve.py -v
```

- [ ] **Step 2.4 — Commit**

```bash
git add dark-factory/tests/test_memory_retrieve.py
git commit -m "test(#646): add Layer 2 filter coverage for passes_line and passes_record"
```

---

## Task 3 — Fallback path and output formatter (TDD)

**Files:** `dark-factory/tests/test_memory_retrieve.py` (ADD test classes)

### Interfaces tested
- `scan_markdown_files(selected_files, memory_dir, phase, affected_files, today) -> dict`
- `format_output(sections, selected_files) -> str`

---

- [ ] **Step 3.1 — Add tests to `test_memory_retrieve.py`**

Append:

```python

import io
from unittest.mock import patch, mock_open


_CODEBASE_MD = """\
# Codebase Patterns

- [PATTERN] Global pattern without source tag
- [PATTERN] Impl pattern <!-- source:implement -->
- [PROVISIONAL] Unverified <!-- source:implement -->
- [PATTERN] Refine-only pattern <!-- source:refine -->
- [PATTERN] Backend-scoped <!-- source:implement path:backend/ -->
- [PATTERN] Expired entry <!-- source:implement expires:2026-01-01 -->
"""

_DF_OPS_MD = """\
# Dark Factory Ops

- [PATTERN] DF ops pattern <!-- source:implement -->
- [AVOID] Refine-only DF entry <!-- source:refine -->
"""


class TestScanMarkdownFiles:
    TODAY = "2026-06-29"

    def _fake_open(self, files_data):
        def _open(p, *a, **kw):
            name = Path(p).name
            if name in files_data:
                return io.StringIO(files_data[name])
            raise FileNotFoundError(name)
        return _open

    def _fake_exists(self, files_data):
        def _exists(self_path):
            return self_path.name in files_data
        return _exists

    def test_reads_global_files_and_filters(self):
        data = {"codebase-patterns.md": _CODEBASE_MD}
        selected = ["codebase-patterns.md"]
        memory_dir = Path("/fake/.archon/memory")

        with patch("builtins.open", side_effect=self._fake_open(data)):
            with patch.object(Path, "exists", self._fake_exists(data)):
                sections = mr.scan_markdown_files(
                    selected, memory_dir, "implement", [], self.TODAY
                )

        lines = sections.get("codebase-patterns.md", [])
        assert any("Global pattern" in l for l in lines)
        assert any("Impl pattern" in l for l in lines)
        assert not any("[PROVISIONAL]" in l for l in lines)
        assert not any("Expired entry" in l for l in lines)

    def test_global_file_exempt_from_source_filter(self):
        """Entries in codebase-patterns.md pass even with source:refine for implement phase."""
        data = {"codebase-patterns.md": _CODEBASE_MD}
        selected = ["codebase-patterns.md"]
        memory_dir = Path("/fake/.archon/memory")

        with patch("builtins.open", side_effect=self._fake_open(data)):
            with patch.object(Path, "exists", self._fake_exists(data)):
                sections = mr.scan_markdown_files(
                    selected, memory_dir, "implement", [], self.TODAY
                )

        lines = sections.get("codebase-patterns.md", [])
        assert any("Refine-only pattern" in l for l in lines)

    def test_area_specific_file_applies_source_filter(self):
        """dark-factory-ops.md: source:refine entries excluded for implement phase."""
        data = {"dark-factory-ops.md": _DF_OPS_MD}
        selected = ["dark-factory-ops.md"]
        memory_dir = Path("/fake/.archon/memory")

        with patch("builtins.open", side_effect=self._fake_open(data)):
            with patch.object(Path, "exists", self._fake_exists(data)):
                sections = mr.scan_markdown_files(
                    selected, memory_dir, "implement", [], self.TODAY
                )

        lines = sections.get("dark-factory-ops.md", [])
        assert any("DF ops pattern" in l for l in lines)
        assert not any("Refine-only DF entry" in l for l in lines)

    def test_path_tag_filter_applied(self):
        md = (
            "- [PATTERN] Backend-scoped <!-- source:implement path:backend/ -->\n"
            "- [PATTERN] No path tag <!-- source:implement -->\n"
        )
        data = {"codebase-patterns.md": md}
        selected = ["codebase-patterns.md"]
        memory_dir = Path("/fake/.archon/memory")

        with patch("builtins.open", side_effect=self._fake_open(data)):
            with patch.object(Path, "exists", self._fake_exists(data)):
                sections = mr.scan_markdown_files(
                    selected, memory_dir, "implement",
                    ["frontend/src/foo.tsx"], self.TODAY
                )

        lines = sections.get("codebase-patterns.md", [])
        assert not any("Backend-scoped" in l for l in lines)
        assert any("No path tag" in l for l in lines)

    def test_missing_file_silently_skipped(self):
        data = {"codebase-patterns.md": "- [PATTERN] exists\n"}
        selected = ["codebase-patterns.md", "backend-patterns.md"]
        memory_dir = Path("/fake/.archon/memory")

        with patch("builtins.open", side_effect=self._fake_open(data)):
            with patch.object(Path, "exists", self._fake_exists(data)):
                sections = mr.scan_markdown_files(
                    selected, memory_dir, "implement", [], self.TODAY
                )

        assert "codebase-patterns.md" in sections
        assert "backend-patterns.md" not in sections

    def test_empty_file_omitted_from_sections(self):
        data = {"codebase-patterns.md": "", "architecture.md": "- [PATTERN] real\n"}
        selected = ["codebase-patterns.md", "architecture.md"]
        memory_dir = Path("/fake/.archon/memory")

        with patch("builtins.open", side_effect=self._fake_open(data)):
            with patch.object(Path, "exists", self._fake_exists(data)):
                sections = mr.scan_markdown_files(
                    selected, memory_dir, "implement", [], self.TODAY
                )

        assert "codebase-patterns.md" not in sections
        assert "architecture.md" in sections

    def test_all_entries_filtered_omits_section(self):
        md = "- [PROVISIONAL] only provisional entry\n"
        data = {"codebase-patterns.md": md}
        selected = ["codebase-patterns.md"]
        memory_dir = Path("/fake/.archon/memory")

        with patch("builtins.open", side_effect=self._fake_open(data)):
            with patch.object(Path, "exists", self._fake_exists(data)):
                sections = mr.scan_markdown_files(
                    selected, memory_dir, "implement", [], self.TODAY
                )

        assert "codebase-patterns.md" not in sections


class TestFormatOutput:
    def test_basic_output_format(self):
        sections = {
            "codebase-patterns.md": ["- [PATTERN] foo", "- [AVOID] bar"],
            "architecture.md": ["- [PATTERN] baz"],
        }
        selected = ["codebase-patterns.md", "architecture.md"]
        result = mr.format_output(sections, selected)
        assert "### Memory: codebase-patterns.md" in result
        assert "- [PATTERN] foo" in result
        assert "- [AVOID] bar" in result
        assert "### Memory: architecture.md" in result
        assert "- [PATTERN] baz" in result

    def test_empty_section_omitted(self):
        sections = {"codebase-patterns.md": ["- [PATTERN] yes"], "architecture.md": []}
        selected = ["codebase-patterns.md", "architecture.md"]
        result = mr.format_output(sections, selected)
        assert "### Memory: codebase-patterns.md" in result
        assert "### Memory: architecture.md" not in result

    def test_section_order_follows_selected_files(self):
        sections = {
            "codebase-patterns.md": ["- [PATTERN] first"],
            "architecture.md": ["- [PATTERN] second"],
        }
        selected = ["codebase-patterns.md", "architecture.md"]
        result = mr.format_output(sections, selected)
        assert result.index("codebase-patterns.md") < result.index("architecture.md")

    def test_no_survivors_returns_empty_string(self):
        assert mr.format_output({}, ["codebase-patterns.md"]) == ""

    def test_blank_line_between_sections(self):
        sections = {
            "codebase-patterns.md": ["- [PATTERN] a"],
            "architecture.md": ["- [PATTERN] b"],
        }
        selected = ["codebase-patterns.md", "architecture.md"]
        result = mr.format_output(sections, selected)
        # There should be a blank line between the two sections
        assert "\n\n" in result
```

- [ ] **Step 3.2 — Verify new tests pass**

```bash
cd /workspace/markethawk && python -m pytest dark-factory/tests/test_memory_retrieve.py::TestScanMarkdownFiles dark-factory/tests/test_memory_retrieve.py::TestFormatOutput -v
```

Expected: all 12 tests pass.

- [ ] **Step 3.3 — Run the full suite**

```bash
cd /workspace/markethawk && python -m pytest dark-factory/tests/test_memory_retrieve.py -v
```

Expected: all tests pass.

- [ ] **Step 3.4 — Commit**

```bash
git add dark-factory/tests/test_memory_retrieve.py
git commit -m "test(#646): add coverage for scan_markdown_files fallback path and format_output"
```

---

## Task 4 — Primary path (index.jsonl) with ranking (TDD)

**Files:** `dark-factory/tests/test_memory_retrieve.py` (ADD test class)

### Interfaces tested
- `scan_index(index_path, selected_files, phase, affected_files, today) -> dict`

---

- [ ] **Step 4.1 — Add tests to `test_memory_retrieve.py`**

Append:

```python

import json as _json


class TestScanIndex:
    TODAY = "2026-06-29"
    SELECTED = ["codebase-patterns.md", "dark-factory-ops.md"]

    def _index(self, *records):
        return "\n".join(_json.dumps(r) for r in records) + "\n"

    def _r(self, **kwargs):
        base = {
            "id": "r1",
            "type": "pattern",
            "status": "active",
            "scope": "dark-factory-ops.md",
            "agent_id": "implement",
            "path_scope": "",
            "content": "- [PATTERN] base content",
            "expires_at": None,
            "created_at": "2026-06-15",
        }
        base.update(kwargs)
        return base

    def test_basic_filter_keeps_active(self):
        records = [
            self._r(id="r1", content="- [PATTERN] keep"),
            self._r(id="r2", status="provisional", content="- [PROVISIONAL] drop"),
        ]
        idx_path = Path("/fake/index.jsonl")
        with patch("builtins.open", mock_open(read_data=self._index(*records))):
            sections = mr.scan_index(idx_path, self.SELECTED, "implement", [], self.TODAY)
        df = sections.get("dark-factory-ops.md", [])
        assert any("keep" in l for l in df)
        assert not any("drop" in l for l in df)

    def test_excludes_non_selected_scope(self):
        records = [self._r(scope="backend-patterns.md")]
        idx_path = Path("/fake/index.jsonl")
        with patch("builtins.open", mock_open(read_data=self._index(*records))):
            sections = mr.scan_index(idx_path, self.SELECTED, "implement", [], self.TODAY)
        assert "backend-patterns.md" not in sections

    def test_agent_id_phase_filter(self):
        records = [
            self._r(id="r1", agent_id="implement", content="- [PATTERN] for implement"),
            self._r(id="r2", agent_id="refine", content="- [PATTERN] for refine"),
        ]
        idx_path = Path("/fake/index.jsonl")
        with patch("builtins.open", mock_open(read_data=self._index(*records))):
            sections = mr.scan_index(idx_path, self.SELECTED, "implement", [], self.TODAY)
        df = sections.get("dark-factory-ops.md", [])
        assert any("for implement" in l for l in df)
        assert not any("for refine" in l for l in df)

    def test_global_file_exempt_from_agent_id(self):
        records = [self._r(
            scope="codebase-patterns.md", agent_id="refine",
            content="- [PATTERN] global passes"
        )]
        idx_path = Path("/fake/index.jsonl")
        with patch("builtins.open", mock_open(read_data=self._index(*records))):
            sections = mr.scan_index(idx_path, self.SELECTED, "implement", [], self.TODAY)
        lines = sections.get("codebase-patterns.md", [])
        assert any("global passes" in l for l in lines)

    def test_expiry_filter(self):
        records = [
            self._r(id="r1", expires_at="2026-01-01", content="- [PATTERN] expired"),
            self._r(id="r2", expires_at="2026-12-31", content="- [PATTERN] valid"),
        ]
        idx_path = Path("/fake/index.jsonl")
        with patch("builtins.open", mock_open(read_data=self._index(*records))):
            sections = mr.scan_index(idx_path, self.SELECTED, "implement", [], self.TODAY)
        df = sections.get("dark-factory-ops.md", [])
        assert not any("expired" in l for l in df)
        assert any("valid" in l for l in df)

    def test_path_scope_filter(self):
        records = [
            self._r(path_scope="frontend/", content="- [PATTERN] frontend only"),
            self._r(path_scope="", content="- [PATTERN] unrestricted"),
        ]
        idx_path = Path("/fake/index.jsonl")
        files = ["dark-factory/scripts/foo.py"]
        with patch("builtins.open", mock_open(read_data=self._index(*records))):
            sections = mr.scan_index(idx_path, self.SELECTED, "implement", files, self.TODAY)
        df = sections.get("dark-factory-ops.md", [])
        assert not any("frontend only" in l for l in df)
        assert any("unrestricted" in l for l in df)

    def test_ranking_path_specificity(self):
        """Deeper path_scope ranks before shallower."""
        records = [
            self._r(id="r1", path_scope="dark-factory/", content="- [PATTERN] shallow"),
            self._r(id="r2", path_scope="dark-factory/scripts/", content="- [PATTERN] deep"),
        ]
        idx_path = Path("/fake/index.jsonl")
        files = ["dark-factory/scripts/memory_retrieve.py"]
        with patch("builtins.open", mock_open(read_data=self._index(*records))):
            sections = mr.scan_index(idx_path, self.SELECTED, "implement", files, self.TODAY)
        df = sections.get("dark-factory-ops.md", [])
        deep_i = next(i for i, l in enumerate(df) if "deep" in l)
        shallow_i = next(i for i, l in enumerate(df) if "shallow" in l)
        assert deep_i < shallow_i

    def test_ranking_recency_tiebreaker(self):
        """Same path_scope length: newer created_at ranks first."""
        records = [
            self._r(id="r1", path_scope="", created_at="2026-01-01", content="- [PATTERN] older"),
            self._r(id="r2", path_scope="", created_at="2026-06-15", content="- [PATTERN] newer"),
        ]
        idx_path = Path("/fake/index.jsonl")
        with patch("builtins.open", mock_open(read_data=self._index(*records))):
            sections = mr.scan_index(idx_path, self.SELECTED, "implement", [], self.TODAY)
        df = sections.get("dark-factory-ops.md", [])
        newer_i = next(i for i, l in enumerate(df) if "newer" in l)
        older_i = next(i for i, l in enumerate(df) if "older" in l)
        assert newer_i < older_i

    def test_sections_preserve_selected_file_order(self):
        """Sections dict keys follow selected_files order, not insertion order."""
        records = [
            self._r(scope="dark-factory-ops.md", content="- [PATTERN] ops"),
            self._r(scope="codebase-patterns.md", agent_id="refine", content="- [PATTERN] global"),
        ]
        idx_path = Path("/fake/index.jsonl")
        with patch("builtins.open", mock_open(read_data=self._index(*records))):
            sections = mr.scan_index(idx_path, self.SELECTED, "implement", [], self.TODAY)
        keys = list(sections.keys())
        # codebase-patterns.md appears first in SELECTED
        if "codebase-patterns.md" in keys and "dark-factory-ops.md" in keys:
            assert keys.index("codebase-patterns.md") < keys.index("dark-factory-ops.md")

    def test_empty_index_returns_empty_sections(self):
        idx_path = Path("/fake/index.jsonl")
        with patch("builtins.open", mock_open(read_data="")):
            sections = mr.scan_index(idx_path, self.SELECTED, "implement", [], self.TODAY)
        assert sections == {}
```

- [ ] **Step 4.2 — Verify new tests pass**

```bash
cd /workspace/markethawk && python -m pytest dark-factory/tests/test_memory_retrieve.py::TestScanIndex -v
```

Expected: all 10 tests pass.

- [ ] **Step 4.3 — Run full suite**

```bash
cd /workspace/markethawk && python -m pytest dark-factory/tests/test_memory_retrieve.py -v
```

Expected: all tests pass.

- [ ] **Step 4.4 — Commit**

```bash
git add dark-factory/tests/test_memory_retrieve.py
git commit -m "test(#646): add coverage for scan_index primary path with path-specificity ranking"
```

---

## Task 5 — Dispatch, integration, and smoke test (TDD)

**Files:** `dark-factory/tests/test_memory_retrieve.py` (ADD test classes), `dark-factory/scripts/memory_retrieve.py` (chmod + verify)

### Interfaces tested
- `retrieve_memory(selected_files, memory_dir, phase, affected_files, today) -> dict`
- `main()` via subprocess

---

- [ ] **Step 5.1 — Add tests to `test_memory_retrieve.py`**

Append:

```python

import subprocess


class TestRetrieveMemory:
    """Unit tests for the index-present vs index-absent dispatch logic."""

    TODAY = "2026-06-29"

    def test_uses_scan_index_when_index_present(self, tmp_path, monkeypatch):
        (tmp_path / "index.jsonl").write_text("")  # present but empty

        scan_index_calls = []
        scan_md_calls = []

        def fake_scan_index(*a, **kw):
            scan_index_calls.append(1)
            return {}

        def fake_scan_md(*a, **kw):
            scan_md_calls.append(1)
            return {}

        monkeypatch.setattr(mr, "scan_index", fake_scan_index)
        monkeypatch.setattr(mr, "scan_markdown_files", fake_scan_md)

        mr.retrieve_memory(["codebase-patterns.md"], tmp_path, "implement", [], self.TODAY)

        assert len(scan_index_calls) == 1
        # index present but empty → fallback triggered
        assert len(scan_md_calls) == 1

    def test_uses_fallback_when_index_absent(self, tmp_path, monkeypatch):
        scan_index_calls = []
        scan_md_calls = []

        monkeypatch.setattr(mr, "scan_index", lambda *a, **kw: scan_index_calls.append(1) or {})
        monkeypatch.setattr(mr, "scan_markdown_files", lambda *a, **kw: scan_md_calls.append(1) or {})

        mr.retrieve_memory(["codebase-patterns.md"], tmp_path, "implement", [], self.TODAY)

        assert len(scan_index_calls) == 0
        assert len(scan_md_calls) == 1

    def test_no_fallback_when_index_has_survivors(self, tmp_path, monkeypatch):
        (tmp_path / "index.jsonl").write_text("")

        scan_md_calls = []

        monkeypatch.setattr(mr, "scan_index", lambda *a, **kw: {"codebase-patterns.md": ["- [PATTERN] x"]})
        monkeypatch.setattr(mr, "scan_markdown_files", lambda *a, **kw: scan_md_calls.append(1) or {})

        sections = mr.retrieve_memory(["codebase-patterns.md"], tmp_path, "implement", [], self.TODAY)

        assert len(scan_md_calls) == 0
        assert "codebase-patterns.md" in sections


class TestMainCLI:
    """Subprocess integration tests for main()."""

    SCRIPT = str(Path(__file__).resolve().parents[1] / "scripts" / "memory_retrieve.py")

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, self.SCRIPT] + list(args),
            capture_output=True, text=True,
        )

    def test_phase_required(self):
        result = self._run("--files", "")
        assert result.returncode != 0

    def test_invalid_phase_rejected(self):
        result = self._run("--phase", "deploy")
        assert result.returncode != 0

    def test_implement_phase_exits_zero(self):
        result = self._run("--phase", "implement", "--files",
                           "dark-factory/scripts/memory_retrieve.py")
        assert result.returncode == 0

    def test_plan_phase_exits_zero(self):
        result = self._run("--phase", "plan", "--files",
                           "dark-factory/scripts/memory_retrieve.py")
        assert result.returncode == 0

    def test_output_has_memory_heading_or_is_empty(self):
        result = self._run("--phase", "implement", "--files",
                           "dark-factory/scripts/memory_retrieve.py")
        assert result.returncode == 0
        if result.stdout.strip():
            assert "### Memory:" in result.stdout

    def test_with_issue_flag(self):
        result = self._run("--phase", "implement", "--issue", "646", "--files", "")
        assert result.returncode == 0

    def test_empty_files_loads_all_areas(self):
        """--files '' → all five area files loaded → no crash."""
        result = self._run("--phase", "implement", "--files", "")
        assert result.returncode == 0

    def test_no_stderr_on_clean_run(self):
        result = self._run("--phase", "implement", "--files",
                           "dark-factory/scripts/memory_retrieve.py")
        assert result.returncode == 0
        assert result.stderr == ""
```

- [ ] **Step 5.2 — Verify new tests pass**

```bash
cd /workspace/markethawk && python -m pytest dark-factory/tests/test_memory_retrieve.py::TestRetrieveMemory dark-factory/tests/test_memory_retrieve.py::TestMainCLI -v
```

Expected: all 11 tests pass.

- [ ] **Step 5.3 — Run full suite**

```bash
cd /workspace/markethawk && python -m pytest dark-factory/tests/test_memory_retrieve.py -v
```

Expected: all tests pass.

- [ ] **Step 5.4 — Make script executable**

```bash
chmod +x /workspace/markethawk/dark-factory/scripts/memory_retrieve.py
```

- [ ] **Step 5.5 — Smoke-test with real memory files**

```bash
cd /workspace/markethawk && python3 dark-factory/scripts/memory_retrieve.py \
  --phase implement \
  --files "dark-factory/scripts/memory_retrieve.py
dark-factory/tests/test_memory_retrieve.py" \
  --issue 646
```

Expected: output with `### Memory: codebase-patterns.md`, `### Memory: architecture.md`, and `### Memory: dark-factory-ops.md` sections (if matching entries exist), or empty output (if all entries are filtered). No error output.

- [ ] **Step 5.6 — Smoke-test plan phase (source:refine filter)**

```bash
cd /workspace/markethawk && python3 dark-factory/scripts/memory_retrieve.py \
  --phase plan \
  --files "dark-factory/scripts/memory_retrieve.py"
```

- [ ] **Step 5.7 — Smoke-test empty --files (should load all five area files)**

```bash
cd /workspace/markethawk && python3 dark-factory/scripts/memory_retrieve.py \
  --phase implement \
  --files ""
```

- [ ] **Step 5.8 — Commit**

```bash
git add dark-factory/tests/test_memory_retrieve.py dark-factory/scripts/memory_retrieve.py
git commit -m "test(#646): add dispatch and CLI integration coverage; make script executable"
```

---

## Summary

| Task | Files | Tests added |
|------|-------|-------------|
| 1 — Skeleton, constants, area selection | `memory_retrieve.py` (all functions), `test_memory_retrieve.py` | TestConstants (2), TestSelectAreaFiles (10) |
| 2 — Layer 2 filter tests | `test_memory_retrieve.py` | TestPassesLine (16), TestPassesRecord (14) |
| 3 — Fallback path + output formatter tests | `test_memory_retrieve.py` | TestScanMarkdownFiles (7), TestFormatOutput (5) |
| 4 — Primary path (index.jsonl) tests | `test_memory_retrieve.py` | TestScanIndex (10) |
| 5 — Dispatch + CLI integration tests | `test_memory_retrieve.py` | TestRetrieveMemory (3), TestMainCLI (8) |

**Total: ~75 test cases** across 8 test classes. All spec requirements are covered: index-present path, index-absent path, two-layer filtering (status, source/agent_id, path-tag, expiry), area selection, global-file exemption, ranking by path specificity and recency, empty-`--files` fallback, PROVISIONAL/INVALID exclusion.
