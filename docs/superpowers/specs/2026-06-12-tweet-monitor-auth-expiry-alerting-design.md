# Tweet-Monitor Cookie Auth Expiry Alerting — Design (issue #290)

**Date**: 2026-06-12
**Issue**: [#290](https://github.com/omniscient/markethawk/issues/290) — Tweet-monitor cookie auth: expiry alerting or official API
**Scope**: Expiry monitoring only (option 1, confirmed by user comment).

## Problem

The `tweet-monitor` service authenticates to X.com using two session cookies
(`X_AUTH_TOKEN` / `X_CSRF_TOKEN`) stored as env vars. They expire roughly every
30 days. When they expire, `XProfileScraper.scrape()` swallows the failure
(broad `except Exception → return []`) and the pipeline silently stops producing
signals. There is no alert, no Prometheus gauge, and no rotation reminder.

Two additional issues compound the problem:

- `health.py` line 22 and `browser.py:is_auth_expired()` both detect auth
  expiry by checking whether the env vars are set — a static config check, not a
  runtime detection. An expired (but set) cookie always reports `auth_expired:
  false`.
- The scraper does not distinguish "auth expired" from "no new tweets" or
  "transient Playwright failure."

## Requirements

1. **Auth failure detection**: the scraper detects when X.com redirects to the
   login page and raises a typed `AuthExpiredError` (not swallowed into `[]`).
2. **Prometheus gauge**: `tweet_monitor_auth_ok` gauge (`1` = healthy, `0` =
   auth expired/failed) exposed on the tweet-monitor's own `/metrics` endpoint.
3. **Prometheus scrape**: Prometheus configured to scrape the tweet-monitor.
4. **Grafana alert rule**: fires when `tweet_monitor_auth_ok == 0` for ≥ 2
   minutes, consistent with the IBKR-disconnect alert pattern.
5. **Fix stale auth checks**: replace the env-var-only checks in `health.py` and
   `browser.py` with runtime state so `/health` reflects actual auth status.
6. **Rotation docs**: `DEVELOPMENT.md` gains a "X.com Cookie Rotation" section
   with the rotation procedure and expected alert signature.

## Approach

### Detection (scraper.py)

Insert a login-redirect check immediately after `page.goto()`, before the
expensive `wait_for_selector` call:

```python
class AuthExpiredError(Exception):
    """Raised when X.com redirects to the login flow (cookie expired)."""

class XProfileScraper:
    async def scrape(self, handle, since_tweet_id=None):
        page = None
        try:
            page = await browser_manager.new_page()
            url = _PROFILE_URL.format(handle=handle)
            await page.goto(url, timeout=_LOAD_TIMEOUT_MS, wait_until="domcontentloaded")

            # Auth check before the expensive tweet-selector wait
            if "/i/flow/login" in page.url:
                raise AuthExpiredError(f"X.com redirected to login for @{handle}")

            await page.wait_for_selector(_TWEET_ARTICLE, timeout=_LOAD_TIMEOUT_MS)
            raw = await self._extract_tweets(page)
        except AuthExpiredError:
            raise                      # propagate — do NOT swallow
        except Exception as exc:
            logger.error(f"Scrape failed for @{handle}: {exc}")
            return []
        finally:
            if page:
                await page.close()
        ...
```

`AuthExpiredError` re-raises so it propagates through `_poll_account()` up to
`poll_all()`. All other exceptions continue to be swallowed into `[]`.

The URL pattern `/i/flow/login` is the X.com hard-redirect destination for
unauthenticated requests to protected content. This is server-side, not a
client-rendered overlay, so `page.url` is settled before the check runs. The
Grafana rule uses a `for: 2m` window to absorb any transient one-off login
challenges.

### Global auth state (main.py)

`poll_all()` tracks whether any account returned `AuthExpiredError` this cycle:

```python
_auth_ok = True   # module-level flag; False = auth failure detected this cycle

@app.post("/poll")
async def poll_all():
    global _auth_ok
    _auth_ok = True          # optimistic start; flipped below on any AuthExpiredError
    ...
    for account in accounts:
        try:
            promoted = await _poll_account(account, summary)
            ...
        except AuthExpiredError as exc:
            _auth_ok = False
            logger.error(f"Auth expired for @{account.handle}: {exc}")
            errors.append(str(exc))
        except Exception as exc:
            ...

    TWEET_MONITOR_AUTH_OK.set(1 if _auth_ok else 0)
    ...
```

### Prometheus gauge (main.py)

```python
from prometheus_client import Gauge, make_asgi_app

TWEET_MONITOR_AUTH_OK = Gauge(
    "tweet_monitor_auth_ok",
    "1 = X.com cookie auth healthy, 0 = auth expired or login redirect detected",
)
TWEET_MONITOR_AUTH_OK.set(1)   # assume healthy at startup

# Mount metrics endpoint
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)
```

Add `prometheus_client` to `services/tweet-monitor/requirements.txt`.

### Fix stale health check (app/state.py + health.py)

`main.py` already imports `check_health` from `health.py`, so `health.py`
cannot import from `main.py` — circular. Introduce a thin `app/state.py`
module as the shared mutable state carrier:

```python
# services/tweet-monitor/app/state.py  (new file, ~3 lines)
auth_ok: bool = True   # True = healthy; False = login redirect detected
```

`main.py` sets `state.auth_ok` on each poll cycle:

```python
import app.state as state
...
state.auth_ok = True   # reset optimistic
...
except AuthExpiredError:
    state.auth_ok = False
...
TWEET_MONITOR_AUTH_OK.set(1 if state.auth_ok else 0)
```

`health.py` reads from `state`, eliminating the static env-var check:

```python
import app.state as state
# Replace:  auth_expired = not settings.x_auth_token or not settings.x_csrf_token
auth_expired = not state.auth_ok
```

`browser.py:is_auth_expired()` returns `not settings.x_auth_token` (dead code —
misleadingly docstringed as "Detect if X returned a login redirect"). Remove it;
callers should use the gauge or `/health` `auth_expired` field instead.

### Prometheus scrape (monitoring/prometheus/prometheus.yml)

Add a new scrape job:

```yaml
  - job_name: tweet_monitor
    static_configs:
      - targets: ["tweet-monitor:8000"]
    metrics_path: /metrics
```

The port `8000` is the internal container port used by Celery beat
(`http://tweet-monitor:8000/poll`). Port 8001 in ARCHITECTURE.md is the
host-mapped port; the Prometheus scrape target uses the container-network
address.

### Grafana alert rule (grafana/provisioning/alerting/rules.yaml)

Add to the `markethawk-infrastructure` group, following the `ibkr-disconnected`
pattern exactly:

```yaml
      - uid: tweet-monitor-auth-expired
        title: Tweet-Monitor Auth Expired
        condition: C
        for: 2m
        annotations:
          summary: >
            Tweet-monitor X.com cookie auth has been failing for 2+ minutes.
            Rotate X_AUTH_TOKEN and X_CSRF_TOKEN in .env and restart tweet-monitor.
        labels:
          severity: warning
        data:
          - refId: B
            relativeTimeRange:
              from: 300
              to: 0
            datasourceUid: prometheus
            model:
              expr: tweet_monitor_auth_ok
              refId: B
          - refId: C
            relativeTimeRange:
              from: 300
              to: 0
            datasourceUid: "-- Grafana --"
            model:
              type: math
              expression: $B < 1
```

The alert routes to `markethawk-webhook` via the existing default notification
policy, which POSTs to `backend:8000/api/alerts/infrastructure` and is logged in
Seq. The Grafana dashboard (`Infrastructure` panel) shows it as a firing alert.

**Note**: the alert is visible in the Grafana dashboard and Seq. If operator
needs email/push delivery, add a second Grafana contact point in
`contact-points.yaml` and extend `notification-policies.yaml` — that is not in
scope for this issue but is straightforward.

### DEVELOPMENT.md addition

Add a "Tweet-Monitor: X.com Cookie Rotation" section documenting:
- What expires and why (~30-day lifetime)
- How to detect the alert (`tweet_monitor_auth_ok` in Grafana, Seq error logs)
- How to rotate: extract fresh cookies from browser dev tools, update `.env`,
  restart tweet-monitor container
- Expected alert resolution: gauge returns to 1 on the next poll cycle after
  restart

## Files changed

| File | Change |
|------|--------|
| `services/tweet-monitor/app/scraper.py` | Add `AuthExpiredError`; URL check after `goto()`; re-raise instead of swallow |
| `services/tweet-monitor/app/main.py` | Catch `AuthExpiredError` in `poll_all()`; add `TWEET_MONITOR_AUTH_OK` gauge; mount `/metrics` |
| `services/tweet-monitor/app/state.py` | New file — shared mutable `auth_ok` bool (avoids circular import between main.py and health.py) |
| `services/tweet-monitor/app/health.py` | Replace static env-var `auth_expired` with `state.auth_ok` |
| `services/tweet-monitor/app/browser.py` | Remove stale `is_auth_expired()` method |
| `services/tweet-monitor/requirements.txt` | Add `prometheus_client` |
| `monitoring/prometheus/prometheus.yml` | Add `tweet_monitor` scrape job |
| `grafana/provisioning/alerting/rules.yaml` | Add `tweet-monitor-auth-expired` rule |
| `DEVELOPMENT.md` | Add cookie rotation procedure section |

## Alternatives considered

### Option B: Backend-side gauge via Celery task health check
The `trigger_tweet_monitor` Celery task could check `/health` and set a backend
Prometheus gauge. Rejected: the metric's source of truth (the actual redirect
event) is in the tweet-monitor; inferring it via a round-trip health check
coupling diverges the metric from its event, and the backend gauge would only
update at Celery-beat cadence (45s) with no clean way to distinguish
"tweet-monitor down" from "auth expired."

### Option C: Direct webhook from tweet-monitor (`TWEET_MONITOR_ALERT_WEBHOOK_URL`)
A direct webhook from tweet-monitor (separate from Grafana) would work but
creates a parallel alert path independent of the gauge — the dashboard and the
alert could disagree. Grafana already watches all other infra signals; keeping
tweet-monitor auth in the same system is the more maintainable path.

### Option D (scraper): DOM-based login form detection
Checking `page.query_selector('[data-testid="loginForm"]')` after navigation.
Rejected: requires the full login page DOM to render before detecting failure
(eating the 15s `wait_for_selector` timeout), whereas the URL check is
instantaneous after `page.goto()` settles. The URL pattern is also more stable
than `data-testid` attributes on the login form.

## Open questions

- If the operator does not monitor Grafana, the alert is invisible. Add a
  Grafana email or Google Chat contact point if human delivery is needed. The
  spec does not provision one since no contact-point credentials are in the
  codebase defaults.

## Assumptions

- X.com responds to expired-cookie requests with a server-side redirect to
  `/i/flow/login` (not a client-rendered login overlay). This is consistent with
  the existing cookie-injection approach (`BrowserManager._inject_cookies`) where
  a fully expired server-side session token triggers an HTTP-level redirect before
  JS renders. The Grafana `for: 2m` window absorbs any edge cases where X.com
  uses a one-off challenge URL that happens to contain "login".
- The tweet-monitor internal port for container-network communication is `8000`
  (per `trigger_tweet_monitor` task target). If docker-compose maps a different
  internal port, the prometheus scrape target must be updated to match.
- `prometheus_client` version pinned to match the backend's version (currently
  unpinned in tweet-monitor — add a compatible version, e.g. `prometheus_client>=0.17`).
