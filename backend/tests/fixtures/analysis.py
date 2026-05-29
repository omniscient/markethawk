"""
Seed helpers for signal analysis tests.
"""

from datetime import datetime, timezone

from app.models.signal_analysis_run import SignalAnalysisRun
from app.models.signal_cluster import SignalCluster
from sqlalchemy.orm import Session


def seed_completed_analysis_run(db: Session) -> SignalAnalysisRun:
    run = SignalAnalysisRun(
        scanner_type=None,
        status="completed",
        event_count=750,
        correlation_matrix={
            "features": ["gap_pct", "relative_volume"],
            "intervals": ["1h", "eod"],
            "pearson": [[0.12, 0.18], [0.22, 0.30]],
            "spearman": [[0.14, 0.19], [0.24, 0.31]],
        },
        feature_weights=[
            {
                "feature": "relative_volume",
                "interval": "1h",
                "shap_importance": 0.034,
                "rank": 1,
            },
            {
                "feature": "gap_pct",
                "interval": "eod",
                "shap_importance": 0.028,
                "rank": 2,
            },
        ],
        completed_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(run)
    db.flush()

    cluster = SignalCluster(
        analysis_run_id=run.id,
        cluster_index=0,
        label="high relative_volume + low gap_pct",
        centroid={"relative_volume": 4.2, "gap_pct": 0.8},
        return_profile={
            "1h": {"median_pct": 0.8, "win_rate": 0.58, "sharpe": 0.9, "n": 375},
            "eod": {"median_pct": 1.4, "win_rate": 0.62, "sharpe": 1.1, "n": 375},
        },
        event_count=375,
    )
    db.add(cluster)
    db.flush()
    return run
