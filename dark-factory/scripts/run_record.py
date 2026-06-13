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
                        "gen_ai.operation.name",
                        f"stage.{record.get('stage', 'unknown')}",
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


def _iter_json_documents(text: str):
    """Yield each top-level JSON value in text (mirrors `jq -s`).

    `archon workflow cost --json` emits the run as a single PRETTY-PRINTED
    (multi-line, indent=2) object; `--quiet` suppresses its pino log lines.
    Parsing line-by-line breaks on the indented object — every fragment is
    invalid JSON — so decode the stream value-by-value with raw_decode and
    resync to the next line on any non-JSON noise (e.g. a leaked pino line).
    """
    decoder = json.JSONDecoder()
    i, n = 0, len(text)
    while i < n:
        while i < n and text[i] in " \t\r\n":
            i += 1
        if i >= n:
            break
        try:
            obj, end = decoder.raw_decode(text, i)
        except json.JSONDecodeError:
            nl = text.find("\n", i)
            if nl == -1:
                break
            i = nl + 1
            continue
        yield obj
        i = end


def _parse_archon_cost(path: pathlib.Path) -> list:
    """Map archon workflow cost JSON nodes to OTel field names."""
    if path is None or not path.exists():
        return []
    try:
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            return []
        run_obj = None
        for obj in _iter_json_documents(content):
            candidates = obj if isinstance(obj, list) else [obj]
            for cand in candidates:
                if isinstance(cand, dict) and (cand.get("run_id") or cand.get("runId")):
                    run_obj = cand
                    break
            if run_obj is not None:
                break
        if run_obj is None:
            return []

        nodes = []
        for n in run_obj.get("nodes") or []:
            model_usage = n.get("modelUsage") or n.get("model_usage") or {}
            raw_model = next(iter(model_usage.keys()), "")
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
            verdict = (
                "PASS" if "PASS" in content else ("FAIL" if "FAIL" in content else None)
            )

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
            verdict = (
                "PASS" if "PASS" in content else ("BLOCKED" if "BLOCKED" in content else None)
            )

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
