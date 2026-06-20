# Strict Data Quality Gate for Automated Trading Design

**Date:** 2026-06-19 (revised 2026-06-20)
**Status:** Draft — pending review
**Issue:** #496 | **Parent Epic:** #491 (Data Quality Trust Gate)
**Blocked by:** #492 (gate contract + service), #494 (advisory scanner gate + scanner_run_id FK)

---

## Overview

Automated trading in MarketHawk creates bracket orders based on scanner events. Today, `AutoTradeExecutor.maybe_execute()` performs 11 guard checks — but none of them verify whether the scanner event's underlying data is trustworthy. An event generated from stale bars, incomplete coverage, or a split/dividend anomaly could trigger a real order at the wrong price.

This slice makes data quality a hard prerequisite for automated order creation. A scanner event must pass the strict quality gate before `maybe_execute()` is permitted to size and submit an order. If the gate says blocked, skipped (without bypass), or warning, the order is refused and the reason is logged.

---

## Requirements

1. **Gate check location:** Insert as a new guard between existing guard 2 (idempotency) and guard 3 (Redis lock) in `maybe_execute()` (`auto_trade_service.py:134–152`).

2. **Gate service call:** Call the quality gate service directly with `policy=QualityGatePolicy.strict` using the scanner event's universe context. Do not trust the pre-stamped `metadata_["quality_gate"]` blob from #494 (which was computed under advisory policy) — re-evaluate under strict policy to ensure blocked-severity issues are correctly escalated.

3. **Verdict handling (strict mode):**
   - `trusted` → proceed with order creation
   - `warning` → refuse order creation (block; log verdict + warning codes)
   - `blocked` → refuse order creation (block; log verdict + issue codes)
   - `skipped` → refuse by default; allow only if `QUALITY_GATE_SKIP_BYPASS` SystemConfig key is set to `"true"`

4. **Refusal recording:** Consistent with all 11 existing guards, use structured log only — no AutoTradeOrder row is written for a gate refusal. The log entry must include: verdict, issue codes (if any), warning codes (if any), ticker, rule_id, event_id, and `bypass_used` flag. Paper mode is NOT exempt from the gate.

5. **Safe bypass for `skipped`:** Read `SystemConfig` key `QUALITY_GATE_SKIP_BYPASS` using the same pattern as `AUTO_TRADING_ENABLED`. Default-absent / `"false"` means no bypass. Setting to `"true"` allows `skipped` events to proceed; the bypass is noted in the structured log.

6. **Rejection reason logging format:**
   ```
   quality_gate_refused: ticker={ticker} event={event_id} rule={rule_id}
   verdict={verdict} issues={issue_codes} warnings={warning_codes}
   bypass_used={bool}
   ```

7. **Gate failure (service unavailable):** If the gate service raises an exception, the guard must **fail-closed** — block the order and log the exception with the same structured pattern. An outage suppressing trades is loud and self-healing; fail-open would silently defeat the gate's purpose.

8. **Refusal-rate monitoring (acceptance criterion):** The implementation must log refusals at `WARNING` severity. A Seq alert (or equivalent) must be configured to fire when gate refusals exceed 5 per hour, enabling detection of misconfigured gates or silent mass-suppression. The specific Seq alert query is an implementation detail, but the requirement to emit a detectable signal on elevated refusal rates is normative.

9. **Universe resolution prerequisite:** `ScannerEvent` currently has no `scanner_run_id` FK. The #494 implementation must add a nullable `scanner_run_id` FK column to `scanner_events` before #496 can be implemented. The canonical universe resolution path for the gate is:
   ```
   event.scanner_run_id → ScannerRun.universe_id
   ```
   If `scanner_run_id` is null or `universe_id` is null, treat the gate result as `skipped` (distinct from a gate service error, which is fail-closed). This `skipped` result is bypassable via `QUALITY_GATE_SKIP_BYPASS`.

10. **Tests (required for all four verdicts plus bypass and failure mode):**
    - `trusted` → order created normally
    - `warning` → no order created
    - `blocked` → no order created
    - `skipped` without bypass → no order created
    - `skipped` with `QUALITY_GATE_SKIP_BYPASS="true"` → order created
    - Gate service raises exception → no order created (fail-closed)

---

## Architecture

### Integration point

```
maybe_execute(rule, event, db):
    # Guard 1: basic guards (rule.auto_trade, strategy active)
    # Guard 2: idempotency (one order per symbol/strategy/day)
    # ─── NEW ────────────────────────────────────────────────
    # Guard 2.5: quality gate (strict policy)
    try:
        universe_id = _resolve_universe_id(event, db)  # via scanner_run_id FK
        assessment = quality_gate_service.assess(
            universe_id=universe_id,
            event=event,
            policy=QualityGatePolicy.strict,
            db=db,
        )
    except Exception as exc:
        logger.warning(
            "quality_gate_service_error: ticker=%s event=%s rule=%s error=%s — failing closed",
            event.ticker, event.id, rule.id, exc
        )
        return None  # fail-closed

    if not _gate_passes(assessment, db):
        logger.warning("quality_gate_refused: ...")
        return None
    # ────────────────────────────────────────────────────────
    # Guard 3: Redis distributed lock
    ...
```

### Gate pass logic

```python
def _gate_passes(assessment: QualityGateAssessment, db: Session) -> bool:
    if assessment.verdict == "trusted":
        return True
    if assessment.verdict == "skipped":
        cfg = db.query(SystemConfig).filter(
            SystemConfig.key == "QUALITY_GATE_SKIP_BYPASS"
        ).first()
        return cfg and cfg.value.lower() == "true"
    # blocked or warning → always refuse
    return False
```

### Universe resolution

```python
def _resolve_universe_id(event: ScannerEvent, db: Session) -> Optional[int]:
    """
    Canonical path: event.scanner_run_id (nullable FK added by #494)
        → ScannerRun.universe_id
    Returns None if the run linkage is absent or the run has no universe.
    A None result causes the gate to return verdict='skipped'.
    """
    if not event.scanner_run_id:
        return None
    run = db.query(ScannerRun).filter(ScannerRun.id == event.scanner_run_id).first()
    return run.universe_id if run else None
```

**Why not fallback via scanner_type → ScannerConfig?** `ScannerConfig.scanner_type` is not unique — multiple configs can have the same scanner_type across different universes. Picking the lowest `id` (oldest) would silently route events to the wrong universe's quality verdict, which is a correctness landmine in a strict-blocker path. The `skipped` verdict with a bypass key is a safer and more honest signal.

### Failure Modes & Blast Radius

| Failure scenario | Behaviour | Justification |
|---|---|---|
| Gate service unavailable (#492 throws) | Fail-closed: block order, log exception | Outage suppresses trades loudly; fail-open silently defeats the gate |
| `scanner_run_id` null (pre-FK events, live-scanner alerts) | Treat as `skipped`; bypassable via `QUALITY_GATE_SKIP_BYPASS` | No universe context → gate cannot assess; skipped is the honest signal |
| `ScannerRun.universe_id` null | Treat as `skipped`; same bypass path | Same rationale |
| `QUALITY_GATE_SKIP_BYPASS` not set in SystemConfig | Skip bypass inactive (safe default) | Default must be secure |
| Elevated refusal rate (>5/hr) | Seq alert fires | Detects misconfigured gate or mass data-quality event |

**Blast radius:** Every automated order decision — live and paper — passes through `maybe_execute()`. This guard runs for every matched alert rule, every scanner type, every universe. A misconfigured gate that always returns `blocked` would suppress all auto-trades silently until the refusal-rate alert fires. The fail-closed choice on exception means a gate service outage also suppresses all trades. These are intentional conservative choices; the monitoring requirement (req. 8) is the mitigation.

### SystemConfig bypass (existing pattern)

```python
cfg = db.query(SystemConfig).filter(
    SystemConfig.key == "QUALITY_GATE_SKIP_BYPASS"
).first()
bypass_enabled = cfg and cfg.value.lower() == "true"
```

This matches the existing `AUTO_TRADING_ENABLED` kill-switch pattern at `auto_trade_service.py:120–132`.

---

## Alternatives Considered

### A: Read pre-stamped `event.metadata_["quality_gate"]` from advisory scanner (#494)

**Rejected.** The advisory scanner stamps events under `policy=advisory`. Under advisory policy, blocker-severity issues yield `verdict=warning` (not `blocked`). Trusting that blob for strict mode would allow events that should be blocked to proceed. Re-calling the gate service under `policy=strict` ensures correct verdict escalation.

### B: Per-strategy `quality_gate_policy` field on TradingStrategy

**Rejected for this milestone.** The bypass mechanism already scoped to `skipped` verdicts is the SystemConfig key. Adding a per-strategy quality policy field introduces schema migration, configuration surface, and scope not requested by issue #496. Auto-trading is strict, full stop.

### C: Write a rejected `AutoTradeOrder` row for gate refusals

**Rejected.** The `AutoTradeOrder` model documents itself as "the record created the moment the system decides to trade on an alert" — a gate refusal is the opposite of intent to trade. More concretely: the unique constraint `uq_auto_trade_symbol_strategy_date(symbol, trading_strategy_id, event_date)` means a gate-refusal row would block a subsequent legitimate order the same day if data quality recovers. All 11 existing guards use structured log + `return None`; the gate guard should be consistent.

### D: Fallback universe resolution via scanner_type → ScannerConfig (when scanner_run_id is null)

**Rejected.** `ScannerConfig.scanner_type` is not unique — multiple active configs may share the same scanner_type across different universes. Picking the oldest config by id silently routes events to the wrong universe's quality verdict. The `skipped` path is the honest and safe alternative.

---

## Assumptions

- **[ASSUMED]** Issue #492 (quality gate service) is merged before this slice starts. The gate service provides `quality_gate_service.assess(universe_id, event, policy, db)` returning a `QualityGateAssessment` with `.verdict` and optional `.issue_codes`/`.warning_codes`.
- **[ASSUMED]** Issue #494 (advisory scanner gate) adds a nullable `scanner_run_id` FK to `scanner_events` table as part of its implementation. Without this FK, universe resolution always returns `skipped` for all events — the gate functions as fail-safe but not as a true data quality gate. The spec requires this FK; if #494 defers it, a sub-task must cover it before #496 starts.
- **[ASSUMED]** `QUALITY_GATE_SKIP_BYPASS` defaults to absent (off). The key should never appear in production SystemConfig except during deliberate operational bypass.
- **[ASSUMED]** Paper-mode strategies are subject to the same gate enforcement as live strategies, since corrupted paper results invalidate strategy validation.

---

## Open Questions (non-blocking)

1. **Warning bypass in future:** If a future slice needs per-strategy warning tolerance (e.g. allow strategies with `paper_mode=True` to trade on certain warning codes), that should be a new `TradingStrategy.quality_gate_warning_policy` field with its own spec — not retrofitted into this slice.

2. **Gate refusal audit surface:** If product wants a queryable history of gate refusals (e.g. "how many orders were blocked by data quality last week?"), a dedicated `quality_gate_refusals` table is the correct design — not overloading `auto_trade_orders`. Deferred; structured logs are the foundation.

3. **Live-scanner events (no ScannerRun link):** Events written by `live_scanner/conditions.py` are written directly without going through `ScannerRun`. These will always have null `scanner_run_id` and therefore always receive `verdict=skipped`. If this is operationally significant, a future slice should give live-scanner events a universe context (perhaps via `MonitoredStock.universe_id`).
