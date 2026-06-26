# QualityGatePolicy Interface — Decouple Gate Consumers from Concrete Service

**Status:** design
**Date:** 2026-06-26
**Issue:** #633 (architecture-audit-v4 — Low-Medium, §3.4 coupling)

## Problem

Adding a new quality-gate evidence type today requires touching three modules:

1. `services/quality_gate_evidence.py` — add the batch evidence generator
2. `services/quality_gate.py` — wire the new evidence check into `_build_assessment`
3. `services/auto_trade_service.py` — the comment in R04-v4 flags line 41 as the hard-coupling point

The third touch is the architectural smell: `auto_trade_service.py` imports the concrete
`QualityGateService` class. When evidence semantics change — or the service is split — the
consumer must be edited even though it never looks inside the evidence. Two other modules
share the same concrete-import coupling:

| Consumer | Import line | Call site |
|---|---|---|
| `services/auto_trade_service.py` | line 41 | `AutoTradeExecutor.maybe_execute` line 189 |
| `tasks/scanning.py` | line 16 | `run_universe_scan` line 312 |
| `routers/data_quality.py` | line 18 | `preflight_gate` line 33 |

All three call the same signature: `QualityGateService.assess(db, request) -> QualityGateAssessment`.

## Goal

Consumers depend on a structural interface, not the concrete `QualityGateService`. Once
migrated, adding a new evidence type requires editing only `quality_gate.py` and
`quality_gate_evidence.py` — no consumer edit needed.

## Requirements

1. Define a `QualityGateServiceProtocol` (`typing.Protocol`) in `schemas/quality_gate.py`
   with a single method: `assess(self, db: Session, request: Any) -> QualityGateAssessment`.
2. Convert `QualityGateService.assess` from `@staticmethod` to a regular instance method
   (zero logic change — the method has no state and already works as an instance method).
3. Export a module-level singleton `quality_gate_service: QualityGateServiceProtocol`
   from `services/quality_gate.py` so consumers have a single stable import target.
4. Migrate all three consumers to import `quality_gate_service` (the singleton) rather
   than `QualityGateService` (the class), and call `quality_gate_service.assess(db, req)`.
5. `QualityGateService` satisfies `QualityGateServiceProtocol` **structurally** — no
   explicit `class QualityGateService(QualityGateServiceProtocol)` inheritance required.
6. Existing tests must continue to pass without modification.
7. Do NOT change the internal evidence logic in `_build_assessment` — that is out of scope
   (see §Open Questions — follow-on issue for evidence-generator registry).

## Architecture

### New Protocol in `schemas/quality_gate.py`

```python
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable
if TYPE_CHECKING:
    from sqlalchemy.orm import Session

@runtime_checkable
class QualityGateServiceProtocol(Protocol):
    def assess(self, db: "Session", request: Any) -> "QualityGateAssessment": ...
```

`runtime_checkable` allows `isinstance(obj, QualityGateServiceProtocol)` guards in tests.
The `TYPE_CHECKING` guard keeps the `Session` import from creating a circular import at
runtime (schemas must stay import-light).

### `QualityGateService` becomes instance-compatible

```python
# Before (in services/quality_gate.py):
class QualityGateService:
    @staticmethod
    def assess(db: Session, request) -> QualityGateAssessment: ...

# After:
class QualityGateService:
    def assess(self, db: Session, request) -> QualityGateAssessment: ...

# Module-level singleton (bottom of services/quality_gate.py):
quality_gate_service: "QualityGateServiceProtocol" = QualityGateService()
```

The method body is **unchanged**. Removing `@staticmethod` is a zero-risk refactor: the
method references no instance state and is tested independently of any particular class call.

### Consumer migrations (three files)

**`services/auto_trade_service.py`** (lines 41, 189):
```python
# Remove:
from app.services.quality_gate import QualityGateService
# Add:
from app.services.quality_gate import quality_gate_service

# Change call (line 189):
assessment = quality_gate_service.assess(db, _gate_req)
```
`_gate_passes` and `_resolve_universe_id` are unchanged — they never referenced the class.

**`tasks/scanning.py`** (lines 16, 312):
```python
# Remove:
from app.services.quality_gate import QualityGateService
# Add:
from app.services.quality_gate import quality_gate_service

# Change call (line 312):
_assessment = quality_gate_service.assess(db, _gate_req)
```

**`routers/data_quality.py`** (lines 18, 33):
```python
# Remove:
from app.services.quality_gate import QualityGateService
# Add:
from app.services.quality_gate import quality_gate_service

# Change call (line 33):
return quality_gate_service.assess(db, body)
```

### Testing benefit

Tests can substitute a fake without subclassing:

```python
class FakeGateService:
    def assess(self, db, request) -> QualityGateAssessment:
        return QualityGateAssessment(verdict=QualityGateVerdict.trusted, ...)

monkeypatch.setattr("app.services.auto_trade_service.quality_gate_service", FakeGateService())
```

No mocking of the concrete class internals required.

## Alternatives Considered

### A: Abstract Base Class (`abc.ABC`) in `services/`
`QualityGateService` inherits from an ABC. Requires modifying the concrete class
(metaclass change) and creates a hard nominal coupling in `services/`. The Protocol
approach achieves the same isolation structurally without touching the class hierarchy.
**Rejected** — more invasive for the same outcome.

### B: Constructor injection on `AutoTradeExecutor`
`AutoTradeExecutor.__init__` accepts `gate_service: QualityGateServiceProtocol = quality_gate_service`.
Cleaner for unit testing `AutoTradeExecutor` in isolation, but requires changing the
module-level `auto_trade_executor = AutoTradeExecutor()` singleton and all its instantiation
sites. Adds complexity without benefit for the scanner task or the router (which are not
classes). **Deferred** — can be added on top of this change if needed; the Protocol is
the prerequisite either way.

### C: Callable Protocol (`QualityGateAssessor`)
Define the Protocol around a single `__call__` rather than a named method, so consumers
receive a bare callable `assess_fn`. More minimal but loses the named-method contract
that makes the interface self-documenting at call sites. **Rejected** — the named method
is clearer.

## Assumptions

- `QualityGateService` has no internal state — removing `@staticmethod` produces an
  identical runtime behavior since Python static methods are already accessible on instances.
  **[Verified: the method body uses no `self` references and no `cls` references.]**
- The `TYPE_CHECKING` guard on the `Session` import in `schemas/quality_gate.py` is
  sufficient to avoid circular imports. **[Assumed: schemas currently has no services/ imports.]**
- No external callers (third-party code, factory scripts) use `QualityGateService.assess`
  as a class-level static call that would break after the singleton migration.
  **[Assumed: grep shows only the three consumers listed above.]**

## Out of Scope (Follow-on)

The inline evidence logic in `_build_assessment` (six issue codes: `missing_bars`,
`survivorship_bias`, `stale_quote`, `provider_gap`, `insufficient_lookback`,
`split_dividend_anomaly`) remains unchanged. The standalone batch generators in
`quality_gate_evidence.py` are NOT wired into `_build_assessment` in this issue.

File a follow-on issue referencing R04-v4 §3.4 for: an `EvidenceGenerator` callable
registry inside `_build_assessment` so new evidence types register rather than edit the
orchestrator, and for reconciling the real-time vs. batch generator paths.

## Open Questions

None blocking. The follow-on evidence-generator registry is the natural next step once this
consumer-side decoupling lands.
