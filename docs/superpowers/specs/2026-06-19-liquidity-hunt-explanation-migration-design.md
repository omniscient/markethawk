# Liquidity Hunt Explanation Contract Migration Design

**Date:** 2026-06-19
**Issue:** #459
**Parent Epic:** #448 — Scanner Explainability Foundation
**Status:** Spec generated
**Blocked by:** #455 (pre-market reference explained scanner), #458 (backfill framework)

---

## Overview

This spec migrates `liquidity_hunt_pre` and `liquidity_hunt_post` event creation to the shared `scanner_explanation.v1` contract. It is the first scanner migration after the reference path (#455 — pre-market volume spike) is proven and is blocked on that reference plus the backfill framework (#458).

The liquidity hunt scanner emits two event types from a single `run_liquidity_hunt_scan()` function in `backend/app/services/liquidity_hunt.py`. Both variants evaluate the same 6 criteria; they differ only in which baseline and reference close they use. By the time #459 is implemented, the following infrastructure is in place:

- `ScannerEvent.explanation` JSONB column (from #451)
- `scanner_explanation.v1` schema + `ExplanationBuilder` class (from #453)
- Event-scoped data quality warning API (from #454)
- `_save_event()` extended with `explanation=` kwarg (from #455)
- `ExplanationReconstructorRegistry` and `HistoricalReconstructor` protocol (from #458)

---

## Problem Statement

`liquidity_hunt_pre` and `liquidity_hunt_post` events currently persist `indicators`, `criteria_met`, and enrichment metadata but no durable explanation. A hit says "fired" but does not capture *why* in a structured, analyst-readable, backfillable form. The Epic #448 foundation explicitly identifies this migration as item 9 in the Epic 1 issue list.

---

## Requirements

Derived from the issue acceptance criteria and Q&A:

1. **Persisted v1 explanation**: Every new `liquidity_hunt_pre` and `liquidity_hunt_post` event must have a populated `scanner_explanation.v1` in `scanner_events.explanation`.

2. **Stable criterion IDs** — `liquidity_hunt.*` namespace (shared across both variants since they use the same criteria struct):

   | Current `criteria_met` key | Stable criterion ID |
   |---|---|
   | `volume_ratio` | `liquidity_hunt.session_volume_ratio` |
   | `volume_materiality` | `liquidity_hunt.volume_materiality` |
   | `session_spike` | `liquidity_hunt.session_spike` |
   | `quiet_regular_vol` | `liquidity_hunt.quiet_regular_volume` |
   | `quiet_regular_range` | `liquidity_hunt.quiet_regular_range` |
   | `volume_floor` | `liquidity_hunt.session_volume_floor` |

   A shared namespace (not `liquidity_hunt_pre.*` / `liquidity_hunt_post.*`) is correct because:
   - Both variants use the identical `_evaluate_criteria()` function with the same 6 keys.
   - The session ("pre"/"post") is already encoded in `scanner_type` and in `indicators["session"]`.
   - A shared namespace allows trait analysis to join across both variants on one stable ID per concept.

3. **Session-specific `why` bullets**: The `why` array names the actual session. Minimum required bullets (for a clean pre-market fire; substitute "After-hours" for `liquidity_hunt_post`):
   - `"Pre-market volume was 10.0x the 20-day average (350,000 shares)"` — from C1 (omit when `session_volume_ratio is None`; see warning below)
   - `"Pre-market high spiked 10.1% above prior day's close ($11.00 → $12.11 peak)"` — from C3 (substitute "today's regular close" for post)
   - `"Session volume was 35% of the 20-day average daily volume"` — from C2 (materiality context)
   - `"Regular session remained orderly (range ratio 1.4x vs 20-day average)"` — from C5 (when `regular_range_ratio` is available)

   C4 (`quiet_regular_volume`) is effectively disabled (threshold 1000.0). It should appear in `criteria_passed` with `importance ≈ 0` but does not warrant a `why` bullet since it fires trivially on every event.

   C6 (`session_volume_floor`) is a hard gate, not a discriminating signal. It does not require a `why` bullet.

4. **Confidence inputs**: C4's `importance` weight must be ~0 in `confidence_inputs.positive` / `confidence_inputs.negative` to reflect that it carries no real signal. Weights for C1–C3 and C5–C6 follow whatever pattern #455 establishes via `load_ranker_config()` / `compute_signal_quality_score()`. If ranker config is unavailable, use static proportional defaults (C1 ≈ 0.35, C3 ≈ 0.30, C2 ≈ 0.20, C5 ≈ 0.15, C6 ≈ 0, C4 = 0).

5. **Data quality warnings** — three cases, in order of severity:

   | Code | Source | Severity | Affected inputs |
   |---|---|---|---|
   | `split_in_lookback` | `indicators["split_in_lookback"] is True` | medium | `avg_session_volume_20d`, `session_volume_ratio`, `session_spike_pct` |
   | `liquidity_hunt.zero_session_baseline` | `indicators["session_volume_ratio"] is None` | medium | `avg_session_volume_20d`, `session_volume_ratio` |
   | `insufficient_lookback` | `baselines["days_available"] < 20` | low | `avg_session_volume_20d`, `avg_regular_range_pct_20d` |

   `split_in_lookback` and `liquidity_hunt.zero_session_baseline` are scanner-local codes defined in this spec. `insufficient_lookback` reuses the shared code from #454.

   Missing enrichment (`market_cap=None`, empty `catalyst_tags`) is **not** a data quality warning — enrichment absence does not degrade the 6 criteria, only leaves context fields empty.

6. **Backfill support**: Implement `LiquidityHuntReconstructor` conforming to #458's `HistoricalReconstructor` protocol and register it for both `liquidity_hunt_pre` and `liquidity_hunt_post`. Reconstruction reads from `scanner_events.indicators`, `criteria_met`, `signal_quality_score`. Include the criterion-ID mapping table (current key → stable ID). Include running `backfill_explanations` for both types as part of the acceptance criteria.

7. **No regression**: Existing `indicators`, `criteria_met`, `enrichment`, `signal_quality_score`, alert evaluation, and outcome tracking remain unchanged.

8. **Tests**: Unit tests cover:
   - Explanation structure for both pre-market and post-market fires (correct criterion IDs, schema version, why bullets naming the session)
   - `split_in_lookback` warning present when flag is set
   - `liquidity_hunt.zero_session_baseline` warning present when `session_volume_ratio is None`
   - `insufficient_lookback` warning present when `days_available < 20`
   - `LiquidityHuntReconstructor.reconstruct()` for full reconstruction (all 6 criteria_met keys present)
   - `LiquidityHuntReconstructor.reconstruct()` for partial reconstruction (sparse indicators dict, older events with missing keys)
   - Explanation is passed through to `_save_event()` — assert the `explanation=` kwarg is populated on mock_save

---

## Architecture / Approach

### Alternatives Considered

**Approach A — Inline explanation dict builder in `liquidity_hunt.py`**

Construct the JSONB payload by hand without using #453's `ExplanationBuilder`.

*Rejected*: Violates the foundation spec's design rule "new scanners should not invent custom top-level explanation shapes." Would require duplicating schema validation and version-tracking logic that the `ExplanationBuilder` owns.

**Approach B — Orchestrator-level explanation hooks on `ScannerDescriptor`**

Add explanation-generation callbacks to `ScannerDescriptor` so `scan_orchestrator.py` generates explanations after calling each scanner's `run()` function.

*Rejected*: Out of scope for #459; adds orchestrator surface area not designed in the Epic #448 foundation; contradicts the pattern #455 establishes (explanation built inside the scanner service).

### Selected Approach — `_build_liquidity_hunt_explanation()` using #453's `ExplanationBuilder`

Follows the identical pattern as `pre_market_scan.py` (#455). The scanner service builds the explanation from its own local values and passes it to `_save_event()`.

#### Implementation plan

**1. New private function `_build_liquidity_hunt_explanation()` in `liquidity_hunt.py`**

```python
def _build_liquidity_hunt_explanation(
    session: str,              # "pre" or "post"
    indicators: dict,
    criteria_met: dict,
    baselines: dict,
    ranker_config: dict | None = None,
) -> dict:
    """Build a scanner_explanation.v1 payload for a liquidity hunt event.

    Parameters mirror the outputs of _evaluate_criteria() and _build_indicators()
    so this function can be called synchronously with no additional DB access.
    """
    from app.services.explanation_builder import ExplanationBuilder  # from #453

    session_label = "Pre-market" if session == "pre" else "After-hours"
    ref_close_label = "prior day's close" if session == "pre" else "today's regular close"
    vol_ratio = indicators.get("session_volume_ratio")

    builder = ExplanationBuilder(schema_version="scanner_explanation.v1")

    # ── Criteria ────────────────────────────────────────────────────────────────

    builder.add_criterion(
        id="liquidity_hunt.session_volume_ratio",
        label=f"{session_label} session volume ratio",
        observed=vol_ratio,
        threshold=4.0,
        operator=">=",
        unit="x",
        source="stock_aggregates.minute.volume",
        lookback="20d",
        passed=criteria_met.get("volume_ratio", False),
        importance=0.35 if vol_ratio is not None else 0.0,
    )
    builder.add_criterion(
        id="liquidity_hunt.volume_materiality",
        label="Session volume as % of daily average",
        observed=round(indicators.get("session_volume_pct_of_daily", 0) * 100, 1),
        threshold=30.0,
        operator=">=",
        unit="%",
        source="stock_aggregates.minute.volume",
        lookback="20d",
        passed=criteria_met.get("volume_materiality", False),
        importance=0.20,
    )
    builder.add_criterion(
        id="liquidity_hunt.session_spike",
        label=f"{session_label} price spike vs {ref_close_label}",
        observed=round(indicators.get("session_spike_pct", 0) * 100, 2),
        threshold=10.0,
        operator=">=",
        unit="%",
        source="stock_aggregates.minute.high",
        lookback=None,
        passed=criteria_met.get("session_spike", False),
        importance=0.30,
    )
    builder.add_criterion(
        id="liquidity_hunt.quiet_regular_volume",
        label="Regular session volume (orderly check)",
        observed=indicators.get("regular_volume_ratio"),
        threshold=1000.0,
        operator="<=",
        unit="x",
        source="stock_aggregates.minute.volume",
        lookback="20d",
        passed=criteria_met.get("quiet_regular_vol", True),
        importance=0.0,          # effectively disabled; tracked for honesty
    )
    builder.add_criterion(
        id="liquidity_hunt.quiet_regular_range",
        label="Regular session range ratio",
        observed=indicators.get("regular_range_ratio"),
        threshold=1.50,
        operator="<=",
        unit="x",
        source="stock_aggregates.minute.high,low,open",
        lookback="20d",
        passed=criteria_met.get("quiet_regular_range", False),
        importance=0.15,
    )
    builder.add_criterion(
        id="liquidity_hunt.session_volume_floor",
        label="Absolute session volume floor",
        observed=indicators.get("session_volume"),
        threshold=50_000,
        operator=">=",
        unit="shares",
        source="stock_aggregates.minute.volume",
        lookback=None,
        passed=criteria_met.get("volume_floor", False),
        importance=0.0,           # hard gate; not a discriminating signal
    )

    # ── Why bullets ─────────────────────────────────────────────────────────────

    if vol_ratio is not None:
        builder.add_why(
            f"{session_label} volume was {vol_ratio:.1f}x the 20-day average "
            f"({indicators.get('session_volume', 0):,} shares)"
        )
    else:
        builder.add_why(
            f"{session_label} session had {indicators.get('session_volume', 0):,} shares "
            f"(no 20-day session baseline on record)"
        )

    spike_pct = indicators.get("session_spike_pct", 0)
    ref_close = indicators.get("reference_close", 0)
    sess_high = indicators.get("session_high", 0)
    builder.add_why(
        f"{session_label} high spiked {spike_pct:.1%} above {ref_close_label} "
        f"(${ref_close:.2f} → ${sess_high:.2f} peak)"
    )

    pct_of_daily = indicators.get("session_volume_pct_of_daily", 0)
    builder.add_why(
        f"Session volume was {pct_of_daily:.0%} of the 20-day average daily volume"
    )

    range_ratio = indicators.get("regular_range_ratio")
    if range_ratio is not None:
        builder.add_why(
            f"Regular session remained orderly (range ratio {range_ratio:.2f}x vs 20-day average)"
        )

    # ── Data quality warnings ────────────────────────────────────────────────────

    if indicators.get("split_in_lookback"):
        builder.add_warning(
            code="split_in_lookback",
            severity="medium",
            message=(
                "Stock had a split within the 20-day lookback window; "
                "volume and price baselines may be distorted"
            ),
            affected_inputs=["avg_session_volume_20d", "session_volume_ratio", "session_spike_pct"],
        )

    if vol_ratio is None:
        builder.add_warning(
            code="liquidity_hunt.zero_session_baseline",
            severity="medium",
            message=(
                f"No historical {session} session volume on record; "
                "volume ratio criterion was trivially satisfied"
            ),
            affected_inputs=["avg_session_volume_20d", "session_volume_ratio"],
        )

    days_available = baselines.get("days_available", 20)
    if days_available < 20:
        builder.add_warning(
            code="insufficient_lookback",   # shared code from #454
            severity="low",
            message=(
                f"Rolling averages computed from {days_available} trading days "
                "(fewer than the 20-day target)"
            ),
            affected_inputs=["avg_session_volume_20d", "avg_regular_range_pct_20d"],
        )

    # ── Confidence inputs ────────────────────────────────────────────────────────

    builder.set_confidence_from_ranker(indicators, ranker_config)

    # ── Evidence ────────────────────────────────────────────────────────────────

    builder.set_evidence(reconstructed=False, provider="polygon")

    return builder.build()
```

**2. Integration in `run_liquidity_hunt_scan()`**

Call `_build_liquidity_hunt_explanation()` after `_build_indicators()` and before `_save_event()` for both the pre and post fire paths. The `baselines` dict is already available in scope:

```python
# Pre-market variant (existing code, additions shown with ++)
if fires_pre:
    indicators_pre = _build_indicators("pre", base_ind_pre, ...)
++  explanation_pre = _build_liquidity_hunt_explanation(
++      "pre", indicators_pre, criteria_pre, baselines, config
++  )
    event_dict = _save_event(
        db=db, ticker=ticker, event_date=event_date,
        scanner_type="liquidity_hunt_pre",
        indicators=indicators_pre, criteria_met=criteria_pre,
        enrichment=enrichment, previous_close=prior_day_close,
        opening_price=session_metrics["regular_open"],
        closing_price=session_metrics["regular_close"],
++      explanation=explanation_pre,
    )
```

The post-market path follows identically with `session="post"` and `reference_close=event_date_regular_close`.

**3. `LiquidityHuntReconstructor` class**

The reconstructor lives in `liquidity_hunt.py` (or `liquidity_hunt_explanation.py` if #455 establishes a sibling-module convention). It conforms to #458's `HistoricalReconstructor` protocol:

```python
class LiquidityHuntReconstructor:
    """Reconstructs scanner_explanation.v1 from historical liquidity hunt events.

    Handles both liquidity_hunt_pre and liquidity_hunt_post — the session
    is read from indicators["session"] (defaults to "pre" for older rows
    that may predate the session field).
    """

    CRITERION_ID_MAP = {
        "volume_ratio":       "liquidity_hunt.session_volume_ratio",
        "volume_materiality": "liquidity_hunt.volume_materiality",
        "session_spike":      "liquidity_hunt.session_spike",
        "quiet_regular_vol":  "liquidity_hunt.quiet_regular_volume",
        "quiet_regular_range": "liquidity_hunt.quiet_regular_range",
        "volume_floor":       "liquidity_hunt.session_volume_floor",
    }

    def reconstruct(self, event: "ScannerEvent") -> dict:
        indicators = event.indicators or {}
        criteria_met = event.criteria_met or {}
        session = indicators.get("session", "pre")
        # Determine quality: full if all 6 criteria_met keys present + session field present
        has_all_keys = all(k in criteria_met for k in self.CRITERION_ID_MAP)
        quality = "full" if has_all_keys and "session" in indicators else "partial"

        # Delegate to _build_liquidity_hunt_explanation, passing a minimal baselines
        # dict reconstructed from the indicators snapshot.
        baselines = {
            "days_available": indicators.get("days_available", 20),
            "avg_pre_vol_20d": indicators.get("avg_session_volume_20d", 0)
            if session == "pre" else 0,
            "avg_post_vol_20d": indicators.get("avg_session_volume_20d", 0)
            if session == "post" else 0,
            "avg_regular_vol_20d": indicators.get("avg_regular_volume_20d", 0),
            "avg_total_daily_vol_20d": (
                indicators.get("session_volume", 0)
                / indicators["session_volume_pct_of_daily"]
                if indicators.get("session_volume_pct_of_daily")
                else 0
            ),
            "avg_regular_range_pct_20d": indicators.get("avg_regular_range_pct_20d", 0),
        }

        explanation = _build_liquidity_hunt_explanation(
            session=session,
            indicators=indicators,
            criteria_met=criteria_met,
            baselines=baselines,
            ranker_config=None,     # not available during reconstruction
        )

        # Stamp reconstruction metadata
        explanation["evidence"]["reconstructed"] = True
        explanation["evidence"]["reconstruction_quality"] = quality
        if event.signal_quality_score is not None:
            explanation["confidence_inputs"]["score"] = float(event.signal_quality_score)
            explanation["confidence_inputs"]["score_source"] = "signal_quality_score"

        return explanation
```

**4. Registry registration**

In the `ExplanationReconstructorRegistry` initialization (wherever #458 places it, likely `backend/app/services/explanation_backfill.py`):

```python
from app.services.liquidity_hunt import LiquidityHuntReconstructor

_reconstructor = LiquidityHuntReconstructor()
registry.register("liquidity_hunt_pre",  _reconstructor)
registry.register("liquidity_hunt_post", _reconstructor)
```

**5. Backfill execution**

As part of the acceptance criteria, invoke the existing backfill task (from #458) targeting both types:

```bash
# Within the backend container:
python -c "
from app.tasks.quality import backfill_explanations
backfill_explanations.delay(scanner_type='liquidity_hunt_pre')
backfill_explanations.delay(scanner_type='liquidity_hunt_post')
"
```

---

## Scope Boundary

**In scope:**
- `_build_liquidity_hunt_explanation()` function in `liquidity_hunt.py`
- Integration into `run_liquidity_hunt_scan()` — both pre and post call sites
- `LiquidityHuntReconstructor` class + registry registration
- Running `backfill_explanations` for both scanner types
- Tests for explanation structure, all 3 warning codes, and reconstruction (full + partial)

**Out of scope:**
- `ExplanationBuilder` API definition (from #453)
- DataQualityService event-scoped warning API (from #454)
- `_save_event()` `explanation=` parameter (from #455)
- `ExplanationReconstructorRegistry` protocol (from #458)
- Frontend explanation UI (separate issue)
- Backfill for other scanner types (`oversold_bounce`, `pocket_pivot`, `trend_pullback`)

---

## Assumptions

1. `ExplanationBuilder` from #453 exposes `add_criterion()`, `add_why()`, `add_warning()`, `set_confidence_from_ranker()`, `set_evidence()`, and `build()` methods. If the exact API differs, the implementation adapts the call sites — not the spec's intent.

2. `_save_event()` from #455 accepts an optional `explanation: dict | None = None` keyword argument. Passing `explanation=None` preserves backward-compatibility for callers that haven't migrated yet.

3. #458's `HistoricalReconstructor` protocol defines `reconstruct(self, event: ScannerEvent) -> dict`.

4. #454 defines a shared `insufficient_lookback` warning code. If the actual constant name differs, use #454's literal string.

5. The `baselines` dict passed to `_build_liquidity_hunt_explanation()` during live scanning always has a `days_available` key (confirmed: `_get_rolling_baselines()` includes it in its return dict at line 345 of `liquidity_hunt.py`).

6. `vol_ratio is None` is the correct condition for "zero session baseline" — the scanner sets `vol_ratio = None` (not 0) explicitly when `avg_session_vol == 0` (line 95).

---

## Open Questions (non-blocking)

1. **Exact ExplanationBuilder API**: The spec assumes an `add_criterion()` method with these kwargs; the actual interface is defined by #453. The implementer should match #455's call sites for consistency.

2. **Reconstruction of `avg_regular_range_pct_20d`**: Historical events don't store this field directly in `indicators`. When reconstructing, this should be set to `0` (triggering no range-ratio bullet / no warning), consistent with "honest reconstruction" from the Epic #448 design rule.

3. **Importance weights**: The static defaults in this spec (C1=0.35, C3=0.30, C2=0.20, C5=0.15) are illustrative. The implementer should match whatever weight convention #455 establishes for pulling from `SystemConfig` via `load_ranker_config()`.
