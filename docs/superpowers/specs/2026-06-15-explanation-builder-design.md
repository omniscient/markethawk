# Scanner-Neutral ExplanationBuilder Design

**Date:** 2026-06-15
**Issue:** #453
**Parent epic:** #448 — Explainability Foundation for scanner events
**Blocked by:** #452 — Define scanner explanation schema and validation helpers
**Status:** Spec pending review

## Overview

This spec covers the implementation of a scanner-neutral `ExplanationBuilder` that assembles a complete `scanner_explanation.v1` payload from structured scanner observations. Every scanner that produces an explained hit passes its observations through this builder to obtain a validated, uniform explanation dict. The builder has no knowledge of any scanner-specific data type — it works from a generic `CriterionObservation` input and returns a dict that is valid against the `scanner_explanation.v1` schema defined in issue #452.

The parent epic spec (`docs/superpowers/specs/2026-06-13-scanner-explainability-design.md`) defines the full v1 schema and the design rules this builder must follow.

## Requirements

- The builder accepts a scanner-neutral list of `CriterionObservation` entries plus confidence and evidence inputs, and knows nothing about scanner-specific types (`RawSignal`, `EnrichedSignal`, etc.).
- Each scanner owns the adapter that maps its indicators and `criteria_met` dict into the `CriterionObservation` list before calling the builder.
- `why` bullets are template-formatted by the builder from the structured criterion fields; no scanner-supplied free-text strings are accepted.
- `data_quality_warnings` are pre-computed by the caller and passed in; the builder validates their shape via the #452 validators and embeds them. It does not call `DataQualityService` or `DataReadinessService` internally.
- `confidence_inputs.score` and `score_source` are accepted as explicit parameters; the score is computed upstream (e.g. during the pre-market `_enrich` stage) and mirrored here to stay in sync with `ScannerEvent.signal_quality_score`. The builder derives the `positive` / `negative` / `missing` weight maps from the `importance` field on each `CriterionObservation`.
- The builder module lives at `backend/app/services/explanations/builder.py` in a new `explanations` subpackage with `__init__.py` re-exporting the public symbol. This establishes the grouping convention before the related modules from issues #454, #455, and #458 land.
- Focused unit tests cover: passed criteria only, failed criteria only, mixed pass/fail, warnings present, all optional fields absent (empty sections), and missing `lookback`.

## Selected Approach

**Pure-function builder with a typed input dataclass.** `build_explanation()` is a module-level function in `backend/app/services/explanations/builder.py`. It accepts a list of `CriterionObservation` dataclass instances plus named keyword arguments for confidence and evidence inputs, and returns a plain `dict` that passes the #452 validator. A class is not used because there is no instance state; the function is pure (no DB access, no network calls), making it easy to test in isolation.

## Alternatives Considered

### Alternative 1: Scanner-specific adapter methods on the builder

The builder would have `build_from_enriched_signal(signal: EnrichedSignal, ...)` for the pre-market scanner, with future scanners adding their own adapter methods. Rejected: this couples the builder to scanner-specific types and forces it to grow per-scanner branches over time, defeating the "scanner-neutral" requirement.

### Alternative 2: Scanner-supplied `why_text` on CriterionObservation

Each criterion entry would carry an optional `why_text` pre-written by the scanner, with the builder falling back to a template when absent. Rejected: the parent spec explicitly states `why` must be derived from structured criteria/evidence, "not manually maintained strings." Allowing `why_text` reintroduces manual strings even under an optional flag.

### Alternative 3: Builder calls DataQualityService internally

The builder would obtain data quality warnings itself by calling `DataQualityService`/`DataReadinessService`. Rejected: this pulls issue #454's scope into #453, requires a DB session, and breaks the scanner-neutral, assembly-only contract. The accepted pattern (caller pre-computes, builder validates+embeds) mirrors how `why` bullets are handled.

## Architecture

### Module location

```
backend/app/services/explanations/
├── __init__.py          # re-exports build_explanation
└── builder.py           # CriterionObservation dataclass + build_explanation()
```

### `CriterionObservation` dataclass

```python
@dataclass(frozen=True)
class CriterionObservation:
    criterion_id: str          # stable ID, e.g. "premarket.relative_volume"
    label: str                 # human label, e.g. "Relative volume"
    observed: float            # observed value
    threshold: float           # comparison threshold
    operator: str              # ">=", "<=", ">", "<", "=="
    unit: str                  # e.g. "x", "%", ""
    source: str                # data lineage, e.g. "stock_aggregates.day.volume"
    passed: bool               # True if the criterion was met
    importance: Optional[float] = None   # optional weight (0.0–1.0)
    lookback: Optional[str] = None       # e.g. "30d" — omit clause when None
```

### `build_explanation()` signature

```python
def build_explanation(
    criteria: list[CriterionObservation],
    *,
    score: float,
    score_source: str,
    data_quality_warnings: list[dict],   # pre-validated by caller or validated here via #452 helpers
    evidence: dict,                       # reconstructed, reconstruction_quality, generated_at,
                                          # market_data_asof, provider — all required by caller
    generator_version: str = "explanation_builder.v1",
) -> dict:
```

Returns a dict valid against `scanner_explanation.v1`.

### `why` bullet template

For each criterion where `passed=True`:

```
"{label}: {observed}{unit} ({operator} {threshold}{unit})"
```

When `lookback` is present, append ` · {lookback} avg`:

```
"Relative volume: 2.3x (>= 2.0x · 30d avg)"
```

When `unit` is empty string, no unit is appended. When `lookback` is None, the clause is omitted.

Only `passed=True` criteria contribute to `why`. Failed criteria appear in `criteria_failed` only.

### `confidence_inputs` derivation

```python
"confidence_inputs": {
    "score": score,                   # passed in from caller
    "score_source": score_source,     # passed in (e.g. "signal_quality_score")
    "positive": {c.criterion_id: c.importance for c in criteria
                 if c.passed and c.importance is not None},
    "negative": {c.criterion_id: c.importance for c in criteria
                 if not c.passed and c.importance is not None},
    "missing": {}                     # reserved for future: criteria expected but not evaluated
}
```

`missing` is always an empty dict in v1. The field is present in the output for schema stability.

### Output shape

```python
{
    "schema_version": "scanner_explanation.v1",
    "why": [...],                    # template-formatted from passed criteria
    "criteria_passed": {
        criterion_id: {
            "label": ..., "observed": ..., "threshold": ...,
            "operator": ..., "unit": ..., "source": ...,
            "lookback": ...,         # omitted from dict if None
            "importance": ...,       # omitted from dict if None
        },
        ...
    },
    "criteria_failed": { ... },      # same shape, criteria where passed=False
    "confidence_inputs": { ... },
    "data_quality_warnings": [...],  # passed in, validated via #452 helpers
    "evidence": {
        "reconstructed": ...,
        "reconstruction_quality": ...,
        "generated_at": ...,
        "generator_version": "explanation_builder.v1",
        "market_data_asof": ...,
        "provider": ...,
    },
}
```

Optional fields (`lookback`, `importance`) are omitted from criterion dicts (not set to `null`) when not present, so the output stays clean for downstream consumers.

### Validation

The builder calls the `validate_explanation(payload)` helper from issue #452 before returning. If validation fails it raises a `ValueError` with the validation error details. This ensures no invalid payload is ever persisted.

### Test file

`backend/tests/services/explanations/test_builder.py` with these cases:

| Test | What it covers |
|---|---|
| `test_passed_criteria_only` | All criteria passed; criteria_failed is empty; why bullets generated |
| `test_failed_criteria_only` | All criteria failed; criteria_passed is empty; why is empty list |
| `test_mixed_pass_fail` | Some passed, some failed; both sections populated correctly |
| `test_warnings_present` | data_quality_warnings with one medium warning; embedded as-is |
| `test_empty_optional_sections` | No importance, no lookback on any criterion; omitted from dicts |
| `test_lookback_in_why` | Criterion with lookback present; bullet includes lookback clause |
| `test_no_lookback_in_why` | Criterion without lookback; bullet excludes lookback clause |
| `test_score_reflected` | score and score_source mirrored exactly in confidence_inputs |
| `test_validation_called` | Monkeypatching validates that the #452 validator is called |

## Assumptions

- Issue #452 will deliver a `validate_explanation(payload: dict) -> None` (raises on invalid) helper that this builder can import without circular-dependency risk.
- `importance` values are 0.0–1.0 floats or `None`; the builder does not normalize or sum them.
- `evidence` dict is assembled entirely by the caller; the builder injects `generator_version` into it (overwriting any caller-supplied value with the builder's own version string).
- `missing` map stays empty in v1; a future spec revision can populate it when scanners report expected-but-unevaluated criteria.
- The `explanations/` subpackage is new; it does not conflict with any existing module of the same name.

## Open Questions

- **Q**: Should the builder enforce that `operator` is one of `[">=", "<=", ">", "<", "=="]`, or does it delegate that check entirely to the #452 validator?  
  *Non-blocking: either approach works; if the #452 schema validates operators, the builder need not duplicate the check.*

- **Q**: Should `why` bullets for failed criteria be included as a "what was close but didn't fire" UX affordance?  
  *Non-blocking for this issue; the parent spec does not mention it. If added in a future issue, the template format established here can be reused.*
