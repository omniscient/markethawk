import typing

import pytest

from app.decisions.policy import (
    DecisionContractViolation,
    PolicyOutcome,
    decide,
    validate_request,
    validate_result,
)
from app.decisions.request import QualityGateRef
from app.decisions.result import DecisionAnswer, DecisionDistribution, DistributionPoint
from tests.decisions.factories import (
    AS_OF,
    CUTOFF,
    make_gate,
    make_request,
    make_result,
    make_schema,
    make_snapshot,
)


def test_happy_path_records():
    schema = make_schema()
    request = make_request(schema)
    result = make_result(schema)
    validate_request(request, schema)
    validate_result(result, schema)
    assert decide(request, result, schema) == "RECORD"


def test_warning_gate_records():
    schema = make_schema()
    request = make_request(
        schema,
        quality_gate=make_gate(
            verdict="warning", trusted=False, issue_codes=("stale_quote",)
        ),
    )
    assert decide(request, make_result(schema), schema) == "RECORD"


def test_validate_request_rejects_schema_ref_mismatch():
    schema = make_schema()
    with pytest.raises(DecisionContractViolation):
        validate_request(make_request(schema, schema_ref="ee" * 32), schema)


def test_validate_request_rejects_future_data():
    schema = make_schema()
    leak = make_snapshot(observed_at=CUTOFF.replace(minute=CUTOFF.minute + 1))
    with pytest.raises(DecisionContractViolation, match="data_cutoff"):
        validate_request(
            make_request(schema, market_snapshot=leak, as_of=AS_OF), schema
        )


def test_validate_request_accepts_as_of_after_cutoff():
    schema = make_schema()
    assert AS_OF > CUTOFF
    validate_request(make_request(schema), schema)


def test_validate_request_rejects_as_of_before_observed_at():
    schema = make_schema()
    early = make_request(schema, as_of=make_snapshot().observed_at.replace(minute=0))
    with pytest.raises(DecisionContractViolation, match="as_of"):
        validate_request(early, schema)


def test_validate_request_rejects_missing_required_state_field():
    schema = make_schema()
    request = make_request(schema, market_snapshot=make_snapshot(relative_volume=None))
    with pytest.raises(DecisionContractViolation, match="relative_volume"):
        validate_request(request, schema)


def test_validate_result_rejects_schema_ref_mismatch():
    schema = make_schema()
    with pytest.raises(DecisionContractViolation):
        validate_result(make_result(schema, schema_ref="ee" * 32), schema)


def test_validate_result_rejects_wrong_answer_count():
    schema = make_schema()
    result = make_result(
        schema, answers=(DecisionAnswer(question_id="gap_continues", label="yes"),)
    )
    with pytest.raises(DecisionContractViolation, match="count"):
        validate_result(result, schema)


def test_validate_result_rejects_answers_out_of_order():
    schema = make_schema()
    answers = tuple(reversed(make_result(schema).answers))
    with pytest.raises(DecisionContractViolation):
        validate_result(make_result(schema, answers=answers), schema)


@pytest.mark.parametrize(
    "answers",
    [
        (
            DecisionAnswer(question_id="gap_continues", label="maybe"),
            DecisionAnswer(question_id="expected_move_pct", value=4.5),
        ),
        (
            DecisionAnswer(question_id="gap_continues", label="yes"),
            DecisionAnswer(question_id="expected_move_pct", value=25.0),
        ),
        (
            DecisionAnswer(question_id="gap_continues", value=1.0),
            DecisionAnswer(question_id="expected_move_pct", value=4.5),
        ),
    ],
    ids=["label_not_in_space", "numeric_above_max", "numeric_for_categorical"],
)
def test_validate_result_rejects_answer_outside_answer_space(answers):
    schema = make_schema()
    result = make_result(schema, answers=answers)
    with pytest.raises(DecisionContractViolation, match="answer_space"):
        validate_result(result, schema)
    assert decide(make_request(schema), result, schema) == "ABSTAIN"


def test_validate_result_rejects_distribution_outside_answer_space():
    schema = make_schema()
    bad = DecisionDistribution(
        question_id="gap_continues",
        points=(DistributionPoint(label="buy", probability=1.0),),
    )
    with pytest.raises(DecisionContractViolation, match="answer_space"):
        validate_result(make_result(schema, distributions=(bad,)), schema)


def test_validate_result_rejects_distribution_for_unknown_question():
    schema = make_schema()
    bad = DecisionDistribution(
        question_id="position_size",
        points=(DistributionPoint(value=1.0, probability=1.0),),
    )
    with pytest.raises(DecisionContractViolation, match="unknown"):
        validate_result(make_result(schema, distributions=(bad,)), schema)


def test_validate_result_rejects_duplicate_distributions():
    schema = make_schema()
    dist = make_result(schema).distributions[0]
    with pytest.raises(DecisionContractViolation, match="duplicate"):
        validate_result(make_result(schema, distributions=(dist, dist)), schema)


def test_rule1_schema_ref_mismatch_abstains():
    schema = make_schema()
    request = make_request(schema)
    result = make_result(schema)
    assert (
        decide(make_request(schema, schema_ref="ee" * 32), result, schema) == "ABSTAIN"
    )
    assert (
        decide(request, make_result(schema, schema_ref="ee" * 32), schema) == "ABSTAIN"
    )


def test_rule1_precedes_blocked_gate():
    schema = make_schema()
    blocked = make_gate(verdict="blocked", trusted=False, issue_codes=("missing_bars",))
    request = make_request(schema, schema_ref="ee" * 32, quality_gate=blocked)
    assert decide(request, make_result(schema), schema) == "ABSTAIN"


def test_rule2_abstention_reason_abstains():
    schema = make_schema()
    blocked = make_gate(verdict="blocked", trusted=False, issue_codes=("missing_bars",))
    abstained = make_result(
        schema, answers=(), distributions=(), abstention_reason="timeout"
    )
    assert decide(make_request(schema), abstained, schema) == "ABSTAIN"
    assert (
        decide(make_request(schema, quality_gate=blocked), abstained, schema)
        == "ABSTAIN"
    )


def test_rule3_blocked_gate_escalates():
    schema = make_schema()
    blocked = make_gate(verdict="blocked", trusted=False, issue_codes=("missing_bars",))
    request = make_request(schema, quality_gate=blocked)
    assert decide(request, make_result(schema), schema) == "ESCALATE_FOR_OFFLINE_REVIEW"


def test_rule4_skipped_gate_abstains():
    schema = make_schema()
    skipped = make_gate(verdict="skipped", trusted=False)
    no_gate = QualityGateRef.no_assessment(as_of=AS_OF)
    for gate in (skipped, no_gate):
        assert decide(
            make_request(schema, quality_gate=gate), make_result(schema), schema
        ) == ("ABSTAIN")


def test_decide_only_returns_three_outcomes():
    assert set(typing.get_args(PolicyOutcome)) == {
        "RECORD",
        "ABSTAIN",
        "ESCALATE_FOR_OFFLINE_REVIEW",
    }
    assert typing.get_type_hints(decide)["return"] == PolicyOutcome
