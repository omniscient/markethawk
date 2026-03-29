"""
Stats Service - Statistical aggregation and analysis for volume events.
"""

from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy import func, extract, and_
from sqlalchemy.orm import Session

from app.models.volume_event import VolumeEvent

class StatsService:
    """Service for calculating statistical edge data from volume events."""

    @staticmethod
    def get_edge_stats(
        db: Session,
        ticker: Optional[str] = None,
        period: str = "monthly", # weekly, monthly, quarterly
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """Get aggregated statistics for stock gap events."""
        
        query = db.query(VolumeEvent)
        
        if ticker:
            query = query.filter(VolumeEvent.ticker == ticker.upper())
            
        if start_date:
            query = query.filter(VolumeEvent.event_date >= start_date)
            
        if end_date:
            query = query.filter(VolumeEvent.event_date <= end_date)
            
        # Select grouping based on period
        if period == "weekly":
            # Extract week and year
            group_by = [
                extract('year', VolumeEvent.event_date).label('year'),
                extract('week', VolumeEvent.event_date).label('group_val')
            ]
        elif period == "quarterly":
            group_by = [
                extract('year', VolumeEvent.event_date).label('year'),
                extract('quarter', VolumeEvent.event_date).label('group_val')
            ]
        else: # monthly
            group_by = [
                extract('year', VolumeEvent.event_date).label('year'),
                extract('month', VolumeEvent.event_date).label('group_val')
            ]
            
        stats = (
            db.query(
                *group_by,
                func.count(VolumeEvent.id).label('event_count'),
                func.avg(VolumeEvent.gap_pct).label('avg_gap_pct'),
                func.avg(VolumeEvent.fade_from_high_pct).label('avg_fade_pct'),
                func.avg(VolumeEvent.day_range_pct).label('avg_day_range_pct'),
                func.avg(VolumeEvent.relative_volume).label('avg_rel_vol')
            )
            .group_by(*group_by)
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
    def get_distribution_data(db: Session, ticker: Optional[str] = None) -> Dict[str, Any]:
        """Get distribution data for scatter plots and histograms."""
        query = db.query(
            VolumeEvent.gap_pct,
            VolumeEvent.fade_from_high_pct,
            VolumeEvent.day_range_pct,
            VolumeEvent.ticker,
            VolumeEvent.event_date
        )
        
        if ticker:
            query = query.filter(VolumeEvent.ticker == ticker.upper())
            
        events = query.all()
        
        data = []
        for e in events:
            if e.gap_pct is not None and e.fade_from_high_pct is not None:
                data.append({
                    "ticker": e.ticker,
                    "date": e.event_date.isoformat(),
                    "gap_pct": float(e.gap_pct),
                    "fade_pct": float(e.fade_from_high_pct),
                    "day_range_pct": float(e.day_range_pct or 0)
                })
                
        return {"events": data}

# Helper for descending sort in SQLAlchemy
def sa_desc(field):
    from sqlalchemy import desc
    return desc(field)
