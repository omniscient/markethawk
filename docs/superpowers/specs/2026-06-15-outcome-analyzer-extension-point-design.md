# Outcome Analyzer Extension Point Design

**Date:** 2026-06-15
**Issue:** #445
**Status:** Pending review

## Overview

The `OutcomeService` today is a fixed set of static methods for creating pending snapshots, capturing price data, and computing outcome summaries. This design adds a registry-based extension point that lets custom (private) modules replace or extend any of these three lifecycle stages for specific scanner types, while keeping the existing `OutcomeService` logic as the default path when no custom analyzer is configured.

No new database tables or columns are required. Analyzer selection is driven by the existing `ScannerConfig.outcome_config` JSONB and a scanner-type-keyed registry.

## Requirements

From the acceptance criteria in issue #445:

1. Outcome analyzers can be registered and resolved by scanner type or explicit analyzer key.
2. Existing `OutcomeService` behavior is the default when no custom analyzer is configured.
3. Analyzer configuration uses existing JSON surfaces (`outcome_config`, `data_requirements`) — no extension-owned migrations.
4. Analyzer failures produce structured `AnalyzerError` records without corrupting existing snapshot or summary rows.
5. Tests cover default analyzer compatibility and a dynamically registered private analyzer.

## Approach

### Three-method interface

The analyzer is a class with the same three lifecycle methods as `OutcomeService`:

```python
class OutcomeAnalyzerBase:
    def create_pending_snapshots(self, db: Session, event: ScannerEvent) -> list[ScannerOutcomeSnapshot]: ...
    def capture_snapshot(self, db: Session, snapshot: ScannerOutcomeSnapshot) -> None: ...
    def recompute_summary(self, db: Session, scanner_event_id: int) -> ScannerOutcomeSummary | None: ...
```

The three methods are a cohesive unit. `capture_snapshot` hardcodes the `interval_map` that must match the `intervals` defined by `create_pending_snapshots`; `recompute_summary` special-cases the `"eod"` interval key from those same snapshots. Splitting the interface at a finer granularity would lock custom analyzers into the default's fixed interval vocabulary — exactly what the extension point is meant to avoid.

`DefaultOutcomeAnalyzer` is a concrete subclass that delegates to the current `OutcomeService` static methods. It is registered as `"default"` at module import time.

### Two-tier registry

```
_KEY_REGISTRY: dict[str, type[OutcomeAnalyzerBase]]  # explicit analyzer-key bindings
_SCANNER_TYPE_REGISTRY: dict[str, type[OutcomeAnalyzerBase]]  # scanner-type bindings
```

Two separate dicts (not a shared namespace) prevent a scanner type named like an analyzer key from shadowing it. Duplicate registrations raise `AnalyzerError` unless `replace=True` is passed explicitly.

Registration API:

```python
def register(key: str, cls: type[OutcomeAnalyzerBase], *, replace: bool = False) -> None: ...
def register_for_scanner_type(scanner_type: str, cls: type[OutcomeAnalyzerBase], *, replace: bool = False) -> None: ...
```

Resolution order (highest to lowest priority):

1. `outcome_config["analyzer"]` explicit key → look up in `_KEY_REGISTRY`
2. `scanner_type` → look up in `_SCANNER_TYPE_REGISTRY`
3. Fall back to `_KEY_REGISTRY["default"]`

```python
def resolve_analyzer(scanner_type: str, outcome_config: dict | None) -> OutcomeAnalyzerBase:
    key = (outcome_config or {}).get("analyzer")
    if key:
        cls = _KEY_REGISTRY.get(key)
        if cls:
            return cls()
    cls = _SCANNER_TYPE_REGISTRY.get(scanner_type)
    if cls:
        return cls()
    return _KEY_REGISTRY["default"]()
```

This mirrors the `scan_orchestrator.py` pattern (`_REGISTRY` dict + `register()` + `get(scanner_type)`) already used for scanners.

### Structured error type

A new `AnalyzerError(MarketHawkError)` with `is_retryable=False` is added to `backend/app/exceptions.py`:

```python
class AnalyzerError(MarketHawkError):
    def __init__(self, *, analyzer_key: str, scanner_type: str, method: str, cause: Exception, **context):
        super().__init__(
            is_retryable=False,
            analyzer_key=analyzer_key,
            scanner_type=scanner_type,
            method=method,
            **context,
        )
        self.__cause__ = cause
```

`is_retryable=False` reflects that a broken custom analyzer is an extension defect, not a transient platform fault.

### Failure handling at call sites

Call sites in `outcomes.py` wrap each analyzer dispatch in a `try/except`:

```python
try:
    analyzer.create_pending_snapshots(db, event)
except Exception as exc:
    raise AnalyzerError(analyzer_key=key, scanner_type=event.scanner_type, method="create_pending_snapshots", cause=exc) from exc
```

The outer router handler catches `AnalyzerError`, logs it as a structured Seq event, and continues (skips outcome recording for that event). Existing snapshot or summary rows are not touched because each lifecycle method wraps its DB writes in `db.flush()` within the call — a failure before `flush()` has no visible side effects, and the outer `db.commit()` is only called after all events in the batch succeed.

**Important**: each lifecycle method call is individually guarded. If `capture_snapshot` fails for one snapshot, the other snapshots in the same batch are still processed.

### Files changed

| File | Change |
|------|--------|
| `backend/app/services/outcome_analyzer.py` | **New** — `OutcomeAnalyzerBase`, `DefaultOutcomeAnalyzer`, `_KEY_REGISTRY`, `_SCANNER_TYPE_REGISTRY`, `register`, `register_for_scanner_type`, `resolve_analyzer` |
| `backend/app/exceptions.py` | Add `AnalyzerError(MarketHawkError)` |
| `backend/app/routers/outcomes.py` | Replace 3 direct `OutcomeService.*` calls with `resolve_analyzer()` dispatch; wrap each in `try/except AnalyzerError` |
| `backend/tests/services/test_outcome_analyzer.py` | **New** — default compatibility tests + dynamic registration tests |

No model changes, no migrations.

## Alternatives Considered

### A: Per-method registration (fine-grained hooks)
Register `create_pending_snapshots`, `capture_snapshot`, and `recompute_summary` independently (`register_snapshot_factory(key, fn)` etc.). **Rejected**: the three methods are tightly coupled through the `interval_key` vocabulary — a custom `create_pending_snapshots` that adds a new interval key must be paired with a matching `capture_snapshot` that understands it. Splitting the interface makes it easy to register mismatched fragments, and testing requires combining fragments from different registries. The cohesive class interface is strictly safer.

### B: Wait for #439 shared primitives before defining the analyzer registry
Defer the entire registry design until #439 ships its `DescriptorRegistry` base class. **Rejected for the spec stage**: #439's shared primitives will be a drop-in replacement for the two dicts in `outcome_analyzer.py`. The interface (`register()`, `resolve_analyzer()`) is defined here and can be wired to #439 primitives by the implement agent when #439 is landed. This avoids coupling this issue's delivery timeline to #439's internals while remaining architecturally aligned.

### C: Fallback to default analyzer on failure
If a custom analyzer raises, silently fall back to `DefaultOutcomeAnalyzer` and log a warning. **Rejected**: a silently incorrect outcome (produced by the wrong analyzer) is harder to diagnose than a missing outcome. The acceptance criterion says "without corrupting existing … records" — producing unintended default outcomes violates the spirit of that requirement. Structured `AnalyzerError` + skip is the correct failure signal.

## Open Questions (non-blocking)

1. Should `register()` and `register_for_scanner_type()` accept an instance instead of a class? The class form is consistent with `scan_orchestrator.py` (resolves a fresh instance per dispatch); the instance form allows stateful analyzers. Class form is preferred for now.
2. When #439 lands its shared `DescriptorRegistry`, should `_KEY_REGISTRY` and `_SCANNER_TYPE_REGISTRY` be replaced in the same PR? Likely yes — the implement agent for this issue should note a TODO comment for the #439 integration.

## Assumptions

- `[ASSUMPTION]` The implementation agent will read issue #439 before implementing — the registry in `outcome_analyzer.py` should use two plain dicts initially, with a TODO comment pointing to the #439 shared primitives for future consolidation.
- `[ASSUMPTION]` Extension modules that register custom analyzers are imported via `MARKETHAWK_EXTENSION_MODULES` at backend startup per #438/#439; the analyzer registry is therefore populated before any request reaches the outcomes router.
- `[ASSUMPTION]` The three-method interface is sufficient for all v1 private analyzer use cases. If an analyzer needs additional context (e.g., raw bar data, external signals) it fetches it from the DB inside its own method body — no additional protocol surface is needed now.
- `[ASSUMPTION]` `DefaultOutcomeAnalyzer` is a thin wrapper; it does not copy-paste the OutcomeService implementation — it delegates to the existing static methods to keep a single source of truth.
