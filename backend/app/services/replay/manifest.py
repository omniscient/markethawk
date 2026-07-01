"""Manifest freezing and market-data hashing for replay runs."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.scanner_config import ScannerConfig
from app.models.stock_aggregate import StockAggregate
from app.models.stock_split import StockSplit
from app.models.stock_universe import StockUniverse
from app.models.stock_universe_ticker import StockUniverseTicker
from app.models.trading_strategy import TradingStrategy
from app.utils.time import utc_now


@dataclass(frozen=True)
class ResolvedManifest:
    scanner_type: str
    scanner_config_snapshot: dict[str, Any]
    strategy_snapshot: dict[str, Any] | None
    universe_snapshot: dict[str, Any]


def _decimal_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _date_range(start_date: date, end_date: date):
    cursor = start_date
    while cursor <= end_date:
        yield cursor
        cursor += timedelta(days=1)


def _snapshot_scanner_config(config: ScannerConfig) -> dict[str, Any]:
    return copy.deepcopy(
        {
            "scanner_type": config.scanner_type,
            "parameters": config.parameters or {},
            "criteria": config.criteria or {},
            "outcome_config": config.outcome_config,
            "data_requirements": config.data_requirements,
        }
    )


def _snapshot_strategy(strategy: TradingStrategy | None) -> dict[str, Any] | None:
    if strategy is None:
        return None
    return copy.deepcopy(
        {
            "direction": strategy.direction,
            "entry_type": strategy.entry_type,
            "limit_offset_pct": _decimal_str(strategy.limit_offset_pct),
            "stop_pct": _decimal_str(strategy.stop_pct),
            "risk_reward_ratio": _decimal_str(strategy.risk_reward_ratio),
            "max_slippage_pct": _decimal_str(strategy.max_slippage_pct),
            "allowed_sessions": strategy.allowed_sessions,
            "risk_per_trade_pct": _decimal_str(strategy.risk_per_trade_pct),
            "max_position_usd": _decimal_str(strategy.max_position_usd),
            "max_trades_per_day": strategy.max_trades_per_day,
            "max_concurrent_positions": strategy.max_concurrent_positions,
        }
    )


class ManifestResolver:
    """Freezes replay inputs into immutable JSON-compatible snapshots."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def resolve(
        self,
        scanner_config_id: int,
        universe_id: int,
        start_date: date,
        end_date: date,
        strategy_id: int | None = None,
    ) -> ResolvedManifest:
        config = (
            self._db.query(ScannerConfig)
            .filter(ScannerConfig.id == scanner_config_id)
            .first()
        )
        if config is None:
            raise ValueError(f"ScannerConfig id={scanner_config_id} not found")

        universe = (
            self._db.query(StockUniverse).filter(StockUniverse.id == universe_id).first()
        )
        if universe is None:
            raise ValueError(f"StockUniverse id={universe_id} not found")

        strategy = None
        if strategy_id is not None:
            strategy = (
                self._db.query(TradingStrategy)
                .filter(TradingStrategy.id == strategy_id)
                .first()
            )
            if strategy is None:
                raise ValueError(f"TradingStrategy id={strategy_id} not found")

        tickers = sorted(
            row[0]
            for row in self._db.query(StockUniverseTicker.ticker)
            .filter(StockUniverseTicker.universe_id == universe_id)
            .all()
        )

        return ResolvedManifest(
            scanner_type=config.scanner_type,
            scanner_config_snapshot=_snapshot_scanner_config(config),
            strategy_snapshot=_snapshot_strategy(strategy),
            universe_snapshot={
                "tickers": tickers,
                "universe_id": universe_id,
                "frozen_at": utc_now().isoformat(),
            },
        )

    def compute_data_hash(
        self,
        tickers: list[str],
        start_date: date,
        end_date: date,
    ) -> str:
        return compute_data_hash(self._db, tickers, start_date, end_date)


def _cell_for(db: Session, ticker: str, trading_day: date) -> dict[str, Any]:
    bar = (
        db.query(StockAggregate)
        .filter(
            StockAggregate.ticker == ticker,
            StockAggregate.timespan == "day",
            StockAggregate.multiplier == 1,
            func.date(StockAggregate.timestamp) == trading_day,
        )
        .order_by(StockAggregate.timestamp.asc())
        .first()
    )
    minute_count = (
        db.query(func.count(StockAggregate.id))
        .filter(
            StockAggregate.ticker == ticker,
            StockAggregate.timespan == "minute",
            func.date(StockAggregate.timestamp) == trading_day,
        )
        .scalar()
        or 0
    )
    applied_splits = (
        db.query(StockSplit)
        .filter(
            StockSplit.ticker == ticker,
            StockSplit.execution_date > trading_day,
            StockSplit.adjustments_applied_at.isnot(None),
        )
        .order_by(StockSplit.execution_date.asc())
        .all()
    )

    base: dict[str, Any] = {
        "ticker": ticker,
        "date": str(trading_day),
        "minute_bar_count": int(minute_count),
        "applied_splits": [
            {
                "execution_date": str(split.execution_date),
                "from": _decimal_str(split.split_from),
                "to": _decimal_str(split.split_to),
            }
            for split in applied_splits
        ],
    }

    if bar is None:
        base["missing"] = True
        return base

    base.update(
        {
            "open": _decimal_str(bar.open),
            "high": _decimal_str(bar.high),
            "low": _decimal_str(bar.low),
            "close": _decimal_str(bar.close),
            "volume": int(bar.volume),
        }
    )
    return base


def compute_data_hash(
    db: Session,
    tickers: list[str],
    start_date: date,
    end_date: date,
) -> str:
    """Return a stable SHA-256 fingerprint over bars, minute counts, and splits."""

    cells = [
        _cell_for(db, ticker, trading_day)
        for ticker in sorted(tickers)
        for trading_day in _date_range(start_date, end_date)
    ]
    canonical = json.dumps(cells, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
