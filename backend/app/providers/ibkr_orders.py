"""
IBKROrderManager — order placement and account queries for automated trading.

Completely separate from IBKRDataProvider (historical/live market data).
Uses a dedicated clientId (IBKR_TRADING_CLIENT_ID) so it never interferes
with the live scanner (clientId 5) or historical data fetching.

Design: connect-per-operation.  Each public method opens a connection,
executes the operation, and disconnects.  This avoids persistent connection
management in a multi-worker Celery environment.

IBKR bracket order mechanics (ib_insync):
  bracketOrder(action, qty, limitPrice, takeProfitPrice, stopLossPrice)
  Returns (parent, takeProfit, stopLoss) — all three must be placed.
  They are linked via OCA group so only one child fires.

Paper-mode safety: if strategy.paper_mode is True the caller never
invokes IBKROrderManager at all — the executor handles that gate.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import List, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy import guard (same pattern as ibkr.py)
# ---------------------------------------------------------------------------
try:
    from ib_insync import (  # noqa: F401
        IB,
        LimitOrder,
        MarketOrder,
        Stock,
        StopOrder,
        util,
    )

    IB_INSYNC_AVAILABLE = True
except ImportError:
    IB_INSYNC_AVAILABLE = False
    logger.warning(
        "ib_insync not installed — IBKROrderManager will be unavailable. "
        "Run: pip install ib_insync"
    )

# ---------------------------------------------------------------------------
# Data transfer objects
# ---------------------------------------------------------------------------


@dataclass
class AccountSummary:
    net_liquidation: float = 0.0
    available_funds: float = 0.0
    buying_power: float = 0.0
    currency: str = "USD"
    raw: dict = field(default_factory=dict)


@dataclass
class BracketOrderResult:
    parent_id: int  # entry order permId
    stop_id: int  # stop-loss child permId
    target_id: int  # take-profit child permId
    parent_order_id: int  # orderId (used for cancel / status queries)
    stop_order_id: int
    target_order_id: int


@dataclass
class OpenOrderInfo:
    order_id: int
    perm_id: int
    symbol: str
    action: str  # "BUY" | "SELL"
    order_type: str  # "MKT", "LMT", "STP"
    total_qty: float
    status: str
    filled: float
    avg_fill_price: float


# ---------------------------------------------------------------------------
# IBKROrderManager
# ---------------------------------------------------------------------------


class IBKROrderManager:
    """
    Manages IBKR order lifecycle: account queries, bracket order placement,
    status polling, and order cancellation.

    All methods are async and must be called from an event loop
    (use asyncio.run() or loop.run_until_complete() from Celery tasks).
    """

    CONNECT_TIMEOUT = 30  # seconds

    def __init__(self):
        if not IB_INSYNC_AVAILABLE:
            raise RuntimeError(
                "ib_insync is not installed. "
                "Add it to requirements.txt and rebuild the container."
            )
        self._ib: Optional["IB"] = None

    # ── Connection helpers ───────────────────────────────────────────────

    async def _connect(self) -> "IB":
        """Open a connection and return the IB instance."""
        ib = IB()
        await asyncio.wait_for(
            ib.connectAsync(
                host=settings.IBKR_HOST,
                port=settings.IBKR_PORT,
                clientId=settings.IBKR_TRADING_CLIENT_ID,
                readonly=False,
            ),
            timeout=self.CONNECT_TIMEOUT,
        )
        logger.info(
            f"IBKROrderManager: connected clientId={settings.IBKR_TRADING_CLIENT_ID} "
            f"{settings.IBKR_HOST}:{settings.IBKR_PORT}"
        )
        return ib

    async def _disconnect(self, ib: "IB") -> None:
        try:
            ib.disconnect()
        except Exception:
            pass

    # ── Account ──────────────────────────────────────────────────────────

    async def _fetch_account_summary(self, ib: "IB") -> AccountSummary:
        """Parse account summary from an already-connected IB instance."""
        raw_values = await ib.reqAccountSummaryAsync()
        result = AccountSummary()
        raw: dict = {}
        for item in raw_values:
            raw[item.tag] = item.value
            if item.tag == "NetLiquidation":
                result.net_liquidation = float(item.value)
                result.currency = item.currency or "USD"
            elif item.tag == "AvailableFunds":
                result.available_funds = float(item.value)
            elif item.tag == "BuyingPower":
                result.buying_power = float(item.value)
        result.raw = raw
        logger.info(
            f"IBKROrderManager: account summary — "
            f"NLV=${result.net_liquidation:,.0f} "
            f"AvailFunds=${result.available_funds:,.0f}"
        )
        return result

    async def _fetch_open_orders(self, ib: "IB") -> List["OpenOrderInfo"]:
        """Parse open orders from an already-connected IB instance."""
        await ib.reqAllOpenOrdersAsync()
        return [
            OpenOrderInfo(
                order_id=t.order.orderId,
                perm_id=t.order.permId,
                symbol=t.contract.symbol,
                action=t.order.action,
                order_type=t.order.orderType,
                total_qty=t.order.totalQuantity,
                status=t.orderStatus.status,
                filled=t.orderStatus.filled,
                avg_fill_price=t.orderStatus.avgFillPrice,
            )
            for t in ib.openTrades()
        ]

    async def get_account_summary(self) -> AccountSummary:
        """Fetch key account metrics: net liquidation, available funds, buying power."""
        ib = await self._connect()
        try:
            return await self._fetch_account_summary(ib)
        finally:
            await self._disconnect(ib)

    async def get_account_and_orders(self) -> tuple:
        """
        Fetch account summary and open orders in one IBKR connection.
        Returns (AccountSummary, List[OpenOrderInfo]).
        """
        ib = await self._connect()
        try:
            account = await self._fetch_account_summary(ib)
            orders = await self._fetch_open_orders(ib)
            return account, orders
        finally:
            await self._disconnect(ib)

    # ── Order placement ──────────────────────────────────────────────────

    async def place_bracket_order(
        self,
        symbol: str,
        side: str,  # "long" | "short"
        quantity: int,
        entry_price: Optional[float],  # None = market order
        stop_price: float,
        target_price: float,
        order_ref: str = "",  # auto_trade_order.id for traceability
    ) -> BracketOrderResult:
        """
        Place a bracket order on IBKR: entry + stop-loss + take-profit.

        For a long:
          - Entry:  BUY  MKT (if entry_price is None) or LMT
          - Target: SELL LMT at target_price
          - Stop:   SELL STP at stop_price

        For a short:
          - Entry:  SELL STP (entry at or below trigger) or MKT
          - Target: BUY  LMT at target_price
          - Stop:   BUY  STP at stop_price

        Returns BracketOrderResult with broker IDs for all three legs.
        """
        ib = await self._connect()
        try:
            contract = Stock(symbol, "SMART", "USD")
            qualified = await ib.qualifyContractsAsync(contract)
            if not qualified:
                raise ValueError(f"Could not qualify contract for {symbol}")
            contract = qualified[0]

            ibkr_action = "BUY" if side == "long" else "SELL"

            # Build parent (entry) order
            if entry_price is None:
                parent = MarketOrder(  # noqa: F841
                    action=ibkr_action,
                    totalQuantity=quantity,
                    orderRef=order_ref,
                    transmit=False,  # don't transmit until all legs are ready
                )
            else:
                parent = LimitOrder(  # noqa: F841
                    action=ibkr_action,
                    totalQuantity=quantity,
                    lmtPrice=round(entry_price, 2),
                    orderRef=order_ref,
                    transmit=False,
                )

            # Use ib_insync bracket helper — builds an OCA-linked triplet
            bracket = ib.bracketOrder(
                action=ibkr_action,
                quantity=quantity,
                limitPrice=round(entry_price, 2) if entry_price else None,
                takeProfitPrice=round(target_price, 2),
                stopLossPrice=round(stop_price, 2),
            )
            # bracket is (parent, takeProfit, stopLoss)
            parent_order, take_profit_order, stop_loss_order = bracket

            # Tag orders for easy identification in IBKR activity statements
            parent_order.orderRef = f"MH-ENTRY-{order_ref}"
            take_profit_order.orderRef = f"MH-TARGET-{order_ref}"
            stop_loss_order.orderRef = f"MH-STOP-{order_ref}"

            # Place all three — last one has transmit=True (set by bracketOrder helper)
            trades = []
            for order in bracket:
                trade = ib.placeOrder(contract, order)
                trades.append(trade)
                await asyncio.sleep(0.05)  # brief pause between placements

            # Wait briefly for IBKR to assign permIds
            await asyncio.sleep(1.0)
            await ib.reqAllOpenOrdersAsync()

            parent_trade, target_trade, stop_trade = trades

            result = BracketOrderResult(
                parent_id=parent_trade.order.permId,
                stop_id=stop_trade.order.permId,
                target_id=target_trade.order.permId,
                parent_order_id=parent_trade.order.orderId,
                stop_order_id=stop_trade.order.orderId,
                target_order_id=target_trade.order.orderId,
            )

            logger.info(
                f"IBKROrderManager: bracket placed — {side.upper()} {quantity}x {symbol} "
                f"entry={entry_price or 'MKT'} stop={stop_price} target={target_price} "
                f"parentId={result.parent_order_id}"
            )
            return result

        finally:
            await self._disconnect(ib)

    # ── Order status ─────────────────────────────────────────────────────

    async def get_order_status(self, order_id: int) -> Optional[dict]:
        """
        Query the status of a specific order by orderId.

        Returns a dict with keys: status, filled, avg_fill_price, remaining
        or None if the order is not found.
        """
        ib = await self._connect()
        try:
            await ib.reqAllOpenOrdersAsync()
            # Also request completed orders
            completed = await ib.reqCompletedOrdersAsync(apiOnly=True)

            # Check open trades first
            for trade in ib.openTrades():
                if trade.order.orderId == order_id:
                    return {
                        "status": trade.orderStatus.status,
                        "filled": trade.orderStatus.filled,
                        "avg_fill_price": trade.orderStatus.avgFillPrice,
                        "remaining": trade.orderStatus.remaining,
                    }

            # Check completed orders
            for trade in completed:
                if trade.order.orderId == order_id:
                    return {
                        "status": trade.orderStatus.status,
                        "filled": trade.orderStatus.filled,
                        "avg_fill_price": trade.orderStatus.avgFillPrice,
                        "remaining": trade.orderStatus.remaining,
                    }

            return None
        finally:
            await self._disconnect(ib)

    async def get_open_orders(self) -> List[OpenOrderInfo]:
        """Return all currently open orders."""
        ib = await self._connect()
        try:
            return await self._fetch_open_orders(ib)
        finally:
            await self._disconnect(ib)

    # ── Cancellation ─────────────────────────────────────────────────────

    async def cancel_order(self, order_id: int) -> bool:
        """Cancel a single order by orderId. Returns True if cancel was sent."""
        ib = await self._connect()
        try:
            await ib.reqAllOpenOrdersAsync()
            for trade in ib.openTrades():
                if trade.order.orderId == order_id:
                    ib.cancelOrder(trade.order)
                    await asyncio.sleep(0.5)
                    logger.info(f"IBKROrderManager: cancel sent for orderId={order_id}")
                    return True
            logger.warning(
                f"IBKROrderManager: order {order_id} not found in open orders"
            )
            return False
        finally:
            await self._disconnect(ib)

    async def cancel_bracket(
        self,
        parent_order_id: int,
        stop_order_id: int,
        target_order_id: int,
    ) -> bool:
        """
        Cancel all three legs of a bracket order.

        In practice, cancelling the parent also cancels children for an
        unexecuted bracket.  If the parent is already filled (position open),
        only cancel the stop/target children.
        """
        ib = await self._connect()
        try:
            await ib.reqAllOpenOrdersAsync()
            open_ids = {t.order.orderId: t for t in ib.openTrades()}
            cancelled = 0
            for oid in (parent_order_id, stop_order_id, target_order_id):
                if oid in open_ids:
                    ib.cancelOrder(open_ids[oid].order)
                    cancelled += 1
                    await asyncio.sleep(0.1)

            logger.info(
                f"IBKROrderManager: cancel_bracket — "
                f"{cancelled}/3 legs cancelled for parentId={parent_order_id}"
            )
            return cancelled > 0
        finally:
            await self._disconnect(ib)
