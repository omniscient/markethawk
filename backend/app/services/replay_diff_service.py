"""Nightly replay-diff service.

Re-runs yesterday's scans from stored StockAggregate data and diffs the resulting
in-memory signals against live ScannerEvent rows.  Persists one ScannerReplayDiff
record per scanner type per day.
"""

import asyncio
import contextlib
import logging
from datetime import date
from typing import Optional
from unittest.mock import patch

from sqlalchemy.orm import Session

from app.core.metrics import replay_drift_signals_total

logger = logging.getLogger(__name__)

# Drift thresholds
_DRIFT_METRIC_KEYS = ("volume_ratio", "gap_pct")
_DRIFT_METRIC_THRESHOLD = 0.05  # 5% relative delta

# All module-level and class-level _save_event bindings that must be patched.
# The order is irrelevant; ExitStack applies all simultaneously.
_SAVE_EVENT_PATCH_TARGETS = [
    "app.services.liquidity_hunt._save_event",
    "app.services.pocket_pivot._save_event",
    "app.services.trend_pullback_scan._save_event",
    "app.services.scanner.ScannerService._save_event",
]


def _make_capture_stub(captured: dict):
    """Return a drop-in replacement for save_event that records signals in-memory."""

    def _stub(
        db,
        ticker,
        event_date,
        scanner_type,
        indicators,
        criteria_met,
        enrichment,
        previous_close=None,
        opening_price=None,
        closing_price=None,
        ranker_config=None,
    ) -> dict:
        captured[ticker] = {
            "ticker": ticker,
            "event_date": event_date,
            "scanner_type": scanner_type,
            "indicators": indicators or {},
            "criteria_met": criteria_met or {},
        }
        return captured[ticker]

    return _stub


def _collect_live_signals(scanner_type: str, scan_date: date, db: Session) -> dict:
    """Return {ticker: ScannerEvent row as dict} for (scanner_type, scan_date)."""
    from app.models.scanner_event import ScannerEvent

    rows = (
        db.query(ScannerEvent)
        .filter(
            ScannerEvent.scanner_type == scanner_type,
            ScannerEvent.event_date == scan_date,
        )
        .all()
    )
    return {
        row.ticker: {
            "ticker": row.ticker,
            "indicators": row.indicators or {},
            "criteria_met": row.criteria_met or {},
        }
        for row in rows
    }


def _run_replay(
    scanner_type: str,
    tickers: list,
    scan_date: date,
    db: Session,
) -> Optional[dict]:
    """Run the scanner for scan_date with save_event patched out.

    Returns {ticker: captured_signal} or None on hard failure.
    Imports scanner modules so that module-level descriptors self-register.
    """
    import app.services.liquidity_hunt  # noqa: F401
    import app.services.oversold_bounce_scan  # noqa: F401
    import app.services.pocket_pivot  # noqa: F401
    import app.services.pre_market_scan  # noqa: F401
    import app.services.scan_orchestrator as _orchestrator
    import app.services.trend_pullback_scan  # noqa: F401

    captured: dict = {}
    stub = _make_capture_stub(captured)

    try:
        with contextlib.ExitStack() as stack:
            for target in _SAVE_EVENT_PATCH_TARGETS:
                stack.enter_context(patch(target, stub))
            asyncio.run(
                _orchestrator.run(scanner_type, tickers, db=db, event_date=scan_date)
            )
    except Exception as exc:
        logger.warning(
            "replay_diff: _run_replay failed for scanner=%s date=%s: %s",
            scanner_type,
            scan_date,
            exc,
        )
        return None

    return captured


def _compute_diff(live: dict, replay: dict) -> dict:
    """Pure comparison of live vs replay signal sets.

    Returns a diff dict with:
      missing_in_replay, new_in_replay, metric_deltas, drift_kinds, has_drift
    """
    live_tickers = set(live)
    replay_tickers = set(replay)

    missing_in_replay = sorted(live_tickers - replay_tickers)
    new_in_replay = sorted(replay_tickers - live_tickers)
    metric_deltas = []
    drift_kinds: list = []

    for ticker in live_tickers & replay_tickers:
        live_ind = live[ticker]["indicators"]
        replay_ind = replay[ticker]["indicators"]
        for key in _DRIFT_METRIC_KEYS:
            live_val = live_ind.get(key)
            replay_val = replay_ind.get(key)
            if live_val is None or replay_val is None:
                continue
            try:
                live_f = float(live_val)
                replay_f = float(replay_val)
            except (TypeError, ValueError):
                continue
            if live_f == 0:
                continue
            delta_pct = abs(replay_f - live_f) / abs(live_f)
            if delta_pct > _DRIFT_METRIC_THRESHOLD:
                metric_deltas.append(
                    {
                        "ticker": ticker,
                        "metric": key,
                        "live": live_f,
                        "replay": replay_f,
                        "delta_pct": round(delta_pct, 4),
                    }
                )
                if "metric_delta" not in drift_kinds:
                    drift_kinds.append("metric_delta")

    if missing_in_replay:
        drift_kinds.append("missing_in_replay")
    if new_in_replay:
        drift_kinds.append("new_in_replay")

    has_drift = bool(missing_in_replay or metric_deltas)

    return {
        "missing_in_replay": missing_in_replay,
        "new_in_replay": new_in_replay,
        "metric_deltas": metric_deltas,
        "drift_kinds": drift_kinds,
        "has_drift": has_drift,
    }


def run_replay_diff_for_scanner(
    scanner_type: str,
    scan_date: date,
    tickers: list,
    db: Session,
) -> dict:
    """Run a complete replay-diff for one scanner type on one day.

    Upserts a ScannerReplayDiff row, emits Prometheus counters, a Seq log event,
    and a SystemNotifier warning if drift is detected.

    Returns the persisted row as a dict.
    """
    from app.services.system_notifier import notify_system

    logger.info(
        "replay_diff: starting scanner=%s date=%s tickers=%d",
        scanner_type,
        scan_date,
        len(tickers),
    )

    # Stage 1 — collect live signals
    live = _collect_live_signals(scanner_type, scan_date, db)
    if not live:
        status = "no_live_events"
        row = _upsert_diff(
            db,
            scanner_type,
            scan_date,
            status=status,
            has_drift=False,
            live_count=0,
            replay_count=0,
            missing_in_replay_count=0,
            new_in_replay_count=0,
            matched_count=0,
            missing_in_replay=[],
            new_in_replay=[],
            metric_deltas=[],
            drift_kinds=[],
        )
        logger.info(
            "replay_diff: scanner=%s date=%s status=no_live_events",
            scanner_type,
            scan_date,
        )
        return row

    # Stage 2 — run replay with patched save_event
    if not tickers:
        status = "insufficient_data"
        row = _upsert_diff(
            db,
            scanner_type,
            scan_date,
            status=status,
            has_drift=False,
            live_count=len(live),
            replay_count=0,
            missing_in_replay_count=0,
            new_in_replay_count=0,
            matched_count=0,
            missing_in_replay=[],
            new_in_replay=[],
            metric_deltas=[],
            drift_kinds=[],
        )
        return row

    replay = _run_replay(scanner_type, tickers, scan_date, db)
    if replay is None:
        status = "insufficient_data"
        row = _upsert_diff(
            db,
            scanner_type,
            scan_date,
            status=status,
            has_drift=False,
            live_count=len(live),
            replay_count=0,
            missing_in_replay_count=0,
            new_in_replay_count=0,
            matched_count=0,
            missing_in_replay=[],
            new_in_replay=[],
            metric_deltas=[],
            drift_kinds=[],
        )
        return row

    # Stage 3 — compute diff
    diff = _compute_diff(live, replay)

    matched_count = len(set(live) & set(replay))
    status = "drift" if diff["has_drift"] else "clean"

    row = _upsert_diff(
        db,
        scanner_type,
        scan_date,
        status=status,
        has_drift=diff["has_drift"],
        live_count=len(live),
        replay_count=len(replay),
        missing_in_replay_count=len(diff["missing_in_replay"]),
        new_in_replay_count=len(diff["new_in_replay"]),
        matched_count=matched_count,
        missing_in_replay=diff["missing_in_replay"],
        new_in_replay=diff["new_in_replay"],
        metric_deltas=diff["metric_deltas"],
        drift_kinds=diff["drift_kinds"],
    )

    # Prometheus
    for kind in diff["drift_kinds"]:
        replay_drift_signals_total.labels(scanner_type=scanner_type, kind=kind).inc()

    # Seq structured log
    logger.info(
        "replay_diff result",
        extra={
            "scanner_type": scanner_type,
            "scan_date": scan_date.isoformat(),
            "status": status,
            "has_drift": diff["has_drift"],
            "live_count": len(live),
            "replay_count": len(replay),
            "missing_in_replay_count": len(diff["missing_in_replay"]),
            "new_in_replay_count": len(diff["new_in_replay"]),
            "drift_kinds": diff["drift_kinds"],
        },
    )

    # SystemNotifier alert on drift
    if diff["has_drift"]:
        missing = diff["missing_in_replay"]
        delta_count = len(diff["metric_deltas"])
        body = (
            f"Scanner {scanner_type!r} on {scan_date}: "
            f"{len(missing)} signal(s) missing in replay"
            + (f", {delta_count} metric delta(s) >5%%" if delta_count else "")
            + f". Drift kinds: {', '.join(diff['drift_kinds'])}."
        )
        notify_system(
            title=f"Replay drift detected — {scanner_type}",
            body=body,
            severity="warning",
            dedupe_key=f"replay_drift:{scanner_type}:{scan_date}",
            cooldown_seconds=86400,
            db=db,
        )

    return row


def _upsert_diff(db: Session, scanner_type: str, scan_date: date, **fields) -> dict:
    """Insert or update the ScannerReplayDiff row for (scanner_type, scan_date)."""
    from app.models.scanner_replay_diff import ScannerReplayDiff

    existing = (
        db.query(ScannerReplayDiff)
        .filter(
            ScannerReplayDiff.scanner_type == scanner_type,
            ScannerReplayDiff.scan_date == scan_date,
        )
        .first()
    )

    if existing:
        for key, val in fields.items():
            setattr(existing, key, val)
        row = existing
    else:
        row = ScannerReplayDiff(
            scanner_type=scanner_type,
            scan_date=scan_date,
            **fields,
        )
        db.add(row)

    try:
        db.commit()
        db.refresh(row)
    except Exception:
        db.rollback()
        raise

    return {
        "id": row.id,
        "scanner_type": row.scanner_type,
        "scan_date": row.scan_date,
        "status": row.status,
        "has_drift": row.has_drift,
        "live_count": row.live_count,
        "replay_count": row.replay_count,
        "missing_in_replay_count": row.missing_in_replay_count,
        "new_in_replay_count": row.new_in_replay_count,
        "matched_count": row.matched_count,
        "missing_in_replay": row.missing_in_replay,
        "new_in_replay": row.new_in_replay,
        "metric_deltas": row.metric_deltas,
        "drift_kinds": row.drift_kinds,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
