"""Valid baseline contract objects. Tests derive degraded/adversarial variants from these.

Strict mode: python-mode validation needs tuples/datetimes/UUIDs, so payloads coming from
JSON fixtures go through ``model_validate_json`` instead.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from app.decisions.request import (
    DecisionMarketSnapshot,
    DecisionRequest,
    DecisionRunLineage,
    QualityGateRef,
)
from app.decisions.result import (
    DecisionAnswer,
    DecisionDistribution,
    DecisionResult,
    DecisionUsage,
    DistributionPoint,
)
from app.decisions.schema import (
    BoundedNumericAnswerSpace,
    CategoricalAnswerSpace,
    DecisionQuestionDef,
    DecisionSchema,
)

CUTOFF = datetime(2026, 10, 21, 13, 25, tzinfo=timezone.utc)
OBSERVED_AT = datetime(2026, 10, 21, 13, 20, tzinfo=timezone.utc)
AS_OF = datetime(2026, 10, 21, 13, 26, tzinfo=timezone.utc)
REQUEST_ID = UUID("6f1c2b8e-1d3a-4c5b-9e7f-0a1b2c3d4e5f")
RUN_UUID = UUID("0b7d5f1e-2c4a-4e6b-8d9f-1a2b3c4d5e6f")
ARTIFACT_SHA = "ab" * 32
GATE_SHA = "cd" * 32


def schema_kwargs() -> dict:
    return dict(
        schema_version="decision_schema.v1",
        strategy_artifact_ref="hypothesis/premarket-gap-v1",
        strategy_artifact_sha256=ARTIFACT_SHA,
        questions=(
            DecisionQuestionDef(
                question_id="gap_continues",
                question_type="binary",
                answer_space=CategoricalAnswerSpace(
                    kind="categorical", labels=("no", "yes")
                ),
            ),
            DecisionQuestionDef(
                question_id="expected_move_pct",
                question_type="bounded_numeric",
                answer_space=BoundedNumericAnswerSpace(
                    kind="bounded_numeric", min_value=-20.0, max_value=20.0
                ),
            ),
        ),
        required_state_fields=("last_price", "gap_pct", "relative_volume"),
        data_cutoff=CUTOFF,
        calibration_policy="none",
        invalidation_conditions=("trading_halted",),
    )


def make_schema(**overrides) -> DecisionSchema:
    return DecisionSchema(**{**schema_kwargs(), **overrides})


def utc_plus(dt: datetime, hours: int) -> datetime:
    return dt.astimezone(timezone(timedelta(hours=hours)))


def make_gate(**overrides) -> QualityGateRef:
    base = dict(
        verdict="trusted",
        trusted=True,
        issue_codes=(),
        generated_at=OBSERVED_AT,
        source_run_uuid=RUN_UUID,
        assessment_sha256=GATE_SHA,
    )
    return QualityGateRef(**{**base, **overrides})


def make_snapshot(**overrides) -> DecisionMarketSnapshot:
    base = dict(
        observed_at=OBSERVED_AT,
        ticker="ACME",
        session="pre_market",
        last_price=12.5,
        prev_close=11.0,
        gap_pct=13.6,
        volume=2_500_000,
        avg_volume=400_000.0,
        relative_volume=6.25,
    )
    return DecisionMarketSnapshot(**{**base, **overrides})


def make_request(schema: DecisionSchema | None = None, **overrides) -> DecisionRequest:
    schema = schema or make_schema()
    base = dict(
        request_id=REQUEST_ID,
        schema_ref=schema.schema_hash,
        as_of=AS_OF,
        market_snapshot=make_snapshot(),
        event_run_lineage=DecisionRunLineage(
            scanner_run_uuid=RUN_UUID, feature_provenance_ref="features/premarket.v3"
        ),
        quality_gate=make_gate(),
    )
    return DecisionRequest(**{**base, **overrides})


def result_kwargs(schema: DecisionSchema | None = None) -> dict:
    schema = schema or make_schema()
    return dict(
        request_ref=str(REQUEST_ID),
        schema_ref=schema.schema_hash,
        answers=(
            DecisionAnswer(question_id="gap_continues", label="yes"),
            DecisionAnswer(question_id="expected_move_pct", value=4.5),
        ),
        distributions=(
            DecisionDistribution(
                question_id="gap_continues",
                points=(
                    DistributionPoint(label="yes", probability=0.7),
                    DistributionPoint(label="no", probability=0.3),
                ),
            ),
        ),
        provider_confidence=0.7,
        provider_name="deterministic_baseline",
        model_version="0",
        latency_ms=12,
        cost_usd=Decimal("0"),
        usage=DecisionUsage(input_tokens=0, output_tokens=0, provider_calls=1),
    )


def make_result(schema: DecisionSchema | None = None, **overrides) -> DecisionResult:
    return DecisionResult(**{**result_kwargs(schema), **overrides})
