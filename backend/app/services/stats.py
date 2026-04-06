"""
Stats Service - Statistical aggregation and analysis for volume events.
"""

from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy import func, extract, and_, desc
import sqlalchemy as sa
from sqlalchemy.orm import Session
from sqlalchemy import cast
from sqlalchemy.dialects.postgresql import JSONB

from app.models.scanner_event import ScannerEvent

class StatsService:
    """Service for calculating statistical edge data from volume events."""

    @staticmethod
    def get_edge_stats(
        db: Session,
        ticker: Optional[str] = None,
        scanner_type: Optional[str] = None,
        period: str = "monthly", # weekly, monthly, quarterly
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """Get aggregated statistics for stock gap events."""
        
        # Select grouping based on period
        if period == "weekly":
            group_by = [
                sa.extract('year', ScannerEvent.event_date).label('year'),
                sa.extract('week', ScannerEvent.event_date).label('group_val')
            ]
        elif period == "quarterly":
            group_by = [
                sa.extract('year', ScannerEvent.event_date).label('year'),
                sa.extract('quarter', ScannerEvent.event_date).label('group_val')
            ]
        else: # monthly
            group_by = [
                sa.extract('year', ScannerEvent.event_date).label('year'),
                sa.extract('month', ScannerEvent.event_date).label('group_val')
            ]

        # Helper for JSON extraction
        def json_col(field_name):
            return cast(ScannerEvent.indicators[field_name].astext, sa.Numeric)

        query = db.query(
            *group_by,
            func.count(ScannerEvent.id).label('event_count'),
            func.avg(json_col('gap_pct')).label('avg_gap_pct'),
            func.avg(json_col('fade_from_high_pct')).label('avg_fade_pct'),
            func.avg(json_col('day_range_pct')).label('avg_day_range_pct'),
            func.avg(json_col('relative_volume')).label('avg_rel_vol')
        )
        
        if ticker:
            query = query.filter(ScannerEvent.ticker == ticker.upper())
        if scanner_type:
            query = query.filter(ScannerEvent.scanner_type == scanner_type)
        if start_date:
            query = query.filter(ScannerEvent.event_date >= start_date)
        if end_date:
            query = query.filter(ScannerEvent.event_date <= end_date)

        stats = (
            query.group_by(*group_by)
            .order_by(sa_desc('year'), sa_desc('group_val'))
            .all()
        )
        
        results = []
        for s in stats:
            results.append({
                "period": period,
                "label": f"{int(s.year)}-{int(s.group_val)}",
                "event_count": s.event_count,
                "avg_gap_pct": round(float(s.avg_gap_pct or 0), 2),
                "avg_fade_pct": round(float(s.avg_fade_pct or 0), 2),
                "avg_day_range_pct": round(float(s.avg_day_range_pct or 0), 2),
                "avg_rel_vol": round(float(s.avg_rel_vol or 0), 2)
            })
            
        return results

    @staticmethod
    def get_distribution_data(db: Session, ticker: Optional[str] = None, scanner_type: Optional[str] = None) -> Dict[str, Any]:
        """Get distribution data for scatter plots and histograms."""
        query = db.query(
            ScannerEvent.indicators,
            ScannerEvent.ticker,
            ScannerEvent.event_date
        )
        
        if ticker:
            query = query.filter(ScannerEvent.ticker == ticker.upper())
        if scanner_type:
            query = query.filter(ScannerEvent.scanner_type == scanner_type)
            
        events = query.all()
        
        data = []
        for e in events:
            # Safely extract from indicators
            ind = e.indicators or {}
            gap_pct = ind.get('gap_pct')
            fade_pct = ind.get('fade_from_high_pct')
            
            if gap_pct is not None and fade_pct is not None:
                data.append({
                    "ticker": e.ticker,
                    "date": e.event_date.isoformat(),
                    "gap_pct": float(gap_pct),
                    "fade_pct": float(fade_pct),
                    "day_range_pct": float(ind.get('day_range_pct') or 0)
                })
                
        return {"events": data}

# Helper for descending sort in SQLAlchemy
def sa_desc(field):
    from sqlalchemy import desc
    return desc(field)
