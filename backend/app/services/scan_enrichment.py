"""Batch ticker enrichment for scanner runs — extracted from ScannerService."""

import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.exceptions import DataFetchError, ProviderError, ScanError
from app.models.futures_aggregate import FuturesAggregate
from app.models.monitored_stock import MonitoredStock
from app.models.stock_aggregate import StockAggregate
from app.models.stock_split import StockSplit
from app.models.ticker_reference import TickerReference
from app.services.catalyst_parser import CatalystParser
from app.utils.time import to_utc_naive

_ET = ZoneInfo("America/New_York")

_SECTOR_ETF_MAP: Dict[str, str] = {
    "Technology": "XLK",
    "Financials": "XLF",
    "Health Care": "XLV",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Energy": "XLE",
    "Industrials": "XLI",
    "Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
    "Communication Services": "XLC",
}
_SECTOR_ETF_SYMBOLS = list(_SECTOR_ETF_MAP.values())


def _get_batch_enrichment_data(
    tickers: List[str], event_date: date, db: Session
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any], Dict[str, Optional[float]]]:
    """Fetch common enrichment data for a batch of tickers.
    Wraps _get_batch_enrichment_data_impl with an OpenTelemetry span.
    """
    from opentelemetry import trace as _otel_trace

    _tracer = _otel_trace.get_tracer(__name__)
    with _tracer.start_as_current_span("scanner.batch_enrichment") as _span:
        _span.set_attribute("ticker_count", len(tickers))
        return _get_batch_enrichment_data_impl(tickers, event_date, db)


def _get_batch_enrichment_data_impl(
    tickers: List[str], event_date: date, db: Session
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any], Dict[str, Optional[float]]]:
    day_start_et = datetime.combine(event_date, datetime.min.time(), tzinfo=_ET)
    day_start_utc = to_utc_naive(day_start_et)
    day_end_utc = to_utc_naive((day_start_et + timedelta(days=1)))
    prev_day_start_utc = to_utc_naive((day_start_et - timedelta(days=1)))

    # 1. Fetch MonitoredStock records
    monitored_records = (
        db.query(MonitoredStock).filter(MonitoredStock.ticker.in_(tickers)).all()
    )
    monitored_map = {r.ticker: r for r in monitored_records}

    # 2. Fetch TickerReference records
    ref_records = (
        db.query(TickerReference).filter(TickerReference.ticker.in_(tickers)).all()
    )
    ref_map = {r.ticker: r for r in ref_records}

    # 3. Recent Splits
    six_months_prior = event_date - timedelta(days=180)
    split_records = (
        db.query(StockSplit)
        .filter(
            StockSplit.ticker.in_(tickers),
            StockSplit.execution_date <= event_date,
            StockSplit.execution_date >= six_months_prior,
        )
        .order_by(desc(StockSplit.execution_date))
        .all()
    )

    split_map = {}
    for s in split_records:
        if s.ticker not in split_map:
            split_map[s.ticker] = s.execution_date.isoformat()

    # 4. Catalyst lookup via optimized batch analyzer
    catalyst_batch = CatalystParser.batch_analyze(tickers, event_date, db)

    batch_data = {}
    for ticker in tickers:
        t_upper = ticker.upper()
        monitored = monitored_map.get(t_upper)
        ref = ref_map.get(t_upper)
        cat = catalyst_batch.get(
            t_upper, {"tags": [], "summary": None, "latest_article_utc": None}
        )

        batch_data[t_upper] = {
            "market_cap": float(monitored.market_cap)
            if monitored and monitored.market_cap
            else None,
            "outstanding_shares": float(ref.share_class_shares_outstanding)
            if ref and ref.share_class_shares_outstanding
            else None,
            "recent_split_date": split_map.get(t_upper),
            "catalyst_tags": cat.get("tags", []),
            "catalyst_summary": cat.get("summary"),
            "catalyst_latest_utc": cat.get("latest_article_utc"),
            "sector": ref.sector if ref else None,
        }

    # 5. ES/NQ market context — two most recent daily bars per symbol
    market_context_dict: Dict[str, Any] = {
        "es_pct_from_prev_close": None,
        "nq_pct_from_prev_close": None,
        "market_context": None,
    }
    try:
        futures_bars = (
            db.query(FuturesAggregate)
            .filter(
                FuturesAggregate.symbol.in_(["ES", "NQ"]),
                FuturesAggregate.timespan == "day",
                FuturesAggregate.timestamp < day_end_utc,
            )
            .order_by(FuturesAggregate.symbol, FuturesAggregate.timestamp.desc())
            .all()
        )
        symbol_bars: Dict[str, list] = {}
        for bar in futures_bars:
            symbol_bars.setdefault(bar.symbol, []).append(bar)

        pct_changes: Dict[str, float] = {}
        for sym in ("ES", "NQ"):
            bars = symbol_bars.get(sym, [])
            if len(bars) >= 2:
                current = float(bars[0].close)
                previous = float(bars[1].close)
                if previous > 0:
                    pct_changes[sym] = round((current - previous) / previous * 100, 4)

        if "ES" in pct_changes:
            market_context_dict["es_pct_from_prev_close"] = pct_changes["ES"]
        if "NQ" in pct_changes:
            market_context_dict["nq_pct_from_prev_close"] = pct_changes["NQ"]

        if "ES" in pct_changes and "NQ" in pct_changes:
            es, nq = pct_changes["ES"], pct_changes["NQ"]
            if es > 0.1 and nq > 0.1:
                market_context_dict["market_context"] = "risk_on"
            elif es < -0.1 and nq < -0.1:
                market_context_dict["market_context"] = "risk_off"
            else:
                market_context_dict["market_context"] = "neutral"
    except (ScanError, DataFetchError, ProviderError) as e:
        logging.warning("Market context enrichment failed (domain error): %s", e)
    except Exception as e:
        logging.warning("Market context enrichment failed (unexpected): %s", e)

    # 6. Sector ETF pre-market bars
    sector_etf_pct_dict: Dict[str, Optional[float]] = {
        s: None for s in _SECTOR_ETF_SYMBOLS
    }
    try:
        etf_daily = (
            db.query(StockAggregate)
            .filter(
                StockAggregate.ticker.in_(_SECTOR_ETF_SYMBOLS),
                StockAggregate.timespan == "day",
                StockAggregate.timestamp >= prev_day_start_utc,
                StockAggregate.timestamp < day_start_utc,
            )
            .order_by(StockAggregate.ticker, StockAggregate.timestamp.desc())
            .all()
        )
        etf_prev_closes: Dict[str, float] = {}
        for bar in etf_daily:
            if bar.ticker not in etf_prev_closes:
                etf_prev_closes[bar.ticker] = float(bar.close)

        etf_pm = (
            db.query(StockAggregate)
            .filter(
                StockAggregate.ticker.in_(_SECTOR_ETF_SYMBOLS),
                StockAggregate.timespan == "minute",
                StockAggregate.is_pre_market == True,
                StockAggregate.timestamp >= day_start_utc,
                StockAggregate.timestamp < day_end_utc,
            )
            .order_by(StockAggregate.ticker, StockAggregate.timestamp.asc())
            .all()
        )
        etf_last_bar: Dict[str, StockAggregate] = {}
        for bar in etf_pm:
            etf_last_bar[bar.ticker] = bar  # ascending order → last write wins

        for etf_sym in _SECTOR_ETF_SYMBOLS:
            if etf_sym in etf_last_bar and etf_sym in etf_prev_closes:
                current = float(etf_last_bar[etf_sym].close)
                prev = etf_prev_closes[etf_sym]
                if prev > 0:
                    sector_etf_pct_dict[etf_sym] = round(
                        (current - prev) / prev * 100, 4
                    )
    except (ScanError, DataFetchError, ProviderError) as e:
        logging.warning("Sector ETF enrichment failed (domain error): %s", e)
    except Exception as e:
        logging.warning("Sector ETF enrichment failed (unexpected): %s", e)

    return batch_data, market_context_dict, sector_etf_pct_dict
