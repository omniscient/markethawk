"""Benchmark daily-bar ingestion for replay regime classification."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.exceptions import ProviderError
from app.models.stock_aggregate import StockAggregate


class BenchmarkIngestionError(Exception):
    def __init__(self, symbol: str, start: date, end: date, cause: Exception):
        super().__init__(f"Benchmark ingestion failed for {symbol} [{start}, {end}]: {cause}")
        self.symbol = symbol
        self.start = start
        self.end = end
        self.cause = cause


def _weekdays(start: date, end: date) -> set[datetime]:
    days: set[datetime] = set()
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5:
            days.add(datetime(cursor.year, cursor.month, cursor.day))
        cursor += timedelta(days=1)
    return days


class BenchmarkIngestor:
    """Gap-fill benchmark daily bars into `stock_aggregates`."""

    def __init__(self, provider):
        self._provider = provider

    def ingest(self, symbol: str, start_date: date, end_date: date, db: Session) -> int:
        start_dt = datetime(start_date.year, start_date.month, start_date.day)
        end_dt = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59)
        existing = {
            row[0].replace(tzinfo=None)
            for row in db.query(StockAggregate.timestamp)
            .filter(
                StockAggregate.ticker == symbol,
                StockAggregate.timespan == "day",
                StockAggregate.multiplier == 1,
                StockAggregate.timestamp >= start_dt,
                StockAggregate.timestamp <= end_dt,
            )
            .all()
        }
        missing = _weekdays(start_date, end_date) - existing
        if not missing:
            return 0

        from_date = min(missing).date()
        to_date = max(missing).date()
        try:
            bars = self._provider.get_bars(
                symbol=symbol,
                timespan="day",
                multiplier=1,
                from_date=str(from_date),
                to_date=str(to_date),
            )
        except ProviderError as exc:
            raise BenchmarkIngestionError(symbol, start_date, end_date, exc) from exc
        except Exception as exc:
            raise BenchmarkIngestionError(symbol, start_date, end_date, exc) from exc

        new_rows = []
        for bar in bars:
            ts = bar["timestamp"].replace(tzinfo=None)
            ts_day = datetime(ts.year, ts.month, ts.day)
            if ts_day in existing:
                continue
            new_rows.append(
                StockAggregate(
                    ticker=symbol,
                    timestamp=ts_day,
                    multiplier=1,
                    timespan="day",
                    open=bar["open"],
                    high=bar["high"],
                    low=bar["low"],
                    close=bar["close"],
                    volume=bar["volume"],
                    vwap=bar.get("vwap"),
                    transactions=bar.get("transactions"),
                    is_pre_market=False,
                    is_after_market=False,
                    provider="polygon",
                )
            )

        if not new_rows:
            return 0
        db.bulk_save_objects(new_rows)
        db.commit()
        return len(new_rows)
