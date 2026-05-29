"""
Integration tests for system config API endpoints.
Runs against a real Postgres DB (via testcontainers).
"""

from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.fixtures.system import seed_system_config

client = TestClient(app)


# ---------------------------------------------------------------------------
# GET /api/system/config
# ---------------------------------------------------------------------------


def test_get_config_empty_db_returns_empty_dict(db: Session):
    response = client.get("/api/v1/system/config")

    assert response.status_code == 200
    assert response.json() == {}


def test_get_config_returns_seeded_keys(db: Session):
    seed_system_config(db)

    response = client.get("/api/v1/system/config")

    assert response.status_code == 200
    data = response.json()
    assert data["scan_enabled"] == "true"
    assert data["volume_threshold"] == "4.0"
    assert data["gap_threshold"] == "1.0"


def test_get_config_returns_flat_dict(db: Session):
    seed_system_config(db)

    response = client.get("/api/v1/system/config")

    data = response.json()
    assert isinstance(data, dict)
    assert len(data) == 3


# ---------------------------------------------------------------------------
# PATCH /api/system/config
# ---------------------------------------------------------------------------


def test_patch_config_inserts_new_key(db: Session):
    response = client.patch("/api/v1/system/config", json={"new_key": "new_value"})

    assert response.status_code == 200
    data = response.json()
    assert data["new_key"] == "new_value"


def test_patch_config_updates_existing_key(db: Session):
    seed_system_config(db)

    response = client.patch("/api/v1/system/config", json={"scan_enabled": "false"})

    assert response.status_code == 200
    data = response.json()
    assert data["scan_enabled"] == "false"


def test_patch_config_multiple_keys(db: Session):
    response = client.patch(
        "/api/v1/system/config",
        json={"key_a": "val_a", "key_b": "val_b", "key_c": "val_c"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["key_a"] == "val_a"
    assert data["key_b"] == "val_b"
    assert data["key_c"] == "val_c"


def test_patch_config_returns_full_config(db: Session):
    seed_system_config(db)

    response = client.patch("/api/v1/system/config", json={"new_setting": "42"})

    data = response.json()
    # Original seeded keys still present
    assert "scan_enabled" in data
    assert "volume_threshold" in data
    assert "gap_threshold" in data
    # New key added
    assert data["new_setting"] == "42"


def test_patch_config_persists_across_get(db: Session):
    client.patch("/api/v1/system/config", json={"persisted_key": "persisted_value"})
    response = client.get("/api/v1/system/config")

    assert response.status_code == 200
    assert response.json()["persisted_key"] == "persisted_value"


def test_patch_config_empty_payload_returns_current_config(db: Session):
    seed_system_config(db)

    response = client.patch("/api/v1/system/config", json={})

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3


def test_patch_config_numeric_value_stored_as_string(db: Session):
    response = client.patch("/api/v1/system/config", json={"threshold": 5})

    assert response.status_code == 200
    data = response.json()
    assert data["threshold"] == "5"
