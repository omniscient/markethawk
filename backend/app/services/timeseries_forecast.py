"""
TimesFM volume forecast wrapper.

Lazy-loads the model on first use. Returns None gracefully when the library
is not installed or the model fails to load — callers fall back to static logic.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

_timesfm_model = None
_timesfm_available: Optional[bool] = None


def _get_model():
    """Lazy-load the TimesFM model exactly once per process."""
    global _timesfm_model, _timesfm_available
    if _timesfm_available is None:
        try:
            import timesfm  # noqa: PLC0415

            _timesfm_model = timesfm.TimesFm(
                hparams=timesfm.TimesFmHparams(
                    backend="torch",
                    per_core_batch_size=32,
                    horizon_len=1,
                ),
                checkpoint=timesfm.TimesFmCheckpoint(
                    huggingface_repo_id="google/timesfm-2.5-200m-pytorch"
                ),
            )
            _timesfm_available = True
            logger.info("TimesFM model loaded successfully")
        except Exception as exc:
            logger.warning("TimesFM unavailable — falling back to static threshold: %s", exc)
            _timesfm_available = False

    return _timesfm_model if _timesfm_available else None


def get_volume_forecast(ticker: str, volumes: list[float]) -> Optional[dict]:
    """
    Feed up to 60 daily volumes into TimesFM and return a 1-day-ahead forecast.

    Returns a dict with keys: mean, std, p50, p90 (all in raw share volume units).
    Returns None when the model is unavailable or the input is too short.
    """
    model = _get_model()
    if model is None or len(volumes) < 1:
        return None

    try:
        log_vols = np.log1p(volumes).tolist()
        point_forecast, quantile_forecast = model.forecast(
            inputs=[log_vols],
            freq=[0],
            quantile_levels=[0.25, 0.50, 0.75, 0.90],
        )

        # quantile_forecast shape: [batch, horizon, n_quantiles]
        mean_log = float(point_forecast[0][0])
        p50_log = float(quantile_forecast[0][0][1])   # index 1 → p50
        p90_log = float(quantile_forecast[0][0][3])   # index 3 → p90

        # Approximate std from p90-mean spread (1.28 σ for normal distribution)
        std_log = max((p90_log - mean_log) / 1.28, 1e-6)

        return {
            "mean": float(np.expm1(mean_log)),
            "std": float(np.expm1(mean_log + std_log) - np.expm1(mean_log)),
            "p50": float(np.expm1(p50_log)),
            "p90": float(np.expm1(p90_log)),
        }
    except Exception as exc:
        logger.warning("TimesFM forecast failed for %s: %s", ticker, exc)
        return None


def compute_anomaly_score(actual_volume: float, forecast: dict) -> Optional[float]:
    """Z-score of actual pre-market volume vs. TimesFM forecast distribution."""
    if forecast is None or forecast.get("std", 0) <= 0:
        return None
    return (actual_volume - forecast["mean"]) / forecast["std"]
