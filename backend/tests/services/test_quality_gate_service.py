"""
Unit tests for quality_gate._build_assessment and QualityGateService.assess().
No DB fixture required for builder tests — all use plain dict inputs.
"""

from datetime import date, timedelta

from app.schemas.quality_gate import (
    QualityGatePolicy,
    QualityGateScope,
    QualityGateVerdict,
    QualityIssueCode,
)
from app.services.quality_gate import _build_assessment


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
                "last_bar": "2026-06-19T00:00:00",
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
                "last_bar": "2026-06-19T00:00:00",
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
                "last_bar": "2026-06-19T00:00:00",
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
                "last_bar": "2026-06-19T00:00:00",
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
                "last_bar": "2026-06-19T00:00:00",
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
                "last_bar": "2026-06-19T00:00:00",
                "coverage_pct": 92.0,
            }
        ],
    }

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = mock_report

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
