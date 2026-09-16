"""
RegimeService — train, persist, query, and cache HMM market regime models.
"""

import base64
import json
import logging
import pickle
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import redis
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.regime_model import RegimeModel
from app.models.stock_aggregate import StockAggregate
from app.utils.time import utc_now

logger = logging.getLogger(__name__)

REDIS_KEY = "regime:current"
REDIS_TTL = 90000  # 25 hours in seconds
FEATURE_SET: List[str] = ["daily_return", "rolling_vol_20d", "rolling_skew_20d"]

# Per-date in-process cache — avoids repeated 730-day SPY fetch + HMM predict
# for the same date within a single scanner run. Cleared on model retrain.
_regime_date_cache: Dict[str, Optional[str]] = {}


class RegimeService:
    @staticmethod
    def _fetch_spy_bars(db: Session) -> pd.DataFrame:
        """Load SPY daily bars from stock_aggregates (rolling 2-year window)."""
        cutoff = utc_now() - timedelta(days=730)
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
        return pd.DataFrame(
            [
                {
                    "date": r.timestamp.date()
                    if hasattr(r.timestamp, "date")
                    else r.timestamp,
                    "close": float(r.close),
                }
                for r in rows
            ]
        )

    @staticmethod
    def _build_feature_matrix(
        df: pd.DataFrame,
    ) -> Optional[Tuple[np.ndarray, pd.DataFrame]]:
        """Compute features; returns None when fewer than 22 rows (20d rolling + 1 lag)."""
        if len(df) < 22:
            return None
        df = df.copy()
        df["daily_return"] = df["close"].pct_change()
        df["rolling_vol_20d"] = df["daily_return"].rolling(20).std()
        df["rolling_skew_20d"] = df["daily_return"].rolling(20).skew()
        feature_df = df[
            ["daily_return", "rolling_vol_20d", "rolling_skew_20d"]
        ].dropna()
        return feature_df.values, feature_df

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
                bic = model.bic(X)
                if bic < best_bic:
                    best_bic = bic
                    best_model = model
                    best_n = n
            except Exception as exc:
                logger.warning("HMM fit failed for n_components=%d: %s", n, exc)
                continue

        return best_model, best_n, best_bic

    @staticmethod
    def _map_state_labels(model) -> Dict[str, str]:
        """Map HMM state indices to regime labels based on mean return and volatility."""
        means = model.means_  # (n_states, n_features): [return, vol, skew]

        state_info = [
            {
                "state": i,
                "mean_return": float(means[i, 0]),
                "mean_vol": float(means[i, 1]),
            }
            for i in range(model.n_components)
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

        # Remaining states get extra labels
        extra_labels = ["low_vol_drift", "transition"]
        extra_idx = 0
        for s in state_info:
            if s["state"] not in assigned:
                mapping[str(s["state"])] = extra_labels[extra_idx % len(extra_labels)]
                assigned.add(s["state"])
                extra_idx += 1

        return mapping

    @staticmethod
    def train_and_persist(db: Session) -> Optional[RegimeModel]:
        """Fetch SPY bars, fit best-BIC HMM, persist to DB, update Redis current-regime cache."""
        df = RegimeService._fetch_spy_bars(db)
        if df.empty:
            logger.warning("train_and_persist: no SPY daily bars found; skipping.")
            return None

        result = RegimeService._build_feature_matrix(df)
        if result is None:
            logger.warning(
                "train_and_persist: insufficient rows after feature computation; skipping."
            )
            return None

        X, feature_df = result
        if len(X) < 500:
            logger.warning(
                "train_and_persist: only %d SPY bars available (< 500); proceeding.",
                len(X),
            )

        model, n_states, bic = RegimeService._fit_best_hmm(X)
        if model is None:
            logger.error("train_and_persist: all HMM fits failed.")
            return None

        state_label_mapping = RegimeService._map_state_labels(model)
        model_b64 = base64.b64encode(pickle.dumps(model)).decode("utf-8")

        db.query(RegimeModel).filter(RegimeModel.status == "active").update(
            {"status": "archived"}
        )

        next_version = db.query(RegimeModel).count() + 1
        data_start = df["date"].min() if "date" in df.columns else None
        data_end = df["date"].max() if "date" in df.columns else None
        trained_at = utc_now()

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

        db.commit()
        logger.info(
            "train_and_persist: n_states=%d BIC=%.2f regime=%s version=%d",
            n_states,
            bic,
            current_regime,
            next_version,
        )

        _regime_date_cache.clear()

        cache_payload = json.dumps(
            {
                "regime": current_regime,
                "as_of_date": str(data_end),
                "model_version": next_version,
            }
        )
        try:
            r = redis.from_url(settings.REDIS_URL)
            r.setex(REDIS_KEY, REDIS_TTL, cache_payload)
        except Exception as exc:
            logger.warning("train_and_persist: Redis cache write failed: %s", exc)

        return new_model

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

        For today: tries Redis cache first, then falls back to DB prediction.
        For historical dates: loads active model from DB, predicts on SPY bars up to that date.
        Results are memoized per date in _regime_date_cache to avoid repeated expensive
        730-day SPY queries + HMM predictions within the same scanner run.
        """
        today = datetime.now(timezone.utc).date()
        if isinstance(target_date, datetime):
            target_date = target_date.date()

        cache_key = str(target_date)
        if cache_key in _regime_date_cache:
            return _regime_date_cache[cache_key]

        if target_date == today:
            cached = RegimeService.get_current_regime()
            if cached:
                _regime_date_cache[cache_key] = cached
                return cached

        active_row = (
            db.query(RegimeModel)
            .filter(RegimeModel.status == "active")
            .order_by(RegimeModel.version.desc())
            .first()
        )
        if not active_row:
            _regime_date_cache[cache_key] = None
            return None

        try:
            model = pickle.loads(base64.b64decode(active_row.model_b64))
            state_label_mapping = active_row.state_label_mapping
        except Exception as exc:
            logger.error("get_regime_at_date: model deserialization failed: %s", exc)
            _regime_date_cache[cache_key] = None
            return None

        cutoff = datetime.combine(target_date, datetime.min.time()) - timedelta(
            days=730
        )
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
            _regime_date_cache[cache_key] = None
            return None

        df = pd.DataFrame([{"close": float(r.close)} for r in rows])
        result = RegimeService._build_feature_matrix(df)
        if result is None:
            _regime_date_cache[cache_key] = None
            return None

        X, _ = result
        try:
            states = model.predict(X)
            regime = state_label_mapping.get(str(int(states[-1])))
            _regime_date_cache[cache_key] = regime
            return regime
        except Exception as exc:
            logger.error("get_regime_at_date: prediction failed: %s", exc)
            _regime_date_cache[cache_key] = None
            return None
