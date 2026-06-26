"""
AutoTradeExecutor — orchestrates the full auto-trade lifecycle.

Called from the evaluate_scanner_alerts Celery task when a matched AlertRule
has auto_trade=True and a linked TradingStrategy.

Decision flow:
  1. Guard checks (kill-switch, strategy active, session eligibility)
  2. Idempotency: one trade per symbol/strategy/day
  3. Redis distributed lock (30 s) — prevents race between Celery workers
  4. Concurrent-position and daily-trade-count limits
  5. Extract trigger price from ScannerEvent.indicators
  6. Determine side from scanner_type + strategy.direction
  7. Fetch account equity (IBKR) or use paper_account_size (paper mode)
  8. Calculate quantity, stop, target
  9. Persist AutoTradeOrder (status=pending_approval or pending)
  10. Submit bracket order to IBKR (skipped in paper_mode or pending_approval)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Optional

import redis
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.alert_rule import AlertRule
from app.models.auto_trade_order import AutoTradeOrder
from app.models.scanner_event import ScannerEvent
from app.models.scanner_run import ScannerRun
from app.models.system_config import SystemConfig
from app.models.trading_strategy import TradingStrategy
from app.schemas.quality_gate import QualityGatePolicy
from app.services.quality_gate import QualityGateService
from app.utils.time import utc_now

logger = logging.getLogger(__name__)

# ── Supported scanner types and their implied trade direction ─────────────────
# If a scanner type naturally implies bullish momentum → "long"
# Short-biased scanners → "short"
# Unknown / neutral → None (fallback to strategy.direction)
SCANNER_DIRECTION_HINTS: dict[str, str] = {
    "pre_market_volume_spike": "long",
    "live_volume_spike": "long",
    "live_price_move": "long",  # could be either; refined below from indicators
    "oversold_bounce": "long",
    "liquidity_hunt": None,  # depends on sweep direction
}


# ---------------------------------------------------------------------------
# Position sizing result
# ---------------------------------------------------------------------------


@dataclass
class PositionCalc:
    quantity: int
    entry: float  # adjusted limit price, or None for market
    stop: float
    target: float
    risk_amount_usd: float
    stop_distance: float  # $ per share from entry to stop


# ---------------------------------------------------------------------------
# AutoTradeExecutor
# ---------------------------------------------------------------------------


class AutoTradeExecutor:
    """
    Synchronous executor (safe for Celery tasks).

    Async IBKR calls are isolated in _run_async() which creates a fresh
    event loop — the same pattern used by sync_futures_aggregates in tasks.py.
    """

    # Paper account equity used when strategy.paper_mode is True and
    # no IBKR connection is available.  Can be overridden via SystemConfig
    # key "PAPER_ACCOUNT_SIZE".
    DEFAULT_PAPER_EQUITY: float = 100_000.0

    def maybe_execute(
        self,
        rule: AlertRule,
        event: ScannerEvent,
        db: Session,
    ) -> Optional[AutoTradeOrder]:
        """
        Entry point called from evaluate_scanner_alerts Celery task.

        Returns the AutoTradeOrder that was created (any status), or None if
        execution was skipped for any reason.
        """
        # ── 1. Basic guards ──────────────────────────────────────────────
        if not rule.auto_trade or not rule.trading_strategy_id:
            return None

        strategy = (
            db.query(TradingStrategy)
            .filter(
                TradingStrategy.id == rule.trading_strategy_id,
                TradingStrategy.is_active == True,
            )
            .first()
        )
        if not strategy:
            logger.debug(
                f"AutoTradeExecutor: strategy {rule.trading_strategy_id} "
                f"not found or inactive — skipping"
            )
            return None

        # Global kill-switch only blocks live orders, not paper.
        if not strategy.paper_mode:
            cfg = (
                db.query(SystemConfig)
                .filter(SystemConfig.key == "AUTO_TRADING_ENABLED")
                .first()
            )
            if not cfg or cfg.value.lower() != "true":
                logger.info(
                    "AutoTradeExecutor: AUTO_TRADING_ENABLED is off — "
                    "blocking live order for rule %s",
                    rule.id,
                )
                return None

        # ── 1b. max_position_usd required and must be positive for live strategies (R3) ──
        if not strategy.paper_mode and (
            strategy.max_position_usd is None or float(strategy.max_position_usd) <= 0
        ):
            logger.error(
                "AutoTradeExecutor: live strategy '%s' (id=%s) has no valid max_position_usd "
                "(None or <= 0) — refusing live order for rule %s",
                strategy.name,
                strategy.id,
                rule.id,
            )
            return None

        # ── 2. Idempotency — one order per symbol/strategy/day ───────────
        today = datetime.now(timezone.utc).date()
        existing = (
            db.query(AutoTradeOrder)
            .filter(
                AutoTradeOrder.symbol == event.ticker,
                AutoTradeOrder.trading_strategy_id == strategy.id,
                AutoTradeOrder.event_date == today,
            )
            .first()
        )
        if existing:
            logger.debug(
                f"AutoTradeExecutor: order already exists for "
                f"{event.ticker}/strategy={strategy.id}/{today} id={existing.id} — skipping"
            )
            return None

        # ── 2.5. Data quality gate (strict policy) ───────────────────────
        # Re-assess under strict policy — do NOT trust any advisory pre-stamped
        # metadata_["quality_gate"] blob from the scanner run (computed under
        # advisory policy, which does not escalate blocked-severity issues).
        # When universe_id is None (no scanner_run_id linkage), the gate uses
        # policy=off which returns verdict='skipped' (bypassable, not fail-closed).
        try:
            universe_id = self._resolve_universe_id(event, db)
            gate_policy = (
                QualityGatePolicy.strict
                if universe_id is not None
                else QualityGatePolicy.off
            )
            _gate_req = SimpleNamespace(
                policy=gate_policy.value,
                universe_id=universe_id,
                scanner_type=event.scanner_type,
                ticker=event.ticker,
                requirements=None,
            )
            assessment = QualityGateService.assess(db, _gate_req)
        except Exception as exc:
            logger.warning(
                "quality_gate_service_error: ticker=%s event=%s rule=%s error=%s"
                " — failing closed",
                event.ticker,
                event.id,
                rule.id,
                exc,
            )
            return None

        gate_ok = self._gate_passes(assessment, db)
        bypass_used = assessment.verdict == "skipped" and gate_ok
        if not gate_ok:
            logger.warning(
                "quality_gate_refused: ticker=%s event=%s rule=%s"
                " verdict=%s issues=%s warnings=%s bypass_used=%s",
                event.ticker,
                event.id,
                rule.id,
                assessment.verdict,
                assessment.issues,
                assessment.warnings,
                bypass_used,
            )
            return None
        if bypass_used:
            logger.warning(
                "quality_gate_bypass_used: ticker=%s event=%s rule=%s"
                " verdict=skipped bypass=QUALITY_GATE_SKIP_BYPASS",
                event.ticker,
                event.id,
                rule.id,
            )

        # ── 3. Redis distributed lock ────────────────────────────────────
        redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        lock_key = f"auto_trade_lock:{event.ticker}:{strategy.id}:{today}"
        acquired = redis_client.set(lock_key, "1", nx=True, ex=30)
        if not acquired:
            logger.debug(f"AutoTradeExecutor: lock contention on {lock_key} — skipping")
            return None

        try:
            # ── 4. Daily trade count check ───────────────────────────────
            today_start = datetime.combine(today, datetime.min.time())
            today_count = (
                db.query(AutoTradeOrder)
                .filter(
                    AutoTradeOrder.trading_strategy_id == strategy.id,
                    AutoTradeOrder.created_at >= today_start,
                    AutoTradeOrder.status.notin_(["rejected", "error", "cancelled"]),
                )
                .count()
            )
            if today_count >= strategy.max_trades_per_day:
                logger.info(
                    f"AutoTradeExecutor: daily limit reached for strategy "
                    f"'{strategy.name}' ({today_count}/{strategy.max_trades_per_day}) — skipping"
                )
                return None

            # ── 5. Concurrent position check ─────────────────────────────
            open_count = (
                db.query(AutoTradeOrder)
                .filter(
                    AutoTradeOrder.trading_strategy_id == strategy.id,
                    AutoTradeOrder.status.in_(
                        ["submitted", "open", "pending_approval", "pending"]
                    ),
                )
                .count()
            )
            if open_count >= strategy.max_concurrent_positions:
                logger.info(
                    f"AutoTradeExecutor: max concurrent positions reached for strategy "
                    f"'{strategy.name}' ({open_count}/{strategy.max_concurrent_positions}) — skipping"
                )
                return None

            # ── 6. Session eligibility ───────────────────────────────────
            event_session = (event.metadata_ or {}).get("session", "regular")
            allowed = strategy.allowed_sessions or ["regular"]
            if event_session not in allowed:
                logger.info(
                    f"AutoTradeExecutor: session '{event_session}' not in "
                    f"allowed_sessions={allowed} — skipping"
                )
                return None

            # ── 7. Extract trigger price ─────────────────────────────────
            trigger_price = self._extract_trigger_price(event)
            if not trigger_price or trigger_price <= 0:
                logger.warning(
                    f"AutoTradeExecutor: could not extract trigger price from "
                    f"event {event.id} {event.ticker} — skipping"
                )
                return None

            # ── 8. Determine trade side ──────────────────────────────────
            side = self._determine_side(event, strategy)
            if not side:
                logger.info(
                    f"AutoTradeExecutor: direction constraint blocks trade "
                    f"for {event.ticker} — skipping"
                )
                return None

            # ── 9. Account equity ────────────────────────────────────────
            account_equity = self._get_account_equity(strategy, db)
            if account_equity <= 0:
                logger.warning(
                    "AutoTradeExecutor: could not determine account equity — skipping"
                )
                return None

            # ── 10. Position sizing ──────────────────────────────────────
            calc = self._calculate_position(
                strategy, trigger_price, side, account_equity
            )
            if calc.quantity <= 0:
                logger.info(
                    f"AutoTradeExecutor: calculated quantity=0 for "
                    f"{event.ticker} — risk too small or price too high, skipping"
                )
                return None

            # ── 11. Create AutoTradeOrder ────────────────────────────────
            initial_status = (
                "pending_approval" if strategy.requires_approval else "pending"
            )
            order = AutoTradeOrder(
                alert_rule_id=rule.id,
                scanner_event_id=event.id,
                trading_strategy_id=strategy.id,
                symbol=event.ticker,
                side=side,
                event_date=today,
                status=initial_status,
                trigger_price=Decimal(str(round(trigger_price, 4))),
                entry_price_target=Decimal(str(round(calc.entry, 4)))
                if calc.entry
                else None,
                calculated_stop=Decimal(str(round(calc.stop, 4))),
                calculated_target=Decimal(str(round(calc.target, 4))),
                quantity=calc.quantity,
                risk_amount_usd=Decimal(str(round(calc.risk_amount_usd, 2))),
                is_paper=strategy.paper_mode,
            )
            db.add(order)
            db.commit()
            db.refresh(order)

            logger.info(
                f"AutoTradeExecutor: order created id={order.id} "
                f"{side.upper()} {calc.quantity}x {event.ticker} "
                f"entry~{trigger_price:.2f} stop={calc.stop:.2f} target={calc.target:.2f} "
                f"risk=${calc.risk_amount_usd:.0f} status={initial_status} "
                f"paper={strategy.paper_mode}"
            )

            # ── 12. Submit or park ───────────────────────────────────────
            if strategy.requires_approval:
                # Human must approve via /api/trading/orders/{id}/approve
                return order

            if strategy.paper_mode:
                # Paper mode: log intent, mark submitted without touching IBKR
                order.status = "submitted"
                order.broker_order_id = f"PAPER-{order.id}"
                order.broker_stop_id = f"PAPER-STOP-{order.id}"
                order.broker_target_id = f"PAPER-TGT-{order.id}"
                db.commit()
                logger.info(
                    f"AutoTradeExecutor: paper order submitted id={order.id} "
                    f"(no real IBKR call)"
                )
                return order

            # Live order — submit bracket to IBKR
            self._submit_to_ibkr(order, calc, db)
            return order

        except Exception as exc:
            logger.exception(
                f"AutoTradeExecutor: unexpected error for rule={rule.id} "
                f"event={event.id} ticker={event.ticker}: {exc}"
            )
            return None
        finally:
            redis_client.delete(lock_key)

    # ── IBKR submission (live only) ──────────────────────────────────────

    def submit_existing_order(self, order: AutoTradeOrder, db: Session) -> None:
        """
        Submit an already-created AutoTradeOrder to IBKR.

        Used by the approve_order endpoint for orders that were held at
        pending_approval and are now manually approved.  All sizing values
        are read directly from the order record so no recalculation happens.
        """
        entry_price = (
            float(order.entry_price_target)
            if order.entry_price_target is not None
            else None
        )
        calc = PositionCalc(
            quantity=order.quantity or 0,
            entry=entry_price,
            stop=float(order.calculated_stop),
            target=float(order.calculated_target),
            risk_amount_usd=float(order.risk_amount_usd)
            if order.risk_amount_usd
            else 0.0,
            stop_distance=0.0,  # not used by _submit_to_ibkr
        )
        self._submit_to_ibkr(order, calc, db)

    def _submit_to_ibkr(
        self,
        order: AutoTradeOrder,
        calc: PositionCalc,
        db: Session,
    ) -> None:
        """Place the bracket order on IBKR and update the AutoTradeOrder record."""
        from app.providers.ibkr_orders import IBKROrderManager

        order.status = "error"  # pessimistic default; overwritten on success
        db.commit()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            manager = IBKROrderManager()
            result = loop.run_until_complete(
                manager.place_bracket_order(
                    symbol=order.symbol,
                    side=order.side,
                    quantity=order.quantity,
                    entry_price=calc.entry,
                    stop_price=calc.stop,
                    target_price=calc.target,
                    order_ref=str(order.id),
                )
            )
            order.broker_order_id = str(result.parent_order_id)
            order.broker_stop_id = str(result.stop_order_id)
            order.broker_target_id = str(result.target_order_id)
            order.status = "submitted"
            db.commit()
            logger.info(
                f"AutoTradeExecutor: live bracket submitted id={order.id} "
                f"brokerOrderId={result.parent_order_id}"
            )
        except Exception as exc:
            order.status = "error"
            order.rejection_reason = str(exc)
            db.commit()
            logger.error(
                f"AutoTradeExecutor: IBKR submission failed for order {order.id}: {exc}"
            )
        finally:
            loop.close()

    # ── Position sizing ──────────────────────────────────────────────────

    def _calculate_position(
        self,
        strategy: TradingStrategy,
        trigger_price: float,
        side: str,
        account_equity: float,
    ) -> PositionCalc:
        """
        Core sizing math:
          risk_amount = equity * risk_per_trade_pct / 100
          stop_distance = trigger_price * stop_pct / 100
          quantity = floor(risk_amount / stop_distance)
          target = trigger_price + stop_distance * rr  (long)
                   trigger_price - stop_distance * rr  (short)
        """
        risk_pct = float(strategy.risk_per_trade_pct or 1.0)
        stop_pct = float(strategy.stop_pct or 2.0)
        rr = float(strategy.risk_reward_ratio or 2.0)
        limit_offset = float(strategy.limit_offset_pct or 0.0)

        risk_amount = account_equity * risk_pct / 100.0

        # Clamp to max_position_usd
        if strategy.max_position_usd:
            max_pos = float(strategy.max_position_usd)
            # risk on max_position = max_pos * stop_pct / 100
            max_risk = max_pos * stop_pct / 100.0
            risk_amount = min(risk_amount, max_risk)

        # Entry price (adjusted for limit offset)
        if strategy.entry_type == "limit" and limit_offset != 0.0:
            if side == "long":
                entry = trigger_price * (1.0 + limit_offset / 100.0)
            else:
                entry = trigger_price * (1.0 - limit_offset / 100.0)
        else:
            entry = trigger_price  # market order uses trigger as reference

        stop_distance = entry * stop_pct / 100.0

        if side == "long":
            stop = entry - stop_distance
            target = entry + stop_distance * rr
        else:
            stop = entry + stop_distance
            target = entry - stop_distance * rr

        quantity = int(risk_amount / stop_distance) if stop_distance > 0 else 0

        return PositionCalc(
            quantity=quantity,
            entry=entry if strategy.entry_type == "limit" else None,
            stop=round(stop, 2),
            target=round(target, 2),
            risk_amount_usd=round(quantity * stop_distance, 2),
            stop_distance=stop_distance,
        )

    # ── Trigger price extraction ─────────────────────────────────────────

    def _extract_trigger_price(self, event: ScannerEvent) -> Optional[float]:
        """
        Pull the best available price from the ScannerEvent.

        Priority:
          1. indicators["last_trade_price"]
          2. indicators["close"]
          3. indicators["price"]
          4. event.closing_price
          5. event.opening_price
          6. event.previous_close (last resort)
        """
        ind = event.indicators or {}
        for key in ("last_trade_price", "close", "price"):
            v = ind.get(key)
            if v is not None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    pass

        for col in (event.closing_price, event.opening_price, event.previous_close):
            if col is not None:
                try:
                    return float(col)
                except (TypeError, ValueError):
                    pass

        return None

    # ── Side determination ───────────────────────────────────────────────

    def _determine_side(
        self, event: ScannerEvent, strategy: TradingStrategy
    ) -> Optional[str]:
        """
        Resolve "long" or "short" based on scanner type hint and strategy.direction.

        Strategy direction acts as a filter:
          "long_only"  → only "long" trades allowed
          "short_only" → only "short" trades allowed
          "both"       → whatever the scanner hints (default "long" if unknown)
        """
        direction = strategy.direction or "long_only"

        # Derive natural direction from scanner type
        hint = SCANNER_DIRECTION_HINTS.get(event.scanner_type)

        # For live_price_move, check the indicators for actual direction
        if event.scanner_type == "live_price_move":
            ind = event.indicators or {}
            move = ind.get("price_change_pct") or ind.get("move_pct", 0)
            try:
                hint = "long" if float(move) >= 0 else "short"
            except (TypeError, ValueError):
                hint = "long"

        if hint is None:
            hint = "long"  # safe default for unknown scanner types

        if direction == "long_only" and hint != "long":
            return None
        if direction == "short_only" and hint != "short":
            return None

        return hint

    # ── Account equity ───────────────────────────────────────────────────

    def _get_account_equity(self, strategy: TradingStrategy, db: Session) -> float:
        """
        Return account net liquidation value.

        In paper_mode: read PAPER_ACCOUNT_SIZE from SystemConfig or use default.
        In live mode: query IBKR synchronously.
        """
        if strategy.paper_mode:
            cfg = (
                db.query(SystemConfig)
                .filter(SystemConfig.key == "PAPER_ACCOUNT_SIZE")
                .first()
            )
            if cfg:
                try:
                    return float(cfg.value)
                except ValueError:
                    pass
            return self.DEFAULT_PAPER_EQUITY

        # Live: fetch from IBKR
        from app.providers.ibkr_orders import IBKROrderManager

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            manager = IBKROrderManager()
            summary = loop.run_until_complete(manager.get_account_summary())
            return summary.net_liquidation
        except Exception as exc:
            logger.error(f"AutoTradeExecutor: failed to get account equity: {exc}")
            return 0.0
        finally:
            loop.close()

    # ── Quality gate helpers ─────────────────────────────────────────────

    def _resolve_universe_id(self, event: ScannerEvent, db: Session) -> Optional[int]:
        """Canonical universe resolution: event.scanner_run_id → ScannerRun.universe_id.

        Returns None when the run linkage is absent or the run has no universe.
        A None result causes the gate call to use policy=off, which returns
        verdict='skipped' — bypassable via QUALITY_GATE_SKIP_BYPASS.
        """
        if not event.scanner_run_id:
            return None
        run = db.query(ScannerRun).filter(ScannerRun.id == event.scanner_run_id).first()
        return run.universe_id if run else None

    def _gate_passes(self, assessment, db: Session) -> bool:
        """Determine whether the quality gate assessment permits order creation.

        trusted   → allow
        skipped   → allow only if QUALITY_GATE_SKIP_BYPASS SystemConfig key == 'true'
        warning   → refuse (strict policy escalates warnings to blockers)
        blocked   → refuse
        """
        if assessment.verdict == "trusted":
            return True
        if assessment.verdict == "skipped":
            cfg = (
                db.query(SystemConfig)
                .filter(SystemConfig.key == "QUALITY_GATE_SKIP_BYPASS")
                .first()
            )
            bypass_enabled = cfg is not None and cfg.value.lower() == "true"
            return bypass_enabled
        # warning or blocked → always refuse
        return False


# Module-level singleton for import convenience
auto_trade_executor = AutoTradeExecutor()


# ── Service functions extracted from routers/auto_trading.py ─────────────────


def approve_order(
    order: "AutoTradeOrder",
    strategy: "TradingStrategy",
    db: Session,
) -> "AutoTradeOrder":
    """
    Approve a pending_approval order.

    Paper mode: immediately marks submitted.
    Live mode: queues the order for IBKR submission via Celery.
    """
    import logging as _logging

    _logger = _logging.getLogger(__name__)

    if strategy.paper_mode:
        order.status = "submitted"
        order.broker_order_id = f"PAPER-{order.id}"
        order.broker_stop_id = f"PAPER-STOP-{order.id}"
        order.broker_target_id = f"PAPER-TGT-{order.id}"
        db.commit()
        _logger.info(f"Approved paper order id={order.id}")
    else:
        from app.core.celery_app import celery_app as _celery

        order.status = "pending"
        db.commit()
        _celery.send_task(
            "app.tasks.submit_approved_order",
            kwargs={"order_id": order.id},
        )
        _logger.info(f"Approved live order id={order.id}, queued for IBKR submission")

    db.refresh(order)
    return order


def cancel_order(
    order: "AutoTradeOrder",
    db: Session,
) -> "AutoTradeOrder":
    """
    Cancel an active order.

    Paper orders: immediately marks cancelled.
    Live orders: sends cancel to IBKR then marks cancelled.
    Raises RuntimeError if IBKR cancel fails.
    """
    import logging as _logging

    _logger = _logging.getLogger(__name__)

    if (
        not order.is_paper
        and order.broker_order_id
        and order.status in ("submitted", "open")
    ):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            from app.providers.ibkr_orders import IBKROrderManager

            manager = IBKROrderManager()
            loop.run_until_complete(
                manager.cancel_bracket(
                    parent_order_id=int(order.broker_order_id),
                    stop_order_id=int(order.broker_stop_id or 0),
                    target_order_id=int(order.broker_target_id or 0),
                )
            )
        except Exception as exc:
            _logger.error(f"IBKR cancel failed for order {order.id}: {exc}")
            raise RuntimeError(f"IBKR cancel failed: {exc}") from exc
        finally:
            loop.close()

    order.status = "cancelled"
    order.updated_at = utc_now()
    db.commit()
    db.refresh(order)
    _logger.info(f"Cancelled order id={order.id}")
    return order


def get_account() -> dict:
    """
    Fetch live account summary from IBKR.

    Returns a dict with net_liquidation, available_funds, buying_power,
    currency, connected, and open_broker_orders.
    """
    import logging as _logging

    _logger = _logging.getLogger(__name__)

    try:
        from app.providers.ibkr_orders import IBKROrderManager

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            manager = IBKROrderManager()
            account, open_broker_orders = loop.run_until_complete(
                manager.get_account_and_orders()
            )
        finally:
            loop.close()

        return {
            "net_liquidation": account.net_liquidation,
            "available_funds": account.available_funds,
            "buying_power": account.buying_power,
            "currency": account.currency,
            "connected": True,
            "open_broker_orders": [
                {
                    "order_id": o.order_id,
                    "symbol": o.symbol,
                    "action": o.action,
                    "order_type": o.order_type,
                    "quantity": o.total_qty,
                    "status": o.status,
                    "filled": o.filled,
                    "avg_fill_price": o.avg_fill_price,
                }
                for o in open_broker_orders
            ],
        }
    except Exception as exc:
        _logger.warning(f"get_account: IBKR unavailable: {exc}")
        return {
            "net_liquidation": None,
            "available_funds": None,
            "buying_power": None,
            "currency": "USD",
            "connected": False,
            "error": str(exc),
            "open_broker_orders": [],
        }


def get_stats(db: Session, days: int = 30) -> dict:
    """Return auto-trading statistics for the last N days."""
    from datetime import date as date_type
    from datetime import timedelta

    from app.models.trade import Trade

    since = date_type.today() - timedelta(days=days)
    orders = db.query(AutoTradeOrder).filter(AutoTradeOrder.event_date >= since).all()

    total = len(orders)
    by_status: dict = {}
    for o in orders:
        by_status[o.status] = by_status.get(o.status, 0) + 1

    closed = [o for o in orders if o.status == "closed"]
    wins = [
        o
        for o in closed
        if o.exit_price
        and o.fill_price
        and (
            (o.side == "long" and float(o.exit_price) > float(o.fill_price))
            or (o.side == "short" and float(o.exit_price) < float(o.fill_price))
        )
    ]

    trade_ids = [o.trade_id for o in closed if o.trade_id]
    total_pnl = 0.0
    if trade_ids:
        trades = db.query(Trade).filter(Trade.id.in_(trade_ids)).all()
        total_pnl = sum(float(t.gross_pnl or 0) for t in trades)

    return {
        "period_days": days,
        "total_orders": total,
        "by_status": by_status,
        "closed_count": len(closed),
        "win_count": len(wins),
        "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else None,
        "total_pnl": round(total_pnl, 2),
        "avg_pnl_per_trade": round(total_pnl / len(closed), 2) if closed else None,
    }
