import asyncio
import logging
import time as _time
from datetime import date, datetime, time, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.core.metrics import scan_duration_seconds, scanner_events_total
from app.exceptions import DataFetchError, ProviderError, ScanError
from app.models.stock_aggregate import StockAggregate
from app.models.system_config import SystemConfig
from app.services.scan_enrichment import _SECTOR_ETF_MAP
from app.services.scan_orchestrator import ScannerDescriptor, register
from app.services.timeseries_forecast import compute_anomaly_score
from app.utils.session import get_market_today
from app.utils.time import to_utc_naive

if TYPE_CHECKING:
    from app.models.scanner_run import ScannerRun


async def run_pre_market_scan(
    tickers: List[str],
    db: Session,
    event_date: date = None,
    scanner_run: Optional["ScannerRun"] = None,
) -> List[Dict[str, Any]]:
    """Run extended hours volume spike scanner using DB aggregates."""
    import app.services.scanner as _scanner_mod
    from app.services.scanner import ScannerService

    _start = _time.monotonic()
    if event_date is None:
        event_date = get_market_today()

    results = []
    failed: List[Dict[str, Any]] = []
    _ET = ZoneInfo("America/New_York")
    day_start_et = datetime.combine(event_date, datetime.min.time(), tzinfo=_ET)
    day_start_utc = to_utc_naive(day_start_et)
    day_end_utc = to_utc_naive((day_start_et + timedelta(days=1)))
    hist_start_utc = to_utc_naive(day_start_et - timedelta(days=90))

    # Read TimesFM config once before the ticker loop
    _timesfm_config_keys = [
        "timesfm_enabled",
        "timesfm_anomaly_threshold",
        "timesfm_min_history_bars",
        "timesfm_fallback_multiplier",
    ]
    _cfg_rows = (
        db.query(SystemConfig).filter(SystemConfig.key.in_(_timesfm_config_keys)).all()
    )
    _cfg = {r.key: r.value for r in _cfg_rows}
    timesfm_enabled = _cfg.get("timesfm_enabled", "false").lower() == "true"
    anomaly_threshold = float(_cfg.get("timesfm_anomaly_threshold", "2.0"))
    min_history_bars = int(_cfg.get("timesfm_min_history_bars", "30"))
    fallback_multiplier = float(_cfg.get("timesfm_fallback_multiplier", "4.0"))

    # Read signal ranker config once before the ticker loop
    ranker_config = _scanner_mod.load_ranker_config(db)

    (
        enrichment_batch,
        market_context_dict,
        sector_etf_pct_dict,
    ) = await asyncio.to_thread(
        ScannerService._get_batch_enrichment_data, tickers, event_date, db
    )

    from opentelemetry import context as _otel_context
    from opentelemetry import trace as _otel_trace

    _tracer = _otel_trace.get_tracer(__name__)

    for ticker in tickers:
        _ticker_span = _tracer.start_span("scanner.evaluate_ticker")
        _ticker_token = _otel_context.attach(
            _otel_trace.set_span_in_context(_ticker_span)
        )
        try:
            _ticker_span.set_attribute("ticker", ticker)
            _ticker_span.set_attribute("scanner_type", "pre_market_volume_spike")
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
                _scanner_mod.get_volume_forecast(ticker, volumes[-60:])
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
                    "avg_volume_50d": int(avg_volume_50d) if avg_volume_50d else None,
                    "relative_volume": round(relative_volume, 2),
                    "volume_spike_ratio": round(pre_market_volume / avg_volume_20d, 2),
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
                indicators["market_context"] = market_context_dict.get("market_context")

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
                    _pm_open_et = datetime.combine(event_date, time(4, 0), tzinfo=_ET)
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
        finally:
            _ticker_span.end()
            _otel_context.detach(_ticker_token)

    if failed and scanner_run is not None:
        scanner_run.failed_tickers = failed
        db.add(scanner_run)

    db.commit()
    scan_duration_seconds.labels(scanner_type="pre_market_volume_spike").observe(
        _time.monotonic() - _start
    )
    return results


async def _run(
    tickers: list[str], db: Any, event_date: date, scanner_run: Optional[Any] = None
) -> list[dict]:
    return await run_pre_market_scan(
        tickers, db, event_date=event_date, scanner_run=scanner_run
    )


register(
    ScannerDescriptor(
        key="pre_market_volume_spike",
        display_name="Pre-Market Volume Spike",
        description="Detects stocks with >4x average volume in the pre-market window.",
        run=_run,
        supports_date_range=True,
    )
)
