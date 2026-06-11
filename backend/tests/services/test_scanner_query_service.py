"""Tests for ScannerQueryService."""

from datetime import date

import pytest

from app.models.scanner_event import ScannerEvent
from app.models.scanner_outcome_summary import ScannerOutcomeSummary
from app.models.scanner_run import ScannerRun
from app.models.signal_review import SignalReview
from app.models.stock_universe import StockUniverse
from app.services.scanner_query_service import ScannerQueryService


@pytest.fixture
def universe(db):
    u = StockUniverse(name="Test Universe", description="test", criteria={})
    db.add(u)
    db.flush()
    return u


@pytest.fixture
def seeded_runs(db, universe):
    runs = [
        ScannerRun(
            scanner_type="liquidity_hunt",
            universe_id=universe.id,
            status="completed",
            stocks_scanned=10,
            events_detected=5,
            execution_time_ms=1000,
        ),
        ScannerRun(
            scanner_type="liquidity_hunt",
            universe_id=universe.id,
            status="failed",
            stocks_scanned=10,
            events_detected=0,
            execution_time_ms=500,
        ),
    ]
    for r in runs:
        db.add(r)
    db.flush()
    return runs


@pytest.fixture
def seeded_events(db):
    events = []
    for i in range(5):
        e = ScannerEvent(
            ticker=f"SYM{i}",
            scanner_type="liquidity_hunt",
            event_date=date(2026, 5, 1),
            signal_quality_score=i * 0.2,
        )
        db.add(e)
        db.flush()
        summary = ScannerOutcomeSummary(
            scanner_event_id=e.id,
            reference_price=100.0,
            eod_pct_change=float(i),
            follow_through=bool(i % 2),
        )
        db.add(summary)
        events.append(e)
    db.flush()
    return events


# ── get_scan_status_block ──────────────────────────────────────────────────


def test_get_scan_status_block_returns_expected_keys(db, universe, seeded_runs):
    result = ScannerQueryService.get_scan_status_block(
        db, "liquidity_hunt", universe_id=universe.id
    )
    assert "last_run" in result
    assert "success_rate" in result
    assert "sparkline" in result
    assert "total_events" in result
    assert "next_run" in result
    assert result["success_rate"] == 50.0  # 1 completed out of 2


def test_get_scan_status_block_no_runs_returns_nones(db):
    result = ScannerQueryService.get_scan_status_block(db, "no_such_scanner")
    assert result["last_run"] is None
    assert result["success_rate"] is None
    assert result["sparkline"] == []


# ── get_signal_quality_distribution ────────────────────────────────────────


def test_get_signal_quality_distribution_returns_10_deciles(db, seeded_events):
    result = ScannerQueryService.get_signal_quality_distribution(db, scanner_type=None)
    assert len(result["deciles"]) == 10
    assert "signal_ranker_version" in result


def test_get_signal_quality_distribution_filters_by_type(db, seeded_events):
    result = ScannerQueryService.get_signal_quality_distribution(
        db, scanner_type="liquidity_hunt"
    )
    populated = [d for d in result["deciles"] if d["count"] > 0]
    assert len(populated) > 0


# ── get_review_stats ───────────────────────────────────────────────────────


def test_get_review_stats_returns_expected_shape(db, seeded_events):
    event = seeded_events[0]
    review = SignalReview(
        scanner_event_id=event.id,
        verdict="confirmed",
    )
    db.add(review)
    db.flush()
    result = ScannerQueryService.get_review_stats(db, scanner_type="liquidity_hunt")
    assert "total_events" in result
    assert "reviewed_count" in result
    assert "acceptance_rate" in result
    assert isinstance(result["by_scanner_type"], list)
    assert isinstance(result["top_rejection_reasons"], list)
