# Token Optimization Quality & Safety Evaluation — Implementation Plan

**Date:** 2026-07-02
**Issue:** [#672](https://github.com/omniscient/markethawk/issues/672)
**Spec:** [2026-07-02-token-optimization-eval-design.md](../specs/2026-07-02-token-optimization-eval-design.md)
**Branch:** `refine/issue-672-evaluate-token-optimization-quality-and-`

---

## Goal

Create a reusable offline Python eval script (`dark-factory/evals/token_opt_eval.py`) that proves the #663 token optimizations reduce context size without dropping safety-critical rules or required ARCHITECTURE.md sections. The script calls `assemble_pack()` from `context_pack.py` twice per issue/scenario — baseline (full-doc fallback) and optimized (current slicing) — then compares token counts, checks safety rules, and emits a committed markdown scorecard.

---

## Architecture

The eval script is a standalone CLI tool that imports directly from the dark-factory scripts directory. It uses no LLM calls and produces deterministic output. The script follows the precedent of `dark-factory/evals/eval_memory_quality.py` and `dark-factory/bench/run_suite.sh` for structure.

**Key integration points:**

- `dark-factory/scripts/context_pack.py:assemble_pack()` — assembles actual context text + returns per-section token manifest
- `dark-factory/scripts/architecture_slice.py:COMPONENT_SECTION_MAP` — defines required sections per component
- `dark-factory/bench/suite.json` — provides the 10 bench issue numbers
- `gh issue view` — fetches issue metadata (body, labels) for each evaluated issue

**Baseline vs. Optimized call difference:**

| Mode | `labels` param | `spec_component` param | Effect |
|------|----------------|------------------------|--------|
| Baseline | `[]` | `None` | Triggers `component_unresolved` fallback → full ARCHITECTURE.md |
| Optimized | actual issue labels | `None` | Normal path → component-scoped slice |

---

## Tech Stack

- Python 3.11 (stdlib + `sys.path.insert` for local imports, same pattern as `context_budget.py`)
- `subprocess` for `gh issue view` calls
- `tempfile.TemporaryDirectory` for ephemeral issue.json and output files
- `json`, `re`, `datetime`, `argparse` (stdlib only — no new dependencies)

---

## File Structure

| File | Action | Description |
|------|--------|-------------|
| `dark-factory/evals/token_opt_eval.py` | **Create** | Main eval script |
| `dark-factory/evals/.gitignore` | **Create** | Gitignore `results/` directory |
| `dark-factory/evals/results/` | Dir (gitignored) | Runtime JSON output (not committed) |
| `dark-factory/evals/reports/` | Dir | Committed scorecard reports |
| `dark-factory/evals/reports/.gitkeep` | **Create** | Ensure directory is tracked by git |
| `dark-factory/evals/reports/token-opt-scorecard-2026-07-02.md` | **Create** (by script run) | Committed scorecard for this issue |
| `dark-factory/tests/test_token_opt_eval.py` | **Create** | Smoke tests for eval script |

---

## Tasks

### Task 1 — Set up eval directory structure and gitignore

**Files:**
- `dark-factory/evals/.gitignore`
- `dark-factory/evals/reports/.gitkeep`

**TDD steps:**

1. **Write failing test** — create `dark-factory/tests/test_token_opt_eval.py` with a test that asserts the eval script can be imported:

   ```python
   # dark-factory/tests/test_token_opt_eval.py
   import importlib.util, os, sys

   SCRIPT_PATH = os.path.join(
       os.path.dirname(__file__), "..", "evals", "token_opt_eval.py"
   )

   def test_eval_script_exists():
       assert os.path.exists(SCRIPT_PATH), f"Missing: {SCRIPT_PATH}"

   def test_eval_script_importable():
       spec = importlib.util.spec_from_file_location("token_opt_eval", SCRIPT_PATH)
       mod = importlib.util.module_from_spec(spec)
       # Suppress sys.exit from argparse at module level
       try:
           spec.loader.exec_module(mod)
       except SystemExit:
           pass
       assert hasattr(mod, "SAFETY_RULES")
       assert hasattr(mod, "TIER1_SCENARIOS")

   def test_reports_dir_exists():
       reports_dir = os.path.join(
           os.path.dirname(__file__), "..", "evals", "reports"
       )
       assert os.path.isdir(reports_dir), f"Missing dir: {reports_dir}"
   ```

2. **Verify fail:**
   ```
   cd /workspace/markethawk
   python3 -m pytest dark-factory/tests/test_token_opt_eval.py -v
   # Expected: FAILED — token_opt_eval.py and reports/ do not exist
   ```
   Expected output:
   ```
   FAILED test_eval_script_exists - AssertionError: Missing: .../evals/token_opt_eval.py
   FAILED test_reports_dir_exists - AssertionError: Missing dir: .../evals/reports
   ```

3. **Implement** — create the directory structure:

   Create `dark-factory/evals/.gitignore`:
   ```
   # Per-run result JSONs are not committed (only scorecard reports are committed)
   results/
   __pycache__/
   *.pyc
   ```

   Create `dark-factory/evals/reports/.gitkeep`:
   ```
   ```
   (empty file)

4. **Verify pass:**
   ```
   python3 -m pytest dark-factory/tests/test_token_opt_eval.py::test_reports_dir_exists -v
   # Expected: PASSED
   ```

5. **Commit:**
   ```
   git add dark-factory/evals/.gitignore dark-factory/evals/reports/.gitkeep dark-factory/tests/test_token_opt_eval.py
   git commit -m "test(eval): scaffold eval dir structure + smoke test for token_opt_eval"
   ```

---

### Task 2 — Write `token_opt_eval.py`: constants, issue fetching, and context-pack assembly

**Files:**
- `dark-factory/evals/token_opt_eval.py`

**TDD steps:**

1. **Write failing test** — add tests for the `fetch_issue` and `run_assemble_pack` helpers to `test_token_opt_eval.py`:

   ```python
   def test_safety_rules_nonempty():
       spec = importlib.util.spec_from_file_location("token_opt_eval", SCRIPT_PATH)
       mod = importlib.util.module_from_spec(spec)
       try:
           spec.loader.exec_module(mod)
       except SystemExit:
           pass
       assert len(mod.SAFETY_RULES) >= 7
       assert "alembic upgrade head" in mod.SAFETY_RULES
       assert "npx tsc --noEmit" in mod.SAFETY_RULES

   def test_tier1_scenarios():
       spec = importlib.util.spec_from_file_location("token_opt_eval", SCRIPT_PATH)
       mod = importlib.util.module_from_spec(spec)
       try:
           spec.loader.exec_module(mod)
       except SystemExit:
           pass
       assert mod.TIER1_SCENARIOS == ["refine", "plan", "implement"]
   ```

2. **Verify fail:**
   ```
   python3 -m pytest dark-factory/tests/test_token_opt_eval.py::test_safety_rules_nonempty -v
   # Expected: FAILED — module doesn't exist yet
   ```

3. **Implement** — create `dark-factory/evals/token_opt_eval.py`:

   ```python
   """Token optimization quality & safety evaluation — issue #672.

   Compares baseline (full-doc ARCHITECTURE.md) vs. optimized (component-scoped slice)
   context packs across the 10 bench suite issues + supplemental labeled issues.

   Usage:
     python3 dark-factory/evals/token_opt_eval.py \
       --clone-dir /workspace/markethawk \
       --output-dir dark-factory/evals

   Options:
     --clone-dir DIR    Repo root (default: /workspace/markethawk)
     --output-dir DIR   Where to write results/ and reports/ (default: dark-factory/evals)
     --issues N,N,...   Comma-separated list of issue numbers (overrides suite.json + supplementals)
     --dry-run          Print issue list and exit without running eval
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

   # ── Constants ─────────────────────────────────────────────────────────────────

   TIER1_SCENARIOS = ["refine", "plan", "implement"]

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
           "comments": [],   # comments not needed for token comparison
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

       # Write issue.json to temp dir
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

       # Architecture section info from optimized manifest
       arch_section = opt_manifest.get("sections", {}).get("architecture_md", {})
       component = arch_section.get("component")
       included_arch = arch_section.get("included_sections", [])
       omitted_arch = arch_section.get("omitted_sections", [])
       fallback = arch_section.get("fallback", True)

       # Safety checks
       safety = _check_safety_rules(baseline_text, opt_text)

       # Section presence check
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


   def safety_verdict(safety: dict) -> str:
       """Return '✅ PASS', '⚠️ GAP', or '🔴 REGRESSION'."""
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
   ) -> dict:
       """Run the full evaluation; return aggregated results dict."""
       suite_json = os.path.join(clone_dir, "dark-factory", "bench", "suite.json")
       bench_issues = load_bench_issues(suite_json)

       if issue_override:
           all_issues = issue_override
       else:
           all_issues = bench_issues + SUPPLEMENTAL_SCOPE_SPILLOVER + SUPPLEMENTAL_FACTORY_REGRESSION

       # Deduplicate, preserve order
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

       all_results: list[dict] = []

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

               for scenario in TIER1_SCENARIOS:
                   print(f"  scenario={scenario} ...", end="", flush=True)
                   try:
                       result = eval_issue_scenario(issue, scenario, clone_dir, tmp_dir)
                       verdict = safety_verdict(result["safety"])
                       savings = result["savings_pct"]
                       print(f" baseline={result['baseline_tokens']:,} optimized={result['opt_tokens']:,} savings={savings}% safety={verdict}")
                       all_results.append(result)
                   except Exception as e:
                       print(f" ERROR: {e}", file=sys.stderr)
                       all_results.append({
                           "issue": issue_num,
                           "scenario": scenario,
                           "status": "error",
                           "error": str(e),
                       })

       date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
       json_path = os.path.join(results_dir, f"token-opt-eval-{date_str}.json")
       with open(json_path, "w", encoding="utf-8") as f:
           json.dump({"generated_at": datetime.now(timezone.utc).isoformat(),
                      "results": all_results}, f, indent=2)
       print(f"\nResults written: {json_path}")

       return {"results": all_results, "json_path": json_path, "date": date_str}


   # ── Report generation ─────────────────────────────────────────────────────────

   def generate_scorecard(eval_data: dict, output_dir: str, clone_dir: str) -> str:
       """Generate markdown scorecard from eval results. Returns path to scorecard."""
       results = eval_data["results"]
       date_str = eval_data["date"]

       # Build summary data per issue (aggregate across scenarios)
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
       lines.append("## Per-Issue Savings (Tier 1: refine / plan / implement)")
       lines.append("")
       lines.append("| Issue | Component | Scenario | Baseline (tok) | Optimized (tok) | Savings % | Safety |")
       lines.append("|-------|-----------|----------|----------------|-----------------|-----------|--------|")

       for num in sorted(by_issue.keys()):
           for r in by_issue[num]:
               component = r.get("component") or "—"
               scenario = r.get("scenario", "?")
               baseline = r.get("baseline_tokens", 0)
               opt = r.get("opt_tokens", 0)
               savings = r.get("savings_pct", 0.0)
               verdict = safety_verdict(r.get("safety", {}))
               lines.append(
                   f"| #{num} | {component} | {scenario} | {baseline:,} | {opt:,} | {savings}% | {verdict} |"
               )

       lines.append("")
       lines.append("---")
       lines.append("")
       lines.append("## Safety Check Details")
       lines.append("")
       lines.append("Status values: `pass` | `gap:pre-existing` | `gap:regression`")
       lines.append("")

       # Build safety table — rows are rules, columns are issue#scenario
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

       # One row per issue (use first scenario's architecture data)
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

       # Compute per-scenario aggregate safety
       scenario_safety: dict[str, list[str]] = {s: [] for s in TIER1_SCENARIOS}
       scenario_savings: dict[str, list[float]] = {s: [] for s in TIER1_SCENARIOS}
       for r in results:
           if r.get("status") in ("skipped", "error") or "safety" not in r:
               continue
           s = r.get("scenario", "")
           if s in scenario_safety:
               scenario_safety[s].append(safety_verdict(r["safety"]))
               scenario_savings[s].append(r.get("savings_pct", 0.0))

       safe_to_enforce = []
       needs_review = []
       for s in TIER1_SCENARIOS:
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
       args = parser.parse_args()

       clone_dir = args.clone_dir
       output_dir = args.output_dir or os.path.join(clone_dir, "dark-factory", "evals")
       issue_override = None
       if args.issues:
           issue_override = [int(n.strip()) for n in args.issues.split(",") if n.strip()]

       eval_data = run_eval(clone_dir, output_dir, issue_override, args.dry_run)

       if not eval_data.get("dry_run"):
           generate_scorecard(eval_data, output_dir, clone_dir)


   if __name__ == "__main__":
       main()
   ```

4. **Verify pass:**
   ```
   python3 -m pytest dark-factory/tests/test_token_opt_eval.py -v
   # Expected: all 5 tests PASSED
   ```
   Expected output:
   ```
   PASSED test_eval_script_exists
   PASSED test_eval_script_importable
   PASSED test_reports_dir_exists
   PASSED test_safety_rules_nonempty
   PASSED test_tier1_scenarios
   ```

5. **Commit:**
   ```
   git add dark-factory/evals/token_opt_eval.py dark-factory/tests/test_token_opt_eval.py
   git commit -m "feat(eval): token optimization quality & safety eval script (#672)"
   ```

---

### Task 3 — Run the eval on bench suite + commit scorecard

**Files:**
- `dark-factory/evals/reports/token-opt-scorecard-2026-07-02.md` (generated, then committed)

**TDD steps:**

1. **Write failing test** — add a test that checks the scorecard report exists and has the expected structure:

   ```python
   import glob

   def test_scorecard_report_committed():
       reports_dir = os.path.join(
           os.path.dirname(__file__), "..", "evals", "reports"
       )
       scorecards = glob.glob(os.path.join(reports_dir, "token-opt-scorecard-*.md"))
       assert scorecards, f"No scorecard reports found in {reports_dir}"

   def test_scorecard_has_required_sections():
       reports_dir = os.path.join(
           os.path.dirname(__file__), "..", "evals", "reports"
       )
       scorecards = sorted(glob.glob(os.path.join(reports_dir, "token-opt-scorecard-*.md")))
       with open(scorecards[-1], encoding="utf-8") as f:
           text = f.read()
       assert "Per-Issue Savings" in text
       assert "Safety Check Details" in text
       assert "Section Coverage" in text
       assert "Recommendations" in text
   ```

2. **Verify fail:**
   ```
   python3 -m pytest dark-factory/tests/test_token_opt_eval.py::test_scorecard_report_committed -v
   # Expected: FAILED — no scorecard exists yet
   ```

3. **Implement** — run the eval script (dry-run first, then full run):

   **Dry run to verify corpus:**
   ```bash
   cd /workspace/markethawk
   python3 dark-factory/evals/token_opt_eval.py \
     --clone-dir /workspace/markethawk \
     --output-dir dark-factory/evals \
     --dry-run
   ```
   Expected output:
   ```
   Evaluation corpus: 18 issues
   Issues: [224, 332, 289, 299, 286, 276, 287, 215, 285, 249, 579, 564, 523, 503, 632, 673, 695, ...]
   [dry-run] Exiting without running eval.
   ```

   **Full run:**
   ```bash
   python3 dark-factory/evals/token_opt_eval.py \
     --clone-dir /workspace/markethawk \
     --output-dir dark-factory/evals
   ```
   Expected output (example rows):
   ```
   Evaluation corpus: 18 issues

   ── Issue #224 ──
     scenario=refine ... baseline=52,400 optimized=32,100 savings=38.7% safety=✅ PASS
     scenario=plan ... baseline=54,200 optimized=33,800 savings=37.6% safety=✅ PASS
     scenario=implement ... baseline=48,100 optimized=28,400 savings=40.9% safety=✅ PASS
   ...
   Results written: dark-factory/evals/results/token-opt-eval-2026-07-02.json
   Scorecard written: dark-factory/evals/reports/token-opt-scorecard-2026-07-02.md
   ```

   **Inspect the scorecard:**
   ```bash
   cat dark-factory/evals/reports/token-opt-scorecard-2026-07-02.md
   ```
   Verify:
   - Savings % column has non-zero values for at least 5 issues
   - Safety column shows `✅ PASS` or `⚠️ GAP` (no `🔴 REGRESSION`)
   - Recommendations section names which scenarios are safe to enforce

4. **Verify pass:**
   ```
   python3 -m pytest dark-factory/tests/test_token_opt_eval.py -v
   # Expected: all 7 tests PASSED
   ```

5. **Commit:**
   ```
   git add dark-factory/evals/reports/token-opt-scorecard-2026-07-02.md \
           dark-factory/tests/test_token_opt_eval.py
   git commit -m "feat(eval): token opt scorecard for issue #672 — run results committed"
   ```

---

## Acceptance Criteria Checklist

From the issue body:

- [ ] Compare baseline vs optimized context packs across ≥5 historical runs — satisfied by 10 bench issues × 3 Tier 1 scenarios = 30 data points
- [ ] Verify optimized packs still include safety-critical rules — `SAFETY_RULES` string presence check in `_check_safety_rules()`
- [ ] Identify any missed context that would have changed outcome — section presence check in `_check_section_presence()` + `gap:pre-existing` vs `gap:regression` attribution
- [ ] Produce a scorecard with estimated token savings by scenario — `token-opt-scorecard-YYYY-MM-DD.md` committed to `dark-factory/evals/reports/`
- [ ] Recommend which scenarios are safe to enforce first — Recommendations section in scorecard

---

## Key Design Decisions

1. **Use `assemble_pack()` not `build_budget()`**: The spec says to call `build_budget()` but the eval needs actual text for string presence checks. `assemble_pack()` from `context_pack.py` supersedes `build_budget()` — it both assembles the text AND writes the same JSON manifest. The token counts are read from the JSON manifest.

2. **Baseline trigger mechanism**: Passing `labels=[]` and `spec_component=None` to `assemble_pack()` → propagated to `slice_architecture()` → triggers `component_unresolved` fallback → full ARCHITECTURE.md loaded. This matches Assumption A1 in the spec exactly.

3. **Graceful skip for unavailable issues**: Issues where `gh issue view` fails (e.g. #695–#700 with `needs-discussion`) are logged and skipped with `status: skipped` in the JSON — no crash.

4. **Output file naming**: `results/` is gitignored (per `.gitignore` in `dark-factory/evals/`); `reports/` scorecard is committed. This follows the existing `dark-factory/bench/results/` (gitignored) vs `baseline.md` (committed) pattern.

5. **No new dependencies**: The script uses only stdlib + the existing `context_pack.py` / `architecture_slice.py` imports that are already on the Python path in the factory container.
