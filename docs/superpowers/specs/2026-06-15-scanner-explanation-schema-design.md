# Scanner Explanation Schema and Validation Helpers

**Date:** 2026-06-15
**Issue:** #452 (Epic: #448)
**Blocked by:** #451 (Add persisted scanner event explanation column)
**Status:** Pending review

## Overview

Issue #451 adds `scanner_events.explanation` as a nullable JSONB column. This issue (#452) defines the versioned shape that column must contain and the Pydantic models plus validation helper that enforce it across all write paths: scanner services, API serializers, backfill jobs, and tests.

The schema (`scanner_explanation.v1`) is already fully specified in the parent design doc (`docs/superpowers/specs/2026-06-13-scanner-explainability-design.md`). This spec translates that JSON shape into a Pydantic implementation contract — deciding where the code lives, which fields are strict vs. loose, and how validation is surfaced to callers.

## Requirements

From acceptance criteria:

1. Validation accepts the required v1 envelope fields (`schema_version`, `why`, `criteria_passed`, `criteria_failed`, `confidence_inputs`, `data_quality_warnings`, `evidence`).
2. Criterion entries validate: stable ID key format, `observed` (float), `threshold` (float), `operator` (closed set), `unit` (string), `source` (string), optional `lookback` (string), optional `importance` (float 0–1).
3. Warning entries validate: `code` (string), `severity` (`low`/`medium`/`high`), `message` (string), `affected_inputs` (list of strings).
4. Tests cover: valid v1 payloads, missing required envelope fields, malformed criterion entries, malformed warning entries.

From the parent spec design rules:
- `criteria_passed` and `criteria_failed` use stable criterion IDs — the key format is part of the contract.
- New scanners must not invent custom top-level shapes — the envelope is scanner-neutral.
- `schema_version` is the discriminator for future versioning.

## Selected Approach

**Pydantic nested models with `extra="forbid"` in `backend/app/schemas/scanner_explanation.py`.**

Each nested object in the schema (`CriterionEntry`, `ConfidenceInputs`, `DataQualityWarning`, `EvidenceBlock`) becomes its own `BaseModel` with `model_config = {"extra": "forbid"}`. The top-level `ScannerExplanationV1` composes them. A module-level `validate_explanation(raw: dict) -> ScannerExplanationV1` helper wraps `model_validate()` and is the single point callers import.

Key decisions from Q&A:

| Field | Type | Rationale |
|-------|------|-----------|
| `schema_version` | `Literal["scanner_explanation.v1"]` | Version discriminator — strict enforcement enables discriminated unions when v2 arrives |
| `operator` | `Literal[">=", ">", "<=", "<", "==", "!="]` | v1 only expresses scalar comparisons; `in`/`between` require a different shape and belong in v2 |
| `severity` (warning) | Reuse `SeverityLiteral` from `schemas/event.py` | Single severity vocabulary across events, alerts, and explanations |
| `importance` | `Optional[float]` + `field_validator` for `0 ≤ x ≤ 1` | Out-of-range values silently corrupt Epic 2 analog matching and UI ordering |
| criterion key | `field_validator` on dict enforcing `^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]+)+$` | Stable IDs are load-bearing for Epic 2 analog matching; multi-segment allows future scanner namespaces beyond two levels |

## File Layout

```
backend/app/schemas/
  scanner_explanation.py        ← new: all models + validate_explanation()
  __init__.py                   ← add ScannerExplanationV1 + validate_explanation to imports/__all__
  event.py                      ← existing: SeverityLiteral imported from here (no change)

backend/tests/services/
  test_explanation_schema.py    ← new: pure-function tests, no DB
```

`scanner_explanation.py` lives in `schemas/` (not `services/`) because it is a pure data-shape contract. Placing it in `services/` would invert the import direction: API serializers and tests would reach into `services/` for a type definition, violating the established convention.

## Schema Shape (Pydantic)

```python
# backend/app/schemas/scanner_explanation.py

import re
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from app.schemas.event import SeverityLiteral

_CRITERION_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]+)+$")

OperatorLiteral = Literal[">=", ">", "<=", "<", "==", "!="]


class CriterionEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    observed: float
    threshold: float
    operator: OperatorLiteral
    unit: str
    source: str
    lookback: Optional[str] = None
    importance: Optional[float] = None

    @field_validator("importance")
    @classmethod
    def importance_in_range(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (0.0 <= v <= 1.0):
            raise ValueError("importance must be between 0.0 and 1.0")
        return v


class DataQualityWarning(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: SeverityLiteral
    message: str
    affected_inputs: List[str]


class ConfidenceInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: float
    score_source: str
    positive: Dict[str, float] = {}
    negative: Dict[str, float] = {}
    missing: Dict[str, float] = {}


class EvidenceBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reconstructed: bool
    reconstruction_quality: Optional[str] = None
    generated_at: str          # ISO-8601 string; kept as str to avoid tz-aware datetime complexity
    generator_version: str
    market_data_asof: str
    provider: str


class ScannerExplanationV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scanner_explanation.v1"]
    why: List[str]
    criteria_passed: Dict[str, CriterionEntry] = {}
    criteria_failed: Dict[str, CriterionEntry] = {}
    confidence_inputs: ConfidenceInputs
    data_quality_warnings: List[DataQualityWarning] = []
    evidence: EvidenceBlock

    @field_validator("criteria_passed", "criteria_failed", mode="before")
    @classmethod
    def criterion_keys_are_stable_ids(
        cls, v: Dict
    ) -> Dict:
        if not isinstance(v, dict):
            raise ValueError("must be a dict")
        for key in v:
            if not _CRITERION_KEY_RE.match(key):
                raise ValueError(
                    f"criterion key {key!r} must match pattern"
                    " ^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]+)+$"
                )
        return v


def validate_explanation(raw: dict) -> ScannerExplanationV1:
    """Parse and validate a raw dict as scanner_explanation.v1.

    Raises pydantic.ValidationError on any schema violation.
    Returns the typed model for downstream use.
    """
    return ScannerExplanationV1.model_validate(raw)
```

## Test Coverage

`backend/tests/services/test_explanation_schema.py` — pure-function, no DB:

| Test | What it covers |
|------|---------------|
| `test_valid_full_payload` | Complete v1 envelope with all optional fields — asserts round-trip via `validate_explanation()` |
| `test_valid_minimal_payload` | Only required fields (empty `criteria_passed`/`criteria_failed`, no warnings) |
| `test_wrong_schema_version` | `schema_version: "v2"` → `ValidationError` |
| `test_missing_evidence` | No `evidence` block → `ValidationError` |
| `test_missing_why` | No `why` list → `ValidationError` |
| `test_invalid_criterion_key_format` | Key `"BAD_KEY"` (uppercase, no dot) → `ValidationError` |
| `test_invalid_operator` | `operator: "between"` → `ValidationError` |
| `test_importance_out_of_range` | `importance: 1.5` → `ValidationError` |
| `test_warning_invalid_severity` | `severity: "critical"` → `ValidationError` |
| `test_extra_top_level_field` | Unknown top-level key → `ValidationError` (extra="forbid") |
| `test_extra_criterion_field` | Unknown criterion-level key → `ValidationError` |

Tests call `validate_explanation(raw_dict)` directly, asserting either success or `pytest.raises(ValidationError)`. No fixtures, no DB. File sits alongside `test_alert_service.py` and other pure-function schema tests in `tests/services/`.

## Alternatives Considered

### A: Coarse `_validate_jsonb_dict` probe only

`alert_service.py` validates JSONB dicts with a coarse `json.dumps()` probe. This could be applied to `explanation` without defining Pydantic models.

**Rejected:** The explanation envelope is fixed-shape and load-bearing — Epic 2 analog matching keys off criterion IDs and importance weights. A coarse probe would pass any dict with serializable values, catching type errors only at read time (API serialization) rather than write time (scanner). The added models also give the ExplanationBuilder (#453) a typed interface at no extra cost.

### B: Schema in `backend/app/services/scanner_explanation.py`

Co-locate schema with the future `ExplanationBuilder` service (issue #453).

**Rejected:** API serializers and test fixtures would import a type definition from `services/`, breaking the established convention that `schemas/` owns all Pydantic contracts. The import direction should flow outward from `schemas/`, not from `services/`.

### C: Generic `Optional[dict]` field on API response with no server-side validation

Let `ScannerEventResponse` expose `explanation: Optional[dict]` and validate nothing server-side.

**Rejected:** Fails the acceptance criterion "Validation accepts the required v1 envelope fields" and leaves the API open to silently persisting malformed envelopes. The whole point of this issue is to make the schema the write-path contract, not a documentation-only artifact.

## Assumptions

- `SeverityLiteral` is imported from `backend/app/schemas/event.py:13` — confirmed present.
- `generated_at` and `market_data_asof` in `EvidenceBlock` are stored as ISO-8601 strings (not `datetime`), matching the JSON example in the parent spec. This avoids timezone-aware datetime serialization complexity in JSONB; the ExplanationBuilder can pass `datetime.isoformat()`.
- `criteria_passed` and `criteria_failed` default to empty dict (not required) because a scanner may fire on a single passing criterion with no explicitly failed criteria tracked yet.
- The `validate_explanation()` helper raises `pydantic.ValidationError` directly — it does not re-wrap as `ValueError`. Callers that want `ValueError` may catch and re-raise; the scanner write path and backfill jobs will typically let the `ValidationError` propagate to their own error handlers.
- `schemas/__init__.py` exports `ScannerExplanationV1` and `validate_explanation` following the existing re-export pattern, but the specific import line is implementation detail for the agent; the spec does not mandate a particular `__all__` position.

## Open Questions

- Should `why` require at least one string (non-empty list), or can it be empty for partial explanations? The parent spec shows at least one entry in every example. The implementation could add `min_length=1` but this may be too strict during the backfill phase where data is incomplete. *Non-blocking — default to `List[str]` with no minimum; the ExplanationBuilder can enforce a non-empty list at generation time.*
- Should `confidence_inputs` be `Optional[ConfidenceInputs]` for scanners that do not yet compute `signal_quality_score`? The parent spec shows it as always present. *Non-blocking — keep required for now; scanners that lack scores can emit `score: 0.0, score_source: "none"`.*
