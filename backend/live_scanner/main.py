"""
Live Scanner — entry point.

Hybrid data model:
  - reqRealTimeBars (5 s)  → volume accumulation, OHLCV aggregation, alert logic
  - reqMktData             → sub-second last-price updates for the UI

Run as:
    python -m live_scanner.main
"""

import asyncio
import datetime
import logging
import sys
import time
import zoneinfo
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
TAG_DISCONNECT = "disconnect"
TAG_CONNECT_RECOVERED = "connect_recovered"

HEARTBEAT_STALE_SECONDS = 30  # watchdog: stale-bar threshold during market hours

_ET = zoneinfo.ZoneInfo("America/New_York")


# ── Market-hours helper ────────────────────────────────────────────────────


def _is_market_hours() -> bool:
    """Return True if current ET time is within the live-bar window (04:00–20:00 ET)."""
    now_et = datetime.datetime.now(_ET)
    if now_et.weekday() >= 5:
        return False
    t = now_et.hour * 60 + now_et.minute
    return 240 <= t < 1200


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

    if symbol not in aggregators:
        prior_close, avg_vol = await provider.fetch_seed_data(
            symbol, item["security_type"], item["exchange"]
        )
        logger.info(
            f"{symbol}: prior_close={prior_close:.2f}, avg_daily_vol={avg_vol:.0f}"
        )
        aggregators[symbol] = BarAggregator(symbol, prior_close, avg_vol)
    else:
        logger.info(
            f"{symbol}: reconnect resubscribe — keeping existing BarAggregator state"
        )

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
    subscribed_items: Dict[str, dict],
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
                subscribed_items.pop(symbol, None)

        for symbol, item in current.items():
            if symbol not in subscribed:
                await _subscribe(provider, item, aggregators, queue)
                subscribed.add(symbol)
                subscribed_items[symbol] = item

        await asyncio.sleep(WATCHLIST_SYNC_INTERVAL)


async def _reconnect_coro(
    adapter,
    queue: asyncio.Queue,
    subscribed_items: Dict[str, dict],
    aggregators: Dict[str, BarAggregator],
    publisher: LivePublisher,
) -> None:
    """Attempt to reconnect and resubscribe all symbols. Runs as a fire-and-forget task."""
    logger.info("live-scanner: starting reconnect sequence…")
    ok = await adapter.reconnect()
    if not ok:
        logger.error(
            "live-scanner: exhausted reconnect retries — process will exit on next crash"
        )
        return
    logger.info("live-scanner: reconnect succeeded — re-wiring disconnect event")
    loop = asyncio.get_event_loop()
    adapter.wire_disconnect_queue(queue, TAG_DISCONNECT, loop)
    queue.put_nowait((TAG_CONNECT_RECOVERED, None, None))


async def _process_loop(
    queue: asyncio.Queue,
    aggregators: Dict[str, BarAggregator],
    publisher: LivePublisher,
    adapter,
    subscribed_items: Dict[str, dict],
    last_bar_ts: list,
) -> None:
    """Drain the queue. Quotes → fast publish. Bars → aggregation + alerts.
    Disconnect/recovered tags → reconnect lifecycle."""
    _reconnect_task = None

    while True:
        try:
            tag, symbol, data = await asyncio.wait_for(queue.get(), timeout=5.0)
        except asyncio.TimeoutError:
            continue

        if tag == TAG_DISCONNECT:
            logger.warning("live-scanner: IB Gateway disconnected")
            try:
                await publisher.publish_feed_loss()
            except Exception as e:
                logger.error(f"publish_feed_loss error: {e}")
            if _reconnect_task is None or _reconnect_task.done():
                _reconnect_task = asyncio.create_task(
                    _reconnect_coro(
                        adapter, queue, subscribed_items, aggregators, publisher
                    )
                )
            continue

        if tag == TAG_CONNECT_RECOVERED:
            logger.info("live-scanner: gateway recovered — resubscribing all symbols")
            for item in list(subscribed_items.values()):
                try:
                    await _subscribe(adapter, item, aggregators, queue)
                except Exception as e:
                    logger.error(f"resubscribe error for {item['symbol']}: {e}")
            try:
                await publisher.publish_feed_recovered()
            except Exception as e:
                logger.error(f"publish_feed_recovered error: {e}")
            continue

        if tag == TAG_QUOTE:
            try:
                await publisher.publish_quote(symbol, data)
            except Exception as e:
                logger.debug(f"publish_quote error for {symbol}: {e}")
            continue

        if tag == TAG_BAR:
            last_bar_ts[0] = time.monotonic()

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


async def _watchdog_loop(adapter, last_bar_ts: list) -> None:
    """Detect network-partition stalls: if no bars arrive for HEARTBEAT_STALE_SECONDS
    during market hours and the adapter reports connected (cached state), force a
    disconnect so disconnectedEvent fires → reconnect path handles recovery."""
    while True:
        await asyncio.sleep(10)
        if last_bar_ts[0] is None:
            continue
        if not _is_market_hours():
            continue
        elapsed = time.monotonic() - last_bar_ts[0]
        if elapsed > HEARTBEAT_STALE_SECONDS and adapter.is_connected():
            logger.warning(
                f"Watchdog: no bars for {elapsed:.0f}s during market hours — "
                "forcing disconnect to trigger reconnect"
            )
            adapter.force_disconnect()


# ── Main entry point ───────────────────────────────────────────────────────


async def run(provider: LiveDataProvider | None = None) -> None:
    publisher = LivePublisher(settings.REDIS_URL)
    await publisher.connect()

    if provider is None:
        if settings.LIVE_SCANNER_MOCK:
            from live_scanner.mock_adapter import MockLiveAdapter

            provider = MockLiveAdapter()
            logger.info("live-scanner: using MockLiveAdapter (LIVE_SCANNER_MOCK=true)")
        else:
            provider = await create_adapter(
                settings.IBKR_HOST, settings.IBKR_PORT, LIVE_SCANNER_CLIENT_ID
            )
            if provider is None:
                await publisher.close()
                return

    aggregators: Dict[str, BarAggregator] = {}
    queue: asyncio.Queue = asyncio.Queue(maxsize=2000)
    subscribed: set = set()
    subscribed_items: Dict[str, dict] = {}
    last_bar_ts: list = [None]

    loop = asyncio.get_event_loop()
    provider.wire_disconnect_queue(queue, TAG_DISCONNECT, loop)

    sync_task = asyncio.create_task(
        _sync_loop(provider, aggregators, queue, subscribed, subscribed_items),
        name="watchlist-sync",
    )
    process_task = asyncio.create_task(
        _process_loop(
            queue, aggregators, publisher, provider, subscribed_items, last_bar_ts
        ),
        name="bar-process",
    )
    watchdog_task = asyncio.create_task(
        _watchdog_loop(provider, last_bar_ts),
        name="heartbeat-watchdog",
    )

    logger.info("Live scanner started (hybrid: reqMktData + reqRealTimeBars)")

    try:
        await asyncio.gather(sync_task, process_task, watchdog_task)
    except (asyncio.CancelledError, KeyboardInterrupt):
        logger.info("Live scanner shutting down…")
    except Exception as e:
        logger.error(f"Live scanner crashed: {e}", exc_info=True)
    finally:
        sync_task.cancel()
        process_task.cancel()
        watchdog_task.cancel()
        await provider.disconnect()
        await publisher.close()
        logger.info("Live scanner stopped")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
