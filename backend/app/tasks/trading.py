import asyncio
import logging
import time as _time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.core.metrics import celery_task_duration_seconds, celery_tasks_total

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=1, name="app.tasks.execute_auto_trade")
def execute_auto_trade(self, rule_id: int, scanner_event_id: int):
    """
    Execute an automated trade for a matched alert rule.

    Runs AutoTradeExecutor.maybe_execute() which handles all guards,
    position sizing, and IBKR bracket-order placement.

    max_retries=1: a single retry on transient failure (e.g. DB lock).
    On IBKR errors the executor sets status='error' and does NOT retry —
    better to miss a trade than to double-enter.
    """
    from app.models.alert_rule import AlertRule
    from app.models.scanner_event import ScannerEvent
    from app.services.auto_trade_service import auto_trade_executor

    _task_name = "execute_auto_trade"
    _start = _time.monotonic()
    db: Session = SessionLocal()
    try:
        rule = db.query(AlertRule).filter(AlertRule.id == rule_id).first()
        event = (
            db.query(ScannerEvent).filter(ScannerEvent.id == scanner_event_id).first()
        )

        if not rule:
            logger.warning(f"execute_auto_trade: AlertRule id={rule_id} not found.")
            return
        if not event:
            logger.warning(
                f"execute_auto_trade: ScannerEvent id={scanner_event_id} not found."
            )
            return

        order = auto_trade_executor.maybe_execute(rule, event, db)
        if order:
            logger.info(
                f"✅ execute_auto_trade: order id={order.id} status={order.status} "
                f"ticker={event.ticker}"
            )
        else:
            logger.debug(
                f"execute_auto_trade: no order created for rule={rule_id} "
                f"event={scanner_event_id}"
            )
        celery_tasks_total.labels(task_name=_task_name, status="success").inc()

    except Exception as exc:
        logger.error(
            f"❌ execute_auto_trade failed rule={rule_id} event={scanner_event_id}: {exc}"
        )
        celery_tasks_total.labels(task_name=_task_name, status="failure").inc()
        db.rollback()
        raise self.retry(exc=exc, countdown=15)
    finally:
        celery_task_duration_seconds.labels(task_name=_task_name).observe(
            _time.monotonic() - _start
        )
        db.close()


@celery_app.task(bind=True, max_retries=1, name="app.tasks.submit_approved_order")
def submit_approved_order(self, order_id: int):
    """
    Submit a manually-approved AutoTradeOrder to IBKR.

    Called by the approve_order endpoint instead of re-queuing execute_auto_trade
    (which would hit the idempotency guard and silently skip the order).
    Reads all sizing values from the stored order — no recalculation.
    """
    from app.models.auto_trade_order import AutoTradeOrder
    from app.services.auto_trade_service import auto_trade_executor

    _task_name = "submit_approved_order"
    _start = _time.monotonic()
    db: Session = SessionLocal()
    try:
        order = db.query(AutoTradeOrder).filter(AutoTradeOrder.id == order_id).first()
        if not order:
            logger.warning(f"submit_approved_order: order {order_id} not found")
            return
        if order.status != "pending":
            logger.warning(
                f"submit_approved_order: order {order_id} has status='{order.status}', "
                f"expected 'pending' — skipping to avoid double-submit"
            )
            return

        auto_trade_executor.submit_existing_order(order, db)
        logger.info(
            f"✅ submit_approved_order: order {order_id} submitted, status={order.status}"
        )
        celery_tasks_total.labels(task_name=_task_name, status="success").inc()

    except Exception as exc:
        logger.error(f"❌ submit_approved_order failed order={order_id}: {exc}")
        celery_tasks_total.labels(task_name=_task_name, status="failure").inc()
        db.rollback()
        raise self.retry(exc=exc, countdown=15)
    finally:
        celery_task_duration_seconds.labels(task_name=_task_name).observe(
            _time.monotonic() - _start
        )
        db.close()


@celery_app.task(bind=True, max_retries=0, name="app.tasks.poll_auto_trade_fills")
def poll_auto_trade_fills(self):
    """
    Poll IBKR for fill updates on submitted/open AutoTradeOrders.

    Runs every minute via Celery Beat during market hours.
    For each open order:
      - "submitted" + entry filled → status=open, create Trade record
      - "open" + exit order filled → status=closed, update Trade record
      - Order disappeared from IBKR open list → status=rejected

    Paper-mode orders simulate an instant fill at trigger_price.
    """
    from app.models.auto_trade_order import AutoTradeOrder

    _task_name = "poll_auto_trade_fills"
    _start = _time.monotonic()
    db: Session = SessionLocal()
    try:
        pending_orders = (
            db.query(AutoTradeOrder)
            .filter(AutoTradeOrder.status.in_(["submitted", "open"]))
            .all()
        )
        if not pending_orders:
            celery_tasks_total.labels(task_name=_task_name, status="success").inc()
            return

        logger.info(
            f"poll_auto_trade_fills: checking {len(pending_orders)} open order(s)"
        )

        # ── Paper mode: simulate fill at trigger price ───────────────────
        paper_orders = [o for o in pending_orders if o.is_paper]
        live_orders = [o for o in pending_orders if not o.is_paper]

        now = datetime.now(timezone.utc).replace(tzinfo=None)

        for order in paper_orders:
            if order.status == "submitted":
                fill_price = float(order.trigger_price or order.entry_price_target or 0)
                _record_entry_fill(order, fill_price, now, db)
            elif order.status == "open":
                _simulate_paper_exit(order, db, now)

        # ── Live mode: query IBKR ────────────────────────────────────────
        if live_orders:
            _poll_live_orders(live_orders, db, now)

        celery_tasks_total.labels(task_name=_task_name, status="success").inc()

    except Exception as exc:
        logger.error(f"❌ poll_auto_trade_fills error: {exc}")
        celery_tasks_total.labels(task_name=_task_name, status="failure").inc()
        db.rollback()
    finally:
        celery_task_duration_seconds.labels(task_name=_task_name).observe(
            _time.monotonic() - _start
        )
        db.close()


# ---------------------------------------------------------------------------
# Fill helpers (called by poll_auto_trade_fills)
# ---------------------------------------------------------------------------


def _check_entry_slippage(
    order: "AutoTradeOrder",  # noqa: F821
    fill_price: float,
    now: "datetime",
    db: "Session",
) -> None:
    """
    Enforce max_slippage_pct: reject the order if fill deviated too far from
    entry_price_target; otherwise delegate to _record_entry_fill.

    Slippage is computed as abs deviation regardless of side, because any
    large deviation from the intended entry invalidates the trade's risk model.
    """
    strategy = order.trading_strategy
    target = order.entry_price_target

    if strategy is not None and target is not None:
        target_f = float(target)
        if target_f > 0:
            slippage_pct = abs(fill_price - target_f) / target_f * 100
            max_slip = float(strategy.max_slippage_pct)
            if slippage_pct > max_slip:
                order.status = "rejected"
                order.rejection_reason = (
                    f"Slippage {slippage_pct:.3f}% exceeded limit {max_slip}% "
                    f"(fill={fill_price}, target={target_f})"
                )
                db.commit()
                logger.warning(
                    f"_check_entry_slippage: order {order.id} rejected — {order.rejection_reason}"
                )
                return

    _record_entry_fill(order, fill_price, now, db)


def _record_entry_fill(
    order: "AutoTradeOrder",  # noqa: F821
    fill_price: float,
    now: "datetime",
    db: "Session",
) -> None:
    """Mark an order as open (entry filled) and create the journal Trade record."""
    from app.models.trade import Trade, TradeExecution

    order.fill_price = fill_price
    order.filled_at = now
    order.status = "open"

    # Create journal Trade
    exec_side = "buy" if order.side == "long" else "sshort"
    trade = Trade(
        symbol=order.symbol,
        status="open",
        side=order.side,
        open_date=now,
        quantity=order.quantity,
        avg_entry_price=fill_price,
        notes=f"Auto-trade order id={order.id} strategy={order.trading_strategy_id}",
    )
    db.add(trade)
    db.flush()  # get trade.id

    execution = TradeExecution(
        trade_id=trade.id,
        timestamp=now,
        side=exec_side,
        price=fill_price,
        quantity=order.quantity,
        external_id=f"auto_trade_order_{order.id}",
    )
    db.add(execution)
    order.trade_id = trade.id
    db.commit()
    logger.info(
        f"poll_auto_trade_fills: entry fill recorded — "
        f"order={order.id} trade={trade.id} price={fill_price}"
    )


def _record_exit_fill(
    order: "AutoTradeOrder",  # noqa: F821
    exit_price: float,
    exit_reason: str,
    now: "datetime",
    db: "Session",
) -> None:
    """Mark an order closed and update the journal Trade."""
    from app.models.trade import Trade, TradeExecution

    order.exit_price = exit_price
    order.exited_at = now
    order.exit_reason = exit_reason
    order.status = "closed"

    if order.trade_id:
        trade = db.query(Trade).filter(Trade.id == order.trade_id).first()
        if trade:
            exec_side = "sell" if order.side == "long" else "scover"
            execution = TradeExecution(
                trade_id=trade.id,
                timestamp=now,
                side=exec_side,
                price=exit_price,
                quantity=order.quantity,
                external_id=f"auto_trade_exit_{order.id}",
            )
            db.add(execution)

            trade.status = "closed"
            trade.close_date = now
            trade.avg_exit_price = exit_price

            # Compute P&L
            if trade.avg_entry_price and trade.quantity:
                entry = float(trade.avg_entry_price)
                qty = float(trade.quantity)
                if order.side == "long":
                    pnl = (exit_price - entry) * qty
                else:
                    pnl = (entry - exit_price) * qty
                trade.gross_pnl = round(pnl, 2)
                trade.net_pnl = round(pnl - float(trade.commissions or 0), 2)
                if entry > 0:
                    trade.return_pct = round(
                        (exit_price - entry)
                        / entry
                        * 100
                        * (1 if order.side == "long" else -1),
                        2,
                    )

    db.commit()
    logger.info(
        f"poll_auto_trade_fills: exit fill recorded — "
        f"order={order.id} price={exit_price} reason={exit_reason}"
    )


def _poll_live_orders(
    orders: list,
    db: "Session",
    now: "datetime",
) -> None:
    """
    Query IBKR for status of live AutoTradeOrders and process any fills.
    Batches all orders into a single IBKR connection to minimise clientId churn.
    """
    from app.providers.ibkr_orders import IBKROrderManager

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        manager = IBKROrderManager()
        open_orders = loop.run_until_complete(manager.get_open_orders())
        open_ids = {o.order_id for o in open_orders}

        for order in orders:
            try:
                parent_id = (
                    int(order.broker_order_id) if order.broker_order_id else None
                )
                stop_id = int(order.broker_stop_id) if order.broker_stop_id else None
                target_id = (
                    int(order.broker_target_id) if order.broker_target_id else None
                )

                if order.status == "submitted":
                    # Check if entry order is filled (no longer in open orders)
                    if parent_id and parent_id not in open_ids:
                        # Fetch fill price from completed orders
                        status = loop.run_until_complete(
                            manager.get_order_status(parent_id)
                        )
                        if status and status.get("filled", 0) > 0:
                            fill_price = float(status["avg_fill_price"])
                            _check_entry_slippage(order, fill_price, now, db)
                        elif status is None:
                            # Order vanished — likely rejected
                            order.status = "rejected"
                            order.rejection_reason = (
                                "Order not found in IBKR after submission"
                            )
                            db.commit()

                elif order.status == "open":
                    # Check if stop or target child is filled
                    for child_id, reason in (
                        (stop_id, "stop"),
                        (target_id, "target"),
                    ):
                        if child_id and child_id not in open_ids:
                            status = loop.run_until_complete(
                                manager.get_order_status(child_id)
                            )
                            if status and status.get("filled", 0) > 0:
                                exit_price = float(status["avg_fill_price"])
                                _record_exit_fill(order, exit_price, reason, now, db)
                                break

            except Exception as exc:
                logger.error(
                    f"poll_auto_trade_fills: error processing order {order.id}: {exc}"
                )

    except Exception as exc:
        logger.error(f"_poll_live_orders: IBKR connection error: {exc}")
    finally:
        loop.close()


def _simulate_paper_exit(
    order: "AutoTradeOrder",  # noqa: F821
    db: "Session",
    now: "datetime",
) -> None:
    from app.providers import DataProviderFactory

    provider = DataProviderFactory.get_or_none("massive")
    if not provider:
        return

    price = provider.get_snapshot_price(order.symbol)
    if price is None:
        return

    stop = float(order.calculated_stop)
    target = float(order.calculated_target)

    if order.side == "long":
        if price >= target:
            _record_exit_fill(order, price, "target", now, db)
        elif price <= stop:
            _record_exit_fill(order, price, "stop", now, db)
    else:  # short
        if price <= target:
            _record_exit_fill(order, price, "target", now, db)
        elif price >= stop:
            _record_exit_fill(order, price, "stop", now, db)
