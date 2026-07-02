"""
Diff ranker and chunker for dark-factory gates.

Classifies files in a unified diff into risk tiers (critical/high/medium/low),
emits a ranked diff to stdout with a configurable token budget, and writes
diff-ranking.json to --artifacts-dir.

CLI:
    python3 dark-factory/scripts/diff_rank.py \
      --diff <path>            \\
      --artifacts-dir <dir>    \\
      [--config <yaml>]        \\
      [--spec-file <path>]     \\
      [--hotspots <path>]

Writes the ranked diff string to stdout. Exits 0 on success; on any error
exits non-zero so the caller's '&&' falls back to the unranked diff.
"""
import argparse
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Import parse_hotspots from gate_blast_radius (same package)
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from gate_blast_radius import parse_hotspots  # noqa: E402  # re-exported for tests

# ---------------------------------------------------------------------------
# Risk classification constants
#
# Canonical signal string values (appear in signals list and diff-ranking.json):
#   Critical signals: "migration_path", "auth_path", "trading_path", "factory_path", "hotspot"
#   High signals:     "spec_named", "api_endpoint", "dependency", "elevated_blast"
#   Low signals:      "test_file"
#   Medium/low:       [] (empty list — no specific signal)
# ---------------------------------------------------------------------------

# SAFETY_PATH_PATTERNS deliberately differs from gate_blast_radius.MIGRATION_SEED_AUTH_PATTERNS:
#   "^dark-factory/" (broad prefix) replaces "^dark-factory/seed/" — covers all factory scripts,
#   not just seed data. The seed/ subdirectory is caught by this broader prefix.
#   "seed.*\.sql$" (external seed SQL outside dark-factory/) is omitted — not listed in spec.
#   Auth router uses prefix "^backend/app/routers/auth" (all auth routes), vs the single exact
#   file match "^backend/app/routers/auth\.py$" in MIGRATION_SEED_AUTH_PATTERNS.
#   Trading paths are added here (not in gate_blast_radius) per spec R4.
SAFETY_PATH_PATTERNS = [
    re.compile(r"^alembic/versions/"),
    re.compile(r"^backend/app/routers/auth"),
    re.compile(r"^backend/app/core/auth"),
    re.compile(r"app/services/trading"),
    re.compile(r"app/tasks/trading\.py"),
    re.compile(r"^dark-factory/"),
]

TEST_PATH_PATTERNS = [
    re.compile(r"(^|/)test_[^/]+\.py$"),
    re.compile(r"(^|/)tests/"),
    re.compile(r"(^|/)conftest\.py$"),
    re.compile(r"\.test\.ts$"),
    re.compile(r"\.spec\.ts$"),
]

DEPENDENCY_PATTERNS = [
    re.compile(r"requirements[^/]*\.txt$"),
    re.compile(r"package[^/]*\.json$"),
    re.compile(r"pyproject\.toml$"),
]

ROUTER_PATTERN = re.compile(r"^backend/app/routers/")

# Medium threshold: files with more changed lines than this (if not critical/high/test)
MEDIUM_LINE_THRESHOLD = 50

# Elevated-blast threshold for high tier (below floor but still notable)
ELEVATED_BLAST_FLOOR = 2.0


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_config(path: str) -> tuple:
    """Return (token_cap: int, score_floor: float, diff_enabled: bool) from config yaml.

    Keys read:
      token_optimization.diff.max_review_tokens  → token_cap    (default 6000)
      blast_radius.hotspot_score_floor           → score_floor  (default 5.0)
      token_optimization.diff.enabled            → diff_enabled (default True)

    When diff_enabled is False, build_ranked_diff() emits the full diff without
    ranking or truncation. The env var TOKEN_OPTIMIZATION_DIFF_ENABLED overrides
    the config value; missing/unknown values default to True (fail-safe).
    """
    import os
    try:
        import yaml  # type: ignore
        with open(path) as f:
            data = yaml.safe_load(f)
        token_cap = int(
            data.get("token_optimization", {})
            .get("diff", {})
            .get("max_review_tokens", 6000)
        )
        score_floor = float(
            data.get("blast_radius", {}).get("hotspot_score_floor", 5.0)
        )
        env_val = os.environ.get("TOKEN_OPTIMIZATION_DIFF_ENABLED", "").strip().lower()
        if env_val in ("false", "0", "no"):
            diff_enabled = False
        elif env_val in ("true", "1", "yes"):
            diff_enabled = True
        else:
            cfg_val = data.get("token_optimization", {}).get("diff", {}).get("enabled")
            diff_enabled = cfg_val is not False
        return token_cap, score_floor, diff_enabled
    except Exception:
        return 6000, 5.0, True


# ---------------------------------------------------------------------------
# Hotspot scores (for JSON output and elevated-blast high tier)
# ---------------------------------------------------------------------------

def _read_hotspot_scores(path: str) -> dict:
    """Return dict of filepath → blast_score for all entries in hotspots file."""
    scores = {}
    try:
        content = Path(path).read_text(errors="replace")
    except FileNotFoundError:
        return scores
    for line in content.splitlines():
        m = re.match(r"^\s*([\d.]+)\s+(\S+)", line)
        if m:
            try:
                scores[m.group(2)] = float(m.group(1))
            except ValueError:
                pass
    return scores


# ---------------------------------------------------------------------------
# Spec-named file extraction
# ---------------------------------------------------------------------------

def _extract_spec_names(spec_file: str) -> set:
    """Return set of file path strings mentioned in the spec file."""
    if not spec_file:
        return set()
    try:
        text = Path(spec_file).read_text(errors="replace")
        # Match tokens with at least one slash that look like paths
        return set(re.findall(r"\b[a-zA-Z0-9_.-]+(?:/[a-zA-Z0-9_.-]+)+\b", text))
    except Exception:
        return set()


# ---------------------------------------------------------------------------
# Risk classification
# ---------------------------------------------------------------------------

def _safety_signal(path: str) -> str:
    for pat in SAFETY_PATH_PATTERNS:
        if pat.search(path):
            src = pat.pattern
            if "alembic" in src:
                return "migration_path"
            if "auth" in src:
                return "auth_path"
            if "trading" in src:
                return "trading_path"
            if "dark-factory" in src:
                return "factory_path"
            return "safety_path"
    return ""


def classify_file(
    path: str,
    hotspot_paths: set,
    spec_names: set,
    score_floor: float,
    total_lines: int = 0,
    hotspot_scores: dict = None,
) -> tuple:
    """Classify a file path into a risk tier.

    Returns (tier: str, signals: list[str], blast_score: float | None).
    Tiers: critical > high > medium > low.

    Test files are checked before safety paths so that test files within
    dark-factory/tests/ are classified as low rather than critical — test files
    don't modify factory behavior regardless of their location.
    """
    blast_score = (hotspot_scores or {}).get(path)

    # --- Low: test files (always, checked before safety paths) ---
    if any(p.search(path) for p in TEST_PATH_PATTERNS):
        return "low", ["test_file"], blast_score

    # --- Critical: safety paths OR hotspot at/above floor ---
    safety_sig = _safety_signal(path)
    is_hotspot_critical = path in hotspot_paths
    if safety_sig or is_hotspot_critical:
        signals = []
        if safety_sig:
            signals.append(safety_sig)
        if is_hotspot_critical:
            signals.append("hotspot")
        return "critical", signals, blast_score

    # --- High: spec-named, router, dependency, elevated blast ---
    high_signals = []
    if path in spec_names:
        high_signals.append("spec_named")
    if ROUTER_PATTERN.search(path):
        high_signals.append("api_endpoint")
    if any(p.search(path) for p in DEPENDENCY_PATTERNS):
        high_signals.append("dependency")
    if blast_score is not None and blast_score >= ELEVATED_BLAST_FLOOR:
        high_signals.append("elevated_blast")
    if high_signals:
        return "high", high_signals, blast_score

    # --- Medium or Low: based on line count ---
    if total_lines > MEDIUM_LINE_THRESHOLD:
        return "medium", [], blast_score
    return "low", [], blast_score


# ---------------------------------------------------------------------------
# Diff parsing
# ---------------------------------------------------------------------------

def parse_diff_files(diff_text: str) -> list:
    """Parse unified diff; return list of file dicts.

    Each dict: {path, added, removed, hunks, lines (list of str)}.
    Leading non-diff lines (e.g. a [Pre-triage] annotation prepended by fmt_hunk_filter)
    are silently ignored because lines are only collected after the first 'diff --git' header
    (cur is None until then).
    """
    files = []
    cur = None

    for line in diff_text.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if cur is not None and cur.get("path"):
                files.append(cur)
            cur = {"path": None, "added": 0, "removed": 0, "hunks": 0, "lines": [line]}
        elif cur is not None:
            cur["lines"].append(line)
            if line.startswith("+++ b/"):
                cur["path"] = line[6:].rstrip("\n")
            elif line.startswith("+++ /dev/null"):
                pass  # deleted file header
            elif re.match(r"^@@ ", line):
                cur["hunks"] += 1
            elif line.startswith("+") and not line.startswith("+++"):
                cur["added"] += 1
            elif line.startswith("-") and not line.startswith("---"):
                cur["removed"] += 1

    if cur is not None and cur.get("path"):
        files.append(cur)

    return files


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------

def estimate_tokens(text: str) -> int:
    """Character-based token approximation matching context_budget.py."""
    return len(text) // 4


# ---------------------------------------------------------------------------
# Ranking and budget
# ---------------------------------------------------------------------------

def build_ranked_diff(
    diff_text: str,
    token_cap: int,
    hotspot_paths: set,
    hotspot_scores: dict,
    spec_names: set,
    score_floor: float,
    diff_enabled: bool = True,
) -> tuple:
    """Return (ranked_diff_str, ranking_info_dict).

    ranked_diff_str is empty when diff_text is empty.
    When diff_enabled is False, the full diff is returned without ranking or
    truncation; raw_diff_tokens is recorded in the sidecar for savings comparison.
    """
    files = parse_diff_files(diff_text)
    raw_diff_tokens = estimate_tokens(diff_text)

    ranking_base = {
        "token_cap": token_cap,
        "estimated_tokens_emitted": 0,
        "critical_tokens": 0,
        "residual_tokens": 0,
        "raw_diff_tokens": raw_diff_tokens,
        "files": [],
    }

    if not files:
        return "", ranking_base

    if not diff_enabled:
        ranking_base["estimated_tokens_emitted"] = raw_diff_tokens
        ranking_base["diff_enabled"] = False
        return diff_text, ranking_base

    # Classify every file
    classified = []
    for f in files:
        total_lines = f["added"] + f["removed"]
        tier, signals, blast_score = classify_file(
            f["path"],
            hotspot_paths,
            spec_names,
            score_floor,
            total_lines=total_lines,
            hotspot_scores=hotspot_scores,
        )
        classified.append({"file": f, "tier": tier, "signals": signals, "blast_score": blast_score})

    # Bucket by tier
    critical = [c for c in classified if c["tier"] == "critical"]
    high = [c for c in classified if c["tier"] == "high"]
    medium = [c for c in classified if c["tier"] == "medium"]
    low = [c for c in classified if c["tier"] == "low"]

    # Sort critical: blast_score desc, then lines desc
    critical.sort(key=lambda c: (-(c["blast_score"] or 0), -(c["file"]["added"] + c["file"]["removed"])))

    # Sort high: spec-named first, then api, then deps, then elevated_blast
    def _high_key(c):
        sigs = c["signals"]
        if "spec_named" in sigs:
            order = 0
        elif "api_endpoint" in sigs:
            order = 1
        elif "dependency" in sigs:
            order = 2
        else:
            order = 3
        return (order, -(c["blast_score"] or 0), -(c["file"]["added"] + c["file"]["removed"]))
    high.sort(key=_high_key)

    # Sort medium: lines desc
    medium.sort(key=lambda c: -(c["file"]["added"] + c["file"]["removed"]))

    output_parts = []
    file_records = []
    critical_tokens = 0
    residual_tokens = 0
    budget = token_cap

    def _full(c, risk_class):
        nonlocal budget, residual_tokens, critical_tokens
        text = "".join(c["file"]["lines"])
        tokens = estimate_tokens(text)
        if risk_class == "critical":
            critical_tokens += tokens
        else:
            residual_tokens += tokens
            budget -= tokens
        output_parts.append(text)
        return tokens, "full"

    def _summary_budget_exhausted(c):
        f = c["file"]
        summary = (
            f"# [SUMMARIZED: budget-exhausted] {f['path']} — "
            f"+{f['added']}/-{f['removed']} ({f['hunks']} hunks)\n"
        )
        output_parts.append(summary)
        return 0, "summary"

    def _summary_low(c):
        f = c["file"]
        # Only call it "test-only" when the file actually matched the test_file signal;
        # non-test files also fall into the low tier and must not be misreported as tests.
        label = "low-risk test-only" if "test_file" in c["signals"] else "low-risk"
        summary = (
            f"# [SUMMARIZED: {label}] {f['path']} — "
            f"+{f['added']}/-{f['removed']} ({f['hunks']} hunks)\n"
        )
        output_parts.append(summary)
        return 0, "summary"

    # Emit critical files (bypass cap)
    for c in critical:
        tokens, included = _full(c, "critical")
        file_records.append({
            "path": c["file"]["path"],
            "risk_class": "critical",
            "signals": c["signals"],
            "blast_score": c["blast_score"],
            "lines_added": c["file"]["added"],
            "lines_removed": c["file"]["removed"],
            "hunk_count": c["file"]["hunks"],
            "included": included,
            "estimated_tokens": tokens,
        })

    # Fill budget with high-tier files
    for c in high:
        text = "".join(c["file"]["lines"])
        tokens = estimate_tokens(text)
        if budget >= tokens:
            t, included = _full(c, "high")
        else:
            t, included = _summary_budget_exhausted(c)
            tokens = t
        file_records.append({
            "path": c["file"]["path"],
            "risk_class": "high",
            "signals": c["signals"],
            "blast_score": c["blast_score"],
            "lines_added": c["file"]["added"],
            "lines_removed": c["file"]["removed"],
            "hunk_count": c["file"]["hunks"],
            "included": included,
            "estimated_tokens": tokens,
        })

    # Fill remaining budget with medium-tier files
    for c in medium:
        text = "".join(c["file"]["lines"])
        tokens = estimate_tokens(text)
        if budget >= tokens:
            t, included = _full(c, "medium")
        else:
            t, included = _summary_budget_exhausted(c)
            tokens = t
        file_records.append({
            "path": c["file"]["path"],
            "risk_class": "medium",
            "signals": c["signals"],
            "blast_score": c["blast_score"],
            "lines_added": c["file"]["added"],
            "lines_removed": c["file"]["removed"],
            "hunk_count": c["file"]["hunks"],
            "included": included,
            "estimated_tokens": tokens,
        })

    # Summarize all low-tier files
    for c in low:
        _summary_low(c)
        file_records.append({
            "path": c["file"]["path"],
            "risk_class": "low",
            "signals": c["signals"],
            "blast_score": c["blast_score"],
            "lines_added": c["file"]["added"],
            "lines_removed": c["file"]["removed"],
            "hunk_count": c["file"]["hunks"],
            "included": "summary",
            "estimated_tokens": 0,
        })

    total_tokens = critical_tokens + residual_tokens

    header = (
        f"# [diff-rank: {len(files)} files — "
        f"{len(critical)} critical / {len(high)} high / "
        f"{len(medium)} medium / {len(low)} low, "
        f"est. {total_tokens} tokens (cap {token_cap})]\n"
    )

    ranked_diff = header + "".join(output_parts)

    ranking_info = {
        "token_cap": token_cap,
        "estimated_tokens_emitted": total_tokens,
        "critical_tokens": critical_tokens,
        "residual_tokens": residual_tokens,
        "raw_diff_tokens": raw_diff_tokens,
        "files": file_records,
    }

    return ranked_diff, ranking_info


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="Rank and chunk a unified diff by risk tier.")
    p.add_argument("--diff", required=True, help="Path to the input diff file")
    p.add_argument("--artifacts-dir", required=True, help="Directory to write diff-ranking.json")
    p.add_argument(
        "--config",
        default=".claude/skills/refinement/config.yaml",
        help="Path to refinement config yaml",
    )
    p.add_argument("--spec-file", default=None, help="Optional spec file to identify spec-named files")
    p.add_argument(
        "--hotspots",
        default="docs/codeindex-hotspots.md",
        help="Path to codeindex-hotspots.md",
    )
    return p.parse_args()


def main():
    args = parse_args()

    diff_text = Path(args.diff).read_text(errors="replace")
    token_cap, score_floor, diff_enabled = load_config(args.config)
    hotspot_paths = parse_hotspots(args.hotspots, score_floor)  # set (fail-open in parse_hotspots)
    hotspot_scores = _read_hotspot_scores(args.hotspots)         # dict for JSON + elevated blast
    spec_names = _extract_spec_names(args.spec_file)

    ranked_diff, ranking_info = build_ranked_diff(
        diff_text, token_cap, hotspot_paths, hotspot_scores, spec_names, score_floor,
        diff_enabled=diff_enabled,
    )

    # Write diff-ranking.json
    ranking_path = Path(args.artifacts_dir) / "diff-ranking.json"
    ranking_path.write_text(json.dumps(ranking_info, indent=2))

    # Write ranked diff to stdout
    sys.stdout.write(ranked_diff)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"diff_rank error: {e}", file=sys.stderr)
        sys.exit(1)
