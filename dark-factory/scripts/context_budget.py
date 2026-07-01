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
            # memory-context.md is written inside the command session by memory_retrieve.py
            # (Phase 1 load). Budget node runs before the command, so it is always absent.
            # Correctly reports status="dropped", reason="empty_or_missing".
            sections[sec] = _included(_read_text(memory_file), memory_file)
            if memory_file and sections[sec]["status"] == "included":
                h = te.hash_file(memory_file)
                if h:
                    source_hashes["memory-context.md"] = h

        elif sec == "pr_reviews":
            sections[sec] = _probe_pr_reviews(issue_json)

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
            if impl_file and sections[sec]["status"] == "included":
                h = te.hash_file(impl_file)
                if h:
                    source_hashes["implementation.md"] = h

        elif sec == "diff":
            sections[sec] = _probe_diff(diff_file)
            if diff_file and sections[sec]["status"] in ("included", "included_partial"):
                h = te.hash_file(diff_file)
                if h:
                    source_hashes["diff"] = h

    estimated = sum(v.get("tokens", 0) for v in sections.values())
    utilization = round(estimated / BUDGET_TOKENS * 100, 1)

    included_sections = [k for k, v in sections.items() if v.get("status") in ("included", "included_partial")]
    dropped_sections = [k for k, v in sections.items() if v.get("status") == "dropped"]

    artifact = {
        "schema_version": 1,
        "scenario": scenario,
        "run_id": run_id,
        "issue_number": issue_num,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "budget_tokens": BUDGET_TOKENS,
        "estimated_input_tokens": estimated,
        "utilization_pct": utilization,
        "sections": sections,
        "included_sections": included_sections,
        "dropped_sections": dropped_sections,
        "source_file_hashes": source_hashes,
    }

    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Emit Dark Factory context budget telemetry.")
    parser.add_argument("--scenario", required=True,
                        choices=list(_SECTION_REGISTRY.keys()),
                        help="Phase scenario name")
    parser.add_argument("--issue-num", required=True, type=int)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--artifacts-dir", required=True)
    parser.add_argument("--clone-dir", required=True)
    parser.add_argument("--spec-file")
    parser.add_argument("--plan-file")
    parser.add_argument("--memory-file")
    parser.add_argument("--issue-json")
    parser.add_argument("--impl-file")
    parser.add_argument("--diff-file")
    parser.add_argument("--out", required=True,
                        help="Output path for context-budget.json")
    args = parser.parse_args()

    build_budget(
        scenario=args.scenario,
        issue_num=args.issue_num,
        run_id=args.run_id,
        artifacts_dir=args.artifacts_dir,
        clone_dir=args.clone_dir,
        out=args.out,
        spec_file=args.spec_file,
        plan_file=args.plan_file,
        memory_file=args.memory_file,
        issue_json=args.issue_json,
        impl_file=args.impl_file,
        diff_file=args.diff_file,
    )
    print(f"context-budget.json written to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
