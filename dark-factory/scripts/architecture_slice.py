"""Architecture slicer — return a component-scoped ARCHITECTURE.md excerpt.

Library: imported by context_budget.py as a drop-in for the monolithic architecture_md handler.
CLI:     python3 architecture_slice.py --arch-file ARCHITECTURE.md --scenario implement ...
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(__file__))
import token_estimate as te

# ── Component → section map ────────────────────────────────────────────────────

COMPONENT_SECTION_MAP: dict[str, list[str]] = {
    "backend": [
        "Scan Execution Flow",
        "Backend Module Map",
        "Error Tracking System",
        "Celery Task Architecture",
        "Test Architecture",
    ],
    "frontend": [
        "Frontend Architecture",
        "Backend Module Map",
        "Error Tracking System",
    ],
    "dark-factory": [
        "Service Topology",
        "Celery Task Architecture",
        "Metrics and Observability",
    ],
    "infrastructure": [
        "Service Topology",
        "IB Gateway Integration",
        "Live Scanner",
        "Celery Task Architecture",
        "Catch Up Feature (Universe Aggregate Backfill)",
        "Metrics and Observability",
    ],
}

# ── Component inference keyword tables ────────────────────────────────────────

_FILE_PREFIX_MAP: list[tuple[str, str]] = [
    ("backend/app/", "backend"),
    ("frontend/src/", "frontend"),
    ("dark-factory/", "dark-factory"),
    ("docker-compose", "infrastructure"),
]

_SPEC_KEYWORD_MAP: list[tuple[frozenset[str], str]] = [
    (frozenset({"backend", "scanner", "api", "celery", "database", "migration"}), "backend"),
    (frozenset({"frontend", "ui", "react", "page", "component"}), "frontend"),
    (frozenset({"factory", "archon", "scheduler", "dark", "refine", "plan", "pipeline"}), "dark-factory"),
    (frozenset({"infrastructure", "docker", "ibkr", "gateway", "prometheus", "grafana"}), "infrastructure"),
]

_LABEL_COMPONENT_MAP: dict[str, str] = {
    "dark factory": "dark-factory",
    "dark-factory": "dark-factory",
    "frontend": "frontend",
    "backend": "backend",
    "infrastructure": "infrastructure",
}

# ── Cross-cutting infra files (hardcoded safety triggers) ────────────────────

_INFRA_PATTERNS = [
    "ARCHITECTURE.md",
    "docker-compose*.yml",
    "docker-compose*.yaml",
    "backend/app/core/",
    "backend/app/main.py",
]

# ── Config defaults ────────────────────────────────────────────────────────────

_DEFAULT_SAFETY_KEYWORDS = r"migration|migrate|performance|perf|architectur|refactor"
_DEFAULT_SENSITIVE_KEYWORDS = (
    r"trading|ibkr|live order|notional|authentication|authorization"
    r"|authn|authz|jwt|oauth|rbac"
)
_DEFAULT_EXCLUDE_PATHS = [
    "app/services/trading",
    "app/tasks/trading.py",
    "app/core/auth",
    "app/routers/auth",
]

_CONFIG_PATHS = [
    "/workspace/project/.claude/skills/refinement/config.yaml",
    "/opt/refinement-skills/config.yaml",
]


# ── SliceResult ────────────────────────────────────────────────────────────────

@dataclass
class SliceResult:
    text: str
    component: str | None
    scenario: str
    included_sections: list[str] = field(default_factory=list)
    omitted_sections: list[str] = field(default_factory=list)
    section_hashes: dict[str, str] = field(default_factory=dict)
    fallback: bool = False
    fallback_reason: str | None = None


# ── Config loading ─────────────────────────────────────────────────────────────

def _load_config(clone_dir: str | None) -> dict:
    """Load config.yaml from known paths; return parsed dict or {}."""
    candidates = list(_CONFIG_PATHS)
    if clone_dir:
        candidates.insert(0, os.path.join(clone_dir, ".claude", "skills", "refinement", "config.yaml"))
    for path in candidates:
        if not os.path.exists(path):
            continue
        try:
            import yaml  # type: ignore[import]
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


def _get_safety_keywords(cfg: dict) -> str:
    return (cfg.get("dispatch_ceiling") or {}).get("keywords") or _DEFAULT_SAFETY_KEYWORDS


def _get_sensitive_keywords(cfg: dict) -> str:
    return (cfg.get("epic_autopilot") or {}).get("sensitive_keywords") or _DEFAULT_SENSITIVE_KEYWORDS


def _get_exclude_paths(cfg: dict) -> list[str]:
    paths = (cfg.get("epic_autopilot") or {}).get("hard_exclude_paths")
    if paths and isinstance(paths, list):
        return [str(p) for p in paths]
    return list(_DEFAULT_EXCLUDE_PATHS)


def _is_architecture_enabled(cfg: dict) -> bool:
    """Return False only when explicitly disabled; default True (fail-safe)."""
    env_val = os.environ.get("TOKEN_OPTIMIZATION_ARCHITECTURE_ENABLED", "").strip().lower()
    if env_val in ("false", "0", "no"):
        return False
    if env_val in ("true", "1", "yes"):
        return True
    val = (cfg.get("token_optimization") or {}).get("architecture", {}).get("enabled")
    if val is False:
        return False
    return True


def _get_architecture_max_tokens(cfg: dict) -> int | None:
    """Return the max_tokens cap for architecture slicing, or None if no cap.

    Priority: TOKEN_OPTIMIZATION_ARCHITECTURE_MAX_TOKENS env var → config value → None.
    """
    env_val = os.environ.get("TOKEN_OPTIMIZATION_ARCHITECTURE_MAX_TOKENS", "").strip()
    if env_val:
        try:
            v = int(env_val)
            if v > 0:
                return v
        except ValueError:
            pass
    cfg_val = (cfg.get("token_optimization") or {}).get("architecture", {}).get("max_tokens")
    if cfg_val is not None:
        try:
            return int(cfg_val)
        except (ValueError, TypeError):
            pass
    return None


# ── Section parsing ────────────────────────────────────────────────────────────

def _parse_sections(path: str) -> dict[str, str]:
    """Parse ARCHITECTURE.md by ##-level headings → {title: full_section_text}."""
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
    except (FileNotFoundError, OSError):
        return {}

    sections: dict[str, str] = {}
    current_title: str | None = None
    current_lines: list[str] = []

    for line in content.splitlines(keepends=True):
        if line.startswith("## "):
            if current_title is not None:
                sections[current_title] = "".join(current_lines)
            current_title = line[3:].rstrip()
            current_lines = [line]
        elif current_title is not None:
            # Stop on level-1 heading (shouldn't appear mid-doc, but guard anyway)
            if line.startswith("# ") and not line.startswith("## "):
                sections[current_title] = "".join(current_lines)
                current_title = None
                current_lines = []
            else:
                current_lines.append(line)

    if current_title is not None:
        sections[current_title] = "".join(current_lines)

    return sections


# ── Component inference ────────────────────────────────────────────────────────

def infer_component(
    spec_file: str | None,
    changed_files: list[str] | None,
    labels: list[str] | None,
) -> str | None:
    """Infer architecture component from available signals; returns None if unresolved."""
    files = changed_files or []
    lbs = [l.lower() for l in (labels or [])]

    # 1. Changed-file path prefixes (first-match)
    for f in files:
        for prefix, component in _FILE_PREFIX_MAP:
            if f.startswith(prefix):
                return component

    # 2. Spec filename keywords
    if spec_file:
        slug = os.path.basename(spec_file)
        # strip date prefix if present and extension
        slug = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", slug)
        slug = os.path.splitext(slug)[0]
        tokens = set(re.split(r"[-_]", slug.lower()))
        for keyword_set, component in _SPEC_KEYWORD_MAP:
            if tokens & keyword_set:
                return component

    # 3. Issue labels
    for label_text in lbs:
        for key, component in _LABEL_COMPONENT_MAP.items():
            if key in label_text:
                return component

    return None


# ── Safety fallback checks ────────────────────────────────────────────────────

def _is_infra_file(f: str) -> bool:
    """Return True if f matches any cross-cutting infrastructure pattern."""
    basename = os.path.basename(f)
    for pattern in _INFRA_PATTERNS:
        if pattern.endswith("/"):
            if f.startswith(pattern) or ("/" + pattern.rstrip("/") + "/") in f:
                return True
        elif "*" in pattern:
            if fnmatch.fnmatch(basename, pattern):
                return True
        else:
            if f == pattern or basename == pattern:
                return True
    return False


def _check_safety_fallback(
    labels: list[str],
    changed_files: list[str],
    cfg: dict,
) -> str | None:
    """Return a fallback_reason string if any safety trigger fires, else None."""
    safety_kw = _get_safety_keywords(cfg)
    sensitive_kw = _get_sensitive_keywords(cfg)
    exclude_paths = _get_exclude_paths(cfg)

    label_text = " ".join(labels).lower()

    # Safety keywords in labels
    if safety_kw and re.search(safety_kw, label_text, re.IGNORECASE):
        m = re.search(safety_kw, label_text, re.IGNORECASE)
        keyword = m.group(0) if m else "unknown"
        return f"safety_keyword:{keyword}"

    # Sensitive keywords in labels
    if sensitive_kw and re.search(sensitive_kw, label_text, re.IGNORECASE):
        m = re.search(sensitive_kw, label_text, re.IGNORECASE)
        keyword = m.group(0) if m else "unknown"
        return f"safety_keyword:{keyword}"

    for f in changed_files:
        # Hard-exclude paths from config
        for ex in exclude_paths:
            if ex in f:
                return f"safety_file:{f}"
        # Cross-cutting infra files
        if _is_infra_file(f):
            return f"safety_file:{f}"

    return None


# ── HTML comment header ────────────────────────────────────────────────────────

def _make_slice_comment(
    component: str | None,
    scenario: str,
    included: list[str],
    omitted: list[str],
    fallback: bool,
    fallback_reason: str | None,
) -> str:
    if fallback:
        return (
            f"<!-- architecture-slice: component={component} scenario={scenario}"
            f" fallback=true reason={fallback_reason}\n"
            f"     full ARCHITECTURE.md loaded -->\n"
        )
    included_str = ", ".join(included)
    omitted_str = ", ".join(omitted)
    return (
        f"<!-- architecture-slice: component={component} scenario={scenario}\n"
        f"     included: {included_str}\n"
        f"     omitted: {omitted_str}\n"
        f"     (load full ARCHITECTURE.md if your change touches an omitted area) -->\n"
    )


# ── Main entry point ────────────────────────────────────────────────────────────

def slice_architecture(
    arch_path: str,
    scenario: str,
    spec_component: str | None = None,
    spec_file: str | None = None,
    changed_files: list[str] | None = None,
    labels: list[str] | None = None,
    clone_dir: str | None = None,
) -> SliceResult:
    """Return a SliceResult with a component-scoped or full-doc ARCHITECTURE.md slice."""
    changed_files = changed_files or []
    labels = labels or []

    cfg = _load_config(clone_dir)
    all_sections = _parse_sections(arch_path)
    all_section_names = list(all_sections.keys())

    # 0. Feature-disabled check — widen to full doc (fail-safe)
    if not _is_architecture_enabled(cfg):
        return _full_doc_result(arch_path, all_sections, all_section_names,
                                scenario, None, "feature_disabled")

    # 1. Resolve component
    component = spec_component or infer_component(spec_file, changed_files, labels)

    # 2. Safety fallback check (fires even when component is resolved)
    if component is not None:
        fallback_reason = _check_safety_fallback(labels, changed_files, cfg)
        if fallback_reason:
            return _full_doc_result(arch_path, all_sections, all_section_names,
                                    scenario, component, fallback_reason)

    # 3. Component unresolved → fallback
    if component is None:
        return _full_doc_result(arch_path, all_sections, all_section_names,
                                scenario, None, "component_unresolved")

    # 4. Component resolved — unknown component key → fallback
    wanted = COMPONENT_SECTION_MAP.get(component)
    if not wanted:
        return _full_doc_result(arch_path, all_sections, all_section_names,
                                scenario, component, f"unknown_component:{component}")

    # 5. Build slice
    included_sections = [s for s in wanted if s in all_sections]
    omitted_sections = [s for s in all_section_names if s not in included_sections]

    if not included_sections:
        return _full_doc_result(arch_path, all_sections, all_section_names,
                                scenario, component, "no_sections_matched")

    # 5a. Apply section-exclusion cap (drop tail sections until under cap; keep at least 1)
    max_tokens = _get_architecture_max_tokens(cfg)
    if max_tokens is not None:
        body = "".join(all_sections[s] for s in included_sections)
        while te.estimate_tokens(body) > max_tokens and len(included_sections) > 1:
            dropped = included_sections.pop()
            omitted_sections.insert(0, dropped)
            body = "".join(all_sections[s] for s in included_sections)
    else:
        body = "".join(all_sections[s] for s in included_sections)

    section_hashes = {s: te.hash_text(all_sections[s]) for s in included_sections}
    comment = _make_slice_comment(component, scenario, included_sections,
                                  omitted_sections, False, None)
    text = comment + body

    return SliceResult(
        text=text,
        component=component,
        scenario=scenario,
        included_sections=included_sections,
        omitted_sections=omitted_sections,
        section_hashes=section_hashes,
        fallback=False,
        fallback_reason=None,
    )


def _full_doc_result(
    arch_path: str,
    all_sections: dict[str, str],
    all_section_names: list[str],
    scenario: str,
    component: str | None,
    fallback_reason: str,
) -> SliceResult:
    try:
        with open(arch_path, encoding="utf-8") as f:
            full_text = f.read()
    except (FileNotFoundError, OSError):
        full_text = ""

    section_hashes = {s: te.hash_text(all_sections[s]) for s in all_section_names}
    comment = _make_slice_comment(component, scenario, all_section_names, [],
                                  True, fallback_reason)
    text = comment + full_text

    return SliceResult(
        text=text,
        component=component,
        scenario=scenario,
        included_sections=all_section_names,
        omitted_sections=[],
        section_hashes=section_hashes,
        fallback=True,
        fallback_reason=fallback_reason,
    )


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Emit a component-scoped ARCHITECTURE.md slice.",
        add_help=True,
    )
    parser.add_argument("--arch-file", required=True)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--spec-component", default=None)
    parser.add_argument("--spec-file", default=None)
    parser.add_argument("--changed-files", nargs="*", default=[])
    parser.add_argument("--labels", nargs="*", default=[])
    parser.add_argument("--clone-dir", default=None)
    parser.add_argument("--out-json", default=None, help="Write SliceResult metadata sidecar")
    args = parser.parse_args()

    result = slice_architecture(
        arch_path=args.arch_file,
        scenario=args.scenario,
        spec_component=args.spec_component,
        spec_file=args.spec_file,
        changed_files=args.changed_files,
        labels=args.labels,
        clone_dir=args.clone_dir,
    )

    print(result.text, end="")

    if args.out_json:
        sidecar = {
            "component": result.component,
            "scenario": result.scenario,
            "included_sections": result.included_sections,
            "omitted_sections": result.omitted_sections,
            "section_hashes": result.section_hashes,
            "fallback": result.fallback,
            "fallback_reason": result.fallback_reason,
        }
        os.makedirs(os.path.dirname(os.path.abspath(args.out_json)), exist_ok=True)
        with open(args.out_json, "w", encoding="utf-8") as f:
            json.dump(sidecar, f, indent=2)

    sys.exit(0)


if __name__ == "__main__":
    main()
