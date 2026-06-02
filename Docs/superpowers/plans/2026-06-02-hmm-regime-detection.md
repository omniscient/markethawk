# HMM Market Regime Detection — Implementation Plan

**Date:** 2026-06-02  
**Issue:** [#106 — Integrate HMM regime detection to enhance and validate scanner signals](https://github.com/omniscient/markethawk/issues/106)  
**Spec:** [Docs/superpowers/specs/2026-05-28-hmm-regime-detection-design.md](../specs/2026-05-28-hmm-regime-detection-design.md)

## Goal

Integrate a GaussianHMM (hmmlearn) into MarketHawk's scanning pipeline to classify broad market conditions (`risk_on`, `risk_off`, `high_volatility`) and annotate each `ScannerEvent` with the prevailing regime at the time it fired. A second deliverable adds per-regime win-rate breakdowns via the existing outcomes framework.

## Architecture

- New `RegimeModel` ORM persists fitted HMM artifacts in PostgreSQL (`regime_models` table)
- New `RegimeService` trains on SPY daily bars from `stock_aggregates`, selects optimal state count via BIC, maps state indices to human-readable labels, and caches the current regime in Redis (25-hour TTL)
- `alert_service.save_event()` — the central event-creation function used by all scanner paths — calls `RegimeService.get_regime_at_date()` before persisting each `ScannerEvent`
- Two Celery tasks: `update_regime_model` (daily beat at 21:00 UTC weekdays) and `backfill_regime_labels` (one-time, back-labels all `regime IS NULL` rows)
- Two new API endpoints on `/api/outcomes`: `?regime=` filter on existing scorecard, and new `/regime-breakdown/{scanner_type}`
- Regime badge on `ScannerResults.tsx` scanner result cards (green=risk_on, red=risk_off, amber=high_volatility, gray=null)

## Tech Stack

hmmlearn (GaussianHMM), pandas/numpy (feature engineering), base64+pickle (model serialization), redis-py (cache — already in requirements.txt as `redis==7.4.0`), PostgreSQL JSONB, FastAPI, React 18 + Tailwind CSS

## File Structure

| File | Action |
|------|--------|
| `backend/requirements.txt` | Add `hmmlearn>=0.3` |
| `backend/app/models/regime_model.py` | **New** — `RegimeModel` ORM |
| `backend/app/models/__init__.py` | Add `RegimeModel` import + `__all__` entry |
| `backend/app/models/scanner_event.py` | Add `regime = Column(String(30), nullable=True, index=True)` |
| `alembic/versions/<hash>_add_regime_models_and_scanner_event_regime.py` | **New** Alembic migration |
| `backend/app/services/regime_service.py` | **New** — `RegimeService` |
| `backend/app/services/alert_service.py` | Inject regime via `RegimeService.get_regime_at_date()` in `save_event()` |
| `backend/app/tasks/regime.py` | **New** — `update_regime_model` + `backfill_regime_labels` |
| `backend/app/tasks/__init__.py` | Export new tasks |
| `backend/app/core/celery_app.py` | Register `update_regime_model` in beat schedule |
| `backend/app/schemas/regime.py` | **New** — Pydantic schemas for regime breakdown |
| `backend/app/services/stats.py` | Add `regime` filter to `get_scorecard()`; add `get_regime_breakdown()` |
| `backend/app/routers/outcomes.py` | Add `?regime=` param to scorecard; add `/regime-breakdown/{scanner_type}` |
| `frontend/src/api/scanner.ts` | Add `regime?: string | null` to `ScannerEvent` interface |
| `frontend/src/components/ScannerResults.tsx` | Render regime badge beside severity pill |
| `backend/tests/services/test_regime_service.py` | **New** — unit tests for RegimeService |
| `backend/tests/api/test_outcomes_regime.py` | **New** — integration tests for regime endpoints |

---

## Task 1 — Add hmmlearn dependency

**Files:** `backend/requirements.txt`

### Steps

Add `hmmlearn>=0.3` after `scipy==1.15.3`:

```
scipy==1.15.3
hmmlearn>=0.3
```

Rebuild and verify:

```bash
docker-compose build backend
docker-compose exec backend python -c "from hmmlearn.hmm import GaussianHMM; print('hmmlearn ok')"
# Expected: hmmlearn ok
```

### Commit

```bash
git add backend/requirements.txt
git commit -m "deps: add hmmlearn>=0.3 for HMM regime detection (#106)"
```

---

## Task 2 — RegimeModel ORM + models/__init__.py

**Files:** `backend/app/models/regime_model.py`, `backend/app/models/__init__.py`, `backend/tests/services/test_regime_service.py`

### Write failing test

The test file is created here. Only `RegimeModel` (created in this same task) is imported at the module level. The `RegimeService` import is added in Task 5 when `regime_service.py` is created — importing it here would cause a collection error for Tasks 2–4.

```python
# backend/tests/services/test_regime_service.py
"""Unit and integration tests for RegimeService and related components."""

import json
import pytest
import numpy as np
import pandas as pd
from datetime import date, datetime
from unittest.mock import MagicMock, patch

from app.models.regime_model import RegimeModel
# NOTE: RegimeService, REDIS_KEY, REDIS_TTL are imported in Task 5 when regime_service.py is created


def test_regime_model_table_name():
    assert RegimeModel.__tablename__ == "regime_models"


def test_regime_model_has_required_columns():
    cols = {c.key for c in RegimeModel.__table__.columns}
    assert {"id", "version", "status", "n_states", "model_b64",
            "feature_set", "state_label_mapping", "data_start_date",
            "data_end_date", "bic_score", "trained_at", "created_at"} <= cols
```

### Verify fail

```bash
docker-compose exec backend python -m pytest tests/services/test_regime_service.py::test_regime_model_table_name -x 2>&1 | tail -5
# Expected: ModuleNotFoundError — no module named 'app.models.regime_model'
```

### Implement

Create `backend/app/models/regime_model.py`:

```python
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, Float, DateTime, Date, Index
from sqlalchemy.dialects.postgresql import JSONB
from app.core.database import Base


def _now_utc():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class RegimeModel(Base):
    __tablename__ = "regime_models"

    id = Column(Integer, primary_key=True, index=True)
    version = Column(Integer, nullable=False, index=True)
    status = Column(String(20), nullable=False, default="active")   # active | archived
    n_states = Column(Integer, nullable=False)
    model_b64 = Column(Text, nullable=False)                        # base64-encoded pickle
    feature_set = Column(JSONB, nullable=False)                     # ["daily_return", ...]
    state_label_mapping = Column(JSONB, nullable=False)             # {"0": "risk_on", ...}
    data_start_date = Column(Date, nullable=False)
    data_end_date = Column(Date, nullable=False)
    bic_score = Column(Float, nullable=True)
    trained_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=_now_utc)

    __table_args__ = (
        Index("ix_regime_models_status_version", "status", "version"),
    )
```

Update `backend/app/models/__init__.py` — add after the `SignalReview` import line:

```python
from app.models.regime_model import RegimeModel
```

Add `"RegimeModel"` to `__all__`.

### Verify pass

```bash
docker-compose exec backend python -m pytest tests/services/test_regime_service.py::test_regime_model_table_name tests/services/test_regime_service.py::test_regime_model_has_required_columns -x
# Expected: 2 passed
```

### Commit

```bash
git add backend/app/models/regime_model.py backend/app/models/__init__.py backend/tests/services/test_regime_service.py
git commit -m "feat(models): add RegimeModel ORM for HMM artifact storage (#106)"
```

---

## Task 3 — ScannerEvent.regime column

**Files:** `backend/app/models/scanner_event.py`, `backend/tests/services/test_regime_service.py`

### Write failing test

```python
# backend/tests/services/test_regime_service.py (append)
from app.models.scanner_event import ScannerEvent


def test_scanner_event_has_regime_column():
    cols = {c.key for c in ScannerEvent.__table__.columns}
    assert "regime" in cols


def test_scanner_event_regime_nullable_and_length():
    col = ScannerEvent.__table__.columns["regime"]
    assert col.nullable is True
    assert col.type.length == 30
```

### Verify fail

```bash
docker-compose exec backend python -m pytest tests/services/test_regime_service.py::test_scanner_event_has_regime_column -x 2>&1 | tail -5
# Expected: AssertionError — 'regime' not in scanner_event columns
```

### Implement

In `backend/app/models/scanner_event.py`, after the `signal_quality_score` column, add:

```python
    regime = Column(String(30), nullable=True, index=True)
```

### Verify pass

```bash
docker-compose exec backend python -m pytest tests/services/test_regime_service.py::test_scanner_event_has_regime_column tests/services/test_regime_service.py::test_scanner_event_regime_nullable_and_length -x
# Expected: 2 passed
```

### Commit

```bash
git add backend/app/models/scanner_event.py backend/tests/services/test_regime_service.py
git commit -m "feat(models): add regime column to ScannerEvent (#106)"
```

---

## Task 4 — Alembic migration

**Files:** `alembic/versions/` (auto-generated)

### Generate and apply

```bash
docker-compose exec backend python -m alembic revision --autogenerate -m "add_regime_models_and_scanner_event_regime"
# Creates: alembic/versions/<hash>_add_regime_models_and_scanner_event_regime.py

docker-compose exec backend python -m alembic upgrade head
# Expected last line: Running upgrade <prev> -> <hash>, add_regime_models_and_scanner_event_regime
```

### Verify schema

The app uses an async SQLAlchemy engine; use a fresh sync engine for `inspect`:

```bash
docker-compose exec backend python -c "
import os
from sqlalchemy import create_engine, inspect
url = os.environ['DATABASE_URL'].replace('+asyncpg', '')
engine = create_engine(url)
i = inspect(engine)
print('regime_models:', [c['name'] for c in i.get_columns('regime_models')])
scanner_cols = [c['name'] for c in i.get_columns('scanner_events')]
print('scanner_events has regime:', 'regime' in scanner_cols)
engine.dispose()
"
# Expected:
# regime_models: ['id', 'version', 'status', 'n_states', 'model_b64', 'feature_set', 'state_label_mapping', 'data_start_date', 'data_end_date', 'bic_score', 'trained_at', 'created_at']
# scanner_events has regime: True
```

### Commit

```bash
git add alembic/versions/
git commit -m "feat(migration): create regime_models table and add scanner_events.regime (#106)"
```

---

## Task 5 — RegimeService: SPY data loading + feature matrix

**Files:** `backend/app/services/regime_service.py`, `backend/tests/services/test_regime_service.py`

### Write failing test

First, add `RegimeService` and its constants to the test file header (now that `regime_service.py` is being created in this task). Insert after the existing `from app.models.regime_model import RegimeModel` line:

```python
from app.services.regime_service import RegimeService, REDIS_KEY, REDIS_TTL
```

Then append the new test functions:

```python
# backend/tests/services/test_regime_service.py (append)
def test_build_feature_matrix_returns_none_for_too_few_rows():
    df = pd.DataFrame({"close": [100.0, 101.0, 102.0]})
    result = RegimeService._build_feature_matrix(df)
    assert result is None


def test_build_feature_matrix_returns_three_feature_columns():
    closes = [100.0 + i * 0.3 + np.random.default_rng(i).normal(0, 0.2) for i in range(60)]
    df = pd.DataFrame({"close": closes})
    result = RegimeService._build_feature_matrix(df)
    assert result is not None
    X, feature_df = result
    assert X.shape[1] == 3
    assert list(feature_df.columns) == ["daily_return", "rolling_vol_20d", "rolling_skew_20d"]
    assert not feature_df.isnull().any().any()
```

### Verify fail

```bash
docker-compose exec backend python -m pytest tests/services/test_regime_service.py::test_build_feature_matrix_returns_none_for_too_few_rows -x 2>&1 | tail -5
# Expected: ModuleNotFoundError — app.services.regime_service does not exist
```

### Implement

Create `backend/app/services/regime_service.py`:

```python
"""
RegimeService — train, persist, query, and cache HMM market regime models.
"""

import base64
import json
import logging
import pickle
from datetime import date, datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd
import redis
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.regime_model import RegimeModel
from app.models.stock_aggregate import StockAggregate

logger = logging.getLogger(__name__)

REDIS_KEY = "regime:current"
REDIS_TTL = 90000  # 25 hours in seconds
FEATURE_SET = ["daily_return", "rolling_vol_20d", "rolling_skew_20d"]


class RegimeService:

    @staticmethod
    def _fetch_spy_bars(db: Session) -> pd.DataFrame:
        """Load SPY daily bars from stock_aggregates (rolling 2-year window)."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=730)).replace(tzinfo=None)
        rows = (
            db.query(StockAggregate)
            .filter(
                StockAggregate.ticker == "SPY",
                StockAggregate.timespan == "day",
                StockAggregate.timestamp >= cutoff,
            )
            .order_by(StockAggregate.timestamp)
            .all()
        )
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame([
            {
                "date": r.timestamp.date() if hasattr(r.timestamp, "date") else r.timestamp,
                "close": float(r.close),
            }
            for r in rows
        ])

    @staticmethod
    def _build_feature_matrix(df: pd.DataFrame) -> Optional[Tuple[np.ndarray, pd.DataFrame]]:
        """Compute features. Returns None when fewer than 22 rows (20d rolling + 1 lag)."""
        if len(df) < 22:
            return None
        df = df.copy()
        df["daily_return"] = df["close"].pct_change()
        df["rolling_vol_20d"] = df["daily_return"].rolling(20).std()
        df["rolling_skew_20d"] = df["daily_return"].rolling(20).skew()
        df = df[["daily_return", "rolling_vol_20d", "rolling_skew_20d"]].dropna()
        return df.values, df
```

### Verify pass

```bash
docker-compose exec backend python -m pytest tests/services/test_regime_service.py::test_build_feature_matrix_returns_none_for_too_few_rows tests/services/test_regime_service.py::test_build_feature_matrix_returns_three_feature_columns -x
# Expected: 2 passed
```

### Commit

```bash
git add backend/app/services/regime_service.py backend/tests/services/test_regime_service.py
git commit -m "feat(services): RegimeService SPY data loading and feature matrix (#106)"
```

---

## Task 6 — RegimeService: HMM training with BIC selection

**Files:** `backend/app/services/regime_service.py`, `backend/tests/services/test_regime_service.py`

### Write failing test

```python
# backend/tests/services/test_regime_service.py (append)
def test_fit_best_hmm_selects_valid_state_count():
    rng = np.random.default_rng(42)
    X = rng.standard_normal((200, 3))
    model, n_states, bic = RegimeService._fit_best_hmm(X)
    assert model is not None
    assert 2 <= n_states <= 5
    assert isinstance(bic, float) and bic < np.inf


def test_fit_best_hmm_model_can_predict():
    rng = np.random.default_rng(0)
    X = rng.standard_normal((200, 3))
    model, n_states, _ = RegimeService._fit_best_hmm(X)
    states = model.predict(X)
    assert len(states) == 200
    assert set(states).issubset(set(range(n_states)))
```

### Verify fail

```bash
docker-compose exec backend python -m pytest tests/services/test_regime_service.py::test_fit_best_hmm_selects_valid_state_count -x 2>&1 | tail -5
# Expected: AttributeError — type object 'RegimeService' has no attribute '_fit_best_hmm'
```

### Implement

Add to `RegimeService` class in `regime_service.py`:

```python
    @staticmethod
    def _fit_best_hmm(X: np.ndarray) -> Tuple:
        """Fit GaussianHMM for n_components in {2..5}; return (model, n_states, bic) for min BIC."""
        from hmmlearn.hmm import GaussianHMM

        best_model = None
        best_bic = np.inf
        best_n = 2

        for n in range(2, 6):
            try:
                model = GaussianHMM(
                    n_components=n,
                    covariance_type="full",
                    n_iter=100,
                    random_state=42,
                )
                model.fit(X)
                # Use hmmlearn's built-in BIC method (available in hmmlearn>=0.3)
                bic = model.bic(X)
                if bic < best_bic:
                    best_bic = bic
                    best_model = model
                    best_n = n
            except Exception as exc:
                logger.warning("HMM fit failed for n_components=%d: %s", n, exc)
                continue

        return best_model, best_n, best_bic
```

### Verify pass

```bash
docker-compose exec backend python -m pytest tests/services/test_regime_service.py::test_fit_best_hmm_selects_valid_state_count tests/services/test_regime_service.py::test_fit_best_hmm_model_can_predict -x
# Expected: 2 passed
```

### Commit

```bash
git add backend/app/services/regime_service.py backend/tests/services/test_regime_service.py
git commit -m "feat(services): RegimeService BIC-driven HMM state selection (#106)"
```

---

## Task 7 — RegimeService: state label mapping

**Files:** `backend/app/services/regime_service.py`, `backend/tests/services/test_regime_service.py`

### Write failing test

```python
# backend/tests/services/test_regime_service.py (append)
from hmmlearn.hmm import GaussianHMM


def _make_mock_hmm(means_array: np.ndarray) -> GaussianHMM:
    model = GaussianHMM.__new__(GaussianHMM)
    model.n_components = len(means_array)
    model.means_ = means_array
    return model


def test_map_state_labels_assigns_three_core_labels():
    means = np.array([
        [-0.010, 0.030, 0.0],   # state 0: negative return, high vol → risk_off / high_volatility
        [ 0.020, 0.010, 0.0],   # state 1: positive return, low vol → risk_on
        [ 0.005, 0.050, 0.0],   # state 2: highest vol → high_volatility
    ])
    mapping = RegimeService._map_state_labels(_make_mock_hmm(means))
    assert set(mapping.values()) == {"risk_off", "risk_on", "high_volatility"}
    assert len(mapping) == 3


def test_map_state_labels_covers_all_states_for_n4():
    means = np.array([
        [-0.015, 0.040, 0.0],
        [ 0.020, 0.010, 0.0],
        [ 0.005, 0.060, 0.0],
        [ 0.004, 0.008, 0.0],
    ])
    mapping = RegimeService._map_state_labels(_make_mock_hmm(means))
    assert len(mapping) == 4
    assert set(mapping.keys()) == {"0", "1", "2", "3"}
```

### Verify fail

```bash
docker-compose exec backend python -m pytest tests/services/test_regime_service.py::test_map_state_labels_assigns_three_core_labels -x 2>&1 | tail -5
# Expected: AttributeError — '_map_state_labels' not found
```

### Implement

Add to `RegimeService` class:

```python
    @staticmethod
    def _map_state_labels(model) -> Dict[str, str]:
        """Map HMM state indices to regime labels based on mean return and volatility."""
        means = model.means_  # (n_states, n_features): [return, vol, skew]
        n = model.n_components

        state_info = [
            {"state": i, "mean_return": float(means[i, 0]), "mean_vol": float(means[i, 1])}
            for i in range(n)
        ]

        mapping: Dict[str, str] = {}
        assigned: set = set()

        # Priority 1: highest vol → high_volatility
        for s in sorted(state_info, key=lambda x: x["mean_vol"], reverse=True):
            if s["state"] not in assigned:
                mapping[str(s["state"])] = "high_volatility"
                assigned.add(s["state"])
                break

        # Priority 2: lowest return among remaining → risk_off
        for s in sorted(state_info, key=lambda x: x["mean_return"]):
            if s["state"] not in assigned:
                mapping[str(s["state"])] = "risk_off"
                assigned.add(s["state"])
                break

        # Priority 3: highest return among remaining → risk_on
        for s in sorted(state_info, key=lambda x: x["mean_return"], reverse=True):
            if s["state"] not in assigned:
                mapping[str(s["state"])] = "risk_on"
                assigned.add(s["state"])
                break

        # Remaining: low_vol_drift (N=4) or transition (N=5)
        extra_labels = ["low_vol_drift", "transition"]
        extra_idx = 0
        for s in state_info:
            if s["state"] not in assigned:
                mapping[str(s["state"])] = extra_labels[extra_idx % len(extra_labels)]
                assigned.add(s["state"])
                extra_idx += 1

        return mapping
```

### Verify pass

```bash
docker-compose exec backend python -m pytest tests/services/test_regime_service.py::test_map_state_labels_assigns_three_core_labels tests/services/test_regime_service.py::test_map_state_labels_covers_all_states_for_n4 -x
# Expected: 2 passed
```

### Commit

```bash
git add backend/app/services/regime_service.py backend/tests/services/test_regime_service.py
git commit -m "feat(services): RegimeService state label mapping algorithm (#106)"
```

---

## Task 8 — RegimeService: train_and_persist() + Redis cache write

**Files:** `backend/app/services/regime_service.py`, `backend/tests/services/test_regime_service.py`

### Write failing test

```python
# backend/tests/services/test_regime_service.py (append)
from unittest.mock import MagicMock, patch


def test_train_and_persist_returns_none_when_no_spy_data(db):
    with patch.object(RegimeService, "_fetch_spy_bars", return_value=pd.DataFrame()):
        result = RegimeService.train_and_persist(db)
    assert result is None


def test_train_and_persist_returns_active_regime_model(db):
    closes = [100.0 + i * 0.4 + np.random.default_rng(i).normal(0, 0.3) for i in range(600)]
    spy_df = pd.DataFrame({"close": closes, "date": [f"2024-01-{(i % 28) + 1:02d}" for i in range(600)]})
    mock_redis = MagicMock()
    with (
        patch.object(RegimeService, "_fetch_spy_bars", return_value=spy_df),
        patch("app.services.regime_service.redis.from_url", return_value=mock_redis),
    ):
        result = RegimeService.train_and_persist(db)
    assert result is not None
    assert result.status == "active"
    assert 2 <= result.n_states <= 5
    assert isinstance(result.state_label_mapping, dict)
    mock_redis.setex.assert_called_once_with(REDIS_KEY, REDIS_TTL, mock_redis.setex.call_args[0][2])
```

### Verify fail

```bash
docker-compose exec backend python -m pytest tests/services/test_regime_service.py::test_train_and_persist_returns_none_when_no_spy_data -x 2>&1 | tail -5
# Expected: AttributeError — 'train_and_persist' not found
```

### Implement

Add to `RegimeService` class (also add `from app.services.regime_service import REDIS_KEY, REDIS_TTL` in test file):

```python
    @staticmethod
    def train_and_persist(db: Session) -> Optional[RegimeModel]:
        """Fetch SPY bars, fit best-BIC HMM, persist to DB, update Redis current-regime cache."""
        df = RegimeService._fetch_spy_bars(db)
        if df.empty:
            logger.warning("train_and_persist: no SPY daily bars found; skipping.")
            return None

        result = RegimeService._build_feature_matrix(df)
        if result is None:
            logger.warning("train_and_persist: insufficient rows after feature computation; skipping.")
            return None

        X, feature_df = result
        if len(X) < 500:
            logger.warning("train_and_persist: only %d SPY bars available (< 500); proceeding.", len(X))

        model, n_states, bic = RegimeService._fit_best_hmm(X)
        if model is None:
            logger.error("train_and_persist: all HMM fits failed.")
            return None

        state_label_mapping = RegimeService._map_state_labels(model)
        model_b64 = base64.b64encode(pickle.dumps(model)).decode("utf-8")

        db.query(RegimeModel).filter(RegimeModel.status == "active").update({"status": "archived"})

        next_version = db.query(RegimeModel).count() + 1
        data_start = df["date"].min() if "date" in df.columns else None
        data_end = df["date"].max() if "date" in df.columns else None
        trained_at = datetime.now(timezone.utc).replace(tzinfo=None)

        new_model = RegimeModel(
            version=next_version,
            status="active",
            n_states=n_states,
            model_b64=model_b64,
            feature_set=FEATURE_SET,
            state_label_mapping=state_label_mapping,
            data_start_date=data_start,
            data_end_date=data_end,
            bic_score=float(bic),
            trained_at=trained_at,
        )
        db.add(new_model)
        db.flush()

        last_state = int(model.predict(X)[-1])
        current_regime = state_label_mapping.get(str(last_state), "unknown")
        cache_payload = json.dumps({
            "regime": current_regime,
            "as_of_date": str(data_end),
            "model_version": next_version,
        })
        try:
            r = redis.from_url(settings.REDIS_URL)
            r.setex(REDIS_KEY, REDIS_TTL, cache_payload)
        except Exception as exc:
            logger.warning("train_and_persist: Redis cache write failed: %s", exc)

        db.commit()
        logger.info(
            "train_and_persist: n_states=%d BIC=%.2f regime=%s version=%d",
            n_states, bic, current_regime, next_version,
        )
        return new_model
```

### Verify pass

```bash
docker-compose exec backend python -m pytest tests/services/test_regime_service.py::test_train_and_persist_returns_none_when_no_spy_data tests/services/test_regime_service.py::test_train_and_persist_returns_active_regime_model -x
# Expected: 2 passed
```

### Commit

```bash
git add backend/app/services/regime_service.py backend/tests/services/test_regime_service.py
git commit -m "feat(services): RegimeService train_and_persist with Redis caching (#106)"
```

---

## Task 9 — RegimeService: get_current_regime() + get_regime_at_date()

**Files:** `backend/app/services/regime_service.py`, `backend/tests/services/test_regime_service.py`

### Write failing test

```python
# backend/tests/services/test_regime_service.py (append)
from datetime import date


def test_get_current_regime_reads_from_redis():
    payload = json.dumps({"regime": "risk_on", "as_of_date": "2026-06-01", "model_version": 1})
    mock_redis = MagicMock()
    mock_redis.get.return_value = payload.encode()
    with patch("app.services.regime_service.redis.from_url", return_value=mock_redis):
        result = RegimeService.get_current_regime()
    assert result == "risk_on"


def test_get_current_regime_returns_none_on_redis_miss():
    mock_redis = MagicMock()
    mock_redis.get.return_value = None
    with patch("app.services.regime_service.redis.from_url", return_value=mock_redis):
        result = RegimeService.get_current_regime()
    assert result is None


def test_get_regime_at_date_returns_none_when_no_active_model(db):
    result = RegimeService.get_regime_at_date(db, date(2025, 3, 15))
    assert result is None
```

### Verify fail

```bash
docker-compose exec backend python -m pytest tests/services/test_regime_service.py::test_get_current_regime_reads_from_redis -x 2>&1 | tail -5
# Expected: AttributeError — 'get_current_regime' not found
```

### Implement

Add imports at test file top: `import json`

Add methods to `RegimeService`:

```python
    @staticmethod
    def get_current_regime() -> Optional[str]:
        """Read current regime label from Redis. Returns None on cache miss or error."""
        try:
            r = redis.from_url(settings.REDIS_URL)
            raw = r.get(REDIS_KEY)
            if raw:
                return json.loads(raw).get("regime")
        except Exception as exc:
            logger.warning("get_current_regime: Redis error: %s", exc)
        return None

    @staticmethod
    def get_regime_at_date(db: Session, target_date) -> Optional[str]:
        """
        Return the regime label for target_date.

        - For today: tries Redis cache first, then falls back to DB prediction.
        - For historical dates: loads active model from DB, predicts on SPY bars up to that date.
        """
        today = datetime.now(timezone.utc).date()
        if isinstance(target_date, datetime):
            target_date = target_date.date()

        if target_date == today:
            cached = RegimeService.get_current_regime()
            if cached:
                return cached

        active_row = (
            db.query(RegimeModel)
            .filter(RegimeModel.status == "active")
            .order_by(RegimeModel.version.desc())
            .first()
        )
        if not active_row:
            return None

        try:
            model = pickle.loads(base64.b64decode(active_row.model_b64))
            state_label_mapping = active_row.state_label_mapping
        except Exception as exc:
            logger.error("get_regime_at_date: model deserialization failed: %s", exc)
            return None

        cutoff = datetime.combine(target_date, datetime.min.time()) - timedelta(days=730)
        target_dt = datetime.combine(target_date, datetime.max.time())
        rows = (
            db.query(StockAggregate)
            .filter(
                StockAggregate.ticker == "SPY",
                StockAggregate.timespan == "day",
                StockAggregate.timestamp >= cutoff,
                StockAggregate.timestamp <= target_dt,
            )
            .order_by(StockAggregate.timestamp)
            .all()
        )
        if not rows:
            return None

        df = pd.DataFrame([{"close": float(r.close)} for r in rows])
        result = RegimeService._build_feature_matrix(df)
        if result is None:
            return None

        X, _ = result
        try:
            states = model.predict(X)
            return state_label_mapping.get(str(int(states[-1])))
        except Exception as exc:
            logger.error("get_regime_at_date: prediction failed: %s", exc)
            return None
```

### Verify pass

```bash
docker-compose exec backend python -m pytest tests/services/test_regime_service.py::test_get_current_regime_reads_from_redis tests/services/test_regime_service.py::test_get_current_regime_returns_none_on_redis_miss tests/services/test_regime_service.py::test_get_regime_at_date_returns_none_when_no_active_model -x
# Expected: 3 passed
```

### Commit

```bash
git add backend/app/services/regime_service.py backend/tests/services/test_regime_service.py
git commit -m "feat(services): RegimeService get_current_regime and get_regime_at_date (#106)"
```

---

## Task 10 — Inject regime in alert_service.save_event()

**Files:** `backend/app/services/alert_service.py`, `backend/tests/services/test_regime_service.py`

### Write failing test

```python
# backend/tests/services/test_regime_service.py (append)
from app.services.alert_service import save_event


def test_save_event_populates_regime_field(db):
    with patch("app.services.alert_service.RegimeService.get_regime_at_date", return_value="risk_on"):
        result = save_event(
            db=db,
            ticker="AAPL",
            event_date=date(2026, 6, 2),
            scanner_type="pre_market_volume_spike",
            indicators={"volume_spike_ratio": 6.0, "gap_pct": 2.5},
            criteria_met={"volume_ok": True},
            enrichment={},
        )
    assert result.get("regime") == "risk_on"


def test_save_event_regime_is_none_when_service_returns_none(db):
    with patch("app.services.alert_service.RegimeService.get_regime_at_date", return_value=None):
        result = save_event(
            db=db,
            ticker="MSFT",
            event_date=date(2026, 6, 2),
            scanner_type="pre_market_volume_spike",
            indicators={"volume_spike_ratio": 3.5, "gap_pct": 1.1},
            criteria_met={},
            enrichment={},
        )
    assert result.get("regime") is None
```

### Verify fail

```bash
docker-compose exec backend python -m pytest tests/services/test_regime_service.py::test_save_event_populates_regime_field -x 2>&1 | tail -5
# Expected: AssertionError — 'regime' key absent from returned dict
```

### Implement

In `backend/app/services/alert_service.py`, add to the imports inside `save_event()`:

```python
    from app.services.regime_service import RegimeService
```

After the `score = None` block, add:

```python
    try:
        regime = RegimeService.get_regime_at_date(db, event_date)
    except Exception as exc:
        logger.warning("save_event: regime lookup failed for %s %s: %s", ticker, event_date, exc)
        regime = None
```

Add `"regime": regime` to `event_dict` (after `"signal_quality_score": score`):

```python
    event_dict = {
        "ticker": ticker,
        "event_date": event_date,
        "scanner_type": scanner_type,
        "summary": summary,
        "severity": severity,
        "previous_close": previous_close,
        "opening_price": opening_price,
        "closing_price": closing_price,
        "indicators": indicators,
        "criteria_met": criteria_met,
        "metadata": enrichment,
        "signal_quality_score": score,
        "regime": regime,
    }
```

Verify `logger` is defined at module level in `alert_service.py`. If not, add near the top:

```python
import logging
logger = logging.getLogger(__name__)
```

No changes needed to the update/insert branches — the `setattr` loop handles `regime` automatically, and `model_data = event_dict.copy()` already includes it for new events.

### Verify pass

```bash
docker-compose exec backend python -m pytest tests/services/test_regime_service.py::test_save_event_populates_regime_field tests/services/test_regime_service.py::test_save_event_regime_is_none_when_service_returns_none -x
# Expected: 2 passed
```

### Commit

```bash
git add backend/app/services/alert_service.py backend/tests/services/test_regime_service.py
git commit -m "feat(services): inject regime into save_event via RegimeService (#106)"
```

---

## Task 11 — Celery tasks: update_regime_model + backfill_regime_labels

**Files:** `backend/app/tasks/regime.py`, `backend/tests/services/test_regime_service.py`

### Write failing test

```python
# backend/tests/services/test_regime_service.py (append)
def test_regime_tasks_are_importable():
    from app.tasks.regime import update_regime_model, backfill_regime_labels
    assert callable(update_regime_model)
    assert callable(backfill_regime_labels)


def test_update_regime_model_task_calls_train_and_persist():
    from app.tasks.regime import update_regime_model
    with patch("app.tasks.regime.RegimeService.train_and_persist") as mock_train:
        mock_train.return_value = MagicMock(n_states=3, version=1)
        update_regime_model.apply()
    mock_train.assert_called_once()
```

### Verify fail

```bash
docker-compose exec backend python -m pytest tests/services/test_regime_service.py::test_regime_tasks_are_importable -x 2>&1 | tail -5
# Expected: ModuleNotFoundError — no module named 'app.tasks.regime'
```

### Implement

Create `backend/app/tasks/regime.py`:

```python
"""
Celery tasks for HMM regime model training and back-labeling.
"""

import logging

from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.services.regime_service import RegimeService

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=0, name="app.tasks.update_regime_model")
def update_regime_model(self):
    """Re-train HMM on rolling 2-year SPY window; write new model to DB + Redis cache."""
    db = SessionLocal()
    try:
        result = RegimeService.train_and_persist(db)
        if result:
            logger.info(
                "update_regime_model: done; n_states=%d version=%d",
                result.n_states, result.version,
            )
        else:
            logger.warning("update_regime_model: train_and_persist returned None (no SPY data?)")
    except Exception as exc:
        logger.exception("update_regime_model: failed: %s", exc)
        raise
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=0, name="app.tasks.backfill_regime_labels")
def backfill_regime_labels(self):
    """One-time task: back-label all ScannerEvent rows where regime IS NULL."""
    from app.models.scanner_event import ScannerEvent

    db = SessionLocal()
    try:
        null_dates = (
            db.query(ScannerEvent.event_date)
            .filter(ScannerEvent.regime.is_(None))
            .distinct()
            .all()
        )
        unique_dates = [row.event_date for row in null_dates]
        logger.info("backfill_regime_labels: %d unique dates to label", len(unique_dates))

        labeled = 0
        for event_date in unique_dates:
            regime = RegimeService.get_regime_at_date(db, event_date)
            if regime:
                count = (
                    db.query(ScannerEvent)
                    .filter(
                        ScannerEvent.event_date == event_date,
                        ScannerEvent.regime.is_(None),
                    )
                    .update({"regime": regime})
                )
                labeled += count

        db.commit()
        logger.info(
            "backfill_regime_labels: labeled %d rows across %d dates",
            labeled, len(unique_dates),
        )
    except Exception as exc:
        logger.exception("backfill_regime_labels: failed: %s", exc)
        db.rollback()
        raise
    finally:
        db.close()
```

### Verify pass

```bash
docker-compose exec backend python -m pytest tests/services/test_regime_service.py::test_regime_tasks_are_importable tests/services/test_regime_service.py::test_update_regime_model_task_calls_train_and_persist -x
# Expected: 2 passed
```

### Commit

```bash
git add backend/app/tasks/regime.py backend/tests/services/test_regime_service.py
git commit -m "feat(tasks): add update_regime_model and backfill_regime_labels Celery tasks (#106)"
```

---

## Task 12 — Register tasks in tasks/__init__.py + beat schedule

**Files:** `backend/app/tasks/__init__.py`, `backend/app/core/celery_app.py`, `backend/tests/services/test_regime_service.py`

### Write failing test

```python
# backend/tests/services/test_regime_service.py (append)
def test_tasks_package_exports_regime_tasks():
    from app.tasks import update_regime_model, backfill_regime_labels
    assert update_regime_model.name == "app.tasks.update_regime_model"
    assert backfill_regime_labels.name == "app.tasks.backfill_regime_labels"


def test_regime_beat_task_in_schedule():
    from app.core.celery_app import celery_app
    schedule = celery_app.conf.beat_schedule
    assert "update-regime-model-nightly" in schedule
    assert schedule["update-regime-model-nightly"]["task"] == "app.tasks.update_regime_model"
```

### Verify fail

```bash
docker-compose exec backend python -m pytest tests/services/test_regime_service.py::test_tasks_package_exports_regime_tasks -x 2>&1 | tail -5
# Expected: ImportError — cannot import name 'update_regime_model' from 'app.tasks'
```

### Implement

In `backend/app/tasks/__init__.py`, add after the `quality` import block:

```python
from app.tasks.regime import (
    update_regime_model,
    backfill_regime_labels,
)
```

Add to `__all__`:

```python
    # regime
    "update_regime_model",
    "backfill_regime_labels",
```

In `backend/app/core/celery_app.py`, add to `beat_schedule` dict:

```python
    # HMM regime retraining: 21:00 UTC weekdays (17:00 ET / 16:00 EDT — post market-close)
    'update-regime-model-nightly': {
        'task': 'app.tasks.update_regime_model',
        'schedule': crontab(minute='0', hour='21', day_of_week='1-5'),
    },
```

### Verify pass

```bash
docker-compose exec backend python -m pytest tests/services/test_regime_service.py::test_tasks_package_exports_regime_tasks tests/services/test_regime_service.py::test_regime_beat_task_in_schedule -x
# Expected: 2 passed
```

Also update `backend/tests/tasks/test_package_exports.py` — the existing test asserts exhaustiveness of the tasks package, beat schedule names, and submodule task lists. Add the two new tasks:

1. Add `"update_regime_model"` and `"backfill_regime_labels"` to the `PUBLIC_TASKS` list
2. Add `"app.tasks.regime": ["update_regime_model", "backfill_regime_labels"]` to the `SUBMODULE_TASKS` dict
3. Add `"update-regime-model-nightly"` to the `beat_task_names` list

Without this, `test_package_exports.py` will fail after this commit.

### Commit

```bash
git add backend/app/tasks/__init__.py backend/app/core/celery_app.py backend/tests/services/test_regime_service.py backend/tests/tasks/test_package_exports.py
git commit -m "feat(tasks): register regime tasks in package and beat schedule (#106)"
```

---

## Task 13 — Pydantic schemas for regime breakdown

**Files:** `backend/app/schemas/regime.py`, `backend/tests/api/test_outcomes_regime.py`

### Write failing test

Create `backend/tests/api/test_outcomes_regime.py`:

```python
"""
Integration tests for regime-related outcomes endpoints.
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.schemas.regime import RegimeSliceSchema, RegimeBreakdownResponse

client = TestClient(app)


def test_regime_slice_schema_fields():
    s = RegimeSliceSchema(sample_size=10, win_rate_pct=60.0, avg_mfe_pct=2.1, avg_mae_pct=1.2)
    assert s.sample_size == 10
    assert s.win_rate_pct == 60.0


def test_regime_breakdown_response_structure():
    resp = RegimeBreakdownResponse(
        scanner_type="pre_market_volume_spike",
        total_events=100,
        breakdown={
            "risk_on": RegimeSliceSchema(
                sample_size=60, win_rate_pct=65.0, avg_mfe_pct=3.0, avg_mae_pct=1.0
            )
        },
    )
    assert resp.total_events == 100
    assert "risk_on" in resp.breakdown
```

### Verify fail

```bash
docker-compose exec backend python -m pytest tests/api/test_outcomes_regime.py::test_regime_slice_schema_fields -x 2>&1 | tail -5
# Expected: ModuleNotFoundError — no module named 'app.schemas.regime'
```

### Implement

Create `backend/app/schemas/regime.py`:

```python
from typing import Dict, Optional
from pydantic import BaseModel


class RegimeSliceSchema(BaseModel):
    sample_size: int
    win_rate_pct: Optional[float]
    avg_mfe_pct: Optional[float]
    avg_mae_pct: Optional[float]


class RegimeBreakdownResponse(BaseModel):
    scanner_type: str
    total_events: int
    breakdown: Dict[str, RegimeSliceSchema]
```

### Verify pass

```bash
docker-compose exec backend python -m pytest tests/api/test_outcomes_regime.py::test_regime_slice_schema_fields tests/api/test_outcomes_regime.py::test_regime_breakdown_response_structure -x
# Expected: 2 passed
```

Also update `backend/app/schemas/__init__.py` to export the new schema (following the existing convention):

```python
from app.schemas.regime import RegimeSliceSchema, RegimeBreakdownResponse
```

Add both to `__all__` if it exists.

### Commit

```bash
git add backend/app/schemas/regime.py backend/app/schemas/__init__.py backend/tests/api/test_outcomes_regime.py
git commit -m "feat(schemas): add RegimeSliceSchema and RegimeBreakdownResponse (#106)"
```

---

## Task 14 — StatsService: regime filter + get_regime_breakdown()

**Files:** `backend/app/services/stats.py`, `backend/tests/api/test_outcomes_regime.py`

### Write failing test

```python
# backend/tests/api/test_outcomes_regime.py (append)
from sqlalchemy.orm import Session
from app.services.stats import StatsService


def test_get_scorecard_accepts_regime_filter(db: Session):
    result = StatsService.get_scorecard(db, "pre_market_volume_spike", regime="risk_on")
    assert "scanner_type" in result
    assert result["scanner_type"] == "pre_market_volume_spike"


def test_get_regime_breakdown_returns_expected_shape(db: Session):
    result = StatsService.get_regime_breakdown(db, "pre_market_volume_spike")
    assert result["scanner_type"] == "pre_market_volume_spike"
    assert "total_events" in result
    assert "breakdown" in result
    assert isinstance(result["breakdown"], dict)


def test_get_regime_breakdown_empty_db_has_no_breakdown(db: Session):
    result = StatsService.get_regime_breakdown(db, "pre_market_volume_spike")
    assert result["total_events"] == 0
    assert result["breakdown"] == {}
```

### Verify fail

```bash
docker-compose exec backend python -m pytest tests/api/test_outcomes_regime.py::test_get_scorecard_accepts_regime_filter -x 2>&1 | tail -5
# Expected: TypeError — get_scorecard() got an unexpected keyword argument 'regime'
```

### Implement

In `backend/app/services/stats.py`, modify `get_scorecard()` signature to add `regime`:

```python
    @staticmethod
    def get_scorecard(
        db: Session,
        scanner_type: str,
        start_date=None,
        end_date=None,
        severity: Optional[str] = None,
        regime: Optional[str] = None,
    ) -> Dict[str, Any]:
```

Add the filter after the `severity` filter block:

```python
        if regime:
            query = query.filter(ScannerEvent.regime == regime)
```

Add `get_regime_breakdown()` at the end of the `StatsService` class:

```python
    @staticmethod
    def get_regime_breakdown(
        db: Session,
        scanner_type: str,
        start_date=None,
        end_date=None,
    ) -> Dict[str, Any]:
        """Per-regime win-rate, avg MFE, avg MAE, and sample size for a scanner type."""
        from collections import defaultdict

        query = (
            db.query(ScannerOutcomeSummary, ScannerEvent.regime)
            .join(ScannerEvent, ScannerEvent.id == ScannerOutcomeSummary.scanner_event_id)
            .filter(
                ScannerEvent.scanner_type == scanner_type,
                ScannerEvent.regime.isnot(None),
            )
        )
        if start_date:
            query = query.filter(ScannerEvent.event_date >= start_date)
        if end_date:
            query = query.filter(ScannerEvent.event_date <= end_date)

        rows = query.all()

        total_events = (
            db.query(ScannerEvent)
            .filter(ScannerEvent.scanner_type == scanner_type)
            .count()
        )

        by_regime: Dict[str, list] = defaultdict(list)
        for summary, regime in rows:
            if summary.is_complete:
                by_regime[regime].append(summary)

        breakdown = {}
        for regime_label, summaries in by_regime.items():
            n = len(summaries)
            wins = [s for s in summaries if s.eod_pct_change is not None and float(s.eod_pct_change) > 0]
            mfe_vals = [float(s.mfe_pct) for s in summaries if s.mfe_pct is not None]
            mae_vals = [float(s.mae_pct) for s in summaries if s.mae_pct is not None]
            breakdown[regime_label] = {
                "sample_size": n,
                "win_rate_pct": round(len(wins) / n * 100, 2) if n else None,
                "avg_mfe_pct": round(sum(mfe_vals) / len(mfe_vals), 4) if mfe_vals else None,
                "avg_mae_pct": round(sum(mae_vals) / len(mae_vals), 4) if mae_vals else None,
            }

        return {"scanner_type": scanner_type, "total_events": total_events, "breakdown": breakdown}
```

### Verify pass

```bash
docker-compose exec backend python -m pytest tests/api/test_outcomes_regime.py::test_get_scorecard_accepts_regime_filter tests/api/test_outcomes_regime.py::test_get_regime_breakdown_returns_expected_shape tests/api/test_outcomes_regime.py::test_get_regime_breakdown_empty_db_has_no_breakdown -x
# Expected: 3 passed
```

### Commit

```bash
git add backend/app/services/stats.py backend/tests/api/test_outcomes_regime.py
git commit -m "feat(services): StatsService regime filter and get_regime_breakdown (#106)"
```

---

## Task 15 — Outcomes router: ?regime= param + /regime-breakdown/ endpoint

**Files:** `backend/app/routers/outcomes.py`, `backend/tests/api/test_outcomes_regime.py`

### Write failing test

```python
# backend/tests/api/test_outcomes_regime.py (append)
def test_scorecard_endpoint_accepts_regime_param(db: Session):
    resp = client.get("/api/outcomes/scorecard/pre_market_volume_spike?regime=risk_on")
    assert resp.status_code == 200
    data = resp.json()
    assert data["scanner_type"] == "pre_market_volume_spike"


def test_regime_breakdown_endpoint_shape(db: Session):
    resp = client.get("/api/outcomes/regime-breakdown/pre_market_volume_spike")
    assert resp.status_code == 200
    data = resp.json()
    assert data["scanner_type"] == "pre_market_volume_spike"
    assert "total_events" in data
    assert "breakdown" in data


def test_regime_breakdown_empty_returns_empty_breakdown(db: Session):
    resp = client.get("/api/outcomes/regime-breakdown/pre_market_volume_spike")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_events"] == 0
    assert data["breakdown"] == {}
```

### Verify fail

```bash
docker-compose exec backend python -m pytest tests/api/test_outcomes_regime.py::test_scorecard_endpoint_accepts_regime_param -x 2>&1 | tail -5
# Expected: 422 Unprocessable Entity — regime not an accepted query param yet
```

### Implement

In `backend/app/routers/outcomes.py`, add import:

```python
from app.schemas.regime import RegimeBreakdownResponse
```

Modify **both** scorecard endpoints to accept and forward `regime`. Show both updated signatures explicitly — the `regime=regime` kwarg must appear in each `StatsService.get_scorecard(...)` call:

```python
@router.get("/scorecard")
def get_scorecard(
    scanner_type: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    severity: Optional[str] = None,
    regime: Optional[str] = None,
    db: Session = Depends(get_db),
):
    if not scanner_type:
        raise HTTPException(status_code=400, detail="scanner_type is required")
    return StatsService.get_scorecard(db, scanner_type, start_date, end_date, severity, regime)


@router.get("/scorecard/{scanner_type}")
def get_scorecard_by_type(
    scanner_type: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    severity: Optional[str] = None,
    regime: Optional[str] = None,
    db: Session = Depends(get_db),
):
    return StatsService.get_scorecard(db, scanner_type, start_date, end_date, severity, regime)
```

Add new endpoint before the `@router.post("/backfill")` line. The dict returned by `get_regime_breakdown()` has keys `scanner_type`, `total_events`, `breakdown` — these match `RegimeBreakdownResponse` field names exactly:

```python
@router.get("/regime-breakdown/{scanner_type}", response_model=RegimeBreakdownResponse)
def get_regime_breakdown(
    scanner_type: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db),
):
    result = StatsService.get_regime_breakdown(db, scanner_type, start_date, end_date)
    return RegimeBreakdownResponse(**result)
```

### Verify pass

```bash
docker-compose exec backend python -m pytest tests/api/test_outcomes_regime.py -x
# Expected: all 8 tests pass
```

### Validate live

```bash
docker-compose logs backend --tail=5
# Expected: no errors after reload

curl -s "http://localhost:8000/api/outcomes/scorecard/pre_market_volume_spike?regime=risk_on" | python -m json.tool
# Expected: {"scanner_type": "pre_market_volume_spike", "total_signals": 0, ...}

curl -s "http://localhost:8000/api/outcomes/regime-breakdown/pre_market_volume_spike" | python -m json.tool
# Expected: {"scanner_type": "pre_market_volume_spike", "total_events": 0, "breakdown": {}}
```

### Commit

```bash
git add backend/app/routers/outcomes.py backend/tests/api/test_outcomes_regime.py
git commit -m "feat(api): add regime filter to scorecard and regime-breakdown endpoint (#106)"
```

---

## Task 16 — Frontend: regime field + regime badge

**Files:** `backend/app/schemas/event.py`, `frontend/src/api/scanner.ts`, `frontend/src/components/ScannerResults.tsx`

### Baseline type check

```bash
cd frontend && npx tsc --noEmit 2>&1 | wc -l
# Note the line count — new changes must not increase it
```

### Implement

**Step 0 — `backend/app/schemas/event.py`** (required so the API serializes `regime` to the frontend)

Find the `ScannerEventResponse` Pydantic schema. Add `regime` field after `signal_quality_score`:

```python
    regime: Optional[str] = None
```

Ensure `Optional` is imported from `typing`. Without this, FastAPI will exclude the field from JSON responses even though the ORM model has it — the frontend would always see `regime: undefined`.

**Step 1 — `frontend/src/api/scanner.ts`**

Find the `ScannerEvent` interface (or equivalent `ScannerEventResponse` type). Add after `signal_quality_score`:

```typescript
  regime?: string | null;
```

**Step 2 — `frontend/src/components/ScannerResults.tsx`**

Add helper functions near the top of the file (after `getSeverityStyle`):

```typescript
const getRegimeStyle = (regime: string | null | undefined): string => {
  switch (regime) {
    case 'risk_on':       return 'bg-green-500/20 text-green-400 border-green-500/30';
    case 'risk_off':      return 'bg-red-500/20 text-red-400 border-red-500/30';
    case 'high_volatility': return 'bg-amber-500/20 text-amber-400 border-amber-500/30';
    case 'low_vol_drift': return 'bg-blue-500/20 text-blue-400 border-blue-500/30';
    default:              return 'bg-gray-500/20 text-gray-400 border-gray-500/30';
  }
};

const getRegimeLabel = (regime: string | null | undefined): string => {
  switch (regime) {
    case 'risk_on':         return 'risk-on';
    case 'risk_off':        return 'risk-off';
    case 'high_volatility': return 'high-vol';
    case 'low_vol_drift':   return 'low-vol';
    case 'transition':      return 'trans';
    default:                return regime ?? '—';
  }
};
```

Render the regime badge **inline inside the same `<td>` cell** as the severity pill (spec: "beside the severity pill") — do not add a new table column or `<th>` header, which would misalign the column count. Find the severity pill `<span>` (around line 271) and add the regime badge immediately after it, inside the same parent element:

```tsx
{/* existing severity pill */}
<span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold uppercase border shadow-sm ${getSeverityStyle(event.severity)}`}>
  {event.severity}
</span>
{/* regime badge — inline, same cell */}
{event.regime !== undefined && (
  <span
    className={`ml-1 inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold uppercase border shadow-sm ${getRegimeStyle(event.regime)}`}
    title={event.regime ?? 'unknown regime'}
  >
    {getRegimeLabel(event.regime)}
  </span>
)}
```

### Verify pass

```bash
cd frontend && npx tsc --noEmit
# Expected: 0 new errors (same or fewer than baseline)
```

### Commit

```bash
git add backend/app/schemas/event.py frontend/src/api/scanner.ts frontend/src/components/ScannerResults.tsx
git commit -m "feat(frontend): add regime badge to scanner result cards (#106)"
```

---

## Summary

| # | Task | Files changed | Tests added |
|---|------|---------------|-------------|
| 1 | hmmlearn dependency | `requirements.txt` | docker verify |
| 2 | RegimeModel ORM | `models/regime_model.py`, `models/__init__.py` | 2 unit |
| 3 | ScannerEvent.regime column | `models/scanner_event.py` | 2 unit |
| 4 | Alembic migration | `alembic/versions/` | schema verify |
| 5 | RegimeService: feature matrix | `services/regime_service.py` | 2 unit |
| 6 | RegimeService: BIC HMM training | `services/regime_service.py` | 2 unit |
| 7 | RegimeService: label mapping | `services/regime_service.py` | 2 unit |
| 8 | RegimeService: train_and_persist | `services/regime_service.py` | 2 unit |
| 9 | RegimeService: get_regime_at_date | `services/regime_service.py` | 3 unit |
| 10 | Inject regime in save_event | `services/alert_service.py` | 2 unit |
| 11 | Celery regime tasks | `tasks/regime.py` | 2 unit |
| 12 | Register tasks + beat schedule | `tasks/__init__.py`, `celery_app.py` | 2 unit |
| 13 | Pydantic schemas | `schemas/regime.py` | 2 unit |
| 14 | StatsService breakdown | `services/stats.py` | 3 unit |
| 15 | Outcomes router endpoints | `routers/outcomes.py` | 3 integration |
| 16 | Backend schema + frontend regime badge | `schemas/event.py`, `api/scanner.ts`, `ScannerResults.tsx` | tsc check |

**Total:** 16 tasks, 33 test assertions
