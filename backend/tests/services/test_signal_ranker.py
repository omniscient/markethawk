from unittest.mock import MagicMock

import pytest

from app.services.signal_ranker import compute_signal_quality_score, load_ranker_config

_DEFAULT_WEIGHTS = {
    "volume_spike_ratio": 0.35,
    "gap_pct": 0.25,
    "relative_volume": 0.20,
    "volume_anomaly_score": 0.15,
    "float_rotation_pct": 0.05,
}


def test_score_all_features_present():
    indicators = {
        "volume_spike_ratio": 10.0,
        "gap_pct": 10.0,
        "relative_volume": 10.0,
        "volume_anomaly_score": 2.5,
        "float_rotation_pct": 25.0,
    }
    score = compute_signal_quality_score(indicators, _DEFAULT_WEIGHTS)
    assert 0.0 <= score <= 1.0
    assert score == pytest.approx(0.5, abs=0.01)


def test_score_normalizes_over_present_features_only():
    # volume_anomaly_score and float_rotation_pct absent — score re-normalizes to 1.0
    indicators = {
        "volume_spike_ratio": 20.0,
        "gap_pct": 20.0,
        "relative_volume": 20.0,
    }
    score = compute_signal_quality_score(indicators, _DEFAULT_WEIGHTS)
    assert score == pytest.approx(1.0, abs=0.001)


def test_score_caps_at_one():
    weights = {"volume_spike_ratio": 1.0}
    indicators = {"volume_spike_ratio": 999.0}  # far above cap of 20
    score = compute_signal_quality_score(indicators, weights)
    assert score == 1.0


def test_score_gap_pct_uses_abs():
    weights = {"gap_pct": 1.0}
    # Negative gap_pct — abs should be taken before normalization
    score_neg = compute_signal_quality_score({"gap_pct": -5.0}, weights)
    score_pos = compute_signal_quality_score({"gap_pct": 5.0}, weights)
    assert score_neg == pytest.approx(score_pos, abs=0.001)


def test_score_all_features_absent_returns_zero():
    score = compute_signal_quality_score({}, _DEFAULT_WEIGHTS)
    assert score == 0.0


def test_score_returns_float_rounded_to_three_decimals():
    indicators = {"volume_spike_ratio": 5.0}
    weights = {"volume_spike_ratio": 1.0}
    score = compute_signal_quality_score(indicators, weights)
    # Result should be a float with at most 3 decimal places
    assert score == round(score, 3)


def test_score_zero_weight_feature_contributes_nothing():
    weights = {"volume_spike_ratio": 0.0, "gap_pct": 1.0}
    indicators = {"volume_spike_ratio": 20.0, "gap_pct": 10.0}
    score = compute_signal_quality_score(indicators, weights)
    # Only gap_pct contributes; normalized value of 10.0 / 20 cap = 0.5
    assert score == pytest.approx(0.5, abs=0.001)


def test_load_ranker_config_enabled():
    db = MagicMock()
    rows = [
        MagicMock(key="signal_ranker_enabled", value="true"),
        MagicMock(key="signal_ranker_weights", value='{"volume_spike_ratio": 0.35}'),
        MagicMock(key="signal_ranker_version", value="0.1.0-baseline"),
    ]
    db.query.return_value.filter.return_value.all.return_value = rows
    config = load_ranker_config(db)
    assert config["enabled"] is True
    assert config["weights"] == {"volume_spike_ratio": 0.35}
    assert config["version"] == "0.1.0-baseline"


def test_load_ranker_config_disabled_returns_empty_weights():
    db = MagicMock()
    rows = [
        MagicMock(key="signal_ranker_enabled", value="false"),
        MagicMock(key="signal_ranker_weights", value='{"volume_spike_ratio": 0.35}'),
        MagicMock(key="signal_ranker_version", value="0.1.0-baseline"),
    ]
    db.query.return_value.filter.return_value.all.return_value = rows
    config = load_ranker_config(db)
    assert config["enabled"] is False
