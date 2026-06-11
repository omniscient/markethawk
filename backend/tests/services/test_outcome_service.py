"""
Tests for OutcomeService — snapshot creation, capture, and summary recompute.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.models.scanner_config import ScannerConfig
from app.models.scanner_event import ScannerEvent
from app.models.stock_aggregate import StockAggregate
from app.models.stock_universe import StockUniverse
from app.services.outcome_service import OutcomeService

# ── helpers ────────────────────────────────────────────────────────────────


def _universe(db):
    u = StockUniverse(name="Test Universe", criteria={})
    db.add(u)
    db.flush()
    return u


def _config(db, scanner_type="pre_market_volume_spike"):
    universe = _universe(db)
    cfg = ScannerConfig(
        name="Test Config",
        scanner_type=scanner_type,
        parameters={},
        criteria={},
        universe_id=universe.id,
        outcome_config={
            "intervals": ["1h", "eod"],
            "reference_price_source": "opening_price",
            "follow_through_threshold_pct": 2.0,
        },
    )
    db.add(cfg)
    db.flush()
    return cfg


def _event(db, scanner_type="pre_market_volume_spike", opening_price=10.0):
    ev = ScannerEvent(
        ticker="AAPL",
        event_date=date.today(),
        scanner_type=scanner_type,
        indicators={},
        criteria_met={},
        metadata_={},
        opening_price=Decimal(str(opening_price)),
    )
    db.add(ev)
    db.flush()
    return ev


# ── create_pending_snapshots ──────────────────────────────────────────────


def test_create_pending_snapshots_returns_correct_count(db: Session):
    _config(db)
    event = _event(db)
    snapshots = OutcomeService.create_pending_snapshots(db, event)
    assert len(snapshots) == 2  # "1h" and "eod"


def test_create_pending_snapshots_sets_status_pending(db: Session):
    _config(db)
    event = _event(db)
    snapshots = OutcomeService.create_pending_snapshots(db, event)
    assert all(s.status == "pending" for s in snapshots)


def test_create_pending_snapshots_no_config_returns_empty(db: Session):
    event = _event(db, scanner_type="unknown_type")
    snapshots = OutcomeService.create_pending_snapshots(db, event)
    assert snapshots == []


def test_create_pending_snapshots_no_opening_price_returns_empty(db: Session):
    _config(db)
    event = _event(db, opening_price=0)
    event.opening_price = None
    db.flush()
    snapshots = OutcomeService.create_pending_snapshots(db, event)
    assert snapshots == []


# ── capture_snapshot ──────────────────────────────────────────────────────


def test_capture_snapshot_sets_status_captured(db: Session):
    from datetime import timedelta
    from zoneinfo import ZoneInfo

    _config(db)
    event = _event(db, opening_price=10.0)
    snapshots = OutcomeService.create_pending_snapshots(db, event)

    _ET = ZoneInfo("America/New_York")
    open_et = datetime.combine(
        event.event_date, __import__("datetime").time(9, 30), tzinfo=_ET
    )
    open_utc = open_et.astimezone(timezone.utc).replace(tzinfo=None)

    bar = StockAggregate(
        ticker="AAPL",
        timespan="minute",
        timestamp=open_utc + timedelta(minutes=5),
        open=Decimal("10.1"),
        high=Decimal("10.5"),
        low=Decimal("9.9"),
        close=Decimal("10.3"),
        volume=5000,
        multiplier=1,
    )
    db.add(bar)
    db.flush()

    snap_1h = next(s for s in snapshots if s.interval_key == "1h")
    OutcomeService.capture_snapshot(db, snap_1h)
    assert snap_1h.status == "captured"
    assert snap_1h.snapshot_price == pytest.approx(Decimal("10.3"), rel=Decimal("1e-4"))


def test_capture_snapshot_no_bars_sets_failed(db: Session):
    _config(db)
    event = _event(db)
    snapshots = OutcomeService.create_pending_snapshots(db, event)
    snap = snapshots[0]
    OutcomeService.capture_snapshot(db, snap)
    assert snap.status == "failed"


# ── recompute_summary ─────────────────────────────────────────────────────


def test_recompute_summary_returns_none_without_captured_snapshots(db: Session):
    _config(db)
    event = _event(db)
    OutcomeService.create_pending_snapshots(db, event)
    result = OutcomeService.recompute_summary(db, event.id)
    assert result is None


def test_recompute_summary_returns_none_for_missing_event(db: Session):
    result = OutcomeService.recompute_summary(db, 999999)
    assert result is None
