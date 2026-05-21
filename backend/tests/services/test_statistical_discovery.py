"""Unit tests for StatisticalDiscoveryService."""
import pytest
import numpy as np
import pandas as pd
from app.services.statistical_discovery import StatisticalDiscoveryService


def _make_df(n: int = 600, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic feature matrix with 3 features, 2 intervals, n rows."""
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        gap_pct = rng.uniform(0.5, 5.0)
        rel_vol = rng.uniform(1.5, 8.0)
        fade_pct = rng.uniform(-3.0, 3.0)
        for interval in ["1h", "eod"]:
            noise = rng.normal(0, 0.5)
            pct_change = 0.3 * gap_pct + 0.2 * rel_vol + noise
            rows.append({
                "event_id": i,
                "interval_key": interval,
                "gap_pct": gap_pct,
                "relative_volume": rel_vol,
                "fade_pct": fade_pct,
                "pct_change": pct_change,
            })
    return pd.DataFrame(rows)


def _make_sparse_df() -> pd.DataFrame:
    """DataFrame with > 50% NULLs in one feature — should be dropped."""
    rng = np.random.default_rng(0)
    rows = []
    for i in range(600):
        rows.append({
            "event_id": i,
            "interval_key": "1h",
            "gap_pct": rng.uniform(0.5, 5.0),
            "sparse_feature": np.nan if i < 400 else rng.uniform(0, 1),
            "pct_change": rng.normal(1.0, 0.5),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# build_feature_matrix
# ---------------------------------------------------------------------------

def test_build_feature_matrix_returns_dataframe():
    svc = StatisticalDiscoveryService()
    df = _make_df()
    result = svc.build_feature_matrix(df)
    assert isinstance(result, pd.DataFrame)
    assert "pct_change" in result.columns


def test_build_feature_matrix_drops_sparse_columns():
    svc = StatisticalDiscoveryService()
    df = _make_sparse_df()
    result = svc.build_feature_matrix(df)
    assert "sparse_feature" not in result.columns


def test_build_feature_matrix_retains_dense_columns():
    svc = StatisticalDiscoveryService()
    df = _make_df()
    result = svc.build_feature_matrix(df)
    for col in ("gap_pct", "relative_volume", "fade_pct"):
        assert col in result.columns


# ---------------------------------------------------------------------------
# compute_correlations
# ---------------------------------------------------------------------------

def test_compute_correlations_shape():
    svc = StatisticalDiscoveryService()
    df = svc.build_feature_matrix(_make_df())
    result = svc.compute_correlations(df)
    features = result["features"]
    intervals = result["intervals"]
    assert len(result["pearson"]) == len(features)
    assert len(result["pearson"][0]) == len(intervals)
    assert len(result["spearman"]) == len(features)


def test_compute_correlations_values_in_range():
    svc = StatisticalDiscoveryService()
    df = svc.build_feature_matrix(_make_df())
    result = svc.compute_correlations(df)
    for row in result["pearson"]:
        for val in row:
            assert -1.0 <= val <= 1.0, f"Pearson out of range: {val}"
    for row in result["spearman"]:
        for val in row:
            assert -1.0 <= val <= 1.0, f"Spearman out of range: {val}"


# ---------------------------------------------------------------------------
# compute_shap_weights
# ---------------------------------------------------------------------------

def test_compute_shap_weights_returns_list():
    svc = StatisticalDiscoveryService()
    df = svc.build_feature_matrix(_make_df())
    weights = svc.compute_shap_weights(df)
    assert isinstance(weights, list)
    assert len(weights) > 0


def test_compute_shap_weights_have_required_keys():
    svc = StatisticalDiscoveryService()
    df = svc.build_feature_matrix(_make_df())
    weights = svc.compute_shap_weights(df)
    for w in weights:
        assert "feature" in w
        assert "interval" in w
        assert "shap_importance" in w
        assert "rank" in w


def test_compute_shap_weights_sorted_by_importance():
    svc = StatisticalDiscoveryService()
    df = svc.build_feature_matrix(_make_df())
    weights = svc.compute_shap_weights(df)
    importances = [w["shap_importance"] for w in weights]
    assert importances == sorted(importances, reverse=True)


# ---------------------------------------------------------------------------
# run_kmeans
# ---------------------------------------------------------------------------

def test_run_kmeans_returns_labels_and_centroids():
    svc = StatisticalDiscoveryService()
    df = svc.build_feature_matrix(_make_df())
    labels, centroids = svc.run_kmeans(df, k=4)
    assert len(labels) == len(df["event_id"].unique())
    assert len(centroids) == 4


def test_run_kmeans_cluster_indices_within_k():
    svc = StatisticalDiscoveryService()
    df = svc.build_feature_matrix(_make_df())
    labels, _ = svc.run_kmeans(df, k=4)
    for label in labels.values():
        assert 0 <= label < 4


# ---------------------------------------------------------------------------
# compute_conditional_stats
# ---------------------------------------------------------------------------

def test_compute_conditional_stats_keys():
    svc = StatisticalDiscoveryService()
    df = svc.build_feature_matrix(_make_df())
    labels, _ = svc.run_kmeans(df, k=4)
    stats = svc.compute_conditional_stats(df, labels)
    assert isinstance(stats, dict)
    for cluster_idx, intervals in stats.items():
        assert isinstance(intervals, dict)
        for interval_key, metrics in intervals.items():
            for key in ("median_pct", "win_rate", "sharpe", "n"):
                assert key in metrics, f"Missing {key} in cluster {cluster_idx} / {interval_key}"


# ---------------------------------------------------------------------------
# generate_label
# ---------------------------------------------------------------------------

def test_generate_label_returns_string():
    svc = StatisticalDiscoveryService()
    centroid = {"gap_pct": 4.5, "relative_volume": 2.0, "fade_pct": 0.1}
    global_mean = {"gap_pct": 2.0, "relative_volume": 3.5, "fade_pct": 0.5}
    label = svc.generate_label(centroid, global_mean)
    assert isinstance(label, str)
    assert len(label) > 0
