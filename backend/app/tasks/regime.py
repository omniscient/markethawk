"""
Celery tasks for HMM regime model training and back-labeling.
"""

import logging

from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.services.regime_service import RegimeService

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=0, name="app.tasks.update_regime_model")
def update_regime_model(self):
    """Re-train HMM on rolling 2-year SPY window; write new model to DB + Redis cache."""
    db = SessionLocal()
    try:
        result = RegimeService.train_and_persist(db)
        if result:
            logger.info(
                "update_regime_model: done; n_states=%d version=%d",
                result.n_states,
                result.version,
            )
        else:
            logger.warning(
                "update_regime_model: train_and_persist returned None (no SPY data?)"
            )
    except Exception as exc:
        logger.exception("update_regime_model: failed: %s", exc)
        raise
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=0, name="app.tasks.backfill_regime_labels")
def backfill_regime_labels(self):
    """One-time task: back-label all ScannerEvent rows where regime IS NULL."""
    from app.models.scanner_event import ScannerEvent

    db = SessionLocal()
    try:
        null_dates = (
            db.query(ScannerEvent.event_date)
            .filter(ScannerEvent.regime.is_(None))
            .distinct()
            .all()
        )
        unique_dates = [row.event_date for row in null_dates]
        logger.info(
            "backfill_regime_labels: %d unique dates to label", len(unique_dates)
        )

        labeled = 0
        for event_date in unique_dates:
            regime = RegimeService.get_regime_at_date(db, event_date)
            if regime:
                count = (
                    db.query(ScannerEvent)
                    .filter(
                        ScannerEvent.event_date == event_date,
                        ScannerEvent.regime.is_(None),
                    )
                    .update({"regime": regime})
                )
                labeled += count

        db.commit()
        logger.info(
            "backfill_regime_labels: labeled %d rows across %d dates",
            labeled,
            len(unique_dates),
        )
    except Exception as exc:
        logger.exception("backfill_regime_labels: failed: %s", exc)
        db.rollback()
        raise
    finally:
        db.close()
