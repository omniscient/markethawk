# TLS Termination and Secure Cookie Enforcement — Implementation Plan

**Date:** 2026-06-05
**Issue:** #202 — [arch-v2][MED] Enforce secure cookies + TLS termination
**Spec:** [docs/superpowers/specs/2026-06-05-tls-termination-secure-cookies-design.md](../specs/2026-06-05-tls-termination-secure-cookies-design.md)
**Branch:** `refine/issue-202--arch-v2--med--enforce-secure-cookies---`

---

## Goal

Close Architecture Quality Report v2 risk R12 (Transport Security, 2/5):
1. Add `COOKIE_SECURE: bool = True` to `Settings`; decouple cookie security from `ENVIRONMENT`.
2. Harden `_set_auth_cookies` to use `settings.COOKIE_SECURE` and `SameSite=Strict`.
3. Change all `0.0.0.0` port bindings in `docker-compose.yml` to `127.0.0.1` for defense-in-depth.
4. Add a profile-gated Caddy reverse proxy (`profiles: ["tls"]`) with auto-HTTPS for deployed stacks.
5. Override `COOKIE_SECURE=false` in `docker-compose.override.yml` so plain-HTTP local dev continues to work.
6. Wire `--profile tls` into `deploy.yml` so Caddy starts on deployed servers.
7. Replace the stub TLS section in `deployment-guide.md`; document `COOKIE_SECURE` and `DOMAIN` in `ENV_VARIABLES.md`.

---

## Architecture

```
[Browser / curl]
       │  HTTPS (port 443)
       ▼
 ┌───────────────────────────────┐
 │   Caddy (caddy:2-alpine)      │  profile: tls — absent in local dev
 │   {$DOMAIN:localhost}         │
 │   /api/* → backend:8000       │
 │   /*      → frontend:3333     │
 └───────────────────────────────┘
       │ plain HTTP (container-internal)
  ┌────┴────────┐
  ▼             ▼
backend:8000  frontend:3333
```

**Cookie hardening:** `COOKIE_SECURE: bool = True` in `config.py`. Auth cookies read `settings.COOKIE_SECURE` directly instead of deriving from `ENVIRONMENT`. `docker-compose.override.yml` sets `COOKIE_SECURE: "false"` so local dev browsers don't reject cookies over plain HTTP.

**Port binding hardening:** All services previously binding `0.0.0.0` are changed to `127.0.0.1`, preventing direct external access without going through the proxy.

---

## Tech Stack

- FastAPI + pydantic-settings (cookie setting)
- Docker Compose profiles (Caddy gating)
- Caddy v2-alpine (TLS termination, auto-HTTPS via Let's Encrypt)

---

## File Structure

| File | Action | Requirements |
|------|--------|--------------|
| `backend/app/core/config.py` | Edit — add `COOKIE_SECURE: bool = True` | REQ-2 |
| `backend/app/routers/auth.py` | Edit — use `settings.COOKIE_SECURE`; `samesite="strict"` | REQ-3, REQ-5 |
| `backend/tests/api/test_auth.py` | Edit — add TDD tests for config default and cookie flags | TDD coverage |
| `docker-compose.yml` | Edit — 6 port bindings + caddy service + 2 named volumes | REQ-1, REQ-7 |
| `caddy/Caddyfile` | New — Caddy reverse proxy config | REQ-6 |
| `docker-compose.override.yml` | Edit — add `COOKIE_SECURE: "false"` to backend service | REQ-4 |
| `.github/workflows/deploy.yml` | Edit — add `--profile tls` to deploy command | REQ-10 |
| `deployment-guide.md` | Edit — replace stub TLS section with Caddy setup | REQ-8 |
| `ENV_VARIABLES.md` | Edit — document `COOKIE_SECURE` and `DOMAIN` | REQ-9 |

---

## Task 1: Add COOKIE_SECURE setting to config.py (REQ-2)

**Files:** `backend/app/core/config.py`, `backend/tests/api/test_auth.py`

**Note on conftest.py:** `COOKIE_SECURE: bool = True` is a plain field with a default value — no `field_validator` is added. Per the backend-patterns memory, `conftest.py` only needs `os.environ.setdefault` for new validators. No `conftest.py` change is needed here.

### Step 1.1 — Write failing test

Add to `backend/tests/api/test_auth.py` (after the existing module-level setup, before the first test function):

```python
def test_cookie_secure_defaults_to_true():
    """COOKIE_SECURE field defaults to True (secure-by-default posture)."""
    from app.core.config import Settings
    s = Settings(
        DATABASE_URL="postgresql://test:test@localhost/test",
        POLYGON_API_KEY="test",
        JWT_SECRET_KEY="a" * 32,
    )
    assert s.COOKIE_SECURE is True
```

### Step 1.2 — Verify test fails

```bash
cd /workspace/markethawk/backend
python -m pytest tests/api/test_auth.py::test_cookie_secure_defaults_to_true -v
```

Expected failure: `AttributeError: type object 'Settings' has no attribute 'COOKIE_SECURE'`

### Step 1.3 — Implement: add COOKIE_SECURE to config.py

In `backend/app/core/config.py`, after the `REFRESH_TOKEN_EXPIRE_DAYS` line, add:

```python
    COOKIE_SECURE: bool = True
```

Exact placement — after line `REFRESH_TOKEN_EXPIRE_DAYS: int = 7`:

```python
    # Auth
    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    COOKIE_SECURE: bool = True
```

### Step 1.4 — Verify test passes

```bash
cd /workspace/markethawk/backend
python -m pytest tests/api/test_auth.py::test_cookie_secure_defaults_to_true -v
```

Expected: `PASSED`

### Step 1.5 — Run full auth test suite to confirm no regressions

```bash
cd /workspace/markethawk/backend
python -m pytest tests/api/test_auth.py -v
```

Expected: all tests pass (TestClient does not enforce the browser secure-cookie rule, so `COOKIE_SECURE=True` does not break login/logout tests)

### Step 1.6 — Commit

```bash
git add backend/app/core/config.py backend/tests/api/test_auth.py
git commit -m "$(cat <<'EOF'
feat(#202): add COOKIE_SECURE setting to config.py (secure-by-default)

Decouples cookie security from ENVIRONMENT by introducing a dedicated
COOKIE_SECURE: bool = True setting. Default True matches the existing
ENVIRONMENT: str = "production" secure-by-default posture.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Harden auth.py cookie flags (REQ-3, REQ-5)

**Files:** `backend/app/routers/auth.py`, `backend/tests/api/test_auth.py`

### Step 2.1 — Write failing test

Add to `backend/tests/api/test_auth.py`:

```python
def test_login_cookies_have_strict_samesite(db):
    """Login response cookies use SameSite=strict (not lax)."""
    client.post("/api/auth/register", json={"username": "admin", "password": "hunter2"})
    response = client.post("/api/auth/login", json={"username": "admin", "password": "hunter2"})
    assert response.status_code == 200
    # httpx Headers.get_list() returns all values for a multi-value header
    set_cookie_headers = response.headers.get_list("set-cookie")
    assert len(set_cookie_headers) >= 1
    for header in set_cookie_headers:
        assert "samesite=strict" in header.lower(), (
            f"Expected SameSite=strict in Set-Cookie header, got: {header}"
        )
```

### Step 2.2 — Verify test fails

```bash
cd /workspace/markethawk/backend
python -m pytest tests/api/test_auth.py::test_login_cookies_have_strict_samesite -v
```

Expected failure: `AssertionError: Expected SameSite=strict in Set-Cookie header, got: ... samesite=lax ...`

### Step 2.3 — Implement: update _set_auth_cookies in auth.py

In `backend/app/routers/auth.py`, replace the `_set_auth_cookies` function body:

**Before:**
```python
def _set_auth_cookies(
    response: Response, access_token: str, refresh_token: str
) -> None:
    settings = get_settings()
    is_prod = settings.ENVIRONMENT == "production"
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        samesite="lax",
        secure=is_prod,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        samesite="lax",
        secure=is_prod,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        path="/api/auth/refresh",
    )
```

**After:**
```python
def _set_auth_cookies(
    response: Response, access_token: str, refresh_token: str
) -> None:
    settings = get_settings()
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        samesite="strict",
        secure=settings.COOKIE_SECURE,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        samesite="strict",
        secure=settings.COOKIE_SECURE,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        path="/api/auth/refresh",
    )
```

### Step 2.4 — Verify test passes

```bash
cd /workspace/markethawk/backend
python -m pytest tests/api/test_auth.py::test_login_cookies_have_strict_samesite -v
```

Expected: `PASSED`

### Step 2.5 — Run full auth test suite

```bash
cd /workspace/markethawk/backend
python -m pytest tests/api/test_auth.py -v
```

Expected: all tests pass

### Step 2.6 — Confirm backend reloaded (live validation)

```bash
docker-compose logs backend --tail=10
curl -s http://localhost:8000/api/auth/status | python -m json.tool
```

Expected: no startup errors in logs; `/api/auth/status` returns `{"bootstrapped": false}` or `{"bootstrapped": true}`

### Step 2.7 — Commit

```bash
git add backend/app/routers/auth.py backend/tests/api/test_auth.py
git commit -m "$(cat <<'EOF'
feat(#202): use COOKIE_SECURE setting in auth cookies; upgrade SameSite to strict

Replaces is_prod derivation (ENVIRONMENT == "production") with the
dedicated COOKIE_SECURE setting. SameSite upgraded from lax to strict —
safe because all browser traffic routes through the same-origin Caddy
proxy in production with no cross-site navigation or OAuth redirect flows.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Harden port bindings in docker-compose.yml (REQ-7)

**Files:** `docker-compose.yml`

No unit test — validation is via `docker compose config` and grep assertions.

### Step 3.1 — Change port bindings

Make the following 7 binding changes in `docker-compose.yml`:

**ib-gateway** (lines ~67–68):
```yaml
# Before
      - "4004:4004"   # paper trading (socat proxy → localhost:4002) — use this for API clients
      - "4003:4003"   # live trading  (socat proxy → localhost:4001) — unused until needed
# After
      - "127.0.0.1:4004:4004"   # paper trading (socat proxy → localhost:4002) — use this for API clients
      - "127.0.0.1:4003:4003"   # live trading  (socat proxy → localhost:4001) — unused until needed
```

**backend** (line ~121):
```yaml
# Before
      - "8000:8000"
# After
      - "127.0.0.1:8000:8000"
```

**frontend** (line ~150):
```yaml
# Before
      - "3333:3333"
# After
      - "127.0.0.1:3333:3333"
```

**prometheus** (line ~387):
```yaml
# Before
      - "9090:9090"
# After
      - "127.0.0.1:9090:9090"
```

**grafana** (line ~399):
```yaml
# Before
      - "3001:3000"
# After
      - "127.0.0.1:3001:3000"
```

**jaeger OTLP** (line ~528):
```yaml
# Before
      - "4317:4317"                # OTLP gRPC receiver
# After
      - "127.0.0.1:4317:4317"     # OTLP gRPC receiver
```

### Step 3.2 — Validate docker-compose config parses cleanly

```bash
docker compose config --quiet 2>&1
echo "Exit code: $?"
```

Expected: no output, exit code 0

### Step 3.3 — Confirm no bare (0.0.0.0) port bindings remain

```bash
grep -nE '^\s+- "[0-9]+:[0-9]+' /workspace/markethawk/docker-compose.yml
```

Expected: no output (all port bindings now have a host IP prefix)

### Step 3.4 — Commit

```bash
git add docker-compose.yml
git commit -m "$(cat <<'EOF'
feat(#202): harden all 0.0.0.0 port bindings to 127.0.0.1

Changes backend (8000), frontend (3333), ib-gateway (4004/4003),
prometheus (9090), grafana (3001), and jaeger OTLP (4317) to bind
127.0.0.1 for defense-in-depth. Services already on 127.0.0.1
(postgres, redis, flower, pgadmin, seq, jaeger UI) are unchanged.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Add caddy/Caddyfile and caddy service (REQ-1, REQ-6)

**Files:** `caddy/Caddyfile` (new), `docker-compose.yml`

### Step 4.1 — Create caddy/Caddyfile

Create the directory and file:

```bash
mkdir -p /workspace/markethawk/caddy
```

File content for `caddy/Caddyfile`:

```
{$DOMAIN:localhost} {
    handle /api/* {
        reverse_proxy backend:8000
    }
    handle {
        reverse_proxy frontend:3333
    }
}
```

Caddy's `reverse_proxy` directive handles HTTP Upgrade (WebSocket) requests transparently — `/api/v1/live/ws/*` works without an explicit `@websocket` matcher.

When `DOMAIN` is unset, `{$DOMAIN:localhost}` falls back to `localhost` and Caddy generates a locally-trusted self-signed cert. Developers use plain HTTP without the `tls` profile; the self-signed cert is only active if they explicitly run `--profile tls`.

### Step 4.2 — Add caddy service to docker-compose.yml

Insert the following service block in `docker-compose.yml` **immediately before the top-level `volumes:` key** (i.e., as the last entry in the `services:` block, just before the line that reads `volumes:` at the top level):

```yaml
  # TLS reverse proxy — auto-HTTPS via Let's Encrypt (profile-gated; absent in local dev)
  caddy:
    image: caddy:2-alpine
    container_name: stockscanner-caddy
    ports:
      - "80:80"
      - "443:443"
      - "443:443/udp"
    volumes:
      - ./caddy/Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    networks:
      - stockscanner-network
    restart: unless-stopped
    profiles:
      - tls
```

### Step 4.3 — Add caddy_data and caddy_config to the volumes block

In the `volumes:` block (line ~534), after the existing `grafana_data:` entry, add:

```yaml
  caddy_data:
  caddy_config:
```

These are internal (non-external) volumes unlike `postgres_data`/`redis_data` which require pre-creation. `caddy_data` persists Let's Encrypt certs across container restarts — critical because Let's Encrypt rate-limits new issuances to 5 per domain per week.

### Step 4.4 — Validate docker-compose config with and without the tls profile

```bash
docker compose config --quiet 2>&1
echo "Base config exit: $?"
docker compose --profile tls config --quiet 2>&1
echo "TLS profile exit: $?"
```

Expected: both exit 0 with no output

### Step 4.5 — Confirm caddy service only appears under --profile tls

```bash
docker compose config | grep -A3 "caddy:"
docker compose --profile tls config | grep -A3 "caddy:"
```

Expected: first command shows no caddy service; second shows the caddy service block

### Step 4.6 — Commit

```bash
git add caddy/Caddyfile docker-compose.yml
git commit -m "$(cat <<'EOF'
feat(#202): add Caddy TLS proxy service (profile-gated) and Caddyfile

Caddy service uses profiles: [tls] so it is absent in local dev
checkouts. Routes /api/* to backend:8000 and /* to frontend:3333.
caddy_data volume persists Let's Encrypt certs across restarts.
caddy_data/caddy_config are internal (non-external) volumes.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Add COOKIE_SECURE=false override for local dev (REQ-4)

**Files:** `docker-compose.override.yml`

### Step 5.1 — Add environment block to backend service in docker-compose.override.yml

In `docker-compose.override.yml`, the current `backend:` block has only `volumes:` and `command:` keys. Add `environment:` before `volumes:`:

```yaml
  backend:
    environment:
      COOKIE_SECURE: "false"
    volumes:
      - ./backend:/app:ro
      - prometheus_multiproc:/tmp/prometheus_multiproc
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Docker Compose merges `environment:` maps additively — `COOKIE_SECURE: "false"` is appended to the env vars declared in `docker-compose.yml`'s `backend:` service without disturbing other vars (`DATABASE_URL`, `JWT_SECRET_KEY`, etc.).

### Step 5.2 — Validate config and verify the merge

```bash
docker compose config --quiet 2>&1
echo "Exit: $?"
docker compose config | grep -A30 "container_name: stockscanner-api" | grep COOKIE_SECURE
```

Expected: exit 0; second command shows `COOKIE_SECURE: "false"`

### Step 5.3 — Commit

```bash
git add docker-compose.override.yml
git commit -m "$(cat <<'EOF'
feat(#202): set COOKIE_SECURE=false in override for plain-HTTP local dev

docker-compose.override.yml is applied automatically by "docker-compose up -d"
in local checkouts. Sets COOKIE_SECURE=false so browser secure-cookie
enforcement does not prevent login over plain HTTP during development.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Add --profile tls to deploy.yml (REQ-10)

**Files:** `.github/workflows/deploy.yml`

### Step 6.1 — Update the docker compose up -d invocation

In `.github/workflows/deploy.yml`, the current restart command (lines ~41–42):

```yaml
            # Restart services with updated images
            docker compose up -d \
              backend celery-worker celery-beat live-scanner flower frontend
```

Change to:

```yaml
            # Restart services with updated images (--profile tls activates Caddy on deployed servers)
            docker compose --profile tls up -d \
              backend celery-worker celery-beat live-scanner flower frontend caddy
```

`caddy` is added to the explicit service list; `--profile tls` makes the profile active so the profile-gated `caddy` service definition is not skipped.

### Step 6.2 — Validate YAML syntax

```bash
python3 -c "import yaml; yaml.safe_load(open('/workspace/markethawk/.github/workflows/deploy.yml')); print('OK')"
```

Expected: `OK`

### Step 6.3 — Commit

```bash
git add .github/workflows/deploy.yml
git commit -m "$(cat <<'EOF'
feat(#202): add --profile tls to deploy workflow so Caddy starts on deploy

Adds caddy to the explicit service list and passes --profile tls to
activate the profile-gated Caddy service. Consistent with the existing
--profile factory/scheduler pattern used by other profile-gated services.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Update documentation (REQ-8, REQ-9)

**Files:** `deployment-guide.md`, `ENV_VARIABLES.md`

### Step 7.1 — Replace stub TLS section in deployment-guide.md

Find and replace the current stub section:

```markdown
### SSL / TLS

Docker Compose does not include a TLS termination layer. For HTTPS, place a reverse proxy (nginx, Caddy, Traefik) in front of the frontend and backend containers and let Docker Compose handle internal traffic over HTTP.
```

Replace with:

```markdown
### TLS / HTTPS (Caddy)

MarketHawk ships a Caddy reverse proxy service, profile-gated as `tls`, that provides automatic HTTPS via Let's Encrypt.

#### Prerequisites

- DNS A record for your domain pointing to the server's public IP.
- Ports 80 and 443 open in the server firewall.
- `DOMAIN` set in `.env` (e.g. `DOMAIN=markethawk.example.com`).
- `CORS_ORIGINS` in `.env` updated to include the HTTPS domain (e.g. `CORS_ORIGINS=["https://markethawk.example.com"]`).

#### Enabling TLS

The `deploy.yml` GitHub Actions workflow already passes `--profile tls` — Caddy starts automatically on every automated deploy. For a manual deploy:

```bash
docker compose --profile tls up -d backend celery-worker celery-beat live-scanner flower frontend caddy
```

Caddy reads `DOMAIN` from the environment and provisions a Let's Encrypt cert on first start. Cert data is stored in the `caddy_data` Docker volume and persists across restarts. Caddy auto-renews before expiry.

#### Caddyfile routing

Traffic is routed by `caddy/Caddyfile`:

| Path | Upstream |
|------|----------|
| `/api/*` | `backend:8000` (FastAPI; WebSocket upgrades for `/api/v1/live/ws/*` are handled transparently) |
| `/*` | `frontend:3333` (React SPA) |

#### Cookie security

Cookies use `Secure` and `SameSite=Strict`. In local dev (with `docker-compose.override.yml`), `COOKIE_SECURE=false` is set automatically so plain-HTTP sessions work without any developer action.

#### Let's Encrypt rate limits

Let's Encrypt allows 5 certificate issuances per domain per week. The `caddy_data` volume prevents re-issuance on container restart. Do not delete this volume in production unless you are prepared to wait out the rate-limit window.
```

### Step 7.2 — Add COOKIE_SECURE to ENV_VARIABLES.md

Find the Auth section table (containing `ACCESS_TOKEN_EXPIRE_MINUTES`) and add a row for `COOKIE_SECURE` after `REFRESH_TOKEN_EXPIRE_DAYS`:

```markdown
| `COOKIE_SECURE` | `true` | Adds the `Secure` attribute to session cookies. Set to `false` in `docker-compose.override.yml` for plain-HTTP local dev. Default `true` ensures deployed stacks are always secure without operator action. |
```

### Step 7.3 — Add DOMAIN to ENV_VARIABLES.md

After the existing Caddy/TLS content or in the Infrastructure/Deploy section, add a table for deployment variables. If a suitable section exists, add a row; otherwise create:

```markdown
### TLS / Caddy

| Variable | Default | Description |
|----------|---------|-------------|
| `DOMAIN` | — | Public hostname for Caddy auto-HTTPS (e.g. `markethawk.example.com`). Required when running with `--profile tls`. When unset, Caddy falls back to `localhost` with a locally-trusted self-signed cert. |
```

### Step 7.4 — Commit

```bash
git add deployment-guide.md ENV_VARIABLES.md
git commit -m "$(cat <<'EOF'
feat(#202): document Caddy TLS setup in deployment guide; add COOKIE_SECURE and DOMAIN to ENV_VARIABLES.md

Replaces the stub "place a reverse proxy" note with concrete Caddy
prerequisites, enable commands, routing table, and Let's Encrypt
rate-limit warning.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Validation Checklist (post-all-tasks)

Before declaring the branch ready, verify:

```bash
# 1. All auth tests pass
cd /workspace/markethawk/backend
python -m pytest tests/api/test_auth.py -v

# 2. No bare 0.0.0.0 port bindings remain
grep -nE '^\s+- "[0-9]+:[0-9]+' /workspace/markethawk/docker-compose.yml
# Expected: no output

# 3. Caddy volumes present in compose config
docker compose config | grep -E "caddy_data|caddy_config"
# Expected: both volume names appear

# 4. COOKIE_SECURE=false in merged override for backend service
docker compose config | grep COOKIE_SECURE
# Expected: COOKIE_SECURE: "false"

# 5. --profile tls activates caddy service
docker compose --profile tls config | grep "container_name: stockscanner-caddy"
# Expected: container_name: stockscanner-caddy
```
