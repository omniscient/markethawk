"""CLI: assemble Dark Factory scenario context packs.

Produces:
  context-pack.md   — prompt-ready assembled content with ## <section_key> headers
  context-pack.json — manifest with token budget, per-section status, over_budget flag

Usage:
  python3 context_pack.py --scenario implement --issue-num 42 --run-id abc123 \
    --artifacts-dir /tmp/artifacts/42 --clone-dir /workspace/markethawk \
    --issue-json /tmp/artifacts/42/issue.json \
    --memory-file /tmp/artifacts/42/memory-context.md
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
from context_budget import (
    _SECTION_REGISTRY,
    BUDGET_TOKENS,
    DIFF_LINE_CAP,
    _read_text,
    _SKILL_PROMPT_DIR,
    _SKILL_PROMPT_FILES,
)


def _included(text: str | None, file_path: str | None = None) -> tuple[dict, str | None]:
    if not text or not text.strip():
        return {"status": "dropped", "tokens": 0, "reason": "empty_or_missing"}, None
    entry: dict = {"status": "included", "tokens": te.estimate_tokens(text)}
    if file_path:
        h = te.hash_file(file_path)
        if h:
            entry["file_hash"] = h
    return entry, text


def _dropped(reason: str) -> tuple[dict, None]:
    return {"status": "dropped", "tokens": 0, "reason": reason}, None


def _read_skill_prompts() -> tuple[dict, str | None]:
    parts = []
    for name in _SKILL_PROMPT_FILES:
        txt = _read_text(os.path.join(_SKILL_PROMPT_DIR, name))
        if txt:
            parts.append(txt)
    if not parts:
        return {"status": "dropped", "tokens": 0, "reason": "container_mounted_not_found"}, None
    combined = "\n".join(parts)
    return {"status": "included", "tokens": te.estimate_tokens(combined)}, combined


def _read_issue_context(issue_json: str | None) -> tuple[dict, str | None]:
    raw = _read_text(issue_json)
    if not raw:
        return _dropped("empty_or_missing")
    try:
        body = json.loads(raw).get("body") or ""
        return _included(body) if body.strip() else _dropped("empty_body")
    except (json.JSONDecodeError, AttributeError):
        return _dropped("invalid_json")


def _read_comments(issue_json: str | None) -> tuple[dict, str | None]:
    raw = _read_text(issue_json)
    if not raw:
        return _dropped("empty_or_missing")
    try:
        comments = json.loads(raw).get("comments") or []
        combined = "\n".join(c.get("body", "") for c in comments if isinstance(c, dict))
        return _included(combined) if combined.strip() else _dropped("no_comments")
    except (json.JSONDecodeError, AttributeError):
        return _dropped("invalid_json")


def _read_pr_reviews(issue_json: str | None) -> tuple[dict, str | None]:
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


def _read_diff(diff_file: str | None) -> tuple[dict, str | None]:
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
        content = effective + f"\n<!-- truncated at {DIFF_LINE_CAP} lines -->"
    else:
        entry["status"] = "included"
        content = effective
    if diff_file:
        h = te.hash_file(diff_file)
        if h:
            entry["file_hash"] = h
    return entry, content


def assemble_pack(
    scenario: str,
    issue_num: int,
    run_id: str,
    clone_dir: str,
    out_md: str,
    out_json: str,
    artifacts_dir: str | None = None,
    spec_file: str | None = None,
    memory_file: str | None = None,
    issue_json: str | None = None,
    impl_file: str | None = None,
    diff_file: str | None = None,
    spec_component: str | None = None,
    changed_files: list[str] | None = None,
    labels: list[str] | None = None,
) -> None:
    active = _SECTION_REGISTRY.get(scenario, [])
    sections: dict[str, dict] = {}
    source_hashes: dict[str, str] = {}
    md_parts: list[str] = []

    for sec in active:
        status_entry: dict
        content: str | None

        if sec == "claude_md":
            path = os.path.join(clone_dir, "CLAUDE.md")
            status_entry, content = _included(_read_text(path), path)
            h = te.hash_file(path)
            if h:
                source_hashes["CLAUDE.md"] = h

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
            # included_slice = targeted slice; included = full fallback
            slice_status = "included" if result.fallback else "included_slice"
            tokens = te.estimate_tokens(result.text)
            status_entry = {
                "status": slice_status,
                "tokens": tokens,
                "component": result.component,
                "included_sections": result.included_sections,
                "omitted_sections": result.omitted_sections,
                "section_hashes": result.section_hashes,
                "fallback": result.fallback,
                "fallback_reason": result.fallback_reason,
            }
            content = result.text if result.text and result.text.strip() else None
            h = te.hash_file(arch_path)
            if h:
                source_hashes["ARCHITECTURE.md"] = h

        elif sec == "skill_prompts":
            status_entry, content = _read_skill_prompts()

        elif sec == "issue_context":
            status_entry, content = _read_issue_context(issue_json)

        elif sec == "comments":
            status_entry, content = _read_comments(issue_json)

        elif sec == "memory_context":
            status_entry, content = _included(_read_text(memory_file), memory_file)
            if memory_file and status_entry["status"] == "included":
                h = te.hash_file(memory_file)
                if h:
                    source_hashes["memory-context.md"] = h

        elif sec == "pr_reviews":
            status_entry, content = _read_pr_reviews(issue_json)

        elif sec == "spec":
            status_entry, content = _included(_read_text(spec_file), spec_file)
            if spec_file and status_entry["status"] == "included":
                h = te.hash_file(spec_file)
                if h:
                    source_hashes["spec"] = h

        elif sec == "implementation_md":
            status_entry, content = _included(_read_text(impl_file), impl_file)
            if impl_file and status_entry["status"] == "included":
                h = te.hash_file(impl_file)
                if h:
                    source_hashes["implementation.md"] = h

        elif sec == "diff":
            status_entry, content = _read_diff(diff_file)
            if diff_file and status_entry["status"] in ("included", "included_partial"):
                h = te.hash_file(diff_file)
                if h:
                    source_hashes["diff"] = h

        else:
            status_entry, content = _dropped("unknown_section")

        sections[sec] = status_entry
        if content is not None:
            md_parts.append(f"## {sec}\n\n{content}")

    estimated = sum(v.get("tokens", 0) for v in sections.values())
    utilization = round(estimated / BUDGET_TOKENS * 100, 1)
    over_budget = estimated > BUDGET_TOKENS

    if over_budget:
        print(
            f"WARNING: context pack for scenario '{scenario}' exceeds budget "
            f"({estimated} > {BUDGET_TOKENS} tokens); sections not dropped",
            file=sys.stderr,
        )

    # included_slice counts as included (content IS assembled into the MD)
    included_sections = [
        k for k, v in sections.items()
        if v.get("status") in ("included", "included_partial", "included_slice")
    ]
    dropped_sections = [k for k, v in sections.items() if v.get("status") == "dropped"]

    os.makedirs(os.path.dirname(os.path.abspath(out_md)), exist_ok=True)
    with open(out_md, "w", encoding="utf-8") as f:
        f.write("\n\n".join(md_parts))
        if md_parts:
            f.write("\n")

    os.makedirs(os.path.dirname(os.path.abspath(out_json)), exist_ok=True)
    artifact = {
        "schema_version": 1,
        "scenario": scenario,
        "run_id": run_id,
        "issue_number": issue_num,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "budget_tokens": BUDGET_TOKENS,
        "estimated_input_tokens": estimated,
        "utilization_pct": utilization,
        "over_budget": over_budget,
        "sections": sections,
        "included_sections": included_sections,
        "dropped_sections": dropped_sections,
        "source_file_hashes": source_hashes,
    }
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Assemble Dark Factory scenario context packs.")
    parser.add_argument("--scenario", required=True,
                        choices=list(_SECTION_REGISTRY.keys()),
                        help="Phase scenario name")
    parser.add_argument("--issue-num", required=True, type=int)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--artifacts-dir", required=True)
    parser.add_argument("--clone-dir", required=True)
    parser.add_argument("--spec-file")
    parser.add_argument("--memory-file")
    parser.add_argument("--issue-json")
    parser.add_argument("--impl-file")
    parser.add_argument("--diff-file")
    parser.add_argument("--spec-component",
                        help="Explicit component for architecture slicing "
                             "(backend|frontend|dark-factory|infrastructure); inferred if omitted")
    parser.add_argument("--changed-files", nargs="*", default=None,
                        help="Changed file paths, used to infer the architecture-slice component")
    parser.add_argument("--labels", nargs="*", default=None,
                        help="Issue labels, used for architecture-slice component inference")
    parser.add_argument("--out-md",
                        help="Output path for context-pack.md "
                             "(default: <artifacts-dir>/context-pack.md)")
    parser.add_argument("--out-json",
                        help="Output path for context-pack.json "
                             "(default: <artifacts-dir>/context-pack.json)")
    args = parser.parse_args()

    out_md = args.out_md or os.path.join(args.artifacts_dir, "context-pack.md")
    out_json = args.out_json or os.path.join(args.artifacts_dir, "context-pack.json")

    assemble_pack(
        scenario=args.scenario,
        issue_num=args.issue_num,
        run_id=args.run_id,
        clone_dir=args.clone_dir,
        out_md=out_md,
        out_json=out_json,
        artifacts_dir=args.artifacts_dir,
        spec_file=args.spec_file,
        memory_file=args.memory_file,
        issue_json=args.issue_json,
        impl_file=args.impl_file,
        diff_file=args.diff_file,
        spec_component=args.spec_component,
        changed_files=args.changed_files,
        labels=args.labels,
    )
    print(f"context-pack.md written to {out_md}", file=sys.stderr)
    print(f"context-pack.json written to {out_json}", file=sys.stderr)


if __name__ == "__main__":
    main()
