from app.models.user import User


def test_user_model_has_required_columns():
    cols = {c.key for c in User.__table__.columns}
    assert {"id", "username", "password_hash", "created_at", "is_active"} <= cols


def test_user_tablename():
    assert User.__tablename__ == "users"
