"""
IBKRLiveAdapter — wraps ib_insync behind the LiveDataProvider Protocol.

All ib_insync imports are confined to this module.
main.py has zero ib_insync imports and calls create_adapter() to obtain a connected adapter.
"""

import asyncio
import logging
import math
from datetime import datetime, timezone
from typing import Any

from ib_insync import IB, ContFuture, Stock, util

from live_scanner.provider import BarCallback, QuoteCallback

logger = logging.getLogger(__name__)

HISTORY_DURATION = "10 D"
MAX_CONNECT_RETRIES = 10
RECONNECT_BASE_DELAY = 5  # seconds; doubles per attempt, capped at 60 s


# ── Internal helpers ───────────────────────────────────────────────────────


def _valid_price(p) -> bool:
    """True if p is a usable price (not None / NaN / zero / negative)."""
    try:
        return p is not None and not math.isnan(p) and p > 0
    except TypeError:
        return False


def _build_contract(symbol: str, security_type: str, exchange: str):
    if security_type == "FUT":
        return ContFuture(symbol=symbol, exchange=exchange, currency="USD")
    return Stock(symbol, "SMART", "USD")


async def _qualify_contract(ib: IB, contract, symbol: str):
    try:
        qualified = await asyncio.wait_for(
            ib.qualifyContractsAsync(contract), timeout=30
        )
        return qualified[0] if qualified else None
    except Exception as e:
        logger.warning(f"qualify_contract failed for {symbol}: {e}")
        return None


async def _fetch_prior_data(ib: IB, qualified, symbol: str) -> tuple[float, float]:
    """Return (prior_close, avg_daily_volume). Both 0.0 on failure."""
    try:
        bars = await asyncio.wait_for(
            ib.reqHistoricalDataAsync(
                qualified,
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


async def _connect_ib(ib: IB, host: str, port: int, client_id: int) -> bool:
    for attempt in range(MAX_CONNECT_RETRIES):
        _errors: list = []

        def _on_error(reqId, errorCode, errorString, contract):
            logger.warning(f"IB error {errorCode} (reqId={reqId}): {errorString}")
            _errors.append(errorCode)

        ib.errorEvent += _on_error

        try:
            await ib.connectAsync(host=host, port=port, clientId=client_id, timeout=30)
            await asyncio.sleep(0.5)

            if ib.isConnected():
                logger.info(
                    f"Connected to IB Gateway at {host}:{port} (clientId={client_id})"
                )
                return True

            reason = (
                f"error {_errors[-1]}"
                if _errors
                else "unknown (clientId may be in use)"
            )
            raise ConnectionError(f"Connection rejected — {reason}")

        except Exception as e:
            delay = min(RECONNECT_BASE_DELAY * (2**attempt), 60)
            logger.warning(
                f"Connection attempt {attempt + 1}/{MAX_CONNECT_RETRIES} failed: {e}. "
                f"Retrying in {delay}s…"
            )
            await asyncio.sleep(delay)

    logger.error("Exhausted all connection retries. Exiting.")
    return False


# ── Public factory ─────────────────────────────────────────────────────────


async def create_adapter(
    host: str, port: int, client_id: int
) -> "IBKRLiveAdapter | None":
    """
    Create a connected IBKRLiveAdapter with exponential-backoff retry.
    Returns None when all retries are exhausted.
    """
    util.patchAsyncio()
    ib = IB()
    ib.disconnectedEvent += lambda: logger.warning(
        "IB Gateway disconnected — will retry subscriptions on next sync cycle"
    )
    if await _connect_ib(ib, host, port, client_id):
        return IBKRLiveAdapter(ib)
    return None


# ── Adapter ────────────────────────────────────────────────────────────────


class IBKRLiveAdapter:
    """
    Implements LiveDataProvider for an ib_insync IB connection.
    Receives a pre-connected IB instance from create_adapter().
    """

    def __init__(self, ib: IB) -> None:
        self._ib = ib
        self._bar_subs: dict[str, Any] = {}
        self._mkt_subs: dict[str, Any] = {}

    async def fetch_seed_data(
        self, symbol: str, security_type: str, exchange: str
    ) -> tuple[float, float]:
        contract = _build_contract(symbol, security_type, exchange)
        qualified = await _qualify_contract(self._ib, contract, symbol)
        if qualified is None:
            return 0.0, 0.0
        return await _fetch_prior_data(self._ib, qualified, symbol)

    async def subscribe(
        self,
        symbol: str,
        security_type: str,
        exchange: str,
        on_bar: BarCallback,
        on_quote: QuoteCallback,
    ) -> None:
        if not self._ib.isConnected():
            logger.warning(
                f"IBKRLiveAdapter: not connected — cannot subscribe {symbol}"
            )
            return

        contract = _build_contract(symbol, security_type, exchange)
        qualified = await _qualify_contract(self._ib, contract, symbol)
        if qualified is None:
            logger.warning(f"Could not qualify {symbol} — skipping")
            return

        # reqRealTimeBars — 5-second OHLCV bars for alert logic
        def _on_bar(bars, hasNewBar):
            if hasNewBar and bars:
                asyncio.get_event_loop().call_soon_threadsafe(
                    asyncio.ensure_future,
                    on_bar(symbol, bars[-1]),
                )

        bar_list = self._ib.reqRealTimeBars(
            qualified, barSize=5, whatToShow="TRADES", useRTH=False
        )
        bar_list.updateEvent += _on_bar
        self._bar_subs[symbol] = bar_list

        # reqMktData — sub-second last-price updates for UI
        _last_price: list = [0.0]

        def _on_ticker(ticker):
            last = ticker.last
            if not _valid_price(last) or last == _last_price[0]:
                return
            _last_price[0] = last
            asyncio.get_event_loop().call_soon_threadsafe(
                asyncio.ensure_future,
                on_quote(
                    symbol,
                    {
                        "last": last,
                        "bid": ticker.bid if _valid_price(ticker.bid) else None,
                        "ask": ticker.ask if _valid_price(ticker.ask) else None,
                        "time": int(datetime.now(timezone.utc).timestamp()),
                    },
                ),
            )

        ticker = self._ib.reqMktData(
            qualified, genericTickList="", snapshot=False, regulatorySnapshot=False
        )
        ticker.updateEvent += _on_ticker
        self._mkt_subs[symbol] = ticker

        logger.info(
            f"IBKRLiveAdapter: real-time bars + market data active for {symbol}"
        )

    async def unsubscribe(self, symbol: str) -> None:
        bar_list = self._bar_subs.pop(symbol, None)
        if bar_list is not None:
            self._ib.cancelRealTimeBars(bar_list)

        ticker = self._mkt_subs.pop(symbol, None)
        if ticker is not None:
            self._ib.cancelMktData(ticker)

        logger.info(f"IBKRLiveAdapter: unsubscribed {symbol}")

    async def disconnect(self) -> None:
        self._ib.disconnect()
