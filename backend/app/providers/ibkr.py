"""
IBKR Data Provider - Interactive Brokers TWS API implementation.

Uses the ib_insync library (async-friendly wrapper around the official TWS API).

Key IBKR pacing rules enforced here:
  - Max 60 historical data requests per 10-minute window
  - No identical requests within 15 seconds
  - Max 50 simultaneous open requests (we keep it at 1 for safety)
"""

import asyncio
import logging
import os
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pybreaker

from app.core.circuit_breakers import IBKR_BREAKER
from app.core.config import settings
from app.core.metrics import ibkr_connection_status
from app.exceptions import ProviderError
from app.providers.base import BaseDataProvider

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy import guard — ib_insync is only needed when IBKR features are used.
# ---------------------------------------------------------------------------
try:
    from ib_insync import IB, ContFuture, Future, Stock, util  # noqa: F401
    from ib_insync.contract import ContractDetails

    IB_INSYNC_AVAILABLE = True
except ImportError:
    IB_INSYNC_AVAILABLE = False
    logger.warning(
        "ib_insync not installed. IBKRDataProvider will be unavailable. "
        "Run: pip install ib_insync"
    )


# ---------------------------------------------------------------------------
# Timespan mapping: our internal names → IBKR barSizeSetting strings
# ---------------------------------------------------------------------------
TIMESPAN_TO_IBKR = {
    "second": "1 secs",
    "5second": "5 secs",
    "minute": "1 min",
    "2minute": "2 mins",
    "5minute": "5 mins",
    "15minute": "15 mins",
    "30minute": "30 mins",
    "hour": "1 hour",
    "2hour": "2 hours",
    "4hour": "4 hours",
    "day": "1 day",
    "week": "1 week",
    "month": "1 month",
}

# How much history IBKR allows per request for each bar size
# (used to chunk multi-year requests into valid IBKR durations)
IBKR_MAX_DURATION = {
    "1 secs": "1800 S",
    "5 secs": "7200 S",
    "1 min": "1 D",
    "2 mins": "2 D",
    "5 mins": "1 W",
    "15 mins": "2 W",
    "30 mins": "1 M",
    "1 hour": "1 M",
    "2 hours": "1 M",
    "4 hours": "1 M",
    "1 day": "1 Y",
    "1 week": "5 Y",
    "1 month": "10 Y",
}


class IBKRPacingGuard:
    """
    Enforces IBKR's pacing rules to prevent pacing violations.

    Rules:
      1. Max 60 requests per 10-minute sliding window
      2. Fixed delay of at least `min_delay_s` seconds between any two requests
    """

    def __init__(self, max_per_10min: int = 55, min_delay_s: float = 2.0):
        self._window: deque = deque()  # timestamps of recent requests
        self._max = max_per_10min
        self._min_delay = min_delay_s
        self._last_request_time: float = 0.0

    async def wait(self):
        """Block until it is safe to make another request."""
        now = time.monotonic()

        # Enforce minimum inter-request delay
        elapsed = now - self._last_request_time
        if elapsed < self._min_delay:
            await asyncio.sleep(self._min_delay - elapsed)

        # Prune timestamps older than 10 minutes
        cutoff = time.monotonic() - 600
        while self._window and self._window[0] < cutoff:
            self._window.popleft()

        # If we are at the limit, wait until the oldest entry falls off
        if len(self._window) >= self._max:
            sleep_for = 600 - (time.monotonic() - self._window[0]) + 1
            if sleep_for > 0:
                logger.warning(
                    f"IBKRPacingGuard: at {self._max} req/10min limit. "
                    f"Sleeping {sleep_for:.1f}s..."
                )
                await asyncio.sleep(sleep_for)

        self._window.append(time.monotonic())
        self._last_request_time = time.monotonic()


class IBKRDataProvider(BaseDataProvider):
    """
    Interactive Brokers data provider.

    Notes
    -----
    * ib_insync is designed around an asyncio event loop. When called from
      a synchronous Celery task the caller must manage the loop. For FastAPI
      async endpoints this works naturally.
    * The connection is created lazily on first use and kept alive. Call
      disconnect() when done if running from a standalone script.
    """

    def __init__(self):
        self._ib: Optional["IB"] = None
        self._pacing = IBKRPacingGuard()
        self._connected = False

    # ------------------------------------------------------------------ #
    #  BaseDataProvider interface                                          #
    # ------------------------------------------------------------------ #

    @property
    def name(self) -> str:
        return "ibkr"

    @property
    def supported_asset_classes(self) -> List[str]:
        return ["futures"]

    def is_available(self) -> tuple[bool, str]:
        """True if ib_insync is installed and IBKR config is present."""
        if not IB_INSYNC_AVAILABLE:
            return False, "Missing 'ib-insync' library"
        if not settings.IBKR_HOST:
            return False, "Missing IBKR_HOST"
        return True, "Ready"

    def get_bars(
        self,
        symbol: str,
        timespan: str,
        multiplier: int,
        from_date: str,
        to_date: str,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """IBKR serves futures only; stock bars are not supported — return empty."""
        return []

    def get_snapshots(
        self, symbols: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """IBKR does not provide a snapshot feed; return empty."""
        return []

    def get_ticker_details(self, symbol: str) -> Dict[str, Any]:
        """IBKR does not provide fundamental data in a convenient way; return empty."""
        return {}

    # ------------------------------------------------------------------ #
    #  Futures-specific methods                                            #
    # ------------------------------------------------------------------ #

    async def get_futures_contracts(
        self,
        symbol: str,
        exchange: str,
        include_expired: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Return all available contract months for a futures symbol.

        Each dict contains:
            {
                "contract_month": "YYYYMMDD",   # lastTradeDateOrContractMonth
                "expiry":         "YYYY-MM-DD",
                "con_id":         int,
                "exchange":       str,
                "is_expired":     bool,
            }
        """
        if not IB_INSYNC_AVAILABLE:
            return []

        try:
            return await IBKR_BREAKER.call_async(
                self._get_futures_contracts_impl, symbol, exchange, include_expired
            )
        except pybreaker.CircuitBreakerError as e:
            raise ProviderError(
                "IBKR circuit breaker open — provider temporarily unavailable",
                provider="ibkr",
                endpoint="get_futures_contracts",
                is_retryable=False,
            ) from e

    async def _get_futures_contracts_impl(
        self,
        symbol: str,
        exchange: str,
        include_expired: bool,
    ) -> List[Dict[str, Any]]:
        ib = await self._get_connection()
        if not ib:
            raise ProviderError(
                "IBKR connection not available",
                provider="ibkr",
                endpoint="get_futures_contracts",
                is_retryable=True,
            )

        # Use a bare Future to request contract details for ALL expiries
        template = Future(symbol=symbol.upper(), exchange=exchange.upper())
        template.includeExpired = include_expired

        try:
            details: List[ContractDetails] = await asyncio.wait_for(
                ib.reqContractDetailsAsync(template),
                timeout=30,
            )
        except Exception as e:
            logger.error(
                f"IBKRDataProvider: get_futures_contracts failed for {symbol}: {e}"
            )
            raise ProviderError(
                f"get_futures_contracts failed for {symbol}: {e}",
                provider="ibkr",
                endpoint="reqContractDetails",
                is_retryable=True,
            ) from e

        now = datetime.now(timezone.utc)
        contracts = []
        for cd in details:
            c = cd.contract
            expiry_str = c.lastTradeDateOrContractMonth  # "YYYYMMDD" or "YYYYMM"
            if not expiry_str:
                continue

            # Normalise to 8-digit format
            expiry_8 = expiry_str.ljust(8, "0")[:8]
            try:
                expiry_dt = datetime.strptime(expiry_8, "%Y%m%d").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                continue

            contracts.append(
                {
                    "contract_month": expiry_8,
                    "expiry": expiry_dt.strftime("%Y-%m-%d"),
                    "con_id": c.conId,
                    "exchange": c.exchange or exchange.upper(),
                    "is_expired": expiry_dt < now,
                }
            )

        # Sort chronologically
        contracts.sort(key=lambda x: x["contract_month"])
        logger.info(
            f"IBKRDataProvider: Found {len(contracts)} contract months for {symbol}"
        )
        return contracts

    async def get_futures_bars(
        self,
        symbol: str,
        exchange: str,
        contract_month: str,
        timespan: str = "day",
        multiplier: int = 1,
        what_to_show: str = "TRADES",
        use_rth: bool = False,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch OHLCV bars for a specific futures contract month.

        Args:
            symbol:         Root symbol, e.g. "ES".
            exchange:       Exchange, e.g. "CME", "COMEX".
            contract_month: YYYYMMDD string (lastTradeDateOrContractMonth).
            timespan:       Bar size ("day", "hour", "minute", etc.).
            multiplier:     Bar multiplier.
            what_to_show:   IBKR data type ("TRADES", "MIDPOINT", etc.).
            use_rth:        If True, only regular trading hours.
            from_date:      Start date "YYYY-MM-DD". If None, uses max lookback.
            to_date:        End date "YYYY-MM-DD". If None, uses today.
        """
        if not IB_INSYNC_AVAILABLE:
            return []

        try:
            return await IBKR_BREAKER.call_async(
                self._get_futures_bars_impl,
                symbol,
                exchange,
                contract_month,
                timespan,
                multiplier,
                what_to_show,
                use_rth,
                from_date,
                to_date,
            )
        except pybreaker.CircuitBreakerError as e:
            raise ProviderError(
                "IBKR circuit breaker open — provider temporarily unavailable",
                provider="ibkr",
                endpoint="get_futures_bars",
                is_retryable=False,
            ) from e

    async def _get_futures_bars_impl(
        self,
        symbol: str,
        exchange: str,
        contract_month: str,
        timespan: str,
        multiplier: int,
        what_to_show: str,
        use_rth: bool,
        from_date: Optional[str],
        to_date: Optional[str],
    ) -> List[Dict[str, Any]]:
        ib = await self._get_connection()
        if not ib:
            raise ProviderError(
                "IBKR connection not available",
                provider="ibkr",
                endpoint="get_futures_bars",
                is_retryable=True,
            )

        bar_size = self._resolve_bar_size(timespan, multiplier)

        contract = Future(
            symbol=symbol.upper(),
            lastTradeDateOrContractMonth=contract_month,
            exchange=exchange.upper(),
        )
        contract.includeExpired = True  # Essential for expired contracts

        # Qualify to get conId and full details
        try:
            qualified = await asyncio.wait_for(
                ib.qualifyContractsAsync(contract),
                timeout=30,
            )
            if not qualified:
                raise ProviderError(
                    f"Could not qualify {symbol} {contract_month}",
                    provider="ibkr",
                    endpoint="qualifyContracts",
                    is_retryable=False,
                )
            contract = qualified[0]
        except asyncio.TimeoutError as e:
            raise ProviderError(
                f"qualifyContracts timed out for {symbol} {contract_month}",
                provider="ibkr",
                endpoint="qualifyContracts",
                is_retryable=True,
            ) from e
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(
                f"qualify failed for {symbol} {contract_month}: {e}",
                provider="ibkr",
                endpoint="qualifyContracts",
                is_retryable=True,
            ) from e

        return await self._fetch_bars_chunked(
            contract=contract,
            bar_size=bar_size,
            from_date=from_date,
            to_date=to_date,
            what_to_show=what_to_show,
            use_rth=use_rth,
        )

    # ------------------------------------------------------------------ #
    #  Connection management                                               #
    # ------------------------------------------------------------------ #

    async def connect(self, max_retries: int = 6) -> bool:
        """
        Connect to IB Gateway / TWS with exponential backoff.

        Retries are important when running IB Gateway in Docker — the container
        takes ~45–60 s to start up and log in before it accepts socket connections.
        Retry schedule (seconds): 5, 10, 20, 40, 60, 60 (capped).
        """
        if not IB_INSYNC_AVAILABLE:
            return False

        if self._ib and self._ib.isConnected():
            return True

        # Per-process client ID so parallel Celery workers don't conflict.
        client_id = settings.IBKR_CLIENT_ID + (os.getpid() % 50)

        for attempt in range(max_retries):
            self._ib = IB()

            # Capture any IB-level errors (e.g. 326 clientId in use) so they
            # appear in logs instead of silently causing a disconnect.
            _last_error: list = []

            def _on_error(reqId, errorCode, errorString, contract):
                logger.warning(
                    f"IBKRDataProvider: IB error {errorCode} "
                    f"(reqId={reqId}): {errorString}"
                )
                _last_error.append((errorCode, errorString))

            self._ib.errorEvent += _on_error

            try:
                await self._ib.connectAsync(
                    host=settings.IBKR_HOST,
                    port=settings.IBKR_PORT,
                    clientId=client_id,
                    timeout=20,
                )
                # Brief pause so ib_insync can process immediate error events
                # (e.g. error 326 "client id already in use").
                await asyncio.sleep(0.5)

                if not self._ib.isConnected():
                    reason = (
                        f"error {_last_error[-1][0]}: {_last_error[-1][1]}"
                        if _last_error
                        else "clientId may already be in use"
                    )
                    raise ProviderError(
                        f"clientId={client_id} rejected — {reason}",
                        provider="ibkr",
                        endpoint="connect",
                        is_retryable=False,
                    )

                self._connected = True
                ibkr_connection_status.set(1)
                logger.info(
                    f"IBKRDataProvider: Connected to IB Gateway at "
                    f"{settings.IBKR_HOST}:{settings.IBKR_PORT} "
                    f"(clientId={client_id}, attempt={attempt + 1})"
                )
                return True

            except ProviderError:
                raise
            except Exception as e:
                self._ib = None
                self._connected = False
                ibkr_connection_status.set(0)
                delay = min(5 * (2**attempt), 60)  # 5 10 20 40 60 60 …
                if attempt < max_retries - 1:
                    logger.warning(
                        f"IBKRDataProvider: Connection attempt {attempt + 1}/{max_retries} "
                        f"failed ({e}). Retrying in {delay}s…"
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        f"IBKRDataProvider: All {max_retries} connection attempts failed. "
                        f"Last error: {e}"
                    )

        return False

    def disconnect(self):
        """Disconnect from TWS/Gateway."""
        if self._ib and self._ib.isConnected():
            self._ib.disconnect()
            logger.info("IBKRDataProvider: Disconnected from TWS.")
        self._ib = None
        self._connected = False
        ibkr_connection_status.set(0)

    async def _get_connection(self) -> Optional["IB"]:
        """Return a live IB connection, connecting if necessary."""
        if self._ib and self._ib.isConnected():
            return self._ib
        success = await self.connect()
        return self._ib if success else None

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _resolve_bar_size(timespan: str, multiplier: int) -> str:
        """Convert (timespan, multiplier) to an IBKR barSizeSetting string."""
        if multiplier > 1:
            # Build combined key like "5minute"
            key = f"{multiplier}{timespan}"
            if key in TIMESPAN_TO_IBKR:
                return TIMESPAN_TO_IBKR[key]

        bar_size = TIMESPAN_TO_IBKR.get(timespan)
        if not bar_size:
            raise ValueError(
                f"IBKRDataProvider: Unsupported timespan '{timespan}'. "
                f"Valid options: {list(TIMESPAN_TO_IBKR.keys())}"
            )
        return bar_size

    async def _fetch_bars_chunked(
        self,
        contract,
        bar_size: str,
        from_date: Optional[str],
        to_date: Optional[str],
        what_to_show: str = "TRADES",
        use_rth: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Download bars in IBKR-compliant chunks, walking backwards from to_date.

        IBKR historical data is requested with an endDateTime and a duration
        string.  To get a long range we repeatedly walk backwards.
        """
        ib = await self._get_connection()
        if not ib:
            return []

        # Determine target date range.
        # to_date is a YYYY-MM-DD string, so parse it as end-of-day (23:59:59 UTC)
        # rather than midnight — otherwise "today" would cap at 00:00 UTC and miss
        # the whole current day's bars.  Always cap at now so we don't ask for
        # future data.
        now_utc = datetime.now(timezone.utc)
        end_dt = (
            min(
                datetime.strptime(to_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                + timedelta(days=1, seconds=-1),
                now_utc,
            )
            if to_date
            else now_utc
        )
        start_dt = (
            datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if from_date
            else end_dt - timedelta(days=3650)  # 10 years default
        )

        # Pick the right chunk duration for this bar size
        max_duration = IBKR_MAX_DURATION.get(bar_size, "1 Y")

        all_bars: List[Dict[str, Any]] = []
        chunk_end = end_dt
        seen_timestamps = set()

        # How far to step back when a chunk returns no bars.
        # Derived from max_duration so we always make forward progress.
        _DURATION_STEP: Dict[str, timedelta] = {
            "1800 S": timedelta(minutes=30),
            "7200 S": timedelta(hours=2),
            "1 D": timedelta(days=1),
            "2 D": timedelta(days=2),
            "1 W": timedelta(weeks=1),
            "2 W": timedelta(weeks=2),
            "1 M": timedelta(days=30),
            "1 Y": timedelta(days=365),
            "5 Y": timedelta(days=365 * 5),
            "10 Y": timedelta(days=365 * 10),
        }
        empty_step = _DURATION_STEP.get(max_duration, timedelta(days=1))
        # Allow this many consecutive empty chunks before giving up.
        # A single empty chunk is common (weekend, holiday, maintenance window)
        # so we skip rather than abort.
        MAX_CONSECUTIVE_EMPTY = 5
        consecutive_empty = 0

        chunk_num = 0
        while chunk_end > start_dt:
            await self._pacing.wait()

            # Ensure we still have a live connection before each chunk
            ib = await self._get_connection()
            if not ib:
                logger.error(
                    "IBKRDataProvider: lost connection during chunked download, aborting."
                )
                break

            chunk_num += 1
            end_str = chunk_end.strftime("%Y%m%d %H:%M:%S UTC")
            logger.info(
                f"IBKRDataProvider: chunk {chunk_num} — end={end_str} "
                f"duration={max_duration} barSize={bar_size} "
                f"(collected {len(all_bars)} bars so far)"
            )

            try:
                bars = await asyncio.wait_for(
                    ib.reqHistoricalDataAsync(
                        contract,
                        endDateTime=end_str,
                        durationStr=max_duration,
                        barSizeSetting=bar_size,
                        whatToShow=what_to_show,
                        useRTH=use_rth,
                        formatDate=2,  # Unix UTC timestamps — avoids exchange-timezone ambiguity
                        keepUpToDate=False,
                    ),
                    timeout=120,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    f"IBKRDataProvider: chunk {chunk_num} timed out (120s) — "
                    f"stopping download with {len(all_bars)} bars collected."
                )
                break
            except Exception as e:
                logger.error(
                    f"IBKRDataProvider: reqHistoricalData failed on chunk {chunk_num}: {e} — "
                    f"stopping with {len(all_bars)} bars collected."
                )
                break

            if not bars:
                consecutive_empty += 1
                logger.info(
                    f"IBKRDataProvider: no bars for chunk {chunk_num} (end={end_str}) — "
                    f"stepping back ({consecutive_empty}/{MAX_CONSECUTIVE_EMPTY} consecutive empty)."
                )
                if consecutive_empty >= MAX_CONSECUTIVE_EMPTY:
                    logger.info(
                        f"IBKRDataProvider: {MAX_CONSECUTIVE_EMPTY} consecutive empty chunks — "
                        "reached start of available data."
                    )
                    break
                chunk_end = chunk_end - empty_step
                continue

            consecutive_empty = 0  # reset on any non-empty chunk

            # Convert to standard format
            new_bars = []
            for b in bars:
                ts = self._bar_date_to_utc(b.date)
                if ts in seen_timestamps:
                    continue
                if ts < start_dt:
                    continue
                seen_timestamps.add(ts)
                new_bars.append(
                    {
                        "timestamp": ts,
                        "open": float(b.open),
                        "high": float(b.high),
                        "low": float(b.low),
                        "close": float(b.close),
                        "volume": int(b.volume),
                        "vwap": float(b.average) if hasattr(b, "average") else None,
                        "transactions": int(b.barCount)
                        if hasattr(b, "barCount")
                        else None,
                    }
                )

            if not new_bars:
                # Bars came back but all were duplicates or before start_dt —
                # we've overlapped with already-collected data; stop.
                break

            all_bars.extend(new_bars)

            # Walk back: set next chunk_end to the oldest bar we got minus 1 second
            oldest_ts = min(b["timestamp"] for b in new_bars)
            if oldest_ts <= start_dt:
                break
            chunk_end = oldest_ts - timedelta(seconds=1)

        # Sort chronologically and deduplicate
        all_bars.sort(key=lambda x: x["timestamp"])
        logger.info(
            f"IBKRDataProvider: Downloaded {len(all_bars)} bars "
            f"({from_date} → {to_date})"
        )
        return all_bars

    @staticmethod
    def _bar_date_to_utc(bar_date) -> datetime:
        """
        Convert an ib_insync bar date to a UTC-aware datetime.

        With formatDate=2, ib_insync sets bar.date to either:
          - An integer Unix timestamp
          - A timezone-aware datetime (UTC)
          - A naive datetime (treat as UTC)
        With formatDate=1 (legacy), it's a local-time string — we no longer use
        that mode, but handle it as a fallback just in case.
        """
        # Integer Unix timestamp (formatDate=2)
        if isinstance(bar_date, (int, float)):
            return datetime.fromtimestamp(bar_date, tz=timezone.utc)

        if isinstance(bar_date, datetime):
            if bar_date.tzinfo is None:
                # ib_insync already decoded the Unix ts into a naive UTC datetime
                return bar_date.replace(tzinfo=timezone.utc)
            return bar_date.astimezone(timezone.utc)

        # String fallback (formatDate=1 legacy or date-only daily bars)
        s = str(bar_date).strip()
        for fmt in ("%Y%m%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y%m%d", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(s, fmt)
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        raise ValueError(f"IBKRDataProvider: Cannot parse bar date: {bar_date!r}")
