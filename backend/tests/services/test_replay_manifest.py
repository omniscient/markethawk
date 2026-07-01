"""Tests for replay manifest freezing and market-data hashing."""

from datetime import date, datetime
from decimal import Decimal


def _seed_replay_inputs(db):
    from app.models import ScannerConfig, StockUniverse, StockUniverseTicker
    from app.models.trading_strategy import TradingStrategy

    universe = StockUniverse(
        name="Replay Universe",
        description="Signals for replay tests",
        criteria={"min_price": 5},
        is_active=True,
    )
    db.add(universe)
    db.flush()

    db.add_all(
        [
            StockUniverseTicker(universe_id=universe.id, ticker="MSFT"),
            StockUniverseTicker(universe_id=universe.id, ticker="AAPL"),
        ]
    )

    scanner = ScannerConfig(
        name="Replay Scanner",
        scanner_type="pre_market_volume_spike",
        parameters={"min_volume": 100000, "spike_ratio": 4.0},
        criteria=[{"field": "volume_ratio", "op": ">=", "value": 4.0}],
        outcome_config={"intervals": ["1d", "5d"]},
        data_requirements={"intraday": "advisory"},
        is_active=True,
        universe_id=universe.id,
    )
    strategy = TradingStrategy(
        name="Replay Strategy",
        direction="long_only",
        entry_type="limit",
        limit_offset_pct=Decimal("1.5"),
        stop_pct=Decimal("2.0"),
        risk_reward_ratio=Decimal("2.5"),
        max_slippage_pct=Decimal("0.5"),
        allowed_sessions=["regular"],
        risk_per_trade_pct=Decimal("1.0"),
        max_position_usd=Decimal("5000"),
        max_trades_per_day=3,
        max_concurrent_positions=2,
    )
    db.add(scanner)
    db.add(strategy)
    db.flush()
    return scanner, strategy, universe


def _daily_bar(db, ticker: str, day: date, close: str = "102.00"):
    from app.models.stock_aggregate import StockAggregate

    bar = StockAggregate(
        ticker=ticker,
        timestamp=datetime(day.year, day.month, day.day),
        multiplier=1,
        timespan="day",
        open=Decimal("100.00"),
        high=Decimal("105.00"),
        low=Decimal("99.00"),
        close=Decimal(close),
        volume=1_000_000,
        vwap=Decimal("101.00"),
        transactions=5000,
    )
    db.add(bar)
    db.flush()
    return bar


def _minute_bar(db, ticker: str, ts: datetime):
    from app.models.stock_aggregate import StockAggregate

    bar = StockAggregate(
        ticker=ticker,
        timestamp=ts,
        multiplier=1,
        timespan="minute",
        open=Decimal("100.00"),
        high=Decimal("101.00"),
        low=Decimal("99.50"),
        close=Decimal("100.50"),
        volume=10_000,
        vwap=Decimal("100.25"),
        transactions=100,
    )
    db.add(bar)
    db.flush()
    return bar


def test_resolve_freezes_scanner_strategy_and_sorted_universe(db):
    from app.services.replay.manifest import ManifestResolver

    scanner, strategy, universe = _seed_replay_inputs(db)
    resolver = ManifestResolver(db)

    manifest = resolver.resolve(
        scanner_config_id=scanner.id,
        universe_id=universe.id,
        start_date=date(2026, 1, 5),
        end_date=date(2026, 1, 9),
        strategy_id=strategy.id,
    )

    assert manifest.scanner_type == "pre_market_volume_spike"
    assert manifest.scanner_config_snapshot == {
        "scanner_type": "pre_market_volume_spike",
        "parameters": {"min_volume": 100000, "spike_ratio": 4.0},
        "criteria": [{"field": "volume_ratio", "op": ">=", "value": 4.0}],
        "outcome_config": {"intervals": ["1d", "5d"]},
        "data_requirements": {"intraday": "advisory"},
    }
    assert manifest.strategy_snapshot["direction"] == "long_only"
    assert manifest.strategy_snapshot["limit_offset_pct"] == "1.5"
    assert manifest.strategy_snapshot["risk_reward_ratio"] == "2.5"
    assert manifest.universe_snapshot["tickers"] == ["AAPL", "MSFT"]
    assert manifest.universe_snapshot["universe_id"] == universe.id
    assert "frozen_at" in manifest.universe_snapshot

    from app.models import StockUniverseTicker

    scanner.parameters["min_volume"] = 999
    strategy.direction = "short_only"
    db.add(StockUniverseTicker(universe_id=universe.id, ticker="NVDA"))
    db.flush()

    assert manifest.scanner_config_snapshot["parameters"]["min_volume"] == 100000
    assert manifest.strategy_snapshot["direction"] == "long_only"
    assert manifest.universe_snapshot["tickers"] == ["AAPL", "MSFT"]


def test_resolve_allows_scanner_only_manifest(db):
    from app.services.replay.manifest import ManifestResolver

    scanner, _strategy, universe = _seed_replay_inputs(db)
    manifest = ManifestResolver(db).resolve(
        scanner_config_id=scanner.id,
        universe_id=universe.id,
        start_date=date(2026, 1, 5),
        end_date=date(2026, 1, 9),
        strategy_id=None,
    )

    assert manifest.strategy_snapshot is None


def test_compute_data_hash_is_stable_and_changes_when_daily_bar_mutates(db):
    from app.services.replay.manifest import compute_data_hash

    day = date(2026, 1, 5)
    bar = _daily_bar(db, "AAPL", day, close="102.00")
    first = compute_data_hash(db, ["AAPL"], day, day)
    second = compute_data_hash(db, ["AAPL"], day, day)
    assert first == second

    bar.close = Decimal("103.00")
    db.flush()

    assert compute_data_hash(db, ["AAPL"], day, day) != first


def test_compute_data_hash_changes_when_minute_count_changes(db):
    from app.services.replay.manifest import compute_data_hash

    day = date(2026, 1, 5)
    _daily_bar(db, "AAPL", day)
    first = compute_data_hash(db, ["AAPL"], day, day)

    _minute_bar(db, "AAPL", datetime(2026, 1, 5, 9, 30))

    assert compute_data_hash(db, ["AAPL"], day, day) != first


def test_compute_data_hash_changes_when_applied_split_version_changes(db):
    from app.models.stock_split import StockSplit
    from app.services.replay.manifest import compute_data_hash

    day = date(2026, 1, 5)
    _daily_bar(db, "AAPL", day)
    first = compute_data_hash(db, ["AAPL"], day, day)

    db.add(
        StockSplit(
            ticker="AAPL",
            execution_date=date(2026, 1, 20),
            split_from=Decimal("1"),
            split_to=Decimal("2"),
            adjustments_applied_at=datetime(2026, 1, 21, 12, 0, 0),
        )
    )
    db.flush()

    assert compute_data_hash(db, ["AAPL"], day, day) != first


def test_replay_run_defaults_and_nullable_strategy(db):
    from app.models.replay_run import ReplayRun

    run = ReplayRun(
        scanner_type="pre_market_volume_spike",
        scanner_config_snapshot={"scanner_type": "pre_market_volume_spike"},
        trading_strategy_id=None,
        strategy_snapshot=None,
        universe_id=1,
        universe_snapshot={"tickers": ["AAPL"]},
        start_date=date(2026, 1, 5),
        end_date=date(2026, 1, 9),
        max_hold_days=10,
    )

    assert run.trading_strategy_id is None
    assert run.metrics is None
    assert run.status is None or run.status == "queued"
