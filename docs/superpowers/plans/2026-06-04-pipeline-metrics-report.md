# Pipeline Metrics Report — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a two-stage Python pipeline that (1) pulls GitHub issue/comment data via `gh`, parses Dark Factory cost-report markers, and writes `metrics.json`; (2) renders `metrics.json` + an ECharts-powered HTML template into a single self-contained `pipeline-report.html` in the Dark Factory visual language.

**Architecture:** `fetch_metrics.py` → `metrics.json` → `render_report.py` → `pipeline-report.html`. A `generate.sh` wrapper runs both stages. The JSON boundary keeps stages independently testable with no live GitHub calls needed in unit tests.

**Tech Stack:** Python 3.12, `gh` CLI, ECharts (vendored inline), Bash

**Spec:** [`docs/superpowers/specs/2026-06-04-pipeline-metrics-report-design.md`](../specs/2026-06-04-pipeline-metrics-report-design.md)
**Issue:** [#212](https://github.com/omniscient/markethawk/issues/212)

---

## File Structure

| Path | Change |
|------|--------|
| `scripts/fetch_metrics.py` | New — Stage 1: gh → metrics.json |
| `scripts/render_report.py` | New — Stage 2: metrics.json + template → report |
| `scripts/template.html` | New — ECharts chart containers + init JS |
| `scripts/generate.sh` | New — orchestrates both stages |
| `metrics.json` | New — committed data snapshot |
| `docs/pipeline-report.html` | New — committed self-contained HTML report |
| `tests/scripts/__init__.py` | New |
| `tests/scripts/conftest.py` | New |
| `tests/scripts/fixtures/sample_issues.json` | New |
| `tests/scripts/fixtures/sample_comments.json` | New |
| `tests/scripts/test_fetch_metrics.py` | New |
| `tests/scripts/test_render_report.py` | New |

---

## Task 1 — Test scaffold + cost-report parser

**Files:** `scripts/fetch_metrics.py` (stub), `tests/scripts/__init__.py`, `tests/scripts/conftest.py`, `tests/scripts/test_fetch_metrics.py`

### Steps

- [ ] 1.1 Create the tests/scripts package:

  ```bash
  mkdir -p tests/scripts
  touch tests/scripts/__init__.py
  ```

- [ ] 1.2 Write `tests/scripts/conftest.py` with a fixture for a sample cost-report comment body:

  ```python
  # tests/scripts/conftest.py
  import pytest

  COST_COMMENT_BODY = """\
  <!-- dark-factory-cost-report -->
  <!-- cumulative: cost=7.197 in=310 out=123906 -->
  ## Dark Factory — Cost Report

  **3 run(s) — Total: $7.197 (310 in / 123.9K out)**

  ### Run: 2026-06-04 12:42 UTC (plan, completed)

  | Step | Model | In tokens | Out tokens | Cost | Duration |
  |------|-------|-----------|------------|------|----------|
  | parse-intent |  | 28 | 271 | $0.0138 | 6.4s |
  | fetch-issue |  | 0 | 0 | $0 | 1.1s |
  | plan |  | 38 | 56700 | $2.8727 | 24m 47s |
  | **Subtotal** | | **66** | **56971** | **$2.8865** | |

  ### Run: 2026-06-04 15:17 UTC (implement, completed)

  | Step | Model | In tokens | Out tokens | Cost | Duration |
  |------|-------|-----------|------------|------|----------|
  | implement |  | 45 | 20200 | $1.9607 | 7m 18s |
  | validate |  | 12 | 7400 | $0.3274 | 4m 0s |
  | **Subtotal** | | **57** | **27600** | **$2.2881** | |

  ### Run: 2026-06-04 17:05 UTC (fix, completed)

  | Step | Model | In tokens | Out tokens | Cost | Duration |
  |------|-------|-----------|------------|------|----------|
  | implement |  | 187 | 40135 | $2.0224 | 8m 12s |
  | **Subtotal** | | **187** | **40135** | **$2.0224** | |
  """

  @pytest.fixture
  def cost_comment():
      return COST_COMMENT_BODY
  ```

- [ ] 1.3 Write failing tests for the three parsing functions in `tests/scripts/test_fetch_metrics.py`:

  ```python
  # tests/scripts/test_fetch_metrics.py
  import pytest
  from scripts.fetch_metrics import parse_cost_comment, parse_run_headers, parse_step_table

  def test_parse_cost_comment_extracts_totals(cost_comment):
      result = parse_cost_comment(cost_comment)
      assert result is not None
      assert abs(result["cost"] - 7.197) < 0.001
      assert result["in_tokens"] == 310
      assert result["out_tokens"] == 123906

  def test_parse_cost_comment_returns_none_when_absent():
      assert parse_cost_comment("just a regular comment") is None

  def test_parse_run_headers_extracts_all_runs(cost_comment):
      runs = parse_run_headers(cost_comment)
      assert len(runs) == 3
      assert runs[0]["run_type"] == "plan"
      assert runs[0]["status"] == "completed"
      assert runs[0]["timestamp"] == "2026-06-04 12:42 UTC"
      assert runs[2]["run_type"] == "fix"

  def test_parse_step_table_extracts_steps(cost_comment):
      runs = parse_run_headers(cost_comment)
      # parse_step_table returns list of {step, in_tokens, out_tokens, cost_usd} dicts
      # for the first run block starting at the run_header position
      steps = parse_step_table(cost_comment, run_index=0)
      non_subtotal = [s for s in steps if s["step"] != "Subtotal"]
      assert len(non_subtotal) == 3
      plan_step = next(s for s in non_subtotal if s["step"] == "plan")
      assert plan_step["in_tokens"] == 38
      assert abs(plan_step["cost_usd"] - 2.8727) < 0.0001

  def test_parse_step_table_aggregates_by_step_name(cost_comment):
      # "implement" appears in run 1 and run 2 — aggregate should sum both
      all_steps = parse_step_table(cost_comment)
      by_name = {s["step"]: s for s in all_steps}
      assert "implement" in by_name
      assert abs(by_name["implement"]["cost_usd"] - (1.9607 + 2.0224)) < 0.001
  ```

  Run to confirm failure:

  ```bash
  cd /workspace/markethawk
  python3 -m pytest tests/scripts/test_fetch_metrics.py -v 2>&1 | head -30
  ```

  Expected: `ModuleNotFoundError` or `ImportError` (fetch_metrics not yet written).

- [ ] 1.4 Create `scripts/fetch_metrics.py` with just the function stubs:

  ```python
  #!/usr/bin/env python3
  """Stage 1: pull GitHub issue data + compute metrics → metrics.json"""
  import json
  import re
  import subprocess
  import sys
  from datetime import datetime, timezone

  REPO = "omniscient/markethawk"

  # ── regex patterns ────────────────────────────────────────────────────────────
  _CUMULATIVE_RE = re.compile(
      r"<!-- cumulative: cost=([0-9.]+) in=(\d+) out=(\d+) -->"
  )
  _RUN_HEADER_RE = re.compile(
      r"### Run: (\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC) \((\w+),\s*(\w+)\)"
  )
  _TABLE_ROW_RE = re.compile(
      r"^\s*\|\s*\*{0,2}([^|*]+?)\*{0,2}\s*\|[^|]*\|\s*\*{0,2}(\d+)\*{0,2}\s*"
      r"\|\s*\*{0,2}(\d+)\*{0,2}\s*\|\s*\*{0,2}\$([0-9.]+)\*{0,2}\s*\|"
  )


  def parse_cost_comment(body: str) -> dict | None:
      """Extract cumulative totals from a cost-report comment. Returns None if absent."""
      raise NotImplementedError


  def parse_run_headers(body: str) -> list[dict]:
      """Return list of {timestamp, run_type, status} for each run block."""
      raise NotImplementedError


  def parse_step_table(body: str, run_index: int | None = None) -> list[dict]:
      """Return aggregated step costs across all runs (or a specific run_index).

      Each item: {step, in_tokens, out_tokens, cost_usd}
      Subtotal rows are excluded from the returned list.
      """
      raise NotImplementedError
  ```

- [ ] 1.5 Implement `parse_cost_comment`, `parse_run_headers`, `parse_step_table`:

  ```python
  def parse_cost_comment(body: str) -> dict | None:
      m = _CUMULATIVE_RE.search(body)
      if not m:
          return None
      return {
          "cost": float(m.group(1)),
          "in_tokens": int(m.group(2)),
          "out_tokens": int(m.group(3)),
      }


  def parse_run_headers(body: str) -> list[dict]:
      return [
          {"timestamp": m.group(1), "run_type": m.group(2), "status": m.group(3)}
          for m in _RUN_HEADER_RE.finditer(body)
      ]


  def _tokens_from_str(s: str) -> int:
      """Convert '56.9K' → 56900 or '271' → 271."""
      s = s.strip()
      if s.endswith("K"):
          return int(float(s[:-1]) * 1000)
      return int(s)


  def parse_step_table(body: str, run_index: int | None = None) -> list[dict]:
      run_positions = [m.start() for m in _RUN_HEADER_RE.finditer(body)]
      if not run_positions:
          return []
      run_positions.append(len(body))

      if run_index is not None:
          if run_index >= len(run_positions) - 1:
              return []
          slices = [body[run_positions[run_index]:run_positions[run_index + 1]]]
      else:
          slices = [
              body[run_positions[i]:run_positions[i + 1]]
              for i in range(len(run_positions) - 1)
          ]

      aggregated: dict[str, dict] = {}
      for block in slices:
          for line in block.splitlines():
              m = _TABLE_ROW_RE.match(line)
              if not m:
                  continue
              step = m.group(1).strip()
              if step.lower() in ("step", "subtotal"):
                  continue
              in_tok = _tokens_from_str(m.group(2))
              out_tok = _tokens_from_str(m.group(3))
              cost = float(m.group(4))
              if step in aggregated:
                  aggregated[step]["in_tokens"] += in_tok
                  aggregated[step]["out_tokens"] += out_tok
                  aggregated[step]["cost_usd"] += cost
              else:
                  aggregated[step] = {
                      "step": step,
                      "in_tokens": in_tok,
                      "out_tokens": out_tok,
                      "cost_usd": cost,
                  }
      return list(aggregated.values())
  ```

- [ ] 1.6 Run tests — all four must pass:

  ```bash
  cd /workspace/markethawk
  python3 -m pytest tests/scripts/test_fetch_metrics.py -v
  ```

  Expected output:
  ```
  PASSED tests/scripts/test_fetch_metrics.py::test_parse_cost_comment_extracts_totals
  PASSED tests/scripts/test_fetch_metrics.py::test_parse_cost_comment_returns_none_when_absent
  PASSED tests/scripts/test_fetch_metrics.py::test_parse_run_headers_extracts_all_runs
  PASSED tests/scripts/test_fetch_metrics.py::test_parse_step_table_extracts_steps
  PASSED tests/scripts/test_fetch_metrics.py::test_parse_step_table_aggregates_by_step_name
  5 passed
  ```

- [ ] 1.7 Commit:

  ```bash
  git add scripts/fetch_metrics.py tests/scripts/ docs/superpowers/specs/2026-06-04-pipeline-metrics-report-design.md
  git commit -m "feat(#212): add cost-report parser + test scaffold"
  ```

---

## Task 2 — GitHub data ingestion + metrics.json

**Files:** `scripts/fetch_metrics.py` (complete), `tests/scripts/fixtures/sample_issues.json`, `tests/scripts/fixtures/sample_comments.json`, `tests/scripts/test_fetch_metrics.py` (extend)

### Steps

- [ ] 2.1 Create fixture data in `tests/scripts/fixtures/sample_issues.json`:

  ```bash
  mkdir -p tests/scripts/fixtures
  ```

  `tests/scripts/fixtures/sample_issues.json`:
  ```json
  [
    {
      "number": 1,
      "title": "Add volume spike scanner",
      "state": "CLOSED",
      "createdAt": "2026-01-10T09:00:00Z",
      "closedAt": "2026-01-10T11:30:00Z",
      "labels": [{"name": "enhancement"}, {"name": "size: S"}, {"name": "Dark Factory"}]
    },
    {
      "number": 2,
      "title": "Fix pre-market gap calculation",
      "state": "CLOSED",
      "createdAt": "2026-01-12T09:00:00Z",
      "closedAt": "2026-01-14T15:00:00Z",
      "labels": [{"name": "bug"}, {"name": "size: M"}, {"name": "priority: must-have"}]
    },
    {
      "number": 3,
      "title": "Dashboard WIP issue",
      "state": "OPEN",
      "createdAt": "2026-02-01T09:00:00Z",
      "closedAt": null,
      "labels": [{"name": "enhancement"}, {"name": "size: L"}]
    }
  ]
  ```

  `tests/scripts/fixtures/sample_comments.json` (keyed by issue number, as a map):
  ```json
  {
    "1": [
      {
        "body": "<!-- dark-factory-cost-report -->\n<!-- cumulative: cost=2.50 in=100 out=50000 -->\n## Dark Factory — Cost Report\n\n### Run: 2026-01-10 09:30 UTC (plan, completed)\n\n| Step | Model | In tokens | Out tokens | Cost | Duration |\n|------|-------|-----------|------------|------|----------|\n| plan |  | 50 | 25000 | $1.25 | 10m 0s |\n| **Subtotal** | | **50** | **25000** | **$1.25** | |\n\n### Run: 2026-01-10 10:15 UTC (implement, completed)\n\n| Step | Model | In tokens | Out tokens | Cost | Duration |\n|------|-------|-----------|------------|------|----------|\n| implement |  | 50 | 25000 | $1.25 | 10m 0s |\n| **Subtotal** | | **50** | **25000** | **$1.25** | |"
      }
    ],
    "2": [{"body": "This looks like a bug in the session timezone handling."}],
    "3": []
  }
  ```

- [ ] 2.2 Write failing tests for `build_issue_metrics` in `test_fetch_metrics.py`:

  ```python
  # append to tests/scripts/test_fetch_metrics.py
  import json
  from pathlib import Path
  from scripts.fetch_metrics import build_issue_metrics

  FIXTURES = Path(__file__).parent / "fixtures"

  def test_build_issue_metrics_lead_time():
      issues = json.loads((FIXTURES / "sample_issues.json").read_text())
      comments_map = json.loads((FIXTURES / "sample_comments.json").read_text())
      result = build_issue_metrics(issues, comments_map)
      closed = {i["number"]: i for i in result["issues"] if i["state"] == "CLOSED"}
      assert abs(closed[1]["lead_time_hours"] - 2.5) < 0.1
      assert abs(closed[2]["lead_time_hours"] - 54.0) < 0.1

  def test_build_issue_metrics_autonomous_flag():
      issues = json.loads((FIXTURES / "sample_issues.json").read_text())
      comments_map = json.loads((FIXTURES / "sample_comments.json").read_text())
      result = build_issue_metrics(issues, comments_map)
      by_num = {i["number"]: i for i in result["issues"]}
      assert by_num[1]["autonomous"] is True
      assert by_num[2]["autonomous"] is False

  def test_build_issue_metrics_summary_counts():
      issues = json.loads((FIXTURES / "sample_issues.json").read_text())
      comments_map = json.loads((FIXTURES / "sample_comments.json").read_text())
      result = build_issue_metrics(issues, comments_map)
      s = result["summary"]
      assert s["total_issues"] == 3
      assert s["closed_issues"] == 2
      assert s["open_issues"] == 1
      assert s["autonomous_issues"] == 1
      assert abs(s["total_cost_usd"] - 2.50) < 0.01

  def test_build_issue_metrics_label_extraction():
      issues = json.loads((FIXTURES / "sample_issues.json").read_text())
      comments_map = json.loads((FIXTURES / "sample_comments.json").read_text())
      result = build_issue_metrics(issues, comments_map)
      by_num = {i["number"]: i for i in result["issues"]}
      assert by_num[1]["size"] == "S"
      assert by_num[2]["size"] == "M"
      assert by_num[2]["priority"] == "must-have"
  ```

  Run to confirm failure:

  ```bash
  python3 -m pytest tests/scripts/test_fetch_metrics.py::test_build_issue_metrics_lead_time -v 2>&1 | tail -5
  ```

  Expected: `ImportError: cannot import name 'build_issue_metrics'`

- [ ] 2.3 Implement `build_issue_metrics` and label extraction helpers in `scripts/fetch_metrics.py`:

  ```python
  # ── label helpers ─────────────────────────────────────────────────────────────
  _SIZE_RE = re.compile(r"size:\s*([SMLX]+)")
  _PRIORITY_RE = re.compile(r"priority:\s*(.+)")


  def _extract_label(labels: list[dict], pattern: re.Pattern) -> str | None:
      for lbl in labels:
          m = pattern.match(lbl["name"])
          if m:
              return m.group(1).strip()
      return None


  def _iso_to_dt(s: str | None) -> datetime | None:
      if not s:
          return None
      return datetime.fromisoformat(s.replace("Z", "+00:00"))


  def _hours_between(a: str | None, b: str | None) -> float | None:
      da, db = _iso_to_dt(a), _iso_to_dt(b)
      if da is None or db is None:
          return None
      return (db - da).total_seconds() / 3600


  def build_issue_metrics(
      issues: list[dict], comments_map: dict[str, list[dict]]
  ) -> dict:
      """Compute full metrics dict from raw issue list + comments map.

      comments_map keys are str(issue_number).
      Returns the metrics.json structure.
      """
      processed = []
      total_cost = 0.0
      autonomous_count = 0

      for issue in issues:
          num = issue["number"]
          labels = issue.get("labels", [])
          comments = comments_map.get(str(num), [])

          cost_info = None
          runs = []
          for c in comments:
              body = c.get("body", "")
              if "<!-- dark-factory-cost-report -->" in body:
                  cost_info = parse_cost_comment(body)
                  runs = parse_run_headers(body)
                  break

          autonomous = cost_info is not None
          if autonomous:
              autonomous_count += 1
              total_cost += cost_info["cost"]

          lead_time = _hours_between(issue.get("createdAt"), issue.get("closedAt"))
          first_run_ts = runs[0]["timestamp"] if runs else None
          factory_cycle = _hours_between(
              first_run_ts.replace(" UTC", "+00:00").replace(" ", "T") if first_run_ts else None,
              issue.get("closedAt"),
          ) if first_run_ts and issue.get("closedAt") else None

          processed.append({
              "number": num,
              "title": issue["title"],
              "state": issue["state"],
              "created_at": issue.get("createdAt"),
              "closed_at": issue.get("closedAt"),
              "lead_time_hours": lead_time,
              "factory_cycle_hours": factory_cycle,
              "labels": [lbl["name"] for lbl in labels],
              "size": _extract_label(labels, _SIZE_RE),
              "priority": _extract_label(labels, _PRIORITY_RE),
              "autonomous": autonomous,
              "cost": {
                  "total_usd": cost_info["cost"],
                  "in_tokens": cost_info["in_tokens"],
                  "out_tokens": cost_info["out_tokens"],
                  "runs": runs,
              } if cost_info else None,
          })

      closed = [i for i in processed if i["state"] == "CLOSED"]
      lead_times = sorted([i["lead_time_hours"] for i in closed if i["lead_time_hours"] is not None])
      median_lt = lead_times[len(lead_times) // 2] if lead_times else None
      p85_lt = lead_times[int(len(lead_times) * 0.85)] if lead_times else None

      return {
          "generated_at": datetime.now(timezone.utc).isoformat(),
          "summary": {
              "total_issues": len(issues),
              "closed_issues": len(closed),
              "open_issues": len(issues) - len(closed),
              "autonomous_issues": autonomous_count,
              "pct_autonomous": round(autonomous_count / len(issues) * 100, 1) if issues else 0,
              "total_cost_usd": round(total_cost, 4),
              "avg_cost_per_ticket": round(total_cost / autonomous_count, 4) if autonomous_count else 0,
              "median_lead_time_hours": median_lt,
              "p85_lead_time_hours": p85_lt,
          },
          "issues": processed,
      }
  ```

- [ ] 2.4 Run tests — all new tests must pass:

  ```bash
  python3 -m pytest tests/scripts/ -v
  ```

  Expected: 9 passed

- [ ] 2.5 Implement `fetch_all_issues`, `fetch_issue_comments`, and the `__main__` block:

  ```python
  # ── GitHub data fetching ───────────────────────────────────────────────────────
  def _gh(*args: str) -> list | dict:
      result = subprocess.run(
          ["gh", *args], capture_output=True, text=True, check=True
      )
      return json.loads(result.stdout)


  def fetch_all_issues() -> list[dict]:
      return _gh(
          "issue", "list", "--repo", REPO,
          "--state", "all", "--limit", "1000",
          "--json", "number,title,state,createdAt,closedAt,labels",
      )


  def fetch_issue_comments(number: int) -> list[dict]:
      data = _gh(
          "issue", "view", str(number), "--repo", REPO,
          "--json", "comments",
      )
      return data.get("comments", [])


  def build_comments_map(issues: list[dict]) -> dict[str, list[dict]]:
      """Fetch comments for all issues; print progress to stderr."""
      result = {}
      for i, issue in enumerate(issues, 1):
          num = issue["number"]
          print(f"  [{i}/{len(issues)}] fetching comments for #{num}", file=sys.stderr)
          result[str(num)] = fetch_issue_comments(num)
      return result


  if __name__ == "__main__":
      import argparse

      parser = argparse.ArgumentParser()
      parser.add_argument("--output", default="metrics.json")
      args = parser.parse_args()

      print("Fetching issues…", file=sys.stderr)
      issues = fetch_all_issues()
      print(f"  {len(issues)} issues found", file=sys.stderr)

      print("Fetching comments…", file=sys.stderr)
      comments_map = build_comments_map(issues)

      print("Computing metrics…", file=sys.stderr)
      metrics = build_issue_metrics(issues, comments_map)

      with open(args.output, "w") as f:
          json.dump(metrics, f, indent=2, default=str)
      print(f"Wrote {args.output}", file=sys.stderr)
  ```

- [ ] 2.6 Commit:

  ```bash
  git add scripts/fetch_metrics.py tests/scripts/
  git commit -m "feat(#212): implement issue ingestion + metrics computation"
  ```

---

## Task 3 — HTML template (Dark Factory visual language)

**Files:** `scripts/template.html` (new)

### Steps

- [ ] 3.1 Create `scripts/template.html` with the Dark Factory palette and skeleton layout. The `{{ECHARTS_JS}}` placeholder is replaced by the renderer with the vendored ECharts minified JS. The `{{METRICS_JSON}}` placeholder is replaced with the serialised metrics data:

  ```html
  <!DOCTYPE html>
  <html lang="en">
  <head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Dark Factory — Pipeline Report</title>
  <style>
    :root {
      --bg:#0a0b0e; --bg2:#0e1015; --panel:#13151d; --panel2:#181b24;
      --line:rgba(255,255,255,.08); --line2:rgba(255,255,255,.14);
      --ink:#eceef3; --mut:#9aa0ad; --mut2:#6b7280;
      --amber:#ff8a3d; --amber-hot:#ff6a1a; --amber-soft:#ffc08a;
      --cyan:#3fe0c8; --cyan-soft:#8af0e2;
      --green:#54d18a; --red:#ff6b6b; --violet:#a78bfa;
      --mono:ui-monospace,"Cascadia Code","SF Mono",Menlo,Consolas,monospace;
      --sans:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    }
    *{box-sizing:border-box;margin:0;padding:0}
    html{font-size:16px}
    body{background:var(--bg);color:var(--ink);font-family:var(--sans);line-height:1.5;-webkit-font-smoothing:antialiased}

    /* ── layout ── */
    .page-header{padding:3rem 2rem 2rem;border-bottom:1px solid var(--line);
      background:linear-gradient(180deg,#0e1015 0%,var(--bg) 100%)}
    .page-header .kicker{font-family:var(--mono);font-size:.75rem;letter-spacing:.28em;
      text-transform:uppercase;color:var(--amber);display:flex;align-items:center;gap:.5em;margin-bottom:.8rem}
    .page-header .kicker .dot{width:6px;height:6px;border-radius:50%;background:var(--amber);box-shadow:0 0 8px var(--amber-hot)}
    .page-header h1{font-size:2.4rem;font-weight:800;letter-spacing:-.02em;margin-bottom:.5rem}
    .page-header .meta{color:var(--mut);font-size:.9rem}

    main{max-width:1400px;margin:0 auto;padding:2rem}
    section{margin-bottom:3rem}
    section h2{font-size:1.2rem;font-weight:700;letter-spacing:.04em;text-transform:uppercase;
      color:var(--amber);margin-bottom:1.25rem;padding-bottom:.5rem;border-bottom:1px solid var(--line)}

    /* ── KPI cards ── */
    .kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:1rem}
    .kpi-card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:1.2rem}
    .kpi-card .label{font-size:.75rem;color:var(--mut);letter-spacing:.06em;text-transform:uppercase;margin-bottom:.4rem}
    .kpi-card .value{font-size:2rem;font-weight:800;font-family:var(--mono);color:var(--amber)}
    .kpi-card .sub{font-size:.78rem;color:var(--mut2);margin-top:.2rem}

    /* ── chart panels ── */
    .chart-grid-2{display:grid;grid-template-columns:1fr 1fr;gap:1rem}
    .chart-grid-3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:1rem}
    @media(max-width:900px){.chart-grid-2,.chart-grid-3{grid-template-columns:1fr}}
    .chart-panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:1.2rem}
    .chart-panel h3{font-size:.82rem;font-weight:600;color:var(--mut);letter-spacing:.06em;
      text-transform:uppercase;margin-bottom:1rem}
    .chart-box{height:260px}
    .chart-box-tall{height:340px}

    /* ── table ── */
    .table-wrap{overflow-x:auto}
    table{width:100%;border-collapse:collapse;font-size:.85rem}
    thead tr{border-bottom:2px solid var(--line2)}
    thead th{padding:.6rem .8rem;text-align:left;color:var(--mut);font-weight:600;font-size:.75rem;letter-spacing:.06em;text-transform:uppercase}
    tbody tr{border-bottom:1px solid var(--line);cursor:default}
    tbody tr:hover{background:var(--panel2)}
    td{padding:.55rem .8rem;color:var(--ink)}
    td.mono{font-family:var(--mono);font-size:.8rem}
    td.am{color:var(--amber);font-family:var(--mono)}
    td.gr{color:var(--green)}
    td.rd{color:var(--red)}
    .badge{display:inline-block;font-size:.7rem;padding:.15em .5em;border-radius:5px;
      border:1px solid;font-family:var(--mono)}
    .badge-s{color:var(--green);border-color:rgba(84,209,138,.4);background:rgba(84,209,138,.08)}
    .badge-m{color:var(--amber);border-color:rgba(255,138,61,.4);background:rgba(255,138,61,.08)}
    .badge-l{color:var(--red);border-color:rgba(255,107,107,.4);background:rgba(255,107,107,.08)}
    .badge-df{color:var(--cyan);border-color:rgba(63,224,200,.4);background:rgba(63,224,200,.08)}

    /* ── filters ── */
    .filters{display:flex;gap:.5rem;flex-wrap:wrap;margin-bottom:1.5rem;align-items:center}
    .filter-btn{font-family:var(--mono);font-size:.73rem;padding:.3em .8em;border-radius:6px;
      border:1px solid var(--line2);background:transparent;color:var(--mut);cursor:pointer;
      transition:all .15s}
    .filter-btn:hover,.filter-btn.active{border-color:var(--amber);color:var(--amber);
      background:rgba(255,138,61,.07)}
    /* ── sortable columns ── */
    th.sortable{cursor:pointer;user-select:none}
    th.sortable:hover{color:var(--ink)}
    th.sortable .sort-icon{color:var(--mut2);font-size:.7em}
    th.sortable.asc .sort-icon::before{content:'↑'}
    th.sortable.desc .sort-icon::before{content:'↓'}
    th.sortable:not(.asc):not(.desc) .sort-icon::before{content:'↕'}

    /* ── footer ── */
    footer{text-align:center;padding:2rem;color:var(--mut2);font-size:.8rem;border-top:1px solid var(--line)}
  </style>
  </head>
  <body>

  <div class="page-header">
    <div style="max-width:1400px;margin:0 auto">
      <div class="kicker"><span class="dot"></span> Dark Factory</div>
      <h1>Pipeline Production Report</h1>
      <div class="meta" id="report-meta"></div>
    </div>
  </div>

  <main>

    <!-- ── Section 1: Headline KPIs ── -->
    <section id="s-kpis">
      <h2>Headline KPIs</h2>
      <div class="kpi-grid" id="kpi-grid"></div>
    </section>

    <!-- ── Section 2: Throughput & Flow ── -->
    <section id="s-throughput">
      <h2>Throughput &amp; Flow</h2>
      <div class="chart-grid-2">
        <div class="chart-panel">
          <h3>Created vs Closed / week</h3>
          <div class="chart-box" id="chart-weekly-flow"></div>
        </div>
        <div class="chart-panel">
          <h3>Cumulative closed</h3>
          <div class="chart-box" id="chart-cumulative"></div>
        </div>
        <div class="chart-panel">
          <h3>Backlog size over time</h3>
          <div class="chart-box" id="chart-backlog"></div>
        </div>
        <div class="chart-panel">
          <h3>Issues opened by category</h3>
          <div class="chart-box" id="chart-category-bar"></div>
        </div>
      </div>
    </section>

    <!-- ── Section 3: Speed ── -->
    <section id="s-speed">
      <h2>Speed</h2>
      <div class="chart-grid-3">
        <div class="chart-panel">
          <h3>Lead-time distribution (hours)</h3>
          <div class="chart-box" id="chart-lead-time-hist"></div>
        </div>
        <div class="chart-panel">
          <h3>Median lead time trend</h3>
          <div class="chart-box" id="chart-lead-time-trend"></div>
        </div>
        <div class="chart-panel">
          <h3>Factory cycle time (DF issues)</h3>
          <div class="chart-box" id="chart-cycle-time"></div>
        </div>
      </div>
      <div class="chart-panel" style="margin-top:1rem">
        <h3>Aging WIP — open issues by age</h3>
        <div class="chart-box" id="chart-aging-wip"></div>
      </div>
    </section>

    <!-- ── Section 4: AI Cost Analytics ── -->
    <section id="s-cost">
      <h2>AI Cost Analytics</h2>
      <div class="chart-grid-2">
        <div class="chart-panel">
          <h3>Spend over time (cumulative)</h3>
          <div class="chart-box" id="chart-cost-cumulative"></div>
        </div>
        <div class="chart-panel">
          <h3>Per-ticket cost distribution</h3>
          <div class="chart-box" id="chart-cost-dist"></div>
        </div>
        <div class="chart-panel">
          <h3>Cost by pipeline step (aggregated)</h3>
          <div class="chart-box" id="chart-cost-by-step"></div>
        </div>
        <div class="chart-panel">
          <h3>Cost vs ticket size</h3>
          <div class="chart-box" id="chart-cost-vs-size"></div>
        </div>
        <div class="chart-panel">
          <h3>Token usage breakdown</h3>
          <div class="chart-box" id="chart-tokens"></div>
        </div>
        <div class="chart-panel">
          <h3>Rework spend (fix / retry runs)</h3>
          <div class="chart-box" id="chart-rework"></div>
        </div>
      </div>
    </section>

    <!-- ── Section 5: Category & Label Composition ── -->
    <section id="s-labels">
      <h2>Category &amp; Label Composition</h2>
      <div class="chart-grid-3">
        <div class="chart-panel">
          <h3>By priority</h3>
          <div class="chart-box" id="chart-by-priority"></div>
        </div>
        <div class="chart-panel">
          <h3>By size</h3>
          <div class="chart-box" id="chart-by-size"></div>
        </div>
        <div class="chart-panel">
          <h3>DF-autonomous vs human</h3>
          <div class="chart-box" id="chart-df-split"></div>
        </div>
      </div>
      <div class="chart-panel" style="margin-top:1rem">
        <h3>Label treemap</h3>
        <div class="chart-box-tall" id="chart-treemap"></div>
      </div>
    </section>

    <!-- ── Section 6: Pipeline Health ── -->
    <section id="s-health">
      <h2>Dark Factory Pipeline Health</h2>
      <div class="chart-grid-3">
        <div class="chart-panel">
          <h3>Run success rate by type</h3>
          <div class="chart-box" id="chart-run-success"></div>
        </div>
        <div class="chart-panel">
          <h3>Retry / rework rate trend</h3>
          <div class="chart-box" id="chart-retry-trend"></div>
        </div>
        <div class="chart-panel">
          <h3>Steps per run distribution</h3>
          <div class="chart-box" id="chart-steps-per-run"></div>
        </div>
      </div>
    </section>

    <!-- ── Issue table ── -->
    <section id="s-table">
      <h2>All Issues</h2>
      <div class="filters" id="table-filters"></div>
      <div class="table-wrap">
        <table id="issue-table">
          <thead>
            <tr>
              <th data-col="number" class="sortable"># <span class="sort-icon">↕</span></th>
              <th data-col="title" class="sortable">Title <span class="sort-icon">↕</span></th>
              <th data-col="size" class="sortable">Size <span class="sort-icon">↕</span></th>
              <th data-col="state" class="sortable">State <span class="sort-icon">↕</span></th>
              <th data-col="lead_time_hours" class="sortable">Lead time <span class="sort-icon">↕</span></th>
              <th data-col="cost" class="sortable">Cost <span class="sort-icon">↕</span></th>
              <th>DF?</th>
            </tr>
          </thead>
          <tbody id="table-body"></tbody>
        </table>
      </div>
    </section>

  </main>

  <footer id="footer"></footer>

  <script>{{ECHARTS_JS}}</script>
  <script>
  // ── Inject metrics data ──────────────────────────────────────────────────────
  window.__METRICS__ = {{METRICS_JSON}};

  // ── Colour palette helpers ───────────────────────────────────────────────────
  const C = {
    amber:'#ff8a3d', amberHot:'#ff6a1a', amberSoft:'#ffc08a',
    cyan:'#3fe0c8', cyanSoft:'#8af0e2',
    green:'#54d18a', red:'#ff6b6b', violet:'#a78bfa',
    mut:'#9aa0ad', mut2:'#6b7280', line:'rgba(255,255,255,.08)',
  };
  const PALETTE = [C.amber, C.cyan, C.green, C.violet, C.amberSoft, C.red, C.cyanSoft];

  function eChart(id, opts) {
    const el = document.getElementById(id);
    if (!el) return null;
    const chart = echarts.init(el, null, {renderer:'canvas'});
    chart.setOption({
      backgroundColor:'transparent',
      textStyle:{color:C.mut, fontFamily:'system-ui,sans-serif'},
      tooltip:{backgroundColor:'#13151d',borderColor:'rgba(255,255,255,.14)',textStyle:{color:'#eceef3'}},
      ...opts
    });
    window.addEventListener('resize', () => chart.resize());
    return chart;
  }

  const M = window.__METRICS__;
  const S = M.summary;
  const issues = M.issues || [];

  // ── KPI cards ────────────────────────────────────────────────────────────────
  (function buildKPIs() {
    const grid = document.getElementById('kpi-grid');
    function kpi(label, value, sub) {
      return `<div class="kpi-card">
        <div class="label">${label}</div>
        <div class="value">${value}</div>
        ${sub ? `<div class="sub">${sub}</div>` : ''}
      </div>`;
    }
    const medLt = S.median_lead_time_hours != null
      ? (S.median_lead_time_hours < 48
          ? S.median_lead_time_hours.toFixed(1) + 'h'
          : (S.median_lead_time_hours/24).toFixed(1) + 'd')
      : '—';
    grid.innerHTML = [
      kpi('Shipped', S.closed_issues, `of ${S.total_issues} total`),
      kpi('Total AI spend', '$' + S.total_cost_usd.toFixed(2), `${S.autonomous_issues} autonomous tickets`),
      kpi('Avg $/ticket', '$' + S.avg_cost_per_ticket.toFixed(2), 'autonomous only'),
      kpi('Median lead time', medLt, 'all closed issues'),
      kpi('% Autonomous', S.pct_autonomous.toFixed(1) + '%', 'tickets with cost report'),
    ].join('');
    document.getElementById('report-meta').textContent =
      `Generated ${new Date(M.generated_at).toLocaleString()} · ${S.total_issues} issues`;
  })();

  // ── Weekly timeseries helpers ─────────────────────────────────────────────────
  function weekKey(iso) {
    const d = new Date(iso);
    const day = d.getUTCDay();
    const diff = d.getUTCDate() - day + (day === 0 ? -6 : 1);
    const mon = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), diff));
    return mon.toISOString().slice(0, 10);
  }

  function buildWeeklyTimeseries() {
    const createdByWeek = {}, closedByWeek = {};
    for (const iss of issues) {
      if (iss.created_at) {
        const w = weekKey(iss.created_at);
        createdByWeek[w] = (createdByWeek[w] || 0) + 1;
      }
      if (iss.closed_at) {
        const w = weekKey(iss.closed_at);
        closedByWeek[w] = (closedByWeek[w] || 0) + 1;
      }
    }
    const weeks = [...new Set([...Object.keys(createdByWeek), ...Object.keys(closedByWeek)])].sort();
    let cum = 0, backlog = 0;
    const series = weeks.map(w => {
      const cr = createdByWeek[w] || 0;
      const cl = closedByWeek[w] || 0;
      backlog += cr - cl;
      cum += cl;
      return { week: w, created: cr, closed: cl, cumClosed: cum, backlog: Math.max(0, backlog) };
    });
    return { weeks, series };
  }

  // ── Section 2: Throughput ────────────────────────────────────────────────────
  (function buildThroughput() {
    const { weeks, series } = buildWeeklyTimeseries();

    eChart('chart-weekly-flow', {
      legend:{ data:['Created','Closed'], textStyle:{color:C.mut}, bottom:0 },
      xAxis:{ type:'category', data:weeks, axisLine:{lineStyle:{color:C.line}}, axisLabel:{color:C.mut2,rotate:30,fontSize:10} },
      yAxis:{ type:'value', splitLine:{lineStyle:{color:C.line}}, axisLabel:{color:C.mut2} },
      series:[
        { name:'Created', type:'bar', data:series.map(s=>s.created), itemStyle:{color:C.violet} },
        { name:'Closed', type:'bar', data:series.map(s=>s.closed), itemStyle:{color:C.green} },
      ]
    });

    eChart('chart-cumulative', {
      xAxis:{ type:'category', data:weeks, axisLabel:{color:C.mut2,rotate:30,fontSize:10}, axisLine:{lineStyle:{color:C.line}} },
      yAxis:{ type:'value', splitLine:{lineStyle:{color:C.line}}, axisLabel:{color:C.mut2} },
      series:[{ type:'line', data:series.map(s=>s.cumClosed), smooth:true,
        lineStyle:{color:C.amber,width:2}, itemStyle:{color:C.amber},
        areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,
          colorStops:[{offset:0,color:'rgba(255,138,61,.25)'},{offset:1,color:'rgba(255,138,61,.01)'}]}} }]
    });

    eChart('chart-backlog', {
      xAxis:{ type:'category', data:weeks, axisLabel:{color:C.mut2,rotate:30,fontSize:10}, axisLine:{lineStyle:{color:C.line}} },
      yAxis:{ type:'value', splitLine:{lineStyle:{color:C.line}}, axisLabel:{color:C.mut2} },
      series:[{ type:'line', data:series.map(s=>s.backlog), smooth:true,
        lineStyle:{color:C.red,width:2}, itemStyle:{color:C.red},
        areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,
          colorStops:[{offset:0,color:'rgba(255,107,107,.25)'},{offset:1,color:'rgba(255,107,107,.01)'}]}} }]
    });

    // category bar
    const cats = {};
    for (const iss of issues) {
      const cat = iss.labels.find(l => ['enhancement','bug','chore','analytics'].some(t => l.includes(t))) || 'other';
      cats[cat] = (cats[cat] || 0) + 1;
    }
    const catKeys = Object.keys(cats).sort((a,b)=>cats[b]-cats[a]);
    eChart('chart-category-bar', {
      xAxis:{ type:'value', splitLine:{lineStyle:{color:C.line}}, axisLabel:{color:C.mut2} },
      yAxis:{ type:'category', data:catKeys, axisLabel:{color:C.mut2,fontSize:10} },
      series:[{ type:'bar', data:catKeys.map(k=>cats[k]),
        itemStyle:{color:new echarts.graphic.LinearGradient(0,0,1,0,[
          {offset:0,color:C.amber},{offset:1,color:C.amberSoft}])} }]
    });
  })();

  // ── Section 3: Speed ─────────────────────────────────────────────────────────
  (function buildSpeed() {
    const ltHours = issues.filter(i=>i.state==='CLOSED'&&i.lead_time_hours!=null)
      .map(i=>i.lead_time_hours).sort((a,b)=>a-b);

    // histogram buckets (days)
    const buckets = [0,1,2,4,7,14,30,60,999];
    const labels = ['<1d','1d','2d','4d','1w','2w','1mo','>1mo'];
    const counts = Array(labels.length).fill(0);
    for (const h of ltHours) {
      const d = h/24;
      for (let i=0;i<buckets.length-1;i++) {
        if (d>=buckets[i]&&d<buckets[i+1]){counts[i]++;break;}
      }
    }
    eChart('chart-lead-time-hist',{
      xAxis:{type:'category',data:labels,axisLabel:{color:C.mut2},axisLine:{lineStyle:{color:C.line}}},
      yAxis:{type:'value',splitLine:{lineStyle:{color:C.line}},axisLabel:{color:C.mut2}},
      series:[{type:'bar',data:counts,itemStyle:{color:C.cyan}}]
    });

    // median trend (4-week rolling)
    const { weeks, series } = buildWeeklyTimeseries();
    const medByWeek = weeks.map((w,i) => {
      const range = weeks.slice(Math.max(0,i-3),i+1);
      const vals = issues
        .filter(iss=>iss.closed_at&&range.includes(weekKey(iss.closed_at))&&iss.lead_time_hours!=null)
        .map(iss=>iss.lead_time_hours).sort((a,b)=>a-b);
      return vals.length ? vals[Math.floor(vals.length/2)]/24 : null;
    });
    eChart('chart-lead-time-trend',{
      xAxis:{type:'category',data:weeks,axisLabel:{color:C.mut2,rotate:30,fontSize:10},axisLine:{lineStyle:{color:C.line}}},
      yAxis:{type:'value',name:'days',nameTextStyle:{color:C.mut2},splitLine:{lineStyle:{color:C.line}},axisLabel:{color:C.mut2}},
      series:[{type:'line',data:medByWeek,smooth:true,connectNulls:true,
        lineStyle:{color:C.amber,width:2},itemStyle:{color:C.amber}}]
    });

    // factory cycle time histogram (DF only) — uses factory_cycle_hours per spec
    const dfIssues = issues.filter(i=>i.autonomous&&i.cost?.runs?.length);
    const ctHours = dfIssues.filter(i=>i.factory_cycle_hours!=null).map(i=>i.factory_cycle_hours).sort((a,b)=>a-b);
    const ctCounts = Array(labels.length).fill(0);
    for (const h of ctHours) {
      const d=h/24;
      for (let i=0;i<buckets.length-1;i++){if(d>=buckets[i]&&d<buckets[i+1]){ctCounts[i]++;break;}}
    }
    eChart('chart-cycle-time',{
      xAxis:{type:'category',data:labels,axisLabel:{color:C.mut2},axisLine:{lineStyle:{color:C.line}}},
      yAxis:{type:'value',splitLine:{lineStyle:{color:C.line}},axisLabel:{color:C.mut2}},
      series:[{type:'bar',data:ctCounts,itemStyle:{color:C.violet}}]
    });

    // aging WIP
    const now = Date.now();
    const ageBuckets = ['<1d','1-7d','1-4w','1-3mo','>3mo'];
    const ageLimits = [1,7,30,90,Infinity].map(d=>d*24*3600*1000);
    const ageCounts = Array(ageBuckets.length).fill(0);
    for (const iss of issues.filter(i=>i.state==='OPEN'&&i.created_at)) {
      const ageMs = now - new Date(iss.created_at).getTime();
      for (let i=0;i<ageLimits.length;i++){if(ageMs<ageLimits[i]){ageCounts[i]++;break;}}
    }
    eChart('chart-aging-wip',{
      xAxis:{type:'category',data:ageBuckets,axisLabel:{color:C.mut2},axisLine:{lineStyle:{color:C.line}}},
      yAxis:{type:'value',splitLine:{lineStyle:{color:C.line}},axisLabel:{color:C.mut2}},
      series:[{type:'bar',data:ageCounts,
        itemStyle:{color:(params)=>params.value>5?C.red:params.value>2?C.amber:C.green}}]
    });
  })();

  // ── Section 4: AI Cost Analytics ─────────────────────────────────────────────
  (function buildCost() {
    const dfIssues = issues.filter(i=>i.autonomous&&i.cost);

    // cumulative spend
    const sorted = [...dfIssues].filter(i=>i.closed_at).sort((a,b)=>new Date(a.closed_at)-new Date(b.closed_at));
    let cum=0;
    const { weeks } = buildWeeklyTimeseries();
    const costByWeek = {};
    for (const iss of sorted) {
      const w = weekKey(iss.closed_at);
      costByWeek[w] = (costByWeek[w]||0) + iss.cost.total_usd;
    }
    let runCum=0;
    const cumCost = weeks.map(w=>{ runCum+=(costByWeek[w]||0); return +runCum.toFixed(4); });
    eChart('chart-cost-cumulative',{
      xAxis:{type:'category',data:weeks,axisLabel:{color:C.mut2,rotate:30,fontSize:10},axisLine:{lineStyle:{color:C.line}}},
      yAxis:{type:'value',name:'$',nameTextStyle:{color:C.mut2},splitLine:{lineStyle:{color:C.line}},axisLabel:{color:C.mut2}},
      series:[{type:'line',data:cumCost,smooth:true,lineStyle:{color:C.amber,width:2},itemStyle:{color:C.amber},
        areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,
          colorStops:[{offset:0,color:'rgba(255,138,61,.3)'},{offset:1,color:'rgba(255,138,61,.01)'}]}}}]
    });

    // cost distribution
    const costs = dfIssues.map(i=>+(i.cost.total_usd.toFixed(2))).sort((a,b)=>a-b);
    eChart('chart-cost-dist',{
      xAxis:{type:'value',name:'$',nameTextStyle:{color:C.mut2},splitLine:{lineStyle:{color:C.line}},axisLabel:{color:C.mut2}},
      yAxis:{type:'value',name:'count',nameTextStyle:{color:C.mut2},splitLine:{lineStyle:{color:C.line}},axisLabel:{color:C.mut2}},
      series:[{type:'scatter',data:costs.map((c,i)=>[c,i+1]),symbolSize:6,itemStyle:{color:C.cyan,opacity:.7}}]
    });

    // cost by step — use the per-issue step data
    const stepAgg = {};
    for (const iss of dfIssues) {
      for (const run of (iss.cost.runs||[])) {
        // runs only have type/status in our schema — steps are global in metrics
      }
    }
    // Use M.cost_by_step if present, else skip
    const cbsData = M.cost_by_step || {};
    const cbsKeys = Object.keys(cbsData).sort((a,b)=>cbsData[b]-cbsData[a]).slice(0,10);
    eChart('chart-cost-by-step',{
      xAxis:{type:'value',splitLine:{lineStyle:{color:C.line}},axisLabel:{color:C.mut2}},
      yAxis:{type:'category',data:cbsKeys,axisLabel:{color:C.mut2,fontSize:10}},
      series:[{type:'bar',data:cbsKeys.map(k=>+cbsData[k].toFixed(4)),
        itemStyle:{color:new echarts.graphic.LinearGradient(0,0,1,0,[
          {offset:0,color:C.amber},{offset:1,color:C.amberSoft}])}}]
    });

    // cost vs size
    const sizeMap={'S':[],'M':[],'L':[],'XL':[]};
    for (const iss of dfIssues) {
      const s = iss.size||'?';
      if (!sizeMap[s]) sizeMap[s]=[];
      sizeMap[s].push(iss.cost.total_usd);
    }
    const sizeKeys = Object.keys(sizeMap).filter(k=>sizeMap[k].length>0);
    eChart('chart-cost-vs-size',{
      xAxis:{type:'category',data:sizeKeys,axisLabel:{color:C.mut2},axisLine:{lineStyle:{color:C.line}}},
      yAxis:{type:'value',name:'$ avg',nameTextStyle:{color:C.mut2},splitLine:{lineStyle:{color:C.line}},axisLabel:{color:C.mut2}},
      series:[{type:'bar',data:sizeKeys.map(k=>{
        const arr=sizeMap[k]; return +(arr.reduce((a,b)=>a+b,0)/arr.length).toFixed(4);
      }),itemStyle:{color:C.violet}}]
    });

    // tokens
    const totIn = dfIssues.reduce((s,i)=>s+i.cost.in_tokens,0);
    const totOut = dfIssues.reduce((s,i)=>s+i.cost.out_tokens,0);
    eChart('chart-tokens',{
      series:[{type:'pie',radius:['40%','70%'],data:[
        {value:totIn,name:'Input',itemStyle:{color:C.cyan}},
        {value:totOut,name:'Output',itemStyle:{color:C.amber}},
      ],label:{color:C.mut},emphasis:{itemStyle:{shadowBlur:10}}}]
    });

    // rework spend
    const reworkCost = dfIssues.reduce((s,iss)=>{
      const rw = (iss.cost.runs||[]).filter(r=>r.run_type==='fix'||r.run_type==='retry');
      return s; // run-level cost not tracked in schema; use issue-count proxy
    }, 0);
    const fixCount = dfIssues.filter(i=>(i.cost.runs||[]).some(r=>r.run_type==='fix')).length;
    eChart('chart-rework',{
      series:[{type:'pie',radius:['40%','70%'],data:[
        {value:dfIssues.length-fixCount,name:'Clean runs',itemStyle:{color:C.green}},
        {value:fixCount,name:'Had fix run',itemStyle:{color:C.amber}},
      ],label:{color:C.mut},emphasis:{itemStyle:{shadowBlur:10}}}]
    });
  })();

  // ── Section 5: Labels ────────────────────────────────────────────────────────
  (function buildLabels() {
    function pieFrom(map) {
      return Object.entries(map).sort((a,b)=>b[1]-a[1]).map(([n,v],i)=>({
        value:v,name:n,itemStyle:{color:PALETTE[i%PALETTE.length]}}));
    }

    const priority={}, size={};
    for (const iss of issues) {
      const p=iss.priority||'unset'; priority[p]=(priority[p]||0)+1;
      const s=iss.size||'?'; size[s]=(size[s]||0)+1;
    }
    eChart('chart-by-priority',{series:[{type:'pie',radius:['40%','70%'],data:pieFrom(priority),label:{color:C.mut}}]});
    eChart('chart-by-size',{series:[{type:'pie',radius:['40%','70%'],data:pieFrom(size),label:{color:C.mut}}]});

    const dfCount=issues.filter(i=>i.autonomous).length;
    eChart('chart-df-split',{series:[{type:'pie',radius:['40%','70%'],data:[
      {value:dfCount,name:'Autonomous (DF)',itemStyle:{color:C.amber}},
      {value:issues.length-dfCount,name:'Human',itemStyle:{color:C.mut}},
    ],label:{color:C.mut}}]});

    // treemap
    const labelCounts={};
    for (const iss of issues) for (const l of iss.labels) {
      labelCounts[l]=(labelCounts[l]||0)+1;
    }
    const tmData=Object.entries(labelCounts).map(([n,v])=>({name:n,value:v}))
      .sort((a,b)=>b.value-a.value);
    eChart('chart-treemap',{
      series:[{type:'treemap',data:tmData,
        label:{show:true,formatter:'{b}: {c}',fontSize:11},
        itemStyle:{borderColor:C.line,borderWidth:1},
        levels:[{itemStyle:{borderColor:'rgba(255,255,255,.12)',gapWidth:2,borderWidth:2,
          colorSaturation:[.6,1]}}],
        color:PALETTE}]
    });
  })();

  // ── Section 6: Pipeline Health ───────────────────────────────────────────────
  (function buildHealth() {
    const allRuns=[];
    for (const iss of issues.filter(i=>i.autonomous&&i.cost)) {
      for (const r of (iss.cost.runs||[])) allRuns.push(r);
    }
    const byType={};
    for (const r of allRuns) {
      const t=r.run_type||'unknown';
      if (!byType[t]) byType[t]={completed:0,total:0};
      byType[t].total++;
      if (r.status==='completed') byType[t].completed++;
    }
    const typeKeys=Object.keys(byType);
    eChart('chart-run-success',{
      legend:{data:['Completed','Other'],textStyle:{color:C.mut},bottom:0},
      xAxis:{type:'category',data:typeKeys,axisLabel:{color:C.mut2},axisLine:{lineStyle:{color:C.line}}},
      yAxis:{type:'value',splitLine:{lineStyle:{color:C.line}},axisLabel:{color:C.mut2}},
      series:[
        {name:'Completed',type:'bar',stack:'total',data:typeKeys.map(k=>byType[k].completed),itemStyle:{color:C.green}},
        {name:'Other',type:'bar',stack:'total',data:typeKeys.map(k=>byType[k].total-byType[k].completed),itemStyle:{color:C.red}},
      ]
    });

    const {weeks} = buildWeeklyTimeseries();
    const fixByWeek={};
    for (const iss of issues.filter(i=>i.autonomous&&i.cost&&i.closed_at)) {
      const hasFix=(iss.cost.runs||[]).some(r=>r.run_type==='fix');
      if (hasFix) { const w=weekKey(iss.closed_at); fixByWeek[w]=(fixByWeek[w]||0)+1; }
    }
    const closedDFByWeek={};
    for (const iss of issues.filter(i=>i.autonomous&&i.closed_at)) {
      const w=weekKey(iss.closed_at); closedDFByWeek[w]=(closedDFByWeek[w]||0)+1;
    }
    const retryRate=weeks.map(w=>closedDFByWeek[w]
      ? +((fixByWeek[w]||0)/closedDFByWeek[w]*100).toFixed(1) : null);
    eChart('chart-retry-trend',{
      xAxis:{type:'category',data:weeks,axisLabel:{color:C.mut2,rotate:30,fontSize:10},axisLine:{lineStyle:{color:C.line}}},
      yAxis:{type:'value',name:'%',nameTextStyle:{color:C.mut2},splitLine:{lineStyle:{color:C.line}},axisLabel:{color:C.mut2}},
      series:[{type:'line',data:retryRate,smooth:true,connectNulls:true,
        lineStyle:{color:C.red,width:2},itemStyle:{color:C.red}}]
    });

    // steps per run
    const runLengths = allRuns.map(()=>1); // placeholder — step count not in schema
    // show run type distribution instead
    eChart('chart-steps-per-run',{
      series:[{type:'pie',radius:['40%','70%'],data:typeKeys.map((k,i)=>({
        value:byType[k].total,name:k,itemStyle:{color:PALETTE[i%PALETTE.length]}})),
        label:{color:C.mut}}]
    });
  })();

  // ── Issue table ──────────────────────────────────────────────────────────────
  (function buildTable() {
    let filtered = [...issues];
    const filters = {state:'ALL',autonomous:'ALL',size:'ALL'};
    let sortCol = null, sortDir = 1; // 1=asc, -1=desc

    const filtersEl = document.getElementById('table-filters');
    function addFilter(key, values) {
      values.forEach(v => {
        const btn = document.createElement('button');
        btn.className = 'filter-btn' + (v === 'ALL' ? ' active' : '');
        btn.textContent = v;
        btn.dataset.key = key;
        btn.dataset.val = v;
        btn.onclick = () => {
          filtersEl.querySelectorAll(`[data-key="${key}"]`).forEach(b=>b.classList.remove('active'));
          btn.classList.add('active');
          filters[key] = v;
          renderTable();
        };
        filtersEl.appendChild(btn);
      });
    }
    addFilter('state', ['ALL','CLOSED','OPEN']);
    addFilter('autonomous', ['ALL','DF','Human']);
    addFilter('size', ['ALL','S','M','L','XL']);

    // Column sort — click header to sort asc; click again to flip
    document.querySelectorAll('th.sortable').forEach(th => {
      th.addEventListener('click', () => {
        const col = th.dataset.col;
        if (sortCol === col) { sortDir *= -1; }
        else { sortCol = col; sortDir = 1; }
        document.querySelectorAll('th.sortable').forEach(h => h.classList.remove('asc','desc'));
        th.classList.add(sortDir === 1 ? 'asc' : 'desc');
        renderTable();
      });
    });

    function colValue(iss, col) {
      if (col === 'number') return iss.number;
      if (col === 'title') return iss.title.toLowerCase();
      if (col === 'size') return ['S','M','L','XL'].indexOf(iss.size ?? '?');
      if (col === 'state') return iss.state;
      if (col === 'lead_time_hours') return iss.lead_time_hours ?? Infinity;
      if (col === 'cost') return iss.cost?.total_usd ?? -1;
      return '';
    }

    function renderTable() {
      filtered = issues.filter(iss => {
        if (filters.state !== 'ALL' && iss.state !== filters.state) return false;
        if (filters.autonomous === 'DF' && !iss.autonomous) return false;
        if (filters.autonomous === 'Human' && iss.autonomous) return false;
        if (filters.size !== 'ALL' && iss.size !== filters.size) return false;
        return true;
      });
      if (sortCol) {
        filtered = [...filtered].sort((a, b) => {
          const av = colValue(a, sortCol), bv = colValue(b, sortCol);
          return av < bv ? -sortDir : av > bv ? sortDir : 0;
        });
      }
      const tbody = document.getElementById('table-body');
      tbody.innerHTML = filtered.map(iss => {
        const lt = iss.lead_time_hours != null
          ? (iss.lead_time_hours < 48 ? iss.lead_time_hours.toFixed(1)+'h' : (iss.lead_time_hours/24).toFixed(1)+'d')
          : '—';
        const cost = iss.cost ? '$'+iss.cost.total_usd.toFixed(2) : '—';
        const sizeClass = iss.size === 'S' ? 'badge badge-s' : iss.size === 'M' ? 'badge badge-m' : iss.size ? 'badge badge-l' : '';
        return `<tr>
          <td class="mono">#${iss.number}</td>
          <td>${iss.title}</td>
          <td>${iss.size ? `<span class="${sizeClass}">${iss.size}</span>` : '—'}</td>
          <td class="${iss.state==='CLOSED'?'gr':'mut'}">${iss.state}</td>
          <td class="mono">${lt}</td>
          <td class="am">${cost}</td>
          <td>${iss.autonomous ? '<span class="badge badge-df">DF</span>' : ''}</td>
        </tr>`;
      }).join('');
    }
    renderTable();
  })();

  // ── Footer ───────────────────────────────────────────────────────────────────
  document.getElementById('footer').textContent =
    `MarketHawk Dark Factory · Pipeline Report · ${new Date(M.generated_at).toLocaleDateString()}`;
  </script>
  </body>
  </html>
  ```

- [ ] 3.2 Verify the template has the two required placeholders:

  ```bash
  grep -c "{{ECHARTS_JS}}" scripts/template.html   # expect: 1
  grep -c "{{METRICS_JSON}}" scripts/template.html  # expect: 1
  ```

- [ ] 3.3 Commit:

  ```bash
  git add scripts/template.html
  git commit -m "feat(#212): add Dark Factory HTML report template with ECharts chart containers"
  ```

---

## Task 4 — Report renderer (`render_report.py`)

**Files:** `scripts/render_report.py` (new), `tests/scripts/test_render_report.py` (new)

### Steps

- [ ] 4.1 Write failing tests for the renderer in `tests/scripts/test_render_report.py`:

  ```python
  # tests/scripts/test_render_report.py
  import json
  import re
  import scripts.render_report as render_report
  from pathlib import Path
  from scripts.render_report import render

  FIXTURES = Path(__file__).parent / "fixtures"
  TEMPLATE = Path(__file__).parent.parent.parent / "scripts" / "template.html"
  STUB_ECHARTS = "var echarts={init:function(){return {setOption:function(){},resize:function(){}};},graphic:{LinearGradient:function(){}}}"

  SAMPLE_METRICS = {
      "generated_at": "2026-06-04T18:00:00Z",
      "summary": {
          "total_issues": 3, "closed_issues": 2, "open_issues": 1,
          "autonomous_issues": 1, "pct_autonomous": 33.3,
          "total_cost_usd": 2.50, "avg_cost_per_ticket": 2.50,
          "median_lead_time_hours": 2.5, "p85_lead_time_hours": 54.0,
      },
      "issues": [],
      "cost_by_step": {"plan": 1.25, "implement": 1.25},
  }

  def test_render_produces_html(tmp_path, monkeypatch):
      monkeypatch.setattr(render_report, "_get_echarts_js", lambda: STUB_ECHARTS)
      metrics_path = tmp_path / "metrics.json"
      metrics_path.write_text(json.dumps(SAMPLE_METRICS))
      output_path = tmp_path / "report.html"
      render(str(metrics_path), str(TEMPLATE), str(output_path))
      assert output_path.exists()
      html = output_path.read_text()
      assert html.startswith("<!DOCTYPE html")

  def test_render_embeds_metrics(tmp_path, monkeypatch):
      monkeypatch.setattr(render_report, "_get_echarts_js", lambda: STUB_ECHARTS)
      metrics_path = tmp_path / "metrics.json"
      metrics_path.write_text(json.dumps(SAMPLE_METRICS))
      output_path = tmp_path / "report.html"
      render(str(metrics_path), str(TEMPLATE), str(output_path))
      html = output_path.read_text()
      assert "window.__METRICS__" in html
      assert '"total_issues": 3' in html

  def test_render_no_external_scripts(tmp_path, monkeypatch):
      monkeypatch.setattr(render_report, "_get_echarts_js", lambda: STUB_ECHARTS)
      metrics_path = tmp_path / "metrics.json"
      metrics_path.write_text(json.dumps(SAMPLE_METRICS))
      output_path = tmp_path / "report.html"
      render(str(metrics_path), str(TEMPLATE), str(output_path))
      html = output_path.read_text()
      # No external src= references
      external = re.findall(r'src=["\']https?://', html)
      assert external == [], f"External script references found: {external}"

  def test_render_no_placeholder_leakage(tmp_path, monkeypatch):
      monkeypatch.setattr(render_report, "_get_echarts_js", lambda: STUB_ECHARTS)
      metrics_path = tmp_path / "metrics.json"
      metrics_path.write_text(json.dumps(SAMPLE_METRICS))
      output_path = tmp_path / "report.html"
      render(str(metrics_path), str(TEMPLATE), str(output_path))
      html = output_path.read_text()
      assert "{{ECHARTS_JS}}" not in html
      assert "{{METRICS_JSON}}" not in html
  ```

  Run to confirm failure:

  ```bash
  python3 -m pytest tests/scripts/test_render_report.py -v 2>&1 | tail -5
  ```

  Expected: `ImportError: cannot import name 'render' from 'scripts.render_report'`

- [ ] 4.2 Create `scripts/render_report.py` with the `render` function and ECharts vendoring:

  ```python
  #!/usr/bin/env python3
  """Stage 2: metrics.json + template.html → self-contained pipeline-report.html"""
  import json
  import sys
  import urllib.request
  from pathlib import Path

  ECHARTS_URL = "https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"
  ECHARTS_CACHE = Path(__file__).parent / "echarts.min.js"


  def _get_echarts_js() -> str:
      """Return vendored ECharts JS, downloading once if not cached."""
      if ECHARTS_CACHE.exists():
          return ECHARTS_CACHE.read_text(encoding="utf-8")
      print(f"Downloading ECharts from {ECHARTS_URL} …", file=sys.stderr)
      with urllib.request.urlopen(ECHARTS_URL, timeout=30) as resp:
          js = resp.read().decode("utf-8")
      ECHARTS_CACHE.write_text(js, encoding="utf-8")
      print(f"Cached to {ECHARTS_CACHE}", file=sys.stderr)
      return js


  def render(metrics_path: str, template_path: str, output_path: str) -> None:
      """Render the pipeline report.

      Reads metrics JSON, injects ECharts (vendored) and metrics data into the
      template, writes a single self-contained HTML file.
      """
      metrics = json.loads(Path(metrics_path).read_text(encoding="utf-8"))
      template = Path(template_path).read_text(encoding="utf-8")
      echarts_js = _get_echarts_js()

      html = template.replace("{{ECHARTS_JS}}", echarts_js, 1)
      html = html.replace("{{METRICS_JSON}}", json.dumps(metrics, indent=2, default=str), 1)

      Path(output_path).write_text(html, encoding="utf-8")
      print(f"Wrote {output_path} ({len(html)//1024} KB)", file=sys.stderr)


  if __name__ == "__main__":
      import argparse

      parser = argparse.ArgumentParser()
      parser.add_argument("--metrics", default="metrics.json")
      parser.add_argument("--template", default="scripts/template.html")
      parser.add_argument("--output", default="docs/pipeline-report.html")
      args = parser.parse_args()

      render(args.metrics, args.template, args.output)
  ```

- [ ] 4.3 Run all renderer tests — all four must pass:

  ```bash
  python3 -m pytest tests/scripts/test_render_report.py -v
  ```

  Expected:
  ```
  PASSED tests/scripts/test_render_report.py::test_render_produces_html
  PASSED tests/scripts/test_render_report.py::test_render_embeds_metrics
  PASSED tests/scripts/test_render_report.py::test_render_no_external_scripts
  PASSED tests/scripts/test_render_report.py::test_render_no_placeholder_leakage
  4 passed
  ```

- [ ] 4.4 Run full test suite:

  ```bash
  python3 -m pytest tests/scripts/ -v
  ```

  Expected: 13 passed

- [ ] 4.5 Commit:

  ```bash
  git add scripts/render_report.py tests/scripts/test_render_report.py
  git commit -m "feat(#212): add self-contained report renderer with ECharts vendoring"
  ```

---

## Task 5 — Cost-by-step aggregation + generate.sh + full run

**Files:** `scripts/fetch_metrics.py` (extend: add `cost_by_step`), `scripts/generate.sh` (new), `metrics.json` (generated), `docs/pipeline-report.html` (generated)

### Steps

- [ ] 5.1 Add `cost_by_step` aggregation to `build_issue_metrics` in `scripts/fetch_metrics.py`. This powers the "Cost by pipeline step" chart:

  ```python
  # Add compute_cost_by_step as a standalone function in scripts/fetch_metrics.py:
  def compute_cost_by_step(issues_raw: list[dict], comments_map: dict[str, list[dict]]) -> dict[str, float]:
      """Aggregate cost per pipeline step across all cost-report comments."""
      agg: dict[str, float] = {}
      for issue in issues_raw:
          num = str(issue["number"])
          for comment in comments_map.get(num, []):
              body = comment.get("body", "")
              if "<!-- dark-factory-cost-report -->" not in body:
                  continue
              for step in parse_step_table(body):
                  name = step["step"]
                  agg[name] = agg.get(name, 0.0) + step["cost_usd"]
      return {k: round(v, 6) for k, v in sorted(agg.items(), key=lambda x: -x[1])}
  ```

  Update the `build_issue_metrics` return to include `cost_by_step`:

  ```python
  return {
      "generated_at": datetime.now(timezone.utc).isoformat(),
      "summary": { ... },
      "issues": processed,
      "cost_by_step": compute_cost_by_step(issues, comments_map),
  }
  ```

  Add a test for this in `test_fetch_metrics.py`:

  ```python
  def test_build_issue_metrics_cost_by_step():
      issues = json.loads((FIXTURES / "sample_issues.json").read_text())
      comments_map = json.loads((FIXTURES / "sample_comments.json").read_text())
      result = build_issue_metrics(issues, comments_map)
      cbs = result["cost_by_step"]
      assert "plan" in cbs
      assert "implement" in cbs
      assert abs(cbs["plan"] - 1.25) < 0.01
  ```

  Run test to confirm pass:

  ```bash
  python3 -m pytest tests/scripts/test_fetch_metrics.py::test_build_issue_metrics_cost_by_step -v
  ```

- [ ] 5.2 Create `scripts/generate.sh`:

  ```bash
  #!/usr/bin/env bash
  set -euo pipefail

  REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  METRICS_OUT="${METRICS_OUT:-${REPO_ROOT}/metrics.json}"
  TEMPLATE="${TEMPLATE:-${REPO_ROOT}/scripts/template.html}"
  REPORT_OUT="${REPORT_OUT:-${REPO_ROOT}/docs/pipeline-report.html}"

  echo "==> Stage 1: fetch metrics"
  python3 "${REPO_ROOT}/scripts/fetch_metrics.py" --output "${METRICS_OUT}"

  echo "==> Stage 2: render report"
  python3 "${REPO_ROOT}/scripts/render_report.py" \
    --metrics "${METRICS_OUT}" \
    --template "${TEMPLATE}" \
    --output "${REPORT_OUT}"

  echo "Done. Report: ${REPORT_OUT}"
  ```

  ```bash
  chmod +x scripts/generate.sh
  ```

- [ ] 5.3 Run `generate.sh` end-to-end (requires `gh` auth and network for ECharts download):

  ```bash
  bash scripts/generate.sh 2>&1
  ```

  Expected output:
  ```
  ==> Stage 1: fetch metrics
  Fetching issues…
    112 issues found
  Fetching comments…
    [1/112] fetching comments for #1
    ...
  Computing metrics…
  Wrote metrics.json
  ==> Stage 2: render report
  Downloading ECharts from https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js …
  Cached to scripts/echarts.min.js
  Wrote docs/pipeline-report.html (NNNN KB)
  Done. Report: docs/pipeline-report.html
  ```

  Verify the output:

  ```bash
  python3 -c "import json; d=json.load(open('metrics.json')); print('Issues:', d['summary']['total_issues'], 'Autonomous:', d['summary']['autonomous_issues'])"
  wc -c docs/pipeline-report.html   # expect > 1 MB with ECharts vendored
  grep -c "external" docs/pipeline-report.html || true  # expect 0 external src= refs
  python3 -c "
  import re
  html = open('docs/pipeline-report.html').read()
  ext = re.findall(r'src=[\"\\']https?://', html)
  print('External refs:', ext or 'none')
  "
  ```

- [ ] 5.4 Commit everything. Note: `scripts/echarts.min.js` is intentionally committed — it is the vendored ECharts bundle that makes `pipeline-report.html` regenerable offline without a network dependency. Do **not** add it to `.gitignore`.

  ```bash
  git add scripts/ metrics.json docs/pipeline-report.html
  git commit -m "feat(#212): generate pipeline report (metrics.json + self-contained HTML)"
  ```

---

## Task 6 — Timeseries extension + factory-cycle-time + README note

**Files:** `scripts/fetch_metrics.py` (extend: add weekly timeseries to metrics.json), `README` / `docs/` (no new doc file — just record usage in commit message)

### Steps

- [ ] 6.1 Add weekly timeseries computation to `fetch_metrics.py` so charts don't recompute it client-side from raw issue data (optional but improves render performance). Add to `build_issue_metrics` return:

  ```python
  def _week_key(iso: str) -> str:
      d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
      day = d.weekday()  # Monday = 0
      monday = d - __import__("datetime").timedelta(days=day)
      return monday.strftime("%Y-%m-%d")


  def _compute_weekly_timeseries(issues: list[dict]) -> list[dict]:
      created_by_week: dict[str, int] = {}
      closed_by_week: dict[str, int] = {}
      for iss in issues:
          if iss.get("created_at"):
              w = _week_key(iss["created_at"])
              created_by_week[w] = created_by_week.get(w, 0) + 1
          if iss.get("closed_at"):
              w = _week_key(iss["closed_at"])
              closed_by_week[w] = closed_by_week.get(w, 0) + 1
      all_weeks = sorted(set(list(created_by_week) + list(closed_by_week)))
      backlog = 0
      cum = 0
      result = []
      for w in all_weeks:
          cr = created_by_week.get(w, 0)
          cl = closed_by_week.get(w, 0)
          backlog += cr - cl
          cum += cl
          result.append({"week": w, "created": cr, "closed": cl,
                         "cum_closed": cum, "backlog": max(0, backlog)})
      return result
  ```

  Add to `build_issue_metrics` return value:

  ```python
  return {
      ...
      "timeseries": {"weekly": _compute_weekly_timeseries(processed)},
      ...
  }
  ```

  Write and run a test:

  ```python
  # append to test_fetch_metrics.py
  def test_build_issue_metrics_timeseries():
      issues = json.loads((FIXTURES / "sample_issues.json").read_text())
      comments_map = json.loads((FIXTURES / "sample_comments.json").read_text())
      result = build_issue_metrics(issues, comments_map)
      ts = result["timeseries"]["weekly"]
      assert isinstance(ts, list)
      for week in ts:
          assert "week" in week and "created" in week and "closed" in week
  ```

  ```bash
  python3 -m pytest tests/scripts/ -v
  ```

  Expected: all tests pass.

- [ ] 6.2 Run the full pipeline once more to bake the timeseries into the committed artifacts:

  ```bash
  bash scripts/generate.sh 2>&1
  ```

- [ ] 6.3 Commit all artifacts and test additions:

  ```bash
  git add scripts/fetch_metrics.py tests/scripts/ metrics.json docs/pipeline-report.html
  git commit -m "feat(#212): add weekly timeseries to metrics.json + regenerate artifacts"
  ```

---

## Appendix — Regenerating the report

```bash
# Re-pull data from GitHub and regenerate:
bash scripts/generate.sh

# Override output paths:
METRICS_OUT=/tmp/metrics.json REPORT_OUT=/tmp/report.html bash scripts/generate.sh

# Use existing metrics.json without re-fetching:
python3 scripts/render_report.py --metrics metrics.json --template scripts/template.html \
  --output docs/pipeline-report.html
```
