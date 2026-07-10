import asyncio
import logging
import time as _time
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.core.metrics import (
    scan_data_to_detection_seconds,
    scan_duration_seconds,
    scan_failed_tickers_ratio,
    scan_last_success_timestamp,
    scanner_events_total,
)
from app.exceptions import DataFetchError, ProviderError, ScanError
from app.models.stock_aggregate import StockAggregate
from app.models.system_config import SystemConfig
from app.services.scan_enrichment import _SECTOR_ETF_MAP
from app.services.scan_orchestrator import ScannerDescriptor, register
from app.services.timeseries_forecast import compute_anomaly_score
from app.utils.session import get_market_today
from app.utils.time import ensure_utc, to_utc_naive

if TYPE_CHECKING:
    from app.models.scanner_run import ScannerRun

_TIMESFM_CONFIG_KEYS = [
    "timesfm_enabled",
    "timesfm_anomaly_threshold",
    "timesfm_min_history_bars",
    "timesfm_fallback_multiplier",
]


@dataclass(frozen=True)
class RawSignal:
    ticker: str
    daily_bars: list[StockAggregate]
    pre_market_volume: float
    volumes: list[float]
    closes: list[float]
    avg_volume_20d: float
    avg_volume_50d: Optional[float]
    previous_close: float
    relative_volume: float
    forecast: Optional[Dict[str, Any]]
    anomaly_score: Optional[float]
    threshold_method: str
    criteria_met: dict[str, bool]


@dataclass
class EnrichedSignal:
    raw: RawSignal
    day_metrics: dict
    indicators: Dict[str, Any]
    enrichment: Dict[str, Any]


def _load_timesfm_config(db: Session) -> tuple:
    """Read TimesFM thresholds from SystemConfig. Returns (enabled, threshold, min_bars, multiplier)."""
    rows = (
        db.query(SystemConfig).filter(SystemConfig.key.in_(_TIMESFM_CONFIG_KEYS)).all()
    )
    cfg = {r.key: r.value for r in rows}
    return (
        cfg.get("timesfm_enabled", "false").lower() == "true",
        float(cfg.get("timesfm_anomaly_threshold", "2.0")),
        int(cfg.get("timesfm_min_history_bars", "30")),
        float(cfg.get("timesfm_fallback_multiplier", "4.0")),
    )


def _detect(
    ticker: str,
    daily_bars: list[StockAggregate],
    pre_market_volume: float,
    timesfm_enabled: bool,
    anomaly_threshold: float,
    min_history_bars: int,
    fallback_multiplier: float,
    scanner_mod: Any,
) -> Optional[RawSignal]:
    if len(daily_bars) < 20:
        return None

    volumes = [float(b.volume) for b in daily_bars]
    closes = [float(b.close) for b in daily_bars]
    avg_volume_20d = sum(volumes[-20:]) / 20
    avg_volume_50d = sum(volumes[-50:]) / 50 if len(volumes) >= 50 else None
    previous_close = closes[-1]
    relative_volume = pre_market_volume / avg_volume_20d if avg_volume_20d > 0 else 0

    forecast = (
        scanner_mod.get_volume_forecast(ticker, volumes[-60:])
        if len(volumes) >= min_history_bars
        else None
    )
    anomaly_score = compute_anomaly_score(pre_market_volume, forecast)

    if timesfm_enabled and anomaly_score is not None:
        volume_spike_ok = anomaly_score >= anomaly_threshold
        threshold_method = "timesfm"
    else:
        volume_spike_ok = pre_market_volume > (avg_volume_20d * fallback_multiplier)
        threshold_method = "static_4x"

    criteria_met = {
        "volume_spike": volume_spike_ok,
        "minimum_volume": pre_market_volume > 100000,
        "liquidity": avg_volume_20d > 500000,
    }
    if not all(criteria_met.values()):
        return None

    return RawSignal(
        ticker=ticker,
        daily_bars=daily_bars,
        pre_market_volume=pre_market_volume,
        volumes=volumes,
        closes=closes,
        avg_volume_20d=avg_volume_20d,
        avg_volume_50d=avg_volume_50d,
        previous_close=previous_close,
        relative_volume=relative_volume,
        forecast=forecast,
        anomaly_score=anomaly_score,
        threshold_method=threshold_method,
        criteria_met=criteria_met,
    )


def _compute_volatility_regime(
    daily_bars: list[StockAggregate],
) -> tuple[Optional[float], Optional[str]]:
    if len(daily_bars) < 11:
        return None, None

    df = pd.DataFrame(
        [
            {"H": float(b.high), "L": float(b.low), "C": float(b.close)}
            for b in daily_bars
        ]
    )
    df["tr"] = pd.DataFrame(
        {
            "a": df["H"] - df["L"],
            "b": (df["H"] - df["C"].shift(1)).abs(),
            "c": (df["L"] - df["C"].shift(1)).abs(),
        }
    ).max(axis=1)
    df["atr10"] = df["tr"].rolling(window=10).mean()
    window = df["atr10"].dropna().tail(60)
    if len(window) < 10:
        return None, None

    rank_pct = window.rank(pct=True).iloc[-1]
    atr_rank = round(float(rank_pct) * 100, 2)
    if rank_pct < 0.25:
        vol_regime = "compressed"
    elif rank_pct > 0.75:
        vol_regime = "expanded"
    else:
        vol_regime = "normal"
    return atr_rank, vol_regime


def _build_timing_features(
    ticker: str,
    day_start_utc: datetime,
    day_end_utc: datetime,
    event_date: date,
    db: Session,
    _ET: Any,
) -> tuple[Optional[StockAggregate], Dict[str, Any]]:
    """Query last pre-market bar and return (bar_obj, timing_indicators_dict)."""
    last_pre = (
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
    if last_pre:
        bar_ts = last_pre.timestamp
        if bar_ts.tzinfo is None:
            bar_ts = ensure_utc(bar_ts)
        bar_ts_et = bar_ts.astimezone(_ET)
        pm_open_et = datetime.combine(event_date, time(4, 0), tzinfo=_ET)
        timing = {
            "minutes_since_premarket_open": round(
                (bar_ts_et - pm_open_et).total_seconds() / 60, 2
            ),
            "day_of_week": bar_ts_et.weekday(),
            "is_monday": bar_ts_et.weekday() == 0,
            "is_friday": bar_ts_et.weekday() == 4,
        }
    else:
        timing = {
            "minutes_since_premarket_open": None,
            "day_of_week": None,
            "is_monday": False,
            "is_friday": False,
        }
    return last_pre, timing


def _build_catalyst_features(
    enrichment: Dict[str, Any], last_pre: Any
) -> Dict[str, Any]:
    cat_tags = enrichment.get("catalyst_tags", [])
    cat_latest = enrichment.get("catalyst_latest_utc")
    result: Dict[str, Any] = {
        "has_news_catalyst": bool(cat_tags),
        "catalyst_tag_count": len(cat_tags),
        "catalyst_recency_hours": None,
    }
    if cat_latest is not None and last_pre is not None:
        ref_ts = last_pre.timestamp
        if ref_ts.tzinfo is None:
            ref_ts = ensure_utc(ref_ts)
        if cat_latest.tzinfo is None:
            cat_latest = ensure_utc(cat_latest)
        result["catalyst_recency_hours"] = round(
            (ref_ts - cat_latest).total_seconds() / 3600, 2
        )
    return result


def _build_indicators(
    raw: RawSignal,
    day_metrics: dict,
    enrichment: Dict[str, Any],
    market_context_dict: Dict[str, Any],
    sector_etf_pct_dict: Dict[str, float],
    day_start_utc: datetime,
    day_end_utc: datetime,
    event_date: date,
    db: Session,
    _ET: Any,
) -> Dict[str, Any]:
    current_price = (
        day_metrics["closing_price"]
        or day_metrics["pre_market_close"]
        or raw.previous_close
    )
    gap_pct = (
        (day_metrics["opening_price"] - raw.previous_close) / raw.previous_close * 100
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
    indicators: Dict[str, Any] = {
        "pre_market_volume": raw.pre_market_volume,
        "avg_volume_20d": int(raw.avg_volume_20d),
        "avg_volume_50d": int(raw.avg_volume_50d) if raw.avg_volume_50d else None,
        "relative_volume": round(raw.relative_volume, 2),
        "volume_spike_ratio": round(raw.pre_market_volume / raw.avg_volume_20d, 2),
        "gap_pct": round(gap_pct, 4),
        "fade_from_high_pct": round(fade_from_high_pct, 4),
        "day_range_pct": round(day_range_pct, 4),
        "volume_anomaly_score": round(raw.anomaly_score, 4)
        if raw.anomaly_score is not None
        else None,
        "predicted_volume_p50": round(raw.forecast["p50"]) if raw.forecast else None,
        "predicted_volume_p90": round(raw.forecast["p90"]) if raw.forecast else None,
        "volume_threshold_method": raw.threshold_method,
    }
    if enrichment.get("outstanding_shares"):
        indicators["float_rotation_pct"] = round(
            raw.pre_market_volume / enrichment["outstanding_shares"] * 100, 4
        )
    indicators["es_pct_from_prev_close"] = market_context_dict.get(
        "es_pct_from_prev_close"
    )
    indicators["nq_pct_from_prev_close"] = market_context_dict.get(
        "nq_pct_from_prev_close"
    )
    indicators["market_context"] = market_context_dict.get("market_context")
    _sector = enrichment.get("sector")
    _sector_etf = _SECTOR_ETF_MAP.get(_sector) if _sector else None
    indicators["sector"] = _sector
    indicators["sector_etf"] = _sector_etf
    indicators["sector_etf_pct_change"] = (
        sector_etf_pct_dict.get(_sector_etf) if _sector_etf else None
    )
    last_pre, timing = _build_timing_features(
        raw.ticker, day_start_utc, day_end_utc, event_date, db, _ET
    )
    indicators.update(timing)
    atr_rank, vol_regime = _compute_volatility_regime(raw.daily_bars)
    indicators["atr_percentile_rank"] = atr_rank
    indicators["volatility_regime"] = vol_regime
    indicators.update(_build_catalyst_features(enrichment, last_pre))
    indicators.update(
        price_direction=None,
        price_confidence=None,
        price_forecast_4h=None,
        price_forecast_1d=None,
    )
    return indicators


def _enrich_one(
    raw: RawSignal,
    enrichment_batch: Dict[str, Dict[str, Any]],
    market_context_dict: Dict[str, Any],
    sector_etf_pct_dict: Dict[str, float],
    day_start_utc: datetime,
    day_end_utc: datetime,
    event_date: date,
    db: Session,
    _ET: Any,
) -> EnrichedSignal:
    from app.services.scanner import ScannerService

    day_metrics = ScannerService.calculate_day_metrics(raw.ticker, event_date, db)
    enrichment = enrichment_batch.get(raw.ticker.upper(), {})
    indicators = _build_indicators(
        raw,
        day_metrics,
        enrichment,
        market_context_dict,
        sector_etf_pct_dict,
        day_start_utc,
        day_end_utc,
        event_date,
        db,
        _ET,
    )
    return EnrichedSignal(
        raw=raw, day_metrics=day_metrics, indicators=indicators, enrichment=enrichment
    )


def _enrich(
    raw_signals: list[RawSignal],
    enrichment_batch: Dict[str, Dict[str, Any]],
    market_context_dict: Dict[str, Any],
    sector_etf_pct_dict: Dict[str, float],
    day_start_utc: datetime,
    day_end_utc: datetime,
    event_date: date,
    db: Session,
) -> tuple[list[EnrichedSignal], list[Dict[str, Any]]]:
    _ET = ZoneInfo("America/New_York")
    enriched: list[EnrichedSignal] = []
    failed: list[Dict[str, Any]] = []
    for raw in raw_signals:
        try:
            enriched.append(
                _enrich_one(
                    raw,
                    enrichment_batch,
                    market_context_dict,
                    sector_etf_pct_dict,
                    day_start_utc,
                    day_end_utc,
                    event_date,
                    db,
                    _ET,
                )
            )
        except Exception as e:
            logging.error(
                "pre_market_scan: enrich error for %s: %s",
                raw.ticker,
                e,
                extra={"ticker": raw.ticker, "error_type": type(e).__name__},
            )
            failed.append(
                {
                    "ticker": raw.ticker,
                    "error_type": type(e).__name__,
                    "message": str(e),
                    "retryable": False,
                }
            )
    return enriched, failed


def _persist(
    enriched: list[EnrichedSignal],
    failed: list[Dict[str, Any]],
    db: Session,
    event_date: date,
    ranker_config: Optional[Dict[str, Any]],
    scanner_run: Optional[Any],
    gate_metadata: Optional[Dict[str, Any]] = None,
) -> list[Dict[str, Any]]:
    from app.services.data_readiness import DataReadinessService
    from app.services.scanner import ScannerService
    from app.services.scanner_explanations import build_pre_market_volume_explanation
    from app.services.signal_ranker import compute_signal_quality_score

    results = []
    for signal in enriched:
        signal_quality_score = None
        if (
            ranker_config
            and ranker_config.get("enabled")
            and ranker_config.get("weights")
        ):
            signal_quality_score = compute_signal_quality_score(
                signal.indicators, ranker_config["weights"]
            )
        event_gate_metadata = DataReadinessService.event_quality_gate_metadata(
            db=db,
            ticker=signal.raw.ticker,
            scanner_type="pre_market_volume_spike",
            event_date=event_date,
            base_metadata=gate_metadata,
        )
        explanation = build_pre_market_volume_explanation(
            signal,
            signal_quality_score=signal_quality_score,
            gate_metadata=event_gate_metadata,
        )
        event_dict = ScannerService._save_event(
            db=db,
            ticker=signal.raw.ticker,
            event_date=event_date,
            scanner_type="pre_market_volume_spike",
            indicators=signal.indicators,
            criteria_met=signal.raw.criteria_met,
            enrichment=signal.enrichment,
            previous_close=signal.raw.previous_close,
            opening_price=signal.day_metrics.get("opening_price", 0.0),
            closing_price=signal.day_metrics.get("closing_price"),
            ranker_config=ranker_config,
            gate_metadata=event_gate_metadata,
            explanation=explanation,
        )
        results.append(event_dict)
        scanner_events_total.labels(scanner_type="pre_market_volume_spike").inc()

    if failed and scanner_run is not None:
        scanner_run.failed_tickers = failed
        db.add(scanner_run)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return results


async def run_pre_market_scan(
    tickers: List[str],
    db: Session,
    event_date: date = None,
    scanner_run: Optional["ScannerRun"] = None,
    gate_metadata: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Run extended hours volume spike scanner using DB aggregates."""
    import app.services.scanner as _scanner_mod
    from app.services.scanner import ScannerService

    _start = _time.monotonic()
    try:
        if event_date is None:
            event_date = get_market_today()

        _ET = ZoneInfo("America/New_York")
        day_start_et = datetime.combine(event_date, datetime.min.time(), tzinfo=_ET)
        day_start_utc = to_utc_naive(day_start_et)
        day_end_utc = to_utc_naive((day_start_et + timedelta(days=1)))
        hist_start_utc = to_utc_naive(day_start_et - timedelta(days=90))

        timesfm_enabled, anomaly_threshold, min_history_bars, fallback_multiplier = (
            _load_timesfm_config(db)
        )
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
        raw_signals: List[RawSignal] = []
        failed: List[Dict[str, Any]] = []

        for ticker in tickers:
            _span = _tracer.start_span("scanner.evaluate_ticker")
            _token = _otel_context.attach(_otel_trace.set_span_in_context(_span))
            try:
                _span.set_attribute("ticker", ticker)
                _span.set_attribute("scanner_type", "pre_market_volume_spike")
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
                raw = _detect(
                    ticker,
                    daily_bars,
                    pre_market_volume,
                    timesfm_enabled,
                    anomaly_threshold,
                    min_history_bars,
                    fallback_multiplier,
                    _scanner_mod,
                )
                if raw is not None:
                    raw_signals.append(raw)
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
                _span.end()
                _otel_context.detach(_token)

        enriched, enrich_failed = _enrich(
            raw_signals,
            enrichment_batch,
            market_context_dict,
            sector_etf_pct_dict,
            day_start_utc,
            day_end_utc,
            event_date,
            db,
        )
        failed.extend(enrich_failed)
        results = _persist(
            enriched, failed, db, event_date, ranker_config, scanner_run, gate_metadata
        )
        # --- SLO metrics -------------------------------------------------------
        if not tickers or len(failed) < len(tickers):
            scan_last_success_timestamp.labels(
                scanner_type="pre_market_volume_spike"
            ).set(_time.time())
        scan_failed_tickers_ratio.labels(scanner_type="pre_market_volume_spike").set(
            len(failed) / len(tickers) if tickers else 0.0
        )
        # data-to-detection: freshest pre-market minute bar consumed vs. wall-clock now
        _max_bar_ts = (
            db.query(func.max(StockAggregate.timestamp))
            .filter(
                StockAggregate.ticker.in_(tickers),
                StockAggregate.timespan == "minute",
                StockAggregate.is_pre_market == True,
                StockAggregate.timestamp >= day_start_utc,
                StockAggregate.timestamp < day_end_utc,
            )
            .scalar()
        )
        if _max_bar_ts is not None and isinstance(_max_bar_ts, datetime):
            _bar_utc = (
                _max_bar_ts
                if _max_bar_ts.tzinfo
                else ensure_utc(_max_bar_ts)
            )
            scan_data_to_detection_seconds.labels(
                scanner_type="pre_market_volume_spike"
            ).observe((datetime.now(timezone.utc) - _bar_utc).total_seconds())
        return results
    finally:
        scan_duration_seconds.labels(scanner_type="pre_market_volume_spike").observe(
            _time.monotonic() - _start
        )


async def _run(
    tickers: list[str],
    db: Any,
    event_date: date,
    scanner_run: Optional[Any] = None,
    gate_metadata: Optional[Any] = None,
) -> list[dict]:
    return await run_pre_market_scan(
        tickers,
        db,
        event_date=event_date,
        scanner_run=scanner_run,
        gate_metadata=gate_metadata,
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
