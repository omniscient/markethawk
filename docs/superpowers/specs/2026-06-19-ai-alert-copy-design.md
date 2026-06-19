# AI-Assisted Alert Copy from Signal Briefs — Design

**Date:** 2026-06-19
**Issue:** #475 (parent: #450)
**Blocked by:** #474 (narrative provenance and forbidden-claim enforcement)
**Status:** Pending review

---

## Overview

Scanner alert notifications currently use the deterministic `ScannerEvent.summary` field — a compact template-driven string produced at event write time by `event_helpers.py:SUMMARY_GENERATORS`. While reliable and fast, this copy is terse: it conveys the trigger condition but not why the signal matters, what risks apply, or what data-quality caveats the reader should understand.

This feature adds feature-flagged AI-assisted alert copy to the notification pipeline. When enabled and generation succeeds, all four notification channels (browser push, email, Google Chat, webhook) use richer 2-4 sentence copy grounded in the event's `ai_signal_brief` payload. When disabled or on any failure, behavior is identical to today — the deterministic `summary` is used and dispatch is unaffected.

This is Epic 3, issue 4 in the Scanner Explainability series (`docs/superpowers/specs/2026-06-13-scanner-explainability-design.md`).

---

## Requirements

1. **Feature-flagged** — alert copy generation is controlled by a settings flag (`LLM_ALERT_COPY_ENABLED`, default `False`). Dispatch always proceeds regardless of flag state.
2. **Content** — generated copy includes explanation (`brief.why`), risks (`brief.risks`), and data-quality caveats from the brief (`brief.data_quality_warnings`).
3. **Fallback is deterministic** — when the flag is off, the brief is absent, generation raises, or generation times out, `ai_alert_copy` stays `NULL` and all notification payloads fall back to `event.summary`.
4. **Never blocks dispatch** — a generation failure must never prevent a notification from going out. Dispatch timing must not regress.
5. **Forbidden claims enforced** — copy that contradicts `brief.forbidden_claims` is rejected before storage (from provenance infrastructure in #474).
6. **Tests cover**: flag enabled + success, flag disabled, generation failure (exception), forbidden-claim rejection, and dispatch fallback on NULL copy.

---

## Architecture

### 1. New column: `scanner_events.ai_alert_copy`

Add a nullable `Text` column to `ScannerEvent`:

```python
# backend/app/models/scanner_event.py
from sqlalchemy import Text

ai_alert_copy = Column(Text, nullable=True)
```

`Text` (unbounded) rather than `String(500)` because generated copy needs room to include caveats from `data_quality_warnings`.

Requires a new Alembic migration (autogenerate from the model change, apply with `alembic upgrade head`).

This column is:
- `NULL` when the flag is off, the brief is absent, or generation fails.
- Written only inside `_evaluate_scanner_alerts_logic` — never by `save_event()`.
- Read by all four `NotificationDispatcher` payload builders as `event.ai_alert_copy or event.summary`.

### 2. New service: `AlertCopyGenerator`

New file: `backend/app/services/alert_copy_generator.py`

```python
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.models.scanner_event import ScannerEvent

logger = logging.getLogger(__name__)

_MAX_COPY_CHARS = 500
_GENERATION_TIMEOUT_SECONDS = 8


class AlertCopyGenerator:
    """Generates notification-appropriate alert copy from a signal brief."""

    @staticmethod
    def generate(event: "ScannerEvent", llm_service) -> Optional[str]:
        """
        Return 2-4 sentence alert copy grounded in the event's ai_signal_brief,
        or None if the brief is absent, generation fails, or forbidden claims
        would be violated.
        """
        brief = (event.metadata_ or {}).get("ai_signal_brief")
        if not brief:
            return None

        why = brief.get("why", [])
        risks = brief.get("risks", [])
        warnings = brief.get("data_quality_warnings", [])
        forbidden = brief.get("forbidden_claims", [])

        # Fetch optional cached narrative for style guidance
        narrative: Optional[str] = None
        try:
            from app.services.narrative_service import NarrativeService
            narrative = NarrativeService.get_cached(event.id)
        except Exception:
            pass  # narrative is optional; never block on its absence

        prompt = _build_prompt(
            ticker=event.ticker,
            scanner_type=event.scanner_type,
            severity=event.severity,
            why=why,
            risks=risks,
            warnings=warnings,
            forbidden=forbidden,
            narrative=narrative,
        )

        try:
            copy = llm_service.generate_text(
                prompt=prompt,
                max_tokens=200,
                timeout=_GENERATION_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            logger.warning("AlertCopyGenerator: LLM call failed: %s", exc)
            return None

        if not copy or not isinstance(copy, str):
            return None

        copy = copy.strip()[:_MAX_COPY_CHARS]

        # Forbidden-claim enforcement (from #474 provenance infrastructure)
        try:
            from app.services.provenance_service import ProvenanceService
            if ProvenanceService.violates_forbidden_claims(copy, forbidden):
                logger.warning(
                    "AlertCopyGenerator: generated copy violates forbidden claims "
                    "for event %s — discarding", event.id
                )
                return None
        except Exception as exc:
            logger.warning(
                "AlertCopyGenerator: provenance check failed for event %s: %s — discarding",
                event.id, exc,
            )
            return None

        return copy


def _build_prompt(
    ticker: str,
    scanner_type: str,
    severity: str,
    why: list,
    risks: list,
    warnings: list,
    forbidden: list,
    narrative: Optional[str],
) -> str:
    scanner_display = scanner_type.replace("_", " ").title()
    why_lines = "\n".join(f"- {w}" for w in why) if why else "(none)"
    risk_lines = "\n".join(f"- {r}" for r in risks) if risks else "(none)"
    warn_lines = (
        "\n".join(f"- {w}" for w in warnings) if warnings else "(none)"
    )
    forbidden_lines = (
        "\n".join(f"- {f}" for f in forbidden) if forbidden else "(none)"
    )

    narrative_section = (
        f"\n\nContext narrative (for style/tone only — do not add claims not in Facts above):\n{narrative}"
        if narrative
        else ""
    )

    return f"""You are writing a short notification for a stock scanner alert. Write 2-4 sentences of compact, factual alert copy for a trader.

Signal:
- Ticker: {ticker}
- Scanner: {scanner_display}
- Severity: {severity}

Facts (use these as the basis for your copy):
Why it fired:
{why_lines}

Risks:
{risk_lines}

Data quality caveats (include if any are listed):
{warn_lines}

Do NOT state or imply any of the following:
{forbidden_lines}{narrative_section}

Instructions:
- Target length: 2-4 sentences, under 500 characters total.
- Include at least one risk or caveat if provided.
- Be factual and grounded — cite the facts above, do not invent.
- Do not use marketing language. Do not make price predictions.
- Output only the alert copy text. No preamble, no headers."""
```

### 3. Integration: `_evaluate_scanner_alerts_logic`

In `backend/app/tasks/scanning.py`, add a copy-generation block at the top of `_evaluate_scanner_alerts_logic`, after the event load, before `get_matching_rules`:

```python
def _evaluate_scanner_alerts_logic(scanner_event_id: int, db: Session) -> None:
    from app.models.scanner_event import ScannerEvent
    from app.services.alert_service import AlertRuleService, NotificationDispatcher

    event = db.query(ScannerEvent).filter(ScannerEvent.id == scanner_event_id).first()
    if not event:
        logger.warning(...)
        return

    # ── AI alert copy (never blocks dispatch) ─────────────────────────────
    if getattr(settings, "LLM_ALERT_COPY_ENABLED", False):
        try:
            from app.services.alert_copy_generator import AlertCopyGenerator
            from app.services.llm_service import get_llm_service
            copy = AlertCopyGenerator.generate(event, get_llm_service())
            if copy:
                event.ai_alert_copy = copy
                db.flush()
        except Exception:
            logger.warning(
                "evaluate_scanner_alerts: copy generation failed for event %s",
                scanner_event_id,
            )
    # ── end copy generation ────────────────────────────────────────────────

    matching_rules = AlertRuleService.get_matching_rules(event, db)
    ...
```

The try/except is **local** — it does not propagate to the task's outer retry handler. If the LLM raises or times out, `ai_alert_copy` stays `NULL`, the warning is logged to Seq, and dispatch proceeds normally.

### 4. `NotificationDispatcher` updates

Each of the four payload builders adopts the fallback pattern. One representative change:

```python
# _build_push_payload — before:
"body": event.summary or f"{scanner_type_display} detected on {event.ticker}",

# after:
"body": event.ai_alert_copy or event.summary or f"{scanner_type_display} detected on {event.ticker}",
```

The same one-line change applies to `_build_email_body`, `_build_chat_message`, and `_build_webhook_payload`.

### 5. Feature flag

Add to `backend/app/core/config.py`:

```python
LLM_ALERT_COPY_ENABLED: bool = False
```

Defaults off. Opt-in by setting `LLM_ALERT_COPY_ENABLED=true` in `.env`. Part of the broader LLM flag infrastructure from issue #472; coordinate naming convention with that issue.

---

## Approaches Considered

### Approach A (chosen): generate inside `_evaluate_scanner_alerts_logic`

Copy is ready before `NotificationDispatcher` runs. Generation failure is locally caught and never propagates to the task retry path. No new Celery task or task chain needed. Mirrors the existing defensive `try/except` pattern for regime lookup in `save_event()`.

### Approach B: separate `generate_alert_copy` Celery task

Cleanest separation of concerns, but introduces a near-guaranteed race: `evaluate_scanner_alerts` dispatches almost immediately while the copy task is executing a 2-5s LLM call. Notifications would nearly always use deterministic copy, meaning AI copy effectively never appears in live alerts. **Rejected.**

### Approach C: inline in `save_event()`

Copy would always be ready before dispatch, but `save_event()` is on the scanner hot path (called once per detected event inside the scan loop). Adding 2-5s of synchronous LLM latency per event write would serialize the entire scan behind LLM calls. **Rejected.**

### Approach D: per-channel structured JSONB

More tailored per channel but exceeds `size: M` scope, requires N LLM calls or complex structured output, and the existing `summary` precedent proves a single string works across all channels. **Rejected.**

---

## Data Model Change

```sql
-- New migration
ALTER TABLE scanner_events ADD COLUMN ai_alert_copy TEXT;
```

No index needed — `ai_alert_copy` is not queried or filtered, only read per row.

---

## Assumptions

1. **`ai_signal_brief` availability** — the brief JSONB is stored inside `event.metadata_["ai_signal_brief"]` (from Epic 2 issues). If the key is absent, `AlertCopyGenerator.generate()` returns `None` immediately and dispatch falls back to `event.summary`. The column must be present on the event by the time `_evaluate_scanner_alerts_logic` runs; this is guaranteed if Epic 2 work is complete for the scanner type. For scanner types that haven't been migrated to produce briefs, generation is silently skipped.

2. **`LLMService` interface** — issue #472 defines the LLM provider infrastructure. This spec assumes `llm_service.generate_text(prompt, max_tokens, timeout)` returns a string or raises. The exact interface is owned by #472.

3. **`ProvenanceService` interface** — issue #474 defines forbidden-claim enforcement. This spec assumes `ProvenanceService.violates_forbidden_claims(text, forbidden_claims)` returns `bool`. If #474's service is not yet available, the `AlertCopyGenerator` degrades gracefully (forbidden-claim check block catches `ImportError` and discards the copy as a safe default).

4. **`NarrativeService.get_cached(event_id)`** — issue #473 defines narrative generation and caching. The call is wrapped in a bare `except Exception: pass` so its absence never blocks copy generation.

---

## Open Questions (non-blocking)

1. **Copy length vs. push notification limits**: Browser push bodies are typically truncated at ~150 chars by the OS/browser. The spec targets 500-char max and lets the OS truncate for push. A future enhancement could add a dedicated shorter push-body format, but this is out of scope for `size: M`.

2. **Retry on LLM failure**: The spec produces `NULL` on any failure — no retries. If a given event fires an alert within the cooldown window again (unusual), the next dispatch attempt will re-run generation. This avoids compounding latency for the common failure case.

3. **Observability**: The warning log goes to Seq but there is no Prometheus counter for copy generation attempts/failures. A `llm_copy_generated_total` counter (labels: `scanner_type`, `status`) could be added alongside the implementation if observability is a priority.
