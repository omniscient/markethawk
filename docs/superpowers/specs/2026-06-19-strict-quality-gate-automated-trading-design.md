# Strict Data Quality Gate for Automated Trading Design

**Date:** 2026-06-19
**Status:** Draft — pending review
**Issue:** #496 | **Parent Epic:** #491 (Data Quality Trust Gate)
**Blocked by:** #492 (gate contract + service), #494 (advisory scanner gate)

---

## Overview

Automated trading in MarketHawk creates bracket orders based on scanner events. Today, `AutoTradeExecutor.maybe_execute()` performs 12 guard checks — but none of them verify whether the scanner event's underlying data is trustworthy. An event generated from stale bars, incomplete coverage, or a split/dividend anomaly could trigger a real order at the wrong price.

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

7. **Tests (required for all four verdicts):**
   - `trusted` → order created normally
   - `warning` → no order created
   - `blocked` → no order created
   - `skipped` without bypass → no order created
   - `skipped` with `QUALITY_GATE_SKIP_BYPASS="true"` → order created

---

## Architecture

### Integration point

```
maybe_execute(rule, event, db):
    # Guard 1: basic guards (rule.auto_trade, strategy active)
    # Guard 2: idempotency (one order per symbol/strategy/day)
    # ─── NEW ────────────────────────────────────────────────
    # Guard 2.5: quality gate (strict policy)
    assessment = quality_gate_service.assess(
        universe_id=...,         # from ScannerEvent → ScannerRun → ScannerConfig → universe_id
        event=event,
        policy=QualityGatePolicy.strict,
        db=db,
    )
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

The `maybe_execute()` method currently receives a `ScannerEvent` but does not directly hold `universe_id`. The event's universe context must be resolved before calling the gate. The canonical path is:

```
ScannerEvent → ScannerRun (via scanner_run_id FK, if present)
             → ScannerConfig.universe_id
```

If no run linkage is available (e.g. manually triggered alert), fall back to `ScannerConfig` matched by `scanner_type`. If still unresolvable, treat as `skipped`.

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

---

## Assumptions

- **[ASSUMED]** Issue #492 (quality gate service) and #494 (advisory scanner integration) are merged before this slice starts. The gate service provides a callable `quality_gate_service.assess(universe_id, event, policy, db)` returning a `QualityGateAssessment`.
- **[ASSUMED]** `ScannerEvent` has a linkage to `ScannerRun` (or equivalent) that exposes `universe_id`. If this FK does not exist at merge time, the universe resolution fallback (by scanner_type → ScannerConfig) must be implemented and tested.
- **[ASSUMED]** `QUALITY_GATE_SKIP_BYPASS` defaults to absent (off). The key should never appear in production SystemConfig except during deliberate operational bypass.
- **[ASSUMED]** Paper-mode strategies are subject to the same gate enforcement as live strategies, since corrupted paper results invalidate strategy validation.

---

## Open Questions (non-blocking)

1. **Warning bypass in future:** If a future slice needs per-strategy warning tolerance (e.g. allow strategies with `paper_mode=True` to trade on certain warning codes), that should be a new `TradingStrategy.quality_gate_warning_policy` field with its own spec — not retrofitted into this slice.

2. **Gate refusal audit surface:** If product wants a queryable history of gate refusals (e.g. "how many orders were blocked by data quality last week?"), a dedicated `quality_gate_refusals` table is the correct design — not overloading `auto_trade_orders`. Deferred; structured logs are the foundation.

3. **Universe resolution for alert-only events:** If scanner events from alert-only rules (no ScannerRun link) become common, the fallback resolution logic may need hardening or a direct `universe_id` FK on `ScannerEvent`.
