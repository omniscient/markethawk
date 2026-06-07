"""Unit tests for quality.py Celery task shells."""

from unittest.mock import MagicMock, patch

import pytest


def _make_report(universe_id=1, has_data=True, norm_data=None):
    r = MagicMock()
    r.universe_id = universe_id
    r.status = "pending"
    r.normalization_status = "pending"
    r.report_data = (
        {"overall_grade": "B", "overall_score": 80, "ticker_count": 5}
        if has_data
        else None
    )
    r.normalization_data = norm_data
    r.overall_grade = None
    r.overall_score = None
    r.ticker_count = None
    r.error_message = None
    return r


class TestAnalyzeUniverseQuality:
    def _run(self, report, analyze_result=None, analyze_raises=None):
        import app.tasks.quality as quality_module

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = report

        if analyze_result is None:
            analyze_result = {
                "overall_grade": "A",
                "overall_score": 95,
                "ticker_count": 10,
            }

        with (
            patch("app.tasks.quality.SessionLocal", return_value=db),
            patch(
                "app.services.data_quality.DataQualityService.analyze_universe",
                side_effect=analyze_raises or (lambda *a, **kw: analyze_result),
            ),
        ):
            if analyze_raises:
                with pytest.raises(Exception):
                    quality_module.analyze_universe_quality.run(1)
            else:
                quality_module.analyze_universe_quality.run(1)

        return db, report

    def test_sets_report_complete_on_success(self):
        report = _make_report()
        db, r = self._run(report)
        assert r.status == "complete"
        assert r.overall_grade == "A"
        assert r.overall_score == 95

    def test_creates_report_when_none_exists(self):
        import app.tasks.quality as quality_module

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        with (
            patch("app.tasks.quality.SessionLocal", return_value=db),
            patch(
                "app.services.data_quality.DataQualityService.analyze_universe",
                return_value={
                    "overall_grade": "A",
                    "overall_score": 95,
                    "ticker_count": 5,
                },
            ),
        ):
            quality_module.analyze_universe_quality.run(1)

        db.add.assert_called_once()

    def test_sets_report_error_on_exception(self):
        import app.tasks.quality as quality_module

        report = _make_report()
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = report

        with (
            patch("app.tasks.quality.SessionLocal", return_value=db),
            patch(
                "app.services.data_quality.DataQualityService.analyze_universe",
                side_effect=RuntimeError("analysis failed"),
            ),
        ):
            with pytest.raises(RuntimeError):
                quality_module.analyze_universe_quality.run(1)

        assert report.status == "error"
        assert "analysis failed" in report.error_message

    def test_running_status_set_before_analysis(self):
        """report.status must be 'running' before analysis is called."""
        import app.tasks.quality as quality_module

        report = _make_report()
        status_at_call = []
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = report

        def _capture_status(*a, **kw):
            status_at_call.append(report.status)
            return {"overall_grade": "A", "overall_score": 95, "ticker_count": 5}

        with (
            patch("app.tasks.quality.SessionLocal", return_value=db),
            patch(
                "app.services.data_quality.DataQualityService.analyze_universe",
                side_effect=_capture_status,
            ),
        ):
            quality_module.analyze_universe_quality.run(1)

        assert status_at_call == ["running"]


class TestNormalizeUniverseQuality:
    def _run(self, report, norm_result=None, norm_raises=None):
        import app.tasks.quality as quality_module

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = report

        if norm_result is None:
            norm_result = {"fixes_applied": 3, "status": "complete"}

        with (
            patch("app.tasks.quality.SessionLocal", return_value=db),
            patch(
                "app.services.normalization.NormalizationService.run",
                side_effect=norm_raises or (lambda **kw: norm_result),
            ),
            patch("app.tasks.quality.analyze_universe_quality") as mock_analyze,
        ):
            if norm_raises:
                with pytest.raises(Exception):
                    quality_module.normalize_universe_quality.run(1)
            else:
                quality_module.normalize_universe_quality.run(1)
            return db, report, mock_analyze

    def test_raises_when_no_quality_report_exists(self):
        import app.tasks.quality as quality_module

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        with patch("app.tasks.quality.SessionLocal", return_value=db):
            with pytest.raises(RuntimeError, match="Quality analysis must be run"):
                quality_module.normalize_universe_quality.run(1)

    def test_raises_when_report_has_no_data(self):
        import app.tasks.quality as quality_module

        report = _make_report(has_data=False)
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = report

        with patch("app.tasks.quality.SessionLocal", return_value=db):
            with pytest.raises(RuntimeError, match="Quality analysis must be run"):
                quality_module.normalize_universe_quality.run(1)

    def test_sets_complete_and_triggers_analysis_on_success(self):
        report = _make_report()
        db, r, mock_analyze = self._run(report)
        assert r.normalization_status == "complete"
        mock_analyze.delay.assert_called_once_with(1)

    def test_sets_normalization_error_on_failure(self):
        import app.tasks.quality as quality_module

        report = _make_report()
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = report

        with (
            patch("app.tasks.quality.SessionLocal", return_value=db),
            patch(
                "app.services.normalization.NormalizationService.run",
                side_effect=RuntimeError("norm failed"),
            ),
        ):
            with pytest.raises(RuntimeError):
                quality_module.normalize_universe_quality.run(1)

        assert report.normalization_status == "error"


class TestAnalyzeSignalFeatures:
    def test_insufficient_data_sets_failed_status(self):
        import app.tasks.quality as quality_module

        db = MagicMock()
        created_run = MagicMock()
        created_run.id = 1

        # Simulate a query returning fewer than 500 unique events
        mock_rows = [
            MagicMock(
                event_id=i,
                scanner_type="pre_market",
                indicators={},
                interval_key="1h",
                pct_change=1.0,
            )
            for i in range(10)
        ]

        # The task queries ScannerEvent+joins, returns rows; we simplify by
        # patching the whole query chain to return our sparse rows
        query_chain = MagicMock()
        query_chain.join.return_value = query_chain
        query_chain.filter.return_value = query_chain
        query_chain.all.return_value = mock_rows
        db.query.return_value = query_chain

        # Also handle SignalAnalysisRun creation
        db.add = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock(side_effect=lambda obj: None)

        with patch("app.tasks.quality.SessionLocal", return_value=db):
            with patch(
                "app.models.signal_analysis_run.SignalAnalysisRun",
                return_value=created_run,
            ):
                quality_module.analyze_signal_features.run()

        assert created_run.status == "failed"
        assert "Insufficient" in created_run.error_message
