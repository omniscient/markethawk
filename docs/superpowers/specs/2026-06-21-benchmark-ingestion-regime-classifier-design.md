# Replay Engine — Benchmark Ingestion + Regime Classifier

**Status:** design  
**Date:** 2026-06-21  
**Issue:** #486 (sub-issue 3 of the Canonical Signal Replay Engine epic)  
**Depends on:** none — parallel with sub-issues 1 (replay run model) and 2 (trade simulation)  
**Consumed by:** sub-issue 4 (wiring regimes into the run pipeline), sub-issue 6 (regime UI)

---

## Problem

The replay engine needs market-regime context to annotate `replay_trade` records and power
regime-sliced analytics. Two primitives are missing:

1. A reliable way to ingest a configurable benchmark symbol's daily bars into `StockAggregate`
   without re-fetching data that is already stored.
2. A deterministic, rule-based classifier that labels each trading day with a two-axis
   `(trend, vol)` regime tuple — independent of the HMM-based `RegimeService` that annotates
   live scanner events.

---

## Requirements

Distilled from issue #486 acceptance criteria and Q&A:

- **R1** — Ingesting SPY for a date range populates `stock_aggregates` with daily bars;
  re-running the same call ingests zero additional rows.
- **R2** — Gap-fill semantics: only the _missing_ days within the requested range are fetched
  from Polygon. Interior gaps are detected, not just a trailing tail.
- **R3** — Swapping `benchmark_symbol` from SPY to QQQ (or any other symbol) requires no code
  change — symbol is a parameter, not a constant.
- **R4** — A failed or missing benchmark ingestion surfaces a clear exception; it does not
  silently return empty data.
- **R5** — The classifier produces deterministic labels for the same historical bars on every
  run (no ML model, no retrained state).
- **R6** — Unit tests cover: bull/bear SMA200 boundary, each vol bucket boundary, and
  duplicate-ingestion returning zero new rows.
- **R7** — Vol thresholds have documented defaults and are overridable via a dict passed to
  the classifier at construction time; the classifier validates the dict and raises on malformed
  input.
- **R8** — A standalone, trade-model-agnostic lookup helper returns the `(trend, vol)` regime
  for an arbitrary date; non-trading days and out-of-range dates carry-forward the last known
  trading day's regime.

---

## Architecture

### Module layout

```
backend/app/services/replay/
    __init__.py           # re-exports BenchmarkIngestor, RegimeClassifier, get_benchmark_regime
    benchmark.py          # BenchmarkIngestor
    classifier.py         # ReplayRegime, RegimeClassifier, get_benchmark_regime
```

The `replay/` sub-package is the home for all future replay engine services. This issue creates
its skeleton; sub-issues 1, 2, and 4 add their own modules alongside.

---

### `BenchmarkIngestor` (`services/replay/benchmark.py`)

```python
class BenchmarkIngestor:
    def __init__(self, provider: MassiveDataProvider):
        self._provider = provider

    def ingest(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        db: Session,
    ) -> int:
        """
        Ensures daily bars for `symbol` over [start_date, end_date] exist in
        stock_aggregates. Returns the count of newly inserted rows.
        Raises BenchmarkIngestionError on provider failure.
        """
```

**Gap-fill algorithm** (idempotent, interior-hole-aware):

1. Query `stock_aggregates` for all timestamps already stored for
   `(ticker=symbol, timespan="day", multiplier=1)` in `[start_date, end_date]`.
2. Build `existing_ts: set[datetime]` from the query result.
3. Compute `expected_trading_days` for the requested range using a local trading-calendar
   helper (filter weekends; US market holidays are an approximation — Polygon simply returns
   no bar for holidays, so the dedup handles them naturally).
4. If `existing_ts` covers all expected days → return 0 immediately (no Polygon call).
5. Otherwise, compute `missing = expected_trading_days - existing_ts`. Fetch the span
   `[min(missing), max(missing)]` in a single Polygon call via `MassiveDataProvider.get_bars()`
   with `timespan="day"`, `multiplier=1`.
6. Insert only rows whose timestamp is not in `existing_ts` (dedup before `db.bulk_save_objects`).
7. Commit; return inserted count.

**Error contract:**  
On any `ProviderError` or network failure, raise `BenchmarkIngestionError(symbol, start_date,
end_date, cause=...)`. Do not return empty. Sub-issue 4's run-failure path catches this
exception.

**`StockAggregate` fields for benchmark bars:**

| Field          | Value                                       |
|----------------|---------------------------------------------|
| `ticker`       | symbol (e.g. "SPY")                         |
| `timestamp`    | bar open date as naive UTC datetime at 00:00|
| `multiplier`   | 1                                           |
| `timespan`     | "day"                                       |
| OHLCV, vwap, transactions | from Polygon response              |
| `is_pre_market`| False                                       |
| `is_after_market` | False                                    |
| `provider`     | "polygon"                                   |

No migration needed — benchmark bars reuse the existing `stock_aggregates` table and schema.

---

### `RegimeClassifier` (`services/replay/classifier.py`)

Not to be confused with `RegimeService` (`services/regime_service.py`), which is an HMM-based
system for annotating live scanner events and is nondeterministic (rolling retrain). This
classifier is rule-based, stateless, and deterministic.

```python
@dataclass(frozen=True)
class ReplayRegime:
    trend: str   # "bull" | "bear" | "unknown"
    vol: str     # "calm" | "normal" | "turbulent"

class RegimeClassifier:
    DEFAULT_VOL_THRESHOLDS = {
        "calm_below": 0.10,       # annualized realized vol < 10% → calm
        "turbulent_above": 0.20,  # annualized realized vol > 20% → turbulent
    }

    def __init__(
        self,
        symbol: str,
        vol_thresholds: dict | None = None,
    ):
        self._symbol = symbol
        self._thresholds = self._validate_thresholds(vol_thresholds or self.DEFAULT_VOL_THRESHOLDS)
        self._regime_map: dict[date, ReplayRegime] = {}

    def classify(self, start_date: date, end_date: date, db: Session) -> None:
        """
        Loads all daily bars for `symbol` from stock_aggregates (full available history),
        computes per-day (trend, vol) labels, and populates self._regime_map for
        [start_date, end_date]. Call this once; then use get_benchmark_regime() for lookups.
        """

    def _validate_thresholds(self, t: dict) -> dict:
        """
        Raises ValueError if calm_below >= turbulent_above, either is non-positive,
        or expected keys are missing.
        """
```

**`trend` label (SMA200):**

- `trend = "bull"` if `close > mean(close[-200:])` (trailing 200 trading days)
- `trend = "bear"` if `close ≤ mean(close[-200:])`
- `trend = "unknown"` if fewer than 200 prior trading days are available for that date

The classifier loads _all_ bars for the symbol from `stock_aggregates` (not just the requested
range) to maximize the warm-up window. For early dates where fewer than 200 prior bars exist in
the table, trend is `"unknown"`. Spec assumes `BenchmarkIngestor` was called with adequate
history (at least 200 trading days before the desired start); this is documented as a caller
responsibility — `classify()` does not auto-ingest.

**`vol` label (annualized realized vol):**

Realized vol = standard deviation of daily log-returns over the trailing 20 trading days,
annualized by `× √252`. This is consistent with `RegimeService._build_feature_matrix()`'s
`rolling_vol_20d` feature, avoiding divergence in how vol is computed across the codebase.

| Condition                          | Label         |
|------------------------------------|---------------|
| `realized_vol < calm_below`        | "calm"        |
| `calm_below ≤ realized_vol ≤ turbulent_above` | "normal" |
| `realized_vol > turbulent_above`   | "turbulent"   |

A minimum of 20 prior trading days is required for the vol calculation. Dates with < 20 prior
bars get `vol = "normal"` (the safe middle bucket) rather than erroring — this is
only a warm-up edge case for very early requested dates and does not affect most replay runs.

---

### `get_benchmark_regime` helper

```python
def get_benchmark_regime(
    classifier: RegimeClassifier,
    lookup_date: date,
) -> ReplayRegime:
    """
    Pure dict lookup into classifier._regime_map.
    - Exact match: returns the stored ReplayRegime.
    - Non-trading day or weekend: carries forward the last available trading day.
    - Date before first available entry: returns ReplayRegime("unknown", "normal").
    - Date after last available entry: carries forward the last entry.
    """
```

This function is trade-model-agnostic; sub-issue 4 imports it directly to tag `replay_trade`
rows without knowing `ReplayRegime`'s internal shape in advance.

---

### `BenchmarkIngestionError`

```python
class BenchmarkIngestionError(Exception):
    def __init__(self, symbol: str, start: date, end: date, cause: Exception):
        super().__init__(f"Benchmark ingestion failed for {symbol} [{start}, {end}]: {cause}")
        self.symbol = symbol
        self.cause = cause
```

Placed in `services/replay/benchmark.py`; re-exported from `__init__.py`.

---

## Alternatives Considered

### A1 — Delete-and-reinsert (like `sync_stock_aggregates`)

`sync_stock_aggregates` deletes rows for a ticker+date range then bulk-inserts from Polygon.
This achieves idempotency but re-fetches years of daily bars on every call. Rejected because
(a) the issue explicitly requires "only fetch the gap," and (b) benchmark tickers accumulate
deep history for SMA200 warm-up — re-pulling that history on every replay run wastes Polygon
quota unnecessarily.

### A2 — Extend `RegimeService` with SMA200+vol-bucket logic

Co-locating rule-based and HMM logic in `regime_service.py` would couple replay's lifecycle to
the live scanner's model retraining cadence and import its DB/Redis dependencies. Rejected: the
HMM labels are nondeterministic (the regime assigned to a historical date can change after a
scheduled retrain) — incompatible with the replay engine's reproducibility requirement.

### A3 — `RegimeClassifier.get_regime_for_date()` method instead of standalone helper

A bare method on the classifier ties the import path of sub-issue 4's trade-tagging code to the
classifier class. A named, importable function (`get_benchmark_regime`) is easier to mock in
tests and decouples sub-issue 4 from classifier internals. The function also enforces the
carry-forward policy in a single, testable place.

---

## Assumptions

- **[ASSUMED]** `BenchmarkIngestor` is called with at least 200 trading days of history before
  the desired classification start. If not, early dates get `trend="unknown"` (not an error).
  Sub-issue 4 is responsible for ensuring adequate history is ingested before calling classify.

- **[ASSUMED]** US market holiday exclusion is approximated by Polygon's own response set
  (no bar returned for holidays); the ingestor does not need an explicit trading-calendar
  library. If a future issue requires exact holiday awareness, a lightweight library (e.g.
  `pandas_market_calendars`) can be added then.

- **[ASSUMED]** `timespan="day"` bars from Polygon represent the full session open (not
  pre/post-market). Both `is_pre_market` and `is_after_market` are set to `False`.

- **[ASSUMED]** The `replay_trade` model (sub-issues 1/2) will expose `entry_date: date`
  and `benchmark_symbol: str` fields. `get_benchmark_regime` is designed to accept those
  primitives directly.

---

## Open Questions (non-blocking)

- **OQ1** — Should `RegimeClassifier.classify()` accept an optional `lookback_days: int`
  parameter to limit how far back it loads bars from `stock_aggregates`? Currently loads all
  available history to maximize SMA200 warm-up. For very long-lived benchmark symbols this
  could be large, but daily bars are compact (~100 bytes/row) and 10 years × 252 rows is
  ~2500 rows — unlikely to be a performance concern.

- **OQ2** — Vol thresholds of 10%/20% (annualized realized vol) are reasonable defaults for
  SPY/QQQ. If sector ETFs (e.g. XBI, ARKK) are used as benchmarks, they may require higher
  turbulent thresholds. This is handled by the override dict; no change needed here.

- **OQ3** — Should `get_benchmark_regime` log a warning when carry-forward activates (i.e.
  a non-trading day or out-of-range date is requested)? Keep it silent for now; sub-issue 4
  can add telemetry if noisy.
