"""Unit tests for scanning task helpers — no broker required."""

from datetime import date
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Import checks
# ---------------------------------------------------------------------------


def test_run_universe_scan_logic_is_importable():
    from app.tasks.scanning import _run_universe_scan_logic

    assert callable(_run_universe_scan_logic)


def test_run_range_scan_logic_is_importable():
    from app.tasks.scanning import _run_range_scan_logic

    assert callable(_run_range_scan_logic)


def test_evaluate_scanner_alerts_logic_is_importable():
    from app.tasks.scanning import _evaluate_scanner_alerts_logic

    assert callable(_evaluate_scanner_alerts_logic)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run(uuid, status="pending"):
    run = MagicMock()
    run.uuid = uuid
    run.status = status
    run.events_detected = 0
    run.execution_time_ms = None
    return run


def _make_ticker(ticker_str):
    t = MagicMock()
    t.ticker = ticker_str
    return t


def _make_db(run=None, tickers=None):
    """Mock DB that returns run from first query().filter().first() and tickers from second."""

    db = MagicMock()
    call_count = [0]

    def _query_side_effect(model):
        q = MagicMock()
        idx = call_count[0]
        call_count[0] += 1
        if idx == 0:
            q.filter.return_value.first.return_value = run
        else:
            q.filter.return_value.all.return_value = tickers or []
        return q

    db.query.side_effect = _query_side_effect
    return db


# ---------------------------------------------------------------------------
# _run_universe_scan_logic tests
# ---------------------------------------------------------------------------


class TestRunUniverseScanLogic:
    def _run_logic(self, run, tickers, is_cancelled=False):
        from app.tasks.scanning import _run_universe_scan_logic

        published = []
        db = _make_db(run=run, tickers=tickers)

        with patch("app.tasks.scanning.asyncio.run", return_value=[]):
            _run_universe_scan_logic(
                scan_id="scan-001",
                scanner_type="pre_market_volume_spike",
                universe_id=1,
                start=date(2026, 6, 2),  # Monday
                end=date(2026, 6, 2),
                db=db,
                publish=lambda p: published.append(p),
                is_cancelled=lambda: is_cancelled,
                task_id="task-abc",
            )

        return published, db

    def test_run_not_found_returns_early(self):
        published, db = self._run_logic(run=None, tickers=[_make_ticker("AAPL")])
        assert not any(p.get("type") == "started" for p in published)
        db.commit.assert_not_called()

    def test_no_tickers_publishes_failed(self):
        run = _make_run("scan-001")
        published, db = self._run_logic(run=run, tickers=[])
        assert run.status == "failed"
        assert any(p.get("type") == "failed" for p in published)

    def test_happy_path_publishes_started_and_completed(self):
        run = _make_run("scan-001")
        published, _ = self._run_logic(run=run, tickers=[_make_ticker("AAPL")])
        types = [p.get("type") for p in published]
        assert "started" in types
        assert "completed" in types

    def test_cancel_flag_sets_status_cancelled(self):
        from app.tasks.scanning import _run_universe_scan_logic

        run = _make_run("scan-001")
        published = []
        db = _make_db(run=run, tickers=[_make_ticker("AAPL")])

        with patch("app.tasks.scanning.asyncio.run", return_value=[]):
            _run_universe_scan_logic(
                scan_id="scan-001",
                scanner_type="pre_market_volume_spike",
                universe_id=1,
                start=date(2026, 6, 2),
                end=date(2026, 6, 2),
                db=db,
                publish=lambda p: published.append(p),
                is_cancelled=lambda: True,
                task_id="task-abc",
            )

        assert run.status == "cancelled"
        assert any(p.get("type") == "cancelled" for p in published)

    def test_day_error_continues_to_completion(self):
        from app.tasks.scanning import _run_universe_scan_logic

        run = _make_run("scan-001")
        published = []
        db = _make_db(run=run, tickers=[_make_ticker("AAPL")])

        with patch(
            "app.tasks.scanning.asyncio.run", side_effect=RuntimeError("day failed")
        ):
            _run_universe_scan_logic(
                scan_id="scan-001",
                scanner_type="pre_market_volume_spike",
                universe_id=1,
                start=date(2026, 6, 2),
                end=date(2026, 6, 2),
                db=db,
                publish=lambda p: published.append(p),
                is_cancelled=lambda: False,
                task_id="task-abc",
            )

        assert any(p.get("type") == "day_error" for p in published)
        assert run.status == "completed"

    def test_weekends_excluded_from_trading_days(self):
        """A Mon-Sun range yields only 5 day_started events (Mon-Fri)."""
        from app.tasks.scanning import _run_universe_scan_logic

        run = _make_run("scan-001")
        day_started = []
        db = _make_db(run=run, tickers=[_make_ticker("AAPL")])

        def _capture(p):
            if p.get("type") == "day_started":
                day_started.append(p)

        with patch("app.tasks.scanning.asyncio.run", return_value=[]):
            _run_universe_scan_logic(
                scan_id="scan-001",
                scanner_type="pre_market_volume_spike",
                universe_id=1,
                start=date(2026, 6, 1),  # Monday
                end=date(2026, 6, 7),  # Sunday
                db=db,
                publish=_capture,
                is_cancelled=lambda: False,
                task_id="task-abc",
            )

        assert len(day_started) == 5  # Mon-Fri only

    def test_write_state_called_with_payload(self):
        from app.tasks.scanning import _run_universe_scan_logic

        run = _make_run("scan-001")
        state_calls = []
        db = _make_db(run=run, tickers=[_make_ticker("AAPL")])

        with patch("app.tasks.scanning.asyncio.run", return_value=[]):
            _run_universe_scan_logic(
                scan_id="scan-001",
                scanner_type="pre_market_volume_spike",
                universe_id=1,
                start=date(2026, 6, 2),
                end=date(2026, 6, 2),
                db=db,
                publish=lambda p: None,
                is_cancelled=lambda: False,
                task_id="task-abc",
                write_state=lambda s: state_calls.append(s),
            )

        assert len(state_calls) >= 2  # initial + each day
        assert "start_date" in state_calls[0]


# ---------------------------------------------------------------------------
# _evaluate_scanner_alerts_logic tests
# ---------------------------------------------------------------------------


class TestEvaluateScannerAlertsLogic:
    def _run_logic(self, event=None, matching_rules=None):
        from app.tasks.scanning import _evaluate_scanner_alerts_logic

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = event

        with (
            patch(
                "app.services.alert_service.AlertRuleService.get_matching_rules",
                return_value=matching_rules or [],
            ),
            patch(
                "app.services.alert_service.NotificationDispatcher.dispatch"
            ) as mock_dispatch,
            patch("app.tasks.trading.execute_auto_trade") as mock_trade,
        ):
            _evaluate_scanner_alerts_logic(scanner_event_id=42, db=db)
            return mock_dispatch, mock_trade

    def test_event_not_found_returns_without_dispatch(self):
        mock_dispatch, _ = self._run_logic(event=None)
        mock_dispatch.assert_not_called()

    def test_no_matching_rules_returns_without_dispatch(self):
        event = MagicMock()
        event.ticker = "AAPL"
        mock_dispatch, _ = self._run_logic(event=event, matching_rules=[])
        mock_dispatch.assert_not_called()

    def test_matching_rule_dispatches_notification(self):
        event = MagicMock()
        event.ticker = "AAPL"
        rule = MagicMock()
        rule.auto_trade = False
        mock_dispatch, _ = self._run_logic(event=event, matching_rules=[rule])
        mock_dispatch.assert_called_once()

    def test_auto_trade_rule_queues_execute_auto_trade(self):
        from app.tasks.scanning import _evaluate_scanner_alerts_logic

        event = MagicMock()
        event.ticker = "AAPL"
        rule = MagicMock()
        rule.id = 7
        rule.auto_trade = True
        rule.trading_strategy_id = 3

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = event

        with (
            patch(
                "app.services.alert_service.AlertRuleService.get_matching_rules",
                return_value=[rule],
            ),
            patch("app.services.alert_service.NotificationDispatcher.dispatch"),
            patch("app.tasks.trading.execute_auto_trade") as mock_trade,
        ):
            _evaluate_scanner_alerts_logic(scanner_event_id=42, db=db)

        mock_trade.delay.assert_called_once_with(rule_id=7, scanner_event_id=42)

    def test_dispatch_exception_does_not_abort_loop(self):
        from app.tasks.scanning import _evaluate_scanner_alerts_logic

        event = MagicMock()
        event.ticker = "AAPL"
        rule1 = MagicMock()
        rule1.auto_trade = False
        rule2 = MagicMock()
        rule2.auto_trade = False

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = event

        dispatch_calls = []

        def _dispatch(rule, evt, db):
            dispatch_calls.append(rule)
            if rule is rule1:
                raise RuntimeError("dispatch boom")

        with (
            patch(
                "app.services.alert_service.AlertRuleService.get_matching_rules",
                return_value=[rule1, rule2],
            ),
            patch(
                "app.services.alert_service.NotificationDispatcher.dispatch",
                side_effect=_dispatch,
            ),
            patch("app.tasks.trading.execute_auto_trade"),
        ):
            _evaluate_scanner_alerts_logic(scanner_event_id=42, db=db)

        # Both rules processed despite first dispatch failing
        assert len(dispatch_calls) == 2


# ---------------------------------------------------------------------------
# Quality gate integration tests
# ---------------------------------------------------------------------------


def _make_assessment(verdict="trusted", warnings=None):
    """Build a minimal QualityGateAssessment-like object for tests."""
    from app.schemas.quality_gate import (
        QualityGateAssessment,
        QualityGatePolicy,
        QualityGateScope,
        QualityGateVerdict,
    )
    from app.utils.time import utc_now

    return QualityGateAssessment(
        policy=QualityGatePolicy.advisory,
        verdict=QualityGateVerdict(verdict),
        trusted=(verdict == "trusted"),
        scope=QualityGateScope(universe_id=1, scanner_type="pre_market_volume_spike"),
        score=95.0,
        grade="A",
        issues=[],
        warnings=warnings or [],
        generated_at=utc_now(),
    )


class TestQualityGateInUniverseScan:
    def _run_logic_with_gate(self, assessment, gate_raises=False):
        from app.tasks.scanning import _run_universe_scan_logic

        run = _make_run("scan-gate-01")
        published = []
        db = _make_db(run=run, tickers=[_make_ticker("AAPL")])

        patch_target = "app.services.quality_gate.QualityGateService.assess"
        if gate_raises:
            gate_mock = patch(patch_target, side_effect=RuntimeError("gate boom"))
        else:
            gate_mock = patch(patch_target, return_value=assessment)

        with gate_mock, patch("app.tasks.scanning.asyncio.run", return_value=[]):
            _run_universe_scan_logic(
                scan_id="scan-gate-01",
                scanner_type="pre_market_volume_spike",
                universe_id=1,
                start=date(2026, 6, 2),
                end=date(2026, 6, 2),
                db=db,
                publish=lambda p: published.append(p),
                is_cancelled=lambda: False,
                task_id="task-gate",
            )

        return run, published

    def test_gate_assessment_persisted_to_quality_gate(self):
        """QualityGateService.assess() result is stored on run.quality_gate."""
        assessment = _make_assessment(verdict="trusted")
        run, _ = self._run_logic_with_gate(assessment)
        assert run.quality_gate is not None
        assert run.quality_gate["verdict"] == "trusted"
        assert run.quality_gate["schema_version"] == "quality_gate.v1"

    def test_advisory_warning_does_not_block_scan(self):
        """A warning verdict under advisory policy does not block scan execution."""
        from app.schemas.quality_gate import QualityGateIssue, QualityIssueCode

        warning_issue = QualityGateIssue(
            code=QualityIssueCode.missing_bars,
            severity="warning",
            message="No completed quality report found",
        )
        assessment = _make_assessment(verdict="warning", warnings=[warning_issue])
        run, published = self._run_logic_with_gate(assessment)
        # scan completed despite warning
        assert run.status == "completed"
        assert any(p.get("type") == "completed" for p in published)

    def test_gate_exception_degrades_gracefully(self):
        """When QualityGateService raises, scan continues and quality_gate is not set to a dict."""
        run, published = self._run_logic_with_gate(assessment=None, gate_raises=True)
        # quality_gate was never assigned a dict (exception prevented it)
        assert not isinstance(run.quality_gate, dict)
        # scan still completed
        assert run.status == "completed"
        assert any(p.get("type") == "completed" for p in published)

    def test_gate_metadata_uses_tier_key_for_stats_compat(self):
        """gate_metadata threaded to orchestrator must use 'tier' key for stats.py compat.

        stats.py reads metadata_["quality_gate"]["tier"] (line 19, line 637); using 'verdict'
        instead silently breaks every trust-tier filter in scorecard and signal views.
        """
        from unittest.mock import AsyncMock

        from app.tasks.scanning import _run_universe_scan_logic

        assessment = _make_assessment(verdict="warning")
        run = _make_run("scan-tier-chk")
        db = _make_db(run=run, tickers=[_make_ticker("AAPL")])
        orch_mock = AsyncMock(return_value=[])

        with (
            patch(
                "app.services.quality_gate.QualityGateService.assess",
                return_value=assessment,
            ),
            patch("app.services.scan_orchestrator.run", orch_mock),
            patch("app.tasks.scanning.asyncio.run", return_value=[]),
        ):
            _run_universe_scan_logic(
                scan_id="scan-tier-chk",
                scanner_type="pre_market_volume_spike",
                universe_id=1,
                start=date(2026, 6, 2),
                end=date(2026, 6, 2),
                db=db,
                publish=lambda p: None,
                is_cancelled=lambda: False,
                task_id="task-tier-chk",
            )

        assert orch_mock.called, (
            "orchestrator.run should have been called for the scan day"
        )
        gate = orch_mock.call_args.kwargs.get("gate_metadata")
        assert gate is not None, (
            "gate_metadata should not be None for a warning verdict"
        )
        assert "tier" in gate, (
            f"gate_metadata must use 'tier' key for stats.py compat; got keys: {sorted(gate.keys())}"
        )


# ---------------------------------------------------------------------------
# _run_range_scan_logic tests
# ---------------------------------------------------------------------------


class TestRunRangeScanLogic:
    def _run_logic(self, start, end, scanner_types=None, fetch_missing=False):
        from app.tasks.scanning import _run_range_scan_logic

        if scanner_types is None:
            scanner_types = ["pre_market_volume_spike"]

        published = []
        db = MagicMock()

        with patch("app.tasks.scanning.asyncio.run", return_value=[MagicMock()]):
            count = _run_range_scan_logic(
                ticker="AAPL",
                scanner_types=scanner_types,
                start=start,
                end=end,
                fetch_missing_data=fetch_missing,
                db=db,
                publish=lambda p: published.append(p),
            )

        return count, published

    def test_weekends_skipped_in_trading_days(self):
        # Mon 2026-06-01 to Sun 2026-06-07 → 5 trading days
        count, published = self._run_logic(start=date(2026, 6, 1), end=date(2026, 6, 7))
        progress_days = [p for p in published if p.get("status") == "progress"]
        assert len(progress_days) == 5

    def test_returns_event_count(self):
        count, _ = self._run_logic(start=date(2026, 6, 2), end=date(2026, 6, 2))
        assert isinstance(count, int)

    def test_completed_message_published(self):
        _, published = self._run_logic(start=date(2026, 6, 2), end=date(2026, 6, 2))
        assert any(p.get("status") == "completed" for p in published)
