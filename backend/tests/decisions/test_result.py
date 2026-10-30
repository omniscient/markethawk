import importlib
import inspect
import json
import pkgutil
import re

import pytest
from pydantic import BaseModel, ValidationError

import app.decisions
from app.decisions.result import DecisionAnswer, DecisionResult
from tests.decisions.factories import make_result, result_kwargs

ORDER_SHAPED_KEYS = (
    "quantity",
    "side",
    "order_type",
    "position_size",
    "notional",
    "stop_loss",
)
ORDER_KEY_LOCATIONS = ("root", "answers", "distributions", "usage")


def _result_json() -> dict:
    return make_result().model_dump(mode="json")


def test_valid_result_constructs():
    result = make_result()
    assert result.answers[0].label == "yes"


def test_rejects_out_of_range_numeric_answer():
    with pytest.raises(ValidationError):
        DecisionAnswer(question_id="expected_move_pct", value=1e12)
    with pytest.raises(ValidationError):
        DecisionAnswer(question_id="expected_move_pct", value=float("nan"))
    with pytest.raises(ValidationError):
        make_result(provider_confidence=1.5)


def test_answer_needs_exactly_one_of_label_or_value():
    with pytest.raises(ValidationError):
        DecisionAnswer(question_id="gap_continues")
    with pytest.raises(ValidationError):
        DecisionAnswer(question_id="gap_continues", label="yes", value=1.0)


def test_distribution_must_sum_to_one():
    payload = _result_json()
    payload["distributions"][0]["points"][0]["probability"] = 0.9
    with pytest.raises(ValidationError):
        DecisionResult.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize("location", ORDER_KEY_LOCATIONS)
@pytest.mark.parametrize("key", ORDER_SHAPED_KEYS)
def test_rejects_order_shaped_keys(key, location):
    payload = _result_json()
    target = {
        "root": payload,
        "answers": payload["answers"][0],
        "distributions": payload["distributions"][0],
        "usage": payload["usage"],
    }[location]
    target[key] = 100
    with pytest.raises(ValidationError):
        DecisionResult.model_validate_json(json.dumps(payload))


def test_confidence_key_rejected():
    payload = _result_json()
    del payload["provider_confidence"]
    payload["confidence"] = 0.9
    with pytest.raises(ValidationError):
        DecisionResult.model_validate_json(json.dumps(payload))


def test_provider_confidence_does_not_populate_calibrated_probability():
    kwargs = result_kwargs()
    kwargs["provider_confidence"] = 0.9
    result = DecisionResult.model_validate(kwargs)
    assert result.provider_confidence == 0.9
    assert result.calibrated_probability is None
    assert result.calibration_ref is None


def test_calibrated_probability_requires_calibration_ref():
    with pytest.raises(ValidationError):
        make_result(calibrated_probability=0.6)
    fitted = make_result(
        calibrated_probability=0.6, calibration_ref="calibration/platt.v1"
    )
    assert fitted.provider_confidence == 0.7


def test_result_carries_schema_ref():
    payload = _result_json()
    del payload["schema_ref"]
    with pytest.raises(ValidationError):
        DecisionResult.model_validate_json(json.dumps(payload))
    with pytest.raises(ValidationError):
        make_result(schema_ref="")
    assert len(make_result().schema_ref) == 64


def test_abstention_reason_excludes_answers():
    abstained = make_result(answers=(), distributions=(), abstention_reason="timeout")
    assert abstained.abstention_reason == "timeout"
    with pytest.raises(ValidationError):
        make_result(abstention_reason="timeout")
    with pytest.raises(ValidationError):
        make_result(answers=(), distributions=())
    with pytest.raises(ValidationError):
        make_result(answers=(), distributions=(), abstention_reason="i_felt_like_it")


def test_strict_mode_rejects_coercion():
    payload = _result_json()
    payload["provider_confidence"] = "0.9"
    with pytest.raises(ValidationError):
        DecisionResult.model_validate_json(json.dumps(payload))


def test_non_anthropic_provider_identity():
    result = make_result(provider_name="deterministic_baseline", model_version="0")
    assert (result.provider_name, result.model_version) == (
        "deterministic_baseline",
        "0",
    )


def _contract_models() -> list[type[BaseModel]]:
    """Every Pydantic model defined in any app.decisions submodule (present or future)."""
    models = []
    for info in pkgutil.iter_modules(app.decisions.__path__, "app.decisions."):
        module = importlib.import_module(info.name)
        models.extend(
            obj
            for _, obj in inspect.getmembers(module, inspect.isclass)
            if issubclass(obj, BaseModel) and obj.__module__ == module.__name__
        )
    return models


def _property_names(node) -> set[str]:
    names: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "properties" and isinstance(value, dict):
                names.update(value)
            names |= _property_names(value)
    elif isinstance(node, list):
        for item in node:
            names |= _property_names(item)
    return names


def test_no_vendor_field_names():
    models = _contract_models()
    names = {m.__name__ for m in models}
    assert {
        "DecisionSchema",
        "QualityGateRef",
        "DecisionRequest",
        "DecisionResult",
    } <= names
    vendor = re.compile(r"jev|anthropic|claude|opus", re.IGNORECASE)
    for model in models:
        offenders = {
            n for n in _property_names(model.model_json_schema()) if vendor.search(n)
        }
        assert not offenders, f"{model.__name__} has vendor-specific fields {offenders}"
