# Live and Social Scanner — Explanation Contract Migration Design

**Date:** 2026-06-19
**Issue:** #462
**Parent Epic:** #448 (Explainability Foundation)
**Blocked by:** #455 (reference ExplanationBuilder), #458 (backfill schema/validation)
**Status:** Spec complete

---

## Overview

Two scanner event writers currently create `ScannerEvent` rows without populating the `explanation` JSONB column being introduced by the Epic #448 blocker chain:

| Writer | File | Scanner types |
|--------|------|--------------|
| Live scanner | `backend/live_scanner/publisher.py:_write_scanner_event()` | `live_volume_spike`, `live_price_move` |
| Tweet monitor | `services/tweet-monitor/app/pipeline.py:_promote()` | `social_callout` |

Both must be migrated to emit a `scanner_explanation.v1` payload without disrupting the existing alert-rule evaluation, auto-trade, and tweet-promotion flows.

---

## Requirements

1. `live_volume_spike` events carry a populated v1 explanation, grounded in IBKR live bar data.
2. `live_price_move` events carry a populated v1 explanation, grounded in IBKR live bar data.
3. `social_callout` events carry a populated v1 explanation, grounded in tweet facts (extracted tickers, price levels, direction) and classifier confidence.
4. Alert and auto-trade consumers (`evaluate_scanner_alerts` Celery task, `AutoTradeExecutor`) are unaffected — they read `ScannerEvent` fields other than `explanation` and must continue to work.
5. The tweet-promotion flow (`TweetSignal.promoted`, `scanner_event_id`, `promotion_reason`) is unaffected — only `explanation` is added to the promoted event.
6. Explanations are stamped atomically at write time (same DB transaction as `indicators`, `criteria_met`, `metadata_`).
7. Tests cover the live-event and social-event creation paths and assert that the produced explanation is schema-valid.

---

## Architecture

### Decision: inline plain dicts at the writer level

**Both writers build the `explanation` as a plain Python dict** following the `scanner_explanation.v1` shape, without importing the `ExplanationBuilder` class from `backend/app/services/`.

Rationale:

- **Atomicity.** Setting `explanation` inline means the event is never API-readable without its explanation. Option B (deferred via `evaluate_scanner_alerts`) opens a race: the API can return a freshly-committed event before the Celery task populates `explanation`. Inline building eliminates that window.
- **Container boundary.** The tweet monitor is a separate Docker service with its own `app/` mirror package. It already hand-constructs `indicators`, `criteria_met`, and `metadata_` as raw dicts in `_promote()`; building `explanation` the same way is consistent and avoids a cross-container import dependency.
- **Data-context mismatch.** The ExplanationBuilder from #455 is designed for batch scanners with Polygon historical bars, DataQualityService gap analysis, and sector ETF context — none of which are available in the IBKR live path. Calling it with mostly-empty fields would produce a misleading output and couple the live scanner to a builder interface that is still being defined.
- **Schema conformance, not class reuse, is the contract.** The acceptance criterion requires "v1 explanations" — not use of the builder class. A test that validates the produced dict against the shared v1 Pydantic schema (provided by #454) is sufficient.

Both paths use `generator_version` values that identify their origin (`"live_scanner.v1"`, `"tweet_monitor.v1"`) rather than the batch builder's `"explanation_builder.v1"`, so downstream consumers can distinguish the source.

---

## §1 Live scanner (`backend/live_scanner/publisher.py`)

### Where the explanation is built

Inside `_write_scanner_event()`, between the severity validation and the `ScannerEvent(...)` constructor call. A new private helper `_build_live_explanation(bar, condition, score)` returns the explanation dict.

### `live_volume_spike` explanation

```python
def _build_live_explanation(
    bar: MinuteBar, condition: ConditionResult, score: float | None
) -> dict:
    ind = condition.indicators  # already computed by check_conditions()
    now_utc = datetime.now(timezone.utc).isoformat()

    if condition.scanner_type == "live_volume_spike":
        vol_ratio = ind["volume_spike_ratio"]
        return {
            "schema_version": "scanner_explanation.v1",
            "why": [
                f"Projected session volume is {vol_ratio:.1f}x average daily volume "
                f"({ind['minutes_elapsed']:.0f} min into {ind['session']} session)"
            ],
            "criteria_passed": {
                "live.projected_volume_ratio": {
                    "label": "Projected volume ratio",
                    "observed": vol_ratio,
                    "threshold": 4.0,
                    "operator": ">=",
                    "unit": "x",
                    "source": "ibkr.reqRealTimeBars",
                },
                "live.sufficient_avg_volume": {
                    "label": "Minimum average daily volume",
                    "observed": float(ind["avg_daily_volume"]),
                    "threshold": 50_000.0,
                    "operator": ">=",
                    "unit": "shares",
                    "source": "ibkr.reqRealTimeBars",
                },
            },
            "criteria_failed": {},
            "confidence_inputs": {
                "score": score,
                "score_source": "signal_quality_score",
                "positive": {"volume_spike_ratio": vol_ratio},
                "negative": {},
                "missing": {},
            },
            "data_quality_warnings": [
                {
                    "code": "projected_volume",
                    "severity": "low",
                    "message": (
                        f"Volume spike ratio is projected over the full session "
                        f"based on {ind['minutes_elapsed']:.0f} min elapsed. "
                        "Accuracy improves as the session progresses."
                    ),
                    "affected_inputs": ["volume_spike_ratio", "projected_volume"],
                }
            ],
            "evidence": {
                "reconstructed": False,
                "reconstruction_quality": None,
                "generated_at": now_utc,
                "generator_version": "live_scanner.v1",
                "market_data_asof": now_utc,
                "provider": "ibkr",
            },
        }
    ...
```

### `live_price_move` explanation

```python
    elif condition.scanner_type == "live_price_move":
        move_pct = ind["price_move_pct"]
        direction = "up" if move_pct > 0 else "down"
        return {
            "schema_version": "scanner_explanation.v1",
            "why": [
                f"Price moved {move_pct:+.2f}% from prior close "
                f"(${ind['prior_close']:.2f} → ${ind['current_price']:.2f})"
            ],
            "criteria_passed": {
                "live.price_move_pct": {
                    "label": "Price move from prior close",
                    "observed": abs(move_pct),
                    "threshold": 1.0,
                    "operator": ">=",
                    "unit": "%",
                    "source": "ibkr.reqRealTimeBars",
                },
            },
            "criteria_failed": {},
            "confidence_inputs": {
                "score": score,
                "score_source": "signal_quality_score",
                "positive": {"price_move_pct": abs(move_pct)},
                "negative": {},
                "missing": {},
            },
            "data_quality_warnings": [],
            "evidence": {
                "reconstructed": False,
                "reconstruction_quality": None,
                "generated_at": now_utc,
                "generator_version": "live_scanner.v1",
                "market_data_asof": now_utc,
                "provider": "ibkr",
            },
        }
```

### Integration in `_write_scanner_event()`

After computing `score` and before constructing `ScannerEvent`:

```python
explanation = _build_live_explanation(bar, condition, score)

event = ScannerEvent(
    ...
    explanation=explanation,   # new field — added to scanner_events table by #453
)
```

The `_validate_jsonb_dict` call already covers `indicators`. Add a parallel validation for `explanation` before the DB write, following the same fail-open pattern used for `indicators`:

```python
try:
    _validate_jsonb_dict(explanation, "explanation")
except (TypeError, ValueError) as exc:
    logger.error(
        f"LivePublisher: non-serializable explanation for "
        f"{bar.symbol} {condition.scanner_type} — skipping DB write: {exc}"
    )
    return
```

---

## §2 Tweet monitor (`services/tweet-monitor/app/pipeline.py`)

### Model mirror update

The tweet monitor's local `ScannerEvent` mirror (`services/tweet-monitor/app/models.py`) does not yet have an `explanation` column. Add it:

```python
explanation = Column(JSONB, nullable=True)
```

No Alembic migration is needed here — the column is added to the real table by issue #453. The mirror is write-only (tweet-monitor never reads back the column), so adding it to the mirror is purely for SQLAlchemy's ORM column mapping to work correctly.

### `social_callout` explanation

A new private helper `_build_social_explanation(signal, ticker, indicators)` in `pipeline.py`:

```python
@staticmethod
def _build_social_explanation(signal: TweetSignal, ticker: str, indicators: dict) -> dict:
    from datetime import datetime, timezone
    now_utc = datetime.now(timezone.utc).isoformat()
    handle = indicators.get("source_account", "?")
    direction = indicators.get("direction") or ""
    confidence = signal.confidence
    threshold = settings.promotion_threshold  # 0.7

    # Build human-readable why strings
    why = []
    dir_str = f"{direction.upper()} " if direction else ""
    why.append(f"@{handle} {dir_str}callout with {confidence:.0%} classifier confidence")
    if indicators.get("price_entry"):
        why.append(f"Entry price level extracted: ${indicators['price_entry']:.2f}")
    if indicators.get("price_target"):
        why.append(f"Target price level extracted: ${indicators['price_target']:.2f}")
    if indicators.get("price_stop"):
        why.append(f"Stop price level extracted: ${indicators['price_stop']:.2f}")

    # Criteria: confidence threshold (numeric), boolean extraction results
    criteria_passed = {
        "social.classifier_confidence": {
            "label": "Classifier confidence",
            "observed": round(confidence, 4),
            "threshold": threshold,
            "operator": ">=",
            "unit": "score",
            "source": "tweet_monitor.classifier",
        },
        "social.has_cashtag": {
            "label": "Cashtag present",
            "observed": 1.0 if signal.tickers else 0.0,
            "threshold": 1.0,
            "operator": "==",
            "unit": None,
            "source": "tweet_monitor.extractor",
        },
    }
    if signal.price_levels and signal.price_levels.get(ticker):
        criteria_passed["social.has_price_level"] = {
            "label": "Price level extracted for ticker",
            "observed": 1.0,
            "threshold": 1.0,
            "operator": "==",
            "unit": None,
            "source": "tweet_monitor.extractor",
        }

    return {
        "schema_version": "scanner_explanation.v1",
        "why": why,
        "criteria_passed": criteria_passed,
        "criteria_failed": {},
        "confidence_inputs": {
            "score": round(confidence, 4),
            "score_source": "classifier_confidence",
            "positive": {
                "classifier_confidence": round(confidence, 4),
                "direction_extracted": 1.0 if direction else 0.0,
                "price_levels_extracted": float(len(signal.price_levels)),
            },
            "negative": {},
            "missing": {},
        },
        "data_quality_warnings": [],
        "evidence": {
            "reconstructed": False,
            "reconstruction_quality": None,
            "generated_at": now_utc,
            "generator_version": "tweet_monitor.v1",
            "market_data_asof": None,  # no market data involved
            "provider": "tweet_monitor",
        },
    }
```

### Integration in `_promote()`

After building `indicators` and before constructing `ScannerEvent`:

```python
explanation = self._build_social_explanation(signal, ticker, indicators)

event = ScannerEvent(
    ...
    explanation=explanation,   # new column in mirror model
)
```

---

## §3 Compatibility guarantee

No changes are needed to downstream consumers:

| Consumer | What it reads | Impact |
|----------|--------------|--------|
| `evaluate_scanner_alerts` | `ScannerEvent.id`, `scanner_type`, `severity`, `indicators`, `criteria_met` | None — `explanation` is additive |
| `AutoTradeExecutor.approve_order()` | `TradingStrategy` and `ScannerEvent.indicators` | None |
| `AlertRule` matching | `scanner_types`, `severity_filter` | None |
| Tweet-promotion flow | `TweetSignal.promoted`, `scanner_event_id`, `promotion_reason` | None |
| Frontend scanner results | `ScannerEvent` fields (existing schema) | None — `explanation` exposed only via #456 API work |

The `explanation` column is nullable in the migration from #453, so any existing code paths that skip setting it continue to work.

---

## §4 Tests

### Live scanner (`backend/tests/live_scanner/test_publisher.py`)

Extend the existing publisher test file to cover explanation construction:

- `test_live_volume_spike_explanation_schema_valid` — construct a `MinuteBar` and `ConditionResult` for `live_volume_spike`; call `_build_live_explanation`; assert `schema_version == "scanner_explanation.v1"`, `criteria_passed` contains `live.projected_volume_ratio`, `data_quality_warnings` contains one `projected_volume` entry, `evidence.provider == "ibkr"`.
- `test_live_price_move_explanation_schema_valid` — same for `live_price_move`; assert `criteria_passed` contains `live.price_move_pct`, `data_quality_warnings == []`.
- `test_write_scanner_event_sets_explanation` — mock `SessionLocal`, `load_ranker_config`; call `publisher._write_scanner_event(bar, condition, summary, severity)`; assert `ScannerEvent.add` was called with an `explanation` kwarg that has `schema_version`.

If #454 ships a `ScannerExplanationV1` Pydantic model, add a `test_*_explanation_pydantic_valid` variant for each type that validates via `ScannerExplanationV1.model_validate(explanation)`.

### Tweet monitor (`services/tweet-monitor/tests/test_pipeline.py`)

New test file covering `_promote()` explanations (currently no `test_pipeline.py` exists):

- `test_social_callout_explanation_schema_valid` — construct a mock `TweetSignal` (confidence=0.85, tickers=["AAPL"], price_levels={"AAPL": {"entry": 185.0, "target": 190.0}}, direction="long"); call `SignalPipeline._build_social_explanation(signal, "AAPL", indicators)`; assert `schema_version`, `criteria_passed.social.classifier_confidence.observed == 0.85`, `why` contains direction string, `evidence.provider == "tweet_monitor"`.
- `test_social_callout_explanation_no_price_level` — signal with no `price_levels`; assert `social.has_price_level` absent from `criteria_passed`.
- `test_promote_sets_explanation_on_event` — mock `db.flush()` and `db.add()`; call `_promote(db, signal, "AAPL")`; capture the `ScannerEvent` added to session; assert it has an `explanation` field with `schema_version`.

---

## §5 Alternatives considered

### A — Deferred explanation via `evaluate_scanner_alerts`

Write the event without `explanation`, then extend the backend's `evaluate_scanner_alerts` Celery task to detect events missing an explanation and build them with `ExplanationBuilder`. Rejected because:
- Opens a race: the API can return a freshly-committed event before Celery processes it, violating the invariant that all new events carry an explanation.
- Bloats `evaluate_scanner_alerts` with backfill/detection logic that belongs to the write path.
- The live path already runs in the backend container so inline building has no boundary cost.

### B — Shared ExplanationBuilder for the live path

Import and call the `ExplanationBuilder` from #455 in `_write_scanner_event()`. Rejected because:
- The builder is designed for Polygon historical data, sector ETF context, and `DataQualityService` gap analysis — none available in the live IBKR path.
- Couples the live scanner to a builder interface that is still TBD in #455.
- The live path already constructs `indicators` and `criteria_met` inline; adding inline `explanation` is consistent.

### C — Shared explanation helper module vendored into tweet monitor

Create a small pure-Python module (no SQLAlchemy/backend deps) in `services/tweet-monitor/app/` that replicates the v1 schema builder logic. Deferred — acceptable if schema drift becomes a problem, but adds maintenance overhead for this issue. Schema conformance via the shared v1 Pydantic model (from #454) is sufficient for now.

---

## Assumptions

- **[ASSUMED]** Issue #453 adds `explanation = Column(JSONB, nullable=True)` to the `scanner_events` table before #462 is implemented. The live scanner and tweet monitor mirror model both depend on this column existing.
- **[ASSUMED]** Issue #454 defines the `scanner_explanation.v1` schema and optionally a `ScannerExplanationV1` Pydantic validator. The test suite should use this validator when available.
- **[ASSUMED]** The `settings.promotion_threshold` (default 0.7) is the canonical confidence threshold for `social_callout` events; it is accessible in `pipeline.py` via `settings.promotion_threshold`.
- The `_validate_jsonb_dict` function from `app.services.alert_service` is importable by the live scanner (it already is today).
- No frontend changes are in scope — explanation display is handled by issue #456 (Expose scanner explanations through API contracts).

---

## Open questions (non-blocking)

1. Should `_build_live_explanation` handle an unknown `scanner_type` gracefully (return a minimal skeleton) or raise? Recommendation: return a minimal v1 dict with `why: ["Unknown live scanner condition"]` and log a warning, consistent with the live scanner's fail-open philosophy.
2. Should the `live.sufficient_avg_volume` criterion appear in `criteria_passed` for `live_volume_spike`? It's always true when the event fires (since the condition check gates on it), but including it makes the explanation self-contained and consistent with how batch scanners expose all checked criteria.
3. The tweet monitor currently has no `test_pipeline.py`. The tests above require creating it. This is within scope since the acceptance criteria explicitly require tests for the social-event creation path.
