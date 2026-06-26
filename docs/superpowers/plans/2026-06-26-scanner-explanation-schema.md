# Plan: Scanner Explanation Schema and Validation Helpers (#452)

**Date:** 2026-06-26  
**Issue:** [#452 — Define scanner explanation schema and validation helpers](https://github.com/omniscient/markethawk/issues/452)  
**Epic:** #448 (Scanner Explainability)  
**Blocked by:** #451 (Add persisted scanner event explanation column)

---

## Goal

Introduce `ScannerExplanationV1` — a versioned Pydantic schema and `validate_explanation()` helper — as the single write-path contract for the `scanner_events.explanation` JSONB column. Used by scanner services, API serializers, and backfill jobs.

## Architecture

Three files touched:

| File | Action | Description |
|------|--------|-------------|
| `backend/app/schemas/scanner_explanation.py` | **CREATE** | All Pydantic models + `validate_explanation()` helper |
| `backend/app/schemas/__init__.py` | **MODIFY** | Re-export `ScannerExplanationV1` + `validate_explanation` |
| `backend/tests/services/test_explanation_schema.py` | **CREATE** | 11 pure-function tests, no DB |

The schema lives in `schemas/` (not `services/`) because it is a pure data-shape contract. Placing it in `services/` would invert the import direction — API serializers and tests would reach into `services/` for a type definition, violating the established convention.

`SeverityLiteral` is imported from `app.schemas.event` (line 13) — not duplicated — to keep a single severity vocabulary across events, alerts, and explanations.

## Tech Stack

- **Pydantic v2** — `BaseModel`, `ConfigDict(extra="forbid")`, `field_validator`, `model_validate`
- **pytest** — pure-function tests, no DB, no fixtures beyond inline dicts
- **Regex** — criterion key stable-ID format enforcement (load-bearing for Epic 2 analog matching)

---

## File Structure

```
backend/
  app/
    schemas/
      scanner_explanation.py     ← new
      __init__.py                ← modified: +2 exports
  tests/
    services/
      test_explanation_schema.py ← new
```

---

## Task 1 — Write failing tests for `ScannerExplanationV1`

**Files:** `backend/tests/services/test_explanation_schema.py`

### TDD steps

**Step 1.1 — Write the test file**

Create `backend/tests/services/test_explanation_schema.py`:

```python
"""
Pure-function tests for ScannerExplanationV1 schema and validate_explanation().
No DB, no fixtures. Tests call validate_explanation(raw_dict) and assert
either a successful typed result or pytest.raises(ValidationError).
"""

import pytest
from pydantic import ValidationError

from app.schemas.scanner_explanation import ScannerExplanationV1, validate_explanation

# ── shared test payloads ────────────────────────────────────────────────────

_VALID_FULL = {
    "schema_version": "scanner_explanation.v1",
    "why": ["Volume spike: 5.2x 20-day average"],
    "criteria_passed": {
        "pre_market.volume_ratio": {
            "label": "Volume Ratio",
            "observed": 5.2,
            "threshold": 4.0,
            "operator": ">=",
            "unit": "ratio",
            "source": "polygon",
            "lookback": "20d",
            "importance": 0.9,
        }
    },
    "criteria_failed": {
        "pre_market.price_gap_pct": {
            "label": "Price Gap %",
            "observed": 0.8,
            "threshold": 1.0,
            "operator": ">=",
            "unit": "percent",
            "source": "polygon",
        }
    },
    "confidence_inputs": {
        "score": 0.82,
        "score_source": "signal_quality_v1",
        "positive": {"pre_market.volume_ratio": 0.9},
        "negative": {"pre_market.price_gap_pct": 0.3},
        "missing": {},
    },
    "data_quality_warnings": [
        {
            "code": "SPARSE_PREMARKET_BARS",
            "severity": "low",
            "message": "Only 3 pre-market bars available (expected ≥10).",
            "affected_inputs": ["pre_market.volume_ratio"],
        }
    ],
    "evidence": {
        "reconstructed": False,
        "generated_at": "2026-06-26T14:00:00",
        "generator_version": "1.0.0",
        "market_data_asof": "2026-06-26T09:30:00",
        "provider": "polygon",
    },
}

_VALID_MINIMAL = {
    "schema_version": "scanner_explanation.v1",
    "why": ["No criteria tracked yet — partial backfill"],
    "criteria_passed": {},
    "criteria_failed": {},
    "confidence_inputs": {
        "score": 0.0,
        "score_source": "none",
    },
    "data_quality_warnings": [],
    "evidence": {
        "reconstructed": True,
        "generated_at": "2026-06-26T08:00:00",
        "generator_version": "1.0.0",
        "market_data_asof": "2026-06-26T07:59:00",
        "provider": "polygon",
    },
}


# ── tests ───────────────────────────────────────────────────────────────────


def test_valid_full_payload():
    """Complete v1 envelope with all optional fields round-trips cleanly."""
    result = validate_explanation(_VALID_FULL)
    assert isinstance(result, ScannerExplanationV1)
    assert result.schema_version == "scanner_explanation.v1"
    assert result.confidence_inputs.score == 0.82
    criterion = result.criteria_passed["pre_market.volume_ratio"]
    assert criterion.importance == 0.9
    assert criterion.operator == ">="


def test_valid_minimal_payload():
    """Only required fields — empty criteria dicts and no warnings — passes."""
    result = validate_explanation(_VALID_MINIMAL)
    assert isinstance(result, ScannerExplanationV1)
    assert result.criteria_passed == {}
    assert result.data_quality_warnings == []
    assert result.evidence.reconstructed is True


def test_wrong_schema_version():
    """schema_version 'v2' (non-literal) raises ValidationError."""
    bad = {**_VALID_FULL, "schema_version": "scanner_explanation.v2"}
    with pytest.raises(ValidationError):
        validate_explanation(bad)


def test_missing_evidence():
    """Omitting the 'evidence' block raises ValidationError."""
    bad = {k: v for k, v in _VALID_FULL.items() if k != "evidence"}
    with pytest.raises(ValidationError):
        validate_explanation(bad)


def test_missing_why():
    """Omitting the 'why' list raises ValidationError."""
    bad = {k: v for k, v in _VALID_FULL.items() if k != "why"}
    with pytest.raises(ValidationError):
        validate_explanation(bad)


def test_invalid_criterion_key_format():
    """Criterion key 'BAD_KEY' (uppercase, no dot) raises ValidationError."""
    bad = dict(_VALID_FULL)
    bad["criteria_passed"] = {
        "BAD_KEY": _VALID_FULL["criteria_passed"]["pre_market.volume_ratio"]
    }
    with pytest.raises(ValidationError):
        validate_explanation(bad)


def test_invalid_operator():
    """operator 'between' (not in closed set) raises ValidationError."""
    criterion = {**_VALID_FULL["criteria_passed"]["pre_market.volume_ratio"], "operator": "between"}
    bad = dict(_VALID_FULL)
    bad["criteria_passed"] = {"pre_market.volume_ratio": criterion}
    with pytest.raises(ValidationError):
        validate_explanation(bad)


def test_importance_out_of_range():
    """importance 1.5 (> 1.0) raises ValidationError."""
    criterion = {**_VALID_FULL["criteria_passed"]["pre_market.volume_ratio"], "importance": 1.5}
    bad = dict(_VALID_FULL)
    bad["criteria_passed"] = {"pre_market.volume_ratio": criterion}
    with pytest.raises(ValidationError):
        validate_explanation(bad)


def test_warning_invalid_severity():
    """Warning severity 'critical' (not in SeverityLiteral) raises ValidationError."""
    bad_warning = {
        "code": "TEST",
        "severity": "critical",
        "message": "test",
        "affected_inputs": [],
    }
    bad = dict(_VALID_FULL)
    bad["data_quality_warnings"] = [bad_warning]
    with pytest.raises(ValidationError):
        validate_explanation(bad)


def test_extra_top_level_field():
    """Unknown top-level key raises ValidationError (extra='forbid')."""
    bad = {**_VALID_FULL, "unexpected_field": "surprise"}
    with pytest.raises(ValidationError):
        validate_explanation(bad)


def test_extra_criterion_field():
    """Unknown field inside a CriterionEntry raises ValidationError (extra='forbid')."""
    criterion = {**_VALID_FULL["criteria_passed"]["pre_market.volume_ratio"], "spurious": True}
    bad = dict(_VALID_FULL)
    bad["criteria_passed"] = {"pre_market.volume_ratio": criterion}
    with pytest.raises(ValidationError):
        validate_explanation(bad)
```

**Step 1.2 — Verify tests fail (ImportError)**

```bash
docker-compose exec backend python -m pytest tests/services/test_explanation_schema.py -v 2>&1 | head -20
```

Expected output (module doesn't exist yet):
```
ImportError: No module named 'app.schemas.scanner_explanation'
```

**Step 1.3 — Commit the test scaffold**

```bash
git add backend/tests/services/test_explanation_schema.py
git commit -m "test: scaffold 11 explanation schema test cases (#452)"
```

---

## Task 2 — Implement `backend/app/schemas/scanner_explanation.py`

**Files:** `backend/app/schemas/scanner_explanation.py`

### TDD steps

**Step 2.1 — Create the schema file**

Create `backend/app/schemas/scanner_explanation.py`:

```python
"""
Pydantic schema for the scanner_explanation.v1 envelope.

This module is the single import point for all write paths (scanner services,
API serializers, backfill jobs) that produce or consume scanner explanations.
The validate_explanation() helper raises pydantic.ValidationError on any
schema violation — callers that want ValueError may catch and re-raise.
"""

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
    generated_at: str
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
    def criterion_keys_are_stable_ids(cls, v: Dict) -> Dict:
        if not isinstance(v, dict):
            raise ValueError("must be a dict")
        for key in v:
            if not _CRITERION_KEY_RE.match(key):
                raise ValueError(
                    f"criterion key {key!r} must match"
                    r" ^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]+)+$"
                )
        return v


def validate_explanation(raw: dict) -> ScannerExplanationV1:
    """Parse and validate a raw dict as scanner_explanation.v1.

    Raises pydantic.ValidationError on any schema violation.
    """
    return ScannerExplanationV1.model_validate(raw)
```

**Step 2.2 — Run the tests, verify all 11 pass**

```bash
docker-compose exec backend python -m pytest tests/services/test_explanation_schema.py -v
```

Expected output:
```
PASSED tests/services/test_explanation_schema.py::test_valid_full_payload
PASSED tests/services/test_explanation_schema.py::test_valid_minimal_payload
PASSED tests/services/test_explanation_schema.py::test_wrong_schema_version
PASSED tests/services/test_explanation_schema.py::test_missing_evidence
PASSED tests/services/test_explanation_schema.py::test_missing_why
PASSED tests/services/test_explanation_schema.py::test_invalid_criterion_key_format
PASSED tests/services/test_explanation_schema.py::test_invalid_operator
PASSED tests/services/test_explanation_schema.py::test_importance_out_of_range
PASSED tests/services/test_explanation_schema.py::test_warning_invalid_severity
PASSED tests/services/test_explanation_schema.py::test_extra_top_level_field
PASSED tests/services/test_explanation_schema.py::test_extra_criterion_field
11 passed in <2s
```

**Step 2.3 — Commit the implementation**

```bash
git add backend/app/schemas/scanner_explanation.py
git commit -m "feat: ScannerExplanationV1 schema and validate_explanation helper (#452)"
```

---

## Task 3 — Export `ScannerExplanationV1` and `validate_explanation` from `schemas/__init__.py`

**Files:** `backend/app/schemas/__init__.py`

### TDD steps

**Step 3.1 — Add import and `__all__` entries**

In `backend/app/schemas/__init__.py`, add after the existing `from app.schemas.regime ...` line:

```python
from app.schemas.scanner_explanation import ScannerExplanationV1, validate_explanation
```

And add to `__all__`:

```python
    "ScannerExplanationV1",
    "validate_explanation",
```

Full diff (placed after the `scanner` block, preserving alphabetical order `scanner` → `scanner_explanation` → `stock`):

```diff
     ScannerStatusBlockResponse,
 )
+from app.schemas.scanner_explanation import ScannerExplanationV1, validate_explanation
 from app.schemas.stock import MonitoredStockResponse
```

```diff
     "QualityGateAssessment",
+    "ScannerExplanationV1",
+    "validate_explanation",
 ]
```

**Step 3.2 — Verify the package imports cleanly**

```bash
docker-compose exec backend python -c "
from app.schemas import ScannerExplanationV1, validate_explanation
print('ScannerExplanationV1:', ScannerExplanationV1)
print('validate_explanation:', validate_explanation)
print('OK')
"
```

Expected:
```
ScannerExplanationV1: <class 'app.schemas.scanner_explanation.ScannerExplanationV1'>
validate_explanation: <function validate_explanation at 0x...>
OK
```

**Step 3.3 — Re-run the full test suite to confirm no regressions**

```bash
docker-compose exec backend python -m pytest tests/services/test_explanation_schema.py tests/ -x -q 2>&1 | tail -10
```

Expected: all prior tests still pass (no import-cycle introduced).

**Step 3.4 — Commit**

```bash
git add backend/app/schemas/__init__.py
git commit -m "feat: export ScannerExplanationV1 and validate_explanation from schemas (#452)"
```

---

## Summary

| Task | Files | Steps |
|------|-------|-------|
| 1 — Test scaffold | `tests/services/test_explanation_schema.py` | Write 11 tests → verify ImportError → commit |
| 2 — Schema implementation | `schemas/scanner_explanation.py` | Implement 5 models + helper → 11 pass → commit |
| 3 — Package export | `schemas/__init__.py` | +2 imports, +2 `__all__` entries → verify → commit |

**Total:** 3 tasks, 9 steps.

All tests are pure-function (no DB, no fixtures). The `extra="forbid"` pattern (from `ChannelConfig` in `schemas/alerts.py`) is applied to all 5 models. `SeverityLiteral` is imported, not duplicated, from `app.schemas.event:13`. Criterion key regex validation is the write-path gate for Epic 2 analog matching — this is the highest-stakes line in the implementation.
