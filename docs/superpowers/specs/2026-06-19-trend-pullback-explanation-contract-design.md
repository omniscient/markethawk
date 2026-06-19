# Trend Pullback Scanner — Explanation Contract Migration Design

**Date:** 2026-06-19
**Issue:** #461
**Parent epic:** #448 (Explainability Foundation)
**Blocked by:** #455 (pre-market reference scanner), #458 (backfill infrastructure)
**Status:** Spec generated

---

## Overview

Issue #461 migrates `trend_pullback_scan.py` to emit a `scanner_explanation.v1` payload for every new event it persists, and registers a reconstruction callable with the generic backfill service from #458 so historical trend_pullback rows can also receive explanations.

The trend_pullback scanner already exists and produces fully-populated `indicators` and `criteria_met` dicts. This migration wires those values into the explanation contract delivered by the blocking issues, without altering any scanner logic.

---

## Requirements

1. Every new trend_pullback `ScannerEvent` persists a `scanner_explanation.v1` payload in the `explanation` JSONB column (added by the early #448 sub-issues).
2. The explanation covers all 6 scanner criteria using stable criterion IDs — these IDs must never change without a schema version bump.
3. ATR(14) surfaces as a structured volatility-context entry in the explanation, with a scanner-specific `data_quality_warning` added when ATR is elevated (elevated-volatility caution).
4. HMM regime is NOT embedded in the `explanation` envelope — it already lives on `ScannerEvent.regime` and is deferred to Epic 2 for analytical use.
5. `confidence_inputs` is populated from the signal ranker's score decomposition; ATR is not hand-injected as a confidence weight.
6. Historical trend_pullback rows can be backfilled by registering a scanner-specific `_build_explanation_from_stored_event` callable with the backfill service from #458.
7. The backfill callable must honour #458's idempotency and `evidence.reconstructed=true` guarantees.
8. Tests verify: all 6 criterion IDs are stable string constants, and `why` bullets are generated correctly for representative indicator values.

---

## Architecture

### Criterion IDs

All 6 criterion IDs mirror the existing `criteria_met` dict keys under the `trend_pullback.` namespace. These are stable string constants, never derived programmatically from the key names:

| Criterion ID | Scanner key | Signal |
|---|---|---|
| `trend_pullback.uptrend` | `uptrend` | close > SMA50 > SMA200, SMA50 rising 20 sessions |
| `trend_pullback.near_high` | `near_high` | within 15% of 252-day high |
| `trend_pullback.pullback_in_progress` | `pullback_in_progress` | low tagged SMA20 after ≥5 consecutive closes above it |
| `trend_pullback.orderly_pullback` | `orderly_pullback` | depth 3–12% from 20-day swing high; no close below SMA50 |
| `trend_pullback.rsi_reset` | `rsi_reset` | RSI(5) < 40 |
| `trend_pullback.liquidity` | `liquidity` | 20-day avg dollar volume ≥ $5M and close ≥ $5 |

There is no pass/fail `criterion ID` for ATR(14) — it is a volatility-context entry, not a gate criterion.

### `_build_explanation()` function

Add a pure function in `trend_pullback_scan.py`:

```python
def _build_explanation(
    indicators: dict[str, Any],
    criteria_met: dict[str, bool],
    cfg: dict[str, Any],
    signal_quality_score: float | None,
    generated_at: str,   # ISO-8601 UTC from caller
) -> dict[str, Any]:
    ...
```

This function:
- Has no DB access; takes only computed values and config.
- Returns a complete `scanner_explanation.v1` dict.
- Is independently importable and testable without a scanner run.

#### `criteria_passed` / `criteria_failed` shape (one entry per criterion):

Each entry follows the v1 schema shape: `{label, observed, threshold, operator, unit, source, lookback}`.

| Criterion ID | label | observed | threshold | operator | unit | source | lookback |
|---|---|---|---|---|---|---|---|
| `trend_pullback.uptrend` | "Established uptrend" | `{"close": indicators["close"], "sma50": indicators["sma50"], "sma200": indicators["sma200"], "sma50_rising": sma50_rising_implied}` | N/A (compound) | "compound" | "price" | "stock_aggregates.day" | "200d + 20d" |
| `trend_pullback.near_high` | "Near 252-day high" | `indicators["pct_off_252d_high"]` | `cfg["max_pct_off_high"]` | "<=" | "%" | "stock_aggregates.day" | "252d" |
| `trend_pullback.pullback_in_progress` | "Pullback to SMA20" | `{"consecutive_above": indicators["consecutive_days_above_sma20"]}` | `cfg["min_days_above_sma"]` | ">=" | "sessions" | "stock_aggregates.day" | "20d+prior 60d" |
| `trend_pullback.orderly_pullback` | "Orderly pullback depth" | `indicators["pullback_depth_pct"]` | `{"min": cfg["pullback_min_pct"], "max": cfg["pullback_max_pct"]}` | "between" | "%" | "stock_aggregates.day" | "20d swing" |
| `trend_pullback.rsi_reset` | "RSI(5) reset" | `indicators["rsi5"]` | `cfg["rsi_max"]` | "<" | "index" | "stock_aggregates.day" | "5d EWM" |
| `trend_pullback.liquidity` | "Liquidity floor" | `{"avg_dollar_vol_20d": indicators["avg_dollar_vol_20d"], "close": indicators["close"]}` | `{"min_dollar_vol": cfg["min_dollar_vol"], "min_price": cfg["min_price"]}` | ">=" | "USD" | "stock_aggregates.day" | "20d avg" |

Non-firing criteria (criteria that returned `False`) go into `criteria_failed` with the same structure.

#### ATR(14) volatility-context entry

Added under `criteria_passed` with criterion ID `trend_pullback.volatility_context`:

```json
{
  "label": "Volatility context (ATR14)",
  "observed": "<atr14_pct_of_close>",
  "threshold": null,
  "operator": "info",
  "unit": "% of close",
  "source": "stock_aggregates.day",
  "lookback": "14d EWM"
}
```

`atr14_pct_of_close = round(indicators["atr14"] / indicators["close"] * 100, 2)`.

This entry is always included (never failed) because ATR(14) has no pass/fail gate; it is informational.

#### Elevated-volatility `data_quality_warning`

When `atr14_pct_of_close > 5.0` (ATR exceeds 5% of price, indicating choppy conditions that degrade the orderly-pullback thesis), append one entry to `data_quality_warnings`:

```json
{
  "code": "elevated_volatility",
  "severity": "medium",
  "message": "ATR(14) is N.N% of price — elevated volatility may reduce signal reliability",
  "affected_inputs": ["pullback_depth_pct", "consecutive_days_above_sma20"]
}
```

The 5% threshold is a constant in the module (`_ELEVATED_ATR_PCT = 5.0`). No warning is added for normal ATR values.

#### `why` bullets

The `why` list is derived from passing criteria and ATR context. Spec for each bullet (implementations must generate them dynamically from actual indicator values, not hardcode):

| Source | Template |
|---|---|
| `trend_pullback.uptrend` | `"Close ($X.XX) above SMA50 ($Y.YY) and SMA200 ($Z.ZZ) — SMA50 rising over 20 sessions"` |
| `trend_pullback.near_high` | `"Within N.N% of 252-day high (strength filter passed)"` |
| `trend_pullback.pullback_in_progress` | `"Low tagged rising SMA20 ($Y.YY) after N consecutive closes above it"` |
| `trend_pullback.orderly_pullback` | `"Pullback depth N.N% from recent swing high — orderly (3–12% range, no SMA50 breach)"` |
| `trend_pullback.rsi_reset` | `"RSI(5) at N.N — oversold reset confirmed (threshold: < M)"` |
| `trend_pullback.liquidity` | `"20-day avg dollar volume $X.XM — above $5M floor"` |
| volatility context | `"ATR(14) $X.XX (N.N% of close)"` |

Bullets are added in the order above. If ATR is elevated, the volatility bullet reads: `"ATR(14) $X.XX (N.N% of close — elevated volatility, see warnings)"`.

#### `confidence_inputs` shape

Populated from the signal ranker's score, matching the v1 schema contract:

```json
{
  "score": <signal_quality_score or null>,
  "score_source": "signal_quality_score",
  "positive": {},
  "negative": {},
  "missing": {}
}
```

The `positive`/`negative`/`missing` sub-dicts are populated by the ExplanationBuilder infrastructure from #455 (which decomposes the ranker's feature weights). `_build_explanation` should accept `signal_quality_score` and pass it through; it does not compute feature weights itself.

#### `evidence` shape

```json
{
  "reconstructed": false,
  "reconstruction_quality": null,
  "generated_at": "<ISO-8601 UTC>",
  "generator_version": "trend_pullback_explanation.v1",
  "market_data_asof": "<event_date>T00:00:00Z",
  "provider": "polygon"
}
```

### Integration point in `run_trend_pullback_scan`

After `_evaluate_ticker` returns a fired result, and before calling `_save_event`, call `_build_explanation` and pass the result:

```python
explanation = _build_explanation(
    indicators=indicators,
    criteria_met=criteria_met,
    cfg=cfg,
    signal_quality_score=None,   # ranker score not yet computed; ExplanationBuilder from #455 may backfill
    generated_at=datetime.now(timezone.utc).isoformat(),
)

event_dict = _save_event(
    db=db,
    ticker=ticker,
    event_date=event_date,
    scanner_type="trend_pullback",
    indicators=indicators,
    criteria_met=criteria_met,
    enrichment={},
    previous_close=None,
    closing_price=close_today,
    explanation=explanation,    # new parameter added by #455
)
```

The `explanation` parameter on `_save_event` is added by the pre-market reference migration (#455). `_build_explanation` is called after `_evaluate_ticker`, not inside it, keeping the evaluation function free of explanation concerns.

### Backfill reconstruction function

Add `_build_explanation_from_stored_event` in `trend_pullback_scan.py`:

```python
def _build_explanation_from_stored_event(event: "ScannerEvent") -> dict[str, Any]:
    """
    Reconstruct a scanner_explanation.v1 from stored event fields.
    Used by the generic backfill service from issue #458.
    Called only when event.explanation is null or evidence.reconstructed=true.
    """
    indicators = event.indicators or {}
    criteria_met = event.criteria_met or {}
    cfg = {**DEFAULT_CONFIG}

    explanation = _build_explanation(
        indicators=indicators,
        criteria_met=criteria_met,
        cfg=cfg,
        signal_quality_score=event.signal_quality_score,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
    # Override evidence for reconstruction
    explanation["evidence"]["reconstructed"] = True
    explanation["evidence"]["reconstruction_quality"] = _assess_reconstruction_quality(indicators)
    return explanation
```

`_assess_reconstruction_quality(indicators)` returns `"full"` when all 10 expected indicator keys are present and non-null, `"partial"` when some are missing, and `"unsupported"` when the `indicators` dict is empty. The backfill idempotency and the `evidence.reconstructed=true` guard, and the `reconstruction_quality` field are managed by #458's infrastructure; `_build_explanation_from_stored_event` returns the raw dict and leaves those decisions to the caller.

#### Registration with #458's backfill service

At module bottom (alongside the orchestrator registration), add:

```python
from app.services.explanation_backfill import register_backfill_reconstructor  # from #458

register_backfill_reconstructor(
    scanner_type="trend_pullback",
    reconstructor=_build_explanation_from_stored_event,
)
```

The exact `register_backfill_reconstructor` import path and signature are defined by #458. This spec treats #458's contract as binding and does not re-define it.

---

## Test Specification

Tests live in `backend/tests/services/test_trend_pullback_explanation.py` (new file).

### 1. Stable criterion ID constants

```python
_SAMPLE_INDICATORS = {
    "close": 45.0, "sma20": 43.5, "sma50": 40.0, "sma200": 35.0,
    "rsi5": 32.1, "pct_off_252d_high": 8.5, "pullback_depth_pct": 6.2,
    "consecutive_days_above_sma20": 9, "atr14": 1.8, "avg_dollar_vol_20d": 7_500_000,
}
_ALL_PASS = {
    "uptrend": True, "near_high": True, "pullback_in_progress": True,
    "orderly_pullback": True, "rsi_reset": True, "liquidity": True,
}

EXPECTED_CRITERION_IDS = {
    "trend_pullback.uptrend",
    "trend_pullback.near_high",
    "trend_pullback.pullback_in_progress",
    "trend_pullback.orderly_pullback",
    "trend_pullback.rsi_reset",
    "trend_pullback.liquidity",
}

def test_criterion_ids_are_stable():
    explanation = _build_explanation(
        indicators=_SAMPLE_INDICATORS,
        criteria_met=_ALL_PASS,
        cfg=DEFAULT_CONFIG,
        signal_quality_score=0.8,
        generated_at="2026-06-19T00:00:00Z",
    )
    passed_ids = set(explanation["criteria_passed"].keys())
    # Remove volatility_context — it's informational, not a gate criterion
    passed_ids.discard("trend_pullback.volatility_context")
    assert passed_ids == EXPECTED_CRITERION_IDS
```

### 2. `why` bullet generation — known indicator values

```python
_SAMPLE_INDICATORS = {
    "close": 45.0, "sma20": 43.5, "sma50": 40.0, "sma200": 35.0,
    "rsi5": 32.1, "pct_off_252d_high": 8.5, "pullback_depth_pct": 6.2,
    "consecutive_days_above_sma20": 9, "atr14": 1.8, "avg_dollar_vol_20d": 7_500_000,
}
_ALL_PASS = {
    "uptrend": True, "near_high": True, "pullback_in_progress": True,
    "orderly_pullback": True, "rsi_reset": True, "liquidity": True,
}

def test_why_bullets_for_known_indicators():
    explanation = _build_explanation(
        _SAMPLE_INDICATORS, _ALL_PASS, DEFAULT_CONFIG, 0.7, "2026-06-19T00:00:00Z"
    )
    why = explanation["why"]
    assert any("$45.00" in b and "SMA50" in b and "SMA200" in b for b in why)
    assert any("8.5%" in b and "252-day high" in b for b in why)
    assert any("6.2%" in b and "orderly" in b for b in why)
    assert any("32.1" in b and "RSI" in b for b in why)
    assert any("$7.5M" in b for b in why)
    assert any("ATR" in b and "1.8" in b for b in why)
```

### 3. Criteria partition — failed criteria go to `criteria_failed`

```python
def test_failed_criteria_in_criteria_failed():
    criteria_met = {
        "uptrend": True, "near_high": False, "pullback_in_progress": True,
        "orderly_pullback": True, "rsi_reset": False, "liquidity": True,
    }
    explanation = _build_explanation(
        _SAMPLE_INDICATORS, criteria_met, DEFAULT_CONFIG, None, "2026-06-19T00:00:00Z"
    )
    assert "trend_pullback.rsi_reset" in explanation["criteria_failed"]
    assert "trend_pullback.near_high" in explanation["criteria_failed"]
    assert "trend_pullback.rsi_reset" not in explanation["criteria_passed"]
    assert "trend_pullback.near_high" not in explanation["criteria_passed"]
```

### 4. Elevated-volatility warning

```python
def test_elevated_atr_warning():
    indicators = {**_SAMPLE_INDICATORS, "atr14": 3.0, "close": 40.0}  # 7.5% > 5%
    explanation = _build_explanation(
        indicators, _ALL_PASS, DEFAULT_CONFIG, None, "2026-06-19T00:00:00Z"
    )
    codes = [w["code"] for w in explanation["data_quality_warnings"]]
    assert "elevated_volatility" in codes

def test_normal_atr_no_warning():
    indicators = {**_SAMPLE_INDICATORS, "atr14": 1.0, "close": 40.0}  # 2.5% < 5%
    explanation = _build_explanation(
        indicators, _ALL_PASS, DEFAULT_CONFIG, None, "2026-06-19T00:00:00Z"
    )
    codes = [w["code"] for w in explanation["data_quality_warnings"]]
    assert "elevated_volatility" not in codes
```

### 5. Reconstruction quality assessment

```python
def test_reconstruction_quality_full():
    event = Mock(indicators=_SAMPLE_INDICATORS, criteria_met=_ALL_PASS, signal_quality_score=0.6)
    explanation = _build_explanation_from_stored_event(event)
    assert explanation["evidence"]["reconstructed"] is True
    assert explanation["evidence"]["reconstruction_quality"] == "full"

def test_reconstruction_quality_partial():
    event = Mock(indicators={"close": 45.0}, criteria_met=_ALL_PASS, signal_quality_score=None)
    explanation = _build_explanation_from_stored_event(event)
    assert explanation["evidence"]["reconstruction_quality"] == "partial"

def test_reconstruction_quality_unsupported():
    event = Mock(indicators={}, criteria_met={}, signal_quality_score=None)
    explanation = _build_explanation_from_stored_event(event)
    assert explanation["evidence"]["reconstruction_quality"] == "unsupported"
```

### 6. Schema version

```python
def test_schema_version():
    explanation = _build_explanation(...)
    assert explanation["schema_version"] == "scanner_explanation.v1"
```

---

## Alternatives Considered

### A: Build explanation inside `_evaluate_ticker`

Build and return the explanation dict as part of `_evaluate_ticker`'s return value.

**Rejected:** `_evaluate_ticker` is a pure evaluation function; embedding explanation-building into it couples it to the explanation contract and makes it harder to test criteria logic in isolation. Keeping `_build_explanation` as a separate callable that takes the already-computed indicator/criteria values preserves the existing separation of concerns.

### B: Delegate entirely to a generic ExplanationBuilder in #455

Have #455's `ExplanationBuilder` generate the explanation from the criterion IDs and indicator names using a static metadata registry, rather than writing scanner-specific `_build_explanation` logic.

**Rejected (for v1):** The trend_pullback criteria include compound checks (uptrend requires close > SMA50 > SMA200 AND SMA50-rising — two sub-signals), orderly_pullback combines two independent sub-checks (depth range + no-breakdown), and the severity logic is conditional. These cannot be expressed as a flat `{criterion_id: indicator_name}` registry. A scanner-specific function is necessary for accurate `why` bullet generation. If #455's ExplanationBuilder evolves to support compound criteria, a future migration could simplify this.

### C: Include HMM regime in the `evidence` block

Embed `ScannerEvent.regime` into `explanation.evidence.market_context`.

**Rejected:** The `scanner_explanation.v1` schema defines a fixed `evidence` block shape — adding `market_context` would be a schema extension. The design spec (`2026-06-13-scanner-explainability-design.md`, Epic 2 section) explicitly defers market/sector context to Epic 2's analog and archetype layer. The regime is already available on `ScannerEvent.regime`; duplicating it in the explanation envelope is premature and schema-violating.

---

## Assumptions

- `_save_event` in `alert_service.py` will accept an `explanation: dict | None = None` keyword argument as delivered by #455. The call site in `run_trend_pullback_scan` passes the explanation dict; if `explanation` is `None` the function's existing behaviour is unchanged (backward compatibility).
- The `register_backfill_reconstructor` function signature from #458 accepts `(scanner_type: str, reconstructor: Callable[[ScannerEvent], dict]) -> None`. If #458's actual signature differs, the registration call in `trend_pullback_scan.py` must adapt.
- `DEFAULT_CONFIG` thresholds are used for reconstruction of historical events. Events created with a custom `ScannerConfig.parameters` may have different effective thresholds; the reconstruction uses defaults and marks `reconstruction_quality="partial"` to signal this imprecision. [Flagged — if #458's backfill infrastructure passes the config snapshot to the reconstructor, `_build_explanation_from_stored_event` should accept and use it.]
- The `generated_at` timestamp in `evidence` is injected by the caller (`run_trend_pullback_scan` and the backfill service), not by `_build_explanation` itself, so the function remains deterministic and testable with a fixed timestamp.
- The 5% ATR threshold for the elevated-volatility warning is a first-pass value. No historical data analysis was performed to calibrate it; it should be revisited after the backfill run produces a distribution of ATR% values across historical trend_pullback events.

---

## Open Questions (non-blocking)

1. **Custom-config reconstruction**: If a historical event was produced with non-default `ScannerConfig.parameters`, should `_build_explanation_from_stored_event` accept the config snapshot? Depends on whether #458's backfill service passes per-event config or just uses defaults. Not blocking — the reconstruction_quality field communicates the uncertainty.

2. **Importance weights**: The v1 schema has a per-criterion `importance` field. For trend_pullback, all 6 gate criteria are equally necessary (AND logic). Should `importance` be set to `1/6 ≈ 0.17` for each, derived from ranker feature weights, or omitted (`null`)? Not blocking — start with `null`; populate from ranker weights when Epic 2 consumes explanations.

3. **ATR threshold calibration**: The 5% ATR-to-price threshold for the elevated-volatility warning is a judgment call. After backfill produces a sample, revisit via the `/outcomes` API or Scorecard.
