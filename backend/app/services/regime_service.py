"""
RegimeService — HMM-based market regime detection.

Trains a GaussianHMM on SPY daily bars from stock_aggregates, selects optimal
state count via BIC, maps state indices to human-readable labels, and caches
the current regime in Redis with a 25-hour TTL.
"""

import base64
import logging
import pickle
from datetime import date, datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.regime_model import RegimeModel
from app.models.stock_aggregate import StockAggregate
from app.utils.time import utc_now

logger = logging.getLogger(__name__)

REDIS_KEY = "regime:current"
REDIS_TTL = 25 * 3600  # 25 hours
FEATURE_SET = ["daily_return", "rolling_vol_20d", "rolling_skew_20d"]
MIN_TRAINING_ROWS = 500
LOOKBACK_DAYS = 730  # ~2 years


class RegimeService:
    # ──────────────────────────────────────────────────────────────────────
    # Feature engineering
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _build_feature_matrix(df: pd.DataFrame) -> Optional[np.ndarray]:
        """Build (N, 3) feature matrix from a DataFrame with a 'close' column.

        Returns None when fewer than MIN_TRAINING_ROWS bars are available after
        computing rolling statistics (which require 20+ prior rows).
        """
        if len(df) < 21:
            return None

        df = df.copy().sort_values(
            "timestamp" if "timestamp" in df.columns else df.index.name or df.index
        )
        closes = df["close"].astype(float)

        daily_return = closes.pct_change()
        rolling_vol = daily_return.rolling(20).std()
        rolling_skew = daily_return.rolling(20).skew()

        features = pd.DataFrame(
            {
                "daily_return": daily_return,
                "rolling_vol_20d": rolling_vol,
                "rolling_skew_20d": rolling_skew,
            }
        ).dropna()

        if len(features) < MIN_TRAINING_ROWS:
            return None

        return features.values

    # ──────────────────────────────────────────────────────────────────────
    # HMM training
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _fit_best_hmm(X: np.ndarray):
        """Fit GaussianHMM for n_states in {2..5}; return model with lowest BIC."""
        from hmmlearn.hmm import GaussianHMM

        best_model = None
        best_bic = np.inf

        for n in range(2, 6):
            try:
                model = GaussianHMM(
                    n_components=n,
                    covariance_type="full",
                    n_iter=100,
                    random_state=42,
                )
                model.fit(X)
                bic = _compute_bic(model, X)
                if bic < best_bic:
                    best_bic = bic
                    best_model = model
            except Exception as exc:
                logger.warning("HMM fit failed for n_states=%d: %s", n, exc)

        return best_model, best_bic

    # ──────────────────────────────────────────────────────────────────────
    # State label mapping
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _build_label_mapping(model) -> dict:
        """Map hidden state indices to human-readable regime labels.

        Sorting logic:
        - Highest volatility (means[:,1]) → high_volatility
        - Remaining states sorted by mean return (means[:,0]):
          highest → risk_on, lowest → risk_off, others → low_vol_drift / transition
        """
        n = model.n_components
        means = model.means_  # shape (n_states, n_features)

        mean_returns = means[:, 0]
        mean_vols = means[:, 1]

        high_vol_idx = int(np.argmax(mean_vols))
        remaining = [i for i in range(n) if i != high_vol_idx]
        remaining_sorted = sorted(
            remaining, key=lambda i: mean_returns[i], reverse=True
        )

        label_names = ["risk_on", "risk_off", "low_vol_drift", "transition"]
        mapping = {str(high_vol_idx): "high_volatility"}
        for rank, state_idx in enumerate(remaining_sorted):
            label = (
                label_names[rank] if rank < len(label_names) else f"state_{state_idx}"
            )
            mapping[str(state_idx)] = label

        return mapping

    # ──────────────────────────────────────────────────────────────────────
    # Persistence helpers
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _serialize_model(model) -> str:
        return base64.b64encode(pickle.dumps(model)).decode("utf-8")

    @staticmethod
    def _deserialize_model(model_b64: str):
        return pickle.loads(base64.b64decode(model_b64))

    # ──────────────────────────────────────────────────────────────────────
    # Train + persist
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def train_and_persist(db: Session) -> Optional[RegimeModel]:
        """Train HMM on rolling 2-year SPY window; write new model to DB + Redis."""
        cutoff = datetime.utcnow() - timedelta(days=LOOKBACK_DAYS)

        rows = (
            db.query(StockAggregate.timestamp, StockAggregate.close)
            .filter(
                StockAggregate.ticker == "SPY",
                StockAggregate.timespan == "day",
                StockAggregate.timestamp >= cutoff,
            )
            .order_by(StockAggregate.timestamp)
            .all()
        )

        if not rows:
            logger.warning("train_and_persist: no SPY daily bars found — skipping")
            return None

        df = pd.DataFrame(rows, columns=["timestamp", "close"])
        X = RegimeService._build_feature_matrix(df)

        if X is None:
            logger.warning(
                "train_and_persist: only %d SPY bars — fewer than %d required, proceeding with warning",
                len(df),
                MIN_TRAINING_ROWS,
            )
            # Use what we have if we have at least 21 rows
            if len(df) < 21:
                return None
            df_tmp = df.copy()
            closes = df_tmp["close"].astype(float)
            dr = closes.pct_change()
            rv = dr.rolling(min(20, len(dr) - 1)).std()
            rs = dr.rolling(min(20, len(dr) - 1)).skew()
            feat = pd.DataFrame(
                {"daily_return": dr, "rolling_vol_20d": rv, "rolling_skew_20d": rs}
            ).dropna()
            X = feat.values

        model, bic = RegimeService._fit_best_hmm(X)
        if model is None:
            logger.error("train_and_persist: HMM fitting failed entirely")
            return None

        label_mapping = RegimeService._build_label_mapping(model)
        model_b64 = RegimeService._serialize_model(model)
        now = utc_now()

        # Archive current active model
        db.query(RegimeModel).filter(RegimeModel.status == "active").update(
            {"status": "archived"}
        )

        # Get next version
        max_version = db.query(func.max(RegimeModel.version)).scalar() or 0

        new_model = RegimeModel(
            version=max_version + 1,
            status="active",
            n_states=model.n_components,
            model_b64=model_b64,
            feature_set=FEATURE_SET,
            state_label_mapping=label_mapping,
            data_start_date=df["timestamp"].iloc[0].date()
            if hasattr(df["timestamp"].iloc[0], "date")
            else df["timestamp"].iloc[0],
            data_end_date=df["timestamp"].iloc[-1].date()
            if hasattr(df["timestamp"].iloc[-1], "date")
            else df["timestamp"].iloc[-1],
            bic_score=float(bic),
            trained_at=now,
        )
        db.add(new_model)
        db.commit()
        db.refresh(new_model)

        # Predict current regime and cache in Redis
        last_state = int(model.predict(X)[-1])
        current_regime = label_mapping.get(str(last_state), "unknown")
        RegimeService._set_redis_cache(current_regime)

        logger.info(
            "train_and_persist: trained n_states=%d bic=%.2f current_regime=%s",
            model.n_components,
            bic,
            current_regime,
        )
        return new_model

    # ──────────────────────────────────────────────────────────────────────
    # Regime lookup
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def get_current_regime() -> Optional[str]:
        """Return current regime from Redis cache, or None if cache miss."""
        return RegimeService._get_redis_cache()

    @staticmethod
    def get_regime_at_date(db: Session, event_date: date) -> Optional[str]:
        """Return regime label for a given date.

        For today: try Redis cache first.
        For any date: load active model from DB and predict using SPY bars up to that date.
        Falls back to None on any error.
        """
        today = datetime.utcnow().date()

        if event_date >= today:
            cached = RegimeService._get_redis_cache()
            if cached:
                return cached

        try:
            regime_model_row = (
                db.query(RegimeModel)
                .filter(RegimeModel.status == "active")
                .order_by(RegimeModel.version.desc())
                .first()
            )
            if not regime_model_row:
                return None

            model = RegimeService._deserialize_model(regime_model_row.model_b64)
            label_mapping = regime_model_row.state_label_mapping

            # Load SPY bars up to event_date within the model's training window
            cutoff = datetime.utcnow() - timedelta(days=LOOKBACK_DAYS)
            end_dt = datetime.combine(event_date, datetime.max.time())

            rows = (
                db.query(StockAggregate.timestamp, StockAggregate.close)
                .filter(
                    StockAggregate.ticker == "SPY",
                    StockAggregate.timespan == "day",
                    StockAggregate.timestamp >= cutoff,
                    StockAggregate.timestamp <= end_dt,
                )
                .order_by(StockAggregate.timestamp)
                .all()
            )

            if not rows:
                return None

            df = pd.DataFrame(rows, columns=["timestamp", "close"])
            closes = df["close"].astype(float)
            dr = closes.pct_change()
            rv = dr.rolling(20, min_periods=1).std()
            rs = dr.rolling(20, min_periods=1).skew()
            feat = pd.DataFrame(
                {"daily_return": dr, "rolling_vol_20d": rv, "rolling_skew_20d": rs}
            ).dropna()

            if feat.empty:
                return None

            X = feat.values
            state_seq = model.predict(X)
            last_state = int(state_seq[-1])
            return label_mapping.get(str(last_state))

        except Exception as exc:
            logger.warning("get_regime_at_date(%s) failed: %s", event_date, exc)
            return None

    # ──────────────────────────────────────────────────────────────────────
    # Redis helpers
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _get_redis_cache() -> Optional[str]:
        try:
            from app.core.cache import get_redis

            r = get_redis()
            if r is None:
                return None
            value = r.get(REDIS_KEY)
            return value.decode("utf-8") if value else None
        except Exception as exc:
            logger.debug("Redis cache read failed: %s", exc)
            return None

    @staticmethod
    def _set_redis_cache(regime: str) -> None:
        try:
            from app.core.cache import get_redis

            r = get_redis()
            if r is None:
                return
            r.setex(REDIS_KEY, REDIS_TTL, regime)
        except Exception as exc:
            logger.debug("Redis cache write failed: %s", exc)


# ──────────────────────────────────────────────────────────────────────────────
# BIC helper (outside class — pure function)
# ──────────────────────────────────────────────────────────────────────────────


def _compute_bic(model, X: np.ndarray) -> float:
    """Compute BIC for a fitted GaussianHMM."""
    n_samples, n_features = X.shape
    n_states = model.n_components
    # params: transition matrix (n^2 - n), means (n*d), covariance (n*d^2 for full)
    n_params = (
        n_states * (n_states - 1)  # transition matrix
        + n_states * n_features  # means
        + n_states * n_features * n_features  # full covariance
    )
    log_likelihood = model.score(X) * n_samples
    return -2 * log_likelihood + n_params * np.log(n_samples)
