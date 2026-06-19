# Expose Scanner Explanations Through API Contracts — Design (issue #456)

**Date**: 2026-06-19
**Issue**: [#456](https://github.com/omniscient/markethawk/issues/456) — Expose scanner explanations through API contracts
**Parent epic**: [#448](https://github.com/omniscient/markethawk/issues/448) — Epic: Explainability Foundation for scanner events
**Blocked by**: [#455](https://github.com/omniscient/markethawk/issues/455) — Integrate pre-market volume spike as the reference explained scanner
**Status**: Spec pending review

---

## Problem

Scanner events already carry `indicators`, `criteria_met`, and `metadata_` — but these are untyped, unversioned, scanner-private blobs. The explainability epic (#448) adds a dedicated `explanation` JSONB column to `scanner_events` (done in #453) with a versioned `scanner_explanation.v1` schema (defined in #454) that is written for new pre-market volume spike hits in #455.

Issue #456 is the API-layer step: make the explanation visible through the backend response schemas and the frontend TypeScript contract, with backward-compatible handling for the large corpus of historical events that predate the explanation infrastructure.

---

## Requirements

1. `ScannerEventResponse` (Pydantic schema in `backend/app/schemas/event.py`) gains an `explanation` field typed as `Optional[ScannerExplanation]`.
2. Historical rows where `scanner_events.explanation IS NULL` serialize as `explanation: null` — never a fabricated empty shape.
3. A shallow `ScannerExplanation` Pydantic model documents the stable top-level envelope of `scanner_explanation.v1` without constraining scanner-specific inner structures.
4. The frontend `ScannerEvent` interface (`frontend/src/api/scanner/types.ts`) gains `explanation: ScannerExplanation | null` via a parallel shallow `ScannerExplanation` TypeScript interface.
5. API tests in `backend/tests/api/test_scanner.py` cover both explained rows (non-null, correct shape) and unexplained historical rows (null).
6. No changes to `ScannerRunResponse` or the `GET /scanner/history` endpoint — run-level metadata is out of scope.

---

## Scope

**In scope:**
- `backend/app/schemas/event.py` — add `ScannerExplanation` model, extend `ScannerEventResponse`
- `frontend/src/api/scanner/types.ts` — add `ScannerExplanation` interface, extend `ScannerEvent`
- `backend/tests/api/test_scanner.py` — two new test cases for the explanation field
- `backend/tests/fixtures/scanner.py` — seed helper for events with and without explanations (if not already present after #455)

**Out of scope:**
- `GET /scanner/history` endpoint (`ScannerRunResponse`) — this returns scan-run metadata, not individual events
- Building, validating, or storing explanations — that is #455's domain
- Historical backfill — deferred to #8 in the epic (`should-have`)
- Any frontend rendering — deferred to issue #7 (UI)

---

## Architecture

### Why this change is small

The `/scanner/results` endpoint already returns `List[ScannerEventResponse]` using SQLAlchemy `from_attributes`. Because SQLAlchemy ORM `from_attributes` serializes model columns directly, adding `explanation: Optional[ScannerExplanation] = None` to `ScannerEventResponse` is sufficient — the column value (NULL or a JSONB dict) flows through automatically once the Pydantic model knows to look for it.

The stock detail page queries `GET /scanner/results?ticker=XXX` — the same endpoint — so it gets explanation at no additional cost.

### Approach

#### Backend — `ScannerExplanation` Pydantic model

Add to `backend/app/schemas/event.py`:

```python
class ScannerExplanation(BaseModel):
    """Versioned explanation envelope for scanner_explanation.v1.

    Top-level keys are stable across all scanners (design rule from #448).
    Inner structures within criteria_passed/criteria_failed and confidence_inputs
    are scanner-specific and intentionally left as Dict[str, Any].
    """
    schema_version: str = "scanner_explanation.v1"
    why: List[str] = Field(default_factory=list)
    criteria_passed: Dict[str, Any] = Field(default_factory=dict)
    criteria_failed: Dict[str, Any] = Field(default_factory=dict)
    confidence_inputs: Optional[Dict[str, Any]] = None
    data_quality_warnings: List[Dict[str, Any]] = Field(default_factory=list)
    evidence: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow")
```

`extra="allow"` on the top-level model permits additive evolution in epics 2 and 3 (e.g. `ai_signal_brief`) without breaking existing clients.

Extend `ScannerEventResponse`:

```python
explanation: Optional[ScannerExplanation] = None
```

#### Frontend — TypeScript interface

Add to `frontend/src/api/scanner/types.ts`:

```ts
export interface ScannerExplanation {
  schema_version: string;
  why: string[];
  criteria_passed: Record<string, unknown>;
  criteria_failed: Record<string, unknown>;
  confidence_inputs: Record<string, unknown> | null;
  data_quality_warnings: Record<string, unknown>[];
  evidence: Record<string, unknown>;
  [key: string]: unknown;  // allow additive extension (epics 2/3)
}
```

Add to the `ScannerEvent` interface:

```ts
explanation: ScannerExplanation | null;
```

#### Tests

Two new test cases in `test_scanner.py`:

1. **`test_results_explained_event_has_explanation_field`** — seeds a `ScannerEvent` with a valid `scanner_explanation.v1` JSONB payload, calls `GET /scanner/results`, asserts the returned event has `explanation` as a dict with keys `schema_version`, `why`, `criteria_passed`, `criteria_failed`, `confidence_inputs`, `data_quality_warnings`, `evidence`.

2. **`test_results_unexplained_event_has_null_explanation`** — seeds a `ScannerEvent` without an explanation (NULL column), calls `GET /scanner/results`, asserts the returned event has `"explanation": null`.

---

## Alternatives Considered

### Option A: `Optional[Dict[str, Any]]` for the explanation field

Match the `indicators`/`criteria_met`/`metadata_` pattern — a raw untyped dict.

**Rejected**: The whole point of this issue is to *expose the explanation as an API contract*. A raw dict does not appear in OpenAPI at all. The explanation is a versioned cross-scanner contract (`scanner_explanation.v1`) with a stable top-level shape — typing it documents and enforces that stability for every API consumer and every future scanner migration.

### Option B: Fabricated empty default for unexplained rows

Return `{"schema_version": "scanner_explanation.v1", "why": [], ..., "evidence": {"reconstructed": true}}` for NULL DB rows.

**Rejected**: This is dishonest — no reconstruction happened, so `evidence.reconstructed: true` would be false. The design doc is explicit: "historical explanations must be honest about reconstruction limits." `null` cleanly means "no explanation present." Real reconstruction (backfill issue #8) will write a populated object with actual reconstruction metadata.

### Option C: Fully nested typed sub-models

`ExplanationCriterion(BaseModel)`, `ConfidenceInputs(BaseModel)`, `DataQualityWarning(BaseModel)`, etc.

**Rejected**: Criterion fields vary by scanner type ("scanner-specific criterion IDs inside the scanner-neutral envelope"). Strict sub-models would reject criterion keys added by liquidity hunt, oversold bounce, trend pullback, and live scanner migrations (#449–#452). `Dict[str, Any]` at the inner level is the deliberate choice, matching the design doc's rule: "use `extra="forbid"` only when the shape is fixed."

---

## Assumptions

- Issue #455 (write path) has merged before this issue is implemented. The `scanner_events.explanation` JSONB column exists in the database. Without it, the `from_attributes` mapping has nothing to serialize.
- The `explanation` column type is `JSONB, nullable=True`. No migration is required for this issue.
- Existing `seed_scanner_events()` in `tests/fixtures/scanner.py` creates events without explanations — test case 2 can reuse those. Test case 1 needs to set `explanation={...}` on a seeded event.

---

## Open Questions

- None blocking. One advisory:
  - When epic 2 fields (`ai_signal_brief`, etc.) are added to the explanation payload, should they extend `ScannerExplanation` (via `extra="allow"` + updated interface) or appear as sibling top-level fields on `ScannerEventResponse`? The design doc suggests the `ai_signal_brief` is a distinct endpoint response rather than embedded in the explanation — but this is a decision for the epic 2 spec, not this issue.
