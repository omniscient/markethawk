#!/usr/bin/env python3
"""Eligibility detection for replay benchmark tasks.

Algorithm:
1. Fetch closed issues with merged PRs from the GitHub API.
2. Diff each golden PR to find added/modified test files — these are oracle candidates.
3. Checkout pre-PR commit → run pytest/bash on oracle candidates → record failures.
4. Checkout post-PR commit → run the same set → record passes.
5. Eligible iff ≥1 test transitions fail→pass.
6. Issues where auto-verification fails (live fixtures, build errors) surface as
   "needs-review" for human decision.

Output: JSON to stdout (pipe to suite.json candidates).
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
GH_REPO = "omniscient/markethawk"


def run(cmd: list[str], cwd: str | None = None, capture: bool = True) -> tuple[int, str]:
    result = subprocess.run(
        cmd, cwd=cwd or str(REPO_ROOT),
        capture_output=capture, text=True
    )
    return result.returncode, result.stdout + result.stderr


def fetch_closed_issues_with_prs(limit: int = 50) -> list[dict[str, Any]]:
    """Return closed issues that have a merged PR."""
    rc, out = run([
        "gh", "pr", "list",
        "--repo", GH_REPO,
        "--state", "merged",
        "--limit", str(limit),
        "--json", "number,title,mergeCommit,headRefName,labels,closingIssuesReferences",
    ])
    if rc != 0:
        print(f"ERROR: gh pr list failed: {out}", file=sys.stderr)
        return []
    prs = json.loads(out.strip() or "[]")
    result = []
    for pr in prs:
        issues = pr.get("closingIssuesReferences", [])
        if not issues:
            continue
        merge_sha = pr.get("mergeCommit", {}).get("oid", "")
        if not merge_sha:
            continue
        for issue in issues:
            result.append({
                "issue": issue["number"],
                "pr": pr["number"],
                "title": pr["title"],
                "merge_sha": merge_sha,
                "head_ref": pr["headRefName"],
                "labels": [la["name"] for la in pr.get("labels", [])],
            })
    return result


def get_pr_test_files(merge_sha: str) -> list[str]:
    """Return test files added or modified in the golden PR."""
    pre_sha = get_pre_pr_sha(merge_sha)
    rc, out = run(["git", "diff", "--name-only", f"{pre_sha}..{merge_sha}"])
    if rc != 0:
        return []
    candidates = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        if any(pat in line for pat in ["test_", "_test.py", ".test.ts", ".spec.ts", "tests/"]):
            candidates.append(line)
    return candidates


def get_pre_pr_sha(merge_sha: str) -> str:
    """Return first parent of merge commit (main before merge)."""
    rc, out = run(["git", "log", "--format=%P", "-1", merge_sha])
    if rc != 0 or not out.strip():
        return merge_sha + "^"
    return out.strip().split()[0]


def get_size_label(labels: list[str]) -> str:
    for la in labels:
        if la.startswith("size:"):
            return la.replace("size: ", "").replace("size:", "").strip()
    return "S"


def verify_fail_pass(pre_sha: str, post_sha: str, oracle_files: list[str]) -> dict[str, Any]:
    """Verify oracle tests fail at pre-SHA and pass at post-SHA.

    Returns a dict with keys: eligible, oracle_tests, notes.
    """
    py_tests = [f for f in oracle_files if f.endswith(".py")]
    sh_tests = [f for f in oracle_files if f.endswith(".sh")]

    if not py_tests and not sh_tests:
        return {"eligible": False, "oracle_tests": [], "notes": "no test files found in diff"}

    # Save current branch to restore later
    rc, current_branch = run(["git", "branch", "--show-current"])
    current_branch = current_branch.strip()
    if not current_branch:
        rc, current_sha = run(["git", "rev-parse", "HEAD"])
        current_branch = current_sha.strip()

    confirmed_oracles = []
    notes = []

    try:
        # Check out pre-PR state
        rc, _ = run(["git", "checkout", pre_sha])
        if rc != 0:
            return {"eligible": False, "oracle_tests": [], "notes": f"could not checkout pre_sha {pre_sha}"}

        # Run pytest on Python test files at pre-SHA
        pre_pass_py = []
        pre_fail_py = []
        for tf in py_tests:
            if not (REPO_ROOT / tf).exists():
                # File doesn't exist at pre-SHA (newly added) — definitely fails pre-patch
                pre_fail_py.append(tf)
                continue
            rc, out = run([
                sys.executable, "-m", "pytest", tf, "-x", "--tb=no", "-q",
                "--no-header"
            ], cwd=str(REPO_ROOT / "backend"))
            if rc == 0:
                pre_pass_py.append(tf)
            else:
                pre_fail_py.append(tf)

        # Run shell tests at pre-SHA
        pre_fail_sh = []
        for tf in sh_tests:
            if not (REPO_ROOT / tf).exists():
                pre_fail_sh.append(tf)
                continue
            rc, _ = run(["bash", tf])
            if rc != 0:
                pre_fail_sh.append(tf)

        # Now check out post-PR state
        rc, _ = run(["git", "checkout", post_sha])
        if rc != 0:
            return {"eligible": False, "oracle_tests": [], "notes": f"could not checkout post_sha {post_sha}"}

        # Confirm pre-fail tests now pass
        for tf in pre_fail_py:
            rc, out = run([
                sys.executable, "-m", "pytest", tf, "-x", "--tb=no", "-q", "--no-header"
            ], cwd=str(REPO_ROOT / "backend"))
            if rc == 0:
                confirmed_oracles.append(tf)
            else:
                notes.append(f"{tf}: still fails post-patch")

        for tf in pre_fail_sh:
            rc, _ = run(["bash", tf])
            if rc == 0:
                confirmed_oracles.append(tf)
            else:
                notes.append(f"{tf}: still fails post-patch")

        # Tests that passed pre-patch are not useful oracles (no fail→pass transition)
        if pre_pass_py:
            notes.append(f"pre-pass (not oracles): {pre_pass_py}")

    except Exception as exc:  # noqa: BLE001
        notes.append(f"exception: {exc}")
        return {"eligible": False, "oracle_tests": [], "notes": "; ".join(notes)}
    finally:
        # Restore original branch/SHA
        run(["git", "checkout", current_branch])

    if confirmed_oracles:
        return {
            "eligible": True,
            "oracle_tests": confirmed_oracles,
            "notes": "; ".join(notes) if notes else "",
        }

    unverified = pre_fail_py + pre_fail_sh
    if unverified:
        return {
            "eligible": "needs-review",
            "oracle_tests": pre_fail_py + pre_fail_sh,
            "notes": "tests fail pre-patch but did not pass post-patch; may need live fixtures or build setup. " + "; ".join(notes),
        }

    return {
        "eligible": False,
        "oracle_tests": [],
        "notes": "no fail→pass test transitions found. " + "; ".join(notes),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Find replay-benchmark-eligible issues")
    parser.add_argument("--limit", type=int, default=50, help="Max PRs to scan (default: 50)")
    parser.add_argument("--verify", action="store_true", help="Run executable pytest verification (slow)")
    parser.add_argument("--json", dest="json_out", action="store_true", help="Output JSON (default: human-readable)")
    args = parser.parse_args()

    items = fetch_closed_issues_with_prs(args.limit)
    if not items:
        print("No merged PRs found", file=sys.stderr)
        sys.exit(1)

    candidates = []
    for item in items:
        merge_sha = item["merge_sha"]
        pre_sha = get_pre_pr_sha(merge_sha)
        test_files = get_pr_test_files(merge_sha)
        size = get_size_label(item["labels"])

        if not test_files:
            continue

        candidate: dict[str, Any] = {
            "issue": item["issue"],
            "title": item["title"][:80],
            "size": size,
            "pre_pr_sha": pre_sha,
            "golden_pr": item["pr"],
            "oracle_tests": test_files,
            "notes": "diff pre-filter only — run with --verify to confirm fail→pass",
            "eligible": "candidate",
        }

        if args.verify:
            verdict = verify_fail_pass(pre_sha, merge_sha, test_files)
            candidate.update(verdict)

        candidates.append(candidate)

    if args.json_out:
        print(json.dumps({"candidates": candidates}, indent=2))
    else:
        eligible = [c for c in candidates if c.get("eligible") is True]
        needs_review = [c for c in candidates if c.get("eligible") == "needs-review"]
        not_eligible = [c for c in candidates if c.get("eligible") is False or c.get("eligible") == "candidate"]

        print(f"\n=== Eligible ({len(eligible)}) ===")
        for c in eligible:
            print(f"  #{c['issue']} [{c['size']}] {c['title']}")
            print(f"    pre_pr_sha: {c['pre_pr_sha']}")
            print(f"    oracle_tests: {c['oracle_tests']}")

        print(f"\n=== Needs review ({len(needs_review)}) ===")
        for c in needs_review:
            print(f"  #{c['issue']} [{c['size']}] {c['title']}")
            print(f"    notes: {c['notes']}")

        print(f"\n=== Not eligible ({len(not_eligible)}) ===")
        for c in not_eligible:
            print(f"  #{c['issue']}: {c.get('notes', 'no test files')}")


if __name__ == "__main__":
    main()
