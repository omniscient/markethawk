"""Replay simulator protocol and shared dataclasses."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional, Protocol, runtime_checkable


@dataclass(frozen=True)
class SignalRecord:
    ticker: str
    signal_date: date
    indicators: dict
    source_event_id: Optional[int] = None


@dataclass(frozen=True)
class StrategyParams:
    entry_type: str
    stop_pct: float
    risk_reward_ratio: float
    limit_offset_pct: float
    direction: str


@dataclass
class SimulatedTrade:
    ticker: str
    signal_date: date
    source_event_id: Optional[int]

    entry_date: Optional[date] = None
    entry_price: Optional[Decimal] = None
    exit_date: Optional[date] = None
    exit_price: Optional[Decimal] = None
    exit_reason: Optional[str] = None
    bars_held: Optional[int] = None

    stop_price: Optional[Decimal] = None
    target_price: Optional[Decimal] = None

    return_pct: Optional[float] = None
    result_r: Optional[float] = None
    mfe_pct: Optional[float] = None
    mae_pct: Optional[float] = None

    fill_source: Optional[str] = None


@runtime_checkable
class ExitSimulator(Protocol):
    def simulate(
        self,
        signal: SignalRecord,
        strategy: StrategyParams,
        bars: list,
        max_hold_days: int,
    ) -> SimulatedTrade: ...
