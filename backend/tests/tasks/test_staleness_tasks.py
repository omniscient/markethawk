"""
Tests for check_aggregate_staleness task and compute_universe_data_health helper.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch


def _make_db_mock(tickers=None, max_ts=None, timestamps=None):
    """Build a minimal DB mock for staleness tests."""
    db = MagicMock()

    # Ticker query returns a list of objects with .ticker
    if tickers is None:
        tickers = []
    ticker_objs = [MagicMock(ticker=t) for t in tickers]
    db.query.return_value.filter.return_value.all.return_value = ticker_objs

    # scalar() returns the MAX timestamp
    db.query.return_value.filter.return_value.scalar.return_value = max_ts

    # order_by().limit().all() returns timestamp rows for gap detection
    ts_rows = [MagicMock(timestamp=ts) for ts in (timestamps or [])]
    db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = ts_rows

    return db


class TestLoadQualityThresholds:
    def test_defaults_when_no_config(self):
        import app.tasks.quality as q

        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []

        staleness, gap_min, alert_pct = q._load_quality_thresholds(db)
        assert staleness == 48
        assert gap_min == 2
        assert alert_pct == 20

    def test_reads_from_system_config(self):
        import app.tasks.quality as q

        row_staleness = MagicMock()
        row_staleness.key = "quality_staleness_hours"
        row_staleness.value = "72"

        row_gap = MagicMock()
        row_gap.key = "quality_gap_min_weekdays"
        row_gap.value = "3"

        row_alert = MagicMock()
        row_alert.key = "quality_alert_pct"
        row_alert.value = "10"

        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [
            row_staleness,
            row_gap,
            row_alert,
        ]

        staleness, gap_min, alert_pct = q._load_quality_thresholds(db)
        assert staleness == 72
        assert gap_min == 3
        assert alert_pct == 10

    def test_bad_value_falls_back_to_default(self):
        import app.tasks.quality as q

        bad_row = MagicMock()
        bad_row.key = "quality_staleness_hours"
        bad_row.value = "not_an_int"

        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [bad_row]

        staleness, _, _ = q._load_quality_thresholds(db)
        assert staleness == 48


class TestComputeUniverseDataHealth:
    def test_empty_universe_returns_grade_A_not_degraded(self):
        import app.tasks.quality as q

        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []

        with patch(
            "app.tasks.quality._load_quality_thresholds", return_value=(48, 2, 20)
        ):
            result = q.compute_universe_data_health(db, universe_id=1)

        assert result["degraded"] is False
        assert result["grade"] == "A"
        assert result["ticker_count"] == 0

    def test_stale_ticker_increments_stale_count(self):
        """A ticker whose last bar is >48h old should be counted as stale."""
        import app.tasks.quality as q

        old_ts = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=100)

        ticker_objs = [MagicMock(ticker="AAPL")]
        db = MagicMock()

        call_count = [0]

        def _query_side(*args):
            call_count[0] += 1
            mock = MagicMock()
            mock.filter.return_value.all.return_value = ticker_objs
            mock.filter.return_value.scalar.return_value = old_ts
            mock.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
            return mock

        db.query.side_effect = _query_side

        with patch(
            "app.tasks.quality._load_quality_thresholds", return_value=(48, 2, 20)
        ):
            result = q.compute_universe_data_health(db, universe_id=1)

        assert result["stale_count"] >= 1
        assert result["worst_staleness_hours"] > 48

    def test_no_bars_for_ticker_treated_as_stale(self):
        """A ticker with no day bars should be counted as stale."""
        import app.tasks.quality as q

        ticker_objs = [MagicMock(ticker="AAPL")]
        db = MagicMock()

        def _query_side(*args):
            mock = MagicMock()
            mock.filter.return_value.all.return_value = ticker_objs
            mock.filter.return_value.scalar.return_value = None  # no bars
            mock.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
            return mock

        db.query.side_effect = _query_side

        with patch(
            "app.tasks.quality._load_quality_thresholds", return_value=(48, 2, 20)
        ):
            result = q.compute_universe_data_health(db, universe_id=1)

        assert result["stale_count"] == 1

    def test_degraded_flag_set_when_stale_pct_exceeds_alert(self):
        """degraded=True when stale_pct > alert_pct."""
        import app.tasks.quality as q

        # Two tickers, both stale → 100% stale > 20% threshold
        ticker_objs = [MagicMock(ticker="AAPL"), MagicMock(ticker="MSFT")]
        old_ts = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=200)

        db = MagicMock()

        def _query_side(*args):
            mock = MagicMock()
            mock.filter.return_value.all.return_value = ticker_objs
            mock.filter.return_value.scalar.return_value = old_ts
            mock.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
            return mock

        db.query.side_effect = _query_side

        with patch(
            "app.tasks.quality._load_quality_thresholds", return_value=(48, 2, 20)
        ):
            result = q.compute_universe_data_health(db, universe_id=1)

        assert result["degraded"] is True


class TestComputeDataDegraded:
    def test_missing_report_returns_true(self):
        from app.tasks.scanning import _compute_data_degraded

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        assert _compute_data_degraded(1, db) is True

    def test_fresh_report_grade_A_returns_false(self):
        from app.tasks.scanning import _compute_data_degraded

        fresh_ts = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        report = MagicMock()
        report.generated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        report.overall_grade = "A"
        report.report_data = {
            "tickers": [
                {"ticker": "AAPL", "last_bar": fresh_ts, "gap_count": 0},
                {"ticker": "MSFT", "last_bar": fresh_ts, "gap_count": 0},
            ]
        }

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = report
        db.query.return_value.filter.return_value.all.return_value = []

        result = _compute_data_degraded(1, db)
        assert result is False

    def test_old_report_returns_true(self):
        """Report older than staleness_hours threshold → degraded."""
        from app.tasks.scanning import _compute_data_degraded

        report = MagicMock()
        report.generated_at = datetime.now(timezone.utc).replace(
            tzinfo=None
        ) - timedelta(hours=100)
        report.overall_grade = "A"

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = report

        result = _compute_data_degraded(1, db)
        assert result is True

    def test_grade_D_returns_true(self):
        from app.tasks.scanning import _compute_data_degraded

        report = MagicMock()
        report.generated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        report.overall_grade = "D"

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = report

        result = _compute_data_degraded(1, db)
        assert result is True

    def test_grade_F_returns_true(self):
        from app.tasks.scanning import _compute_data_degraded

        report = MagicMock()
        report.generated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        report.overall_grade = "F"

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = report

        result = _compute_data_degraded(1, db)
        assert result is True

    def test_uses_affected_pct_not_overall_grade(self):
        """degraded must be based on affected_pct > alert_pct from report_data.tickers,
        not overall_grade. A grade-C report with 100% stale tickers should be degraded."""
        from app.tasks.scanning import _compute_data_degraded

        old_ts = (
            datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=100)
        ).isoformat()
        report = MagicMock()
        report.generated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        report.overall_grade = "C"  # current impl would return False for C
        report.report_data = {
            "tickers": [
                {"ticker": "AAPL", "last_bar": old_ts, "gap_count": 0},
                {"ticker": "MSFT", "last_bar": old_ts, "gap_count": 0},
            ]
        }

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = report
        db.query.return_value.filter.return_value.all.return_value = []  # no SystemConfig

        # 100% stale > 20% alert_pct → must be True
        result = _compute_data_degraded(1, db)
        assert result is True, (
            "grade-C report with 100% stale tickers should be degraded"
        )

    def test_healthy_tickers_not_degraded_regardless_of_grade(self):
        """A report with 0% stale/gapped tickers should not be degraded even if
        the grade is low — affected_pct (0%) is below alert_pct (20%)."""
        from app.tasks.scanning import _compute_data_degraded

        fresh_ts = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        report = MagicMock()
        report.generated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        report.overall_grade = "D"  # old impl would return True for D
        report.report_data = {
            "tickers": [
                {"ticker": "AAPL", "last_bar": fresh_ts, "gap_count": 0},
                {"ticker": "MSFT", "last_bar": fresh_ts, "gap_count": 0},
            ]
        }

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = report
        db.query.return_value.filter.return_value.all.return_value = []

        # 0% affected < 20% alert_pct → should be False
        result = _compute_data_degraded(1, db)
        assert result is False, (
            "0% stale/gapped should not be degraded regardless of grade"
        )


class TestWorstGapDaysIsWeekdays:
    def test_worst_gap_days_counts_weekdays_not_calendar_days(self):
        """aggregate_gap_days gauge must report weekday span, not calendar-day span.
        Monday→next Monday = 7 calendar days but 5 weekdays."""
        import app.tasks.quality as q

        monday1 = datetime(2024, 1, 1, 0, 0, 0)  # Monday
        tuesday = datetime(2024, 1, 2, 0, 0, 0)  # next day (no gap)
        monday2 = datetime(
            2024, 1, 8, 0, 0, 0
        )  # Monday next week (7 cal, 5 weekday gap)

        ticker_objs = [MagicMock(ticker="AAPL")]
        db = MagicMock()

        call_count = [0]

        def _query_side(*args):
            call_count[0] += 1
            mock = MagicMock()
            mock.filter.return_value.all.return_value = ticker_objs
            # MAX timestamp returns monday2
            mock.filter.return_value.scalar.return_value = monday2
            # Gap timestamps: monday1, tuesday, then a big jump to monday2
            ts_rows = [
                MagicMock(timestamp=monday1),
                MagicMock(timestamp=tuesday),
                MagicMock(timestamp=monday2),
            ]
            mock.filter.return_value.order_by.return_value.limit.return_value.all.return_value = ts_rows
            return mock

        db.query.side_effect = _query_side

        with patch(
            "app.tasks.quality._load_quality_thresholds", return_value=(48, 2, 20)
        ):
            result = q.compute_universe_data_health(db, universe_id=1)

        # The gap from tuesday (Jan 2) to monday2 (Jan 8) spans 5 weekdays (Wed-Thu-Fri + Mon)
        # wait: Jan 2 (Tue) to Jan 8 (Mon): weekdays strictly between = Wed3,Thu4,Fri5 = 3 weekdays
        # Actually _count_weekdays_between(Jan2, Jan8) counts strictly between:
        # Jan3(Wed), Jan4(Thu), Jan5(Fri) = 3 weekdays
        # Calendar days = 6 (Jan2 to Jan8)
        # worst_gap_days should be 3 (weekdays), not 6 (calendar)
        assert result["worst_gap_days"] < 6, (
            f"worst_gap_days={result['worst_gap_days']} should be weekday count (<6), not calendar days"
        )
        assert result["worst_gap_days"] >= 1, "should detect at least 1 weekday in gap"
