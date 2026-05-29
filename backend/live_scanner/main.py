"""
Live Scanner — entry point.

Hybrid data model:
  - reqRealTimeBars (5 s)  → volume accumulation, OHLCV aggregation, alert logic
  - reqMktData             → sub-second last-price updates for the UI

Run as:
    python -m live_scanner.main
"""

import asyncio
import logging
import sys
from typing import Dict

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.active_watchlist import ActiveWatchlist

from live_scanner.bar_aggregator import BarAggregator
from live_scanner.conditions import check_conditions
from live_scanner.ibkr_adapter import create_adapter
from live_scanner.provider import LiveDataProvider
from live_scanner.publisher import LivePublisher

# ── Logging ────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("live_scanner")

# ── Constants ──────────────────────────────────────────────────────────────

LIVE_SCANNER_CLIENT_ID = 5
WATCHLIST_SYNC_INTERVAL = 30  # seconds between DB polls

# Queue message tags
TAG_BAR = "bar"
TAG_QUOTE = "quote"


# ── DB helpers ─────────────────────────────────────────────────────────────


def _db_get_watchlist():
    db = SessionLocal()
    try:
        rows = db.query(ActiveWatchlist).all()
        return [
            {
                "symbol": r.symbol,
                "security_type": r.security_type or "STK",
                "exchange": r.exchange
                or ("CME" if (r.security_type or "STK") == "FUT" else "SMART"),
            }
            for r in rows
        ]
    finally:
        db.close()


# ── Subscription coordination ──────────────────────────────────────────────


async def _subscribe(
    provider: LiveDataProvider,
    item: Dict[str, str],
    aggregators: Dict[str, BarAggregator],
    queue: asyncio.Queue,
) -> None:
    symbol = item["symbol"]
    logger.info(f"Subscribing to {symbol} ({item['security_type']}:{item['exchange']})")

    prior_close, avg_vol = await provider.fetch_seed_data(
        symbol, item["security_type"], item["exchange"]
    )
    logger.info(f"{symbol}: prior_close={prior_close:.2f}, avg_daily_vol={avg_vol:.0f}")
    aggregators[symbol] = BarAggregator(symbol, prior_close, avg_vol)

    async def on_bar(sym: str, bar) -> None:
        queue.put_nowait((TAG_BAR, sym, bar))

    async def on_quote(sym: str, quote: dict) -> None:
        queue.put_nowait((TAG_QUOTE, sym, quote))

    await provider.subscribe(
        symbol,
        item["security_type"],
        item["exchange"],
        on_bar=on_bar,
        on_quote=on_quote,
    )
    logger.info(f"Real-time bars + market data active for {symbol}")


async def _unsubscribe(
    provider: LiveDataProvider,
    symbol: str,
    aggregators: Dict[str, BarAggregator],
) -> None:
    await provider.unsubscribe(symbol)
    aggregators.pop(symbol, None)
    logger.info(f"Unsubscribed {symbol}")


# ── Core loops ─────────────────────────────────────────────────────────────


async def _sync_loop(
    provider: LiveDataProvider,
    aggregators: Dict[str, BarAggregator],
    queue: asyncio.Queue,
    subscribed: set,
) -> None:
    """Periodically reconcile live subscriptions against the DB watchlist."""
    while True:
        try:
            watchlist = await asyncio.to_thread(_db_get_watchlist)
        except Exception as e:
            logger.error(f"DB watchlist fetch failed: {e}")
            await asyncio.sleep(WATCHLIST_SYNC_INTERVAL)
            continue

        current = {item["symbol"]: item for item in watchlist}

        for symbol in list(subscribed):
            if symbol not in current:
                await _unsubscribe(provider, symbol, aggregators)
                subscribed.discard(symbol)

        for symbol, item in current.items():
            if symbol not in subscribed:
                await _subscribe(provider, item, aggregators, queue)
                subscribed.add(symbol)

        await asyncio.sleep(WATCHLIST_SYNC_INTERVAL)


async def _process_loop(
    queue: asyncio.Queue,
    aggregators: Dict[str, BarAggregator],
    publisher: LivePublisher,
) -> None:
    """Drain the queue. Quotes → fast publish. Bars → aggregation + alerts."""
    while True:
        try:
            tag, symbol, data = await asyncio.wait_for(queue.get(), timeout=5.0)
        except asyncio.TimeoutError:
            continue

        if tag == TAG_QUOTE:
            try:
                await publisher.publish_quote(symbol, data)
            except Exception as e:
                logger.debug(f"publish_quote error for {symbol}: {e}")
            continue

        bar = data
        try:
            await publisher.publish_tick(symbol, bar)
        except Exception as e:
            logger.debug(f"publish_tick error for {symbol}: {e}")

        aggregator = aggregators.get(symbol)
        if aggregator is None:
            continue

        minute_bar = aggregator.update(bar)
        if minute_bar is None:
            continue

        try:
            await publisher.publish_minute_bar(symbol, minute_bar)
        except Exception as e:
            logger.debug(f"publish_minute_bar error for {symbol}: {e}")

        if minute_bar.session != "closed":
            try:
                for condition in check_conditions(minute_bar):
                    await publisher.fire_alert_if_new(minute_bar, condition)
            except Exception as e:
                logger.error(f"Condition/alert error for {symbol}: {e}")


# ── Main entry point ───────────────────────────────────────────────────────


async def run(provider: LiveDataProvider | None = None) -> None:
    publisher = LivePublisher(settings.REDIS_URL)
    await publisher.connect()

    if provider is None:
        provider = await create_adapter(
            settings.IBKR_HOST, settings.IBKR_PORT, LIVE_SCANNER_CLIENT_ID
        )
        if provider is None:
            await publisher.close()
            return

    aggregators: Dict[str, BarAggregator] = {}
    queue: asyncio.Queue = asyncio.Queue(maxsize=2000)
    subscribed: set = set()

    sync_task = asyncio.create_task(
        _sync_loop(provider, aggregators, queue, subscribed),
        name="watchlist-sync",
    )
    process_task = asyncio.create_task(
        _process_loop(queue, aggregators, publisher),
        name="bar-process",
    )

    logger.info("Live scanner started (hybrid: reqMktData + reqRealTimeBars)")

    try:
        await asyncio.gather(sync_task, process_task)
    except (asyncio.CancelledError, KeyboardInterrupt):
        logger.info("Live scanner shutting down…")
    except Exception as e:
        logger.error(f"Live scanner crashed: {e}", exc_info=True)
    finally:
        sync_task.cancel()
        process_task.cancel()
        await provider.disconnect()
        await publisher.close()
        logger.info("Live scanner stopped")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
