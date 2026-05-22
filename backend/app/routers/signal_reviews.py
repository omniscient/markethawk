"""
Signal reviews router — POST/GET /api/signal-reviews.
"""
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.scanner_event import ScannerEvent
from app.models.signal_review import SignalReview
from app.schemas.signal_review import SignalReviewCreate, SignalReviewResponse

router = APIRouter(prefix="/api/signal-reviews", tags=["signal-reviews"])


@router.post("", response_model=SignalReviewResponse, status_code=201)
def create_signal_review(payload: SignalReviewCreate, db: Session = Depends(get_db)):
    event = db.query(ScannerEvent).filter(ScannerEvent.id == payload.scanner_event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="ScannerEvent not found")

    review = SignalReview(
        scanner_event_id=payload.scanner_event_id,
        verdict=payload.verdict,
        reject_reason=payload.reject_reason,
        notes=payload.notes,
        enhance_suggestion=payload.enhance_suggestion,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return review


@router.get("", response_model=List[SignalReviewResponse])
def list_signal_reviews(
    scanner_type: str = Query(...),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    query = (
        db.query(SignalReview, ScannerEvent.ticker, ScannerEvent.event_date, ScannerEvent.scanner_type)
        .join(ScannerEvent, SignalReview.scanner_event_id == ScannerEvent.id)
    )
    # Mirror the liquidity_hunt alias expansion from GET /api/scanner/results
    if scanner_type == "liquidity_hunt":
        query = query.filter(ScannerEvent.scanner_type.in_(["liquidity_hunt", "liquidity_hunt_pre", "liquidity_hunt_post"]))
    else:
        query = query.filter(ScannerEvent.scanner_type == scanner_type)
    if start_date:
        query = query.filter(ScannerEvent.event_date >= start_date)
    if end_date:
        query = query.filter(ScannerEvent.event_date <= end_date)

    rows = query.order_by(ScannerEvent.event_date, ScannerEvent.ticker).all()

    results = []
    for review, ticker, event_date, stype in rows:
        results.append(SignalReviewResponse(
            id=review.id,
            scanner_event_id=review.scanner_event_id,
            verdict=review.verdict,
            reject_reason=review.reject_reason,
            notes=review.notes,
            enhance_suggestion=review.enhance_suggestion,
            reviewed_at=review.reviewed_at,
            reviewed_by=review.reviewed_by,
            ticker=ticker,
            event_date=str(event_date),
            scanner_type=stype,
        ))
    return results
