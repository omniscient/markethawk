# System Notifications Enabler — generic email/push for non-scanner events

**Status:** design
**Date:** 2026-06-20
**Epic:** #548 (Dark Factory platform — maintenance, telemetry)
**Consumed by:** Epic Autopilot (`2026-06-20-epic-autopilot-design.md`)

## Problem

MarketHawk already has multi-channel notification delivery — `NotificationDispatcher`
in `app/services/alert_service.py` sends **email** (SMTP via `smtplib`) and **browser
push** (VAPID via `pywebpush`), plus `google_chat` and `webhook`. But it is wired
**only** to the scanner path: `dispatch(rule: AlertRule, event: ScannerEvent, db)`.
The delivery helpers (`_send_email`, `_send_browser_push`) take a `ScannerEvent` and
build scanner-specific subject/body.

The one generic entry point, `POST /api/alerts/infrastructure`, merely **logs the
payload to Seq** (`receive_infrastructure_alert`) — it does not deliver anything.

So there is no way for the app — or an external component like the backlog scheduler —
to say "email/push me this system message." The Epic Autopilot feature needs exactly
that, and so will future system events (main-red, circuit-breaker trips, preview
failures).

## Decision

Add a small **generic system-notification path** that reuses the existing SMTP/VAPID
delivery, decoupled from `AlertRule`/`ScannerEvent`.

### Components

1. **Refactor delivery helpers to a generic core** (`app/services/alert_service.py`):
   - Extract `_send_email(to, subject, body)` and
     `_send_browser_push(title, body, url=None)` as generic functions.
   - The existing scanner-specific senders become thin wrappers that build the
     scanner subject/body, then call the generic core. No behavior change on the
     scanner path.

2. **`app/services/system_notifier.py`** — new module:
   ```python
   def notify_system(
       title: str,
       body: str,
       severity: str = "info",        # info | warning | critical
       dedupe_key: str | None = None,
       channels: list[str] | None = None,  # default: ["email", "browser_push"]
   ) -> dict:  # {channel: "sent"|"skipped"|"failed:<reason>"}
   ```
   - Email → `OPS_ALERT_EMAIL` (new optional Settings field). If unset: skip email,
     log a warning (never raise).
   - Browser push → all stored `PushSubscription` rows.
   - **Severity** prefixes the subject (`[WARNING] …`) and sets push urgency.
   - **Dedupe/throttle:** if `dedupe_key` is given, suppress re-sends of the same key
     within a short cooldown (default 60 min). `AlertDeliveryLog` is scanner-rule-scoped
     (`rule_id` FK) and is **not** reused directly; the store is decided in the plan —
     a small dedicated table or persisted state so the cooldown survives restarts
     (mirroring the `is_on_cooldown` *pattern*, not the table).
   - **Fail-soft:** each channel is attempted independently; a failure is logged to Seq
     and recorded in `AlertDeliveryLog`, never raised to the caller.

3. **`POST /api/alerts/system`** (in `app/routers/alerts.py`):
   - Body: `{title, body, severity?, dedupe_key?, channels?}` → calls `notify_system`
     → returns the per-channel delivery summary.
   - **Auth:** server-to-server only. Require a shared-secret header
     `X-Internal-Token` matching `INTERNAL_API_TOKEN` (new Settings field). Reject with
     401 if absent/mismatched. This avoids coupling to the evolving user-auth model
     (#373) while preventing an open spam endpoint. If `INTERNAL_API_TOKEN` is unset,
     the endpoint is disabled (503) — fail-closed.

### Config (new Settings fields)

| Field | Default | Purpose |
|---|---|---|
| `OPS_ALERT_EMAIL` | `""` (optional) | recipient for system emails; unset → email skipped |
| `INTERNAL_API_TOKEN` | `""` (required to enable the endpoint) | shared secret for `/api/alerts/system` |

`SMTP_*` and `VAPID_*` already exist. **Preview env contract:** these new fields are
optional/empty-default, so they do not break the smoke gate or preview boot
(cf. #190 / REDIS_PASSWORD lesson — no new *required-no-default* field).

## Non-goals

- Per-user notification routing or preferences (single ops recipient for now).
- Templated digests / batching.
- Retry queues or guaranteed delivery (fail-soft, best-effort).

## Validation

- **Unit tests** (mock `smtplib.SMTP` and `pywebpush`):
  - `notify_system` sends to email + push; returns per-channel summary.
  - `OPS_ALERT_EMAIL` unset → email skipped, push still attempted, no raise.
  - One channel failing does not prevent the other; both logged.
  - `dedupe_key` cooldown suppresses the second identical send.
- **Endpoint tests:** valid `X-Internal-Token` → 200 + summary; missing/wrong → 401;
  `INTERNAL_API_TOKEN` unset → 503.
- **Manual:** `curl -H "X-Internal-Token: $TOK" -d '{"title":"test","body":"hi","severity":"warning"}'
  http://localhost:8000/api/alerts/system` → email + browser push received.
- **Migration:** none (no schema change; `AlertDeliveryLog` reused).

## Accepted trade-offs

- Single ops recipient (`OPS_ALERT_EMAIL`) rather than per-user — simplest thing that
  serves the autopilot use case; multi-recipient routing can come later.
- Shared-secret auth rather than full JWT — appropriate for server-to-server and
  decoupled from the in-flight authz epic (#373).
