from pydantic import BaseModel, ConfigDict
from typing import Optional, Any
from datetime import datetime


class AnalysisTriggerResponse(BaseModel):
    task_id: str


class CorrelationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_id: int
    scanner_type: Optional[str]
    event_count: int
    completed_at: datetime
    features: list[str]
    intervals: list[str]
    pearson: list[list[float]]
    spearman: list[list[float]]


class FeatureWeight(BaseModel):
    feature: str
    interval: str
    shap_importance: float
    rank: int


class ClusterReturnInterval(BaseModel):
    median_pct: float
    win_rate: float
    sharpe: float
    n: int


class ClusterSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str
    event_count: int
    centroid: dict[str, float]
    return_profile: dict[str, ClusterReturnInterval]


class LatestAnalysisResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_id: int
    completed_at: datetime
    feature_weights: list[FeatureWeight]
    clusters: list[ClusterSummary]
