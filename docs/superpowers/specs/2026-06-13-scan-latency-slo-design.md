# Pre-Market Scan Latency SLO — Metrics + Missed-Slot Alerts

**Date:** 2026-06-13
**Issue:** #391
**Status:** Spec (brainstorming complete) → ready for implementation plan

## Overview

Inside the 4:00–9:30 AM EST pre-market window, a slow or silently-stuck scan looks
identical to a healthy one until a human notices. `ScannerRun.execution_time_ms`
already records duration; nothing turns it into an alert. This issue adds three
Prometheus metrics (one already exists, two are new), three Grafana alert rules,
a `scan_failed_tickers_ratio` Gauge, two Grafana dashboard panels, and env-var
configurable SLO thresholds.

## Decisions made during brainstorming

1. **Metric naming: no prefix change.** The codebase already has `scan_duration_seconds`
   with `{scanner_type}` label used across all five scanner services. The issue's
   `markethawk_scan_duration_seconds` naming is illustrative, not a hard requirement.
   The existing `scan_duration_seconds` is kept as-is. New metrics follow the same
   convention without a `markethawk_` prefix.

2. **Missed-slot alert: time-since-last-success.** `pre_market_volume_spike` is
   API-triggered (not in the Celery beat schedule) and `ScannerConfig.run_frequency`
   stores coarse labels like `'evening'`, not cron expressions. Alert when
   `time() - scan_last_success_timestamp > SCAN_STALENESS_SLO_SECONDS` within the
   pre-market window (08:00–15:00 UTC, covering both EST and EDT for 04:00–09:30 ET).

3. **`scan_data_to_detection_seconds` is in scope.** It is the headline metric: the
   end-to-end latency a trader actually feels (freshest bar timestamp → ScannerEvent
   creation). Implementation does not require dataclass surgery — one post-scan
   `func.max()` query over `StockAggregate` for the tickers processed is sufficient.

4. **SLO configurability: env vars only for v1.** `SCAN_DURATION_SLO_SECONDS=120` and
   `SCAN_STALENESS_SLO_SECONDS=900` go into `Settings`. Grafana alert YAML hardcodes
   the defaults with a comment pointing back to the env vars. Promoting thresholds to
   `ScannerConfig` is deferred (requires migration, adds complexity, blocked for size:M).

5. **Grafana panels: extend existing `scanner-performance.json`.** The new panels
   (duration trend, last-success age, data-to-detection) belong alongside the existing
   scanner metrics, not in a new dashboard file.

6. **Alert location: Grafana-managed (not Prometheus rule_files).** The existing pattern
   in `grafana/provisioning/alerting/rules.yaml` is Grafana's native alerting engine.
   `monitoring/prometheus/prometheus.yml` has no `rule_files:` or `alerting:` block —
   this issue does NOT add them. All three new alert rules go into `rules.yaml`.

## §1 New Prometheus metrics

All three additions go in `backend/app/core/metrics.py`.

### 1a. `scan_last_success_timestamp{scanner_type}` (Gauge)

```python
scan_last_success_timestamp = Gauge(
    "scan_last_success_timestamp",
    "Unix timestamp of the last successful scan completion",
    ["scanner_type"],
)
```

Updated via `scan_last_success_timestamp.labels(scanner_type=...).set(time.time())`
at the end of each scanner service's entry-point function, after `_persist` returns
successfully. Apply to all scanner services: `pre_market_scan.py`,
`pocket_pivot.py`, `liquidity_hunt.py`, `trend_pullback_scan.py`,
`oversold_bounce_scan.py`.

### 1b. `scan_data_to_detection_seconds{scanner_type}` (Histogram)

```python
scan_data_to_detection_seconds = Histogram(
    "scan_data_to_detection_seconds",
    "Seconds between the freshest bar used and ScannerEvent creation time",
    ["scanner_type"],
    buckets=[30, 60, 120, 300, 600, 900, 1800, 3600],
)
```

**Implementation in `run_pre_market_scan()`** (after `_persist` returns, before
`scan_duration_seconds.observe`):

```python
# One query across all tickers to find the freshest bar consumed this scan
max_bar_ts = (
    db.query(func.max(StockAggregate.timestamp))
    .filter(
        StockAggregate.ticker.in_(tickers),
        StockAggregate.timespan == "minute",
        StockAggregate.is_pre_market == True,
        StockAggregate.timestamp >= day_start_utc,
        StockAggregate.timestamp < day_end_utc,
    )
    .scalar()
)
if max_bar_ts is not None:
    bar_utc = max_bar_ts if max_bar_ts.tzinfo else max_bar_ts.replace(tzinfo=timezone.utc)
    scan_data_to_detection_seconds.labels(
        scanner_type="pre_market_volume_spike"
    ).observe((utc_now().replace(tzinfo=timezone.utc) - bar_utc).total_seconds())
```

For other scanner services (evening scanners), the same pattern applies using
their respective bar-type queries; omit if the scanner does not consume
time-series bars (unlikely). Mark those as a follow-up if not trivially
reachable within scope.

### 1c. `scan_failed_tickers_ratio{scanner_type}` (Gauge)

```python
scan_failed_tickers_ratio = Gauge(
    "scan_failed_tickers_ratio",
    "Fraction of tickers that failed in the most recent scan run (0.0–1.0)",
    ["scanner_type"],
)
```

Updated at scan completion (before `db.close()`). In `pre_market_scan.py`:

```python
total = len(tickers)
scan_failed_tickers_ratio.labels(scanner_type="pre_market_volume_spike").set(
    len(failed) / total if total else 0.0
)
```

Apply the same pattern to the other scanner services.

## §2 Config and env vars

Add to `backend/app/core/config.py` `Settings`:

```python
SCAN_DURATION_SLO_SECONDS: int = 120
SCAN_STALENESS_SLO_SECONDS: int = 900
```

Document both in `ENV_VARIABLES.md` under a new **Scanner SLO** section:

| Variable | Default | Description |
|---|---|---|
| `SCAN_DURATION_SLO_SECONDS` | `120` | p95 scan duration threshold (seconds) above which the SLO-breach alert fires |
| `SCAN_STALENESS_SLO_SECONDS` | `900` | Seconds since last successful scan before the missed-slot alert fires (pre-market window only) |

The Grafana alert YAML hardcodes these defaults; a comment in each rule references
the env var name so operators know where to change the value.

## §3 Alert rules (`grafana/provisioning/alerting/rules.yaml`)

Add three rules to the existing `markethawk-infrastructure` group (existing pattern:
one Prometheus refId for the metric, one `-- Grafana --` refId for the math
threshold expression).

### Rule 1 — Missed-slot (pre-market scan not completing)

```yaml
- uid: scan-missed-slot-pre-market
  title: Pre-Market Scan Missed Slot
  condition: C
  for: 0m
  annotations:
    summary: >
      pre_market_volume_spike has not completed successfully for >15 min
      during the pre-market window (04:00–09:30 ET). Check Celery worker health.
  labels:
    severity: critical
  data:
    - refId: B
      relativeTimeRange:
        from: 60
        to: 0
      datasourceUid: prometheus
      model:
        # Staleness check — metric value is positive when scan is overdue.
        # SCAN_STALENESS_SLO_SECONDS default: 900
        expr: time() - scan_last_success_timestamp{scanner_type="pre_market_volume_spike"}
        refId: B
    - refId: C
      relativeTimeRange:
        from: 60
        to: 0
      datasourceUid: "-- Grafana --"
      model:
        type: math
        # Alert fires when scan is stale AND we're inside 08:00–15:00 UTC
        # (covers 04:00–09:30 ET in both EST and EDT).
        # Implementer note: hour() is not directly available in Grafana math
        # expressions; gate by restricting the alert's active time range in
        # the alert rule's "Evaluation behavior → Schedule" to weekdays 08–15 UTC,
        # or add a second Prometheus refId querying
        # `vector(1) and on() (hour() >= 8 and hour() < 15)` and multiply.
        expression: $B > 900
```

### Rule 2 — p95 duration SLO breach

```yaml
- uid: scan-duration-slo-breach
  title: Scanner p95 Duration Exceeds SLO
  condition: C
  for: 5m
  annotations:
    summary: >
      {{ $labels.scanner_type }} p95 scan duration exceeds the 120-second SLO.
      Tune threshold via SCAN_DURATION_SLO_SECONDS env var.
  labels:
    severity: warning
  data:
    - refId: B
      relativeTimeRange:
        from: 900
        to: 0
      datasourceUid: prometheus
      model:
        # SCAN_DURATION_SLO_SECONDS default: 120
        expr: >
          histogram_quantile(0.95,
            rate(scan_duration_seconds_bucket[15m])
          )
        refId: B
    - refId: C
      relativeTimeRange:
        from: 900
        to: 0
      datasourceUid: "-- Grafana --"
      model:
        type: math
        expression: $B > 120
```

### Rule 3 — Failed tickers ratio

```yaml
- uid: scan-high-failed-ticker-ratio
  title: Scanner High Failed-Ticker Ratio
  condition: C
  for: 0m
  annotations:
    summary: >
      {{ $labels.scanner_type }} had >10% failed tickers on the last run.
      Check provider connectivity (Polygon/IBKR) or universe health.
  labels:
    severity: warning
  data:
    - refId: B
      relativeTimeRange:
        from: 300
        to: 0
      datasourceUid: prometheus
      model:
        expr: scan_failed_tickers_ratio
        refId: B
    - refId: C
      relativeTimeRange:
        from: 300
        to: 0
      datasourceUid: "-- Grafana --"
      model:
        type: math
        expression: $B > 0.1
```

## §4 Grafana dashboard panels (`grafana/provisioning/dashboards/scanner-performance.json`)

Add three panels to the existing `scanner-performance.json` dashboard:

**Panel A — Scan duration trend (time series)**
- Query: `histogram_quantile(0.95, rate(scan_duration_seconds_bucket[5m]))` by
  `scanner_type`
- Add a threshold line at 120 (rendered in red) annotated "SLO (120s)"
- Legend: per-scanner p95 latency

**Panel B — Last-success age (stat / gauge viz)**
- Query: `time() - scan_last_success_timestamp` by `scanner_type`
- Color thresholds: green < 600s, yellow 600–900s, red > 900s

**Panel C — Data-to-detection p50 (stat)**
- Query: `histogram_quantile(0.50, rate(scan_data_to_detection_seconds_bucket[15m]))` by
  `scanner_type`
- Color threshold: green < 300s, yellow 300–600s, red > 600s
- Title: "Bar-to-Signal Latency (p50)"

## §5 Integration points

| File | Change |
|---|---|
| `backend/app/core/metrics.py` | Add `scan_last_success_timestamp`, `scan_data_to_detection_seconds`, `scan_failed_tickers_ratio` |
| `backend/app/core/config.py` | Add `SCAN_DURATION_SLO_SECONDS: int = 120` and `SCAN_STALENESS_SLO_SECONDS: int = 900` |
| `backend/app/services/pre_market_scan.py` | Observe all three new metrics at end of `run_pre_market_scan()` |
| `backend/app/services/pocket_pivot.py` | Update `scan_last_success_timestamp` and `scan_failed_tickers_ratio` |
| `backend/app/services/liquidity_hunt.py` | Same |
| `backend/app/services/trend_pullback_scan.py` | Same |
| `backend/app/services/oversold_bounce_scan.py` | Same |
| `grafana/provisioning/alerting/rules.yaml` | Add 3 alert rules |
| `grafana/provisioning/dashboards/scanner-performance.json` | Add 3 panels |
| `ENV_VARIABLES.md` | Document `SCAN_DURATION_SLO_SECONDS` and `SCAN_STALENESS_SLO_SECONDS` |

**No migration needed** — no new SQLAlchemy model fields.

**No `prometheus.yml` changes** — alerts use Grafana's native alerting engine
(same pattern as existing rules). `rule_files:` plumbing is not introduced.

## Alternatives considered

### A. Rename `scan_duration_seconds` → `markethawk_scan_duration_seconds`
Rejected. None of the 20+ existing metrics use a `markethawk_` prefix. The metric is
already wired in 5 scanner services and potentially referenced by Grafana panels.
Renaming for cosmetic alignment adds blast radius with no functional improvement.

### B. Derive missed-slot from `ScannerConfig.next_run`
Rejected. `compute_next_run()` in `scan_orchestrator.py` returns `None` for
`pre_market_volume_spike` (hardcoded to evening scanners only). `next_run` is never
updated for this scanner type. Time-since-last-success is the only viable approach.

### C. `ScannerConfig.slo_duration_seconds` field for per-config SLO
Rejected for v1. Requires Alembic migration + gauge-sync plumbing to expose the DB
value to Prometheus. Env vars satisfy the acceptance criterion ("documented in
ENV_VARIABLES.md"). Promote to `ScannerConfig` in a follow-up if operators need
runtime tuning per scanner type.

### D. PromQL recording rules for p95 (not Grafana alerts)
Rejected. The existing alerting infrastructure uses Grafana-managed alerts only.
`monitoring/prometheus/prometheus.yml` has no `rule_files:` block, and adding one
for a single issue introduces new operational scope. Grafana's `histogram_quantile`
in a query panel/alert is sufficient and matches the established pattern.

## Open questions (non-blocking)

1. **`scan_data_to_detection_seconds` for evening scanners.** The implementation for
   `pocket_pivot`, `liquidity_hunt`, `trend_pullback`, and `oversold_bounce` is not
   specified in detail. Those scanners consume daily bars; the "freshest bar" concept
   still applies but the latency would be hours, not minutes. Implementer judgment:
   add to all five services for completeness, or pre_market only for v1.

2. **DST correctness for missed-slot gate.** The PromQL `hour() >= 8 < 15` gate covers
   04:00–09:30 EST (UTC+0) but not EDT (UTC-4, which shifts pre-market to 08:00–13:30
   UTC). During EDT (March–November) the current gate (08:00–15:00 UTC) is a superset
   — the alert window is slightly larger than needed, not smaller. This is safe (no
   missed alerts; potential extra window) and acceptable for v1.

3. **Celery multiprocess and Gauge semantics.** `scan_last_success_timestamp` and
   `scan_failed_tickers_ratio` are Gauges. In Prometheus multiprocess mode
   (`PROMETHEUS_MULTIPROC_DIR` set), Gauges are aggregated across processes using
   the `all` mode (sum) by default — but the last-write-wins semantic is needed here.
   Use `Gauge(..., multiprocess_mode='livemax')` to ensure the most recent write
   survives process boundaries. See the existing `ibkr_connection_status` Gauge for
   reference if it already sets this mode.

## Assumptions

- `scan_last_success_timestamp` emitting `time.time()` at service-function exit is
  sufficient freshness granularity (within seconds of actual completion).
- The existing `scan_duration_seconds` buckets `[0.5, 1, 2, 5, 10, 30, 60, 120, 300]`
  include 120 as a breakpoint, making `histogram_quantile(0.95, ...)` accurate at the
  proposed 120s SLO boundary. No bucket changes required.
- `grafana/provisioning/alerting/rules.yaml` hot-reloads on Grafana restart without
  manual import; this is already true for the existing rules.
- The failing acceptance criterion "Killing the Celery worker mid-window fires the
  missed-slot alert" is satisfied by the `scan_last_success_timestamp` approach: once
  the Celery worker is killed, the gauge stops advancing, and after `SCAN_STALENESS_SLO_SECONDS`
  elapses within the gate window, the alert fires.

## Out of scope

- Prometheus recording rules / `rule_files` infrastructure in `prometheus.yml`
- Per-config SLO thresholds via `ScannerConfig` model field (requires migration)
- Backtest or historical latency replay against past `ScannerRun` records
- Alertmanager configuration changes (routing already set in `notification-policies.yaml`)
- Frontend UI for SLO thresholds or latency visualization (Grafana is the display layer)
