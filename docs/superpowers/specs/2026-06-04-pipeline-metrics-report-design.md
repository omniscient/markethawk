# Pipeline Metrics Report — Design Spec

**Issue:** [#212](https://github.com/omniscient/markethawk/issues/212)
**Component:** `scripts/` (new Python scripts + shell orchestrator + HTML template)
**Status:** Approved

---

## Summary

Build a single self-contained, interactive HTML report that visualises the MarketHawk GitHub-issue delivery pipeline — with a focus on the **Dark Factory** autonomous production line. It answers at a glance: *how much have we shipped, how fast, at what AI cost, and how reliably?*

Showcase piece (visual impact first), rendered in the existing **Dark Factory visual language**. **Regenerable**: a script re-pulls GitHub data and bakes a fresh, offline-viewable HTML file on demand.

---

## Locked Decisions

| Decision | Choice |
|----------|--------|
| Audience | Showcase / portfolio — visual impact first |
| Freshness | Regenerable static snapshot (data baked at generation time) |
| Interactivity | Rich — hover tooltips, filters, toggles, sortable table |
| Visual | "Dark Factory" skin (palette from `docs/presentations/dark-factory.html`) |
| Architecture | Two-stage: `metrics.json` dump + template renderer |
| Language | Python both stages (JSON boundary keeps it decoupled) |
| Charts | ECharts, vendored inline for offline self-containment |

---

## Architecture

```
scripts/
  fetch_metrics.py     # Stage 1: gh CLI → issues/comments → metrics.json
  render_report.py     # Stage 2: metrics.json + template.html → pipeline-report.html
  template.html        # Chart containers + ECharts init JS
  generate.sh          # Runs both stages end-to-end
docs/
  pipeline-report.html # Committed output (self-contained)
metrics.json           # Committed data snapshot
```

- **Stage 1 `fetch_metrics.py`** — `gh` pulls issues + comments, parses the `<!-- dark-factory-cost-report -->` markers (machine-readable `cumulative:` totals + per-step table), computes metrics, writes committable `metrics.json`. Independently unit-testable.
- **Stage 2 `render_report.py`** — `metrics.json` + `template.html` + vendored ECharts → one self-contained `pipeline-report.html`.
- **`generate.sh`** runs both.

---

## Report Sections (~18–20 charts)

1. **Headline KPIs** — shipped, total AI spend, avg $/ticket, median lead time, % autonomous
2. **Throughput & flow** — created vs. closed/week, cumulative burned-down, backlog size over time
3. **Speed** — lead-time distribution (median/p85), trend over time, factory cycle time, aging WIP
4. **AI cost analytics** — spend over time, per-ticket distribution, cost by step, cost vs. size label, token counts, rework spend
5. **Category / label composition** — category / priority / size / timeframe breakdown, DF-vs-human split, treemap
6. **Dark Factory pipeline health** — run success rate, retry/rework rate, steps per run (honest caveat: failure-reason detail is thin)

---

## Data Definitions

- **Lead time** = `closedAt − createdAt` (all closed issues)
- **Factory cycle time** = `closedAt − first-run-timestamp` (cost-report subset only)
- **% autonomous** = issues-with-cost-report ÷ total (labeled precisely in UI)
- **Rework spend** = cost of runs with `run_type` ≠ `plan` and ≠ `implement` (e.g. `fix`, `retry`)

---

## Cost-Report Marker Format

Comments containing `<!-- dark-factory-cost-report -->` drive cost analytics. Machine-readable line:

```
<!-- cumulative: cost=7.197 in=310 out=123906 -->
```

Per-run block:
```
### Run: 2026-06-04 12:42 UTC (plan, completed)
| Step | Model | In tokens | Out tokens | Cost | Duration |
```

---

## Data Coverage (2026-06-04 snapshot)

- 112 issues (89 closed, 23 open)
- 34 carry a cost-report comment → cost + health metrics
- 17 carry the "Dark Factory" label

---

## Out of Scope (v1)

- Leaderboards / hall-of-fame section
- Conformance-gate pass/fail detail
- GitHub Pages publishing
