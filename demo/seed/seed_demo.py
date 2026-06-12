from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal


DEMO_USERNAME = "demo"
DEMO_PASSWORD = "markethawk-demo"
DEMO_SOURCE = "markethawk_demo"
DEMO_DATE = date(2026, 1, 15)
DEMO_UNIVERSE_ID = 9001


def _dt(hour: int, minute: int = 0, day_offset: int = 0) -> datetime:
    return datetime.combine(DEMO_DATE + timedelta(days=day_offset), time(hour, minute))


def _money(value: str) -> Decimal:
    return Decimal(value)


def build_dataset() -> dict:
    scanner_events = [
        {
            "key": "nvda_pre_market",
            "ticker": "NVDA",
            "event_date": DEMO_DATE,
            "scanner_type": "pre_market_volume",
            "summary": "NVDA showing 6.2x average pre-market volume with a 2.3% gap up",
            "severity": "high",
            "previous_close": "132.50",
            "opening_price": "135.55",
            "closing_price": "137.45",
            "signal_quality_score": 91.5,
            "indicators": {
                "relative_volume": 6.2,
                "volume_spike_ratio": 6.2,
                "pre_market_volume": 1850000,
                "avg_volume_20d": 298000,
                "gap_pct": 2.3,
            },
            "criteria_met": {"volume_spike": True, "gap_up": True, "min_price": True},
        },
        {
            "key": "amd_pre_market",
            "ticker": "AMD",
            "event_date": DEMO_DATE,
            "scanner_type": "pre_market_volume",
            "summary": "AMD showing 4.8x average pre-market volume with a 1.5% gap up",
            "severity": "medium",
            "previous_close": "165.20",
            "opening_price": "167.68",
            "closing_price": "168.60",
            "signal_quality_score": 76.0,
            "indicators": {
                "relative_volume": 4.8,
                "volume_spike_ratio": 4.8,
                "pre_market_volume": 920000,
                "avg_volume_20d": 191000,
                "gap_pct": 1.5,
            },
            "criteria_met": {"volume_spike": True, "gap_up": True, "min_price": True},
        },
        {
            "key": "msft_liquidity",
            "ticker": "MSFT",
            "event_date": DEMO_DATE - timedelta(days=1),
            "scanner_type": "liquidity_hunt",
            "summary": "MSFT unusual post-market volume at 3.8x average with tight spread",
            "severity": "high",
            "previous_close": "428.50",
            "opening_price": "430.20",
            "closing_price": "431.10",
            "signal_quality_score": 84.0,
            "indicators": {
                "relative_volume": 3.8,
                "volume_spike_ratio": 3.8,
                "post_market_volume": 680000,
                "spread_pct": 0.3,
            },
            "criteria_met": {"volume_spike": True, "spread_tight": True, "min_price": True},
        },
        {
            "key": "tsla_liquidity",
            "ticker": "TSLA",
            "event_date": DEMO_DATE - timedelta(days=1),
            "scanner_type": "liquidity_hunt",
            "summary": "TSLA post-market volume at 3.2x average with elevated spread",
            "severity": "medium",
            "previous_close": "248.90",
            "opening_price": "251.40",
            "closing_price": "247.80",
            "signal_quality_score": 58.0,
            "indicators": {
                "relative_volume": 3.2,
                "volume_spike_ratio": 3.2,
                "post_market_volume": 520000,
                "spread_pct": 0.7,
            },
            "criteria_met": {"volume_spike": True, "spread_tight": False, "min_price": True},
        },
        {
            "key": "amzn_oversold",
            "ticker": "AMZN",
            "event_date": DEMO_DATE - timedelta(days=2),
            "scanner_type": "oversold_bounce",
            "summary": "AMZN RSI at 28.5 with early reversal candle pattern",
            "severity": "low",
            "previous_close": "185.30",
            "opening_price": "183.90",
            "closing_price": "186.40",
            "signal_quality_score": 63.5,
            "indicators": {
                "rsi_14": 28.5,
                "reversal_candle": True,
                "volume_confirmation": False,
            },
            "criteria_met": {"rsi_oversold": True, "reversal_signal": True, "min_price": True},
        },
    ]

    return {
        "tickers": [
            {
                "ticker": "NVDA",
                "name": "NVIDIA Corporation",
                "market_cap": 2800000000000,
                "sector": "Technology",
                "industry": "Semiconductors",
                "primary_exchange": "XNAS",
            },
            {
                "ticker": "AMD",
                "name": "Advanced Micro Devices",
                "market_cap": 230000000000,
                "sector": "Technology",
                "industry": "Semiconductors",
                "primary_exchange": "XNAS",
            },
            {
                "ticker": "MSFT",
                "name": "Microsoft Corporation",
                "market_cap": 3100000000000,
                "sector": "Technology",
                "industry": "Software",
                "primary_exchange": "XNAS",
            },
            {
                "ticker": "TSLA",
                "name": "Tesla, Inc.",
                "market_cap": 780000000000,
                "sector": "Consumer Cyclical",
                "industry": "Auto Manufacturers",
                "primary_exchange": "XNAS",
            },
            {
                "ticker": "AMZN",
                "name": "Amazon.com, Inc.",
                "market_cap": 1900000000000,
                "sector": "Consumer Cyclical",
                "industry": "Internet Retail",
                "primary_exchange": "XNAS",
            },
        ],
        "universe": {
            "id": DEMO_UNIVERSE_ID,
            "name": "MarketHawk Demo Universe",
            "description": "Credential-free sample universe for the MarketHawk demo",
            "criteria": {"source": DEMO_SOURCE, "theme": "large_cap_momentum"},
        },
        "configs": [
            {
                "name": "Demo - Pre-market Volume",
                "scanner_type": "pre_market_volume",
                "description": "Demo scanner for relative pre-market volume and gap context",
                "parameters": {"universe_id": DEMO_UNIVERSE_ID, "min_volume": 100000},
                "criteria": {"relative_volume_min": 4.0, "gap_pct_min": 1.0},
                "run_frequency": "manual",
            },
            {
                "name": "Demo - Liquidity Hunt",
                "scanner_type": "liquidity_hunt",
                "description": "Demo scanner for unusual liquidity and spread context",
                "parameters": {"universe_id": DEMO_UNIVERSE_ID, "min_relative_volume": 3.0},
                "criteria": {"relative_volume_min": 3.0, "spread_pct_max": 0.5},
                "run_frequency": "manual",
            },
            {
                "name": "Demo - Oversold Bounce",
                "scanner_type": "oversold_bounce",
                "description": "Demo scanner for oversold reversal setups",
                "parameters": {"universe_id": DEMO_UNIVERSE_ID, "rsi_max": 30},
                "criteria": {"rsi_14_max": 30, "requires_reversal": True},
                "run_frequency": "manual",
            },
        ],
        "scanner_runs": [
            {
                "scanner_type": "pre_market_volume",
                "stocks_scanned": 5,
                "events_detected": 2,
                "execution_time_ms": 1180,
                "created_at": _dt(9, 28),
            },
            {
                "scanner_type": "liquidity_hunt",
                "stocks_scanned": 5,
                "events_detected": 2,
                "execution_time_ms": 940,
                "created_at": _dt(16, 15, -1),
            },
            {
                "scanner_type": "oversold_bounce",
                "stocks_scanned": 5,
                "events_detected": 1,
                "execution_time_ms": 1020,
                "created_at": _dt(15, 55, -2),
            },
        ],
        "scanner_events": scanner_events,
        "watchlist": [
            {"symbol": "NVDA", "notes": "markethawk_demo: high relative volume today"},
            {"symbol": "AMD", "notes": "markethawk_demo: moderate pre-market gap setup"},
            {"symbol": "MSFT", "notes": "markethawk_demo: post-market liquidity activity"},
        ],
        "reviews": [
            {
                "event_key": "nvda_pre_market",
                "verdict": "confirmed",
                "notes": "markethawk_demo: catalyst and volume both support review.",
            },
            {
                "event_key": "amd_pre_market",
                "verdict": "enhanced",
                "notes": "markethawk_demo: keep, but require stronger opening range confirmation.",
                "enhance_suggestion": {
                    "threshold": "gap_pct",
                    "current_value": 1.0,
                    "proposed_value": 1.4,
                    "rationale": "Demo review suggests filtering weaker gaps.",
                },
            },
            {
                "event_key": "tsla_liquidity",
                "verdict": "rejected",
                "reject_reason": "threshold_too_loose",
                "notes": "markethawk_demo: spread was too wide for a clean liquidity signal.",
            },
        ],
        "outcomes": [
            {
                "event_key": "nvda_pre_market",
                "reference_price": "135.55",
                "snapshots": [("30m", "137.10", "1.14"), ("1d", "137.45", "1.40")],
                "summary": {
                    "mfe_pct": "2.05",
                    "mfe_time_minutes": 75,
                    "mae_pct": "-0.45",
                    "mae_time_minutes": 12,
                    "mfe_mae_ratio": "4.56",
                    "r_multiple": "2.10",
                    "eod_pct_change": "1.40",
                    "follow_through": True,
                    "gap_filled": False,
                },
            },
            {
                "event_key": "amd_pre_market",
                "reference_price": "167.68",
                "snapshots": [("30m", "168.30", "0.37"), ("1d", "168.60", "0.55")],
                "summary": {
                    "mfe_pct": "0.85",
                    "mfe_time_minutes": 48,
                    "mae_pct": "-0.30",
                    "mae_time_minutes": 10,
                    "mfe_mae_ratio": "2.83",
                    "r_multiple": "0.80",
                    "eod_pct_change": "0.55",
                    "follow_through": True,
                    "gap_filled": False,
                },
            },
            {
                "event_key": "tsla_liquidity",
                "reference_price": "251.40",
                "snapshots": [("30m", "249.20", "-0.88"), ("1d", "247.80", "-1.43")],
                "summary": {
                    "mfe_pct": "0.20",
                    "mfe_time_minutes": 7,
                    "mae_pct": "-1.60",
                    "mae_time_minutes": 84,
                    "mfe_mae_ratio": "0.13",
                    "r_multiple": "-1.20",
                    "eod_pct_change": "-1.43",
                    "follow_through": False,
                    "gap_filled": True,
                },
            },
        ],
        "news": [
            {
                "title": "Demo catalyst: semiconductor leaders trade higher before the open",
                "author": "MarketHawk Demo",
                "published_utc": _dt(8, 5).replace(tzinfo=timezone.utc),
                "article_url": "https://demo.markethawk.local/news/semiconductor-volume",
                "description": "markethawk_demo sample news catalyst for NVDA and AMD.",
                "tickers": ["NVDA", "AMD"],
            },
            {
                "title": "Demo catalyst: cloud software demand lifts large-cap technology",
                "author": "MarketHawk Demo",
                "published_utc": _dt(7, 50, -1).replace(tzinfo=timezone.utc),
                "article_url": "https://demo.markethawk.local/news/cloud-demand",
                "description": "markethawk_demo sample news catalyst for MSFT.",
                "tickers": ["MSFT"],
            },
            {
                "title": "Demo catalyst: electric vehicle tape turns mixed after hours",
                "author": "MarketHawk Demo",
                "published_utc": _dt(16, 30, -1).replace(tzinfo=timezone.utc),
                "article_url": "https://demo.markethawk.local/news/ev-after-hours",
                "description": "markethawk_demo sample news catalyst for TSLA.",
                "tickers": ["TSLA"],
            },
        ],
        "journal_entries": [
            {
                "entry_date": DEMO_DATE,
                "content": "markethawk_demo: Reviewed semiconductor volume spikes, confirmed NVDA, enhanced AMD, rejected wide-spread TSLA liquidity.",
                "sentiment": "neutral",
            }
        ],
        "trades": [
            {
                "symbol": "NVDA",
                "status": "closed",
                "side": "long",
                "open_date": _dt(9, 36),
                "close_date": _dt(10, 45),
                "quantity": "100",
                "avg_entry_price": "136.10",
                "avg_exit_price": "137.35",
                "gross_pnl": "125.00",
                "net_pnl": "123.00",
                "commissions": "2.00",
                "return_pct": "0.92",
                "notes": "markethawk_demo: Paper trade from confirmed NVDA scanner review.",
                "executions": [
                    {"timestamp": _dt(9, 36), "side": "buy", "price": "136.10", "quantity": "100", "commission": "1.00"},
                    {"timestamp": _dt(10, 45), "side": "sell", "price": "137.35", "quantity": "100", "commission": "1.00"},
                ],
            }
        ],
        "bars": _build_bars(),
    }


def _build_bars() -> list[dict]:
    rows = []
    templates = {
        "NVDA": ("133.10", "137.45", 45000),
        "AMD": ("165.50", "168.60", 28000),
        "MSFT": ("427.80", "431.10", 15000),
    }
    for ticker, (start_price, end_price, base_volume) in templates.items():
        start = Decimal(start_price)
        end = Decimal(end_price)
        step = (end - start) / Decimal("9")
        for idx in range(10):
            close = start + (step * idx)
            open_ = close - Decimal("0.18")
            rows.append(
                {
                    "ticker": ticker,
                    "timestamp": _dt(4 + min(idx, 5), (idx % 2) * 30),
                    "open": str(open_),
                    "high": str(close + Decimal("0.35")),
                    "low": str(open_ - Decimal("0.25")),
                    "close": str(close),
                    "volume": base_volume + (idx * 18000),
                    "vwap": str((open_ + close) / Decimal("2")),
                    "is_pre_market": idx < 6,
                }
            )
    return rows


def _decimal(value: str | None) -> Decimal | None:
    return Decimal(value) if value is not None else None


def seed_database() -> None:
    from app.core.auth import hash_password
    from app.core.database import SessionLocal
    from app.models import (
        ActiveWatchlist,
        JournalEntry,
        NewsArticle,
        ScannerConfig,
        ScannerEvent,
        ScannerOutcomeSnapshot,
        ScannerOutcomeSummary,
        ScannerRun,
        SignalReview,
        StockAggregate,
        StockUniverse,
        StockUniverseTicker,
        TickerReference,
        Trade,
        TradeExecution,
        User,
    )

    dataset = build_dataset()
    db = SessionLocal()
    try:
        event_ids = [
            row.id
            for row in db.query(ScannerEvent.id)
            .filter(
                ScannerEvent.ticker.in_([event["ticker"] for event in dataset["scanner_events"]]),
                ScannerEvent.scanner_type.in_(
                    [event["scanner_type"] for event in dataset["scanner_events"]]
                ),
            )
            .all()
        ]
        if event_ids:
            db.query(ScannerOutcomeSnapshot).filter(
                ScannerOutcomeSnapshot.scanner_event_id.in_(event_ids)
            ).delete(synchronize_session=False)
            db.query(ScannerOutcomeSummary).filter(
                ScannerOutcomeSummary.scanner_event_id.in_(event_ids)
            ).delete(synchronize_session=False)
            db.query(SignalReview).filter(
                SignalReview.scanner_event_id.in_(event_ids)
            ).delete(synchronize_session=False)
            db.query(ScannerEvent).filter(ScannerEvent.id.in_(event_ids)).delete(
                synchronize_session=False
            )

        db.query(ScannerRun).filter(ScannerRun.universe_id == DEMO_UNIVERSE_ID).delete(
            synchronize_session=False
        )
        db.query(ScannerConfig).filter(ScannerConfig.universe_id == DEMO_UNIVERSE_ID).delete(
            synchronize_session=False
        )
        db.query(ActiveWatchlist).filter(
            ActiveWatchlist.notes.contains(DEMO_SOURCE)
        ).delete(synchronize_session=False)
        db.query(NewsArticle).filter(NewsArticle.provider == DEMO_SOURCE).delete(
            synchronize_session=False
        )
        db.query(TradeExecution).filter(
            TradeExecution.external_id.like(f"{DEMO_SOURCE}%")
        ).delete(synchronize_session=False)
        db.query(Trade).filter(Trade.notes.contains(DEMO_SOURCE)).delete(
            synchronize_session=False
        )
        db.query(JournalEntry).filter(JournalEntry.content.contains(DEMO_SOURCE)).delete(
            synchronize_session=False
        )
        db.query(StockAggregate).filter(StockAggregate.provider == DEMO_SOURCE).delete(
            synchronize_session=False
        )
        db.query(StockUniverseTicker).filter(
            StockUniverseTicker.universe_id == DEMO_UNIVERSE_ID
        ).delete(synchronize_session=False)
        db.query(StockUniverse).filter(StockUniverse.id == DEMO_UNIVERSE_ID).delete(
            synchronize_session=False
        )
        db.query(User).filter(User.username == DEMO_USERNAME).delete(
            synchronize_session=False
        )
        db.flush()

        for ticker in dataset["tickers"]:
            existing = db.get(TickerReference, ticker["ticker"])
            if existing:
                for key, value in ticker.items():
                    setattr(existing, key, value)
                existing.active = True
            else:
                db.add(TickerReference(active=True, **ticker))

        universe = dataset["universe"]
        db.add(
            StockUniverse(
                id=universe["id"],
                name=universe["name"],
                description=universe["description"],
                criteria=universe["criteria"],
                is_active=True,
                cached_ticker_count=len(dataset["tickers"]),
            )
        )
        for ticker in dataset["tickers"]:
            db.add(
                StockUniverseTicker(
                    universe_id=DEMO_UNIVERSE_ID,
                    ticker=ticker["ticker"],
                    asset_class="stocks",
                    data_source=DEMO_SOURCE,
                )
            )

        for config in dataset["configs"]:
            db.add(
                ScannerConfig(
                    universe_id=DEMO_UNIVERSE_ID,
                    is_active=True,
                    outcome_config={"intervals": ["30m", "1d"], "source": DEMO_SOURCE},
                    data_requirements={"timespan": "minute", "source": DEMO_SOURCE},
                    **config,
                )
            )

        for run in dataset["scanner_runs"]:
            db.add(
                ScannerRun(
                    universe_id=DEMO_UNIVERSE_ID,
                    status="completed",
                    scan_start_date=DEMO_DATE - timedelta(days=3),
                    scan_end_date=DEMO_DATE,
                    **run,
                )
            )

        event_by_key = {}
        for event in dataset["scanner_events"]:
            key = event["key"]
            row = ScannerEvent(
                ticker=event["ticker"],
                event_date=event["event_date"],
                scanner_type=event["scanner_type"],
                summary=event["summary"],
                severity=event["severity"],
                previous_close=_decimal(event["previous_close"]),
                opening_price=_decimal(event["opening_price"]),
                closing_price=_decimal(event["closing_price"]),
                signal_quality_score=event["signal_quality_score"],
                indicators=event["indicators"],
                criteria_met=event["criteria_met"],
                metadata_={"source": DEMO_SOURCE, "demo_key": key},
            )
            db.add(row)
            db.flush()
            event_by_key[key] = row

        for watch in dataset["watchlist"]:
            db.add(
                ActiveWatchlist(
                    symbol=watch["symbol"],
                    security_type="STK",
                    exchange="SMART",
                    notes=watch["notes"],
                )
            )

        for review in dataset["reviews"]:
            db.add(
                SignalReview(
                    scanner_event_id=event_by_key[review["event_key"]].id,
                    verdict=review["verdict"],
                    reject_reason=review.get("reject_reason"),
                    notes=review["notes"],
                    enhance_suggestion=review.get("enhance_suggestion"),
                    reviewed_by=DEMO_USERNAME,
                )
            )

        for outcome in dataset["outcomes"]:
            event = event_by_key[outcome["event_key"]]
            for interval_key, snapshot_price, pct_change in outcome["snapshots"]:
                db.add(
                    ScannerOutcomeSnapshot(
                        scanner_event_id=event.id,
                        interval_key=interval_key,
                        reference_price=_decimal(outcome["reference_price"]),
                        snapshot_price=_decimal(snapshot_price),
                        pct_change=_decimal(pct_change),
                        high_since_signal=_decimal(snapshot_price),
                        low_since_signal=_decimal(outcome["reference_price"]),
                        volume_since_signal=250000,
                        captured_at=_dt(16, 0),
                        status="captured",
                    )
                )
            summary = outcome["summary"]
            db.add(
                ScannerOutcomeSummary(
                    scanner_event_id=event.id,
                    reference_price=_decimal(outcome["reference_price"]),
                    mfe_pct=_decimal(summary["mfe_pct"]),
                    mfe_time_minutes=summary["mfe_time_minutes"],
                    mae_pct=_decimal(summary["mae_pct"]),
                    mae_time_minutes=summary["mae_time_minutes"],
                    mfe_mae_ratio=_decimal(summary["mfe_mae_ratio"]),
                    r_multiple=_decimal(summary["r_multiple"]),
                    eod_pct_change=_decimal(summary["eod_pct_change"]),
                    follow_through=summary["follow_through"],
                    gap_filled=summary["gap_filled"],
                    is_complete=True,
                    completed_at=_dt(16, 0),
                )
            )

        for article in dataset["news"]:
            db.add(NewsArticle(provider=DEMO_SOURCE, **article))

        for entry in dataset["journal_entries"]:
            db.add(JournalEntry(**entry))

        for trade in dataset["trades"]:
            executions = trade.pop("executions")
            row = Trade(
                symbol=trade["symbol"],
                status=trade["status"],
                side=trade["side"],
                open_date=trade["open_date"],
                close_date=trade["close_date"],
                quantity=_decimal(trade["quantity"]),
                avg_entry_price=_decimal(trade["avg_entry_price"]),
                avg_exit_price=_decimal(trade["avg_exit_price"]),
                gross_pnl=_decimal(trade["gross_pnl"]),
                net_pnl=_decimal(trade["net_pnl"]),
                commissions=_decimal(trade["commissions"]),
                return_pct=_decimal(trade["return_pct"]),
                notes=trade["notes"],
            )
            db.add(row)
            db.flush()
            for execution in executions:
                db.add(
                    TradeExecution(
                        trade_id=row.id,
                        timestamp=execution["timestamp"],
                        side=execution["side"],
                        price=_decimal(execution["price"]),
                        quantity=_decimal(execution["quantity"]),
                        commission=_decimal(execution["commission"]),
                        external_id=f"{DEMO_SOURCE}:{trade['symbol']}:{execution['side']}",
                    )
                )

        for bar in dataset["bars"]:
            db.add(
                StockAggregate(
                    ticker=bar["ticker"],
                    timestamp=bar["timestamp"],
                    multiplier=1,
                    timespan="minute",
                    open=_decimal(bar["open"]),
                    high=_decimal(bar["high"]),
                    low=_decimal(bar["low"]),
                    close=_decimal(bar["close"]),
                    volume=bar["volume"],
                    vwap=_decimal(bar["vwap"]),
                    is_pre_market=bar["is_pre_market"],
                    provider=DEMO_SOURCE,
                )
            )

        db.add(
            User(
                username=DEMO_USERNAME,
                password_hash=hash_password(DEMO_PASSWORD),
                is_active=True,
            )
        )

        db.commit()
        print(
            "Seeded MarketHawk demo: "
            f"{len(dataset['tickers'])} tickers, "
            f"{len(dataset['scanner_events'])} scanner events, "
            f"{len(dataset['watchlist'])} watchlist rows, "
            f"{len(dataset['outcomes'])} outcomes, "
            f"{len(dataset['trades'])} trade."
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_database()
