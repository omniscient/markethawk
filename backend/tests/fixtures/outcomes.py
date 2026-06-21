"""
Outcomes seed helpers — scanner events, outcome snapshots, and outcome summaries.
Each function inserts rows and flushes; the caller's transaction provides rollback.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.scanner_event import ScannerEvent
from app.models.scanner_outcome_snapshot import ScannerOutcomeSnapshot
from app.models.scanner_outcome_summary import ScannerOutcomeSummary
from app.models.signal_review import SignalReview


def seed_outcomes(db: Session) -> dict:
    """
    Creates 4 ScannerEvents, 9 captured ScannerOutcomeSnapshots, and 3 complete
    ScannerOutcomeSummaries (2 wins, 1 loss) for scanner_type='pre_market_volume_spike'.
    Returns {"events": [...], "snapshots": [...], "summaries": [...]}.
    """
    today = date.today()

    events = [
        ScannerEvent(
            ticker="AAPL",
            event_date=today,
            scanner_type="pre_market_volume_spike",
            summary="AAPL triggered volume spike",
            severity="high",
            indicators={"volume_spike_ratio": 6.0, "pre_market_volume": 500000},
            criteria_met={"volume_threshold": True, "price_gap": True},
            metadata_={},
        ),
        ScannerEvent(
            ticker="MSFT",
            event_date=today,
            scanner_type="pre_market_volume_spike",
            summary="MSFT triggered volume spike",
            severity="medium",
            indicators={"volume_spike_ratio": 5.0, "pre_market_volume": 400000},
            criteria_met={"volume_threshold": True, "price_gap": False},
            metadata_={},
        ),
        ScannerEvent(
            ticker="NVDA",
            event_date=today - timedelta(days=1),
            scanner_type="pre_market_volume_spike",
            summary="NVDA triggered volume spike",
            severity="low",
            indicators={"volume_spike_ratio": 4.2, "pre_market_volume": 300000},
            criteria_met={"volume_threshold": True, "price_gap": False},
            metadata_={},
        ),
        ScannerEvent(
            ticker="MRNA",
            event_date=today,
            scanner_type="liquidity_hunt_pre",
            summary="MRNA liquidity hunt",
            severity="medium",
            indicators={"volume_spike_ratio": 4.5, "pre_market_volume": 350000},
            criteria_met={"volume_threshold": True, "price_gap": True},
            metadata_={},
        ),
    ]
    for event in events:
        db.add(event)
    db.flush()

    ref_price = Decimal("100.00")
    interval_specs = [
        ("5m", Decimal("1.5")),
        ("15m", Decimal("2.5")),
        ("30m", Decimal("3.0")),
    ]
    snapshots = []
    for event in events[:3]:
        for interval_key, pct in interval_specs:
            snap_price = ref_price * (1 + pct / 100)
            snap = ScannerOutcomeSnapshot(
                scanner_event_id=event.id,
                interval_key=interval_key,
                reference_price=ref_price,
                snapshot_price=snap_price,
                pct_change=pct,
                high_since_signal=snap_price + Decimal("0.50"),
                low_since_signal=ref_price - Decimal("0.50"),
                volume_since_signal=50000,
                status="captured",
            )
            db.add(snap)
            snapshots.append(snap)
    db.flush()

    # 2 wins (eod_pct > 0), 1 loss (eod_pct < 0)
    summary_specs = [
        (Decimal("3.00"), Decimal("0.50"), Decimal("2.50"), True),
        (Decimal("2.50"), Decimal("0.80"), Decimal("1.50"), True),
        (Decimal("1.50"), Decimal("1.20"), Decimal("-0.50"), False),
    ]
    summaries = []
    for event, (mfe, mae, eod, ft) in zip(events[:3], summary_specs):
        summary = ScannerOutcomeSummary(
            scanner_event_id=event.id,
            reference_price=ref_price,
            mfe_pct=mfe,
            mfe_time_minutes=15,
            mae_pct=mae,
            mae_time_minutes=5,
            mfe_mae_ratio=(mfe / mae).quantize(Decimal("0.0001")),
            r_multiple=(eod / mae).quantize(Decimal("0.0001")),
            eod_pct_change=eod,
            follow_through=ft,
            gap_filled=False,
            is_complete=True,
        )
        db.add(summary)
        summaries.append(summary)
    db.flush()

    return {"events": events, "snapshots": snapshots, "summaries": summaries}


def _make_gate_meta(tier: str) -> dict:
    return {"quality_gate": {"tier": tier, "warnings": []}}


def seed_outcomes_with_gate_tiers(db: Session) -> dict:
    """
    Creates 4 ScannerEvents with explicit quality_gate tiers:
      - AAPL: trusted  (with complete summary)
      - MSFT: warning  (with complete summary)
      - NVDA: blocked  (with complete summary)
      - AMD:  skipped  (with complete summary)
    All events for scanner_type='pre_market_volume_spike'.
    Returns {"events": [...], "summaries": [...]}.
    """
    today = date.today()
    tiers = [
        ("AAPL", "trusted"),
        ("MSFT", "warning"),
        ("NVDA", "blocked"),
        ("AMD", "skipped"),
    ]

    events = []
    for ticker, tier in tiers:
        ev = ScannerEvent(
            ticker=ticker,
            event_date=today,
            scanner_type="pre_market_volume_spike",
            summary=f"{ticker} {tier} gate tier",
            severity="medium",
            indicators={"volume_spike_ratio": 5.0},
            criteria_met={"volume_threshold": True},
            metadata_=_make_gate_meta(tier),
        )
        db.add(ev)
        events.append(ev)
    db.flush()

    ref_price = Decimal("100.00")
    summaries = []
    for ev in events:
        sm = ScannerOutcomeSummary(
            scanner_event_id=ev.id,
            reference_price=ref_price,
            mfe_pct=Decimal("2.00"),
            mae_pct=Decimal("0.50"),
            mfe_mae_ratio=Decimal("4.00"),
            r_multiple=Decimal("3.00"),
            eod_pct_change=Decimal("1.50"),
            follow_through=True,
            gap_filled=False,
            is_complete=True,
        )
        db.add(sm)
        summaries.append(sm)
    db.flush()

    return {"events": events, "summaries": summaries}


def seed_reviews(db: Session, events: list) -> list:
    """
    Creates SignalReview rows on the first 3 events passed (expected to be
    pre_market_volume_spike events from seed_outcomes).

    Distribution: 2 confirmed, 1 rejected (reason='noise').
    With seed_outcomes' 3 complete pre_market_volume_spike summaries (total_signals=3):
      precision_pct = 2 / (2+1) * 100 = 66.67
      review_sample_n = 3
      review_coverage_pct = 3 / 3 * 100 = 100.0
      top_reject_reasons = [{"reason": "noise", "count": 1}]
      verdict_counts = {"confirmed": 2, "rejected": 1, "enhanced": 0}
    """
    specs = [
        ("confirmed", None),
        ("confirmed", None),
        ("rejected", "noise"),
    ]
    reviews = []
    for event, (verdict, reason) in zip(events[:3], specs):
        rv = SignalReview(
            scanner_event_id=event.id,
            verdict=verdict,
            reject_reason=reason,
            reviewed_at=datetime.utcnow(),
        )
        db.add(rv)
        reviews.append(rv)
    db.flush()
    return reviews
