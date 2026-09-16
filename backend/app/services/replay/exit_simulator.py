"""Pure intraday exit simulator for replay trades."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from app.services.replay.protocols import SignalRecord, SimulatedTrade, StrategyParams

EXIT_STOP = "stop"
EXIT_TARGET = "target"
EXIT_TIME = "time_exit"
EXIT_NO_FILL = "eod-no-fill"
EXIT_DATA_END = "delisted_or_data_end"


def _as_decimal(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _bar_date(bar) -> date:
    ts = bar.timestamp
    if isinstance(ts, datetime):
        return ts.date()
    return date(ts.year, ts.month, ts.day)


def _is_regular_minute(bar) -> bool:
    ts = bar.timestamp
    is_after_open = not isinstance(ts, datetime) or ts.time() >= time(9, 30)
    return (
        getattr(bar, "timespan", None) == "minute"
        and not getattr(bar, "is_pre_market", False)
        and not getattr(bar, "is_after_market", False)
        and is_after_open
    )


class IntradayExitSimulator:
    """Resolve entries/exits by walking caller-supplied minute/daily bars."""

    def simulate(
        self,
        signal: SignalRecord,
        strategy: StrategyParams,
        bars: list,
        max_hold_days: int,
    ) -> SimulatedTrade:
        trade = SimulatedTrade(
            ticker=signal.ticker,
            signal_date=signal.signal_date,
            source_event_id=signal.source_event_id,
        )
        is_short = strategy.direction == "short_only"

        entry_day_bars = sorted(
            [
                bar
                for bar in bars
                if _bar_date(bar) == signal.signal_date and _is_regular_minute(bar)
            ],
            key=lambda bar: bar.timestamp,
        )
        if not entry_day_bars:
            trade.exit_reason = EXIT_NO_FILL
            return trade

        entry_price = self._resolve_entry_price(
            entry_day_bars=entry_day_bars,
            signal=signal,
            strategy=strategy,
            is_short=is_short,
        )
        if entry_price is None:
            trade.exit_reason = EXIT_NO_FILL
            return trade

        stop_price, target_price = self._levels(entry_price, strategy, is_short)
        trade.entry_date = signal.signal_date
        trade.entry_price = entry_price
        trade.stop_price = stop_price
        trade.target_price = target_price

        hold_bars_by_date = self._hold_bars_by_date(bars, signal.signal_date)
        return self._walk_exits(
            trade=trade,
            bars_by_date=hold_bars_by_date,
            entry_date=signal.signal_date,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            max_hold_days=max_hold_days,
            is_short=is_short,
        )

    def _resolve_entry_price(
        self,
        entry_day_bars: list,
        signal: SignalRecord,
        strategy: StrategyParams,
        is_short: bool,
    ) -> Decimal | None:
        if strategy.entry_type != "limit":
            return _as_decimal(entry_day_bars[0].open)

        previous_close = signal.indicators.get("previous_close")
        if previous_close is None:
            return None
        limit_price = _as_decimal(previous_close) * (
            Decimal("1") + _as_decimal(strategy.limit_offset_pct) / Decimal("100")
        )
        for bar in entry_day_bars:
            open_price = _as_decimal(bar.open)
            if not is_short and _as_decimal(bar.low) <= limit_price:
                return min(open_price, limit_price)
            if is_short and _as_decimal(bar.high) >= limit_price:
                return max(open_price, limit_price)
        return None

    def _levels(
        self, entry_price: Decimal, strategy: StrategyParams, is_short: bool
    ) -> tuple[Decimal, Decimal]:
        stop_distance = entry_price * _as_decimal(strategy.stop_pct) / Decimal("100")
        if is_short:
            stop_price = entry_price + stop_distance
            target_price = entry_price - (
                abs(entry_price - stop_price) * _as_decimal(strategy.risk_reward_ratio)
            )
        else:
            stop_price = entry_price - stop_distance
            target_price = entry_price + (
                abs(entry_price - stop_price) * _as_decimal(strategy.risk_reward_ratio)
            )
        return stop_price, target_price

    def _hold_bars_by_date(self, bars: list, entry_date: date) -> dict[date, list]:
        grouped: dict[date, list] = defaultdict(list)
        for bar in bars:
            day = _bar_date(bar)
            if day <= entry_date:
                continue
            grouped[day].append(bar)
        return {
            day: sorted(day_bars, key=lambda bar: bar.timestamp)
            for day, day_bars in sorted(grouped.items())
        }

    def _walk_exits(
        self,
        trade: SimulatedTrade,
        bars_by_date: dict[date, list],
        entry_date: date,
        entry_price: Decimal,
        stop_price: Decimal,
        target_price: Decimal,
        max_hold_days: int,
        is_short: bool,
    ) -> SimulatedTrade:
        cutoff_date = entry_date + timedelta(days=max_hold_days)
        mfe_pct = 0.0
        mae_pct = 0.0
        bars_walked = 0
        used_daily_fallback = False
        last_bar = None

        for day, day_bars in bars_by_date.items():
            minute_bars = [bar for bar in day_bars if _is_regular_minute(bar)]
            daily_bars = [
                bar
                for bar in day_bars
                if getattr(bar, "timespan", None) == "day"
                and getattr(bar, "multiplier", 1) == 1
            ]
            if minute_bars:
                bars_to_walk = minute_bars
            elif daily_bars:
                bars_to_walk = [daily_bars[0]]
                used_daily_fallback = True
            else:
                continue

            for bar in bars_to_walk:
                if day >= cutoff_date:
                    return self._finish(
                        trade=trade,
                        exit_date=day,
                        exit_price=_as_decimal(bar.open),
                        exit_reason=EXIT_TIME,
                        bars_held=bars_walked,
                        mfe_pct=mfe_pct,
                        mae_pct=mae_pct,
                        used_daily_fallback=used_daily_fallback,
                        is_short=is_short,
                    )

                bars_walked += 1
                last_bar = bar
                high = _as_decimal(bar.high)
                low = _as_decimal(bar.low)

                if is_short:
                    mfe_pct = max(
                        mfe_pct, float((entry_price - low) / entry_price * 100)
                    )
                    mae_pct = max(
                        mae_pct, float((high - entry_price) / entry_price * 100)
                    )
                    if high >= stop_price:
                        return self._finish(
                            trade,
                            day,
                            stop_price,
                            EXIT_STOP,
                            bars_walked,
                            mfe_pct,
                            mae_pct,
                            used_daily_fallback,
                            is_short,
                        )
                    if low <= target_price:
                        return self._finish(
                            trade,
                            day,
                            target_price,
                            EXIT_TARGET,
                            bars_walked,
                            mfe_pct,
                            mae_pct,
                            used_daily_fallback,
                            is_short,
                        )
                else:
                    mfe_pct = max(
                        mfe_pct, float((high - entry_price) / entry_price * 100)
                    )
                    mae_pct = max(
                        mae_pct, float((entry_price - low) / entry_price * 100)
                    )
                    if low <= stop_price:
                        return self._finish(
                            trade,
                            day,
                            stop_price,
                            EXIT_STOP,
                            bars_walked,
                            mfe_pct,
                            mae_pct,
                            used_daily_fallback,
                            is_short,
                        )
                    if high >= target_price:
                        return self._finish(
                            trade,
                            day,
                            target_price,
                            EXIT_TARGET,
                            bars_walked,
                            mfe_pct,
                            mae_pct,
                            used_daily_fallback,
                            is_short,
                        )

        if last_bar is None:
            trade.exit_reason = EXIT_DATA_END
            trade.bars_held = 0
            trade.fill_source = "daily-fallback" if used_daily_fallback else "intraday"
            return trade

        return self._finish(
            trade=trade,
            exit_date=_bar_date(last_bar),
            exit_price=_as_decimal(last_bar.close),
            exit_reason=EXIT_DATA_END,
            bars_held=bars_walked,
            mfe_pct=mfe_pct,
            mae_pct=mae_pct,
            used_daily_fallback=used_daily_fallback,
            is_short=is_short,
        )

    def _finish(
        self,
        trade: SimulatedTrade,
        exit_date: date,
        exit_price: Decimal,
        exit_reason: str,
        bars_held: int,
        mfe_pct: float,
        mae_pct: float,
        used_daily_fallback: bool,
        is_short: bool,
    ) -> SimulatedTrade:
        trade.exit_date = exit_date
        trade.exit_price = exit_price
        trade.exit_reason = exit_reason
        trade.bars_held = bars_held
        trade.mfe_pct = mfe_pct
        trade.mae_pct = mae_pct
        trade.fill_source = "daily-fallback" if used_daily_fallback else "intraday"

        if trade.entry_price is None or trade.stop_price is None:
            return trade
        direction_sign = Decimal("-1") if is_short else Decimal("1")
        stop_distance = abs(trade.entry_price - trade.stop_price)
        if stop_distance == 0:
            trade.result_r = 0.0
        else:
            trade.result_r = float(
                direction_sign * (exit_price - trade.entry_price) / stop_distance
            )
        trade.return_pct = float(
            direction_sign * (exit_price - trade.entry_price) / trade.entry_price * 100
        )
        return trade
