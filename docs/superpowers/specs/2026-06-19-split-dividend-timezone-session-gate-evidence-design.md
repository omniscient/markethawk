# Split/Dividend and Timezone/Session Gate Evidence Design

**Date:** 2026-06-19  
**Issue:** #500  
**Parent Epic:** #491 (Data Quality Trust Gate)  
**Blocked by:** #492 (gate contract and service)  
**Status:** Pending review

---

## Overview

Issue #500 is slice 9 of the Data Quality Trust Gate epic (#491). It adds two evidence emitters to the gate evidence module:

- `generate_split_dividend_anomaly_issues()` — detects adjustment discontinuities caused by unapplied or incorrectly recorded stock splits.
- `generate_timezone_session_mismatch_issues()` — detects bars whose stored `is_pre_market`/`is_after_market` flags disagree with the recomputed DST-correct session classification.

Both checks protect session-sensitive scanners (pre-market volume spike, liquidity hunt) and backtests from acting on silently corrupted market data.

---

## Requirements

1. The module `backend/app/services/quality_gate_evidence.py` exposes `generate_split_dividend_anomaly_issues()` and `generate_timezone_session_mismatch_issues()` — both with the signature `(db: Session, universe_id: int, scanner_config: ScannerConfig | None, ticker: str | None = None) -> list[GateIssue]`.
2. The module defines a `GateIssue` stub dataclass so the emitters are testable in isolation before the #492 gate contract is implemented.
3. `generate_split_dividend_anomaly_issues()` runs two sub-checks:
   - **Unapplied-split check**: flags any universe ticker with a `StockSplit` row where `adjustments_applied_at IS NULL` and bars straddle `execution_date`.
   - **Discontinuity check**: flags overnight session-boundary returns ≥ 25% that lack a matching, correctly-factored `StockSplit` entry.
4. `generate_timezone_session_mismatch_issues()` recomputes the expected session for each minute bar via `session_for_ts()` from `app.utils.session` and compares it against the stored `is_pre_market`/`is_after_market` flags. Emits per ticker when mismatch rate exceeds 1%.
5. Bars landing in `'closed'` windows per `session_for_ts()` are flagged at blocker severity (higher than a standard flag mismatch) as they indicate an ingest-time timezone offset error.
6. Both emitters scope to `StockAggregate` (equities) and `timespan == "minute"` bars only. Daily bars and `FuturesAggregate` are excluded.
7. All thresholds are configurable via `scanner_config.parameters` with explicit defaults (see Approach section).
8. Strict vs. advisory enforcement is the gate policy layer's responsibility (from #492), not a new `ScannerConfig` column.
9. When called with `ticker=None`, emitters iterate all active universe tickers. When called with a specific `ticker`, they scope to that ticker only.
10. Tests cover: unapplied split with/without straddling bars, applied split within/outside factor tolerance, price discontinuity with matching vs. missing split, correct session flags (no emit), wrong flags above/below threshold, DST-transition edge case, and a `'closed'`-window bar.

---

## Architecture

### Module Layout

```
backend/app/services/quality_gate_evidence.py   ← new file (this slice)
```

The module deliberately does not extend `data_quality.py` (which owns the universe-level coverage/integrity/continuity scoring responsibility — a different concern) or the scanner pipeline (latency-sensitive). This is consistent with the architectural decision from the prior slices in the epic.

### GateIssue Stub

Until #492 ships the full gate contract, a minimal stub lives in `quality_gate_evidence.py`:

```python
from dataclasses import dataclass, field
from typing import Any

@dataclass
class GateIssue:
    code: str           # stable machine-readable issue code
    severity: str       # "blocker" | "warning"
    ticker: str
    evidence: dict[str, Any] = field(default_factory=dict)
    generated_at: str = ""  # ISO 8601
```

When #492 defines the authoritative `GateIssue`, the stub is replaced with an import from the gate contract module.

### Split/Dividend Anomaly Emitter

**Entry point:** `generate_split_dividend_anomaly_issues(db, universe_id, scanner_config, ticker=None) -> list[GateIssue]`

**Sub-check 1 — Unapplied split:**

```
For each ticker T in universe:
  splits = StockSplit WHERE ticker=T AND adjustments_applied_at IS NULL
  For each split S:
    has_pre  = StockAggregate WHERE ticker=T AND timestamp < S.execution_date EXISTS
    has_post = StockAggregate WHERE ticker=T AND timestamp >= S.execution_date EXISTS
    If has_pre AND has_post:
      emit GateIssue(
        code="split_dividend_anomaly",
        severity="blocker",
        ticker=T,
        evidence={
          "reason": "unapplied_split",
          "execution_date": str(S.execution_date),
          "split_from": float(S.split_from),
          "split_to": float(S.split_to),
        }
      )
```

**Sub-check 2 — Price discontinuity:**

Uses the `is_pre_market` / `is_after_market` classification from existing `StockAggregate` flags to identify daily session boundaries (last regular-session close on day D → first open on or after day D+1), avoiding noise from overnight pre-market sessions.

```
DETECTION_FLOOR    = scanner_config.parameters.get("split_discontinuity_floor_pct", 25) / 100
FACTOR_TOLERANCE   = scanner_config.parameters.get("split_factor_tolerance_pct", 5) / 100

For each ticker T:
  daily bars = StockAggregate WHERE ticker=T AND timespan="minute", ordered by timestamp ASC
  Group by ET date. For each consecutive date pair (D, D+1):
    last_close = last regular-session bar's close on day D
    first_open = first regular-session bar's open on day D+1
    If last_close == 0: skip
    overnight_return = abs(first_open / last_close - 1)
    If overnight_return < DETECTION_FLOOR: continue

    # Large move detected — check against known splits
    splits_on_boundary = StockSplit WHERE ticker=T AND execution_date=D+1
    If no split row:
      # Unexplained large discontinuity (possible unrecorded split or dividend)
      emit GateIssue(code="split_dividend_anomaly", severity="blocker", ...)
    Else:
      factor = compute_price_factor(split)  # split_from / split_to
      observed_ratio = first_open / last_close
      expected_ratio = float(factor)        # e.g. 0.5 for 2:1 forward split
      If abs(observed_ratio - expected_ratio) / expected_ratio > FACTOR_TOLERANCE:
        # Recorded split factor doesn't match observed price jump
        emit GateIssue(code="split_dividend_anomaly", severity="blocker", ...)
      # Else: consistent with recorded split — do not emit
```

Volume corroboration: when a discontinuity is emitted, include `volume_ratio` in `evidence` (first post-boundary bar volume / last pre-boundary bar volume). A true forward split should show approximately inverse volume scaling (2:1 split → ~2× volume), which strengthens the anomaly signal for reviewers.

### Timezone/Session Mismatch Emitter

**Entry point:** `generate_timezone_session_mismatch_issues(db, universe_id, scanner_config, ticker=None) -> list[GateIssue]`

**Algorithm:**

```
MISMATCH_THRESHOLD = scanner_config.parameters.get("session_mismatch_threshold_pct", 1.0) / 100

For each ticker T in universe:
  bars = StockAggregate WHERE ticker=T AND timespan="minute"
  total = len(bars)
  If total == 0: skip

  mismatch_count = 0
  closed_count = 0
  sample_mismatches = []  # store up to 10 examples for evidence

  For each bar B:
    expected_session = session_for_ts(B.timestamp)  # DST-correct, from app.utils.session
    expected_pre  = (expected_session == "pre")
    expected_post = (expected_session == "post")

    If expected_session == "closed":
      closed_count += 1
      continue  # counted separately

    If expected_pre != B.is_pre_market or expected_post != B.is_after_market:
      mismatch_count += 1
      if len(sample_mismatches) < 10:
        sample_mismatches.append({
          "timestamp_utc": B.timestamp.isoformat(),
          "stored_pre": B.is_pre_market,
          "stored_post": B.is_after_market,
          "expected_session": expected_session,
        })

  # Emit for 'closed' bars — always blocker regardless of threshold
  If closed_count > 0:
    emit GateIssue(
      code="timezone_session_mismatch",
      severity="blocker",
      ticker=T,
      evidence={
        "reason": "bars_in_closed_window",
        "closed_bar_count": closed_count,
        "total_bars": total,
      }
    )

  # Emit for flag mismatches above threshold
  mismatch_rate = mismatch_count / total
  If mismatch_rate > MISMATCH_THRESHOLD:
    emit GateIssue(
      code="timezone_session_mismatch",
      severity="warning",
      ticker=T,
      evidence={
        "reason": "flag_mismatch",
        "mismatch_count": mismatch_count,
        "total_bars": total,
        "mismatch_rate_pct": round(mismatch_rate * 100, 2),
        "threshold_pct": MISMATCH_THRESHOLD * 100,
        "sample_mismatches": sample_mismatches,
      }
    )
```

**Why reuse `session_for_ts()`:** `classify_session()` in `tasks/sync.py:359` (the existing ingest path) delegates to `session_for_ts()`, which handles DST via `ZoneInfo("America/New_York")`. Reusing the same function means a mismatch detection by the emitter and a re-ingest of the same bar would produce consistent flags — no divergence between the stored and the recomputed session classification.

**Strict mode:** Enforced by the gate policy layer (#492 `policy=strict`), not by a new `ScannerConfig` field. When the gate policy is `strict` and this emitter returns any blocker-severity issue for a ticker, the gate assessment yields `blocked`. When `advisory`, the issue is persisted as a visible warning without blocking. The emitter itself is policy-agnostic — it only produces coded `GateIssue` payloads.

---

## Alternatives Considered

### A: Extend `DataQualityService.analyze_universe()`

Add split and session checks directly inside `DataQualityService.analyze_universe()` (already 547 lines), augmenting `UniverseQualityReport.report_data`.

**Rejected because:** `data_quality.py` owns universe-level OHLCV scoring (Coverage/Integrity/Continuity) — a separate responsibility from gate issue emission. Mixing them would make the service harder to extend and test independently. The prior slices in the epic explicitly rejected this approach when establishing `quality_gate_evidence.py`.

### B: Run checks at scan time (per scan run, per ticker)

Integrate evidence checks into the scanner pipeline so they run during `run_universe_scan` for each ticker.

**Rejected because:** the scan pipeline is latency-sensitive and already parallelised with an `asyncio.Semaphore(10)` bound. Split/session checks require full ticker bar history (not just the scan window), making them expensive as per-scan-run operations. The batch quality analysis cadence (triggered explicitly via `POST /api/v1/universe/{id}/quality`) is the right home.

---

## Open Questions

1. **Dividend table future work:** Should a dividends table be added to the data model in a future slice to enable verified dividend-adjusted price checks, or is the discontinuity detector (sub-check 2) sufficient as a catch-all for unexplained large gaps?
2. **FuturesAggregate session classification:** Futures sessions differ from US equity sessions (CME 23:00–22:00 ET, near 24 hours). Should a separate future slice extend `generate_timezone_session_mismatch_issues()` to cover `FuturesAggregate` with CME-specific session boundaries?
3. **Batch efficiency:** For universes with 2,000+ tickers, the discontinuity check iterates all minute bars per ticker. A date-windowed approach (e.g., only scan bars within the most recent N days of known splits) may be needed for performance at scale.

---

## Assumptions

- A1: `quality_gate_evidence.py` does not yet exist in the codebase (confirmed by code scan 2026-06-19). Prior slice #498 described creating it in spec but implementation is pending. This slice creates it and defines the `GateIssue` stub.
- A2: The #492 gate contract (which defines the authoritative `GateIssue` class and the policy enforcement layer) will be implemented before the gate assessment layer calls these emitters. Until then, emitters can be unit-tested in isolation via the stub.
- A3: Scope is `StockAggregate` (equities) only. `FuturesAggregate` is excluded from both checks in this slice.
- A4: `timespan == "minute"` bars are the target for session mismatch. Daily (`timespan == "day"`) and higher-resolution bars are excluded — session flag semantics don't apply to them.
- A5: `scanner_config` may be `None` if called outside a scanner context; emitters must fall back to hardcoded defaults when `None`.
- A6: The `SplitAdjustmentService.compute_price_factor()` method is reused to derive expected split ratios (no reimplementation).
