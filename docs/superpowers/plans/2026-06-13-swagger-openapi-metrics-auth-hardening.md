# Implementation Plan: Swagger/openapi.json/metrics Auth Hardening (F-AUTH-01)

**Date:** 2026-06-13  
**Issue:** #369  
**Spec:** [docs/superpowers/specs/2026-06-12-swagger-openapi-metrics-auth-design.md](../specs/2026-06-12-swagger-openapi-metrics-auth-design.md)  
**Branch:** `refine/issue-369--security--f-auth-01--swagger-openapi-js`  
**Status:** Plan

---

## Goal

Harden the production backend so that:
- Swagger UI, ReDoc, and `openapi.json` are unreachable (404) in production (OWASP A05:2021 / CWE-200 fix)
- `/metrics` is blocked at the Caddy layer for external traffic while Prometheus scraping over the internal Docker network continues unaffected
- Local developer experience is unchanged: `docker-compose.override.yml` enables docs automatically

## Architecture

- `Settings.DOCS_ENABLED: bool = False` — new field, defaults secure
- `create_app()` in `main.py` — conditional `docs_url`/`redoc_url`/`openapi_url` + dynamic `EXEMPT_PREFIXES`
- `caddy/Caddyfile` — explicit deny block for `/metrics` (defense-in-depth)
- `docker-compose.override.yml` — adds `DOCS_ENABLED: "true"` alongside existing `COOKIE_SECURE: "false"`

## Tech Stack

Backend: FastAPI, Pydantic Settings  
Infra: Caddy reverse proxy, Docker Compose  
Docs: deployment-guide.md

---

## File Structure

| File | Change |
|------|--------|
| `backend/app/core/config.py` | Add `DOCS_ENABLED: bool = False` after `COOKIE_SECURE` |
| `backend/app/main.py` | Conditional docs URLs + dynamic `EXEMPT_PREFIXES` in `create_app()` |
| `backend/tests/test_settings.py` | New test class for `DOCS_ENABLED` |
| `backend/tests/test_main_docs_auth.py` | New test file: docs URL routing + auth gating |
| `caddy/Caddyfile` | Add `handle /metrics { respond "Not found" 404 }` |
| `docker-compose.override.yml` | Add `DOCS_ENABLED: "true"` to backend environment |
| `deployment-guide.md` | Add `DOCS_ENABLED` + metrics-port section under Production Hardening |

---

## Tasks

### Task 1 — Add `DOCS_ENABLED` to Settings

**Files:** `backend/app/core/config.py`, `backend/tests/test_settings.py`

#### TDD steps

**Step 1a — Write failing test**

Add a new test class to `backend/tests/test_settings.py` (after the existing classes):

```python
class TestDocsEnabledSetting:
    def test_docs_enabled_defaults_false(self):
        from app.core.config import Settings

        s = Settings(
            DATABASE_URL="postgresql://test:test@localhost/test",
            POLYGON_API_KEY="test-key",
        )
        assert s.DOCS_ENABLED is False

    def test_docs_enabled_can_be_set_true(self):
        from app.core.config import Settings

        s = Settings(
            DATABASE_URL="postgresql://test:test@localhost/test",
            POLYGON_API_KEY="test-key",
            DOCS_ENABLED=True,
        )
        assert s.DOCS_ENABLED is True

    def test_docs_enabled_coerces_string_true(self, monkeypatch):
        monkeypatch.setenv("DOCS_ENABLED", "true")
        from app.core.config import Settings

        s = Settings(
            DATABASE_URL="postgresql://test:test@localhost/test",
            POLYGON_API_KEY="test-key",
        )
        assert s.DOCS_ENABLED is True
```

**Step 1b — Verify test fails**

```bash
docker-compose exec backend python -m pytest backend/tests/test_settings.py::TestDocsEnabledSetting -x -q 2>&1 | tail -10
# Expected: AttributeError or similar — DOCS_ENABLED not yet defined
```

**Step 1c — Implement**

In `backend/app/core/config.py`, add after line 58 (`COOKIE_SECURE: bool = True`):

```python
    # API documentation — disabled by default in production; set True in docker-compose.override.yml for dev
    DOCS_ENABLED: bool = False
```

**Step 1d — Verify test passes**

```bash
docker-compose exec backend python -m pytest backend/tests/test_settings.py::TestDocsEnabledSetting -x -q 2>&1 | tail -5
# Expected: 3 passed
```

**Step 1e — Commit**

```bash
git add backend/app/core/config.py backend/tests/test_settings.py
git commit -m "feat(#369): add DOCS_ENABLED setting — secure-by-default False"
```

---

### Task 2 — Update `create_app()`: conditional docs URLs + dynamic EXEMPT_PREFIXES

**Files:** `backend/app/main.py`, `backend/tests/test_main_docs_auth.py`

#### TDD steps

**Step 2a — Write failing tests**

Create `backend/tests/test_main_docs_auth.py`:

```python
"""
Tests for DOCS_ENABLED-gated Swagger/ReDoc/openapi.json routing and EXEMPT_PREFIXES behavior.
"""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings


class TestDocsUrlsWhenDisabled:
    """DOCS_ENABLED=False: doc routes must not be registered (route-level 404)."""

    @pytest.fixture()
    def app_docs_off(self):
        with patch.object(settings, "DOCS_ENABLED", False):
            from app.main import create_app
            return create_app()

    def test_docs_route_not_registered(self, app_docs_off):
        paths = {r.path for r in app_docs_off.routes}
        assert "/docs" not in paths

    def test_openapi_route_not_registered(self, app_docs_off):
        paths = {r.path for r in app_docs_off.routes}
        assert "/openapi.json" not in paths

    def test_redoc_route_not_registered(self, app_docs_off):
        paths = {r.path for r in app_docs_off.routes}
        assert "/redoc" not in paths

    def test_docs_returns_401_unauthenticated(self, app_docs_off):
        """Unauthenticated request: AuthMiddleware blocks /docs with 401 (not exempt)."""
        client = TestClient(app_docs_off, raise_server_exceptions=False)
        assert client.get("/docs").status_code == 401

    def test_openapi_returns_401_unauthenticated(self, app_docs_off):
        client = TestClient(app_docs_off, raise_server_exceptions=False)
        assert client.get("/openapi.json").status_code == 401


class TestDocsUrlsWhenEnabled:
    """DOCS_ENABLED=True: doc routes must be registered and exempt from auth."""

    @pytest.fixture()
    def app_docs_on(self):
        with patch.object(settings, "DOCS_ENABLED", True):
            from app.main import create_app
            return create_app()

    def test_docs_route_registered(self, app_docs_on):
        paths = {r.path for r in app_docs_on.routes}
        assert "/docs" in paths

    def test_openapi_route_registered(self, app_docs_on):
        paths = {r.path for r in app_docs_on.routes}
        assert "/openapi.json" in paths

    def test_docs_accessible_without_auth(self, app_docs_on):
        """No auth cookie required: /docs is in EXEMPT_PREFIXES → served without token."""
        client = TestClient(app_docs_on, raise_server_exceptions=False)
        assert client.get("/docs").status_code == 200

    def test_openapi_accessible_without_auth(self, app_docs_on):
        client = TestClient(app_docs_on, raise_server_exceptions=False)
        assert client.get("/openapi.json").status_code == 200


class TestMetricsAlwaysExempt:
    """Regardless of DOCS_ENABLED, /metrics must remain accessible."""

    @pytest.fixture()
    def app_docs_off(self):
        with patch.object(settings, "DOCS_ENABLED", False):
            from app.main import create_app
            return create_app()

    def test_metrics_accessible_without_auth(self, app_docs_off):
        client = TestClient(app_docs_off, raise_server_exceptions=False)
        response = client.get("/metrics")
        # /metrics is in EXEMPT_PREFIXES and the route is registered
        assert response.status_code == 200
```

**Step 2b — Verify tests fail**

```bash
docker-compose exec backend python -m pytest backend/tests/test_main_docs_auth.py -x -q 2>&1 | tail -15
# Expected: failures — currently /docs IS registered regardless of setting
```

**Step 2c — Implement**

In `backend/app/main.py`, inside `create_app()`, replace the current FastAPI instantiation and `EXEMPT_PREFIXES` block.

**Current** (around the `app = FastAPI(...)` call):

```python
    app = FastAPI(
        title=settings.APP_NAME,
        description="Professional stock scanning and alert system",
        version=settings.APP_VERSION,
        lifespan=lifespan,
    )
```

**Replace with:**

```python
    _docs_url = "/docs" if settings.DOCS_ENABLED else None
    _redoc_url = "/redoc" if settings.DOCS_ENABLED else None
    _openapi_url = "/openapi.json" if settings.DOCS_ENABLED else None
    app = FastAPI(
        title=settings.APP_NAME,
        description="Professional stock scanning and alert system",
        version=settings.APP_VERSION,
        lifespan=lifespan,
        docs_url=_docs_url,
        redoc_url=_redoc_url,
        openapi_url=_openapi_url,
    )
```

**Current** `EXEMPT_PREFIXES` tuple (inside `create_app()`, before the `AuthMiddleware` class definition):

```python
    EXEMPT_PREFIXES = (
        "/api/auth/",
        "/api/health",
        "/api/ready",
        "/metrics",
        "/api/alerts/infrastructure",
        "/docs",
        "/redoc",
        "/openapi.json",
    )
```

**Replace with:**

```python
    _base_exempt = (
        "/api/auth/",
        "/api/health",
        "/api/ready",
        "/metrics",
        "/api/alerts/infrastructure",
    )
    _doc_prefixes = ("/docs", "/redoc", "/openapi.json") if settings.DOCS_ENABLED else ()
    EXEMPT_PREFIXES = _base_exempt + _doc_prefixes
```

**Step 2d — Verify tests pass**

```bash
docker-compose exec backend python -m pytest backend/tests/test_main_docs_auth.py -x -q 2>&1 | tail -10
# Expected: all tests pass
```

Also run full test suite to check for regressions:

```bash
docker-compose exec backend python -m pytest backend/tests/ -x -q --ignore=backend/tests/test_main_docs_auth.py 2>&1 | tail -15
# Expected: no new failures
```

**Step 2e — Validate backend reloaded**

```bash
docker-compose logs backend --tail=5
# Expected: "Application startup complete."
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/docs
# Expected: 401 (auth middleware blocks /docs since DOCS_ENABLED=False in docker-compose.yml)
# Local dev with override: expected 200
```

**Step 2f — Commit**

```bash
git add backend/app/main.py backend/tests/test_main_docs_auth.py
git commit -m "feat(#369): gate docs URLs and EXEMPT_PREFIXES behind DOCS_ENABLED"
```

---

### Task 3 — Add Caddyfile `/metrics` deny block

**Files:** `caddy/Caddyfile`

This is a defense-in-depth measure. Prometheus scrapes `backend:8000/metrics` directly over the internal Docker network (never through Caddy). The deny block makes the protection explicit and visible.

#### Steps

**Step 3a — Implement**

In `caddy/Caddyfile`, inside the `{$DOMAIN:localhost}` block, add the deny handle **before** `handle /api/*`:

Current:
```
{$DOMAIN:localhost} {
    # HSTS: instruct browsers to use HTTPS for this domain for 1 year
    header Strict-Transport-Security "max-age=31536000; includeSubDomains" always

    # WebSocket and REST API — backend
    handle /api/* {
        reverse_proxy backend:8000
    }

    # Frontend SPA — all other paths
    handle {
        reverse_proxy frontend:3333
    }
}
```

After edit:
```
{$DOMAIN:localhost} {
    # HSTS: instruct browsers to use HTTPS for this domain for 1 year
    header Strict-Transport-Security "max-age=31536000; includeSubDomains" always

    # Block /metrics at the reverse proxy — Prometheus scrapes backend:8000 directly
    # over the internal Docker network; external clients must not reach this endpoint.
    handle /metrics {
        respond "Not found" 404
    }

    # WebSocket and REST API — backend
    handle /api/* {
        reverse_proxy backend:8000
    }

    # Frontend SPA — all other paths
    handle {
        reverse_proxy frontend:3333
    }
}
```

**Step 3b — Verify Caddy config is valid**

```bash
docker-compose exec caddy caddy validate --config /etc/caddy/Caddyfile 2>&1
# Expected: "Valid configuration"
```

If Caddy container name differs, check with:
```bash
docker-compose ps | grep caddy
```

**Step 3c — Commit**

```bash
git add caddy/Caddyfile
git commit -m "feat(#369): block /metrics at Caddy layer (defense-in-depth)"
```

---

### Task 4 — Update `docker-compose.override.yml` and `deployment-guide.md`

**Files:** `docker-compose.override.yml`, `deployment-guide.md`

#### Step 4a — Update docker-compose.override.yml

Add `DOCS_ENABLED: "true"` to the `backend` service environment block alongside the existing `COOKIE_SECURE` override.

Current backend environment block:
```yaml
  backend:
    ...
    environment:
      COOKIE_SECURE: "false"
```

After edit:
```yaml
  backend:
    ...
    environment:
      COOKIE_SECURE: "false"
      DOCS_ENABLED: "true"
```

**Step 4b — Update deployment-guide.md**

Add a new section after the existing `COOKIE_SECURE` block (after line 117). Find the line that reads:

```
`COOKIE_SECURE` defaults to `true`. Local dev overrides this automatically via `docker-compose.override.yml` so cookies work over plain HTTP. In production the cookies require HTTPS; enabling the Caddy profile satisfies this.
```

After it, add:

```markdown

### API Documentation & Metrics Exposure

`DOCS_ENABLED` defaults to `false`. **Never set `DOCS_ENABLED=true` in production** — it exposes the full API schema (every route, parameter, and model) to unauthenticated clients. Local dev sets this automatically via `docker-compose.override.yml`.

> **Port 8000 must not be published to the host in production.** If `docker-compose.yml` maps `8000:8000`, the Caddyfile deny block for `/metrics` is bypassed and Prometheus metrics are world-readable. Verify the production compose has no host port mapping for the backend service.

```

**Step 4c — Verify dev stack uses DOCS_ENABLED=true**

```bash
# With docker-compose.override.yml present (local dev):
docker-compose config | grep -A5 "DOCS_ENABLED"
# Expected: DOCS_ENABLED: "true" in backend environment

# Test docs accessible in dev:
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/docs
# Expected: 200 (DOCS_ENABLED=true from override file)
```

**Step 4d — Commit**

```bash
git add docker-compose.override.yml deployment-guide.md
git commit -m "feat(#369): enable docs in dev override, document production restrictions"
```

---

## Verification Checklist

After all tasks are complete, validate the full security fix:

```bash
# 1. Confirm backend reloaded
docker-compose logs backend --tail=5

# 2. Production behavior (no DOCS_ENABLED override):
#    Test with baked-image stack (no override file):
docker-compose -f docker-compose.yml exec backend sh -c "echo \$DOCS_ENABLED"
# Expected: (empty) — defaults to False

# 3. Docs return 401 for unauthenticated requests (AuthMiddleware blocks):
curl -i http://localhost:8000/docs 2>&1 | head -5
# Expected: HTTP/1.1 401

# 4. Metrics still accessible internally (Prometheus scrape path):
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/metrics
# Expected: 200

# 5. Full test suite:
docker-compose exec backend python -m pytest backend/tests/ -q 2>&1 | tail -10
# Expected: all pass
```
