"""
Signal quality ranker — lightweight weighted-sum scorer for ScannerEvents.

Weights are stored in SystemConfig so they can be updated without a code deploy.
"""

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models.system_config import SystemConfig

logger = logging.getLogger(__name__)

# Normalization caps: raw feature value → 0.0–1.0
_NORM_CAPS: dict[str, float] = {
    "volume_spike_ratio": 20.0,
    "gap_pct": 20.0,
    "relative_volume": 20.0,
    "volume_anomaly_score": 5.0,
    "float_rotation_pct": 50.0,
}

_RANKER_KEYS = ["signal_ranker_enabled", "signal_ranker_weights", "signal_ranker_version"]


def _normalize(value: float, feature: str) -> float:
    """Clip raw value to [0, cap] then scale to [0, 1]."""
    cap = _NORM_CAPS.get(feature, 1.0)
    if cap <= 0:
        return 0.0
    return min(abs(value) / cap, 1.0)


def compute_signal_quality_score(indicators: dict[str, Any], weights: dict[str, float]) -> float:
    """
    Weighted sum of normalized feature values, re-normalized over present features.

    Returns a float in [0.0, 1.0] rounded to 3 decimal places.
    """
    if not weights:
        return 0.0

    present = {f: w for f, w in weights.items() if indicators.get(f) is not None}
    if not present:
        return 0.0

    total_weight = sum(present.values())
    if total_weight == 0.0:
        return 0.0

    raw = sum(
        weight * _normalize(indicators[feature], feature)
        for feature, weight in present.items()
    )
    score = raw / total_weight
    return round(min(max(score, 0.0), 1.0), 3)


def load_ranker_config(db: Session) -> dict[str, Any]:
    """
    Load signal ranker configuration from SystemConfig.

    Returns a dict with keys: enabled (bool), weights (dict), version (str).
    """
    rows = db.query(SystemConfig).filter(SystemConfig.key.in_(_RANKER_KEYS)).all()
    cfg = {r.key: r.value for r in rows}

    enabled = cfg.get("signal_ranker_enabled", "false").lower() == "true"
    version = cfg.get("signal_ranker_version", "unknown")

    weights: dict[str, float] = {}
    if enabled:
        raw = cfg.get("signal_ranker_weights", "{}")
        try:
            weights = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning("signal_ranker_weights is not valid JSON — scoring disabled")
            enabled = False

    return {"enabled": enabled, "weights": weights, "version": version}
