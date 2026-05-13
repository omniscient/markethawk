# backend/tests/services/test_timeseries_forecast.py
"""
Unit tests for the timeseries_forecast service.
TimesFM itself is never installed in the test environment, so all tests
exercise the graceful-fallback and pure-math paths only.
"""

import numpy as np
from unittest.mock import MagicMock, patch

from app.services import timeseries_forecast as tf_module
from app.services.timeseries_forecast import get_volume_forecast, compute_anomaly_score


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_model_cache():
    """Reset the module-level lazy-load state between tests."""
    tf_module._timesfm_model = None
    tf_module._timesfm_available = None


def _make_forecast(mean=1_000_000.0, std=200_000.0, p50=950_000.0, p90=1_300_000.0):
    return {"mean": mean, "std": std, "p50": p50, "p90": p90}


# ---------------------------------------------------------------------------
# get_volume_forecast — model unavailable (no timesfm installed)
# ---------------------------------------------------------------------------

def test_get_volume_forecast_returns_none_when_timesfm_missing():
    _reset_model_cache()
    # No mock needed — timesfm is not installed in the test environment
    result = get_volume_forecast("AAPL", [500_000.0] * 60)
    assert result is None


def test_get_volume_forecast_returns_none_for_empty_volumes():
    _reset_model_cache()
    result = get_volume_forecast("AAPL", [])
    assert result is None


def test_get_volume_forecast_caches_unavailable_state():
    """After one failed import, subsequent calls do not re-attempt the import."""
    _reset_model_cache()
    get_volume_forecast("X", [1.0])  # triggers the failed import
    assert tf_module._timesfm_available is False

    # Second call must not change the flag (no re-import attempt)
    get_volume_forecast("X", [1.0])
    assert tf_module._timesfm_available is False


# ---------------------------------------------------------------------------
# get_volume_forecast — model available (mocked)
# ---------------------------------------------------------------------------

def test_get_volume_forecast_with_mocked_model():
    _reset_model_cache()

    mean_log = np.log1p(1_000_000)
    p50_log = np.log1p(900_000)
    p90_log = np.log1p(1_300_000)

    mock_model = MagicMock()
    mock_model.forecast.return_value = (
        [[mean_log]],                          # point_forecast[0][0]
        [[[0.0, p50_log, 0.0, p90_log]]],     # quantile_forecast[0][0][1,3]
    )

    tf_module._timesfm_model = mock_model
    tf_module._timesfm_available = True

    result = get_volume_forecast("AAPL", [500_000.0] * 60)

    assert result is not None
    assert "mean" in result and "std" in result and "p50" in result and "p90" in result
    assert result["mean"] > 0
    assert result["std"] > 0
    assert result["p50"] > 0
    assert result["p90"] > result["p50"]

    _reset_model_cache()


def test_get_volume_forecast_returns_none_on_model_exception():
    _reset_model_cache()

    mock_model = MagicMock()
    mock_model.forecast.side_effect = RuntimeError("GPU OOM")

    tf_module._timesfm_model = mock_model
    tf_module._timesfm_available = True

    result = get_volume_forecast("CRASH", [500_000.0] * 60)
    assert result is None

    _reset_model_cache()


# ---------------------------------------------------------------------------
# compute_anomaly_score
# ---------------------------------------------------------------------------

def test_compute_anomaly_score_positive():
    forecast = _make_forecast(mean=1_000_000, std=200_000)
    score = compute_anomaly_score(1_500_000, forecast)
    assert abs(score - 2.5) < 1e-9


def test_compute_anomaly_score_negative():
    forecast = _make_forecast(mean=1_000_000, std=200_000)
    score = compute_anomaly_score(600_000, forecast)
    assert abs(score - (-2.0)) < 1e-9


def test_compute_anomaly_score_returns_none_for_none_forecast():
    assert compute_anomaly_score(1_000_000, None) is None


def test_compute_anomaly_score_returns_none_for_zero_std():
    forecast = _make_forecast(std=0)
    assert compute_anomaly_score(1_000_000, forecast) is None


def test_compute_anomaly_score_zero_when_equal_to_mean():
    forecast = _make_forecast(mean=1_000_000, std=200_000)
    assert compute_anomaly_score(1_000_000, forecast) == 0.0
