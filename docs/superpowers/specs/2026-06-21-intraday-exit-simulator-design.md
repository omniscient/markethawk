# Intraday Exit Simulator — Design

**Date:** 2026-06-21
**Status:** Pending review
**Issue:** #485 — Replay engine: intraday-accurate exit simulator
**Parent epic:** #300 — Backtest scanner signals against TradingStrategy definitions

---

## Overview

This spec covers `IntradayExitSimulator`: the minute-bar exit resolver for the MarketHawk signal
replay engine. Unlike the existing `backtest_service._simulate_trade()` (daily bars only), this
simulator walks **minute bars** in chronological order so stop-vs-target ordering is unambiguous
and MFE/MAE reflects the real intraday price path. A conservative daily fallback applies when
minute data is absent for any day in the hold window.

The module defines two things:
1. A Python `Protocol` (`ExitSimulator`) plus supporting dataclasses — the shared interface for
   all replay simulators. Issue #300 will consume this interface.
2. `IntradayExitSimulator` — the concrete implementation of that protocol using minute bars.

This is a **backend-only, pure-logic module**. No API endpoint, UI, or new database migration is
in scope for this issue.

---

## Problem Statement

`backtest_service._simulate_trade()` resolves exits using daily OHLCV bars. When a daily bar
touches both stop and target (common in volatile pre-market names), the engine applies
stop-first (worst-case). With minute bars, the actual triggering bar is identified precisely,
MFE/MAE tracks the real intraday path, and limit-entry fills are tested against actual intraday
prices rather than just the day's opening print.

---

## Decisions Made During Brainstorming

1. **Entry timing:** Enter at the 09:30 ET regular-session open on signal day D (not D+1). The
   pre-market scanner fires before 09:30; the first regular-session minute bar is a legitimately
   tradeable "next session open" with no lookahead. The daily engine enters D+1 only because
   daily bars can't express "9:30 on the same day." (Q1)

2. **`max_hold_days` is a call-time parameter, not a TradingStrategy column.** Matches the
   existing `BacktestRun.max_hold_sessions` pattern — hold period is a run-level sweep parameter,
   not a fixed property of the strategy. (Q2A)

3. **`direction == "both"` → simulate long.** Long is the scanner baseline. Only `"short_only"`
   inverts stop/target math. This mirrors `AutoTradeService._resolve_direction()` where `"both"`
   is the most permissive setting and never skips. (Q2B)

4. **Return type:** New `SimulatedTrade` dataclass in `services/replay/protocols.py`. Mirrors
   `backtest_service.SimulatedTrade` for vocabulary consistency but is a distinct class with new
   fields (`return_pct`, `mfe_pct`, `mae_pct`, `bars_held`, `fill_source`). Does not inherit
   from nor extend the daily dataclass. (Q3A)

5. **Protocol in `protocols.py`, implementation in `exit_simulator.py`.** Issue #300 should
   depend only on the thin protocol module, not on the concrete implementation. Standard Python
   Protocol pattern for cross-module reuse. (Q3B)

---

## Requirements

| ID | Requirement |
|----|-------------|
| R1 | Create `backend/app/services/replay/` as a Python package (`__init__.py` + `protocols.py` + `exit_simulator.py`). |
| R2 | `protocols.py` defines `SignalRecord`, `StrategyParams`, `SimulatedTrade` dataclasses and the `ExitSimulator` Protocol. |
| R3 | `exit_simulator.py` defines `IntradayExitSimulator` that structurally satisfies `ExitSimulator`. |
| R4 | Entry bar = first regular-session minute bar at or after 09:30 ET on signal day D (`is_pre_market=False AND is_after_market=False`, `timespan="minute"`). No such bar → `exit_reason="eod-no-fill"`. |
| R5 | Market entry: fill at `entry_bar.open`. |
| R6 | Limit entry: `limit_price = previous_close × (1 + limit_offset_pct / 100)`. Walk entry-day regular-session minute bars in order. Long: first bar where `bar.low ≤ limit_price` → fill at `min(bar.open, limit_price)`. Short: first bar where `bar.high ≥ limit_price` → fill at `max(bar.open, limit_price)`. No qualifying bar by EOD → `exit_reason="eod-no-fill"`. |
| R7 | Stop/target levels from entry_price: **Long** → `stop = entry - entry × stop_pct/100`; `target = entry + (entry - stop) × rr`. **Short** → `stop = entry + entry × stop_pct/100`; `target = entry - (entry - stop) × rr`. |
| R8 | Minute-bar exit walk: for each bar, check stop first then target. **Long stop:** `bar.low ≤ stop_price` → exit at stop. **Long target:** `bar.high ≥ target_price` → exit at target. **Short stop:** `bar.high ≥ stop_price` → exit at stop. **Short target:** `bar.low ≤ target_price` → exit at target. Both triggered on the same bar → stop wins (conservative). |
| R9 | Daily fallback: when no regular-session minute bars exist for a given day in the hold window, use the day's daily bar (`timespan="day"`, `multiplier=1`). Apply the same stop-first rule. Flag `fill_source="daily-fallback"` when at least one day resolves via a daily bar. |
| R10 | Time exit: if neither stop nor target is hit after `max_hold_days` calendar days from entry_date, exit at the open of the first available bar on or after `entry_date + timedelta(days=max_hold_days)`. `exit_reason="time_exit"`. No bar after the hold window → `exit_reason="delisted_or_data_end"`. |
| R11 | Track running MFE and MAE while the position is open (starting from the bar *after* entry through the exit bar inclusive): **Long** MFE = `(bar.high - entry_price) / entry_price × 100`; MAE = `(entry_price - bar.low) / entry_price × 100`. **Short** MFE = `(entry_price - bar.low) / entry_price × 100`; MAE = `(bar.high - entry_price) / entry_price × 100`. Record the maximum of each across all bars walked. |
| R12 | Compute direction-aware P&L where **+value = profitable**. Let `stop_distance = abs(entry_price - stop_price)` and `direction_sign = 1 if long else -1`. Then: `return_pct = direction_sign × (exit_price - entry_price) / entry_price × 100` and `result_r = direction_sign × (exit_price - entry_price) / stop_distance`. A long trade hitting target yields `result_r = +rr`; a short trade hitting target also yields `result_r = +rr`. A stop-out is always `result_r = -1.0`. |
| R13 | `bars_held` = count of bars walked from (exclusive) the entry bar to (inclusive) the exit bar, counting both minute bars and any daily fallback bars as 1 each. |
| R14 | `fill_source = "intraday"` when all exit resolution used minute bars; `"daily-fallback"` when at least one hold-window day fell back to a daily bar. |
| R15 | Same `signal + strategy + bars` inputs → same `SimulatedTrade` output (deterministic). |
| R16 | Fixture-based unit tests (no DB, no live data) covering: long stop-first, long target-first, time exit, EOD no-fill, daily-fallback (both stop and target on same daily bar → stop), short_only inversion. Each test asserts exact entry/exit/return_pct/result_r/mfe_pct/mae_pct values against hand-computed expectations. |

---

## Architecture

### Package layout

```
backend/app/services/replay/
├── __init__.py
├── protocols.py          # Protocol + dataclasses (dependency-free)
└── exit_simulator.py     # IntradayExitSimulator implementation
```

### protocols.py — interface contract

```python
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional, Protocol, runtime_checkable


@dataclass(frozen=True)
class SignalRecord:
    ticker: str
    signal_date: date
    indicators: dict          # must contain "previous_close" for limit entry
    source_event_id: Optional[int] = None


@dataclass(frozen=True)
class StrategyParams:
    entry_type: str           # "market" | "limit"
    stop_pct: float
    risk_reward_ratio: float
    limit_offset_pct: float   # % offset for limit price; may be negative
    direction: str            # "long_only" | "short_only" | "both"


@dataclass
class SimulatedTrade:
    ticker: str
    signal_date: date
    source_event_id: Optional[int]

    entry_date: Optional[date] = None
    entry_price: Optional[Decimal] = None
    exit_date: Optional[date] = None
    exit_price: Optional[Decimal] = None
    # stop | target | time_exit | eod-no-fill | delisted_or_data_end
    exit_reason: Optional[str] = None
    bars_held: Optional[int] = None     # minute-bar (or daily-fallback-bar) count

    stop_price: Optional[Decimal] = None
    target_price: Optional[Decimal] = None

    return_pct: Optional[float] = None
    result_r: Optional[float] = None
    mfe_pct: Optional[float] = None
    mae_pct: Optional[float] = None

    fill_source: Optional[str] = None  # "intraday" | "daily-fallback"


@runtime_checkable
class ExitSimulator(Protocol):
    def simulate(
        self,
        signal: SignalRecord,
        strategy: StrategyParams,
        bars: list,          # list[StockAggregate]; loosely typed to avoid circular import
        max_hold_days: int,
    ) -> SimulatedTrade: ...
```

### Caller contract for `bars`

The caller is responsible for pre-fetching and passing **all** bars the simulator may need:

- Regular-session minute bars (`timespan="minute"`, `multiplier=1`, `is_pre_market=False`,
  `is_after_market=False`) for signal day D through `D + max_hold_days + 7` (buffer for
  weekends/holidays).
- Daily bars (`timespan="day"`, `multiplier=1`) for the same date range, as fallback when
  minute bars are absent for a given day.

The simulator partitions the `bars` list by `(date, timespan)`. For each day in the hold
window: if minute bars exist for that date, use them; otherwise use the daily bar.

### IntradayExitSimulator — algorithm

```
1. Partition bars:
   - entry_day_bars = [b for b in bars if b.timestamp.date() == signal.signal_date
                       and b.timespan == "minute"
                       and not b.is_pre_market and not b.is_after_market]
     sorted by timestamp ascending
   - hold_bars_by_date = group remaining bars by date in ascending date order

2. is_short = strategy.direction == "short_only"

3. ENTRY:
   if not entry_day_bars:
       return SimulatedTrade(exit_reason="eod-no-fill")
   entry_bar = entry_day_bars[0]  (first bar at 09:30 ET)

   if strategy.entry_type == "market":
       entry_price = entry_bar.open

   elif strategy.entry_type == "limit":
       previous_close = signal.indicators.get("previous_close")
       if previous_close is None:
           return SimulatedTrade(exit_reason="eod-no-fill")
       limit_price = Decimal(previous_close) * (1 + Decimal(strategy.limit_offset_pct) / 100)
       fill_bar = None
       for bar in entry_day_bars:
           if not is_short and bar.low <= limit_price:
               fill_bar = bar; break
           if is_short and bar.high >= limit_price:
               fill_bar = bar; break
       if fill_bar is None:
           return SimulatedTrade(exit_reason="eod-no-fill")
       entry_price = (min(fill_bar.open, limit_price) if not is_short
                      else max(fill_bar.open, limit_price))

4. Compute stop/target:
   stop_dist = entry_price * Decimal(strategy.stop_pct) / 100
   if not is_short:
       stop_price  = entry_price - stop_dist
       target_price = entry_price + stop_dist * Decimal(strategy.risk_reward_ratio)
   else:
       stop_price  = entry_price + stop_dist
       target_price = entry_price - stop_dist * Decimal(strategy.risk_reward_ratio)

5. EXIT WALK:
   entry_date = signal.signal_date
   cutoff_date = entry_date + timedelta(days=max_hold_days)
   mfe = mae = 0.0
   bars_walked = 0
   used_daily_fallback = False

   # Skip entry_day_bars (already used for entry)
   # Walk hold_bars_by_date in ascending date order:
   for day_date, day_bars in hold_bars_by_date:
       minute_bars = [b for b in day_bars if b.timespan == "minute"
                      and not b.is_pre_market and not b.is_after_market]
                     sorted by timestamp
       daily_bar = first(b for b in day_bars if b.timespan == "day") or None

       if minute_bars:
           bars_to_walk = minute_bars
       elif daily_bar:
           bars_to_walk = [daily_bar]
           used_daily_fallback = True
       else:
           continue

       for bar in bars_to_walk:
           # Time exit: fire at open of first bar on or after cutoff_date
           if day_date >= cutoff_date:
               exit_price = bar.open
               exit_reason = "time_exit"
               exit_date = day_date
               → return result

           low, high = Decimal(bar.low), Decimal(bar.high)
           bars_walked += 1

           # Update MFE/MAE (long)
           if not is_short:
               mfe = max(mfe, float((high - entry_price) / entry_price * 100))
               mae = max(mae, float((entry_price - low) / entry_price * 100))
           else:
               mfe = max(mfe, float((entry_price - low) / entry_price * 100))
               mae = max(mae, float((high - entry_price) / entry_price * 100))

           # Stop check (first)
           if not is_short and low <= stop_price:
               → exit at stop_price, exit_reason="stop"
           if is_short and high >= stop_price:
               → exit at stop_price, exit_reason="stop"

           # Target check
           if not is_short and high >= target_price:
               → exit at target_price, exit_reason="target"
           if is_short and low <= target_price:
               → exit at target_price, exit_reason="target"

   # No bars remain after hold window
   if bars_walked == 0:
       return SimulatedTrade(exit_reason="delisted_or_data_end")
   last_bar = last bar walked
   → exit at last_bar.close, exit_reason="delisted_or_data_end"

6. Compute returns:
   stop_distance = abs(float(entry_price) - float(stop_price))
   return_pct = (float(exit_price) - float(entry_price)) / float(entry_price) * 100
   result_r = (float(exit_price) - float(entry_price)) / stop_distance
              if stop_distance > 0 else 0.0
   fill_source = "daily-fallback" if used_daily_fallback else "intraday"

7. Return SimulatedTrade(all fields populated)
```

---

## Alternatives Considered

**Alt 1 — Extend `backtest_service._simulate_trade()` in place**
The existing function is a module-level function with 8 positional args. Adding minute-bar
support would balloon it further and provide no interface for #300 to depend on. The issue
explicitly calls for a Protocol-based design. Rejected.

**Alt 2 — DB-fetching inside `simulate()`**
The issue's `simulate(signal, strategy, bars)` signature explicitly names `bars` as a parameter.
Fixture-based unit tests require passing pre-built bar lists with no DB dependency. DB coupling
inside the simulator prevents the test pattern mandated by the acceptance criteria. Rejected.

**Alt 3 — Single-file package (`exit_simulator.py` only)**
The issue notes that issue #300 will consume the `ExitSimulator` interface. A consumer should
depend only on the thin protocol definition, not the implementation module (which will pull in
bar-fetching helpers, logging, etc.). A separate `protocols.py` is the standard Python pattern
for reusable typed interfaces. Rejected in favor of the two-file package.

---

## Assumptions

| ID | Assumption |
|----|------------|
| A1 | "Trigger" in the limit formula = `previous_close` from `signal.indicators["previous_close"]`, consistent with `backtest_service._simulate_trade()` which reads the same key for daily limit logic. |
| A2 | `bars` (caller-supplied) contains both minute and daily `StockAggregate` rows for signal_date through signal_date + max_hold_days + 7 calendar days. The simulator is pure — no DB access inside `simulate()`. |
| A3 | Regular-session minute bars are identified by `is_pre_market=False AND is_after_market=False AND timespan="minute"`, following the existing flag convention on `StockAggregate`. |
| A4 | `bars_held` counts each bar walked (minute or daily-fallback) as 1. A daily-fallback bar for a given day counts as 1, not as the number of equivalent minutes in a session. |
| A5 | MFE/MAE tracking begins from the bar *after* entry (the first hold-window bar), not the entry bar itself. |
| A6 | `max_hold_days` is measured in calendar days from `entry_date`. The time exit fires at the first available bar on or after `entry_date + timedelta(days=max_hold_days)` regardless of whether that day is a trading day. |
| A7 | When `direction == "both"`, the simulator uses long math (stop below, target above). Only `"short_only"` inverts. |

---

## Open Questions (non-blocking)

- **OQ1:** Should a bar-fetching helper (`_fetch_bars_for_simulation(ticker, signal_date, max_hold_days, db)`) be provided in `exit_simulator.py` for callers that have DB access? This is a UX-for-callers question; can be added in a follow-up without touching the Protocol.
- **OQ2:** When `direction == "both"` is combined with a specific scanner type (e.g., an oversold-bounce signal, which is long-biased), should the simulator accept an optional `signal_direction_hint` parameter to override the long default? Not required for this issue.
- **OQ3:** Should MFE/MAE be expressed as unsigned percentages (always ≥ 0) or as signed? Spec above uses unsigned (both are always non-negative). Consistent with the outcome snapshot convention in `ScannerOutcomeSummary`.
