"""DecisionResult — a provider's typed answer set. Cannot express an order, side or size."""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Annotated, Literal, Optional, Tuple

from pydantic import Field, StringConstraints, model_validator

from app.decisions.schema import (
    MAX_QUESTIONS,
    AnswerLabel,
    BoundedFloat,
    FrozenContract,
    Identifier,
    Sha256Hex,
)

MAX_DISTRIBUTION_POINTS = 64
DISTRIBUTION_SUM_TOLERANCE = 1e-6

RequestRef = Annotated[
    str,
    StringConstraints(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    ),
]
ProviderName = Annotated[
    str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_.\-]{0,63}$")
]
ModelVersion = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:\-]{0,63}$")
]
CalibrationRef = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:/\-]{0,127}$")
]
UnitInterval = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
Counter = Annotated[int, Field(ge=0, le=1_000_000_000)]

AbstentionReason = Literal[
    "timeout",
    "low_confidence",
    "schema_mismatch",
    "provider_error",
    "provider_unavailable",
    "data_cutoff_violation",
    "quality_gate",
    "insufficient_data",
]


class DecisionAnswer(FrozenContract):
    """Exactly one of ``label`` (categorical/binary) or ``value`` (bounded_numeric)."""

    question_id: Identifier
    label: Optional[AnswerLabel] = None
    value: Optional[BoundedFloat] = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "DecisionAnswer":
        if (self.label is None) == (self.value is None):
            raise ValueError("exactly one of label or value must be set")
        return self


class DistributionPoint(FrozenContract):
    label: Optional[AnswerLabel] = None
    value: Optional[BoundedFloat] = None
    probability: UnitInterval

    @model_validator(mode="after")
    def _exactly_one(self) -> "DistributionPoint":
        if (self.label is None) == (self.value is None):
            raise ValueError("exactly one of label or value must be set")
        return self


class DecisionDistribution(FrozenContract):
    question_id: Identifier
    points: Tuple[DistributionPoint, ...] = Field(
        min_length=1, max_length=MAX_DISTRIBUTION_POINTS
    )

    @model_validator(mode="after")
    def _sums_to_one(self) -> "DecisionDistribution":
        total = math.fsum(p.probability for p in self.points)
        if abs(total - 1.0) > DISTRIBUTION_SUM_TOLERANCE:
            raise ValueError("distribution probabilities must sum to 1")
        return self


class DecisionUsage(FrozenContract):
    input_tokens: Counter
    output_tokens: Counter
    provider_calls: Counter


class DecisionResult(FrozenContract):
    request_ref: RequestRef
    schema_ref: Sha256Hex
    answers: Tuple[DecisionAnswer, ...] = Field(max_length=MAX_QUESTIONS)
    distributions: Tuple[DecisionDistribution, ...] = Field(max_length=MAX_QUESTIONS)
    # Self-reported by the provider. Never copied into calibrated_probability.
    provider_confidence: Optional[UnitInterval] = None
    # Set only by MarketHawk's own calibration step (#874/#875); null until fitted.
    calibrated_probability: Optional[UnitInterval] = None
    calibration_ref: Optional[CalibrationRef] = None
    provider_name: ProviderName
    model_version: ModelVersion
    latency_ms: Counter
    cost_usd: Optional[
        Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=6)]
    ] = None
    usage: DecisionUsage
    abstention_reason: Optional[AbstentionReason] = None

    @model_validator(mode="after")
    def _abstention_xor_answers(self) -> "DecisionResult":
        if self.abstention_reason is not None and (self.answers or self.distributions):
            raise ValueError(
                "an abstaining result must carry no answers or distributions"
            )
        if self.abstention_reason is None and not self.answers:
            raise ValueError("a non-abstaining result must carry answers")
        if (self.calibrated_probability is None) != (self.calibration_ref is None):
            raise ValueError(
                "calibrated_probability and calibration_ref are set together"
            )
        return self
