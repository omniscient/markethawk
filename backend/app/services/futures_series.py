"""Continuous futures series assembly — extracted from FuturesDataService."""

import logging
from datetime import datetime
from typing import Optional

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.futures_contract import FuturesContract
from app.models.futures_rollover import FuturesRollover
from app.services.futures_rollovers import _build_time_slices

logger = logging.getLogger(__name__)


class FutureSeriesService:
    """Continuous series assembly — extracted from FuturesDataService."""

    @staticmethod
    def get_continuous_series(
        symbol: str,
        timespan: str = "day",
        multiplier: int = 1,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """Assemble and return a continuous (stitched) price series for a futures symbol."""
        db = SessionLocal()
        try:
            return FutureSeriesService._get_continuous_series_with_db(
                db=db,
                symbol=symbol,
                timespan=timespan,
                multiplier=multiplier,
                from_date=from_date,
                to_date=to_date,
            )
        finally:
            db.close()

    @staticmethod
    def _get_continuous_series_with_db(
        db: Session,
        symbol: str,
        timespan: str = "day",
        multiplier: int = 1,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """Internal implementation of continuous series assembly."""
        rollovers = (
            db.query(FuturesRollover)
            .filter(FuturesRollover.symbol == symbol)
            .order_by(FuturesRollover.roll_date.asc())
            .all()
        )

        oldest_contract = (
            db.query(FuturesContract)
            .filter(
                FuturesContract.symbol == symbol,
                FuturesContract.data_downloaded == True,  # noqa: E712
            )
            .order_by(FuturesContract.contract_month.asc())
            .first()
        )

        if not oldest_contract:
            return pd.DataFrame()

        slices = _build_time_slices(
            rollovers=rollovers,
            first_contract=oldest_contract.contract_month,
        )

        from_dt = (
            datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=None)
            if from_date
            else None
        )
        to_dt = (
            datetime.strptime(to_date, "%Y-%m-%d").replace(tzinfo=None)
            if to_date
            else None
        )

        frames = []
        for slice_start, slice_end, contract_month in slices:
            ts_start = max(filter(None, [slice_start, from_dt]), default=None)
            ts_end = (
                min(filter(None, [slice_end, to_dt]), default=None)
                if (slice_end or to_dt)
                else None
            )

            params: dict = {
                "symbol": symbol,
                "contract_month": contract_month,
                "timespan": timespan,
                "multiplier": multiplier,
            }
            clauses = [
                "symbol = :symbol",
                "contract_month = :contract_month",
                "timespan = :timespan",
                "multiplier = :multiplier",
            ]
            if ts_start:
                clauses.append("timestamp >= :ts_start")
                params["ts_start"] = ts_start
            if ts_end:
                clauses.append("timestamp < :ts_end")
                params["ts_end"] = ts_end

            sql = text(
                f"SELECT timestamp, open, high, low, close, volume, vwap "
                f"FROM futures_aggregates WHERE {' AND '.join(clauses)} "
                f"ORDER BY timestamp ASC"
            )
            rows = db.execute(sql, params).fetchall()
            if not rows:
                continue

            chunk = pd.DataFrame(
                rows,
                columns=["timestamp", "open", "high", "low", "close", "volume", "vwap"],
            )
            chunk["contract_month"] = contract_month
            frames.append(chunk)

        if not frames:
            return pd.DataFrame()

        df = pd.concat(frames, ignore_index=True)

        if len(frames) > 1:
            df.sort_values("timestamp", inplace=True)
            df.drop_duplicates(subset=["timestamp"], keep="last", inplace=True)
            df.reset_index(drop=True, inplace=True)

        return df
