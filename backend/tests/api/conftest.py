import os

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("POLYGON_API_KEY", "test-key-for-unit-tests-only")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars!")
# Disable rate limiting in tests: Redis is not available in the test environment,
# and SlowAPIASGIMiddleware would raise ConnectionError on every request.
os.environ.setdefault("RATE_LIMITING_ENABLED", "false")

from app.core.config import get_settings

get_settings.cache_clear()

from unittest.mock import patch

import fakeredis
import pytest
from app.core.database import get_db
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def override_get_db(db):
    app.dependency_overrides[get_db] = lambda: db
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def fake_redis():
    """Patch redis.from_url in auth router to use fakeredis for all tests."""
    fake = fakeredis.FakeRedis(decode_responses=True)
    with patch("app.routers.auth._get_redis", return_value=fake):
        yield fake


@pytest.fixture(autouse=True)
def inject_auth_into_module_client(request):
    """Inject a valid JWT cookie into any module-level TestClient.

    Existing test files define `client = TestClient(app)` at module level.
    The auth middleware only validates jwt.decode() — no DB lookup — so any
    token signed with the test secret passes, regardless of subject UUID.
    """
    from app.core.auth import create_access_token

    module = request.module
    if hasattr(module, "client") and isinstance(module.client, TestClient):
        token = create_access_token("00000000-0000-0000-0000-000000000001")
        module.client.cookies.set("access_token", token)
