"""Tests for replay_diff_service — core diff logic and alert path."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from app.services.replay_diff_service import (
    _compute_diff,
    _make_capture_stub,
    run_replay_diff_for_scanner,
)

SCAN_DATE = date(2026, 6, 20)
SCANNER_TYPE = "liquidity_hunt"


# ---------------------------------------------------------------------------
# _compute_diff — pure unit tests
# ---------------------------------------------------------------------------


def test_compute_diff_no_drift():
    live = {
        "AAPL": {
            "indicators": {"volume_ratio": 5.0, "gap_pct": 0.02},
            "criteria_met": {},
        },
        "TSLA": {
            "indicators": {"volume_ratio": 6.0, "gap_pct": 0.03},
            "criteria_met": {},
        },
    }
    replay = {
        "AAPL": {
            "indicators": {"volume_ratio": 5.0, "gap_pct": 0.02},
            "criteria_met": {},
        },
        "TSLA": {
            "indicators": {"volume_ratio": 6.0, "gap_pct": 0.03},
            "criteria_met": {},
        },
    }
    diff = _compute_diff(live, replay)
    assert diff["has_drift"] is False
    assert diff["missing_in_replay"] == []
    assert diff["new_in_replay"] == []
    assert diff["metric_deltas"] == []
    assert diff["drift_kinds"] == []


def test_compute_diff_missing_in_replay():
    live = {
        "AAPL": {"indicators": {"volume_ratio": 5.0}, "criteria_met": {}},
        "TSLA": {"indicators": {"volume_ratio": 6.0}, "criteria_met": {}},
    }
    replay = {
        "AAPL": {"indicators": {"volume_ratio": 5.0}, "criteria_met": {}},
    }
    diff = _compute_diff(live, replay)
    assert diff["has_drift"] is True
    assert "TSLA" in diff["missing_in_replay"]
    assert "missing_in_replay" in diff["drift_kinds"]


def test_compute_diff_new_in_replay():
    live = {
        "AAPL": {"indicators": {"volume_ratio": 5.0}, "criteria_met": {}},
    }
    replay = {
        "AAPL": {"indicators": {"volume_ratio": 5.0}, "criteria_met": {}},
        "TSLA": {"indicators": {"volume_ratio": 6.0}, "criteria_met": {}},
    }
    diff = _compute_diff(live, replay)
    # new_in_replay alone does NOT set has_drift (only missing does, per spec)
    assert "TSLA" in diff["new_in_replay"]
    assert "new_in_replay" in diff["drift_kinds"]


def test_compute_diff_metric_delta_exceeds_threshold():
    live = {
        "AAPL": {
            "indicators": {"volume_ratio": 5.0, "gap_pct": 0.10},
            "criteria_met": {},
        },
    }
    # volume_ratio delta = (5.5-5.0)/5.0 = 10% > 5% threshold
    replay = {
        "AAPL": {
            "indicators": {"volume_ratio": 5.5, "gap_pct": 0.10},
            "criteria_met": {},
        },
    }
    diff = _compute_diff(live, replay)
    assert diff["has_drift"] is True
    assert len(diff["metric_deltas"]) == 1
    assert diff["metric_deltas"][0]["metric"] == "volume_ratio"
    assert diff["metric_deltas"][0]["delta_pct"] == pytest.approx(0.10, abs=0.001)
    assert "metric_delta" in diff["drift_kinds"]


def test_compute_diff_metric_delta_within_threshold():
    live = {
        "AAPL": {"indicators": {"volume_ratio": 5.0}, "criteria_met": {}},
    }
    # 1% delta — within 5% threshold
    replay = {
        "AAPL": {"indicators": {"volume_ratio": 5.05}, "criteria_met": {}},
    }
    diff = _compute_diff(live, replay)
    assert diff["has_drift"] is False
    assert diff["metric_deltas"] == []


# ---------------------------------------------------------------------------
# _make_capture_stub — verifies patch stub captures signals correctly
# ---------------------------------------------------------------------------


def test_make_capture_stub_captures_signals():
    captured = {}
    stub = _make_capture_stub(captured)

    fake_db = MagicMock()
    result = stub(
        db=fake_db,
        ticker="AAPL",
        event_date=SCAN_DATE,
        scanner_type=SCANNER_TYPE,
        indicators={"volume_ratio": 5.0},
        criteria_met={"vol_ok": True},
        enrichment={},
    )

    assert "AAPL" in captured
    assert captured["AAPL"]["indicators"] == {"volume_ratio": 5.0}
    assert result["ticker"] == "AAPL"


def test_make_capture_stub_is_idempotent_last_write_wins():
    captured = {}
    stub = _make_capture_stub(captured)
    fake_db = MagicMock()

    stub(fake_db, "AAPL", SCAN_DATE, SCANNER_TYPE, {"volume_ratio": 4.0}, {}, {})
    stub(fake_db, "AAPL", SCAN_DATE, SCANNER_TYPE, {"volume_ratio": 5.0}, {}, {})

    assert captured["AAPL"]["indicators"]["volume_ratio"] == 5.0


# ---------------------------------------------------------------------------
# run_replay_diff_for_scanner — integration with mocked DB
# ---------------------------------------------------------------------------


def _fake_scanner_event(ticker, indicators):
    e = MagicMock()
    e.ticker = ticker
    e.indicators = indicators
    e.criteria_met = {}
    return e


def _build_db_mock(live_events, existing_diff=None):
    """Return a MagicMock db that returns live_events from ScannerEvent query."""
    db = MagicMock(spec=["query", "add", "commit", "refresh", "rollback"])

    replay_diff_row = MagicMock()
    replay_diff_row.id = 1
    replay_diff_row.scanner_type = SCANNER_TYPE
    replay_diff_row.scan_date = SCAN_DATE
    replay_diff_row.status = "clean"
    replay_diff_row.has_drift = False
    replay_diff_row.live_count = len(live_events)
    replay_diff_row.replay_count = 0
    replay_diff_row.missing_in_replay_count = 0
    replay_diff_row.new_in_replay_count = 0
    replay_diff_row.matched_count = 0
    replay_diff_row.missing_in_replay = []
    replay_diff_row.new_in_replay = []
    replay_diff_row.metric_deltas = []
    replay_diff_row.drift_kinds = []
    replay_diff_row.created_at = None
    replay_diff_row.updated_at = None

    def _query_side_effect(model):
        from app.models.scanner_event import ScannerEvent
        from app.models.scanner_replay_diff import ScannerReplayDiff

        q = MagicMock()
        q.filter.return_value = q
        if model is ScannerEvent:
            q.all.return_value = live_events
        elif model is ScannerReplayDiff:
            q.first.return_value = existing_diff
        else:
            q.all.return_value = []
            q.first.return_value = None
        return q

    db.query.side_effect = _query_side_effect
    db.refresh.side_effect = lambda row: None

    return db, replay_diff_row


def test_no_live_events_returns_no_live_events_status():
    db, _ = _build_db_mock(live_events=[], existing_diff=None)

    with (
        patch("app.services.replay_diff_service._upsert_diff") as mock_upsert,
        patch("app.services.system_notifier.notify_system") as mock_notify,
    ):
        mock_upsert.return_value = {"status": "no_live_events", "has_drift": False}
        result = run_replay_diff_for_scanner(SCANNER_TYPE, SCAN_DATE, ["AAPL"], db)

    mock_upsert.assert_called_once()
    kwargs = mock_upsert.call_args[1]
    assert kwargs["status"] == "no_live_events"
    assert kwargs["has_drift"] is False
    mock_notify.assert_not_called()


def test_empty_tickers_returns_insufficient_data():
    live_events = [_fake_scanner_event("AAPL", {"volume_ratio": 5.0})]
    db, _ = _build_db_mock(live_events=live_events, existing_diff=None)

    with (
        patch("app.services.replay_diff_service._upsert_diff") as mock_upsert,
        patch("app.services.system_notifier.notify_system"),
    ):
        mock_upsert.return_value = {"status": "insufficient_data", "has_drift": False}
        result = run_replay_diff_for_scanner(SCANNER_TYPE, SCAN_DATE, [], db)

    kwargs = mock_upsert.call_args[1]
    assert kwargs["status"] == "insufficient_data"


def test_zero_drift_produces_clean_record():
    """Acceptance criterion: zero-drift night produces a queryable 'all green' record."""
    live_events = [_fake_scanner_event("AAPL", {"volume_ratio": 5.0, "gap_pct": 0.02})]
    db, _ = _build_db_mock(live_events=live_events, existing_diff=None)

    replay_signals = {
        "AAPL": {
            "ticker": "AAPL",
            "event_date": SCAN_DATE,
            "scanner_type": SCANNER_TYPE,
            "indicators": {"volume_ratio": 5.0, "gap_pct": 0.02},
            "criteria_met": {},
        }
    }

    with (
        patch(
            "app.services.replay_diff_service._run_replay", return_value=replay_signals
        ),
        patch("app.services.replay_diff_service._upsert_diff") as mock_upsert,
        patch("app.services.system_notifier.notify_system") as mock_notify,
    ):
        mock_upsert.return_value = {"status": "clean", "has_drift": False}
        result = run_replay_diff_for_scanner(SCANNER_TYPE, SCAN_DATE, ["AAPL"], db)

    kwargs = mock_upsert.call_args[1]
    assert kwargs["status"] == "clean"
    assert kwargs["has_drift"] is False
    assert kwargs["missing_in_replay_count"] == 0
    mock_notify.assert_not_called()


def test_injected_drift_fires_alert_path():
    """Acceptance criterion: injected fixture drift fires the alert path."""
    live_events = [
        _fake_scanner_event("AAPL", {"volume_ratio": 5.0}),
        _fake_scanner_event("TSLA", {"volume_ratio": 7.0}),
    ]
    db, _ = _build_db_mock(live_events=live_events, existing_diff=None)

    # Replay only finds AAPL — TSLA is missing (injected drift)
    replay_signals = {
        "AAPL": {
            "ticker": "AAPL",
            "event_date": SCAN_DATE,
            "scanner_type": SCANNER_TYPE,
            "indicators": {"volume_ratio": 5.0},
            "criteria_met": {},
        }
    }

    with (
        patch(
            "app.services.replay_diff_service._run_replay", return_value=replay_signals
        ),
        patch("app.services.replay_diff_service._upsert_diff") as mock_upsert,
        patch("app.services.system_notifier.notify_system") as mock_notify,
        patch(
            "app.services.replay_diff_service.replay_drift_signals_total"
        ) as mock_counter,
    ):
        mock_upsert.return_value = {
            "status": "drift",
            "has_drift": True,
            "scanner_type": SCANNER_TYPE,
        }
        result = run_replay_diff_for_scanner(
            SCANNER_TYPE, SCAN_DATE, ["AAPL", "TSLA"], db
        )

    # Alert path must have been triggered
    mock_notify.assert_called_once()
    notify_call = mock_notify.call_args
    assert notify_call[1]["severity"] == "warning"
    assert "replay_drift" in notify_call[1]["dedupe_key"]

    # Upsert with drift status
    kwargs = mock_upsert.call_args[1]
    assert kwargs["status"] == "drift"
    assert kwargs["has_drift"] is True
    assert "TSLA" in kwargs["missing_in_replay"]


def test_replay_failure_produces_insufficient_data():
    live_events = [_fake_scanner_event("AAPL", {"volume_ratio": 5.0})]
    db, _ = _build_db_mock(live_events=live_events, existing_diff=None)

    with (
        patch("app.services.replay_diff_service._run_replay", return_value=None),
        patch("app.services.replay_diff_service._upsert_diff") as mock_upsert,
        patch("app.services.system_notifier.notify_system"),
    ):
        mock_upsert.return_value = {"status": "insufficient_data", "has_drift": False}
        run_replay_diff_for_scanner(SCANNER_TYPE, SCAN_DATE, ["AAPL"], db)

    kwargs = mock_upsert.call_args[1]
    assert kwargs["status"] == "insufficient_data"
