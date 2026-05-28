"""
Orchestration logic for universe operations: Celery task dispatch,
Redis state management, and multi-service coordination.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import redis as redis_lib
from celery.result import AsyncResult
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.celery_app import celery_app
from app.core.config import settings
from app.exceptions import UniverseNotFoundError, UniverseValidationError
from app.models import MonitoredStock, StockUniverse, StockUniverseTicker
from app.models.futures_aggregate import FuturesAggregate
from app.models.stock_aggregate import StockAggregate
from app.models.universe_quality_report import UniverseQualityReport
from app.services.universe_stats import UniverseStatsService
from app.utils.session import get_market_today

logger = logging.getLogger(__name__)

# Celery task and SYMBOL_EXCHANGE_MAP imports are lazy (inside function bodies)
# to prevent circular imports — tasks.py imports from app.services at module level,
# so cross-importing at module level is risky.


def discover_and_refresh(universe_id: int, db: Session) -> dict:
    """
    Refresh stocks in a universe using the Universe Discovery Engine.
    Clears MonitoredStock + StockUniverseTicker, runs DiscoveryService.run_screen(),
    bulk-inserts results, refreshes cached stats.
    Raises UniverseNotFoundError if the universe does not exist.
    """
    from app.services.discovery_service import DiscoveryService

    universe = db.query(StockUniverse).filter(StockUniverse.id == universe_id).first()
    if not universe:
        raise UniverseNotFoundError(universe_id)

    db.query(MonitoredStock).filter(MonitoredStock.universe_id == universe_id).delete()
    db.query(StockUniverseTicker).filter(
        StockUniverseTicker.universe_id == universe_id
    ).delete()

    service = DiscoveryService(db)
    criteria = universe.criteria or {}
    results = service.run_screen(criteria)

    added_count = 0
    for res in results:
        monitored_stock = MonitoredStock(
            ticker=res["ticker"],
            universe_id=universe_id,
            added_date=get_market_today(),
            is_active=True,
            asset_class=res.get("asset_class", "stocks"),
            data_source=res.get("data_source", "massive"),
            company_name=res["name"],
            sector=res["sector"],
            market_cap=res["market_cap"],
            stock_metadata={
                "source": "discovery_engine",
                "close_price": res["close_price"],
                "volume": res["volume"],
                "primary_exchange": res.get("primary_exchange"),
                "employees": res.get("employees"),
                "sic_code": res.get("sic_code"),
                "description_preview": (res.get("description") or "")[:100] + "..."
                if res.get("description")
                else None,
            },
        )
        db.add(monitored_stock)

        stock_ticker = StockUniverseTicker(
            universe_id=universe_id,
            ticker=res["ticker"],
            asset_class=res.get("asset_class", "stocks"),
            data_source=res.get("data_source", "massive"),
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(stock_ticker)
        added_count += 1

    db.commit()

    stats = UniverseStatsService.compute(universe_id, db)
    universe.cached_ticker_count = stats["ticker_count"]
    universe.cached_aggregate_count = stats["aggregate_count"]
    universe.cached_min_date = stats["min_date"]
    universe.cached_max_date = stats["max_date"]
    universe.cached_timespans = stats["timespans"]
    universe.stats_refreshed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()

    return {
        "status": "completed",
        "scanned": "ALL",
        "added": added_count,
        "message": f"Successfully refreshed universe. Added {added_count} assets from Discovery Engine.",
    }


def sync_missing_aggregates(universe_id: int, db: Session) -> dict:
    """
    For every (timespan, multiplier) already recorded in this universe,
    queue a sync from the last stored bar up to today.
    Writes task IDs to Redis universe:{id}:sync key (4-hour TTL).
    """
    from app.services.futures_data import SYMBOL_EXCHANGE_MAP
    from app.tasks import sync_futures_aggregates, sync_stock_aggregates

    stocks = (
        db.query(MonitoredStock)
        .filter(
            MonitoredStock.universe_id == universe_id, MonitoredStock.is_active == True
        )
        .all()
    )
    if not stocks:
        return {"status": "skipped", "message": "No active stocks in this universe."}

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    today = now_utc.strftime("%Y-%m-%d")
    stock_tickers = [s.ticker for s in stocks if s.asset_class != "futures"]
    futures_stocks = [s for s in stocks if s.asset_class == "futures"]
    futures_tickers = list({s.ticker for s in futures_stocks})

    task_ids: list = []
    summary: list = []

    if stock_tickers:
        combos = (
            db.query(
                StockAggregate.timespan,
                StockAggregate.multiplier,
                func.max(StockAggregate.timestamp).label("max_ts"),
            )
            .filter(StockAggregate.ticker.in_(stock_tickers))
            .group_by(StockAggregate.timespan, StockAggregate.multiplier)
            .all()
        )
        for combo in combos:
            from_dt = (
                (combo.max_ts + timedelta(seconds=1))
                if combo.max_ts
                else (now_utc - timedelta(days=7))
            )
            if from_dt > now_utc:
                summary.append(
                    f"{combo.timespan}×{combo.multiplier}: already up to date"
                )
                continue
            from_date = from_dt.strftime("%Y-%m-%d")
            for ticker in stock_tickers:
                r = sync_stock_aggregates.delay(
                    ticker=ticker,
                    from_date=from_date,
                    to_date=today,
                    multiplier=combo.multiplier,
                    timespan=combo.timespan,
                )
                task_ids.append(r.id)
            summary.append(
                f"{combo.timespan}×{combo.multiplier}: {len(stock_tickers)} stocks from {from_date}"
            )

    if futures_tickers:
        combos = (
            db.query(
                FuturesAggregate.timespan,
                FuturesAggregate.multiplier,
                func.max(FuturesAggregate.timestamp).label("max_ts"),
            )
            .filter(FuturesAggregate.symbol.in_(futures_tickers))
            .group_by(FuturesAggregate.timespan, FuturesAggregate.multiplier)
            .all()
        )
        stock_map = {s.ticker: s for s in futures_stocks}
        for combo in combos:
            from_dt = (
                (combo.max_ts + timedelta(seconds=1))
                if combo.max_ts
                else (now_utc - timedelta(days=7))
            )
            if from_dt > now_utc:
                summary.append(
                    f"{combo.timespan}×{combo.multiplier} futures: already up to date"
                )
                continue
            from_date = from_dt.strftime("%Y-%m-%d")
            for symbol in futures_tickers:
                s = stock_map.get(symbol)
                metadata = (s.stock_metadata or {}) if s else {}
                exchange = metadata.get("primary_exchange")
                if not exchange or exchange == "Unknown":
                    exchange = SYMBOL_EXCHANGE_MAP.get(symbol)
                if not exchange:
                    logger.warning(f"sync-missing: no exchange for {symbol}, skipping")
                    continue
                r = sync_futures_aggregates.delay(
                    symbol=symbol,
                    exchange=exchange,
                    timespan=combo.timespan,
                    multiplier=combo.multiplier,
                    from_date=from_date,
                    to_date=today,
                )
                task_ids.append(r.id)
            summary.append(
                f"{combo.timespan}×{combo.multiplier}: {len(futures_tickers)} futures from {from_date}"
            )

    if not task_ids:
        return {
            "status": "skipped",
            "message": "No existing aggregate data found to extend — use Sync to do an initial download first.",
        }

    try:
        r = redis_lib.from_url(settings.REDIS_URL)
        r.setex(
            f"universe:{universe_id}:sync",
            14400,
            json.dumps(
                {
                    "task_ids": task_ids,
                    "total": len(task_ids),
                    "started_at": datetime.now(timezone.utc).isoformat(),
                }
            ),
        )
    except Exception as e:
        logger.warning(f"Could not store sync-missing status in Redis: {e}")

    return {"status": "accepted", "queued": len(task_ids), "summary": summary}


def get_sync_status(universe_id: int) -> dict:
    """
    Return the current sync progress for a universe.
    Reads task IDs from Redis, inspects AsyncResult.state for each.
    Clears stale keys older than 4 hours (Celery result TTL boundary).
    """
    r = redis_lib.from_url(settings.REDIS_URL)
    raw = r.get(f"universe:{universe_id}:sync")
    if not raw:
        return {
            "is_syncing": False,
            "pending": 0,
            "success": 0,
            "failed": 0,
            "total": 0,
        }

    data = json.loads(raw)
    task_ids = data.get("task_ids", [])
    started_at_str = data.get("started_at")

    if started_at_str:
        try:
            started_at = datetime.fromisoformat(started_at_str).replace(
                tzinfo=timezone.utc
            )
            age_hours = (datetime.now(timezone.utc) - started_at).total_seconds() / 3600
            if age_hours > 4:
                r.delete(f"universe:{universe_id}:sync")
                return {
                    "is_syncing": False,
                    "pending": 0,
                    "success": 0,
                    "failed": 0,
                    "total": 0,
                }
        except (ValueError, TypeError):
            pass

    states = [AsyncResult(tid, app=celery_app).state for tid in task_ids]
    pending = sum(1 for s in states if s in ("PENDING", "STARTED", "RETRY"))
    success = sum(1 for s in states if s == "SUCCESS")
    failed = sum(1 for s in states if s in ("FAILURE", "REVOKED"))

    is_syncing = pending > 0
    if not is_syncing:
        r.delete(f"universe:{universe_id}:sync")

    return {
        "is_syncing": is_syncing,
        "total": len(task_ids),
        "pending": pending,
        "success": success,
        "failed": failed,
        "started_at": started_at_str,
        "timespan": data.get("timespan"),
        "from_date": data.get("from_date"),
        "to_date": data.get("to_date"),
    }


def sync_aggregates(
    universe_id: int,
    from_date: str,
    to_date: str,
    multiplier: int,
    timespan: str,
    adjusted: bool,
    sort: str,
    limit: int,
    db: Session,
) -> dict:
    """
    Trigger backfill of aggregates for all stocks in the universe.
    Deduplicates: refuses if a sync is already in progress (pending > 0).
    Writes task IDs to Redis universe:{id}:sync (4-hour TTL).
    """
    from app.services.futures_data import SYMBOL_EXCHANGE_MAP
    from app.tasks import sync_futures_aggregates, sync_stock_aggregates

    stocks = (
        db.query(MonitoredStock)
        .filter(
            MonitoredStock.universe_id == universe_id,
            MonitoredStock.is_active == True,
        )
        .all()
    )

    if not stocks:
        return {"status": "skipped", "message": "No active stocks in this universe."}

    r = redis_lib.from_url(settings.REDIS_URL)
    existing = r.get(f"universe:{universe_id}:sync")
    if existing:
        try:
            data = json.loads(existing)
            states = [
                AsyncResult(tid, app=celery_app).state
                for tid in data.get("task_ids", [])
            ]
            pending = sum(1 for s in states if s in ("PENDING", "STARTED", "RETRY"))
            if pending > 0:
                return {
                    "status": "rejected",
                    "message": (
                        f"Sync already in progress for universe {universe_id} "
                        f"({pending} tasks pending, started {data.get('started_at')}, "
                        f"timespan={data.get('timespan')}). "
                        f"Wait for it to finish or call /sync/stop first."
                    ),
                    "pending": pending,
                    "started_at": data.get("started_at"),
                    "timespan": data.get("timespan"),
                }
            r.delete(f"universe:{universe_id}:sync")
        except (ValueError, json.JSONDecodeError):
            r.delete(f"universe:{universe_id}:sync")

    stock_count = 0
    futures_count = 0
    queued_futures: set = set()
    task_ids: list = []

    for stock in stocks:
        if stock.asset_class == "futures":
            symbol = stock.ticker
            if symbol in queued_futures:
                continue
            metadata = stock.stock_metadata or {}
            exchange = metadata.get("primary_exchange")
            if not exchange or exchange == "Unknown":
                exchange = SYMBOL_EXCHANGE_MAP.get(symbol)
            if not exchange:
                logger.warning(
                    f"Universe {universe_id}: cannot determine exchange for futures "
                    f"symbol '{symbol}' — skipping aggregate sync."
                )
                continue
            result = sync_futures_aggregates.delay(
                symbol=symbol,
                exchange=exchange,
                timespan=timespan,
                multiplier=multiplier,
                from_date=from_date,
                to_date=to_date,
            )
            task_ids.append(result.id)
            queued_futures.add(symbol)
            futures_count += 1
        else:
            result = sync_stock_aggregates.delay(
                ticker=stock.ticker,
                from_date=from_date,
                to_date=to_date,
                multiplier=multiplier,
                timespan=timespan,
                adjusted=adjusted,
                sort=sort,
                limit=limit,
            )
            task_ids.append(result.id)
            stock_count += 1

    try:
        r.setex(
            f"universe:{universe_id}:sync",
            14400,
            json.dumps(
                {
                    "task_ids": task_ids,
                    "total": len(task_ids),
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "timespan": timespan,
                    "from_date": from_date,
                    "to_date": to_date,
                }
            ),
        )
    except Exception as e:
        logger.warning(f"Could not store sync status in Redis: {e}")

    parts = []
    if stock_count:
        parts.append(f"{stock_count} stocks ({from_date} to {to_date})")
    if futures_count:
        parts.append(f"{futures_count} futures symbol(s) via IBKR")
    return {
        "status": "accepted",
        "queued": len(task_ids),
        "message": f"Scheduled aggregate sync for {', '.join(parts)}.",
    }


def queue_quality_analysis(universe_id: int, db: Session) -> dict:
    """
    Upsert a pending UniverseQualityReport row (clearing stale snapshot fields)
    and queue the analyze_universe_quality Celery task.
    Raises UniverseNotFoundError if the universe does not exist.
    """
    from app.tasks import analyze_universe_quality

    universe = db.query(StockUniverse).filter(StockUniverse.id == universe_id).first()
    if not universe:
        raise UniverseNotFoundError(universe_id)

    report = (
        db.query(UniverseQualityReport)
        .filter(UniverseQualityReport.universe_id == universe_id)
        .first()
    )
    if not report:
        report = UniverseQualityReport(universe_id=universe_id)
        db.add(report)
    report.status = "pending"
    report.started_at = datetime.now(timezone.utc).replace(tzinfo=None)
    report.generated_at = None
    report.report_data = None
    report.overall_grade = None
    report.overall_score = None
    report.ticker_count = None
    report.error_message = None
    db.commit()

    analyze_universe_quality.delay(universe_id)

    return {"status": "accepted", "message": "Quality analysis queued."}


def queue_normalization(
    universe_id: int,
    target_tickers: Optional[List[str]],
    db: Session,
) -> dict:
    """
    Start (or resume) a normalization run for the universe.
    Accepts target_tickers (already unwrapped from NormalizeRequest by the router)
    to keep the service layer free of Pydantic models.
    Resumes from checkpoint if normalization_status is 'running' or 'error'
    and processed_combos exists.
    Raises UniverseNotFoundError if the universe does not exist.
    Raises UniverseValidationError if no quality analysis has been run yet.
    """
    from app.tasks import normalize_universe_quality

    universe = db.query(StockUniverse).filter(StockUniverse.id == universe_id).first()
    if not universe:
        raise UniverseNotFoundError(universe_id)

    report = (
        db.query(UniverseQualityReport)
        .filter(UniverseQualityReport.universe_id == universe_id)
        .first()
    )

    if not report or not report.report_data:
        raise UniverseValidationError(
            "No quality analysis found. Run 'Analyse' first.",
            universe_id=universe_id,
        )

    resume = bool(
        report.normalization_status in ("running", "error")
        and report.normalization_data
        and report.normalization_data.get("processed_combos")
    )

    report.normalization_status = "pending"
    if not resume:
        report.normalization_data = None
    db.commit()

    normalize_universe_quality.delay(
        universe_id, resume=resume, target_tickers=target_tickers
    )

    return {
        "status": "accepted",
        "resume": resume,
        "message": "Normalization queued."
        + (" Resuming from checkpoint." if resume else ""),
    }
