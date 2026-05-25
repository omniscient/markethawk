"""
Tests for AutoTradeExecutor — guard checks, position sizing, and paper-mode order path.

All tests use paper_mode=True strategies. Redis is replaced with fakeredis.
Live IBKR paths are isolated with unittest.mock.patch.
"""
from datetime import date
from decimal import Decimal
from unittest.mock import patch, MagicMock, AsyncMock
import fakeredis
import pytest
from sqlalchemy.orm import Session

from app.models.alert_rule import AlertRule
from app.models.scanner_event import ScannerEvent
from app.models.trading_strategy import TradingStrategy
from app.services.auto_trade_service import AutoTradeExecutor, PositionCalc


# ── helpers ────────────────────────────────────────────────────────────────

def _strategy(db, paper_mode=True, requires_approval=False, direction="long_only",
              max_trades_per_day=5, max_concurrent_positions=3,
              stop_pct=Decimal("2.0"), risk_per_trade_pct=Decimal("1.0"),
              risk_reward_ratio=Decimal("2.0"), max_position_usd=None):
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


def _event(db, ticker="AAPL", scanner_type="pre_market_volume_spike",
           opening_price=Decimal("50.00"), indicators=None):
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
    calc = executor._calculate_position(s, trigger_price=100.0, side="long",
                                        account_equity=10_000.0)
    assert calc.quantity == 50          # 100 risk / (100*2%) = 50
    assert calc.stop == pytest.approx(98.0, abs=0.01)
    assert calc.target == pytest.approx(104.0, abs=0.01)


def test_calculate_position_short_flips_stop_and_target():
    s = _mock_strategy()
    executor = AutoTradeExecutor()
    calc = executor._calculate_position(s, trigger_price=100.0, side="short",
                                        account_equity=10_000.0)
    assert calc.stop == pytest.approx(102.0, abs=0.01)
    assert calc.target == pytest.approx(96.0, abs=0.01)


def test_calculate_position_zero_quantity_when_price_too_high():
    s = _mock_strategy(risk_per_trade_pct=Decimal("0.001"))
    executor = AutoTradeExecutor()
    calc = executor._calculate_position(s, trigger_price=50000.0, side="long",
                                        account_equity=100.0)
    assert calc.quantity == 0


# ── _determine_side ────────────────────────────────────────────────────────

def test_determine_side_long_only_with_long_scanner():
    s = _mock_strategy(direction="long_only")
    ev = _mock_event(scanner_type="pre_market_volume_spike", indicators={})
    side = AutoTradeExecutor()._determine_side(ev, s)
    assert side == "long"


def test_determine_side_long_only_blocks_short():
    s = _mock_strategy(direction="long_only")
    ev = _mock_event(scanner_type="live_price_move", indicators={"price_change_pct": -3.0})
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
    strategy = _strategy(db, paper_mode=True, max_concurrent_positions=10,
                         max_trades_per_day=10)
    rule = _rule(db, strategy)
    event = _event(db)
    with patch(REDIS_PATCH, return_value=_fake_redis()):
        order = AutoTradeExecutor().maybe_execute(rule, event, db)
    assert order is not None
    assert order.status == "submitted"
    assert order.is_paper is True
    assert order.broker_order_id.startswith("PAPER-")


def test_maybe_execute_requires_approval_creates_pending_approval(db: Session):
    strategy = _strategy(db, paper_mode=True, requires_approval=True,
                         max_concurrent_positions=10, max_trades_per_day=10)
    rule = _rule(db, strategy)
    event = _event(db)
    with patch(REDIS_PATCH, return_value=_fake_redis()):
        order = AutoTradeExecutor().maybe_execute(rule, event, db)
    assert order is not None
    assert order.status == "pending_approval"


def test_maybe_execute_idempotent_second_call_returns_none(db: Session):
    strategy = _strategy(db, paper_mode=True, max_concurrent_positions=10,
                         max_trades_per_day=10)
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
    strategy = _strategy(db, paper_mode=False, requires_approval=False,
                         max_concurrent_positions=10, max_trades_per_day=10)
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

    with patch(REDIS_PATCH, return_value=_fake_redis()), \
         patch("app.providers.ibkr_orders.IBKROrderManager", return_value=mock_mgr):
        order = AutoTradeExecutor().maybe_execute(rule, event, db)

    assert order is not None
    assert order.status == "submitted"
    assert order.broker_order_id == "IB-PARENT-1"
