"""DecisionSchema — the versioned, hash-addressed question set for one strategy artifact.

``schema_hash`` is Optional on input only so it can be omitted; after validation it is
always a 64-hex string (derived, and tamper-checked when supplied).

Everything in ``app.decisions`` depends only on the standard library and Pydantic.
Never import ``app.schemas``, ``app.providers``, ``app.services``, ``app.models``,
``app.routers``, ``app.tasks`` or ``ib_insync`` here — see
``tests/decisions/test_architecture_boundary.py``.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Optional, Tuple, Union

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

MAX_QUESTIONS = 32
MAX_LABELS = 16
MAX_STATE_FIELDS = 16
MAX_INVALIDATION_CONDITIONS = 16
MAX_UNTRUSTED_TEXT = 1000
NUMERIC_LIMIT = 1_000_000_000.0

Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
AnswerLabel = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,31}$")]
# Fallback shape while #845's artifact id is unmerged (spec §6): bounded, id-like.
StrategyArtifactRef = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:/\-]{0,127}$")
]
BoundedFloat = Annotated[
    float, Field(ge=-NUMERIC_LIMIT, le=NUMERIC_LIMIT, allow_inf_nan=False)
]


def _to_utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc)


UtcDatetime = Annotated[AwareDatetime, AfterValidator(_to_utc)]

QuestionType = Literal["binary", "categorical", "bounded_numeric"]
CalibrationPolicy = Literal["none", "platt", "isotonic"]
StateFieldName = Literal[
    "ticker",
    "session",
    "last_price",
    "prev_close",
    "gap_pct",
    "volume",
    "avg_volume",
    "relative_volume",
    "vwap",
    "day_high",
    "day_low",
]


def canonical_json(payload: Any) -> str:
    """Canonical JSON used for every digest in this package (spec §3.2)."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_hex(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("ascii")).hexdigest()


class FrozenContract(BaseModel):
    """Base for every model in ``app.decisions``: immutable, closed, no coercion."""

    # protected_namespaces=(): ``model_version`` (spec §3.4) would otherwise warn on
    # pydantic < 2.10, whose default protected namespace is "model_".
    model_config = ConfigDict(
        frozen=True, extra="forbid", strict=True, protected_namespaces=()
    )


class UntrustedText(FrozenContract):
    """Inert, bounded external text. Never drives a question type, answer or policy branch."""

    untrusted_text: Annotated[str, StringConstraints(max_length=MAX_UNTRUSTED_TEXT)]

    @field_validator("untrusted_text")
    @classmethod
    def _reject_control_characters(cls, value: str) -> str:
        for ch in value:
            if unicodedata.category(ch) in {"Cc", "Cf"}:
                raise ValueError(
                    f"control/format character U+{ord(ch):04X} not allowed"
                )
        return value


class CategoricalAnswerSpace(FrozenContract):
    kind: Literal["categorical"]
    labels: Tuple[AnswerLabel, ...] = Field(min_length=2, max_length=MAX_LABELS)

    @field_validator("labels")
    @classmethod
    def _unique_labels(cls, value: Tuple[str, ...]) -> Tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("answer labels must be unique")
        return value


class BoundedNumericAnswerSpace(FrozenContract):
    kind: Literal["bounded_numeric"]
    min_value: BoundedFloat
    max_value: BoundedFloat

    @model_validator(mode="after")
    def _ordered(self) -> "BoundedNumericAnswerSpace":
        if not self.min_value < self.max_value:
            raise ValueError("min_value must be < max_value")
        return self


AnswerSpace = Annotated[
    Union[CategoricalAnswerSpace, BoundedNumericAnswerSpace],
    Field(discriminator="kind"),
]


class DecisionQuestionDef(FrozenContract):
    question_id: Identifier
    question_type: QuestionType
    answer_space: AnswerSpace

    @model_validator(mode="after")
    def _type_matches_space(self) -> "DecisionQuestionDef":
        space = self.answer_space
        if self.question_type == "bounded_numeric":
            if space.kind != "bounded_numeric":
                raise ValueError(
                    "bounded_numeric questions need a bounded_numeric answer_space"
                )
        elif space.kind != "categorical":
            raise ValueError(
                f"{self.question_type} questions need a categorical answer_space"
            )
        elif self.question_type == "binary" and len(space.labels) != 2:
            raise ValueError("binary questions need exactly two labels")
        return self


class DecisionSchema(FrozenContract):
    schema_version: Literal["decision_schema.v1"]
    # Derived: omit on construction; if supplied it must equal the recomputed digest.
    schema_hash: Optional[Sha256Hex] = None
    strategy_artifact_ref: StrategyArtifactRef
    strategy_artifact_sha256: Sha256Hex
    questions: Tuple[DecisionQuestionDef, ...] = Field(
        min_length=1, max_length=MAX_QUESTIONS
    )
    required_state_fields: Tuple[StateFieldName, ...] = Field(
        max_length=MAX_STATE_FIELDS
    )
    data_cutoff: UtcDatetime
    calibration_policy: CalibrationPolicy
    invalidation_conditions: Tuple[Identifier, ...] = Field(
        max_length=MAX_INVALIDATION_CONDITIONS
    )

    @field_validator("questions")
    @classmethod
    def _unique_question_ids(
        cls, value: Tuple[DecisionQuestionDef, ...]
    ) -> Tuple[DecisionQuestionDef, ...]:
        ids = [q.question_id for q in value]
        if len(set(ids)) != len(ids):
            raise ValueError("question_id values must be unique")
        return value

    def compute_hash(self) -> str:
        return sha256_hex(self.model_dump(mode="json", exclude={"schema_hash"}))

    @model_validator(mode="after")
    def _derive_schema_hash(self) -> "DecisionSchema":
        digest = self.compute_hash()
        if self.schema_hash is not None and self.schema_hash != digest:
            raise ValueError(
                "schema_hash does not match the canonical digest of this schema"
            )
        # Frozen model: bypass __setattr__ exactly once, during validation.
        object.__setattr__(self, "schema_hash", digest)
        return self
