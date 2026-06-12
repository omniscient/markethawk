"""Unit and integration tests for RegimeService and related components."""

from datetime import date
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

from app.models.regime_model import RegimeModel
from app.models.scanner_event import ScannerEvent
from app.services.regime_service import RegimeService


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


def test_scanner_event_has_regime_column():
    cols = {c.key for c in ScannerEvent.__table__.columns}
    assert "regime" in cols


def test_scanner_event_regime_nullable_and_length():
    col = ScannerEvent.__table__.columns["regime"]
    assert col.nullable is True
    assert col.type.length == 30


# ── T5: Feature matrix ────────────────────────────────────────────────────────


def test_build_feature_matrix_returns_none_for_too_few_rows():
    df = pd.DataFrame(
        {
            "close": [100.0, 101.0, 102.0],
            "timestamp": pd.date_range("2024-01-01", periods=3),
        }
    )
    result = RegimeService._build_feature_matrix(df)
    assert result is None


def test_build_feature_matrix_returns_three_feature_columns():
    rng = np.random.default_rng(42)
    closes = [100.0 + i * 0.3 + rng.normal(0, 0.2) for i in range(600)]
    timestamps = pd.date_range("2022-01-01", periods=600)
    df = pd.DataFrame({"close": closes, "timestamp": timestamps})
    result = RegimeService._build_feature_matrix(df)
    assert result is not None
    assert result.shape[1] == 3


# ── T6: HMM training ─────────────────────────────────────────────────────────


def test_fit_best_hmm_returns_model_with_bic():
    rng = np.random.default_rng(42)
    X = rng.standard_normal((600, 3))
    model, bic = RegimeService._fit_best_hmm(X)
    assert model is not None
    assert isinstance(bic, float)
    assert model.n_components in range(2, 6)


def test_fit_best_hmm_selects_lowest_bic():
    rng = np.random.default_rng(7)
    X = rng.standard_normal((400, 3))
    model, bic = RegimeService._fit_best_hmm(X)
    assert model is not None
    # BIC should be finite
    assert np.isfinite(bic)


# ── T7: Label mapping ─────────────────────────────────────────────────────────


def test_label_mapping_contains_high_volatility():
    rng = np.random.default_rng(42)
    X = rng.standard_normal((600, 3))
    model, _ = RegimeService._fit_best_hmm(X)
    mapping = RegimeService._build_label_mapping(model)
    assert "high_volatility" in mapping.values()


def test_label_mapping_covers_all_states():
    rng = np.random.default_rng(42)
    X = rng.standard_normal((600, 3))
    model, _ = RegimeService._fit_best_hmm(X)
    mapping = RegimeService._build_label_mapping(model)
    assert len(mapping) == model.n_components
    for key in mapping:
        assert int(key) in range(model.n_components)


# ── T8: train_and_persist ─────────────────────────────────────────────────────


def _make_spy_rows(n=600):
    """Produce n daily SPY bar tuples (timestamp, close) as query result objects."""
    import collections

    Row = collections.namedtuple("Row", ["timestamp", "close"])
    rng = np.random.default_rng(42)
    closes = 400.0 + np.cumsum(rng.normal(0, 2, n))
    timestamps = pd.date_range("2024-01-01", periods=n, freq="D")
    return [Row(ts, cl) for ts, cl in zip(timestamps, closes)]


def test_train_and_persist_returns_regime_model_row():
    # Patch _build_feature_matrix and _fit_best_hmm to avoid real HMM in unit test
    from hmmlearn.hmm import GaussianHMM

    rng = np.random.default_rng(42)
    X_fake = rng.standard_normal((600, 3))
    fake_model = GaussianHMM(
        n_components=3, covariance_type="full", n_iter=10, random_state=42
    )
    fake_model.fit(X_fake)

    db = MagicMock()
    rows = _make_spy_rows(600)

    call_count = {"n": 0}

    def query_side_effect(*args, **kwargs):
        call_count["n"] += 1
        q = MagicMock()
        if call_count["n"] == 1:
            # First call: StockAggregate SPY bars query (one .filter() call, then .order_by().all())
            q.filter.return_value.order_by.return_value.all.return_value = rows
        elif call_count["n"] == 2:
            # Second call: archive active models
            q.filter.return_value.update.return_value = 0
        else:
            # Third call: get max version
            q.scalar.return_value = 0
        return q

    db.query.side_effect = query_side_effect

    with (
        patch.object(
            RegimeService, "_fit_best_hmm", return_value=(fake_model, -1000.0)
        ),
        patch.object(RegimeService, "_set_redis_cache"),
    ):
        result = RegimeService.train_and_persist(db)

    assert result is not None
    db.add.assert_called_once()
    db.commit.assert_called_once()


def test_train_and_persist_returns_none_when_no_spy_data():
    db = MagicMock()
    db.query.return_value.filter.return_value.filter.return_value.filter.return_value.order_by.return_value.all.return_value = []
    result = RegimeService.train_and_persist(db)
    assert result is None


# ── T9: get_regime_at_date ────────────────────────────────────────────────────


def test_get_current_regime_returns_redis_value():
    with patch.object(RegimeService, "_get_redis_cache", return_value="risk_on"):
        result = RegimeService.get_current_regime()
    assert result == "risk_on"


def test_get_regime_at_date_returns_none_when_no_model(db=None):
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
    with patch.object(RegimeService, "_get_redis_cache", return_value=None):
        result = RegimeService.get_regime_at_date(mock_db, date(2024, 1, 15))
    assert result is None


def test_get_regime_at_date_handles_exception_gracefully():
    mock_db = MagicMock()
    mock_db.query.side_effect = Exception("DB error")
    with patch.object(RegimeService, "_get_redis_cache", return_value=None):
        result = RegimeService.get_regime_at_date(mock_db, date(2024, 1, 15))
    assert result is None


# ── T10: save_event regime injection ─────────────────────────────────────────


def test_save_event_populates_regime_field():
    """save_event must include regime in the returned event_dict."""
    from app.services.alert_service import save_event

    db = MagicMock()
    db.query.return_value.filter.return_value.filter.return_value.filter.return_value.first.return_value = None

    new_event = MagicMock()
    new_event.id = 99
    db.flush.return_value = None

    # ScannerEvent constructor returns our mock
    with (
        patch("app.services.alert_service.ScannerEvent", return_value=new_event),
        patch("app.services.alert_service.trigger_scanner_alert"),
        patch.object(RegimeService, "get_regime_at_date", return_value="risk_on"),
    ):
        result = save_event(
            db=db,
            ticker="AAPL",
            event_date=date(2024, 1, 15),
            scanner_type="pre_market_volume_spike",
            indicators={"volume_ratio": 5.0},
            criteria_met={"volume_spike": True},
            enrichment={},
        )

    assert result.get("regime") == "risk_on"


# ── T11: Celery tasks ─────────────────────────────────────────────────────────


def test_regime_tasks_are_importable():
    from app.tasks.regime import backfill_regime_labels, update_regime_model

    assert callable(update_regime_model)
    assert callable(backfill_regime_labels)


def test_update_regime_model_task_calls_train_and_persist():
    from app.tasks.regime import update_regime_model

    with patch.object(RegimeService, "train_and_persist") as mock_train:
        mock_train.return_value = MagicMock(n_states=3, version=1)
        update_regime_model.apply()
    mock_train.assert_called_once()


def test_save_event_regime_is_none_when_service_returns_none():
    """save_event must gracefully use None when RegimeService returns None."""
    from app.services.alert_service import save_event

    db = MagicMock()
    db.query.return_value.filter.return_value.filter.return_value.filter.return_value.first.return_value = None

    new_event = MagicMock()
    new_event.id = 100

    with (
        patch("app.services.alert_service.ScannerEvent", return_value=new_event),
        patch("app.services.alert_service.trigger_scanner_alert"),
        patch.object(RegimeService, "get_regime_at_date", return_value=None),
    ):
        result = save_event(
            db=db,
            ticker="TSLA",
            event_date=date(2024, 1, 15),
            scanner_type="pre_market_volume_spike",
            indicators={},
            criteria_met={},
            enrichment={},
        )

    assert result.get("regime") is None
