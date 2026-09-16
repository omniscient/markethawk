# System Notifications Enabler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a generic `notify_system()` + `POST /api/v1/alerts/system` endpoint that delivers email + browser-push for non-scanner events, reusing the existing SMTP/VAPID delivery.

**Architecture:** Extract the scanner-coupled browser-push loop into a generic payload sender (email's `_send_email(to, subject, body)` is already generic). Add a thin `system_notifier.notify_system()` that fans out to email + push with per-channel fail-soft and an in-process dedupe cooldown. Expose it via a token-guarded endpoint that is exempt from the JWT/CSRF middleware (server-to-server).

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (sync), `smtplib` (SMTP), `pywebpush` (VAPID), pytest.

**Spec:** `docs/superpowers/specs/2026-06-20-system-notifications-enabler-design.md`

## Global Constraints

- No new **required-no-default** Settings field — both new fields default to `""` (the smoke gate runs `python -c "import app.main"` with only 3 env vars; a required field breaks it, cf. REDIS_PASSWORD).
- Endpoint auth is a shared secret `X-Internal-Token` (NOT JWT) — decoupled from the in-flight authz epic #373.
- `notify_system` must be **fail-soft**: a channel error is logged + recorded in the return value, never raised.
- Router prefix is `/api/v1/alerts` (full path `/api/v1/alerts/system`).
- Tests mock `smtplib`/`pywebpush` — no live SMTP/push in CI.

---

### Task 1: Config fields

**Files:**
- Modify: `backend/app/core/config.py` (Settings class, near SMTP fields ~line 110 and JWT ~line 57)
- Test: `backend/tests/core/test_config_system_notify.py`

**Interfaces:**
- Produces: `settings.OPS_ALERT_EMAIL: str` (default `""`), `settings.INTERNAL_API_TOKEN: str` (default `""`)

- [ ] **Step 1: Write the failing test**
```python
# backend/tests/core/test_config_system_notify.py
from app.core.config import Settings

def test_system_notify_fields_default_empty(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://smoke:smoke@localhost:5432/smoke")
    monkeypatch.setenv("POLYGON_API_KEY", "x")
    monkeypatch.setenv("JWT_SECRET_KEY", "smoke-gate-only-not-secret-0123456789abcdef")
    monkeypatch.setenv("REDIS_PASSWORD", "smoke-gate-only-not-a-real-redis-password")
    s = Settings()
    assert s.OPS_ALERT_EMAIL == ""
    assert s.INTERNAL_API_TOKEN == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/core/test_config_system_notify.py -v`
Expected: FAIL (`AttributeError: 'Settings' object has no attribute 'OPS_ALERT_EMAIL'`)

- [ ] **Step 3: Add the fields**

In `backend/app/core/config.py`, add after `SMTP_FROM_EMAIL` (~line 110):
```python
    # System notifications (generic non-scanner alerts). Both optional/empty-default —
    # NEVER make these required-no-default (would break the smoke gate, cf. REDIS_PASSWORD).
    OPS_ALERT_EMAIL: str = ""
    INTERNAL_API_TOKEN: str = Field(default="", repr=False)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/core/test_config_system_notify.py -v`
Expected: PASS

- [ ] **Step 5: Verify smoke-gate import still passes**

Run: `docker exec stockscanner-api sh -c 'cd /app && env -i PATH=/usr/local/bin:/usr/bin:/bin HOME=/root DATABASE_URL=postgresql://smoke:smoke@localhost:5432/smoke POLYGON_API_KEY=x JWT_SECRET_KEY=smoke-gate-only-not-secret-0123456789abcdef REDIS_PASSWORD=smoke-gate-only-not-a-real-redis-password python -c "import app.main; print(\"OK\")"'`
Expected: `OK`

- [ ] **Step 6: Commit**
```bash
git add backend/app/core/config.py backend/tests/core/test_config_system_notify.py
git commit -m "feat(config): add OPS_ALERT_EMAIL + INTERNAL_API_TOKEN (optional, empty-default)"
```

---

### Task 2: Extract a generic browser-push sender

**Files:**
- Modify: `backend/app/services/alert_service.py:177-226` (`_send_browser_push`)
- Test: `backend/tests/services/test_push_generic.py`

**Interfaces:**
- Produces: `NotificationDispatcher._push_to_subscriptions(payload: dict, db: Session) -> int` (returns # delivered; raises `RuntimeError` only if ALL deliveries fail)
- `_send_browser_push(event, db)` becomes a thin wrapper that builds the scanner payload then calls `_push_to_subscriptions`.

- [ ] **Step 1: Write the failing test**
```python
# backend/tests/services/test_push_generic.py
from unittest.mock import MagicMock, patch
from app.services.alert_service import NotificationDispatcher

@patch("app.services.alert_service.settings")
def test_push_to_subscriptions_sends_to_all(mock_settings):
    mock_settings.VAPID_PRIVATE_KEY = "k"; mock_settings.VAPID_PUBLIC_KEY = "p"
    mock_settings.VAPID_CLAIMS_EMAIL = "mailto:a@b.c"
    db = MagicMock()
    sub = MagicMock(endpoint="e", p256dh="x", auth="y", id=1)
    db.query.return_value.all.return_value = [sub]
    with patch("pywebpush.webpush") as wp:
        count = NotificationDispatcher._push_to_subscriptions(
            {"title": "T", "body": "B", "severity": "warning", "url": "/"}, db)
    assert count == 1
    wp.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/services/test_push_generic.py -v`
Expected: FAIL (`AttributeError: ... has no attribute '_push_to_subscriptions'`)

- [ ] **Step 3: Refactor — add the generic sender, rewire the scanner wrapper**

In `backend/app/services/alert_service.py`, replace the body of `_send_browser_push` (lines 177-226). Move the VAPID check + subscription loop into a new generic method that takes a pre-built `payload`:
```python
    @staticmethod
    def _push_to_subscriptions(payload: dict, db: Session) -> int:
        """Web-push `payload` (a dict with title/body/...) to all stored subscriptions.
        Returns the number delivered. Raises RuntimeError only if ALL deliveries fail."""
        try:
            from pywebpush import webpush  # noqa: F401
        except ImportError:
            raise RuntimeError("pywebpush is not installed. Add it to requirements.txt and rebuild.")
        if not settings.VAPID_PRIVATE_KEY or not settings.VAPID_PUBLIC_KEY:
            raise ValueError("VAPID_PRIVATE_KEY and VAPID_PUBLIC_KEY must be set to send browser push.")
        subscriptions = db.query(PushSubscription).all()
        if not subscriptions:
            logger.debug("No push subscriptions registered — skipping browser push.")
            return 0
        data = json.dumps(payload)
        vapid_claims = {"sub": settings.VAPID_CLAIMS_EMAIL}
        failed = 0
        for sub in subscriptions:
            try:
                webpush(
                    subscription_info={"endpoint": sub.endpoint,
                                       "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
                    data=data, vapid_private_key=settings.VAPID_PRIVATE_KEY, vapid_claims=vapid_claims)
            except Exception as exc:
                failed += 1
                if "410" in str(exc) or "404" in str(exc):
                    logger.info(f"Removing expired push subscription id={sub.id}"); db.delete(sub)
                else:
                    logger.warning(f"Push failed for subscription {sub.id}: {exc}")
        if failed == len(subscriptions):
            raise RuntimeError(f"All {failed} push deliveries failed.")
        return len(subscriptions) - failed

    @staticmethod
    def _send_browser_push(event: ScannerEvent, db: Session) -> None:
        """Scanner-event browser push (thin wrapper over the generic sender)."""
        NotificationDispatcher._push_to_subscriptions(
            NotificationDispatcher._build_push_payload(event), db)
```
(`webpush` is imported lazily inside `_push_to_subscriptions`; the test patches `pywebpush.webpush`.)

- [ ] **Step 4: Run tests to verify pass (new + existing alert tests)**

Run: `pytest backend/tests/services/test_push_generic.py backend/tests/services/ -k "push or alert" -v`
Expected: PASS (new test passes; existing scanner-push tests unaffected)

- [ ] **Step 5: Commit**
```bash
git add backend/app/services/alert_service.py backend/tests/services/test_push_generic.py
git commit -m "refactor(alerts): extract generic _push_to_subscriptions from scanner push"
```

---

### Task 3: `notify_system()`

**Files:**
- Create: `backend/app/services/system_notifier.py`
- Test: `backend/tests/services/test_system_notifier.py`

**Interfaces:**
- Consumes: `NotificationDispatcher._send_email(to, subject, body)`, `NotificationDispatcher._push_to_subscriptions(payload, db)` (Task 2), `settings.OPS_ALERT_EMAIL`
- Produces: `notify_system(title, body, severity="info", dedupe_key=None, channels=None, db=None, cooldown_seconds=3600, _now=None) -> dict[str, str]` (per-channel: `"sent"|"sent:<n>"|"skipped"|"suppressed"|"unknown_channel"|"failed:<reason>"`)

- [ ] **Step 1: Write the failing tests**
```python
# backend/tests/services/test_system_notifier.py
from unittest.mock import patch
import app.services.system_notifier as sn

def _patch(email_ok=True, ops="ops@x.com"):
    return patch.multiple("app.services.system_notifier",
        settings=type("S", (), {"OPS_ALERT_EMAIL": ops})())

@patch("app.services.system_notifier.NotificationDispatcher")
def test_email_and_push(mock_disp):
    with patch.object(sn.settings, "OPS_ALERT_EMAIL", "ops@x.com"):
        mock_disp._push_to_subscriptions.return_value = 2
        r = sn.notify_system("T", "B", severity="warning", db=object())
    assert r["email"] == "sent"
    assert r["browser_push"] == "sent:2"
    mock_disp._send_email.assert_called_once()

@patch("app.services.system_notifier.NotificationDispatcher")
def test_email_skipped_when_ops_unset(mock_disp):
    with patch.object(sn.settings, "OPS_ALERT_EMAIL", ""):
        mock_disp._push_to_subscriptions.return_value = 0
        r = sn.notify_system("T", "B", db=object())
    assert r["email"] == "skipped"
    mock_disp._send_email.assert_not_called()

@patch("app.services.system_notifier.NotificationDispatcher")
def test_channel_failure_is_soft(mock_disp):
    with patch.object(sn.settings, "OPS_ALERT_EMAIL", "ops@x.com"):
        mock_disp._send_email.side_effect = RuntimeError("smtp down")
        mock_disp._push_to_subscriptions.return_value = 1
        r = sn.notify_system("T", "B", db=object())
    assert r["email"].startswith("failed:")
    assert r["browser_push"] == "sent:1"

@patch("app.services.system_notifier.NotificationDispatcher")
def test_dedupe_suppresses_within_cooldown(mock_disp):
    with patch.object(sn.settings, "OPS_ALERT_EMAIL", "ops@x.com"):
        mock_disp._push_to_subscriptions.return_value = 0
        first = sn.notify_system("T", "B", dedupe_key="k1", db=object(), cooldown_seconds=100, _now=1000.0)
        second = sn.notify_system("T", "B", dedupe_key="k1", db=object(), cooldown_seconds=100, _now=1050.0)
        third = sn.notify_system("T", "B", dedupe_key="k1", db=object(), cooldown_seconds=100, _now=1200.0)
    assert first["email"] == "sent"
    assert second == {"email": "suppressed", "browser_push": "suppressed"}
    assert third["email"] == "sent"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/services/test_system_notifier.py -v`
Expected: FAIL (`ModuleNotFoundError: app.services.system_notifier`)

- [ ] **Step 3: Implement `system_notifier.py`**
```python
# backend/app/services/system_notifier.py
"""Generic system notifications (non-scanner) reusing the alert delivery channels."""
import logging
import time
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.alert_service import NotificationDispatcher

logger = logging.getLogger(__name__)

# In-process dedupe cache: dedupe_key -> last-sent monotonic timestamp.
# Best-effort (per-process, resets on restart) — acceptable for fail-soft alerts.
_dedupe_cache: dict[str, float] = {}

_SEV_COLOR = {"info": "#3b82f6", "warning": "#f59e0b", "critical": "#ef4444"}


def _html(title: str, body: str, severity: str) -> str:
    color = _SEV_COLOR.get(severity, "#3b82f6")
    return (
        '<html><body style="font-family:sans-serif;background:#111827;color:#f3f4f6;padding:24px">'
        f'<h2 style="color:{color}">{title}</h2><p>{body}</p></body></html>'
    )


def notify_system(
    title: str,
    body: str,
    severity: str = "info",
    dedupe_key: Optional[str] = None,
    channels: Optional[list[str]] = None,
    db: Optional[Session] = None,
    cooldown_seconds: int = 3600,
    _now: Optional[float] = None,
) -> dict:
    """Fan out a system notification to email + browser push. Never raises."""
    channels = channels if channels is not None else ["email", "browser_push"]
    now = _now if _now is not None else time.monotonic()

    if dedupe_key is not None:
        last = _dedupe_cache.get(dedupe_key)
        if last is not None and (now - last) < cooldown_seconds:
            return {ch: "suppressed" for ch in channels}
        _dedupe_cache[dedupe_key] = now

    subject = title if severity == "info" else f"[{severity.upper()}] {title}"
    result: dict[str, str] = {}
    for ch in channels:
        try:
            if ch == "email":
                if settings.OPS_ALERT_EMAIL:
                    NotificationDispatcher._send_email(settings.OPS_ALERT_EMAIL, subject, _html(title, body, severity))
                    result[ch] = "sent"
                else:
                    result[ch] = "skipped"
            elif ch == "browser_push":
                if db is not None:
                    count = NotificationDispatcher._push_to_subscriptions(
                        {"title": title, "body": body, "severity": severity, "url": "/"}, db)
                    result[ch] = f"sent:{count}"
                else:
                    result[ch] = "skipped"
            else:
                result[ch] = "unknown_channel"
        except Exception as exc:  # fail-soft per channel
            logger.error("system notification channel=%s failed: %s", ch, exc)
            result[ch] = f"failed:{exc}"
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/tests/services/test_system_notifier.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**
```bash
git add backend/app/services/system_notifier.py backend/tests/services/test_system_notifier.py
git commit -m "feat(notifications): add notify_system() generic email/push dispatcher"
```

---

### Task 4: `POST /api/v1/alerts/system` endpoint + middleware exemption

**Files:**
- Modify: `backend/app/routers/alerts.py` (add import + endpoint)
- Modify: `backend/app/main.py:52` (CSRF_EXEMPT_PREFIXES) and `backend/app/main.py:280-286` (`_base_exempt`)
- Test: `backend/tests/routers/test_alerts_system.py`

**Interfaces:**
- Consumes: `notify_system(...)` (Task 3), `settings.INTERNAL_API_TOKEN`
- Produces: `POST /api/v1/alerts/system` — `{title, body, severity?, dedupe_key?, channels?}` + header `X-Internal-Token` → `{"status":"dispatched","channels":{...}}`. 503 if token unset, 401 if mismatch, 422 if title/body missing.

- [ ] **Step 1: Write the failing tests**
```python
# backend/tests/routers/test_alerts_system.py
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import create_app

def _client():
    return TestClient(create_app())

def test_503_when_token_unset():
    with patch("app.routers.alerts.settings") as s:
        s.INTERNAL_API_TOKEN = ""
        r = _client().post("/api/v1/alerts/system", json={"title": "t", "body": "b"})
    assert r.status_code == 503

def test_401_on_bad_token():
    with patch("app.routers.alerts.settings") as s:
        s.INTERNAL_API_TOKEN = "secret"
        r = _client().post("/api/v1/alerts/system", json={"title": "t", "body": "b"},
                           headers={"X-Internal-Token": "wrong"})
    assert r.status_code == 401

def test_200_dispatches():
    with patch("app.routers.alerts.settings") as s, \
         patch("app.routers.alerts.notify_system") as ns:
        s.INTERNAL_API_TOKEN = "secret"
        ns.return_value = {"email": "sent", "browser_push": "sent:0"}
        r = _client().post("/api/v1/alerts/system",
                           json={"title": "t", "body": "b", "severity": "warning"},
                           headers={"X-Internal-Token": "secret"})
    assert r.status_code == 200
    assert r.json()["channels"]["email"] == "sent"

def test_422_missing_fields():
    with patch("app.routers.alerts.settings") as s:
        s.INTERNAL_API_TOKEN = "secret"
        r = _client().post("/api/v1/alerts/system", json={"title": "t"},
                           headers={"X-Internal-Token": "secret"})
    assert r.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/routers/test_alerts_system.py -v`
Expected: FAIL (404 — endpoint missing, and/or 401 from AuthMiddleware because path not exempt)

- [ ] **Step 3: Add the middleware exemptions**

In `backend/app/main.py`, line 52:
```python
CSRF_EXEMPT_PREFIXES = ("/api/auth/", "/api/v1/alerts/infrastructure", "/api/v1/alerts/system")
```
And in `_base_exempt` (lines 280-286), add the path:
```python
    _base_exempt = (
        "/api/auth/",
        "/api/health",
        "/api/ready",
        "/metrics",
        "/api/v1/alerts/infrastructure",
        "/api/v1/alerts/system",
    )
```

- [ ] **Step 4: Add the endpoint**

In `backend/app/routers/alerts.py`, add imports near the top:
```python
from fastapi import Header
from app.core.config import settings
from app.services.system_notifier import notify_system
```
And add the endpoint (place after `receive_infrastructure_alert`):
```python
@router.post("/system", status_code=200)
def send_system_notification(
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    x_internal_token: str | None = Header(default=None, alias="X-Internal-Token"),
) -> Dict[str, Any]:
    """Generic system notification (email + browser push). Server-to-server only."""
    if not settings.INTERNAL_API_TOKEN:
        raise HTTPException(status_code=503, detail="system notifications disabled (INTERNAL_API_TOKEN unset)")
    if x_internal_token != settings.INTERNAL_API_TOKEN:
        raise HTTPException(status_code=401, detail="invalid internal token")
    title = payload.get("title")
    body = payload.get("body")
    if not title or not body:
        raise HTTPException(status_code=422, detail="title and body are required")
    channels = notify_system(
        title=title, body=body,
        severity=payload.get("severity", "info"),
        dedupe_key=payload.get("dedupe_key"),
        channels=payload.get("channels"),
        db=db,
    )
    return {"status": "dispatched", "channels": channels}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest backend/tests/routers/test_alerts_system.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Validate live (per project rule — curl the new endpoint)**

Confirm reload, set a token, and exercise it:
```bash
docker-compose logs backend --tail=10
docker exec stockscanner-api sh -c 'INTERNAL_API_TOKEN=test-token python - <<PY
# quick in-container check that the route exists and token logic works
PY'
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/api/v1/alerts/system \
  -H "Content-Type: application/json" -d '{"title":"t","body":"b"}'   # 503 if token unset
```
Expected: `503` when `INTERNAL_API_TOKEN` is unset (fail-closed), confirming the route is mounted and not behind JWT.

- [ ] **Step 7: Commit**
```bash
git add backend/app/routers/alerts.py backend/app/main.py backend/tests/routers/test_alerts_system.py
git commit -m "feat(api): POST /api/v1/alerts/system (token-guarded, middleware-exempt)"
```

---

## Self-Review

- **Spec coverage:** generic delivery (Task 2/3) ✓; endpoint + token auth + 503/401 (Task 4) ✓; optional empty-default config (Task 1) ✓; fail-soft + dedupe (Task 3) ✓; email reuse of `_send_email` ✓. Google-chat/webhook channels are out of scope (not needed by autopilot) — consistent with the spec's non-goals.
- **Placeholders:** none — every step has concrete code/commands.
- **Type consistency:** `_push_to_subscriptions(payload, db) -> int` used identically in Task 2 and Task 3; `notify_system(...)` signature matches between Task 3 definition and Task 4 call.
- **Note for executor:** run pytest via the project recipe (throwaway `TEST_DATABASE_URL` in `stockscanner-db`, `COVERAGE_FILE=/tmp/.coverage`, `--no-cov`) — see project memory "Backend local test recipe".
