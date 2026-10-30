import json
from datetime import timedelta

import pytest
from pydantic import ValidationError

from app.decisions.schema import (
    BoundedNumericAnswerSpace,
    CategoricalAnswerSpace,
    DecisionQuestionDef,
    DecisionSchema,
    UntrustedText,
)
from tests.decisions.factories import CUTOFF, make_schema, schema_kwargs, utc_plus


def test_valid_schema_derives_hash():
    schema = make_schema()
    assert len(schema.schema_hash) == 64
    assert schema.schema_hash == schema.compute_hash()


def test_rejects_unknown_question_type():
    with pytest.raises(ValidationError):
        DecisionQuestionDef(
            question_id="vibes",
            question_type="momentum_vibes",
            answer_space=CategoricalAnswerSpace(
                kind="categorical", labels=("no", "yes")
            ),
        )


def test_rejects_question_type_answer_space_mismatch():
    with pytest.raises(ValidationError):
        DecisionQuestionDef(
            question_id="move",
            question_type="bounded_numeric",
            answer_space=CategoricalAnswerSpace(
                kind="categorical", labels=("no", "yes")
            ),
        )
    with pytest.raises(ValidationError):
        DecisionQuestionDef(
            question_id="gap",
            question_type="binary",
            answer_space=CategoricalAnswerSpace(
                kind="categorical", labels=("a", "b", "c")
            ),
        )


def test_rejects_unbounded_answer_space():
    with pytest.raises(ValidationError):
        BoundedNumericAnswerSpace(
            kind="bounded_numeric", min_value=0.0, max_value=float("inf")
        )
    with pytest.raises(ValidationError):
        BoundedNumericAnswerSpace(kind="bounded_numeric", min_value=5.0, max_value=5.0)
    with pytest.raises(ValidationError):
        CategoricalAnswerSpace(
            kind="categorical", labels=tuple(f"l{i}" for i in range(17))
        )


def test_rejects_too_many_questions():
    q = schema_kwargs()["questions"][0]
    many = tuple(q.model_copy(update={"question_id": f"q{i}"}) for i in range(33))
    with pytest.raises(ValidationError):
        make_schema(questions=many)


def test_rejects_duplicate_question_ids():
    q = schema_kwargs()["questions"][0]
    with pytest.raises(ValidationError):
        make_schema(questions=(q, q))


def test_rejects_unknown_required_state_field():
    with pytest.raises(ValidationError):
        make_schema(required_state_fields=("account_balance",))


def test_rejects_missing_data_cutoff():
    kwargs = schema_kwargs()
    del kwargs["data_cutoff"]
    with pytest.raises(ValidationError):
        DecisionSchema(**kwargs)


def test_rejects_naive_data_cutoff():
    with pytest.raises(ValidationError):
        make_schema(data_cutoff=CUTOFF.replace(tzinfo=None))


def test_schema_hash_deterministic():
    forward = make_schema()
    reordered = DecisionSchema(**dict(reversed(list(schema_kwargs().items()))))
    offset = make_schema(data_cutoff=utc_plus(CUTOFF, 2))
    assert offset.data_cutoff.utcoffset() == timedelta(0)
    assert forward.schema_hash == reordered.schema_hash == offset.schema_hash
    assert forward == reordered == offset
    dumped = json.loads(forward.model_dump_json())
    reversed_json = json.dumps({k: dumped[k] for k in reversed(dumped)})
    assert DecisionSchema.model_validate_json(reversed_json) == forward


_SINGLE_FIELD_CHANGES = {
    "strategy_artifact_ref": "hypothesis/premarket-gap-v2",
    "strategy_artifact_sha256": "ef" * 32,
    "questions": schema_kwargs()["questions"][:1],
    "required_state_fields": ("last_price",),
    "data_cutoff": CUTOFF + timedelta(seconds=1),
    "calibration_policy": "platt",
    "invalidation_conditions": (),
}


def test_single_field_changes_cover_every_hashed_field():
    hashed = set(DecisionSchema.model_fields) - {"schema_hash", "schema_version"}
    assert set(_SINGLE_FIELD_CHANGES) == hashed


@pytest.mark.parametrize("field, value", sorted(_SINGLE_FIELD_CHANGES.items()))
def test_schema_hash_changes_on_any_field(field, value):
    assert make_schema(**{field: value}).schema_hash != make_schema().schema_hash


def test_schema_hash_round_trip_and_tamper():
    schema = make_schema()
    assert DecisionSchema.model_validate(schema.model_dump()) == schema
    assert DecisionSchema.model_validate_json(schema.model_dump_json()) == schema
    with pytest.raises(ValidationError):
        DecisionSchema.model_validate({**schema.model_dump(), "schema_hash": "ff" * 32})


def test_frozen_instance_rejects_mutation():
    schema = make_schema()
    with pytest.raises(ValidationError):
        schema.calibration_policy = "platt"
    with pytest.raises(ValidationError):
        schema.schema_hash = "ff" * 32
    with pytest.raises(ValidationError):
        schema.questions[0].question_type = "categorical"


def test_v1_literal_rejects_v2():
    with pytest.raises(ValidationError):
        make_schema(schema_version="decision_schema.v2")


def test_untrusted_text_is_bounded_and_rejects_control_characters():
    assert UntrustedText(untrusted_text="CEO resigns").untrusted_text == "CEO resigns"
    with pytest.raises(ValidationError):
        UntrustedText(untrusted_text="x" * 1001)
    with pytest.raises(ValidationError):
        UntrustedText(untrusted_text="ok\x1b[2Jboom")
    with pytest.raises(ValidationError):
        UntrustedText(untrusted_text="abc\u202edcba")
