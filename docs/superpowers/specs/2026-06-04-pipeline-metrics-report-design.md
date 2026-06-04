# Pipeline Production Report — Design Spec

**Date:** 2026-06-04
**Status:** Approved (brainstorming) → ready for implementation plan
**Author:** Frank + Claude (brainstorming session)

## Summary

A single self-contained, interactive HTML report that visualizes the MarketHawk
GitHub-issue delivery pipeline — with a focus on the Dark Factory autonomous
production line. It answers, at a glance: *how much have we shipped, how fast,
at what AI cost, and how reliably?*

The artifact is a **showcase piece** (visual impact first) rendered in the
existing **"Dark Factory" visual language** (near-black background, hot-amber
primary, cyan/green/violet data accents, monospace labels). It is **regenerable**:
a script re-pulls GitHub data and bakes a fresh, offline-viewable HTML file on
demand.

## Goals

- Tell the production-pipeline story persuasively to a non-engineer-friendly
  audience (showcase / portfolio).
- Surface the metrics a professional delivery team tracks to improve: throughput,
  lead/cycle time, cost, composition, pipeline reliability.
- Stay current via a one-command regeneration; no live backend, no auth needed to
  *view*.
- Be fully self-contained: one HTML file that opens by double-click, works offline,
  and is commit-friendly.

## Non-Goals

- No live in-browser GitHub API calls (no client-side auth/CORS complexity).
- No new backend service, database table, or app route — this is a standalone
  artifact under `docs/`.
- Not a real-time dashboard; it is a point-in-time snapshot, regenerated on demand.
- The **Leaderboards / hall-of-fame** section was considered and deliberately
  left out of v1 scope (may return later as a closer).

## Decisions (locked during brainstorming)

| Decision | Choice |
|----------|--------|
| Audience / purpose | Showcase / portfolio — visual impact first |
| Freshness | Regenerable static snapshot (data baked at generation time) |
| Interactivity | Rich — hover tooltips, filters, toggles, sortable table |
| Visual direction | "Dark Factory" skin, exact palette from `docs/presentations/dark-factory.html` |
| Build architecture | **Two-stage**: JSON dump (`metrics.json`) + template renderer |
| Language | Python for both stages (matches backend; JSON boundary keeps it decoupled) |
| Charting | ECharts, **vendored inline** for offline self-containment |
| Sections | 6 (KPIs, Throughput, Speed, Cost, Composition, Pipeline Health) |

## Visual Language

Palette lifted verbatim from `docs/presentations/dark-factory.html`:

```
--bg:#0a0b0e;  --bg2:#0e1015;  --panel:#13151d;  --panel2:#181b24;
--line:rgba(255,255,255,.08);  --line2:rgba(255,255,255,.14);
--ink:#eceef3;  --mut:#9aa0ad;  --mut2:#6b7280;
--amber:#ff8a3d;  --amber-hot:#ff6a1a;  --amber-soft:#ffc08a;   /* primary */
--cyan:#3fe0c8;   --cyan-soft:#8af0e2;                          /* secondary */
--green:#54d18a;  --red:#ff6b6b;  --violet:#a78bfa;             /* data accents */
--mono: ui-monospace,"Cascadia Code","SF Mono",Menlo,Consolas,monospace;
--sans: system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
--grad: linear-gradient(135deg,var(--amber-hot),var(--amber-soft));
```

- Mono for labels/section headers; sans for body. Gradient amber on the title.
- KPI tiles on `--panel`, hairline `--line` borders, per-metric accent colors.
- Mission-control / readout feel; charts on dark panels with subtle gridlines.

## Architecture

Two stages with a clean, committable JSON contract between them. Both Python; the
JSON boundary means a future renderer in another language could swap in.

### Stage 1 — `fetch_metrics.py` (data layer; independently testable)

1. **Fetch issues** (all states):
   `gh issue list --repo omniscient/markethawk --state all --limit 500 --json number,title,state,createdAt,closedAt,labels,author`
2. **Fetch comments** per issue via `gh api` and locate the cost-report comment by
   its marker `<!-- dark-factory-cost-report -->`.
3. **Parse the cost report:**
   - Machine-readable marker `<!-- cumulative: cost=<float> in=<int> out=<int> -->`
     → **authoritative totals** (cost, tokens in/out).
   - Markdown body → **run count**, each run's **type** (`new` / `fix`) and
     **status** (`completed` / failed), and the **per-step table**
     (step, in-tokens, out-tokens, cost, duration).
4. **Cache** raw API responses under `.cache/` (gitignored) so iterative re-runs
   don't re-hit the API.
5. **Compute** every metric (below) and write **`metrics.json`** — clean,
   committable, point-in-time. This file is the contract for Stage 2.

### Stage 2 — `render_report.py` (presentation layer)

1. Read `metrics.json` + `template.html` + `vendor/echarts.min.js`.
2. Emit one **self-contained** `pipeline-report.html`: data baked in as a JSON
   blob, ECharts inlined. Opens offline, double-clickable.

### `generate.sh`

Runs Stage 1 then Stage 2 end-to-end.

## Data Definitions (judgment calls — stated explicitly)

- **Lead time** = `closedAt − createdAt`, for all closed issues.
- **Factory cycle time** = `closedAt − first-run-timestamp` (from the cost report),
  available for the subset with run data (~34 tickets as of 2026-06-04).
- **% autonomous** = (issues with a cost report) ÷ (total issues). Labeled
  precisely in the UI so it is not mistaken for a merge/success rate.
- Tickets **without** a cost report are excluded from cost/health charts and
  included in all others.
- Weekly buckets are computed in **UTC** (all GitHub timestamps are UTC).

## Metrics Catalog

Approx. 18–20 charts across six sections.

### ① Headline KPIs (hero band)
Tickets tracked · shipped · total AI spend · avg $/ticket · median lead time ·
% autonomous. Six accent-colored tiles.

### ② Throughput & flow
- Created vs. closed **per week** (grouped bars).
- **Cumulative** created vs. closed (lines) — the gap opening then closing.
- **Open backlog over time** (area) + net flow per week.
- Toggle: cumulative ↔ per-week.

### ③ Speed: lead & cycle time
- Lead-time **distribution** (histogram) with median + p85 markers.
- **Median lead time by week of closure** (line) — the "getting faster?" trend.
- Factory **cycle time** vs. lead time (subset with run data).
- **Aging WIP** — open issues bucketed by age (0–2d, 3–7d, 1–2w, 2w+).

### ④ AI cost analytics (~34 tickets)
- **Cumulative spend over time** (line) + per-ticket bars.
- Cost-per-ticket **distribution** (histogram).
- **Cost by step** (implement / conformance / validate / classify / parse-intent…)
  — ranked/stacked bars; implement dominates.
- **Cost vs. size** (S/M/L/XL) — does L actually cost more?
- **Tokens in vs. out** (totals).
- **Spend on rework** — cost from `fix` (retry) runs vs. first `new` runs.

### ⑤ Category / label composition
- By **category** (scanner, frontend, infra, security, performance, testing,
  observability, ml, docs, architecture-audit…).
- By **priority** (must/should-have), by **size**, by **timeframe**.
- **Dark-Factory vs. human-authored** split.
- Label **treemap** for overall mix.

### ⑥ Dark Factory pipeline health (run data)
- **Run success rate** (completed vs. failed).
- **Retry/rework rate** — tickets with >1 run; runs-per-ticket distribution.
- **Avg steps per run** + step-duration profile.
- **Honest caveat:** a detailed *failure-reason* breakdown is thin in current
  data. Show what is parseable (run status, retry counts) and **flag gaps**
  rather than invent categories.

## Interactivity (ECharts, all client-side, no server)

- **Hover tooltips** on every chart (exact values, ticket counts).
- **Sticky global filter bar:** filter by category, size, and date range — all
  charts re-render from the baked JSON; a "reset" chip.
- **Toggles** where they add insight: cumulative ↔ per-week (throughput),
  absolute ↔ per-ticket (cost).
- **Sortable / filterable ticket table** at the bottom: #, title, size, labels,
  lead time, cost, #runs, status. Sort by header, type to filter. The "show me
  the receipts" backing for all charts.
- Smooth section navigation (sticky rail or top tabs).

## File Layout

Mirrors the existing `docs/*.html` report convention.

```
docs/pipeline-report/
  fetch_metrics.py       # stage 1: gh → metrics.json
  render_report.py       # stage 2: metrics.json + template → html
  template.html          # dark-factory skin + chart scaffolding
  vendor/echarts.min.js  # vendored for offline self-containment
  metrics.json           # committed snapshot (point-in-time)
  pipeline-report.html   # committed output (the showcase artifact)
  generate.sh            # runs both stages
  test_fetch_metrics.py  # unit tests for parser + computations
  .cache/                # gitignored raw API responses
```

## Testing & Robustness

- **Stage 1 unit tests with real fixtures:** capture the actual #206 cost-report
  comment as a fixture; assert parsed totals/steps/run-type. Cover lead-time math,
  weekly bucketing, and cost-by-step aggregation.
- **Format-drift tolerance:** totals come from the `cumulative:` marker first;
  table parse only for breakdown. A malformed report is **skipped with a logged
  warning**, never crashes the run.
- **Stage 2 smoke test:** output HTML contains the expected chart containers and a
  parseable embedded JSON blob.
- **Idempotent:** re-running overwrites cleanly; `.cache/` keeps API calls cheap
  during iteration.

## Data Coverage (as of 2026-06-04)

- 112 issues total · 89 closed.
- 34 issues carry a Dark Factory cost-report comment (drives cost + health
  sections).
- 17 issues carry the "Dark Factory" label.
- Throughput / speed / composition draw on all 112; cost / health on the ~34.

## Open Questions / Future

- Leaderboards section (most expensive, fastest, biggest token burn) as a v2
  closer.
- Conformance-gate pass/fail detail once richer run logs are available.
- Optional: publish the HTML to GitHub Pages for a shareable link.
