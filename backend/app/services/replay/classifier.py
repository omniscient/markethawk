"""Deterministic rule-based benchmark regime classifier."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.models.stock_aggregate import StockAggregate


@dataclass(frozen=True)
class ReplayRegime:
    trend: str
    vol: str


class RegimeClassifier:
    DEFAULT_VOL_THRESHOLDS = {"calm_below": 0.10, "turbulent_above": 0.20}

    def __init__(self, symbol: str, vol_thresholds: dict[str, float] | None = None):
        self.symbol = symbol
        self.thresholds = self._validate_thresholds(
            vol_thresholds or self.DEFAULT_VOL_THRESHOLDS
        )
        self.regime_map: dict[date, ReplayRegime] = {}

    @staticmethod
    def _validate_thresholds(thresholds: dict[str, float]) -> dict[str, float]:
        required = {"calm_below", "turbulent_above"}
        if set(thresholds.keys()) != required:
            raise ValueError("vol_thresholds must contain calm_below and turbulent_above")
        if thresholds["calm_below"] <= 0 or thresholds["turbulent_above"] <= 0:
            raise ValueError("vol thresholds must be positive")
        if thresholds["calm_below"] >= thresholds["turbulent_above"]:
            raise ValueError("calm_below must be less than turbulent_above")
        return dict(thresholds)

    def classify(self, start_date: date, end_date: date, db: Session) -> None:
        rows = (
            db.query(StockAggregate.timestamp, StockAggregate.close)
            .filter(
                StockAggregate.ticker == self.symbol,
                StockAggregate.timespan == "day",
                StockAggregate.multiplier == 1,
            )
            .order_by(StockAggregate.timestamp.asc())
            .all()
        )
        dates: list[date] = []
        closes: list[float] = []
        for row in rows:
            ts = row.timestamp
            dates.append(ts.date() if isinstance(ts, datetime) else ts)
            closes.append(float(row.close))

        self.regime_map = {}
        log_returns: list[float | None] = [None]
        for previous, current in zip(closes, closes[1:]):
            log_returns.append(math.log(current / previous))

        for index, current_date in enumerate(dates):
            if not (start_date <= current_date <= end_date):
                continue
            trend = "unknown"
            if index >= 199:
                sma200 = sum(closes[index - 199 : index + 1]) / 200
                trend = "bull" if closes[index] > sma200 else "bear"

            vol = "normal"
            if index >= 20:
                window = [value for value in log_returns[index - 19 : index + 1] if value is not None]
                if len(window) == 20:
                    mean = sum(window) / len(window)
                    variance = sum((value - mean) ** 2 for value in window) / (len(window) - 1)
                    annualized = math.sqrt(variance) * math.sqrt(252)
                    if annualized < self.thresholds["calm_below"]:
                        vol = "calm"
                    elif annualized > self.thresholds["turbulent_above"]:
                        vol = "turbulent"

            self.regime_map[current_date] = ReplayRegime(trend=trend, vol=vol)


UNKNOWN_REGIME = ReplayRegime("unknown", "normal")


def get_benchmark_regime(classifier: RegimeClassifier, lookup_date: date) -> ReplayRegime:
    regime_map = classifier.regime_map
    if not regime_map:
        return UNKNOWN_REGIME
    sorted_dates = sorted(regime_map)
    if lookup_date < sorted_dates[0]:
        return UNKNOWN_REGIME
    for current in reversed(sorted_dates):
        if current <= lookup_date:
            return regime_map[current]
    return UNKNOWN_REGIME
