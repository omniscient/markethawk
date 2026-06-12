"""Deterministic blast-radius gate for the dark-factory validate pipeline.

Reads a newline-separated list of changed file paths from stdin.
Writes a blast.md-format verdict to stdout.

Exit 0 always — the caller reads STATUS from the output.
"""
import argparse
import re
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--changed-files-stdin",
        action="store_true",
        help="Read newline-separated changed-file list from stdin",
    )
    p.add_argument(
        "--lines-changed",
        type=int,
        default=0,
        help="Total added+deleted lines (computed by caller from git diff --shortstat)",
    )
    p.add_argument(
        "--hotspots",
        required=True,
        help="Path to docs/codeindex-hotspots.md",
    )
    p.add_argument(
        "--config",
        required=True,
        help="Path to .claude/skills/refinement/config.yaml",
    )
    return p.parse_args()


def load_config(path: str) -> dict:
    try:
        import yaml  # type: ignore

        with open(path) as f:
            data = yaml.safe_load(f)
        return data.get("blast_radius", {})
    except Exception:
        return {}


def parse_hotspots(path: str, score_floor: float) -> set:
    """Return set of file paths whose blast score >= score_floor.

    Parses the space-separated codeindex-hotspots.md format:
        64.0  frontend/src/api/client.ts  (20d / 88t)  78 loc
    Score is the first token, path is the second.
    """
    hot = set()
    try:
        content = Path(path).read_text(errors="replace")
    except FileNotFoundError:
        return hot
    for line in content.splitlines():
        m = re.match(r"^\s*([\d.]+)\s+(\S+)", line)
        if m:
            try:
                score = float(m.group(1))
            except ValueError:
                continue
            if score >= score_floor:
                hot.add(m.group(2))
    return hot


MIGRATION_SEED_AUTH_PATTERNS = [
    re.compile(r"^alembic/versions/"),
    re.compile(r"^dark-factory/seed/"),
    re.compile(r"seed.*\.sql$"),
    re.compile(r"^backend/app/routers/auth\.py$"),
]


def classify_file(fpath: str, hotspots: set) -> list:
    """Return list of triggered categories for a single file path."""
    cats = []
    if fpath in hotspots:
        cats.append("hotspot")
    for pat in MIGRATION_SEED_AUTH_PATTERNS:
        if pat.search(fpath):
            cats.append("migration-seed")
            break
    return cats


def main() -> None:
    args = parse_args()
    cfg = load_config(args.config)

    if not cfg.get("enabled", True):
        print("STATUS: SKIPPED\nGATE_TYPE: blast\nFINDINGS_COUNT: 0\nSEVERITY: none")
        print("---\nTRIGGER: none\nTRIGGERED_FILES:\nLINES_CHANGED: 0")
        return

    score_floor = float(cfg.get("hotspot_score_floor", 5.0))
    size_budget = int(cfg.get("size_budget_lines", 400))
    size_blocks = bool(cfg.get("size_budget_blocks", False))

    hotspots = parse_hotspots(args.hotspots, score_floor)

    changed_files = []
    if args.changed_files_stdin:
        changed_files = [ln.strip() for ln in sys.stdin.read().splitlines() if ln.strip()]

    lines_changed = args.lines_changed

    triggered = []
    for fpath in changed_files:
        cats = classify_file(fpath, hotspots)
        if cats:
            triggered.append((fpath, cats))

    hard_trigger = bool(triggered)
    size_trigger = size_blocks and lines_changed > size_budget

    status = "HUMAN_REQUIRED" if (hard_trigger or size_trigger) else "PASS"
    severity = "critical" if status == "HUMAN_REQUIRED" else "none"
    findings_count = len(triggered) + (1 if size_trigger else 0)

    trigger_label = "none"
    if hard_trigger:
        cats_all = [c for _, cats in triggered for c in cats]
        trigger_label = "hotspot" if "hotspot" in cats_all else "migration-seed"
    elif size_trigger:
        trigger_label = "size"

    print(f"STATUS: {status}")
    print(f"GATE_TYPE: blast")
    print(f"FINDINGS_COUNT: {findings_count}")
    print(f"SEVERITY: {severity}")
    print("---")
    print(f"TRIGGER: {trigger_label}")
    print("TRIGGERED_FILES:")
    for fpath, cats in triggered:
        label = ", ".join(cats)
        print(f"  - {fpath} (category: {label})")
    if size_trigger:
        print(f"  - [size] {lines_changed} lines > {size_budget} budget")
    print(f"LINES_CHANGED: {lines_changed}")


if __name__ == "__main__":
    main()
