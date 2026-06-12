# Run Record Module — Implementation Plan (issue #333)

**Goal**: Create `dark-factory/scripts/run_record.py` with `record` and `assemble` subcommands, wire it into `entrypoint.sh`, and add the required `docker-compose.yml` plumbing so every factory run produces one durable, queryable record.

**Architecture**: All changes are in the dark-factory layer (`scripts/`, `entrypoint.sh`, `docker-compose.yml`). No backend, frontend, or Alembic changes.

**Tech Stack**: Python 3.9+ stdlib (`json`, `urllib.request`, `fcntl`, `pathlib`, `argparse`, `uuid`), bash, Docker Compose.

---

## File Structure

| File | Action |
|------|--------|
| `dark-factory/scripts/run_record.py` | Create — Python CLI with `record` + `assemble` subcommands |
| `dark-factory/tests/test_run_record.py` | Create — pytest unit tests |
| `docker-compose.yml` | Modify — add `SEQ_URL` env + `scheduler_state` volume mount to `dark-factory` service |
| `dark-factory/entrypoint.sh` | Modify — hoist `ARTIFACTS_DIR`, generate `RUN_ID`, wire `on_failure` trap, wire `assemble` call, rewrite `post_cost_report()` |

---

## Task 1: Create `run_record.py` (TDD)

**Files**: `dark-factory/scripts/run_record.py`, `dark-factory/tests/test_run_record.py`

### Step 1.1 — Write failing tests

Create `dark-factory/tests/test_run_record.py`:

```python
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_record as rr


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
    # model name is stripped of prefix and date suffix
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
    # spec-required timestamps
    assert rec["started_at"] == "2026-06-12T04:00:00Z"
    assert rec["completed_at"]  # non-empty ISO string


def test_assemble_missing_artifacts_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(rr, "JSONL_PATH", tmp_path / "runs.jsonl")
    monkeypatch.setattr(rr, "_post_seq", lambda r: None)

    # No artifact files present
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
```

### Step 1.2 — Verify tests fail

```bash
cd /workspace/markethawk
python -m pytest dark-factory/tests/test_run_record.py -v 2>&1 | head -20
# Expected: ModuleNotFoundError: No module named 'run_record'
```

### Step 1.3 — Implement `run_record.py`

Create `dark-factory/scripts/run_record.py`:

```python
#!/usr/bin/env python3
"""
Dark factory run record — writes per-stage verdicts to runs.jsonl and Seq.

Two subcommands:
  record   — write one event line (called from entrypoint or on_failure trap)
  assemble — end-of-run aggregation from artifact files + archon cost JSON
"""

import argparse
import fcntl
import json
import os
import pathlib
import urllib.error
import urllib.request
from datetime import datetime, timezone

JSONL_PATH = pathlib.Path("/var/lib/dark-factory/runs.jsonl")
SEQ_URL = os.environ.get("SEQ_URL", "http://seq:5341")


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _append_jsonl(record: dict) -> None:
    JSONL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(JSONL_PATH, "a", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            fh.write(json.dumps(record) + "\n")
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _post_seq(record: dict) -> None:
    payload = {
        "Events": [
            {
                "Timestamp": record.get("timestamp", _timestamp()),
                "Level": "Information",
                "MessageTemplate": (
                    "factory.stage.{Stage} verdict={Verdict} issue=#{IssueNumber}"
                ),
                "Properties": {
                    "gen_ai.system": record.get("gen_ai.system", "dark-factory"),
                    "gen_ai.operation.name": record.get(
                        "gen_ai.operation.name", f"stage.{record.get('stage', 'unknown')}"
                    ),
                    "gen_ai.usage.input_tokens": record.get(
                        "gen_ai.usage.input_tokens", 0
                    ),
                    "gen_ai.usage.output_tokens": record.get(
                        "gen_ai.usage.output_tokens", 0
                    ),
                    "Stage": record.get("stage", ""),
                    "Verdict": record.get("verdict", ""),
                    "IssueNumber": record.get("issue_number", 0),
                    "Intent": record.get("intent", ""),
                    "RunId": record.get("run_id", ""),
                    "CostUsd": record.get("cost_usd", 0),
                    "DurationMs": record.get("duration_ms", 0),
                },
            }
        ]
    }
    endpoint = f"{SEQ_URL.rstrip('/')}/api/events/raw"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        endpoint, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            resp.read()
    except Exception:
        pass  # non-fatal: local file was already written


def cmd_record(args) -> None:
    details: dict = {}
    for kv in args.detail or []:
        k, _, v = kv.partition("=")
        if v.isdigit():
            details[k] = int(v)
        else:
            try:
                details[k] = float(v)
            except ValueError:
                details[k] = v

    record: dict = {
        "run_id": args.run_id,
        "issue_number": args.issue,
        "intent": args.intent,
        "stage": args.stage,
        "verdict": args.verdict,
        "gen_ai.system": "dark-factory",
        "gen_ai.operation.name": f"stage.{args.stage}",
        "gen_ai.usage.input_tokens": args.tokens_in or 0,
        "gen_ai.usage.output_tokens": args.tokens_out or 0,
        "cost_usd": args.cost_usd or 0.0,
        "duration_ms": args.duration_ms or 0,
        "timestamp": _timestamp(),
    }
    if details:
        record["detail"] = details

    _append_jsonl(record)
    _post_seq(record)


def _parse_archon_cost(path: pathlib.Path) -> list:
    """Map archon workflow cost JSON nodes to OTel field names."""
    if path is None or not path.exists():
        return []
    try:
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            return []
        # archon may emit ndjson; find first line with runId/run_id
        run_obj = None
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict) and (obj.get("run_id") or obj.get("runId")):
                    run_obj = obj
                    break
            except json.JSONDecodeError:
                continue
        if run_obj is None:
            return []

        nodes = []
        for n in run_obj.get("nodes") or []:
            model_usage = n.get("modelUsage") or n.get("model_usage") or {}
            raw_model = next(iter(model_usage.keys()), "")
            # strip "claude-" prefix and "-YYYYMMDD" date suffix
            if raw_model.startswith("claude-"):
                raw_model = raw_model[len("claude-"):]
            if "-20" in raw_model:
                raw_model = raw_model[: raw_model.index("-20")]
            nodes.append(
                {
                    "node_id": n.get("nodeId") or n.get("node_id", ""),
                    "model": raw_model,
                    "gen_ai.usage.input_tokens": (
                        n.get("inputTokens") or n.get("input_tokens") or 0
                    ),
                    "gen_ai.usage.output_tokens": (
                        n.get("outputTokens") or n.get("output_tokens") or 0
                    ),
                    "cost_usd": n.get("costUsd") or n.get("cost_usd") or 0,
                    "duration_ms": n.get("durationMs") or n.get("duration_ms") or 0,
                }
            )
        return nodes
    except Exception:
        return []


def _parse_artifact_stage(name: str, content: str) -> "dict | None":
    """Extract stage verdict and metadata from a verdict artifact .md file."""
    if not content.strip():
        return None

    lines = content.splitlines()
    verdict = None
    detail: dict = {}

    if name == "validation":
        for line in lines:
            if line.startswith("STATUS:"):
                verdict = line.split(":", 1)[1].strip()
                break
        if verdict is None:
            verdict = "PASS" if "PASS" in content else ("FAIL" if "FAIL" in content else None)

    elif name == "conformance":
        for line in lines:
            if line.startswith("STATUS:"):
                verdict = line.split(":", 1)[1].strip()
            elif line.startswith("CYCLES:"):
                try:
                    detail["cycles"] = int(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
        if verdict is None:
            if "⛔" in content:
                verdict = "BLOCKED"
            elif "Conforms" in content or "Minor" in content or "PASS" in content:
                verdict = "PASS"

    elif name == "review":
        for line in lines:
            if line.startswith("STATUS:"):
                verdict = line.split(":", 1)[1].strip()
            elif line.startswith("BLOCKERS:"):
                try:
                    detail["blockers"] = int(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
            elif line.startswith("ADVISORY:"):
                try:
                    detail["advisory"] = int(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
        if verdict is None:
            verdict = "PASS" if "PASS" in content else ("BLOCKED" if "BLOCKED" in content else None)

    elif name == "conflict_resolution":
        for line in lines:
            if line.startswith("CONFLICT_VERDICT="):
                verdict = line.split("=", 1)[1].strip()
                break
            if "**Status:**" in line:
                verdict = line.split("**Status:**", 1)[1].strip().strip("*").strip()
                break
        if verdict is None:
            verdict = "RESOLVED" if "RESOLVED" in content else "none"

    if verdict is None:
        return None

    result: dict = {"stage": name, "verdict": verdict}
    result.update(detail)
    return result


def cmd_assemble(args) -> None:
    artifacts_dir = pathlib.Path(args.artifacts_dir)
    out_file = pathlib.Path(args.out_file)

    stages = []
    artifacts: dict = {}
    artifact_names = ["validation", "conformance", "review", "conflict_resolution"]

    for name in artifact_names:
        md_path = artifacts_dir / f"{name}.md"
        if md_path.exists():
            content = md_path.read_text(encoding="utf-8")
            artifacts[name] = content
            stage = _parse_artifact_stage(name, content)
            if stage:
                stages.append(stage)

    archon_path = pathlib.Path(args.archon_cost_json) if args.archon_cost_json else None
    nodes = _parse_archon_cost(archon_path)

    totals_in = sum(n.get("gen_ai.usage.input_tokens", 0) for n in nodes)
    totals_out = sum(n.get("gen_ai.usage.output_tokens", 0) for n in nodes)
    totals_cost = sum(n.get("cost_usd", 0) for n in nodes)

    run_record = {
        "run_id": args.run_id,
        "issue_number": args.issue,
        "intent": args.intent,
        "started_at": args.started_at or _timestamp(),
        "completed_at": _timestamp(),
        "status": "completed",
        "stages": stages,
        "nodes": nodes,
        "artifacts": artifacts,
        "totals": {
            "gen_ai.usage.input_tokens": totals_in,
            "gen_ai.usage.output_tokens": totals_out,
            "cost_usd": totals_cost,
        },
    }

    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(run_record, indent=2), encoding="utf-8")

    ts = _timestamp()
    for stage in stages:
        record: dict = {
            "run_id": args.run_id,
            "issue_number": args.issue,
            "intent": args.intent,
            "stage": stage["stage"],
            "verdict": stage["verdict"],
            "gen_ai.system": "dark-factory",
            "gen_ai.operation.name": f"stage.{stage['stage']}",
            "gen_ai.usage.input_tokens": 0,
            "gen_ai.usage.output_tokens": 0,
            "cost_usd": 0.0,
            "duration_ms": 0,
            "timestamp": ts,
        }
        extra = {k: v for k, v in stage.items() if k not in ("stage", "verdict")}
        if extra:
            record["detail"] = extra
        _append_jsonl(record)
        _post_seq(record)


def main() -> None:
    parser = argparse.ArgumentParser(description="Dark factory run record")
    sub = parser.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("record", help="Write one stage event")
    r.add_argument("--run-id", required=True)
    r.add_argument("--issue", type=int, required=True)
    r.add_argument("--intent", required=True)
    r.add_argument("--stage", required=True)
    r.add_argument("--verdict", required=True)
    r.add_argument("--tokens-in", type=int, default=0)
    r.add_argument("--tokens-out", type=int, default=0)
    r.add_argument("--cost-usd", type=float, default=0.0)
    r.add_argument("--duration-ms", type=int, default=0)
    r.add_argument("--detail", nargs="*", metavar="KEY=VAL")

    a = sub.add_parser("assemble", help="Assemble end-of-run record from artifacts")
    a.add_argument("--run-id", required=True)
    a.add_argument("--issue", type=int, required=True)
    a.add_argument("--intent", required=True)
    a.add_argument("--started-at", default="")
    a.add_argument("--artifacts-dir", required=True)
    a.add_argument("--archon-cost-json")
    a.add_argument("--out-file", required=True)

    parsed = parser.parse_args()
    if parsed.cmd == "record":
        cmd_record(parsed)
    elif parsed.cmd == "assemble":
        cmd_assemble(parsed)


if __name__ == "__main__":
    main()
```

### Step 1.4 — Verify tests pass

```bash
cd /workspace/markethawk
python -m pytest dark-factory/tests/test_run_record.py -v
# Expected: all tests pass
```

### Step 1.5 — Commit

```bash
git add dark-factory/scripts/run_record.py dark-factory/tests/test_run_record.py
git commit -m "feat(factory): add run_record.py with record + assemble subcommands

Writes per-stage verdicts to /var/lib/dark-factory/runs.jsonl (flock'd)
and POSTs to Seq raw events API using gen_ai.* OTel attribute names.
The assemble command folds verdict artifact files into a per-run
run-record.json and emits one jsonl line per stage.

Closes #333 (partial — entrypoint wiring in subsequent tasks)"
```

---

## Task 2: Update `docker-compose.yml`

**Files**: `docker-compose.yml`

### Step 2.1 — Write failing test (shell smoke check)

```bash
# Verify the dark-factory service currently lacks SEQ_URL and the volume mount
grep -A 20 "dark-factory:" docker-compose.yml | grep "SEQ_URL"
# Expected: no output (does not exist yet)
grep -A 20 "dark-factory:" docker-compose.yml | grep "scheduler_state"
# Expected: no output
```

### Step 2.2 — Add `SEQ_URL` env + volume mount to `dark-factory` service

Find the `dark-factory:` service block (around line 437). Add `SEQ_URL` to the `environment:` section and add a `volumes:` section with the named volume mount.

Current `dark-factory` service environment block (lines ~446-449):
```yaml
    environment:
      DOCKER_HOST: tcp://docker-socket-proxy:2375
```

Replace with:
```yaml
    environment:
      DOCKER_HOST: tcp://docker-socket-proxy:2375
      SEQ_URL: http://seq:5341
    volumes:
      - scheduler_state:/var/lib/dark-factory
```

After this change the `dark-factory` service block should look like:
```yaml
  dark-factory:
    image: ghcr.io/omniscient/markethawk-dark-factory:${IMAGE_TAG:-latest}
    build:
      context: .
      dockerfile: dark-factory/Dockerfile
    container_name: markethawk-dark-factory
    env_file:
      - path: .archon/.env
        required: true
    environment:
      DOCKER_HOST: tcp://docker-socket-proxy:2375
      SEQ_URL: http://seq:5341
    volumes:
      - scheduler_state:/var/lib/dark-factory
    depends_on:
      - docker-socket-proxy
    networks:
      - factory-network
      - stockscanner-network
    logging:
      driver: gelf
      options:
        gelf-address: "udp://host.docker.internal:12201"
        tag: "dark-factory"
    profiles:
      - factory
```

### Step 2.3 — Verify

```bash
grep -A 25 "dark-factory:" docker-compose.yml | grep -E "SEQ_URL|scheduler_state"
# Expected:
#       SEQ_URL: http://seq:5341
#       - scheduler_state:/var/lib/dark-factory

# Validate docker-compose YAML syntax
docker compose config --quiet 2>&1 | head -5
# Expected: no errors
```

### Step 2.4 — Commit

```bash
git add docker-compose.yml
git commit -m "feat(factory): add SEQ_URL env + named-volume mount to dark-factory service

Gives the factory container access to the durable /var/lib/dark-factory/
named volume (shared with backlog-scheduler) and the Seq URL for
run_record.py to POST structured events."
```

---

## Task 3: Hoist `ARTIFACTS_DIR` + generate `RUN_ID` in `entrypoint.sh`

**Files**: `dark-factory/entrypoint.sh`

### Step 3.1 — Locate the insertion point

The hoisted variables belong after the `INTENT` parse block (line ~52) and before the concurrency guard (line ~54), so they are available for all subsequent code including `on_failure`.

Current block (lines 50-53):
```bash
ISSUE_NUM=$(echo "$ARGUMENTS" | grep -oP '#\K\d+' | head -1)
INTENT=$(echo "$ARGUMENTS" | grep -oiP '^\s*\K(fix|continue|close|refine|plan|deconflict)' | head -1 | tr '[:upper:]' '[:lower:]')
INTENT=${INTENT:-fix}
```

### Step 3.2 — Add `RUN_ID` + `ARTIFACTS_DIR` canonical export

Insert the following block immediately after `INTENT=${INTENT:-fix}` (line 52):

```bash
# --- Canonical run identity and artifact directory ---
# ARCHON_RUN_ID is not set by archon; always generate a UUID for correlation.
RUN_ID=$(python3 -c 'import uuid; print(uuid.uuid4().hex)')
RUN_STARTED_AT=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
ARTIFACTS_DIR="${HOME}/.archon/workspaces/omniscient/markethawk/artifacts/runs/${RUN_ID}"
export ARTIFACTS_DIR
mkdir -p "$ARTIFACTS_DIR"
```

**Why `export ARTIFACTS_DIR` propagates to DAG nodes**: archon node `bash:` blocks are standard subprocess forks — they inherit the parent process environment. Confirmed by `fetch-issue` in `archon-dark-factory.yaml` (line 122) using `$ARTIFACTS_DIR` with no `:-` fallback: if archon were injecting its own value, this node would override it. The `:-` fallback in `de-conflict` (line 369) and `preview-up-resolve` (line 751) is a safety guard for runs that do NOT go through `entrypoint.sh`, not evidence archon overrides the exported value.

### Step 3.3 — Remove local `DECONFLICT_ARTIFACTS_DIR` definition and use canonical `ARTIFACTS_DIR`

The `deconflict` path currently defines its own `DECONFLICT_ARTIFACTS_DIR` (lines 592-594). Replace both those lines with the canonical variable:

```bash
# Before (lines 592-594):
  DECONFLICT_ARTIFACTS_DIR="${HOME}/.archon/workspaces/omniscient/markethawk/artifacts"
  mkdir -p "$DECONFLICT_ARTIFACTS_DIR"
  cat > "$DECONFLICT_ARTIFACTS_DIR/conflict_resolution.md" << EOF

# After:
  cat > "$ARTIFACTS_DIR/conflict_resolution.md" << EOF
```

### Step 3.4 — Verify

```bash
bash -n dark-factory/entrypoint.sh
# Expected: no output (bash syntax OK)

grep -n "ARTIFACTS_DIR\|RUN_ID\|RUN_STARTED_AT" dark-factory/entrypoint.sh
# Expected:
# ~54: RUN_ID=$(python3 -c 'import uuid; print(uuid.uuid4().hex)')
# ~55: RUN_STARTED_AT=$(date -u ...)
# ~56: ARTIFACTS_DIR="..."
# ~57: export ARTIFACTS_DIR
# ~58: mkdir -p "$ARTIFACTS_DIR"
# ~595: cat > "$ARTIFACTS_DIR/conflict_resolution.md" << EOF
```

### Step 3.5 — Commit

```bash
git add dark-factory/entrypoint.sh
git commit -m "refactor(factory): hoist ARTIFACTS_DIR to canonical export in entrypoint.sh

Generates RUN_ID (UUID) early in the script so run_record.py,
post_cost_report(), and DAG nodes share one artifact path.
Removes the local DECONFLICT_ARTIFACTS_DIR alias."
```

---

## Task 4: Wire `on_failure` trap → partial-failure record

**Files**: `dark-factory/entrypoint.sh`

### Step 4.1 — Locate insertion point

The `on_failure` function starts at line 237. The partial-failure record call should be the first action in the function body, before the GitHub comment logic, so that even if comment posting fails the record is still written.

Current start of `on_failure` (lines 237-240):
```bash
on_failure() {
  local EXIT_CODE=$?
  if [ -n "${ISSUE_NUM:-}" ] && [ "$INTENT" != "close" ]; then
    if [ "$INTENT" = "refine" ] || ...
```

### Step 4.2 — Insert partial-failure record call

Add these lines immediately after `local EXIT_CODE=$?`:

```bash
  # Capture partial-failure record before any other action (non-fatal)
  python3 "$CLONE_DIR/dark-factory/scripts/run_record.py" record \
    --run-id "${RUN_ID:-unknown}" \
    --issue "${ISSUE_NUM:-0}" \
    --intent "${INTENT:-unknown}" \
    --stage "failed" \
    --verdict "failed" || true
```

### Step 4.3 — Verify

```bash
bash -n dark-factory/entrypoint.sh
# Expected: no errors

grep -n "run_record.py record" dark-factory/entrypoint.sh
# Expected: line in on_failure and (after Task 5) line at end of file
```

### Step 4.4 — Commit

```bash
git add dark-factory/entrypoint.sh
git commit -m "feat(factory): wire on_failure trap to run_record.py partial-failure record

Ensures every failed run produces a runs.jsonl entry even when the
container exits before the success path assemble step runs."
```

---

## Task 5: Wire `assemble` + archon cost capture after successful run

**Files**: `dark-factory/entrypoint.sh`

### Step 5.1 — Locate insertion point

The insertion point is the **last line of the file**: the standalone `post_cost_report || true` call (currently line 673). This is unambiguous — anchor to this exact line, not to any `done` token (there are two: the inner file-loop done at line 456 and the archon-retry-loop done at line 670).

Current last two lines of the file:
```bash
# --- Post cost report to GitHub issue (success path) — non-fatal ---
post_cost_report || true
```

### Step 5.2 — Insert archon cost capture + assemble call

Replace the comment + `post_cost_report` line with:

```bash
# --- Capture archon cost data and assemble run record (non-fatal) ---
ARCHON_COST_JSON=$(mktemp)
archon workflow cost --last --json --quiet > "$ARCHON_COST_JSON" 2>/dev/null || true

python3 "$CLONE_DIR/dark-factory/scripts/run_record.py" assemble \
  --run-id "${RUN_ID:-unknown}" \
  --issue "$ISSUE_NUM" \
  --intent "$INTENT" \
  --started-at "${RUN_STARTED_AT:-}" \
  --artifacts-dir "$ARTIFACTS_DIR" \
  --archon-cost-json "$ARCHON_COST_JSON" \
  --out-file "$ARTIFACTS_DIR/run-record.json" || true

rm -f "$ARCHON_COST_JSON"

# --- Post cost report to GitHub issue (success path) — non-fatal ---
post_cost_report || true
```

### Step 5.3 — Verify

```bash
bash -n dark-factory/entrypoint.sh
# Expected: no errors

grep -n "assemble\|ARCHON_COST_JSON" dark-factory/entrypoint.sh
# Expected: the three blocks added above, no other occurrences
```

### Step 5.4 — Commit

```bash
git add dark-factory/entrypoint.sh
git commit -m "feat(factory): wire assemble call and archon cost capture after successful run

Calls 'run_record.py assemble' with all verdict artifact files and archon
cost JSON to produce ARTIFACTS_DIR/run-record.json. Both steps are
non-fatal; runs.jsonl and Seq always receive the stage records."
```

---

## Task 6: Rewrite `post_cost_report()` to read from `run-record.json`

**Files**: `dark-factory/entrypoint.sh`

### Step 6.1 — Write regression check

```bash
# Before editing, record current comment format expectations:
grep -c "COST_MARKER\|cumulative:\|fmt_tokens\|RUN_ROWS" dark-factory/entrypoint.sh
# Expected: these markers remain in the new implementation
```

### Step 6.2 — Replace `post_cost_report()` body

The new implementation reads `$ARTIFACTS_DIR/run-record.json` instead of calling `archon workflow cost --last --json`. The comment format (cumulative totals, hidden HTML markers, per-run markdown table) is unchanged.

Replace the entire `post_cost_report()` function body (lines 117-234) with:

```bash
post_cost_report() {
  if [ -z "${ISSUE_NUM:-}" ]; then return; fi
  local RUN_RECORD_FILE="${ARTIFACTS_DIR:-}/run-record.json"
  if [ ! -f "$RUN_RECORD_FILE" ]; then return; fi

  echo "Posting cost report to issue #${ISSUE_NUM}..."

  # Extract totals and status from run-record.json
  local RUN_STATUS TOTAL_COST TOTAL_IN TOTAL_OUT
  RUN_STATUS=$(jq -r '.status // "completed"' "$RUN_RECORD_FILE" 2>/dev/null || echo "unknown")
  TOTAL_COST=$(jq -r '.totals.cost_usd // 0' "$RUN_RECORD_FILE" 2>/dev/null || echo "0")
  TOTAL_IN=$(jq -r '.totals["gen_ai.usage.input_tokens"] // 0' "$RUN_RECORD_FILE" 2>/dev/null || echo "0")
  TOTAL_OUT=$(jq -r '.totals["gen_ai.usage.output_tokens"] // 0' "$RUN_RECORD_FILE" 2>/dev/null || echo "0")

  # Build per-node table rows from nodes[] (OTel field names, model pre-stripped)
  local RUN_ROWS TIMESTAMP
  TIMESTAMP=$(date -u +"%Y-%m-%d %H:%M UTC")
  RUN_ROWS=$(jq -r '
    def fmt_tokens: if . >= 1000000 then "\(. / 1000000 * 10 | round / 10)M"
                    elif . >= 1000 then "\(. / 1000 * 10 | round / 10)K"
                    else "\(.)" end;
    def fmt_dur: if . < 1000 then "\(.)ms"
                 elif . < 60000 then "\(. / 100 | round / 10)s"
                 else "\(. / 60000 | floor)m \((. % 60000 / 1000) | round)s" end;
    def fmt_cost: "$\(. * 10000 | round / 10000)";
    (.nodes // [])[] |
    "| \(.node_id) | \(.model // "") | \((.["gen_ai.usage.input_tokens"] // 0) | fmt_tokens) | \((.["gen_ai.usage.output_tokens"] // 0) | fmt_tokens) | \((.cost_usd // 0) | fmt_cost) | \((.duration_ms // 0) | fmt_dur) |"
  ' "$RUN_RECORD_FILE" 2>/dev/null || true)

  if [ -z "$RUN_ROWS" ]; then return; fi

  # Find existing cost report comment by marker
  local COMMENT_ID
  COMMENT_ID=$(gh api "repos/omniscient/markethawk/issues/${ISSUE_NUM}/comments" \
    --jq "[.[] | select(.body | contains(\"$COST_MARKER\"))] | last | .id // empty" 2>/dev/null || true)

  # If there's an existing comment, extract prior run sections and cumulative totals
  local PRIOR_RUNS="" PREV_COST="0" PREV_IN="0" PREV_OUT="0"
  if [ -n "$COMMENT_ID" ]; then
    local EXISTING_BODY
    EXISTING_BODY=$(gh api "repos/omniscient/markethawk/issues/comments/${COMMENT_ID}" \
      --jq '.body' 2>/dev/null || true)
    PRIOR_RUNS=$(echo "$EXISTING_BODY" | sed -n '/^### Run:/,/^---$/p' | head -n -1 || true)
    PREV_COST=$(echo "$EXISTING_BODY" | grep -oP '<!-- cumulative: cost=\K[0-9.]+' || echo "0")
    PREV_IN=$(echo "$EXISTING_BODY" | grep -oP '<!-- cumulative: cost=[0-9.]+ in=\K[0-9]+' || echo "0")
    PREV_OUT=$(echo "$EXISTING_BODY" | grep -oP '<!-- cumulative: cost=[0-9.]+ in=[0-9]+ out=\K[0-9]+' || echo "0")
  fi

  # Calculate cumulative totals
  local CUM_COST CUM_IN CUM_OUT
  CUM_COST=$(echo "$PREV_COST + $TOTAL_COST" | bc)
  CUM_IN=$(( PREV_IN + TOTAL_IN ))
  CUM_OUT=$(( PREV_OUT + TOTAL_OUT ))
  local RUN_COUNT
  RUN_COUNT=$(echo "$PRIOR_RUNS" | grep -c '^### Run:' || true)
  RUN_COUNT=$(( ${RUN_COUNT:-0} + 1 ))

  fmt_tokens() {
    local n=$1
    if [ "$n" -ge 1000000 ]; then
      echo "$(echo "scale=1; $n / 1000000" | bc)M"
    elif [ "$n" -ge 1000 ]; then
      echo "$(echo "scale=1; $n / 1000" | bc)K"
    else
      echo "$n"
    fi
  }

  # Build the full comment body (same format as before)
  local BODY
  BODY="${COST_MARKER}
<!-- cumulative: cost=${CUM_COST} in=${CUM_IN} out=${CUM_OUT} -->
## Dark Factory — Cost Report

**${RUN_COUNT} run(s) — Total: \$${CUM_COST} ($(fmt_tokens "$CUM_IN") in / $(fmt_tokens "$CUM_OUT") out)**

${PRIOR_RUNS}
### Run: ${TIMESTAMP} (${INTENT:-fix}, ${RUN_STATUS})

| Step | Model | In tokens | Out tokens | Cost | Duration |
|------|-------|-----------|------------|------|----------|
${RUN_ROWS}
| **Subtotal** | | **$(fmt_tokens "$TOTAL_IN")** | **$(fmt_tokens "$TOTAL_OUT")** | **\$${TOTAL_COST}** | |

---
*Updated by MarketHawk Dark Factory*"

  # Create or update the comment
  local TMPFILE
  TMPFILE=$(mktemp /tmp/cost-report-XXXXXX.md)
  echo "$BODY" > "$TMPFILE"

  if [ -n "$COMMENT_ID" ]; then
    if ! gh api "repos/omniscient/markethawk/issues/comments/${COMMENT_ID}" \
        --method PATCH -F "body=@${TMPFILE}" >/dev/null; then
      echo "WARNING: Could not update cost report comment ${COMMENT_ID}"
    fi
  else
    gh issue comment "$ISSUE_NUM" --body-file "$TMPFILE" 2>/dev/null \
      || echo "WARNING: Could not post cost report"
  fi
  rm -f "$TMPFILE"
}
```

### Step 6.3 — Verify

```bash
bash -n dark-factory/entrypoint.sh
# Expected: no errors

# Confirm the old archon workflow cost call is gone from post_cost_report
grep -n "archon workflow cost" dark-factory/entrypoint.sh
# Expected: only the new capture line outside post_cost_report (Task 5 addition)
# i.e. NOT inside the post_cost_report() function

# Confirm run-record.json is the data source
grep -n "run-record.json" dark-factory/entrypoint.sh
# Expected: 2 lines — assemble --out-file and post_cost_report read
```

### Step 6.4 — Run existing cost report shell tests

```bash
cd /workspace/markethawk
bash dark-factory/tests/test_cost_report_endpoint.sh 2>&1 | tail -10
# Expected: all assertions pass
```

### Step 6.5 — Commit

```bash
git add dark-factory/entrypoint.sh
git commit -m "feat(factory): rewrite post_cost_report() to read from run-record.json

Removes the direct 'archon workflow cost --last --json' call from
post_cost_report(). The function now reads token/cost data from
\$ARTIFACTS_DIR/run-record.json (assembled by run_record.py assemble).
Comment format (cumulative totals, HTML markers, per-run table) is
unchanged. Closes #333."
```

---

## Summary

| Task | Files | Steps |
|------|-------|-------|
| 1. Create `run_record.py` | `scripts/run_record.py`, `tests/test_run_record.py` | 5 |
| 2. Update `docker-compose.yml` | `docker-compose.yml` | 4 |
| 3. Hoist `ARTIFACTS_DIR` | `entrypoint.sh` | 5 |
| 4. Wire `on_failure` trap | `entrypoint.sh` | 4 |
| 5. Wire `assemble` call | `entrypoint.sh` | 4 |
| 6. Rewrite `post_cost_report()` | `entrypoint.sh` | 5 |

**Total: 6 tasks, 27 steps**

### Memory lessons applied

- `dark-factory-ops.md` [PATTERN]: `runs.jsonl` stored in `/var/lib/dark-factory/` (named volume), never in `$ARTIFACTS_DIR` — baked into Task 2 (volume mount) and Task 1 (`JSONL_PATH` constant).
- `dark-factory-ops.md` [AVOID]: No GELF/stdout for Seq; direct HTTP POST to `api/events/raw` with `{"Events":[...]}` envelope — baked into `_post_seq()` in Task 1.
- Spec constraint R7 (non-fatal Seq, local write first): `_append_jsonl` runs before `_post_seq`; exceptions from `_post_seq` are silently swallowed.
- Spec constraint R8 (atomic appends with `fcntl.flock`): implemented in `_append_jsonl` with `LOCK_EX`.
- `ARCHON_RUN_ID` is confirmed absent (grep finds no occurrence in the repo); `RUN_ID` is always a fresh UUID generated by `python3 -c 'import uuid; ...'` in Task 3. Tasks 4 and 5 reference `${RUN_ID:-unknown}` as a safety guard since `on_failure` can fire before Task 3 has run.
