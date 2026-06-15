"""
Backtest service — daily-bar replay of TradingStrategy vs scanner signals.

Survivorship-bias rules (issue #301 addendum):
- Tickers are included by presence of StockAggregate bars, NOT current tradability.
- Delisted-mid-trade positions exit at the last available close (tagged delisted_or_data_end).
- Every run carries signals_skipped_no_data, trades_exited_on_data_end, universe_as_of, bars_source.

Signal sourcing:
- First queries existing ScannerEvent rows for the ticker/date/scanner_type.
- Falls back to scan_orchestrator.run() in-memory for missing dates (never written to scanner_events).

Conservative intrabar rule:
- If a daily bar's low <= stop AND high >= target → count the stop (worst-case assumption).
"""

import asyncio
import logging
import statistics
import uuid as _uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

EXIT_STOP = "stop"
EXIT_TARGET = "target"
EXIT_TIME_STOP = "time_stop"
EXIT_DELISTED = "delisted_or_data_end"
EXIT_NO_ENTRY = "no_entry_bar"


@dataclass
class SimulatedTrade:
    ticker: str
    signal_date: date
    source_event_id: Optional[int]
    signal_indicators: dict

    entry_date: Optional[date] = None
    entry_price: Optional[Decimal] = None
    exit_date: Optional[date] = None
    exit_price: Optional[Decimal] = None
    exit_reason: Optional[str] = None
    hold_sessions: Optional[int] = None
    result_r: Optional[float] = None
    stop_price: Optional[Decimal] = None
    target_price: Optional[Decimal] = None


@dataclass
class BacktestResult:
    run_uuid: str
    total_signals: int = 0
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: Optional[float] = None
    profit_factor: Optional[float] = None
    expectancy_r: Optional[float] = None
    max_drawdown_r: Optional[float] = None
    avg_hold_sessions: Optional[float] = None
    median_hold_sessions: Optional[float] = None
    signals_skipped_no_data: int = 0
    trades_exited_on_data_end: int = 0
    universe_as_of: Optional[str] = None
    bars_source: Optional[str] = None
    strategy_snapshot: Optional[dict] = None
    trades: list = field(default_factory=list)


def _get_daily_bars(
    ticker: str,
    from_date: date,
    to_date: date,
    db: Session,
) -> list:
    """
    Return daily StockAggregate bars for a ticker in ascending date order.
    Uses bar presence (not current tradability) for survivorship-bias avoidance.
    """
    from datetime import datetime, timezone

    from sqlalchemy import and_

    from app.models.stock_aggregate import StockAggregate

    from_dt = datetime(
        from_date.year, from_date.month, from_date.day, tzinfo=timezone.utc
    )
    to_dt = datetime(
        to_date.year, to_date.month, to_date.day, 23, 59, 59, tzinfo=timezone.utc
    )

    rows = (
        db.query(StockAggregate)
        .filter(
            and_(
                StockAggregate.ticker == ticker,
                StockAggregate.timespan == "day",
                StockAggregate.multiplier == 1,
                StockAggregate.timestamp >= from_dt,
                StockAggregate.timestamp <= to_dt,
                StockAggregate.is_pre_market.is_(False),
                StockAggregate.is_after_market.is_(False),
            )
        )
        .order_by(StockAggregate.timestamp.asc())
        .all()
    )
    return rows


def _simulate_trade(
    entry_bar,
    subsequent_bars: list,
    stop_pct: float,
    risk_reward_ratio: float,
    entry_type: str,
    limit_offset_pct: float,
    max_hold_sessions: int,
    signal_previous_close: Optional[float] = None,
) -> tuple[
    Optional[Decimal],
    Optional[Decimal],
    Optional[str],
    int,
    Optional[Decimal],
    Optional[Decimal],
]:
    """
    Simulate one trade from an entry bar + ordered subsequent bars.

    Returns: (entry_price, exit_price, exit_reason, hold_sessions, stop_price, target_price)

    Conservative intrabar rule: if bar.low <= stop AND bar.high >= target → stop wins.
    Time stop: exits at NEXT session open after max_hold_sessions (spec req #6).
    Limit entry: uses signal_previous_close for limit_price computation (spec §Entry price).
    """
    open_price = Decimal(str(entry_bar.open))
    if entry_type == "limit":
        # Limit price = signal_previous_close * (1 + offset/100); fill at open if open <= limit_price.
        # When signal_previous_close is unavailable, treat as missing data and skip rather than
        # silently falling back to open-based limit (which always fills on positive offset).
        if signal_previous_close is None:
            return None, None, EXIT_NO_ENTRY, 0, None, None
        prev_close = Decimal(str(signal_previous_close))
        limit_price = prev_close * (1 + Decimal(str(limit_offset_pct)) / 100)
        if open_price > limit_price:
            return None, None, EXIT_NO_ENTRY, 0, None, None
        entry_price = open_price  # filled at open (at or better than limit)
    else:
        entry_price = open_price

    stop_dist = entry_price * Decimal(str(stop_pct)) / 100
    stop_price = entry_price - stop_dist
    target_price = entry_price + stop_dist * Decimal(str(risk_reward_ratio))

    if not subsequent_bars:
        return entry_price, entry_price, EXIT_DELISTED, 0, stop_price, target_price

    hold = 0
    for i, bar in enumerate(subsequent_bars):
        hold += 1
        low = Decimal(str(bar.low))
        high = Decimal(str(bar.high))
        close = Decimal(str(bar.close))

        # Conservative intrabar rule: stop is evaluated first, so a bar that touches both
        # the stop and the target in the same session counts as a stop (worst-case).
        stop_hit = low <= stop_price
        target_hit = high >= target_price

        if stop_hit:
            return entry_price, stop_price, EXIT_STOP, hold, stop_price, target_price
        if target_hit:
            return (
                entry_price,
                target_price,
                EXIT_TARGET,
                hold,
                stop_price,
                target_price,
            )

        if hold >= max_hold_sessions:
            # Exit at next session open; fall back to close if no next bar
            if i + 1 < len(subsequent_bars):
                next_open = Decimal(str(subsequent_bars[i + 1].open))
            else:
                next_open = close
            return (
                entry_price,
                next_open,
                EXIT_TIME_STOP,
                hold,
                stop_price,
                target_price,
            )

    # Bars ran out while position is open — delisting or data end
    last_close = Decimal(str(subsequent_bars[-1].close))
    return entry_price, last_close, EXIT_DELISTED, hold, stop_price, target_price


def _compute_stats(trades: list[SimulatedTrade]) -> dict:
    """Aggregate simulation stats from a list of completed SimulatedTrade objects."""
    completed = [t for t in trades if t.result_r is not None]
    if not completed:
        return {}

    wins = [t for t in completed if t.result_r > 0]
    losses = [t for t in completed if t.result_r < 0]

    win_rate = len(wins) / len(completed) if completed else None

    gross_profit = sum(t.result_r for t in wins) if wins else 0.0
    gross_loss = abs(sum(t.result_r for t in losses)) if losses else 0.0
    # gross_loss == 0 and wins exist → undefined/infinite; None means "not enough trades"
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    elif wins:
        profit_factor = float("inf")
    else:
        profit_factor = None

    expectancy_r = (
        sum(t.result_r for t in completed) / len(completed) if completed else None
    )

    # Max drawdown in R: cumulative sum, track peak then max drop from peak
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in completed:
        cumulative += t.result_r
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd

    holds = [t.hold_sessions for t in completed if t.hold_sessions is not None]
    avg_hold = statistics.mean(holds) if holds else None
    median_hold = statistics.median(holds) if holds else None

    return {
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "expectancy_r": expectancy_r,
        "max_drawdown_r": max_dd if completed else None,
        "avg_hold_sessions": avg_hold,
        "median_hold_sessions": float(median_hold) if median_hold is not None else None,
    }


def _get_signals_for_date(
    scanner_type: str,
    tickers: list[str],
    event_date: date,
    db: Session,
    fallback_loop=None,
) -> list[tuple[str, Optional[int], dict]]:
    """
    Return (ticker, source_event_id, indicators) for tickers that signaled on event_date.

    Strategy:
    1. Query existing ScannerEvent rows for this scanner_type + date.
    2. For any ticker NOT found in DB, run the scanner in-memory (never written to DB).
    """
    from app.models.scanner_event import ScannerEvent

    db_events = (
        db.query(ScannerEvent)
        .filter(
            ScannerEvent.scanner_type == scanner_type,
            ScannerEvent.event_date == event_date,
            ScannerEvent.ticker.in_(tickers),
        )
        .all()
    )

    found_tickers = {e.ticker for e in db_events}
    result = []
    for e in db_events:
        # previous_close is a ScannerEvent column, not an indicators JSON key. Fold it into
        # the indicators dict the caller reads from so limit-entry strategies can compute a
        # limit price; without this, DB-sourced limit signals always resolve to no_entry_bar.
        ind = dict(e.indicators or {})
        if e.previous_close is not None and "previous_close" not in ind:
            ind["previous_close"] = float(e.previous_close)
        result.append((e.ticker, e.id, ind))

    missing = [t for t in tickers if t not in found_tickers]
    if missing:
        try:
            descriptor = None
            try:
                from app.services import scan_orchestrator as _so

                descriptor = next(
                    (d for d in _so.get_all() if d.key == scanner_type), None
                )
            except ImportError:
                logger.warning(
                    "scan_orchestrator unavailable; skipping in-memory fallback"
                )

            if (
                descriptor is not None
                and descriptor.supports_date_range
                and fallback_loop is not None
            ):
                raw_signals = fallback_loop.run_until_complete(
                    descriptor.run(missing, db, event_date, scanner_run=None)
                )
                for sig in raw_signals:
                    ticker = sig.get("ticker")
                    if ticker:
                        result.append((ticker, None, sig.get("indicators", {})))
        except Exception as exc:
            logger.warning(
                f"In-memory scanner fallback failed for {scanner_type} on {event_date}: {exc}"
            )

    return result


def run_backtest_logic(
    run_id: int,
    scanner_type: str,
    strategy_id: int,
    universe_id: int,
    start_date: date,
    end_date: date,
    max_hold_sessions: int,
    db: Session,
) -> BacktestResult:
    """
    Core backtest simulation. Called by the Celery task.

    Deterministic: same inputs, same StockAggregate data → same output.
    """
    from datetime import datetime, timezone

    from app.models.stock_aggregate import StockAggregate
    from app.models.stock_universe_ticker import StockUniverseTicker
    from app.models.trading_strategy import TradingStrategy

    strategy = (
        db.query(TradingStrategy).filter(TradingStrategy.id == strategy_id).first()
    )
    if strategy is None:
        raise ValueError(f"TradingStrategy id={strategy_id} not found")

    stop_pct = float(strategy.stop_pct)
    if stop_pct <= 0:
        raise ValueError(
            f"TradingStrategy id={strategy_id} has stop_pct={stop_pct}; must be > 0"
        )

    # Snapshot strategy fields at run time for determinism (spec req #9, #11)
    strategy_snapshot_data = {
        "entry_type": strategy.entry_type,
        "stop_pct": str(strategy.stop_pct),
        "risk_reward_ratio": str(strategy.risk_reward_ratio),
        "limit_offset_pct": str(strategy.limit_offset_pct)
        if strategy.limit_offset_pct is not None
        else None,
    }

    # Resolve universe tickers — NOT filtered by current tradability (survivorship-bias rule)
    universe_tickers_rows = (
        db.query(StockUniverseTicker.ticker)
        .filter(StockUniverseTicker.universe_id == universe_id)
        .all()
    )
    all_tickers = [r.ticker for r in universe_tickers_rows]

    # Further filter to only tickers that have any daily bars in the replay window
    # (this is the "include by data" bias rule)
    from_dt = datetime(
        start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc
    )
    to_dt = datetime(
        end_date.year, end_date.month, end_date.day, 23, 59, 59, tzinfo=timezone.utc
    )

    tickers_with_data = set(
        row[0]
        for row in db.query(StockAggregate.ticker)
        .filter(
            StockAggregate.ticker.in_(all_tickers),
            StockAggregate.timespan == "day",
            StockAggregate.multiplier == 1,
            StockAggregate.timestamp >= from_dt,
            StockAggregate.timestamp <= to_dt,
        )
        .distinct()
        .all()
    )

    eligible_tickers = list(tickers_with_data)

    result = BacktestResult(
        run_uuid=str(_uuid.uuid4()),
        # Derived from inputs for determinism: "as of the end of the replay window"
        universe_as_of=str(end_date),
        bars_source="polygon_adjusted",
        strategy_snapshot=strategy_snapshot_data,
    )

    risk_reward_ratio = float(strategy.risk_reward_ratio)
    entry_type = strategy.entry_type
    limit_offset_pct = (
        float(strategy.limit_offset_pct) if strategy.limit_offset_pct else 0.0
    )

    # Walk each trading day in [start_date, end_date].
    # Create the asyncio loop once for in-memory scanner fallbacks to avoid creating
    # a new loop for every missing date in the day-walk.
    _fallback_loop = asyncio.new_event_loop()
    cursor = start_date
    one_day = timedelta(days=1)
    simulated_trades: list[SimulatedTrade] = []

    try:
        while cursor <= end_date:
            # Get signals for this date
            daily_signals = _get_signals_for_date(
                scanner_type, eligible_tickers, cursor, db, fallback_loop=_fallback_loop
            )
            result.total_signals += len(daily_signals)

            for ticker, source_event_id, indicators in daily_signals:
                trade = SimulatedTrade(
                    ticker=ticker,
                    signal_date=cursor,
                    source_event_id=source_event_id,
                    signal_indicators=indicators,
                )

                # Entry bar: the NEXT session's open (first daily bar after signal date).
                # Bound the search to ~5 calendar days (≈3-4 trading sessions) to prevent
                # stale-bar entry after halts or data gaps.
                next_day = cursor + one_day
                entry_bars = _get_daily_bars(
                    ticker, next_day, next_day + timedelta(days=7), db
                )

                if not entry_bars:
                    result.signals_skipped_no_data += 1
                    trade.exit_reason = EXIT_NO_ENTRY
                    simulated_trades.append(trade)
                    continue

                entry_bar = entry_bars[0]
                # Subsequent bars for simulation: fetch from entry date + 1 through a window
                # large enough to cover max_hold_sessions (add buffer for weekends/holidays).
                entry_bar_date = date(
                    entry_bar.timestamp.year,
                    entry_bar.timestamp.month,
                    entry_bar.timestamp.day,
                )
                subsequent_bars = _get_daily_bars(
                    ticker,
                    entry_bar_date + one_day,
                    entry_bar_date + timedelta(days=max_hold_sessions * 2 + 14),
                    db,
                )

                previous_close = indicators.get("previous_close")

                (
                    entry_price,
                    exit_price,
                    exit_reason,
                    hold_sessions,
                    stop_price,
                    target_price,
                ) = _simulate_trade(
                    entry_bar=entry_bar,
                    subsequent_bars=subsequent_bars,
                    stop_pct=stop_pct,
                    risk_reward_ratio=risk_reward_ratio,
                    entry_type=entry_type,
                    limit_offset_pct=limit_offset_pct,
                    max_hold_sessions=max_hold_sessions,
                    signal_previous_close=float(previous_close)
                    if previous_close is not None
                    else None,
                )

                if exit_reason == EXIT_NO_ENTRY:
                    result.signals_skipped_no_data += 1
                    trade.exit_reason = EXIT_NO_ENTRY
                    simulated_trades.append(trade)
                    continue

                entry_date_val = date(
                    entry_bar.timestamp.year,
                    entry_bar.timestamp.month,
                    entry_bar.timestamp.day,
                )

                # Compute exit_date from bars and hold_sessions
                if hold_sessions == 0:
                    exit_date_val = (
                        entry_date_val  # delisted immediately (no subsequent bars)
                    )
                elif exit_reason == EXIT_TIME_STOP:
                    # Time stop: exit at NEXT bar's open; that bar is subsequent_bars[hold_sessions]
                    next_idx = hold_sessions
                    next_bar = (
                        subsequent_bars[next_idx]
                        if next_idx < len(subsequent_bars)
                        else subsequent_bars[-1]
                    )
                    exit_date_val = date(
                        next_bar.timestamp.year,
                        next_bar.timestamp.month,
                        next_bar.timestamp.day,
                    )
                else:
                    exit_bar = subsequent_bars[hold_sessions - 1]
                    exit_date_val = date(
                        exit_bar.timestamp.year,
                        exit_bar.timestamp.month,
                        exit_bar.timestamp.day,
                    )

                trade.entry_date = entry_date_val
                trade.entry_price = entry_price
                trade.exit_date = exit_date_val
                trade.exit_reason = exit_reason
                trade.hold_sessions = hold_sessions
                trade.stop_price = stop_price
                trade.target_price = target_price

                if (
                    exit_price is not None
                    and entry_price is not None
                    and stop_price is not None
                ):
                    trade.exit_price = exit_price
                    stop_dist = float(entry_price - stop_price)
                    if stop_dist > 0:
                        trade.result_r = float(exit_price - entry_price) / stop_dist
                    else:
                        trade.result_r = 0.0

                if exit_reason == EXIT_DELISTED:
                    result.trades_exited_on_data_end += 1

                simulated_trades.append(trade)

            cursor += one_day

    finally:
        _fallback_loop.close()

    # Tally completed trades (exclude no_entry signals)
    completed = [t for t in simulated_trades if t.exit_reason != EXIT_NO_ENTRY]
    result.total_trades = len(completed)

    stats = _compute_stats(completed)
    result.wins = stats.get("wins", 0)
    result.losses = stats.get("losses", 0)
    result.win_rate = stats.get("win_rate")
    result.profit_factor = stats.get("profit_factor")
    result.expectancy_r = stats.get("expectancy_r")
    result.max_drawdown_r = stats.get("max_drawdown_r")
    result.avg_hold_sessions = stats.get("avg_hold_sessions")
    result.median_hold_sessions = stats.get("median_hold_sessions")
    result.trades = simulated_trades

    return result
