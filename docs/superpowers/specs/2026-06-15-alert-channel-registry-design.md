# Alert Channel Registry Design

**Issue:** #442  
**Date:** 2026-06-15  
**Status:** Pending review  
**Epic:** #438 — Formal module extension points for MarketHawk  
**Blocked by:** #439 — Add extension loader and shared registry primitives

---

## Overview

`NotificationDispatcher.dispatch()` in `backend/app/services/alert_service.py` dispatches
alert notifications using a hardcoded `if/elif` block over four channel names. Every new
delivery channel — whether built-in or from a private extension module — requires editing
this block.

This spec converts the four built-in channels (browser push, email, Google Chat, webhook)
into registered handler functions and replaces the `if/elif` with a registry lookup, making
alert channels a proper extension point consistent with the extension system introduced in
#438/#439.

---

## Requirements

Derived from issue #442 acceptance criteria and the Q&A:

1. **Stable handler contract** — Each channel handler is a callable with signature
   `(event: ScannerEvent, rule: AlertRule, db: Session) -> None`. Handlers raise on
   failure; they do not write `AlertDeliveryLog` rows directly.

2. **Registry dispatch** — `NotificationDispatcher.dispatch()` resolves each channel name
   via the registry. The `if/elif` block is removed.

3. **Built-in behavior preserved** — All four built-in channels (browser_push, email,
   google_chat, webhook) keep identical delivery behavior and logging semantics.

4. **Unknown channel handling** — Channels not found in the registry are skipped with a
   `logger.warning(...)` and `continue`, identical to the current `else` branch. No
   `AlertDeliveryLog` row is written for an unrecognised channel name (the `continue`
   bypasses the log write, same as today).

5. **Private channel support** — A private extension module can call `register_channel()`
   at import time to add a new delivery channel without modifying `alert_service.py`.

6. **Schema relaxation** — `ChannelConfig` in `backend/app/schemas/alerts.py` is changed
   from `extra="forbid"` to `extra="allow"` so `AlertRule` creation/update requests that
   include private-channel config keys are not rejected with 422.

7. **Test coverage** — Tests cover: each built-in channel dispatch (success path via
   mocked send functions), a dynamically registered private channel dispatched end-to-end,
   and the unknown-channel skip path.

---

## Approach

### New module: `backend/app/services/alert_channels.py`

Following the pattern of `scan_orchestrator.py` (which holds the scanner `_REGISTRY`,
`ScannerDescriptor`, and `register()`), this module owns all alert channel infrastructure:

```python
# Type alias for the handler contract
AlertChannelFn = Callable[[ScannerEvent, AlertRule, Session], None]

# Module-level registry — populated at import time by registration calls below
_REGISTRY: dict[str, AlertChannelFn] = {}


def register_channel(name: str, handler: AlertChannelFn) -> None:
    """Register a channel handler. Raises on duplicate name."""
    if name in _REGISTRY:
        raise ValueError(f"Alert channel already registered: {name!r}")
    _REGISTRY[name] = handler


def get_channel(name: str) -> AlertChannelFn | None:
    return _REGISTRY.get(name)
```

The four built-in handler functions (`_browser_push_handler`, `_email_handler`,
`_google_chat_handler`, `_webhook_handler`) replace the four `elif` branches.  
Each handler wraps the existing `_send_*` and `_build_*` private methods, which are
relocated from `NotificationDispatcher` to this module.

Registration calls at module bottom:

```python
register_channel("browser_push", _browser_push_handler)
register_channel("email",        _email_handler)
register_channel("google_chat",  _google_chat_handler)
register_channel("webhook",      _webhook_handler)
```

Import of `alert_channels` from `alert_service` triggers registration at startup,
matching the self-registration pattern used by scanner modules.

### Changes to `NotificationDispatcher.dispatch()`

Before (sketch):
```python
if channel == "browser_push":
    ...
elif channel == "email":
    ...
elif channel == "google_chat":
    ...
elif channel == "webhook":
    ...
else:
    logger.warning(f"Unknown alert channel '{channel}' on rule {rule.id}")
    continue
```

After:
```python
from app.services import alert_channels  # triggers built-in registration

handler = alert_channels.get_channel(channel)
if handler is None:
    logger.warning(f"Unknown alert channel '{channel}' on rule {rule.id}")
    continue
handler(event, rule, db)
```

All surrounding exception handling, logging, and `AlertDeliveryLog` writes remain exactly
as they are today — only the dispatch line changes.

### `NotificationDispatcher` cleanup

- Remove `_send_browser_push`, `_send_email`, `_send_google_chat`, `_send_webhook`,
  `_build_push_payload`, `_build_email_body`, `_build_chat_message`,
  `_build_webhook_payload` — all move to `alert_channels.py`.
- `dispatch()` and `_validate_jsonb_dict` / `save_event` / `trigger_scanner_alert` remain
  in `alert_service.py`.

### Schema change

`backend/app/schemas/alerts.py`:

```python
class ChannelConfig(BaseModel):
    model_config = {"extra": "allow"}   # was "forbid"

    email: Optional[EmailStr] = None
    google_chat_webhook: Optional[HttpUrl] = None
    webhook_url: Optional[HttpUrl] = None
```

Built-in field format validation (EmailStr, HttpUrl) is preserved. Per-channel config
validation owned by each handler is deferred to the #439 follow-up.

---

## Alternatives Considered

### Alt A: Keep everything in `alert_service.py` (no new module)

A `_CHANNEL_REGISTRY` dict in `alert_service.py` avoids a new file. Rejected because it
mixes registry infrastructure with `AlertRuleService`, `save_event`, and
`NotificationDispatcher` concerns in an already-substantial module, and it diverges from
the `scan_orchestrator.py` pattern that the rest of the extension system will follow.

### Alt B: Class-based `AlertChannelHandler` protocol

Each channel implemented as a class with a `send(self, event, rule, db) -> None` method
rather than a plain callable. More extensible if handlers need state or metadata (e.g., a
`display_name` for a future UI listing registered channels). Rejected for this ticket
because M-sized scope doesn't justify the extra boilerplate and there's no UI listing
requirement. Can be introduced later as a wrapper around the callable contract.

### Alt C: Defer schema change; gate private channels on a feature flag

Skip the `ChannelConfig` relaxation and require private channel config to use a separate
top-level JSONB field on the rule. Rejected because it adds a data model change and the
`extra="allow"` relaxation is a one-line, non-breaking change that unblocks the private
channel test case required by AC#5.

---

## Assumptions

- `[ASSUMPTION]` #439's shared registry primitives are not yet available in this branch.
  `alert_channels.py` implements a minimal local dict-based registry. When #439 merges,
  migration to the shared `ExtensionRegistry` base class is a non-breaking internal change.

- `[ASSUMPTION]` The `ChannelConfig` `extra="allow"` change means misspelled built-in
  keys (e.g. `webhook_ur`) silently pass API validation. This is an accepted trade-off for
  M-sized scope; per-handler validation (reclaiming that strictness) is the #439 follow-up.

- `[ASSUMPTION]` `AlertRule.channels` continues to store plain string channel names. No
  data migration or model change is needed.

- `[ASSUMPTION]` Private extension modules call `register_channel()` once, at import time,
  via `MARKETHAWK_EXTENSION_MODULES`. Duplicate registration raises `ValueError` at startup
  (fast-fail), consistent with #439's "reject duplicate keys" AC.

---

## Open Questions (non-blocking)

1. **Read-only rule protocol** — The handler signature passes the full `AlertRule` ORM
   object. If #439 establishes a read-only rule protocol/dataclass (reducing the surface
   extension authors depend on), the callable signature can be narrowed to
   `(event, rule_view, db) -> None` in a later ticket. The transition is type-only and
   non-breaking if the view exposes `id`, `name`, and `channel_config`.

2. **Channel metadata** — No `display_name` or `description` is stored alongside the
   handler for now. If a future UI lists registered channels, a descriptor wrapper (Alt B
   above) would be the natural upgrade path.

3. **`browser_push` handler and DB side-effects** — The handler deletes expired
   `PushSubscription` rows (410/404 responses). This DB write happens inside the handler
   before `dispatch()` calls `db.commit()`. Behavior is unchanged from today but worth
   noting: the handler's side-effect writes are flushed by the dispatcher's commit, not
   the handler itself.

---

## Files Changed

| File | Change |
|------|--------|
| `backend/app/services/alert_channels.py` | **NEW** — registry, type alias, built-in handlers, builder helpers, registration calls |
| `backend/app/services/alert_service.py` | **MODIFY** — remove `_send_*` / `_build_*` from `NotificationDispatcher`; replace `if/elif` with registry lookup + import |
| `backend/app/schemas/alerts.py` | **MODIFY** — `extra="allow"` on `ChannelConfig` |
| `backend/tests/services/test_alert_service.py` | **MODIFY** — add dispatch tests via registry; private channel test |
| `backend/tests/services/test_alert_channels.py` | **NEW** (optional split) — unit tests for `register_channel`, `get_channel`, built-in handler send paths |
