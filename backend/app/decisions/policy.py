"""Deterministic decision policy: pure functions, no I/O, three possible outcomes only."""

from __future__ import annotations

from typing import Literal, Optional

from app.decisions.request import DecisionRequest
from app.decisions.result import DecisionResult
from app.decisions.schema import (
    BoundedNumericAnswerSpace,
    CategoricalAnswerSpace,
    DecisionSchema,
)

PolicyOutcome = Literal["RECORD", "ABSTAIN", "ESCALATE_FOR_OFFLINE_REVIEW"]


class DecisionContractViolation(ValueError):
    """A request or result is inconsistent with the schema it claims to answer."""


def _in_space(
    space: CategoricalAnswerSpace | BoundedNumericAnswerSpace,
    label: Optional[str],
    value: Optional[float],
) -> bool:
    if isinstance(space, CategoricalAnswerSpace):
        return value is None and label in space.labels
    return (
        label is None
        and value is not None
        and space.min_value <= value <= space.max_value
    )


def validate_request(request: DecisionRequest, schema: DecisionSchema) -> None:
    if request.schema_ref != schema.schema_hash:
        raise DecisionContractViolation(
            "request.schema_ref does not match schema.schema_hash"
        )
    snapshot = request.market_snapshot
    if snapshot.observed_at > schema.data_cutoff:
        raise DecisionContractViolation(
            "market_snapshot.observed_at is after data_cutoff"
        )
    if request.as_of < snapshot.observed_at:
        raise DecisionContractViolation("as_of is before market_snapshot.observed_at")
    missing = [f for f in schema.required_state_fields if getattr(snapshot, f) is None]
    if missing:
        raise DecisionContractViolation(
            f"snapshot is missing required state fields: {missing}"
        )


def validate_result(result: DecisionResult, schema: DecisionSchema) -> None:
    if result.schema_ref != schema.schema_hash:
        raise DecisionContractViolation(
            "result.schema_ref does not match schema.schema_hash"
        )
    if len(result.answers) != len(schema.questions):
        raise DecisionContractViolation(
            "answer count differs from the schema's question count"
        )
    spaces = {q.question_id: q.answer_space for q in schema.questions}
    distribution_ids = [d.question_id for d in result.distributions]
    if len(set(distribution_ids)) != len(distribution_ids):
        raise DecisionContractViolation("duplicate distribution for a question")
    for question, answer in zip(schema.questions, result.answers):
        if answer.question_id != question.question_id:
            raise DecisionContractViolation(
                f"answer for {answer.question_id!r} is out of order or unknown"
            )
        if not _in_space(question.answer_space, answer.label, answer.value):
            raise DecisionContractViolation(
                f"answer to {question.question_id!r} is outside its answer_space"
            )
    for distribution in result.distributions:
        space = spaces.get(distribution.question_id)
        if space is None:
            raise DecisionContractViolation(
                f"distribution for unknown question {distribution.question_id!r}"
            )
        for point in distribution.points:
            if not _in_space(space, point.label, point.value):
                raise DecisionContractViolation(
                    f"distribution for {distribution.question_id!r} is outside its answer_space"
                )


def decide(
    request: DecisionRequest, result: DecisionResult, schema: DecisionSchema
) -> PolicyOutcome:
    """v1 rule table (spec §3.6), evaluated in order. The only policy logic C1 ships.

    Callers must run ``validate_request`` before dispatching a request to a provider;
    ``decide`` does not re-check data cutoffs.
    """
    if (
        request.schema_ref != schema.schema_hash
        or result.schema_ref != schema.schema_hash
    ):
        return "ABSTAIN"
    if result.abstention_reason is not None:
        return "ABSTAIN"
    if request.quality_gate.verdict == "blocked":
        return "ESCALATE_FOR_OFFLINE_REVIEW"
    if request.quality_gate.verdict == "skipped":
        return "ABSTAIN"
    try:
        validate_result(result, schema)
    except DecisionContractViolation:
        return "ABSTAIN"
    return "RECORD"
