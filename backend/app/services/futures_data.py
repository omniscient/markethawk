"""
Futures Data Service.

Orchestrates the download of historical futures data from IBKR, handles
the rollover logic, and assembles continuous price series for consumption
by the rest of the application.

Rollover strategy: VOLUME-BASED
  On each date where both the expiring contract and the successor contract
  have bars, we compare volumes.  The first date on which the successor's
  volume exceeds the expiring contract's volume becomes the roll_date.
  If no crossover is found within the two-contract overlap window, we fall
  back to a calendar rule (N days before expiry).

Continuous series assembly (read path):
  1. Load rollover records for the symbol (ordered ascending by roll_date).
  2. Build a time-slice map:  each slice [from_date, to_date) maps to a
     specific contract_month.
  3. For each slice, load bars from FuturesAggregate and concatenate them.
  4. Return a single sorted DataFrame labelled with the root symbol.
"""

import asyncio
import logging
from datetime import datetime, date, timedelta, timezone
from typing import Dict, Any, List, Optional, Tuple

import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.config import settings
from app.models.futures_aggregate import FuturesAggregate
from app.models.futures_rollover import FuturesRollover
from app.models.futures_contract import FuturesContract
from app.providers import DataProviderFactory

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Maximum historical lookback (years)
MAX_HISTORY_YEARS = 10

# Calendar fallback: roll N days before expiry when volume crossover not found
CALENDAR_ROLL_DAYS_BEFORE_EXPIRY = 8

# Exchanges for common symbols — used for display / defaults
SYMBOL_EXCHANGE_MAP = {
    "ES": "CME",
    "NQ": "CME",
    "MES": "CME",
    "MNQ": "CME",
    "RTY": "CME",
    "GC": "COMEX",
    "SI": "COMEX",
    "CL": "NYMEX",
    "NG": "NYMEX",
    "ZB": "CBOT",
    "ZN": "CBOT",
    "ZF": "CBOT",
}


# ---------------------------------------------------------------------------
# FuturesDataService
# ---------------------------------------------------------------------------

class FuturesDataService:
    """
    High-level service for futures data management.

    All methods that talk to IBKR are async because ib_insync is async-based.
    DB operations use synchronous SQLAlchemy sessions (standard for FastAPI).
    """

    # ------------------------------------------------------------------ #
    #  Contract Catalog                                                    #
    # ------------------------------------------------------------------ #

    @staticmethod
    async def sync_contract_catalog(
        db: Session,
        symbol: str,
        exchange: str,
    ) -> List[Dict[str, Any]]:
        """
        Query IBKR for all contract months (including expired) and cache them
        in the futures_contracts table.

        Returns the list of contracts found.
        """
        ibkr = DataProviderFactory.get("ibkr")
        available, reason = ibkr.is_available()
        if not available:
            raise RuntimeError(f"IBKR provider is not available: {reason}")

        logger.info(f"FuturesDataService: Syncing contract catalog for {symbol} ({exchange})...")
        contracts = await ibkr.get_futures_contracts(
            symbol=symbol,
            exchange=exchange,
            include_expired=True,
        )

        if not contracts:
            raise RuntimeError(
                f"IBKR returned no contracts for {symbol} on {exchange}. "
                "TWS may be unreachable or the symbol/exchange is incorrect."
            )

        # Apply 10-year limit
        cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_HISTORY_YEARS * 365)

        saved = 0
        for c in contracts:
            # Skip contracts too old to have usable data
            try:
                expiry_dt = datetime.strptime(c["contract_month"], "%Y%m%d").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                continue

            if expiry_dt < cutoff:
                continue

            existing = (
                db.query(FuturesContract)
                .filter(
                    FuturesContract.symbol == symbol,
                    FuturesContract.contract_month == c["contract_month"],
                )
                .first()
            )

            if not existing:
                rec = FuturesContract(
                    symbol=symbol,
                    exchange=exchange.upper(),
                    contract_month=c["contract_month"],
                    expiry_date=datetime.strptime(c["contract_month"], "%Y%m%d").date(),
                    con_id=c.get("con_id"),
                    is_expired=c.get("is_expired", False),
                )
                db.add(rec)
                saved += 1
            else:
                # Update con_id and expiry status in case it changed
                existing.con_id = c.get("con_id") or existing.con_id
                existing.is_expired = c.get("is_expired", existing.is_expired)

        db.commit()
        logger.info(
            f"FuturesDataService: Saved {saved} new contracts for {symbol}. "
            f"Total in catalog: {len(contracts)}."
        )
        return contracts

    # ------------------------------------------------------------------ #
    #  Download                                                            #
    # ------------------------------------------------------------------ #

    @staticmethod
    async def download_contract(
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
        """
        Download bars for a single contract month from IBKR and store them.

        Returns a status dict with counts.
        """
        ibkr = DataProviderFactory.get("ibkr")
        available, reason = ibkr.is_available()
        if not available:
            return {"status": "error", "message": f"IBKR provider unavailable: {reason}"}

        # Check if already downloaded (unless forced)
        catalog_entry = (
            db.query(FuturesContract)
            .filter(
                FuturesContract.symbol == symbol,
                FuturesContract.contract_month == contract_month,
            )
            .first()
        )

        # Skip only on full-history runs where the contract is already fully downloaded.
        # When a specific date range is requested we always re-fetch that window so
        # that incremental syncs pick up bars added since the last full download.
        targeted = bool(from_date or to_date)
        if catalog_entry and catalog_entry.data_downloaded and not force_refresh and not targeted:
            return {
                "status": "skipped",
                "message": f"{symbol} {contract_month} already downloaded",
                "added": 0,
            }

        logger.info(
            f"FuturesDataService: Downloading {symbol} {contract_month} "
            f"({timespan} bars) from IBKR..."
        )

        # Determine date range to fetch
        now = datetime.now(timezone.utc)
        try:
            expiry_dt = datetime.strptime(contract_month, "%Y%m%d").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            return {"status": "error", "message": f"Invalid contract_month: {contract_month}"}

        # Upper bound: caller override, capped at min(expiry, now)
        natural_to = min(expiry_dt, now)
        if to_date:
            caller_to = datetime.strptime(to_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            effective_to = min(caller_to, natural_to)
        else:
            effective_to = natural_to
        to_date = effective_to.strftime("%Y-%m-%d")

        # Lower bound: caller override, or full lookback capped by IBKR's 2-year limit
        if from_date:
            from_date = from_date  # use as-is; caller is responsible for reasonable range
        else:
            from_dt = now - timedelta(days=MAX_HISTORY_YEARS * 365)
            if expiry_dt < now:
                ibkr_limit = expiry_dt - timedelta(days=730)
                from_dt = max(from_dt, ibkr_limit)
            from_date = from_dt.strftime("%Y-%m-%d")

        # Fetch from IBKR
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

        # Load existing timestamps once for deduplication
        existing_ts = set(
            r[0]
            for r in db.query(FuturesAggregate.timestamp).filter(
                FuturesAggregate.symbol == symbol,
                FuturesAggregate.contract_month == contract_month,
                FuturesAggregate.timespan == timespan,
                FuturesAggregate.multiplier == multiplier,
            ).all()
        )

        # Insert in batches of 5000 to preserve progress on large downloads
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

        _flush_batch()  # flush remainder

        # Update catalog entry
        if catalog_entry:
            catalog_entry.data_downloaded = True
            if total_added:
                all_saved_ts = (
                    db.query(func.min(FuturesAggregate.timestamp), func.max(FuturesAggregate.timestamp))
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
            db.add(FuturesContract(
                symbol=symbol,
                exchange=exchange.upper(),
                contract_month=contract_month,
                expiry_date=expiry_dt.date(),
                is_expired=(expiry_dt < now),
                data_downloaded=True,
            ))

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
    async def download_full_history(
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
        """
        Download the complete available history for a futures symbol from IBKR.

        Steps:
          1. Sync contract catalog (get all contract months from IBKR).
          2. Download bars for each contract month (oldest first, respecting
             IBKR pacing via the provider's built-in guard).
          3. Detect rollovers and store them.

        Args:
            progress_callback:  Optional callable(contract_month, done, total)
                                for CLI progress reporting.
        """
        logger.info(
            f"FuturesDataService: Starting full history download for "
            f"{symbol} ({exchange}) — {timespan} bars."
        )

        # Step 1: Build contract catalog
        await FuturesDataService.sync_contract_catalog(db, symbol, exchange)

        # Step 2: Get all catalog entries in chronological order
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

        # When a date range is requested keep contracts that were plausibly
        # trading during it:
        #   • Expiry >= from_date - 90 days  (covers the front-month at range start)
        #   • Expiry <= to_date + 180 days   (excludes far-future contracts)
        # The -90 day look-back ensures we don't miss the contract that was the
        # front-month at the very beginning of the requested range.
        if from_date:
            now_utc = datetime.now(timezone.utc)
            from_dt_filter = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            to_dt_filter = (
                datetime.strptime(to_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                if to_date else now_utc
            )
            min_expiry = from_dt_filter - timedelta(days=90)
            max_expiry = to_dt_filter + timedelta(days=180)

            contracts = [
                c for c in contracts
                if (
                    datetime.strptime(c.contract_month, "%Y%m%d").replace(tzinfo=timezone.utc)
                    >= min_expiry
                    and
                    datetime.strptime(c.contract_month, "%Y%m%d").replace(tzinfo=timezone.utc)
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
                f"FuturesDataService: [{idx+1}/{total}] Downloading {symbol} {cm}..."
            )

            result = await FuturesDataService.download_contract(
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

        # Step 3: Detect and store rollovers
        logger.info(
            f"FuturesDataService: Detecting rollovers for {symbol}..."
        )
        rollover_count = await FuturesDataService.detect_rollovers(
            db=db,
            symbol=symbol,
            exchange=exchange,
            timespan=timespan,
            multiplier=multiplier,
        )

        # Step 4: Gap-fill pass — re-download any holes left by truncated downloads
        # or back-month contracts with limited IBKR history.
        gap_result = await FuturesDataService.fill_data_gaps(
            db=db,
            symbol=symbol,
            exchange=exchange,
            timespan=timespan,
            multiplier=multiplier,
            from_date=from_date,
            to_date=to_date,
        )

        total_added = sum(r.get("added", 0) for r in results) + gap_result.get("bars_added", 0)
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

    # ------------------------------------------------------------------ #
    #  Gap Detection & Fill                                                #
    # ------------------------------------------------------------------ #

    @staticmethod
    async def fill_data_gaps(
        db: Session,
        symbol: str,
        exchange: str,
        timespan: str = "minute",
        multiplier: int = 1,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        min_gap_hours: int = 80,
    ) -> Dict[str, Any]:
        """
        Scan for time gaps in stored bars and attempt to fill them by
        re-downloading the gap period from whichever contract covers it.

        Strategy for each gap [gap_start, gap_end]:
          1. Try every contract whose expiry falls WITHIN the gap window
             (i.e., it was the front-month during that period).
          2. Also try the contract that expired just before the gap — it may
             still have late-life bars for the period.
          3. Stop as soon as any contract yields new bars for that window.

        min_gap_hours: gaps shorter than this are ignored.
          NQ trades ~23 h/day Sun–Fri with a ~1 h maintenance break, so
          80 h (≈3.5 days) safely skips weekends without false positives.
        """
        base_query = (
            db.query(FuturesAggregate.timestamp, FuturesAggregate.contract_month)
            .filter(
                FuturesAggregate.symbol == symbol,
                FuturesAggregate.timespan == timespan,
                FuturesAggregate.multiplier == multiplier,
            )
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

        # Detect gaps
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

        # Load all known contracts for this symbol, sorted chronologically
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
            gap_end_str   = gap_end.strftime("%Y-%m-%d")
            logger.info(
                f"FuturesDataService: Filling gap {gap_start_str} → {gap_end_str} "
                f"({(gap_end - gap_start).days}d) for {symbol}..."
            )

            # Build ordered candidate list:
            #   • Contracts that expire during or after the gap start
            #     (front-month or next-month at that time), nearest first
            #   • Followed by the contract that expired just before the gap
            #     (may still have late-life bars right up to its expiry)
            candidates = sorted(
                [c for c in all_contracts
                 if datetime.strptime(c.contract_month, "%Y%m%d") >= gap_start],
                key=lambda c: c.contract_month,
            )[:3]

            just_expired = sorted(
                [c for c in all_contracts
                 if datetime.strptime(c.contract_month, "%Y%m%d") < gap_start],
                key=lambda c: c.contract_month,
                reverse=True,
            )[:1]

            for contract in (candidates + just_expired):
                result = await FuturesDataService.download_contract(
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

    # ------------------------------------------------------------------ #
    #  Rollover Detection                                                  #
    # ------------------------------------------------------------------ #

    @staticmethod
    async def detect_rollovers(
        db: Session,
        symbol: str,
        exchange: str,
        timespan: str = "day",
        multiplier: int = 1,
    ) -> int:
        """
        Analyse downloaded bar data and detect volume-crossover rollover dates.

        For each consecutive pair of contract months with overlapping bar data:
          - Find the first date where next_contract.volume > current_contract.volume
          - Record this as the roll_date in futures_rollovers

        Returns the number of rollover records created/updated.
        """
        # Load all contracts in order
        contracts = (
            db.query(FuturesContract)
            .filter(
                FuturesContract.symbol == symbol,
                FuturesContract.exchange == exchange.upper(),
                FuturesContract.data_downloaded == True,
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

            # Upsert rollover record
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

    # ------------------------------------------------------------------ #
    #  Continuous Series Assembly                                          #
    # ------------------------------------------------------------------ #

    @staticmethod
    def get_continuous_series(
        db: Session,
        symbol: str,
        timespan: str = "day",
        multiplier: int = 1,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Assemble and return a continuous (stitched) price series for a futures symbol.

        The returned DataFrame has columns:
            timestamp, open, high, low, close, volume, vwap, contract_month

        The 'contract_month' column tells you which underlying contract each
        bar came from  — useful for debugging or displaying rollover points.
        """
        # 1. Load rollover table for this symbol
        rollovers = (
            db.query(FuturesRollover)
            .filter(FuturesRollover.symbol == symbol)
            .order_by(FuturesRollover.roll_date.asc())
            .all()
        )

        # 2. Find the oldest contract with data
        oldest_contract = (
            db.query(FuturesContract)
            .filter(
                FuturesContract.symbol == symbol,
                FuturesContract.data_downloaded == True,
            )
            .order_by(FuturesContract.contract_month.asc())
            .first()
        )

        if not oldest_contract:
            return pd.DataFrame()

        # 3. Build time slices: [(start_date, end_date, contract_month), ...]
        slices = _build_time_slices(
            rollovers=rollovers,
            first_contract=oldest_contract.contract_month,
        )

        # 4. Apply date filters
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

        # 5. Fetch and concatenate bars for each slice
        frames = []
        for slice_start, slice_end, contract_month in slices:
            query = db.query(FuturesAggregate).filter(
                FuturesAggregate.symbol == symbol,
                FuturesAggregate.contract_month == contract_month,
                FuturesAggregate.timespan == timespan,
                FuturesAggregate.multiplier == multiplier,
            )
            if slice_start:
                query = query.filter(FuturesAggregate.timestamp >= slice_start)
            if slice_end:
                query = query.filter(FuturesAggregate.timestamp < slice_end)
            if from_dt:
                query = query.filter(FuturesAggregate.timestamp >= from_dt)
            if to_dt:
                query = query.filter(FuturesAggregate.timestamp <= to_dt)

            rows = query.order_by(FuturesAggregate.timestamp.asc()).all()
            if not rows:
                continue

            chunk = pd.DataFrame(
                [
                    {
                        "timestamp": r.timestamp,
                        "open": float(r.open),
                        "high": float(r.high),
                        "low": float(r.low),
                        "close": float(r.close),
                        "volume": int(r.volume),
                        "vwap": float(r.vwap) if r.vwap else None,
                        "contract_month": r.contract_month,
                    }
                    for r in rows
                ]
            )
            frames.append(chunk)

        if not frames:
            return pd.DataFrame()

        df = pd.concat(frames, ignore_index=True)
        df.sort_values("timestamp", inplace=True)
        df.drop_duplicates(subset=["timestamp"], keep="last", inplace=True)
        df.reset_index(drop=True, inplace=True)
        return df

    # ------------------------------------------------------------------ #
    #  Convenience / Info                                                  #
    # ------------------------------------------------------------------ #

    @staticmethod
    def get_contracts(db: Session, symbol: str) -> List[Dict[str, Any]]:
        """Return all known contracts for a symbol with their download status."""
        contracts = (
            db.query(FuturesContract)
            .filter(FuturesContract.symbol == symbol)
            .order_by(FuturesContract.contract_month.asc())
            .all()
        )
        return [
            {
                "symbol": c.symbol,
                "exchange": c.exchange,
                "contract_month": c.contract_month,
                "expiry_date": c.expiry_date.isoformat() if c.expiry_date else None,
                "con_id": c.con_id,
                "is_expired": c.is_expired,
                "data_downloaded": c.data_downloaded,
                "first_bar_date": c.first_bar_date.isoformat() if c.first_bar_date else None,
                "last_bar_date": c.last_bar_date.isoformat() if c.last_bar_date else None,
            }
            for c in contracts
        ]

    @staticmethod
    def get_rollovers(db: Session, symbol: str) -> List[Dict[str, Any]]:
        """Return all detected rollover events for a symbol."""
        rollovers = (
            db.query(FuturesRollover)
            .filter(FuturesRollover.symbol == symbol)
            .order_by(FuturesRollover.roll_date.asc())
            .all()
        )
        return [
            {
                "symbol": r.symbol,
                "from_contract": r.from_contract,
                "to_contract": r.to_contract,
                "roll_date": r.roll_date.isoformat() if r.roll_date else None,
                "detection_method": r.detection_method,
            }
            for r in rollovers
        ]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

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
    """
    Determine the roll date between two consecutive contract months.

    Returns (roll_date, detection_method) or None if insufficient data.
    """
    # Load bars for both contracts in the overlap period
    # The overlap is typically 2–4 weeks before the current contract expires
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
        # Fall back to calendar rule
        if current_expiry:
            roll_date = current_expiry - timedelta(days=CALENDAR_ROLL_DAYS_BEFORE_EXPIRY)
            return roll_date, "calendar"
        return None

    # Merge on date (truncate to date for comparison)
    curr_df["date"] = curr_df["timestamp"].dt.date
    next_df["date"] = next_df["timestamp"].dt.date
    curr_df = curr_df.groupby("date")["volume"].sum().reset_index()
    next_df = next_df.groupby("date")["volume"].sum().reset_index()

    merged = pd.merge(curr_df, next_df, on="date", suffixes=("_curr", "_next"))
    if merged.empty:
        if current_expiry:
            roll_date = current_expiry - timedelta(days=CALENDAR_ROLL_DAYS_BEFORE_EXPIRY)
            return roll_date, "calendar"
        return None

    # Find first date where next volume > current volume
    crossover = merged[merged["volume_next"] > merged["volume_curr"]]
    if crossover.empty:
        # No crossover found — use calendar rule
        if current_expiry:
            roll_date = current_expiry - timedelta(days=CALENDAR_ROLL_DAYS_BEFORE_EXPIRY)
            return roll_date, "calendar"
        return None

    roll_date = crossover.iloc[0]["date"]
    return roll_date, "volume"


def _build_time_slices(
    rollovers: List[FuturesRollover],
    first_contract: str,
) -> List[Tuple[Optional[datetime], Optional[datetime], str]]:
    """
    Convert rollover records into (start, end, contract_month) time slices.

    Example output for ES with 3 contracts H25→M25→U25 rolling on 3/10 and 6/9:
        (None,              2025-03-10,  "20250321")  ← H25 used until roll
        (2025-03-10,        2025-06-09,  "20250620")  ← M25 from roll to next roll
        (2025-06-09,        None,        "20250919")  ← U25 from roll onwards
    """
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

    # Final slice: from the last roll to "now"
    slices.append((prev_end, None, current_contract))
    return slices
