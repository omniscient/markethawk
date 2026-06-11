"""
Scanner seed helpers — runs and events.
Each function inserts rows and flushes; the caller's transaction provides rollback.
"""

from datetime import timedelta

from sqlalchemy.orm import Session

from app.models import ScannerEvent, ScannerRun
from app.utils.session import get_market_today


def seed_scanner_runs(db: Session, universe_id: int | None = None) -> list[ScannerRun]:
    specs = [
        ("pre_market_volume_spike", "completed", 12, 4),
        ("liquidity_hunt", "completed", 10, 6),
        ("pre_market_volume_spike", "completed", 8, 2),
        ("liquidity_hunt", "failed", 5, 0),
        ("pre_market_volume_spike", "running", 3, 0),
    ]
    runs = []
    for scanner_type, status, stocks_scanned, events_detected in specs:
        run = ScannerRun(
            scanner_type=scanner_type,
            status=status,
            stocks_scanned=stocks_scanned,
            events_detected=events_detected,
            execution_time_ms=250,
            universe_id=universe_id,
        )
        db.add(run)
        runs.append(run)
    db.flush()
    return runs


def seed_scanner_events(
    db: Session, tickers: list[str] | None = None
) -> list[ScannerEvent]:
    if tickers is None:
        tickers = ["AAPL", "MSFT", "NVDA", "MRNA", "BNTX"]

    today = get_market_today()
    # Build unique (ticker, event_date, scanner_type) combinations
    specs = [
        ("AAPL", today, "pre_market_volume_spike"),
        ("MSFT", today, "pre_market_volume_spike"),
        ("NVDA", today, "pre_market_volume_spike"),
        ("MRNA", today, "liquidity_hunt_pre"),
        ("BNTX", today, "liquidity_hunt_pre"),
        ("AAPL", today - timedelta(days=1), "pre_market_volume_spike"),
        ("MSFT", today - timedelta(days=1), "liquidity_hunt_pre"),
        ("NVDA", today - timedelta(days=1), "liquidity_hunt_post"),
        ("MRNA", today - timedelta(days=2), "pre_market_volume_spike"),
        ("BNTX", today - timedelta(days=2), "pre_market_volume_spike"),
        ("AAPL", today - timedelta(days=2), "liquidity_hunt_pre"),
    ]

    # Filter to requested tickers only
    ticker_set = set(tickers)
    events = []
    for i, (ticker, event_date, scanner_type) in enumerate(specs):
        if ticker not in ticker_set:
            continue
        event = ScannerEvent(
            ticker=ticker,
            event_date=event_date,
            scanner_type=scanner_type,
            summary=f"{ticker} triggered {scanner_type}",
            severity="medium",
            indicators={
                "volume_spike_ratio": 5.0 + i * 0.5,
                "pre_market_volume": 400000 + i * 10000,
            },
            criteria_met={"volume_threshold": True, "price_gap": i % 2 == 0},
            metadata_={},
        )
        db.add(event)
        events.append(event)
    db.flush()
    return events
