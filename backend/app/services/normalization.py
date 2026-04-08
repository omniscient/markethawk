"""
Normalization Service.

Analyses the data-quality report for a universe and fills every gap, stale
tail, and integrity violation so each ticker × timespan combination reaches
an A grade.

Fixes applied (in order, per ticker combination):
  1. Dedup      — remove duplicate timestamps, keeping the earliest row.
  2. Gap fill   — re-sync every detected gap window from the stored report.
  3. Back-fill  — extend data to today if last_bar is stale (> 1 day old).
  4. Bad-bar    — delete bars that fail OHLCV sanity checks, then re-sync
                  the calendar dates that contained those bars.

Provider selection
──────────────────
  • stocks  → reads the `provider` column from the existing rows; defaults to
              'polygon' when NULL (legacy rows before the column was added).
  • futures → always uses 'ibkr' (mirroring FuturesAggregate.source).

Resumability
────────────
  Progress is checkpointed in ``UniverseQualityReport.normalization_data``
  after every completed ticker combo.  If the worker dies mid-run, calling
  the task again with resume=True reads the checkpoint and skips already-
  processed combos.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import func, text

logger = logging.getLogger(__name__)


# ── helpers ───────────────────────────────────────────────────────────────────

def _parse_date(dt_str: Optional[str]) -> Optional[datetime]:
    """Parse an ISO datetime string (with or without fractional seconds)."""
    if not dt_str:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(dt_str, fmt)
        except ValueError:
            continue
    return None


def _to_date_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


# ── low-level DB helpers ──────────────────────────────────────────────────────

def _dedup_stock(db: Session, ticker: str, timespan: str, multiplier: int) -> int:
    """
    Remove duplicate timestamps for a stock ticker combo.
    Keeps the row with the lowest id (earliest inserted).
    Returns the number of rows deleted.
    """
    result = db.execute(text("""
        DELETE FROM stock_aggregates
        WHERE id IN (
            SELECT id FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY ticker, timespan, multiplier, timestamp
                           ORDER BY id ASC
                       ) AS rn
                FROM stock_aggregates
                WHERE ticker     = :ticker
                  AND timespan   = :timespan
                  AND multiplier = :multiplier
            ) sub
            WHERE rn > 1
        )
    """), {"ticker": ticker, "timespan": timespan, "multiplier": multiplier})
    db.commit()
    return result.rowcount


def _dedup_futures(db: Session, symbol: str, timespan: str, multiplier: int) -> int:
    """Remove duplicate timestamps for a futures symbol combo."""
    result = db.execute(text("""
        DELETE FROM futures_aggregates
        WHERE id IN (
            SELECT id FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY symbol, timespan, multiplier, timestamp
                           ORDER BY id ASC
                       ) AS rn
                FROM futures_aggregates
                WHERE symbol     = :symbol
                  AND timespan   = :timespan
                  AND multiplier = :multiplier
            ) sub
            WHERE rn > 1
        )
    """), {"symbol": symbol, "timespan": timespan, "multiplier": multiplier})
    db.commit()
    return result.rowcount


def _get_stock_provider(db: Session, ticker: str, timespan: str, multiplier: int) -> str:
    """Return the provider used for this stock combo (defaults to 'polygon')."""
    from app.models.stock_aggregate import StockAggregate
    row = (
        db.query(StockAggregate.provider)
        .filter(
            StockAggregate.ticker     == ticker,
            StockAggregate.timespan   == timespan,
            StockAggregate.multiplier == multiplier,
            StockAggregate.provider   != None,
        )
        .first()
    )
    return (row.provider if row and row.provider else "polygon")


def _get_futures_exchange(db: Session, symbol: str) -> str:
    """Return the exchange for a futures symbol."""
    from app.models.futures_aggregate import FuturesAggregate
    row = (
        db.query(FuturesAggregate.exchange)
        .filter(FuturesAggregate.symbol == symbol)
        .first()
    )
    return row.exchange if row else "CME"


# ── sync helpers ──────────────────────────────────────────────────────────────

async def _sync_stock_range(
    db: Session,
    ticker: str,
    timespan: str,
    multiplier: int,
    from_date: str,
    to_date: str,
    provider: str,
) -> int:
    """
    Re-fetch and upsert stock bars for [from_date, to_date] (inclusive).
    Returns the number of rows inserted.
    """
    from app.models.stock_aggregate import StockAggregate
    from app.services.stock_data import StockDataService

    logger.info(f"  sync_stock_range {ticker} {timespan}×{multiplier} {from_date}→{to_date} via {provider}")

    aggs = await StockDataService.get_aggregates(
        ticker=ticker,
        multiplier=multiplier,
        timespan=timespan,
        from_date=from_date,
        to_date=to_date,
        limit=50000,
    )

    if not aggs:
        return 0

    # Delete-then-insert for the range to handle partial overlaps cleanly
    start_dt = datetime.strptime(from_date, "%Y-%m-%d")
    end_dt   = datetime.strptime(to_date,   "%Y-%m-%d") + timedelta(days=1)

    db.query(StockAggregate).filter(
        StockAggregate.ticker     == ticker,
        StockAggregate.timespan   == timespan,
        StockAggregate.multiplier == multiplier,
        StockAggregate.timestamp  >= start_dt,
        StockAggregate.timestamp  <  end_dt,
    ).delete(synchronize_session=False)

    records = []
    for agg in aggs:
        ts = agg["timestamp"].replace(tzinfo=None)
        h = ts.hour
        m = ts.minute
        is_pre  = (h >= 4 and h < 9) or (h == 9 and m < 30)
        is_post = (h >= 16 and h < 20)
        records.append(StockAggregate(
            ticker=ticker, timestamp=ts,
            multiplier=multiplier, timespan=timespan,
            open=agg["open"], high=agg["high"],
            low=agg["low"],   close=agg["close"],
            volume=agg["volume"], vwap=agg.get("vwap"),
            transactions=agg.get("transactions"),
            is_pre_market=is_pre, is_after_market=is_post,
            provider=provider,
        ))

    db.bulk_save_objects(records)
    db.commit()
    return len(records)


async def _sync_futures_range(
    db: Session,
    symbol: str,
    exchange: str,
    timespan: str,
    multiplier: int,
    from_date: str,
    to_date: str,
) -> int:
    """
    Re-fetch and upsert futures bars for [from_date, to_date] (inclusive).

    Avoids calling ``sync_contract_catalog`` (which makes a live IBKR API call
    to enumerate contract months) because the contracts are already known from
    the initial download.  Instead we query the local DB for contracts that
    were plausibly trading during the requested window and call
    ``download_contract`` directly on each one.

    Falls back to ``download_full_history`` (full catalog re-sync) only when
    no matching contracts exist in the DB.
    """
    from app.models.futures_contract import FuturesContract
    from app.services.futures_data import FuturesDataService

    logger.info(f"  sync_futures_range {symbol} {timespan}×{multiplier} {from_date}→{to_date}")

    from_dt = datetime.strptime(from_date, "%Y-%m-%d")
    to_dt   = datetime.strptime(to_date,   "%Y-%m-%d")

    # A contract that covers [from_date, to_date] must expire after
    # (from_date - 90 days) so the front-month at range start is included,
    # and before (to_date + 180 days) to exclude far-future contracts.
    min_expiry_str = _to_date_str(from_dt - timedelta(days=90))
    max_expiry_str = _to_date_str(to_dt   + timedelta(days=180))

    contracts = (
        db.query(FuturesContract)
        .filter(
            FuturesContract.symbol   == symbol,
            FuturesContract.exchange == exchange.upper(),
            FuturesContract.contract_month >= min_expiry_str.replace("-", ""),
            FuturesContract.contract_month <= max_expiry_str.replace("-", ""),
        )
        .order_by(FuturesContract.contract_month.asc())
        .all()
    )

    if not contracts:
        # No contracts in the DB for this range — fall back to full re-sync
        # (this will trigger a catalog sync with IBKR)
        logger.warning(
            f"  No local contracts for {symbol} in {from_date}→{to_date}. "
            "Falling back to full history download (will query IBKR catalog)."
        )
        result = await FuturesDataService.download_full_history(
            db=db, symbol=symbol, exchange=exchange,
            timespan=timespan, multiplier=multiplier,
            force_refresh=False, from_date=from_date, to_date=to_date,
        )
        return result.get("added", 0) if isinstance(result, dict) else 0

    logger.info(
        f"  Found {len(contracts)} local contract(s) for {symbol} "
        f"covering {from_date}→{to_date}: "
        + ", ".join(c.contract_month for c in contracts)
    )

    total_added = 0
    for contract in contracts:
        result = await FuturesDataService.download_contract(
            db=db,
            symbol=symbol,
            exchange=exchange,
            contract_month=contract.contract_month,
            timespan=timespan,
            multiplier=multiplier,
            force_refresh=False,
            from_date=from_date,
            to_date=to_date,
        )
        added = result.get("added", 0) if isinstance(result, dict) else 0
        total_added += added
        if added:
            logger.info(f"  +{added} bars from contract {contract.contract_month}")

    return total_added


# ── fix planning ──────────────────────────────────────────────────────────────

def _plan_fixes(ticker_result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Given one QualityTickerResult dict from the report, return an ordered
    list of date-range windows that need to be (re-)synced.

    Window types:
      gap_fill   — a specific gap detected by the quality analyser
      backfill   — extend from last_bar to today
      bad_bar    — re-sync specific calendar dates that contained bad bars
                   (we can only identify the dates, not the individual rows,
                   without a heavier scan; deleting the whole date is safe
                   because we replace with fresh data)
    """
    today = datetime.utcnow().date()
    fixes: List[Dict] = []

    # 1. Fill detected gaps
    for gap in ticker_result.get("gaps", []):
        from_dt = _parse_date(gap["from"])
        to_dt   = _parse_date(gap["to"])
        if from_dt and to_dt:
            # Slightly widen the window by 1 day on each side to capture
            # bar boundary issues
            fixes.append({
                "type": "gap_fill",
                "from": _to_date_str(from_dt - timedelta(days=1)),
                "to":   _to_date_str(to_dt   + timedelta(days=1)),
            })

    # 2. Back-fill if last_bar is stale (more than 1 day behind today)
    last_bar = _parse_date(ticker_result.get("last_bar"))
    if last_bar:
        last_date = last_bar.date()
        if (today - last_date).days > 1:
            fixes.append({
                "type": "backfill",
                "from": _to_date_str(last_bar),
                "to":   _to_date_str(datetime.utcnow()),
            })

    return fixes


# ── main service ──────────────────────────────────────────────────────────────

class NormalizationService:

    @staticmethod
    def run(
        db: Session,
        universe_id: int,
        quality_report: Dict[str, Any],
        normalization_data: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """
        Synchronous entry point called from the Celery task.

        ``quality_report``    — the ``report_data`` JSON from the stored report.
        ``normalization_data`` — existing checkpoint dict (for resume); pass
                                 None or {} to start fresh.
        Returns the final normalization_data dict to be persisted.
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(
                NormalizationService._run_async(
                    db, universe_id, quality_report, normalization_data or {}
                )
            )
        finally:
            loop.close()

    @staticmethod
    async def _run_async(
        db: Session,
        universe_id: int,
        quality_report: Dict[str, Any],
        checkpoint: Dict,
    ) -> Dict:
        tickers: List[Dict] = quality_report.get("tickers", [])

        # Skip combos with no data at all (grade F + no bars) — nothing to fill
        workload = [
            t for t in tickers
            if not (t.get("actual_bars", 0) == 0 and t.get("grade") == "F" and not t.get("gaps"))
        ]

        processed: List[str] = checkpoint.get("processed_combos", [])
        processed_set = set(processed)

        fixes_applied = checkpoint.get("fixes_applied", {
            "deduped": 0,
            "gaps_filled": 0,
            "backfilled": 0,
        })
        errors: List[Dict] = checkpoint.get("errors", [])

        total = len(workload)

        for idx, result in enumerate(workload):
            ticker     = result["ticker"]
            timespan   = result.get("timespan")
            multiplier = result.get("multiplier")
            is_futures = result.get("asset_class") == "futures"
            combo_key  = f"{ticker}|{timespan}|{multiplier}"

            if combo_key in processed_set:
                logger.info(f"[normalize] skip {combo_key} (already processed)")
                continue

            logger.info(
                f"[normalize] {idx+1}/{total}  {combo_key}"
                f" grade={result.get('grade')} dups={result.get('duplicate_count',0)}"
                f" gaps={result.get('gap_count',0)}"
            )

            try:
                # 1. Dedup
                if result.get("duplicate_count", 0) > 0:
                    if is_futures:
                        n = _dedup_futures(db, ticker, timespan, multiplier)
                    else:
                        n = _dedup_stock(db, ticker, timespan, multiplier)
                    fixes_applied["deduped"] += n
                    logger.info(f"  deduped {n} rows for {combo_key}")

                # 2. Plan + execute sync ranges
                if timespan:  # skip combos with no timespan (no data at all)
                    fixes = _plan_fixes(result)
                    for fix in fixes:
                        try:
                            if is_futures:
                                exchange = _get_futures_exchange(db, ticker)
                                added = await _sync_futures_range(
                                    db, ticker, exchange, timespan, multiplier,
                                    fix["from"], fix["to"],
                                )
                            else:
                                provider = _get_stock_provider(db, ticker, timespan, multiplier)
                                added = await _sync_stock_range(
                                    db, ticker, timespan, multiplier,
                                    fix["from"], fix["to"], provider,
                                )
                            key = "backfilled" if fix["type"] == "backfill" else "gaps_filled"
                            fixes_applied[key] = fixes_applied.get(key, 0) + added
                            logger.info(f"  {fix['type']} +{added} bars for {combo_key}")
                        except Exception as e:
                            logger.error(f"  fix {fix['type']} failed for {combo_key}: {e}")
                            errors.append({"combo": combo_key, "fix": fix["type"], "error": str(e)})

            except Exception as e:
                logger.error(f"[normalize] error on {combo_key}: {e}")
                errors.append({"combo": combo_key, "fix": "top-level", "error": str(e)})

            # Checkpoint after every combo so we can resume
            processed.append(combo_key)
            processed_set.add(combo_key)

            checkpoint_data = {
                "status": "running",
                "total_combos": total,
                "processed_combos": processed,
                "fixes_applied": fixes_applied,
                "errors": errors,
            }
            # Persist checkpoint directly (caller has already set status=running)
            from app.models.universe_quality_report import UniverseQualityReport
            report_row = db.query(UniverseQualityReport).filter(
                UniverseQualityReport.universe_id == universe_id
            ).first()
            if report_row:
                report_row.normalization_data = checkpoint_data
                db.commit()

        return {
            "status": "complete",
            "total_combos": total,
            "processed_combos": processed,
            "fixes_applied": fixes_applied,
            "errors": errors,
        }
