import os
import subprocess
from pathlib import Path

_EXCLUDED_DIRS = frozenset({".git", "node_modules"})
_INCLUDED_EXTS = frozenset({
    ".py", ".ts", ".tsx", ".js", ".json",
    ".yaml", ".yml", ".sh", ".sql", ".md",
})


def tier1(filepath: str, clone_dir: str) -> bool:
    """Mechanical resolution for known file patterns. Returns True if resolved."""
    basename = os.path.basename(filepath)

    if filepath in ("codeindex.json", "symbolindex.json", "docs/codeindex-hotspots.md"):
        r = subprocess.run(["git", "checkout", "--theirs", filepath],
                           cwd=clone_dir, capture_output=True)
        if r.returncode != 0:
            return False
        subprocess.run(["git", "add", filepath], cwd=clone_dir, capture_output=True)
        return True

    if basename == "package-lock.json" and "frontend" in filepath:
        r = subprocess.run(["git", "checkout", "--theirs", filepath],
                           cwd=clone_dir, capture_output=True)
        if r.returncode != 0:
            return False
        frontend_dir = os.path.join(clone_dir, "frontend")
        subprocess.run(["npm", "install", "--silent"], cwd=frontend_dir, capture_output=True)
        subprocess.run(["git", "add", filepath], cwd=clone_dir, capture_output=True)
        return True

    if filepath == "backend/app/models/__init__.py":
        full = os.path.join(clone_dir, filepath)
        try:
            with open(full) as fh:
                content = fh.read()
            lines = content.split("\n")
            stripped = [line for line in lines
                        if not line.startswith("<<<<<<<")
                        and not line.startswith("=======")
                        and not line.startswith(">>>>>>>")]
            seen: set = set()
            final = []
            for line in stripped:
                s = line.strip()
                if s and (s.startswith("from ") or s.startswith("import ")):
                    if s not in seen:
                        seen.add(s)
                        final.append(line)
                else:
                    final.append(line)
            with open(full, "w") as fh:
                fh.write("\n".join(final))
            subprocess.run(["git", "add", filepath], cwd=clone_dir, capture_output=True)
            return True
        except OSError:
            return False

    if "alembic/versions/" in filepath and filepath.endswith(".py"):
        r = subprocess.run(["git", "checkout", "--theirs", filepath],
                           cwd=clone_dir, capture_output=True)
        if r.returncode != 0:
            return False
        subprocess.run(["git", "add", filepath], cwd=clone_dir, capture_output=True)
        return True

    return False


def tier2(filepath: str, issue_num: int, owner: str, repo: str, clone_dir: str) -> bool:
    """AI-assisted resolution using sentinel-wrapped output. Returns True if resolved."""
    full = os.path.join(clone_dir, filepath) if not os.path.isabs(filepath) else filepath
    if not os.path.exists(full):
        return False
    try:
        with open(full) as fh:
            conflict_content = fh.read()
    except OSError:
        return False

    r1 = subprocess.run(
        ["gh", "issue", "view", str(issue_num), "--repo", f"{owner}/{repo}",
         "--json", "body", "--jq", ".body"],
        capture_output=True, text=True,
    )
    issue_body = r1.stdout.strip() if r1.returncode == 0 else ""

    r2 = subprocess.run(["git", "log", "--oneline", "-15", "HEAD"],
                        cwd=clone_dir, capture_output=True, text=True)
    git_log = r2.stdout.strip() if r2.returncode == 0 else ""

    prompt = (
        "Resolve the git merge conflict markers in this file, preserving both intents "
        "(what the feature branch added AND what main added).\n\n"
        "Return the COMPLETE resolved file content between two marker lines, EXACTLY like this "
        "and nothing else:\n"
        "===BEGIN_RESOLVED_FILE===\n"
        "<complete resolved file content>\n"
        "===END_RESOLVED_FILE===\n\n"
        "No explanation, commentary, or markdown code fences — inside or outside the markers.\n\n"
        f"File: {filepath}\n\n"
        f"Issue context:\n{issue_body}\n\n"
        f"Recent git log:\n{git_log}\n\n"
        f"File content with conflict markers:\n{conflict_content}\n"
    )

    r3 = subprocess.run(
        ["claude", "-p", "--model", "sonnet"],
        input=prompt, capture_output=True, text=True,
    )
    if r3.returncode != 0:
        return False

    raw = r3.stdout
    if "===BEGIN_RESOLVED_FILE===" not in raw or "===END_RESOLVED_FILE===" not in raw:
        return False

    lines = raw.splitlines()
    in_block = False
    resolved_lines = []
    for line in lines:
        if line == "===BEGIN_RESOLVED_FILE===":
            in_block = True
            continue
        if line == "===END_RESOLVED_FILE===":
            in_block = False
            continue
        if in_block:
            resolved_lines.append(line)

    resolved = "\n".join(resolved_lines)
    if not resolved.strip():
        return False
    if any(ln.startswith("<<<<<<<") or ln.startswith(">>>>>>>") for ln in resolved_lines):
        return False

    with open(full, "w") as fh:
        fh.write(resolved + "\n")
    subprocess.run(["git", "add", filepath], cwd=clone_dir, capture_output=True)
    return True


def hard_grep_survivors(root: str) -> list:
    """Return relative paths of files containing conflict markers, excluding .git/node_modules."""
    survivors = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _EXCLUDED_DIRS]
        for filename in filenames:
            if os.path.splitext(filename)[1] not in _INCLUDED_EXTS:
                continue
            full = os.path.join(dirpath, filename)
            try:
                with open(full, encoding="utf-8", errors="ignore") as fh:
                    for line in fh:
                        if line.startswith("<<<<<<<"):
                            survivors.append(os.path.relpath(full, root))
                            break
            except OSError:
                pass
    return survivors


def _write_artifact(path: Path, verdict: str, files: int,
                    tier1_count: int, tier2_count: int, escalated: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"CONFLICT_VERDICT={verdict}\n"
        f"FILES_CONFLICTED={files}\n"
        f"TIER1_RESOLVED={tier1_count}\n"
        f"TIER2_RESOLVED={tier2_count}\n"
        f"ESCALATED={escalated}\n"
    )


def _escalate(issue_num: int, owner: str, repo: str, reason: str) -> None:
    from .board import set_board_status, STATUS_BLOCKED
    set_board_status(issue_num, STATUS_BLOCKED)
    body = (
        "## Dark Factory — Conflict Resolution Escalated\n\n"
        "The factory attempted automatic merge conflict resolution but could not complete it.\n\n"
        f"**Reason:** {reason}\n\n"
        "**To fix manually:**\n"
        "```bash\n"
        f"git checkout feat/issue-{issue_num}-*\n"
        "git fetch origin main\n"
        "git merge origin/main\n"
        "# Resolve conflicts manually, then push\n"
        "```\n\n"
        "---\n*Posted by MarketHawk Dark Factory*"
    )
    subprocess.run(
        ["gh", "issue", "comment", str(issue_num),
         "--repo", f"{owner}/{repo}", "--body", body],
        capture_output=True,
    )


def resolve_merge_conflicts(
    issue_num: int,
    clone_dir: str,
    owner: str,
    repo: str,
    artifacts_dir: str,
    ai_tier: bool = True,
) -> int:
    """
    Orchestrate Tier 1 → Tier 2 → hard-grep gate.
    Writes artifacts_dir/conflict_resolution.md.
    Returns 0 on success, 1 after escalation.
    """
    artifact_path = Path(artifacts_dir) / "conflict_resolution.md"

    subprocess.run(["git", "fetch", "origin", "main"],
                   cwd=clone_dir, capture_output=True)
    r = subprocess.run(
        ["git", "merge", "origin/main", "--no-edit", "--no-ff"],
        cwd=clone_dir, capture_output=True, text=True,
    )

    if r.returncode == 0:
        _write_artifact(artifact_path, "none", 0, 0, 0, 0)
        return 0

    r2 = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=U"],
        cwd=clone_dir, capture_output=True, text=True,
    )
    conflicted = [f for f in r2.stdout.splitlines() if f]

    if not conflicted:
        subprocess.run(["git", "merge", "--abort"], cwd=clone_dir, capture_output=True)
        _escalate(issue_num, owner, repo,
                  "Merge failed with no resolvable conflict markers.")
        _write_artifact(artifact_path, "escalate", 0, 0, 0, 1)
        return 1

    tier1_count = 0
    tier2_needed = []
    for f in conflicted:
        if tier1(f, clone_dir):
            tier1_count += 1
        else:
            tier2_needed.append(f)

    # Alembic multi-head check after tier1
    backend_dir = os.path.join(clone_dir, "backend")
    r3 = subprocess.run(
        ["python", "-m", "alembic", "heads"],
        cwd=backend_dir, capture_output=True, text=True,
    )
    heads = [ln for ln in r3.stdout.splitlines()
             if ln and ln[:1] in "0123456789abcdef"]
    if len(heads) > 1:
        subprocess.run(
            ["python", "-m", "alembic", "merge", "heads",
             "-m", f"merge_branches_issue_{issue_num}"],
            cwd=backend_dir, capture_output=True,
        )
        subprocess.run(["git", "add", "backend/alembic/versions/"],
                       cwd=clone_dir, capture_output=True)

    tier2_count = 0
    ai_uncertain = []
    if tier2_needed and ai_tier:
        for f in tier2_needed:
            if tier2(f, issue_num, owner, repo, clone_dir):
                tier2_count += 1
            else:
                ai_uncertain.append(f)
    else:
        ai_uncertain = list(tier2_needed)

    survivors = hard_grep_survivors(clone_dir)

    if ai_uncertain or survivors:
        parts = []
        if ai_uncertain:
            parts.append(f"AI could not resolve: {', '.join(ai_uncertain)}.")
        if survivors:
            parts.append(f"Surviving markers in: {', '.join(survivors)}.")
        subprocess.run(["git", "merge", "--abort"], cwd=clone_dir, capture_output=True)
        _escalate(issue_num, owner, repo, " ".join(parts))
        _write_artifact(artifact_path, "escalate", len(conflicted),
                        tier1_count, tier2_count, 1)
        return 1

    subprocess.run(
        ["git", "commit", "-m",
         f"chore: merge origin/main, resolve conflicts [#{issue_num}]"],
        cwd=clone_dir, capture_output=True,
    )

    if tier2_count > 0:
        verdict = "tier2"
    elif tier1_count > 0:
        verdict = "tier1"
    else:
        verdict = "clean_merge"

    _write_artifact(artifact_path, verdict, len(conflicted),
                    tier1_count, tier2_count, 0)
    return 0
