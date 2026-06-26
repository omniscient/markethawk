# Data Quality Trust Gate Design

**Date:** 2026-06-13
**Status:** Approved for implementation planning

## Product Goal

MarketHawk should treat data quality as part of risk management, not as an optional maintenance report. Before a scanner result, backtest result, automated action, or performance claim is trusted, the product should make the relevant data risks visible and, in strict contexts, block the result.

The guiding stance matches serious trading-system documentation: market data and model output can be wrong, incomplete, stale, biased, or misaligned with the trading session. MarketHawk should be explicit about those limits in-product.

## Existing Project Fit

The design builds on the existing data-quality feature instead of creating a parallel subsystem:

- `DataQualityService` already analyzes universe OHLCV coverage, integrity, continuity, gaps, duplicates, bad bars, and grades.
- `UniverseQualityReport` already persists the latest universe report and normalization status.
- The quality modal already exposes report details and normalization actions to users.
- `DataReadinessService` already checks scanner `data_requirements` for required lookback coverage.
- `ScannerConfig.data_requirements` already describes timespan, multiplier, and lookback needs.
- `ScannerRun.failed_tickers`, scanner run metadata, and `ScannerEvent.metadata_` already provide JSONB-friendly places to record per-run or per-event caveats.
- Future backtesting can reuse the same gate contract before writing trusted backtest results.

## Recommended Architecture

Add a backend `DataQualityGateService` that converts existing quality/readiness data into a reusable trust verdict.

The quality report remains the historical audit artifact. The new gate is the runtime decision contract used by other subsystems.

```text
UniverseQualityReport + scanner/backtest requirements + market/session/provider facts
    -> DataQualityGateService.assess(...)
    -> QualityGateAssessment
    -> scanner/backtest/auto-trading/UI behavior
```

Consumers should not parse `UniverseQualityReport.report_data` directly. They should call the gate and receive a stable assessment envelope.

## Gate Policies

`strict`

- Blocks trusted output when required checks fail.
- Used by backtesting, automated trading, persisted performance claims, and any future system that presents results as reliable.
- A blocked assessment prevents trusted result persistence and records the blocking issues.

`advisory`

- Allows exploratory workflows to run.
- Attaches warnings to scanner runs, scanner events, or API responses.
- Used by scanner UI, stock detail exploration, and research views where users may still want to inspect imperfect data.

`off`

- Allows explicit developer/admin bypasses only.
- Still records that quality gating was skipped.
- Not available as the default for product workflows.

## Assessment Contract

Add a versioned assessment shape:

```json
{
  "schema_version": "quality_gate.v1",
  "policy": "strict",
  "verdict": "blocked",
  "trusted": false,
  "scope": {
    "universe_id": 1,
    "scanner_type": "trend_pullback",
    "ticker": "AAPL",
    "start_date": "2026-01-01",
    "end_date": "2026-06-12",
    "timespans": [
      {"timespan": "day", "multiplier": 1, "lookback_days": 300}
    ]
  },
  "score": 72.4,
  "grade": "C",
  "issues": [
    {
      "code": "missing_bars",
      "severity": "blocker",
      "message": "Daily data has 18 missing bars in the requested lookback window.",
      "ticker": "AAPL",
      "timespan": "day",
      "multiplier": 1,
      "observed": 282,
      "required": 300,
      "affected_inputs": ["sma200", "atr14", "pullback_depth_pct"],
      "action": "Run aggregate sync or normalization before trusting this result."
    }
  ],
  "warnings": [],
  "generated_at": "2026-06-13T18:30:00Z"
}
```

Verdicts:

- `trusted`: no blocker issues; warnings may still exist.
- `warning`: advisory mode allowed the result, but warnings must be displayed or persisted.
- `blocked`: strict mode found one or more blocker issues.
- `skipped`: policy was `off`; result must not be presented as quality-gated.

## Required Issue Codes

The gate should emit these stable issue codes so UI, backtesting, alerts, and future agents can rely on them:

- `missing_bars`: required OHLCV bars are absent for the requested scope.
- `split_dividend_anomaly`: split or dividend adjustment risk may distort prices, volume, or returns.
- `stale_quote_risk`: the latest quote/bar is older than acceptable for the requested market context.
- `provider_gap`: a provider returned no data, partial data, errors, rate-limit gaps, or inconsistent coverage.
- `timezone_session_mismatch`: timestamps do not align with the expected exchange session or MarketHawk session classification.
- `survivorship_bias_warning`: universe membership may exclude delisted or inactive symbols for historical analysis.
- `insufficient_lookback`: a scanner/backtest requested indicators that require more bars than are available.

Each issue has:

- `severity`: `info`, `warning`, or `blocker`.
- `code`: stable machine-readable code.
- `message`: human-readable product copy.
- `ticker`: optional ticker or symbol.
- `asset_class`: optional asset class.
- `timespan` and `multiplier`: optional data grain.
- `observed` and `required`: optional numeric evidence.
- `affected_inputs`: indicators, features, or calculations affected by the issue.
- `action`: recommended user/system remediation.

## Scoring Rules

The initial implementation should be conservative and easy to reason about:

- Reuse the existing `DataQualityService` score and grade as the base historical-data score.
- Treat any existing ticker/timespan grade of `D` or `F` as a blocker in `strict` mode for the affected ticker and timespan.
- Treat coverage below 95% as a blocker when the requested result depends on exact historical windows.
- Treat missing required lookback as a blocker in `strict` mode and a warning in `advisory` mode.
- Treat survivorship bias as a warning by default unless the result is a backtest/performance claim, where it becomes a blocker unless explicitly marked as a non-survivorship-safe exploratory run.
- Treat stale quote and provider gaps as blockers only when the consumer requires live or current data; otherwise they are warnings.
- Treat timezone/session mismatch as a blocker when the scanner or strategy is session-specific.

These thresholds should live in a small policy module or config object, not scattered across consumers.

## Data Flow

### Universe Quality Analysis

`DataQualityService.analyze_universe()` continues to generate `UniverseQualityReport.report_data`.

Enhance report data where needed so it can support the required issue codes:

- Add split/dividend anomaly evidence when split rows or adjustment markers conflict with large discontinuities.
- Add provider/source coverage markers when sync tasks can identify failed or partial provider fetches.
- Add timezone/session checks for intraday bars against expected exchange sessions.
- Add stale-tail evidence based on latest available bar versus expected current session/date.

### Gate Assessment

`DataQualityGateService.assess()` accepts a scope:

- `universe_id`
- optional `ticker`
- optional `scanner_type`
- optional `strategy_id` or future `backtest_config_id`
- `start_date` and `end_date`
- required timespans, multipliers, and lookback windows
- `policy`
- optional consumer name such as `scanner`, `range_scan`, `backtest`, or `auto_trade`

It loads the latest completed `UniverseQualityReport`, scanner `data_requirements`, aggregate coverage, and available market/session/provider metadata. It returns `QualityGateAssessment`.

If no completed quality report exists, strict consumers receive `blocked` with `provider_gap` or `missing_quality_report`; advisory consumers receive a warning and a prompt to run analysis. `missing_quality_report` is an internal support code that can be shown in UI even though it is not one of the seven primary product risks.

## Consumer Behavior

### Backtesting

Backtesting uses `strict` by default.

Before running or persisting a backtest, the backtesting facility calls the gate for the universe, date range, symbols, and required bars. If the gate returns `blocked`, the backtest does not write a trusted result. The UI shows the blocker list and remediation actions.

Backtesting may support an explicit exploratory mode. Exploratory mode can run with warnings, but output must be labeled as not trusted and excluded from scorecards/performance summaries.

### Scanner Runs

Interactive scanner runs use `advisory` by default.

The scanner run stores the aggregate assessment on `ScannerRun` metadata or a new JSONB field when added. Individual scanner events should include relevant quality warnings in `ScannerEvent.metadata_` so downstream alerting, review, and scorecard workflows can inspect them.

Scheduled scanners may use `strict` when their output triggers automated trading or trusted scorecard updates. Otherwise they use `advisory` and persist warnings.

### Automated Trading

Automated trading uses `strict` before order creation.

If a scanner event has a blocker or skipped gate status, auto-trading refuses to create an order and records the reason.

### Scorecard And EdgeExplorer

Scorecard and EdgeExplorer should filter or label data by gate status:

- trusted events can contribute to default performance metrics.
- warning events can be included only when a user opts into degraded data.
- blocked or skipped events are excluded from trusted performance calculations.

### Quality Modal

The existing quality modal remains the audit and remediation surface.

It should add a trust-gate-oriented section that summarizes:

- current gate status by issue type,
- blocker count,
- warning count,
- most affected tickers,
- remediation actions such as sync aggregates, normalize, refresh splits/dividends, or rerun quality analysis.

## API Surface

Add a backend endpoint for product surfaces that need an explicit preflight:

```text
POST /api/v1/data-quality/gate
```

Request:

```json
{
  "universe_id": 1,
  "policy": "strict",
  "consumer": "backtest",
  "scanner_type": "trend_pullback",
  "ticker": null,
  "start_date": "2026-01-01",
  "end_date": "2026-06-12",
  "requirements": {
    "timespans": [
      {"timespan": "day", "multiplier": 1, "lookback_days": 300}
    ]
  }
}
```

Response is `QualityGateAssessment`.

Internal services may call `DataQualityGateService.assess()` directly rather than going through HTTP.

## Persistence

Initial persistence can use existing JSONB fields to keep the rollout small:

- Store run-level assessments in `ScannerRun.failed_tickers` only for per-ticker failures during the first slice, or add a dedicated `quality_gate` JSONB column when implementation begins if the plan determines that read paths need it.
- Store event-level warnings in `ScannerEvent.metadata_["quality_gate"]`.
- Future backtesting tables should include a `quality_gate` JSONB column from the start.

The implementation plan should decide whether to add `scanner_runs.quality_gate` immediately. If scanner run status pages need to show the assessment without scanning events, adding the column is the cleaner path.

## UI Direction

The product copy should be blunt and practical:

- "Not trusted" for blocked results.
- "Data warnings" for advisory results.
- "Quality gate skipped" for bypassed checks.

Avoid implying that a clean gate guarantees profitability or correctness. The gate only says the input data passed MarketHawk's current quality checks.

Scanner and backtesting surfaces should show:

- overall gate verdict,
- blocker/warning badges,
- issue list grouped by code,
- affected symbols and inputs,
- remediation action.

## Testing Strategy

Backend tests:

- Unit-test `DataQualityGateService` for each issue code.
- Unit-test policy behavior for `strict`, `advisory`, and `off`.
- Unit-test scanner data requirement integration using `ScannerConfig.data_requirements`.
- Unit-test missing quality report behavior.
- Add service tests proving blocked strict assessments prevent trusted persistence in the first consumer slice.

Frontend tests:

- Test rendering for trusted, warning, blocked, and skipped states.
- Test issue grouping and remediation copy.
- Test that backtesting or scanner preflight surfaces do not hide blockers.

Regression tests:

- Existing `DataQualityService` tests continue to pass.
- Existing quality modal tests continue to pass after API type expansion.
- Existing scanner runs continue to work in advisory mode when data warnings exist.

## Rollout Plan

1. Define `QualityGateAssessment` schemas and pure policy helpers.
2. Implement `DataQualityGateService.assess()` using existing quality reports and data requirements.
3. Add the preflight API endpoint.
4. Wire scanner runs in advisory mode and persist warnings.
5. Update the quality modal and scanner UI to show gate status.
6. Wire the first strict consumer. If backtesting is not yet present, use auto-trading or a test-only trusted-persistence guard as the first strict integration.
7. Require future backtesting to call the gate before trusted result persistence.
8. Expand report evidence for split/dividend anomalies, provider gaps, stale quote risk, timezone/session mismatch, and survivorship-bias warnings.

## Acceptance Criteria

- Other subsystems can call one service to determine whether market data is trusted, warning-only, blocked, or skipped.
- The seven requested risks are represented as stable issue codes.
- Strict consumers block trusted results when blocker issues are present.
- Advisory consumers show and persist warnings without silently treating results as clean.
- Existing universe data-quality analysis and normalization remain the source of historical data evidence.
- Backtesting has a clear contract to reuse before writing trusted results.
- Product UI makes data and risk quality visible without implying guarantees.

## Survivorship bias (#501)

Slice 10 activates the `survivorship_bias` issue code in `QualityGateService`.

**What the current metadata can prove:** nothing about survivorship. MarketHawk has **no delisted-symbol tracking today** — neither `StockUniverse` nor `StockUniverseTicker` carries a `delisted_date` or `survivorship_safe` field. A universe is assembled "as of today", so it silently excludes any symbol that was delisted before the run. We therefore **cannot prove** that any universe is survivorship-safe.

**Decision (made for this slice):** treat every *historical-analysis* scope as potentially survivorship-biased by default. Historical-analysis scopes are defined as `request.consumer in {"backtesting", "scorecard"}`. Live / forward consumers (`scanner`, `auto_trading`, `ui`) are exempt and never receive a `survivorship_bias` issue, because forward scanning does not depend on a survivorship-complete history.

**Policy is the trusted-vs-exploratory toggle.** No new request field is added; the existing `policy` already expresses the caller's risk appetite:

| policy | historical scope | issue severity | verdict | trusted |
|---|---|---|---|---|
| `strict` | yes | `blocker` | `blocked` | `False` (a trusted backtest/scorecard refuses unprovable data) |
| `advisory` | yes | `warning` | `warning` | `False` (exploratory: proceeds, but visibly not-trusted) |
| `off` | yes | — | `skipped` | `False` (existing off short-circuit) |
| any | no (live) | — | unaffected | unaffected |

Severity is emitted per-policy (`blocker` under strict, `warning` under advisory) so the advisory case surfaces the concern in the assessment's `warnings` list while still proceeding — matching the existing `missing_bars` / stale-report / partial `provider_gap` convention. The verdict downgrade is also applied independently by `_derive_verdict`, so the verdict/trusted columns above hold regardless.

**Implementation note:** the signal is a derived boolean (`survivorship_scope`) computed in `QualityGateService.assess()` from `request.consumer` and threaded into the pure `_build_assessment()` — no DB query, no migration, no new field — mirroring how `market_holidays` is sourced (#499).

**Future unblock path:** add delisted-symbol tracking (e.g. a `StockUniverseTicker.delisted_date` column plus a universe-level `survivorship_safe` marker populated when a universe is reconstructed point-in-time). `assess()` can then pass `survivorship_scope=False` for universes proven survivorship-safe, suppressing the issue for those universes while it keeps firing for everything that remains unprovable.
