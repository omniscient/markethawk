"""
Tests for AutoTradeExecutor — guard checks, position sizing, and paper-mode order path.

All tests use paper_mode=True strategies. Redis is replaced with fakeredis.
Live IBKR paths are isolated with unittest.mock.patch.
"""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis
import pytest
from sqlalchemy.orm import Session

from app.models.alert_rule import AlertRule
from app.models.auto_trade_order import AutoTradeOrder
from app.models.scanner_event import ScannerEvent
from app.models.trading_strategy import TradingStrategy
from app.services.auto_trade_service import (
    AutoTradeExecutor,
    approve_order,
    cancel_order,
    get_account,
    get_stats,
)

# ── Quality-gate patch target ──────────────────────────────────────────────────
# QualityGateService is imported into auto_trade_service's module namespace;
# patch via the service module attribute so all tests can override it cleanly.
GATE_PATCH = "app.services.auto_trade_service.QualityGateService.assess"


def _gate_assessment(verdict_str: str):
    """Return a lightweight mock QualityGateAssessment with the given verdict."""
    a = MagicMock()
    a.verdict = verdict_str  # str enum comparison works with plain string
    a.issues = []
    a.warnings = []
    return a


# ── helpers ────────────────────────────────────────────────────────────────


def _strategy(
    db,
    paper_mode=True,
    requires_approval=False,
    direction="long_only",
    max_trades_per_day=5,
    max_concurrent_positions=3,
    stop_pct=Decimal("2.0"),
    risk_per_trade_pct=Decimal("1.0"),
    risk_reward_ratio=Decimal("2.0"),
    max_position_usd=None,
):
    s = TradingStrategy(
        name=f"Test Strategy {id(db)}",
        paper_mode=paper_mode,
        requires_approval=requires_approval,
        is_active=True,
        direction=direction,
        max_trades_per_day=max_trades_per_day,
        max_concurrent_positions=max_concurrent_positions,
        stop_pct=stop_pct,
        risk_per_trade_pct=risk_per_trade_pct,
        risk_reward_ratio=risk_reward_ratio,
        max_position_usd=max_position_usd,
        allowed_sessions=["regular", "pre_market"],
    )
    db.add(s)
    db.flush()
    return s


def _rule(db, strategy, auto_trade=True):
    r = AlertRule(
        name="Test Rule",
        is_active=True,
        scanner_types=[],
        severity_filter="any",
        cooldown_minutes=0,
        channels=[],
        channel_config={},
        auto_trade=auto_trade,
        trading_strategy_id=strategy.id,
    )
    db.add(r)
    db.flush()
    return r


def _event(
    db,
    ticker="AAPL",
    scanner_type="pre_market_volume_spike",
    opening_price=Decimal("50.00"),
    indicators=None,
):
    ev = ScannerEvent(
        ticker=ticker,
        event_date=date.today(),
        scanner_type=scanner_type,
        indicators=indicators or {"last_trade_price": 50.0},
        criteria_met={},
        metadata_={"session": "pre_market"},
        opening_price=opening_price,
    )
    db.add(ev)
    db.flush()
    return ev


def _fake_redis():
    return fakeredis.FakeRedis(decode_responses=True)


# Patch target for Redis: use the module-local name, not the top-level redis package.
REDIS_PATCH = "app.services.auto_trade_service.redis.from_url"


@pytest.fixture(autouse=True)
def _default_gate_trusted():
    """Patch QualityGateService.assess to return 'trusted' for all tests by default.

    Tests that explicitly verify gate behaviour use their own patch(GATE_PATCH, ...)
    which overrides this autouse fixture's outer mock for the duration of the test.
    This prevents existing maybe_execute tests from breaking when Guard 2.5 is added.
    """
    with patch(GATE_PATCH, return_value=_gate_assessment("trusted")):
        yield


def _event_with_run(db, ticker="AAPL", scanner_run_id_override=None):
    """Create a Universe, ScannerRun, and ScannerEvent with scanner_run_id set.

    Used by gate-specific tests that need a resolvable universe_id so Guard 2.5
    will call QualityGateService.assess under strict policy (not policy=off).
    """
    from app.models.scanner_run import ScannerRun
    from app.models.stock_universe import StockUniverse

    universe = StockUniverse(
        name=f"Test Universe {ticker}",
        description="",
        criteria={},
        is_active=True,
    )
    db.add(universe)
    db.flush()

    run = ScannerRun(
        scanner_type="pre_market_volume_spike",
        universe_id=universe.id,
        status="completed",
    )
    db.add(run)
    db.flush()

    ev = ScannerEvent(
        ticker=ticker,
        event_date=date.today(),
        scanner_type="pre_market_volume_spike",
        indicators={"last_trade_price": 50.0},
        criteria_met={},
        metadata_={"session": "pre_market"},
        opening_price=Decimal("50.00"),
        scanner_run_id=scanner_run_id_override
        if scanner_run_id_override is not None
        else run.id,
    )
    db.add(ev)
    db.flush()
    return ev


# ── _calculate_position (pure math, no DB/Redis) ───────────────────────────


def _mock_strategy(**attrs):
    """Build a MagicMock with TradingStrategy-like attributes for pure-math tests."""
    defaults = {
        "risk_per_trade_pct": Decimal("1.0"),
        "stop_pct": Decimal("2.0"),
        "risk_reward_ratio": Decimal("2.0"),
        "limit_offset_pct": Decimal("0.0"),
        "entry_type": "market",
        "max_position_usd": None,
        "direction": "long_only",
    }
    defaults.update(attrs)
    s = MagicMock(spec_set=list(defaults.keys()))
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


def _mock_event(**attrs):
    """Build a MagicMock with ScannerEvent-like attributes for pure-math tests."""
    defaults = {
        "scanner_type": "pre_market_volume_spike",
        "indicators": {},
    }
    defaults.update(attrs)
    ev = MagicMock(spec_set=list(defaults.keys()))
    for k, v in defaults.items():
        setattr(ev, k, v)
    return ev


def test_calculate_position_long_basic():
    s = _mock_strategy()
    executor = AutoTradeExecutor()
    calc = executor._calculate_position(
        s, trigger_price=100.0, side="long", account_equity=10_000.0
    )
    assert calc.quantity == 50  # 100 risk / (100*2%) = 50
    assert calc.stop == pytest.approx(98.0, abs=0.01)
    assert calc.target == pytest.approx(104.0, abs=0.01)


def test_calculate_position_short_flips_stop_and_target():
    s = _mock_strategy()
    executor = AutoTradeExecutor()
    calc = executor._calculate_position(
        s, trigger_price=100.0, side="short", account_equity=10_000.0
    )
    assert calc.stop == pytest.approx(102.0, abs=0.01)
    assert calc.target == pytest.approx(96.0, abs=0.01)


def test_calculate_position_zero_quantity_when_price_too_high():
    s = _mock_strategy(risk_per_trade_pct=Decimal("0.001"))
    executor = AutoTradeExecutor()
    calc = executor._calculate_position(
        s, trigger_price=50000.0, side="long", account_equity=100.0
    )
    assert calc.quantity == 0


# ── _determine_side ────────────────────────────────────────────────────────


def test_determine_side_long_only_with_long_scanner():
    s = _mock_strategy(direction="long_only")
    ev = _mock_event(scanner_type="pre_market_volume_spike", indicators={})
    side = AutoTradeExecutor()._determine_side(ev, s)
    assert side == "long"


def test_determine_side_long_only_blocks_short():
    s = _mock_strategy(direction="long_only")
    ev = _mock_event(
        scanner_type="live_price_move", indicators={"price_change_pct": -3.0}
    )
    side = AutoTradeExecutor()._determine_side(ev, s)
    assert side is None


# ── maybe_execute — guard checks ──────────────────────────────────────────


def test_maybe_execute_skips_when_auto_trade_false(db: Session):
    strategy = _strategy(db)
    rule = _rule(db, strategy, auto_trade=False)
    event = _event(db)
    with patch(REDIS_PATCH, return_value=_fake_redis()):
        result = AutoTradeExecutor().maybe_execute(rule, event, db)
    assert result is None


def test_maybe_execute_skips_when_strategy_inactive(db: Session):
    strategy = _strategy(db)
    strategy.is_active = False
    db.flush()
    rule = _rule(db, strategy)
    event = _event(db)
    with patch(REDIS_PATCH, return_value=_fake_redis()):
        result = AutoTradeExecutor().maybe_execute(rule, event, db)
    assert result is None


def test_maybe_execute_paper_mode_creates_submitted_order(db: Session):
    strategy = _strategy(
        db, paper_mode=True, max_concurrent_positions=10, max_trades_per_day=10
    )
    rule = _rule(db, strategy)
    event = _event(db)
    with patch(REDIS_PATCH, return_value=_fake_redis()):
        order = AutoTradeExecutor().maybe_execute(rule, event, db)
    assert order is not None
    assert order.status == "submitted"
    assert order.is_paper is True
    assert order.broker_order_id.startswith("PAPER-")


def test_maybe_execute_requires_approval_creates_pending_approval(db: Session):
    strategy = _strategy(
        db,
        paper_mode=True,
        requires_approval=True,
        max_concurrent_positions=10,
        max_trades_per_day=10,
    )
    rule = _rule(db, strategy)
    event = _event(db)
    with patch(REDIS_PATCH, return_value=_fake_redis()):
        order = AutoTradeExecutor().maybe_execute(rule, event, db)
    assert order is not None
    assert order.status == "pending_approval"


def test_maybe_execute_idempotent_second_call_returns_none(db: Session):
    strategy = _strategy(
        db, paper_mode=True, max_concurrent_positions=10, max_trades_per_day=10
    )
    rule = _rule(db, strategy)
    event = _event(db)
    fake_r = _fake_redis()
    with patch(REDIS_PATCH, return_value=fake_r):
        AutoTradeExecutor().maybe_execute(rule, event, db)
    with patch(REDIS_PATCH, return_value=fake_r):
        second = AutoTradeExecutor().maybe_execute(rule, event, db)
    assert second is None


def test_maybe_execute_live_mode_isolates_ibkr(db: Session):
    """Live (paper_mode=False) path: IBKROrderManager is patched per spec Req 7."""
    from app.models.system_config import SystemConfig

    db.add(SystemConfig(key="AUTO_TRADING_ENABLED", value="true"))
    db.flush()
    strategy = _strategy(
        db,
        paper_mode=False,
        requires_approval=False,
        max_concurrent_positions=10,
        max_trades_per_day=10,
        max_position_usd=Decimal("5000.0"),
    )
    rule = _rule(db, strategy)
    event = _event(db)

    mock_result = MagicMock()
    mock_result.parent_order_id = "IB-PARENT-1"
    mock_result.stop_order_id = "IB-STOP-1"
    mock_result.target_order_id = "IB-TGT-1"

    mock_summary = MagicMock()
    mock_summary.net_liquidation = 100_000.0

    mock_mgr = MagicMock()
    mock_mgr.get_account_summary = AsyncMock(return_value=mock_summary)
    mock_mgr.place_bracket_order = AsyncMock(return_value=mock_result)

    with (
        patch(REDIS_PATCH, return_value=_fake_redis()),
        patch("app.providers.ibkr_orders.IBKROrderManager", return_value=mock_mgr),
    ):
        order = AutoTradeExecutor().maybe_execute(rule, event, db)

    assert order is not None
    assert order.status == "submitted"
    assert order.broker_order_id == "IB-PARENT-1"


# ── New service functions ──────────────────────────────────────────────────


def _make_order(db, strategy, paper=True, status="pending_approval"):
    order = AutoTradeOrder(
        trading_strategy_id=strategy.id,
        symbol="AAPL",
        side="long",
        event_date=date.today(),
        status=status,
        is_paper=paper,
        trigger_price=Decimal("50.00"),
        calculated_stop=Decimal("49.00"),
        calculated_target=Decimal("52.00"),
        quantity=10,
    )
    db.add(order)
    db.flush()
    return order


# ── approve_order ──────────────────────────────────────────────────────────


def test_approve_order_paper_sets_submitted(db):
    s = _strategy(db, paper_mode=True)
    o = _make_order(db, s)
    result = approve_order(o, s, db)
    assert result.status == "submitted"
    assert result.broker_order_id.startswith("PAPER-")


def test_approve_order_live_queues_celery(db):
    s = _strategy(db, paper_mode=False)
    o = _make_order(db, s)
    with patch("app.services.auto_trade_service.AutoTradeExecutor._get_account_equity"):
        with patch("app.core.celery_app.celery_app.send_task") as mock_send:
            result = approve_order(o, s, db)
    assert result.status == "pending"
    mock_send.assert_called_once_with(
        "app.tasks.submit_approved_order",
        kwargs={"order_id": o.id},
    )


# ── cancel_order ───────────────────────────────────────────────────────────


def test_cancel_order_paper_sets_cancelled(db):
    s = _strategy(db, paper_mode=True)
    o = _make_order(db, s, paper=True, status="submitted")
    result = cancel_order(o, db)
    assert result.status == "cancelled"


def test_cancel_order_live_calls_ibkr_cancel(db):
    s = _strategy(db, paper_mode=False)
    o = _make_order(db, s, paper=False, status="submitted")
    o.broker_order_id = "12345"
    o.broker_stop_id = "12346"
    o.broker_target_id = "12347"
    db.flush()

    mock_mgr = MagicMock()
    mock_mgr.cancel_bracket = AsyncMock()

    with patch("app.providers.ibkr_orders.IBKROrderManager", return_value=mock_mgr):
        result = cancel_order(o, db)

    assert result.status == "cancelled"
    mock_mgr.cancel_bracket.assert_awaited_once()


# ── get_account ────────────────────────────────────────────────────────────


def test_get_account_returns_disconnected_on_error():
    result = get_account()
    # In test env IBKR is not running — should return a graceful fallback
    assert "connected" in result
    # Either connected (if somehow IBKR is up) or not
    if not result["connected"]:
        assert result["net_liquidation"] is None
        assert "error" in result


# ── get_stats ──────────────────────────────────────────────────────────────


def test_get_stats_returns_expected_shape(db):
    result = get_stats(db, days=30)
    assert "period_days" in result
    assert "total_orders" in result
    assert "by_status" in result
    assert "win_rate" in result
    assert result["period_days"] == 30


# ── Guard 2.5: quality gate verdicts ──────────────────────────────────────────


def test_quality_gate_trusted_allows_order(db: Session):
    """verdict=trusted → order created normally; gate called with policy=strict."""
    from app.schemas.quality_gate import QualityGatePolicy

    strategy = _strategy(db, max_concurrent_positions=10, max_trades_per_day=10)
    rule = _rule(db, strategy)
    event = _event_with_run(db)

    with (
        patch(REDIS_PATCH, return_value=_fake_redis()),
        patch(GATE_PATCH, return_value=_gate_assessment("trusted")) as mock_assess,
    ):
        order = AutoTradeExecutor().maybe_execute(rule, event, db)

    assert order is not None
    assert order.status == "submitted"
    # Gate must be called exactly once with strict policy (not trusting advisory blob)
    mock_assess.assert_called_once()
    call_request = mock_assess.call_args.args[1]
    assert call_request.policy == QualityGatePolicy.strict.value


def test_quality_gate_warning_refuses_order(db: Session):
    """verdict=warning → no order created."""
    strategy = _strategy(db, max_concurrent_positions=10, max_trades_per_day=10)
    rule = _rule(db, strategy)
    event = _event_with_run(db, ticker="MSFT")

    with (
        patch(REDIS_PATCH, return_value=_fake_redis()),
        patch(GATE_PATCH, return_value=_gate_assessment("warning")),
    ):
        order = AutoTradeExecutor().maybe_execute(rule, event, db)

    assert order is None


def test_quality_gate_blocked_refuses_order(db: Session):
    """verdict=blocked → no order created."""
    strategy = _strategy(db, max_concurrent_positions=10, max_trades_per_day=10)
    rule = _rule(db, strategy)
    event = _event_with_run(db, ticker="GOOG")

    with (
        patch(REDIS_PATCH, return_value=_fake_redis()),
        patch(GATE_PATCH, return_value=_gate_assessment("blocked")),
    ):
        order = AutoTradeExecutor().maybe_execute(rule, event, db)

    assert order is None


def test_quality_gate_skipped_without_bypass_refuses_order(db: Session):
    """verdict=skipped and QUALITY_GATE_SKIP_BYPASS absent → no order created."""
    strategy = _strategy(db, max_concurrent_positions=10, max_trades_per_day=10)
    rule = _rule(db, strategy)
    event = _event_with_run(db, ticker="AMZN")
    # No QUALITY_GATE_SKIP_BYPASS row in SystemConfig

    with (
        patch(REDIS_PATCH, return_value=_fake_redis()),
        patch(GATE_PATCH, return_value=_gate_assessment("skipped")),
    ):
        order = AutoTradeExecutor().maybe_execute(rule, event, db)

    assert order is None


def test_quality_gate_skipped_with_bypass_allows_order(db: Session):
    """verdict=skipped + QUALITY_GATE_SKIP_BYPASS='true' → order created."""
    from app.models.system_config import SystemConfig

    db.add(SystemConfig(key="QUALITY_GATE_SKIP_BYPASS", value="true"))
    db.flush()

    strategy = _strategy(db, max_concurrent_positions=10, max_trades_per_day=10)
    rule = _rule(db, strategy)
    event = _event_with_run(db, ticker="NFLX")

    with (
        patch(REDIS_PATCH, return_value=_fake_redis()),
        patch(GATE_PATCH, return_value=_gate_assessment("skipped")),
    ):
        order = AutoTradeExecutor().maybe_execute(rule, event, db)

    assert order is not None
    assert order.status == "submitted"


def test_quality_gate_exception_fails_closed(db: Session):
    """Gate service raises → no order created (fail-closed)."""
    strategy = _strategy(db, max_concurrent_positions=10, max_trades_per_day=10)
    rule = _rule(db, strategy)
    event = _event_with_run(db, ticker="META")

    with (
        patch(REDIS_PATCH, return_value=_fake_redis()),
        patch(GATE_PATCH, side_effect=RuntimeError("gate unavailable")),
    ):
        order = AutoTradeExecutor().maybe_execute(rule, event, db)

    assert order is None


def test_quality_gate_warning_refuses_even_with_bypass(db: Session):
    """verdict=warning + QUALITY_GATE_SKIP_BYPASS='true' → still refuses.

    The bypass flag only covers 'skipped' verdicts (universe-unresolvable runs).
    An active 'warning' verdict from a strict-policy assessment must never be
    overridden — this is the critical live-trading safety invariant.
    """
    from app.models.system_config import SystemConfig

    db.add(SystemConfig(key="QUALITY_GATE_SKIP_BYPASS", value="true"))
    db.flush()

    strategy = _strategy(db, max_concurrent_positions=10, max_trades_per_day=10)
    rule = _rule(db, strategy)
    event = _event_with_run(db, ticker="TSLA")

    with (
        patch(REDIS_PATCH, return_value=_fake_redis()),
        patch(GATE_PATCH, return_value=_gate_assessment("warning")),
    ):
        order = AutoTradeExecutor().maybe_execute(rule, event, db)

    assert order is None
    assert db.query(AutoTradeOrder).count() == 0


def test_quality_gate_blocked_refuses_even_with_bypass(db: Session):
    """verdict=blocked + QUALITY_GATE_SKIP_BYPASS='true' → still refuses.

    Same invariant as warning: bypass only unlocks 'skipped', never 'blocked'.
    """
    from app.models.system_config import SystemConfig

    db.add(SystemConfig(key="QUALITY_GATE_SKIP_BYPASS", value="true"))
    db.flush()

    strategy = _strategy(db, max_concurrent_positions=10, max_trades_per_day=10)
    rule = _rule(db, strategy)
    event = _event_with_run(db, ticker="NVDA")

    with (
        patch(REDIS_PATCH, return_value=_fake_redis()),
        patch(GATE_PATCH, return_value=_gate_assessment("blocked")),
    ):
        order = AutoTradeExecutor().maybe_execute(rule, event, db)

    assert order is None
    assert db.query(AutoTradeOrder).count() == 0


# ── Guard 1b: max_position_usd required for live strategies ───────────────────


class TestMaybeExecuteMaxPositionGuard:
    """Execution-time guard: live strategy with no or invalid max_position_usd returns None (R3)."""

    def _setup(self, db, max_position_usd=None):
        """Create AUTO_TRADING_ENABLED=true, a live strategy, rule, and event."""
        from app.models.scanner_event import ScannerEvent
        from app.models.system_config import SystemConfig

        db.add(SystemConfig(key="AUTO_TRADING_ENABLED", value="true"))
        strat = _strategy(db, paper_mode=False, max_position_usd=max_position_usd)
        rule = AlertRule(
            name="Live Guard Test",
            auto_trade=True,
            trading_strategy_id=strat.id,
        )
        db.add(rule)
        event = ScannerEvent(
            ticker="AAPL",
            scanner_type="pre_market_volume_spike",
            event_date=date.today(),
            indicators={"last_trade_price": 150.0},
        )
        db.add(event)
        db.flush()
        return strat, rule, event

    def test_maybe_execute_rejects_live_strategy_without_max_position(self, db):
        """guard 1b: max_position_usd=None → returns None.

        Uses _get_account_equity mocked to positive equity so the ONLY reason
        maybe_execute returns None is the max_position_usd guard (not a missing
        account-equity fallback).  If the guard is removed the code proceeds to
        create an order and returns it — the assertion then FAILS, making the test
        non-vacuous.
        """
        strat, rule, event = self._setup(db, max_position_usd=None)
        executor = AutoTradeExecutor()

        with (
            patch(REDIS_PATCH, return_value=_fake_redis()),
            patch.object(executor, "_get_account_equity", return_value=100_000.0),
            patch.object(executor, "_submit_to_ibkr") as mock_submit,
        ):
            result = executor.maybe_execute(rule=rule, event=event, db=db)

        assert result is None, "Live strategy missing max_position_usd must be rejected"
        mock_submit.assert_not_called()

    def test_maybe_execute_rejects_live_strategy_with_zero_max_position(self, db):
        """guard 1b: max_position_usd=0 → returns None (FIX 5: reject <= 0)."""
        from decimal import Decimal

        strat, rule, event = self._setup(db, max_position_usd=Decimal("0"))
        executor = AutoTradeExecutor()

        with (
            patch(REDIS_PATCH, return_value=_fake_redis()),
            patch.object(executor, "_get_account_equity", return_value=100_000.0),
            patch.object(executor, "_submit_to_ibkr") as mock_submit,
        ):
            result = executor.maybe_execute(rule=rule, event=event, db=db)

        assert result is None, "Live strategy with max_position_usd=0 must be rejected"
        mock_submit.assert_not_called()

    def test_maybe_execute_rejects_live_strategy_with_negative_max_position(self, db):
        """guard 1b: max_position_usd=-100 → returns None (FIX 5: reject <= 0)."""
        from decimal import Decimal

        strat, rule, event = self._setup(db, max_position_usd=Decimal("-100"))
        executor = AutoTradeExecutor()

        with (
            patch(REDIS_PATCH, return_value=_fake_redis()),
            patch.object(executor, "_get_account_equity", return_value=100_000.0),
            patch.object(executor, "_submit_to_ibkr") as mock_submit,
        ):
            result = executor.maybe_execute(rule=rule, event=event, db=db)

        assert result is None, "Live strategy with max_position_usd<0 must be rejected"
        mock_submit.assert_not_called()


class TestPaperOrderNeverCallsPlaceBracketOrder:
    """Paper mode must never invoke place_bracket_order — validates the upstream invariant (R-V-8)."""

    def test_paper_order_never_calls_place_bracket_order(self, db):
        from app.models.scanner_event import ScannerEvent

        strat = _strategy(db, paper_mode=True, max_position_usd=Decimal("5000.0"))
        rule = AlertRule(
            name="Paper Invariant Test",
            auto_trade=True,
            trading_strategy_id=strat.id,
        )
        db.add(rule)
        event = ScannerEvent(
            ticker="TSLA",
            scanner_type="pre_market_volume_spike",
            event_date=date.today(),
            indicators={"last_trade_price": 200.0},
        )
        db.add(event)
        db.flush()

        fake_r = fakeredis.FakeRedis(decode_responses=True)
        executor = AutoTradeExecutor()

        with patch("redis.from_url", return_value=fake_r):
            with patch(
                "app.providers.ibkr_orders.IBKROrderManager.place_bracket_order",
                new_callable=AsyncMock,
            ) as mock_place:
                executor.maybe_execute(rule=rule, event=event, db=db)

        mock_place.assert_not_called()


# ── _validate_basics direct unit tests ────────────────────────────────────────


def test_validate_basics_kill_switch_off_returns_none(db: Session):
    """Live strategy + AUTO_TRADING_ENABLED absent → _validate_basics returns None.

    Covers the kill-switch None branch without the expensive idempotency/gate setup.
    """
    from app.models.system_config import SystemConfig

    # Ensure no AUTO_TRADING_ENABLED row exists (live DB might have it; delete it)
    db.query(SystemConfig).filter(SystemConfig.key == "AUTO_TRADING_ENABLED").delete()
    db.flush()

    strategy = _strategy(db, paper_mode=False)
    rule = _rule(db, strategy)

    result = AutoTradeExecutor()._validate_basics(rule, db)
    assert result is None


def test_validate_basics_missing_max_position_usd_returns_none(db: Session):
    """Live strategy with max_position_usd=None → _validate_basics returns None.

    AUTO_TRADING_ENABLED=true so we reach the max_position_usd guard.
    """
    from app.models.system_config import SystemConfig

    # Upsert AUTO_TRADING_ENABLED=true so we reach the max_position_usd guard
    existing = (
        db.query(SystemConfig)
        .filter(SystemConfig.key == "AUTO_TRADING_ENABLED")
        .first()
    )
    if existing:
        existing.value = "true"
    else:
        db.add(SystemConfig(key="AUTO_TRADING_ENABLED", value="true"))
    db.flush()

    strategy = _strategy(db, paper_mode=False, max_position_usd=None)
    rule = _rule(db, strategy)

    result = AutoTradeExecutor()._validate_basics(rule, db)
    assert result is None


# ── _size_position direct unit tests ──────────────────────────────────────────


def test__size_position_no_trigger_price(db: Session):
    """Event with no price fields → _size_position returns None.

    Uses a ScannerEvent with no indicators and no price columns so
    _extract_trigger_price returns None.
    """
    strategy = _strategy(db)
    # Build an event directly (not via _event()) to avoid the fallback default indicators
    ev = ScannerEvent(
        ticker="AAPL",
        event_date=date.today(),
        scanner_type="pre_market_volume_spike",
        indicators={},  # no price keys
        criteria_met={},
        metadata_={"session": "pre_market"},
        opening_price=None,
        closing_price=None,
        previous_close=None,
    )
    db.add(ev)
    db.flush()

    result = AutoTradeExecutor()._size_position(ev, strategy, db)
    assert result is None


def test__size_position_undetermined_side(db: Session):
    """pre_market_volume_spike (hint='long') + short_only strategy → _size_position returns None.

    The scanner hints 'long' but the strategy only allows 'short', so
    _determine_side returns None and _size_position returns None.
    """
    strategy = _strategy(db, direction="short_only")
    ev = ScannerEvent(
        ticker="QQQ",
        event_date=date.today(),
        scanner_type="pre_market_volume_spike",  # SCANNER_DIRECTION_HINTS → "long"
        indicators={"last_trade_price": 400.0},
        criteria_met={},
        metadata_={"session": "regular"},
    )
    db.add(ev)
    db.flush()

    result = AutoTradeExecutor()._size_position(ev, strategy, db)
    assert result is None


def test__size_position_zero_equity(db: Session):
    """_get_account_equity returns 0 → _size_position returns None."""
    strategy = _strategy(db)
    event = _event(db)
    executor = AutoTradeExecutor()

    with patch.object(executor, "_get_account_equity", return_value=0.0):
        result = executor._size_position(event, strategy, db)

    assert result is None


def test__size_position_zero_quantity(db: Session):
    """Risk too small to buy one share → _size_position returns None.

    With equity=100, risk_per_trade_pct=0.001%, stop_pct=2%, price=50000:
      risk_amount = 100 * 0.001 / 100 = 0.001
      stop_distance = 50000 * 0.02 / 100 = 10
      quantity = int(0.001 / 10) = 0
    """
    strategy = _strategy(
        db,
        risk_per_trade_pct=Decimal("0.001"),
        stop_pct=Decimal("2.0"),
    )
    event = _event(db, indicators={"last_trade_price": 50000.0})
    executor = AutoTradeExecutor()

    with patch.object(executor, "_get_account_equity", return_value=100.0):
        result = executor._size_position(event, strategy, db)

    assert result is None
