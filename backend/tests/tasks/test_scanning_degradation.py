"""_run_universe_scan_logic degraded-feed behaviour (#388, ADR-0013)."""

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from prometheus_client import REGISTRY

from app.core.provider_health import ProviderHealthSnapshot
from app.models.market_holiday import MarketHoliday
from tests.tasks.test_scanning_tasks import (
    _make_assessment,
    _make_db,
    _make_run,
    _make_ticker,
)

DAY = date(2026, 6, 2)
LIVE_NOW = datetime(2026, 6, 2, 12, 0)  # naive UTC = 08:00 EDT


def _healthy():
    return ProviderHealthSnapshot(provider="polygon")


def _breaker_open():
    return ProviderHealthSnapshot(
        provider="polygon", breaker_state="open", breaker_open_workers=["celery:1"]
    )


def _fake_orchestrator(diag_payload, calls=None):
    async def fake_run(
        scanner_type,
        tickers,
        db,
        event_date,
        scanner_run=None,
        gate_metadata=None,
        diagnostics_out=None,
    ):
        if calls is not None:
            calls.append(event_date)
        if diagnostics_out is not None and diag_payload is not None:
            diagnostics_out.update(diag_payload)
        return []

    return fake_run


def _with_holidays(db, holidays):
    """Serve NYSE full-close rows to the scan's MarketHoliday.date query."""
    base = db.query.side_effect

    def _query(model, *args):
        if model is MarketHoliday.date:
            q = MagicMock()
            q.filter.return_value = [SimpleNamespace(date=h) for h in holidays]
            return q
        return base(model, *args)

    db.query.side_effect = _query
    return db


def _run(
    health, diag_payload, start=DAY, end=DAY, now=LIVE_NOW, calls=None, holidays=()
):
    from app.tasks.scanning import _run_universe_scan_logic

    run = _make_run("scan-deg-01")
    run.quality_gate = None
    published = []
    db = _with_holidays(_make_db(run=run, tickers=[_make_ticker("AAPL")]), holidays)
    health_mock = MagicMock(side_effect=lambda *a, **k: health())
    with (
        patch(
            "app.services.quality_gate.QualityGateService.assess",
            return_value=_make_assessment("trusted"),
        ),
        patch("app.tasks.scanning._compute_data_degraded", return_value=False),
        patch("app.tasks.scanning.utc_now", return_value=now),
        patch("app.tasks.scanning.get_provider_health", health_mock),
        patch(
            "app.services.scan_orchestrator.run",
            _fake_orchestrator(diag_payload, calls),
        ),
    ):
        _run_universe_scan_logic(
            scan_id="scan-deg-01",
            scanner_type="pre_market_volume_spike",
            universe_id=1,
            start=start,
            end=end,
            db=db,
            publish=published.append,
            is_cancelled=lambda: False,
            task_id="task-deg",
        )
    return run, published, health_mock


def _live_issues(run):
    return [
        i
        for i in run.quality_gate["issues"]
        if i["detail"].get("subtype") == "live_degradation"
    ]


def _gauge():
    return REGISTRY.get_sample_value(
        "scan_provider_gap_severity", {"scanner_type": "pre_market_volume_spike"}
    )


def test_breaker_open_before_live_day_stops_scan():
    calls = []
    run, published, _ = _run(_breaker_open, None, calls=calls)
    assert calls == []  # the live day was never scanned
    assert run.status == "failed"
    assert "Polygon degraded" in run.error_message
    assert run.data_degraded is True
    (issue,) = _live_issues(run)
    assert issue["severity"] == "blocker"
    assert issue["detail"]["reason"] == "breaker_open"
    assert issue["detail"]["breaker_open_workers"] == ["celery:1"]
    assert issue["detail"]["worker"]  # process that observed it
    assert published[-1]["type"] == "failed"
    assert not any(p.get("type") == "completed" for p in published)
    assert _gauge() == 2


def test_empty_but_green_completes_but_is_marked_blocker():
    diag = {
        "tickers": 1,
        "evaluated": 0,
        "no_premarket_data": 1,
        "no_history": 0,
        "errors": 0,
        "max_premarket_bar_ts": None,
    }
    run, published, _ = _run(_healthy, diag)
    assert run.status == "completed"
    assert run.data_degraded is True
    (issue,) = _live_issues(run)
    assert (issue["severity"], issue["detail"]["reason"]) == (
        "blocker",
        "no_fresh_premarket_bars",
    )
    completed = [p for p in published if p.get("type") == "completed"][-1]
    assert completed["data_degraded"] is True
    assert _gauge() == 2


def test_partial_coverage_marks_warning_with_ratio():
    diag = {
        "tickers": 10,
        "evaluated": 2,
        "no_premarket_data": 8,
        "no_history": 0,
        "errors": 0,
        "max_premarket_bar_ts": "2026-06-02T11:58:00+00:00",
    }
    run, _, _ = _run(_healthy, diag)
    assert run.status == "completed"
    (issue,) = _live_issues(run)
    assert issue["severity"] == "warning"
    assert issue["detail"]["coverage_ratio"] == 0.2
    assert _gauge() == 1


def test_healthy_live_scan_stays_clean():
    diag = {
        "tickers": 10,
        "evaluated": 9,
        "no_premarket_data": 1,
        "no_history": 0,
        "errors": 0,
        "max_premarket_bar_ts": "2026-06-02T11:58:00+00:00",
    }
    run, published, _ = _run(_healthy, diag)
    assert run.status == "completed"
    assert run.data_degraded is False
    assert _live_issues(run) == []
    assert [p for p in published if p.get("type") == "completed"][-1][
        "data_degraded"
    ] is False
    assert _gauge() == 0


def test_breaker_opening_mid_scan_fails_run_at_completion():
    states = iter([_healthy(), _breaker_open()])
    diag = {
        "tickers": 1,
        "evaluated": 1,
        "no_premarket_data": 0,
        "no_history": 0,
        "errors": 0,
        "max_premarket_bar_ts": "2026-06-02T11:58:00+00:00",
    }
    run, published, _ = _run(lambda: next(states), diag)
    assert run.status == "failed"
    assert "at completion" in run.error_message
    assert run.data_degraded is True
    assert published[-1]["type"] == "failed"


def test_historical_range_never_consults_provider_health():
    run, published, health_mock = _run(
        _breaker_open, None, start=date(2026, 5, 26), end=date(2026, 5, 29)
    )
    health_mock.assert_not_called()
    assert run.status == "completed"
    assert run.data_degraded is False


def test_findings_record_the_phase_they_were_raised_in():
    """#388 review A3: on-call must distinguish "never scanned" from
    "scanned, then failed at completion"."""
    run, _, _ = _run(_breaker_open, None)
    (issue,) = _live_issues(run)
    assert issue["detail"]["phase"] == "before_day"

    states = iter([_healthy(), _breaker_open()])
    diag = {
        "tickers": 1,
        "evaluated": 1,
        "no_premarket_data": 0,
        "no_history": 0,
        "errors": 0,
        "max_premarket_bar_ts": "2026-06-02T11:58:00+00:00",
    }
    run2, _, _ = _run(lambda: next(states), diag)
    (issue2,) = _live_issues(run2)
    assert issue2["detail"]["phase"] == "at_completion"
    assert run2.events_detected == 0  # events, if any, stay recorded on the run

    # Warning-only completion findings carry the phase too (they take the
    # apply_provider_gaps path, not _stop_for_provider_degradation).
    run3, _, _ = _run(
        _healthy,
        {
            "tickers": 10,
            "evaluated": 2,
            "no_premarket_data": 8,
            "no_history": 0,
            "errors": 0,
            "max_premarket_bar_ts": "2026-06-02T11:58:00+00:00",
        },
    )
    (issue3,) = _live_issues(run3)
    assert (issue3["severity"], issue3["detail"]["phase"]) == (
        "warning",
        "at_completion",
    )


def test_live_day_run_clears_a_latched_severity_gauge():
    """#388 review A2: a fresh live-day run must not inherit yesterday's blocker."""
    from app.core.metrics import scan_provider_gap_severity

    scan_provider_gap_severity.labels(scanner_type="pre_market_volume_spike").set(2)
    diag = {
        "tickers": 10,
        "evaluated": 9,
        "no_premarket_data": 1,
        "no_history": 0,
        "errors": 0,
        "max_premarket_bar_ts": "2026-06-02T11:58:00+00:00",
    }
    _run(_healthy, diag)
    assert _gauge() == 0


def test_weekday_market_holiday_does_not_page():
    """#388 review A1: no pre-market bars on a NYSE full close is not an outage."""
    from app.core.metrics import scan_provider_gap_severity

    # A holiday is not a live session day, so the scan neither raises nor resets
    # the gauge. Seed it here so the assertion below does not depend on an
    # earlier test in this file having created the label's child.
    scan_provider_gap_severity.labels(scanner_type="pre_market_volume_spike").set(0)
    diag = {
        "tickers": 10,
        "evaluated": 0,
        "no_premarket_data": 10,
        "no_history": 0,
        "errors": 0,
        "max_premarket_bar_ts": None,
    }
    holiday = date(2026, 11, 26)  # Thursday, NYSE full close
    run, _, _ = _run(
        _healthy,
        diag,
        start=holiday,
        end=holiday,
        now=datetime(2026, 11, 26, 13, 0),
        holidays=[holiday],
    )
    assert run.status == "completed"
    assert run.data_degraded is False
    assert _gauge() == 0
