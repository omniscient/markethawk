"""Failure-class → posture mapping for degraded Polygon feeds (#388, ADR-0013)."""

from datetime import date, datetime, timezone
from types import SimpleNamespace

from app.core.config import settings
from app.core.provider_health import LATENCY_BUCKETS, ProviderHealthSnapshot
from app.services.provider_degradation import (
    LIVE_SUBTYPE,
    apply_provider_gaps,
    assess_premarket_ingestion,
    assess_provider_health,
    is_live_session_day,
    live_provider_gaps,
    severity_level,
)

DAY = date(2026, 6, 2)  # Tuesday, EDT (UTC-4)


def _utc(h, m=0):
    return datetime(2026, 6, 2, h, m, tzinfo=timezone.utc)


def _diag(max_bar=None, evaluated=80, no_pm=20, no_history=5, errors=0):
    return {
        "tickers": evaluated + no_pm + no_history + errors,
        "evaluated": evaluated,
        "no_premarket_data": no_pm,
        "no_history": no_history,
        "errors": errors,
        "max_premarket_bar_ts": max_bar,
    }


# --- is_live_session_day ---------------------------------------------------


def test_live_session_day_after_premarket_open():
    assert is_live_session_day(DAY, _utc(12)) is True  # 08:00 ET


def test_not_live_before_premarket_open():
    assert is_live_session_day(DAY, _utc(7)) is False  # 03:00 ET


def test_not_live_for_other_dates():
    assert is_live_session_day(date(2026, 6, 1), _utc(12)) is False


def test_naive_utc_now_is_accepted():
    assert is_live_session_day(DAY, datetime(2026, 6, 2, 12, 0)) is True


def test_weekday_market_holiday_is_not_a_live_session_day():
    """#388 review A1: Thanksgiving 2026-11-26 is a Thursday, so it survives the
    `weekday() < 5` trading_days filter, but it is a NYSE full close."""
    holiday = date(2026, 11, 26)
    now = datetime(2026, 11, 26, 13, 0, tzinfo=timezone.utc)  # 08:00 EST
    assert is_live_session_day(holiday, now) is True  # no holiday set supplied
    assert is_live_session_day(holiday, now, {holiday}) is False


def test_market_holiday_suppresses_no_fresh_bars_blocker():
    holiday = date(2026, 11, 26)
    now = datetime(2026, 11, 26, 13, 0, tzinfo=timezone.utc)
    diag = {
        "tickers": 500,
        "evaluated": 0,
        "no_premarket_data": 500,
        "no_history": 0,
        "errors": 0,
        "max_premarket_bar_ts": None,
    }
    assert assess_premarket_ingestion(diag, holiday, now)  # would page today
    assert assess_premarket_ingestion(diag, holiday, now, {holiday}) == []


def test_live_session_boundary_holds_in_est():
    """#388 review A6: the plan otherwise only tests the EDT (UTC-4) offset."""
    winter = date(2026, 1, 6)  # Tuesday, EST (UTC-5)
    assert (
        is_live_session_day(winter, datetime(2026, 1, 6, 8, 0, tzinfo=timezone.utc))
        is False
    )
    assert (
        is_live_session_day(winter, datetime(2026, 1, 6, 9, 0, tzinfo=timezone.utc))
        is True
    )


# --- assess_provider_health -----------------------------------------------


def test_healthy_snapshot_has_no_findings():
    assert assess_provider_health(ProviderHealthSnapshot(provider="polygon")) == []


def test_breaker_open_is_blocker_and_aborts():
    snap = ProviderHealthSnapshot(
        provider="polygon", breaker_state="open", breaker_open_workers=["w:1"]
    )
    (f,) = assess_provider_health(snap)
    assert (f.reason, f.severity, f.abort) == ("breaker_open", "blocker", True)
    assert f.detail["breaker_open_workers"] == ["w:1"]


def test_error_rate_over_threshold_is_blocker_and_aborts():
    snap = ProviderHealthSnapshot(
        provider="polygon",
        calls_error_window=40,
        errors_error_window=20,
        error_rate=0.5,
    )
    (f,) = assess_provider_health(snap)
    assert (f.reason, f.severity, f.abort) == ("error_rate", "blocker", True)
    assert f.detail["error_rate"] == 0.5


def test_error_rate_below_min_calls_ignored():
    snap = ProviderHealthSnapshot(
        provider="polygon", calls_error_window=2, errors_error_window=2, error_rate=1.0
    )
    assert assess_provider_health(snap) == []


def test_latency_is_warning_and_continues():
    snap = ProviderHealthSnapshot(provider="polygon", latency_p95_seconds=10.0)
    (f,) = assess_provider_health(snap)
    assert (f.reason, f.severity, f.abort) == ("latency", "warning", False)


def test_latency_exactly_at_the_threshold_bucket_is_not_a_finding():
    """latency_p95_seconds is the bucket's upper bound, so == threshold means a
    real p95 anywhere in (2.5s, 5.0s] — healthy-but-slow, not degraded."""
    threshold = settings.POLYGON_HEALTH_LATENCY_P95_THRESHOLD_SECONDS
    assert LATENCY_BUCKETS[5] == threshold == 5.0  # the reported bound
    snap = ProviderHealthSnapshot(provider="polygon", latency_p95_seconds=threshold)
    assert assess_provider_health(snap) == []


# --- assess_premarket_ingestion -------------------------------------------


def test_historical_day_never_assessed():
    assert assess_premarket_ingestion(_diag(), date(2026, 6, 1), _utc(12)) == []


def test_too_early_to_judge():
    assert assess_premarket_ingestion(_diag(), DAY, _utc(8, 5)) == []  # 04:05 ET


def test_no_premarket_bars_is_blocker():
    (f,) = assess_premarket_ingestion(_diag(max_bar=None), DAY, _utc(12))
    assert (f.reason, f.severity, f.abort) == (
        "no_fresh_premarket_bars",
        "blocker",
        False,
    )


def test_empty_universe_is_not_a_polygon_outage():
    """A universe with no tickers has no bars by construction; paging on it
    would blame Polygon for a misconfigured universe."""
    empty = _diag(max_bar=None, evaluated=0, no_pm=0, no_history=0)
    assert empty["tickers"] == 0
    assert assess_premarket_ingestion(empty, DAY, _utc(12)) == []


def test_stale_premarket_bars_is_blocker():
    bar = _utc(11, 40).isoformat()  # 07:40 ET; now 08:00 ET → 20 min old
    (f,) = assess_premarket_ingestion(_diag(max_bar=bar), DAY, _utc(12))
    assert (f.reason, f.severity) == ("stale_premarket_bars", "blocker")
    assert f.detail["minutes_since_last_bar"] == 20.0


def test_fresh_bars_and_good_coverage_have_no_findings():
    bar = _utc(11, 58).isoformat()
    assert assess_premarket_ingestion(_diag(max_bar=bar), DAY, _utc(12)) == []


def test_staleness_not_checked_after_regular_open():
    bar = _utc(13, 29).isoformat()  # 09:29 ET; now 11:00 ET
    assert assess_premarket_ingestion(_diag(max_bar=bar), DAY, _utc(15)) == []


def test_partial_coverage_is_warning_with_ratio():
    bar = _utc(11, 58).isoformat()
    (f,) = assess_premarket_ingestion(
        _diag(max_bar=bar, evaluated=30, no_pm=70), DAY, _utc(12)
    )
    assert (f.reason, f.severity, f.abort) == ("partial_coverage", "warning", False)
    assert f.detail["coverage_ratio"] == 0.3


# --- apply_provider_gaps / live_provider_gaps / severity_level ------------


def _trusted_gate():
    return {
        "schema_version": "quality_gate.v1",
        "policy": "advisory",
        "verdict": "trusted",
        "trusted": True,
        "scope": {"universe_id": 1, "scanner_type": "pre_market_volume_spike"},
        "score": 95.0,
        "grade": "A",
        "issues": [
            {
                "code": "provider_gap",
                "severity": "warning",
                "message": "historical",
                "detail": {"subtype": "structural"},
            }
        ],
        "warnings": [],
        "generated_at": "2026-06-02T11:00:00",
    }


def _findings():
    snap = ProviderHealthSnapshot(provider="polygon", latency_p95_seconds=10.0)
    return assess_provider_health(snap)


def test_apply_appends_live_issue_and_downgrades_verdict():
    run = SimpleNamespace(quality_gate=_trusted_gate(), data_degraded=False)
    apply_provider_gaps(
        run,
        _findings(),
        universe_id=1,
        scanner_type="pre_market_volume_spike",
        worker="celery:9",
    )
    assert run.data_degraded is True
    assert run.quality_gate["verdict"] == "warning"
    assert run.quality_gate["trusted"] is False
    live = [
        i
        for i in run.quality_gate["issues"]
        if i["detail"].get("subtype") == LIVE_SUBTYPE
    ]
    assert len(live) == 1
    assert live[0]["code"] == "provider_gap"
    assert live[0]["detail"]["provider"] == "polygon"
    assert live[0]["detail"]["reason"] == "latency"
    assert live[0]["detail"]["worker"] == "celery:9"
    # the pre-existing historical provider_gap issue is preserved
    assert any(
        i["detail"].get("subtype") == "structural" for i in run.quality_gate["issues"]
    )


def test_apply_is_idempotent_for_live_issues():
    run = SimpleNamespace(quality_gate=_trusted_gate(), data_degraded=False)
    for _ in range(2):
        apply_provider_gaps(
            run,
            _findings(),
            universe_id=1,
            scanner_type="pre_market_volume_spike",
            worker="w",
        )
    assert len(live_provider_gaps(run.quality_gate)) == 1


def test_apply_creates_assessment_when_gate_missing():
    run = SimpleNamespace(quality_gate=None, data_degraded=None)
    apply_provider_gaps(
        run,
        _findings(),
        universe_id=7,
        scanner_type="pre_market_volume_spike",
        worker="w",
    )
    assert run.quality_gate["schema_version"] == "quality_gate.v1"
    assert run.quality_gate["scope"]["universe_id"] == 7
    assert run.quality_gate["policy"] == "advisory"
    assert run.data_degraded is True


def test_apply_with_no_findings_is_noop():
    run = SimpleNamespace(quality_gate=None, data_degraded=False)
    apply_provider_gaps(run, [], universe_id=1, scanner_type="x", worker="w")
    assert run.quality_gate is None and run.data_degraded is False


def test_live_provider_gaps_filters_by_subtype():
    assert live_provider_gaps(None) == []
    assert live_provider_gaps(_trusted_gate()) == []


def test_severity_level():
    assert severity_level([]) == 0
    assert severity_level(_findings()) == 1
    snap = ProviderHealthSnapshot(provider="polygon", breaker_state="open")
    assert severity_level(assess_provider_health(snap)) == 2
