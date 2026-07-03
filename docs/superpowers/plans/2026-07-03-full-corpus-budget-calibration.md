# Phase 4b T1: Full-Corpus Budget Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run `token_opt_eval.py --calibrate` over the full bench corpus (18 issues), commit the generated scorecard and raw JSON, confirm or adjust the provisional 22k budgets for `conformance`/`code-review` with atomic config + test-guard updates, and report per-scenario p90 uncapped arch-slice sizes in the PR description. Leave all `enforce` flags at T6 state throughout.

**Architecture:** Operational calibration task — no new application code. The script `dark-factory/evals/token_opt_eval.py` already handles all eval + calibration logic. Conditional updates land in `.claude/skills/refinement/config.yaml`, `dark-factory/tests/test_budget_enforce_dag.py`, and `docs/agents/dark-factory-token-optimization.md`. All file changes commit in one atomic commit. The raw JSON excludes `opt_manifest` (stripped before serialization), so a standalone helper must re-call `assemble_pack()` to recover per-scenario p90 arch-slice token sizes.

**Tech Stack:** Python 3, `token_opt_eval.py`, `context_pack.assemble_pack()`, `budget_enforce.py` (all in `dark-factory/scripts/`), `pytest`, `gh` CLI, `git`.

---

## Artifact Map

| Status | Path |
|--------|------|
| Created by calibration script | `dark-factory/evals/results/token-opt-eval-<date>.json` |
| Created by calibration script | `dark-factory/evals/reports/budget-calibration-scorecard-<date>.md` |
| Conditionally modified | `.claude/skills/refinement/config.yaml` |
| Conditionally modified | `dark-factory/tests/test_budget_enforce_dag.py` |
| Conditionally modified | `docs/agents/dark-factory-token-optimization.md` |

All modified files commit together in a single atomic commit (Task 4).

---

### Task 1: Run Full-Corpus Budget Calibration

**Files:**
- Run (not modified): `dark-factory/evals/token_opt_eval.py`
- Created: `dark-factory/evals/results/token-opt-eval-<date>.json`
- Created: `dark-factory/evals/reports/budget-calibration-scorecard-<date>.md`

- [ ] Confirm the T6 test guard passes before any changes:
  ```bash
  cd /workspace/markethawk
  python -m pytest dark-factory/tests/test_budget_enforce_dag.py \
    -k "test_config_budgets_t6_state or test_config_enforce_t6_state" -v
  ```
  Expected: `2 passed`. This is the baseline: `conformance=22000`, `code-review=22000`; `enforce` flags at T6 state.

- [ ] Run the full-corpus calibration inside the factory container (no `--issues` filter = all 18 corpus issues, all 5 enforcement scenarios, default budget sweep `[22000, 24000, 26000, 28000, 30000, 32000, 36000, 40000]`):
  ```bash
  python3 dark-factory/evals/token_opt_eval.py --calibrate
  ```
  Expected terminal output ends with:
  ```
  Results written: dark-factory/evals/results/token-opt-eval-2026-07-03.json
  Calibration scorecard written: dark-factory/evals/reports/budget-calibration-scorecard-2026-07-03.md
  ```
  The run covers ~18 issues × 5 scenarios × 8 budgets. If the date rolls over midnight UTC during the run, the filename will use the date when the script started — use the actual filename that appears in the terminal output.

- [ ] Verify both artifacts exist and the JSON contains `calibration_results`:
  ```bash
  DATE=$(python3 -c "from datetime import datetime,timezone; print(datetime.now(timezone.utc).strftime('%Y-%m-%d'))")
  ls -lh dark-factory/evals/results/token-opt-eval-${DATE}.json
  ls -lh dark-factory/evals/reports/budget-calibration-scorecard-${DATE}.md
  python3 -c "
  import json, sys
  d = json.load(open('dark-factory/evals/results/token-opt-eval-${DATE}.json'))
  assert 'calibration_results' in d, 'calibration_results key missing'
  assert len(d.get('calibration_results', [])) > 0, 'calibration_results is empty'
  print(f\"OK: {len(d['results'])} eval results, {len(d['calibration_results'])} calibration rows\")
  "
  ```

No commit yet — all artifacts commit atomically in Task 4.

---

### Task 2: Interpret Scorecard and Conditionally Update Config, Test Guard, and Runbook

**Files:**
- Read: `dark-factory/evals/reports/budget-calibration-scorecard-<date>.md`
- Conditionally modified: `.claude/skills/refinement/config.yaml` (lines `conformance: 22000` / `code-review: 22000` under `token_optimization.budgets`)
- Conditionally modified: `dark-factory/tests/test_budget_enforce_dag.py` (lines 52–58, `expected` dict in `test_config_budgets_t6_state`)
- Conditionally modified: `docs/agents/dark-factory-token-optimization.md` (lines 191–196, budget table + provisional note)

- [ ] Read the "Safe-Budget Recommendations" table from the scorecard:
  ```bash
  DATE=$(python3 -c "from datetime import datetime,timezone; print(datetime.now(timezone.utc).strftime('%Y-%m-%d'))")
  # Use the actual filename from Task 1 if date differs
  grep -A 10 "Safe-Budget Recommendations" \
    dark-factory/evals/reports/budget-calibration-scorecard-${DATE}.md
  ```
  The table format is:
  ```
  | Scenario        | Recommended Budget         |
  |-----------------|----------------------------|
  | refine          | <value or "none — widen..."> |
  | plan            | <value or "none — widen..."> |
  | implement       | <value or "none — widen..."> |
  | conformance     | <value or "none — widen..."> |
  | code-review     | <value or "none — widen..."> |
  ```

**Branch A — "none — widen --budgets" appears for `conformance` or `code-review`:**

- [ ] Post a comment on issue #730 flagging the unexpected state:
  ```bash
  gh issue comment 730 --repo omniscient/markethawk --body "## Calibration Blocked — No Passing Budget Found

  The full-corpus calibration run ($(date +%Y-%m-%d)) found no candidate budget satisfying
  \`section_at_risk_rate == 0%\` AND \`over_budget_rate ≤ 10%\` for scenario(s): <FILL IN AFFECTED SCENARIOS>.

  Scorecard: \`dark-factory/evals/reports/budget-calibration-scorecard-$(date +%Y-%m-%d).md\`

  The provisional 22k budgets remain unchanged. Manual review required.

  ---
  *Posted by MarketHawk Factory*"
  ```
- [ ] Add `needs-discussion` label and exit cleanly (Task 4 commit covers artifacts only):
  ```bash
  gh issue edit 730 --repo omniscient/markethawk --add-label needs-discussion
  ```
  Proceed to Task 4, staging only `dark-factory/evals/results/` and `dark-factory/evals/reports/`.

**Branch B — Both `conformance` and `code-review` recommend 22000:**

- [ ] No config changes needed. Record "budgets confirmed at 22k" for the commit message.
- [ ] Proceed to Task 3.

**Branch C — Either recommendation differs from 22000 (and neither is "none — widen..."):**

- [ ] Extract the exact recommended integer values:
  ```python
  import re, json
  DATE = "<date>"  # use actual date from Task 1
  text = open(f"dark-factory/evals/reports/budget-calibration-scorecard-{DATE}.md").read()
  for scenario in ("conformance", "code-review"):
      m = re.search(rf"\|\s*{re.escape(scenario)}\s*\|\s*(\d+)\s*\|", text)
      print(f"{scenario}: {m.group(1) if m else 'NOT FOUND'}")
  ```

- [ ] Update `.claude/skills/refinement/config.yaml` — change only the scenarios with new values under `token_optimization.budgets`. Current state (lines near `budgets:`):
  ```yaml
      conformance: 22000         # provisional from T5 smoke run; ...
      code-review: 22000         # provisional from T5 smoke run; ...
  ```
  Replace with the calibrated values (example if both change to 24000):
  ```yaml
      conformance: 24000         # full-corpus calibration (#730); recalibrate per runbook Follow-up Path
      code-review: 24000         # full-corpus calibration (#730); recalibrate per runbook Follow-up Path
  ```
  **Do not touch any `enforce:` entries** — they must remain: `conformance: true`, `code-review: true`, `refine/plan/implement: false`.

- [ ] Update `expected` dict in `dark-factory/tests/test_budget_enforce_dag.py` (lines 52–58):
  ```python
  expected = {
      "refine": 30000,
      "plan": 30000,
      "implement": 30000,
      "conformance": <new_value>,   # replace with calibrated value
      "code-review": <new_value>,   # replace with calibrated value
  }
  ```

- [ ] Update the budget table in `docs/agents/dark-factory-token-optimization.md`. Current rows (lines 191–196):
  ```markdown
  | conformance | **true** | **22 000** | **enforced (T6)** |
  | code-review | **true** | **22 000** | **enforced (T6)** |

  Budgets for conformance and code-review are **provisional** — derived from a 2-issue
  T5 smoke run. Run the full-corpus calibration (`dark-factory/evals/token_opt_eval.py
  --calibrate`) after accumulating ≥ 10 bench issues to confirm or adjust.
  ```
  Change to (for each scenario that changed; bold the new value):
  ```markdown
  | conformance | **true** | **<new_value>** | **enforced (T6; full-corpus #730)** |
  | code-review | **true** | **<new_value>** | **enforced (T6; full-corpus #730)** |

  Budgets for conformance and code-review were confirmed/adjusted by the full-corpus
  calibration run (#730, 2026-07-03). For the next calibration round see the Follow-up Path below.
  ```

- [ ] Run the test guard to confirm config ↔ test guard are in sync:
  ```bash
  python -m pytest dark-factory/tests/test_budget_enforce_dag.py \
    -k "test_config_budgets_t6_state or test_config_enforce_t6_state" -v
  ```
  Expected: `2 passed`. `test_config_enforce_t6_state` confirms `enforce` flags are unchanged.

No commit yet — atomic commit in Task 4.

---

### Task 3: Compute Per-Scenario p90 Uncapped Architecture Slice Sizes

**Files:**
- Read: `dark-factory/evals/results/token-opt-eval-<date>.json` (to identify sliced pairs)
- Temporary (not committed): `/tmp/extract_arch_p90.py`

**Context**: `token_opt_eval.py` excludes `opt_manifest` from the JSON output (`result_for_json = {k: v for k, v in result.items() if k != "opt_manifest"}`). The `sections.architecture_md.tokens` value lives only in `opt_manifest`. To recover it, re-call `assemble_pack()` for the (issue, scenario) pairs where `fallback == False` in the JSON. This mirrors exactly what the calibration run did in memory.

- [ ] Identify which (issue, scenario) pairs had `fallback == False` in the JSON:
  ```bash
  DATE=$(python3 -c "from datetime import datetime,timezone; print(datetime.now(timezone.utc).strftime('%Y-%m-%d'))")
  # Use the actual filename from Task 1 if the date rolled over midnight UTC
  python3 -c "
  import json, collections, sys
  d = json.load(open(f'dark-factory/evals/results/token-opt-eval-${DATE}.json'))
  sliced = collections.defaultdict(list)
  for r in d['results']:
      if not r.get('fallback', True) and r.get('status') not in ('skipped', 'error'):
          sliced[r['scenario']].append(r['issue'])
  for s in ['refine', 'plan', 'implement', 'conformance', 'code-review']:
      print(f'  {s}: {len(sliced[s])} sliced -> {sliced[s]}')
  "
  ```

- [ ] Write the helper script to `/tmp/extract_arch_p90.py` (not committed):
  ```python
  #!/usr/bin/env python3
  """Re-extract architecture_md.tokens for sliced issues; compute p90 per scenario.
  
  Usage (from repo root inside factory container):
    REPO_ROOT=$(git rev-parse --show-toplevel) \
    python3 /tmp/extract_arch_p90.py dark-factory/evals/results/token-opt-eval-<date>.json
  """
  import json, os, subprocess, sys, tempfile
  
  REPO_ROOT = os.environ.get("REPO_ROOT", ".")
  sys.path.insert(0, os.path.join(REPO_ROOT, "dark-factory", "scripts"))
  from context_pack import assemble_pack
  
  SCENARIOS = ["refine", "plan", "implement", "conformance", "code-review"]
  
  def _percentile(values, pct):
      """Linear-interpolation percentile — mirrors token_opt_eval._percentile."""
      if not values:
          return None
      sv = sorted(values)
      idx = (pct / 100) * (len(sv) - 1)
      lo = int(idx)
      hi = lo + 1
      if hi >= len(sv):
          return sv[-1]
      return sv[lo] + (idx - lo) * (sv[hi] - sv[lo])
  
  def fetch_issue(num):
      r = subprocess.run(
          ["gh", "issue", "view", str(num), "--repo", "omniscient/markethawk",
           "--json", "number,title,body,labels"],
          capture_output=True, text=True, timeout=30, check=True,
      )
      return json.loads(r.stdout)
  
  def build_issue_json(issue):
      return json.dumps({
          "number": issue["number"],
          "title": issue.get("title", ""),
          "body": issue.get("body", ""),
          "labels": [l["name"] for l in issue.get("labels", [])],
      })
  
  def main():
      eval_json = sys.argv[1]
      d = json.load(open(eval_json))
  
      sliced = {s: [] for s in SCENARIOS}
      for r in d["results"]:
          if not r.get("fallback", True) and r.get("status") not in ("skipped", "error"):
              sliced[r["scenario"]].append(r["issue"])
  
      arch_tokens = {s: [] for s in SCENARIOS}
  
      with tempfile.TemporaryDirectory(prefix="arch-p90-") as tmp:
          for scenario in SCENARIOS:
              print(f"  {scenario}: {len(sliced[scenario])} sliced issues", flush=True)
              for issue_num in sliced[scenario]:
                  issue = fetch_issue(issue_num)
                  labels = [l["name"] for l in issue.get("labels", [])]
                  ijson = os.path.join(tmp, f"{issue_num}-issue.json")
                  open(ijson, "w").write(build_issue_json(issue))
                  out_md  = os.path.join(tmp, f"{issue_num}-{scenario}.md")
                  out_json = os.path.join(tmp, f"{issue_num}-{scenario}.json")
                  assemble_pack(
                      scenario=scenario,
                      issue_num=issue_num,
                      run_id="arch-p90",
                      clone_dir=REPO_ROOT,
                      out_md=out_md,
                      out_json=out_json,
                      issue_json=ijson,
                      labels=labels,
                      spec_component=None,
                  )
                  manifest = json.load(open(out_json))
                  arch_sec = manifest.get("sections", {}).get("architecture_md", {})
                  if (not arch_sec.get("fallback", True)
                          and arch_sec.get("status") != "dropped"):
                      tok = arch_sec.get("tokens")
                      if tok is not None:
                          arch_tokens[scenario].append(int(tok))
  
      print("\n## Per-Scenario p90 Uncapped Architecture Slice Sizes")
      print("| Scenario | p90 arch-slice tokens |")
      print("|----------|-----------------------|")
      for s in SCENARIOS:
          vals = arch_tokens[s]
          p90 = _percentile(vals, 90)
          if p90 is None:
              print(f"| {s} | no sliced samples |")
          else:
              print(f"| {s} | {int(p90):,} (n={len(vals)}) |")
  
  main()
  ```

- [ ] Run the helper (from repo root):
  ```bash
  REPO_ROOT=$(git rev-parse --show-toplevel) \
  DATE=$(python3 -c "from datetime import datetime,timezone; print(datetime.now(timezone.utc).strftime('%Y-%m-%d'))") \
  python3 /tmp/extract_arch_p90.py dark-factory/evals/results/token-opt-eval-${DATE}.json
  ```
  Expected: a 5-row table printed to stdout. Record all 5 values for the PR description. If a scenario shows "no sliced samples", record that verbatim — do not substitute a fallback value.

---

### Task 4: Commit All Artifacts Atomically and Prepare PR Description

**Files (always committed):**
- `dark-factory/evals/results/token-opt-eval-<date>.json`
- `dark-factory/evals/reports/budget-calibration-scorecard-<date>.md`

**Files (committed only if budgets changed):**
- `.claude/skills/refinement/config.yaml`
- `dark-factory/tests/test_budget_enforce_dag.py`
- `docs/agents/dark-factory-token-optimization.md`

- [ ] Run the full budget-enforce DAG test suite to confirm no regressions:
  ```bash
  python -m pytest dark-factory/tests/test_budget_enforce_dag.py -v
  ```
  All tests must pass.

- [ ] Stage the correct set of files (no extras):
  ```bash
  git add dark-factory/evals/results/ dark-factory/evals/reports/
  # Only if budgets changed in Task 2 Branch C:
  git add .claude/skills/refinement/config.yaml
  git add dark-factory/tests/test_budget_enforce_dag.py
  git add docs/agents/dark-factory-token-optimization.md
  git status  # verify only expected files appear in staged diff
  ```

- [ ] Create the atomic commit:
  ```bash
  # If budgets were confirmed unchanged (Branch B):
  git commit -m "feat(#730): full-corpus budget calibration — 22k budgets confirmed"

  # If budgets changed (Branch C; substitute actual values):
  git commit -m "feat(#730): full-corpus budget calibration — adjust conformance/code-review to <N>k"

  # If Branch A (no-passing-budget):
  git commit -m "feat(#730): full-corpus calibration artifacts — budgets unchanged (needs-discussion)"
  ```

- [ ] Verify the enforce flags were NOT changed in the commit:
  ```bash
  git diff HEAD~1 -- .claude/skills/refinement/config.yaml | grep "^[+-]" | grep "enforce"
  ```
  Expected: no lines changing `enforce:` values (diff should be empty or show only budget lines).

- [ ] Prepare the PR description. Fill in the values from Tasks 1–3:
  ```markdown
  ## Summary

  Full-corpus budget calibration run (#730) over 18 bench + supplemental issues
  (`token_opt_eval.py --calibrate`, all 5 enforcement scenarios, budget sweep 22k–40k).

  **Calibration artifacts:**
  - Scorecard: `dark-factory/evals/reports/budget-calibration-scorecard-<date>.md`
  - Raw JSON: `dark-factory/evals/results/token-opt-eval-<date>.json`

  **Budget outcome:** [confirmed at 22k / adjusted to Nk for conformance; Mk for code-review]

  **p90 Uncapped Architecture Slice Sizes (sliced issues only, per scenario):**
  | Scenario | p90 arch-slice tokens |
  |----------|-----------------------|
  | refine | <from Task 3> |
  | plan | <from Task 3> |
  | implement | <from Task 3> |
  | conformance | <from Task 3> |
  | code-review | <from Task 3> |

  These sizes are the direct input for the follow-up cap-raise ticket
  (whether to raise `architecture.max_tokens` above 3000 for the deferred scenarios).

  **enforce flags:** unchanged from T6 state — `conformance: true`, `code-review: true`;
  `refine/plan/implement: false`.

  ## Test plan
  - [ ] `pytest dark-factory/tests/test_budget_enforce_dag.py` passes
  - [ ] `git diff HEAD~1 -- .claude/skills/refinement/config.yaml | grep enforce` is empty
  - [ ] Scorecard "Safe-Budget Recommendations" table matches config values
  - [ ] p90 arch-slice table reported in PR description
  ```
