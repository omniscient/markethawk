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
import math
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from ib_insync import IB, ContFuture, Stock, util

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.active_watchlist import ActiveWatchlist
from live_scanner.bar_aggregator import BarAggregator
from live_scanner.conditions import check_conditions
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
WATCHLIST_SYNC_INTERVAL = 30   # seconds between DB polls
HISTORY_DURATION = "10 D"
MAX_CONNECT_RETRIES = 10
RECONNECT_BASE_DELAY = 5       # seconds; doubles per attempt, capped at 60 s

# Queue message tags
TAG_BAR   = "bar"    # (TAG_BAR,   symbol, RealTimeBar)
TAG_QUOTE = "quote"  # (TAG_QUOTE, symbol, dict)


# ── Helpers ────────────────────────────────────────────────────────────────

def _valid_price(p) -> bool:
    """True if p is a usable price (not None / NaN / zero / negative)."""
    try:
        return p is not None and not math.isnan(p) and p > 0
    except TypeError:
        return False


# ── DB helpers ─────────────────────────────────────────────────────────────

def _db_get_watchlist() -> List[Dict[str, str]]:
    db = SessionLocal()
    try:
        rows = db.query(ActiveWatchlist).all()
        return [
            {
                "symbol": r.symbol,
                "security_type": r.security_type or "STK",
                "exchange": r.exchange or (
                    "CME" if (r.security_type or "STK") == "FUT" else "SMART"
                ),
            }
            for r in rows
        ]
    finally:
        db.close()


# ── IBKR helpers ───────────────────────────────────────────────────────────

def _build_contract(symbol: str, security_type: str, exchange: str):
    if security_type == "FUT":
        return ContFuture(symbol=symbol, exchange=exchange, currency="USD")
    return Stock(symbol, "SMART", "USD")


async def _qualify_contract(ib: IB, contract) -> Any | None:
    try:
        qualified = await asyncio.wait_for(
            ib.qualifyContractsAsync(contract), timeout=30
        )
        return qualified[0] if qualified else None
    except Exception as e:
        logger.warning(f"qualify_contract failed for {contract.symbol}: {e}")
        return None


async def _fetch_prior_data(ib: IB, contract, symbol: str) -> Tuple[float, float]:
    """Returns (prior_close, avg_daily_volume); both 0.0 on failure."""
    try:
        bars = await asyncio.wait_for(
            ib.reqHistoricalDataAsync(
                contract,
                endDateTime="",
                durationStr=HISTORY_DURATION,
                barSizeSetting="1 day",
                whatToShow="TRADES",
                useRTH=True,
                formatDate=1,
                keepUpToDate=False,
            ),
            timeout=30,
        )
    except Exception as e:
        logger.warning(f"_fetch_prior_data failed for {symbol}: {e}")
        return 0.0, 0.0

    if not bars:
        return 0.0, 0.0

    prior_close = float(bars[-1].close)
    volumes = [int(b.volume) for b in bars if int(b.volume) > 0]
    avg_vol = sum(volumes) / len(volumes) if volumes else 0.0
    return prior_close, avg_vol


# ── Subscription management ────────────────────────────────────────────────

async def _subscribe(
    ib: IB,
    item: Dict[str, str],
    bar_subs: Dict[str, Any],    # symbol → RealTimeBarList
    mkt_subs: Dict[str, Any],    # symbol → Ticker
    aggregators: Dict[str, BarAggregator],
    queue: asyncio.Queue,
) -> None:
    symbol = item["symbol"]
    logger.info(f"Subscribing to {symbol} ({item['security_type']}:{item['exchange']})")

    contract = _build_contract(symbol, item["security_type"], item["exchange"])
    qualified = await _qualify_contract(ib, contract)
    if qualified is None:
        logger.warning(f"Could not qualify {symbol} — skipping")
        return

    prior_close, avg_vol = await _fetch_prior_data(ib, qualified, symbol)
    logger.info(f"{symbol}: prior_close={prior_close:.2f}, avg_daily_vol={avg_vol:.0f}")

    aggregators[symbol] = BarAggregator(symbol, prior_close, avg_vol)

    # ── reqRealTimeBars — OHLCV every 5 s, used for alert logic ────────────
    def _on_bar(bars, hasNewBar):
        if hasNewBar and bars:
            queue.put_nowait((TAG_BAR, symbol, bars[-1]))

    bars = ib.reqRealTimeBars(qualified, barSize=5, whatToShow="TRADES", useRTH=False)
    bars.updateEvent += _on_bar
    bar_subs[symbol] = bars

    # ── reqMktData — fires on every price change, used for UI display ───────
    # Track last published price so we only enqueue when the last price moves.
    _last_price: list = [0.0]

    def _on_ticker(ticker):
        last = ticker.last
        if not _valid_price(last):
            return
        if last == _last_price[0]:
            return  # price unchanged — skip to avoid flooding
        _last_price[0] = last
        queue.put_nowait((
            TAG_QUOTE,
            symbol,
            {
                "last": last,
                "bid":  ticker.bid if _valid_price(ticker.bid)  else None,
                "ask":  ticker.ask if _valid_price(ticker.ask)  else None,
                "time": int(datetime.now(timezone.utc).timestamp()),
            },
        ))

    ticker = ib.reqMktData(qualified, genericTickList="", snapshot=False,
                           regulatorySnapshot=False)
    ticker.updateEvent += _on_ticker
    mkt_subs[symbol] = ticker

    logger.info(f"Real-time bars + market data active for {symbol}")


def _unsubscribe(
    ib: IB,
    symbol: str,
    bar_subs: Dict[str, Any],
    mkt_subs: Dict[str, Any],
    aggregators: Dict[str, BarAggregator],
) -> None:
    bars = bar_subs.pop(symbol, None)
    if bars is not None:
        ib.cancelRealTimeBars(bars)

    ticker = mkt_subs.pop(symbol, None)
    if ticker is not None:
        ib.cancelMktData(ticker)

    aggregators.pop(symbol, None)
    logger.info(f"Unsubscribed {symbol}")


# ── Core loops ─────────────────────────────────────────────────────────────

async def _sync_loop(
    ib: IB,
    bar_subs: Dict[str, Any],
    mkt_subs: Dict[str, Any],
    aggregators: Dict[str, BarAggregator],
    queue: asyncio.Queue,
) -> None:
    """Periodically reconcile live subscriptions against the DB watchlist."""
    while True:
        if not ib.isConnected():
            await asyncio.sleep(5)
            continue

        try:
            watchlist = await asyncio.to_thread(_db_get_watchlist)
        except Exception as e:
            logger.error(f"DB watchlist fetch failed: {e}")
            await asyncio.sleep(WATCHLIST_SYNC_INTERVAL)
            continue

        current = {item["symbol"]: item for item in watchlist}

        for symbol in list(bar_subs.keys()):
            if symbol not in current:
                _unsubscribe(ib, symbol, bar_subs, mkt_subs, aggregators)

        for symbol, item in current.items():
            if symbol not in bar_subs:
                await _subscribe(ib, item, bar_subs, mkt_subs, aggregators, queue)

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
            # reqMktData price update — publish immediately for UI
            try:
                await publisher.publish_quote(symbol, data)
            except Exception as e:
                logger.debug(f"publish_quote error for {symbol}: {e}")
            continue

        # tag == TAG_BAR — 5-second OHLCV bar
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


# ── Connection with retries ────────────────────────────────────────────────

async def _connect_ib(ib: IB) -> bool:
    for attempt in range(MAX_CONNECT_RETRIES):
        _errors: list = []

        def _on_error(reqId, errorCode, errorString, contract):
            logger.warning(f"IB error {errorCode} (reqId={reqId}): {errorString}")
            _errors.append(errorCode)

        ib.errorEvent += _on_error

        try:
            await ib.connectAsync(
                host=settings.IBKR_HOST,
                port=settings.IBKR_PORT,
                clientId=LIVE_SCANNER_CLIENT_ID,
                timeout=30,
            )
            await asyncio.sleep(0.5)

            if ib.isConnected():
                logger.info(
                    f"Connected to IB Gateway at {settings.IBKR_HOST}:{settings.IBKR_PORT} "
                    f"(clientId={LIVE_SCANNER_CLIENT_ID})"
                )
                return True

            reason = (
                f"error {_errors[-1]}" if _errors
                else "unknown (clientId may be in use)"
            )
            raise ConnectionError(f"Connection rejected — {reason}")

        except Exception as e:
            delay = min(RECONNECT_BASE_DELAY * (2 ** attempt), 60)
            logger.warning(
                f"Connection attempt {attempt + 1}/{MAX_CONNECT_RETRIES} failed: {e}. "
                f"Retrying in {delay}s…"
            )
            await asyncio.sleep(delay)

    logger.error("Exhausted all connection retries. Exiting.")
    return False


# ── Main entry point ───────────────────────────────────────────────────────

async def run() -> None:
    util.patchAsyncio()

    publisher = LivePublisher(settings.REDIS_URL, settings.DATABASE_URL)
    await publisher.connect()

    ib = IB()
    if not await _connect_ib(ib):
        await publisher.close()
        return

    bar_subs:   Dict[str, Any]          = {}
    mkt_subs:   Dict[str, Any]          = {}
    aggregators: Dict[str, BarAggregator] = {}
    queue: asyncio.Queue = asyncio.Queue(maxsize=2000)

    ib.disconnectedEvent += lambda: logger.warning(
        "IB Gateway disconnected — will reconnect on next sync cycle"
    )

    sync_task = asyncio.create_task(
        _sync_loop(ib, bar_subs, mkt_subs, aggregators, queue),
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
        if ib.isConnected():
            ib.disconnect()
        await publisher.close()
        logger.info("Live scanner stopped")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
