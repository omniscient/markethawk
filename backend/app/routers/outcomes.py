"""
Outcomes router — scanner signal quality and outcome tracking endpoints.
"""

from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError
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
from app.schemas.common import OutcomeDateRange
from app.schemas.outcome import (
    BackfillRequest,
    BackfillResponse,
    EventOutcomeResponse,
    ReadinessResponse,
    SignalListResponse,
)
from app.schemas.regime import RegimeBreakdownResponse
from app.services.ai_signal_brief import AISignalBriefService
from app.services.analyst_qa_service import AnalystQAService
from app.services.data_readiness import DataReadinessService
from app.services.embedding_service import EmbeddingService
from app.services.explanation_archetype_service import ExplanationArchetypeService
from app.services.explanation_trait_performance import (
    ExplanationTraitPerformanceService,
)
from app.services.historical_analog_service import HistoricalAnalogService
from app.services.outcome_service import OutcomeService
from app.services.scanner_event_narrative import ScannerEventNarrativeService
from app.services.semantic_signal_search import SemanticSignalSearchService
from app.services.signal_post_mortem import SignalPostMortemService
from app.services.stats import StatsService
from app.utils.db import get_or_404

router = APIRouter(prefix="/api/v1/outcomes", tags=["outcomes"])


def get_outcome_date_range(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> OutcomeDateRange:
    """Validate the shared outcomes date-range query params (366-day cap, F-INPUT-02).

    A bare ``Depends(OutcomeDateRange)`` would surface a Pydantic ValidationError as
    a 500; building the model here lets us return the correct 422 instead.
    """
    try:
        return OutcomeDateRange(start_date=start_date, end_date=end_date)
    except ValidationError as exc:
        # Only the message strings are JSON-serializable; the raw error dicts
        # carry the originating ValueError in ctx, which would 500 on render.
        raise HTTPException(
            status_code=422,
            detail="; ".join(e["msg"] for e in exc.errors()),
        ) from exc


def _analog_event_payload(event: ScannerEvent) -> dict[str, Any]:
    explanation = event.explanation or {}
    return {
        "id": event.id,
        "ticker": event.ticker,
        "event_date": event.event_date.isoformat() if event.event_date else None,
        "scanner_type": event.scanner_type,
        "summary": event.summary,
        "severity": event.severity,
        "why": list(explanation.get("why") or []),
        "criteria_passed": _criteria_payload(explanation.get("criteria_passed") or {}),
        "criteria_failed": _criteria_payload(explanation.get("criteria_failed") or {}),
        "warnings": [
            {
                "code": str(warning.get("code") or "quality_warning"),
                "severity": warning.get("severity"),
                "message": warning.get("message") or warning.get("code"),
                "affected_inputs": warning.get("affected_inputs") or [],
            }
            for warning in explanation.get("data_quality_warnings") or []
        ],
    }


def _criteria_payload(criteria: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "key": key,
            "label": criterion.get("label") or key,
            "observed": criterion.get("observed"),
            "threshold": criterion.get("threshold"),
            "operator": criterion.get("operator"),
            "importance": criterion.get("importance"),
        }
        for key, criterion in sorted(criteria.items())
    ]


@router.get("/scorecard")
def get_scorecard(
    scanner_type: Optional[str] = None,
    date_range: OutcomeDateRange = Depends(get_outcome_date_range),
    severity: Optional[str] = None,
    regime: Optional[str] = None,
    include_warnings: bool = False,
    include_all: bool = False,
    review_window_days: int = Query(default=90, ge=1, le=365),
    db: Session = Depends(get_db),
):
    if not scanner_type:
        raise HTTPException(status_code=400, detail="scanner_type is required")
    return StatsService.get_scorecard(
        db,
        scanner_type,
        date_range.start_date,
        date_range.end_date,
        severity,
        regime=regime,
        include_warnings=include_warnings,
        include_all=include_all,
        review_window_days=review_window_days,
    )


@router.get("/scorecard/{scanner_type}")
def get_scorecard_by_type(
    scanner_type: str,
    date_range: OutcomeDateRange = Depends(get_outcome_date_range),
    severity: Optional[str] = None,
    regime: Optional[str] = None,
    include_warnings: bool = False,
    include_all: bool = False,
    review_window_days: int = Query(default=90, ge=1, le=365),
    db: Session = Depends(get_db),
):
    return StatsService.get_scorecard(
        db,
        scanner_type,
        date_range.start_date,
        date_range.end_date,
        severity,
        regime=regime,
        include_warnings=include_warnings,
        include_all=include_all,
        review_window_days=review_window_days,
    )


@router.get("/traits/{scanner_type}")
def get_explanation_trait_performance(
    scanner_type: str,
    date_range: OutcomeDateRange = Depends(get_outcome_date_range),
    severity: Optional[str] = None,
    min_sample_size: int = Query(default=5, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return ExplanationTraitPerformanceService().aggregate(
        db,
        scanner_type=scanner_type,
        start_date=date_range.start_date,
        end_date=date_range.end_date,
        severity=severity,
        min_sample_size=min_sample_size,
    )


@router.get("/archetypes/{scanner_type}")
def get_explanation_archetypes(
    scanner_type: str,
    date_range: OutcomeDateRange = Depends(get_outcome_date_range),
    severity: Optional[str] = None,
    min_sample_size: int = Query(default=5, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return ExplanationArchetypeService().latest_performance(
        db,
        scanner_type=scanner_type,
        start_date=date_range.start_date,
        end_date=date_range.end_date,
        severity=severity,
        min_sample_size=min_sample_size,
    )


@router.get("/regime-breakdown/{scanner_type}", response_model=RegimeBreakdownResponse)
def get_regime_breakdown(
    scanner_type: str,
    date_range: OutcomeDateRange = Depends(get_outcome_date_range),
    db: Session = Depends(get_db),
):
    result = StatsService.get_regime_breakdown(
        db, scanner_type, date_range.start_date, date_range.end_date
    )
    return RegimeBreakdownResponse(**result)


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
    date_range: OutcomeDateRange = Depends(get_outcome_date_range),
    period: str = "weekly",
    db: Session = Depends(get_db),
):
    return StatsService.get_edge_decay(
        db, scanner_type, date_range.start_date, date_range.end_date, period
    )


@router.get("/signals/{scanner_type}", response_model=SignalListResponse)
def get_signals(
    scanner_type: str,
    date_range: OutcomeDateRange = Depends(get_outcome_date_range),
    severity: Optional[str] = None,
    sort_by: str = "event_date",
    sort_order: str = "desc",
    limit: int = Query(100, ge=1, le=200),
    offset: int = 0,
    db: Session = Depends(get_db),
):
    return StatsService.get_signals(
        db,
        scanner_type,
        date_range.start_date,
        date_range.end_date,
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
    get_or_404(db, ScannerEvent, event_id, "ScannerEvent")

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


@router.get("/semantic-search")
def semantic_search(
    query: str = Query(..., min_length=1),
    top_k: int = Query(default=10, ge=1, le=50),
    source_type: list[str] | None = Query(default=None),
    db: Session = Depends(get_db),
):
    return EmbeddingService().search(
        db,
        query_text=query,
        top_k=top_k,
        source_types=source_type,
    )


@router.get("/semantic-signal-search")
def semantic_signal_search(
    query: str = Query(..., min_length=1),
    top_k: int = Query(default=10, ge=1, le=50),
    source_type: list[str] | None = Query(default=None),
    db: Session = Depends(get_db),
):
    return SemanticSignalSearchService().find_for_text(
        db,
        query_text=query,
        top_k=top_k,
        source_types=source_type,
    )


@router.get("/analyst-qa")
def analyst_qa_for_events(
    question: str = Query(..., min_length=1),
    scanner_type: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return AnalystQAService().answer_for_events(
        db,
        question=question,
        scanner_type=scanner_type,
        limit=limit,
    )


@router.get("/event/{event_id}/ai-signal-brief")
def get_ai_signal_brief(
    event_id: int,
    db: Session = Depends(get_db),
):
    event = get_or_404(db, ScannerEvent, event_id, "ScannerEvent")
    return AISignalBriefService().build(db, event)


@router.get("/event/{event_id}/ai-signal-narrative")
def get_ai_signal_narrative(
    event_id: int,
    db: Session = Depends(get_db),
):
    event = get_or_404(db, ScannerEvent, event_id, "ScannerEvent")
    return ScannerEventNarrativeService().build(db, event)


@router.get("/event/{event_id}/signal-post-mortem")
def get_signal_post_mortem(
    event_id: int,
    db: Session = Depends(get_db),
):
    event = get_or_404(db, ScannerEvent, event_id, "ScannerEvent")
    return SignalPostMortemService().build(db, event)


@router.get("/event/{event_id}/semantic-matches")
def get_event_semantic_matches(
    event_id: int,
    top_k: int = Query(default=10, ge=1, le=50),
    source_type: list[str] | None = Query(default=None),
    db: Session = Depends(get_db),
):
    event = get_or_404(db, ScannerEvent, event_id, "ScannerEvent")
    return SemanticSignalSearchService().find_for_event(
        db,
        event,
        top_k=top_k,
        source_types=source_type,
    )


@router.get("/event/{event_id}/analyst-qa")
def analyst_qa_for_event(
    event_id: int,
    question: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
):
    event = get_or_404(db, ScannerEvent, event_id, "ScannerEvent")
    return AnalystQAService().answer_for_event(db, event, question=question)


@router.get("/event/{event_id}/historical-analogs")
def get_historical_analogs(
    event_id: int,
    limit: int = Query(default=5, ge=1, le=25),
    min_sample_size: int = Query(default=5, ge=1, le=100),
    same_scanner_only: bool = True,
    db: Session = Depends(get_db),
):
    target = get_or_404(db, ScannerEvent, event_id, "ScannerEvent")
    result = HistoricalAnalogService().find_similar_events(
        db,
        target_event_id=target.id,
        limit=limit,
        min_sample_size=min_sample_size,
        same_scanner_only=same_scanner_only,
    )
    analog_ids = [analog["event_id"] for analog in result["analogs"]]
    events_by_id = {
        event.id: event
        for event in db.query(ScannerEvent).filter(ScannerEvent.id.in_(analog_ids)).all()
    }
    return {
        **result,
        "target_event": _analog_event_payload(target),
        "analogs": [
            {
                **analog,
                "event": _analog_event_payload(events_by_id[analog["event_id"]]),
            }
            for analog in result["analogs"]
            if analog["event_id"] in events_by_id
        ],
    }


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
