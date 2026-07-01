"""Replay ledger metrics and analytics."""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.replay_trade import ReplayTrade


@dataclass
class MetricsResult:
    total_trades: int
    hit_rate: float | None
    expectancy_r: float | None
    profit_factor: float | None
    max_drawdown_r: float | None
    avg_bars_held: float | None
    median_bars_held: float | None
    avg_mfe_pct: float | None
    avg_mae_pct: float | None
    mfe_mae_ratio: float | None
    equity_curve: list[dict]
    calendar_decay: list[dict]
    holding_period_decay: list[dict]
    regime_breakdown: list[dict]

    def as_metrics_json(self) -> dict:
        return {
            "headline": {
                "total_trades": self.total_trades,
                "hit_rate": self.hit_rate,
                "expectancy_r": self.expectancy_r,
                "profit_factor": self.profit_factor,
                "max_drawdown_r": self.max_drawdown_r,
                "avg_bars_held": self.avg_bars_held,
                "median_bars_held": self.median_bars_held,
                "avg_mfe_pct": self.avg_mfe_pct,
                "avg_mae_pct": self.avg_mae_pct,
                "mfe_mae_ratio": self.mfe_mae_ratio,
            },
            "equity_curve": self.equity_curve,
            "calendar_decay": self.calendar_decay,
            "holding_period_decay": self.holding_period_decay,
            "regime_breakdown": self.regime_breakdown,
        }


def _f(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _quarter(day) -> str:
    return f"{day.year}-Q{((day.month - 1) // 3) + 1}"


def _bucket_stats(trades: list[ReplayTrade]) -> dict:
    values = [_f(trade.return_r) for trade in trades if trade.return_r is not None]
    if not values:
        return {
            "n": len(trades),
            "trades": len(trades),
            "hit_rate": None,
            "expectancy_r": None,
            "profit_factor": None,
            "avg_mfe_pct": None,
        }
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else None
    mfes = [_f(trade.mfe_pct) for trade in trades if trade.mfe_pct is not None]
    return {
        "n": len(values),
        "trades": len(values),
        "hit_rate": len(wins) / len(values),
        "expectancy_r": sum(values) / len(values),
        "profit_factor": profit_factor,
        "avg_mfe_pct": statistics.mean(mfes) if mfes else None,
    }


class MetricsComputer:
    def __init__(self, db: Session):
        self._db = db

    def compute(self, run_id: int) -> MetricsResult:
        trades = (
            self._db.query(ReplayTrade)
            .filter(ReplayTrade.replay_run_id == run_id)
            .order_by(ReplayTrade.signal_date.asc(), ReplayTrade.id.asc())
            .all()
        )
        values = [_f(trade.return_r) for trade in trades if trade.return_r is not None]
        if not values:
            return MetricsResult(
                total_trades=0,
                hit_rate=None,
                expectancy_r=None,
                profit_factor=None,
                max_drawdown_r=None,
                avg_bars_held=None,
                median_bars_held=None,
                avg_mfe_pct=None,
                avg_mae_pct=None,
                mfe_mae_ratio=None,
                equity_curve=[],
                calendar_decay=[],
                holding_period_decay=[],
                regime_breakdown=[],
            )

        wins = [value for value in values if value > 0]
        losses = [value for value in values if value < 0]
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else None
        cumulative = 0.0
        peak = 0.0
        max_drawdown = 0.0
        equity_curve = []
        for trade, value in zip(
            [trade for trade in trades if trade.return_r is not None], values
        ):
            cumulative += value
            peak = max(peak, cumulative)
            max_drawdown = max(max_drawdown, peak - cumulative)
            equity_curve.append(
                {"date": trade.signal_date.isoformat(), "cumulative_r": cumulative}
            )

        bars = [trade.bars_held for trade in trades if trade.bars_held is not None]
        mfes = [_f(trade.mfe_pct) for trade in trades if trade.mfe_pct is not None]
        maes = [_f(trade.mae_pct) for trade in trades if trade.mae_pct is not None]
        avg_mfe = statistics.mean(mfes) if mfes else None
        avg_mae = statistics.mean(maes) if maes else None

        by_quarter: dict[str, list[ReplayTrade]] = defaultdict(list)
        by_regime: dict[tuple[str, str], list[ReplayTrade]] = defaultdict(list)
        max_hold = max(bars) if bars else 0
        for trade in trades:
            by_quarter[_quarter(trade.signal_date)].append(trade)
            by_regime[
                (trade.regime_trend or "unknown", trade.regime_vol or "normal")
            ].append(trade)

        calendar_decay = [
            {"period": period, "bucket": period, **_bucket_stats(bucket)}
            for period, bucket in sorted(by_quarter.items())
        ]
        holding_period_decay = []
        for day in range(1, max_hold + 1):
            open_trades = [
                trade
                for trade in trades
                if trade.bars_held is not None and trade.bars_held >= day
            ]
            return_values = [
                _f(trade.return_r)
                for trade in open_trades
                if trade.return_r is not None
            ]
            mfe_values = [
                _f(trade.mfe_pct) for trade in open_trades if trade.mfe_pct is not None
            ]
            holding_period_decay.append(
                {
                    "day": day,
                    "bars_held": day,
                    "avg_return_r": statistics.mean(return_values)
                    if return_values
                    else None,
                    "expectancy_r": statistics.mean(return_values)
                    if return_values
                    else None,
                    "avg_mfe_pct": statistics.mean(mfe_values) if mfe_values else None,
                    "n": len(return_values),
                    "trades": len(return_values),
                }
            )
        regime_breakdown = [
            {"trend": trend, "vol": vol, "volatility": vol, **_bucket_stats(bucket)}
            for (trend, vol), bucket in sorted(by_regime.items())
        ]

        return MetricsResult(
            total_trades=len(values),
            hit_rate=len(wins) / len(values),
            expectancy_r=sum(values) / len(values),
            profit_factor=profit_factor,
            max_drawdown_r=max_drawdown,
            avg_bars_held=statistics.mean(bars) if bars else None,
            median_bars_held=float(statistics.median(bars)) if bars else None,
            avg_mfe_pct=avg_mfe,
            avg_mae_pct=avg_mae,
            mfe_mae_ratio=(avg_mfe / avg_mae) if avg_mfe is not None and avg_mae else None,
            equity_curve=equity_curve,
            calendar_decay=calendar_decay,
            holding_period_decay=holding_period_decay,
            regime_breakdown=regime_breakdown,
        )
