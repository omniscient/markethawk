# Statistical Discovery Engine — Phase 2b Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Phase 2b statistical discovery pipeline: a Celery task that analyses completed signal outcomes using correlation analysis (Pearson + Spearman), LightGBM + SHAP feature importance, and K-means clustering — persisting results in two new tables and surfacing them via three new API endpoints and a new CorrelationHeatmap component in EdgeExplorer.

**Architecture:**
- `StatisticalDiscoveryService` — pure-Python service (numpy/pandas/scipy/sklearn/lightgbm/shap) with no DB dependencies; receives DataFrames in, returns typed results out
- `analyze_signal_features` Celery task — orchestrates the service methods, persists results to `SignalAnalysisRun` and `SignalCluster`, back-fills `ScannerEvent.signal_cluster_id`
- Three new endpoints on the existing `/api/outcomes` router (POST trigger, GET correlations, GET latest analysis)
- `CorrelationHeatmap` React component + new EdgeExplorer card — no new npm packages

**Tech Stack:** FastAPI, SQLAlchemy, Celery, lightgbm, shap, scikit-learn, scipy, React 18, TypeScript, React Query, Tailwind CSS

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/requirements.txt` | Modify | Add lightgbm, shap, scikit-learn, scipy |
| `backend/app/models/signal_analysis_run.py` | Create | SignalAnalysisRun ORM model |
| `backend/app/models/signal_cluster.py` | Create | SignalCluster ORM model |
| `backend/app/models/scanner_event.py` | Modify | Add signal_cluster_id FK column |
| `backend/app/models/__init__.py` | Modify | Register new models |
| `backend/app/alembic/versions/<hash>_add_signal_analysis_tables.py` | Create | Migration for new tables + column |
| `backend/app/services/statistical_discovery.py` | Create | Pure-Python computation service |
| `backend/app/schemas/analysis.py` | Create | Pydantic schemas for API responses |
| `backend/app/tasks.py` | Modify | Add analyze_signal_features task |
| `backend/app/core/celery_app.py` | Modify | Add nightly Beat schedule entry |
| `backend/app/routers/outcomes.py` | Modify | Add 3 new endpoints |
| `backend/tests/services/test_statistical_discovery.py` | Create | Unit tests for service methods |
| `backend/tests/api/test_analysis.py` | Create | Integration tests for 3 new endpoints |
| `backend/tests/fixtures/analysis.py` | Create | DB seed helpers for analysis tests |
| `frontend/src/api/analysis.ts` | Create | Axios API layer for analysis endpoints |
| `frontend/src/components/CorrelationHeatmap.tsx` | Create | Table-based heatmap component |
| `frontend/src/pages/EdgeExplorer.tsx` | Modify | Add Feature Correlations card |

---

## Task 1: Add Python dependencies

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Append new dependencies to requirements.txt**

Open `backend/requirements.txt` and add after the `pandas` line:

```
lightgbm==4.6.0
shap==0.47.2
scikit-learn==1.6.1
scipy==1.15.3
```

- [ ] **Step 2: Verify install inside Docker**

```bash
docker-compose exec backend pip install lightgbm==4.6.0 shap==0.47.2 scikit-learn==1.6.1 scipy==1.15.3
```

Expected output ends with: `Successfully installed lightgbm-4.6.0 shap-0.47.2 scikit-learn-1.6.1 scipy-1.15.3` (order may vary; already-installed transitive deps show as "already satisfied").

- [ ] **Step 3: Commit**

```bash
git add backend/requirements.txt
git commit -m "feat(discovery): add lightgbm, shap, scikit-learn, scipy dependencies"
```

---

## Task 2: Create SignalAnalysisRun and SignalCluster models + migration

**Files:**
- Create: `backend/app/models/signal_analysis_run.py`
- Create: `backend/app/models/signal_cluster.py`
- Modify: `backend/app/models/scanner_event.py`
- Modify: `backend/app/models/__init__.py`
- Create: migration file

- [ ] **Step 1: Create SignalAnalysisRun model**

Create `backend/app/models/signal_analysis_run.py`:

```python
"""
SignalAnalysisRun SQLAlchemy model.
"""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base


class SignalAnalysisRun(Base):
    """Anchor table for each statistical analysis execution."""

    __tablename__ = "signal_analysis_runs"

    id = Column(Integer, primary_key=True, index=True)
    scanner_type = Column(String(50), nullable=True, index=True)
    status = Column(String(20), nullable=False, default="pending", index=True)
    event_count = Column(Integer, nullable=True)
    correlation_matrix = Column(JSONB, nullable=True)
    feature_weights = Column(JSONB, nullable=True)
    celery_task_id = Column(String(255), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        index=True,
    )
    completed_at = Column(DateTime, nullable=True)
```

- [ ] **Step 2: Create SignalCluster model**

Create `backend/app/models/signal_cluster.py`:

```python
"""
SignalCluster SQLAlchemy model.
"""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.schema import Index

from app.core.database import Base


class SignalCluster(Base):
    """One row per cluster archetype produced by a single analysis run."""

    __tablename__ = "signal_clusters"

    id = Column(Integer, primary_key=True, index=True)
    analysis_run_id = Column(
        Integer, ForeignKey("signal_analysis_runs.id"), nullable=False
    )
    cluster_index = Column(Integer, nullable=False)
    label = Column(String(200), nullable=False)
    centroid = Column(JSONB, nullable=False, default=dict)
    return_profile = Column(JSONB, nullable=False, default=dict)
    event_count = Column(Integer, nullable=False, default=0)
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )

    __table_args__ = (
        Index("ix_signal_clusters_analysis_run_id", "analysis_run_id"),
    )
```

- [ ] **Step 3: Add signal_cluster_id to ScannerEvent**

In `backend/app/models/scanner_event.py`, add this import and column:

After the existing imports, add `ForeignKey` to the sqlalchemy import line:
```python
from sqlalchemy import Column, Integer, String, DateTime, Date, Numeric, ForeignKey, Uuid as UUID, UniqueConstraint
```

After `updated_at`, before `__table_args__`, add:
```python
    signal_cluster_id = Column(
        Integer, ForeignKey("signal_clusters.id"), nullable=True, index=True
    )
```

- [ ] **Step 4: Register models in __init__.py**

In `backend/app/models/__init__.py`, add after the `ScannerOutcomeSummary` import:
```python
from app.models.signal_analysis_run import SignalAnalysisRun
from app.models.signal_cluster import SignalCluster
```

Add to `__all__`:
```python
    "SignalAnalysisRun",
    "SignalCluster",
```

- [ ] **Step 5: Verify models load**

```bash
docker-compose exec backend python -c "from app.models import SignalAnalysisRun, SignalCluster; print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Generate and apply migration**

```bash
docker-compose exec backend python -m alembic revision --autogenerate -m "add_signal_analysis_tables"
docker-compose exec backend python -m alembic upgrade head
```

Expected: migration file created in `app/alembic/versions/`, upgrade prints `Running upgrade ... -> <hash>`.

**Important**: Open the generated migration file and verify the `upgrade()` function creates `signal_analysis_runs` before `signal_clusters` and both before the `signal_cluster_id` column is added to `scanner_events`. If the ordering is wrong, reorder the `op.create_table()` calls manually before applying.

Verify tables exist:
```bash
docker-compose exec backend python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
result = db.execute(text(\"SELECT tablename FROM pg_tables WHERE tablename IN ('signal_analysis_runs', 'signal_clusters')\")).fetchall()
print([r[0] for r in result])
db.close()
"
```

Expected: `['signal_analysis_runs', 'signal_clusters']`

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/signal_analysis_run.py backend/app/models/signal_cluster.py backend/app/models/scanner_event.py backend/app/models/__init__.py backend/app/alembic/versions/
git commit -m "feat(discovery): add SignalAnalysisRun, SignalCluster models and migration"
```

---

## Task 3: Create StatisticalDiscoveryService (TDD)

**Files:**
- Create: `backend/tests/services/test_statistical_discovery.py`
- Create: `backend/app/services/statistical_discovery.py`

- [ ] **Step 1: Write failing unit tests**

Create `backend/tests/services/test_statistical_discovery.py`:

```python
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
```

- [ ] **Step 2: Run tests — verify all fail**

```bash
docker-compose exec backend python -m pytest tests/services/test_statistical_discovery.py -v 2>&1 | tail -20
```

Expected: `ERROR` or `ImportError` because service module doesn't exist yet.

- [ ] **Step 3: Create StatisticalDiscoveryService**

Create `backend/app/services/statistical_discovery.py`:

```python
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
```

- [ ] **Step 4: Run tests — verify all pass**

```bash
docker-compose exec backend python -m pytest tests/services/test_statistical_discovery.py -v 2>&1 | tail -30
```

Expected: all tests pass, output ends with `passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/services/test_statistical_discovery.py backend/app/services/statistical_discovery.py
git commit -m "feat(discovery): add StatisticalDiscoveryService with unit tests"
```

---

## Task 4: Add analyze_signal_features Celery task + Beat schedule

**Files:**
- Modify: `backend/app/tasks.py`
- Modify: `backend/app/core/celery_app.py`

- [ ] **Step 1: Add task to tasks.py**

At the end of `backend/app/tasks.py`, append (all model/service imports are local inside the function body, matching the existing pattern in this file — see lines 763, 822):

```python
@celery_app.task(bind=True, max_retries=1, name='app.tasks.analyze_signal_features')
def analyze_signal_features(self, scanner_type: str | None = None, k: int = 6):
    import pandas as pd
    from app.models.scanner_event import ScannerEvent
    from app.models.signal_analysis_run import SignalAnalysisRun
    from app.models.signal_cluster import SignalCluster
    from app.models.scanner_outcome_summary import ScannerOutcomeSummary
    from app.models.scanner_outcome_snapshot import ScannerOutcomeSnapshot
    from app.services.statistical_discovery import StatisticalDiscoveryService

    db: Session = SessionLocal()
    try:
        run = SignalAnalysisRun(
            status="running",
            scanner_type=scanner_type,
            celery_task_id=self.request.id,
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        # --- Query complete events with snapshots ---
        query = (
            db.query(
                ScannerEvent.id.label("event_id"),
                ScannerEvent.scanner_type,
                ScannerEvent.indicators,
                ScannerOutcomeSnapshot.interval_key,
                ScannerOutcomeSnapshot.pct_change,
            )
            .join(
                ScannerOutcomeSummary,
                ScannerOutcomeSummary.scanner_event_id == ScannerEvent.id,
            )
            .join(
                ScannerOutcomeSnapshot,
                ScannerOutcomeSnapshot.scanner_event_id == ScannerEvent.id,
            )
            .filter(
                ScannerOutcomeSummary.is_complete.is_(True),
                ScannerOutcomeSnapshot.status == "captured",
            )
        )
        if scanner_type:
            query = query.filter(ScannerEvent.scanner_type == scanner_type)

        rows = query.all()

        unique_event_ids = {r.event_id for r in rows}
        if len(unique_event_ids) < 500:
            run.status = "failed"
            run.error_message = f"Insufficient data (n={len(unique_event_ids)} events, min=500)"
            db.commit()
            logger.info("analyze_signal_features: insufficient data (%d events)", len(unique_event_ids))
            return

        # --- Build feature matrix ---
        flat_rows = []
        for r in rows:
            indicators = r.indicators or {}
            row = {
                "event_id": r.event_id,
                "interval_key": r.interval_key,
                "pct_change": float(r.pct_change) if r.pct_change is not None else None,
            }
            for k_feat, v in indicators.items():
                try:
                    row[k_feat] = float(v)
                except (TypeError, ValueError):
                    row[k_feat] = None
            flat_rows.append(row)

        raw_df = pd.DataFrame(flat_rows)
        svc = StatisticalDiscoveryService()
        df = svc.build_feature_matrix(raw_df)

        # --- Correlations ---
        correlation_matrix = svc.compute_correlations(df)
        run.correlation_matrix = correlation_matrix

        # --- SHAP feature weights ---
        feature_weights = svc.compute_shap_weights(df)
        run.feature_weights = feature_weights

        # --- K-means clustering ---
        cluster_labels, centroids = svc.run_kmeans(df, k=k)
        conditional_stats = svc.compute_conditional_stats(df, cluster_labels)

        feature_cols = [
            c for c in df.columns
            if c not in {"event_id", "interval_key", "pct_change"}
        ]
        global_mean = {feat: float(df[feat].mean()) for feat in feature_cols}

        cluster_id_map: dict[int, int] = {}
        for cluster_idx, centroid in enumerate(centroids):
            label = svc.generate_label(centroid, global_mean)
            event_count = sum(1 for v in cluster_labels.values() if v == cluster_idx)
            cluster = SignalCluster(
                analysis_run_id=run.id,
                cluster_index=cluster_idx,
                label=label,
                centroid=centroid,
                return_profile=conditional_stats.get(cluster_idx, {}),
                event_count=event_count,
            )
            db.add(cluster)
            db.flush()
            cluster_id_map[cluster_idx] = cluster.id

        # --- Back-fill ScannerEvent.signal_cluster_id ---
        for event_id, cluster_idx in cluster_labels.items():
            db.query(ScannerEvent).filter(ScannerEvent.id == event_id).update(
                {"signal_cluster_id": cluster_id_map[cluster_idx]},
                synchronize_session=False,
            )

        run.status = "completed"
        run.event_count = len(unique_event_ids)
        run.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
        logger.info("analyze_signal_features: completed (events=%d)", len(rows))

    except Exception as exc:
        logger.exception("analyze_signal_features failed: %s", exc)
        try:
            run.status = "failed"
            run.error_message = str(exc)
            db.commit()
        except Exception:
            pass
        raise
    finally:
        db.close()
```

- [ ] **Step 2: Add Beat schedule entry to celery_app.py**

In `backend/app/core/celery_app.py`, inside `celery_app.conf.beat_schedule`, add:

```python
    'analyze-signal-features-nightly': {
        'task': 'app.tasks.analyze_signal_features',
        'schedule': crontab(minute='0', hour='11', day_of_week='1-5'),
    },
```

- [ ] **Step 3: Verify task registers**

```bash
docker-compose exec backend python -c "from app.tasks import analyze_signal_features; print(analyze_signal_features.name)"
```

Expected: `app.tasks.analyze_signal_features`

- [ ] **Step 4: Commit**

```bash
git add backend/app/tasks.py backend/app/core/celery_app.py
git commit -m "feat(discovery): add analyze_signal_features Celery task and nightly Beat schedule"
```

---

## Task 5: Add analysis schemas

**Files:**
- Create: `backend/app/schemas/analysis.py`

- [ ] **Step 1: Create analysis schemas**

Create `backend/app/schemas/analysis.py`:

```python
from pydantic import BaseModel
from typing import Optional, Any
from datetime import datetime


class AnalysisTriggerResponse(BaseModel):
    task_id: str


class CorrelationResponse(BaseModel):
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
    id: int
    label: str
    event_count: int
    centroid: dict[str, float]
    return_profile: dict[str, ClusterReturnInterval]


class LatestAnalysisResponse(BaseModel):
    run_id: int
    completed_at: datetime
    feature_weights: list[FeatureWeight]
    clusters: list[ClusterSummary]
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/schemas/analysis.py
git commit -m "feat(discovery): add analysis Pydantic schemas"
```

---

## Task 6: Add API endpoints (TDD)

**Files:**
- Create: `backend/tests/fixtures/analysis.py`
- Create: `backend/tests/api/test_analysis.py`
- Modify: `backend/app/routers/outcomes.py`

- [ ] **Step 1: Create seed fixture**

Create `backend/tests/fixtures/analysis.py`:

```python
"""
Seed helpers for signal analysis tests.
"""
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models.signal_analysis_run import SignalAnalysisRun
from app.models.signal_cluster import SignalCluster


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
            {"feature": "relative_volume", "interval": "1h", "shap_importance": 0.034, "rank": 1},
            {"feature": "gap_pct", "interval": "eod", "shap_importance": 0.028, "rank": 2},
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
```

- [ ] **Step 2: Write failing integration tests**

Create `backend/tests/api/test_analysis.py`:

```python
"""Integration tests for signal analysis endpoints."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.core.database import get_db
from tests.fixtures.analysis import seed_completed_analysis_run

client = TestClient(app)


# ---------------------------------------------------------------------------
# GET /api/outcomes/correlations
# ---------------------------------------------------------------------------

def test_correlations_returns_404_when_no_run(db: Session):
    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/outcomes/correlations")
    app.dependency_overrides.clear()
    assert response.status_code == 404


def test_correlations_returns_correct_shape(db: Session):
    seed_completed_analysis_run(db)
    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/outcomes/correlations")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert "run_id" in data
    assert "features" in data
    assert "intervals" in data
    assert "pearson" in data
    assert "spearman" in data
    assert len(data["pearson"]) == len(data["features"])
    assert len(data["pearson"][0]) == len(data["intervals"])


def test_correlations_filters_by_scanner_type(db: Session):
    seed_completed_analysis_run(db)
    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/outcomes/correlations?scanner_type=nonexistent_type")
    app.dependency_overrides.clear()
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/outcomes/analysis/latest
# ---------------------------------------------------------------------------

def test_latest_returns_404_when_no_run(db: Session):
    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/outcomes/analysis/latest")
    app.dependency_overrides.clear()
    assert response.status_code == 404


def test_latest_returns_feature_weights_and_clusters(db: Session):
    seed_completed_analysis_run(db)
    app.dependency_overrides[get_db] = lambda: db
    response = client.get("/api/outcomes/analysis/latest")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert "run_id" in data
    assert "feature_weights" in data
    assert "clusters" in data
    assert len(data["feature_weights"]) > 0
    assert len(data["clusters"]) > 0

    cluster = data["clusters"][0]
    assert "id" in cluster
    assert "label" in cluster
    assert "event_count" in cluster
    assert "centroid" in cluster
    assert "return_profile" in cluster


# ---------------------------------------------------------------------------
# POST /api/outcomes/analyze
# ---------------------------------------------------------------------------

def test_trigger_analysis_returns_202(db: Session):
    from unittest.mock import patch
    mock_result = type("R", (), {"id": "test-task-123"})()
    with patch("app.tasks.analyze_signal_features") as mock_task:
        mock_task.delay.return_value = mock_result
        app.dependency_overrides[get_db] = lambda: db
        response = client.post("/api/outcomes/analyze")
        app.dependency_overrides.clear()
    assert response.status_code == 202
    data = response.json()
    assert "task_id" in data
```

- [ ] **Step 3: Run tests — verify they fail**

```bash
docker-compose exec backend python -m pytest tests/api/test_analysis.py -v 2>&1 | tail -15
```

Expected: `FAILED` or `404` errors because endpoints don't exist.

- [ ] **Step 4: Add endpoints to outcomes.py router**

In `backend/app/routers/outcomes.py`, add new imports at the top (after existing imports):

```python
from app.models.signal_analysis_run import SignalAnalysisRun
from app.models.signal_cluster import SignalCluster
from app.schemas.analysis import (
    AnalysisTriggerResponse,
    CorrelationResponse,
    LatestAnalysisResponse,
    ClusterSummary,
    ClusterReturnInterval,
    FeatureWeight,
)
```

Note: **do not** add `from app.tasks import analyze_signal_features` at the module level — use a local import inside the endpoint function body (same pattern as `scanner.py`, `universe.py`, etc.) to avoid circular import issues.

At the end of `backend/app/routers/outcomes.py`, append:

```python
@router.post("/analyze", status_code=202, response_model=AnalysisTriggerResponse)
def trigger_signal_analysis(
    scanner_type: Optional[str] = None,
    k: int = 6,
    db: Session = Depends(get_db),
):
    from app.tasks import analyze_signal_features
    result = analyze_signal_features.delay(scanner_type=scanner_type, k=k)
    return AnalysisTriggerResponse(task_id=result.id)


@router.get("/correlations", response_model=CorrelationResponse)
def get_correlations(
    scanner_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = (
        db.query(SignalAnalysisRun)
        .filter(SignalAnalysisRun.status == "completed")
        .order_by(SignalAnalysisRun.created_at.desc())
    )
    if scanner_type:
        query = query.filter(SignalAnalysisRun.scanner_type == scanner_type)
    run = query.first()
    if not run:
        raise HTTPException(status_code=404, detail="No completed analysis run found")

    matrix = run.correlation_matrix or {}
    return CorrelationResponse(
        run_id=run.id,
        scanner_type=run.scanner_type,
        event_count=run.event_count or 0,
        completed_at=run.completed_at,
        features=matrix.get("features", []),
        intervals=matrix.get("intervals", []),
        pearson=matrix.get("pearson", []),
        spearman=matrix.get("spearman", []),
    )


@router.get("/analysis/latest", response_model=LatestAnalysisResponse)
def get_latest_analysis(
    db: Session = Depends(get_db),
):
    run = (
        db.query(SignalAnalysisRun)
        .filter(SignalAnalysisRun.status == "completed")
        .order_by(SignalAnalysisRun.created_at.desc())
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="No completed analysis run found")

    clusters_db = (
        db.query(SignalCluster)
        .filter(SignalCluster.analysis_run_id == run.id)
        .order_by(SignalCluster.cluster_index)
        .all()
    )

    clusters = []
    for c in clusters_db:
        return_profile = {}
        for interval_key, metrics in (c.return_profile or {}).items():
            return_profile[interval_key] = ClusterReturnInterval(**metrics)
        clusters.append(
            ClusterSummary(
                id=c.id,
                label=c.label,
                event_count=c.event_count,
                centroid=c.centroid or {},
                return_profile=return_profile,
            )
        )

    weights = [FeatureWeight(**w) for w in (run.feature_weights or [])]

    return LatestAnalysisResponse(
        run_id=run.id,
        completed_at=run.completed_at,
        feature_weights=weights,
        clusters=clusters,
    )
```

- [ ] **Step 5: Run tests — verify all pass**

```bash
docker-compose exec backend python -m pytest tests/api/test_analysis.py -v 2>&1 | tail -20
```

Expected: all tests pass.

- [ ] **Step 6: Smoke-test endpoints with curl**

```bash
# Confirm backend reloaded
docker-compose logs backend --tail=5

# Test correlations endpoint (no data → 404)
curl -s http://localhost:8000/api/outcomes/correlations | python -m json.tool

# Test latest analysis endpoint (no data → 404)
curl -s http://localhost:8000/api/outcomes/analysis/latest | python -m json.tool

# Test trigger endpoint
curl -s -X POST "http://localhost:8000/api/outcomes/analyze" | python -m json.tool
```

Expected:
- `/correlations` and `/analysis/latest` → `{"detail": "No completed analysis run found"}`
- `POST /analyze` → `{"task_id": "<celery-task-id>"}`

- [ ] **Step 7: Commit**

```bash
git add backend/tests/fixtures/analysis.py backend/tests/api/test_analysis.py backend/app/routers/outcomes.py backend/app/schemas/analysis.py
git commit -m "feat(discovery): add correlation, analysis, and trigger API endpoints with tests"
```

---

## Task 7: Create CorrelationHeatmap frontend component (TDD)

**Files:**
- Create: `frontend/src/api/analysis.ts`
- Create: `frontend/src/components/CorrelationHeatmap.tsx`

- [ ] **Step 1: Create analysis API layer**

Create `frontend/src/api/analysis.ts`:

```typescript
import { apiClient } from './client';

export interface CorrelationResponse {
  run_id: number;
  scanner_type: string | null;
  event_count: number;
  completed_at: string;
  features: string[];
  intervals: string[];
  pearson: number[][];
  spearman: number[][];
}

export interface FeatureWeight {
  feature: string;
  interval: string;
  shap_importance: number;
  rank: number;
}

export interface ClusterReturnInterval {
  median_pct: number;
  win_rate: number;
  sharpe: number;
  n: number;
}

export interface ClusterSummary {
  id: number;
  label: string;
  event_count: number;
  centroid: Record<string, number>;
  return_profile: Record<string, ClusterReturnInterval>;
}

export interface LatestAnalysisResponse {
  run_id: number;
  completed_at: string;
  feature_weights: FeatureWeight[];
  clusters: ClusterSummary[];
}

export interface AnalysisTriggerResponse {
  task_id: string;
}

export async function fetchCorrelations(scannerType?: string): Promise<CorrelationResponse> {
  const params = scannerType ? `?scanner_type=${encodeURIComponent(scannerType)}` : '';
  const response = await apiClient.get<CorrelationResponse>(`/outcomes/correlations${params}`);
  return response.data;
}

export async function fetchLatestAnalysis(): Promise<LatestAnalysisResponse> {
  const response = await apiClient.get<LatestAnalysisResponse>('/outcomes/analysis/latest');
  return response.data;
}

export async function triggerAnalysis(
  scannerType?: string,
  k?: number,
): Promise<AnalysisTriggerResponse> {
  const params = new URLSearchParams();
  if (scannerType) params.append('scanner_type', scannerType);
  if (k) params.append('k', String(k));
  const query = params.toString() ? `?${params.toString()}` : '';
  const response = await apiClient.post<AnalysisTriggerResponse>(`/outcomes/analyze${query}`);
  return response.data;
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors.

- [ ] **Step 3: Create CorrelationHeatmap component**

Create `frontend/src/components/CorrelationHeatmap.tsx`:

```tsx
import React, { useState } from 'react';
import type { CorrelationResponse } from '../api/analysis';

interface Props {
  data: CorrelationResponse;
}

function interpolateColor(r: number): string {
  // r in [-1, 1]: -1 → red #EF4444, 0 → dark gray #374151, 1 → green #10B981
  const clamp = Math.max(-1, Math.min(1, r));
  if (clamp >= 0) {
    const t = clamp;
    const red = Math.round(55 + (16 - 55) * t);
    const green = Math.round(65 + (185 - 65) * t);
    const blue = Math.round(81 + (129 - 81) * t);
    return `rgb(${red}, ${green}, ${blue})`;
  } else {
    const t = -clamp;
    const red = Math.round(55 + (239 - 55) * t);
    const green = Math.round(65 + (68 - 65) * t);
    const blue = Math.round(81 + (68 - 81) * t);
    return `rgb(${red}, ${green}, ${blue})`;
  }
}

const CorrelationHeatmap: React.FC<Props> = ({ data }) => {
  const [mode, setMode] = useState<'pearson' | 'spearman'>('pearson');

  const matrix = mode === 'pearson' ? data.pearson : data.spearman;

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        {(['pearson', 'spearman'] as const).map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={`px-3 py-1 text-[10px] font-black uppercase tracking-widest rounded-md transition-all ${
              mode === m
                ? 'bg-financial-blue text-white'
                : 'text-gray-500 hover:text-white border border-gray-700'
            }`}
          >
            {m}
          </button>
        ))}
        <span className="text-gray-500 text-xs ml-2">
          {data.event_count.toLocaleString()} events
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="text-xs border-collapse w-full">
          <thead>
            <tr>
              <th className="text-left text-gray-400 font-medium py-1 pr-4 whitespace-nowrap">
                Feature
              </th>
              {data.intervals.map((interval) => (
                <th
                  key={interval}
                  className="text-center text-gray-400 font-medium py-1 px-2 whitespace-nowrap uppercase tracking-wider"
                >
                  {interval}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.features.map((feature, fi) => (
              <tr key={feature}>
                <td className="text-gray-300 pr-4 py-1 whitespace-nowrap font-mono text-[11px]">
                  {feature}
                </td>
                {data.intervals.map((_, ii) => {
                  const val = matrix[fi]?.[ii] ?? 0;
                  return (
                    <td
                      key={ii}
                      className="text-center py-1 px-2 font-mono text-[11px] font-bold rounded"
                      style={{ backgroundColor: interpolateColor(val), color: '#F9FAFB' }}
                    >
                      {val.toFixed(2)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default CorrelationHeatmap;
```

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/analysis.ts frontend/src/components/CorrelationHeatmap.tsx
git commit -m "feat(discovery): add CorrelationHeatmap component and analysis API layer"
```

---

## Task 8: Add Feature Correlations card to EdgeExplorer

**Files:**
- Modify: `frontend/src/pages/EdgeExplorer.tsx`

- [ ] **Step 1: Add imports to EdgeExplorer.tsx**

At the top of `frontend/src/pages/EdgeExplorer.tsx`, update the existing React Query import line:

```tsx
import { useQuery, useMutation } from '@tanstack/react-query';
```

(The existing file imports only `useQuery` from `@tanstack/react-query` — add `useMutation` to that same import. Do NOT use `'react-query'` — the project uses `@tanstack/react-query` v5.)

Also add after the existing React Query import:

```tsx
import CorrelationHeatmap from '../components/CorrelationHeatmap';
import { fetchCorrelations, triggerAnalysis } from '../api/analysis';
```

- [ ] **Step 2: Add analysis hooks inside EdgeExplorer component**

After the existing `useQuery` calls inside the `EdgeExplorer` component body, add:

```tsx
  const { data: correlations, isLoading: loadingCorr, refetch: refetchCorr } = useQuery({
    queryKey: ['correlations', scannerType],
    queryFn: () => fetchCorrelations(scannerType || undefined),
    retry: false,
  });

  const triggerMutation = useMutation({
    mutationFn: () => triggerAnalysis(scannerType || undefined),
    onSuccess: (data) => {
      alert(`Analysis triggered. Task ID: ${data.task_id}`);
      refetchCorr();
    },
  });
```

- [ ] **Step 3: Add Feature Correlations card to the JSX return**

At the end of the JSX `<>...</>` block (before the closing `</>` of the inner fragment that contains existing charts), add:

```tsx
          {/* Feature Correlations */}
          <Card title="Feature Correlations" icon={BarChart2 as any}>
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <p className="text-gray-400 text-xs">
                  Correlation between signal features and subsequent returns.
                </p>
                <button
                  onClick={() => triggerMutation.mutate()}
                  disabled={triggerMutation.isPending}
                  className="px-3 py-1.5 text-[10px] font-black uppercase tracking-widest rounded-md bg-gray-700 hover:bg-financial-blue text-white transition-all disabled:opacity-50"
                >
                  {triggerMutation.isPending ? 'Queuing...' : 'Run Analysis'}
                </button>
              </div>

              {loadingCorr ? (
                <div className="flex items-center justify-center h-32 text-gray-500 text-xs">
                  Loading correlation data...
                </div>
              ) : correlations ? (
                <CorrelationHeatmap data={correlations} />
              ) : (
                <div className="flex items-center justify-center h-32 text-gray-500 text-xs text-center">
                  No analysis data yet. Run analysis to populate this panel.
                </div>
              )}
            </div>
          </Card>
```

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/EdgeExplorer.tsx
git commit -m "feat(discovery): add Feature Correlations card to EdgeExplorer"
```

---

## Final Validation

- [ ] **Step 1: Run full backend test suite**

```bash
docker-compose exec backend python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: all tests pass (new tests in `tests/services/test_statistical_discovery.py` and `tests/api/test_analysis.py` included).

- [ ] **Step 2: TypeScript final check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: exit 0, no output.

- [ ] **Step 3: Verify all new endpoints in Swagger**

Open `http://localhost:8000/docs` and confirm:
- `POST /api/outcomes/analyze`
- `GET /api/outcomes/correlations`
- `GET /api/outcomes/analysis/latest`

are listed and schema matches the spec.
