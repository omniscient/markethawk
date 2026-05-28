"""
Scanner Service - Pre-market volume scanning logic.
"""

import asyncio
import logging
import time as _time
from datetime import date, datetime, time, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.core.metrics import scan_duration_seconds, scanner_events_total
from app.exceptions import DataFetchError, ProviderError, ScanError
from app.models.futures_aggregate import FuturesAggregate
from app.models.monitored_stock import MonitoredStock
from app.models.stock_aggregate import StockAggregate
from app.models.stock_split import StockSplit
from app.models.system_config import SystemConfig
from app.models.ticker_reference import TickerReference
from app.services.catalyst_parser import CatalystParser
from app.services.signal_ranker import load_ranker_config
from app.services.timeseries_forecast import compute_anomaly_score, get_volume_forecast
from app.utils.session import get_market_today

if TYPE_CHECKING:
    from app.models.scanner_run import ScannerRun

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


class ScannerService:
    """Service for running stock scanners."""

    @staticmethod
    def calculate_day_metrics_from_aggs(aggs: List[StockAggregate]) -> Dict[str, Any]:
        """Calculate detailed price metrics from a list of minute aggregates."""
        metrics = {
            "pre_market_high": 0.0,
            "pre_market_low": 0.0,
            "pre_market_open": 0.0,
            "pre_market_close": 0.0,
            "regular_high": 0.0,
            "regular_low": 0.0,
            "opening_price": 0.0,
            "closing_price": 0.0,
            "post_market_high": 0.0,
            "post_market_low": 0.0,
            "post_market_open": 0.0,
            "post_market_close": 0.0,
            "total_day_high": 0.0,
            "total_day_low": 0.0,
            "total_volume": 0,
        }

        if not aggs:
            return metrics

        pre_aggs = [a for a in aggs if a.is_pre_market]
        reg_aggs = [a for a in aggs if not a.is_pre_market and not a.is_after_market]
        post_aggs = [a for a in aggs if a.is_after_market]

        # Total Day
        metrics["total_day_high"] = float(max(a.high for a in aggs))
        metrics["total_day_low"] = float(min(a.low for a in aggs))
        metrics["total_volume"] = sum(a.volume for a in aggs)

        # Pre Market
        if pre_aggs:
            metrics["pre_market_high"] = float(max(a.high for a in pre_aggs))
            metrics["pre_market_low"] = float(min(a.low for a in pre_aggs))
            metrics["pre_market_open"] = float(pre_aggs[0].open)
            metrics["pre_market_close"] = float(pre_aggs[-1].close)

        # Regular Market
        if reg_aggs:
            metrics["regular_high"] = float(max(a.high for a in reg_aggs))
            metrics["regular_low"] = float(min(a.low for a in reg_aggs))
            metrics["opening_price"] = float(reg_aggs[0].open)
            metrics["closing_price"] = float(reg_aggs[-1].close)

        # Post Market
        if post_aggs:
            metrics["post_market_high"] = float(max(a.high for a in post_aggs))
            metrics["post_market_low"] = float(min(a.low for a in post_aggs))
            metrics["post_market_open"] = float(post_aggs[0].open)
            metrics["post_market_close"] = float(post_aggs[-1].close)

        return metrics

    @staticmethod
    def calculate_day_metrics(
        ticker: str, event_date: date, db: Session
    ) -> Dict[str, Any]:
        """Calculate detailed price metrics for different sessions of a given day."""
        metrics = {
            "pre_market_high": 0.0,
            "pre_market_low": 0.0,
            "pre_market_open": 0.0,
            "pre_market_close": 0.0,
            "regular_high": 0.0,
            "regular_low": 0.0,
            "opening_price": 0.0,
            "closing_price": 0.0,
            "post_market_high": 0.0,
            "post_market_low": 0.0,
            "post_market_open": 0.0,
            "post_market_close": 0.0,
            "total_day_high": 0.0,
            "total_day_low": 0.0,
            "total_volume": 0,
        }

        # Get all minute aggregates for the day
        _ET = ZoneInfo("America/New_York")
        day_start_et = datetime.combine(event_date, datetime.min.time(), tzinfo=_ET)
        day_end_et = datetime.combine(event_date, datetime.max.time(), tzinfo=_ET)

        # Convert to UTC and strip tzinfo for DB comparison (since DB stores naive UTC)
        day_start_utc = day_start_et.astimezone(timezone.utc).replace(tzinfo=None)
        day_end_utc = day_end_et.astimezone(timezone.utc).replace(tzinfo=None)

        aggs = (
            db.query(StockAggregate)
            .filter(
                StockAggregate.ticker == ticker,
                StockAggregate.timestamp >= day_start_utc,
                StockAggregate.timestamp <= day_end_utc,
                StockAggregate.timespan == "minute",
            )
            .order_by(StockAggregate.timestamp.asc())
            .all()
        )

        if not aggs:
            return metrics

        pre_aggs = [a for a in aggs if a.is_pre_market]
        reg_aggs = [a for a in aggs if not a.is_pre_market and not a.is_after_market]
        post_aggs = [a for a in aggs if a.is_after_market]

        # Total Day
        metrics["total_day_high"] = float(max(a.high for a in aggs))
        metrics["total_day_low"] = float(min(a.low for a in aggs))
        metrics["total_volume"] = sum(a.volume for a in aggs)

        # Pre Market
        if pre_aggs:
            metrics["pre_market_high"] = float(max(a.high for a in pre_aggs))
            metrics["pre_market_low"] = float(min(a.low for a in pre_aggs))
            metrics["pre_market_open"] = float(pre_aggs[0].open)
            metrics["pre_market_close"] = float(pre_aggs[-1].close)

        # Regular Market
        if reg_aggs:
            metrics["regular_high"] = float(max(a.high for a in reg_aggs))
            metrics["regular_low"] = float(min(a.low for a in reg_aggs))
            metrics["opening_price"] = float(reg_aggs[0].open)
            metrics["closing_price"] = float(reg_aggs[-1].close)

        # Post Market
        if post_aggs:
            metrics["post_market_high"] = float(max(a.high for a in post_aggs))
            metrics["post_market_low"] = float(min(a.low for a in post_aggs))
            metrics["post_market_open"] = float(post_aggs[0].open)
            metrics["post_market_close"] = float(post_aggs[-1].close)

        return metrics

    @staticmethod
    def default_scan_date() -> date:
        """Most recent completed trading weekday."""
        from datetime import timedelta as _td

        d = get_market_today() - _td(days=1)
        while d.weekday() >= 5:
            d -= _td(days=1)
        return d

    @staticmethod
    def check_concurrency(
        redis_url: str, universe_id: int, scanner_type: str
    ) -> Optional[dict]:
        """Returns in-flight scan state dict if one exists, else None.
        On corrupt Redis key: clears it and returns None.
        """
        import json

        import redis as _redis

        r = _redis.Redis.from_url(redis_url, decode_responses=True)
        state_key = f"universe:{universe_id}:scan:{scanner_type}"
        existing = r.get(state_key)
        if existing:
            try:
                return json.loads(existing)
            except json.JSONDecodeError:
                r.delete(state_key)
        return None

    @staticmethod
    def resolve_date_range(
        start_date: Optional[date],
        end_date: Optional[date],
    ) -> tuple[date, date]:
        """Apply date defaults and validate ordering.
        Raises ValueError if end_date < start_date.
        """
        resolved_start = start_date or ScannerService.default_scan_date()
        resolved_end = end_date or resolved_start
        if resolved_end < resolved_start:
            raise ValueError("end_date must not be before start_date")
        return resolved_start, resolved_end

    @staticmethod
    def count_active_tickers(db: Session, universe_id: int) -> int:
        """Count active tickers in a universe. Returns count (may be 0)."""
        return (
            db.query(MonitoredStock)
            .filter(
                MonitoredStock.universe_id == universe_id,
                MonitoredStock.is_active.is_(True),
            )
            .count()
        )

    @staticmethod
    def _get_batch_enrichment_data(
        tickers: List[str], event_date: date, db: Session
    ) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any], Dict[str, Optional[float]]]:
        """Fetch common enrichment data for a list of tickers in one batch.

        Returns a 3-tuple: (ticker_batch_data, market_context_dict, sector_etf_pct_dict)
        """
        day_start_et = datetime.combine(event_date, datetime.min.time(), tzinfo=_ET)
        day_start_utc = day_start_et.astimezone(timezone.utc).replace(tzinfo=None)
        day_end_utc = (
            (day_start_et + timedelta(days=1))
            .astimezone(timezone.utc)
            .replace(tzinfo=None)
        )
        prev_day_start_utc = (
            (day_start_et - timedelta(days=1))
            .astimezone(timezone.utc)
            .replace(tzinfo=None)
        )

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
                        pct_changes[sym] = round(
                            (current - previous) / previous * 100, 4
                        )

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

    @staticmethod
    def _save_event(
        db: Session,
        ticker: str,
        event_date: date,
        scanner_type: str,
        indicators: Dict[str, Any],
        criteria_met: Dict[str, Any],
        enrichment: Dict[str, Any],
        previous_close: float = None,
        opening_price: float = None,
        closing_price: float = None,
        ranker_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        from app.services.alert_service import save_event

        return save_event(
            db=db,
            ticker=ticker,
            event_date=event_date,
            scanner_type=scanner_type,
            indicators=indicators,
            criteria_met=criteria_met,
            enrichment=enrichment,
            previous_close=previous_close,
            opening_price=opening_price,
            closing_price=closing_price,
            ranker_config=ranker_config,
        )

    @staticmethod
    async def run_pre_market_scan(
        tickers: List[str],
        db: Session,
        event_date: date = None,
        scanner_run: Optional["ScannerRun"] = None,
    ) -> List[Dict[str, Any]]:
        """Run extended hours volume spike scanner using DB aggregates."""
        _start = _time.monotonic()
        if event_date is None:
            event_date = get_market_today()

        results = []
        failed: List[Dict[str, Any]] = []
        _ET = ZoneInfo("America/New_York")
        day_start_et = datetime.combine(event_date, datetime.min.time(), tzinfo=_ET)
        day_start_utc = day_start_et.astimezone(timezone.utc).replace(tzinfo=None)
        day_end_utc = (
            (day_start_et + timedelta(days=1))
            .astimezone(timezone.utc)
            .replace(tzinfo=None)
        )
        hist_start_utc = (
            (day_start_et - timedelta(days=90))
            .astimezone(timezone.utc)
            .replace(tzinfo=None)
        )

        # Read TimesFM config once before the ticker loop
        _timesfm_config_keys = [
            "timesfm_enabled",
            "timesfm_anomaly_threshold",
            "timesfm_min_history_bars",
            "timesfm_fallback_multiplier",
        ]
        _cfg_rows = (
            db.query(SystemConfig)
            .filter(SystemConfig.key.in_(_timesfm_config_keys))
            .all()
        )
        _cfg = {r.key: r.value for r in _cfg_rows}
        timesfm_enabled = _cfg.get("timesfm_enabled", "false").lower() == "true"
        anomaly_threshold = float(_cfg.get("timesfm_anomaly_threshold", "2.0"))
        min_history_bars = int(_cfg.get("timesfm_min_history_bars", "30"))
        fallback_multiplier = float(_cfg.get("timesfm_fallback_multiplier", "4.0"))

        # Read signal ranker config once before the ticker loop
        ranker_config = load_ranker_config(db)

        (
            enrichment_batch,
            market_context_dict,
            sector_etf_pct_dict,
        ) = await asyncio.to_thread(
            ScannerService._get_batch_enrichment_data, tickers, event_date, db
        )

        for ticker in tickers:
            try:
                daily_bars = (
                    db.query(StockAggregate)
                    .filter(
                        StockAggregate.ticker == ticker,
                        StockAggregate.timespan == "day",
                        StockAggregate.timestamp >= hist_start_utc,
                        StockAggregate.timestamp < day_start_utc,
                    )
                    .order_by(StockAggregate.timestamp.asc())
                    .all()
                )

                if len(daily_bars) < 20:
                    continue

                volumes = [float(b.volume) for b in daily_bars]
                closes = [float(b.close) for b in daily_bars]

                avg_volume_20d = sum(volumes[-20:]) / 20
                avg_volume_50d = sum(volumes[-50:]) / 50 if len(volumes) >= 50 else None
                previous_close = closes[-1]

                pre_market_volume = float(
                    db.query(func.sum(StockAggregate.volume))
                    .filter(
                        StockAggregate.ticker == ticker,
                        StockAggregate.timespan == "minute",
                        StockAggregate.is_pre_market == True,
                        StockAggregate.timestamp >= day_start_utc,
                        StockAggregate.timestamp < day_end_utc,
                    )
                    .scalar()
                    or 0
                )

                relative_volume = (
                    pre_market_volume / avg_volume_20d if avg_volume_20d > 0 else 0
                )

                # TimesFM anomaly score — Phase 1a/1b
                forecast = (
                    get_volume_forecast(ticker, volumes[-60:])
                    if len(volumes) >= min_history_bars
                    else None
                )
                anomaly_score = compute_anomaly_score(pre_market_volume, forecast)

                # Phase 1b: dynamic threshold when enabled and score available
                if timesfm_enabled and anomaly_score is not None:
                    volume_spike_ok = anomaly_score >= anomaly_threshold
                    threshold_method = "timesfm"
                else:
                    volume_spike_ok = pre_market_volume > (
                        avg_volume_20d * fallback_multiplier
                    )
                    threshold_method = "static_4x"

                criteria_met = {
                    "volume_spike": volume_spike_ok,
                    "minimum_volume": pre_market_volume > 100000,
                    "liquidity": avg_volume_20d > 500000,
                }

                if all(criteria_met.values()):
                    day_metrics = ScannerService.calculate_day_metrics(
                        ticker, event_date, db
                    )
                    current_price = (
                        day_metrics["closing_price"]
                        or day_metrics["pre_market_close"]
                        or previous_close
                    )
                    gap_pct = (
                        (day_metrics["opening_price"] - previous_close)
                        / previous_close
                        * 100
                        if day_metrics["opening_price"] > 0
                        else 0
                    )
                    fade_from_high_pct = (
                        (day_metrics["regular_high"] - current_price)
                        / day_metrics["regular_high"]
                        * 100
                        if day_metrics["regular_high"] > 0
                        else 0
                    )
                    day_range_pct = (
                        (day_metrics["regular_high"] - day_metrics["regular_low"])
                        / day_metrics["regular_low"]
                        * 100
                        if day_metrics["regular_low"] > 0
                        else 0
                    )

                    indicators = {
                        "pre_market_volume": pre_market_volume,
                        "avg_volume_20d": int(avg_volume_20d),
                        "avg_volume_50d": int(avg_volume_50d)
                        if avg_volume_50d
                        else None,
                        "relative_volume": round(relative_volume, 2),
                        "volume_spike_ratio": round(
                            pre_market_volume / avg_volume_20d, 2
                        ),
                        "gap_pct": round(gap_pct, 4),
                        "fade_from_high_pct": round(fade_from_high_pct, 4),
                        "day_range_pct": round(day_range_pct, 4),
                        "volume_anomaly_score": round(anomaly_score, 4)
                        if anomaly_score is not None
                        else None,
                        "predicted_volume_p50": round(forecast["p50"])
                        if forecast
                        else None,
                        "predicted_volume_p90": round(forecast["p90"])
                        if forecast
                        else None,
                        "volume_threshold_method": threshold_method,
                    }

                    enrichment = enrichment_batch.get(ticker.upper(), {})
                    if enrichment.get("outstanding_shares"):
                        indicators["float_rotation_pct"] = round(
                            pre_market_volume / enrichment["outstanding_shares"] * 100,
                            4,
                        )

                    # --- Phase 2a feature enrichment ---

                    # Market context (batch-level, zero cost here)
                    indicators["es_pct_from_prev_close"] = market_context_dict.get(
                        "es_pct_from_prev_close"
                    )
                    indicators["nq_pct_from_prev_close"] = market_context_dict.get(
                        "nq_pct_from_prev_close"
                    )
                    indicators["market_context"] = market_context_dict.get(
                        "market_context"
                    )

                    # Sector features
                    _sector = enrichment.get("sector")
                    _sector_etf = _SECTOR_ETF_MAP.get(_sector) if _sector else None
                    indicators["sector"] = _sector
                    indicators["sector_etf"] = _sector_etf
                    indicators["sector_etf_pct_change"] = (
                        sector_etf_pct_dict.get(_sector_etf) if _sector_etf else None
                    )

                    # Timing features — derived from last pre-market bar, never datetime.now()
                    _last_pre = (
                        db.query(StockAggregate)
                        .filter(
                            StockAggregate.ticker == ticker,
                            StockAggregate.timespan == "minute",
                            StockAggregate.is_pre_market == True,
                            StockAggregate.timestamp >= day_start_utc,
                            StockAggregate.timestamp < day_end_utc,
                        )
                        .order_by(desc(StockAggregate.timestamp))
                        .first()
                    )
                    if _last_pre:
                        _bar_ts = _last_pre.timestamp
                        if _bar_ts.tzinfo is None:
                            _bar_ts = _bar_ts.replace(tzinfo=timezone.utc)
                        _bar_ts_et = _bar_ts.astimezone(_ET)
                        _pm_open_et = datetime.combine(
                            event_date, time(4, 0), tzinfo=_ET
                        )
                        indicators["minutes_since_premarket_open"] = round(
                            (_bar_ts_et - _pm_open_et).total_seconds() / 60, 2
                        )
                        indicators["day_of_week"] = _bar_ts_et.weekday()
                        indicators["is_monday"] = _bar_ts_et.weekday() == 0
                        indicators["is_friday"] = _bar_ts_et.weekday() == 4
                    else:
                        indicators["minutes_since_premarket_open"] = None
                        indicators["day_of_week"] = None
                        indicators["is_monday"] = False
                        indicators["is_friday"] = False

                    # Volatility regime — ATR_10 percentile rank within 60-day window
                    _atr_rank: Optional[float] = None
                    _vol_regime: Optional[str] = None
                    if len(daily_bars) >= 11:
                        _df = pd.DataFrame(
                            [
                                {
                                    "H": float(b.high),
                                    "L": float(b.low),
                                    "C": float(b.close),
                                }
                                for b in daily_bars
                            ]
                        )
                        _df["tr"] = pd.DataFrame(
                            {
                                "a": _df["H"] - _df["L"],
                                "b": (_df["H"] - _df["C"].shift(1)).abs(),
                                "c": (_df["L"] - _df["C"].shift(1)).abs(),
                            }
                        ).max(axis=1)
                        _df["atr10"] = _df["tr"].rolling(window=10).mean()
                        _window = _df["atr10"].dropna().tail(60)
                        if len(_window) >= 10:
                            _rank_pct = _window.rank(pct=True).iloc[-1]
                            _atr_rank = round(float(_rank_pct) * 100, 2)
                            if _rank_pct < 0.25:
                                _vol_regime = "compressed"
                            elif _rank_pct > 0.75:
                                _vol_regime = "expanded"
                            else:
                                _vol_regime = "normal"
                    indicators["atr_percentile_rank"] = _atr_rank
                    indicators["volatility_regime"] = _vol_regime

                    # Catalyst enrichment features
                    _cat_tags = enrichment.get("catalyst_tags", [])
                    _cat_latest = enrichment.get("catalyst_latest_utc")
                    indicators["has_news_catalyst"] = bool(_cat_tags)
                    indicators["catalyst_tag_count"] = len(_cat_tags)
                    if _cat_latest is not None and _last_pre is not None:
                        _ref_ts = _last_pre.timestamp
                        if _ref_ts.tzinfo is None:
                            _ref_ts = _ref_ts.replace(tzinfo=timezone.utc)
                        if _cat_latest.tzinfo is None:
                            _cat_latest = _cat_latest.replace(tzinfo=timezone.utc)
                        indicators["catalyst_recency_hours"] = round(
                            (_ref_ts - _cat_latest).total_seconds() / 3600, 2
                        )
                    else:
                        indicators["catalyst_recency_hours"] = None

                    # TimesFM price forecast keys (deferred — Phase 1 dependency #20)
                    indicators["price_direction"] = None
                    indicators["price_confidence"] = None
                    indicators["price_forecast_4h"] = None
                    indicators["price_forecast_1d"] = None

                    event_dict = ScannerService._save_event(
                        db=db,
                        ticker=ticker,
                        event_date=event_date,
                        scanner_type="pre_market_volume_spike",
                        indicators=indicators,
                        criteria_met=criteria_met,
                        enrichment=enrichment,
                        previous_close=previous_close,
                        opening_price=day_metrics["opening_price"],
                        closing_price=day_metrics["closing_price"],
                        ranker_config=ranker_config,
                    )
                    results.append(event_dict)
                    scanner_events_total.labels(
                        scanner_type="pre_market_volume_spike"
                    ).inc()
            except (ScanError, DataFetchError, ProviderError) as e:
                logging.error(
                    "pre_market_scan: domain error for %s: %s",
                    ticker,
                    e,
                    extra={"ticker": ticker, "error_type": type(e).__name__},
                )
                failed.append(
                    {
                        "ticker": ticker,
                        "error_type": type(e).__name__,
                        "message": str(e),
                        "retryable": e.is_retryable,
                    }
                )

        if failed and scanner_run is not None:
            scanner_run.failed_tickers = failed
            db.add(scanner_run)

        db.commit()
        scan_duration_seconds.labels(scanner_type="pre_market_volume_spike").observe(
            _time.monotonic() - _start
        )
        return results

    @staticmethod
    async def run_oversold_bounce_scan(
        tickers: List[str],
        db: Session,
        event_date: date = None,
        scanner_run: Optional["ScannerRun"] = None,
    ) -> List[Dict[str, Any]]:
        """Run the Oversold Bounce (Dual RSI) scan using DB daily aggregates."""
        _start = _time.monotonic()
        if event_date is None:
            event_date = get_market_today()

        results = []
        failed: List[Dict[str, Any]] = []
        _ET = ZoneInfo("America/New_York")
        day_start_et = datetime.combine(event_date, datetime.min.time(), tzinfo=_ET)
        day_end_utc = (
            (day_start_et + timedelta(days=1))
            .astimezone(timezone.utc)
            .replace(tzinfo=None)
        )
        hist_start_utc = (
            (day_start_et - timedelta(days=90))
            .astimezone(timezone.utc)
            .replace(tzinfo=None)
        )

        # Read signal ranker config once before the ticker loop
        # Oversold bounce uses a reduced feature set; scorer re-normalizes over present features
        ranker_config = load_ranker_config(db)

        enrichment_batch, _, _ = await asyncio.to_thread(
            ScannerService._get_batch_enrichment_data, tickers, event_date, db
        )

        for ticker in tickers:
            try:
                daily_bars = (
                    db.query(StockAggregate)
                    .filter(
                        StockAggregate.ticker == ticker,
                        StockAggregate.timespan == "day",
                        StockAggregate.timestamp >= hist_start_utc,
                        StockAggregate.timestamp < day_end_utc,
                    )
                    .order_by(StockAggregate.timestamp.asc())
                    .all()
                )

                if len(daily_bars) < 10:
                    continue

                df = pd.DataFrame(
                    [
                        {
                            "Close": float(b.close),
                            "Open": float(b.open),
                            "High": float(b.high),
                            "Low": float(b.low),
                            "Volume": float(b.volume),
                        }
                        for b in daily_bars
                    ]
                )

                df["vol_ma_3"] = df["Volume"].rolling(window=3).mean()
                df["prev_close"] = df["Close"].shift(1)

                def calc_rsi(series, period):
                    delta = series.diff()
                    up, down = delta.clip(lower=0), -1 * delta.clip(upper=0)
                    ema_up = up.ewm(com=period - 1, adjust=False).mean()
                    ema_down = down.ewm(com=period - 1, adjust=False).mean()
                    rs = ema_up / ema_down
                    return 100 - (100 / (1 + rs))

                df["rsi_2"] = calc_rsi(df["Close"], 2)
                df["rsi_5"] = calc_rsi(df["Close"], 5)

                df["typ_price"] = (
                    df["High"] + df["Low"] + df["Close"] + df["Open"]
                ) / 4
                df["liq"] = df["Volume"] * df["typ_price"]
                df["avg_liq_5"] = df["liq"].rolling(window=5).mean()

                df["tr"] = pd.DataFrame(
                    {
                        "tr1": df["High"] - df["Low"],
                        "tr2": (df["High"] - df["Close"].shift(1)).abs(),
                        "tr3": (df["Low"] - df["Close"].shift(1)).abs(),
                    }
                ).max(axis=1)
                df["atr_1_prev"] = df["tr"].shift(1)
                df["prev_low"] = df["Low"].shift(1)

                today = df.iloc[-1]
                yesterday = df.iloc[-2]

                vol_ok = today["vol_ma_3"] >= 500000
                price_ok = today["prev_close"] >= 5
                short_rsi_ok = yesterday["rsi_2"] < 15 and today["rsi_2"] >= 15
                long_rsi_ok = yesterday["rsi_5"] < 27 and today["rsi_5"] >= 27
                no_gap_down = today["Open"] >= today["prev_low"]

                if vol_ok and price_ok and short_rsi_ok and long_rsi_ok and no_gap_down:
                    day_metrics = ScannerService.calculate_day_metrics(
                        ticker, event_date, db
                    )
                    current_price = (
                        day_metrics["closing_price"]
                        or day_metrics["pre_market_close"]
                        or float(today["Close"])
                    )
                    gap_pct = (
                        (float(today["Open"]) - float(today["prev_close"]))
                        / float(today["prev_close"])
                        * 100
                        if float(today["prev_close"]) > 0
                        else 0
                    )
                    fade_from_high_pct = (
                        (day_metrics["regular_high"] - current_price)
                        / day_metrics["regular_high"]
                        * 100
                        if day_metrics["regular_high"] > 0
                        else 0
                    )
                    day_range_pct = (
                        (day_metrics["regular_high"] - day_metrics["regular_low"])
                        / day_metrics["regular_low"]
                        * 100
                        if day_metrics["regular_low"] > 0
                        else 0
                    )

                    indicators = {
                        "rsi_2": float(today["rsi_2"]),
                        "rsi_5": float(today["rsi_5"]),
                        "vol_ma_3": int(today["vol_ma_3"]),
                        "atr_target": float(today["atr_1_prev"]),
                        "avg_liquidity_5d": float(today["avg_liq_5"]),
                        "gap_pct": round(gap_pct, 4),
                        "fade_from_high_pct": round(fade_from_high_pct, 4),
                        "day_range_pct": round(day_range_pct, 4),
                        "relative_volume": round(
                            float(today["Volume"]) / float(today["vol_ma_3"]), 2
                        )
                        if today["vol_ma_3"] > 0
                        else 0.0,
                    }

                    criteria_met = {
                        "volume_ma_3_ok": True,
                        "price_ge_5": True,
                        "rsi_2_crossed": True,
                        "rsi_5_crossed": True,
                        "no_gap_down": True,
                    }

                    enrichment = enrichment_batch.get(ticker.upper(), {})
                    event_dict = ScannerService._save_event(
                        db=db,
                        ticker=ticker,
                        event_date=event_date,
                        scanner_type="oversold_bounce",
                        indicators=indicators,
                        criteria_met=criteria_met,
                        enrichment=enrichment,
                        previous_close=float(today["prev_close"]),
                        opening_price=float(today["Open"]),
                        closing_price=float(today["Close"]),
                        ranker_config=ranker_config,
                    )
                    results.append(event_dict)
                    scanner_events_total.labels(scanner_type="oversold_bounce").inc()
            except (ScanError, DataFetchError, ProviderError) as e:
                logging.error(
                    "oversold_bounce_scan: domain error for %s: %s",
                    ticker,
                    e,
                    extra={"ticker": ticker, "error_type": type(e).__name__},
                )
                failed.append(
                    {
                        "ticker": ticker,
                        "error_type": type(e).__name__,
                        "message": str(e),
                        "retryable": e.is_retryable,
                    }
                )

        if failed and scanner_run is not None:
            scanner_run.failed_tickers = failed
            db.add(scanner_run)

        db.commit()
        scan_duration_seconds.labels(scanner_type="oversold_bounce").observe(
            _time.monotonic() - _start
        )
        return results

    @staticmethod
    async def run_pre_market_scan_for_date(
        ticker: str, event_date: date, db: Session
    ) -> List[Dict[str, Any]]:
        return await ScannerService.run_pre_market_scan(
            [ticker], db, event_date=event_date
        )

    @staticmethod
    async def run_oversold_bounce_scan_for_date(
        ticker: str, event_date: date, db: Session
    ) -> List[Dict[str, Any]]:
        return await ScannerService.run_oversold_bounce_scan(
            [ticker], db, event_date=event_date
        )
