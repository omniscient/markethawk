"""Pure-stdlib budget enforcement for Dark Factory — per-scenario budget derivation.

CLI:
  python3 budget_enforce.py \
    --context-budget-json <path>  \
    --budget-tokens <n>           \
    --mode observe|enforce        \
    [--config <yaml>]

Observe mode: compute BudgetResult, return it, emit nothing to stdout.
Enforce mode: also print sourceable KEY=VALUE lines to stdout, status to stderr.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Hardcoded defaults — used when config is missing/invalid/partially specified
# ---------------------------------------------------------------------------

_HARDCODED = {
    "token_optimization": {
        "issue_context": {"reserve_tokens": 2000},
        "architecture": {"max_tokens": 3000, "min_tokens": 1500},
        "memory": {"max_tokens": 1500, "min_tokens": 750},
        "comments": {"max_tokens": 2000, "min_tokens": 1000},
        "diff": {"max_review_tokens": 6000, "min_review_tokens": 3000},
    }
}

_DEFAULT_CONFIG_PATH = ".claude/skills/refinement/config.yaml"

# ---------------------------------------------------------------------------
# Optimizable section slots
#
# Each entry: (canonical_name, aliases, env_var, cfg_key, default_key, floor_key)
#
# architecture_md is optimizable ONLY when arch_fallback=False.
# When fallback=True it is reserved (fixed cost) and excluded from the
# optimizable set so derive_caps does not double-count it.
#
# comment_digest is the continue-scenario alias for the comments slot.
# Both map to TOKEN_OPTIMIZATION_COMMENTS_MAX_TOKENS.
# ---------------------------------------------------------------------------

_SLOTS = [
    (
        "architecture_md",
        ["architecture_md"],
        "TOKEN_OPTIMIZATION_ARCHITECTURE_MAX_TOKENS",
        "architecture",
        "max_tokens",
        "min_tokens",
    ),
    (
        "memory_context",
        ["memory_context"],
        "TOKEN_OPTIMIZATION_MEMORY_MAX_TOKENS",
        "memory",
        "max_tokens",
        "min_tokens",
    ),
    (
        "comments",
        ["comments", "comment_digest"],
        "TOKEN_OPTIMIZATION_COMMENTS_MAX_TOKENS",
        "comments",
        "max_tokens",
        "min_tokens",
    ),
    (
        "diff",
        ["diff"],
        "TOKEN_OPTIMIZATION_DIFF_MAX_REVIEW_TOKENS",
        "diff",
        "max_review_tokens",
        "min_review_tokens",
    ),
]

# Flat env_var lookup by section key (both canonical and aliases)
_SECTION_ENV_VAR: dict[str, str] = {
    alias: env_var
    for _, aliases, env_var, *_ in _SLOTS
    for alias in aliases
}


# ---------------------------------------------------------------------------
# BudgetResult
# ---------------------------------------------------------------------------

@dataclass
class BudgetResult:
    reserved_tokens: int
    allowance: int
    over_budget: bool
    derived_caps: dict          # {section_key: int} — only optimizable sections present
    would_trim: bool
    sections_skipped: list      # canonical names of optimizable sections absent from input
    claude_md_tokens: int
    issue_context_tokens: int


# ---------------------------------------------------------------------------
# Config loading (yaml lazy-imported; falls back to hardcoded defaults)
# ---------------------------------------------------------------------------

def _load_config(path: str) -> dict:
    """Load config from yaml. Returns merged defaults on any error (fail-open)."""
    try:
        import yaml  # type: ignore
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise ValueError("config root is not a mapping")
        return _merge_with_defaults(data)
    except Exception:
        return copy.deepcopy(_HARDCODED)


def _merge_with_defaults(data: dict) -> dict:
    """Merge yaml data with hardcoded defaults, preferring yaml values for known keys."""
    merged = copy.deepcopy(_HARDCODED)
    to = data.get("token_optimization", {})
    if not isinstance(to, dict):
        return merged
    m = merged["token_optimization"]

    for section_name, key_pairs in [
        ("issue_context", [("reserve_tokens", "reserve_tokens")]),
        ("architecture",  [("max_tokens", "max_tokens"), ("min_tokens", "min_tokens")]),
        ("memory",        [("max_tokens", "max_tokens"), ("min_tokens", "min_tokens")]),
        ("comments",      [("max_tokens", "max_tokens"), ("min_tokens", "min_tokens")]),
        ("diff",          [("max_review_tokens", "max_review_tokens"), ("min_review_tokens", "min_review_tokens")]),
    ]:
        src = to.get(section_name, {})
        if not isinstance(src, dict):
            continue
        for src_key, dst_key in key_pairs:
            if src_key in src:
                try:
                    m[section_name][dst_key] = int(src[src_key])
                except (TypeError, ValueError):
                    pass

    return merged


# ---------------------------------------------------------------------------
# Core derivation logic (pure — no I/O)
# ---------------------------------------------------------------------------

def derive_caps(
    sections: dict,
    budget: int,
    arch_fallback: bool,
    config: dict,
    scenario: str = "unknown",
) -> BudgetResult:
    """Compute per-scenario budget allocation.

    Args:
        sections: dict from context-budget.json["sections"]
        budget: total per-scenario token budget
        arch_fallback: True when architecture_md was loaded as full doc (safety/fallback trigger).
                       When True, architecture_md is reserved (not optimizable).
        config: loaded config dict (from _load_config)
        scenario: scenario name (informational)

    Returns:
        BudgetResult with breakdown and derived caps.
    """
    to = config.get("token_optimization", _HARDCODED["token_optimization"])
    if not isinstance(to, dict):
        to = _HARDCODED["token_optimization"]
    ic_floor = int(to.get("issue_context", {}).get("reserve_tokens", 2000))

    # --- Reserved (un-trimmable) set ---
    claude_md_tokens = 0
    claude_sec = sections.get("claude_md", {})
    if claude_sec.get("status", "dropped") != "dropped":
        claude_md_tokens = max(0, int(claude_sec.get("tokens", 0)))

    issue_context_tokens = 0
    ic_sec = sections.get("issue_context", {})
    if ic_sec.get("status", "dropped") != "dropped":
        actual = max(0, int(ic_sec.get("tokens", 0)))
        issue_context_tokens = max(actual, ic_floor)

    arch_reserved = 0
    if arch_fallback:
        arch_sec = sections.get("architecture_md", {})
        if arch_sec.get("status", "dropped") != "dropped":
            arch_reserved = max(0, int(arch_sec.get("tokens", 0)))

    reserved_tokens = claude_md_tokens + issue_context_tokens + arch_reserved
    allowance = max(0, budget - reserved_tokens)
    over_budget = reserved_tokens >= budget

    # --- Optimizable sections: present vs skipped ---
    present: dict[str, tuple] = {}   # section_key -> (env_var, cfg_key, default_key, floor_key)
    skipped: list[str] = []

    for canonical, aliases, env_var, cfg_key, default_key, floor_key in _SLOTS:
        # architecture_md is reserved (not optimizable) when fallback=True
        if canonical == "architecture_md" and arch_fallback:
            continue

        found_key: str | None = None
        for alias in aliases:
            sec = sections.get(alias, {})
            if sec.get("status", "dropped") != "dropped":
                found_key = alias
                break

        if found_key is None:
            skipped.append(canonical)
        else:
            present[found_key] = (env_var, cfg_key, default_key, floor_key)

    # --- Get default and floor for each present section ---
    section_defaults: dict[str, int] = {}
    section_floors: dict[str, int] = {}
    for sec_key, (env_var, cfg_key, default_key, floor_key) in present.items():
        hd = _HARDCODED["token_optimization"][cfg_key]
        cfg_section = to.get(cfg_key, {}) if isinstance(to, dict) else {}
        section_defaults[sec_key] = int(cfg_section.get(default_key, hd[default_key]))
        section_floors[sec_key] = int(cfg_section.get(floor_key, hd[floor_key]))

    total_default = sum(section_defaults.values())

    # --- Proportional distribution clamped to [floor, default] ---
    derived_caps: dict[str, int] = {}
    for sec_key in present:
        if total_default > 0:
            raw = int(allowance * section_defaults[sec_key] / total_default)
        else:
            raw = 0
        cap = max(section_floors[sec_key], min(section_defaults[sec_key], raw))
        derived_caps[sec_key] = cap

    would_trim = any(
        derived_caps[sec_key] < section_defaults[sec_key]
        for sec_key in derived_caps
    )

    return BudgetResult(
        reserved_tokens=reserved_tokens,
        allowance=allowance,
        over_budget=over_budget,
        derived_caps=derived_caps,
        would_trim=would_trim,
        sections_skipped=skipped,
        claude_md_tokens=claude_md_tokens,
        issue_context_tokens=issue_context_tokens,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def run_cli(argv: list[str] | None = None) -> BudgetResult:
    """Parse CLI args, call derive_caps, optionally print env lines. Returns BudgetResult."""
    parser = argparse.ArgumentParser(
        description="Derive per-scenario token budget caps from context-budget.json."
    )
    parser.add_argument(
        "--context-budget-json", required=True,
        help="Path to context-budget.json written by context_budget.py",
    )
    parser.add_argument(
        "--budget-tokens", required=True, type=int,
        help="Total per-scenario token budget",
    )
    parser.add_argument(
        "--mode", choices=["observe", "enforce"], default="observe",
        help="observe = compute only; enforce = also print KEY=VALUE to stdout",
    )
    parser.add_argument(
        "--config", default=_DEFAULT_CONFIG_PATH,
        help="Path to refinement config.yaml",
    )
    args = parser.parse_args(argv)

    try:
        with open(args.context_budget_json, encoding="utf-8") as f:
            cb = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(
            f"budget_enforce: error reading {args.context_budget_json}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    sections = cb.get("sections", {})
    scenario = cb.get("scenario", "unknown")
    arch_fallback = bool(sections.get("architecture_md", {}).get("fallback", False))

    config = _load_config(args.config)
    result = derive_caps(
        sections=sections,
        budget=args.budget_tokens,
        arch_fallback=arch_fallback,
        config=config,
        scenario=scenario,
    )

    if args.mode == "enforce":
        # Deduplicate by env_var (comment_digest and comments share one env var).
        # If two present sections resolve to the same env var, raise rather than
        # silently overwriting — would indicate a new scenario emitting both aliases.
        env_lines: dict[str, int] = {}
        for sec_key, cap in result.derived_caps.items():
            env_var = _SECTION_ENV_VAR.get(sec_key)
            if env_var:
                if env_var in env_lines:
                    raise RuntimeError(
                        f"budget_enforce: collision — two sections map to {env_var!r}; "
                        f"update _SLOTS to resolve the conflict before proceeding."
                    )
                env_lines[env_var] = cap
        for env_var in sorted(env_lines):
            print(f"{env_var}={env_lines[env_var]}")
        print(
            f"budget_enforce: scenario={scenario} budget={args.budget_tokens} "
            f"reserved={result.reserved_tokens} allowance={result.allowance} "
            f"over_budget={result.over_budget} would_trim={result.would_trim}",
            file=sys.stderr,
        )

    return result


def main() -> None:
    run_cli()


if __name__ == "__main__":
    main()
