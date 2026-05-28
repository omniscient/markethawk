"""
Outcomes router — scanner signal quality and outcome tracking endpoints.
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.scanner_event import ScannerEvent
from app.models.scanner_outcome_snapshot import ScannerOutcomeSnapshot
from app.models.scanner_outcome_summary import ScannerOutcomeSummary
from app.models.signal_analysis_run import SignalAnalysisRun
from app.models.signal_cluster import SignalCluster
from app.schemas.analysis import (
    AnalysisTriggerResponse,
    ClusterReturnInterval,
    ClusterSummary,
    CorrelationResponse,
    FeatureWeight,
    LatestAnalysisResponse,
)
from app.schemas.outcome import (
    BackfillRequest,
    BackfillResponse,
    EventOutcomeResponse,
    ReadinessResponse,
    SignalListResponse,
)
from app.services.data_readiness import DataReadinessService
from app.services.outcome_service import OutcomeService
from app.services.stats import StatsService

router = APIRouter(prefix="/api/outcomes", tags=["outcomes"])


@router.get("/scorecard")
def get_scorecard(
    scanner_type: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    severity: Optional[str] = None,
    db: Session = Depends(get_db),
):
    if not scanner_type:
        raise HTTPException(status_code=400, detail="scanner_type is required")
    return StatsService.get_scorecard(db, scanner_type, start_date, end_date, severity)


@router.get("/scorecard/{scanner_type}")
def get_scorecard_by_type(
    scanner_type: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    severity: Optional[str] = None,
    db: Session = Depends(get_db),
):
    return StatsService.get_scorecard(db, scanner_type, start_date, end_date, severity)


@router.get("/intervals/{scanner_type}")
def get_intervals(
    scanner_type: str,
    interval_key: Optional[str] = None,
    db: Session = Depends(get_db),
):
    return StatsService.get_interval_performance(db, scanner_type, interval_key)


@router.get("/distribution/{scanner_type}")
def get_distribution(
    scanner_type: str,
    metric: str = "mfe_pct",
    db: Session = Depends(get_db),
):
    return StatsService.get_distribution(db, scanner_type, metric)


@router.get("/edge-decay/{scanner_type}")
def get_edge_decay(
    scanner_type: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    period: str = "weekly",
    db: Session = Depends(get_db),
):
    return StatsService.get_edge_decay(db, scanner_type, start_date, end_date, period)


@router.get("/signals/{scanner_type}", response_model=SignalListResponse)
def get_signals(
    scanner_type: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    severity: Optional[str] = None,
    sort_by: str = "event_date",
    sort_order: str = "desc",
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    return StatsService.get_signals(
        db,
        scanner_type,
        start_date,
        end_date,
        severity,
        sort_by,
        sort_order,
        limit,
        offset,
    )


@router.get("/event/{event_id}", response_model=EventOutcomeResponse)
def get_event_outcome(
    event_id: int,
    db: Session = Depends(get_db),
):
    event = db.query(ScannerEvent).filter(ScannerEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    summary = (
        db.query(ScannerOutcomeSummary)
        .filter(ScannerOutcomeSummary.scanner_event_id == event_id)
        .first()
    )
    snapshots = (
        db.query(ScannerOutcomeSnapshot)
        .filter(ScannerOutcomeSnapshot.scanner_event_id == event_id)
        .order_by(ScannerOutcomeSnapshot.interval_key)
        .all()
    )

    return EventOutcomeResponse(summary=summary, snapshots=snapshots)


@router.get("/readiness/{ticker}", response_model=ReadinessResponse)
def get_readiness(
    ticker: str,
    scanner_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    if not scanner_type:
        raise HTTPException(
            status_code=400, detail="scanner_type query param is required"
        )
    report = DataReadinessService.check(db, ticker.upper(), scanner_type)
    return ReadinessResponse(
        ticker=report.ticker,
        scanner_type=report.scanner_type,
        coverages=[
            {
                "timespan": c.timespan,
                "multiplier": c.multiplier,
                "required_from": c.required_from,
                "required_to": c.required_to,
                "available_from": c.available_from,
                "available_to": c.available_to,
                "is_ready": c.is_ready,
            }
            for c in report.coverages
        ],
        is_ready=report.is_ready,
        missing_summary=report.missing_summary,
    )


@router.post("/backfill", response_model=BackfillResponse, status_code=202)
def backfill_outcomes(
    request: BackfillRequest,
    db: Session = Depends(get_db),
):
    events = (
        db.query(ScannerEvent)
        .filter(
            ScannerEvent.scanner_type == request.scanner_type,
            ScannerEvent.event_date >= request.start_date,
            ScannerEvent.event_date <= request.end_date,
        )
        .all()
    )

    snapshots_created = 0
    for event in events:
        existing = (
            db.query(ScannerOutcomeSnapshot)
            .filter(ScannerOutcomeSnapshot.scanner_event_id == event.id)
            .count()
        )
        if existing == 0:
            created = OutcomeService.create_pending_snapshots(db, event)
            snapshots_created += len(created)

    db.flush()

    pending = (
        db.query(ScannerOutcomeSnapshot)
        .join(ScannerEvent, ScannerEvent.id == ScannerOutcomeSnapshot.scanner_event_id)
        .filter(
            ScannerEvent.scanner_type == request.scanner_type,
            ScannerOutcomeSnapshot.status == "pending",
        )
        .all()
    )

    event_ids_touched = set()
    for snapshot in pending:
        OutcomeService.capture_snapshot(db, snapshot)
        event_ids_touched.add(snapshot.scanner_event_id)

    for eid in event_ids_touched:
        OutcomeService.recompute_summary(db, eid)

    db.commit()
    return BackfillResponse(
        snapshots_created=snapshots_created,
        events_processed=len(events),
        scanner_type=request.scanner_type,
    )


@router.post("/analyze", status_code=202, response_model=AnalysisTriggerResponse)
def trigger_signal_analysis(
    scanner_type: Optional[str] = None,
    k: int = 6,
    db: Session = Depends(get_db),
):
    from app.tasks import analyze_signal_features

    result = analyze_signal_features.delay(scanner_type=scanner_type, k=k)
    return AnalysisTriggerResponse(task_id=result.id)


@router.get("/correlations", response_model=CorrelationResponse)
def get_correlations(
    scanner_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = (
        db.query(SignalAnalysisRun)
        .filter(SignalAnalysisRun.status == "completed")
        .order_by(SignalAnalysisRun.created_at.desc())
    )
    if scanner_type:
        query = query.filter(SignalAnalysisRun.scanner_type == scanner_type)
    run = query.first()
    if not run:
        raise HTTPException(status_code=404, detail="No completed analysis run found")

    matrix = run.correlation_matrix or {}
    return CorrelationResponse(
        run_id=run.id,
        scanner_type=run.scanner_type,
        event_count=run.event_count or 0,
        completed_at=run.completed_at,
        features=matrix.get("features", []),
        intervals=matrix.get("intervals", []),
        pearson=matrix.get("pearson", []),
        spearman=matrix.get("spearman", []),
    )


@router.get("/analysis/latest", response_model=LatestAnalysisResponse)
def get_latest_analysis(
    db: Session = Depends(get_db),
):
    run = (
        db.query(SignalAnalysisRun)
        .filter(SignalAnalysisRun.status == "completed")
        .order_by(SignalAnalysisRun.created_at.desc())
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="No completed analysis run found")

    clusters_db = (
        db.query(SignalCluster)
        .filter(SignalCluster.analysis_run_id == run.id)
        .order_by(SignalCluster.cluster_index)
        .all()
    )

    clusters = []
    for c in clusters_db:
        return_profile = {}
        for interval_key, metrics in (c.return_profile or {}).items():
            return_profile[interval_key] = ClusterReturnInterval(**metrics)
        clusters.append(
            ClusterSummary(
                id=c.id,
                label=c.label,
                event_count=c.event_count,
                centroid=c.centroid or {},
                return_profile=return_profile,
            )
        )

    weights = [FeatureWeight(**w) for w in (run.feature_weights or [])]

    return LatestAnalysisResponse(
        run_id=run.id,
        completed_at=run.completed_at,
        feature_weights=weights,
        clusters=clusters,
    )
