"""
Data quality gate preflight API (issue #493).

Exposes POST /api/v1/data-quality/gate so product surfaces can request a
trust assessment before running scanner, backtest, or automation workflows.
The router is thin: it validates input, checks the universe exists, then
delegates entirely to QualityGateService.assess() — no policy logic here.
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.rate_limits import SCANNER_LIMIT, limiter
from app.models.stock_universe import StockUniverse
from app.schemas.data_quality import GateRequest
from app.schemas.quality_gate import QualityGateAssessment
from app.services.quality_gate import quality_gate_service
from app.utils.db import get_or_404

router = APIRouter(prefix="/api/v1/data-quality", tags=["data-quality"])


@router.post("/gate", response_model=QualityGateAssessment)
@limiter.limit(SCANNER_LIMIT)
def preflight_gate(
    request: Request,
    body: GateRequest,
    db: Session = Depends(get_db),
) -> QualityGateAssessment:
    """Return a trust assessment for a universe before running a workflow."""
    get_or_404(db, StockUniverse, body.universe_id, "Universe")
    return quality_gate_service.assess(db, body)
