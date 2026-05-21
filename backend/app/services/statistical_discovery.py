"""
StatisticalDiscoveryService — pure computation methods for signal analysis.
All methods are stateless; they receive DataFrames and return typed dicts/lists.
"""

import logging
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
import lightgbm as lgb
import shap

logger = logging.getLogger(__name__)

MIN_NULL_FRACTION = 0.5


class StatisticalDiscoveryService:

    def build_feature_matrix(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Accepts a raw DataFrame with columns event_id, interval_key, pct_change,
        and arbitrary feature columns. Drops feature columns where > 50% of values
        are NULL. Coerces remaining columns to float, dropping un-coercible ones.
        Returns the cleaned DataFrame (pct_change retained, event_id and
        interval_key retained as index/grouping columns).
        """
        reserved = {"event_id", "interval_key", "pct_change"}
        feature_cols = [c for c in df.columns if c not in reserved]

        keep = []
        for col in feature_cols:
            null_frac = df[col].isna().mean()
            if null_frac >= MIN_NULL_FRACTION:
                logger.debug("Dropping sparse column %s (null_frac=%.2f)", col, null_frac)
                continue
            try:
                df[col] = pd.to_numeric(df[col], errors="raise")
                keep.append(col)
            except (ValueError, TypeError):
                logger.debug("Dropping non-numeric column %s", col)

        cols = list(reserved & set(df.columns)) + keep
        result = df[cols].copy()
        result = result.dropna(subset=keep)
        return result

    def compute_correlations(self, df: pd.DataFrame) -> dict[str, Any]:
        """
        Computes Pearson and Spearman correlation for each (feature × interval_key) pair.
        Returns a dict with keys: features, intervals, pearson (list[list[float]]),
        spearman (list[list[float]]).
        """
        reserved = {"event_id", "interval_key", "pct_change"}
        feature_cols = [c for c in df.columns if c not in reserved]
        intervals = sorted(df["interval_key"].unique().tolist())

        pearson_matrix: list[list[float]] = []
        spearman_matrix: list[list[float]] = []

        for feature in feature_cols:
            p_row: list[float] = []
            s_row: list[float] = []
            for interval in intervals:
                subset = df[df["interval_key"] == interval][[feature, "pct_change"]].dropna()
                if len(subset) < 10:
                    p_row.append(0.0)
                    s_row.append(0.0)
                    continue
                p_r, _ = scipy_stats.pearsonr(subset[feature], subset["pct_change"])
                s_r, _ = scipy_stats.spearmanr(subset[feature], subset["pct_change"])
                p_row.append(round(float(p_r), 4))
                s_row.append(round(float(s_r), 4))
            pearson_matrix.append(p_row)
            spearman_matrix.append(s_row)

        return {
            "features": feature_cols,
            "intervals": intervals,
            "pearson": pearson_matrix,
            "spearman": spearman_matrix,
        }

    def compute_shap_weights(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        """
        For each interval_key, fits LGBMRegressor and computes mean |SHAP| per feature.
        Returns list of dicts sorted by shap_importance desc, each with
        feature, interval, shap_importance, rank.
        """
        reserved = {"event_id", "interval_key", "pct_change"}
        feature_cols = [c for c in df.columns if c not in reserved]
        intervals = sorted(df["interval_key"].unique().tolist())

        all_weights: list[dict[str, Any]] = []
        for interval in intervals:
            subset = df[df["interval_key"] == interval][feature_cols + ["pct_change"]].dropna()
            if len(subset) < 50:
                logger.warning("Skipping SHAP for interval %s — only %d rows", interval, len(subset))
                continue
            X = subset[feature_cols].values
            y = subset["pct_change"].values

            model = lgb.LGBMRegressor(n_estimators=100, max_depth=4, verbose=-1)
            model.fit(X, y)

            explainer = shap.TreeExplainer(model)
            shap_values = explainer.shap_values(X)
            mean_shap = np.abs(shap_values).mean(axis=0)

            for feat, importance in zip(feature_cols, mean_shap):
                all_weights.append({
                    "feature": feat,
                    "interval": interval,
                    "shap_importance": round(float(importance), 6),
                    "rank": 0,
                })

        all_weights.sort(key=lambda w: w["shap_importance"], reverse=True)
        for i, w in enumerate(all_weights, start=1):
            w["rank"] = i

        return all_weights

    def run_kmeans(
        self, df: pd.DataFrame, k: int = 6
    ) -> tuple[dict[int, int], list[dict[str, float]]]:
        """
        Fits KMeans on standardised per-event feature vectors (one row per event_id,
        features averaged across intervals). Returns (labels, centroids) where labels
        is {event_id: cluster_index} and centroids is a list of k dicts
        {feature: centroid_value}.
        """
        reserved = {"event_id", "interval_key", "pct_change"}
        feature_cols = [c for c in df.columns if c not in reserved]

        event_features = (
            df.groupby("event_id")[feature_cols]
            .mean()
            .dropna()
        )

        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(event_features.values)

        km = KMeans(n_clusters=k, random_state=42, n_init=10)
        km.fit(X_scaled)

        labels: dict[int, int] = {
            int(eid): int(label)
            for eid, label in zip(event_features.index, km.labels_)
        }

        centroid_values = scaler.inverse_transform(km.cluster_centers_)
        centroids: list[dict[str, float]] = [
            {feat: round(float(val), 4) for feat, val in zip(feature_cols, row)}
            for row in centroid_values
        ]

        return labels, centroids

    def compute_conditional_stats(
        self,
        df: pd.DataFrame,
        labels: dict[int, int],
    ) -> dict[int, dict[str, dict[str, Any]]]:
        """
        For each cluster × interval, computes median_pct, win_rate, sharpe, n.
        Returns nested dict: {cluster_index: {interval_key: {metric: value}}}.
        """
        df = df.copy()
        df["cluster"] = df["event_id"].map(labels)
        df = df.dropna(subset=["cluster"])
        df["cluster"] = df["cluster"].astype(int)

        result: dict[int, dict[str, dict[str, Any]]] = {}
        for cluster_idx in sorted(df["cluster"].unique()):
            cluster_df = df[df["cluster"] == cluster_idx]
            result[cluster_idx] = {}
            for interval in sorted(cluster_df["interval_key"].unique()):
                subset = cluster_df[cluster_df["interval_key"] == interval]["pct_change"].dropna()
                n = len(subset)
                if n == 0:
                    result[cluster_idx][interval] = {"median_pct": 0.0, "win_rate": 0.0, "sharpe": 0.0, "n": 0}
                    continue
                median_pct = float(subset.median())
                win_rate = float((subset > 0).mean())
                std = float(subset.std())
                sharpe = float(subset.mean() / std) if std > 0 else 0.0
                result[cluster_idx][interval] = {
                    "median_pct": round(median_pct, 4),
                    "win_rate": round(win_rate, 4),
                    "sharpe": round(sharpe, 4),
                    "n": n,
                }

        return result

    def generate_label(
        self, centroid: dict[str, float], global_mean: dict[str, float]
    ) -> str:
        """
        Auto-generates a human label from the top 2 features with highest absolute
        centroid deviation from the global mean.
        """
        deviations = {
            feat: abs(centroid.get(feat, 0.0) - global_mean.get(feat, 0.0))
            for feat in centroid
        }
        top_two = sorted(deviations, key=lambda f: deviations[f], reverse=True)[:2]
        if not top_two:
            return "cluster"
        parts = []
        for feat in top_two:
            val = centroid.get(feat, 0.0)
            mean_val = global_mean.get(feat, 0.0)
            qualifier = "high" if val > mean_val else "low"
            parts.append(f"{qualifier} {feat}")
        return " + ".join(parts)
