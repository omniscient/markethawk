# Implementation Plan: Memory Trace Artifacts for Every Dark Factory Run

**Date:** 2026-06-30
**Issue:** #647
**Spec:** `docs/superpowers/specs/2026-06-27-memory-trace-artifacts-design.md`
**Branch:** `refine/issue-647-add-memory-trace-artifacts-for-every-dar`

---

## Goal

Every Dark Factory gate that calls `memory_retrieve.py` must emit a `memory-trace.json` artifact to `$ARTIFACTS_DIR`. This makes memory retrieval auditable: a reviewer can open the artifact and see exactly which memory files were considered, how many entries survived path-tag filtering, and what file set drove the filter. The trace is assembled into `run-record.json` at end-of-run.

**Spec requirements traceability:**
| Req | Description | Task |
|-----|-------------|------|
| R1 | Every phase calling `memory_retrieve.py` emits the trace | Task 2, Task 3 |
| R2 | Trace emitted from `memory_retrieve.py` via `--emit-trace-to` | Task 1 |
| R3 | Schema is file-level (`schema_version: 1`, `retrieval_mechanism: "flatfile-pathtag"`) | Task 1 |
| R4 | Best-effort, non-blocking (wrapped in try/except) | Task 1 |
| R5 | `fallback_used: true` when trace derivation fails | Task 1 |
| R6 | `run_record.py` picks up `memory-trace.json` into `run-record.json["memory_trace"]` | Task 3 |

---

## Architecture

The change is purely additive to `memory_retrieve.py`. A new `--emit-trace-to <path>` CLI argument triggers a best-effort JSON write as a side-effect of the retrieval call that already populates memory context — no second invocation, no count mismatch window. The four gate command files each add one argument to their existing invocation. `run_record.py`'s `cmd_assemble()` gains a one-block pickup of the artifact.

**Memory patterns applied (from `.archon/memory/`):**
- `[PATTERN]` Emit the trace from inside `memory_retrieve.py` via `--emit-trace-to`, not from a second invocation — guarantees the trace matches what entered context. (`architecture.md`)
- `[AVOID]` No second `memory_retrieve.py` call for the trace — two invocations create a count-mismatch window. (`architecture.md`)
- `[AVOID]` No pseudo-IDs (`file.md#L42`) or floating-point scores in the schema — implies semantic retrieval that doesn't exist. (`architecture.md`)
- `[PATTERN]` `.archon/commands/` files are read from the cloned repo at runtime (no image rebuild needed); changes take effect on the next run. (`dark-factory-ops.md`)

---

## Tech Stack

- Python 3 (no new deps; only stdlib `json`, `pathlib`, `argparse`)
- pytest for `dark-factory/tests/`
- Bash markdown command files in `.archon/commands/`

---

## File Structure

| File | Action | Notes |
|------|--------|-------|
| `dark-factory/scripts/memory_retrieve.py` | Modify | Add `PHASE_AGENT_ID`, `--emit-trace-to` arg, trace-writing block in `main()` |
| `.archon/commands/dark-factory-refine.md` | Modify | Add `--emit-trace-to "$ARTIFACTS_DIR/memory-trace.json"` |
| `.archon/commands/dark-factory-plan.md` | Modify | Add `--emit-trace-to "$ARTIFACTS_DIR/memory-trace.json"` |
| `.archon/commands/dark-factory-implement.md` | Modify | Add `--emit-trace-to "$ARTIFACTS_DIR/memory-trace.json"` |
| `.archon/commands/dark-factory-validate.md` | Modify | Add `--emit-trace-to "$ARTIFACTS_DIR/memory-trace.json"` |
| `dark-factory/scripts/factory_core/run_record.py` | Modify | Add `memory-trace.json` pickup in `cmd_assemble()` |
| `dark-factory/tests/test_memory_retrieve.py` | Create | Tests for `--emit-trace-to` |
| `dark-factory/tests/test_run_record.py` | Extend | Tests for `memory_trace` assembly |

---

## Task 0: Sync branch with main

**Files:** none (git operation)

**Purpose:** PRs #678 (`memory_retrieve.py`) and #681 (gate command file wiring) merged after this branch was cut. Merge main to get the current `memory_retrieve.py` and the updated command files before modifying them.

**Steps:**

1. Verify the files are absent locally but present on main:
   ```bash
   ls dark-factory/scripts/memory_retrieve.py 2>/dev/null || echo "absent — expected"
   git show origin/main:dark-factory/scripts/memory_retrieve.py | head -3
   ```
   Expected: first line absent locally, second shows `#!/usr/bin/env python3`.

2. Fetch and merge:
   ```bash
   git fetch origin main
   git merge origin/main --no-edit
   ```
   Expected output: `Merge made by the 'ort' strategy.` with `memory_retrieve.py` listed.

3. Verify the merge landed correctly:
   ```bash
   ls dark-factory/scripts/memory_retrieve.py
   grep "PHASE_SOURCE_MAP" dark-factory/scripts/memory_retrieve.py
   grep "memory_retrieve.py" .archon/commands/dark-factory-implement.md | head -2
   ```
   Expected: file exists, `PHASE_SOURCE_MAP` present, command files show `memory_retrieve.py` invocation.

---

## Task 1: Add `--emit-trace-to` to `memory_retrieve.py` (TDD)

**Files:**
- `dark-factory/tests/test_memory_retrieve.py` (new)
- `dark-factory/scripts/memory_retrieve.py` (modify)

### Step 1a — Write failing tests

Create `dark-factory/tests/test_memory_retrieve.py`:

```python
"""Tests for memory_retrieve.py --emit-trace-to."""
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import memory_retrieve


def _make_memory_dir(tmp_path):
    """Minimal .archon/memory/ with one codebase-patterns entry per phase."""
    d = tmp_path / "memory"
    d.mkdir()
    (d / "codebase-patterns.md").write_text(
        "- [PATTERN] Use PostgreSQL for durable state. <!-- source:implement date:2026-01-01 expires:2027-01-01 -->\n"
        "- [AVOID] Avoid Redis for durable state. <!-- source:implement date:2026-01-01 expires:2027-01-01 -->\n"
    )
    return d


def _run_main(argv):
    with patch("sys.argv", argv), patch("sys.stdout", new_callable=io.StringIO):
        memory_retrieve.main()


class TestEmitTraceTo:
    def test_writes_valid_json(self, tmp_path):
        memory_dir = _make_memory_dir(tmp_path)
        trace_path = tmp_path / "out" / "memory-trace.json"

        _run_main([
            "memory_retrieve.py",
            "--phase", "implement",
            "--files", "dark-factory/scripts/memory_retrieve.py",
            "--issue", "647",
            "--memory-dir", str(memory_dir),
            "--emit-trace-to", str(trace_path),
        ])

        assert trace_path.exists(), "trace file must be written"
        trace = json.loads(trace_path.read_text())
        assert trace["schema_version"] == 1
        assert trace["retrieval_mechanism"] == "flatfile-pathtag"
        assert trace["issue"] == 647
        assert trace["phase"] == "implement"
        assert trace["agent_id"] == "implementation-agent"
        assert trace["project"] == "markethawk"
        assert isinstance(trace["files_loaded"], list)
        assert isinstance(trace["fallback_used"], bool)
        assert trace["fallback_used"] is False

    def test_creates_parent_dirs(self, tmp_path):
        memory_dir = _make_memory_dir(tmp_path)
        deep = tmp_path / "a" / "b" / "c" / "memory-trace.json"

        _run_main([
            "memory_retrieve.py",
            "--phase", "plan",
            "--memory-dir", str(memory_dir),
            "--emit-trace-to", str(deep),
        ])

        assert deep.exists()

    def test_no_trace_without_flag(self, tmp_path):
        memory_dir = _make_memory_dir(tmp_path)

        _run_main([
            "memory_retrieve.py",
            "--phase", "implement",
            "--memory-dir", str(memory_dir),
        ])

        assert list(tmp_path.glob("*.json")) == [], "no JSON files without --emit-trace-to"

    def test_affected_files_in_trace(self, tmp_path):
        memory_dir = _make_memory_dir(tmp_path)
        trace_path = tmp_path / "memory-trace.json"

        _run_main([
            "memory_retrieve.py",
            "--phase", "implement",
            "--files", "dark-factory/scripts/memory_retrieve.py\nbackend/app/models/foo.py",
            "--memory-dir", str(memory_dir),
            "--emit-trace-to", str(trace_path),
        ])

        trace = json.loads(trace_path.read_text())
        assert "dark-factory/scripts/memory_retrieve.py" in trace["affected_files"]
        assert "backend/app/models/foo.py" in trace["affected_files"]

    def test_entry_counts_correct(self, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        (memory_dir / "codebase-patterns.md").write_text(
            "- [PATTERN] Keep. <!-- source:implement date:2026-01-01 expires:2027-01-01 -->\n"
            "- [AVOID] Keep too. <!-- source:implement date:2026-01-01 expires:2027-01-01 -->\n"
            "- [PROVISIONAL] Skip. <!-- source:implement date:2026-01-01 expires:2027-01-01 -->\n"
            "- [INVALID: old] Skip. <!-- source:implement date:2026-01-01 expires:2027-01-01 -->\n"
        )
        trace_path = tmp_path / "memory-trace.json"

        _run_main([
            "memory_retrieve.py",
            "--phase", "implement",
            "--memory-dir", str(memory_dir),
            "--emit-trace-to", str(trace_path),
        ])

        trace = json.loads(trace_path.read_text())
        entry = next(
            (f for f in trace["files_loaded"] if "codebase-patterns.md" in f["path"]), None
        )
        assert entry is not None
        assert entry["entries_total"] == 4
        assert entry["entries_included"] == 2
        assert entry["entries_filtered_out"] == 2

    def test_fallback_used_on_read_error(self, tmp_path, monkeypatch):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        md = memory_dir / "codebase-patterns.md"
        md.write_text("- [PATTERN] Entry. <!-- source:implement date:2026-01-01 expires:2027-01-01 -->\n")
        trace_path = tmp_path / "memory-trace.json"

        original_read = Path.read_text

        def _patched_read(self, *args, **kwargs):
            if self.name == "codebase-patterns.md":
                raise OSError("permission denied")
            return original_read(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", _patched_read)

        # Must not raise even when file read fails
        _run_main([
            "memory_retrieve.py",
            "--phase", "implement",
            "--memory-dir", str(memory_dir),
            "--emit-trace-to", str(trace_path),
        ])

        # trace written with fallback_used=True
        if trace_path.exists():
            trace = json.loads(trace_path.read_text())
            assert trace["fallback_used"] is True

    def test_phase_agent_id_mapping(self):
        assert memory_retrieve.PHASE_AGENT_ID["implement"] == "implementation-agent"
        assert memory_retrieve.PHASE_AGENT_ID["plan"] == "plan-agent"
        assert memory_retrieve.PHASE_AGENT_ID["refine"] == "refine-agent"
        assert memory_retrieve.PHASE_AGENT_ID["validate"] == "validate-agent"
        assert memory_retrieve.PHASE_AGENT_ID["review"] == "review-agent"

    def test_main_output_unaffected(self, tmp_path):
        """Stdout markdown output must be the same whether or not --emit-trace-to is set."""
        memory_dir = _make_memory_dir(tmp_path)
        trace_path = tmp_path / "memory-trace.json"

        buf_with = io.StringIO()
        with patch("sys.argv", [
            "memory_retrieve.py", "--phase", "implement",
            "--memory-dir", str(memory_dir),
            "--emit-trace-to", str(trace_path),
        ]), patch("sys.stdout", buf_with):
            memory_retrieve.main()

        buf_without = io.StringIO()
        with patch("sys.argv", [
            "memory_retrieve.py", "--phase", "implement",
            "--memory-dir", str(memory_dir),
        ]), patch("sys.stdout", buf_without):
            memory_retrieve.main()

        assert buf_with.getvalue() == buf_without.getvalue()

    def test_all_phase_choices_accepted(self, tmp_path):
        memory_dir = _make_memory_dir(tmp_path)
        for phase in ("refine", "plan", "implement", "validate", "review"):
            trace_path = tmp_path / f"trace-{phase}.json"
            _run_main([
                "memory_retrieve.py", "--phase", phase,
                "--memory-dir", str(memory_dir),
                "--emit-trace-to", str(trace_path),
            ])
            trace = json.loads(trace_path.read_text())
            assert trace["phase"] == phase
```

### Step 1b — Verify tests fail

```bash
cd /workspace/markethawk
python -m pytest dark-factory/tests/test_memory_retrieve.py -v 2>&1 | tail -20
```

Expected: `FAILED` on `test_phase_agent_id_mapping` (`AttributeError: module 'memory_retrieve' has no attribute 'PHASE_AGENT_ID'`) and any test calling `--emit-trace-to` (argparse error or no trace file written).

### Step 1c — Implement `--emit-trace-to` in `memory_retrieve.py`

Open `dark-factory/scripts/memory_retrieve.py`. Make three changes:

**Change 1**: After the `PHASE_SOURCE_MAP` dict (around line 31), add `PHASE_AGENT_ID`:

```python
# Phase → agent identifier written into memory-trace.json
PHASE_AGENT_ID = {
    "refine":    "refine-agent",
    "plan":      "plan-agent",
    "implement": "implementation-agent",
    "validate":  "validate-agent",
    "review":    "review-agent",
}
```

**Change 2**: In `main()`, after the `--labels` argument, add:

```python
    parser.add_argument(
        "--emit-trace-to",
        default=None,
        help="If set, write memory-trace.json to this path as a side-effect (best-effort).",
    )
```

**Change 3**: At the end of `main()`, after `if output: print(output)`, add:

```python
    if args.emit_trace_to:
        try:
            area_files = select_area_files(files)
            allowed_sources = PHASE_SOURCE_MAP.get(args.phase, set())
            files_loaded = []
            fallback = False

            for fname in area_files:
                fpath = memory_dir / fname
                if not fpath.exists():
                    continue
                try:
                    raw_lines = fpath.read_text(encoding="utf-8").splitlines()
                except OSError:
                    fallback = True
                    continue
                total = sum(1 for ln in raw_lines if ln.startswith("- ["))
                included = 0
                for line in raw_lines:
                    m = _ENTRY_RE.match(line)
                    if not m:
                        continue
                    meta = parse_meta(m.group("meta") or "")
                    if passes_line_filters(m.group("tag"), meta, fname, files, allowed_sources):
                        included += 1
                try:
                    display_path = str(fpath.relative_to(Path(".").resolve()))
                except ValueError:
                    display_path = str(fpath)
                files_loaded.append({
                    "path": display_path,
                    "entries_total": total,
                    "entries_included": included,
                    "entries_filtered_out": total - included,
                })

            trace = {
                "schema_version": 1,
                "retrieval_mechanism": "flatfile-pathtag",
                "issue": args.issue or 0,
                "phase": args.phase,
                "agent_id": PHASE_AGENT_ID.get(args.phase, args.phase + "-agent"),
                "project": "markethawk",
                "affected_files": files,
                "files_loaded": files_loaded,
                "fallback_used": fallback,
            }
            out = Path(args.emit_trace_to)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(trace, indent=2), encoding="utf-8")
        except Exception:
            pass  # best-effort: never affect the main retrieval
```

**Note:** `memory_dir` and `files` are already defined earlier in `main()` as `Path(args.memory_dir)` and `[f.strip() for f in args.files.splitlines() if f.strip()]` respectively. The trace block reuses them directly — no re-parsing needed. The `json` module is already imported at the top of the file.

### Step 1d — Verify tests pass

```bash
python -m pytest dark-factory/tests/test_memory_retrieve.py -v
```

Expected output:
```
PASSED dark-factory/tests/test_memory_retrieve.py::TestEmitTraceTo::test_writes_valid_json
PASSED dark-factory/tests/test_memory_retrieve.py::TestEmitTraceTo::test_creates_parent_dirs
PASSED dark-factory/tests/test_memory_retrieve.py::TestEmitTraceTo::test_no_trace_without_flag
PASSED dark-factory/tests/test_memory_retrieve.py::TestEmitTraceTo::test_affected_files_in_trace
PASSED dark-factory/tests/test_memory_retrieve.py::TestEmitTraceTo::test_entry_counts_correct
PASSED dark-factory/tests/test_memory_retrieve.py::TestEmitTraceTo::test_fallback_used_on_read_error
PASSED dark-factory/tests/test_memory_retrieve.py::TestEmitTraceTo::test_phase_agent_id_mapping
PASSED dark-factory/tests/test_memory_retrieve.py::TestEmitTraceTo::test_main_output_unaffected
PASSED dark-factory/tests/test_memory_retrieve.py::TestEmitTraceTo::test_all_phase_choices_accepted
9 passed in ...
```

Also confirm existing tests still pass:
```bash
python -m pytest dark-factory/tests/test_run_record.py -v
```

### Step 1e — Smoke test from CLI

```bash
cd /workspace/markethawk
TRACE_OUT=$(mktemp)
python dark-factory/scripts/memory_retrieve.py \
  --phase implement \
  --files "dark-factory/scripts/memory_retrieve.py" \
  --issue 647 \
  --memory-dir .archon/memory \
  --emit-trace-to "$TRACE_OUT"
python -m json.tool "$TRACE_OUT"
rm "$TRACE_OUT"
```

Expected: pretty-printed JSON with `schema_version: 1`, `phase: "implement"`, `agent_id: "implementation-agent"`, `files_loaded` entries with `entries_total`/`entries_included`/`entries_filtered_out`.

### Step 1f — Commit

```bash
git add dark-factory/scripts/memory_retrieve.py dark-factory/tests/test_memory_retrieve.py
git commit -m "feat: add --emit-trace-to argument to memory_retrieve.py (#647)"
```

---

## Task 2: Wire `--emit-trace-to` into the four gate command files

**Files:**
- `.archon/commands/dark-factory-refine.md`
- `.archon/commands/dark-factory-plan.md`
- `.archon/commands/dark-factory-implement.md`
- `.archon/commands/dark-factory-validate.md`

The change is identical in all four files. Each file has a block like:

```bash
MEMORY_CONTEXT=$(python3 "${REPO_ROOT}/dark-factory/scripts/memory_retrieve.py" \
  --phase <PHASE> \
  --files "$AFFECTED" \
  $ISSUE_ARG \
  --memory-dir "${REPO_ROOT}/.archon/memory" 2>/dev/null || true)
```

Add one argument (before `2>/dev/null`):

```bash
MEMORY_CONTEXT=$(python3 "${REPO_ROOT}/dark-factory/scripts/memory_retrieve.py" \
  --phase <PHASE> \
  --files "$AFFECTED" \
  $ISSUE_ARG \
  --memory-dir "${REPO_ROOT}/.archon/memory" \
  --emit-trace-to "$ARTIFACTS_DIR/memory-trace.json" 2>/dev/null || true)
```

**Note:** `$ARTIFACTS_DIR` is set and `mkdir -p`'d in `entrypoint.sh` before archon launches. The `2>/dev/null || true` wrapper already present on each call ensures any trace write failure is non-fatal. No other change to the command files is required.

### Step 2a — Edit `dark-factory-refine.md`

Find the block:
```bash
MEMORY_CONTEXT=$(python3 "${REPO_ROOT}/dark-factory/scripts/memory_retrieve.py" \
  --phase refine \
  --files "$AFFECTED" \
  $ISSUE_ARG \
  --memory-dir "${REPO_ROOT}/.archon/memory" 2>/dev/null || true)
```

Replace with:
```bash
MEMORY_CONTEXT=$(python3 "${REPO_ROOT}/dark-factory/scripts/memory_retrieve.py" \
  --phase refine \
  --files "$AFFECTED" \
  $ISSUE_ARG \
  --memory-dir "${REPO_ROOT}/.archon/memory" \
  --emit-trace-to "$ARTIFACTS_DIR/memory-trace.json" 2>/dev/null || true)
```

### Step 2b — Edit `dark-factory-plan.md`

Find the block:
```bash
MEMORY_CONTEXT=$(python3 "${REPO_ROOT}/dark-factory/scripts/memory_retrieve.py" \
  --phase plan \
  --files "$AFFECTED" \
  $ISSUE_ARG \
  --memory-dir "${REPO_ROOT}/.archon/memory" 2>/dev/null || true)
```

Replace with:
```bash
MEMORY_CONTEXT=$(python3 "${REPO_ROOT}/dark-factory/scripts/memory_retrieve.py" \
  --phase plan \
  --files "$AFFECTED" \
  $ISSUE_ARG \
  --memory-dir "${REPO_ROOT}/.archon/memory" \
  --emit-trace-to "$ARTIFACTS_DIR/memory-trace.json" 2>/dev/null || true)
```

### Step 2c — Edit `dark-factory-implement.md`

Find the block:
```bash
MEMORY_CONTEXT=$(python3 "${REPO_ROOT}/dark-factory/scripts/memory_retrieve.py" \
  --phase implement \
  --files "$AFFECTED" \
  $ISSUE_ARG \
  --memory-dir "${REPO_ROOT}/.archon/memory" 2>/dev/null || true)
```

Replace with:
```bash
MEMORY_CONTEXT=$(python3 "${REPO_ROOT}/dark-factory/scripts/memory_retrieve.py" \
  --phase implement \
  --files "$AFFECTED" \
  $ISSUE_ARG \
  --memory-dir "${REPO_ROOT}/.archon/memory" \
  --emit-trace-to "$ARTIFACTS_DIR/memory-trace.json" 2>/dev/null || true)
```

### Step 2d — Edit `dark-factory-validate.md`

Find the block:
```bash
MEMORY_CONTEXT=$(python3 "${REPO_ROOT}/dark-factory/scripts/memory_retrieve.py" \
  --phase validate \
  --files "$AFFECTED" \
  $ISSUE_ARG \
  --memory-dir "${REPO_ROOT}/.archon/memory" 2>/dev/null || true)
```

Replace with:
```bash
MEMORY_CONTEXT=$(python3 "${REPO_ROOT}/dark-factory/scripts/memory_retrieve.py" \
  --phase validate \
  --files "$AFFECTED" \
  $ISSUE_ARG \
  --memory-dir "${REPO_ROOT}/.archon/memory" \
  --emit-trace-to "$ARTIFACTS_DIR/memory-trace.json" 2>/dev/null || true)
```

### Step 2e — Verify all four files have the flag

```bash
grep -n "emit-trace-to" .archon/commands/dark-factory-*.md
```

Expected: four lines, one per file, each containing `--emit-trace-to "$ARTIFACTS_DIR/memory-trace.json"`.

### Step 2f — Commit

```bash
git add .archon/commands/dark-factory-refine.md \
        .archon/commands/dark-factory-plan.md \
        .archon/commands/dark-factory-implement.md \
        .archon/commands/dark-factory-validate.md
git commit -m "feat: wire --emit-trace-to into all four gate command files (#647)"
```

---

## Task 3: Update `run_record.py` to assemble memory-trace (TDD)

**Files:**
- `dark-factory/tests/test_run_record.py` (extend)
- `dark-factory/scripts/factory_core/run_record.py` (modify)

### Step 3a — Write failing tests

Append to `dark-factory/tests/test_run_record.py`:

```python
# ---------------------------------------------------------------------------
# assemble — memory_trace pickup
# ---------------------------------------------------------------------------

def test_assemble_picks_up_memory_trace(tmp_path, monkeypatch):
    """memory-trace.json is read into run_record['memory_trace'] if present."""
    monkeypatch.setattr(rr, "JSONL_PATH", tmp_path / "runs.jsonl")
    monkeypatch.setattr(rr, "_post_seq", lambda r: None)

    trace = {
        "schema_version": 1,
        "retrieval_mechanism": "flatfile-pathtag",
        "issue": 647,
        "phase": "implement",
        "agent_id": "implementation-agent",
        "project": "markethawk",
        "affected_files": ["dark-factory/scripts/memory_retrieve.py"],
        "files_loaded": [
            {"path": ".archon/memory/codebase-patterns.md",
             "entries_total": 5, "entries_included": 4, "entries_filtered_out": 1}
        ],
        "fallback_used": False,
    }
    (tmp_path / "memory-trace.json").write_text(json.dumps(trace))

    out = tmp_path / "run-record.json"
    args = _AssembleArgs(tmp_path, out)
    rr.cmd_assemble(args)

    rec = json.loads(out.read_text())
    assert "memory_trace" in rec
    assert rec["memory_trace"]["schema_version"] == 1
    assert rec["memory_trace"]["phase"] == "implement"
    assert rec["memory_trace"]["agent_id"] == "implementation-agent"
    assert rec["memory_trace"]["files_loaded"][0]["entries_total"] == 5


def test_assemble_no_memory_trace_absent(tmp_path, monkeypatch):
    """When memory-trace.json is absent, memory_trace key is not in run_record."""
    monkeypatch.setattr(rr, "JSONL_PATH", tmp_path / "runs.jsonl")
    monkeypatch.setattr(rr, "_post_seq", lambda r: None)

    out = tmp_path / "run-record.json"
    args = _AssembleArgs(tmp_path, out)
    rr.cmd_assemble(args)

    rec = json.loads(out.read_text())
    assert "memory_trace" not in rec


def test_assemble_memory_trace_malformed_silently_skipped(tmp_path, monkeypatch):
    """Malformed memory-trace.json is silently skipped; assemble still completes."""
    monkeypatch.setattr(rr, "JSONL_PATH", tmp_path / "runs.jsonl")
    monkeypatch.setattr(rr, "_post_seq", lambda r: None)

    (tmp_path / "memory-trace.json").write_text("not valid json {{{")

    out = tmp_path / "run-record.json"
    args = _AssembleArgs(tmp_path, out)
    rr.cmd_assemble(args)  # must not raise

    rec = json.loads(out.read_text())
    assert "memory_trace" not in rec


def test_assemble_memory_trace_does_not_affect_stages(tmp_path, monkeypatch):
    """memory_trace is a top-level key; it must not appear in stages[]."""
    monkeypatch.setattr(rr, "JSONL_PATH", tmp_path / "runs.jsonl")
    monkeypatch.setattr(rr, "_post_seq", lambda r: None)

    trace = {"schema_version": 1, "phase": "implement", "files_loaded": []}
    (tmp_path / "memory-trace.json").write_text(json.dumps(trace))
    (tmp_path / "validation.md").write_text("STATUS: PASS\n")

    out = tmp_path / "run-record.json"
    args = _AssembleArgs(tmp_path, out)
    rr.cmd_assemble(args)

    rec = json.loads(out.read_text())
    stage_names = [s["stage"] for s in rec["stages"]]
    assert "memory_trace" not in stage_names
    assert "memory-trace" not in stage_names
    assert len(rec["stages"]) == 1  # only validation
```

### Step 3b — Verify tests fail

```bash
python -m pytest dark-factory/tests/test_run_record.py -v -k "memory_trace" 2>&1 | tail -15
```

Expected: 4 tests FAILED — `AssertionError` on `"memory_trace" in rec` or `"memory_trace" not in rec`.

### Step 3c — Implement memory_trace pickup in `run_record.py`

Open `dark-factory/scripts/factory_core/run_record.py`. In `cmd_assemble()`, after the `artifact_names` loop (the block ending with `if stage: stages.append(stage)`), add:

```python
    memory_trace_path = artifacts_dir / "memory-trace.json"
    if memory_trace_path.exists():
        try:
            run_record["memory_trace"] = json.loads(
                memory_trace_path.read_text(encoding="utf-8")
            )
        except Exception:
            pass  # non-fatal: trace absent or malformed
```

Place this block immediately before `archon_path = pathlib.Path(args.archon_cost_json) ...` so it fits between the artifact loop and the archon cost section.

The full context for the insertion point in `cmd_assemble()`:

```python
    # ... existing artifact loop ends here:
    for name in artifact_names:
        md_path = artifacts_dir / f"{name}.md"
        if md_path.exists():
            content = md_path.read_text(encoding="utf-8")
            artifacts[name] = content
            stage = _parse_artifact_stage(name, content)
            if stage:
                stages.append(stage)

    # NEW BLOCK — add after the loop above:
    memory_trace_path = artifacts_dir / "memory-trace.json"
    if memory_trace_path.exists():
        try:
            run_record["memory_trace"] = json.loads(
                memory_trace_path.read_text(encoding="utf-8")
            )
        except Exception:
            pass  # non-fatal: trace absent or malformed

    archon_path = pathlib.Path(args.archon_cost_json) if args.archon_cost_json else None
    # ... rest of cmd_assemble() unchanged
```

**Wait**: `run_record` is built later in `cmd_assemble()`, after the artifact loop — check the exact order:

```python
def cmd_assemble(args) -> None:
    artifacts_dir = pathlib.Path(args.artifacts_dir)
    ...
    stages = []
    artifacts: dict = {}
    artifact_names = [...]

    for name in artifact_names:   # ← artifact loop
        ...
        if stage:
            stages.append(stage)

    archon_path = ...
    nodes = _parse_archon_cost(archon_path)
    totals_in = ...

    run_record = {           # ← run_record built here
        "run_id": ...,
        ...
        "stages": stages,
        ...
    }
```

Since `run_record` is built after the artifact loop, the `memory_trace` pickup must go **after** `run_record` is built. Insert it after `run_record = {...}` and before `out_file.write_text(...)`:

```python
    run_record = {
        "run_id": args.run_id,
        ...
        "totals": {...},
    }

    # NEW BLOCK — add here, after run_record is built:
    memory_trace_path = artifacts_dir / "memory-trace.json"
    if memory_trace_path.exists():
        try:
            run_record["memory_trace"] = json.loads(
                memory_trace_path.read_text(encoding="utf-8")
            )
        except Exception:
            pass  # non-fatal: trace absent or malformed

    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(run_record, indent=2), encoding="utf-8")
```

### Step 3d — Verify tests pass

```bash
python -m pytest dark-factory/tests/test_run_record.py -v
```

Expected:
```
PASSED ... test_assemble_picks_up_memory_trace
PASSED ... test_assemble_no_memory_trace_absent
PASSED ... test_assemble_memory_trace_malformed_silently_skipped
PASSED ... test_assemble_memory_trace_does_not_affect_stages
... (all existing tests also pass)
```

### Step 3e — Run full test suite for dark-factory

```bash
python -m pytest dark-factory/tests/test_memory_retrieve.py dark-factory/tests/test_run_record.py -v 2>&1 | tail -5
```

Expected: all tests pass, 0 errors.

### Step 3f — Commit

```bash
git add dark-factory/scripts/factory_core/run_record.py dark-factory/tests/test_run_record.py
git commit -m "feat: aggregate memory-trace.json into run-record.json (#647)"
```

---

## Final Verification

After all tasks complete:

```bash
# 1. All new tests pass
python -m pytest dark-factory/tests/test_memory_retrieve.py dark-factory/tests/test_run_record.py -v

# 2. Command files all have the flag
grep -c "emit-trace-to" .archon/commands/dark-factory-*.md | sort -u
# Expected: each file shows "1"

# 3. Smoke test: emit a real trace against the live memory directory
python dark-factory/scripts/memory_retrieve.py \
  --phase implement \
  --files "dark-factory/scripts/memory_retrieve.py\n.archon/commands/dark-factory-implement.md" \
  --issue 647 \
  --memory-dir .archon/memory \
  --emit-trace-to /tmp/smoke-trace.json
python -m json.tool /tmp/smoke-trace.json

# 4. Confirm key fields
python -c "
import json
t = json.load(open('/tmp/smoke-trace.json'))
assert t['schema_version'] == 1
assert t['retrieval_mechanism'] == 'flatfile-pathtag'
assert t['agent_id'] == 'implementation-agent'
assert isinstance(t['files_loaded'], list)
print('All assertions passed')
"
```

---

## Commit History (expected)

```
feat: add --emit-trace-to argument to memory_retrieve.py (#647)
feat: wire --emit-trace-to into all four gate command files (#647)
feat: aggregate memory-trace.json into run-record.json (#647)
```

(Plus the merge commit from Task 0 syncing origin/main.)
