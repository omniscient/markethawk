"""
SignalPipeline: persists TweetSignal to DB, promotes high-confidence CALLOUTs
to ScannerEvent, and publishes to Redis pub/sub channels.

Promotion rule: classification == "CALLOUT" and confidence >= threshold,
one ScannerEvent per ticker per day (unique constraint deduplicates).
"""
from __future__ import annotations

import json
import logging
import uuid as uuid_mod
from datetime import datetime, timezone
from typing import Any, Optional

import redis
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models import MonitoredAccount, TweetSignal, ScannerEvent

logger = logging.getLogger(__name__)

_engine = create_engine(settings.database_url, pool_pre_ping=True)
_SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)

_redis = redis.from_url(settings.redis_url, decode_responses=True)

# Celery task name for alert evaluation (matches backend task registration)
_ALERT_TASK = "app.tasks.evaluate_scanner_alerts"


class SignalPipeline:
    def __init__(self, promotion_threshold: float = settings.promotion_threshold) -> None:
        self.threshold = promotion_threshold

    def process(
        self,
        account: MonitoredAccount,
        raw: dict[str, Any],
        classification: str,
        confidence: float,
        tickers: list[str],
        price_levels: dict[str, Any],
        direction: Optional[str],
    ) -> TweetSignal:
        """Persist tweet signal, optionally promote, publish to Redis."""
        with _SessionLocal() as db:
            signal = self._write_signal(db, account, raw, classification, confidence,
                                        tickers, price_levels, direction)
            if signal and classification == "CALLOUT" and confidence >= self.threshold:
                for ticker in tickers:
                    event_id = self._promote(db, signal, ticker)
                    if event_id:
                        self._queue_alert_evaluation(event_id)

            db.commit()

        self._publish(signal, raw["handle"])
        return signal

    def _write_signal(
        self,
        db: Session,
        account: MonitoredAccount,
        raw: dict[str, Any],
        classification: str,
        confidence: float,
        tickers: list[str],
        price_levels: dict,
        direction: Optional[str],
    ) -> Optional[TweetSignal]:
        posted_at = self._parse_dt(raw["posted_at"])
        signal = TweetSignal(
            account_id=account.id,
            tweet_id=raw["tweet_id"],
            tweet_url=raw["tweet_url"],
            posted_at=posted_at,
            full_text=raw["text"],
            media_urls=raw.get("media_urls", []),
            classification=classification,
            confidence=confidence,
            tickers=tickers,
            price_levels=price_levels,
            direction=direction,
        )
        try:
            db.add(signal)
            db.flush()
            return signal
        except IntegrityError:
            db.rollback()
            logger.debug(f"Duplicate tweet {raw['tweet_id']} — skipped")
            return None

    def _promote(self, db: Session, signal: TweetSignal, ticker: str) -> Optional[int]:
        """Create one ScannerEvent for ticker. Returns event id or None if duplicate."""
        ind = signal.price_levels.get(ticker, {})
        indicators: dict[str, Any] = {
            "confidence": signal.confidence,
            "source_account": signal.account.handle if signal.account else "",
            "direction": signal.direction,
        }
        if ind.get("entry"):
            indicators["price_entry"] = ind["entry"]
        if ind.get("target"):
            indicators["price_target"] = ind["target"]
        if ind.get("stop"):
            indicators["price_stop"] = ind["stop"]

        severity = "high" if signal.confidence > 0.9 else "medium"
        summary = self._build_summary(indicators)

        event = ScannerEvent(
            uuid=str(uuid_mod.uuid4()),
            ticker=ticker,
            event_date=signal.posted_at.date() if hasattr(signal.posted_at, "date") else signal.posted_at,
            scanner_type="social_callout",
            summary=summary,
            severity=severity,
            indicators=indicators,
            criteria_met={
                "has_cashtag": bool(signal.tickers),
                "has_price_level": bool(signal.price_levels),
                "above_confidence_threshold": True,
            },
            metadata_={
                "tweet_id": signal.tweet_id,
                "tweet_url": signal.tweet_url,
                "full_text": signal.full_text,
                "tweet_signal_id": signal.id,
                "source": "tweet_monitor",
            },
            signal_quality_score=signal.confidence,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        try:
            db.add(event)
            db.flush()
            signal.promoted = True
            signal.scanner_event_id = event.id
            signal.promotion_reason = "callout_threshold"
            logger.info(f"Promoted tweet {signal.tweet_id} → ScannerEvent {event.id} [{ticker}]")
            return event.id
        except IntegrityError:
            db.rollback()
            logger.debug(f"Duplicate ScannerEvent for {ticker} — skipped")
            return None

    def _queue_alert_evaluation(self, event_id: int) -> None:
        try:
            from celery import Celery
            app = Celery(broker=settings.redis_url)
            app.send_task(_ALERT_TASK, args=[event_id])
        except Exception as exc:
            logger.warning(f"Failed to queue alert evaluation for event {event_id}: {exc}")

    def _publish(self, signal: Optional[TweetSignal], handle: str) -> None:
        if not signal:
            return
        payload = json.dumps({
            "id": signal.id,
            "tweet_id": signal.tweet_id,
            "tweet_url": signal.tweet_url,
            "handle": handle,
            "full_text": signal.full_text,
            "classification": signal.classification,
            "confidence": signal.confidence,
            "tickers": signal.tickers,
            "direction": signal.direction,
            "promoted": signal.promoted,
            "posted_at": signal.posted_at.isoformat() if signal.posted_at else None,
        })
        try:
            _redis.publish("tweet_signals:all", payload)
            if signal.promoted:
                for ticker in signal.tickers:
                    _redis.publish(f"tweet_signals:{ticker}", payload)
        except Exception as exc:
            logger.warning(f"Redis publish failed: {exc}")

    @staticmethod
    def _parse_dt(value: Any) -> datetime:
        if isinstance(value, datetime):
            return value.replace(tzinfo=None) if value.tzinfo else value
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return dt.replace(tzinfo=None)
        except Exception:
            return datetime.now(timezone.utc).replace(tzinfo=None)

    @staticmethod
    def _build_summary(indicators: dict) -> str:
        account = indicators.get("source_account", "?")
        direction = indicators.get("direction", "")
        conf = indicators.get("confidence", 0)
        entry = indicators.get("price_entry")
        target = indicators.get("price_target")
        s = f"@{account} {direction} callout" if direction else f"@{account} callout"
        if entry:
            s += f" ${entry:.2f}"
        if target:
            s += f" → ${target:.2f}"
        s += f" (conf {conf:.0%})"
        return s
