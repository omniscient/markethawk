import logging
import time as _time
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.core.metrics import celery_task_duration_seconds, celery_tasks_total
from app.models.scanner_event import ScannerEvent
from app.services.scanner_explanations import reconstruct_explanation_for_event

logger = logging.getLogger(__name__)


def _backfill_scanner_explanations_logic(
    db: Session,
    scanner_type: Optional[str] = None,
    limit: int = 500,
) -> dict:
    base_query = db.query(ScannerEvent)
    if scanner_type:
        base_query = base_query.filter(ScannerEvent.scanner_type == scanner_type)

    missing_explanation = sa.or_(
        ScannerEvent.explanation.is_(None),
        ScannerEvent.explanation == sa.JSON.NULL,
    )
    skipped = base_query.filter(sa.not_(missing_explanation)).count()
    events = (
        base_query.filter(missing_explanation)
        .order_by(ScannerEvent.event_date.desc(), ScannerEvent.id.desc())
        .limit(limit)
        .all()
    )

    updated = 0
    for event in events:
        event.explanation = reconstruct_explanation_for_event(event)
        updated += 1
    db.commit()
    return {"updated": updated, "skipped": skipped}


@celery_app.task(name="app.tasks.backfill_scanner_explanations")
def backfill_scanner_explanations(
    scanner_type: Optional[str] = None,
    limit: int = 500,
) -> dict:
    _task_name = "backfill_scanner_explanations"
    _start = _time.monotonic()
    db: Session = SessionLocal()
    try:
        result = _backfill_scanner_explanations_logic(
            db,
            scanner_type=scanner_type,
            limit=limit,
        )
        celery_tasks_total.labels(task_name=_task_name, status="success").inc()
        return result
    except Exception:
        celery_tasks_total.labels(task_name=_task_name, status="failure").inc()
        logger.exception("backfill_scanner_explanations failed")
        db.rollback()
        raise
    finally:
        celery_task_duration_seconds.labels(task_name=_task_name).observe(
            _time.monotonic() - _start
        )
        db.close()
