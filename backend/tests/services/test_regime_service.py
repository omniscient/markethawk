"""Unit and integration tests for RegimeService and related components."""

from app.models.regime_model import RegimeModel

# NOTE: RegimeService, REDIS_KEY, REDIS_TTL are imported in Task 5 tests
# when regime_service.py is created.


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
