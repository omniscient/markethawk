"""Unit tests for scheduled scanner task logic and startup validation."""

from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Task 1 tests: ScannerConfig.universe_id column exists
# ---------------------------------------------------------------------------


def test_scanner_config_has_universe_id_column():
    """ScannerConfig must declare universe_id as a mapped column."""
    from sqlalchemy import inspect as sa_inspect

    from app.models.scanner_config import ScannerConfig

    mapper = sa_inspect(ScannerConfig)
    col_names = [c.key for c in mapper.mapper.column_attrs]
    assert "universe_id" in col_names, (
        "ScannerConfig is missing universe_id column — add it to scanner_config.py"
    )


def test_scanner_config_universe_id_is_integer():
    """universe_id must be an Integer column."""
    import sqlalchemy as sa

    from app.models.scanner_config import ScannerConfig

    col = ScannerConfig.__table__.c["universe_id"]
    assert isinstance(col.type, sa.Integer)


def test_scanner_config_universe_id_is_not_nullable():
    """universe_id must be NOT NULL (nullable=False)."""
    from app.models.scanner_config import ScannerConfig

    col = ScannerConfig.__table__.c["universe_id"]
    assert col.nullable is False, "universe_id must be NOT NULL"


# ---------------------------------------------------------------------------
# Task 2 tests: Alembic migration file exists and has correct revision chain
# ---------------------------------------------------------------------------


def test_migration_file_exists():
    """The add_universe_id migration file must exist at the expected path."""
    import os

    path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "app",
        "alembic",
        "versions",
        "c7d8e9f0a1b2_add_universe_id_to_scanner_configs.py",
    )
    assert os.path.isfile(os.path.abspath(path)), (
        "Migration file c7d8e9f0a1b2_add_universe_id_to_scanner_configs.py not found"
    )


def test_migration_revision_chain():
    """Migration must declare correct revision and a non-None down_revision."""
    import importlib.util
    import os

    path = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "app",
            "alembic",
            "versions",
            "c7d8e9f0a1b2_add_universe_id_to_scanner_configs.py",
        )
    )
    spec = importlib.util.spec_from_file_location("mig", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.revision == "c7d8e9f0a1b2"
    assert mod.down_revision is not None, (
        "down_revision is None — set it to the current alembic HEAD revision"
    )


# ---------------------------------------------------------------------------
# Task 3 tests: Seed SQL correctness
# ---------------------------------------------------------------------------


def test_seed_liquidity_hunt_has_universe_id():
    """The liquidity_hunt seed row (id=2) must include universe_id column and value."""
    import os

    seed_path = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "..",
            "dark-factory",
            "seed",
            "seed",
            "01_scanner_configs.sql",
        )
    )
    if not os.path.exists(seed_path):
        pytest.skip("dark-factory seed dir not mounted in this container")
    with open(seed_path) as f:
        content = f.read()
    assert "universe_id" in content, (
        "01_scanner_configs.sql is missing universe_id — update the liquidity_hunt INSERT"
    )


def test_seed_pocket_pivot_row_exists():
    """A pocket_pivot config row must be present in the seed SQL."""
    import os

    seed_path = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "..",
            "dark-factory",
            "seed",
            "seed",
            "01_scanner_configs.sql",
        )
    )
    if not os.path.exists(seed_path):
        pytest.skip("dark-factory seed dir not mounted in this container")
    with open(seed_path) as f:
        content = f.read()
    assert "pocket_pivot" in content, (
        "01_scanner_configs.sql is missing the pocket_pivot config row"
    )
    assert "lookback_days" in content and "volume_floor" in content, (
        "pocket_pivot seed row is missing required parameters (lookback_days, volume_floor)"
    )


# ---------------------------------------------------------------------------
# Task 4 tests: Fixed scheduled task logic
# ---------------------------------------------------------------------------


def _make_cfg(id, universe_id, scanner_type="liquidity_hunt", is_active=True):
    """Return a MagicMock resembling a ScannerConfig ORM row."""
    cfg = MagicMock()
    cfg.id = id
    cfg.scanner_type = scanner_type
    cfg.is_active = is_active
    cfg.universe_id = universe_id
    # parameters.get must NOT be called in the fixed implementation
    cfg.parameters = MagicMock()
    cfg.parameters.get.side_effect = AssertionError(
        "Fixed task must not call cfg.parameters.get('universe_id')"
    )
    return cfg


class TestRunLiquidityHuntScheduledFixed:
    """Tests for the fixed run_liquidity_hunt_scheduled task."""

    def _run_with_configs(self, configs, tickers=None):
        """Invoke the task with a mocked DB returning given configs."""
        from app.models.scanner_config import ScannerConfig

        if tickers is None:
            tickers = [MagicMock(ticker="AAPL"), MagicMock(ticker="MSFT")]

        import app.tasks.scanning as scanning_module

        def _make_query_mock(return_rows):
            q = MagicMock()
            q.filter.return_value.all.return_value = return_rows
            return q

        mock_db = MagicMock()
        mock_db.query.side_effect = lambda model: (
            _make_query_mock(configs)
            if model is ScannerConfig
            else _make_query_mock(tickers)
        )

        def _retry_reraises(exc, **kw):
            raise exc

        with (
            patch("app.tasks.scanning.SessionLocal", return_value=mock_db),
            patch("app.utils.session.get_market_today", return_value="2026-06-03"),
            patch("app.tasks.scanning.asyncio.run", return_value=[]),
            patch(
                "app.services.liquidity_hunt.run_liquidity_hunt_scan", return_value=[]
            ),
            patch.object(
                scanning_module.run_liquidity_hunt_scheduled,
                "retry",
                side_effect=_retry_reraises,
            ),
        ):
            # For bind=True tasks .run() already has self bound to the task instance.
            scanning_module.run_liquidity_hunt_scheduled.run()

    def test_does_not_call_parameters_get(self):
        """Fixed task must read cfg.universe_id, never cfg.parameters.get."""
        cfg = _make_cfg(id=2, universe_id=1)
        self._run_with_configs([cfg])

    def test_logs_error_and_raises_when_zero_configs(self, caplog):
        """Task must log an error when no active ScannerConfig rows are found."""
        import logging

        with caplog.at_level(logging.ERROR, logger="app.tasks.scanning"):
            with pytest.raises(Exception):
                self._run_with_configs([])
        assert any("liquidity_hunt" in r.message.lower() for r in caplog.records), (
            "Expected an error log mentioning 'liquidity_hunt' when zero configs found"
        )

    def test_logs_error_when_universe_id_is_null(self, caplog):
        """Task must log a loud error when cfg.universe_id is None."""
        import logging

        cfg = _make_cfg(id=2, universe_id=None)
        with caplog.at_level(logging.ERROR, logger="app.tasks.scanning"):
            with pytest.raises(Exception):
                self._run_with_configs([cfg])
        assert any("universe_id" in r.message.lower() for r in caplog.records)

    def test_no_tickers_logs_warning_and_does_not_raise(self, caplog):
        """Universe with no active tickers should log a warning and skip, not raise."""
        import logging

        cfg = _make_cfg(id=2, universe_id=1)
        with caplog.at_level(logging.WARNING, logger="app.tasks.scanning"):
            self._run_with_configs([cfg], tickers=[])
        assert any("no active tickers" in r.message.lower() for r in caplog.records)

    def test_success_with_tickers_does_not_raise(self):
        """Happy path: valid config + tickers completes without exception."""
        cfg = _make_cfg(id=2, universe_id=1)
        tickers = [MagicMock(ticker="AAPL"), MagicMock(ticker="TSLA")]
        self._run_with_configs([cfg], tickers=tickers)


class TestRunPocketPivotScheduledFixed:
    """Tests for the fixed run_pocket_pivot_scheduled task."""

    def _run_with_configs(self, configs, tickers=None):
        from app.models.scanner_config import ScannerConfig

        if tickers is None:
            tickers = [MagicMock(ticker="AAPL")]

        import app.tasks.scanning as scanning_module

        def _make_query_mock(return_rows):
            q = MagicMock()
            q.filter.return_value.all.return_value = return_rows
            return q

        mock_db = MagicMock()
        mock_db.query.side_effect = lambda model: (
            _make_query_mock(configs)
            if model is ScannerConfig
            else _make_query_mock(tickers)
        )

        def _retry_reraises(exc, **kw):
            raise exc

        with (
            patch("app.tasks.scanning.SessionLocal", return_value=mock_db),
            patch("app.utils.session.get_market_today", return_value="2026-06-03"),
            patch("app.tasks.scanning.asyncio.run", return_value=[]),
            patch("app.services.pocket_pivot.run_pocket_pivot_scan", return_value=[]),
            patch.object(
                scanning_module.run_pocket_pivot_scheduled,
                "retry",
                side_effect=_retry_reraises,
            ),
        ):
            scanning_module.run_pocket_pivot_scheduled.run()

    def test_does_not_call_parameters_get(self):
        """Fixed task must read cfg.universe_id, never cfg.parameters.get."""
        cfg = _make_cfg(id=4, universe_id=1, scanner_type="pocket_pivot")
        self._run_with_configs([cfg])

    def test_logs_error_and_raises_when_zero_configs(self, caplog):
        """Task must log an error when no active pocket_pivot configs are found."""
        import logging

        with caplog.at_level(logging.ERROR, logger="app.tasks.scanning"):
            with pytest.raises(Exception):
                self._run_with_configs([])
        assert any("pocket_pivot" in r.message.lower() for r in caplog.records)

    def test_logs_error_when_universe_id_is_null(self, caplog):
        """Task must log a loud error when cfg.universe_id is None."""
        import logging

        cfg = _make_cfg(id=4, universe_id=None, scanner_type="pocket_pivot")
        with caplog.at_level(logging.ERROR, logger="app.tasks.scanning"):
            with pytest.raises(Exception):
                self._run_with_configs([cfg])
        assert any("universe_id" in r.message.lower() for r in caplog.records)

    def test_no_tickers_logs_warning_and_does_not_raise(self, caplog):
        """Universe with no active tickers should log a warning and skip, not raise."""
        import logging

        cfg = _make_cfg(id=4, universe_id=1, scanner_type="pocket_pivot")
        with caplog.at_level(logging.WARNING, logger="app.tasks.scanning"):
            self._run_with_configs([cfg], tickers=[])
        assert any("no active tickers" in r.message.lower() for r in caplog.records)

    def test_success_with_tickers_does_not_raise(self):
        """Happy path: valid config + tickers completes without exception."""
        cfg = _make_cfg(id=4, universe_id=1, scanner_type="pocket_pivot")
        tickers = [MagicMock(ticker="AAPL")]
        self._run_with_configs([cfg], tickers=tickers)


# ---------------------------------------------------------------------------
# Task 5 tests: validate_scheduled_scanner_configs startup validation
# ---------------------------------------------------------------------------


class TestValidateScheduledScannerConfigs:
    """Tests for the validate_scheduled_scanner_configs() startup check."""

    def _run_validation(
        self, liquidity_hunt_configs, pocket_pivot_configs, trend_pullback_configs=None
    ):
        """Invoke validate_scheduled_scanner_configs with mocked DB results.

        The validation function iterates _BEAT_SCHEDULED_SCANNER_TYPES in order:
        ["liquidity_hunt", "pocket_pivot", "trend_pullback"]. We return configs by call index.
        """
        import app.tasks.scanning as scanning_module

        call_count = [0]
        results_by_index = [
            liquidity_hunt_configs,
            pocket_pivot_configs,
            trend_pullback_configs or [],
        ]

        def _make_filter_chain():
            idx = call_count[0]
            call_count[0] += 1
            rows = results_by_index[idx] if idx < len(results_by_index) else []
            f = MagicMock()
            f.all.return_value = rows
            return f

        mock_db = MagicMock()
        mock_db.query.return_value.filter.side_effect = lambda *a, **kw: (
            _make_filter_chain()
        )

        with patch("app.tasks.scanning.SessionLocal", return_value=mock_db):
            scanning_module.validate_scheduled_scanner_configs()

    def test_validate_passes_when_all_types_configured(self, caplog):
        """No error logged when all scanner types have a valid config."""
        import logging

        lh = _make_cfg(id=2, universe_id=1, scanner_type="liquidity_hunt")
        pp = _make_cfg(id=4, universe_id=1, scanner_type="pocket_pivot")
        tp = _make_cfg(id=6, universe_id=1, scanner_type="trend_pullback")
        with caplog.at_level(logging.ERROR, logger="app.tasks.scanning"):
            self._run_validation([lh], [pp], [tp])
        assert not any(r.levelno >= logging.ERROR for r in caplog.records), (
            "validate_scheduled_scanner_configs logged ERROR when it should not have"
        )

    def test_validate_logs_error_for_missing_liquidity_hunt(self, caplog):
        """Error logged when no active liquidity_hunt config exists."""
        import logging

        pp = _make_cfg(id=4, universe_id=1, scanner_type="pocket_pivot")
        with caplog.at_level(logging.ERROR, logger="app.tasks.scanning"):
            self._run_validation([], [pp])
        assert any("liquidity_hunt" in r.message.lower() for r in caplog.records)

    def test_validate_logs_error_for_missing_pocket_pivot(self, caplog):
        """Error logged when no active pocket_pivot config exists."""
        import logging

        lh = _make_cfg(id=2, universe_id=1, scanner_type="liquidity_hunt")
        tp = _make_cfg(id=6, universe_id=1, scanner_type="trend_pullback")
        with caplog.at_level(logging.ERROR, logger="app.tasks.scanning"):
            self._run_validation([lh], [], [tp])
        assert any("pocket_pivot" in r.message.lower() for r in caplog.records)

    def test_validate_logs_error_for_missing_trend_pullback(self, caplog):
        """Error logged when no active trend_pullback config exists."""
        import logging

        lh = _make_cfg(id=2, universe_id=1, scanner_type="liquidity_hunt")
        pp = _make_cfg(id=4, universe_id=1, scanner_type="pocket_pivot")
        with caplog.at_level(logging.ERROR, logger="app.tasks.scanning"):
            self._run_validation([lh], [pp], [])
        assert any("trend_pullback" in r.message.lower() for r in caplog.records)

    def test_validate_logs_error_when_universe_id_null(self, caplog):
        """Error logged when a config has universe_id=NULL."""
        import logging

        lh = _make_cfg(id=2, universe_id=None, scanner_type="liquidity_hunt")
        pp = _make_cfg(id=4, universe_id=1, scanner_type="pocket_pivot")
        with caplog.at_level(logging.ERROR, logger="app.tasks.scanning"):
            self._run_validation([lh], [pp])
        assert any("universe_id" in r.message.lower() for r in caplog.records)

    def test_validate_does_not_raise(self):
        """validate_scheduled_scanner_configs must never raise, even on DB error."""
        import app.tasks.scanning as scanning_module

        with patch(
            "app.tasks.scanning.SessionLocal",
            side_effect=Exception("DB unavailable"),
        ):
            scanning_module.validate_scheduled_scanner_configs()


def test_worker_ready_signal_wired_in_celery_app():
    """celery_app.py must import and wire validate_scheduled_scanner_configs."""
    import app.core.celery_app as celery_module

    assert hasattr(celery_module, "_on_worker_ready"), (
        "celery_app.py is missing _on_worker_ready — add @worker_ready.connect decorator"
    )
    from celery.signals import worker_ready

    assert len(worker_ready.receivers) > 0, (
        "worker_ready signal has no receivers — "
        "wire _on_worker_ready in celery_app.py with @worker_ready.connect"
    )
