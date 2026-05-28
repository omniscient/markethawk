"""
Live scanner publisher — pushes tick data and alerts to Redis.

Tick data flows to:
  stock_updates:{symbol}:second  — raw 5-second bars (consumed by existing WS endpoint)
  stock_updates:{symbol}:minute  — completed 1-minute bars
  watchlist:live_data            — all watchlist ticks/bars (consumed by /ws/watchlist)

Alerts flow to:
  watchlist:alerts               — fired when a scanner condition triggers
"""

import asyncio
import json
import logging
import uuid as uuid_module
from datetime import datetime, timezone

import redis.asyncio as aioredis

from app.core.database import SessionLocal
from app.models.scanner_event import ScannerEvent
from app.services.event_helpers import compute_event_severity, generate_event_summary
from app.services.signal_ranker import compute_signal_quality_score, load_ranker_config
from live_scanner.bar_aggregator import ET, MinuteBar
from live_scanner.conditions import ConditionResult

logger = logging.getLogger(__name__)


class LivePublisher:
    def __init__(self, redis_url: str):
        self._redis_url = redis_url
        self._redis: aioredis.Redis | None = None

    async def connect(self):
        self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
        logger.info("LivePublisher: connected to Redis")

    async def close(self):
        if self._redis:
            await self._redis.aclose()

    # ------------------------------------------------------------------
    # Tick / bar publishing
    # ------------------------------------------------------------------

    async def publish_tick(self, symbol: str, bar) -> None:
        """Publish a raw 5-second IBKR bar to Redis."""
        t = bar.time
        ts_int = int(t.timestamp()) if isinstance(t, datetime) else int(t)
        msg = json.dumps(
            {
                "type": "tick",
                "symbol": symbol,
                "time": ts_int,
                "open": float(bar.open_),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": int(bar.volume),
                "wap": float(bar.wap),
            }
        )
        await self._redis.publish(f"stock_updates:{symbol}:second", msg)
        await self._redis.publish("watchlist:live_data", msg)

    async def publish_quote(self, symbol: str, quote: dict) -> None:
        """Publish a reqMktData price update — fires on every last-price change."""
        msg = json.dumps(
            {
                "type": "quote",
                "symbol": symbol,
                "last": quote["last"],
                "bid": quote.get("bid"),
                "ask": quote.get("ask"),
                "time": quote["time"],
            }
        )
        await self._redis.publish("watchlist:live_data", msg)

    async def publish_minute_bar(self, symbol: str, bar: MinuteBar) -> None:
        """Publish a completed 1-minute bar to Redis."""
        price_change_pct = (
            round((bar.close - bar.prior_close) / bar.prior_close * 100, 2)
            if bar.prior_close > 0
            else 0.0
        )
        msg = json.dumps(
            {
                "type": "minute_bar",
                "symbol": symbol,
                "minute_ts": bar.minute_ts.isoformat(),
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "vwap": bar.vwap,
                "session": bar.session,
                "session_volume": bar.session_volume,
                "minutes_elapsed": bar.minutes_elapsed,
                "prior_close": bar.prior_close,
                "price_change_pct": price_change_pct,
            }
        )
        await self._redis.publish(f"stock_updates:{symbol}:minute", msg)
        await self._redis.publish("watchlist:live_data", msg)

    # ------------------------------------------------------------------
    # Alert publishing
    # ------------------------------------------------------------------

    async def fire_alert_if_new(
        self, bar: MinuteBar, condition: ConditionResult
    ) -> None:
        """
        Dedup → write ScannerEvent to DB → publish to watchlist:alerts.

        Dedup uses Redis SET NX (1-hour window) so we don't spam the same
        alert repeatedly during a sustained move. The DB UniqueConstraint
        provides a hard daily dedup as backup.

        After a successful DB write, evaluate_scanner_alerts is queued so that
        notification rules and auto-trade rules are evaluated — same path as
        the historical scanner.
        """
        dedup_key = f"live_alert_dedup:{bar.symbol}:{condition.scanner_type}"
        acquired = await self._redis.set(dedup_key, "1", nx=True, ex=3600)
        if not acquired:
            return  # Already fired within the last hour

        summary = generate_event_summary(condition.scanner_type, condition.indicators)
        severity = compute_event_severity(condition.scanner_type, condition.indicators)

        # Write to DB in a background thread (sync SQLAlchemy)
        event_id: int | None = None
        try:
            event_id = await asyncio.to_thread(
                self._write_scanner_event, bar, condition, summary, severity
            )
        except Exception as e:
            logger.error(
                f"LivePublisher: DB write failed for {bar.symbol} {condition.scanner_type}: {e}"
            )
            return

        alert_msg = json.dumps(
            {
                "type": "alert",
                "symbol": bar.symbol,
                "scanner_type": condition.scanner_type,
                "summary": summary,
                "severity": severity,
                "indicators": condition.indicators,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        await self._redis.publish("watchlist:alerts", alert_msg)
        logger.info(
            f"LivePublisher: alert fired — {bar.symbol} [{condition.scanner_type}] {summary}"
        )

        # Trigger alert rule evaluation (notifications + auto-trading)
        if event_id:
            try:
                await asyncio.to_thread(self._queue_alert_evaluation, event_id)
            except Exception as e:
                logger.error(
                    f"LivePublisher: failed to queue alert evaluation for event {event_id}: {e}"
                )

    # ------------------------------------------------------------------
    # Internal / synchronous helpers
    # ------------------------------------------------------------------

    def _write_scanner_event(
        self,
        bar: MinuteBar,
        condition: ConditionResult,
        summary: str,
        severity: str,
    ) -> int | None:
        """
        Synchronous DB write — runs via asyncio.to_thread.
        Returns the new ScannerEvent.id, or None if the event already existed.
        """
        from sqlalchemy.exc import IntegrityError

        today = bar.minute_ts.astimezone(ET).date()

        # Fresh config read each event — live scanner is long-running; weights may change
        score = None
        try:
            with SessionLocal() as cfg_session:
                ranker_cfg = load_ranker_config(cfg_session)
            if ranker_cfg.get("enabled") and ranker_cfg.get("weights"):
                score = compute_signal_quality_score(
                    condition.indicators, ranker_cfg["weights"]
                )
        except Exception:
            logger.debug(
                "LivePublisher: signal ranker config load failed — scoring skipped"
            )

        event = ScannerEvent(
            uuid=uuid_module.uuid4(),
            ticker=bar.symbol,
            event_date=today,
            scanner_type=condition.scanner_type,
            summary=summary,
            severity=severity,
            previous_close=bar.prior_close if bar.prior_close > 0 else None,
            closing_price=bar.close,
            indicators=condition.indicators,
            criteria_met=condition.criteria_met,
            metadata_={"source": "live_scanner", "session": bar.session},
            signal_quality_score=score,
        )

        with SessionLocal() as session:
            try:
                session.add(event)
                session.commit()
                session.refresh(event)
                logger.debug(
                    f"LivePublisher: ScannerEvent created — "
                    f"{bar.symbol} {condition.scanner_type} {today}"
                )
                return event.id
            except IntegrityError:
                session.rollback()
                logger.debug(
                    f"LivePublisher: ScannerEvent already exists for "
                    f"{bar.symbol} {condition.scanner_type} {today} — skipping"
                )
                return None

    def _queue_alert_evaluation(self, event_id: int) -> None:
        """
        Queue evaluate_scanner_alerts Celery task for a live-scanner event.
        Runs in a background thread (called via asyncio.to_thread).
        """
        from app.core.celery_app import celery_app

        celery_app.send_task("app.tasks.evaluate_scanner_alerts", args=[event_id])
        logger.debug(
            f"LivePublisher: queued evaluate_scanner_alerts for event {event_id}"
        )
