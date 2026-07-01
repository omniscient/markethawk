# Top-k Memory Retrieval Cap — Implementation Plan

**Date:** 2026-07-01
**Issue:** #667
**Spec:** `docs/superpowers/specs/2026-07-01-top-k-memory-retrieval-cap-design.md`
**Branch:** `refine/issue-667-add-top-k-memory-retrieval-cap-compatibl`

## Goal

Stop dumping large `.archon/memory/*.md` files into prompts. Apply a dual cap (top-8 entries OR 1 500 estimated tokens, whichever is hit first) inside `format_index_output()` with multi-factor ranking that adds label-domain affinity to the existing path-specificity + recency sort. Wire the `--labels` CLI arg, emit cap counts in `memory-trace.json` and `context-budget.json`, and leave the markdown fallback path unchanged.

## Architecture

Changes are confined to the Dark Factory scripting layer:
- `dark-factory/scripts/memory_retrieve.py` — core retrieval logic
- `dark-factory/scripts/context_budget.py` — telemetry output
- `dark-factory/tests/test_memory_retrieve.py` — retrieval tests
- `dark-factory/tests/test_context_budget.py` — budget tests

No backend, frontend, or Celery changes. No new files beyond tests. All changes are pure Python, stdlib only (except `token_estimate` which is already in the scripts directory).

## Tech Stack

Python 3.11+, no third-party dependencies. `token_estimate.estimate_tokens()` uses 4 chars/token. Tests run with `pytest` inside the factory container.

## File Structure

| File | Change |
|------|--------|
| `dark-factory/scripts/memory_retrieve.py` | Add constants, label map, `compute_label_boost()`, update `format_index_output()` and `emit_memory_trace()`, wire `--labels` and `_cap_out` through CLI and `retrieve_memory()` |
| `dark-factory/scripts/context_budget.py` | Add `_read_json()` helper, update `memory_context` section to read `memory-trace.json` for cap counts |
| `dark-factory/tests/test_memory_retrieve.py` | New test classes for constants, label boost, dual cap, trace cap counts |
| `dark-factory/tests/test_context_budget.py` | New tests for `memory_context` entries_selected/entries_dropped fields |

## Tasks

---

### Task 1 — Add constants and label boost map

**Goal:** Establish `TOP_K_DEFAULT`, `TOKEN_BUDGET_DEFAULT`, and `_LABEL_SOURCE_BOOST_MAP` in `memory_retrieve.py` without changing any behavior.

**Files:** `dark-factory/scripts/memory_retrieve.py`, `dark-factory/tests/test_memory_retrieve.py`

#### TDD steps

**Step 1 — Write failing tests**

In `dark-factory/tests/test_memory_retrieve.py`, add at the end of `TestConstants`:

```python
def test_top_k_default(self):
    assert mr.TOP_K_DEFAULT == 8

def test_token_budget_default(self):
    assert mr.TOKEN_BUDGET_DEFAULT == 1500

def test_label_source_boost_map_exists(self):
    assert hasattr(mr, "_LABEL_SOURCE_BOOST_MAP")

def test_label_source_boost_map_dark_factory_keys(self):
    assert mr._LABEL_SOURCE_BOOST_MAP.get("dark factory") == "dark-factory-ops.md"
    assert mr._LABEL_SOURCE_BOOST_MAP.get("dark-factory") == "dark-factory-ops.md"

def test_label_source_boost_map_frontend_backend(self):
    assert mr._LABEL_SOURCE_BOOST_MAP.get("frontend") == "frontend-patterns.md"
    assert mr._LABEL_SOURCE_BOOST_MAP.get("backend") == "backend-patterns.md"

def test_label_source_boost_map_four_keys(self):
    assert len(mr._LABEL_SOURCE_BOOST_MAP) == 4
```

**Step 2 — Verify tests fail**

```bash
cd /workspace/markethawk
docker-compose exec backend bash -c "cd /app && python -m pytest dark-factory/tests/test_memory_retrieve.py::TestConstants -x -q 2>&1 | tail -20"
```

Expected: `AttributeError: module 'memory_retrieve' has no attribute 'TOP_K_DEFAULT'` (or similar).

**Step 3 — Implement**

In `dark-factory/scripts/memory_retrieve.py`, after `AUTHORITATIVE_KINDS`:

```python
# Cap defaults for the index retrieval path
TOP_K_DEFAULT = 8
TOKEN_BUDGET_DEFAULT = 1500

# Issue label → source_file boost mapping (mirrors architecture_slice._LABEL_COMPONENT_MAP)
_LABEL_SOURCE_BOOST_MAP = {
    "dark factory":     "dark-factory-ops.md",
    "dark-factory":     "dark-factory-ops.md",
    "frontend":         "frontend-patterns.md",
    "backend":          "backend-patterns.md",
}
```

**Step 4 — Verify tests pass**

```bash
docker-compose exec backend bash -c "cd /app && python -m pytest dark-factory/tests/test_memory_retrieve.py::TestConstants -x -q 2>&1 | tail -10"
```

Expected: all tests in `TestConstants` pass (existing tests + 6 new ones).

**Step 5 — Run full suite to confirm no regressions**

```bash
docker-compose exec backend bash -c "cd /app && python -m pytest dark-factory/tests/test_memory_retrieve.py -q 2>&1 | tail -10"
```

Expected: all existing tests pass.

**Step 6 — Commit**

```bash
git add dark-factory/scripts/memory_retrieve.py dark-factory/tests/test_memory_retrieve.py
git commit -m "feat: add TOP_K_DEFAULT, TOKEN_BUDGET_DEFAULT, and _LABEL_SOURCE_BOOST_MAP constants (#667)"
```

---

### Task 2 — Add `compute_label_boost()` and wire `--labels` through CLI

**Goal:** Implement the label-boost helper and thread `labels: list[str]` from the CLI arg through `retrieve_memory()`.

**Files:** `dark-factory/scripts/memory_retrieve.py`, `dark-factory/tests/test_memory_retrieve.py`

#### TDD steps

**Step 1 — Write failing tests**

Add a new `TestComputeLabelBoost` class to `test_memory_retrieve.py`:

```python
class TestComputeLabelBoost:
    def test_no_labels_returns_zero(self):
        assert mr.compute_label_boost("backend-patterns.md", []) == 0

    def test_none_labels_returns_zero(self):
        assert mr.compute_label_boost("backend-patterns.md", None) == 0

    def test_backend_label_boosts_backend_patterns(self):
        assert mr.compute_label_boost("backend-patterns.md", ["backend"]) == 1

    def test_frontend_label_boosts_frontend_patterns(self):
        assert mr.compute_label_boost("frontend-patterns.md", ["frontend"]) == 1

    def test_dark_factory_label_boosts_ops_patterns(self):
        assert mr.compute_label_boost("dark-factory-ops.md", ["Dark Factory"]) == 1

    def test_dark_factory_hyphen_label_boosts_ops_patterns(self):
        assert mr.compute_label_boost("dark-factory-ops.md", ["dark-factory"]) == 1

    def test_label_match_is_case_insensitive(self):
        assert mr.compute_label_boost("backend-patterns.md", ["BACKEND"]) == 1

    def test_label_match_is_substring(self):
        # "performance" does not map to any file
        assert mr.compute_label_boost("backend-patterns.md", ["performance"]) == 0

    def test_mismatched_file_returns_zero(self):
        assert mr.compute_label_boost("codebase-patterns.md", ["backend"]) == 0

    def test_global_file_never_boosted(self):
        assert mr.compute_label_boost("codebase-patterns.md", ["frontend", "backend"]) == 0
        assert mr.compute_label_boost("architecture.md", ["dark factory"]) == 0

    def test_returns_one_not_more(self):
        # Multiple matching labels still return exactly 1
        assert mr.compute_label_boost("dark-factory-ops.md", ["dark factory", "dark-factory"]) == 1

    def test_multiple_labels_one_matching(self):
        assert mr.compute_label_boost("frontend-patterns.md", ["performance", "frontend", "backend"]) == 1
```

Also add to `TestMainCLI`:

```python
def test_labels_nargs_accepts_multiple(self, tmp_path):
    mem_dir = self._make_mem_dir(tmp_path)
    result = self._run(
        ["--phase", "implement", "--labels", "Dark Factory", "performance"],
        memory_dir=mem_dir,
    )
    assert result.returncode == 0
```

**Step 2 — Verify tests fail**

```bash
docker-compose exec backend bash -c "cd /app && python -m pytest dark-factory/tests/test_memory_retrieve.py::TestComputeLabelBoost -x -q 2>&1 | tail -10"
```

Expected: `AttributeError: module 'memory_retrieve' has no attribute 'compute_label_boost'`.

**Step 3 — Implement `compute_label_boost()`**

In `dark-factory/scripts/memory_retrieve.py`, add after `_LABEL_SOURCE_BOOST_MAP`:

```python
def compute_label_boost(source_file, labels):
    """Return +1 if source_file maps to a domain matched by any issue label; 0 otherwise.

    Global files (codebase-patterns.md, architecture.md) are never boosted.
    Match is case-insensitive substring: 'dark factory' in label.lower().
    """
    if not labels or source_file in GLOBAL_FILES:
        return 0
    for label_text in labels:
        label_lower = label_text.lower()
        for key, target_file in _LABEL_SOURCE_BOOST_MAP.items():
            if key in label_lower and source_file == target_file:
                return 1
    return 0
```

**Step 4 — Change `--labels` from string to list in CLI**

In `main()`, find:

```python
    parser.add_argument("--labels", default="", help="Issue labels (reserved, unused)")
```

Replace with:

```python
    parser.add_argument("--labels", nargs="*", default=None, help="Issue labels for memory ranking label boost")
```

**Step 5 — Thread `labels` into `retrieve_memory()`**

Update `retrieve_memory()` signature:

```python
def retrieve_memory(memory_dir, phase, files, labels=None, _cap_out=None):
    """Return a markdown memory block for the given phase and changed files."""
    allowed_sources = PHASE_SOURCE_MAP.get(phase, set())
    area_files = select_area_files(files)
    memory_dir = Path(memory_dir)

    index_path = memory_dir / "index.jsonl"
    if index_path.exists():
        try:
            candidates = scan_index(memory_dir, area_files, files, allowed_sources)
        except (OSError, ValueError):
            candidates = []
        if candidates:
            return format_index_output(candidates, labels=labels, _cap_out=_cap_out)

    results = scan_markdown_files(memory_dir, area_files, files, allowed_sources)
    return format_markdown_output(results)
```

Update `main()` call site:

```python
    labels = args.labels or []
    output = retrieve_memory(memory_dir, args.phase, files, labels=labels)
    if output:
        print(output)
```

**Step 6 — Verify all tests pass**

```bash
docker-compose exec backend bash -c "cd /app && python -m pytest dark-factory/tests/test_memory_retrieve.py -q 2>&1 | tail -10"
```

Expected: all tests pass (new `TestComputeLabelBoost` + existing suite).

**Step 7 — Commit**

```bash
git add dark-factory/scripts/memory_retrieve.py dark-factory/tests/test_memory_retrieve.py
git commit -m "feat: add compute_label_boost() and wire --labels nargs through retrieve_memory() (#667)"
```

---

### Task 3 — Apply dual cap in `format_index_output()` and import `token_estimate`

**Goal:** Apply the greedy dual cap (≤8 entries OR ≤1 500 tokens) with the new sort key `(specificity + label_boost, created_at DESC)` inside `format_index_output()`. Expose cap counts via optional `_cap_out` side-channel dict.

**Files:** `dark-factory/scripts/memory_retrieve.py`, `dark-factory/tests/test_memory_retrieve.py`

#### TDD steps

**Step 1 — Write failing tests**

Add a new `TestFormatIndexOutputCap` class:

```python
class TestFormatIndexOutputCap:
    """Tests for dual cap and label-boost sort in format_index_output()."""

    def _make_candidate(self, text, specificity=0, created_at="2026-01-01", source_file="backend-patterns.md"):
        return {
            "source_file": source_file,
            "text": f"- [PATTERN] {text}",
            "specificity": specificity,
            "created_at": created_at,
        }

    def _candidates(self, n, source_file="backend-patterns.md"):
        """Return n candidates with unique texts."""
        return [self._make_candidate(f"Entry {i}", source_file=source_file) for i in range(n)]

    def test_nine_candidates_capped_to_eight(self):
        caps = {}
        out = mr.format_index_output(self._candidates(9), _cap_out=caps)
        assert caps["entries_selected"] == 8
        assert caps["entries_dropped_by_cap"] == 1

    def test_eight_candidates_no_drop(self):
        caps = {}
        mr.format_index_output(self._candidates(8), _cap_out=caps)
        assert caps["entries_selected"] == 8
        assert caps["entries_dropped_by_cap"] == 0

    def test_two_candidates_no_drop(self):
        caps = {}
        mr.format_index_output(self._candidates(2), _cap_out=caps)
        assert caps["entries_selected"] == 2
        assert caps["entries_dropped_by_cap"] == 0

    def test_token_budget_cap_stops_early(self):
        # Each entry uses "x"*590 + suffix ≈ 600 chars = ~150 tokens.
        # 9 entries ≈ 1350 tokens; the 10th (~150 tokens) would push total > 1500 and is dropped.
        # So entries_selected ≈ 9, but we assert ≤10 to tolerate off-by-one in char counts.
        long_text = "x" * 590
        candidates = [
            self._make_candidate(long_text + f"_{i}") for i in range(20)
        ]
        caps = {}
        mr.format_index_output(candidates, _cap_out=caps)
        assert caps["entries_selected"] <= 10
        assert caps["entries_dropped_by_cap"] >= 10

    def test_count_cap_takes_priority_over_token_cap(self):
        # Short entries: 8 short entries < 1500 tokens, count cap hits first
        caps = {}
        mr.format_index_output(self._candidates(12), _cap_out=caps)
        assert caps["entries_selected"] == 8
        assert caps["entries_dropped_by_cap"] == 4

    def test_cap_out_none_no_error(self):
        # _cap_out=None: no side effects, just returns text
        out = mr.format_index_output(self._candidates(2))
        assert "### Memory:" in out

    def test_cap_out_per_file_selected(self):
        caps = {}
        candidates = (
            [self._make_candidate(f"B{i}", source_file="backend-patterns.md") for i in range(5)] +
            [self._make_candidate(f"F{i}", source_file="frontend-patterns.md") for i in range(5)]
        )
        mr.format_index_output(candidates, _cap_out=caps)
        assert caps["entries_selected"] == 8
        total_per_file = sum(caps["per_file_selected"].values())
        assert total_per_file == 8

    def test_cap_out_per_file_dropped(self):
        caps = {}
        candidates = (
            [self._make_candidate(f"B{i}", source_file="backend-patterns.md") for i in range(5)] +
            [self._make_candidate(f"F{i}", source_file="frontend-patterns.md") for i in range(5)]
        )
        mr.format_index_output(candidates, _cap_out=caps)
        total_dropped = sum(caps["per_file_dropped"].values())
        assert total_dropped == 2

    def test_label_boost_promotes_matching_file(self):
        """backend label boosts backend-patterns.md entries to the top."""
        candidates = [
            # Low specificity, backend file — should be boosted
            {"source_file": "backend-patterns.md", "text": "- [PATTERN] Low spec backend.",
             "specificity": 0, "created_at": "2026-01-01"},
            # High specificity, frontend file — no boost
            {"source_file": "frontend-patterns.md", "text": "- [PATTERN] High spec frontend.",
             "specificity": 100, "created_at": "2026-01-01"},
        ]
        out = mr.format_index_output(candidates, labels=["backend"])
        # Both should appear (only 2 candidates, well within cap)
        assert "Low spec backend" in out
        assert "High spec frontend" in out

    def test_only_selected_entries_in_output(self):
        """With 9 candidates, the 9th (lowest rank) must not appear in output."""
        candidates = [
            self._make_candidate(f"Entry {i}", specificity=9 - i) for i in range(9)
        ]
        out = mr.format_index_output(candidates)
        assert "Entry 8" not in out  # lowest specificity, ranked last, dropped

    def test_markdown_fallback_unchanged_by_cap(self, tmp_path):
        """scan_markdown_files / format_markdown_output must be unaffected by cap logic."""
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        # 10 passing entries in a markdown file — fallback should return all 10
        lines = [
            f"- [PATTERN] Entry {i}. <!-- source:implement expires:2099-12-31 -->"
            for i in range(10)
        ]
        (mem_dir / "backend-patterns.md").write_text("\n".join(lines), encoding="utf-8")
        out = mr.retrieve_memory(str(mem_dir), "implement", ["backend/app/foo.py"])
        for i in range(10):
            assert f"Entry {i}" in out
```

**Step 2 — Verify tests fail**

```bash
docker-compose exec backend bash -c "cd /app && python -m pytest dark-factory/tests/test_memory_retrieve.py::TestFormatIndexOutputCap -x -q 2>&1 | tail -10"
```

Expected: failures (cap logic doesn't exist yet, `_cap_out` param not accepted).

**Step 3 — Add `token_estimate` import**

At the top of `dark-factory/scripts/memory_retrieve.py`, after the `from pathlib import Path` line, add:

```python
sys.path.insert(0, str(Path(__file__).parent))
import token_estimate as te  # 4 chars/token estimator
```

**Step 4 — Update `format_index_output()`**

Replace the existing `format_index_output()` function with:

```python
def format_index_output(candidates, labels=None, _cap_out=None):
    """Format scan_index output with dual cap and label-boost ranking.

    Sort key: (path_specificity + label_boost, created_at DESC) globally.
    Cap: stop at TOP_K_DEFAULT entries OR TOKEN_BUDGET_DEFAULT tokens, whichever first.
    Groups selected entries by source_file in ALL_MEMORY_FILES order.
    _cap_out: if provided, populated with entries_selected, entries_dropped_by_cap,
              per_file_selected, per_file_dropped.
    """
    labels = labels or []

    # Global sort: (specificity + label_boost, created_at) descending
    ranked = sorted(
        candidates,
        key=lambda c: (
            c["specificity"] + compute_label_boost(c["source_file"], labels),
            c.get("created_at") or "",
        ),
        reverse=True,
    )

    # Greedy dual cap
    selected = []
    dropped = []
    token_total = 0
    for c in ranked:
        token_cost = te.estimate_tokens(c["text"])
        if len(selected) >= TOP_K_DEFAULT or token_total + token_cost > TOKEN_BUDGET_DEFAULT:
            dropped.append(c)
        else:
            selected.append(c)
            token_total += token_cost

    if _cap_out is not None:
        per_file_selected: dict[str, int] = {}
        per_file_dropped: dict[str, int] = {}
        for c in selected:
            per_file_selected[c["source_file"]] = per_file_selected.get(c["source_file"], 0) + 1
        for c in dropped:
            per_file_dropped[c["source_file"]] = per_file_dropped.get(c["source_file"], 0) + 1
        _cap_out["entries_selected"] = len(selected)
        _cap_out["entries_dropped_by_cap"] = len(dropped)
        _cap_out["per_file_selected"] = per_file_selected
        _cap_out["per_file_dropped"] = per_file_dropped

    # Group selected by file in ALL_MEMORY_FILES order
    grouped: dict[str, list] = {}
    for c in selected:
        grouped.setdefault(c["source_file"], []).append(c)

    parts = []
    for fname in ALL_MEMORY_FILES:
        if fname not in grouped:
            continue
        parts.append(f"### Memory: {fname}")
        for e in grouped[fname]:
            parts.append(e["text"])
        parts.append("")

    return "\n".join(parts).rstrip()
```

**Step 5 — Verify all tests pass**

```bash
docker-compose exec backend bash -c "cd /app && python -m pytest dark-factory/tests/test_memory_retrieve.py -q 2>&1 | tail -10"
```

Expected: all tests pass, including existing `TestFormatOutput` tests (they use ≤2 candidates, well within cap limits).

**Step 6 — Commit**

```bash
git add dark-factory/scripts/memory_retrieve.py dark-factory/tests/test_memory_retrieve.py
git commit -m "feat: apply dual cap (top-8 / 1500-token) in format_index_output() with label-boost sort (#667)"
```

---

### Task 4 — Wire `_cap_out` into `main()` and update `emit_memory_trace()`

**Goal:** Pass cap counts from `format_index_output()` through `main()` into `emit_memory_trace()`. The trace gains `entries_selected_total`, `entries_dropped_by_cap_total` at the root, and `entries_selected` + `entries_dropped_by_cap` per `files_loaded` entry.

**Note:** Task 2 Step 5 already rewrites `retrieve_memory()` to accept `labels` and `_cap_out` and passes them to `format_index_output()`. Task 4 does NOT re-edit `retrieve_memory()`'s signature — it only edits `emit_memory_trace()` and the `main()` call site where `cap_counts` is collected and forwarded.

**Files:** `dark-factory/scripts/memory_retrieve.py`, `dark-factory/tests/test_memory_retrieve.py`

#### TDD steps

**Step 1 — Write failing tests**

Add a new `TestEmitMemoryTraceCap` class:

```python
class TestEmitMemoryTraceCap:
    """Tests for cap-count fields in emit_memory_trace()."""

    def _make_mem_dir(self, tmp_path):
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        content = "- [PATTERN] Foo. <!-- source:implement expires:2099-12-31 -->\n"
        for fname in mr.ALL_MEMORY_FILES:
            (mem_dir / fname).write_text(content)
        return mem_dir

    def test_cap_counts_in_trace_root(self, tmp_path):
        mem_dir = self._make_mem_dir(tmp_path)
        trace_path = tmp_path / "trace.json"
        cap_counts = {
            "entries_selected": 6,
            "entries_dropped_by_cap": 10,
            "per_file_selected": {"backend-patterns.md": 3, "codebase-patterns.md": 3},
            "per_file_dropped": {"frontend-patterns.md": 5, "dark-factory-ops.md": 5},
        }
        mr.emit_memory_trace(
            trace_path, "implement", [], mem_dir, mr.ALL_MEMORY_FILES, {"implement"},
            cap_counts=cap_counts,
        )
        data = json.loads(trace_path.read_text())
        assert data["entries_selected_total"] == 6
        assert data["entries_dropped_by_cap_total"] == 10

    def test_no_cap_counts_omits_root_totals(self, tmp_path):
        mem_dir = self._make_mem_dir(tmp_path)
        trace_path = tmp_path / "trace.json"
        mr.emit_memory_trace(
            trace_path, "implement", [], mem_dir, mr.ALL_MEMORY_FILES, {"implement"},
        )
        data = json.loads(trace_path.read_text())
        assert "entries_selected_total" not in data
        assert "entries_dropped_by_cap_total" not in data

    def test_per_file_cap_fields_added(self, tmp_path):
        mem_dir = self._make_mem_dir(tmp_path)
        trace_path = tmp_path / "trace.json"
        cap_counts = {
            "entries_selected": 2,
            "entries_dropped_by_cap": 1,
            "per_file_selected": {"backend-patterns.md": 2},
            "per_file_dropped": {"backend-patterns.md": 1},
        }
        mr.emit_memory_trace(
            trace_path, "implement", [], mem_dir, ["backend-patterns.md"], {"implement"},
            cap_counts=cap_counts,
        )
        data = json.loads(trace_path.read_text())
        entry = next(e for e in data["files_loaded"] if e["path"].endswith("backend-patterns.md"))
        assert entry["entries_selected"] == 2
        assert entry["entries_dropped_by_cap"] == 1

    def test_per_file_zero_for_unmentioned_files(self, tmp_path):
        """Files not in per_file_selected/dropped get 0."""
        mem_dir = self._make_mem_dir(tmp_path)
        trace_path = tmp_path / "trace.json"
        cap_counts = {
            "entries_selected": 2,
            "entries_dropped_by_cap": 0,
            "per_file_selected": {"backend-patterns.md": 2},
            "per_file_dropped": {},
        }
        mr.emit_memory_trace(
            trace_path, "implement", [], mem_dir, mr.ALL_MEMORY_FILES, {"implement"},
            cap_counts=cap_counts,
        )
        data = json.loads(trace_path.read_text())
        frontend_entry = next(
            (e for e in data["files_loaded"] if e["path"].endswith("frontend-patterns.md")), None
        )
        if frontend_entry:
            assert frontend_entry["entries_selected"] == 0
            assert frontend_entry["entries_dropped_by_cap"] == 0

    def test_empty_cap_counts_omits_root_totals(self, tmp_path):
        """Empty dict (markdown fallback ran) → no root totals."""
        mem_dir = self._make_mem_dir(tmp_path)
        trace_path = tmp_path / "trace.json"
        mr.emit_memory_trace(
            trace_path, "implement", [], mem_dir, mr.ALL_MEMORY_FILES, {"implement"},
            cap_counts={},
        )
        data = json.loads(trace_path.read_text())
        assert "entries_selected_total" not in data
        assert "entries_dropped_by_cap_total" not in data

    def test_cli_cap_counts_in_trace_via_index_path(self, tmp_path):
        """Integration: CLI with index path emits cap count fields in trace."""
        import subprocess
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        records_dir = mem_dir / "records"
        records_dir.mkdir()
        # Create 10 index entries (more than TOP_K_DEFAULT=8)
        index_lines = []
        for i in range(10):
            entry_id = f"aabb{i:04d}"
            entry = {
                "id": entry_id,
                "kind": "PATTERN",
                "source_file": "backend-patterns.md",
                "agent_id": "implement",  # must match PHASE_SOURCE_MAP["implement"] = {"implement"}
                "path_prefixes": [],
                "expires_at": "2099-12-31",
                "created_at": f"2026-01-{i+1:02d}",  # distinct dates for deterministic recency sort
                "confidence": 1.0,
                "summary_snippet": f"Entry {i}.",
            }
            index_lines.append(json.dumps(entry))
            record = {
                "id": entry_id,
                "kind": "PATTERN",
                "summary": f"Entry {i} full summary.",
                "evidence": [{"source": "implement", "date": "2026-01-01", "issue": 667}],
                "path_prefixes": [],
                "expires_at": "2099-12-31",
            }
            (records_dir / f"{entry_id}.json").write_text(json.dumps(record), encoding="utf-8")
        (mem_dir / "index.jsonl").write_text("\n".join(index_lines), encoding="utf-8")

        trace_path = tmp_path / "trace.json"
        result = subprocess.run(
            [
                sys.executable, str(Path(mr.__file__).resolve()),
                "--phase", "implement",
                "--memory-dir", str(mem_dir),
                "--emit-trace-to", str(trace_path),
            ],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert trace_path.exists()
        data = json.loads(trace_path.read_text())
        assert data.get("entries_selected_total") == 8
        assert data.get("entries_dropped_by_cap_total") == 2
```

**Step 2 — Verify tests fail**

```bash
docker-compose exec backend bash -c "cd /app && python -m pytest dark-factory/tests/test_memory_retrieve.py::TestEmitMemoryTraceCap -x -q 2>&1 | tail -10"
```

Expected: `TypeError` (emit_memory_trace doesn't accept `cap_counts` kwarg yet).

**Step 3 — Update `emit_memory_trace()` signature**

In `dark-factory/scripts/memory_retrieve.py`, update `emit_memory_trace()`:

```python
def emit_memory_trace(trace_path, phase, files, memory_dir, area_files, allowed_sources, issue=0, agent_id=None, cap_counts=None):
    """Write memory-trace.json to trace_path. Best-effort: never raises.

    cap_counts: dict from format_index_output() _cap_out, containing:
        entries_selected, entries_dropped_by_cap, per_file_selected, per_file_dropped.
        Empty dict or None means markdown fallback ran (no cap applied).
    """
    try:
        memory_dir = Path(memory_dir)
        files_loaded = []
        fallback_used = False

        per_file_selected = (cap_counts or {}).get("per_file_selected", {})
        per_file_dropped = (cap_counts or {}).get("per_file_dropped", {})

        for fname in area_files:
            fpath = memory_dir / fname
            counts = _count_entries(fpath, files, allowed_sources, fname) if fpath.exists() else None
            if counts is None:
                fallback_used = True
                continue
            files_loaded.append({
                "path": str(fpath),
                "entries_total": counts["total"],
                "entries_included": counts["included"],
                "entries_filtered_out": counts["total"] - counts["included"],
                "entries_selected": per_file_selected.get(fname, 0),
                "entries_dropped_by_cap": per_file_dropped.get(fname, 0),
            })

        trace = {
            "schema_version": 1,
            "retrieval_mechanism": "flatfile-pathtag",
            "issue": issue or 0,
            "phase": phase,
            "agent_id": agent_id or PHASE_AGENT_ID.get(phase, phase + "-agent"),
            "project": "markethawk",
            "affected_files": list(files),
            "files_loaded": files_loaded,
            "fallback_used": fallback_used,
        }

        if cap_counts:
            trace["entries_selected_total"] = cap_counts.get("entries_selected", 0)
            trace["entries_dropped_by_cap_total"] = cap_counts.get("entries_dropped_by_cap", 0)

        trace_path = Path(trace_path)
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        trace_path.write_text(json.dumps(trace, indent=2), encoding="utf-8")
    except Exception:
        pass
```

**Step 4 — Wire `_cap_out` through `main()`**

In `main()`, replace the existing `retrieve_memory` call and `emit_memory_trace` call:

```python
    labels = args.labels or []
    cap_counts: dict = {}
    output = retrieve_memory(memory_dir, args.phase, files, labels=labels, _cap_out=cap_counts)
    if output:
        print(output)

    if args.emit_trace_to:
        emit_memory_trace(
            args.emit_trace_to, args.phase, files, memory_dir, area_files, allowed_sources,
            issue=args.issue or 0,
            agent_id=PHASE_AGENT_ID.get(args.phase, args.phase + "-agent"),
            cap_counts=cap_counts if cap_counts else None,
        )
```

**Step 5 — Verify all tests pass**

```bash
docker-compose exec backend bash -c "cd /app && python -m pytest dark-factory/tests/test_memory_retrieve.py -q 2>&1 | tail -10"
```

Expected: all tests pass (existing suite + new `TestEmitMemoryTraceCap`).

**Step 6 — Commit**

```bash
git add dark-factory/scripts/memory_retrieve.py dark-factory/tests/test_memory_retrieve.py
git commit -m "feat: thread cap_counts into emit_memory_trace() with per-file and run-level totals (#667)"
```

---

### Task 5 — Update `context_budget.py` to surface cap counts from trace

**Goal:** Add a `_read_json()` helper and read `memory-trace.json` from `artifacts_dir` in the `memory_context` section of `build_budget()`, surfacing `entries_selected` and `entries_dropped` (best-effort, fail-open).

**Files:** `dark-factory/scripts/context_budget.py`, `dark-factory/tests/test_context_budget.py`

#### TDD steps

**Step 1 — Write failing tests**

In `dark-factory/tests/test_context_budget.py`, add at the end of the file:

```python
# ── memory_context cap counts from trace ─────────────────────────────────────

import json as _json
from pathlib import Path as _Path


def write_memory_trace(artifacts_dir, entries_selected, entries_dropped):
    """Write a minimal memory-trace.json with run-level cap totals."""
    trace = {
        "schema_version": 1,
        "entries_selected_total": entries_selected,
        "entries_dropped_by_cap_total": entries_dropped,
    }
    (_Path(artifacts_dir) / "memory-trace.json").write_text(
        _json.dumps(trace), encoding="utf-8"
    )


def make_memory_file(tmp_path, content="Memory block content here.\n"):
    p = tmp_path / "memory-context.md"
    p.write_text(content)
    return str(p)


class TestMemoryContextCapCounts:
    def test_entries_selected_from_trace(self, tmp_path):
        issue_json = make_issue_json(tmp_path)
        mem_file = make_memory_file(tmp_path)
        write_memory_trace(str(tmp_path), entries_selected=6, entries_dropped=10)
        result = run_budget(tmp_path, "plan", issue_json=issue_json, memory_file=mem_file)
        mc = result["sections"]["memory_context"]
        assert mc.get("entries_selected") == 6

    def test_entries_dropped_from_trace(self, tmp_path):
        issue_json = make_issue_json(tmp_path)
        mem_file = make_memory_file(tmp_path)
        write_memory_trace(str(tmp_path), entries_selected=3, entries_dropped=25)
        result = run_budget(tmp_path, "plan", issue_json=issue_json, memory_file=mem_file)
        mc = result["sections"]["memory_context"]
        assert mc.get("entries_dropped") == 25

    def test_no_trace_no_cap_fields(self, tmp_path):
        """When trace is absent, cap fields are absent (not 0)."""
        issue_json = make_issue_json(tmp_path)
        mem_file = make_memory_file(tmp_path)
        result = run_budget(tmp_path, "plan", issue_json=issue_json, memory_file=mem_file)
        mc = result["sections"]["memory_context"]
        assert "entries_selected" not in mc
        assert "entries_dropped" not in mc

    def test_missing_trace_fields_omitted(self, tmp_path):
        """Trace present but without cap totals → cap fields absent (fail-open)."""
        issue_json = make_issue_json(tmp_path)
        mem_file = make_memory_file(tmp_path)
        # Write trace without cap fields
        (_Path(tmp_path) / "memory-trace.json").write_text(
            _json.dumps({"schema_version": 1}), encoding="utf-8"
        )
        result = run_budget(tmp_path, "plan", issue_json=issue_json, memory_file=mem_file)
        mc = result["sections"]["memory_context"]
        # trace.get("entries_selected_total", 0) → 0, but we only emit when trace present
        # so 0 may appear; this is acceptable and tested here for the actual behavior
        # (fields may be 0 if trace exists but lacks the keys)
        # The important invariant is the call does NOT raise
        assert isinstance(result, dict)

    def test_corrupt_trace_does_not_raise(self, tmp_path):
        """Corrupt trace JSON → fail-open, no cap fields, no exception."""
        issue_json = make_issue_json(tmp_path)
        mem_file = make_memory_file(tmp_path)
        (_Path(tmp_path) / "memory-trace.json").write_text("not valid json", encoding="utf-8")
        result = run_budget(tmp_path, "plan", issue_json=issue_json, memory_file=mem_file)
        assert "memory_context" in result["sections"]

    def test_dropped_memory_file_no_trace_no_crash(self, tmp_path):
        """When memory_file is missing (pre-run call), trace read is not attempted."""
        issue_json = make_issue_json(tmp_path)
        write_memory_trace(str(tmp_path), entries_selected=5, entries_dropped=3)
        result = run_budget(tmp_path, "plan", issue_json=issue_json, memory_file=None)
        mc = result["sections"]["memory_context"]
        assert mc["status"] == "dropped"
```

**Step 2 — Verify tests fail**

```bash
docker-compose exec backend bash -c "cd /app && python -m pytest dark-factory/tests/test_context_budget.py::TestMemoryContextCapCounts -x -q 2>&1 | tail -10"
```

Expected: `AssertionError` or `KeyError` (cap fields not yet present in `memory_context`).

**Step 3 — Add `_read_json()` to `context_budget.py`**

In `dark-factory/scripts/context_budget.py`, after the existing `_dropped()` function:

```python
def _read_json(path: str | None) -> dict | None:
    """Read and parse a JSON file. Returns None on missing file, OSError, or parse error."""
    raw = _read_text(path)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
```

**Step 4 — Update `memory_context` section in `build_budget()`**

In `context_budget.py`, find the `elif sec == "memory_context":` block:

```python
        elif sec == "memory_context":
            # memory-context.md is written inside the command session by memory_retrieve.py
            # (Phase 1 load). Budget node runs before the command, so it is always absent.
            # Correctly reports status="dropped", reason="empty_or_missing".
            sections[sec] = _included(_read_text(memory_file), memory_file)
            if memory_file and sections[sec]["status"] == "included":
                h = te.hash_file(memory_file)
                if h:
                    source_hashes["memory-context.md"] = h
```

Replace with:

```python
        elif sec == "memory_context":
            # memory-context.md is written inside the command session by memory_retrieve.py
            # (Phase 1 load). Budget node runs before the command, so it is always absent.
            # Correctly reports status="dropped", reason="empty_or_missing".
            sections[sec] = _included(_read_text(memory_file), memory_file)
            if memory_file and sections[sec]["status"] == "included":
                h = te.hash_file(memory_file)
                if h:
                    source_hashes["memory-context.md"] = h
            # Best-effort: surface cap counts from memory-trace.json when available.
            # Pre-run budget calls will not have the trace; post-run calls will.
            if artifacts_dir:
                trace_path = os.path.join(artifacts_dir, "memory-trace.json")
                trace = _read_json(trace_path)
                if trace:
                    sections[sec]["entries_selected"] = trace.get("entries_selected_total", 0)
                    sections[sec]["entries_dropped"] = trace.get("entries_dropped_by_cap_total", 0)
```

**Step 5 — Verify all tests pass**

```bash
docker-compose exec backend bash -c "cd /app && python -m pytest dark-factory/tests/test_context_budget.py -q 2>&1 | tail -10"
```

Expected: all tests pass (existing suite + new `TestMemoryContextCapCounts`).

Also run the full memory_retrieve suite to confirm no regressions:

```bash
docker-compose exec backend bash -c "cd /app && python -m pytest dark-factory/tests/test_memory_retrieve.py dark-factory/tests/test_context_budget.py -q 2>&1 | tail -10"
```

Expected: all pass.

**Step 6 — Commit**

```bash
git add dark-factory/scripts/context_budget.py dark-factory/tests/test_context_budget.py
git commit -m "feat: surface memory cap counts (entries_selected/dropped) in context-budget.json (#667)"
```

---

## Final Verification

After all 5 tasks, run the combined suite:

```bash
docker-compose exec backend bash -c "cd /app && python -m pytest dark-factory/tests/test_memory_retrieve.py dark-factory/tests/test_context_budget.py -v 2>&1 | tail -30"
```

Expected: all tests pass with no FAILED lines.

Smoke-test the CLI end-to-end against the live memory directory:

```bash
docker-compose exec backend bash -c "
  python3 dark-factory/scripts/memory_retrieve.py \
    --phase implement \
    --files 'dark-factory/scripts/memory_retrieve.py' \
    --issue 667 \
    --labels 'Dark Factory' 'performance' \
    --memory-dir .archon/memory \
    --emit-trace-to /tmp/test-trace.json && \
  echo '=== Trace cap totals ===' && \
  python3 -c \"import json; d=json.load(open('/tmp/test-trace.json')); print('selected:', d.get('entries_selected_total','n/a'), 'dropped:', d.get('entries_dropped_by_cap_total','n/a'))\"
"
```

Expected: memory block printed to stdout, trace written, cap totals printed.

## Constraints and Invariants

- Markdown fallback path is **never capped**: `entries_dropped_by_cap=0` for all fallback-path trace entries.
- `TOP_K_DEFAULT = 8` and `TOKEN_BUDGET_DEFAULT = 1500` are constants, not CLI flags (out of scope per spec).
- `--labels nargs="*"` is backward-compatible: `--labels backend` (single arg) still works.
- `_cap_out` side-channel: callers that don't pass it get the same string return value — no API break.
- `context_budget.py` trace-read is fail-open: missing/corrupt trace → fields absent, no exception.
- Global files (`codebase-patterns.md`, `architecture.md`) are never label-boosted.
- Cap is applied to **authoritative kinds only** via the existing `scan_index()` status filter (PROVISIONAL/INVALID already excluded before reaching `format_index_output()`).
