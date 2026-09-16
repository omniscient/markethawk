"""
Scanner Service — public facade.

All heavy logic lives in focused sibling modules:
  session_metrics.py      — calculate_day_metrics_*
  scan_enrichment.py      — _get_batch_enrichment_data_*
  pre_market_scan.py      — run_pre_market_scan (body)
  oversold_bounce_scan.py — run_oversold_bounce_scan (body)
"""

from datetime import date
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.monitored_stock import MonitoredStock
from app.services.scan_enrichment import (
    _get_batch_enrichment_data as _enrich,
)
from app.services.scan_enrichment import (
    _get_batch_enrichment_data_impl as _enrich_impl,
)
from app.services.session_metrics import (
    calculate_day_metrics as _calc_metrics,
)
from app.services.session_metrics import (
    calculate_day_metrics_from_aggs as _calc_metrics_from_aggs,
)
from app.services.signal_ranker import (
    load_ranker_config,  # noqa: F401 — test patch target
)
from app.services.timeseries_forecast import (  # noqa: F401 — test patch target
    compute_anomaly_score,
    get_volume_forecast,
)
from app.utils.session import get_market_today

if TYPE_CHECKING:
    from app.models.scanner_run import ScannerRun


class ScannerService:
    """Thin facade — delegates to focused submodules. Public API unchanged."""

    # ------------------------------------------------------------------ #
    #  Session metrics (→ session_metrics.py)                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def calculate_day_metrics_from_aggs(aggs: List) -> Dict[str, Any]:
        return _calc_metrics_from_aggs(aggs)

    @staticmethod
    def calculate_day_metrics(
        ticker: str, event_date: date, db: Session
    ) -> Dict[str, Any]:
        return _calc_metrics(ticker, event_date, db)

    # ------------------------------------------------------------------ #
    #  Utility helpers (stay on facade — small, heavily referenced)       #
    # ------------------------------------------------------------------ #

    @staticmethod
    def default_scan_date() -> date:
        """Most recent completed trading weekday."""
        from datetime import timedelta as _td

        d = get_market_today() - _td(days=1)
        while d.weekday() >= 5:
            d -= _td(days=1)
        return d

    @staticmethod
    def check_concurrency(
        redis_url: str, universe_id: int, scanner_type: str
    ) -> Optional[dict]:
        import json

        import redis as _redis

        r = _redis.Redis.from_url(redis_url, decode_responses=True)
        state_key = f"universe:{universe_id}:scan:{scanner_type}"
        existing = r.get(state_key)
        if existing:
            try:
                return json.loads(existing)
            except json.JSONDecodeError:
                r.delete(state_key)
        return None

    @staticmethod
    def resolve_date_range(
        start_date: Optional[date], end_date: Optional[date]
    ) -> tuple:
        resolved_start = start_date or ScannerService.default_scan_date()
        resolved_end = end_date or resolved_start
        if resolved_end < resolved_start:
            raise ValueError("end_date must not be before start_date")
        return resolved_start, resolved_end

    @staticmethod
    def count_active_tickers(db: Session, universe_id: int) -> int:
        return (
            db.query(MonitoredStock)
            .filter(
                MonitoredStock.universe_id == universe_id,
                MonitoredStock.is_active.is_(True),
            )
            .count()
        )

    # ------------------------------------------------------------------ #
    #  Batch enrichment (→ scan_enrichment.py)                            #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _get_batch_enrichment_data(
        tickers: List[str], event_date: date, db: Session
    ) -> Tuple:
        return _enrich(tickers, event_date, db)

    @staticmethod
    def _get_batch_enrichment_data_impl(
        tickers: List[str], event_date: date, db: Session
    ) -> Tuple:
        return _enrich_impl(tickers, event_date, db)

    # ------------------------------------------------------------------ #
    #  _save_event stays here (thin wrapper, heavily referenced)          #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _save_event(
        db: Session,
        ticker: str,
        event_date: date,
        scanner_type: str,
        indicators: Dict[str, Any],
        criteria_met: Dict[str, Any],
        enrichment: Dict[str, Any],
        previous_close: float = None,
        opening_price: float = None,
        closing_price: float = None,
        ranker_config: Optional[Dict[str, Any]] = None,
        gate_metadata: Optional[Dict[str, Any]] = None,
        explanation: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        from app.services.alert_service import save_event

        return save_event(
            db=db,
            ticker=ticker,
            event_date=event_date,
            scanner_type=scanner_type,
            indicators=indicators,
            criteria_met=criteria_met,
            enrichment=enrichment,
            previous_close=previous_close,
            opening_price=opening_price,
            closing_price=closing_price,
            ranker_config=ranker_config,
            gate_metadata=gate_metadata,
            explanation=explanation,
        )

    # ------------------------------------------------------------------ #
    #  Scan runners — lazy import shims (avoid load-time cycle)           #
    # ------------------------------------------------------------------ #

    @staticmethod
    async def run_pre_market_scan(
        tickers: List[str],
        db: Session,
        event_date: date = None,
        scanner_run: Optional["ScannerRun"] = None,
    ) -> List[Dict[str, Any]]:
        from app.services.pre_market_scan import run_pre_market_scan as _impl

        return await _impl(tickers, db, event_date=event_date, scanner_run=scanner_run)

    @staticmethod
    async def run_oversold_bounce_scan(
        tickers: List[str],
        db: Session,
        event_date: date = None,
        scanner_run: Optional["ScannerRun"] = None,
    ) -> List[Dict[str, Any]]:
        from app.services.oversold_bounce_scan import run_oversold_bounce_scan as _impl

        return await _impl(tickers, db, event_date=event_date, scanner_run=scanner_run)

    # ------------------------------------------------------------------ #
    #  Date convenience wrappers (stay on facade — tiny, named callers)   #
    # ------------------------------------------------------------------ #

    @staticmethod
    async def run_pre_market_scan_for_date(
        ticker: str, event_date: date, db: Session
    ) -> List[Dict[str, Any]]:
        return await ScannerService.run_pre_market_scan(
            [ticker], db, event_date=event_date
        )

    @staticmethod
    async def run_oversold_bounce_scan_for_date(
        ticker: str, event_date: date, db: Session
    ) -> List[Dict[str, Any]]:
        return await ScannerService.run_oversold_bounce_scan(
            [ticker], db, event_date=event_date
        )
