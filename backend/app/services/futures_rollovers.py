"""Rollover detection — extracted from FuturesDataService."""

import logging
from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple

import pandas as pd
from sqlalchemy.orm import Session

from app.models.futures_aggregate import FuturesAggregate
from app.models.futures_contract import FuturesContract
from app.models.futures_rollover import FuturesRollover

logger = logging.getLogger(__name__)

CALENDAR_ROLL_DAYS_BEFORE_EXPIRY = 8


class FuturesRolloversService:
    """Rollover detection — extracted from FuturesDataService."""

    @staticmethod
    async def _detect_rollovers(
        db: Session,
        symbol: str,
        exchange: str,
        timespan: str = "day",
        multiplier: int = 1,
    ) -> int:
        """Analyse downloaded bar data and detect volume-crossover rollover dates."""
        contracts = (
            db.query(FuturesContract)
            .filter(
                FuturesContract.symbol == symbol,
                FuturesContract.exchange == exchange.upper(),
                FuturesContract.data_downloaded == True,  # noqa: E712
            )
            .order_by(FuturesContract.contract_month.asc())
            .all()
        )

        if len(contracts) < 2:
            return 0

        rollover_count = 0

        for i in range(len(contracts) - 1):
            current = contracts[i]
            nxt = contracts[i + 1]

            roll = _detect_single_rollover(
                db=db,
                symbol=symbol,
                exchange=exchange,
                current_month=current.contract_month,
                next_month=nxt.contract_month,
                current_expiry=current.expiry_date,
                timespan=timespan,
                multiplier=multiplier,
            )

            if roll is None:
                continue

            roll_date, method = roll

            existing = (
                db.query(FuturesRollover)
                .filter(
                    FuturesRollover.symbol == symbol,
                    FuturesRollover.from_contract == current.contract_month,
                )
                .first()
            )

            if existing:
                existing.roll_date = roll_date
                existing.to_contract = nxt.contract_month
                existing.detection_method = method
            else:
                db.add(
                    FuturesRollover(
                        symbol=symbol,
                        exchange=exchange.upper(),
                        from_contract=current.contract_month,
                        to_contract=nxt.contract_month,
                        roll_date=roll_date,
                        detection_method=method,
                    )
                )
                rollover_count += 1

        db.commit()
        logger.info(
            f"FuturesDataService: Detected {rollover_count} new rollovers for {symbol}."
        )
        return rollover_count


def _detect_single_rollover(
    db: Session,
    symbol: str,
    exchange: str,
    current_month: str,
    next_month: str,
    current_expiry: Optional[date],
    timespan: str,
    multiplier: int,
) -> Optional[Tuple[date, str]]:
    """Determine the roll date between two consecutive contract months."""
    if current_expiry:
        overlap_start = datetime.combine(
            current_expiry - timedelta(days=30), datetime.min.time()
        )
    else:
        overlap_start = None

    def load_volume_series(contract_month: str) -> pd.DataFrame:
        q = db.query(
            FuturesAggregate.timestamp,
            FuturesAggregate.volume,
        ).filter(
            FuturesAggregate.symbol == symbol,
            FuturesAggregate.contract_month == contract_month,
            FuturesAggregate.timespan == timespan,
            FuturesAggregate.multiplier == multiplier,
        )
        if overlap_start:
            q = q.filter(FuturesAggregate.timestamp >= overlap_start)

        rows = q.order_by(FuturesAggregate.timestamp.asc()).all()
        if not rows:
            return pd.DataFrame(columns=["timestamp", "volume"])
        return pd.DataFrame(rows, columns=["timestamp", "volume"])

    curr_df = load_volume_series(current_month)
    next_df = load_volume_series(next_month)

    if curr_df.empty or next_df.empty:
        if current_expiry:
            roll_date = current_expiry - timedelta(
                days=CALENDAR_ROLL_DAYS_BEFORE_EXPIRY
            )
            return roll_date, "calendar"
        return None

    curr_df["date"] = curr_df["timestamp"].dt.date
    next_df["date"] = next_df["timestamp"].dt.date
    curr_df = curr_df.groupby("date")["volume"].sum().reset_index()
    next_df = next_df.groupby("date")["volume"].sum().reset_index()

    merged = pd.merge(curr_df, next_df, on="date", suffixes=("_curr", "_next"))
    if merged.empty:
        if current_expiry:
            roll_date = current_expiry - timedelta(
                days=CALENDAR_ROLL_DAYS_BEFORE_EXPIRY
            )
            return roll_date, "calendar"
        return None

    crossover = merged[merged["volume_next"] > merged["volume_curr"]]
    if crossover.empty:
        if current_expiry:
            roll_date = current_expiry - timedelta(
                days=CALENDAR_ROLL_DAYS_BEFORE_EXPIRY
            )
            return roll_date, "calendar"
        return None

    roll_date = crossover.iloc[0]["date"]
    return roll_date, "volume"


def _build_time_slices(
    rollovers: List[FuturesRollover],
    first_contract: str,
) -> List[Tuple[Optional[datetime], Optional[datetime], str]]:
    """Convert rollover records into (start, end, contract_month) time slices."""
    if not rollovers:
        return [(None, None, first_contract)]

    slices = []
    prev_end = None
    current_contract = first_contract

    for rv in rollovers:
        roll_dt = datetime.combine(rv.roll_date, datetime.min.time())
        slices.append((prev_end, roll_dt, current_contract))
        current_contract = rv.to_contract
        prev_end = roll_dt

    slices.append((prev_end, None, current_contract))
    return slices
