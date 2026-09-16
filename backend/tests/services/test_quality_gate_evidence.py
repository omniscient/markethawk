"""
Unit tests for quality_gate_evidence — generate_missing_bars_issues and
generate_insufficient_lookback_issues.

Uses MagicMock for the DB session (service-layer unit tests, not full-pipeline
regression tests). Each test exercises one scenario from AC-6.
"""

from datetime import date, datetime
from unittest.mock import MagicMock

from app.models.stock_aggregate import StockAggregate
from app.models.stock_split import StockSplit
from app.models.stock_universe_ticker import StockUniverseTicker
from app.services.quality_gate_evidence import (
    GateIssue,
    generate_insufficient_lookback_issues,
    generate_missing_bars_issues,
    generate_split_dividend_anomaly_issues,
    generate_timezone_session_mismatch_issues,
)

# --- helpers ----------------------------------------------------------------


def _cfg(timespans: list) -> MagicMock:
    cfg = MagicMock()
    cfg.data_requirements = {"timespans": timespans}
    return cfg


def _flat_cfg() -> MagicMock:
    """Flat data_requirements shape — no timespans key."""
    cfg = MagicMock()
    cfg.data_requirements = {"timespan": "day", "min_bars": 260}
    return cfg


def _db_with_report(
    report_data, ticker_rows=None, scalar_side_effect=None, status="complete"
) -> MagicMock:
    """Build a MagicMock db that returns a cached report and optional bar counts."""
    report_mock = MagicMock()
    report_mock.report_data = report_data
    report_mock.status = status

    filter_mock = MagicMock()
    filter_mock.first.return_value = report_mock
    if ticker_rows is not None:
        filter_mock.all.return_value = ticker_rows
    if scalar_side_effect is not None:
        filter_mock.scalar.side_effect = scalar_side_effect
    else:
        filter_mock.scalar.return_value = 0

    db = MagicMock()
    db.query.return_value.filter.return_value = filter_mock
    return db


# --- GateIssue dataclass ----------------------------------------------------


def test_gate_issue_fields_are_populated():
    issue = GateIssue(
        issue_code="missing_bars",
        ticker="AAPL",
        timespan="minute",
        multiplier=1,
        observed=100,
        required=500,
    )
    assert issue.issue_code == "missing_bars"
    assert issue.ticker == "AAPL"
    assert issue.observed == 100
    assert issue.required == 500


# --- generate_missing_bars_issues -------------------------------------------


def test_missing_bars_flat_shape_returns_empty():
    """Flat data_requirements (no timespans key) -> [] with no DB calls."""
    db = MagicMock()
    issues = generate_missing_bars_issues(db, 1, _flat_cfg(), ticker="AAPL")
    assert issues == []


def test_missing_bars_per_ticker_uses_report_cache():
    """Per-ticker mode: uses report_data cache, emits issue when actual < expected."""
    report_data = {
        "tickers": [
            {
                "ticker": "AAPL",
                "timespan": "minute",
                "multiplier": 1,
                "actual_bars": 200,
                "expected_bars": 500,
            }
        ]
    }
    cfg = _cfg([{"timespan": "minute", "multiplier": 1, "lookback_days": 10}])
    db = _db_with_report(report_data)

    issues = generate_missing_bars_issues(db, 1, cfg, ticker="AAPL")

    assert len(issues) == 1
    assert issues[0].issue_code == "missing_bars"
    assert issues[0].ticker == "AAPL"
    assert issues[0].observed == 200
    assert issues[0].required == 500


def test_missing_bars_no_issue_when_actual_meets_expected():
    """No issue when actual_bars >= expected_bars in cache."""
    report_data = {
        "tickers": [
            {
                "ticker": "AAPL",
                "timespan": "minute",
                "multiplier": 1,
                "actual_bars": 600,
                "expected_bars": 500,
            }
        ]
    }
    cfg = _cfg([{"timespan": "minute", "multiplier": 1, "lookback_days": 10}])
    db = _db_with_report(report_data)

    issues = generate_missing_bars_issues(db, 1, cfg, ticker="AAPL")
    assert issues == []


def test_missing_bars_universe_wide_partial_coverage():
    """Universe-wide (ticker=None): emits issue only for AAPL (below threshold), not MSFT."""
    report_data = {
        "tickers": [
            {
                "ticker": "AAPL",
                "timespan": "minute",
                "multiplier": 1,
                "actual_bars": 200,
                "expected_bars": 500,
            },
            {
                "ticker": "MSFT",
                "timespan": "minute",
                "multiplier": 1,
                "actual_bars": 600,
                "expected_bars": 500,
            },
        ]
    }
    cfg = _cfg([{"timespan": "minute", "multiplier": 1, "lookback_days": 10}])
    ticker_rows = [MagicMock(ticker="AAPL"), MagicMock(ticker="MSFT")]
    db = _db_with_report(report_data, ticker_rows=ticker_rows)

    issues = generate_missing_bars_issues(db, 1, cfg, ticker=None)

    assert len(issues) == 1
    assert issues[0].ticker == "AAPL"


def test_missing_bars_fallback_direct_db_when_no_report():
    """When report_data is absent, falls back to direct SELECT count(*) for actual_bars."""
    cfg = _cfg([{"timespan": "day", "multiplier": 1, "lookback_days": 90}])
    db = _db_with_report(report_data=None, scalar_side_effect=[10])

    issues = generate_missing_bars_issues(db, 1, cfg, ticker="AAPL")

    # expected_bars = 90 * 1 bar/day = 90; actual = 10 -> issue emitted
    assert len(issues) == 1
    assert issues[0].observed == 10
    assert issues[0].required == 90


def test_missing_bars_zero_expected_bars_falls_through_to_direct_count():
    """Cache entry with expected_bars=0 must NOT be trusted — gate would silently
    pass even with 0 actual bars.  After FIX-A the entry is skipped; the code
    falls through to direct count + lookback estimate and emits a missing_bars issue."""
    report_data = {
        "tickers": [
            {
                "ticker": "AAPL",
                "timespan": "minute",
                "multiplier": 1,
                "actual_bars": 0,
                "expected_bars": 0,  # corrupt / absent in report
            }
        ]
    }
    cfg = _cfg([{"timespan": "minute", "multiplier": 1, "lookback_days": 10}])
    # scalar.return_value=0 by default — direct DB count shows no bars
    db = _db_with_report(report_data)

    issues = generate_missing_bars_issues(db, 1, cfg, ticker="AAPL")

    # Fallback: expected = lookback_days(10) * bars_per_day(minute/1=390) = 3900
    # 0 < 3900 -> issue must be emitted (not a silent false-clear)
    assert len(issues) == 1
    assert issues[0].issue_code == "missing_bars"
    assert issues[0].ticker == "AAPL"
    assert issues[0].observed == 0
    assert issues[0].required == 3900


def test_missing_bars_running_report_ignored_falls_through():
    """A report with status='running' must be ignored; the code falls through to the
    direct count path and emits a missing_bars issue rather than trusting stale data."""
    report_data = {
        "tickers": [
            {
                "ticker": "AAPL",
                "timespan": "minute",
                "multiplier": 1,
                "actual_bars": 500,
                "expected_bars": 500,  # would look healthy if trusted
            }
        ]
    }
    cfg = _cfg([{"timespan": "minute", "multiplier": 1, "lookback_days": 10}])
    # Report is running — cache must be ignored; direct count shows 0 bars
    db = _db_with_report(report_data, status="running")

    issues = generate_missing_bars_issues(db, 1, cfg, ticker="AAPL")

    # Cache not trusted; fallback: 0 < 3900 -> issue emitted
    assert len(issues) == 1
    assert issues[0].issue_code == "missing_bars"
    assert issues[0].ticker == "AAPL"
    assert issues[0].observed == 0
    assert issues[0].required == 3900


# --- generate_insufficient_lookback_issues ----------------------------------


def test_insufficient_lookback_flat_shape_returns_empty():
    """Flat data_requirements (no timespans key) -> []."""
    db = MagicMock()
    assert (
        generate_insufficient_lookback_issues(db, 1, _flat_cfg(), ticker="AAPL") == []
    )


def test_insufficient_lookback_no_min_bars_returns_empty():
    """Timespan with no min_bars field -> no issue emitted, regardless of bar count."""
    cfg = _cfg([{"timespan": "minute", "multiplier": 1, "lookback_days": 10}])
    db = MagicMock()
    db.query.return_value.filter.return_value.scalar.return_value = 0

    issues = generate_insufficient_lookback_issues(db, 1, cfg, ticker="AAPL")
    assert issues == []


def test_insufficient_lookback_per_ticker_emits_when_below_min_bars():
    """Per-ticker: emits issue when actual bar count < min_bars."""
    cfg = _cfg(
        [{"timespan": "day", "multiplier": 1, "lookback_days": 90, "min_bars": 260}]
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.scalar.return_value = 50  # actual bars

    issues = generate_insufficient_lookback_issues(db, 1, cfg, ticker="AAPL")

    assert len(issues) == 1
    assert issues[0].issue_code == "insufficient_lookback"
    assert issues[0].ticker == "AAPL"
    assert issues[0].observed == 50
    assert issues[0].required == 260


def test_insufficient_lookback_universe_wide_partial_coverage():
    """Universe-wide (ticker=None): AAPL fails (50 < 260), MSFT passes (300 >= 260)."""
    cfg = _cfg(
        [{"timespan": "day", "multiplier": 1, "lookback_days": 90, "min_bars": 260}]
    )
    ticker_rows = [MagicMock(ticker="AAPL"), MagicMock(ticker="MSFT")]

    filter_mock = MagicMock()
    filter_mock.all.return_value = ticker_rows
    filter_mock.scalar.side_effect = [50, 300]  # AAPL -> 50, MSFT -> 300

    db = MagicMock()
    db.query.return_value.filter.return_value = filter_mock

    issues = generate_insufficient_lookback_issues(db, 1, cfg, ticker=None)

    assert len(issues) == 1
    assert issues[0].ticker == "AAPL"
    assert issues[0].observed == 50
    assert issues[0].required == 260


# --- split/dividend + session helpers ---------------------------------------


class _Result:
    """Minimal query result that ignores filter/order_by and returns fixed rows."""

    def __init__(self, rows):
        self._rows = list(rows)

    def filter(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _DispatchDB:
    """Fake Session that returns queued result-sets keyed by model class.

    Each model maps to a list of row-lists; successive db.query(model) calls
    pop the next row-list, so universe-wide tests can give each ticker its own
    bars/splits in iteration order.
    """

    def __init__(self, *, tickers=None, splits=None, bars=None):
        self._queues = {
            StockUniverseTicker: (
                [[MagicMock(ticker=t) for t in tickers]] if tickers else []
            ),
            StockSplit: list(splits) if splits else [],
            StockAggregate: list(bars) if bars else [],
        }

    def query(self, model):
        queue = self._queues.get(model, [])
        rows = queue.pop(0) if queue else []
        return _Result(rows)


def _bar(ts, *, o=10.0, h=10.0, low=10.0, c=10.0, volume=1000, pre=False, post=False):
    return MagicMock(
        timestamp=ts,
        open=o,
        high=h,
        low=low,
        close=c,
        volume=volume,
        is_pre_market=pre,
        is_after_market=post,
    )


def _split(execution_date, *, split_from=1, split_to=2, applied=None):
    return MagicMock(
        execution_date=execution_date,
        split_from=split_from,
        split_to=split_to,
        adjustments_applied_at=applied,
    )


def _params_cfg(**params) -> MagicMock:
    cfg = MagicMock()
    cfg.parameters = params
    return cfg


# --- GateIssue richer payload -----------------------------------------------


def test_gate_issue_context_defaults_to_none():
    """Richer checks can construct a GateIssue with only code/ticker; the
    bar-count numeric fields default and context starts None."""
    issue = GateIssue(issue_code="split_dividend_anomaly", ticker="AAPL")
    assert issue.context is None
    assert issue.observed == 0
    assert issue.timespan == "minute"


# --- generate_split_dividend_anomaly_issues ---------------------------------


def test_split_unapplied_with_straddling_bars_emits_blocker():
    """Unapplied split with bars on both sides of execution_date -> blocker."""
    bars = [
        _bar(datetime(2026, 6, 15, 14, 0), c=100.0),  # before exec
        _bar(datetime(2026, 6, 16, 14, 0), o=100.0, c=100.0),  # on/after exec
    ]
    split = _split(date(2026, 6, 16), applied=None)
    db = _DispatchDB(bars=[bars], splits=[[split]])

    issues = generate_split_dividend_anomaly_issues(db, 1, None, ticker="AAPL")

    assert len(issues) == 1
    assert issues[0].issue_code == "split_dividend_anomaly"
    assert issues[0].ticker == "AAPL"
    assert issues[0].context["severity"] == "blocker"
    assert issues[0].context["reason"] == "unapplied_split"


def test_split_unapplied_without_straddling_bars_no_emit():
    """Unapplied split but every bar is on/after execution_date -> no straddle."""
    bars = [
        _bar(datetime(2026, 6, 16, 14, 0), c=100.0),
        _bar(datetime(2026, 6, 16, 15, 0), c=100.0),
    ]
    split = _split(date(2026, 6, 16), applied=None)
    db = _DispatchDB(bars=[bars], splits=[[split]])

    issues = generate_split_dividend_anomaly_issues(db, 1, None, ticker="AAPL")
    assert issues == []


def test_split_applied_within_factor_tolerance_no_emit():
    """Applied 2:1 split, observed jump matches factor 0.5 -> consistent, no emit."""
    bars = [
        _bar(datetime(2026, 6, 15, 14, 0), c=100.0),
        _bar(datetime(2026, 6, 16, 14, 0), o=50.0, c=50.0),
    ]
    split = _split(
        date(2026, 6, 16), split_from=1, split_to=2, applied=datetime(2026, 6, 16)
    )
    db = _DispatchDB(bars=[bars], splits=[[split]])

    issues = generate_split_dividend_anomaly_issues(db, 1, None, ticker="AAPL")
    assert issues == []


def test_split_recorded_factor_outside_tolerance_emits_blocker():
    """Recorded split factor (1:3 -> 0.333) disagrees with observed 0.5 -> blocker."""
    bars = [
        _bar(datetime(2026, 6, 15, 14, 0), c=100.0),
        _bar(datetime(2026, 6, 16, 14, 0), o=50.0, c=50.0),
    ]
    split = _split(
        date(2026, 6, 16), split_from=1, split_to=3, applied=datetime(2026, 6, 16)
    )
    db = _DispatchDB(bars=[bars], splits=[[split]])

    issues = generate_split_dividend_anomaly_issues(db, 1, None, ticker="AAPL")

    assert len(issues) == 1
    assert issues[0].context["reason"] == "split_factor_mismatch"
    assert issues[0].context["severity"] == "blocker"
    assert "volume_ratio" in issues[0].context


def test_split_discontinuity_with_missing_split_emits_blocker():
    """Large overnight jump with no recorded split -> unexplained discontinuity."""
    bars = [
        _bar(datetime(2026, 6, 15, 14, 0), c=100.0),
        _bar(datetime(2026, 6, 16, 14, 0), o=50.0, c=50.0),
    ]
    db = _DispatchDB(bars=[bars], splits=[[]])

    issues = generate_split_dividend_anomaly_issues(db, 1, None, ticker="AAPL")

    assert len(issues) == 1
    assert issues[0].context["reason"] == "unexplained_discontinuity"
    assert issues[0].context["discontinuity_pct"] == 50.0


def test_split_subfloor_move_no_emit():
    """Overnight move below the discontinuity floor -> no emit."""
    bars = [
        _bar(datetime(2026, 6, 15, 14, 0), c=100.0),
        _bar(datetime(2026, 6, 16, 14, 0), o=98.0, c=98.0),
    ]
    db = _DispatchDB(bars=[bars], splits=[[]])

    issues = generate_split_dividend_anomaly_issues(db, 1, None, ticker="AAPL")
    assert issues == []


def test_split_custom_floor_threshold_from_config():
    """A 30% jump clears the default 25% floor but not a configured 40% floor."""
    bars = [
        _bar(datetime(2026, 6, 15, 14, 0), c=100.0),
        _bar(datetime(2026, 6, 16, 14, 0), o=70.0, c=70.0),
    ]
    db = _DispatchDB(bars=[bars], splits=[[]])
    cfg = _params_cfg(split_discontinuity_floor_pct=40)

    issues = generate_split_dividend_anomaly_issues(db, 1, cfg, ticker="AAPL")
    assert issues == []


def test_split_no_bars_no_emit():
    """Ticker with no minute bars is skipped entirely."""
    db = _DispatchDB(bars=[[]], splits=[[_split(date(2026, 6, 16), applied=None)]])
    issues = generate_split_dividend_anomaly_issues(db, 1, None, ticker="AAPL")
    assert issues == []


def test_split_winter_evening_before_bar_is_not_a_straddle_no_emit():
    """Regression (#500): in winter (EST, UTC-5) a 20:00 ET post-market bar the
    evening BEFORE execution_date carries a UTC timestamp of 01:00 ON
    execution_date. The old naive-UTC-midnight straddle boundary wrongly counted
    it as a post-split bar and emitted a false-positive blocker; ET-date
    comparison correctly treats it as pre-split, so no anomaly is emitted.

    (Fails against the old naive-UTC logic, passes with the _et_date boundary.)
    """
    bars = [
        # 09:00 EST 01-15 (ET date 01-15) — genuinely pre-split, regular session.
        _bar(datetime(2026, 1, 15, 14, 0), c=100.0),
        # 20:00 EST 01-15 == 01:00 UTC 01-16 (ET date 01-15) — evening-before
        # post-market bar; its UTC date rolls into execution_date.
        _bar(datetime(2026, 1, 16, 1, 0), c=100.0, post=True),
    ]
    split = _split(date(2026, 1, 16), applied=None)
    db = _DispatchDB(bars=[bars], splits=[[split]])

    issues = generate_split_dividend_anomaly_issues(db, 1, None, ticker="AAPL")
    assert issues == []


def test_split_winter_genuine_straddle_emits_blocker():
    """Positive counterpart to the winter regression: a bar whose ET date is
    actually >= execution_date is a genuine straddle and still emits the
    unapplied-split blocker."""
    bars = [
        _bar(datetime(2026, 1, 15, 14, 0), c=100.0),  # ET 01-15, pre-split
        # 09:00 EST 01-16 (ET date 01-16) — genuinely post-split.
        _bar(datetime(2026, 1, 16, 14, 0), c=100.0, pre=True),
    ]
    split = _split(date(2026, 1, 16), applied=None)
    db = _DispatchDB(bars=[bars], splits=[[split]])

    issues = generate_split_dividend_anomaly_issues(db, 1, None, ticker="AAPL")

    assert len(issues) == 1
    assert issues[0].context["reason"] == "unapplied_split"
    assert issues[0].context["severity"] == "blocker"


def test_split_universe_wide_only_flags_offending_ticker():
    """ticker=None iterates universe tickers; only AAPL (unapplied straddling
    split) is flagged, MSFT (clean) is not."""
    aapl_bars = [
        _bar(datetime(2026, 6, 15, 14, 0), c=100.0),  # before exec
        _bar(datetime(2026, 6, 16, 14, 0), o=100.0, c=100.0),  # on/after exec
    ]
    msft_bars = [_bar(datetime(2026, 6, 15, 14, 0), c=100.0)]
    aapl_split = _split(date(2026, 6, 16), applied=None)
    db = _DispatchDB(
        tickers=["AAPL", "MSFT"],
        bars=[aapl_bars, msft_bars],
        splits=[[aapl_split], []],
    )

    issues = generate_split_dividend_anomaly_issues(db, 1, None, ticker=None)

    assert len(issues) == 1
    assert issues[0].ticker == "AAPL"
    assert issues[0].context["reason"] == "unapplied_split"


# --- generate_timezone_session_mismatch_issues ------------------------------


def test_session_correct_flags_no_emit():
    """Correctly flagged pre/regular/post bars -> no mismatch, no emit."""
    bars = [
        _bar(datetime(2026, 6, 15, 12, 0), pre=True),  # 08:00 ET -> pre
        _bar(datetime(2026, 6, 15, 14, 0)),  # 10:00 ET -> regular
        _bar(datetime(2026, 6, 15, 22, 0), post=True),  # 18:00 ET -> post
    ]
    db = _DispatchDB(bars=[bars])

    issues = generate_timezone_session_mismatch_issues(db, 1, None, ticker="AAPL")
    assert issues == []


def test_session_wrong_flags_above_threshold_emits_warning():
    """A regular bar mis-flagged as pre-market pushes mismatch rate over 1%."""
    bars = [
        _bar(datetime(2026, 6, 15, 14, 0), pre=True),  # regular flagged pre -> wrong
        _bar(datetime(2026, 6, 15, 14, 1)),
        _bar(datetime(2026, 6, 15, 14, 2)),
        _bar(datetime(2026, 6, 15, 14, 3)),
        _bar(datetime(2026, 6, 15, 14, 4)),
    ]
    db = _DispatchDB(bars=[bars])

    issues = generate_timezone_session_mismatch_issues(db, 1, None, ticker="AAPL")

    assert len(issues) == 1
    assert issues[0].issue_code == "session_mismatch"
    assert issues[0].context["severity"] == "warning"
    assert issues[0].context["reason"] == "flag_mismatch"
    assert issues[0].context["mismatch_count"] == 1
    assert len(issues[0].context["sample_mismatches"]) == 1


def test_session_wrong_flags_below_threshold_no_emit():
    """Same single mismatch stays under a configured 50% threshold -> no emit."""
    bars = [
        _bar(datetime(2026, 6, 15, 14, 0), pre=True),  # wrong
        _bar(datetime(2026, 6, 15, 14, 1)),
        _bar(datetime(2026, 6, 15, 14, 2)),
    ]
    db = _DispatchDB(bars=[bars])
    cfg = _params_cfg(session_mismatch_threshold_pct=50.0)

    issues = generate_timezone_session_mismatch_issues(db, 1, cfg, ticker="AAPL")
    assert issues == []


def test_session_closed_window_bar_emits_blocker():
    """A bar landing in a 'closed' window is always a blocker."""
    bars = [_bar(datetime(2026, 6, 15, 6, 0))]  # 02:00 ET -> closed
    db = _DispatchDB(bars=[bars])

    issues = generate_timezone_session_mismatch_issues(db, 1, None, ticker="AAPL")

    assert len(issues) == 1
    assert issues[0].context["severity"] == "blocker"
    assert issues[0].context["reason"] == "bars_in_closed_window"
    assert issues[0].context["closed_bar_count"] == 1


def test_session_dst_aware_flags_match():
    """Same 13:30 UTC wall-time is 'pre' in winter (EST) but 'regular' in summer
    (EDT); correctly DST-aware flags produce no mismatch."""
    bars = [
        _bar(datetime(2026, 1, 15, 13, 30), pre=True),  # 08:30 EST -> pre
        _bar(datetime(2026, 6, 15, 13, 30)),  # 09:30 EDT -> regular
    ]
    db = _DispatchDB(bars=[bars])

    issues = generate_timezone_session_mismatch_issues(db, 1, None, ticker="AAPL")
    assert issues == []


def test_session_empty_bars_no_emit():
    """Ticker with no minute bars is skipped."""
    db = _DispatchDB(bars=[[]])
    issues = generate_timezone_session_mismatch_issues(db, 1, None, ticker="AAPL")
    assert issues == []


def test_session_universe_wide_only_flags_offending_ticker():
    """ticker=None iterates universe tickers; only AAPL (closed bar) is flagged."""
    aapl_bars = [_bar(datetime(2026, 6, 15, 6, 0))]  # closed
    msft_bars = [_bar(datetime(2026, 6, 15, 14, 0))]  # regular, correct
    db = _DispatchDB(tickers=["AAPL", "MSFT"], bars=[aapl_bars, msft_bars])

    issues = generate_timezone_session_mismatch_issues(db, 1, None, ticker=None)

    assert len(issues) == 1
    assert issues[0].ticker == "AAPL"
    assert issues[0].context["reason"] == "bars_in_closed_window"


def test_session_mismatch_rate_uses_open_window_denominator():
    """Fix 2 (#500): the warning rate is computed over open-window bars only, not
    over the full bar count (closed bars are handled by the separate blocker).

    2 closed + 3 open bars (1 open mismatch), threshold 25%:
      - full-count rate  = 1/5 = 20% -> would NOT warn (old logic)
      - open-window rate = 1/3 = 33% -> warns (new logic)
    The closed-window blocker fires in both cases.
    """
    bars = [
        _bar(datetime(2026, 6, 15, 6, 0)),  # 02:00 ET -> closed
        _bar(datetime(2026, 6, 15, 6, 1)),  # 02:01 ET -> closed
        _bar(datetime(2026, 6, 15, 14, 0), pre=True),  # regular flagged pre -> mismatch
        _bar(datetime(2026, 6, 15, 14, 1)),  # regular, correct
        _bar(datetime(2026, 6, 15, 14, 2)),  # regular, correct
    ]
    db = _DispatchDB(bars=[bars])
    cfg = _params_cfg(session_mismatch_threshold_pct=25.0)

    issues = generate_timezone_session_mismatch_issues(db, 1, cfg, ticker="AAPL")

    reasons = {i.context["reason"] for i in issues}
    assert reasons == {"bars_in_closed_window", "flag_mismatch"}
    warning = next(i for i in issues if i.context["reason"] == "flag_mismatch")
    assert warning.context["severity"] == "warning"
    assert warning.context["open_window_bars"] == 3
    assert warning.context["mismatch_count"] == 1
