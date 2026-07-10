"""Futures bar download and gap-fill — extracted from FuturesDataService."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.futures_aggregate import FuturesAggregate
from app.models.futures_contract import FuturesContract
from app.providers import DataProviderFactory
from app.services.futures_contracts import MAX_HISTORY_YEARS, FuturesContractService
from app.services.futures_rollovers import FuturesRolloversService
from app.utils.time import ensure_utc

logger = logging.getLogger(__name__)


class FuturesAggregatesService:
    """Bar download and gap-fill — extracted from FuturesDataService."""

    @staticmethod
    async def _download_contract(
        db: Session,
        symbol: str,
        exchange: str,
        contract_month: str,
        timespan: str = "day",
        multiplier: int = 1,
        force_refresh: bool = False,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Download bars for a single contract month from IBKR and store them."""
        ibkr = DataProviderFactory.get("ibkr")
        available, reason = ibkr.is_available()
        if not available:
            return {
                "status": "error",
                "message": f"IBKR provider unavailable: {reason}",
            }

        catalog_entry = (
            db.query(FuturesContract)
            .filter(
                FuturesContract.symbol == symbol,
                FuturesContract.contract_month == contract_month,
            )
            .first()
        )

        targeted = bool(from_date or to_date)
        if (
            catalog_entry
            and catalog_entry.data_downloaded
            and not force_refresh
            and not targeted
        ):
            return {
                "status": "skipped",
                "message": f"{symbol} {contract_month} already downloaded",
                "added": 0,
            }

        logger.info(
            f"FuturesDataService: Downloading {symbol} {contract_month} "
            f"({timespan} bars) from IBKR..."
        )

        now = datetime.now(timezone.utc)
        try:
            expiry_dt = datetime.strptime(contract_month, "%Y%m%d").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            return {
                "status": "error",
                "message": f"Invalid contract_month: {contract_month}",
            }

        natural_to = min(expiry_dt, now)
        if to_date:
            caller_to = datetime.strptime(to_date, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            ) + timedelta(days=1, seconds=-1)
            effective_to = min(caller_to, natural_to)
        else:
            effective_to = natural_to
        to_date = effective_to.strftime("%Y-%m-%d")

        if from_date:
            from_date = from_date
        else:
            from_dt = now - timedelta(days=MAX_HISTORY_YEARS * 365)
            if expiry_dt < now:
                ibkr_limit = expiry_dt - timedelta(days=730)
                from_dt = max(from_dt, ibkr_limit)
            from_date = from_dt.strftime("%Y-%m-%d")

        bars = await ibkr.get_futures_bars(
            symbol=symbol,
            exchange=exchange,
            contract_month=contract_month,
            timespan=timespan,
            multiplier=multiplier,
            from_date=from_date,
            to_date=to_date,
        )

        if not bars:
            logger.warning(
                f"FuturesDataService: No bars returned for {symbol} {contract_month}"
            )
            return {
                "status": "success",
                "message": "No bars returned from IBKR",
                "added": 0,
            }

        existing_ts = set(
            r[0]
            for r in db.query(FuturesAggregate.timestamp)
            .filter(
                FuturesAggregate.symbol == symbol,
                FuturesAggregate.contract_month == contract_month,
                FuturesAggregate.timespan == timespan,
                FuturesAggregate.multiplier == multiplier,
            )
            .all()
        )

        BATCH_SIZE = 5000
        total_added = 0
        batch = []

        def _flush_batch():
            nonlocal total_added
            if batch:
                db.bulk_save_objects(batch)
                db.commit()
                total_added += len(batch)
                logger.info(
                    f"FuturesDataService: Committed {len(batch)} bars for "
                    f"{symbol} {contract_month} (total so far: {total_added})."
                )
                batch.clear()

        for bar in bars:
            ts = bar["timestamp"].replace(tzinfo=None)
            if ts in existing_ts:
                continue
            batch.append(
                FuturesAggregate(
                    symbol=symbol,
                    contract_month=contract_month,
                    exchange=exchange.upper(),
                    timestamp=ts,
                    timespan=timespan,
                    multiplier=multiplier,
                    open=bar["open"],
                    high=bar["high"],
                    low=bar["low"],
                    close=bar["close"],
                    volume=bar["volume"],
                    vwap=bar["vwap"],
                    transactions=bar["transactions"],
                    source="ibkr",
                )
            )
            existing_ts.add(ts)
            if len(batch) >= BATCH_SIZE:
                _flush_batch()

        _flush_batch()

        if catalog_entry:
            catalog_entry.data_downloaded = True
            if total_added:
                all_saved_ts = (
                    db.query(
                        func.min(FuturesAggregate.timestamp),
                        func.max(FuturesAggregate.timestamp),
                    )
                    .filter(
                        FuturesAggregate.symbol == symbol,
                        FuturesAggregate.contract_month == contract_month,
                    )
                    .first()
                )
                if all_saved_ts:
                    catalog_entry.first_bar_date = all_saved_ts[0]
                    catalog_entry.last_bar_date = all_saved_ts[1]
        else:
            db.add(
                FuturesContract(
                    symbol=symbol,
                    exchange=exchange.upper(),
                    contract_month=contract_month,
                    expiry_date=expiry_dt.date(),
                    is_expired=(expiry_dt < now),
                    data_downloaded=True,
                )
            )

        db.commit()

        logger.info(
            f"FuturesDataService: Saved {total_added} bars for {symbol} {contract_month}."
        )
        return {
            "status": "success",
            "symbol": symbol,
            "contract_month": contract_month,
            "added": total_added,
            "from_date": from_date,
            "to_date": to_date,
        }

    @staticmethod
    async def _download_full_history(
        db: Session,
        symbol: str,
        exchange: str,
        timespan: str = "day",
        multiplier: int = 1,
        force_refresh: bool = False,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        progress_callback=None,
    ) -> Dict[str, Any]:
        """Download the complete available history for a futures symbol from IBKR."""
        logger.info(
            f"FuturesDataService: Starting full history download for "
            f"{symbol} ({exchange}) — {timespan} bars."
        )

        await FuturesContractService._sync_contract_catalog(db, symbol, exchange)

        contracts = (
            db.query(FuturesContract)
            .filter(
                FuturesContract.symbol == symbol,
                FuturesContract.exchange == exchange.upper(),
            )
            .order_by(FuturesContract.contract_month.asc())
            .all()
        )

        if not contracts:
            return {
                "status": "error",
                "message": f"No contracts found for {symbol} on {exchange}",
            }

        if from_date:
            now_utc = datetime.now(timezone.utc)
            from_dt_filter = datetime.strptime(from_date, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
            to_dt_filter = (
                ensure_utc(datetime.strptime(to_date, "%Y-%m-%d"))
                if to_date
                else now_utc
            )
            min_expiry = from_dt_filter - timedelta(days=90)
            max_expiry = to_dt_filter + timedelta(days=180)

            contracts = [
                c
                for c in contracts
                if (
                    datetime.strptime(c.contract_month, "%Y%m%d").replace(
                        tzinfo=timezone.utc
                    )
                    >= min_expiry
                    and datetime.strptime(c.contract_month, "%Y%m%d").replace(
                        tzinfo=timezone.utc
                    )
                    <= max_expiry
                )
            ]
            logger.info(
                f"FuturesDataService: {len(contracts)} contract(s) in window "
                f"{from_date} → {to_date or 'now'} (after date filter)."
            )

        if not contracts:
            return {
                "status": "error",
                "message": f"No contracts for {symbol} overlap the requested date range.",
            }

        total = len(contracts)
        results = []

        for idx, contract in enumerate(contracts):
            cm = contract.contract_month
            logger.info(
                f"FuturesDataService: [{idx + 1}/{total}] Downloading {symbol} {cm}..."
            )

            result = await FuturesAggregatesService._download_contract(
                db=db,
                symbol=symbol,
                exchange=exchange,
                contract_month=cm,
                timespan=timespan,
                multiplier=multiplier,
                force_refresh=force_refresh,
                from_date=from_date,
                to_date=to_date,
            )
            results.append(result)

            if progress_callback:
                progress_callback(cm, idx + 1, total)

        logger.info(f"FuturesDataService: Detecting rollovers for {symbol}...")
        rollover_count = await FuturesRolloversService._detect_rollovers(
            db=db,
            symbol=symbol,
            exchange=exchange,
            timespan=timespan,
            multiplier=multiplier,
        )

        gap_result = await FuturesAggregatesService._fill_data_gaps(
            db=db,
            symbol=symbol,
            exchange=exchange,
            timespan=timespan,
            multiplier=multiplier,
            from_date=from_date,
            to_date=to_date,
        )

        total_added = sum(r.get("added", 0) for r in results) + gap_result.get(
            "bars_added", 0
        )
        total_skipped = sum(1 for r in results if r.get("status") == "skipped")
        total_errors = sum(1 for r in results if r.get("status") == "error")

        summary = {
            "status": "success",
            "symbol": symbol,
            "exchange": exchange,
            "contracts_processed": total,
            "contracts_skipped": total_skipped,
            "contracts_with_errors": total_errors,
            "bars_added": total_added,
            "rollovers_detected": rollover_count,
            "gaps_found": gap_result.get("gaps_found", 0),
            "gaps_filled": gap_result.get("gaps_filled", 0),
        }
        logger.info(f"FuturesDataService: Full download complete. {summary}")
        return summary

    @staticmethod
    async def _fill_data_gaps(
        db: Session,
        symbol: str,
        exchange: str,
        timespan: str = "minute",
        multiplier: int = 1,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        min_gap_hours: int = 80,
    ) -> Dict[str, Any]:
        """Scan for time gaps in stored bars and attempt to fill them."""
        base_query = db.query(
            FuturesAggregate.timestamp, FuturesAggregate.contract_month
        ).filter(
            FuturesAggregate.symbol == symbol,
            FuturesAggregate.timespan == timespan,
            FuturesAggregate.multiplier == multiplier,
        )
        if from_date:
            base_query = base_query.filter(
                FuturesAggregate.timestamp >= datetime.strptime(from_date, "%Y-%m-%d")
            )
        if to_date:
            base_query = base_query.filter(
                FuturesAggregate.timestamp <= datetime.strptime(to_date, "%Y-%m-%d")
            )

        rows = base_query.order_by(FuturesAggregate.timestamp.asc()).all()

        if len(rows) < 2:
            return {"gaps_found": 0, "gaps_filled": 0, "bars_added": 0}

        gaps: List[Tuple[datetime, datetime]] = []
        for i in range(1, len(rows)):
            delta = rows[i][0] - rows[i - 1][0]
            if delta.total_seconds() > min_gap_hours * 3600:
                gaps.append((rows[i - 1][0], rows[i][0]))

        if not gaps:
            return {"gaps_found": 0, "gaps_filled": 0, "bars_added": 0}

        logger.info(
            f"FuturesDataService: {len(gaps)} gap(s) detected for {symbol} "
            f"({timespan}×{multiplier}) — attempting to fill..."
        )

        all_contracts = (
            db.query(FuturesContract)
            .filter(FuturesContract.symbol == symbol)
            .order_by(FuturesContract.contract_month.asc())
            .all()
        )

        total_added = 0
        gaps_filled = 0

        for gap_start, gap_end in gaps:
            gap_start_str = gap_start.strftime("%Y-%m-%d")
            gap_end_str = gap_end.strftime("%Y-%m-%d")
            logger.info(
                f"FuturesDataService: Filling gap {gap_start_str} → {gap_end_str} "
                f"({(gap_end - gap_start).days}d) for {symbol}..."
            )

            candidates = sorted(
                [
                    c
                    for c in all_contracts
                    if datetime.strptime(c.contract_month, "%Y%m%d") >= gap_start
                ],
                key=lambda c: c.contract_month,
            )[:3]

            just_expired = sorted(
                [
                    c
                    for c in all_contracts
                    if datetime.strptime(c.contract_month, "%Y%m%d") < gap_start
                ],
                key=lambda c: c.contract_month,
                reverse=True,
            )[:1]

            for contract in candidates + just_expired:
                result = await FuturesAggregatesService._download_contract(
                    db=db,
                    symbol=symbol,
                    exchange=exchange,
                    contract_month=contract.contract_month,
                    timespan=timespan,
                    multiplier=multiplier,
                    force_refresh=False,
                    from_date=gap_start_str,
                    to_date=gap_end_str,
                )
                added = result.get("added", 0)
                if added > 0:
                    total_added += added
                    gaps_filled += 1
                    logger.info(
                        f"FuturesDataService: Gap filled using {contract.contract_month}: "
                        f"added {added} bars."
                    )
                    break
            else:
                logger.warning(
                    f"FuturesDataService: Could not fill gap {gap_start_str} → "
                    f"{gap_end_str} — no contract had data for this window."
                )

        return {
            "gaps_found": len(gaps),
            "gaps_filled": gaps_filled,
            "bars_added": total_added,
        }
