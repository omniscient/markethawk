# Implementation Plan — Statistical Discovery Engine (Phase 2b)

**Date**: 2026-05-14  
**Issue**: #22 feat(phase-2b): Statistical discovery engine  
**Spec**: `Docs/superpowers/specs/2026-05-14-statistical-discovery-engine-design.md`  
**Branch**: `refine/issue-22-feat-phase-2b---statistical-discovery-en`

---

## Goal

Build the Phase 2b statistical analysis pipeline that turns the Phase 2a backtest dataset into findings Phase 2c can consume. Delivers: a Celery task that computes Pearson/Spearman correlations, SHAP feature weights, and K-means cluster archetypes from complete outcome data; three new API endpoints; and a `CorrelationHeatmap` component added to EdgeExplorer.

## Architecture

```
ScannerEvent.indicators × ScannerOutcomeSnapshot.pct_change
  → StatisticalDiscoveryService (pure computation)
    ├── build_feature_matrix()      → pd.DataFrame
    ├── compute_correlations()      → CorrelationResult
    ├── compute_shap_weights()      → list[FeatureWeight]
    ├── run_kmeans()                → ClusterAssignment
    └── compute_conditional_stats() → dict[int, dict]
  → analyze_signal_features (Celery task)
    ├── Creates SignalAnalysisRun (anchor)
    ├── Saves correlation_matrix + feature_weights as JSONB
    ├── Creates SignalCluster rows
    └── Bulk-updates ScannerEvent.signal_cluster_id
  → /api/outcomes/analyze (POST 202)
  → /api/outcomes/correlations (GET)
  → /api/outcomes/analysis/latest (GET)
  → CorrelationHeatmap (React component in EdgeExplorer)
```

## Tech Stack

- **Backend**: FastAPI, SQLAlchemy ORM (sync Session), PostgreSQL JSONB, Celery + Redis
- **New packages**: `lightgbm`, `shap`, `scikit-learn`, `scipy`
- **Frontend**: React 18 + TypeScript, React Query, no new npm packages

## File Structure

| File | Action |
|------|--------|
| `backend/requirements.txt` | Add 4 new packages |
| `backend/app/models/signal_analysis_run.py` | New model |
| `backend/app/models/signal_cluster.py` | New model |
| `backend/app/models/scanner_event.py` | Add `signal_cluster_id` FK column |
| `backend/app/models/__init__.py` | Export new models |
| `backend/app/services/statistical_discovery.py` | New service |
| `backend/app/tasks.py` | Add `analyze_signal_features` task |
| `backend/app/core/celery_app.py` | Add nightly Beat schedule entry |
| `backend/app/schemas/outcome.py` | Add 3 new Pydantic response models |
| `backend/app/routers/outcomes.py` | Add 3 new endpoints |
| `backend/alembic/versions/<hash>_add_signal_analysis_tables.py` | Migration |
| `backend/tests/test_statistical_discovery.py` | New test file |
| `backend/tests/test_outcomes_analysis.py` | New test file |
| `frontend/src/api/analysis.ts` | New API client functions |
| `frontend/src/components/CorrelationHeatmap.tsx` | New component |
| `frontend/src/pages/EdgeExplorer.tsx` | Add Feature Correlations card |

---

## Tasks

### Task 1 — Add new Python dependencies

**Files**: `backend/requirements.txt`

#### Steps

**1.1 — Write failing test (import check)**

Create `backend/tests/test_statistical_discovery.py` with a single import test:

```python
# backend/tests/test_statistical_discovery.py
def test_deps_importable():
    import lightgbm  # noqa: F401
    import shap  # noqa: F401
    import sklearn  # noqa: F401
    import scipy  # noqa: F401
```

Run and verify it fails (packages not yet installed):
```bash
docker-compose exec backend python -m pytest tests/test_statistical_discovery.py::test_deps_importable -v
# Expected: FAILED — ModuleNotFoundError
```

**1.2 — Add packages to requirements.txt**

Append to `backend/requirements.txt`:
```
lightgbm>=4.3.0
shap>=0.45.0
scikit-learn>=1.4.0
scipy>=1.13.0
```

**1.3 — Install and verify**

```bash
docker-compose exec backend pip install lightgbm>=4.3.0 shap>=0.45.0 scikit-learn>=1.4.0 scipy>=1.13.0
docker-compose exec backend python -m pytest tests/test_statistical_discovery.py::test_deps_importable -v
# Expected: PASSED
```

**1.4 — Commit**
```bash
git add backend/requirements.txt backend/tests/test_statistical_discovery.py
git commit -m "feat(phase-2b): add lightgbm, shap, scikit-learn, scipy dependencies"
```

---

### Task 2 — SQLAlchemy models: SignalAnalysisRun and SignalCluster

**Files**:  
- `backend/app/models/signal_analysis_run.py` (new)  
- `backend/app/models/signal_cluster.py` (new)  
- `backend/app/models/__init__.py` (update)

#### Steps

**2.1 — Write failing import test**

Add to `backend/tests/test_statistical_discovery.py`:
```python
def test_models_importable():
    from app.models.signal_analysis_run import SignalAnalysisRun  # noqa: F401
    from app.models.signal_cluster import SignalCluster  # noqa: F401
```

Run and verify it fails:
```bash
docker-compose exec backend python -m pytest tests/test_statistical_discovery.py::test_models_importable -v
# Expected: FAILED — ModuleNotFoundError
```

**2.2 — Create SignalAnalysisRun model**

Create `backend/app/models/signal_analysis_run.py`:
```python
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Text, Index
from sqlalchemy.dialects.postgresql import JSONB
from app.core.database import Base


class SignalAnalysisRun(Base):
    __tablename__ = "signal_analysis_runs"

    id = Column(Integer, primary_key=True, index=True)
    scanner_type = Column(String(50), nullable=True)
    status = Column(String(20), nullable=False, default="pending")  # pending, running, completed, failed
    event_count = Column(Integer, nullable=True)
    correlation_matrix = Column(JSONB, nullable=True)
    feature_weights = Column(JSONB, nullable=True)
    celery_task_id = Column(String(255), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    completed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_signal_analysis_runs_created_at", "created_at"),
    )
```

**2.3 — Create SignalCluster model**

Create `backend/app/models/signal_cluster.py`:
```python
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from app.core.database import Base


class SignalCluster(Base):
    __tablename__ = "signal_clusters"

    id = Column(Integer, primary_key=True, index=True)
    analysis_run_id = Column(Integer, ForeignKey("signal_analysis_runs.id"), nullable=False)
    cluster_index = Column(Integer, nullable=False)
    label = Column(String(200), nullable=False)
    centroid = Column(JSONB, nullable=False, default=dict)
    return_profile = Column(JSONB, nullable=False, default=dict)
    event_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    __table_args__ = (
        Index("ix_signal_clusters_analysis_run_id", "analysis_run_id"),
    )
```

**2.4 — Update models/__init__.py**

Add after the `ScannerOutcomeSummary` import line:
```python
from app.models.signal_analysis_run import SignalAnalysisRun
from app.models.signal_cluster import SignalCluster
```

Add to `__all__`:
```python
"SignalAnalysisRun",
"SignalCluster",
```

**2.5 — Verify test passes**
```bash
docker-compose exec backend python -m pytest tests/test_statistical_discovery.py::test_models_importable -v
# Expected: PASSED
```

**2.6 — Commit**
```bash
git add backend/app/models/signal_analysis_run.py backend/app/models/signal_cluster.py backend/app/models/__init__.py backend/tests/test_statistical_discovery.py
git commit -m "feat(phase-2b): add SignalAnalysisRun and SignalCluster models"
```

---

### Task 3 — Add signal_cluster_id FK to ScannerEvent

**Files**: `backend/app/models/scanner_event.py`

#### Steps

**3.1 — Write failing test**

Add to `backend/tests/test_statistical_discovery.py`:
```python
def test_scanner_event_has_cluster_id():
    from app.models.scanner_event import ScannerEvent
    assert hasattr(ScannerEvent, "signal_cluster_id")
```

Run and verify it fails:
```bash
docker-compose exec backend python -m pytest tests/test_statistical_discovery.py::test_scanner_event_has_cluster_id -v
# Expected: FAILED — AssertionError
```

**3.2 — Add column to ScannerEvent**

In `backend/app/models/scanner_event.py`, add `ForeignKey` to the existing `sqlalchemy` import tuple (do NOT add a second `from sqlalchemy import` line — that breaks codebase convention):

```python
# Before (existing line):
from sqlalchemy import Column, Integer, String, DateTime, Date, Numeric, Uuid as UUID, UniqueConstraint
# After:
from sqlalchemy import Column, Integer, String, DateTime, Date, Numeric, Uuid as UUID, UniqueConstraint, ForeignKey
```

After `updated_at`, before `__table_args__`:
```python
signal_cluster_id = Column(Integer, ForeignKey("signal_clusters.id"), nullable=True, index=True)
```

The full addition in context:
```python
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    signal_cluster_id = Column(Integer, ForeignKey("signal_clusters.id"), nullable=True, index=True)

    __table_args__ = (
```

**3.3 — Verify test passes**
```bash
docker-compose exec backend python -m pytest tests/test_statistical_discovery.py::test_scanner_event_has_cluster_id -v
# Expected: PASSED
```

**3.4 — Commit**
```bash
git add backend/app/models/scanner_event.py backend/tests/test_statistical_discovery.py
git commit -m "feat(phase-2b): add signal_cluster_id FK to ScannerEvent"
```

---

### Task 4 — Alembic migration: add signal analysis tables

**Files**: `backend/alembic/versions/<hash>_add_signal_analysis_tables.py`

#### Steps

**4.1 — Generate migration**
```bash
docker-compose exec backend python -m alembic revision --autogenerate -m "add_signal_analysis_tables"
# Expected output: Generating .../alembic/versions/<hash>_add_signal_analysis_tables.py
```

**4.2 — Inspect generated migration**

Open the new migration file and verify it contains:
- `CREATE TABLE signal_analysis_runs` with all columns
- `CREATE TABLE signal_clusters` with all columns and FK
- `ALTER TABLE scanner_events ADD COLUMN signal_cluster_id` with FK and index
- `DROP TABLE` statements in `downgrade()`

**4.3 — Apply migration**
```bash
docker-compose exec backend python -m alembic upgrade head
# Expected: Running upgrade ... -> <hash>, add_signal_analysis_tables
```

**4.4 — Verify tables exist**
```bash
docker-compose exec backend python -c "
from app.core.database import SessionLocal
from app.models.signal_analysis_run import SignalAnalysisRun
from app.models.signal_cluster import SignalCluster
db = SessionLocal()
print('signal_analysis_runs:', db.query(SignalAnalysisRun).count())
print('signal_clusters:', db.query(SignalCluster).count())
db.close()
print('OK')
"
# Expected: signal_analysis_runs: 0 / signal_clusters: 0 / OK
```

**4.5 — Commit**
```bash
git add backend/alembic/versions/
git commit -m "feat(phase-2b): migration — add signal_analysis_runs, signal_clusters, ScannerEvent.signal_cluster_id"
```

---

### Task 5 — StatisticalDiscoveryService

**Files**:  
- `backend/app/services/statistical_discovery.py` (new)  
- `backend/tests/test_statistical_discovery.py` (update)

#### Steps

**5.1 — Write failing tests for build_feature_matrix**

Add to `backend/tests/test_statistical_discovery.py`:
```python
import pandas as pd
import numpy as np
from unittest.mock import MagicMock

def _make_mock_row(event_id, indicators, pct_change, interval_key):
    row = MagicMock()
    row.id = event_id
    row.indicators = indicators
    row.pct_change = pct_change
    row.interval_key = interval_key
    return row

def test_build_feature_matrix_basic():
    from app.services.statistical_discovery import StatisticalDiscoveryService
    rows = [
        _make_mock_row(1, {"gap_pct": 2.1, "relative_volume": 3.5}, 1.2, "1h"),
        _make_mock_row(1, {"gap_pct": 2.1, "relative_volume": 3.5}, 2.4, "4h"),
        _make_mock_row(2, {"gap_pct": 1.5, "relative_volume": 2.0}, 0.5, "1h"),
        _make_mock_row(2, {"gap_pct": 1.5, "relative_volume": 2.0}, 1.1, "4h"),
    ]
    df = StatisticalDiscoveryService.build_feature_matrix(rows)
    assert isinstance(df, pd.DataFrame)
    assert "gap_pct" in df.columns
    assert "relative_volume" in df.columns
    assert "pct_change" in df.columns
    assert "interval_key" in df.columns
    assert len(df) == 4

def test_build_feature_matrix_drops_sparse_rows():
    from app.services.statistical_discovery import StatisticalDiscoveryService
    # Row with > 50% nulls across 4 features should be dropped
    rows = [
        _make_mock_row(1, {"gap_pct": None, "relative_volume": None, "fade": None, "range": 1.0}, 1.0, "1h"),
        _make_mock_row(2, {"gap_pct": 2.1, "relative_volume": 3.5, "fade": 1.2, "range": 1.5}, 1.5, "1h"),
    ]
    df = StatisticalDiscoveryService.build_feature_matrix(rows)
    assert len(df) == 1
    assert df.iloc[0]["gap_pct"] == 2.1

def test_compute_correlations_shape():
    from app.services.statistical_discovery import StatisticalDiscoveryService
    rng = np.random.default_rng(42)
    data = {
        "event_id": list(range(20)),
        "interval_key": ["1h"] * 10 + ["4h"] * 10,
        "gap_pct": rng.uniform(0.5, 5.0, 20).tolist(),
        "relative_volume": rng.uniform(1.0, 10.0, 20).tolist(),
        "pct_change": rng.uniform(-2.0, 5.0, 20).tolist(),
    }
    df = pd.DataFrame(data)
    result = StatisticalDiscoveryService.compute_correlations(df)
    assert "features" in result
    assert "intervals" in result
    assert "pearson" in result
    assert "spearman" in result
    assert len(result["pearson"]) == len(result["features"])
    assert len(result["pearson"][0]) == len(result["intervals"])

def test_run_kmeans_returns_labels_and_centroids():
    from app.services.statistical_discovery import StatisticalDiscoveryService
    rng = np.random.default_rng(42)
    n = 60
    data = {
        "event_id": list(range(n)),
        "interval_key": ["1h"] * n,
        "gap_pct": rng.uniform(0.5, 5.0, n).tolist(),
        "relative_volume": rng.uniform(1.0, 10.0, n).tolist(),
        "pct_change": rng.uniform(-2.0, 5.0, n).tolist(),
    }
    df = pd.DataFrame(data)
    labels, centroids = StatisticalDiscoveryService.run_kmeans(df, k=3)
    assert len(labels) == n
    assert len(centroids) == 3
    assert all(0 <= l < 3 for l in labels.values())
```

Run and verify all 4 tests fail:
```bash
docker-compose exec backend python -m pytest tests/test_statistical_discovery.py -k "test_build_feature_matrix or test_compute_correlations or test_run_kmeans" -v
# Expected: 4 FAILED — ModuleNotFoundError (service doesn't exist yet)
```

**5.2 — Create StatisticalDiscoveryService**

Create `backend/app/services/statistical_discovery.py`:
```python
import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)


@dataclass
class ClusterAssignment:
    labels: dict[int, int]   # event_id → cluster_index
    centroids: list[dict]    # list of {feature: centroid_value} per cluster


class StatisticalDiscoveryService:

    @staticmethod
    def build_feature_matrix(rows: list) -> pd.DataFrame:
        """
        Flatten event rows (each has .indicators JSONB + .pct_change + .interval_key)
        into a DataFrame with one row per (event_id, interval_key).
        Drops rows where > 50% of feature columns are NULL.
        """
        records = []
        for row in rows:
            indicators = row.indicators or {}
            record = {"event_id": row.id, "interval_key": row.interval_key, "pct_change": row.pct_change}
            for k, v in indicators.items():
                try:
                    record[k] = float(v) if v is not None else None
                except (TypeError, ValueError):
                    record[k] = None
            records.append(record)

        if not records:
            return pd.DataFrame()

        df = pd.DataFrame(records)
        feature_cols = [c for c in df.columns if c not in ("event_id", "interval_key", "pct_change")]

        if feature_cols:
            null_frac = df[feature_cols].isnull().mean(axis=1)
            df = df[null_frac <= 0.5].reset_index(drop=True)

        return df

    @staticmethod
    def compute_correlations(df: pd.DataFrame) -> dict[str, Any]:
        """
        Compute Pearson and Spearman r per (feature × interval_key).
        Returns dict suitable for JSON serialisation.
        """
        feature_cols = [c for c in df.columns if c not in ("event_id", "interval_key", "pct_change")]
        intervals = sorted(df["interval_key"].unique().tolist())

        pearson_matrix = []
        spearman_matrix = []

        for feat in feature_cols:
            p_row, s_row = [], []
            for interval in intervals:
                sub = df[df["interval_key"] == interval][["pct_change", feat]].dropna()
                if len(sub) < 5:
                    p_row.append(None)
                    s_row.append(None)
                    continue
                pr, _ = stats.pearsonr(sub[feat], sub["pct_change"])
                sr, _ = stats.spearmanr(sub[feat], sub["pct_change"])
                p_row.append(round(float(pr), 4))
                s_row.append(round(float(sr), 4))
            pearson_matrix.append(p_row)
            spearman_matrix.append(s_row)

        return {
            "features": feature_cols,
            "intervals": intervals,
            "pearson": pearson_matrix,
            "spearman": spearman_matrix,
        }

    @staticmethod
    def compute_shap_weights(df: pd.DataFrame) -> list[dict]:
        """
        Fit LightGBM per interval_key, compute mean |SHAP| per feature.
        Returns list of {feature, interval, shap_importance, rank} sorted by importance desc.
        """
        import lightgbm as lgb
        import shap

        feature_cols = [c for c in df.columns if c not in ("event_id", "interval_key", "pct_change")]
        intervals = sorted(df["interval_key"].unique().tolist())
        weights: list[dict] = []

        for interval in intervals:
            sub = df[df["interval_key"] == interval][feature_cols + ["pct_change"]].dropna()
            if len(sub) < 20:
                logger.warning("Skipping SHAP for interval %s — only %d rows after dropna", interval, len(sub))
                continue

            X = sub[feature_cols].values
            y = sub["pct_change"].values

            model = lgb.LGBMRegressor(n_estimators=100, max_depth=4, verbose=-1)
            model.fit(X, y)

            explainer = shap.TreeExplainer(model)
            shap_values = explainer.shap_values(X)
            mean_abs_shap = np.abs(shap_values).mean(axis=0)

            for feat, importance in zip(feature_cols, mean_abs_shap):
                weights.append({"feature": feat, "interval": interval, "shap_importance": round(float(importance), 6)})

        weights.sort(key=lambda w: w["shap_importance"], reverse=True)
        for rank, w in enumerate(weights, start=1):
            w["rank"] = rank

        return weights

    @staticmethod
    def run_kmeans(df: pd.DataFrame, k: int = 6) -> tuple[dict[int, int], list[dict]]:
        """
        Fit K-means on standardised feature vectors (one row per event, averaged across intervals).
        Returns (labels dict event_id→cluster_index, centroids list).
        """
        feature_cols = [c for c in df.columns if c not in ("event_id", "interval_key", "pct_change")]

        event_features = (
            df.groupby("event_id")[feature_cols]
            .mean()
            .dropna()
            .reset_index()
        )

        if len(event_features) < k:
            k = max(1, len(event_features))

        scaler = StandardScaler()
        X = scaler.fit_transform(event_features[feature_cols].values)

        km = KMeans(n_clusters=k, random_state=42, n_init=10)
        cluster_labels = km.fit_predict(X)

        labels = {int(row["event_id"]): int(label) for row, label in zip(event_features.to_dict("records"), cluster_labels)}

        centroids = []
        for i in range(k):
            centroid_scaled = km.cluster_centers_[i]
            centroid_original = scaler.inverse_transform([centroid_scaled])[0]
            centroids.append({feat: round(float(val), 4) for feat, val in zip(feature_cols, centroid_original)})

        return labels, centroids

    @staticmethod
    def compute_conditional_stats(df: pd.DataFrame, labels: dict[int, int]) -> dict[int, dict]:
        """
        For each cluster × interval: median pct_change, win_rate, Sharpe, sample size.
        Returns {cluster_index: {interval: {median_pct, win_rate, sharpe, n}}}.
        """
        df = df.copy()
        df["cluster"] = df["event_id"].map(labels)
        df = df.dropna(subset=["cluster"])
        df["cluster"] = df["cluster"].astype(int)

        result: dict[int, dict] = {}
        for cluster_idx in df["cluster"].unique():
            cluster_df = df[df["cluster"] == cluster_idx]
            result[cluster_idx] = {}
            for interval in cluster_df["interval_key"].unique():
                sub = cluster_df[cluster_df["interval_key"] == interval]["pct_change"].dropna()
                if len(sub) == 0:
                    continue
                mean_r = sub.mean()
                std_r = sub.std()
                sharpe = round(float(mean_r / std_r), 4) if std_r and std_r != 0 else 0.0
                result[cluster_idx][interval] = {
                    "median_pct": round(float(sub.median()), 4),
                    "win_rate": round(float((sub > 0).mean()), 4),
                    "sharpe": sharpe,
                    "n": int(len(sub)),
                }
        return result

    @staticmethod
    def generate_label(centroid: dict, global_mean: dict) -> str:
        """
        Auto-label a cluster from top 2 features with highest absolute deviation from global mean.
        E.g. 'high relative_volume + low gap_pct'
        """
        deviations = []
        for feat, val in centroid.items():
            gmean = global_mean.get(feat, 0.0) or 0.0
            deviations.append((abs(val - gmean), feat, val, gmean))

        deviations.sort(reverse=True)
        top2 = deviations[:2]

        parts = []
        for _, feat, val, gmean in top2:
            direction = "high" if val > gmean else "low"
            parts.append(f"{direction} {feat}")

        return " + ".join(parts) if parts else "unlabelled"
```

**5.3 — Verify tests pass**
```bash
docker-compose exec backend python -m pytest tests/test_statistical_discovery.py -k "test_build_feature_matrix or test_compute_correlations or test_run_kmeans" -v
# Expected: 4 PASSED
```

**5.4 — Commit**
```bash
git add backend/app/services/statistical_discovery.py backend/tests/test_statistical_discovery.py
git commit -m "feat(phase-2b): add StatisticalDiscoveryService (correlations, SHAP, K-means)"
```

---

### Task 6 — analyze_signal_features Celery task + Beat schedule

**Files**:  
- `backend/app/tasks.py` (update)  
- `backend/app/core/celery_app.py` (update)  
- `backend/tests/test_statistical_discovery.py` (update)

#### Steps

**6.1 — Write failing task import test**

Add to `backend/tests/test_statistical_discovery.py`:
```python
def test_analyze_task_importable():
    from app.tasks import analyze_signal_features  # noqa: F401
    assert callable(analyze_signal_features)
```

Run and verify it fails:
```bash
docker-compose exec backend python -m pytest tests/test_statistical_discovery.py::test_analyze_task_importable -v
# Expected: FAILED — ImportError
```

**6.2 — Add imports to tasks.py**

At the module level (top) of `backend/app/tasks.py`, add:
```python
from app.models.signal_analysis_run import SignalAnalysisRun
from app.models.signal_cluster import SignalCluster
from app.services.statistical_discovery import StatisticalDiscoveryService
```

`ScannerEvent`, `ScannerOutcomeSnapshot`, and `ScannerOutcomeSummary` may already be imported at the module level — verify with grep before adding. If they only appear inside individual function bodies (not at the module top), also add them at the module top. Do NOT modify any existing intra-function imports.

```bash
grep -n "^from app.models.scanner_event\|^from app.models.scanner_outcome" backend/app/tasks.py
```
If those lines are absent at the module top, add them alongside the new imports above.

**6.3 — Add analyze_signal_features task to tasks.py**

Append at the end of `backend/app/tasks.py`:
```python
@celery_app.task(bind=True, max_retries=1, name='app.tasks.analyze_signal_features')
def analyze_signal_features(self, scanner_type: str = None, k: int = 6):
    """
    Statistical discovery pipeline: correlations, SHAP weights, K-means clusters.
    Requires >= 500 complete events (ScannerOutcomeSummary.is_complete = True).
    """
    db: Session = SessionLocal()
    run = None
    try:
        run = SignalAnalysisRun(status="running", scanner_type=scanner_type)
        db.add(run)
        db.commit()
        db.refresh(run)

        query = (
            db.query(
                ScannerEvent,
                ScannerOutcomeSnapshot.pct_change,
                ScannerOutcomeSnapshot.interval_key,
            )
            .join(ScannerOutcomeSummary, ScannerOutcomeSummary.scanner_event_id == ScannerEvent.id)
            .join(ScannerOutcomeSnapshot, ScannerOutcomeSnapshot.scanner_event_id == ScannerEvent.id)
            .filter(ScannerOutcomeSummary.is_complete == True)
            .filter(ScannerOutcomeSnapshot.status == "captured")
        )
        if scanner_type:
            query = query.filter(ScannerEvent.scanner_type == scanner_type)

        rows = query.all()

        class _Row:
            def __init__(self, event, pct_change, interval_key):
                self.id = event.id
                self.indicators = event.indicators
                self.pct_change = pct_change
                self.interval_key = interval_key

        flat_rows = [_Row(event, pct_change, interval_key) for event, pct_change, interval_key in rows]
        event_count = len({r.id for r in flat_rows})

        MIN_EVENTS = 500
        if event_count < MIN_EVENTS:
            run.status = "failed"
            run.error_message = f"Insufficient data (n={event_count}, min={MIN_EVENTS})"
            run.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.commit()
            logger.warning("analyze_signal_features: %s", run.error_message)
            return

        df = StatisticalDiscoveryService.build_feature_matrix(flat_rows)

        correlation_matrix = StatisticalDiscoveryService.compute_correlations(df)
        run.correlation_matrix = correlation_matrix
        db.commit()

        feature_weights = StatisticalDiscoveryService.compute_shap_weights(df)
        run.feature_weights = feature_weights
        db.commit()

        labels, centroids = StatisticalDiscoveryService.run_kmeans(df, k=k)
        conditional_stats = StatisticalDiscoveryService.compute_conditional_stats(df, labels)

        feature_cols = [c for c in df.columns if c not in ("event_id", "interval_key", "pct_change")]
        global_mean = {feat: float(df[feat].mean()) for feat in feature_cols if feat in df.columns}

        cluster_id_map: dict[int, int] = {}
        for cluster_idx, centroid in enumerate(centroids):
            label = StatisticalDiscoveryService.generate_label(centroid, global_mean)
            return_profile = conditional_stats.get(cluster_idx, {})
            event_count_in_cluster = sum(1 for v in labels.values() if v == cluster_idx)
            cluster = SignalCluster(
                analysis_run_id=run.id,
                cluster_index=cluster_idx,
                label=label,
                centroid=centroid,
                return_profile=return_profile,
                event_count=event_count_in_cluster,
            )
            db.add(cluster)
            db.flush()
            cluster_id_map[cluster_idx] = cluster.id

        for event_id, cluster_idx in labels.items():
            db.query(ScannerEvent).filter(ScannerEvent.id == event_id).update(
                {"signal_cluster_id": cluster_id_map[cluster_idx]},
                synchronize_session=False,
            )

        run.status = "completed"
        run.event_count = event_count
        run.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
        logger.info("analyze_signal_features: completed run_id=%d events=%d", run.id, event_count)

    except Exception as exc:
        logger.exception("analyze_signal_features failed: %s", exc)
        if run:
            run.status = "failed"
            run.error_message = str(exc)
            run.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            try:
                db.commit()
            except Exception:
                db.rollback()
        raise
    finally:
        db.close()
```

**6.4 — Add Beat schedule to celery_app.py**

Add to `celery_app.conf.beat_schedule` dict in `backend/app/core/celery_app.py`:
```python
    'analyze-signal-features-nightly': {
        'task': 'app.tasks.analyze_signal_features',
        'schedule': crontab(minute='0', hour='11', day_of_week='1-5'),
    },
```

**6.5 — Verify test passes**
```bash
docker-compose exec backend python -m pytest tests/test_statistical_discovery.py::test_analyze_task_importable -v
# Expected: PASSED
```

**6.6 — Restart backend and verify no import errors**
```bash
docker-compose restart backend
docker-compose logs backend --tail=20
# Expected: no ImportError, Uvicorn running
```

**6.7 — Commit**
```bash
git add backend/app/tasks.py backend/app/core/celery_app.py backend/tests/test_statistical_discovery.py
git commit -m "feat(phase-2b): add analyze_signal_features Celery task and nightly Beat schedule"
```

---

### Task 7 — Pydantic schemas for analysis endpoints

**Files**: `backend/app/schemas/outcome.py`

#### Steps

**7.1 — Write failing test**

Create `backend/tests/test_outcomes_analysis.py`:
```python
def test_analysis_schemas_importable():
    from app.schemas.outcome import (  # noqa: F401
        AnalysisRunResponse,
        CorrelationMatrixResponse,
        AnalysisLatestResponse,
        ClusterResponse,
        FeatureWeightItem,
    )
```

Run and verify it fails:
```bash
docker-compose exec backend python -m pytest tests/test_outcomes_analysis.py::test_analysis_schemas_importable -v
# Expected: FAILED — ImportError
```

**7.2 — Add schemas to outcome.py**

Append to `backend/app/schemas/outcome.py`:
```python
class AnalysisRunResponse(BaseModel):
    task_id: str


class ClusterResponse(BaseModel):
    id: int
    label: str
    event_count: int
    centroid: Dict[str, Any]
    return_profile: Dict[str, Any]


class CorrelationMatrixResponse(BaseModel):
    run_id: int
    scanner_type: Optional[str] = None
    event_count: int
    completed_at: Optional[datetime] = None
    features: List[str]
    intervals: List[str]
    pearson: List[List[Optional[float]]]
    spearman: List[List[Optional[float]]]


class FeatureWeightItem(BaseModel):
    feature: str
    interval: str
    shap_importance: float
    rank: int


class AnalysisLatestResponse(BaseModel):
    run_id: int
    completed_at: Optional[datetime] = None
    feature_weights: List[FeatureWeightItem]
    clusters: List[ClusterResponse]
```

**7.3 — Verify test passes**
```bash
docker-compose exec backend python -m pytest tests/test_outcomes_analysis.py::test_analysis_schemas_importable -v
# Expected: PASSED
```

**7.4 — Commit**
```bash
git add backend/app/schemas/outcome.py backend/tests/test_outcomes_analysis.py
git commit -m "feat(phase-2b): add Pydantic schemas for analysis endpoints"
```

---

### Task 8 — API endpoints: POST /analyze, GET /correlations, GET /analysis/latest

**Files**:  
- `backend/app/routers/outcomes.py` (update)  
- `backend/tests/test_outcomes_analysis.py` (update)

#### Steps

**8.1 — Write failing endpoint tests**

Add to `backend/tests/test_outcomes_analysis.py`:
```python
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock


def _get_client():
    from app.main import app
    return TestClient(app)


def test_post_analyze_returns_202():
    client = _get_client()
    with patch("app.routers.outcomes.analyze_signal_features") as mock_task:
        mock_result = MagicMock()
        mock_result.id = "abc-123"
        mock_task.delay.return_value = mock_result
        resp = client.post("/api/outcomes/analyze")
    assert resp.status_code == 202
    assert resp.json()["task_id"] == "abc-123"


def test_get_correlations_404_when_no_run():
    client = _get_client()
    resp = client.get("/api/outcomes/correlations")
    assert resp.status_code == 404


def test_get_analysis_latest_404_when_no_run():
    client = _get_client()
    resp = client.get("/api/outcomes/analysis/latest")
    assert resp.status_code == 404
```

Run and verify all 3 fail:
```bash
docker-compose exec backend python -m pytest tests/test_outcomes_analysis.py -k "test_post_analyze or test_get_correlations or test_get_analysis_latest" -v
# Expected: 3 FAILED — 404 not raised or route not found
```

**8.2 — Add imports to outcomes.py**

At the top of `backend/app/routers/outcomes.py`, add the model and schema imports (NOT the task import — see note below):
```python
from app.models.signal_analysis_run import SignalAnalysisRun
from app.models.signal_cluster import SignalCluster
from app.schemas.outcome import (
    AnalysisRunResponse,
    CorrelationMatrixResponse,
    AnalysisLatestResponse,
    ClusterResponse,
    FeatureWeightItem,
)
```

`Optional` and `from typing import Optional` are likely already present — add only what is missing.

**Do NOT add `from app.tasks import analyze_signal_features` at module level.** Every router in this codebase imports tasks inside function bodies to avoid circular imports (see `scanner.py:65`, `universe.py:453`, `news.py:79`). The task import goes inside `trigger_signal_analysis()` as shown in step 8.3 below.

**8.3 — Add three endpoints to outcomes.py**

Append to `backend/app/routers/outcomes.py`:
```python
@router.post("/analyze", response_model=AnalysisRunResponse, status_code=202)
def trigger_signal_analysis(
    scanner_type: Optional[str] = None,
    k: int = 6,
    db: Session = Depends(get_db),
):
    from app.tasks import analyze_signal_features  # local import — avoids circular import at module load
    result = analyze_signal_features.delay(scanner_type=scanner_type, k=k)
    return AnalysisRunResponse(task_id=result.id)


@router.get("/correlations", response_model=CorrelationMatrixResponse)
def get_correlations(
    scanner_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = (
        db.query(SignalAnalysisRun)
        .filter(SignalAnalysisRun.status == "completed")
    )
    if scanner_type:
        query = query.filter(SignalAnalysisRun.scanner_type == scanner_type)
    # When no scanner_type filter is given, return the most recent completed run regardless
    # of which scanner_type it targeted (do NOT add a NULL filter here — that would hide
    # per-type runs when the caller omits the filter).
    run = query.order_by(SignalAnalysisRun.created_at.desc()).first()
    if not run:
        raise HTTPException(status_code=404, detail="No completed analysis run found")

    matrix = run.correlation_matrix or {}
    return CorrelationMatrixResponse(
        run_id=run.id,
        scanner_type=run.scanner_type,
        event_count=run.event_count or 0,
        completed_at=run.completed_at,
        features=matrix.get("features", []),
        intervals=matrix.get("intervals", []),
        pearson=matrix.get("pearson", []),
        spearman=matrix.get("spearman", []),
    )


@router.get("/analysis/latest", response_model=AnalysisLatestResponse)
def get_analysis_latest(
    scanner_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = (
        db.query(SignalAnalysisRun)
        .filter(SignalAnalysisRun.status == "completed")
    )
    if scanner_type:
        query = query.filter(SignalAnalysisRun.scanner_type == scanner_type)
    # Same reasoning as /correlations: no NULL filter when scanner_type is omitted.
    run = query.order_by(SignalAnalysisRun.created_at.desc()).first()
    if not run:
        raise HTTPException(status_code=404, detail="No completed analysis run found")

    clusters = (
        db.query(SignalCluster)
        .filter(SignalCluster.analysis_run_id == run.id)
        .order_by(SignalCluster.cluster_index)
        .all()
    )

    weights = [FeatureWeightItem(**w) for w in (run.feature_weights or [])]
    cluster_responses = [
        ClusterResponse(
            id=c.id,
            label=c.label,
            event_count=c.event_count,
            centroid=c.centroid,
            return_profile=c.return_profile,
        )
        for c in clusters
    ]

    return AnalysisLatestResponse(
        run_id=run.id,
        completed_at=run.completed_at,
        feature_weights=weights,
        clusters=cluster_responses,
    )
```

**8.4 — Verify tests pass**
```bash
docker-compose exec backend python -m pytest tests/test_outcomes_analysis.py -v
# Expected: 4 PASSED (including the schema import test)
```

**8.5 — Live curl validation**
```bash
docker-compose restart backend
# Wait 5 seconds for reload

curl -s -X POST "http://localhost:8000/api/outcomes/analyze" | python3 -m json.tool
# Expected: {"task_id": "<some-uuid>"}  (202 Accepted)

curl -s "http://localhost:8000/api/outcomes/correlations" | python3 -m json.tool
# Expected: {"detail": "No completed analysis run found"}  (404)

curl -s "http://localhost:8000/api/outcomes/analysis/latest" | python3 -m json.tool
# Expected: {"detail": "No completed analysis run found"}  (404)
```

**8.6 — Commit**
```bash
git add backend/app/routers/outcomes.py backend/tests/test_outcomes_analysis.py
git commit -m "feat(phase-2b): add POST /analyze, GET /correlations, GET /analysis/latest endpoints"
```

---

### Task 9 — Frontend API client

**Files**: `frontend/src/api/analysis.ts` (new)

#### Steps

**9.1 — Write failing TypeScript check**

Create `frontend/src/api/analysis.ts` with just a type export (incomplete) to establish the file exists, then run tsc:
```typescript
// frontend/src/api/analysis.ts — placeholder
export {};
```

```bash
cd /workspace/markethawk/frontend && npx tsc --noEmit
# Expected: PASSED (empty export is valid TS)
```

**9.2 — Implement the API functions**

Replace `frontend/src/api/analysis.ts` with:
```typescript
import { apiClient } from './client';

export interface CorrelationMatrixResponse {
  run_id: number;
  scanner_type: string | null;
  event_count: number;
  completed_at: string | null;
  features: string[];
  intervals: string[];
  pearson: (number | null)[][];
  spearman: (number | null)[][];
}

export interface FeatureWeightItem {
  feature: string;
  interval: string;
  shap_importance: number;
  rank: number;
}

export interface ClusterResponse {
  id: number;
  label: string;
  event_count: number;
  centroid: Record<string, number>;
  return_profile: Record<string, { median_pct: number; win_rate: number; sharpe: number; n: number }>;
}

export interface AnalysisLatestResponse {
  run_id: number;
  completed_at: string | null;
  feature_weights: FeatureWeightItem[];
  clusters: ClusterResponse[];
}

export async function fetchCorrelations(scannerType?: string): Promise<CorrelationMatrixResponse> {
  const params = new URLSearchParams();
  if (scannerType) params.append('scanner_type', scannerType);
  const resp = await apiClient.get<CorrelationMatrixResponse>(`/api/outcomes/correlations?${params}`);
  return resp.data;
}

export async function triggerAnalysis(scannerType?: string): Promise<{ task_id: string }> {
  const params = new URLSearchParams();
  if (scannerType) params.append('scanner_type', scannerType);
  const resp = await apiClient.post<{ task_id: string }>(`/api/outcomes/analyze?${params}`);
  return resp.data;
}
```

Note: `apiClient` is the shared Axios instance from `./client`. It provides base URL config and any interceptors already set up by the app. Every other file in `frontend/src/api/` uses it — do NOT use raw `fetch` here.

**9.3 — Verify TypeScript compiles**
```bash
cd /workspace/markethawk/frontend && npx tsc --noEmit
# Expected: no errors
```

**9.4 — Commit**
```bash
git add frontend/src/api/analysis.ts
git commit -m "feat(phase-2b): add frontend API client for analysis endpoints"
```

---

### Task 10 — CorrelationHeatmap component

**Files**: `frontend/src/components/CorrelationHeatmap.tsx` (new)

#### Steps

**10.1 — Write failing TypeScript check (stub)**

Create `frontend/src/components/CorrelationHeatmap.tsx`:
```typescript
// stub to verify TypeScript checks before implementation
export default function CorrelationHeatmap() { return null; }
```

```bash
cd /workspace/markethawk/frontend && npx tsc --noEmit
# Expected: PASSED
```

**10.2 — Implement CorrelationHeatmap**

Replace with full implementation in `frontend/src/components/CorrelationHeatmap.tsx`:
```typescript
import React, { useState } from 'react';
import { CorrelationMatrixResponse } from '../api/analysis';

interface Props {
  data: CorrelationMatrixResponse;
}

function interpolateColor(r: number | null): string {
  if (r === null) return '#1f2937';
  const clamped = Math.max(-1, Math.min(1, r));
  if (clamped < 0) {
    const t = -clamped;
    const red = Math.round(55 + t * (239 - 55));
    const green = Math.round(65 + t * (68 - 65));
    const blue = Math.round(81 + t * (68 - 81));
    return `rgb(${red},${green},${blue})`;
  }
  const t = clamped;
  const red = Math.round(55 + t * (16 - 55));
  const green = Math.round(65 + t * (185 - 65));
  const blue = Math.round(81 + t * (129 - 81));
  return `rgb(${red},${green},${blue})`;
}

const CorrelationHeatmap: React.FC<Props> = ({ data }) => {
  const [mode, setMode] = useState<'pearson' | 'spearman'>('pearson');
  const matrix = mode === 'pearson' ? data.pearson : data.spearman;

  return (
    <div>
      <div className="flex items-center gap-3 mb-4">
        <span className="text-xs text-gray-400 font-bold uppercase tracking-wider">Correlation type:</span>
        {(['pearson', 'spearman'] as const).map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={`px-3 py-1 text-xs font-black uppercase tracking-widest rounded-md transition-all ${
              mode === m ? 'bg-financial-blue text-white' : 'text-gray-500 hover:text-white bg-gray-800'
            }`}
          >
            {m}
          </button>
        ))}
      </div>
      <div className="overflow-x-auto">
        <table className="text-xs w-full border-collapse">
          <thead>
            <tr>
              <th className="text-left text-gray-400 font-bold py-1 pr-4 uppercase tracking-wider">Feature</th>
              {data.intervals.map((interval) => (
                <th key={interval} className="text-center text-gray-400 font-bold py-1 px-2 uppercase tracking-wider min-w-[60px]">
                  {interval}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.features.map((feature, fi) => (
              <tr key={feature}>
                <td className="text-gray-300 font-mono py-1 pr-4 whitespace-nowrap">{feature}</td>
                {(matrix[fi] ?? []).map((val, ii) => (
                  <td
                    key={ii}
                    className="text-center py-1 px-2 rounded font-mono font-bold"
                    style={{ backgroundColor: interpolateColor(val), color: '#f9fafb' }}
                  >
                    {val !== null ? val.toFixed(2) : '—'}
                  </td>
                ))}
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

**10.3 — Verify TypeScript compiles**
```bash
cd /workspace/markethawk/frontend && npx tsc --noEmit
# Expected: no errors
```

**10.4 — Commit**
```bash
git add frontend/src/components/CorrelationHeatmap.tsx
git commit -m "feat(phase-2b): add CorrelationHeatmap component with Pearson/Spearman toggle"
```

---

### Task 11 — EdgeExplorer: Feature Correlations card

**Files**: `frontend/src/pages/EdgeExplorer.tsx` (update)

#### Steps

**11.1 — Write failing TypeScript check (add import stub)**

In `frontend/src/pages/EdgeExplorer.tsx`, add this import right after the existing imports (before the component definition):
```typescript
import CorrelationHeatmap from '../components/CorrelationHeatmap';
import { fetchCorrelations, triggerAnalysis, CorrelationMatrixResponse } from '../api/analysis';
```

```bash
cd /workspace/markethawk/frontend && npx tsc --noEmit
# Expected: PASSED (both files exist and types are compatible)
```

**11.2 — Add state and queries inside the EdgeExplorer component**

Inside the `EdgeExplorer` component function, after the existing query declarations, add:
```typescript
  const [analysisTaskId, setAnalysisTaskId] = useState<string | null>(null);

  const { data: correlations, isLoading: loadingCorrelations, error: correlationsError, refetch: refetchCorrelations } = useQuery<CorrelationMatrixResponse>({
    queryKey: ['correlations', scannerType],
    queryFn: () => fetchCorrelations(scannerType || undefined),
    retry: false,
  });

  const handleRunAnalysis = async () => {
    try {
      const result = await triggerAnalysis(scannerType || undefined);
      setAnalysisTaskId(result.task_id);
    } catch {
      // trigger failed — silently ignore, button is best-effort
    }
  };
```

**11.3 — Add the Feature Correlations card to the JSX**

In `EdgeExplorer.tsx`, at the bottom of the return statement, inside the outer `<div className="space-y-6 animate-fade-in">` but after the last existing card/section, add the new card before the closing `</div>`.

Note: `<Card>` is used here without a `title` prop — the heading and Run Analysis button are placed manually inside `children`. This is intentional: it gives layout control over the header row. Do not add a `title` prop; the manual header already renders correctly.

```tsx
      {/* Feature Correlations */}
      <Card>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-sm font-black uppercase tracking-widest text-financial-light">Feature Correlations</h2>
            <p className="text-xs text-gray-400 mt-0.5">Pearson / Spearman r for each feature × outcome interval</p>
          </div>
          <button
            onClick={handleRunAnalysis}
            className="px-4 py-1.5 text-xs font-black uppercase tracking-widest rounded-lg bg-gray-800 border border-gray-700 text-gray-300 hover:text-white hover:border-financial-blue transition-all"
          >
            Run Analysis
          </button>
        </div>

        {analysisTaskId && (
          <div className="mb-3 px-3 py-2 bg-financial-blue/10 border border-financial-blue/30 rounded-lg text-xs text-financial-blue font-bold">
            Analysis queued — task {analysisTaskId}
          </div>
        )}

        {loadingCorrelations ? (
          <div className="flex items-center justify-center h-32">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-financial-blue"></div>
          </div>
        ) : correlationsError || !correlations ? (
          <div className="flex flex-col items-center justify-center h-32 text-center">
            <p className="text-gray-500 text-xs font-bold uppercase tracking-wider">No analysis data yet.</p>
            <p className="text-gray-600 text-xs mt-1">Run analysis to populate this panel.</p>
          </div>
        ) : (
          <CorrelationHeatmap data={correlations} />
        )}
      </Card>
```

**11.4 — Verify TypeScript compiles**
```bash
cd /workspace/markethawk/frontend && npx tsc --noEmit
# Expected: no errors
```

**11.5 — Commit**
```bash
git add frontend/src/pages/EdgeExplorer.tsx
git commit -m "feat(phase-2b): add Feature Correlations card to EdgeExplorer"
```

---

## Completion Checklist

| Item | Verified by |
|------|-------------|
| `lightgbm`, `shap`, `scikit-learn`, `scipy` in requirements.txt | Task 1 test |
| `signal_analysis_runs` table exists in DB | Task 4 Python check |
| `signal_clusters` table exists in DB | Task 4 Python check |
| `scanner_events.signal_cluster_id` column exists | Task 3 test + migration |
| `StatisticalDiscoveryService` unit tests pass | Task 5 pytest |
| `analyze_signal_features` task importable | Task 6 test |
| Beat schedule entry present | Task 6 celery_app.py edit |
| `POST /api/outcomes/analyze` returns 202 | Task 8 curl |
| `GET /api/outcomes/correlations` returns 404 (no data) | Task 8 curl |
| `GET /api/outcomes/analysis/latest` returns 404 (no data) | Task 8 curl |
| `CorrelationHeatmap` component TypeScript-clean | Task 10 tsc |
| EdgeExplorer Feature Correlations card compiles | Task 11 tsc |
| All backend tests pass | `python -m pytest` |
| Frontend TypeScript clean | `npx tsc --noEmit` |
