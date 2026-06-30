import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from factory_core import run_record as rr


# ---------------------------------------------------------------------------
# record command
# ---------------------------------------------------------------------------

class _RecordArgs:
    run_id = "abc123"
    issue = 333
    intent = "new"
    stage = "conformance"
    verdict = "PASS"
    tokens_in = 1000
    tokens_out = 500
    cost_usd = 0.01
    duration_ms = 5000
    detail = ["cycles=2"]


def test_record_writes_jsonl(tmp_path, monkeypatch):
    jsonl = tmp_path / "runs.jsonl"
    monkeypatch.setattr(rr, "JSONL_PATH", jsonl)
    monkeypatch.setattr(rr, "_post_seq", lambda r: None)

    rr.cmd_record(_RecordArgs())

    lines = jsonl.read_text().strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["stage"] == "conformance"
    assert rec["verdict"] == "PASS"
    assert rec["gen_ai.usage.input_tokens"] == 1000
    assert rec["gen_ai.usage.output_tokens"] == 500
    assert rec["gen_ai.system"] == "dark-factory"
    assert rec["gen_ai.operation.name"] == "stage.conformance"
    assert rec["detail"]["cycles"] == 2


def test_record_appends_multiple(tmp_path, monkeypatch):
    jsonl = tmp_path / "runs.jsonl"
    monkeypatch.setattr(rr, "JSONL_PATH", jsonl)
    monkeypatch.setattr(rr, "_post_seq", lambda r: None)

    for verdict in ("PASS", "FAIL"):
        args = type("A", (), {**vars(_RecordArgs), "verdict": verdict})()
        rr.cmd_record(args)

    lines = jsonl.read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["verdict"] == "PASS"
    assert json.loads(lines[1])["verdict"] == "FAIL"


def test_record_detail_empty(tmp_path, monkeypatch):
    jsonl = tmp_path / "runs.jsonl"
    monkeypatch.setattr(rr, "JSONL_PATH", jsonl)
    monkeypatch.setattr(rr, "_post_seq", lambda r: None)

    args = type("A", (), {**vars(_RecordArgs), "detail": None})()
    rr.cmd_record(args)

    rec = json.loads(jsonl.read_text().strip())
    assert "detail" not in rec


def test_record_detail_float(tmp_path, monkeypatch):
    jsonl = tmp_path / "runs.jsonl"
    monkeypatch.setattr(rr, "JSONL_PATH", jsonl)
    monkeypatch.setattr(rr, "_post_seq", lambda r: None)

    args = type("A", (), {**vars(_RecordArgs), "detail": ["cost=1.23", "count=5"]})()
    rr.cmd_record(args)

    rec = json.loads(jsonl.read_text().strip())
    assert rec["detail"]["cost"] == pytest.approx(1.23)
    assert rec["detail"]["count"] == 5


def test_post_seq_is_nonfatal(tmp_path, monkeypatch):
    jsonl = tmp_path / "runs.jsonl"
    monkeypatch.setattr(rr, "JSONL_PATH", jsonl)
    monkeypatch.setattr(rr, "SEQ_URL", "http://unreachable-host-99999:5341")

    # Should not raise even when Seq is unreachable
    rr.cmd_record(_RecordArgs())
    assert jsonl.exists()


# ---------------------------------------------------------------------------
# _parse_archon_cost
# ---------------------------------------------------------------------------

def test_parse_archon_cost_basic(tmp_path):
    cost_json = tmp_path / "cost.json"
    cost_json.write_text(json.dumps({
        "runId": "xyz",
        "nodes": [
            {
                "nodeId": "implement",
                "inputTokens": 120000,
                "outputTokens": 52000,
                "costUsd": 0.34,
                "durationMs": 300000,
                "modelUsage": {"claude-sonnet-4-6-20251101": 1},
            }
        ],
        "totals": {"costUsd": 0.34, "inputTokens": 120000, "outputTokens": 52000},
    }))

    nodes = rr._parse_archon_cost(cost_json)
    assert len(nodes) == 1
    assert nodes[0]["node_id"] == "implement"
    assert nodes[0]["gen_ai.usage.input_tokens"] == 120000
    assert nodes[0]["gen_ai.usage.output_tokens"] == 52000
    assert nodes[0]["cost_usd"] == pytest.approx(0.34)
    assert nodes[0]["duration_ms"] == 300000
    assert nodes[0]["model"] == "sonnet-4-6"


def test_parse_archon_cost_missing_file(tmp_path):
    assert rr._parse_archon_cost(tmp_path / "nonexistent.json") == []


def test_parse_archon_cost_empty_file(tmp_path):
    f = tmp_path / "cost.json"
    f.write_text("")
    assert rr._parse_archon_cost(f) == []


# ---------------------------------------------------------------------------
# _parse_artifact_stage
# ---------------------------------------------------------------------------

def test_parse_artifact_validation_pass():
    stage = rr._parse_artifact_stage("validation", "STATUS: PASS\nSome detail\n")
    assert stage["stage"] == "validation"
    assert stage["verdict"] == "PASS"


def test_parse_artifact_validation_fail():
    stage = rr._parse_artifact_stage("validation", "STATUS: FAIL\nError details\n")
    assert stage["verdict"] == "FAIL"


def test_parse_artifact_conformance_with_cycles():
    content = "STATUS: PASS\nCYCLES: 2\nVERDICT: Approved\n"
    stage = rr._parse_artifact_stage("conformance", content)
    assert stage["verdict"] == "PASS"
    assert stage["cycles"] == 2


def test_parse_artifact_conformance_blocked():
    content = "⛔ Material divergence\n"
    stage = rr._parse_artifact_stage("conformance", content)
    assert stage["verdict"] == "BLOCKED"


def test_parse_artifact_review_with_blockers():
    content = "STATUS: PASS\nBLOCKERS: 0\nADVISORY: 3\n"
    stage = rr._parse_artifact_stage("review", content)
    assert stage["verdict"] == "PASS"
    assert stage["blockers"] == 0
    assert stage["advisory"] == 3


def test_parse_artifact_conflict_none():
    content = "CONFLICT_VERDICT=none\n"
    stage = rr._parse_artifact_stage("conflict_resolution", content)
    assert stage["verdict"] == "none"


def test_parse_artifact_conflict_resolved():
    content = "**Status:** RESOLVED\nBranch: feat/123\n"
    stage = rr._parse_artifact_stage("conflict_resolution", content)
    assert stage["verdict"] == "RESOLVED"


def test_parse_artifact_missing_returns_none():
    assert rr._parse_artifact_stage("validation", "") is None


# ---------------------------------------------------------------------------
# assemble command
# ---------------------------------------------------------------------------

class _AssembleArgs:
    run_id = "abc123"
    issue = 333
    intent = "new"
    started_at = "2026-06-12T04:00:00Z"
    archon_cost_json = None

    def __init__(self, artifacts_dir, out_file):
        self.artifacts_dir = str(artifacts_dir)
        self.out_file = str(out_file)


def test_assemble_builds_run_record(tmp_path, monkeypatch):
    monkeypatch.setattr(rr, "JSONL_PATH", tmp_path / "runs.jsonl")
    monkeypatch.setattr(rr, "_post_seq", lambda r: None)

    (tmp_path / "validation.md").write_text("STATUS: PASS\n")
    (tmp_path / "conformance.md").write_text("STATUS: PASS\nCYCLES: 1\n")
    (tmp_path / "review.md").write_text("STATUS: PASS\nBLOCKERS: 0\nADVISORY: 2\n")

    out = tmp_path / "run-record.json"
    args = _AssembleArgs(tmp_path, out)
    rr.cmd_assemble(args)

    assert out.exists()
    rec = json.loads(out.read_text())
    assert rec["run_id"] == "abc123"
    assert rec["issue_number"] == 333
    assert len(rec["stages"]) == 3
    stages_by_name = {s["stage"]: s for s in rec["stages"]}
    assert stages_by_name["validation"]["verdict"] == "PASS"
    assert stages_by_name["conformance"]["cycles"] == 1
    assert stages_by_name["review"]["blockers"] == 0
    assert rec["artifacts"]["validation"] == "STATUS: PASS\n"
    assert rec["started_at"] == "2026-06-12T04:00:00Z"
    assert rec["completed_at"]


def test_assemble_missing_artifacts_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(rr, "JSONL_PATH", tmp_path / "runs.jsonl")
    monkeypatch.setattr(rr, "_post_seq", lambda r: None)

    out = tmp_path / "run-record.json"
    args = _AssembleArgs(tmp_path, out)
    rr.cmd_assemble(args)

    rec = json.loads(out.read_text())
    assert rec["stages"] == []
    assert rec["artifacts"] == {}


def test_assemble_incorporates_archon_cost(tmp_path, monkeypatch):
    monkeypatch.setattr(rr, "JSONL_PATH", tmp_path / "runs.jsonl")
    monkeypatch.setattr(rr, "_post_seq", lambda r: None)

    cost_json = tmp_path / "cost.json"
    cost_json.write_text(json.dumps({
        "runId": "abc123",
        "nodes": [{"nodeId": "implement", "inputTokens": 100, "outputTokens": 50,
                   "costUsd": 0.01, "durationMs": 60000, "modelUsage": {}}],
        "totals": {"costUsd": 0.01, "inputTokens": 100, "outputTokens": 50},
    }))

    out = tmp_path / "run-record.json"
    args = _AssembleArgs(tmp_path, out)
    args.archon_cost_json = str(cost_json)
    rr.cmd_assemble(args)

    rec = json.loads(out.read_text())
    assert len(rec["nodes"]) == 1
    assert rec["nodes"][0]["gen_ai.usage.input_tokens"] == 100
    assert rec["totals"]["gen_ai.usage.input_tokens"] == 100
    assert rec["totals"]["cost_usd"] == pytest.approx(0.01)


def test_assemble_emits_jsonl_per_stage(tmp_path, monkeypatch):
    jsonl = tmp_path / "runs.jsonl"
    monkeypatch.setattr(rr, "JSONL_PATH", jsonl)
    monkeypatch.setattr(rr, "_post_seq", lambda r: None)

    (tmp_path / "validation.md").write_text("STATUS: PASS\n")
    (tmp_path / "conformance.md").write_text("STATUS: PASS\nCYCLES: 0\n")

    out = tmp_path / "run-record.json"
    args = _AssembleArgs(tmp_path, out)
    rr.cmd_assemble(args)

    lines = jsonl.read_text().strip().splitlines()
    assert len(lines) == 2
    stages = [json.loads(l)["stage"] for l in lines]
    assert "validation" in stages
    assert "conformance" in stages


# ── memory-trace pickup tests (issue #647) ─────────────────────────────────

def test_assemble_picks_up_memory_trace(tmp_path, monkeypatch):
    monkeypatch.setattr(rr, "JSONL_PATH", tmp_path / "runs.jsonl")
    monkeypatch.setattr(rr, "_post_seq", lambda r: None)

    trace = {
        "schema_version": 1,
        "retrieval_mechanism": "flatfile-pathtag",
        "phase": "implement",
        "affected_files": [],
        "files_loaded": [],
        "fallback_used": False,
    }
    (tmp_path / "memory-trace.json").write_text(json.dumps(trace))

    out = tmp_path / "run-record.json"
    args = _AssembleArgs(tmp_path, out)
    rr.cmd_assemble(args)

    rec = json.loads(out.read_text())
    assert "memory_trace" in rec
    assert rec["memory_trace"]["schema_version"] == 1
    assert rec["memory_trace"]["retrieval_mechanism"] == "flatfile-pathtag"


def test_assemble_no_memory_trace_key_when_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(rr, "JSONL_PATH", tmp_path / "runs.jsonl")
    monkeypatch.setattr(rr, "_post_seq", lambda r: None)

    out = tmp_path / "run-record.json"
    args = _AssembleArgs(tmp_path, out)
    rr.cmd_assemble(args)

    rec = json.loads(out.read_text())
    assert "memory_trace" not in rec


def test_assemble_tolerates_malformed_memory_trace(tmp_path, monkeypatch):
    monkeypatch.setattr(rr, "JSONL_PATH", tmp_path / "runs.jsonl")
    monkeypatch.setattr(rr, "_post_seq", lambda r: None)

    (tmp_path / "memory-trace.json").write_text("not valid json {{{")

    out = tmp_path / "run-record.json"
    args = _AssembleArgs(tmp_path, out)
    rr.cmd_assemble(args)  # must not raise

    rec = json.loads(out.read_text())
    assert "memory_trace" not in rec


def test_assemble_tolerates_unreadable_memory_trace(tmp_path, monkeypatch):
    monkeypatch.setattr(rr, "JSONL_PATH", tmp_path / "runs.jsonl")
    monkeypatch.setattr(rr, "_post_seq", lambda r: None)

    # Create a directory where the file is expected — causes read failure
    (tmp_path / "memory-trace.json").mkdir()

    out = tmp_path / "run-record.json"
    args = _AssembleArgs(tmp_path, out)
    rr.cmd_assemble(args)  # must not raise

    rec = json.loads(out.read_text())
    assert "memory_trace" not in rec
