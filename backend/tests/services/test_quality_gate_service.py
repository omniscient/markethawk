"""
Unit tests for quality_gate._build_assessment and QualityGateService.assess().
No DB fixture required for builder tests — all use plain dict inputs.
"""

from datetime import date, datetime, timedelta, timezone

from app.schemas.quality_gate import (
    QualityGatePolicy,
    QualityGateScope,
    QualityGateVerdict,
    QualityIssueCode,
)
from app.services.quality_gate import _build_assessment

# Most fixtures want a "fresh" last_bar so the stale_quote check does not fire
# for tests that are about other checks. Use today so it is never stale.
_FRESH_LAST_BAR = date.today().isoformat() + "T00:00:00"


def _stale_last_bar(days: int = 14) -> str:
    """An ISO last_bar that is comfortably stale under every threshold."""
    return (date.today() - timedelta(days=days)).isoformat() + "T00:00:00"


def _scope() -> QualityGateScope:
    return QualityGateScope(universe_id=1)


def _report(overall_score=90.0, overall_grade="A", tickers=None):
    if tickers is None:
        tickers = [
            {
                "ticker": "AAPL",
                "gap_count": 0,
                "continuity_score": 100.0,
                "first_bar": "2025-01-01T00:00:00",
                "last_bar": _FRESH_LAST_BAR,
                "coverage_pct": overall_score,
            }
        ]
    return {
        "overall_score": overall_score,
        "overall_grade": overall_grade,
        "tickers": tickers,
    }


def _data_requirements(lookback_days: int = 30) -> dict:
    return {
        "timespans": [
            {"timespan": "minute", "multiplier": 5, "lookback_days": lookback_days}
        ]
    }


# ── Test 1: policy=off ────────────────────────────────────────────────────────


def test_policy_off_returns_skipped():
    result = _build_assessment(None, None, _scope(), QualityGatePolicy.off)
    assert result.verdict == QualityGateVerdict.skipped
    assert result.trusted is False
    assert result.issues == []
    assert result.score is None
    assert result.grade is None


def test_policy_off_ignores_report_content():
    result = _build_assessment(_report(), None, _scope(), QualityGatePolicy.off)
    assert result.verdict == QualityGateVerdict.skipped
    assert result.issues == []


# ── Test 2: missing report + strict ──────────────────────────────────────────


def test_missing_report_strict_is_blocked():
    result = _build_assessment(None, None, _scope(), QualityGatePolicy.strict)
    assert result.verdict == QualityGateVerdict.blocked
    blocker_codes = [i.code for i in result.issues if i.severity == "blocker"]
    assert QualityIssueCode.missing_bars in blocker_codes


# ── Test 3: missing report + advisory ────────────────────────────────────────


def test_missing_report_advisory_is_warning():
    result = _build_assessment(None, None, _scope(), QualityGatePolicy.advisory)
    assert result.verdict == QualityGateVerdict.warning
    assert any(
        i.code == QualityIssueCode.missing_bars and i.severity == "warning"
        for i in result.issues
    )


# ── Test 4: coverage_pct < 70 ────────────────────────────────────────────────


def test_coverage_below_70_strict_is_blocked():
    result = _build_assessment(
        _report(overall_score=60.0), None, _scope(), QualityGatePolicy.strict
    )
    assert result.verdict == QualityGateVerdict.blocked
    assert any(
        i.code == QualityIssueCode.missing_bars and i.severity == "blocker"
        for i in result.issues
    )


def test_coverage_below_70_advisory_is_warning():
    result = _build_assessment(
        _report(overall_score=60.0), None, _scope(), QualityGatePolicy.advisory
    )
    assert result.verdict == QualityGateVerdict.warning
    assert any(i.code == QualityIssueCode.missing_bars for i in result.issues)


# ── Test 5: 70 ≤ coverage_pct < 85 ───────────────────────────────────────────


def test_coverage_70_to_85_emits_warning():
    result = _build_assessment(
        _report(overall_score=78.0), None, _scope(), QualityGatePolicy.strict
    )
    assert result.verdict == QualityGateVerdict.warning
    assert any(
        i.code == QualityIssueCode.missing_bars and i.severity == "warning"
        for i in result.issues
    )


# ── Test 6: coverage ≥ 85, no gaps → trusted ─────────────────────────────────


def test_clean_report_is_trusted():
    result = _build_assessment(
        _report(overall_score=92.0), None, _scope(), QualityGatePolicy.strict
    )
    assert result.verdict == QualityGateVerdict.trusted
    assert result.trusted is True
    assert result.issues == []
    assert result.score == 92.0


# ── Test 7: gap_count ≥ 1 → warning ─────────────────────────────────────────


def test_gap_count_one_emits_provider_gap_warning():
    report = _report(
        overall_score=90.0,
        tickers=[
            {
                "ticker": "AAPL",
                "gap_count": 1,
                "continuity_score": 95.0,
                "first_bar": "2025-01-01T00:00:00",
                "last_bar": _FRESH_LAST_BAR,
                "coverage_pct": 90.0,
            }
        ],
    )
    result = _build_assessment(report, None, _scope(), QualityGatePolicy.strict)
    assert result.verdict == QualityGateVerdict.warning
    assert any(
        i.code == QualityIssueCode.provider_gap and i.severity == "warning"
        for i in result.issues
    )
    assert any(i.severity == "warning" for i in result.warnings)


# ── Test 8: continuity_score < 70 → blocker ──────────────────────────────────


def test_continuity_below_70_strict_is_blocked():
    report = _report(
        overall_score=90.0,
        tickers=[
            {
                "ticker": "AAPL",
                "gap_count": 15,
                "continuity_score": 25.0,
                "first_bar": "2025-01-01T00:00:00",
                "last_bar": _FRESH_LAST_BAR,
                "coverage_pct": 90.0,
            }
        ],
    )
    result = _build_assessment(report, None, _scope(), QualityGatePolicy.strict)
    assert result.verdict == QualityGateVerdict.blocked
    assert any(
        i.code == QualityIssueCode.provider_gap and i.severity == "blocker"
        for i in result.issues
    )


# ── Test 9: insufficient_lookback ────────────────────────────────────────────


def test_insufficient_lookback_emits_blocker():
    first_bar = (date.today() - timedelta(days=10)).isoformat() + "T00:00:00"
    report = _report(
        overall_score=92.0,
        tickers=[
            {
                "ticker": "AAPL",
                "gap_count": 0,
                "continuity_score": 100.0,
                "first_bar": first_bar,
                "last_bar": _FRESH_LAST_BAR,
                "coverage_pct": 92.0,
            }
        ],
    )
    result = _build_assessment(
        report, _data_requirements(lookback_days=30), _scope(), QualityGatePolicy.strict
    )
    assert any(
        i.code == QualityIssueCode.insufficient_lookback and i.severity == "blocker"
        for i in result.issues
    )


# ── Test 10: assessment shape ─────────────────────────────────────────────────


def test_assessment_shape():
    result = _build_assessment(_report(), None, _scope(), QualityGatePolicy.strict)
    assert result.schema_version == "quality_gate.v1"
    assert result.policy is not None
    assert result.verdict is not None
    assert isinstance(result.trusted, bool)
    assert result.scope is not None
    assert result.generated_at is not None
    assert result.trusted == (result.verdict == QualityGateVerdict.trusted)


# ── Advisory variants (tests 11-12) ──────────────────────────────────────────


def test_coverage_below_70_advisory_blocker_becomes_warning():
    """Under advisory, a blocker-severity issue still yields verdict=warning not blocked."""
    result = _build_assessment(
        _report(overall_score=50.0), None, _scope(), QualityGatePolicy.advisory
    )
    assert result.verdict == QualityGateVerdict.warning
    assert result.trusted is False


def test_continuity_below_70_advisory_is_warning():
    """Under advisory, a provider_gap blocker still yields verdict=warning not blocked."""
    report = _report(
        overall_score=90.0,
        tickers=[
            {
                "ticker": "AAPL",
                "gap_count": 20,
                "continuity_score": 10.0,
                "first_bar": "2025-01-01T00:00:00",
                "last_bar": _FRESH_LAST_BAR,
                "coverage_pct": 90.0,
            }
        ],
    )
    result = _build_assessment(report, None, _scope(), QualityGatePolicy.advisory)
    assert result.verdict == QualityGateVerdict.warning
    assert result.trusted is False


# ── DB wrapper smoke tests ─────────────────────────────────────────────────────


def test_assess_wrapper_with_complete_report():
    """QualityGateService.assess() delegates to _build_assessment correctly."""
    from unittest.mock import MagicMock

    from app.schemas.data_quality import GateRequest
    from app.services.quality_gate import QualityGateService

    mock_report = MagicMock()
    mock_report.status = "complete"
    mock_report.report_data = {
        "overall_score": 92.0,
        "overall_grade": "A",
        "tickers": [
            {
                "ticker": "AAPL",
                "gap_count": 0,
                "continuity_score": 100.0,
                "first_bar": "2025-01-01T00:00:00",
                "last_bar": _FRESH_LAST_BAR,
                "coverage_pct": 92.0,
            }
        ],
    }

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = mock_report
    # MarketHoliday lookup uses .all(); return no holidays.
    mock_db.query.return_value.filter.return_value.all.return_value = []

    body = GateRequest(universe_id=1, policy="strict", consumer="scanner")
    result = QualityGateService.assess(db=mock_db, request=body)
    assert result.verdict == QualityGateVerdict.trusted
    assert result.trusted is True
    assert result.score == 92.0


def test_assess_wrapper_missing_report_strict():
    """Missing row → blocked under strict policy via the DB wrapper."""
    from unittest.mock import MagicMock

    from app.schemas.data_quality import GateRequest
    from app.services.quality_gate import QualityGateService

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None

    body = GateRequest(universe_id=99, policy="strict", consumer="scanner")
    result = QualityGateService.assess(db=mock_db, request=body)
    assert result.verdict == QualityGateVerdict.blocked


def test_assess_wrapper_incomplete_report_strict():
    """Report row present but status != 'complete' → treated as absent → blocked (strict)."""
    from unittest.mock import MagicMock

    from app.schemas.data_quality import GateRequest
    from app.services.quality_gate import QualityGateService

    mock_report = MagicMock()
    mock_report.status = "running"
    mock_report.report_data = {
        "overall_score": 95.0,
        "overall_grade": "A",
        "tickers": [],
    }

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = mock_report

    body = GateRequest(universe_id=5, policy="strict", consumer="scanner")
    result = QualityGateService.assess(db=mock_db, request=body)
    assert result.verdict == QualityGateVerdict.blocked
    assert any(i.code == QualityIssueCode.missing_bars for i in result.issues)


# ── #499: stale_quote ─────────────────────────────────────────────────────────


def _clean_ticker(**overrides) -> dict:
    """A fully-fresh, high-coverage ticker entry; override per test."""
    base = {
        "ticker": "AAPL",
        "timespan": "minute",
        "multiplier": 5,
        "gap_count": 0,
        "continuity_score": 100.0,
        "first_bar": "2025-01-01T00:00:00",
        "last_bar": _FRESH_LAST_BAR,
        "coverage_pct": 95.0,
        "actual_bars": 1000,
        "expected_bars": 1050,
    }
    base.update(overrides)
    return base


def _report_with(tickers, overall_score=95.0, generated_at=None) -> dict:
    report = {
        "overall_score": overall_score,
        "overall_grade": "A",
        "tickers": tickers,
    }
    if generated_at is not None:
        report["generated_at"] = generated_at
    return report


def test_stale_strict_emits_blocker():
    report = _report_with([_clean_ticker(last_bar=_stale_last_bar(14))])
    result = _build_assessment(report, None, _scope(), QualityGatePolicy.strict)
    assert result.verdict == QualityGateVerdict.blocked
    stale = [i for i in result.issues if i.code == QualityIssueCode.stale_quote]
    assert stale and stale[0].severity == "blocker"
    assert stale[0].detail["subtype"] == "ticker_stale"
    assert stale[0].detail["threshold_trading_days"] == 1
    assert stale[0].detail["source"] is None


def test_stale_advisory_emits_warning():
    report = _report_with([_clean_ticker(last_bar=_stale_last_bar(21))])
    result = _build_assessment(report, None, _scope(), QualityGatePolicy.advisory)
    assert result.verdict == QualityGateVerdict.warning
    stale = [i for i in result.issues if i.code == QualityIssueCode.stale_quote]
    assert stale and stale[0].severity == "warning"
    assert stale[0].detail["threshold_trading_days"] == 5  # intraday advisory


def test_fresh_ticker_not_stale():
    report = _report_with([_clean_ticker()])
    result = _build_assessment(report, None, _scope(), QualityGatePolicy.strict)
    assert not any(i.code == QualityIssueCode.stale_quote for i in result.issues)
    assert result.verdict == QualityGateVerdict.trusted


def test_report_freshness_guard_strict_blocks_and_skips_tickers():
    generated = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
    # last_bar is fresh, so any stale_quote can only come from the report guard.
    report = _report_with([_clean_ticker()], generated_at=generated)
    result = _build_assessment(report, None, _scope(), QualityGatePolicy.strict)
    stale = [i for i in result.issues if i.code == QualityIssueCode.stale_quote]
    assert len(stale) == 1
    assert stale[0].severity == "blocker"
    assert stale[0].detail["subtype"] == "report_stale"
    assert result.verdict == QualityGateVerdict.blocked


def test_report_freshness_guard_advisory_warns():
    generated = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
    report = _report_with([_clean_ticker()], generated_at=generated)
    result = _build_assessment(report, None, _scope(), QualityGatePolicy.advisory)
    stale = [i for i in result.issues if i.code == QualityIssueCode.stale_quote]
    assert len(stale) == 1
    assert stale[0].severity == "warning"
    assert stale[0].detail["subtype"] == "report_stale"


def test_report_freshness_fresh_report_does_not_fire():
    generated = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    report = _report_with([_clean_ticker()], generated_at=generated)
    result = _build_assessment(report, None, _scope(), QualityGatePolicy.strict)
    assert not any(i.code == QualityIssueCode.stale_quote for i in result.issues)


def test_as_of_date_override_suppresses_stale():
    # last_bar covers the requested historical date → never stale, even though
    # it is months old in calendar terms and the report snapshot is old.
    generated = (datetime.now(timezone.utc) - timedelta(hours=8)).isoformat()
    report = _report_with(
        [_clean_ticker(last_bar="2026-01-05T00:00:00")], generated_at=generated
    )
    reqs = {"as_of_date": "2026-01-05"}
    result = _build_assessment(report, reqs, _scope(), QualityGatePolicy.strict)
    assert not any(i.code == QualityIssueCode.stale_quote for i in result.issues)
    assert result.verdict == QualityGateVerdict.trusted


def test_as_of_date_stale_when_last_bar_predates_it():
    report = _report_with([_clean_ticker(last_bar="2025-12-01T00:00:00")])
    reqs = {"as_of_date": "2026-01-15"}
    result = _build_assessment(report, reqs, _scope(), QualityGatePolicy.strict)
    stale = [i for i in result.issues if i.code == QualityIssueCode.stale_quote]
    assert stale and stale[0].severity == "blocker"
    assert stale[0].detail["as_of_date"] == "2026-01-15"


def test_market_holidays_reduce_staleness():
    # last_bar Friday, reference the following Tuesday with Monday a holiday →
    # only Tuesday counts as a trading day (1 day stale) → not stale under strict.
    last = date(2026, 6, 12)  # Friday
    ref = date(2026, 6, 16)  # Tuesday
    report = _report_with([_clean_ticker(last_bar=last.isoformat() + "T00:00:00")])
    reqs = {"as_of_date": ref.isoformat()}
    holidays = {date(2026, 6, 15)}  # Monday holiday
    result = _build_assessment(
        report, reqs, _scope(), QualityGatePolicy.strict, market_holidays=holidays
    )
    assert not any(i.code == QualityIssueCode.stale_quote for i in result.issues)
    # Without the holiday, Mon+Tue = 2 trading days → stale blocker.
    result_no_holiday = _build_assessment(
        report, reqs, _scope(), QualityGatePolicy.strict, market_holidays=set()
    )
    assert any(i.code == QualityIssueCode.stale_quote for i in result_no_holiday.issues)


# ── #499: provider_gap subtypes ──────────────────────────────────────────────


def test_provider_gap_absent_is_blocker():
    report = _report_with(
        [_clean_ticker(actual_bars=0, coverage_pct=0.0, last_bar=None)],
        overall_score=95.0,
    )
    result = _build_assessment(report, None, _scope(), QualityGatePolicy.strict)
    absent = [
        i
        for i in result.issues
        if i.code == QualityIssueCode.provider_gap
        and i.detail.get("subtype") == "absent"
    ]
    assert absent and absent[0].severity == "blocker"
    assert result.verdict == QualityGateVerdict.blocked


def test_provider_gap_absent_blocker_under_advisory_is_warning_verdict():
    report = _report_with(
        [_clean_ticker(actual_bars=0, coverage_pct=0.0, last_bar=None)]
    )
    result = _build_assessment(report, None, _scope(), QualityGatePolicy.advisory)
    absent = [
        i
        for i in result.issues
        if i.code == QualityIssueCode.provider_gap
        and i.detail.get("subtype") == "absent"
    ]
    assert absent and absent[0].severity == "blocker"
    assert result.verdict == QualityGateVerdict.warning


def test_provider_gap_partial_absolute():
    report = _report_with(
        [_clean_ticker(coverage_pct=40.0, actual_bars=400)], overall_score=95.0
    )
    result = _build_assessment(report, None, _scope(), QualityGatePolicy.strict)
    partial = [
        i
        for i in result.issues
        if i.code == QualityIssueCode.provider_gap
        and i.detail.get("subtype") == "partial"
    ]
    assert partial and partial[0].severity == "blocker"
    assert partial[0].detail["coverage_pct"] == 40.0


def test_provider_gap_partial_advisory_is_warning():
    report = _report_with([_clean_ticker(coverage_pct=40.0, actual_bars=400)])
    result = _build_assessment(report, None, _scope(), QualityGatePolicy.advisory)
    partial = [
        i
        for i in result.issues
        if i.code == QualityIssueCode.provider_gap
        and i.detail.get("subtype") == "partial"
    ]
    assert partial and partial[0].severity == "warning"


def test_provider_gap_partial_relative_outlier():
    # Two high-coverage tickers anchor the median; the third is >30pts below it
    # and < 80 → flagged as a relative-outlier partial return.
    tickers = [
        _clean_ticker(ticker="AAA", coverage_pct=95.0),
        _clean_ticker(ticker="BBB", coverage_pct=95.0),
        _clean_ticker(ticker="CCC", coverage_pct=60.0, actual_bars=600),
    ]
    report = _report_with(tickers, overall_score=90.0)
    result = _build_assessment(report, None, _scope(), QualityGatePolicy.strict)
    partial = [
        i
        for i in result.issues
        if i.code == QualityIssueCode.provider_gap
        and i.detail.get("subtype") == "partial"
    ]
    assert len(partial) == 1
    assert partial[0].detail["ticker"] == "CCC"
    assert partial[0].detail["universe_median_coverage"] == 95.0


def test_provider_gap_structural_retained():
    report = _report_with(
        [_clean_ticker(gap_count=15, continuity_score=25.0)], overall_score=90.0
    )
    result = _build_assessment(report, None, _scope(), QualityGatePolicy.strict)
    structural = [
        i
        for i in result.issues
        if i.code == QualityIssueCode.provider_gap
        and i.detail.get("subtype") == "structural"
    ]
    assert structural and structural[0].severity == "blocker"


def test_policy_off_suppresses_stale_and_provider_gap():
    tickers = [
        _clean_ticker(last_bar=_stale_last_bar(30)),
        _clean_ticker(ticker="ZZZ", actual_bars=0, coverage_pct=0.0, last_bar=None),
    ]
    report = _report_with(tickers, generated_at="2020-01-01T00:00:00+00:00")
    result = _build_assessment(report, None, _scope(), QualityGatePolicy.off)
    assert result.verdict == QualityGateVerdict.skipped
    assert result.issues == []
