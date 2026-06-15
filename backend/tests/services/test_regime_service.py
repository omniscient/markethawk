"""Unit and integration tests for RegimeService and related components."""

import json
from datetime import date
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

from app.models.regime_model import RegimeModel
from app.models.scanner_event import ScannerEvent
from app.services.alert_service import save_event
from app.services.regime_service import RegimeService

# ── RegimeModel ORM tests ─────────────────────────────────────────────────────


def test_regime_model_table_name():
    assert RegimeModel.__tablename__ == "regime_models"


def test_regime_model_has_required_columns():
    cols = {c.key for c in RegimeModel.__table__.columns}
    assert {
        "id",
        "version",
        "status",
        "n_states",
        "model_b64",
        "feature_set",
        "state_label_mapping",
        "data_start_date",
        "data_end_date",
        "bic_score",
        "trained_at",
        "created_at",
    } <= cols


# ── ScannerEvent.regime column tests ─────────────────────────────────────────


def test_scanner_event_has_regime_column():
    cols = {c.key for c in ScannerEvent.__table__.columns}
    assert "regime" in cols


def test_scanner_event_regime_nullable_and_length():
    col = ScannerEvent.__table__.columns["regime"]
    assert col.nullable is True
    assert col.type.length == 30


# ── Feature matrix tests ──────────────────────────────────────────────────────


def test_build_feature_matrix_returns_none_for_too_few_rows():
    df = pd.DataFrame({"close": [100.0, 101.0, 102.0]})
    result = RegimeService._build_feature_matrix(df)
    assert result is None


def test_build_feature_matrix_returns_three_feature_columns():
    rng = np.random.default_rng(0)
    closes = [100.0 + i * 0.3 + rng.normal(0, 0.2) for i in range(60)]
    df = pd.DataFrame({"close": closes})
    result = RegimeService._build_feature_matrix(df)
    assert result is not None
    X, feature_df = result
    assert X.shape[1] == 3
    assert list(feature_df.columns) == [
        "daily_return",
        "rolling_vol_20d",
        "rolling_skew_20d",
    ]
    assert not feature_df.isnull().any().any()


# ── HMM training tests ────────────────────────────────────────────────────────


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


# ── Label mapping tests ───────────────────────────────────────────────────────


def _make_mock_hmm(means_array: np.ndarray):
    from hmmlearn.hmm import GaussianHMM

    model = GaussianHMM.__new__(GaussianHMM)
    model.n_components = len(means_array)
    model.means_ = means_array
    return model


def test_map_state_labels_assigns_three_core_labels():
    means = np.array(
        [
            [-0.010, 0.030, 0.0],
            [0.020, 0.010, 0.0],
            [0.005, 0.050, 0.0],
        ]
    )
    mapping = RegimeService._map_state_labels(_make_mock_hmm(means))
    assert set(mapping.values()) == {"risk_off", "risk_on", "high_volatility"}
    assert len(mapping) == 3


def test_map_state_labels_covers_all_states_for_n4():
    means = np.array(
        [
            [-0.015, 0.040, 0.0],
            [0.020, 0.010, 0.0],
            [0.005, 0.060, 0.0],
            [0.004, 0.008, 0.0],
        ]
    )
    mapping = RegimeService._map_state_labels(_make_mock_hmm(means))
    assert len(mapping) == 4
    assert set(mapping.keys()) == {"0", "1", "2", "3"}


# ── train_and_persist tests ───────────────────────────────────────────────────


def test_train_and_persist_returns_none_when_no_spy_data(db):
    with patch.object(RegimeService, "_fetch_spy_bars", return_value=pd.DataFrame()):
        result = RegimeService.train_and_persist(db)
    assert result is None


def test_train_and_persist_returns_active_regime_model(db):
    rng = np.random.default_rng(7)
    closes = [100.0 + i * 0.4 + rng.normal(0, 0.3) for i in range(600)]
    spy_df = pd.DataFrame(
        {
            "close": closes,
            "date": ["2024-01-01" for _ in range(600)],
        }
    )
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
    mock_redis.setex.assert_called_once()


def test_train_and_persist_redis_write_happens_after_commit(db):
    """Redis setex must not be called before db.commit() — a failed commit must not pollute cache."""
    rng = np.random.default_rng(7)
    closes = [100.0 + i * 0.4 + rng.normal(0, 0.3) for i in range(600)]
    spy_df = pd.DataFrame({"close": closes, "date": ["2024-01-01"] * 600})
    call_order = []
    mock_redis = MagicMock()
    mock_redis.setex.side_effect = lambda *a, **kw: call_order.append("redis")
    original_commit = db.commit

    def tracked_commit():
        call_order.append("commit")
        original_commit()

    db.commit = tracked_commit
    with (
        patch.object(RegimeService, "_fetch_spy_bars", return_value=spy_df),
        patch("app.services.regime_service.redis.from_url", return_value=mock_redis),
    ):
        RegimeService.train_and_persist(db)
    assert call_order.index("commit") < call_order.index("redis"), (
        "db.commit() must happen before redis.setex()"
    )


def test_get_regime_at_date_memoizes_result(db):
    """Second call for the same date must not re-query the DB or re-run the HMM."""
    import app.services.regime_service as rs_mod

    rs_mod._regime_date_cache.clear()
    with (
        patch.object(
            RegimeService,
            "get_current_regime",
            return_value=None,
        ),
        patch.object(
            db.__class__,
            "query",
            wraps=db.query,
        ) as mock_query,
    ):
        with patch.object(
            RegimeService, "get_regime_at_date", wraps=RegimeService.get_regime_at_date
        ):
            rs_mod._regime_date_cache["2025-03-15"] = "risk_on"
            result = RegimeService.get_regime_at_date(db, date(2025, 3, 15))
            assert result == "risk_on"
            mock_query.assert_not_called()
    rs_mod._regime_date_cache.clear()


# ── get_current_regime / get_regime_at_date tests ────────────────────────────


def test_get_regime_at_date_memoizes_missing_active_model():
    """No-model lookups are cached so scanner loops do not re-query once per event."""
    import app.services.regime_service as rs_mod

    query = MagicMock()
    query.filter.return_value.order_by.return_value.first.return_value = None
    db = MagicMock()
    db.query.return_value = query

    rs_mod._regime_date_cache.clear()
    try:
        first = RegimeService.get_regime_at_date(db, date(2025, 3, 15))
        second = RegimeService.get_regime_at_date(db, date(2025, 3, 15))
    finally:
        rs_mod._regime_date_cache.clear()

    assert first is None
    assert second is None
    db.query.assert_called_once_with(RegimeModel)


def test_get_current_regime_reads_from_redis():
    payload = json.dumps(
        {"regime": "risk_on", "as_of_date": "2026-06-01", "model_version": 1}
    )
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


# ── save_event regime injection tests ────────────────────────────────────────


def test_save_event_populates_regime_field(db):
    with (
        patch(
            "app.services.regime_service.RegimeService.get_regime_at_date",
            return_value="risk_on",
        ),
        patch("app.services.alert_service.trigger_scanner_alert") as mock_trigger,
    ):
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
    mock_trigger.assert_called_once_with(result["id"])


def test_save_event_regime_is_none_when_service_returns_none(db):
    with (
        patch(
            "app.services.regime_service.RegimeService.get_regime_at_date",
            return_value=None,
        ),
        patch("app.services.alert_service.trigger_scanner_alert") as mock_trigger,
    ):
        result = save_event(
            db=db,
            ticker="MSFT",
            event_date=date(2026, 6, 3),
            scanner_type="pre_market_volume_spike",
            indicators={"volume_spike_ratio": 3.5, "gap_pct": 1.1},
            criteria_met={},
            enrichment={},
        )
    assert result.get("regime") is None
    mock_trigger.assert_called_once_with(result["id"])


# ── Celery task importability tests ──────────────────────────────────────────


def test_regime_tasks_are_importable():
    from app.tasks.regime import backfill_regime_labels, update_regime_model

    assert callable(update_regime_model)
    assert callable(backfill_regime_labels)


def test_update_regime_model_task_calls_train_and_persist():
    from app.tasks.regime import update_regime_model

    with patch("app.tasks.regime.RegimeService.train_and_persist") as mock_train:
        mock_train.return_value = MagicMock(n_states=3, version=1)
        update_regime_model.apply()
    mock_train.assert_called_once()


# ── Package export tests ──────────────────────────────────────────────────────


def test_tasks_package_exports_regime_tasks():
    from app.tasks import backfill_regime_labels, update_regime_model

    assert update_regime_model.name == "app.tasks.update_regime_model"
    assert backfill_regime_labels.name == "app.tasks.backfill_regime_labels"


def test_regime_beat_task_in_schedule():
    from app.core.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule
    assert "update-regime-model-nightly" in schedule
    assert (
        schedule["update-regime-model-nightly"]["task"]
        == "app.tasks.update_regime_model"
    )
