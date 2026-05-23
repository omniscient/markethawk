from sqlalchemy.orm import Session
from sqlalchemy import func


class UniverseStatsService:
    @staticmethod
    def compute(universe_id: int, db: Session) -> dict:
        """Aggregate stats for one universe.

        Returns: {ticker_count, aggregate_count, min_date, max_date, timespans: list[str]}
        Queries StockAggregate and FuturesAggregate directly.
        No caching — callers are responsible for persisting results to cached columns.
        """
        from app.models import StockUniverseTicker
        from app.models.stock_aggregate import StockAggregate
        from app.models.futures_aggregate import FuturesAggregate

        ticker_count = (
            db.query(func.count(StockUniverseTicker.id))
            .filter(StockUniverseTicker.universe_id == universe_id)
            .scalar()
        ) or 0

        futures_tickers = [
            row.ticker
            for row in db.query(StockUniverseTicker.ticker)
            .filter(
                StockUniverseTicker.universe_id == universe_id,
                StockUniverseTicker.asset_class == "futures",
            )
            .all()
        ]
        stock_tickers = [
            row.ticker
            for row in db.query(StockUniverseTicker.ticker)
            .filter(
                StockUniverseTicker.universe_id == universe_id,
                StockUniverseTicker.asset_class != "futures",
            )
            .all()
        ]

        count_aggs = 0
        min_date = None
        max_date = None

        if stock_tickers:
            stock_stats = (
                db.query(
                    func.count(StockAggregate.id),
                    func.min(StockAggregate.timestamp),
                    func.max(StockAggregate.timestamp),
                )
                .filter(StockAggregate.ticker.in_(stock_tickers))
                .first()
            )
            if stock_stats and stock_stats[0]:
                count_aggs += stock_stats[0]
                min_date = (
                    stock_stats[1] if min_date is None
                    else (min(min_date, stock_stats[1]) if stock_stats[1] else min_date)
                )
                max_date = (
                    stock_stats[2] if max_date is None
                    else (max(max_date, stock_stats[2]) if stock_stats[2] else max_date)
                )

        if futures_tickers:
            futures_stats = (
                db.query(
                    func.count(FuturesAggregate.id),
                    func.min(FuturesAggregate.timestamp),
                    func.max(FuturesAggregate.timestamp),
                )
                .filter(FuturesAggregate.symbol.in_(futures_tickers))
                .first()
            )
            if futures_stats and futures_stats[0]:
                count_aggs += futures_stats[0]
                min_date = (
                    futures_stats[1] if min_date is None
                    else (min(min_date, futures_stats[1]) if futures_stats[1] else min_date)
                )
                max_date = (
                    futures_stats[2] if max_date is None
                    else (max(max_date, futures_stats[2]) if futures_stats[2] else max_date)
                )

        timespans_set: set = set()
        if stock_tickers:
            for row in (
                db.query(StockAggregate.timespan, StockAggregate.multiplier)
                .filter(StockAggregate.ticker.in_(stock_tickers))
                .distinct()
                .all()
            ):
                label = f"{row.multiplier}{row.timespan}" if row.multiplier > 1 else row.timespan
                timespans_set.add(label)
        if futures_tickers:
            for row in (
                db.query(FuturesAggregate.timespan, FuturesAggregate.multiplier)
                .filter(FuturesAggregate.symbol.in_(futures_tickers))
                .distinct()
                .all()
            ):
                label = f"{row.multiplier}{row.timespan}" if row.multiplier > 1 else row.timespan
                timespans_set.add(label)

        return {
            "ticker_count": ticker_count,
            "aggregate_count": count_aggs,
            "min_date": min_date,
            "max_date": max_date,
            "timespans": sorted(timespans_set),
        }
