"""Drives the JSON cases in tests/decisions/fixtures/ (malformed, stale, low_quality,
prompt_injected) against the contract models and the deterministic policy."""

import json

import pytest
from pydantic import BaseModel, ValidationError

from app.decisions.policy import DecisionContractViolation, decide, validate_request
from app.decisions.request import DecisionRequest, QualityGateRef
from app.decisions.result import DecisionResult
from app.decisions.schema import DecisionSchema, UntrustedText
from tests.decisions.factories import (
    AS_OF,
    RUN_UUID,
    make_request,
    make_result,
    make_schema,
)
from tests.decisions.fixtures import apply_patch, load_cases

_MODELS: dict[str, type[BaseModel]] = {
    "schema": DecisionSchema,
    "request": DecisionRequest,
    "result": DecisionResult,
}


def _baseline_json(target: str) -> dict:
    if target == "schema":
        # schema_hash is derived; drop it so a patched schema fails for the patched reason.
        return make_schema().model_dump(mode="json", exclude={"schema_hash"})
    if target == "request":
        return make_request().model_dump(mode="json")
    return make_result().model_dump(mode="json")


def _validate(case: dict) -> BaseModel:
    payload = apply_patch(_baseline_json(case["target"]), case["patch"])
    return _MODELS[case["target"]].model_validate_json(json.dumps(payload))


@pytest.mark.parametrize("name, case", load_cases("malformed"))
def test_malformed_fixture_rejected(name, case):
    with pytest.raises(ValidationError) as excinfo:
        _validate(case)
    expected = tuple(case["error_loc"])
    locs = [tuple(err["loc"]) for err in excinfo.value.errors()]
    assert any(loc[: len(expected)] == expected for loc in locs), (name, locs)


@pytest.mark.parametrize("name, case", load_cases("stale"))
def test_stale_fixture_rejected_by_validate_request(name, case):
    request = _validate(case)  # stale data is well-formed; the policy layer rejects it
    with pytest.raises(DecisionContractViolation, match=case["violation"]):
        validate_request(request, make_schema())


@pytest.mark.parametrize("name, case", load_cases("low_quality"))
def test_low_quality_fixture_never_records(name, case):
    schema = make_schema()
    request = _validate(case)
    validate_request(request, schema)  # a degraded gate is valid, recordable data
    if case.get("equals_no_assessment"):
        assert request.quality_gate == QualityGateRef.no_assessment(
            as_of=AS_OF, source_run_uuid=RUN_UUID
        )
    outcome = decide(request, make_result(schema), schema)
    assert outcome == case["expected_outcome"]
    assert outcome != "RECORD"


@pytest.mark.parametrize("name, case", load_cases("prompt_injected"))
def test_prompt_injected_fixture_fails_validation(name, case):
    # v1 has no UntrustedText-typed field, so every injected payload must be rejected.
    with pytest.raises(ValidationError):
        _validate(case)


def _injected_strings() -> list[str]:
    strings: list[str] = []

    def walk(node):
        if isinstance(node, str):
            strings.append(node)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for _, case in load_cases("prompt_injected"):
        walk(case["patch"])
    return strings


@pytest.mark.parametrize("payload", _injected_strings())
def test_injected_text_is_inert_as_untrusted_text(payload):
    schema = make_schema()
    request, result = make_request(schema), make_result(schema)
    baseline = (schema.schema_hash, [q.model_dump() for q in schema.questions])
    baseline_outcome = decide(request, result, schema)
    try:
        text = UntrustedText(untrusted_text=payload)
    except ValidationError:
        return  # rejected outright (control/format characters or over-length)
    assert text.untrusted_text == payload
    assert UntrustedText.model_validate_json(text.model_dump_json()) == text
    assert (schema.schema_hash, [q.model_dump() for q in schema.questions]) == baseline
    assert decide(request, result, schema) == baseline_outcome == "RECORD"
