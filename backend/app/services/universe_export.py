"""
Export logic for universe aggregate data: DB queries and ZIP streaming.
Follows the universe_stats.py pattern: pure DB queries, no Celery, no Redis.
"""

import csv
import io
import zipfile
from datetime import datetime, timedelta

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.exceptions import UniverseNotFoundError
from app.models import StockUniverse, StockUniverseTicker
from app.models.futures_aggregate import FuturesAggregate
from app.models.stock_aggregate import StockAggregate


STOCK_COLS = ["timestamp", "open", "high", "low", "close", "volume", "vwap", "transactions"]
FUTURES_COLS = [
    "timestamp", "open", "high", "low", "close",
    "volume", "vwap", "transactions", "contract_month",
]


def export_aggregates(universe_id: int, request, db: Session) -> StreamingResponse:
    """
    Build and stream a ZIP file containing aggregate (OHLCV) data for the
    requested tickers. `request` is duck-typed so this service does not import
    ExportAggregatesRequest — it accesses request.tickers, request.timespan,
    request.multiplier, request.from_date, request.to_date, request.zip_format.
    ExportAggregatesRequest stays defined in routers/universe.py.
    Raises UniverseNotFoundError if the universe does not exist.
    Raises HTTPException(400) if no tickers are provided.
    """
    universe = db.query(StockUniverse).filter(StockUniverse.id == universe_id).first()
    if not universe:
        raise UniverseNotFoundError(universe_id)

    tickers = request.tickers
    if not tickers:
        raise HTTPException(status_code=400, detail="No tickers selected")

    futures_set = {
        row.ticker
        for row in db.query(StockUniverseTicker.ticker)
        .filter(
            StockUniverseTicker.universe_id == universe_id,
            StockUniverseTicker.ticker.in_(tickers),
            StockUniverseTicker.asset_class == "futures",
        )
        .all()
    }
    stock_tickers = [t for t in tickers if t not in futures_set]
    futures_tickers = [t for t in tickers if t in futures_set]

    def _date_filter(ts_col):
        filters = []
        if request.from_date:
            filters.append(ts_col >= datetime.strptime(request.from_date, "%Y-%m-%d"))
        if request.to_date:
            filters.append(
                ts_col < datetime.strptime(request.to_date, "%Y-%m-%d") + timedelta(days=1)
            )
        return filters

    def _rows_for_stock(ticker):
        q = (
            db.query(StockAggregate)
            .filter(
                StockAggregate.ticker == ticker,
                StockAggregate.timespan == request.timespan,
                StockAggregate.multiplier == request.multiplier,
                *_date_filter(StockAggregate.timestamp),
            )
            .order_by(StockAggregate.timestamp.asc())
        )
        for row in q:
            yield {
                "timestamp": row.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
                "volume": int(row.volume),
                "vwap": float(row.vwap) if row.vwap is not None else "",
                "transactions": row.transactions if row.transactions is not None else "",
            }

    def _rows_for_futures(symbol):
        q = (
            db.query(FuturesAggregate)
            .filter(
                FuturesAggregate.symbol == symbol,
                FuturesAggregate.timespan == request.timespan,
                FuturesAggregate.multiplier == request.multiplier,
                *_date_filter(FuturesAggregate.timestamp),
            )
            .order_by(FuturesAggregate.timestamp.asc())
        )
        for row in q:
            yield {
                "timestamp": row.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
                "volume": int(row.volume),
                "vwap": float(row.vwap) if row.vwap is not None else "",
                "transactions": row.transactions if row.transactions is not None else "",
                "contract_month": row.contract_month,
            }

    def _write_csv(writer, rows, include_ticker=None):
        for row in rows:
            if include_ticker:
                row = {"ticker": include_ticker, **row}
            writer.writerow(row)

    safe_name = universe.name.replace(" ", "_")
    zip_filename = f"{safe_name}_export.zip"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if request.zip_format == "single_csv":
            csv_buf = io.StringIO()
            writer = csv.DictWriter(
                csv_buf, fieldnames=["ticker"] + FUTURES_COLS, extrasaction="ignore"
            )
            writer.writeheader()
            for ticker in stock_tickers:
                _write_csv(writer, _rows_for_stock(ticker), include_ticker=ticker)
            for symbol in futures_tickers:
                _write_csv(writer, _rows_for_futures(symbol), include_ticker=symbol)
            zf.writestr(f"{safe_name}/{safe_name}_aggregates.csv", csv_buf.getvalue())
        else:
            for ticker in stock_tickers:
                csv_buf = io.StringIO()
                writer = csv.DictWriter(csv_buf, fieldnames=STOCK_COLS)
                writer.writeheader()
                _write_csv(writer, _rows_for_stock(ticker))
                zf.writestr(f"{safe_name}/{ticker}.csv", csv_buf.getvalue())
            for symbol in futures_tickers:
                csv_buf = io.StringIO()
                writer = csv.DictWriter(csv_buf, fieldnames=FUTURES_COLS)
                writer.writeheader()
                _write_csv(writer, _rows_for_futures(symbol))
                zf.writestr(f"{safe_name}/{symbol}.csv", csv_buf.getvalue())

    buf.seek(0)

    return StreamingResponse(
        iter([buf.read()]),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_filename}"'},
    )
