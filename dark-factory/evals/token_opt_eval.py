"""Token optimization quality & safety evaluation — issue #672.

Compares baseline (full-doc ARCHITECTURE.md) vs. optimized (component-scoped slice)
context packs across the 10 bench suite issues + supplemental labeled issues.

Usage:
  python3 dark-factory/evals/token_opt_eval.py \\
    --clone-dir /workspace/markethawk \\
    --output-dir dark-factory/evals

Options:
  --clone-dir DIR    Repo root (default: /workspace/markethawk)
  --output-dir DIR   Where to write results/ and reports/ (default: dark-factory/evals)
  --issues N,N,...   Comma-separated list of issue numbers (overrides suite.json + supplementals)
  --dry-run          Print issue list and exit without running eval
  --calibrate        Also run budget-calibration sweep and emit scorecard
  --budgets N,N,...  Comma-separated candidate budgets for --calibrate (default: 22000,24000,...)
  --scenarios S,...  Comma-separated scenarios for --calibrate (default: all 5 enforcement scenarios)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# ── Script directory is dark-factory/evals; scripts are one level up in scripts/
_SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
sys.path.insert(0, _SCRIPTS_DIR)

import architecture_slice as aslice
from context_pack import assemble_pack

# ── Fail-open import of budget_enforce (T1, may not be present in all envs) ──

try:
    from budget_enforce import derive_caps as _derive_caps, _load_config as _be_load_config
    _BUDGET_ENFORCE_AVAILABLE = True
except Exception:
    _BUDGET_ENFORCE_AVAILABLE = False

# ── Constants ─────────────────────────────────────────────────────────────────

ENFORCEMENT_SCENARIOS = ["refine", "plan", "implement", "conformance", "code-review"]
TIER1_SCENARIOS = ENFORCEMENT_SCENARIOS  # backward-compat alias

_DEFAULT_BUDGET_SWEEP = [22000, 24000, 26000, 28000, 30000, 32000, 36000, 40000]
_DEFAULT_CONFIG_PATH = ".claude/skills/refinement/config.yaml"
_OVER_BUDGET_RATE_THRESHOLD = 0.10  # 10% max for safe-budget recommendation

SAFETY_RULES = [
    "alembic upgrade head",
    "alembic revision --autogenerate",
    "npx tsc --noEmit",
    "docker-compose logs backend",
    "models/__init__.py",
    "Import and add it to",
    "curl",
]

# Supplemental issues by label category
SUPPLEMENTAL_SCOPE_SPILLOVER = [579, 564, 523, 503]
SUPPLEMENTAL_FACTORY_REGRESSION = [632, 673, 695, 696, 697, 698, 699, 700]

REPO = "omniscient/markethawk"

# ── Issue fetching ────────────────────────────────────────────────────────────


def fetch_issue(issue_num: int, repo: str = REPO) -> dict | None:
    """Fetch issue metadata via gh CLI. Returns None if unavailable."""
    try:
        result = subprocess.run(
            ["gh", "issue", "view", str(issue_num), "--repo", repo,
             "--json", "number,title,body,labels"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            print(f"  [skip] #{issue_num}: gh error: {result.stderr.strip()[:120]}", file=sys.stderr)
            return None
        data = json.loads(result.stdout)
        return data
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as e:
        print(f"  [skip] #{issue_num}: {e}", file=sys.stderr)
        return None


def issue_labels(issue: dict) -> list[str]:
    """Extract label name strings from gh issue JSON."""
    return [lbl["name"] for lbl in issue.get("labels", []) if isinstance(lbl, dict)]


def build_issue_json(issue: dict) -> str:
    """Serialize issue to the format expected by context_pack.assemble_pack() (issue.json)."""
    return json.dumps({
        "number": issue.get("number"),
        "title": issue.get("title", ""),
        "body": issue.get("body") or "",
        "comments": [],
        "labels": issue.get("labels", []),
    })

# ── Context-pack assembly ─────────────────────────────────────────────────────


def _run_assemble(
    scenario: str,
    issue_num: int,
    clone_dir: str,
    issue_json_path: str,
    out_dir: str,
    labels: list[str] | None,
    spec_component: str | None,
    mode: str,
) -> tuple[str, dict]:
    """Call assemble_pack() for one scenario and return (md_text, manifest_dict).

    mode is 'baseline' or 'optimized' — used only for temp file naming.
    """
    out_md = os.path.join(out_dir, f"{issue_num}-{scenario}-{mode}.md")
    out_json = os.path.join(out_dir, f"{issue_num}-{scenario}-{mode}.json")
    assemble_pack(
        scenario=scenario,
        issue_num=issue_num,
        run_id=f"eval-{mode}",
        clone_dir=clone_dir,
        out_md=out_md,
        out_json=out_json,
        issue_json=issue_json_path,
        labels=labels,
        spec_component=spec_component,
    )
    with open(out_md, encoding="utf-8") as f:
        md_text = f.read()
    with open(out_json, encoding="utf-8") as f:
        manifest = json.load(f)
    return md_text, manifest


def eval_issue_scenario(
    issue: dict,
    scenario: str,
    clone_dir: str,
    tmp_dir: str,
) -> dict:
    """Run baseline + optimized assembly for one issue/scenario; return result dict."""
    issue_num = issue["number"]
    labels = issue_labels(issue)

    issue_json_path = os.path.join(tmp_dir, f"{issue_num}-issue.json")
    with open(issue_json_path, "w", encoding="utf-8") as f:
        f.write(build_issue_json(issue))

    # Baseline: no labels/component → component_unresolved → full-doc fallback
    baseline_text, baseline_manifest = _run_assemble(
        scenario=scenario,
        issue_num=issue_num,
        clone_dir=clone_dir,
        issue_json_path=issue_json_path,
        out_dir=tmp_dir,
        labels=[],
        spec_component=None,
        mode="baseline",
    )

    # Optimized: actual labels → component-scoped slice
    opt_text, opt_manifest = _run_assemble(
        scenario=scenario,
        issue_num=issue_num,
        clone_dir=clone_dir,
        issue_json_path=issue_json_path,
        out_dir=tmp_dir,
        labels=labels,
        spec_component=None,
        mode="optimized",
    )

    baseline_tokens = baseline_manifest.get("estimated_input_tokens", 0)
    opt_tokens = opt_manifest.get("estimated_input_tokens", 0)
    savings_pct = (
        round((baseline_tokens - opt_tokens) / baseline_tokens * 100, 1)
        if baseline_tokens > 0 else 0.0
    )

    arch_section = opt_manifest.get("sections", {}).get("architecture_md", {})
    component = arch_section.get("component")
    included_arch = arch_section.get("included_sections", [])
    omitted_arch = arch_section.get("omitted_sections", [])
    fallback = arch_section.get("fallback", True)

    safety = _check_safety_rules(baseline_text, opt_text)
    section_check = _check_section_presence(component, opt_text, included_arch)

    return {
        "issue": issue_num,
        "title": issue.get("title", ""),
        "scenario": scenario,
        "component": component,
        "fallback": fallback,
        "baseline_tokens": baseline_tokens,
        "opt_tokens": opt_tokens,
        "savings_pct": savings_pct,
        "safety": safety,
        "section_check": section_check,
        "included_arch_sections": included_arch,
        "omitted_arch_sections": omitted_arch,
        "opt_manifest": opt_manifest,
    }

# ── Safety rule checks ────────────────────────────────────────────────────────


def _check_safety_rules(baseline_text: str, opt_text: str) -> dict:
    """Return per-rule status: 'pass', 'gap:pre-existing', or 'gap:regression'."""
    results = {}
    for rule in SAFETY_RULES:
        in_baseline = rule in baseline_text
        in_opt = rule in opt_text
        if in_opt:
            results[rule] = "pass"
        elif not in_baseline:
            results[rule] = "gap:pre-existing"
        else:
            results[rule] = "gap:regression"
    return results


def safety_verdict(safety: dict, section_check: dict | None = None) -> str:
    """Return '✅ PASS', '⚠️ GAP', or '🔴 REGRESSION'.

    The primary slice-regression signal is section_check: a component-required
    ARCHITECTURE.md section that the optimized (sliced) pack dropped ("missing")
    is a real regression on the ACTUAL optimized surface. The SAFETY_RULES
    strings live in CLAUDE.md, which is never sliced, so they can only ever be a
    supplementary sanity check — they cannot detect slice-induced content loss.
    """
    if section_check and any(v == "missing" for v in section_check.values()):
        return "🔴 REGRESSION"
    if any(v == "gap:regression" for v in safety.values()):
        return "🔴 REGRESSION"
    if any(v == "gap:pre-existing" for v in safety.values()):
        return "⚠️ GAP"
    return "✅ PASS"

# ── Section presence checks ───────────────────────────────────────────────────


def _check_section_presence(
    component: str | None,
    opt_text: str,
    included_arch: list[str],
) -> dict:
    """Check that COMPONENT_SECTION_MAP required sections appear in opt_text."""
    if component is None or component not in aslice.COMPONENT_SECTION_MAP:
        return {"status": "skipped", "reason": "component_unresolved_or_unknown"}

    required = aslice.COMPONENT_SECTION_MAP[component]
    results = {}
    for section in required:
        heading = f"## {section}"
        results[section] = "present" if heading in opt_text else "missing"
    return results

# ── Budget calibration ────────────────────────────────────────────────────────


def _get_default_budget_tokens(clone_dir: str) -> int:
    """Read default_budget_tokens from config.yaml; fall back to 30000."""
    config_path = os.path.join(clone_dir, _DEFAULT_CONFIG_PATH)
    try:
        if not _BUDGET_ENFORCE_AVAILABLE:
            raise ImportError("budget_enforce unavailable")
        cfg = _be_load_config(config_path)
        val = cfg.get("token_optimization", {}).get("default_budget_tokens")
        if val is not None:
            return int(val)
    except Exception:
        pass
    # Fallback: parse yaml manually with a simple regex
    try:
        with open(config_path, encoding="utf-8") as f:
            text = f.read()
        m = re.search(r"default_budget_tokens\s*:\s*(\d+)", text)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return 30000


def _build_budget_sweep(budgets_override: list[int] | None, clone_dir: str) -> list[int]:
    """Build final budget sweep list including config default."""
    base = list(budgets_override) if budgets_override else list(_DEFAULT_BUDGET_SWEEP)
    default = _get_default_budget_tokens(clone_dir)
    if default not in base:
        base.append(default)
    return sorted(set(base))


def simulate_enforcement(
    result: dict,
    budget: int,
    config: dict,
) -> dict:
    """Simulate what budget_enforce.derive_caps() would do for one issue/scenario/budget row.

    Returns a dict with enforcement simulation fields, or a calibration_error row on failure.
    """
    if not _BUDGET_ENFORCE_AVAILABLE:
        return {
            "issue": result["issue"],
            "scenario": result["scenario"],
            "budget": budget,
            "status": "calibration_error",
            "error": "budget_enforce not available",
        }

    opt_manifest = result.get("opt_manifest", {})
    sections = opt_manifest.get("sections", {})
    arch_fallback = result.get("fallback", True)

    try:
        br = _derive_caps(
            sections=sections,
            budget=budget,
            arch_fallback=arch_fallback,
            config=config,
            scenario=result.get("scenario", "unknown"),
        )

        # section_at_risk: arch_fallback=False AND derived arch cap < opt arch tokens
        section_at_risk = False
        if not arch_fallback:
            arch_sec = sections.get("architecture_md", {})
            opt_arch_tokens = int(arch_sec.get("tokens", 0)) if arch_sec.get("status", "dropped") != "dropped" else 0
            derived_arch = br.derived_caps.get("architecture_md", None)
            if derived_arch is not None and opt_arch_tokens > 0:
                section_at_risk = derived_arch < opt_arch_tokens

        # Also propagate pre-existing section_check "missing" verdicts
        section_check = result.get("section_check", {})
        if any(v == "missing" for v in section_check.values()):
            section_at_risk = True

        return {
            "issue": result["issue"],
            "scenario": result["scenario"],
            "budget": budget,
            "over_budget": br.over_budget,
            "would_trim": br.would_trim,
            "derived_caps": br.derived_caps,
            "section_at_risk": section_at_risk,
            "reserved_tokens": br.reserved_tokens,
            "allowance": br.allowance,
            "opt_tokens": result.get("opt_tokens", 0),
        }
    except Exception as e:
        return {
            "issue": result["issue"],
            "scenario": result["scenario"],
            "budget": budget,
            "status": "calibration_error",
            "error": str(e),
        }


def calibrate_issue(
    result: dict,
    budget_sweep: list[int],
    config: dict,
) -> list[dict]:
    """Run enforcement simulation across all candidate budgets for one issue/scenario result."""
    rows = []
    for budget in budget_sweep:
        row = simulate_enforcement(result, budget, config)
        rows.append(row)
    return rows


def safe_budget_recommendation(
    scenario_rows: list[dict],
    budget_sweep: list[int],
) -> str:
    """Find lowest budget where section_at_risk_rate==0 AND over_budget_rate<=10%.

    Returns the budget as a string, or 'none — widen --budgets' if none qualifies.
    """
    for budget in sorted(budget_sweep):
        budget_rows = [r for r in scenario_rows if r.get("budget") == budget
                       and r.get("status") != "calibration_error"]
        if not budget_rows:
            continue
        total = len(budget_rows)
        risk_count = sum(1 for r in budget_rows if r.get("section_at_risk"))
        over_count = sum(1 for r in budget_rows if r.get("over_budget"))
        section_at_risk_rate = risk_count / total
        over_budget_rate = over_count / total
        if section_at_risk_rate == 0.0 and over_budget_rate <= _OVER_BUDGET_RATE_THRESHOLD:
            return str(budget)
    return "none — widen --budgets"


def _percentile(values: list[float], pct: int) -> float:
    """Compute the pct-th percentile of a sorted list."""
    if not values:
        return 0.0
    sv = sorted(values)
    idx = (pct / 100) * (len(sv) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(sv) - 1)
    frac = idx - lo
    return sv[lo] + frac * (sv[hi] - sv[lo])


def generate_calibration_scorecard(
    calibration_rows: list[dict],
    eval_results: list[dict],
    budget_sweep: list[int],
    scenarios: list[str],
    output_dir: str,
    date_str: str,
) -> str:
    """Generate budget-calibration scorecard markdown. Returns path to file."""
    lines: list[str] = []
    lines.append(f"# Budget Calibration Scorecard — {date_str}")
    lines.append("")
    lines.append("**Issue:** [#718](https://github.com/omniscient/markethawk/issues/718)")
    lines.append("**Script:** `dark-factory/evals/token_opt_eval.py --calibrate`")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Per-Scenario Token Distribution (opt_tokens)")
    lines.append("")
    lines.append("| Scenario | p50 (tok) | p90 (tok) | p90×1.1 advisory |")
    lines.append("|----------|-----------|-----------|------------------|")

    scenario_opt_tokens: dict[str, list[float]] = {s: [] for s in scenarios}
    for r in eval_results:
        s = r.get("scenario", "")
        if s in scenario_opt_tokens and "opt_tokens" in r:
            scenario_opt_tokens[s].append(float(r["opt_tokens"]))

    for s in scenarios:
        vals = scenario_opt_tokens[s]
        p50 = _percentile(vals, 50)
        p90 = _percentile(vals, 90)
        advisory = p90 * 1.1
        lines.append(f"| {s} | {int(p50):,} | {int(p90):,} | {int(advisory):,} |")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Over-Budget Rate and Section-at-Risk Rate per Scenario × Budget")
    lines.append("")

    budget_cols = " | ".join(f"{b:,}" for b in sorted(budget_sweep))
    lines.append(f"| Scenario | Metric | {budget_cols} |")
    lines.append("|----------|--------|" + "--------|" * len(budget_sweep))

    for s in scenarios:
        s_rows = [r for r in calibration_rows if r.get("scenario") == s]
        ob_vals = []
        risk_vals = []
        for budget in sorted(budget_sweep):
            budget_rows = [r for r in s_rows if r.get("budget") == budget
                           and r.get("status") != "calibration_error"]
            total = len(budget_rows)
            if total == 0:
                ob_vals.append("—")
                risk_vals.append("—")
            else:
                ob_rate = sum(1 for r in budget_rows if r.get("over_budget")) / total
                risk_rate = sum(1 for r in budget_rows if r.get("section_at_risk")) / total
                ob_vals.append(f"{ob_rate:.0%}")
                risk_vals.append(f"{risk_rate:.0%}")
        ob_str = " | ".join(ob_vals)
        risk_str = " | ".join(risk_vals)
        lines.append(f"| {s} | over_budget_rate | {ob_str} |")
        lines.append(f"| {s} | section_at_risk_rate | {risk_str} |")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Safe-Budget Recommendations")
    lines.append("")
    lines.append("Criteria: `section_at_risk_rate == 0%` AND `over_budget_rate ≤ 10%`")
    lines.append("")
    lines.append("| Scenario | Recommended Budget |")
    lines.append("|----------|--------------------|")

    for s in scenarios:
        s_rows = [r for r in calibration_rows if r.get("scenario") == s]
        rec = safe_budget_recommendation(s_rows, budget_sweep)
        lines.append(f"| {s} | {rec} |")

    lines.append("")
    lines.append("---")
    lines.append("")

    # Unresolved component counts per scenario
    unresolved_counts: dict[str, int] = {s: 0 for s in scenarios}
    for r in eval_results:
        s = r.get("scenario", "")
        if s in unresolved_counts:
            sc = r.get("section_check", {})
            if sc.get("reason") == "component_unresolved_or_unknown":
                unresolved_counts[s] += 1

    lines.append("## Unresolved Component Counts (by Scenario)")
    lines.append("")
    lines.append("| Scenario | Issues with unresolved component |")
    lines.append("|----------|----------------------------------|")
    for s in scenarios:
        lines.append(f"| {s} | {unresolved_counts[s]} |")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*Generated by `dark-factory/evals/token_opt_eval.py --calibrate`*")

    reports_dir = os.path.join(output_dir, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    report_path = os.path.join(reports_dir, f"budget-calibration-scorecard-{date_str}.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Calibration scorecard written: {report_path}")
    return report_path

# ── Main eval loop ────────────────────────────────────────────────────────────


def load_bench_issues(suite_json_path: str) -> list[int]:
    """Load bench suite issue numbers from suite.json."""
    with open(suite_json_path, encoding="utf-8") as f:
        data = json.load(f)
    return [t["issue"] for t in data.get("tasks", [])]


def run_eval(
    clone_dir: str,
    output_dir: str,
    issue_override: list[int] | None = None,
    dry_run: bool = False,
    calibrate: bool = False,
    budgets_override: list[int] | None = None,
    scenarios_override: list[str] | None = None,
) -> dict:
    """Run the full evaluation; return aggregated results dict."""
    suite_json = os.path.join(clone_dir, "dark-factory", "bench", "suite.json")
    bench_issues = load_bench_issues(suite_json)

    if issue_override:
        all_issues = issue_override
    else:
        all_issues = bench_issues + SUPPLEMENTAL_SCOPE_SPILLOVER + SUPPLEMENTAL_FACTORY_REGRESSION

    seen: set[int] = set()
    deduped: list[int] = []
    for n in all_issues:
        if n not in seen:
            seen.add(n)
            deduped.append(n)
    all_issues = deduped

    print(f"Evaluation corpus: {len(all_issues)} issues")
    print(f"Issues: {all_issues}")

    if dry_run:
        print("[dry-run] Exiting without running eval.")
        return {"dry_run": True, "issues": all_issues}

    results_dir = os.path.join(output_dir, "results")
    os.makedirs(results_dir, exist_ok=True)

    # Determine which scenarios to use for calibration
    calib_scenarios = scenarios_override if scenarios_override else ENFORCEMENT_SCENARIOS

    # Scenarios used for the regular eval — always TIER1_SCENARIOS for backward compat
    eval_scenarios = ENFORCEMENT_SCENARIOS

    all_results: list[dict] = []
    calibration_rows: list[dict] = []

    # Load budget_enforce config once for the calibration sweep
    calib_config: dict | None = None
    budget_sweep: list[int] = []
    if calibrate:
        budget_sweep = _build_budget_sweep(budgets_override, clone_dir)
        print(f"Calibration budget sweep: {budget_sweep}")
        print(f"Calibration scenarios: {calib_scenarios}")
        if _BUDGET_ENFORCE_AVAILABLE:
            config_path = os.path.join(clone_dir, _DEFAULT_CONFIG_PATH)
            calib_config = _be_load_config(config_path)
        else:
            print("[warn] budget_enforce not available; calibration rows will be error rows", file=sys.stderr)
            calib_config = {}

    with tempfile.TemporaryDirectory(prefix="tokeval-") as tmp_dir:
        for issue_num in all_issues:
            print(f"\n── Issue #{issue_num} ──")
            issue = fetch_issue(issue_num)
            if issue is None:
                print(f"  [skip] #{issue_num}: could not fetch issue data")
                all_results.append({
                    "issue": issue_num, "status": "skipped",
                    "reason": "fetch_failed",
                })
                continue

            for scenario in eval_scenarios:
                print(f"  scenario={scenario} ...", end="", flush=True)
                try:
                    result = eval_issue_scenario(issue, scenario, clone_dir, tmp_dir)
                    verdict = safety_verdict(result["safety"], result.get("section_check"))
                    savings = result["savings_pct"]
                    print(
                        f" baseline={result['baseline_tokens']:,}"
                        f" optimized={result['opt_tokens']:,}"
                        f" savings={savings}%"
                        f" safety={verdict}"
                    )
                    # Store result without opt_manifest (large, not needed in JSON output)
                    result_for_json = {k: v for k, v in result.items() if k != "opt_manifest"}
                    all_results.append(result_for_json)

                    # Calibration: run sweep for this issue × scenario if in calib_scenarios
                    if calibrate and calib_config is not None and scenario in calib_scenarios:
                        rows = calibrate_issue(result, budget_sweep, calib_config)
                        calibration_rows.extend(rows)
                except Exception as e:
                    print(f" ERROR: {e}", file=sys.stderr)
                    all_results.append({
                        "issue": issue_num,
                        "scenario": scenario,
                        "status": "error",
                        "error": str(e),
                    })

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    output: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "results": all_results,
    }
    if calibrate:
        output["calibration_results"] = calibration_rows

    json_path = os.path.join(results_dir, f"token-opt-eval-{date_str}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    print(f"\nResults written: {json_path}")

    return {
        "results": all_results,
        "calibration_results": calibration_rows,
        "json_path": json_path,
        "date": date_str,
        "budget_sweep": budget_sweep,
        "calib_scenarios": calib_scenarios,
    }


# ── Report generation ─────────────────────────────────────────────────────────


def generate_scorecard(eval_data: dict, output_dir: str, clone_dir: str) -> str:
    """Generate markdown scorecard from eval results. Returns path to scorecard."""
    results = eval_data["results"]
    date_str = eval_data["date"]

    by_issue: dict[int, list[dict]] = {}
    for r in results:
        if r.get("status") in ("skipped", "error"):
            continue
        num = r["issue"]
        by_issue.setdefault(num, []).append(r)

    lines: list[str] = []
    lines.append(f"# Token Optimization Scorecard — {date_str}")
    lines.append("")
    lines.append("**Issue:** [#672](https://github.com/omniscient/markethawk/issues/672)")
    lines.append("**Script:** `dark-factory/evals/token_opt_eval.py`")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Per-Issue Savings (Enforcement scenarios: refine / plan / implement / conformance / code-review)")
    lines.append("")
    lines.append("| Issue | Component | Scenario | Baseline (tok) | Optimized (tok) | Savings % | Safety | Sliced? |")
    lines.append("|-------|-----------|----------|----------------|-----------------|-----------|--------|---------|")

    for num in sorted(by_issue.keys()):
        for r in by_issue[num]:
            component = r.get("component") or "—"
            scenario = r.get("scenario", "?")
            baseline = r.get("baseline_tokens", 0)
            opt = r.get("opt_tokens", 0)
            savings = r.get("savings_pct", 0.0)
            verdict = safety_verdict(r.get("safety", {}), r.get("section_check"))
            sliced = "no (fallback)" if r.get("fallback") else "yes"
            lines.append(
                f"| #{num} | {component} | {scenario} | {baseline:,} | {opt:,} | {savings}% | {verdict} | {sliced} |"
            )

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Safety Check Details")
    lines.append("")
    lines.append("Status values: `pass` | `gap:pre-existing` | `gap:regression`")
    lines.append("")

    issue_scenario_keys = [
        (r["issue"], r["scenario"])
        for r in results
        if r.get("status") not in ("skipped", "error") and "safety" in r
    ]
    if issue_scenario_keys:
        col_headers = " | ".join(f"#{n}/{s}" for n, s in issue_scenario_keys)
        lines.append(f"| Rule | {col_headers} |")
        lines.append("|------|" + "------|" * len(issue_scenario_keys))
        rule_rows: dict[str, list[str]] = {rule: [] for rule in SAFETY_RULES}
        for r in results:
            if r.get("status") in ("skipped", "error") or "safety" not in r:
                continue
            for rule in SAFETY_RULES:
                rule_rows[rule].append(r["safety"].get(rule, "—"))
        for rule, vals in rule_rows.items():
            row_vals = " | ".join(vals)
            lines.append(f"| `{rule}` | {row_vals} |")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Section Coverage")
    lines.append("")
    lines.append("| Issue | Component | Sections kept | Sections omitted |")
    lines.append("|-------|-----------|---------------|------------------|")

    for num in sorted(by_issue.keys()):
        first = by_issue[num][0]
        comp = first.get("component") or "—"
        kept = ", ".join(first.get("included_arch_sections", [])) or "—"
        omitted = ", ".join(first.get("omitted_arch_sections", [])) or "none"
        lines.append(f"| #{num} | {comp} | {kept} | {omitted} |")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Recommendations")
    lines.append("")

    scenario_safety: dict[str, list[str]] = {s: [] for s in ENFORCEMENT_SCENARIOS}
    scenario_savings: dict[str, list[float]] = {s: [] for s in ENFORCEMENT_SCENARIOS}
    for r in results:
        if r.get("status") in ("skipped", "error") or "safety" not in r:
            continue
        s = r.get("scenario", "")
        if s in scenario_safety:
            scenario_safety[s].append(safety_verdict(r["safety"], r.get("section_check")))
            scenario_savings[s].append(r.get("savings_pct", 0.0))

    safe_to_enforce = []
    needs_review = []
    for s in ENFORCEMENT_SCENARIOS:
        verdicts = scenario_safety[s]
        if not verdicts:
            continue
        has_regression = any("REGRESSION" in v for v in verdicts)
        avg_savings = sum(scenario_savings[s]) / len(scenario_savings[s]) if scenario_savings[s] else 0.0
        if has_regression:
            needs_review.append(f"`{s}` — regression detected; investigate before enforcing")
        else:
            safe_to_enforce.append(f"`{s}` — avg savings {avg_savings:.1f}%, no regressions")

    if safe_to_enforce:
        lines.append("**Scenarios safe to enforce (hard budget) first:**")
        for item in safe_to_enforce:
            lines.append(f"- {item}")
        lines.append("")
    if needs_review:
        lines.append("**Scenarios requiring further review:**")
        for item in needs_review:
            lines.append(f"- {item}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*Generated by `dark-factory/evals/token_opt_eval.py`*")

    reports_dir = os.path.join(output_dir, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    report_path = os.path.join(reports_dir, f"token-opt-scorecard-{date_str}.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Scorecard written: {report_path}")
    return report_path


# ── CLI ───────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Token optimization eval for issue #672")
    parser.add_argument("--clone-dir", default="/workspace/markethawk",
                        help="Repo root (default: /workspace/markethawk)")
    parser.add_argument("--output-dir", default=None,
                        help="Output base dir (default: <clone-dir>/dark-factory/evals)")
    parser.add_argument("--issues", default=None,
                        help="Comma-separated issue numbers (overrides suite.json + supplementals)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print issue list and exit without running eval")
    parser.add_argument("--calibrate", action="store_true",
                        help="Also run budget-calibration sweep and emit calibration scorecard")
    parser.add_argument("--budgets", default=None,
                        help="Comma-separated candidate budgets for --calibrate (e.g. 22000,30000)")
    parser.add_argument("--scenarios", default=None,
                        help="Comma-separated scenarios for --calibrate (default: all 5 enforcement scenarios)")
    args = parser.parse_args()

    clone_dir = args.clone_dir
    output_dir = args.output_dir or os.path.join(clone_dir, "dark-factory", "evals")
    issue_override = None
    if args.issues:
        issue_override = [int(n.strip()) for n in args.issues.split(",") if n.strip()]
    budgets_override = None
    if args.budgets:
        budgets_override = [int(n.strip()) for n in args.budgets.split(",") if n.strip()]
    scenarios_override = None
    if args.scenarios:
        scenarios_override = [s.strip() for s in args.scenarios.split(",") if s.strip()]

    eval_data = run_eval(
        clone_dir,
        output_dir,
        issue_override,
        args.dry_run,
        calibrate=args.calibrate,
        budgets_override=budgets_override,
        scenarios_override=scenarios_override,
    )

    if not eval_data.get("dry_run"):
        generate_scorecard(eval_data, output_dir, clone_dir)
        if args.calibrate and eval_data.get("calibration_results"):
            generate_calibration_scorecard(
                calibration_rows=eval_data["calibration_results"],
                eval_results=eval_data["results"],
                budget_sweep=eval_data["budget_sweep"],
                scenarios=eval_data["calib_scenarios"],
                output_dir=output_dir,
                date_str=eval_data["date"],
            )


if __name__ == "__main__":
    main()
