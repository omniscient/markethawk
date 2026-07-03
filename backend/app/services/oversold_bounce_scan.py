import asyncio
import logging
import time as _time
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy.orm import Session

from app.core.metrics import (
    scan_duration_seconds,
    scan_failed_tickers_ratio,
    scan_last_success_timestamp,
    scanner_events_total,
)
from app.exceptions import DataFetchError, ProviderError, ScanError
from app.models.stock_aggregate import StockAggregate
from app.services.scan_orchestrator import ScannerDescriptor, register
from app.services.scanner_explanations import build_oversold_bounce_explanation
from app.utils.session import get_market_today
from app.utils.time import to_utc_naive

if TYPE_CHECKING:
    from app.models.scanner_run import ScannerRun


async def run_oversold_bounce_scan(
    tickers: List[str],
    db: Session,
    event_date: date = None,
    scanner_run: Optional["ScannerRun"] = None,
    gate_metadata: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """Run the Oversold Bounce (Dual RSI) scan using DB daily aggregates."""
    import app.services.scanner as _scanner_mod
    from app.services.scanner import ScannerService

    _start = _time.monotonic()
    try:
        if event_date is None:
            event_date = get_market_today()

        results = []
        failed: List[Dict[str, Any]] = []
        _ET = ZoneInfo("America/New_York")
        day_start_et = datetime.combine(event_date, datetime.min.time(), tzinfo=_ET)
        day_end_utc = to_utc_naive((day_start_et + timedelta(days=1)))
        hist_start_utc = to_utc_naive(day_start_et - timedelta(days=90))

        # Read signal ranker config once before the ticker loop
        # Oversold bounce uses a reduced feature set; scorer re-normalizes over present features
        ranker_config = _scanner_mod.load_ranker_config(db)

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
                        gate_metadata=gate_metadata,
                        explanation=build_oversold_bounce_explanation(
                            indicators=indicators,
                            criteria_met=criteria_met,
                            gate_metadata=gate_metadata,
                        ),
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
        if not tickers or len(failed) < len(tickers):
            scan_last_success_timestamp.labels(scanner_type="oversold_bounce").set(
                _time.time()
            )
        scan_failed_tickers_ratio.labels(scanner_type="oversold_bounce").set(
            len(failed) / max(1, len(tickers))
        )
        return results
    finally:
        scan_duration_seconds.labels(scanner_type="oversold_bounce").observe(
            _time.monotonic() - _start
        )


async def _run(
    tickers: list[str],
    db: Any,
    event_date: date,
    scanner_run: Optional[Any] = None,
    gate_metadata: Optional[Any] = None,
) -> list[dict]:
    return await run_oversold_bounce_scan(
        tickers,
        db,
        event_date=event_date,
        scanner_run=scanner_run,
        gate_metadata=gate_metadata,
    )


register(
    ScannerDescriptor(
        key="oversold_bounce",
        display_name="Oversold Bounce",
        description="Identifies oversold stocks showing early reversal signals.",
        run=_run,
        supports_date_range=True,
    )
)
